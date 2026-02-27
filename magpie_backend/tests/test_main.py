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
    _DdgLiteParser,
    _build_reddit_item,
    _build_web_item,
    _call_graphrag_mcp,
    _extract_graphrag_results,
    _normalize_snippet,
    _search_reddit_public,
    _search_web_ddg_lite,
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
    code = run(
        stdin,
        stdout,
        env
        or {
            "MAGPIE_USE_FIXTURES": "0",
            "MAGPIE_WEBSEARCH_PROVIDER": "none",
            "MAGPIE_REDDIT_PROVIDER": "none",
        },
    )
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
        self.assertEqual(ack["capabilities"]["web_search"], False)
        self.assertEqual(ack["capabilities"]["reddit_search"], False)

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

    def test_hello_ack_capabilities_true_when_providers_enabled(self) -> None:
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
            env={
                "MAGPIE_USE_FIXTURES": "0",
                "MAGPIE_WEBSEARCH_PROVIDER": "ddg",
                "MAGPIE_REDDIT_PROVIDER": "public",
            },
        )
        ack = next(m for m in out if m.get("type") == "hello_ack")
        self.assertEqual(ack["capabilities"]["web_search"], True)
        self.assertEqual(ack["capabilities"]["reddit_search"], True)

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
        self.assertEqual([p.get("name") for p in phases], ["rag", "search", "idle"])

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

        web_items = next(m for m in out if m.get("type") == "items" and m.get("group") == "web")
        self.assertEqual(web_items["in_reply_to"], "r2")
        self.assertEqual(web_items["items"][0]["id"], "web:1")

        reddit_items = next(m for m in out if m.get("type") == "items" and m.get("group") == "reddit")
        self.assertEqual(reddit_items["in_reply_to"], "r2")
        self.assertEqual(reddit_items["items"][0]["id"], "reddit:1")

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
                "MAGPIE_WEBSEARCH_PROVIDER": "none",
                "MAGPIE_REDDIT_PROVIDER": "none",
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
        self.assertEqual(ack["capabilities"]["web_search"], True)
        self.assertEqual(ack["capabilities"]["reddit_search"], True)

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

    def test_build_web_and_reddit_items_include_detail_only_when_present(self) -> None:
        web = _build_web_item({"title": "t", "url": "u", "snippet": "s"}, 0)
        self.assertTrue("detail" not in web)

        web_with_detail = _build_web_item({"title": "t", "url": "u", "snippet": "s", "detail": "d"}, 0)
        self.assertEqual(web_with_detail["detail"], "d")

        reddit = _build_reddit_item({"title": "t", "url": "u", "snippet": "s"}, 0)
        self.assertTrue("detail" not in reddit)

        reddit_with_detail = _build_reddit_item({"title": "t", "url": "u", "snippet": "s", "detail": "d"}, 0)
        self.assertEqual(reddit_with_detail["detail"], "d")

    def test_ddg_lite_parser_extracts_title_url_and_snippet(self) -> None:
        html = (
            '<a class="result-link" href="https://example.com">Example</a>'
            '<td class="result-snippet">Snippet here</td>'
        )
        parser = _DdgLiteParser()
        parser.feed(html)
        self.assertEqual(len(parser.results), 1)
        self.assertEqual(parser.results[0]["title"], "Example")
        self.assertEqual(parser.results[0]["url"], "https://example.com")
        self.assertEqual(parser.results[0]["snippet"], "Snippet here")

    def test_web_and_reddit_search_helpers_success_and_edge_shapes(self) -> None:
        ddg_html = (
            '<a class="result-link" href="https://a.example">A</a>'
            '<td class="result-snippet">A snip</td>'
            '<a class="result-link" href="https://b.example">B</a>'
            '<td class="result-snippet">B snip</td>'
        )
        reddit_json = json.dumps(
            {
                "data": {
                    "children": [
                        "bad",
                        {"data": "bad"},
                        {"data": {"title": "", "permalink": "/r/x"}},
                        {"data": {"title": "T1", "permalink": "/r/test/1", "subreddit_name_prefixed": "r/test", "author": "a", "selftext": "body"}},
                        {"data": {"title": "T2", "permalink": "/r/test/2", "subreddit_name_prefixed": "r/test", "author": "b", "selftext": ""}},
                    ]
                }
            }
        )

        class FakeHeaders:
            def __init__(self, charset: str = "utf-8") -> None:
                self._charset = charset

            def get_content_charset(self) -> str:
                return self._charset

        class FakeResp:
            def __init__(self, body: str) -> None:
                self.headers = FakeHeaders()
                self._body = body.encode("utf-8")

            def read(self) -> bytes:
                return self._body

            def __enter__(self) -> "FakeResp":
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                return None

        def fake_urlopen(req, timeout=None):  # noqa: ANN001
            url = getattr(req, "full_url", str(req))
            if "duckduckgo" in url:
                return FakeResp(ddg_html)
            if "reddit.com/search.json" in url:
                return FakeResp(reddit_json)
            raise AssertionError(f"unexpected url: {url}")

        with mock.patch("magpie_backend.__main__.urllib.request.urlopen", side_effect=fake_urlopen):
            web_items = _search_web_ddg_lite("q", {"MAGPIE_WEB_TOP_K": "1"})
            self.assertEqual(len(web_items), 1)
            self.assertEqual(web_items[0]["group"], "web")

            empty_reddit = _search_reddit_public("q", {"MAGPIE_REDDIT_TOP_K": "1", "MAGPIE_SEARCH_TIMEOUT_SEC": "1", "MAGPIE_REDDIT_PROVIDER": "public", "MAGPIE_WEBSEARCH_PROVIDER": "ddg", "MAGPIE_DDG_LITE_URL": "https://lite.duckduckgo.com/lite/" , "MAGPIE_WEB_TOP_K": "5", "MAGPIE_REDDIT_TOP_K": "1"})
            self.assertEqual(len(empty_reddit), 1)
            self.assertEqual(empty_reddit[0]["group"], "reddit")

            # children not a list -> []
            class FakeResp2(FakeResp):
                pass

            def fake_urlopen_children_bad(req, timeout=None):  # noqa: ANN001
                return FakeResp2(json.dumps({"data": {"children": "oops"}}))

            with mock.patch("magpie_backend.__main__.urllib.request.urlopen", side_effect=fake_urlopen_children_bad):
                self.assertEqual(_search_reddit_public("q", {"MAGPIE_REDDIT_TOP_K": "5"}), [])

    def test_start_with_providers_sends_web_and_reddit_items_and_handles_errors(self) -> None:
        class FakeHeaders:
            def get_content_charset(self) -> str:
                return "utf-8"

        class FakeResp:
            def __init__(self, body: str) -> None:
                self.headers = FakeHeaders()
                self._body = body.encode("utf-8")

            def read(self) -> bytes:
                return self._body

            def __enter__(self) -> "FakeResp":
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                return None

        ddg_html = '<a class="result-link" href="https://example.com">X</a><td class="result-snippet">Y</td>'
        reddit_json = json.dumps({"data": {"children": [{"data": {"title": "T", "permalink": "/r/t/1", "subreddit_name_prefixed": "r/t", "author": "a", "selftext": ""}}]}})

        def fake_urlopen(req, timeout=None):  # noqa: ANN001
            url = getattr(req, "full_url", str(req))
            if "duckduckgo" in url:
                return FakeResp(ddg_html)
            if "reddit.com/search.json" in url:
                return FakeResp(reddit_json)
            raise AssertionError(f"unexpected url: {url}")

        out = []
        with mock.patch("magpie_backend.__main__.urllib.request.urlopen", side_effect=fake_urlopen):
            out = _run_backend(
                [
                    {"type": "hello", "session_id": "s1", "request_id": "r1", "protocol_version": 1, "workspace_root": "/tmp", "permission": "ro"},
                    {"type": "start", "session_id": "s1", "request_id": "r2", "query": "q", "workspace_root": "/tmp", "permission": "ro"},
                ],
                env={"MAGPIE_USE_FIXTURES": "0", "MAGPIE_WEBSEARCH_PROVIDER": "ddg", "MAGPIE_REDDIT_PROVIDER": "public"},
            )
        web_items = next(m for m in out if m.get("type") == "items" and m.get("group") == "web")
        reddit_items = next(m for m in out if m.get("type") == "items" and m.get("group") == "reddit")
        self.assertEqual(len(web_items["items"]), 1)
        self.assertEqual(len(reddit_items["items"]), 1)

        def always_fail(_req, timeout=None):  # noqa: ANN001
            raise OSError("net down")

        with mock.patch("magpie_backend.__main__.urllib.request.urlopen", side_effect=always_fail):
            out2 = _run_backend(
                [
                    {"type": "hello", "session_id": "s1", "request_id": "r1", "protocol_version": 1, "workspace_root": "/tmp", "permission": "ro"},
                    {"type": "start", "session_id": "s1", "request_id": "r2", "query": "q", "workspace_root": "/tmp", "permission": "ro"},
                ],
                env={"MAGPIE_USE_FIXTURES": "0", "MAGPIE_WEBSEARCH_PROVIDER": "ddg", "MAGPIE_REDDIT_PROVIDER": "public"},
            )
        warn_logs = [m for m in out2 if m.get("type") == "log" and m.get("level") == "warn"]
        self.assertTrue(any("web search failed" in str(m.get("message")) for m in warn_logs))
        self.assertTrue(any("reddit search failed" in str(m.get("message")) for m in warn_logs))

        web_empty = next(m for m in out2 if m.get("type") == "items" and m.get("group") == "web")
        reddit_empty = next(m for m in out2 if m.get("type") == "items" and m.get("group") == "reddit")
        self.assertEqual(web_empty["items"], [])
        self.assertEqual(reddit_empty["items"], [])

        out3 = _run_backend(
            [
                {"type": "hello", "session_id": "s1", "request_id": "r1", "protocol_version": 1, "workspace_root": "/tmp", "permission": "ro"},
                {"type": "start", "session_id": "s1", "request_id": "r2", "query": "q", "workspace_root": "/tmp", "permission": "ro"},
            ],
            env={"MAGPIE_USE_FIXTURES": "0", "MAGPIE_WEBSEARCH_PROVIDER": "weird", "MAGPIE_REDDIT_PROVIDER": "weird"},
        )
        warn3 = [m for m in out3 if m.get("type") == "log" and m.get("level") == "warn"]
        self.assertTrue(any("unknown web provider" in str(m.get("message")) for m in warn3))
        self.assertTrue(any("unknown reddit provider" in str(m.get("message")) for m in warn3))

if __name__ == "__main__":
    unittest.main()
