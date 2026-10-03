from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from .models import utc_now
from .space_transport import SpaceTransportAdapter
from .store import CockpitStore


class SpaceDogfoodManager:
    """Evidence-backed real-client challenge for Space MCP."""

    def __init__(self, store: CockpitStore) -> None:
        self.store = store
        self.base = (
            store.base
            / "dogfood"
            / "space"
        )
        self.transport = (
            SpaceTransportAdapter(store)
        )

    def prepare(
        self,
        *,
        title: str = (
            "Real Space transport dogfood"
        ),
    ) -> dict[str, Any]:
        self._require_initialized()
        challenge_id = (
            f"dog_{uuid4().hex[:12]}"
        )
        nonce = secrets.token_urlsafe(18)
        mission_id = (
            "MCC-DOGFOOD-"
            + challenge_id.split(
                "_",
                1,
            )[1].upper()
        )
        root = self.base / challenge_id

        envelope = {
            "schema_version": (
                "mado.mission-envelope.v1"
            ),
            "mission_id": mission_id,
            "title": title,
            "objective": (
                "Prove that a real ChatGPT Space "
                "session can reach the private MADO "
                "Cockpit MCP through Secure MCP Tunnel "
                "and receive an evidence-backed outcome."
            ),
            "source": {
                "kind": "space",
                "space_id": None,
                "page_id": None,
                "revision": "1",
            },
            "priority": "normal",
            "constraints": [
                (
                    "Do not launch Codex or consume "
                    "model quota in this transport dogfood."
                ),
                (
                    "Do not enable paid, publish, delete, "
                    "or external-message authority."
                ),
            ],
            "deliverables": [
                "tunnel handshake",
                "accepted mission",
                "started operator",
                "compiled outcome",
                "outcome acknowledgement",
            ],
            "required_evidence": [
                "git_diff",
                "test_result",
            ],
            "human_decisions": [],
            "execution_policy": {
                "allow_paid": False,
                "allow_publish": False,
                "allow_delete": False,
                "allow_external_message": False,
            },
            "metadata": {
                "dogfood_challenge_id": (
                    challenge_id
                ),
                "dogfood_nonce": nonce,
                "zero_quota": True,
            },
        }

        request_ids = {
            "submit": (
                f"{challenge_id}-submit"
            ),
            "start": (
                f"{challenge_id}-start"
            ),
            "ack": (
                f"{challenge_id}-ack"
            ),
        }
        challenge = {
            "challenge_id": challenge_id,
            "nonce": nonce,
            "mission_id": mission_id,
            "title": title,
            "envelope": envelope,
            "request_ids": request_ids,
            "status": "prepared",
            "created_at": utc_now(),
        }
        self._write_json(
            root / "challenge.json",
            challenge,
        )
        return {
            "challenge_id": challenge_id,
            "nonce": nonce,
            "mission_id": mission_id,
            "prompt": self._prompt(
                challenge_id,
                nonce,
            ),
        }

    def handshake(
        self,
        challenge_id: str,
        nonce: str,
        *,
        client_label: str = "chatgpt-space",
    ) -> dict[str, Any]:
        challenge = self._challenge(
            challenge_id
        )
        if not secrets.compare_digest(
            str(challenge["nonce"]),
            nonce,
        ):
            raise RuntimeError(
                "Dogfood challenge nonce mismatch"
            )

        root = self.base / challenge_id
        path = root / "handshake.json"
        if path.exists():
            return self._read_json(path)

        payload = {
            "challenge_id": challenge_id,
            "mission_id": challenge["mission_id"],
            "client_label": client_label,
            "transport": "mcp",
            "handshake_at": utc_now(),
            "envelope": challenge["envelope"],
            "request_ids": challenge[
                "request_ids"
            ],
            "instructions": [
                (
                    "Call mado_submit_mission with "
                    "the returned envelope and submit "
                    "request_id."
                ),
                (
                    "Call mado_start_mission with the "
                    "returned envelope_id and start "
                    "request_id."
                ),
                (
                    "Call mado_refresh_outcome."
                ),
                (
                    "Call mado_acknowledge_outcome "
                    "with the exact outcome_digest and "
                    "ack request_id."
                ),
            ],
        }
        self._write_json(path, payload)
        return payload

    def verify(
        self,
        challenge_id: str,
    ) -> dict[str, Any]:
        challenge = self._challenge(
            challenge_id
        )
        root = self.base / challenge_id
        handshake = (
            self._read_json(
                root / "handshake.json"
            )
            if (
                root / "handshake.json"
            ).exists()
            else None
        )

        request_ids = challenge[
            "request_ids"
        ]
        submit_receipt = self._request_receipt(
            request_ids["submit"]
        )
        start_receipt = self._request_receipt(
            request_ids["start"]
        )
        ack_receipt = self._request_receipt(
            request_ids["ack"]
        )

        envelope_id = None
        if submit_receipt:
            envelope_id = (
                submit_receipt[
                    "result"
                ].get("envelope_id")
            )

        control = None
        if envelope_id:
            try:
                control = (
                    self.transport.control.inspect(
                        str(envelope_id)
                    )
                )
            except RuntimeError:
                control = None

        outcome = (
            control.get("outcome")
            if control
            else None
        )
        outcome_digest = (
            self.transport.outcome_digest(
                outcome
            )
            if outcome
            else None
        )

        ack_record = None
        if envelope_id and outcome_digest:
            path = (
                self.transport.acks_dir
                / str(envelope_id)
                / f"{outcome_digest}.json"
            )
            if path.exists():
                ack_record = self._read_json(
                    path
                )

        checks = {
            "mcp_handshake": handshake is not None,
            "mission_submitted": (
                submit_receipt is not None
            ),
            "mission_started": (
                start_receipt is not None
            ),
            "outcome_compiled": (
                outcome is not None
            ),
            "outcome_acknowledged": (
                ack_receipt is not None
                and ack_record is not None
            ),
        }
        complete = all(checks.values())
        result = {
            "challenge_id": challenge_id,
            "mission_id": challenge["mission_id"],
            "complete": complete,
            "checks": checks,
            "envelope_id": envelope_id,
            "outcome_status": (
                outcome.get("status")
                if outcome
                else None
            ),
            "outcome_digest": outcome_digest,
            "verified_at": utc_now(),
        }
        self._write_json(
            root / "verification.json",
            result,
        )
        return result

    def inspect(
        self,
        challenge_id: str,
    ) -> dict[str, Any]:
        challenge = self._challenge(
            challenge_id
        )
        root = self.base / challenge_id
        return {
            "challenge": challenge,
            "handshake": (
                self._read_json(
                    root / "handshake.json"
                )
                if (
                    root / "handshake.json"
                ).exists()
                else None
            ),
            "verification": (
                self._read_json(
                    root / "verification.json"
                )
                if (
                    root / "verification.json"
                ).exists()
                else None
            ),
        }

    def _request_receipt(
        self,
        request_id: str,
    ) -> dict[str, Any] | None:
        path = (
            self.transport.requests_dir
            / f"{request_id}.json"
        )
        if not path.exists():
            return None
        return self._read_json(path)

    def _challenge(
        self,
        challenge_id: str,
    ) -> dict[str, Any]:
        if (
            not challenge_id
            or "/" in challenge_id
            or "\\" in challenge_id
            or ".." in challenge_id
        ):
            raise RuntimeError(
                "Invalid dogfood challenge id"
            )
        path = (
            self.base
            / challenge_id
            / "challenge.json"
        )
        if not path.exists():
            raise RuntimeError(
                "Dogfood challenge not found: "
                f"{challenge_id}"
            )
        return self._read_json(path)

    @staticmethod
    def _prompt(
        challenge_id: str,
        nonce: str,
    ) -> str:
        return (
            "Use the MADO Cockpit Space plugin to run "
            "the zero-quota transport dogfood. First call "
            "mado_dogfood_handshake with challenge_id="
            f"{challenge_id} and nonce={nonce}. Then "
            "follow the returned instructions exactly. "
            "Do not launch Codex or add any paid/publish/"
            "delete/external-message authority."
        )

    def _require_initialized(self) -> None:
        if not self.store.project_file.exists():
            raise RuntimeError(
                "Cockpit is not initialized"
            )

    @staticmethod
    def _write_json(
        path: Path,
        payload: Mapping[str, Any],
    ) -> None:
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        path.write_text(
            json.dumps(
                dict(payload),
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
            path.read_text(encoding="utf-8")
        )
