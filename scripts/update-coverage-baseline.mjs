import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

function runCapture(cmd, args) {
  const res = spawnSync(cmd, args, { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
  if (res.status !== 0) {
    throw new Error(
      `${cmd} ${args.join(" ")} failed (code ${res.status})\n${res.stdout}\n${res.stderr}`
    );
  }
  return { stdout: res.stdout, stderr: res.stderr };
}

function parseNodeLineCoverage(output) {
  const lines = output.split("\n");

  const cleaned = (line) =>
    line
      .trim()
      // Node test runner prefixes many lines with "ℹ ".
      .replace(/^ℹ\s+/, "")
      .trim();

  // Prefer parsing via the table header so we stay compatible if columns move.
  // Current Node output:
  // file | line % | branch % | funcs % | uncovered lines
  let lineColumnIndex = null;
  for (const line of lines) {
    const t = cleaned(line);
    if (!t || !t.includes("|")) continue;
    const parts = t.split("|").map((p) => p.trim());
    if (parts.length < 2) continue;
    if (parts[0]?.toLowerCase() !== "file") continue;
    const idx = parts.findIndex((p) => p.toLowerCase().startsWith("line"));
    if (idx > 0) {
      lineColumnIndex = idx;
      break;
    }
  }

  for (const line of lines) {
    const t = cleaned(line);
    if (!t || !t.includes("|")) continue;

    const parts = t.split("|").map((p) => p.trim());
    if (parts.length < 2) continue;
    if (parts[0]?.toLowerCase() !== "all files") continue;

    if (lineColumnIndex != null && parts[lineColumnIndex] != null) {
      const percent = Number(parts[lineColumnIndex]);
      if (!Number.isNaN(percent)) return percent;
    }

    // Fallback: grab the first numeric column after "all files".
    for (let i = 1; i < parts.length; i++) {
      const n = Number(parts[i]);
      if (!Number.isNaN(n)) return n;
    }
  }

  throw new Error(
    "Failed to parse Node line coverage from output (expected a coverage table with an 'all files' row)"
  );
}

function readPythonLineCoverage() {
  const { stdout } = runCapture("python3", ["scripts/py_coverage.py", "--json"]);
  const obj = JSON.parse(stdout);
  const lines = Number(obj?.lines);
  if (!Number.isFinite(lines)) {
    throw new Error(`Invalid python coverage json: ${stdout}`);
  }
  return lines;
}

function main() {
  const node = runCapture("node", [
    "--import",
    "tsx",
    "--test",
    "--experimental-test-coverage",
    "--test-coverage-include=src/ipc/**",
    "--test-coverage-exclude=test/**",
  ]);

  const nodeLines = parseNodeLineCoverage(node.stdout + "\n" + node.stderr);
  const pyLines = readPythonLineCoverage();

  const baseline = {
    node: { lines: nodeLines },
    python: { lines: pyLines },
  };

  const outPath = path.join(process.cwd(), "coverage-baseline.json");
  fs.writeFileSync(outPath, `${JSON.stringify(baseline, null, 2)}\n`, "utf8");
  // eslint-disable-next-line no-console
  console.log(`[coverage] baseline updated: node.lines=${nodeLines.toFixed(2)} python.lines=${pyLines.toFixed(2)}`);
}

main();
