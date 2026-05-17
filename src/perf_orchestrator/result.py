class WorkerResult:
    __slots__ = ("timings_ns", "counts", "errors")

    def __init__(self) -> None:
        self.timings_ns: list[int] = []
        self.counts: dict[str, int] = {}
        self.errors: int = 0
