# magpie-cli (Demo)

目标（Demo）：Ink TUI 启动并拉起 Python 后端，通过 stdio JSONL 完成握手；输入查询后触发本地 RAG（MCP GraphRAG，可 fixtures 降级）与外搜（web + reddit），并在 UI 展示 items。M3 起支持可选的 agent：基于 RAG chunks 改写外搜 query（失败自动降级）。

## 开发运行

### 1) 安装 Node 依赖

```bash
npm install
```

### 2) 启动（dev）

开发模式使用 `node --import tsx` 直接运行 `src/cli.tsx`（不使用 `tsx` CLI）。

默认后端命令：`python3 -m magpie_backend`

```bash
npm run dev
```

如需用 `uv`：

```bash
MAGPIE_USE_UV=1 npm run dev
```

或自定义后端命令（任意可执行字符串，走 shell）：

```bash
MAGPIE_BACKEND_CMD="uv run python3 -m magpie_backend" npm run dev
```

### 2.5) 仅验证 IPC（不依赖 Ink/Node 依赖安装）

```bash
node scripts/smoke-ipc.js
```

### 2.6) GraphRAG MCP

本地 MCP GraphRAG server，可通过环境变量接入：

```bash
MAGPIE_GRAPHRAG_MCP_CMD="python3 /path/to/server.py --config /path/to/config.json" npm run dev
```

无网/无 MCP 时使用 fixtures：

```bash
MAGPIE_USE_FIXTURES=1 npm run dev
```

### 2.7)（M3）Agent：rewrite + judge loop

行为：
- 仅当 RAG 返回了 chunk（`rag_items.length > 0`）才会触发 rewrite
- rewrite 产出 **1 条** query，同时用于 web + reddit
- 每轮外搜结束后，只要 `attempt < max_attempts` 就会执行一次 judge（即使 web/reddit 为空）
- judge 若判定需要重搜，则给出下一轮 query 并进入下一轮 search（最多 `max_attempts` 轮）
- rewrite 失败（未配置 key / 网络错误 / 返回格式异常）会 `warn` 并回退为原始 `user_query`，外搜继续
- judge 失败会 `warn` 并降级为不重搜（`retry=no`）
- TUI 事件流会出现（示例）：
  - `Agent rewrite (1/2): "<q1>"`
  - `Search (1/2): web=<n> reddit=<n> (provider=...)`
  - `Agent judge (1/2): retry=yes|no (reason=...)`
- 列表区会追加显示多轮外搜结果；每条 item 会在 `[...]` 中追加 `attempt/max`（例如 `[web:1-a1 1/2]`）
- 状态列（底部）会显示 `SEARCH 1/2`（attempt/max）

OpenAI compatible 配置（环境变量）：
- `MAGPIE_OPENAI_API_KEY`（或 `OPENAI_API_KEY`）
- `MAGPIE_OPENAI_BASE_URL`（或 `OPENAI_BASE_URL`，默认 `https://api.openai.com/v1`）
- `MAGPIE_QUERY_REWRITE_MODEL`（可选；否则依次回退到 `MAGPIE_OPENAI_MODEL_QUERY_REWRITE` / `MAGPIE_OPENAI_MODEL` / `OPENAI_MODEL` / 默认 `gpt-5`）
- `MAGPIE_SEARCH_JUDGE_MODEL`（可选；否则依次回退到 `MAGPIE_OPENAI_MODEL_SEARCH_JUDGE` / `MAGPIE_OPENAI_MODEL` / `OPENAI_MODEL` / 默认 `gpt-5`）
- `MAGPIE_LLM_TIMEOUT_SEC`（可选，默认 12）
- `MAGPIE_AGENT_MAX_ATTEMPTS`（可选，默认 2；用于 agent loop 的最大迭代次数）

示例（在启用 MCP 的情况下）：

```bash
MAGPIE_OPENAI_API_KEY="..." MAGPIE_QUERY_REWRITE_MODEL="gpt-5" npm run dev:mcp
```

### 3) 构建并运行（bin）

```bash
npm run build
npm run start
```

## 参数

- `--root <path>`：指定 workspace root（默认 `process.cwd()`）
- `--read-only`：强制 RO
- `--allow-write`：设置 RW（v0 默认仍建议 RO）
