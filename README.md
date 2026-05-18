# perf-orchestrator

Orchestrate `Linux perf` for profiling any arbitrary process or a group of interacting processes.

## Install

```bash
pip install -e .          # basic install
pip install -e ".[dev]"   # include black + ruff
```

## Development

```bash
make format         # black src/
make format-check   # black --check src/ (CI)
make lint           # ruff check src/
```
