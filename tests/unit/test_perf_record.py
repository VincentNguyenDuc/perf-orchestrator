"""Unit tests for PerfRecord."""
import signal
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from perf_orchestrator.perf import PerfRecord

PERF_REPORT_OUTPUT = """\
# To display the perf.data header info, please use --header/--header-only options.
#
# Samples: 1K of event 'cpu-clock'
# Event count (approx.): 10000000
#
# Overhead  Command  Shared Object  Symbol
# ........  .......  .............  ......
#
    50.00%  kvc      kvc            [.] handle_request
    30.00%  kvc      kvc            [.] hashmap_get
    20.00%  kvc      kvc            [.] parse_command
"""


def _mock_proc(stderr: bytes = b"") -> MagicMock:
    proc = MagicMock()
    proc.stderr = MagicMock()
    proc.stderr.read.return_value = stderr
    return proc


class TestPerfRecordStart:
    def test_builds_correct_command(self, tmp_path):
        output = tmp_path / "perf.data"
        with patch("perf_orchestrator.perf.subprocess.Popen") as popen:
            popen.return_value = _mock_proc()
            PerfRecord(output).start(pid=1234)
        cmd = popen.call_args[0][0]
        assert cmd == [
            "perf", "record",
            "-p", "1234",
            "-e", "cpu-clock",
            "--call-graph", "dwarf",
            "-F", "99",
            "-o", str(output),
        ]

    def test_custom_event(self, tmp_path):
        output = tmp_path / "perf.data"
        with patch("perf_orchestrator.perf.subprocess.Popen") as popen:
            popen.return_value = _mock_proc()
            PerfRecord(output, event="cycles").start(pid=1)
        cmd = popen.call_args[0][0]
        assert cmd[cmd.index("-e") + 1] == "cycles"

    def test_custom_freq(self, tmp_path):
        output = tmp_path / "perf.data"
        with patch("perf_orchestrator.perf.subprocess.Popen") as popen:
            popen.return_value = _mock_proc()
            PerfRecord(output, freq=999).start(pid=1)
        cmd = popen.call_args[0][0]
        assert cmd[cmd.index("-F") + 1] == "999"

    def test_custom_call_graph(self, tmp_path):
        output = tmp_path / "perf.data"
        with patch("perf_orchestrator.perf.subprocess.Popen") as popen:
            popen.return_value = _mock_proc()
            PerfRecord(output, call_graph="fp").start(pid=1)
        cmd = popen.call_args[0][0]
        assert cmd[cmd.index("--call-graph") + 1] == "fp"

    def test_stderr_pipe_requested(self, tmp_path):
        with patch("perf_orchestrator.perf.subprocess.Popen") as popen:
            popen.return_value = _mock_proc()
            PerfRecord(tmp_path / "perf.data").start(pid=1)
        assert popen.call_args[1]["stderr"] == subprocess.PIPE

    def test_perf_not_found_is_graceful(self, tmp_path):
        with patch("perf_orchestrator.perf.subprocess.Popen", side_effect=FileNotFoundError):
            rec = PerfRecord(tmp_path / "perf.data")
            rec.start(pid=1234)
        assert rec._proc is None


class TestPerfRecordStop:
    def test_sends_sigint(self, tmp_path):
        with patch("perf_orchestrator.perf.subprocess.Popen") as popen:
            proc = _mock_proc()
            popen.return_value = proc
            rec = PerfRecord(tmp_path / "perf.data")
            rec.start(pid=1234)
            rec.stop()
        proc.send_signal.assert_called_once_with(signal.SIGINT)

    def test_waits_with_timeout(self, tmp_path):
        with patch("perf_orchestrator.perf.subprocess.Popen") as popen:
            proc = _mock_proc()
            popen.return_value = proc
            rec = PerfRecord(tmp_path / "perf.data")
            rec.start(pid=1234)
            rec.stop()
        proc.wait.assert_called_once_with(timeout=10)

    def test_kills_on_wait_timeout(self, tmp_path):
        with patch("perf_orchestrator.perf.subprocess.Popen") as popen:
            proc = _mock_proc()
            proc.wait.side_effect = [subprocess.TimeoutExpired("perf", 10), None]
            popen.return_value = proc
            rec = PerfRecord(tmp_path / "perf.data")
            rec.start(pid=1234)
            rec.stop()
        proc.kill.assert_called_once()
        assert proc.wait.call_count == 2

    def test_process_lookup_error_on_sigint_is_graceful(self, tmp_path):
        with patch("perf_orchestrator.perf.subprocess.Popen") as popen:
            proc = _mock_proc()
            proc.send_signal.side_effect = ProcessLookupError
            popen.return_value = proc
            rec = PerfRecord(tmp_path / "perf.data")
            rec.start(pid=1234)
            rec.stop()
        proc.wait.assert_not_called()

    def test_reads_stderr_after_wait(self, tmp_path):
        with patch("perf_orchestrator.perf.subprocess.Popen") as popen:
            proc = _mock_proc(stderr=b"perf warning: some message")
            popen.return_value = proc
            rec = PerfRecord(tmp_path / "perf.data")
            rec.start(pid=1234)
            rec.stop()
        assert rec._stderr == "perf warning: some message"

    def test_noop_when_not_started(self, tmp_path):
        PerfRecord(tmp_path / "perf.data").stop()

    def test_noop_when_perf_not_found(self, tmp_path):
        with patch("perf_orchestrator.perf.subprocess.Popen", side_effect=FileNotFoundError):
            rec = PerfRecord(tmp_path / "perf.data")
            rec.start(pid=1)
        rec.stop()


