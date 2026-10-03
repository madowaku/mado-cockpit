from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


HARNESS_VERSION = "MCC-M1.5"
SCHEMA = "mado.opendots.dogfood-report.v1"


class OpenDotsDogfoodError(RuntimeError):
    """Raised when OpenDots drift or a dogfood verification step fails."""


@dataclass(frozen=True)
class CommandResult:
    argv: list[str]
    returncode: int
    stdout: str
    stderr: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "argv": self.argv,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


class OpenDotsDogfoodHarness:
    def __init__(
        self,
        cockpit_root: Path,
        opendots_root: Path,
        *,
        allow_drift: bool = False,
    ) -> None:
        self.cockpit_root = cockpit_root.resolve()
        self.opendots_root = opendots_root.resolve()
        self.allow_drift = allow_drift
        self.lock = self._read_json(
            self.cockpit_root
            / "fixtures"
            / "opendots"
            / "mcc-m1.5-upstream-lock.json"
        )
        self.overlay = list(self.lock["overlay"])

    def preflight(self) -> dict[str, Any]:
        package_path = self.opendots_root / "package.json"
        if not package_path.is_file():
            raise OpenDotsDogfoodError(
                f"OpenDots package.json not found: {package_path}"
            )

        package = self._read_json(package_path)
        if package.get("name") != "opendots":
            raise OpenDotsDogfoodError(
                "Target checkout does not look like OpenDots: "
                f"package name is {package.get('name')!r}"
            )

        required = [
            "src/server/dot-agent.ts",
            "src/client/Chat.tsx",
            "src/client/main.tsx",
        ]
        missing = [
            value
            for value in required
            if not (self.opendots_root / value).is_file()
        ]
        if missing:
            raise OpenDotsDogfoodError(
                "OpenDots checkout is missing required files: "
                + ", ".join(missing)
            )

        drift: list[dict[str, str]] = []
        locked_files = dict(
            self.lock["upstream"]["locked_files"]
        )
        for relative, expected in locked_files.items():
            path = self.opendots_root / relative
            if not path.is_file():
                drift.append(
                    {
                        "path": relative,
                        "expected": expected,
                        "actual": "missing",
                    }
                )
                continue

            if self._already_patched(relative, path):
                continue

            actual = self._git_blob_sha(path)
            if actual != expected:
                drift.append(
                    {
                        "path": relative,
                        "expected": expected,
                        "actual": actual,
                    }
                )

        if drift and not self.allow_drift:
            lines = [
                f"{item['path']}: expected {item['expected']}, "
                f"got {item['actual']}"
                for item in drift
            ]
            raise OpenDotsDogfoodError(
                "OpenDots upstream drift detected. Rebase the M1.5 "
                "fixtures before applying, or pass --allow-drift "
                "for an intentional local experiment:\n"
                + "\n".join(lines)
            )

        return {
            "package_version": package.get("version"),
            "node_engine": (
                package.get("engines", {}).get("node")
                if isinstance(
                    package.get("engines"),
                    dict,
                )
                else None
            ),
            "drift": drift,
            "already_patched": all(
                self._already_patched(
                    relative,
                    self.opendots_root / relative,
                )
                for relative in required
            ),
        }

    def apply(self) -> dict[str, Any]:
        preflight = self.preflight()
        changed: list[str] = []

        for item in self.overlay:
            source = (
                self.cockpit_root / str(item["source"])
            )
            target = (
                self.opendots_root / str(item["target"])
            )
            if not source.is_file():
                raise OpenDotsDogfoodError(
                    f"Overlay source is missing: {source}"
                )
            target.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            payload = source.read_bytes()
            if (
                not target.exists()
                or target.read_bytes() != payload
            ):
                target.write_bytes(payload)
                changed.append(str(item["target"]))

        if self._patch_dot_agent():
            changed.append("src/server/dot-agent.ts")
        if self._patch_chat():
            changed.append("src/client/Chat.tsx")
        if self._patch_main():
            changed.append("src/client/main.tsx")

        return {
            "preflight": preflight,
            "changed": changed,
            "overlay_count": len(self.overlay),
        }

    def verify(
        self,
        *,
        install: bool = False,
        commands: Iterable[
            Iterable[str]
        ] | None = None,
    ) -> dict[str, Any]:
        results: list[CommandResult] = []
        if install:
            results.append(
                self._run(
                    ["npm", "install"],
                    check=True,
                )
            )

        selected = (
            [list(command) for command in commands]
            if commands is not None
            else [
                list(command)
                for command in self.lock[
                    "verify_commands"
                ]
            ]
        )

        for argv in selected:
            results.append(
                self._run(
                    argv,
                    check=True,
                )
            )

        return {
            "commands": [
                result.to_dict()
                for result in results
            ],
        }

    def smoke_python_bridge(
        self,
        *,
        operator_id: str,
        python: str | None = None,
    ) -> dict[str, Any]:
        request = {
            "schema": (
                "mado.opendots.tool-call.v1"
            ),
            "tool_call_id": (
                "mcc-m1.5-dogfood-status"
            ),
            "tool_name": "mado_check_mission",
            "context": {
                "dot_id": "mcc-m1.5-dogfood",
                "space_id": "dogfood",
                "thread_id": "dogfood",
            },
            "arguments": {
                "operator_id": operator_id,
            },
        }
        executable = (
            python
            or sys.executable
        )
        env = dict(
            __import__("os").environ
        )
        source_root = str(
            self.cockpit_root / "src"
        )
        existing = env.get(
            "PYTHONPATH",
            "",
        )
        env["PYTHONPATH"] = (
            source_root
            if not existing
            else source_root
            + __import__("os").pathsep
            + existing
        )
        result = subprocess.run(
            [
                executable,
                "-m",
                "mado_cockpit.opendots_tools",
                "--root",
                str(self.cockpit_root),
            ],
            input=json.dumps(request),
            capture_output=True,
            text=True,
            env=env,
        )
        stdout = result.stdout.strip()
        if not stdout:
            raise OpenDotsDogfoodError(
                "Python bridge smoke returned no JSON: "
                + result.stderr.strip()
            )
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise OpenDotsDogfoodError(
                "Python bridge smoke returned invalid JSON"
            ) from exc
        if result.returncode not in {0, 1}:
            raise OpenDotsDogfoodError(
                "Python bridge smoke was rejected: "
                + (
                    result.stderr.strip()
                    or stdout
                )
            )
        return {
            "returncode": result.returncode,
            "payload": payload,
        }

    def report(
        self,
        *,
        apply_result: dict[str, Any] | None,
        verify_result: dict[str, Any] | None,
        bridge_result: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "harness_version": (
                HARNESS_VERSION
            ),
            "recorded_at": (
                datetime.now(timezone.utc)
                .isoformat()
            ),
            "cockpit_root": str(
                self.cockpit_root
            ),
            "opendots_root": str(
                self.opendots_root
            ),
            "allow_drift": self.allow_drift,
            "apply": apply_result,
            "verify": verify_result,
            "bridge_smoke": bridge_result,
        }

    def write_report(
        self,
        report: dict[str, Any],
    ) -> Path:
        stamp = (
            datetime.now(timezone.utc)
            .strftime("%Y%m%dT%H%M%SZ")
        )
        root = (
            self.cockpit_root
            / ".mado"
            / "cockpit"
            / "integrations"
            / "opendots"
            / "dogfood"
            / stamp
        )
        root.mkdir(
            parents=True,
            exist_ok=False,
        )
        path = root / "report.json"
        path.write_text(
            json.dumps(
                report,
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return path

    def _patch_dot_agent(self) -> bool:
        path = (
            self.opendots_root
            / "src/server/dot-agent.ts"
        )
        text = path.read_text(
            encoding="utf-8"
        )
        original = text

        import_marker = (
            "MADO_COCKPIT_M1_5_IMPORTS"
        )
        if import_marker not in text:
            anchor = (
                "import { pageReviewTool } "
                "from '../shared/page-review.js';"
            )
            addition = (
                "\n"
                "import { madoHumanGateReviewTool } "
                "from '../shared/mado-human-gate.js';\n"
                "// MADO_COCKPIT_M1_5_IMPORTS\n"
                "import { callMadoCockpit } "
                "from './mado-cockpit-caller.js';\n"
                "import { madoCockpitTools } "
                "from './mado-cockpit-tools.js';"
            )
            text = self._insert_after(
                text,
                anchor,
                addition,
                "dot-agent imports",
            )

        tools_marker = (
            "MADO_COCKPIT_M1_5_TOOLS"
        )
        if tools_marker not in text:
            anchor = (
                "          ...pageTools(pages),\n"
            )
            addition = (
                "          // MADO_COCKPIT_M1_5_TOOLS\n"
                "          ...madoCockpitTools(\n"
                "            {\n"
                "              dotId: dot.id,\n"
                "              spaceId: dot.spaceId,\n"
                "              threadId: input.threadId,\n"
                "            },\n"
                "            callMadoCockpit,\n"
                "          ),\n"
            )
            text = self._insert_after(
                text,
                anchor.rstrip("\n"),
                "\n" + addition.rstrip("\n"),
                "dot-agent server tools",
            )

        prompt_rule = (
            "When mado_check_mission reports an open human_gate"
        )
        if prompt_rule not in text:
            anchor = (
                "When the user requests review before saving, "
                "use review_space_page if available and wait for its result."
            )
            addition = (
                " When mado_check_mission reports an open human_gate, "
                "never infer or manufacture the decision. "
                "Call mado_review_human_gate with the exact gate metadata "
                "and wait for its result. Then pass the returned operator_id, "
                "gate_id, choice or choose_for_me, and note unchanged to "
                "mado_answer_human_gate. Do not call "
                "mado_answer_human_gate before the review tool completes."
            )
            text = self._insert_after(
                text,
                anchor,
                addition,
                "dot-agent Human Gate prompt",
            )

        frontend_marker = (
            "MADO_COCKPIT_M1_5_FRONTEND_TOOLS"
        )
        if frontend_marker not in text:
            old = """            tools:
              !this.channel &&
              input.tools.some((tool) => tool.name === pageReviewTool.name)
                ? [pageReviewTool]
                : [],
"""
            new = """            // MADO_COCKPIT_M1_5_FRONTEND_TOOLS
            tools:
              !this.channel
                ? input.tools.filter((tool) =>
                    [pageReviewTool.name, madoHumanGateReviewTool.name].includes(
                      tool.name,
                    ),
                  )
                : [],
"""
            text = self._replace_once(
                text,
                old,
                new,
                "dot-agent frontend tools",
            )

        if text != original:
            path.write_text(
                text,
                encoding="utf-8",
            )
            return True
        return False

    def _patch_chat(self) -> bool:
        path = (
            self.opendots_root
            / "src/client/Chat.tsx"
        )
        text = path.read_text(
            encoding="utf-8"
        )
        original = text

        if (
            "MADO_COCKPIT_M1_5_RENDERER_IMPORT"
            not in text
        ):
            anchor = (
                "import { CallView } from './CallView';"
            )
            addition = (
                "\n"
                "// MADO_COCKPIT_M1_5_RENDERER_IMPORT\n"
                "import { useMadoCockpitRenderers } "
                "from './mado-cockpit-renderers';"
            )
            text = self._insert_after(
                text,
                anchor,
                addition,
                "Chat renderer import",
            )

        if (
            "MADO_COCKPIT_M1_5_RENDERER_HOOK"
            not in text
        ):
            anchor = (
                "  const voice = useVoice("
                "thread.id, onSaved, "
                "agent.messages.at(-1)?.id);"
            )
            addition = (
                "\n"
                "  // MADO_COCKPIT_M1_5_RENDERER_HOOK\n"
                "  useMadoCockpitRenderers();"
            )
            text = self._insert_after(
                text,
                anchor,
                addition,
                "Chat renderer hook",
            )

        if (
            "call.function.name.startsWith('mado_')"
            not in text
        ):
            old = """              call.function.name.startsWith('computer_') ||
              call.function.name === pageReviewTool.name,
"""
            new = """              call.function.name.startsWith('computer_') ||
              call.function.name.startsWith('mado_') ||
              call.function.name === pageReviewTool.name,
"""
            text = self._replace_once(
                text,
                old,
                new,
                "Chat visible MADO tool calls",
            )

        if text != original:
            path.write_text(
                text,
                encoding="utf-8",
            )
            return True
        return False

    def _patch_main(self) -> bool:
        path = (
            self.opendots_root
            / "src/client/main.tsx"
        )
        text = path.read_text(
            encoding="utf-8"
        )
        original = text
        marker = (
            "MADO_COCKPIT_M1_5_RENDERER_CSS"
        )
        if marker not in text:
            anchor = "import './style.css';"
            addition = (
                "\n"
                "// MADO_COCKPIT_M1_5_RENDERER_CSS\n"
                "import './mado-cockpit-renderers.css';"
            )
            text = self._insert_after(
                text,
                anchor,
                addition,
                "client renderer CSS",
            )
        if text != original:
            path.write_text(
                text,
                encoding="utf-8",
            )
            return True
        return False

    def _already_patched(
        self,
        relative: str,
        path: Path,
    ) -> bool:
        if not path.is_file():
            return False
        text = path.read_text(
            encoding="utf-8",
            errors="replace",
        )
        markers = {
            "src/server/dot-agent.ts": (
                "MADO_COCKPIT_M1_5_IMPORTS"
            ),
            "src/client/Chat.tsx": (
                "MADO_COCKPIT_M1_5_RENDERER_IMPORT"
            ),
            "src/client/main.tsx": (
                "MADO_COCKPIT_M1_5_RENDERER_CSS"
            ),
        }
        marker = markers.get(relative)
        return bool(
            marker
            and marker in text
        )

    def _git_blob_sha(
        self,
        path: Path,
    ) -> str:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(self.opendots_root),
                "hash-object",
                str(path),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()

        payload = path.read_bytes()
        header = (
            f"blob {len(payload)}\0"
            .encode("utf-8")
        )
        return hashlib.sha1(
            header + payload
        ).hexdigest()

    def _run(
        self,
        argv: list[str],
        *,
        check: bool,
    ) -> CommandResult:
        result = subprocess.run(
            argv,
            cwd=self.opendots_root,
            capture_output=True,
            text=True,
        )
        record = CommandResult(
            argv=argv,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
        if (
            check
            and result.returncode != 0
        ):
            raise OpenDotsDogfoodError(
                "OpenDots verification failed: "
                + " ".join(argv)
                + "\n"
                + (
                    result.stderr.strip()
                    or result.stdout.strip()
                )
            )
        return record

    @staticmethod
    def _insert_after(
        text: str,
        anchor: str,
        addition: str,
        label: str,
    ) -> str:
        count = text.count(anchor)
        if count != 1:
            raise OpenDotsDogfoodError(
                f"{label} anchor expected once, found {count}"
            )
        return text.replace(
            anchor,
            anchor + addition,
            1,
        )

    @staticmethod
    def _replace_once(
        text: str,
        old: str,
        new: str,
        label: str,
    ) -> str:
        count = text.count(old)
        if count != 1:
            raise OpenDotsDogfoodError(
                f"{label} anchor expected once, found {count}"
            )
        return text.replace(
            old,
            new,
            1,
        )

    @staticmethod
    def _read_json(
        path: Path,
    ) -> dict[str, Any]:
        return json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main(
    argv: list[str] | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog=(
            "python -m "
            "mado_cockpit.opendots_dogfood"
        )
    )
    parser.add_argument(
        "--opendots-root",
        required=True,
        help="Path to a local CopilotKit/OpenDots checkout",
    )
    parser.add_argument(
        "--cockpit-root",
        default=str(_repo_root()),
        help="Path to this mado-cockpit checkout",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Copy the overlay and patch the OpenDots checkout",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Run OpenDots typecheck, build, and tests",
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="Run npm install before verification",
    )
    parser.add_argument(
        "--allow-drift",
        action="store_true",
        help="Allow current OpenDots files to differ from the pinned fixture",
    )
    parser.add_argument(
        "--operator-id",
        help="Optionally smoke the Python tool bridge against an existing Operator",
    )
    args = parser.parse_args(argv)

    harness = OpenDotsDogfoodHarness(
        Path(args.cockpit_root),
        Path(args.opendots_root),
        allow_drift=args.allow_drift,
    )

    try:
        apply_result = (
            harness.apply()
            if args.apply
            else {
                "preflight": (
                    harness.preflight()
                ),
                "changed": [],
                "overlay_count": len(
                    harness.overlay
                ),
            }
        )
        verify_result = (
            harness.verify(
                install=args.install
            )
            if args.verify
            else None
        )
        bridge_result = (
            harness.smoke_python_bridge(
                operator_id=args.operator_id
            )
            if args.operator_id
            else None
        )
        report = harness.report(
            apply_result=apply_result,
            verify_result=verify_result,
            bridge_result=bridge_result,
        )
        report_path = harness.write_report(
            report
        )
    except OpenDotsDogfoodError as exc:
        print(
            json.dumps(
                {
                    "schema": SCHEMA,
                    "harness_version": (
                        HARNESS_VERSION
                    ),
                    "ok": False,
                    "error": str(exc),
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2

    print(
        json.dumps(
            {
                "ok": True,
                "report": report,
                "report_path": str(
                    report_path
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
