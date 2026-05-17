import re
import signal
import subprocess
import sys
from pathlib import Path

_PERF_EVENTS = ",".join([
    "cache-references",
    "cache-misses",
    "instructions",
    "cycles",
    "branch-misses",
    "branch-instructions",
    "L1-dcache-load-misses",
    "dTLB-load-misses",
])

_STAT_LINE_RE = re.compile(
    r"^\s+([\d,]+)\s+([a-zA-Z0-9_\-]+)(?::[a-zA-Z]+)?"
)


class PerfStat:
    """Attaches `perf stat` to a PID and collects hardware counters.

    Requires CAP_PERFMON (Linux 5.8+), CAP_SYS_ADMIN, or
    kernel.perf_event_paranoid <= 1.
    """

    def __init__(self, pid: int) -> None:
        self._pid = pid
        self._proc: subprocess.Popen | None = None

    def start(self) -> None:
        try:
            self._proc = subprocess.Popen(
                ["perf", "stat", "-p", str(self._pid), "-e", _PERF_EVENTS],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError:
            print("warning: perf not found — skipping hardware counters", file=sys.stderr)

    def stop(self) -> dict:
        if self._proc is None:
            return {}
        self._proc.send_signal(signal.SIGINT)
        try:
            _, stderr = self._proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            _, stderr = self._proc.communicate()
        return _parse_perf_stat(stderr.decode(errors="replace"))


class PerfRecord:
    """Records call stacks for a PID via `perf record`.

    Produces a perf.data file that can be used to generate a hot-path
    report and a flamegraph SVG.

    Requires CAP_PERFMON (Linux 5.8+), CAP_SYS_ADMIN, or
    kernel.perf_event_paranoid <= 1.
    """

    def __init__(
        self,
        pid: int,
        output: Path,
        *,
        event: str = "cpu-clock",
        freq: int = 99,
        call_graph: str = "dwarf",
    ) -> None:
        self._pid = pid
        self._output = output
        self._event = event
        self._freq = freq
        self._call_graph = call_graph
        self._proc: subprocess.Popen | None = None

    def start(self) -> None:
        try:
            self._proc = subprocess.Popen(
                [
                    "perf", "record",
                    "-p", str(self._pid),
                    "-e", self._event,
                    "--call-graph", self._call_graph,
                    "-F", str(self._freq),
                    "-o", str(self._output),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError:
            print("warning: perf not found — skipping perf record", file=sys.stderr)

    def stop(self) -> str:
        """Send SIGINT to stop recording. Returns stderr (useful for diagnostics)."""
        if self._proc is None:
            return ""
        try:
            self._proc.send_signal(signal.SIGINT)
        except ProcessLookupError:
            return ""
        try:
            self._proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait()
        return self._proc.stderr.read().decode(errors="replace").strip()

    def report(self) -> str:
        """Return a hot-path text report from the recorded perf.data."""
        if not self._output.exists() or self._output.stat().st_size == 0:
            return "(perf.data missing or empty — perf record may have failed)"
        r = subprocess.run(
            ["perf", "report", "-i", str(self._output), "--stdio", "--no-children", "-g", "none"],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            return f"(perf report failed)\n{r.stderr.strip()}"
        lines = [l for l in r.stdout.splitlines() if l and not l.startswith("#")]
        return "\n".join(lines) or f"(no samples)\n{r.stderr.strip()}"

    def flamegraph(self, collapse_script: Path, render_script: Path) -> bytes | None:
        """Generate a flamegraph SVG from the recorded perf.data.

        Returns the SVG bytes, or None if scripts are missing or rendering fails.
        collapse_script and render_script are paths to the FlameGraph perl scripts.
        """
        if not (collapse_script.is_file() and render_script.is_file()):
            print("warning: FlameGraph scripts not found, skipping flamegraph", file=sys.stderr)
            return None
        script  = subprocess.run(["perf", "script", "-i", str(self._output)], capture_output=True)
        folded  = subprocess.run(["perl", str(collapse_script)], input=script.stdout, capture_output=True)
        rendered = subprocess.run(["perl", str(render_script)],  input=folded.stdout, capture_output=True)
        return rendered.stdout if rendered.returncode == 0 and rendered.stdout else None


def _parse_perf_stat(output: str) -> dict:
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
    instrs     = counters.get("instructions", 0)
    cycles     = counters.get("cycles", 0)
    br_miss    = counters.get("branch-misses", 0)
    br_total   = counters.get("branch-instructions", 0)

    derived: dict[str, float] = {}
    if cache_refs > 0:
        derived["cache_miss_rate_pct"] = round(cache_miss / cache_refs * 100, 2)
    if cycles > 0:
        derived["ipc"] = round(instrs / cycles, 3)
        derived["cpi"] = round(cycles / instrs, 3) if instrs else 0.0
    if br_total > 0:
        derived["branch_miss_rate_pct"] = round(br_miss / br_total * 100, 2)

    return {"counters": counters, "derived": derived}
