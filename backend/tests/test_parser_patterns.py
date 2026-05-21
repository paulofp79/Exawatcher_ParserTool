from __future__ import annotations

import lzma
import tempfile
import unittest
from pathlib import Path

from backend.app.kb import KnowledgeEntry
from backend.app.parser import parse_bundle
from backend.app.patterns import detect_findings


class ParserPatternTests(unittest.TestCase):
    def test_parses_iostat_xz_and_detects_high_util(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "ExaWatcher_cell_2026"
            module = root / "Iostat.ExaWatcher"
            module.mkdir(parents=True)
            sample = """############################################################
# Starting Time:\t05/13/2026 19:00:00
# Collection Module:\tIostatExaWatcher
############################################################
zzz <05/13/2026 19:00:00> Count:1
Linux 5.15.0 (cell.example.com) \t05/13/2026 \t_x86_64_\t(128 CPU)

05/13/2026 07:00:00 PM
avg-cpu:  %user   %nice %system %iowait  %steal   %idle
           4.87    0.02    2.22    0.01    0.00   92.87

Device            r/s     w/s     rMB/s     wMB/s   rrqm/s   wrqm/s  %rrqm  %wrqm r_await w_await aqu-sz rareq-sz wareq-sz  svctm  %util
nvme0n1        700.00 2500.00     80.00     75.00     0.00     2.00   0.00   0.10    0.45   80.00   0.40   118.10    31.69   0.03  96.00
"""
            with lzma.open(module / "2026_05_13_19_00_00_IostatExaWatcher_cell.example.com.dat.xz", "wt") as handle:
                handle.write(sample)

            result = parse_bundle(str(root), "case1")
            self.assertEqual(result.host, "cell.example.com")
            self.assertGreaterEqual(len(result.metrics), 1)

            findings = detect_findings("case1", result.metrics, result.modules_seen, kb())
            patterns = {finding.pattern_id for finding in findings}
            self.assertIn("io.high_util", patterns)
            self.assertIn("io.high_write_await", patterns)

    def test_parses_ecstat_json_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "ExaWatcher_cell_2026"
            module = root / "ECStatJSON.ExaWatcher"
            module.mkdir(parents=True)
            sample = """# Starting Time:\t05/13/2026 19:00:22
zzz <05/13/2026 19:00:22> Count:0
{
  "celldisk stats": [
    {
      "name": "FD_00_cell",
      "timestampFormatted": "2026-05-13 19:00:22.985",
      "stats": {
        "latency warning": {
          "iops": 12,
          "bytes": 4096
        }
      }
    }
  ]
}
"""
            with lzma.open(module / "2026_05_13_19_00_22_ECStatJSONExaWatcher_cell.example.com.dat.xz", "wt") as handle:
                handle.write(sample)

            result = parse_bundle(str(root), "case2")
            metric_names = {metric.metric_name for metric in result.metrics}
            self.assertTrue(any("iops" in name for name in metric_names))

    def test_missing_module_findings_are_emitted(self) -> None:
        findings = detect_findings("case3", [], set(), kb())
        self.assertIn("coverage.missing_module", {finding.pattern_id for finding in findings})


def kb() -> list[KnowledgeEntry]:
    return [
        KnowledgeEntry(
            id="test",
            title="test",
            symptoms=[],
            matched_patterns=["io.high_util", "io.high_write_await", "coverage.missing_module"],
            explanation="",
            recommended_checks=[],
            severity_guidance="",
        )
    ]


if __name__ == "__main__":
    unittest.main()

