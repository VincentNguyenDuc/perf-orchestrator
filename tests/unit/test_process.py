"""Unit tests for Process."""

import signal
import subprocess
from unittest.mock import MagicMock, call, patch

import pytest

from perf_orchestrator import Process


def _mock_sys_proc(pid: int = 1234, returncode=None) -> MagicMock:
    """Fake subprocess.Popen instance."""
    proc = MagicMock()
    proc.pid = pid
    proc.returncode = returncode
    return proc


def _mock_perf(name: str = "mock_perf") -> MagicMock:
    """Fake Perf capability."""
    cap = MagicMock()
    cap.name = name
    cap.report.return_value = {"data": name}
    return cap


@pytest.fixture
def mock_popen():
    """Patch subprocess.Popen in process module; yield (popen_mock, proc_mock)."""
    sys_proc = _mock_sys_proc()
    with patch(
        "perf_orchestrator.process.subprocess.Popen", return_value=sys_proc
    ) as popen:
        yield popen, sys_proc


class TestProcessPid:
    def test_pid_before_start_raises(self):
        proc = Process(["sleep", "10"])
        with pytest.raises(RuntimeError, match="has not been started"):
            _ = proc.pid

    def test_pid_after_start(self, mock_popen):
        _, sys_proc = mock_popen
        sys_proc.pid = 5678
        proc = Process(["sleep", "10"])
        proc.start()
        assert proc.pid == 5678


class TestProcessStart:
    def test_spawns_subprocess(self, mock_popen):
        popen, _ = mock_popen
        Process(["sleep", "10"]).start()
        popen.assert_called_once()
        assert popen.call_args[0][0] == ["sleep", "10"]

    def test_name_defaults_to_first_cmd_element(self, mock_popen):
        proc = Process(["sleep", "10"]).start()
        assert proc.name == "sleep"

    def test_name_defaults_to_first_word_of_string_cmd(self, mock_popen):
        proc = Process("sleep 10").start()
        assert proc.name == "sleep"

    def test_custom_name(self, mock_popen):
        proc = Process(["sleep", "10"], name="my-server").start()
        assert proc.name == "my-server"

    def test_calls_ready_fn(self, mock_popen):
        ready = MagicMock()
        Process(["sleep", "10"], ready=ready).start()
        ready.assert_called_once()

    def test_ready_fn_called_before_perf(self, mock_popen):
        _, sys_proc = mock_popen
        call_order = []
        ready = MagicMock(side_effect=lambda: call_order.append("ready"))
        cap = _mock_perf()
        cap.start.side_effect = lambda pid: call_order.append("perf")
        Process(["sleep", "10"], perf=[cap], ready=ready).start()
        assert call_order == ["ready", "perf"]

    def test_attaches_perf_capabilities(self, mock_popen):
        _, sys_proc = mock_popen
        sys_proc.pid = 42
        cap1, cap2 = _mock_perf("p1"), _mock_perf("p2")
        Process(["sleep", "10"], perf=[cap1, cap2]).start()
        cap1.start.assert_called_once_with(42)
        cap2.start.assert_called_once_with(42)

    def test_perf_started_in_forward_order(self, mock_popen):
        order = []
        caps = []
        for name in ["a", "b", "c"]:
            cap = _mock_perf(name)
            cap.start.side_effect = lambda pid, n=name: order.append(n)
            caps.append(cap)
        Process(["sleep", "10"], perf=caps).start()
        assert order == ["a", "b", "c"]

    def test_returns_self(self, mock_popen):
        proc = Process(["sleep", "10"])
        assert proc.start() is proc


class TestProcessStop:
    def test_stops_perf_in_reverse_order(self, mock_popen):
        order = []
        caps = []
        for name in ["a", "b", "c"]:
            cap = _mock_perf(name)
            cap.stop.side_effect = lambda n=name: order.append(n)
            caps.append(cap)
        proc = Process(["sleep", "10"], perf=caps)
        proc.start()
        proc.stop()
        assert order == ["c", "b", "a"]

    def test_sends_sigterm_to_running_process(self, mock_popen):
        _, sys_proc = mock_popen
        sys_proc.returncode = None
        proc = Process(["sleep", "10"])
        proc.start()
        proc.stop()
        sys_proc.send_signal.assert_called_once_with(signal.SIGTERM)

    def test_waits_after_sigterm(self, mock_popen):
        _, sys_proc = mock_popen
        sys_proc.returncode = None
        proc = Process(["sleep", "10"])
        proc.start()
        proc.stop()
        sys_proc.wait.assert_called_once_with(timeout=5.0)

    def test_kills_on_wait_timeout(self, mock_popen):
        _, sys_proc = mock_popen
        sys_proc.returncode = None
        sys_proc.wait.side_effect = [subprocess.TimeoutExpired("sleep", 5), None]
        proc = Process(["sleep", "10"])
        proc.start()
        proc.stop()
        sys_proc.kill.assert_called_once()
        assert sys_proc.wait.call_count == 2

    def test_skips_signal_when_already_exited(self, mock_popen):
        _, sys_proc = mock_popen
        sys_proc.returncode = 0  # already exited
        proc = Process(["sleep", "10"])
        proc.start()
        proc.stop()
        sys_proc.send_signal.assert_not_called()

    def test_idempotent(self, mock_popen):
        _, sys_proc = mock_popen
        sys_proc.returncode = None
        proc = Process(["sleep", "10"])
        proc.start()
        proc.stop()
        proc.stop()
        sys_proc.send_signal.assert_called_once()

    def test_process_lookup_error_on_sigterm_is_graceful(self, mock_popen):
        _, sys_proc = mock_popen
        sys_proc.returncode = None
        sys_proc.send_signal.side_effect = ProcessLookupError
        proc = Process(["sleep", "10"])
        proc.start()
        proc.stop()


class TestProcessContextManager:
    def test_enter_returns_process(self, mock_popen):
        proc = Process(["sleep", "10"])
        with proc as p:
            assert p is proc

    def test_exit_calls_stop(self, mock_popen):
        _, sys_proc = mock_popen
        sys_proc.returncode = None
        with Process(["sleep", "10"]):
            pass
        sys_proc.send_signal.assert_called_once_with(signal.SIGTERM)


class TestProcessReport:
    def test_aggregates_perf_reports_by_name(self, mock_popen):
        cap1 = _mock_perf("perf_stat")
        cap2 = _mock_perf("perf_record")
        cap1.report.return_value = {"counters": {}}
        cap2.report.return_value = {"report": "hot path"}
        proc = Process(["sleep", "10"], perf=[cap1, cap2])
        proc.start()
        proc.stop()
        result = proc.report()
        assert result == {
            "perf_stat": {"counters": {}},
            "perf_record": {"report": "hot path"},
        }

    def test_empty_report_with_no_perf(self, mock_popen):
        proc = Process(["sleep", "10"])
        proc.start()
        proc.stop()
        assert proc.report() == {}

    def test_report_cached_after_stop(self, mock_popen):
        cap = _mock_perf()
        proc = Process(["sleep", "10"], perf=[cap])
        proc.start()
        proc.stop()
        proc.report()
        proc.report()
        assert cap.report.call_count == 1

    def test_report_not_cached_before_stop(self, mock_popen):
        cap = _mock_perf()
        proc = Process(["sleep", "10"], perf=[cap])
        proc.start()
        proc.report()
        proc.report()
        assert cap.report.call_count == 2
