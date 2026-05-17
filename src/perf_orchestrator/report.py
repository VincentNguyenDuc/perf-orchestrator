def print_result(r: dict) -> None:
    if r.get("label"):
        print(f"\n{'='*60}")
        print(f"  {r['label']}")
        print(f"{'='*60}")

    t = r["timing_us"]
    print(f"workers     : {r['workers']}")
    print(f"total       : {r['total']:,}  (errors: {r['errors']})")
    if r.get("counts"):
        mix = "  ".join(f"{label}={cnt:,}" for label, cnt in r["counts"].items())
        print(f"counts      : {mix}")
    print(f"duration    : {r['duration_s']} s")
    print(f"throughput  : {r['throughput_per_s']:,} /sec")
    print(
        f"timing us   : min={t['min']}  p50={t['p50']}  "
        f"p95={t['p95']}  p99={t['p99']}  "
        f"p999={t['p999']}  max={t['max']}"
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
        ("cache-references", "cache refs"),
        ("cache-misses", "cache misses"),
        ("L1-dcache-load-misses", "L1d load misses"),
        ("dTLB-load-misses", "dTLB load misses"),
        ("instructions", "instructions"),
        ("cycles", "cycles"),
        ("branch-instructions", "branches"),
        ("branch-misses", "branch misses"),
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
