from __future__ import annotations

import argparse
import ast
import json
import os
import sys
import trace
import unittest
from pathlib import Path
from typing import Iterable


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _discover_tests() -> unittest.TestSuite:
    loader = unittest.TestLoader()
    root = _project_root()
    start_dir = root / "magpie_backend" / "tests"
    return loader.discover(
        start_dir=str(start_dir),
        pattern="test_*.py",
        top_level_dir=str(root),
    )


def _coverable_lines(py_file: Path) -> set[int]:
    source = py_file.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(py_file))

    lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.stmt):
            continue
        lineno = getattr(node, "lineno", None)
        if lineno is None:
            continue
        lines.add(int(lineno))

    return lines


def _measure(files: Iterable[Path]) -> dict:
    tracer = trace.Trace(count=True, trace=False)

    def _run() -> None:
        suite = _discover_tests()
        runner = unittest.TextTestRunner(stream=open(os.devnull, "w"), verbosity=0)
        result = runner.run(suite)
        if not result.wasSuccessful():
            raise SystemExit(1)

    tracer.runfunc(_run)
    results = tracer.results()
    counts = results.counts  # (filename, lineno) -> count

    per_file: dict[str, dict] = {}
    total_coverable = 0
    total_executed = 0

    for py_file in files:
        coverable = _coverable_lines(py_file)
        executed = {
            lineno
            for (fname, lineno), c in counts.items()
            if c > 0 and Path(fname).resolve() == py_file.resolve()
        }

        coverable_count = len(coverable)
        executed_count = len(coverable & executed)
        percent = 100.0 if coverable_count == 0 else (executed_count / coverable_count) * 100.0

        per_file[str(py_file)] = {
            "lines": percent,
            "coverable": coverable_count,
            "executed": executed_count,
        }
        total_coverable += coverable_count
        total_executed += executed_count

    total_percent = 100.0 if total_coverable == 0 else (total_executed / total_coverable) * 100.0
    return {"lines": total_percent, "files": per_file}


def _default_files() -> list[Path]:
    root = _project_root() / "magpie_backend"
    return sorted(p for p in root.rglob("*.py") if p.is_file() and "/tests/" not in str(p))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="output JSON only")
    ap.add_argument("--min-lines", type=float, default=None, help="minimum line coverage percent")
    ap.add_argument("--files", nargs="*", default=None, help="specific python files to evaluate")
    args = ap.parse_args()

    files = [Path(f) for f in args.files] if args.files else _default_files()
    summary = _measure(files)

    if args.json:
        sys.stdout.write(json.dumps({"lines": summary["lines"]}))
        return 0

    lines = float(summary["lines"])
    print(f"[py coverage] lines={lines:.2f}% (files={len(files)})")
    if args.min_lines is not None and lines + 1e-9 < float(args.min_lines):
        print(f"[py coverage] FAIL: lines {lines:.2f}% < min {float(args.min_lines):.2f}%")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
