from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from .models import Event, utc_now
from .store import CockpitStore


PERSONA_REGISTRY_VERSION = "MCC-M2.5"
PERSONA_PROVIDER = "agency-agents"
DEFAULT_REPOSITORY = "https://github.com/msitarzewski/agency-agents"
TrustState = Literal["experimental", "reviewed", "trusted", "rejected"]
TRUST_STATES: set[str] = {
    "experimental",
    "reviewed",
    "trusted",
    "rejected",
}
_REQUIRED_FRONTMATTER = {
    "name",
    "description",
    "color",
    "emoji",
    "vibe",
}


class PersonaRegistryError(RuntimeError):
    pass


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _stable_persona_id(
    provider: str,
    repository: str,
    source_path: str,
) -> str:
    digest = hashlib.sha256(
        f"{provider}\0{repository}\0{source_path}".encode("utf-8")
    ).hexdigest()
    return f"extp_{digest[:16]}"


def _strip_markdown(value: str) -> str:
    value = re.sub(r"\x60([^\x60]*)\x60", r"\1", value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"\1", value)
    value = re.sub(r"\*([^*]+)\*", r"\1", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    return value.strip()


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise PersonaRegistryError(
            "Agency Agents persona must start with YAML-style frontmatter."
        )

    end_index: int | None = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = index
            break
    if end_index is None:
        raise PersonaRegistryError(
            "Agency Agents persona frontmatter is not terminated."
        )

    metadata: dict[str, str] = {}
    for line in lines[1:end_index]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise PersonaRegistryError(
                f"Unsupported frontmatter line: {line}"
            )
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise PersonaRegistryError(
                "Frontmatter contains an empty key."
            )
        metadata[key] = value

    body = "\n".join(lines[end_index + 1 :]).strip()
    return metadata, body


def _sections(body: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    current: str | None = None
    for line in body.splitlines():
        if line.startswith("## "):
            current = _strip_markdown(line[3:])
            result.setdefault(current, [])
            continue
        if current is not None:
            result[current].append(line)
    return result


def _find_section(
    sections: dict[str, list[str]],
    needle: str,
) -> list[str]:
    needle = needle.lower()
    for title, lines in sections.items():
        if needle in title.lower():
            return lines
    return []


def _heading_list(
    lines: list[str],
    *,
    limit: int = 24,
) -> list[str]:
    headings: list[str] = []
    for line in lines:
        if line.startswith("### "):
            value = _strip_markdown(line[4:])
            if value:
                headings.append(value)
        if len(headings) >= limit:
            break
    return headings


def _bullet_list(
    lines: list[str],
    *,
    limit: int = 24,
) -> list[str]:
    bullets: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(("- ", "* ")):
            value = _strip_markdown(stripped[2:])
            if value:
                bullets.append(value[:320])
        if len(bullets) >= limit:
            break
    return bullets


def _first_summary(lines: list[str]) -> str | None:
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("### "):
            return _strip_markdown(stripped[4:])[:500]
        if stripped.startswith("#"):
            continue
        if stripped.startswith(("- ", "* ")):
            stripped = stripped[2:]
        value = _strip_markdown(stripped)
        if value:
            return value[:500]
    return None


def _division_for_path(relative_path: str) -> str:
    parts = Path(relative_path).parts
    if len(parts) < 2:
        return "root"
    return parts[0]


def _slug_for_path(relative_path: str) -> str:
    return Path(relative_path).stem


def _candidate_contract(body: str) -> dict[str, Any]:
    sections = _sections(body)
    mission = _find_section(sections, "core mission")
    critical = _find_section(sections, "critical rules")
    deliverables = _find_section(sections, "technical deliverables")
    success = _find_section(sections, "success metrics")
    return {
        "mission_summary": _first_summary(mission),
        "critical_rule_headings": _heading_list(critical),
        "deliverable_headings": _heading_list(deliverables),
        "success_metrics": _bullet_list(success),
        "capability_assumptions": {
            "status": "unverified",
            "declared": [],
            "note": (
                "Agency Agents markdown does not provide a structured "
                "capability contract. Capabilities must be resolved and "
                "bound separately by MADO Cockpit."
            ),
        },
        "runtime_claims": {
            "persistent_memory": (
                "unverified"
                if re.search(r"\b(memory|remember)\b", body, re.IGNORECASE)
                else "not_declared"
            ),
        },
    }


def _is_agency_agent(metadata: dict[str, str]) -> bool:
    return _REQUIRED_FRONTMATTER.issubset(metadata)


class ExternalPersonaRegistry:
    def __init__(self, store: CockpitStore) -> None:
        self.store = store
        if not store.project_file.exists():
            raise PersonaRegistryError(
                "Cockpit is not initialized. Run: mado-cockpit init"
            )
        self.base = store.base / "personas"
        self.records_dir = self.base / "records"
        self.sources_dir = self.base / "sources"
        self.reviews_dir = self.base / "reviews"
        self.intakes_dir = self.base / "intakes"
        self.registry_file = self.base / "registry.json"

    def intake_tree(
        self,
        source_root: Path | str,
        *,
        repository: str = DEFAULT_REPOSITORY,
        revision: str,
        provider: str = PERSONA_PROVIDER,
        divisions: list[str] | None = None,
        agents: list[str] | None = None,
    ) -> dict[str, Any]:
        revision = revision.strip()
        repository = repository.strip()
        provider = provider.strip()
        if not revision:
            raise PersonaRegistryError(
                "A pinned source revision is required."
            )
        if not repository:
            raise PersonaRegistryError(
                "Source repository must not be empty."
            )
        if not provider:
            raise PersonaRegistryError(
                "Persona provider must not be empty."
            )

        root = Path(source_root).resolve()
        if not root.is_dir():
            raise PersonaRegistryError(
                f"Source root does not exist: {root}"
            )

        division_filter = {
            value.strip()
            for value in (divisions or [])
            if value.strip()
        }
        agent_filter = {
            value.strip()
            for value in (agents or [])
            if value.strip()
        }

        items: list[dict[str, Any]] = []
        skipped_non_agents = 0
        excluded = 0
        for source_file in sorted(root.rglob("*.md")):
            relative_path = source_file.relative_to(root).as_posix()
            division = _division_for_path(relative_path)
            slug = _slug_for_path(relative_path)

            try:
                metadata, _ = _parse_frontmatter(
                    source_file.read_text(encoding="utf-8")
                )
            except (PersonaRegistryError, UnicodeDecodeError):
                skipped_non_agents += 1
                continue
            if not _is_agency_agent(metadata):
                skipped_non_agents += 1
                continue

            if division_filter and division not in division_filter:
                excluded += 1
                continue
            if agent_filter and (
                slug not in agent_filter
                and metadata["name"] not in agent_filter
            ):
                excluded += 1
                continue

            items.append(
                self.intake_file(
                    source_file,
                    source_root=root,
                    repository=repository,
                    revision=revision,
                    provider=provider,
                )
            )

        if agent_filter:
            matched = {
                item["slug"] for item in items
            } | {
                item["display_name"] for item in items
            }
            missing = sorted(agent_filter - matched)
            if missing:
                raise PersonaRegistryError(
                    "Requested Agency Agents were not found: "
                    + ", ".join(missing)
                )

        counts: dict[str, int] = {}
        for item in items:
            counts[item["intake_status"]] = (
                counts.get(item["intake_status"], 0) + 1
            )

        intake_id = f"pint_{uuid4().hex[:12]}"
        receipt = {
            "schema": "mado.external-persona-intake.v1",
            "version": PERSONA_REGISTRY_VERSION,
            "id": intake_id,
            "provider": provider,
            "repository": repository,
            "revision": revision,
            "source_root_name": root.name,
            "filters": {
                "divisions": sorted(division_filter),
                "agents": sorted(agent_filter),
            },
            "counts": {
                **counts,
                "intaken": len(items),
                "skipped_non_agents": skipped_non_agents,
                "excluded": excluded,
            },
            "items": [
                {
                    "persona_id": item["id"],
                    "slug": item["slug"],
                    "path": item["source"]["path"],
                    "sha256": item["source"]["sha256"],
                    "trust_state": item["trust"]["state"],
                    "intake_status": item["intake_status"],
                }
                for item in items
            ],
            "created_at": utc_now(),
        }
        self._write_json(
            self.intakes_dir / f"{intake_id}.json",
            receipt,
        )
        self.store.append_event(
            Event(
                type="persona.intake.completed",
                actor="persona_registry",
                subject={
                    "intake_id": intake_id,
                    "provider": provider,
                    "repository": repository,
                    "revision": revision,
                    "counts": receipt["counts"],
                },
            )
        )
        return receipt

    def intake_file(
        self,
        source_file: Path | str,
        *,
        source_root: Path | str,
        repository: str,
        revision: str,
        provider: str = PERSONA_PROVIDER,
    ) -> dict[str, Any]:
        root = Path(source_root).resolve()
        path = Path(source_file).resolve()
        try:
            relative_path = path.relative_to(root).as_posix()
        except ValueError as exc:
            raise PersonaRegistryError(
                "Persona source must stay inside source_root."
            ) from exc

        if path.suffix.lower() != ".md":
            raise PersonaRegistryError(
                "Persona source must be a Markdown file."
            )

        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PersonaRegistryError(
                f"Persona source is not UTF-8: {relative_path}"
            ) from exc
        metadata, body = _parse_frontmatter(text)
        if not _is_agency_agent(metadata):
            raise PersonaRegistryError(
                f"Not an Agency Agents persona definition: {relative_path}"
            )

        source_sha = _sha256_bytes(raw)
        persona_id = _stable_persona_id(
            provider,
            repository,
            relative_path,
        )
        record_path = self.records_dir / f"{persona_id}.json"
        previous = (
            self._read_json(record_path)
            if record_path.exists()
            else None
        )

        snapshot_dir = self.sources_dir / persona_id
        snapshot_path = snapshot_dir / f"{source_sha}.md"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        if not snapshot_path.exists():
            snapshot_path.write_bytes(raw)
        elif snapshot_path.read_bytes() != raw:
            raise PersonaRegistryError(
                "Snapshot digest collision detected."
            )

        changed = (
            previous is not None
            and previous["source"]["sha256"] != source_sha
        )
        same_content = (
            previous is not None
            and previous["source"]["sha256"] == source_sha
        )
        if previous is None:
            intake_status = "created"
            trust = self._experimental_trust(
                "New external persona requires review.",
                source_sha,
            )
            previous_sha = None
        elif changed:
            intake_status = "updated"
            trust = self._experimental_trust(
                "Source content changed; prior review is no longer authoritative.",
                source_sha,
            )
            previous_sha = previous["source"]["sha256"]
        elif previous["source"].get("revision") != revision:
            intake_status = "revision_updated"
            trust = previous["trust"]
            previous_sha = previous.get("previous_source_sha256")
        else:
            intake_status = "unchanged"
            trust = previous["trust"]
            previous_sha = previous.get("previous_source_sha256")

        record = {
            "schema": "mado.external-persona.v1",
            "version": PERSONA_REGISTRY_VERSION,
            "id": persona_id,
            "provider": provider,
            "slug": _slug_for_path(relative_path),
            "display_name": metadata["name"],
            "division": _division_for_path(relative_path),
            "description": metadata["description"],
            "presentation": {
                "color": metadata.get("color"),
                "emoji": metadata.get("emoji"),
                "vibe": metadata.get("vibe"),
            },
            "source": {
                "repository": repository,
                "revision": revision,
                "path": relative_path,
                "sha256": source_sha,
                "size_bytes": len(raw),
            },
            "snapshot": {
                "path": self._relative(snapshot_path),
                "sha256": source_sha,
            },
            "trust": trust,
            "contract": _candidate_contract(body),
            "previous_source_sha256": previous_sha,
            "created_at": (
                previous["created_at"]
                if previous is not None
                else utc_now()
            ),
            "updated_at": utc_now(),
        }

        if (
            not same_content
            or previous is None
            or intake_status == "revision_updated"
        ):
            self._write_json(record_path, record)
        else:
            record = previous

        self._rebuild_registry()
        self.store.append_event(
            Event(
                type="persona.intake.recorded",
                actor="persona_registry",
                subject={
                    "persona_id": persona_id,
                    "provider": provider,
                    "source_path": relative_path,
                    "source_sha256": source_sha,
                    "revision": revision,
                    "intake_status": intake_status,
                    "trust_state": record["trust"]["state"],
                },
            )
        )
        result = dict(record)
        result["intake_status"] = intake_status
        return result

    def set_trust(
        self,
        persona_id: str,
        *,
        state: TrustState,
        actor: str,
        note: str | None = None,
    ) -> dict[str, Any]:
        if state not in TRUST_STATES:
            raise PersonaRegistryError(
                "Trust state must be one of: "
                + ", ".join(sorted(TRUST_STATES))
            )
        actor = actor.strip()
        if not actor.startswith("human:"):
            raise PersonaRegistryError(
                "Trust changes require an actor in the form human:<id>."
            )
        normalized_note = note.strip() if note and note.strip() else None
        if state == "trusted" and not normalized_note:
            raise PersonaRegistryError(
                "Promoting an external persona to trusted requires a review note."
            )

        record = self.inspect(persona_id)
        previous_state = record["trust"]["state"]
        record["trust"] = {
            "state": state,
            "actor": actor,
            "note": normalized_note,
            "changed_at": utc_now(),
            "source_sha256": record["source"]["sha256"],
        }
        record["updated_at"] = utc_now()
        self._write_json(
            self.records_dir / f"{persona_id}.json",
            record,
        )

        self.reviews_dir.mkdir(parents=True, exist_ok=True)
        review_path = self.reviews_dir / f"{persona_id}.jsonl"
        review_entry = {
            "schema": "mado.external-persona-review.v1",
            "version": PERSONA_REGISTRY_VERSION,
            "persona_id": persona_id,
            "from_state": previous_state,
            "to_state": state,
            "actor": actor,
            "note": normalized_note,
            "source_sha256": record["source"]["sha256"],
            "created_at": utc_now(),
        }
        with review_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(review_entry, ensure_ascii=False) + "\n"
            )

        self._rebuild_registry()
        self.store.append_event(
            Event(
                type="persona.trust.changed",
                actor=actor,
                subject={
                    "persona_id": persona_id,
                    "from_state": previous_state,
                    "to_state": state,
                    "source_sha256": record["source"]["sha256"],
                },
            )
        )
        return record

    def inspect(self, persona_id: str) -> dict[str, Any]:
        path = self.records_dir / f"{persona_id}.json"
        if not path.exists():
            raise PersonaRegistryError(
                f"External persona not found: {persona_id}"
            )
        return self._read_json(path)

    def list_personas(
        self,
        *,
        trust_state: str | None = None,
        division: str | None = None,
    ) -> list[dict[str, Any]]:
        if trust_state is not None and trust_state not in TRUST_STATES:
            raise PersonaRegistryError(
                f"Unknown trust state: {trust_state}"
            )
        records = []
        if self.records_dir.exists():
            for path in sorted(self.records_dir.glob("*.json")):
                record = self._read_json(path)
                if trust_state and record["trust"]["state"] != trust_state:
                    continue
                if division and record["division"] != division:
                    continue
                records.append(record)
        return records

    def reconcile(
        self,
        source_root: Path | str,
        *,
        repository: str = DEFAULT_REPOSITORY,
        provider: str = PERSONA_PROVIDER,
    ) -> dict[str, Any]:
        root = Path(source_root).resolve()
        if not root.is_dir():
            raise PersonaRegistryError(
                f"Source root does not exist: {root}"
            )

        relevant = {
            record["source"]["path"]: record
            for record in self.list_personas()
            if record["provider"] == provider
            and record["source"]["repository"] == repository
        }

        statuses: list[dict[str, Any]] = []
        seen_paths: set[str] = set()
        for relative_path, record in sorted(relevant.items()):
            source_file = root / relative_path
            seen_paths.add(relative_path)
            if not source_file.is_file():
                status = "removed"
                candidate_sha = None
            else:
                candidate_sha = _sha256_bytes(source_file.read_bytes())
                status = (
                    "current"
                    if candidate_sha == record["source"]["sha256"]
                    else "changed"
                )
            statuses.append(
                {
                    "persona_id": record["id"],
                    "slug": record["slug"],
                    "path": relative_path,
                    "status": status,
                    "registered_sha256": record["source"]["sha256"],
                    "candidate_sha256": candidate_sha,
                    "trust_state": record["trust"]["state"],
                }
            )

        for source_file in sorted(root.rglob("*.md")):
            relative_path = source_file.relative_to(root).as_posix()
            if relative_path in seen_paths:
                continue
            try:
                metadata, _ = _parse_frontmatter(
                    source_file.read_text(encoding="utf-8")
                )
            except (PersonaRegistryError, UnicodeDecodeError):
                continue
            if not _is_agency_agent(metadata):
                continue
            statuses.append(
                {
                    "persona_id": None,
                    "slug": _slug_for_path(relative_path),
                    "path": relative_path,
                    "status": "unregistered",
                    "registered_sha256": None,
                    "candidate_sha256": _sha256_bytes(
                        source_file.read_bytes()
                    ),
                    "trust_state": None,
                }
            )

        counts: dict[str, int] = {}
        for item in statuses:
            counts[item["status"]] = counts.get(item["status"], 0) + 1
        return {
            "schema": "mado.external-persona-reconcile.v1",
            "version": PERSONA_REGISTRY_VERSION,
            "provider": provider,
            "repository": repository,
            "source_root_name": root.name,
            "counts": counts,
            "items": sorted(
                statuses,
                key=lambda item: (item["status"], item["path"]),
            ),
            "checked_at": utc_now(),
        }

    def _experimental_trust(
        self,
        note: str,
        source_sha256: str,
    ) -> dict[str, Any]:
        return {
            "state": "experimental",
            "actor": "system:intake",
            "note": note,
            "changed_at": utc_now(),
            "source_sha256": source_sha256,
        }

    def _rebuild_registry(self) -> None:
        personas = []
        for record in self.list_personas():
            personas.append(
                {
                    "id": record["id"],
                    "provider": record["provider"],
                    "slug": record["slug"],
                    "display_name": record["display_name"],
                    "division": record["division"],
                    "description": record["description"],
                    "trust": record["trust"],
                    "source": record["source"],
                    "snapshot": record["snapshot"],
                }
            )
        self._write_json(
            self.registry_file,
            {
                "schema": "mado.external-persona-registry.v1",
                "version": PERSONA_REGISTRY_VERSION,
                "personas": personas,
                "updated_at": utc_now(),
            },
        )

    def _relative(self, path: Path) -> str:
        return path.resolve().relative_to(
            self.store.root.resolve()
        ).as_posix()

    @staticmethod
    def _write_json(
        path: Path,
        payload: dict[str, Any],
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))


