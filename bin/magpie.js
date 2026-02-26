#!/usr/bin/env node

import path from "node:path";
import process from "node:process";
import { fileURLToPath, pathToFileURL } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

async function main() {
  const entry = path.join(__dirname, "..", "dist", "cli.js");
  try {
    await import(pathToFileURL(entry).href);
  } catch (err) {
    // eslint-disable-next-line no-console
    console.error("[magpie] Failed to start CLI.");
    // eslint-disable-next-line no-console
    console.error("[magpie] Build first with: npm run build");
    // eslint-disable-next-line no-console
    console.error("");
    // eslint-disable-next-line no-console
    console.error(String(err && err.stack ? err.stack : err));
    process.exitCode = 1;
  }
}

await main();
