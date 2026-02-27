from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any, Dict, Optional


def _send(stream: io.TextIOBase, obj: Dict[str, Any]) -> None:
    stream.write(json.dumps(obj, ensure_ascii=False) + "\n")
    stream.flush()


def _log(
    stream: io.TextIOBase,
    session_id: str,
    level: str,
    message: str,
    in_reply_to: Optional[str] = None,
) -> None:
    payload: Dict[str, Any] = {
        "type": "log",
        "session_id": session_id,
        "level": level,
        "message": message,
    }
    if in_reply_to is not None:
        payload["in_reply_to"] = in_reply_to
    _send(stream, payload)


def _safe_float(value: str, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _safe_int(value: str, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _normalize_snippet(text: str, max_chars: int = 280) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= max_chars:
        return collapsed
    return collapsed[: max_chars - 3] + "..."


def _build_rag_item(raw: Dict[str, Any], index: int) -> Dict[str, Any]:
    title = str(raw.get("title") or f"RAG Result {index + 1}")
    detail = str(raw.get("text") or raw.get("snippet") or "")
    source_ref = str(raw.get("source") or "")
    url = str(raw.get("url") or source_ref)

    metadata: Dict[str, Any] = {}
    if isinstance(raw.get("metadata"), dict):
        metadata.update(raw["metadata"])
    for key in ("score", "node_id", "rank"):
        if key in raw:
            metadata[key] = raw[key]
    if source_ref:
        metadata.setdefault("source_ref", source_ref)

    return {
        "id": f"rag:{index + 1}",
        "group": "rag",
        "title": title,
        "url": url,
        "snippet": _normalize_snippet(detail),
        "detail": detail,
        "source": "graphrag",
        "metadata": metadata,
    }


def _build_web_item(raw: Dict[str, Any], index: int) -> Dict[str, Any]:
    title = str(raw.get("title") or f"Web Result {index + 1}")
    url = str(raw.get("url") or "")
    snippet = str(raw.get("snippet") or raw.get("detail") or "")
    detail = raw.get("detail")
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    item: Dict[str, Any] = {
        "id": f"web:{index + 1}",
        "group": "web",
        "title": title,
        "url": url,
        "snippet": _normalize_snippet(snippet),
        "source": str(raw.get("source") or "web"),
        "metadata": metadata,
        "clipped": False,
    }
    if isinstance(detail, str) and detail:
        item["detail"] = detail
    return item


def _build_reddit_item(raw: Dict[str, Any], index: int) -> Dict[str, Any]:
    title = str(raw.get("title") or f"Reddit Result {index + 1}")
    url = str(raw.get("url") or "")
    snippet = str(raw.get("snippet") or raw.get("detail") or "")
    detail = raw.get("detail")
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    item: Dict[str, Any] = {
        "id": f"reddit:{index + 1}",
        "group": "reddit",
        "title": title,
        "url": url,
        "snippet": _normalize_snippet(snippet),
        "source": str(raw.get("source") or "reddit"),
        "metadata": metadata,
        "clipped": False,
    }
    if isinstance(detail, str) and detail:
        item["detail"] = detail
    return item


def _fixture_rag_items(query: str) -> list[Dict[str, Any]]:
    items = [
        {
            "id": "rag:1",
            "group": "rag",
            "title": "GraphRAG basics: vector retrieval plus graph expansion",
            "url": "obsidian://graphrag/chunk/1",
            "snippet": "GraphRAG uses graph edges to improve recall across related chunks.",
            "detail": "GraphRAG uses graph edges to improve recall across related chunks.",
            "source": "fixtures",
            "metadata": {"score": 0.92, "query": query},
        },
        {
            "id": "rag:2",
            "group": "rag",
            "title": "Obsidian pattern: frontmatter filters",
            "url": "obsidian://graphrag/chunk/2",
            "snippet": "Filter by tags and frontmatter to reduce noisy retrieval results.",
            "detail": "Filter by tags and frontmatter to reduce noisy retrieval results.",
            "source": "fixtures",
            "metadata": {"score": 0.87, "query": query},
        },
    ]
    return items


def _fixture_web_items(query: str) -> list[Dict[str, Any]]:
    return [
        {
            "id": "web:1",
            "group": "web",
            "title": "DuckDuckGo Lite: query operators",
            "url": "https://duckduckgo.com/duckduckgo-help-pages/results/syntax/",
            "snippet": f"Example web result for query: {query}",
            "detail": f"Example web result for query: {query}\n\ndemonstrate clipping in the UI. " * 10,
            "source": "fixtures",
            "metadata": {"query": query},
            "clipped": False,
        }
    ]


def _fixture_reddit_items(query: str) -> list[Dict[str, Any]]:
    return [
        {
            "id": "reddit:1",
            "group": "reddit",
            "title": "AskReddit: best resources for worldbuilding?",
            "url": "https://www.reddit.com/r/AskReddit/comments/example/",
            "snippet": f"Example reddit result for query: {query}",
            "detail": f"Example reddit result for query: {query}",
            "source": "fixtures",
            "metadata": {"subreddit": "r/AskReddit", "query": query},
            "clipped": False,
        }
    ]


def _extract_graphrag_results(call_result: Dict[str, Any]) -> list[Dict[str, Any]]:
    def _extract_dict_list(obj: Any) -> list[Dict[str, Any]]:
        if not isinstance(obj, dict):
            return []

        for key in ("results", "items"):
            value = obj.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]

        for key in ("data", "payload", "output"):
            nested = obj.get(key)
            if isinstance(nested, list):
                dicts = [x for x in nested if isinstance(x, dict)]
                if dicts:
                    return dicts
            if isinstance(nested, dict):
                inner = _extract_dict_list(nested)
                if inner:
                    return inner

        return []

    def _json_candidates(text: str) -> list[str]:
        stripped = text.strip()
        if not stripped:
            return []

        candidates: list[str] = [stripped]
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].startswith("```"):
                candidates.append("\n".join(lines[1:-1]).strip())

        for left, right in (("{", "}"), ("[", "]")):
            start = stripped.find(left)
            end = stripped.rfind(right)
            if start >= 0 and end > start:
                candidates.append(stripped[start : end + 1].strip())

        deduped: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            deduped.append(candidate)
        return deduped

    for candidate in (call_result.get("structuredContent"), call_result):
        extracted = _extract_dict_list(candidate)
        if extracted:
            return extracted

    content = call_result.get("content")
    if not isinstance(content, list):
        return []

    for block in content:
        extracted = _extract_dict_list(block)
        if extracted:
            return extracted
        if not isinstance(block, dict):
            continue
        text = block.get("text")
        if not isinstance(text, str):
            continue
        for raw in _json_candidates(text):
            try:
                parsed = json.loads(raw)
            except Exception:
                continue
            if isinstance(parsed, list):
                dicts = [x for x in parsed if isinstance(x, dict)]
                if dicts:
                    return dicts
            extracted = _extract_dict_list(parsed)
            if extracted:
                return extracted

    return []


