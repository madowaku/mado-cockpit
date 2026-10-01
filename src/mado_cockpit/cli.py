from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .evidence import EvidenceManager
from .handoffs import HandoffManager
from .models import Mission, Project, Worker
from .operator import OperatorManager
from .providers import CodexCLIProvider
from .sessions import SessionManager
from .store import CockpitStore
from .worktrees import WorktreeManager


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mado-cockpit"
    )
    sub = parser.add_subparsers(
        dest="command",
        required=True,
    )

    init_parser = sub.add_parser(
        "init",
        help="Initialize cockpit state",
    )
    init_parser.add_argument("--project-id")
    init_parser.add_argument("--name")
    init_parser.add_argument("--root", default=".")

    mission = sub.add_parser(
        "mission",
        help="Mission operations",
    )
    mission_sub = mission.add_subparsers(
        dest="mission_command",
        required=True,
    )
    mission_create = mission_sub.add_parser(
        "create",
        help="Create a mission",
    )
    mission_create.add_argument("mission_id")
    mission_create.add_argument("title")

    worker = sub.add_parser(
        "worker",
        help="Worker operations",
    )
    worker_sub = worker.add_subparsers(
        dest="worker_command",
        required=True,
    )
    worker_create = worker_sub.add_parser(
        "create",
        help="Create a worker",
    )
    worker_create.add_argument("worker_id")
    worker_create.add_argument(
        "--role",
        required=True,
    )
    worker_create.add_argument("--mission")
    worker_create.add_argument(
        "--provider",
        default="unassigned",
    )

    workspace = sub.add_parser(
        "workspace",
        help="Workspace operations",
    )
    workspace_sub = workspace.add_subparsers(
        dest="workspace_command",
        required=True,
    )

    workspace_create = workspace_sub.add_parser(
        "create",
        help="Create a worker Git worktree",
    )
    workspace_create.add_argument("worker_id")
    workspace_create.add_argument(
        "--base-ref",
        default="HEAD",
    )

    workspace_sub.add_parser(
        "list",
        help="List workspaces",
    )

    workspace_status = workspace_sub.add_parser(
        "status",
        help="Inspect a workspace",
    )
    workspace_status.add_argument("workspace_id")

    workspace_remove = workspace_sub.add_parser(
        "remove",
        help="Remove a workspace",
    )
    workspace_remove.add_argument("workspace_id")
    workspace_remove.add_argument(
        "--delete-branch",
        action="store_true",
    )
    workspace_remove.add_argument(
        "--force",
        action="store_true",
    )

    session = sub.add_parser(
        "session",
        help="Agent session operations",
    )
    session_sub = session.add_subparsers(
        dest="session_command",
        required=True,
    )

    session_start = session_sub.add_parser(
        "start",
        help="Start an agent session in a worker workspace",
    )
    session_start.add_argument("worker_id")
    session_start.add_argument("prompt")
    session_start.add_argument(
        "--provider",
        default="codex",
        choices=["codex"],
    )
    session_start.add_argument("--model")
    session_start.add_argument(
        "--codex-binary",
        default=os.environ.get(
            "MADO_CODEX_BIN",
            "codex",
        ),
    )

    session_send = session_sub.add_parser(
        "send",
        help="Send a follow-up turn to an agent session",
    )
    session_send.add_argument("session_id")
    session_send.add_argument("prompt")
    session_send.add_argument(
        "--codex-binary",
        default=os.environ.get(
            "MADO_CODEX_BIN",
            "codex",
        ),
    )

    session_status = session_sub.add_parser(
        "status",
        help="Inspect an agent session",
    )
    session_status.add_argument("session_id")

    session_stop = session_sub.add_parser(
        "stop",
        help="Close a local agent session",
    )
    session_stop.add_argument("session_id")

    session_sub.add_parser(
        "list",
        help="List agent sessions",
    )

    task = sub.add_parser(
        "task",
        help="Task contract operations",
    )
    task_sub = task.add_subparsers(
        dest="task_command",
        required=True,
    )

    task_create = task_sub.add_parser(
        "create",
        help="Assign a task contract to a worker",
    )
    task_create.add_argument("task_id")
    task_create.add_argument("worker_id")
    task_create.add_argument("objective")
    task_create.add_argument(
        "--require",
        action="append",
        default=[],
        dest="required_evidence",
    )
    task_create.add_argument(
        "--constraint",
        action="append",
        default=[],
    )
    task_create.add_argument(
        "--deliverable",
        action="append",
        default=[],
    )
    task_create.add_argument(
        "--done-when",
        action="append",
        default=[],
    )

    task_sub.add_parser(
        "list",
        help="List task contracts",
    )

    task_show = task_sub.add_parser(
        "show",
        help="Inspect a task contract",
    )
    task_show.add_argument("task_id")

    result = sub.add_parser(
        "result",
        help="Result contract operations",
    )
    result_sub = result.add_subparsers(
        dest="result_command",
        required=True,
    )

    result_submit = result_sub.add_parser(
        "submit",
        help="Submit a result and build its evidence bundle",
    )
    result_submit.add_argument("task_id")
    result_submit.add_argument(
        "--status",
        required=True,
        choices=[
            "completed",
            "blocked",
            "failed",
        ],
    )
    result_submit.add_argument(
        "--summary",
        required=True,
    )
    result_submit.add_argument("--session")
    result_submit.add_argument(
        "--evidence",
        action="append",
        default=[],
        metavar="KIND=PATH",
    )
    result_submit.add_argument(
        "--change",
        action="append",
        default=[],
    )
    result_submit.add_argument(
        "--risk",
        action="append",
        default=[],
    )

    result_list = result_sub.add_parser(
        "list",
        help="List result contracts",
    )
    result_list.add_argument("--task")

    evidence = sub.add_parser(
        "evidence",
        help="Evidence bundle operations",
    )
    evidence_sub = evidence.add_subparsers(
        dest="evidence_command",
        required=True,
    )

    evidence_list = evidence_sub.add_parser(
        "list",
        help="List evidence bundles",
    )
    evidence_list.add_argument("--task")

    evidence_inspect = evidence_sub.add_parser(
        "inspect",
        help="Inspect an evidence bundle",
    )
    evidence_inspect.add_argument("bundle_id")

    handoff = sub.add_parser(
        "handoff",
        help="Builder to QA handoff operations",
    )
    handoff_sub = handoff.add_subparsers(
        dest="handoff_command",
        required=True,
    )

    handoff_create = handoff_sub.add_parser(
        "create",
        help="Create an immutable handoff for QA",
    )
    handoff_create.add_argument("source_task_id")
    handoff_create.add_argument("qa_worker_id")

    handoff_sub.add_parser(
        "list",
        help="List handoffs",
    )

    handoff_inspect = handoff_sub.add_parser(
        "inspect",
        help="Inspect a handoff",
    )
    handoff_inspect.add_argument("handoff_id")

    handoff_verdict = handoff_sub.add_parser(
        "verdict",
        help="Resolve a handoff from a QA result",
    )
    handoff_verdict.add_argument("handoff_id")
    handoff_verdict.add_argument(
        "--qa-result",
        required=True,
    )
    handoff_verdict.add_argument(
        "--verdict",
        required=True,
        choices=[
            "pass",
            "needs_fix",
            "blocked",
        ],
    )
    handoff_verdict.add_argument(
        "--summary",
        required=True,
    )

    operator = sub.add_parser(
        "operator",
        help="Deterministic production operator",
    )
    operator_sub = operator.add_subparsers(
        dest="operator_command",
        required=True,
    )

    operator_start = operator_sub.add_parser(
        "start",
        help="Provision Builder, QA, worktrees, and Builder task",
    )
    operator_start.add_argument("mission_id")
    operator_start.add_argument("objective")
    operator_start.add_argument(
        "--require",
        action="append",
        required=True,
        dest="required_evidence",
    )
    operator_start.add_argument(
        "--provider",
        default="codex",
        choices=["codex"],
    )
    operator_start.add_argument(
        "--base-ref",
        default="HEAD",
    )

    operator_sub.add_parser(
        "list",
        help="List operator runs",
    )

    operator_status = operator_sub.add_parser(
        "status",
        help="Inspect one operator run",
    )
    operator_status.add_argument("operator_id")

    operator_advance = operator_sub.add_parser(
        "advance",
        help="Advance deterministic orchestration state",
    )
    operator_advance.add_argument("operator_id")

    operator_launch = operator_sub.add_parser(
        "launch",
        help="Start or resume a Builder/QA Codex turn",
    )
    operator_launch.add_argument("operator_id")
    operator_launch.add_argument(
        "role",
        choices=["builder", "qa"],
    )
    operator_launch.add_argument("--model")
    operator_launch.add_argument(
        "--codex-binary",
        default=os.environ.get(
            "MADO_CODEX_BIN",
            "codex",
        ),
    )

    operator_stop = operator_sub.add_parser(
        "stop",
        help="Stop a recorded Builder/QA session between turns",
    )
    operator_stop.add_argument("operator_id")
    operator_stop.add_argument(
        "role",
        choices=["builder", "qa"],
    )
    operator_stop.add_argument(
        "--codex-binary",
        default=os.environ.get(
            "MADO_CODEX_BIN",
            "codex",
        ),
    )

    operator_result = operator_sub.add_parser(
        "result",
        help="Submit Builder/QA result through the operator",
    )
    operator_result.add_argument("operator_id")
    operator_result.add_argument(
        "role",
        choices=["builder", "qa"],
    )
    operator_result.add_argument(
        "--status",
        required=True,
        choices=[
            "completed",
            "blocked",
            "failed",
        ],
    )
    operator_result.add_argument(
        "--summary",
        required=True,
    )
    operator_result.add_argument(
        "--evidence",
        action="append",
        default=[],
        metavar="KIND=PATH",
    )
    operator_result.add_argument(
        "--change",
        action="append",
        default=[],
    )
    operator_result.add_argument(
        "--risk",
        action="append",
        default=[],
    )

    operator_verdict = operator_sub.add_parser(
        "verdict",
        help="Resolve the current QA handoff",
    )
    operator_verdict.add_argument("operator_id")
    operator_verdict.add_argument(
        "--verdict",
        required=True,
        choices=[
            "pass",
            "needs_fix",
            "blocked",
        ],
    )
    operator_verdict.add_argument(
        "--summary",
        required=True,
    )
    operator_verdict.add_argument(
        "--qa-result",
    )

    sub.add_parser(
        "status",
        help="Show cockpit status",
    )
    return parser


