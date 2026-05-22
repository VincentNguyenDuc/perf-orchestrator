"""Unit tests for PerfStat."""
import signal
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from perf_orchestrator.perf import _PERF_EVENTS, _STAT_INT_RE, _STAT_MSEC_RE, PerfStat

PERF_STAT_OUTPUT = """\
 Performance counter stats for process id '1234':

      1,234,567      cache-references
         12,345      cache-misses
     12,345,678      instructions
      6,789,012      cycles
         67,890      branch-misses
      1,234,567      branch-instructions
         12,345      L1-dcache-load-misses
          1,234      dTLB-load-misses

       1.234567 seconds time elapsed
"""


def _mock_proc(stderr: str = "") -> MagicMock:
    proc = MagicMock()
    proc.communicate.return_value = (None, stderr.encode())
    return proc


def _run_stat(output: str) -> PerfStat:
    """Helper: start + stop a PerfStat with faked perf output."""
    with patch("perf_orchestrator.perf.subprocess.Popen") as popen:
        popen.return_value = _mock_proc(output)
        stat = PerfStat()
        stat.start(pid=1)
        stat.stop()
    return stat


class TestPerfStatStart:
    def test_builds_correct_command(self):
        with patch("perf_orchestrator.perf.subprocess.Popen") as popen:
            popen.return_value = MagicMock()
            PerfStat().start(pid=1234)
        assert popen.call_args[0][0] == [
            "perf", "stat", "-p", "1234", "-e", ",".join(_PERF_EVENTS)
        ]

    def test_custom_events_forwarded(self):
        with patch("perf_orchestrator.perf.subprocess.Popen") as popen:
            popen.return_value = MagicMock()
            PerfStat(events=["cycles", "instructions"]).start(pid=42)
        cmd = popen.call_args[0][0]
        assert cmd[cmd.index("-e") + 1] == "cycles,instructions"

    def test_pid_passed_as_string(self):
        with patch("perf_orchestrator.perf.subprocess.Popen") as popen:
            popen.return_value = MagicMock()
            PerfStat().start(pid=9999)
        cmd = popen.call_args[0][0]
        assert cmd[cmd.index("-p") + 1] == "9999"

    def test_stderr_pipe_requested(self):
        with patch("perf_orchestrator.perf.subprocess.Popen") as popen:
            popen.return_value = MagicMock()
            PerfStat().start(pid=1)
        assert popen.call_args[1]["stderr"] == subprocess.PIPE

    def test_perf_not_found_is_graceful(self):
        with patch("perf_orchestrator.perf.subprocess.Popen", side_effect=FileNotFoundError):
            stat = PerfStat()
            stat.start(pid=1234)
        assert stat._proc is None


class TestPerfStatStop:
    def test_sends_sigint(self):
        with patch("perf_orchestrator.perf.subprocess.Popen") as popen:
            proc = _mock_proc()
            popen.return_value = proc
            stat = PerfStat()
            stat.start(pid=1234)
            stat.stop()
        proc.send_signal.assert_called_once_with(signal.SIGINT)

    def test_communicate_with_timeout(self):
        with patch("perf_orchestrator.perf.subprocess.Popen") as popen:
            proc = _mock_proc()
            popen.return_value = proc
            stat = PerfStat()
            stat.start(pid=1234)
            stat.stop()
        proc.communicate.assert_called_once_with(timeout=10)

    def test_kills_on_communicate_timeout(self):
        with patch("perf_orchestrator.perf.subprocess.Popen") as popen:
            proc = MagicMock()
            proc.communicate.side_effect = [
                subprocess.TimeoutExpired("perf", 10),
                (None, b""),
            ]
            popen.return_value = proc
            stat = PerfStat()
            stat.start(pid=1234)
            stat.stop()
        proc.kill.assert_called_once()
        assert proc.communicate.call_count == 2

    def test_noop_when_not_started(self):
        PerfStat().stop()

    def test_noop_when_perf_not_found(self):
        with patch("perf_orchestrator.perf.subprocess.Popen", side_effect=FileNotFoundError):
            stat = PerfStat()
            stat.start(pid=1)
        stat.stop()


