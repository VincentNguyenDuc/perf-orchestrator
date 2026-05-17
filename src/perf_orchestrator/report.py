def print_result(r: dict) -> None:
    if r.get("label"):
        print(f"\n{'='*60}")
        print(f"  {r['label']}")
        print(f"{'='*60}")

    lat = r["latency_us"]
    print(f"connections : {r['connections']}")
    print(f"requests    : {r['total_ops']:,}  (errors: {r['errors']})")
    if r.get("op_counts"):
        mix = "  ".join(f"{op}={cnt:,}" for op, cnt in r["op_counts"].items())
        print(f"op mix      : {mix}")
    print(f"duration    : {r['duration_s']} s")
    print(f"throughput  : {r['throughput_ops_per_s']:,} ops/sec")
    print(
        f"latency us  : min={lat['min']}  p50={lat['p50']}  "
        f"p95={lat['p95']}  p99={lat['p99']}  "
        f"p999={lat['p999']}  max={lat['max']}"
    )
    if "perf" in r:
        _print_perf(r["perf"])


def _print_perf(p: dict) -> None:
    c = p.get("counters", {})
    d = p.get("derived", {})

    print()
    print("--- hardware counters (server process) ---")

    if not c:
        print("  (no data — perf may require CAP_PERFMON or perf_event_paranoid <= 1)")
        return

    rows = [
        ("cache-references",      "cache refs"),
        ("cache-misses",          "cache misses"),
        ("L1-dcache-load-misses", "L1d load misses"),
        ("dTLB-load-misses",      "dTLB load misses"),
        ("instructions",          "instructions"),
        ("cycles",                "cycles"),
        ("branch-instructions",   "branches"),
        ("branch-misses",         "branch misses"),
    ]
    for key, label in rows:
        val = c.get(key)
        if val is not None:
            print(f"  {label:<24}: {val:>16,}")

    if d:
        print()
        if "cache_miss_rate_pct" in d:
            print(f"  cache miss rate         : {d['cache_miss_rate_pct']}%")
        if "ipc" in d:
            print(f"  IPC                     : {d['ipc']}")
        if "cpi" in d:
            print(f"  CPI                     : {d['cpi']}")
        if "branch_miss_rate_pct" in d:
            print(f"  branch miss rate        : {d['branch_miss_rate_pct']}%")
