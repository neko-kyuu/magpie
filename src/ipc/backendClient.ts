import { EventEmitter } from "node:events";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import process from "node:process";

import { newId } from "./ids";
import { JsonlReader } from "./jsonl";
import type {
  ClientMessage,
  HelloAckMessage,
  Permission,
  ServerMessage,
} from "./protocol";

type BackendClientOptions = {
  workspaceRoot: string;
  permission: Permission;
};

function resolveBackendSpawn() {
  const cmd = process.env.MAGPIE_BACKEND_CMD;
  if (cmd && cmd.trim().length > 0) {
    return { command: cmd, args: [] as string[], shell: true as const };
  }

  const useUv = process.env.MAGPIE_USE_UV === "1";
  if (useUv) {
    return {
      command: "uv",
      args: ["run", "python3", "-m", "magpie_backend"],
      shell: false as const,
    };
  }

  return {
    command: "python3",
    args: ["-m", "magpie_backend"],
    shell: false as const,
  };
}

export class BackendClient extends EventEmitter {
  readonly sessionId = newId();
  private child: ChildProcessWithoutNullStreams | null = null;
  private permission: Permission;
  private workspaceRoot: string;
  private buffered: ServerMessage[] = [];

  constructor(opts: BackendClientOptions) {
    super();
    this.workspaceRoot = opts.workspaceRoot;
    this.permission = opts.permission;
  }

  async start() {
    if (this.child) return;

    const resolved = resolveBackendSpawn();
    const child = spawn(resolved.command, resolved.args, {
      shell: resolved.shell,
      stdio: ["pipe", "pipe", "pipe"],
      env: {
        ...process.env,
        MAGPIE_SESSION_ID: this.sessionId,
      },
    });
    this.child = child;

    child.stderr.setEncoding("utf8");
    child.stderr.on("data", (chunk: string) => {
      const text = chunk.trim();
      if (!text) return;
      this.pushMessage({
        type: "log",
        session_id: this.sessionId,
        level: "warn",
        message: `[backend stderr] ${text}`,
      } satisfies ServerMessage);
    });

    const reader = new JsonlReader<ServerMessage>(child.stdout);
    reader.on("message", (msg) => this.pushMessage(msg));
    reader.on("parse_error", ({ line, err }) => {
      this.pushMessage({
        type: "log",
        session_id: this.sessionId,
        level: "warn",
        message: `[ipc] failed to parse JSONL: ${String(err)} :: ${line}`,
      } satisfies ServerMessage);
    });
    reader.on("error", (err) => this.emit("error", err));

    child.on("exit", (code, signal) => {
      this.child = null;
      const reason = signal ? `signal ${signal}` : `code ${code ?? "null"}`;
      this.pushMessage({
        type: "log",
        session_id: this.sessionId,
        level: "warn",
        message: `[backend] exited (${reason})`,
      } satisfies ServerMessage);
    });

    await this.handshake();
  }

  stop() {
    if (!this.child) return;
    try {
      this.child.kill("SIGTERM");
    } catch {
      // ignore
    }
    this.child = null;
  }

  startQuery(query: string) {
    const requestId = newId();
    this.sendRaw({
      type: "start",
      session_id: this.sessionId,
      request_id: requestId,
      query,
      workspace_root: this.workspaceRoot,
      permission: this.permission,
    });
    return requestId;
  }

  cancel() {
    const requestId = newId();
    this.sendRaw({
      type: "cancel",
      session_id: this.sessionId,
      request_id: requestId,
    });
    return requestId;
  }

  setPermission(permission: Permission) {
    this.permission = permission;
    const requestId = newId();
    this.sendRaw({
      type: "set_permission",
      session_id: this.sessionId,
      request_id: requestId,
      permission,
    });
    return requestId;
  }

  private sendRaw(msg: ClientMessage) {
    if (!this.child) {
      throw new Error("backend is not running");
    }
    this.child.stdin.write(`${JSON.stringify(msg)}\n`);
  }

  private handshake() {
    return new Promise<void>((resolve, reject) => {
      const requestId = newId();

      const onMessage = (msg: ServerMessage) => {
        if (msg.type !== "hello_ack") return;
        const ack = msg as HelloAckMessage;
        if (ack.in_reply_to !== requestId) return;
        cleanup();
        resolve();
      };

      const onExit = () => {
        cleanup();
        reject(new Error("backend exited before hello_ack"));
      };

      const timeout = setTimeout(() => {
        cleanup();
        reject(new Error("timeout waiting for hello_ack"));
      }, 5000);

      const cleanup = () => {
        clearTimeout(timeout);
        this.off("message", onMessage);
        this.child?.off("exit", onExit);
      };

      this.on("message", onMessage);
      this.child?.once("exit", onExit);

      this.sendRaw({
        type: "hello",
        session_id: this.sessionId,
        request_id: requestId,
        protocol_version: 1,
        workspace_root: this.workspaceRoot,
        permission: this.permission,
      });
    });
  }

  consumeBufferedMessages() {
    const msgs = this.buffered;
    this.buffered = [];
    return msgs;
  }

  private pushMessage(msg: ServerMessage) {
    this.buffered.push(msg);
    if (this.buffered.length > 200) {
      this.buffered = this.buffered.slice(-200);
    }
    this.emit("message", msg);
  }
}
