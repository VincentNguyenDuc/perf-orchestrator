import logging
import re
import signal
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

logger = logging.getLogger(__name__)


class Perf(ABC):
    """Abstract base class for perf capabilities attached to a Process.

    Subclasses implement a specific perf tool (stat, record, trace, …).
    Each capability is configured at construction time and attached to a
    PID at runtime via start(pid).
    """

    name: str

    @abstractmethod
    def start(self, pid: int) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def report(self) -> dict: ...


_PERF_EVENTS = ",".join(
    [
        "cache-references",
        "cache-misses",
        "instructions",
        "cycles",
        "branch-misses",
        "branch-instructions",
        "L1-dcache-load-misses",
        "dTLB-load-misses",
    ]
)

_STAT_LINE_RE = re.compile(r"^\s+([\d,]+)\s+([a-zA-Z0-9_\-]+)(?::[a-zA-Z]+)?")


class PerfStat(Perf):
    """Attaches `perf stat` to a PID and collects hardware counters.

    Requires CAP_PERFMON (Linux 5.8+), CAP_SYS_ADMIN, or
    kernel.perf_event_paranoid <= 1.

    Example::

        stat = po.PerfStat()
        stat = po.PerfStat(events="cycles,instructions")
    """

    name = "perf_stat"

    def __init__(self, *, events: str = _PERF_EVENTS) -> None:
        self._events = events
        self._proc: subprocess.Popen | None = None
        self._data: dict = {}

    def start(self, pid: int) -> None:
        logger.debug("attaching perf stat to pid %d", pid)
        try:
            self._proc = subprocess.Popen(
                ["perf", "stat", "-p", str(pid), "-e", self._events],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError:
            logger.warning("perf not found — hardware counters unavailable")

    def stop(self) -> None:
        if self._proc is None:
            return
        logger.debug("stopping perf stat")
        self._proc.send_signal(signal.SIGINT)
        try:
            _, stderr = self._proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            _, stderr = self._proc.communicate()
        self._data = self._parse_perf_stat(stderr.decode(errors="replace"))

    def report(self) -> dict:
        return self._data

    def _parse_perf_stat(self, output: str) -> dict:
        counters: dict[str, int] = {}
        for line in output.splitlines():
            m = _STAT_LINE_RE.match(line)
            if not m:
                continue
            raw_val, event = m.group(1), m.group(2)
            try:
                counters[event] = int(raw_val.replace(",", ""))
            except ValueError:
                pass

        if not counters:
            return {}

        cache_refs = counters.get("cache-references", 0)
        cache_miss = counters.get("cache-misses", 0)
        instrs = counters.get("instructions", 0)
        cycles = counters.get("cycles", 0)
        br_miss = counters.get("branch-misses", 0)
        br_total = counters.get("branch-instructions", 0)

        derived: dict[str, float] = {}
        if cache_refs > 0:
            derived["cache_miss_rate_pct"] = round(cache_miss / cache_refs * 100, 2)
        if cycles > 0:
            derived["ipc"] = round(instrs / cycles, 3)
            derived["cpi"] = round(cycles / instrs, 3) if instrs else 0.0
        if br_total > 0:
            derived["branch_miss_rate_pct"] = round(br_miss / br_total * 100, 2)

        return {"counters": counters, "derived": derived}


class PerfRecord(Perf):
    """Records call stacks for a PID via `perf record`.

    Produces a perf.data file for hot-path reports and flamegraph SVGs.

    Requires CAP_PERFMON (Linux 5.8+), CAP_SYS_ADMIN, or
    kernel.perf_event_paranoid <= 1.

    Example::

        record = po.PerfRecord(output / "perf.data")
        record = po.PerfRecord(output / "perf.data", freq=999, call_graph="fp")
    """

    name = "perf_record"

    def __init__(
        self,
        output: Path,
        *,
        event: str = "cpu-clock",
        freq: int = 99,
        call_graph: str = "dwarf",
    ) -> None:
        self._output = output
        self._event = event
        self._freq = freq
        self._call_graph = call_graph
        self._proc: subprocess.Popen | None = None
        self._stderr: str = ""
        self._report_cache: str | None = None

    def start(self, pid: int) -> None:
        logger.debug(
            "attaching perf record to pid %d (event=%s, freq=%d, output=%s)",
            pid, self._event, self._freq, self._output,
        )
        try:
            self._proc = subprocess.Popen(
                [
                    "perf", "record",
                    "-p", str(pid),
                    "-e", self._event,
                    "--call-graph", self._call_graph,
                    "-F", str(self._freq),
                    "-o", str(self._output),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError:
            logger.warning("perf not found — call-stack recording unavailable")

    def stop(self) -> None:
        if self._proc is None:
            return
        logger.debug("stopping perf record")
        try:
            self._proc.send_signal(signal.SIGINT)
        except ProcessLookupError:
            return
        try:
            self._proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait()
        if self._proc.stderr is not None:
            self._stderr = self._proc.stderr.read().decode(errors="replace").strip()
            if self._stderr:
                logger.debug("perf record stderr: %s", self._stderr)

    def report(self) -> dict:
        if self._report_cache is None:
            self._report_cache = self._run_report()
        return {"report": self._report_cache, "stderr": self._stderr}

    def _run_report(self) -> str:
        if not self._output.exists() or self._output.stat().st_size == 0:
            return "(perf.data missing or empty — perf record may have failed)"
        r = subprocess.run(
            [
                "perf", "report",
                "-i", str(self._output),
                "--stdio", "--no-children",
                "-g", "none",
            ],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            return f"(perf report failed)\n{r.stderr.strip()}"
        lines = [ln for ln in r.stdout.splitlines() if ln and not ln.startswith("#")]
        return "\n".join(lines) or f"(no samples)\n{r.stderr.strip()}"