def _session_manager(
    store: CockpitStore,
    *,
    codex_binary: str = "codex",
) -> SessionManager:
    return SessionManager(
        store,
        providers={
            "codex": CodexCLIProvider(
                executable=codex_binary,
            )
        },
    )


def _parse_evidence_specs(
    specs: list[str],
) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for spec in specs:
        kind, separator, path = spec.partition("=")
        if not separator or not kind.strip() or not path.strip():
            raise RuntimeError(
                "Evidence must use KIND=PATH format: "
                f"{spec}"
            )
        result.append(
            (kind.strip(), path.strip())
        )
    return result


def _print_json(payload: object) -> None:
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )
    )


def main(
    argv: list[str] | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    root = Path(
        getattr(args, "root", ".")
    ).resolve()
    store = CockpitStore(root)

    if args.command == "init":
        project_id = args.project_id or root.name
        name = args.name or project_id
        store.init(
            Project(
                id=project_id,
                name=name,
                root=str(root),
            )
        )
        print(
            f"Initialized MADO Cockpit for {name}"
        )
        return 0

    if (
        args.command == "mission"
        and args.mission_command == "create"
    ):
        store.save_mission(
            Mission(
                id=args.mission_id,
                title=args.title,
            )
        )
        print(
            f"Created mission {args.mission_id}"
        )
        return 0

    if (
        args.command == "worker"
        and args.worker_command == "create"
    ):
        store.save_worker(
            Worker(
                id=args.worker_id,
                role=args.role,
                mission_id=args.mission,
                provider=args.provider,
            )
        )
        print(
            f"Created worker {args.worker_id}"
        )
        return 0

    if args.command == "workspace":
        manager = WorktreeManager(store)

        if args.workspace_command == "create":
            _print_json(
                manager.create(
                    args.worker_id,
                    base_ref=args.base_ref,
                ).to_dict()
            )
            return 0

        if args.workspace_command == "list":
            _print_json(store.list_workspaces())
            return 0

        if args.workspace_command == "status":
            _print_json(
                manager.status(
                    args.workspace_id
                )
            )
            return 0

        if args.workspace_command == "remove":
            _print_json(
                manager.remove(
                    args.workspace_id,
                    delete_branch=(
                        args.delete_branch
                    ),
                    force=args.force,
                )
            )
            return 0

    if args.command == "session":
        if args.session_command == "list":
            _print_json(store.list_sessions())
            return 0

        if args.session_command == "start":
            manager = _session_manager(
                store,
                codex_binary=args.codex_binary,
            )
            _print_json(
                manager.start(
                    args.worker_id,
                    args.prompt,
                    provider_name=args.provider,
                    model=args.model,
                )
            )
            return 0

        if args.session_command == "send":
            manager = _session_manager(
                store,
                codex_binary=args.codex_binary,
            )
            _print_json(
                manager.send(
                    args.session_id,
                    args.prompt,
                )
            )
            return 0

        manager = _session_manager(store)

        if args.session_command == "status":
            _print_json(
                manager.status(
                    args.session_id
                )
            )
            return 0

        if args.session_command == "stop":
            _print_json(
                manager.stop(
                    args.session_id
                )
            )
            return 0

    if args.command == "task":
        manager = EvidenceManager(store)

        if args.task_command == "create":
            _print_json(
                manager.create_task(
                    args.task_id,
                    args.worker_id,
                    args.objective,
                    required_evidence=(
                        args.required_evidence
                    ),
                    constraints=args.constraint,
                    deliverables=args.deliverable,
                    done_when=args.done_when,
                )
            )
            return 0

        if args.task_command == "list":
            _print_json(manager.list_tasks())
            return 0

        if args.task_command == "show":
            _print_json(
                manager.get_task(
                    args.task_id
                )
            )
            return 0

    if args.command == "result":
        manager = EvidenceManager(store)

        if args.result_command == "submit":
            _print_json(
                manager.submit_result(
                    args.task_id,
                    status=args.status,
                    summary=args.summary,
                    evidence_files=(
                        _parse_evidence_specs(
                            args.evidence
                        )
                    ),
                    changes=args.change,
                    risks=args.risk,
                    session_id=args.session,
                )
            )
            return 0

        if args.result_command == "list":
            _print_json(
                manager.list_results(
                    args.task
                )
            )
            return 0

    if args.command == "evidence":
        manager = EvidenceManager(store)

        if args.evidence_command == "list":
            _print_json(
                manager.list_bundles(
                    args.task
                )
            )
            return 0

        if args.evidence_command == "inspect":
            _print_json(
                manager.inspect_bundle(
                    args.bundle_id
                )
            )
            return 0

    if args.command == "handoff":
        manager = HandoffManager(store)

        if args.handoff_command == "create":
            _print_json(
                manager.create(
                    args.source_task_id,
                    args.qa_worker_id,
                )
            )
            return 0

        if args.handoff_command == "list":
            _print_json(manager.list())
            return 0

        if args.handoff_command == "inspect":
            _print_json(
                manager.inspect(
                    args.handoff_id
                )
            )
            return 0

        if args.handoff_command == "verdict":
            _print_json(
                manager.submit_verdict(
                    args.handoff_id,
                    args.qa_result,
                    verdict=args.verdict,
                    summary=args.summary,
                )
            )
            return 0

    if args.command == "operator":
        manager = OperatorManager(store)

        if args.operator_command == "start":
            _print_json(
                manager.start(
                    args.mission_id,
                    args.objective,
                    required_evidence=(
                        args.required_evidence
                    ),
                    provider=args.provider,
                    base_ref=args.base_ref,
                )
            )
            return 0

        if args.operator_command == "list":
            _print_json(
                manager.list()
            )
            return 0

        if args.operator_command == "status":
            _print_json(
                manager.inspect(
                    args.operator_id
                )
            )
            return 0

        if args.operator_command == "advance":
            _print_json(
                manager.advance(
                    args.operator_id
                )
            )
            return 0

        if args.operator_command == "launch":
            sessions = _session_manager(
                store,
                codex_binary=(
                    args.codex_binary
                ),
            )
            _print_json(
                manager.launch(
                    args.operator_id,
                    args.role,
                    sessions=sessions,
                    model=args.model,
                )
            )
            return 0

        if args.operator_command == "stop":
            sessions = _session_manager(
                store,
                codex_binary=(
                    args.codex_binary
                ),
            )
            _print_json(
                manager.stop(
                    args.operator_id,
                    args.role,
                    sessions=sessions,
                )
            )
            return 0

        if args.operator_command == "result":
            _print_json(
                manager.submit_result(
                    args.operator_id,
                    args.role,
                    status=args.status,
                    summary=args.summary,
                    evidence_files=(
                        _parse_evidence_specs(
                            args.evidence
                        )
                    ),
                    changes=args.change,
                    risks=args.risk,
                )
            )
            return 0

        if args.operator_command == "verdict":
            _print_json(
                manager.verdict(
                    args.operator_id,
                    verdict=args.verdict,
                    summary=args.summary,
                    qa_result_id=(
                        args.qa_result
                    ),
                )
            )
            return 0

    if args.command == "status":
        snapshot = store.snapshot()
        snapshot["evidence"] = (
            EvidenceManager(store).summary()
        )
        snapshot["handoffs"] = (
            HandoffManager(store).summary()
        )
        snapshot["operators"] = (
            OperatorManager(store).summary()
        )
        _print_json(snapshot)
        return 0

    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
