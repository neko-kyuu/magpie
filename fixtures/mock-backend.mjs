#!/usr/bin/env node

import process from "node:process";

function send(obj) {
  process.stdout.write(`${JSON.stringify(obj)}\n`);
}

function log(sessionId, level, message, inReplyTo) {
  const payload = { type: "log", session_id: sessionId, level, message };
  if (inReplyTo) payload.in_reply_to = inReplyTo;
  send(payload);
}

process.stderr.write("mock-backend: started\n");

let buffer = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => {
  buffer += chunk;
  while (true) {
    const idx = buffer.indexOf("\n");
    if (idx < 0) break;
    const line = buffer.slice(0, idx).trim();
    buffer = buffer.slice(idx + 1);
    if (!line) continue;

    let msg;
    try {
      msg = JSON.parse(line);
    } catch (err) {
      // Emit something backendClient can still handle.
      send({ type: "log", session_id: "mock", level: "warn", message: `invalid json: ${String(err)}` });
      continue;
    }

    const sessionId = String(msg.session_id || "mock");
    const requestId = msg.request_id ? String(msg.request_id) : undefined;

    if (msg.type === "hello") {
      if (process.env.MOCK_SEND_INVALID_JSON === "1") {
        process.stdout.write("{not json}\n");
      }
      send({
        type: "hello_ack",
        session_id: sessionId,
        in_reply_to: requestId,
        protocol_version: 1,
        capabilities: {
          mcp_graphrag: false,
          web_search: false,
          reddit_search: false,
          fixtures: true,
        },
      });
      log(sessionId, "info", "hello_ack sent", requestId);
      continue;
    }

    if (msg.type === "start") {
      send({ type: "phase", session_id: sessionId, name: "rag", in_reply_to: requestId });
      log(sessionId, "info", `received query: ${String(msg.query || "")}`, requestId);
      send({ type: "done", session_id: sessionId, in_reply_to: requestId, ok: true, canceled: false });
      send({ type: "phase", session_id: sessionId, name: "idle", in_reply_to: requestId });
      continue;
    }

    if (msg.type === "cancel") {
      log(sessionId, "info", "cancel received", requestId);
      send({ type: "done", session_id: sessionId, in_reply_to: requestId, ok: true, canceled: true });
      send({ type: "phase", session_id: sessionId, name: "idle", in_reply_to: requestId });
      continue;
    }

    log(sessionId, "warn", `unknown message type: ${String(msg.type)}`, requestId);
  }
});

process.stdin.on("end", () => {
  process.exit(0);
});

