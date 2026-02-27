# magpie-cli (Demo)

M1 目标（最小子集）：Ink TUI 启动并拉起 Python 后端，通过 stdio JSONL 完成 `hello/hello_ack` 握手；输入查询后触发 `graphrag_search`（或 fixtures 降级），并在 UI 展示 RAG `items`。

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

### 3) 构建并运行（bin）

```bash
npm run build
npm run start
```

## 参数

- `--root <path>`：指定 workspace root（默认 `process.cwd()`）
- `--read-only`：强制 RO
- `--allow-write`：设置 RW（v0 默认仍建议 RO）
