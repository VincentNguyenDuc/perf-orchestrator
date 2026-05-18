# perf-orchestrator

General-purpose benchmark orchestrator with Linux `perf` integration.

Designed around two independent concerns:

1. **perf attachment** — attach `perf` capabilities to any running process by PID, 
   regardless of what that process is or how it was started.

2. **Load generation** — run concurrent async workers against whatever those 
   processes expose, collect timing samples, and produce a structured report.

These two concerns compose: you can profile one process, many interacting
processes, or none at all. The library does not assume a specific workload shape
(HTTP, TCP, file I/O, IPC) — all protocol and connection details live in the
caller's worker closure.

## Install

```bash
pip install -e .          # basic install
pip install -e ".[dev]"   # include black + ruff
```

Requires Python 3.11+. Linux `perf` is optional — the library degrades gracefully
if it is unavailable or lacks `CAP_PERFMON`.

## Development

```bash
make format         # black src/
make format-check   # black --check src/ (CI)
make lint           # ruff check src/
```

Requires the parent repo's `.venv` (`make init` from the kvc root).
Tool config lives in `pyproject.toml` under `[tool.black]` and `[tool.ruff]`.
