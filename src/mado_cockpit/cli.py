from __future__ import annotations

import argparse
import json
from pathlib import Path

from .models import Mission, Project, Worker
from .store import CockpitStore
from .worktrees import WorktreeManager


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mado-cockpit")
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
    worker_create.add_argument("--role", required=True)
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

    sub.add_parser(
        "status",
        help="Show cockpit status",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
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
            created = manager.create(
                args.worker_id,
                base_ref=args.base_ref,
            )
            print(
                json.dumps(
                    created.to_dict(),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        if args.workspace_command == "list":
            print(
                json.dumps(
                    store.list_workspaces(),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        if args.workspace_command == "status":
            print(
                json.dumps(
                    manager.status(
                        args.workspace_id
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        if args.workspace_command == "remove":
            print(
                json.dumps(
                    manager.remove(
                        args.workspace_id,
                        delete_branch=(
                            args.delete_branch
                        ),
                        force=args.force,
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

    if args.command == "status":
        print(
            json.dumps(
                store.snapshot(),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
