from __future__ import annotations

import contextlib
import io
import json
import os
import runpy
import subprocess
import sys
import unittest
from unittest import mock
from pathlib import Path

from magpie_backend.__main__ import (
    _call_graphrag_mcp,
    _extract_graphrag_results,
    _normalize_snippet,
    _safe_float,
    _safe_int,
    run,
)


def _lines_to_jsonl(lines: list[dict]) -> str:
    return "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines)


@contextlib.contextmanager
def _patched_env(vars: dict[str, str]) -> object:
    prev: dict[str, str | None] = {k: os.environ.get(k) for k in vars}
    for k, v in vars.items():
        os.environ[k] = v
    try:
        yield None
    finally:
        for k, old in prev.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old


@contextlib.contextmanager
def _patched_stdio(stdin_text: str) -> object:
    prev_in, prev_out = sys.stdin, sys.stdout
    sys.stdin = io.StringIO(stdin_text)
    sys.stdout = io.StringIO()
    try:
        yield sys.stdout
    finally:
        sys.stdin, sys.stdout = prev_in, prev_out


def _run_backend(messages: list[dict], env: dict[str, str] | None = None) -> list[dict]:
    stdin = io.StringIO(_lines_to_jsonl(messages))
    stdout = io.StringIO()
    code = run(stdin, stdout, env or {"MAGPIE_USE_FIXTURES": "0"})
    assert code == 0
    return [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]