class TestPerfStatReport:
    def test_empty_before_start(self):
        assert PerfStat().report() == {}

    def test_empty_when_perf_unavailable(self):
        with patch("perf_orchestrator.perf.subprocess.Popen", side_effect=FileNotFoundError):
            stat = PerfStat()
            stat.start(pid=1)
            stat.stop()
        assert stat.report() == {}

    def test_parses_all_counters(self):
        counters = _run_stat(PERF_STAT_OUTPUT).report()["counters"]
        assert counters["cache-references"] == 1_234_567
        assert counters["cache-misses"] == 12_345
        assert counters["instructions"] == 12_345_678
        assert counters["cycles"] == 6_789_012
        assert counters["branch-misses"] == 67_890
        assert counters["branch-instructions"] == 1_234_567
        assert counters["L1-dcache-load-misses"] == 12_345
        assert counters["dTLB-load-misses"] == 1_234

    def test_ipc(self):
        derived = _run_stat(PERF_STAT_OUTPUT).report()["derived"]
        assert derived["ipc"] == round(12_345_678 / 6_789_012, 3)

    def test_cpi(self):
        derived = _run_stat(PERF_STAT_OUTPUT).report()["derived"]
        assert derived["cpi"] == round(6_789_012 / 12_345_678, 3)

    def test_cache_miss_rate(self):
        derived = _run_stat(PERF_STAT_OUTPUT).report()["derived"]
        assert derived["cache_miss_rate_pct"] == round(12_345 / 1_234_567 * 100, 2)

    def test_branch_miss_rate(self):
        derived = _run_stat(PERF_STAT_OUTPUT).report()["derived"]
        assert derived["branch_miss_rate_pct"] == round(67_890 / 1_234_567 * 100, 2)

    def test_no_ipc_when_cycles_zero(self):
        output = "      1,000      instructions\n          0      cycles\n"
        derived = _run_stat(output).report().get("derived", {})
        assert "ipc" not in derived
        assert "cpi" not in derived

    def test_cpi_is_zero_when_instructions_zero(self):
        output = "          0      instructions\n      1,000      cycles\n"
        derived = _run_stat(output).report()["derived"]
        assert derived["cpi"] == 0.0

    def test_no_cache_miss_rate_when_refs_zero(self):
        output = "      1,000      cache-misses\n          0      cache-references\n"
        derived = _run_stat(output).report().get("derived", {})
        assert "cache_miss_rate_pct" not in derived

    def test_no_branch_miss_rate_when_total_zero(self):
        output = "      1,000      branch-misses\n          0      branch-instructions\n"
        derived = _run_stat(output).report().get("derived", {})
        assert "branch_miss_rate_pct" not in derived

    def test_empty_output_returns_empty_dict(self):
        assert _run_stat("").report() == {}

    def test_colon_suffix_stripped_from_event_name(self):
        output = "      1,000      cache-references:u\n"
        counters = _run_stat(output).report()["counters"]
        assert "cache-references" in counters
        assert "cache-references:u" not in counters

    def test_non_counter_lines_ignored(self):
        output = "Performance counter stats for process id '1':\n\n" + PERF_STAT_OUTPUT
        counters = _run_stat(output).report()["counters"]
        assert all(isinstance(v, int) for v in counters.values())

    def test_task_clock_parsed_as_float(self):
        output = "      1,234.56 msec task-clock:u              #    1.234 CPUs utilized\n"
        counters = _run_stat(output).report()["counters"]
        assert counters["task-clock"] == pytest.approx(1234.56)

    def test_elapsed_time_line_ignored(self):
        output = "       1.234567890 seconds time elapsed\n"
        assert _run_stat(output).report() == {}

    def test_software_events_in_defaults(self):
        assert "task-clock" in _PERF_EVENTS
        assert "page-faults" in _PERF_EVENTS
        assert "context-switches" in _PERF_EVENTS
