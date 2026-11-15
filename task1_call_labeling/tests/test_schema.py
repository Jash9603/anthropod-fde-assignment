"""Schema leniency tests. Run from task1_call_labeling/:
    python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from schema import normalize_extraction, normalize_timespec  # noqa: E402
from rules import decide  # noqa: E402

CALL = "2026-11-09T14:00:00+05:30"


class TestSchemaNeverRaises(unittest.TestCase):
    def test_garbage_inputs_give_defaults(self):
        for bad in (None, [], "text", 5, {"consultation": "oops", "callback": [1], "blockers": "cost_concern",
                                           "final_refusal": 7, "invalid_reasons": None}):
            ex = normalize_extraction(bad)
            self.assertEqual(ex["final_refusal"], "none")
            self.assertEqual(ex["blockers"], [])
            self.assertEqual(ex["consultation"]["date"]["date_kind"], "none")
            self.assertEqual(ex["pain_need"], "unclear")
            decide(bad, CALL)   # full pipeline must not raise

    def test_loose_values_are_coerced(self):
        ex = normalize_extraction({
            "relevant_discussion": "True", "pain_need": " YES ",
            "blockers": ["Cost Concern", "bogus", "cost_concern"], "primary_blocker": "Treatment-Concern",
            "callback": {"agreed": "yes", "time": {"date_kind": "Tomorrow", "time_kind": "clock", "hour": "4.0", "meridiem": "PM"}},
            "unknown_key": 1,
        })
        self.assertTrue(ex["relevant_discussion"])
        self.assertEqual(ex["pain_need"], "yes")
        self.assertEqual(ex["blockers"], ["cost_concern", "treatment_concern"])
        self.assertEqual(ex["primary_blocker"], "treatment_concern")
        t = ex["callback"]["time"]
        self.assertEqual((t["date_kind"], t["hour"], t["meridiem"]), ("tomorrow", 4, "pm"))
        self.assertNotIn("unknown_key", ex)

    def test_bad_time_values_fall_back(self):
        t = normalize_timespec({"date_kind": "someday", "weekday": "funday", "n": "abc", "hour": True})
        self.assertEqual((t["date_kind"], t["weekday"], t["n"], t["hour"]), ("none", None, None, None))


if __name__ == "__main__":
    unittest.main()
