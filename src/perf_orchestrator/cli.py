import argparse


def build_parser(**kwargs) -> argparse.ArgumentParser:
    """Return a base ArgumentParser with common benchmark flags.

    Callers add their own protocol-specific arguments on top:

        p = build_parser(description="my-bench")
        p.add_argument("--key-space", type=int, default=10_000)
        args = p.parse_args()
    """
    kwargs.setdefault("formatter_class", argparse.ArgumentDefaultsHelpFormatter)
    p = argparse.ArgumentParser(**kwargs)
    p.add_argument("--host",        default="127.0.0.1", help="server host")
    p.add_argument("--port",        type=int, default=8080, help="server port")
    p.add_argument("--requests",    type=int, default=100_000, help="total requests")
    p.add_argument("--connections", type=int, default=1, help="concurrent connections")
    p.add_argument("--warmup",      type=int, default=1_000, help="warmup requests (excluded from metrics)")
    p.add_argument("--label",       default="", help="label printed in the report")
    p.add_argument("--json",        action="store_true", help="output JSON instead of text")
    p.add_argument(
        "--perf-pid",
        type=int,
        default=0,
        metavar="PID",
        help="attach perf stat to this server PID for hardware counters",
    )
    return p
