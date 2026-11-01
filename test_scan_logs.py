"""Unit tests for InferaCap Log Scanner."""

import json
from pathlib import Path
import unittest

from scan_logs import LogScanner, LogRecord


class TestLogScanner(unittest.TestCase):
    def setUp(self):
        self.scanner = LogScanner(on_demand_rate_gpu_hour=4.00, reservation_discount_pct=0.50)
        self.sample_csv = Path(__file__).parent / "sample_customer_vllm_logs.csv"

    def test_01_parse_valid_csv(self):
        records = self.scanner.parse_log_file(self.sample_csv)
        self.assertGreaterEqual(len(records), 1000)
        self.assertIsInstance(records[0], LogRecord)
        self.assertIn(records[0].origin_region, ("US", "EU", "ASIA"))

    def test_02_analyze_and_savings_calculation(self):
        records = self.scanner.parse_log_file(self.sample_csv)
        result = self.scanner.analyze(records)
        self.assertEqual(result.total_requests, len(records))
        self.assertGreater(result.baseline_compute_usd, result.inferacap_compute_usd)
        self.assertGreater(result.net_savings_usd, 0.0)
        self.assertGreater(result.savings_percentage, 0.0)
        self.assertGreater(result.annualized_projected_savings_usd, 0.0)


if __name__ == "__main__":
    unittest.main()
