import asyncio
import time
from typing import Any, Callable, Coroutine

from .perf import PerfStat
from .result import WorkerResult
from .stats import percentile

WorkerFn = Callable[[int, int, WorkerResult], Coroutine[Any, Any, None]]


async def _gather(args: Any, worker_fn: WorkerFn, results: list[WorkerResult]) -> float:
    n_workers = args.workers
    tasks = [
        asyncio.create_task(worker_fn(
            args.requests // n_workers,
            args.warmup // n_workers,
            results[i],
        ))
        for i in range(n_workers)
    ]
    t_start = time.perf_counter()
    await asyncio.gather(*tasks)
    return time.perf_counter() - t_start


def run(args: Any, worker_fn: WorkerFn) -> dict:
    perf: PerfStat | None = None
    if getattr(args, "perf_pid", 0):
        perf = PerfStat(args.perf_pid)
        perf.start()

    n_workers = args.workers
    results = [WorkerResult() for _ in range(n_workers)]
    elapsed = asyncio.run(_gather(args, worker_fn, results))

    perf_data = perf.stop() if perf else None

    all_ns: list[int] = []
    op_counts: dict[str, int] = {}
    total_errors = 0
    for r in results:
        all_ns.extend(r.latencies_ns)
        for op, count in r.op_counts.items():
            op_counts[op] = op_counts.get(op, 0) + count
        total_errors += r.errors

    all_ns.sort()
    total_ops = sum(op_counts.values())

    result: dict = {
        "label": getattr(args, "label", ""),
        "workers": n_workers,
        "requests": args.requests,
        "duration_s": round(elapsed, 3),
        "total_ops": total_ops,
        "throughput_ops_per_s": round(total_ops / elapsed) if elapsed > 0 else 0,
        "errors": total_errors,
        "op_counts": op_counts,
        "latency_us": {
            "min":  round(percentile(all_ns,   0), 2),
            "p50":  round(percentile(all_ns,  50), 2),
            "p95":  round(percentile(all_ns,  95), 2),
            "p99":  round(percentile(all_ns,  99), 2),
            "p999": round(percentile(all_ns,  99.9), 2),
            "max":  round(percentile(all_ns, 100), 2),
        },
    }
    if perf_data:
        result["perf"] = perf_data
    return result
