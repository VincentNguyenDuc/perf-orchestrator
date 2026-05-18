import signal
import subprocess
from pathlib import Path
from typing import Callable

from .perf import PerfRecord, PerfStat

ReadyFn = Callable[[], None]


class Process:
    """A managed subprocess with optional perf capabilities.

    Can be used standalone as a context manager, or added to a ProcessGroup.

    Example::

        with po.Process(["./server", "8080"], perf_stat=True, perf_record=True,
                        ready=po.tcp_ready(8080)) as server:
            result = po.run(args, make_worker("localhost", 8080))

        report = server.report()
        svg = server.flamegraph(collapse, render)
    """

    def __init__(
        self,
        cmd: list[str] | str,
        *,
        name: str | None = None,
        perf_stat: bool = False,
        perf_record: bool = False,
        record_output: Path | None = None,
        ready: ReadyFn | None = None,
    ) -> None:
        self._cmd = cmd
        self.name = name or (cmd[0] if isinstance(cmd, list) else cmd.split()[0])
        self._want_stat = perf_stat
        self._want_record = perf_record
        self._record_output = record_output or Path(f"{self.name}.perf.data")
        self._ready = ready

        self._proc: subprocess.Popen | None = None
        self._stat: PerfStat | None = None
        self._record: PerfRecord | None = None
        self._stat_data: dict = {}
        self._record_stderr: str = ""

    @property
    def pid(self) -> int:
        if self._proc is None:
            raise RuntimeError(f"process '{self.name}' has not been started")
        return self._proc.pid

    def start(self) -> "Process":
        self._proc = subprocess.Popen(
            self._cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if self._ready:
            self._ready()
        if self._want_stat:
            self._stat = PerfStat(self._proc.pid)
            self._stat.start()
        if self._want_record:
            self._record = PerfRecord(self._proc.pid, self._record_output)
            self._record.start()
        return self

    def stop(self) -> None:
        # stop perf before the process so it can flush cleanly
        if self._stat:
            self._stat_data = self._stat.stop()
        if self._record:
            self._record_stderr = self._record.stop()
        if self._proc and self._proc.returncode is None:
            try:
                self._proc.send_signal(signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                self._proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()

    def report(self) -> dict:
        """Return a structured report of all collected perf data."""
        result: dict = {}
        if self._stat_data:
            result["perf_stat"] = self._stat_data
        if self._record:
            result["perf_record"] = {
                "report": self._record.report(),
                "stderr": self._record_stderr,
            }
        return result

    def flamegraph(self, collapse_script: Path, render_script: Path) -> bytes | None:
        """Generate a flamegraph SVG. Returns None if perf_record was not enabled."""
        if self._record:
            return self._record.flamegraph(collapse_script, render_script)
        return None

    def __enter__(self) -> "Process":
        self.start()
        return self

    def __exit__(self, *_) -> None:
        self.stop()


class ProcessGroup:
    """Manages a collection of processes as a unit.

    Processes are started in the order they are added and stopped in reverse
    order on exit. Each process can have independent perf capabilities.

    Example::

        with po.ProcessGroup() as group:
            db = group.add(["./db"], perf=True)
            server = group.add(["./server"], perf=True, ready=po.tcp_ready(8080))

            result = po.run(args, make_worker("localhost", 8080))
            reports = group.reports()
    """

    def __init__(self) -> None:
        self._processes: list[Process] = []

    def add(
        self,
        cmd: list[str] | str,
        *,
        name: str | None = None,
        perf: bool = False,
        perf_stat: bool = False,
        perf_record: bool = False,
        record_output: Path | None = None,
        ready: ReadyFn | None = None,
    ) -> Process:
        """Start a process and add it to the group. Returns the Process instance."""
        p = Process(
            cmd,
            name=name,
            perf_stat=perf or perf_stat,
            perf_record=perf or perf_record,
            record_output=record_output,
            ready=ready,
        )
        p.start()
        self._processes.append(p)
        return p

    def reports(self) -> dict[str, dict]:
        """Return {name: report_dict} for all processes in the group."""
        return {p.name: p.report() for p in self._processes}

    def stop(self) -> None:
        for p in reversed(self._processes):
            p.stop()

    def __enter__(self) -> "ProcessGroup":
        return self

    def __exit__(self, *_) -> None:
        self.stop()
