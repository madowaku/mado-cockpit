# MCC-M2.9 Free Coding Fallback / MiniMax M3.1 Flash Bridge

OpenCode is an optional, explicitly selected provider for Cockpit's existing
turn-based AgentSession API. The Codex default is unchanged.

## Prerequisites

1. Install OpenCode CLI and authenticate with its OpenCode provider.
2. Verify availability with `opencode models --refresh` and
   `opencode models | Select-String "minimax-m3.1-flash-free"` (PowerShell).
3. Use `provider_name="opencode"` with `SessionManager.start(worker_id,
   prompt, provider_name="opencode")`. By default the OpenCode adapter selects
   `opencode/minimax-m3.1-flash-free`.
4. Resume via `SessionManager.send(session_id, prompt)`.

The adapter refuses non-OpenCode and non-`-free` model IDs, never silently
routes to a paid model, and verifies session ID continuity through the
existing SessionManager. OpenCode's non-interactive `run --format json`
provides JSONL trace evidence. A failing command or missing session ID
fails closed.

This is not a security sandbox: the OpenCode CLI may run tools with the user's
local permissions. Use isolated worktrees and limited credentials. Free access
is temporary and must be verified at execution time. No automatic Codex
exhaustion detection or cross-provider conversation migration is claimed.

## Verification

`python -m pytest tests/test_opencode_provider.py tests/test_sessions.py`

Live OpenCode authentication and Windows execution require local dogfood;
unit tests use deterministic fake command output.