def _print_json(payload: Any) -> None:
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m mado_cockpit.persona_registry"
    )
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)

    intake = sub.add_parser("intake")
    intake.add_argument("--source-root", required=True)
    intake.add_argument(
        "--repository",
        default=DEFAULT_REPOSITORY,
    )
    intake.add_argument("--revision", required=True)
    intake.add_argument(
        "--provider",
        default=PERSONA_PROVIDER,
    )
    intake.add_argument(
        "--division",
        action="append",
        default=[],
    )
    intake.add_argument(
        "--agent",
        action="append",
        default=[],
    )

    list_cmd = sub.add_parser("list")
    list_cmd.add_argument("--trust")
    list_cmd.add_argument("--division")

    inspect = sub.add_parser("inspect")
    inspect.add_argument("persona_id")

    trust = sub.add_parser("trust")
    trust.add_argument("persona_id")
    trust.add_argument(
        "--state",
        required=True,
        choices=sorted(TRUST_STATES),
    )
    trust.add_argument("--actor", required=True)
    trust.add_argument("--note")

    reconcile = sub.add_parser("reconcile")
    reconcile.add_argument("--source-root", required=True)
    reconcile.add_argument(
        "--repository",
        default=DEFAULT_REPOSITORY,
    )
    reconcile.add_argument(
        "--provider",
        default=PERSONA_PROVIDER,
    )

    args = parser.parse_args(argv)
    try:
        registry = ExternalPersonaRegistry(
            CockpitStore(Path(args.root).resolve())
        )
        if args.command == "intake":
            result = registry.intake_tree(
                args.source_root,
                repository=args.repository,
                revision=args.revision,
                provider=args.provider,
                divisions=args.division,
                agents=args.agent,
            )
        elif args.command == "list":
            result = {
                "schema": "mado.external-persona-list.v1",
                "version": PERSONA_REGISTRY_VERSION,
                "personas": registry.list_personas(
                    trust_state=args.trust,
                    division=args.division,
                ),
            }
        elif args.command == "inspect":
            result = registry.inspect(args.persona_id)
        elif args.command == "trust":
            result = registry.set_trust(
                args.persona_id,
                state=args.state,
                actor=args.actor,
                note=args.note,
            )
        else:
            result = registry.reconcile(
                args.source_root,
                repository=args.repository,
                provider=args.provider,
            )
    except PersonaRegistryError as exc:
        _print_json(
            {
                "schema": "mado.external-persona-result.v1",
                "version": PERSONA_REGISTRY_VERSION,
                "ok": False,
                "error": str(exc),
            }
        )
        return 2

    _print_json(
        {
            "schema": "mado.external-persona-result.v1",
            "version": PERSONA_REGISTRY_VERSION,
            "ok": True,
            "result": result,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
