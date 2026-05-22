"""Unit tests for ProcessGroup."""

from unittest.mock import MagicMock, call, patch

import pytest

from perf_orchestrator import ProcessGroup


def _mock_sys_proc(pid: int = 1, returncode=None) -> MagicMock:
    proc = MagicMock()
    proc.pid = pid
    proc.returncode = returncode
    return proc


class TestProcessGroupAdd:
    def test_add_starts_process_immediately(self):
        sys_proc = _mock_sys_proc()
        with patch("perf_orchestrator.process.subprocess.Popen", return_value=sys_proc):
            with ProcessGroup() as group:
                group.add(["sleep", "10"])
            sys_proc.send_signal.assert_called()

    def test_add_returns_process_instance(self):
        from perf_orchestrator import Process

        with patch(
            "perf_orchestrator.process.subprocess.Popen", return_value=_mock_sys_proc()
        ):
            with ProcessGroup() as group:
                result = group.add(["sleep", "10"])
        assert isinstance(result, Process)

    def test_add_forwards_name_kwarg(self):
        with patch(
            "perf_orchestrator.process.subprocess.Popen", return_value=_mock_sys_proc()
        ):
            with ProcessGroup() as group:
                p = group.add(["sleep", "10"], name="my-proc")
        assert p.name == "my-proc"

    def test_add_forwards_perf_kwarg(self):
        cap = MagicMock()
        cap.name = "mock"
        sys_proc = _mock_sys_proc(pid=42)
        with patch("perf_orchestrator.process.subprocess.Popen", return_value=sys_proc):
            with ProcessGroup() as group:
                group.add(["sleep", "10"], perf=[cap])
        cap.start.assert_called_once_with(42)


class TestProcessGroupStop:
    def test_stops_in_reverse_order(self):
        order = []
        sys_procs = [_mock_sys_proc(pid=i, returncode=None) for i in range(3)]
        for i, sp in enumerate(sys_procs):
            sp.send_signal.side_effect = lambda sig, idx=i: order.append(idx)

        procs_iter = iter(sys_procs)
        with patch(
            "perf_orchestrator.process.subprocess.Popen",
            side_effect=lambda *a, **kw: next(procs_iter),
        ):
            with ProcessGroup() as group:
                group.add(["sleep", "10"], name="p0")
                group.add(["sleep", "10"], name="p1")
                group.add(["sleep", "10"], name="p2")

        assert order == [2, 1, 0]

    def test_stop_on_empty_group(self):
        with ProcessGroup() as group:
            pass  # no processes added, must not raise


class TestProcessGroupReport:
    def test_keyed_by_process_name(self):
        cap1, cap2 = MagicMock(), MagicMock()
        cap1.name = "perf_stat"
        cap2.name = "perf_stat"
        cap1.report.return_value = {"x": 1}
        cap2.report.return_value = {"x": 2}

        sys_procs = [_mock_sys_proc(pid=i, returncode=None) for i in range(2)]
        procs_iter = iter(sys_procs)
        with patch(
            "perf_orchestrator.process.subprocess.Popen",
            side_effect=lambda *a, **kw: next(procs_iter),
        ):
            with ProcessGroup() as group:
                group.add(["sleep", "10"], name="server", perf=[cap1])
                group.add(["sleep", "10"], name="client", perf=[cap2])
                reports = group.report()

        assert "server" in reports
        assert "client" in reports
        assert reports["server"] == {"perf_stat": {"x": 1}}
        assert reports["client"] == {"perf_stat": {"x": 2}}

    def test_empty_group_returns_empty_dict(self):
        with ProcessGroup() as group:
            result = group.report()
        assert result == {}


class TestProcessGroupContextManager:
    def test_enter_returns_self(self):
        group = ProcessGroup()
        assert group.__enter__() is group
        group.__exit__(None, None, None)

    def test_exit_calls_stop(self):
        sys_proc = _mock_sys_proc(returncode=None)
        with patch("perf_orchestrator.process.subprocess.Popen", return_value=sys_proc):
            group = ProcessGroup()
            group.__enter__()
            group.add(["sleep", "10"])
            group.__exit__(None, None, None)
        sys_proc.send_signal.assert_called()
