from __future__ import annotations

import contextlib
import io
import json
import os
import runpy
import sys
import unittest

from magpie_backend.__main__ import run


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
        done = next(m for m in out if m.get("type") == "done" and m.get("in_reply_to") == "r2")
        self.assertEqual(done["ok"], True)
        self.assertEqual(done["canceled"], False)

        phases = [m for m in out if m.get("type") == "phase" and m.get("in_reply_to") == "r2"]
        self.assertEqual([p.get("name") for p in phases], ["rag", "idle"])

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
