import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import cpusample
import summarize


class CpuAccountingTest(unittest.TestCase):
    def test_exited_threads_and_window_are_counted(self):
        before = {"t": 10, "procs": {"node": {"42": ["MainThread", 100, 3, 1, 9]}},
                  "process_totals": {"node": [42, 9, 100]}}
        after = {"t": 15, "procs": {"node": {"42": ["MainThread", 110, 4, 1, 9]}},
                 "process_totals": {"node": [42, 9, 200]}}
        with tempfile.TemporaryDirectory() as d:
            run = Path(d)
            a, b = run / "cpu-u8-a.json", run / "cpu-u8-b.json"
            a.write_text(json.dumps(before))
            b.write_text(json.dumps(after))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                cpusample.diff(a, b, 20)
            self.assertIn("42:MainThread", out.getvalue())
            self.assertIn(f"cpu_s={100 / cpusample.HZ:.3f}", out.getvalue())
            # The reported rate uses a different interval. CPU/request must
            # come from the two snapshots and request count, independently.
            (run / "summary.txt").write_text(
                "== users=8: frontend req/s=10 requests=20 p50=1ms p95=2ms p99=3ms failures=0\n"
                "total 0.20\n")
            row = next(summarize.rows(run))
            self.assertEqual(float(row["host_ms_per_page"]), 100 / cpusample.HZ / 20 * 1000)

    def test_idle_row_counts_cores_and_switches(self):
        before = {"t": 0, "procs": {"svc": {"7": ["dpumesh", 0, 10, 5, 3], "8": ["old", 50, 0, 0, 1]}},
                  "process_totals": {"svc": [7, 3, 100]}}
        after = {"t": 10, "procs": {"svc": {"7": ["dpumesh", 20, 110, 5, 3], "8": ["new", 5, 30, 0, 9]}},
                 "process_totals": {"svc": [7, 3, 100 + 2 * cpusample.HZ]}}
        with tempfile.TemporaryDirectory() as d:
            run = Path(d)
            (run / "cpu-idle-a.json").write_text(json.dumps(before))
            (run / "cpu-idle-b.json").write_text(json.dumps(after))
            (run / "summary.txt").write_text("== idle 10s\ntotal 0.20\ndpuproxy 0.97 x\n")
            row = next(summarize.rows(run))
            self.assertEqual(row["kind"], "idle")
            self.assertAlmostEqual(float(row["host_cores"]), 0.2, places=3)
            # 100 switches on the surviving thread, 30 on the reused TID.
            self.assertEqual(row["rate_per_s"], "13")
            self.assertIn("dpu proxy 0.97", row["note"])

    def test_restarted_process_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "restarted"):
            cpusample.cpu_seconds({"process_totals": {"p": [42, 9, 100]}},
                                  {"process_totals": {"p": [42, 10, 1000]}}, "p")


if __name__ == "__main__":
    unittest.main()
