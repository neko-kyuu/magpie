import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

function run(cmd, args, opts = {}) {
  const res = spawnSync(cmd, args, { stdio: "inherit", ...opts });
  if (res.status !== 0) {
    throw new Error(`${cmd} ${args.join(" ")} failed (code ${res.status})`);
  }
}

function runQuiet(cmd, args) {
  const res = spawnSync(cmd, args, { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
  if (res.status !== 0) return null;
  return (res.stdout || "").trim();
}

function listChangedFiles() {
  const changed = new Set();

  const diff = runQuiet("git", ["diff", "--name-only", "--diff-filter=AM"]);
  if (diff) diff.split("\n").filter(Boolean).forEach((f) => changed.add(f));

  const staged = runQuiet("git", ["diff", "--name-only", "--cached", "--diff-filter=AM"]);
  if (staged) staged.split("\n").filter(Boolean).forEach((f) => changed.add(f));

  const untracked = runQuiet("git", ["ls-files", "--others", "--exclude-standard"]);
  if (untracked) untracked.split("\n").filter(Boolean).forEach((f) => changed.add(f));

  return [...changed];
}

function loadBaseline() {
  const p = path.join(process.cwd(), "coverage-baseline.json");
  if (!fs.existsSync(p)) {
    return { node: { lines: 0 }, python: { lines: 0 } };
  }
  return JSON.parse(fs.readFileSync(p, "utf8"));
}

function main() {
  const baseline = loadBaseline();

  const changedFiles = listChangedFiles();
  const changedTs = changedFiles.filter(
    (f) =>
      (f.startsWith("src/ipc/") && (f.endsWith(".ts") || f.endsWith(".tsx"))) ||
      (f.startsWith("scripts/") && (f.endsWith(".ts") || f.endsWith(".tsx")))
  );
  const changedPy = changedFiles.filter(
    (f) =>
      f.startsWith("magpie_backend/") &&
      f.endsWith(".py") &&
      !f.startsWith("magpie_backend/tests/")
  );

  const changedMinLines = Number(process.env.MAGPIE_CHANGED_LINES ?? 80);
  const nodeBaselineLines = Number(process.env.MAGPIE_NODE_BASELINE_LINES ?? baseline?.node?.lines ?? 0);
  const pyBaselineLines = Number(process.env.MAGPIE_PY_BASELINE_LINES ?? baseline?.python?.lines ?? 0);

  run("npm", ["run", "typecheck"]);
  run("npm", ["run", "smoke:ipc"]);
  run("npm", ["run", "test"]);
  run("npm", ["run", "py:test"]);

  if (changedTs.length > 0) {
    const includeArgs = changedTs.map((f) => `--test-coverage-include=${f}`);
    run("node", [
      "--import",
      "tsx",
      "--test",
      "--experimental-test-coverage",
      "--test-coverage-exclude=test/**",
      `--test-coverage-lines=${changedMinLines}`,
      ...includeArgs,
    ]);
  }

  run("node", [
    "--import",
    "tsx",
    "--test",
    "--experimental-test-coverage",
    "--test-coverage-include=src/ipc/**",
    "--test-coverage-exclude=test/**",
    `--test-coverage-lines=${nodeBaselineLines}`,
  ]);

  if (changedPy.length > 0) {
    run("python3", [
      "scripts/py_coverage.py",
      "--min-lines",
      String(changedMinLines),
      "--files",
      ...changedPy,
    ]);
  }

  run("python3", [
    "scripts/py_coverage.py",
    "--min-lines",
    String(pyBaselineLines),
  ]);
}

main();