def _http_get_text(url: str, headers: dict[str, str], timeout_sec: float) -> str:
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:  # noqa: S310
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def _reddit_provider(env: dict[str, str]) -> str:
    return str(env.get("MAGPIE_REDDIT_PROVIDER") or "public").strip().lower()


def _websearch_provider(env: dict[str, str]) -> str:
    return str(env.get("MAGPIE_WEBSEARCH_PROVIDER") or "ddg").strip().lower()


def _search_timeout_sec(env: dict[str, str]) -> float:
    return _safe_float(str(env.get("MAGPIE_SEARCH_TIMEOUT_SEC") or "8"), 8.0)


def _top_k(env: dict[str, str], key: str, default: int = 5) -> int:
    return _safe_int(str(env.get(key) or str(default)), default)


class _DdgLiteParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_link = False
        self._in_snippet = False
        self._current_href: str | None = None
        self._current_title_parts: list[str] = []
        self._current_snippet_parts: list[str] = []
        self.results: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "a" and "result-link" in str(attrs_dict.get("class") or ""):
            self._in_link = True
            self._current_href = str(attrs_dict.get("href") or "")
            self._current_title_parts = []
            return
        if tag == "td" and "result-snippet" in str(attrs_dict.get("class") or ""):
            self._in_snippet = True
            self._current_snippet_parts = []
            return

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_link:
            self._in_link = False
            title = " ".join("".join(self._current_title_parts).split()).strip()
            href = (self._current_href or "").strip()
            if title and href:
                self.results.append({"title": title, "url": href, "snippet": ""})
            self._current_href = None
            self._current_title_parts = []
            return
        if tag == "td" and self._in_snippet:
            self._in_snippet = False
            snippet = " ".join("".join(self._current_snippet_parts).split()).strip()
            if snippet and self.results:
                last = self.results[-1]
                if not last.get("snippet"):
                    last["snippet"] = snippet
            self._current_snippet_parts = []
            return

    def handle_data(self, data: str) -> None:
        if self._in_link:
            self._current_title_parts.append(data)
            return
        if self._in_snippet:
            self._current_snippet_parts.append(data)
            return


