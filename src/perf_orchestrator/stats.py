def percentile(sorted_ns: list[int], p: float) -> float:
    """Return the p-th percentile of sorted nanosecond latencies in microseconds."""
    if not sorted_ns:
        return 0.0
    idx = min(int(len(sorted_ns) * p / 100), len(sorted_ns) - 1)
    return sorted_ns[idx] / 1_000  # ns -> µs
