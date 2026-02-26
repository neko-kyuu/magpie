from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Dict, Optional


def _send(obj: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _log(session_id: str, level: str, message: str, in_reply_to: Optional[str] = None) -> None:
    payload: Dict[str, Any] = {
        "type": "log",
        "session_id": session_id,
        "level": level,
        "message": message,
    }
    if in_reply_to is not None:
        payload["in_reply_to"] = in_reply_to
    _send(payload)


def main() -> int:
    session_id = os.environ.get("MAGPIE_SESSION_ID", "unknown")
    fixtures = os.environ.get("MAGPIE_USE_FIXTURES") == "1"

    _log(session_id, "info", "backend booted")

    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception as e:  # noqa: BLE001
            _log(session_id, "warn", f"failed to parse JSON: {e} :: {line[:200]}")
            continue

        session_id = str(msg.get("session_id") or session_id)
        mtype = msg.get("type")
        request_id = msg.get("request_id")

        if mtype == "hello":
            _send(
                {
                    "type": "hello_ack",
                    "session_id": session_id,
                    "in_reply_to": request_id,
                    "protocol_version": 1,
                    "capabilities": {
                        "mcp_graphrag": False,
                        "web_search": False,
                        "reddit_search": False,
                        "fixtures": fixtures,
                    },
                }
            )
            _log(session_id, "info", "hello_ack sent", in_reply_to=request_id)
            continue

        if mtype == "cancel":
            _log(session_id, "info", "cancel received", in_reply_to=request_id)
            _send(
                {
                    "type": "done",
                    "session_id": session_id,
                    "in_reply_to": request_id,
                    "ok": True,
                    "canceled": True,
                }
            )
            _send({"type": "phase", "session_id": session_id, "name": "idle", "in_reply_to": request_id})
            continue

        if mtype == "start":
            query = str(msg.get("query") or "")
            _send({"type": "phase", "session_id": session_id, "name": "rag", "in_reply_to": request_id})
            _log(session_id, "info", f"received query: {query}", in_reply_to=request_id)
            time.sleep(0.1)
            _log(session_id, "info", "M0 demo: no-op pipeline (RAG/SEARCH/GENERATE to be added in later milestones)", in_reply_to=request_id)
            _send(
                {
                    "type": "done",
                    "session_id": session_id,
                    "in_reply_to": request_id,
                    "ok": True,
                    "canceled": False,
                }
            )
            _send({"type": "phase", "session_id": session_id, "name": "idle", "in_reply_to": request_id})
            continue

        _log(session_id, "warn", f"unknown message type: {mtype}", in_reply_to=request_id)

    _log(session_id, "info", "stdin closed; exiting")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

