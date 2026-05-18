"""Integration tests that require a real Linux perf installation.

Skipped automatically on non-Linux systems or when perf is not in PATH.
These tests verify the full perf stat / perf record pipeline against a
real subprocess.
"""
import shutil
import sys
import time

import pytest

from perf_orchestrator import PerfRecord, PerfStat, Process

pytestmark = pytest.mark.skipif(
    not (sys.platform == "linux" and shutil.which("perf") is not None),
    reason="requires Linux with perf installed",
)

_BUSY_LOOP = (
    "import time; end = time.monotonic() + 2; "
    "[x*x for x in range(10**6) for _ in iter(lambda: time.monotonic() < end, False)]"
)


class TestPerfStatLive:
    def test_collects_counters(self, tmp_path):
        with Process(
            ["python3", "-c", "import time; time.sleep(2)"],
            perf=[PerfStat()],
        ) as proc:
            time.sleep(1)

        report = proc.report()
        assert "perf_stat" in report
        counters = report["perf_stat"].get("counters", {})
        assert len(counters) > 0

    def test_default_events_present(self, tmp_path):
        with Process(
            ["python3", "-c", "import time; time.sleep(2)"],
            perf=[PerfStat()],
        ) as proc:
            time.sleep(1)

        counters = proc.report()["perf_stat"].get("counters", {})
        for event in ("instructions", "cycles"):
            assert event in counters, f"expected '{event}' in counters"

    def test_custom_events(self):
        with Process(
            ["python3", "-c", "import time; time.sleep(2)"],
            perf=[PerfStat(events=["instructions", "cycles"])],
        ) as proc:
            time.sleep(1)

        counters = proc.report()["perf_stat"].get("counters", {})
        assert "instructions" in counters
        assert "cycles" in counters

    def test_derived_metrics_present_when_counters_nonzero(self):
        with Process(
            ["python3", "-c", f"{_BUSY_LOOP}"],
            perf=[PerfStat()],
        ) as proc:
            time.sleep(1)

        report = proc.report()["perf_stat"]
        counters = report.get("counters", {})
        derived = report.get("derived", {})
        if counters.get("cycles", 0) > 0 and counters.get("instructions", 0) > 0:
            assert "ipc" in derived
            assert "cpi" in derived

    def test_graceful_when_process_exits_quickly(self):
        with Process(
            ["python3", "-c", ""],
            perf=[PerfStat()],
        ):
            time.sleep(0.1)

        # should not raise regardless of whether perf captured anything


class TestPerfRecordLive:
    def test_creates_perf_data_file(self, tmp_path):
        perf_data = tmp_path / "perf.data"
        with Process(
            ["python3", "-c", "import time; time.sleep(2)"],
            perf=[PerfRecord(perf_data)],
        ) as proc:
            time.sleep(1)

        assert perf_data.exists()
        assert perf_data.stat().st_size > 0

    def test_report_contains_report_key(self, tmp_path):
        perf_data = tmp_path / "perf.data"
        with Process(
            ["python3", "-c", f"{_BUSY_LOOP}"],
            perf=[PerfRecord(perf_data)],
        ) as proc:
            time.sleep(1)

        result = proc.report()["perf_record"]
        assert "report" in result
        assert "stderr" in result

    def test_custom_freq(self, tmp_path):
        perf_data = tmp_path / "perf.data"
        with Process(
            ["python3", "-c", "import time; time.sleep(2)"],
            perf=[PerfRecord(perf_data, freq=49)],
        ) as proc:
            time.sleep(1)

        assert perf_data.exists()

    def test_stat_and_record_together(self, tmp_path):
        perf_data = tmp_path / "perf.data"
        with Process(
            ["python3", "-c", f"{_BUSY_LOOP}"],
            perf=[PerfStat(), PerfRecord(perf_data)],
        ) as proc:
            time.sleep(1)

        report = proc.report()
        assert "perf_stat" in report
        assert "perf_record" in report