class TestPerfRecordReport:
    def test_placeholder_when_perf_data_missing(self, tmp_path):
        rec = PerfRecord(tmp_path / "perf.data")
        result = rec.report()
        assert "missing or empty" in result["report"]

    def test_placeholder_when_perf_data_empty(self, tmp_path):
        perf_data = tmp_path / "perf.data"
        perf_data.write_bytes(b"")
        rec = PerfRecord(perf_data)
        result = rec.report()
        assert "missing or empty" in result["report"]

    def test_runs_perf_report_command(self, tmp_path):
        perf_data = tmp_path / "perf.data"
        perf_data.write_bytes(b"nonempty")
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = PERF_REPORT_OUTPUT
        mock_result.stderr = ""
        with patch("perf_orchestrator.perf.subprocess.run", return_value=mock_result) as run:
            rec = PerfRecord(perf_data)
            rec.report()
        cmd = run.call_args[0][0]
        assert cmd[:2] == ["perf", "report"]
        assert "-i" in cmd
        assert str(perf_data) in cmd
        assert "--stdio" in cmd

    def test_filters_comment_lines(self, tmp_path):
        perf_data = tmp_path / "perf.data"
        perf_data.write_bytes(b"nonempty")
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = PERF_REPORT_OUTPUT
        mock_result.stderr = ""
        with patch("perf_orchestrator.perf.subprocess.run", return_value=mock_result):
            result = PerfRecord(perf_data).report()["report"]
        assert not any(line.startswith("#") for line in result.splitlines())

    def test_no_samples_when_only_comments(self, tmp_path):
        perf_data = tmp_path / "perf.data"
        perf_data.write_bytes(b"nonempty")
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "# comment only\n# another comment\n"
        mock_result.stderr = ""
        with patch("perf_orchestrator.perf.subprocess.run", return_value=mock_result):
            result = PerfRecord(perf_data).report()["report"]
        assert result.startswith("(no samples)")

    def test_perf_report_failure(self, tmp_path):
        perf_data = tmp_path / "perf.data"
        perf_data.write_bytes(b"nonempty")
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "perf: error reading perf.data"
        with patch("perf_orchestrator.perf.subprocess.run", return_value=mock_result):
            result = PerfRecord(perf_data).report()["report"]
        assert result.startswith("(perf report failed)")

    def test_report_is_cached(self, tmp_path):
        perf_data = tmp_path / "perf.data"
        perf_data.write_bytes(b"nonempty")
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = PERF_REPORT_OUTPUT
        mock_result.stderr = ""
        with patch("perf_orchestrator.perf.subprocess.run", return_value=mock_result) as run:
            rec = PerfRecord(perf_data)
            rec.report()
            rec.report()
        assert run.call_count == 1

    def test_includes_stderr_in_result(self, tmp_path):
        with patch("perf_orchestrator.perf.subprocess.Popen") as popen:
            proc = _mock_proc(stderr=b"perf: some warning")
            popen.return_value = proc
            rec = PerfRecord(tmp_path / "perf.data")
            rec.start(pid=1)
            rec.stop()
        result = rec.report()
        assert result["stderr"] == "perf: some warning"

    def test_placeholder_when_perf_unavailable(self, tmp_path):
        with patch("perf_orchestrator.perf.subprocess.Popen", side_effect=FileNotFoundError):
            rec = PerfRecord(tmp_path / "perf.data")
            rec.start(pid=1)
            rec.stop()
        result = rec.report()
        assert "missing or empty" in result["report"]
        assert result["stderr"] == ""
