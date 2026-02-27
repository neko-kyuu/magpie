#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from typing import Any


def _send(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


for raw in sys.stdin:
    line = raw.strip()
    if not line:
        continue
    try:
        msg = json.loads(line)
    except Exception:
        continue

    method = msg.get("method")
    if method == "initialize":
        _send(
            {
                "jsonrpc": "2.0",
                "id": msg.get("id"),
                "result": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "mock-graphrag-mcp", "version": "0.0.1"},
                },
            }
        )
        continue

    if method == "tools/call":
        _send(
            {
                "jsonrpc": "2.0",
                "id": msg.get("id"),
                "result": {
                    "content": [{"type": "text", "text": "ok"}],
                    "isError": False,
                    "structuredContent": {
                        "results": [
                            {
                                "rank": 1,
                                "node_id": "n1",
                                "score": 0.91,
                                "source": "vault://note-1",
                                "title": "Mock GraphRAG Note",
                                "text": "This is a mock graphrag result chunk for tests.",
                                "metadata": {"doc_id": "doc-1", "chunk_id": "chunk-1"},
                            }
                        ]
                    },
                },
            }
        )
        continue

