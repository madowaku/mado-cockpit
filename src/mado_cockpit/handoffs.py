from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

from .evidence import EvidenceManager
from .models import Event, HandoffContract, QAVerdict, utc_now
from .store import CockpitStore


_ALLOWED_VERDICTS = {
    "pass",
    "needs_fix",
    "blocked",
}


class HandoffManager:
    def __init__(self, store: CockpitStore) -> None:
        self.store = store
        self.evidence = EvidenceManager(store)
        self.handoffs_dir = store.base / "handoffs"

    def create(
        self,
        source_task_id: str,
        qa_worker_id: str,
    ) -> dict[str, Any]:
        task = self.evidence.get_task(source_task_id)
        if task["status"] != "ready_for_qa":
            raise RuntimeError(
                "Source task is not ready_for_qa: "
                f"{source_task_id} ({task['status']})"
            )

        result = self.evidence.latest_ready_result(
            source_task_id
        )
        bundle_id = str(
            result["evidence_bundle_id"]
        )
        bundle_root = self.evidence.bundle_root(
            bundle_id
        )

        source_worker = self.store.get_worker(
            str(task["worker_id"])
        )
        qa_worker = self.store.get_worker(
            qa_worker_id
        )
        self._validate_workers(
            source_worker,
            qa_worker,
        )

        source_workspace = self.store.get_workspace(
            str(task["workspace_id"])
        )
        qa_workspace = (
            self.store.get_workspace_for_worker(
                qa_worker_id
            )
        )
        self._require_workspace_ready(
            source_workspace
        )
        self._require_workspace_ready(
            qa_workspace
        )

        if (
            source_workspace["id"]
            == qa_workspace["id"]
        ):
            raise RuntimeError(
                "QA must use a different workspace "
                "from the source worker"
            )

        handoff_id = (
            f"hnd_{uuid4().hex[:12]}"
        )
        qa_task_id = (
            f"qa_{handoff_id}"
        )
        handoff_root = (
            self.handoffs_dir
            / handoff_id
        )
        handoff_root.mkdir(
            parents=True,
            exist_ok=False,
        )

        qa_workspace_root = Path(
            str(qa_workspace["path"])
        ).resolve()
        snapshot_root = (
            qa_workspace_root
            / ".mado"
            / "handoffs"
            / handoff_id
            / "source_bundle"
        )

        try:
            shutil.copytree(
                bundle_root,
                snapshot_root,
            )
            source_digest = self._tree_digest(
                bundle_root
            )
            snapshot_digest = self._tree_digest(
                snapshot_root
            )
            if source_digest != snapshot_digest:
                raise RuntimeError(
                    "Handoff snapshot digest mismatch "
                    "during materialization"
                )

            relative_snapshot = str(
                snapshot_root.relative_to(
                    qa_workspace_root
                )
            )

            contract = HandoffContract(
                id=handoff_id,
                source_task_id=source_task_id,
                source_result_id=str(
                    result["id"]
                ),
                source_bundle_id=bundle_id,
                source_worker_id=str(
                    task["worker_id"]
                ),
                source_workspace_id=str(
                    task["workspace_id"]
                ),
                qa_worker_id=qa_worker_id,
                qa_workspace_id=str(
                    qa_workspace["id"]
                ),
                qa_task_id=qa_task_id,
                snapshot_path=relative_snapshot,
                snapshot_sha256=snapshot_digest,
            )

            self._write_json(
                handoff_root
                / "handoff.json",
                contract.to_dict(),
            )
            self._write_json(
                handoff_root
                / "status.json",
                {
                    "handoff_id": handoff_id,
                    "status": "awaiting_qa",
                    "updated_at": utc_now(),
                    "verdict_id": None,
                },
            )

            self.evidence.create_task(
                qa_task_id,
                qa_worker_id,
                (
                    "Independently validate handoff "
                    f"{handoff_id} for source task "
                    f"{source_task_id}. Review the "
                    "materialized source bundle at "
                    f"{relative_snapshot} and return "
                    "a QA report."
                ),
                required_evidence=[
                    "qa_report",
                ],
                constraints=[
                    (
                        "Do not modify the materialized "
                        "handoff source bundle."
                    ),
                    (
                        "Review independently from the "
                        "source worker."
                    ),
                ],
                deliverables=[
                    "qa_report",
                ],
                done_when=[
                    (
                        "QA report identifies checks, "
                        "findings, and proposed verdict."
                    ),
                ],
            )
        except Exception:
            shutil.rmtree(
                handoff_root,
                ignore_errors=True,
            )
            shutil.rmtree(
                snapshot_root.parent,
                ignore_errors=True,
            )
            raise

        self.evidence.set_task_status(
            source_task_id,
            "qa_in_review",
        )

        mission_id = self._mission_id(
            source_worker
        )
        self.store.append_event(
            Event(
                type="handoff.created",
                mission_id=mission_id,
                actor="cockpit",
                subject={
                    "handoff_id": handoff_id,
                    "source_task_id": (
                        source_task_id
                    ),
                    "source_result_id": (
                        result["id"]
                    ),
                    "source_bundle_id": bundle_id,
                    "source_worker_id": (
                        task["worker_id"]
                    ),
                    "qa_worker_id": qa_worker_id,
                    "qa_task_id": qa_task_id,
                },
            )
        )
        self.store.append_event(
            Event(
                type="handoff.materialized",
                mission_id=mission_id,
                actor="cockpit",
                subject={
                    "handoff_id": handoff_id,
                    "qa_workspace_id": (
                        qa_workspace["id"]
                    ),
                    "snapshot_path": (
                        relative_snapshot
                    ),
                    "snapshot_sha256": (
                        snapshot_digest
                    ),
                },
            )
        )

        return self.inspect(handoff_id)

    def submit_verdict(
        self,
        handoff_id: str,
        qa_result_id: str,
        *,
        verdict: str,
        summary: str,
    ) -> dict[str, Any]:
        if verdict not in _ALLOWED_VERDICTS:
            allowed = ", ".join(
                sorted(_ALLOWED_VERDICTS)
            )
            raise RuntimeError(
                f"Unsupported QA verdict: {verdict}. "
                f"Expected one of: {allowed}"
            )
        if not summary.strip():
            raise RuntimeError(
                "QA verdict summary must not be empty"
            )

        handoff = self._handoff(handoff_id)
        status = self._status(handoff_id)
        if status["status"] != "awaiting_qa":
            raise RuntimeError(
                "Handoff is already resolved: "
                f"{handoff_id} ({status['status']})"
            )

        qa_result = self.evidence.get_result(
            qa_result_id
        )
        if (
            qa_result["task_id"]
            != handoff["qa_task_id"]
        ):
            raise RuntimeError(
                "QA result does not belong to "
                "the handoff QA task"
            )
        if (
            qa_result["worker_id"]
            != handoff["qa_worker_id"]
        ):
            raise RuntimeError(
                "QA result worker does not match "
                "the handoff QA worker"
            )
        if (
            qa_result["evidence_status"]
            != "validated"
        ):
            raise RuntimeError(
                "QA result evidence is not validated"
            )

        qa_status = str(
            qa_result["status"]
        )
        if verdict in {
            "pass",
            "needs_fix",
        } and qa_status != "completed":
            raise RuntimeError(
                "pass/needs_fix requires a completed "
                "QA result"
            )
        if (
            verdict == "blocked"
            and qa_status not in {
                "completed",
                "blocked",
            }
        ):
            raise RuntimeError(
                "blocked verdict requires a completed "
                "or blocked QA result"
            )

        qa_workspace = self.store.get_workspace(
            str(handoff["qa_workspace_id"])
        )
        snapshot_root = (
            Path(str(qa_workspace["path"]))
            / str(handoff["snapshot_path"])
        ).resolve()
        if not snapshot_root.is_dir():
            raise RuntimeError(
                "Handoff source snapshot is missing"
            )

        current_digest = self._tree_digest(
            snapshot_root
        )
        if (
            current_digest
            != handoff["snapshot_sha256"]
        ):
            raise RuntimeError(
                "Handoff source snapshot was modified "
                "during QA"
            )

        verdict_id = (
            f"qav_{uuid4().hex[:12]}"
        )
        record = QAVerdict(
            id=verdict_id,
            handoff_id=handoff_id,
            qa_task_id=str(
                handoff["qa_task_id"]
            ),
            qa_result_id=qa_result_id,
            qa_worker_id=str(
                handoff["qa_worker_id"]
            ),
            verdict=verdict,
            summary=summary.strip(),
            source_snapshot_sha256=(
                current_digest
            ),
        )

        root = (
            self.handoffs_dir
            / handoff_id
        )
        self._write_json(
            root / "verdict.json",
            record.to_dict(),
        )
        self._write_json(
            root / "status.json",
            {
                "handoff_id": handoff_id,
                "status": verdict,
                "updated_at": utc_now(),
                "verdict_id": verdict_id,
            },
        )

        source_status = {
            "pass": "qa_passed",
            "needs_fix": "needs_fix",
            "blocked": "qa_blocked",
        }[verdict]
        self.evidence.set_task_status(
            str(handoff["source_task_id"]),
            source_status,
        )

        qa_worker = self.store.get_worker(
            str(handoff["qa_worker_id"])
        )
        mission_id = self._mission_id(
            qa_worker
        )
        self.store.append_event(
            Event(
                type="qa.verdict",
                mission_id=mission_id,
                actor="cockpit",
                subject={
                    "verdict_id": verdict_id,
                    "handoff_id": handoff_id,
                    "qa_result_id": qa_result_id,
                    "qa_worker_id": (
                        handoff["qa_worker_id"]
                    ),
                    "verdict": verdict,
                },
            )
        )
        self.store.append_event(
            Event(
                type="handoff.resolved",
                mission_id=mission_id,
                actor="cockpit",
                subject={
                    "handoff_id": handoff_id,
                    "source_task_id": (
                        handoff["source_task_id"]
                    ),
                    "verdict": verdict,
                },
            )
        )

        return self.inspect(handoff_id)

    def inspect(
        self,
        handoff_id: str,
    ) -> dict[str, Any]:
        handoff = self._handoff(
            handoff_id
        )
        status = self._status(
            handoff_id
        )
        verdict_path = (
            self.handoffs_dir
            / handoff_id
            / "verdict.json"
        )
        verdict = (
            self._read_json(
                verdict_path
            )
            if verdict_path.exists()
            else None
        )
        return {
            "handoff": handoff,
            "status": status,
            "verdict": verdict,
        }

    def list(
        self,
    ) -> list[dict[str, Any]]:
        if not self.handoffs_dir.exists():
            return []
        return [
            self.inspect(
                path.parent.name
            )
            for path in sorted(
                self.handoffs_dir.glob(
                    "*/handoff.json"
                )
            )
        ]

    def summary(
        self,
    ) -> dict[str, int]:
        handoffs = self.list()
        return {
            "handoff_count": len(
                handoffs
            ),
            "awaiting_qa_count": sum(
                1
                for item in handoffs
                if item["status"]["status"]
                == "awaiting_qa"
            ),
            "qa_passed_count": sum(
                1
                for item in handoffs
                if item["status"]["status"]
                == "pass"
            ),
            "needs_fix_count": sum(
                1
                for item in handoffs
                if item["status"]["status"]
                == "needs_fix"
            ),
        }

    def _handoff(
        self,
        handoff_id: str,
    ) -> dict[str, Any]:
        path = (
            self.handoffs_dir
            / handoff_id
            / "handoff.json"
        )
        if not path.exists():
            raise RuntimeError(
                f"Handoff not found: {handoff_id}"
            )
        return self._read_json(path)

    def _status(
        self,
        handoff_id: str,
    ) -> dict[str, Any]:
        path = (
            self.handoffs_dir
            / handoff_id
            / "status.json"
        )
        if not path.exists():
            raise RuntimeError(
                "Handoff status not found: "
                f"{handoff_id}"
            )
        return self._read_json(path)

    @staticmethod
    def _validate_workers(
        source_worker: dict[str, Any],
        qa_worker: dict[str, Any],
    ) -> None:
        if (
            source_worker["id"]
            == qa_worker["id"]
        ):
            raise RuntimeError(
                "Source worker cannot QA its own work"
            )
        if (
            str(qa_worker["role"]).lower()
            != "qa"
        ):
            raise RuntimeError(
                "Handoff target worker must have "
                "role=qa"
            )
        if (
            source_worker.get(
                "mission_id"
            )
            != qa_worker.get(
                "mission_id"
            )
        ):
            raise RuntimeError(
                "Source and QA workers must belong "
                "to the same mission"
            )

    @staticmethod
    def _require_workspace_ready(
        workspace: dict[str, Any],
    ) -> None:
        if workspace["status"] != "ready":
            raise RuntimeError(
                "Workspace is not ready: "
                f"{workspace['id']} "
                f"({workspace['status']})"
            )
        path = Path(
            str(workspace["path"])
        )
        if not path.is_dir():
            raise RuntimeError(
                "Workspace path is missing: "
                f"{path}"
            )

    @staticmethod
    def _tree_digest(
        root: Path,
    ) -> str:
        digest = hashlib.sha256()
        files = sorted(
            path
            for path in root.rglob("*")
            if path.is_file()
        )
        for path in files:
            relative = path.relative_to(
                root
            ).as_posix()
            digest.update(
                relative.encode("utf-8")
            )
            digest.update(b"\0")
            with path.open("rb") as handle:
                for chunk in iter(
                    lambda: handle.read(
                        1024 * 1024
                    ),
                    b"",
                ):
                    digest.update(chunk)
            digest.update(b"\0")
        return digest.hexdigest()

    @staticmethod
    def _mission_id(
        worker: dict[str, Any],
    ) -> str | None:
        value = worker.get(
            "mission_id"
        )
        return (
            str(value)
            if value is not None
            else None
        )

    @staticmethod
    def _write_json(
        path: Path,
        payload: dict[str, Any],
    ) -> None:
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
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
    def _read_json(
        path: Path,
    ) -> dict[str, Any]:
        return json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
