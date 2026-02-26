import fs from "node:fs";
import process from "node:process";

import React from "react";
import { render } from "ink";

import { BackendClient } from "./ipc/backendClient";
import { App } from "./ui/App";
import type { Permission } from "./ipc/protocol";

function parseArgs(argv: string[]) {
  const allowWrite = argv.includes("--allow-write");
  const readOnly = argv.includes("--read-only");
  const rootFlagIndex = argv.findIndex((a) => a === "--root");
  const rootFromFlag =
    rootFlagIndex >= 0 ? argv[rootFlagIndex + 1] : undefined;

  const permission: Permission = allowWrite ? "rw" : "ro";
  return { permission: readOnly ? "ro" : permission, rootFromFlag };
}

async function main() {
  const { permission, rootFromFlag } = parseArgs(process.argv.slice(2));
  const workspaceRoot = fs.realpathSync(rootFromFlag ?? process.cwd());

  const backend = new BackendClient({
    workspaceRoot,
    permission,
  });

  await backend.start();

  render(
    <App
      backend={backend}
      workspaceRoot={workspaceRoot}
      initialPermission={permission}
    />,
    { exitOnCtrlC: false }
  );

  const shutdown = () => {
    backend.stop();
  };
  process.on("exit", shutdown);
  process.on("SIGTERM", () => {
    shutdown();
    process.exit(143);
  });
}

main().catch((err) => {
  const message =
    err instanceof Error ? `${err.message}\n${err.stack ?? ""}` : String(err);
  // eslint-disable-next-line no-console
  console.error(message);
  process.exit(1);
});
