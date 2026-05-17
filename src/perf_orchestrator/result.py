class WorkerResult:
    __slots__ = ("latencies_ns", "op_counts", "errors")

    def __init__(self) -> None:
        self.latencies_ns: list[int] = []
        self.op_counts: dict[str, int] = {}
        self.errors: int = 0