def _search_web_ddg_lite(query: str, env: dict[str, str]) -> list[Dict[str, Any]]:
    timeout_sec = _search_timeout_sec(env)
    top_k = _top_k(env, "MAGPIE_WEB_TOP_K", default=5)
    base_url = str(env.get("MAGPIE_DDG_LITE_URL") or "https://lite.duckduckgo.com/lite/").strip()

    q = urllib.parse.urlencode({"q": query})
    url = f"{base_url}?{q}"
    html_text = _http_get_text(
        url,
        headers={"User-Agent": "magpie-cli/0.0.0"},
        timeout_sec=timeout_sec,
    )
    parser = _DdgLiteParser()
    parser.feed(html_text)
    raw = parser.results[:top_k]
    return [
        _build_web_item({"title": r["title"], "url": r["url"], "snippet": r.get("snippet") or "", "source": "ddg"}, i)
        for i, r in enumerate(raw)
    ]


def _search_reddit_public(query: str, env: dict[str, str]) -> list[Dict[str, Any]]:
    timeout_sec = _search_timeout_sec(env)
    top_k = _top_k(env, "MAGPIE_REDDIT_TOP_K", default=5)

    params = urllib.parse.urlencode({"q": query, "limit": str(top_k), "sort": "relevance", "t": "all"})
    url = f"https://www.reddit.com/search.json?{params}"
    text = _http_get_text(
        url,
        headers={"User-Agent": "magpie-cli/0.0.0"},
        timeout_sec=timeout_sec,
    )
    payload = json.loads(text)
    children = payload.get("data", {}).get("children", [])
    if not isinstance(children, list):
        return []

    results: list[Dict[str, Any]] = []
    for child in children:
        if not isinstance(child, dict):
            continue
        data = child.get("data")
        if not isinstance(data, dict):
            continue
        title = str(data.get("title") or "").strip()
        permalink = str(data.get("permalink") or "").strip()
        subreddit = str(data.get("subreddit_name_prefixed") or "").strip()
        author = str(data.get("author") or "").strip()
        selftext = str(data.get("selftext") or "").strip()
        url_full = f"https://www.reddit.com{permalink}" if permalink.startswith("/") else str(data.get("url") or "")
        snippet = selftext or f"{subreddit} by u/{author}".strip()

        if not title or not url_full:
            continue
        results.append(
            _build_reddit_item(
                {
                    "title": title,
                    "url": url_full,
                    "snippet": snippet,
                    "source": "reddit",
                    "metadata": {"subreddit": subreddit, "author": author},
                },
                len(results),
            )
        )
        if len(results) >= top_k:
            break

    return results


