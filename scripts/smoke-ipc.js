#!/usr/bin/env node

import { spawn } from "node:child_process";
import process from "node:process";

function send(child, obj) {
  child.stdin.write(`${JSON.stringify(obj)}\n`);
}

async function main() {
  const child = spawn("python3", ["-m", "magpie_backend"], {
    stdio: ["pipe", "pipe", "inherit"],
    env: {
      ...process.env,
      MAGPIE_USE_FIXTURES: "1",
    },
  });

  let buffer = "";
  const messages = [];

  child.stdout.setEncoding("utf8");
  child.stdout.on("data", (chunk) => {
    buffer += chunk;
    while (true) {
      const idx = buffer.indexOf("\n");
      if (idx < 0) break;
      const line = buffer.slice(0, idx).trim();
      buffer = buffer.slice(idx + 1);
      if (!line) continue;
      messages.push(JSON.parse(line));
    }
  });

  const sessionId = "smoke-session";

  send(child, {
    type: "hello",
    session_id: sessionId,
    request_id: "r-hello",
    protocol_version: 1,
    workspace_root: process.cwd(),
    permission: "ro",
  });
  send(child, {
    type: "start",
    session_id: sessionId,
    request_id: "r-start",
    query: "smoke test",
    workspace_root: process.cwd(),
    permission: "ro",
  });

  const deadline = Date.now() + 3000;
  while (Date.now() < deadline) {
    const hasAck = messages.some((m) => m.type === "hello_ack");
    const hasDone = messages.some(
      (m) => m.type === "done" && m.in_reply_to === "r-start"
    );
    const hasItems = messages.some(
      (m) => m.type === "items" && m.group === "rag" && m.in_reply_to === "r-start"
    );
    if (hasAck && hasItems && hasDone) {
      child.kill("SIGTERM");
      // eslint-disable-next-line no-console
      console.log("[smoke:ipc] ok");
      return;
    }
    // eslint-disable-next-line no-await-in-loop
    await new Promise((r) => setTimeout(r, 25));
  }

  child.kill("SIGTERM");
  // eslint-disable-next-line no-console
  console.error("[smoke:ipc] timeout; messages:");
  // eslint-disable-next-line no-console
  console.error(JSON.stringify(messages, null, 2));
  process.exit(1);
}

main().catch((err) => {
  // eslint-disable-next-line no-console
  console.error(String(err && err.stack ? err.stack : err));
  process.exit(1);
});