class BackendMainTests(unittest.TestCase):
    def test_helper_parsers_and_normalize(self) -> None:
        self.assertEqual(_safe_float("bad", 1.5), 1.5)
        self.assertEqual(_safe_int("bad", 7), 7)
        normalized = _normalize_snippet("a " * 40, max_chars=20)
        self.assertTrue(normalized.endswith("..."))
        self.assertLessEqual(len(normalized), 20)

    def test_extract_graphrag_results_supports_direct_results(self) -> None:
        items = _extract_graphrag_results({"results": [{"title": "x"}]})
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "x")

    def test_extract_graphrag_results_from_content_text_json(self) -> None:
        payload = {
            "content": [
                {
                    "type": "text",
                    "text": '{"results":[{"title":"from-content","text":"chunk"}]}',
                }
            ]
        }
        items = _extract_graphrag_results(payload)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "from-content")

    def test_extract_graphrag_results_handles_nested_and_fenced_shapes(self) -> None:
        nested_payload = {"structuredContent": {"payload": {"data": [{"title": "nested"}]}}}
        nested = _extract_graphrag_results(nested_payload)
        self.assertEqual(nested[0]["title"], "nested")

        fenced_payload = {
            "content": [
                {"type": "text", "text": "```json\n[{\"title\":\"list-item\"}]\n```"},
            ]
        }
        fenced = _extract_graphrag_results(fenced_payload)
        self.assertEqual(fenced[0]["title"], "list-item")

    def test_extract_graphrag_results_ignores_unparseable_content(self) -> None:
        payload = {"content": [1, {"type": "text", "text": "not json"}, {"type": "text"}]}
        items = _extract_graphrag_results(payload)
        self.assertEqual(items, [])

    def test_extract_graphrag_results_edge_paths(self) -> None:
        # content 不是 list 时直接返回空
        self.assertEqual(_extract_graphrag_results({"content": "x"}), [])

        # content block 内含 items 时直接命中 block 级提取
        from_block = _extract_graphrag_results({"content": [{"items": [{"title": "block-item"}]}]})
        self.assertEqual(len(from_block), 1)
        self.assertEqual(from_block[0]["title"], "block-item")

        # 空白 text 触发 _json_candidates 的空串分支
        self.assertEqual(_extract_graphrag_results({"content": [{"type": "text", "text": "   "}]}), [])

    def test_call_graphrag_mcp_errors_without_command(self) -> None:
        items, warn = _call_graphrag_mcp("q", {})
        self.assertEqual(items, [])
        self.assertIn("not configured", str(warn))

    def test_call_graphrag_mcp_timeout_and_nonzero_exit(self) -> None:
        class TimeoutProc:
            def __init__(self) -> None:
                self._first = True
                self.returncode = 0

            def communicate(self, _payload: str | None = None, timeout: float | None = None):
                if self._first:
                    self._first = False
                    raise subprocess.TimeoutExpired(cmd="mock", timeout=timeout or 0)
                return ("", "")

            def kill(self) -> None:
                return None

        class ExitProc:
            returncode = 2

            def communicate(self, _payload: str | None = None, timeout: float | None = None):
                return ("", "boom")

            def kill(self) -> None:
                return None

        with mock.patch("magpie_backend.__main__.subprocess.Popen", return_value=TimeoutProc()):
            items, warn = _call_graphrag_mcp("q", {"MAGPIE_GRAPHRAG_MCP_CMD": "mock", "MAGPIE_MCP_TIMEOUT_SEC": "0.01"})
            self.assertEqual(items, [])
            self.assertIn("timed out", str(warn))

        with mock.patch("magpie_backend.__main__.subprocess.Popen", return_value=ExitProc()):
            items, warn = _call_graphrag_mcp("q", {"MAGPIE_GRAPHRAG_MCP_CMD": "mock"})
            self.assertEqual(items, [])
            self.assertIn("exited with code 2", str(warn))

    def test_call_graphrag_mcp_response_shapes(self) -> None:
        class Proc:
            def __init__(self, stdout_text: str, stderr_text: str = "", returncode: int = 0) -> None:
                self._stdout_text = stdout_text
                self._stderr_text = stderr_text
                self.returncode = returncode

            def communicate(self, _payload: str | None = None, timeout: float | None = None):
                return (self._stdout_text, self._stderr_text)

            def kill(self) -> None:
                return None

        no_call_stdout = '{"jsonrpc":"2.0","id":"init-1","result":{}}\n'
        with mock.patch("magpie_backend.__main__.subprocess.Popen", return_value=Proc(no_call_stdout)):
            items, warn = _call_graphrag_mcp("q", {"MAGPIE_GRAPHRAG_MCP_CMD": "mock"})
            self.assertEqual(items, [])
            self.assertIn("did not return tools/call", str(warn))

        err_stdout = '{"jsonrpc":"2.0","id":"call-1","error":{"message":"bad"}}\n'
        with mock.patch("magpie_backend.__main__.subprocess.Popen", return_value=Proc(err_stdout)):
            items, warn = _call_graphrag_mcp("q", {"MAGPIE_GRAPHRAG_MCP_CMD": "mock"})
            self.assertEqual(items, [])
            self.assertIn("failed: bad", str(warn))

        invalid_result_stdout = '{"jsonrpc":"2.0","id":"call-1","result":"oops"}\n'
        with mock.patch("magpie_backend.__main__.subprocess.Popen", return_value=Proc(invalid_result_stdout)):
            items, warn = _call_graphrag_mcp("q", {"MAGPIE_GRAPHRAG_MCP_CMD": "mock"})
            self.assertEqual(items, [])
            self.assertIn("invalid result payload", str(warn))

        ok_stdout = (
            "\n"
            "not-json\n"
            '{"jsonrpc":"2.0","id":"call-1","result":{"content":[{"type":"text","text":"{\\"results\\":[{\\"title\\":\\"x\\",\\"text\\":\\"y\\"}]}"}]}}\n'
        )
        with mock.patch("magpie_backend.__main__.subprocess.Popen", return_value=Proc(ok_stdout, "server-log")):
            items, warn = _call_graphrag_mcp("q", {"MAGPIE_GRAPHRAG_MCP_CMD": "mock"})
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["id"], "rag:1")
            self.assertIn("stderr", str(warn))

    def test_hello_ack(self) -> None:
        out = _run_backend(
            [
                {
                    "type": "hello",
                    "session_id": "s1",
                    "request_id": "r1",
                    "protocol_version": 1,
                    "workspace_root": "/tmp",
                    "permission": "ro",
                }
            ]
        )
        types = [m.get("type") for m in out]
        self.assertIn("log", types)  # backend booted
        self.assertIn("hello_ack", types)

        ack = next(m for m in out if m.get("type") == "hello_ack")
        self.assertEqual(ack["in_reply_to"], "r1")
        self.assertEqual(ack["session_id"], "s1")
        self.assertEqual(ack["protocol_version"], 1)
        self.assertEqual(ack["capabilities"]["fixtures"], False)
        self.assertEqual(ack["capabilities"]["mcp_graphrag"], False)

    def test_hello_ack_mcp_capability_true_when_configured(self) -> None:
        out = _run_backend(
            [
                {
                    "type": "hello",
                    "session_id": "s1",
                    "request_id": "r1",
                    "protocol_version": 1,
                    "workspace_root": "/tmp",
                    "permission": "ro",
                }
            ],
            env={"MAGPIE_USE_FIXTURES": "0", "MAGPIE_GRAPHRAG_MCP_CMD": "echo test"},
        )
        ack = next(m for m in out if m.get("type") == "hello_ack")
        self.assertEqual(ack["capabilities"]["mcp_graphrag"], True)

    def test_start_produces_done(self) -> None:
        out = _run_backend(
            [
                {
                    "type": "hello",
                    "session_id": "s1",
                    "request_id": "r1",
                    "protocol_version": 1,
                    "workspace_root": "/tmp",
                    "permission": "ro",
                },
                {
                    "type": "start",
                    "session_id": "s1",
                    "request_id": "r2",
                    "query": "test",
                    "workspace_root": "/tmp",
                    "permission": "ro",
                },
            ]
        )
        items = next(m for m in out if m.get("type") == "items" and m.get("in_reply_to") == "r2")
        self.assertEqual(items["group"], "rag")
        self.assertEqual(items["items"], [])

        done = next(m for m in out if m.get("type") == "done" and m.get("in_reply_to") == "r2")
        self.assertEqual(done["ok"], True)
        self.assertEqual(done["canceled"], False)

        phases = [m for m in out if m.get("type") == "phase" and m.get("in_reply_to") == "r2"]
        self.assertEqual([p.get("name") for p in phases], ["rag", "idle"])

    def test_start_with_fixtures_returns_rag_items(self) -> None:
        out = _run_backend(
            [
                {
                    "type": "hello",
                    "session_id": "s1",
                    "request_id": "r1",
                    "protocol_version": 1,
                    "workspace_root": "/tmp",
                    "permission": "ro",
                },
                {
                    "type": "start",
                    "session_id": "s1",
                    "request_id": "r2",
                    "query": "fixtures query",
                    "workspace_root": "/tmp",
                    "permission": "ro",
                },
            ],
            env={"MAGPIE_USE_FIXTURES": "1", "MAGPIE_SESSION_ID": "s_env"},
        )
        items = next(m for m in out if m.get("type") == "items" and m.get("in_reply_to") == "r2")
        self.assertEqual(items["group"], "rag")
        self.assertGreaterEqual(len(items["items"]), 2)
        self.assertEqual(items["items"][0]["id"], "rag:1")

    def test_start_with_mcp_command_returns_rag_items(self) -> None:
        mcp_script = Path(__file__).resolve().parents[2] / "fixtures" / "mock-graphrag-mcp.py"
        out = _run_backend(
            [
                {
                    "type": "hello",
                    "session_id": "s1",
                    "request_id": "r1",
                    "protocol_version": 1,
                    "workspace_root": "/tmp",
                    "permission": "ro",
                },
                {
                    "type": "start",
                    "session_id": "s1",
                    "request_id": "r2",
                    "query": "mcp query",
                    "workspace_root": "/tmp",
                    "permission": "ro",
                },
            ],
            env={
                "MAGPIE_USE_FIXTURES": "0",
                "MAGPIE_SESSION_ID": "s_mcp",
                "MAGPIE_GRAPHRAG_MCP_CMD": f"python3 {mcp_script}",
            },
        )
        items = next(m for m in out if m.get("type") == "items" and m.get("in_reply_to") == "r2")
        self.assertEqual(items["group"], "rag")
        self.assertEqual(len(items["items"]), 1)
        self.assertEqual(items["items"][0]["title"], "Mock GraphRAG Note")

    def test_cancel_produces_done_canceled(self) -> None:
        out = _run_backend(
            [
                {
                    "type": "hello",
                    "session_id": "s1",
                    "request_id": "r1",
                    "protocol_version": 1,
                    "workspace_root": "/tmp",
                    "permission": "ro",
                },
                {
                    "type": "cancel",
                    "session_id": "s1",
                    "request_id": "r_cancel",
                },
            ]
        )

        done = next(
            m for m in out if m.get("type") == "done" and m.get("in_reply_to") == "r_cancel"
        )
        self.assertEqual(done["ok"], True)
        self.assertEqual(done["canceled"], True)

        phase = next(
            m for m in out if m.get("type") == "phase" and m.get("in_reply_to") == "r_cancel"
        )
        self.assertEqual(phase["name"], "idle")

    def test_invalid_json_is_logged_and_ignored(self) -> None:
        stdin = io.StringIO("{not json}\n")
        stdout = io.StringIO()
        code = run(stdin, stdout, {"MAGPIE_USE_FIXTURES": "0", "MAGPIE_SESSION_ID": "s_err"})
        self.assertEqual(code, 0)

        out = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
        warn = next(m for m in out if m.get("type") == "log" and m.get("level") == "warn")
        self.assertEqual(warn["session_id"], "s_err")
        self.assertIn("failed to parse JSON", warn["message"])

    def test_unknown_message_type_is_logged(self) -> None:
        out = _run_backend(
            [
                {
                    "type": "hello",
                    "session_id": "s1",
                    "request_id": "r1",
                    "protocol_version": 1,
                    "workspace_root": "/tmp",
                    "permission": "ro",
                },
                {
                    "type": "set_permission",
                    "session_id": "s1",
                    "request_id": "r_perm",
                    "permission": "rw",
                },
            ]
        )
        warn = next(m for m in out if m.get("type") == "log" and m.get("level") == "warn")
        self.assertEqual(warn["in_reply_to"], "r_perm")
        self.assertIn("unknown message type", warn["message"])

    def test_stdin_closed_is_logged(self) -> None:
        out = _run_backend(
            [
                {
                    "type": "hello",
                    "session_id": "s1",
                    "request_id": "r1",
                    "protocol_version": 1,
                    "workspace_root": "/tmp",
                    "permission": "ro",
                }
            ]
        )
        last = out[-1]
        self.assertEqual(last["type"], "log")
        self.assertIn("stdin closed", last["message"])

    def test_fixtures_capability_true_when_env_set(self) -> None:
        out = _run_backend(
            [
                {
                    "type": "hello",
                    "request_id": "r1",
                    "protocol_version": 1,
                    "workspace_root": "/tmp",
                    "permission": "ro",
                }
            ],
            env={"MAGPIE_USE_FIXTURES": "1", "MAGPIE_SESSION_ID": "s_env"},
        )
        ack = next(m for m in out if m.get("type") == "hello_ack")
        self.assertEqual(ack["session_id"], "s_env")
        self.assertEqual(ack["capabilities"]["fixtures"], True)

    def test_blank_lines_are_ignored(self) -> None:
        stdin = io.StringIO("\n\n" + _lines_to_jsonl([{"type": "hello", "session_id": "s1", "request_id": "r1"}]))
        stdout = io.StringIO()
        code = run(stdin, stdout, {"MAGPIE_USE_FIXTURES": "0"})
        self.assertEqual(code, 0)

        out = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
        self.assertTrue(any(m.get("type") == "hello_ack" for m in out))

    def test_module_entrypoint_exits_0(self) -> None:
        stdin_text = _lines_to_jsonl(
            [
                {
                    "type": "hello",
                    "session_id": "s_entry",
                    "request_id": "r1",
                    "protocol_version": 1,
                    "workspace_root": "/tmp",
                    "permission": "ro",
                }
            ]
        )
        with _patched_env({"MAGPIE_USE_FIXTURES": "1", "MAGPIE_SESSION_ID": "s_entry"}):
            with _patched_stdio(stdin_text) as stdout:
                with self.assertRaises(SystemExit) as cm:
                    sys.modules.pop("magpie_backend.__main__", None)
                    runpy.run_module("magpie_backend.__main__", run_name="__main__")
                self.assertEqual(cm.exception.code, 0)

                out = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
                ack = next(m for m in out if m.get("type") == "hello_ack")
                self.assertEqual(ack["capabilities"]["fixtures"], True)

if __name__ == "__main__":
    unittest.main()
