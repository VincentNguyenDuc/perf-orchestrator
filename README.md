# perf-orchestrator

Process lifecycle manager with Linux `perf` attachment.

Manages subprocess start/stop and attaches `perf` capabilities (`perf stat`,
`perf record`, etc.) to the process for the duration of its lifetime. Each
capability is configured independently and started/stopped with the process.
Multiple processes can be managed together as a `ProcessGroup`, started in
order and stopped in reverse.

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
