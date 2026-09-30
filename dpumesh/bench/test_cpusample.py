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

    def test_restarted_process_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "restarted"):
            cpusample.cpu_seconds({"process_totals": {"p": [42, 9, 100]}},
                                  {"process_totals": {"p": [42, 10, 1000]}}, "p")


if __name__ == "__main__":
    unittest.main()