def _call_graphrag_mcp(query: str, env: dict[str, str]) -> tuple[list[Dict[str, Any]], Optional[str]]:
    cmd = str(env.get("MAGPIE_GRAPHRAG_MCP_CMD") or "").strip()
    if not cmd:
        return [], "graphrag MCP is not configured (MAGPIE_GRAPHRAG_MCP_CMD is empty)"

    timeout_sec = _safe_float(str(env.get("MAGPIE_MCP_TIMEOUT_SEC") or "8"), 8.0)
    top_k = _safe_int(str(env.get("MAGPIE_GRAPHRAG_TOP_K") or "5"), 5)

    initialize_req = {
        "jsonrpc": "2.0",
        "id": "init-1",
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "magpie-cli", "version": "0.0.0"},
        },
    }
    initialized_noti = {
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
        "params": {},
    }
    call_req = {
        "jsonrpc": "2.0",
        "id": "call-1",
        "method": "tools/call",
        "params": {
            "name": "graphrag_search",
            "arguments": {"query": query, "top_k": top_k},
        },
    }
    payload = (
        json.dumps(initialize_req, ensure_ascii=False)
        + "\n"
        + json.dumps(initialized_noti, ensure_ascii=False)
        + "\n"
        + json.dumps(call_req, ensure_ascii=False)
        + "\n"
    )

    proc = subprocess.Popen(
        cmd,
        shell=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    try:
        stdout_text, stderr_text = proc.communicate(payload, timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return [], f"graphrag MCP timed out after {timeout_sec:.1f}s"

    if proc.returncode not in (0, None):
        err = stderr_text.strip()
        return [], f"graphrag MCP exited with code {proc.returncode}: {err or 'no stderr'}"

    responses: list[Dict[str, Any]] = []
    for line in stdout_text.splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            msg = json.loads(text)
        except Exception:
            continue
        if isinstance(msg, dict):
            responses.append(msg)

    call_res = next((x for x in responses if x.get("id") == "call-1"), None)
    if not isinstance(call_res, dict):
        return [], "graphrag MCP did not return tools/call response"

    if isinstance(call_res.get("error"), dict):
        return [], f"graphrag_search failed: {call_res['error'].get('message', 'unknown error')}"

    result = call_res.get("result")
    if not isinstance(result, dict):
        return [], "graphrag_search returned invalid result payload"

    raw_items = _extract_graphrag_results(result)
    items = [_build_rag_item(raw, i) for i, raw in enumerate(raw_items)]

    if stderr_text.strip():
        return items, f"stderr: {stderr_text.strip()}"
    return items, None


def run(stdin: io.TextIOBase, stdout: io.TextIOBase, env: dict[str, str]) -> int:
    session_id = env.get("MAGPIE_SESSION_ID", "unknown")
    fixtures = env.get("MAGPIE_USE_FIXTURES") == "1"
    graphrag_cmd = str(env.get("MAGPIE_GRAPHRAG_MCP_CMD") or "").strip()
    reddit_provider = _reddit_provider(env)
    web_provider = _websearch_provider(env)

    _log(stdout, session_id, "info", "backend booted")

    for raw in stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception as e:  # noqa: BLE001
            _log(stdout, session_id, "warn", f"failed to parse JSON: {e} :: {line[:200]}")
            continue

        session_id = str(msg.get("session_id") or session_id)
        mtype = msg.get("type")
        request_id = msg.get("request_id")

        if mtype == "hello":
            _send(
                stdout,
                {
                    "type": "hello_ack",
                    "session_id": session_id,
                    "in_reply_to": request_id,
                    "protocol_version": 1,
                    "capabilities": {
                        "mcp_graphrag": fixtures or bool(graphrag_cmd),
                        "web_search": fixtures or web_provider != "none",
                        "reddit_search": fixtures or reddit_provider != "none",
                        "fixtures": fixtures,
                    },
                }
            )
            _log(stdout, session_id, "info", "hello_ack sent", in_reply_to=request_id)
            continue

        if mtype == "cancel":
            _log(stdout, session_id, "info", "cancel received", in_reply_to=request_id)
            _send(
                stdout,
                {
                    "type": "done",
                    "session_id": session_id,
                    "in_reply_to": request_id,
                    "ok": True,
                    "canceled": True,
                }
            )
            _send(
                stdout,
                {"type": "phase", "session_id": session_id, "name": "idle", "in_reply_to": request_id},
            )
            continue

        if mtype == "start":
            query = str(msg.get("query") or "")
            _send(
                stdout,
                {"type": "phase", "session_id": session_id, "name": "rag", "in_reply_to": request_id},
            )
            _log(stdout, session_id, "info", f"received query: {query}", in_reply_to=request_id)
            rag_items: list[Dict[str, Any]] = []
            if fixtures:
                rag_items = _fixture_rag_items(query)
                _log(stdout, session_id, "info", "rag from fixtures", in_reply_to=request_id)
            else:
                rag_items, warn = _call_graphrag_mcp(query, env)
                if warn:
                    _log(stdout, session_id, "warn", warn, in_reply_to=request_id)
                else:
                    _log(
                        stdout,
                        session_id,
                        "info",
                        f"graphrag_search returned {len(rag_items)} item(s)",
                        in_reply_to=request_id,
                    )

            _send(
                stdout,
                {
                    "type": "items",
                    "session_id": session_id,
                    "group": "rag",
                    "items": rag_items,
                    "in_reply_to": request_id,
                },
            )

            _send(
                stdout,
                {"type": "phase", "session_id": session_id, "name": "search", "in_reply_to": request_id},
            )
            _log(stdout, session_id, "info", f"search query: {query}", in_reply_to=request_id)

            if fixtures:
                web_items = _fixture_web_items(query)
                reddit_items = _fixture_reddit_items(query)
                _send(
                    stdout,
                    {
                        "type": "items",
                        "session_id": session_id,
                        "group": "web",
                        "items": web_items,
                        "in_reply_to": request_id,
                    },
                )
                _send(
                    stdout,
                    {
                        "type": "items",
                        "session_id": session_id,
                        "group": "reddit",
                        "items": reddit_items,
                        "in_reply_to": request_id,
                    },
                )
            else:
                if web_provider == "ddg":
                    try:
                        web_items = _search_web_ddg_lite(query, env)
                        _send(
                            stdout,
                            {
                                "type": "items",
                                "session_id": session_id,
                                "group": "web",
                                "items": web_items,
                                "in_reply_to": request_id,
                            },
                        )
                    except Exception as e:  # noqa: BLE001
                        _log(stdout, session_id, "warn", f"web search failed: {e}", in_reply_to=request_id)
                        _send(
                            stdout,
                            {
                                "type": "items",
                                "session_id": session_id,
                                "group": "web",
                                "items": [],
                                "in_reply_to": request_id,
                            },
                        )
                elif web_provider != "none":
                    _log(stdout, session_id, "warn", f"unknown web provider: {web_provider}", in_reply_to=request_id)
                    _send(
                        stdout,
                        {
                            "type": "items",
                            "session_id": session_id,
                            "group": "web",
                            "items": [],
                            "in_reply_to": request_id,
                        },
                    )

                if reddit_provider == "public":
                    try:
                        reddit_items = _search_reddit_public(query, env)
                        _send(
                            stdout,
                            {
                                "type": "items",
                                "session_id": session_id,
                                "group": "reddit",
                                "items": reddit_items,
                                "in_reply_to": request_id,
                            },
                        )
                    except Exception as e:  # noqa: BLE001
                        _log(stdout, session_id, "warn", f"reddit search failed: {e}", in_reply_to=request_id)
                        _send(
                            stdout,
                            {
                                "type": "items",
                                "session_id": session_id,
                                "group": "reddit",
                                "items": [],
                                "in_reply_to": request_id,
                            },
                        )
                elif reddit_provider != "none":
                    _log(stdout, session_id, "warn", f"unknown reddit provider: {reddit_provider}", in_reply_to=request_id)
                    _send(
                        stdout,
                        {
                            "type": "items",
                            "session_id": session_id,
                            "group": "reddit",
                            "items": [],
                            "in_reply_to": request_id,
                        },
                    )

            _send(
                stdout,
                {
                    "type": "done",
                    "session_id": session_id,
                    "in_reply_to": request_id,
                    "ok": True,
                    "canceled": False,
                }
            )
            _send(
                stdout,
                {"type": "phase", "session_id": session_id, "name": "idle", "in_reply_to": request_id},
            )
            continue

        _log(stdout, session_id, "warn", f"unknown message type: {mtype}", in_reply_to=request_id)

    _log(stdout, session_id, "info", "stdin closed; exiting")
    return 0


def main() -> int:
    return run(sys.stdin, sys.stdout, dict(os.environ))


if __name__ == "__main__":
    raise SystemExit(main())
