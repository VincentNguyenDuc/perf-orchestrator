import logging
import signal
import subprocess
from pathlib import Path
from typing import Any, Callable

from .perf import Perf

logger = logging.getLogger(__name__)

ReadyFn = Callable[[], None]


class Process:
    """A managed subprocess with optional perf capabilities.

    Pass perf capability instances to attach them to the process. Each
    capability controls its own parameters and is started/stopped with
    the process lifecycle.

    Example::

        with po.Process(
            ["./server", "8080"],
            perf=[po.PerfStat(), po.PerfRecord(output / "perf.data")],
            ready=my_ready_fn,
        ) as server:
            ...

        report = server.report()   # {"perf_stat": {...}, "perf_record": {...}}
    """

    def __init__(
        self,
        cmd: list[str] | str,
        *,
        name: str | None = None,
        perf: list[Perf] | None = None,
        ready: ReadyFn | None = None,
    ) -> None:
        self._cmd = cmd
        self.name = name or (cmd[0] if isinstance(cmd, list) else cmd.split()[0])
        self._perf = perf or []
        self._ready = ready

        self._proc: subprocess.Popen | None = None
        self._stopped: bool = False
        self._report_cache: dict | None = None

    @property
    def pid(self) -> int:
        if self._proc is None:
            raise RuntimeError(f"process '{self.name}' has not been started")
        return self._proc.pid

    def start(self) -> "Process":
        logger.info("starting '%s'", self.name)
        self._proc = subprocess.Popen(
            self._cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logger.debug("'%s' spawned with pid %d", self.name, self._proc.pid)
        if self._ready:
            logger.debug("waiting for '%s' to become ready", self.name)
            self._ready()
            logger.debug("'%s' is ready", self.name)
        for cap in self._perf:
            cap.start(self._proc.pid)
        return self

    def stop(self) -> None:
        if self._stopped:
            logger.debug("'%s' already stopped, skipping", self.name)
            return
        self._stopped = True
        logger.info("stopping '%s'", self.name)
        for cap in reversed(self._perf):
            cap.stop()
        if self._proc and self._proc.returncode is None:
            try:
                self._proc.send_signal(signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                self._proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                logger.warning(
                    "'%s' did not exit after SIGTERM, sending SIGKILL", self.name
                )
                self._proc.kill()
                self._proc.wait()
        exit_code = self._proc.returncode if self._proc else "n/a"
        logger.debug("'%s' stopped (exit code %s)", self.name, exit_code)

    def report(self) -> dict:
        """Return {capability.name: capability.report()} for all perf capabilities."""
        if self._report_cache is not None:
            return self._report_cache
        result = {cap.name: cap.report() for cap in self._perf}
        if self._stopped:
            self._report_cache = result
        return result

    def __enter__(self) -> "Process":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()


class ProcessGroup:
    """Manages a collection of processes as a unit.

    Processes are started in order and stopped in reverse order on exit.

    Example::

        with po.ProcessGroup() as group:
            db     = group.add(["./db"],     perf=[po.PerfStat()])
            server = group.add(["./server"], perf=[po.PerfStat(), po.PerfRecord(out)],
                               ready=my_ready_fn)
            ...
            reports    = group.report()
    """

    def __init__(self) -> None:
        self._processes: list[Process] = []

    def add(self, cmd: list[str] | str, **kwargs: Any) -> Process:
        """Start a process and add it to the group. Returns the Process instance.

        Accepts the same keyword arguments as Process.__init__.
        """
        p = Process(cmd, **kwargs)
        p.start()
        self._processes.append(p)
        return p

    def stop(self) -> None:
        for p in reversed(self._processes):
            p.stop()

    def report(self) -> dict[str, dict]:
        """Return {name: report_dict} for all processes in the group."""
        return {p.name: p.report() for p in self._processes}

    def __enter__(self) -> "ProcessGroup":
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()
