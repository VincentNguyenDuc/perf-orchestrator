"""Integration tests for Process and ProcessGroup using real subprocesses.

These tests use real OS processes (sleep, python3) and do not require
Linux perf. They verify lifecycle, signaling, and ready-function behavior.
"""

import socket
import time

import pytest

from perf_orchestrator import Process, ProcessGroup


def _find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _tcp_ready(host: str, port: int, timeout: float = 5.0):
    def _check():
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                socket.create_connection((host, port), timeout=0.1).close()
                return
            except OSError:
                time.sleep(0.05)
        raise TimeoutError(f"no connection on {host}:{port} within {timeout}s")

    return _check


class TestProcessLifecycle:
    def test_starts_and_stops(self):
        proc = Process(["sleep", "10"])
        proc.start()
        assert proc.pid > 0
        assert proc._proc.returncode is None
        proc.stop()
        assert proc._proc.returncode is not None

    def test_context_manager(self):
        with Process(["sleep", "10"]) as proc:
            assert proc.pid > 0
        assert proc._proc.returncode is not None

    def test_pid_is_positive_integer(self):
        with Process(["sleep", "10"]) as proc:
            assert isinstance(proc.pid, int)
            assert proc.pid > 0

    def test_report_empty_without_perf(self):
        with Process(["sleep", "10"]) as proc:
            pass
        assert proc.report() == {}

    def test_process_exits_before_stop(self):
        """stop() must not raise when the process already exited."""
        proc = Process(["python3", "-c", ""])
        proc.start()
        proc._proc.wait()
        proc.stop()

    def test_stop_is_idempotent(self):
        proc = Process(["sleep", "10"])
        proc.start()
        proc.stop()
        proc.stop()

    def test_ready_fn_is_called(self):
        called = []

        def ready():
            called.append(True)

        with Process(["sleep", "10"], ready=ready):
            pass
        assert called == [True]

    def test_ready_fn_called_after_process_starts(self):
        """ready() must be called while the process is still running."""
        pid_at_ready = []

        def ready():
            pid_at_ready.append(proc._proc.pid)

        proc = Process(["sleep", "10"], ready=ready)
        proc.start()
        proc.stop()
        assert len(pid_at_ready) == 1
        assert pid_at_ready[0] > 0

    def test_ready_fn_with_tcp_server(self):
        """ready() blocks until the subprocess is accepting TCP connections."""
        port = _find_free_port()
        cmd = [
            "python3",
            "-c",
            (
                "import socket, time; s = socket.socket();"
                f" s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1);"
                f" s.bind(('127.0.0.1', {port})); s.listen(); time.sleep(10)"
            ),
        ]
        with Process(cmd, ready=_tcp_ready("127.0.0.1", port)) as proc:
            assert proc.pid > 0
            conn = socket.create_connection(("127.0.0.1", port), timeout=1)
            conn.close()

    def test_name_defaults_to_command(self):
        proc = Process(["sleep", "10"])
        assert proc.name == "sleep"

    def test_custom_name(self):
        proc = Process(["sleep", "10"], name="my-sleep")
        assert proc.name == "my-sleep"


class TestProcessGroupLifecycle:
    def test_manages_multiple_processes(self):
        with ProcessGroup() as group:
            p1 = group.add(["sleep", "10"], name="p1")
            p2 = group.add(["sleep", "10"], name="p2")
            assert p1.pid > 0
            assert p2.pid > 0
            assert p1.pid != p2.pid
        assert p1._proc.returncode is not None
        assert p2._proc.returncode is not None

    def test_stops_in_reverse_order(self):
        """Processes added last should stop first."""
        stop_order = []

        class _TrackingProcess(Process):
            def stop(self):
                stop_order.append(self.name)
                super().stop()

        import perf_orchestrator.process as _mod

        original = _mod.Process

        def _tracked(cmd, **kw):
            p = _TrackingProcess(cmd, **kw)
            return p

        # Use real ProcessGroup but intercept Process construction
        group = ProcessGroup()
        with group:
            # manually inject tracked processes
            for name in ["first", "second", "third"]:
                p = _TrackingProcess(["sleep", "10"], name=name)
                p.start()
                group._processes.append(p)

        assert stop_order == ["third", "second", "first"]

    def test_context_manager_stops_on_exit(self):
        with ProcessGroup() as group:
            p = group.add(["sleep", "10"])
        assert p._proc.returncode is not None

    def test_report_keyed_by_name(self):
        with ProcessGroup() as group:
            group.add(["sleep", "10"], name="alpha")
            group.add(["sleep", "10"], name="beta")
            reports = group.report()
        assert "alpha" in reports
        assert "beta" in reports

    def test_empty_group(self):
        with ProcessGroup() as group:
            result = group.report()
        assert result == {}
