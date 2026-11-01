import copy
import json
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from sw004_simulator import ScenarioError
from sw004_sensitivity import compare_scenarios


SAMPLE = json.loads(Path(__file__).with_name("sw004_sample_scenario.json").read_text())


class SensitivityTests(unittest.TestCase):
    def test_explicit_downside_and_repeatability(self):
        base = copy.deepcopy(SAMPLE)
        downside = copy.deepcopy(SAMPLE)
        downside["software_usd"] = "1000"
        cases = [("base", base), ("downside", downside)]
        first = compare_scenarios(cases)
        self.assertEqual(first, compare_scenarios(cases))
        self.assertEqual(first["minimum_case"], "downside")
        self.assertEqual(first["maximum_case"], "base")
        self.assertTrue(first["includes_nonpositive_case"])
        self.assertLess(0, float(first["maximum_net_current_cash_delta_usd"]))
        self.assertGreater(0, float(first["minimum_net_current_cash_delta_usd"]))
        self.assertEqual(first["analysis_type"], "DETERMINISTIC_SCENARIO_ENVELOPE")

    def test_incomparable_period_rejected(self):
        other = copy.deepcopy(SAMPLE)
        def shift(value):
            date = datetime.fromisoformat(value.replace("Z", "+00:00")) + timedelta(days=1)
            return date.isoformat().replace("+00:00", "Z")
        other["start_utc"] = shift(other["start_utc"])
        for row in other["observations"]:
            row["timestamp_utc"] = shift(row["timestamp_utc"])
        for region in other["regions"]:
            for field in ("reservation_start_utc", "reservation_end_utc", "price_start_utc", "price_end_utc"):
                if field in region:
                    region[field] = shift(region[field])
        with self.assertRaisesRegex(ScenarioError, "period and region/model"):
            compare_scenarios([("base", SAMPLE), ("other", other)])

    def test_duplicate_names_rejected(self):
        with self.assertRaisesRegex(ScenarioError, "unique"):
            compare_scenarios([("same", SAMPLE), ("same", SAMPLE)])
        with self.assertRaisesRegex(ScenarioError, "printable"):
            compare_scenarios([(42, SAMPLE), ("other", SAMPLE)])
        for unsafe in (" ", "case\x7f", "case\u202e"):
            with self.subTest(name=repr(unsafe)), self.assertRaisesRegex(ScenarioError, "printable"):
                compare_scenarios([(unsafe, SAMPLE), ("other", SAMPLE)])


if __name__ == "__main__":
    unittest.main()
