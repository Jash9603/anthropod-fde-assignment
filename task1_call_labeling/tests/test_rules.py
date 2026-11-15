"""Unit tests (stdlib unittest). Run from task1_call_labeling/:
    python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from callback_time import parse_call_time, resolve_callback, format_iso  # noqa: E402
from rules import decide, VALID_PAIRS  # noqa: E402
from schema import normalize_extraction  # noqa: E402

MON = "2026-11-09T14:00:00+05:30"   # Monday, as in the rules' examples


def spec(**kw):
    base = {"date_kind": "none", "time_kind": "none"}
    base.update(kw)
    return base


def cb(call, **kw):
    # the callback time goes through the same validation path as real model output
    t = normalize_extraction({"callback": {"agreed": True, "time": spec(**kw)}})["callback"]["time"]
    r = resolve_callback(t, parse_call_time(call))
    return format_iso(r) if r else None


def ex(**kw):
    base = {"relevant_discussion": True, "pain_need": "yes"}
    base.update(kw)
    return base


class TestCallbackTime(unittest.TestCase):
    def test_ex1_tomorrow_at_4(self):
        self.assertEqual(cb(MON, date_kind="tomorrow", time_kind="clock", hour=4), "2026-11-10T16:00:00+05:30")

    def test_day_default_11(self):
        self.assertEqual(cb(MON, date_kind="day_after_tomorrow"), "2026-11-11T11:00:00+05:30")

    def test_time_only_future_today_else_tomorrow(self):
        self.assertEqual(cb(MON, time_kind="clock", hour=5), "2026-11-09T17:00:00+05:30")   # 5 -> PM, future
        self.assertEqual(cb(MON, time_kind="clock", hour=10), "2026-11-10T10:00:00+05:30")  # 10 AM past -> tomorrow

    def test_hour_defaults(self):
        self.assertEqual(cb(MON, date_kind="tomorrow", time_kind="clock", hour=12), "2026-11-10T12:00:00+05:30")
        self.assertEqual(cb(MON, date_kind="tomorrow", time_kind="clock", hour=9), "2026-11-10T09:00:00+05:30")
        self.assertEqual(cb(MON, date_kind="tomorrow", time_kind="clock", hour=9, meridiem="pm"), "2026-11-10T21:00:00+05:30")

    def test_part_of_day(self):
        self.assertEqual(cb(MON, date_kind="tomorrow", time_kind="evening"), "2026-11-10T18:00:00+05:30")
        self.assertEqual(cb(MON, date_kind="tomorrow", time_kind="lunch"), "2026-11-10T13:00:00+05:30")

    def test_weekdays(self):
        # bare weekday: nearest strictly future (Monday call, "Monday" -> next Monday)
        self.assertEqual(cb(MON, date_kind="weekday", weekday="monday"), "2026-11-16T11:00:00+05:30")
        self.assertEqual(cb(MON, date_kind="weekday", weekday="friday"), "2026-11-13T11:00:00+05:30")
        # this Monday at 5pm is still today and future
        self.assertEqual(cb(MON, date_kind="this_weekday", weekday="monday", time_kind="clock", hour=5),
                         "2026-11-09T17:00:00+05:30")
        # this Monday at 11 (past) -> following week
        self.assertEqual(cb(MON, date_kind="this_weekday", weekday="monday"), "2026-11-16T11:00:00+05:30")
        # next Friday = Friday of the following Mon-Sun week
        self.assertEqual(cb(MON, date_kind="next_weekday", weekday="friday"), "2026-11-20T11:00:00+05:30")

    def test_next_week_and_this_week(self):
        self.assertEqual(cb(MON, date_kind="next_week"), "2026-11-16T11:00:00+05:30")
        self.assertIsNone(cb(MON, date_kind="this_week"))

    def test_months(self):
        self.assertEqual(cb("2026-01-31T10:00:00+05:30", date_kind="in_n_months", n=1), "2026-02-28T11:00:00+05:30")
        self.assertEqual(cb(MON, date_kind="next_month"), "2026-12-01T11:00:00+05:30")

    def test_absolute_dates(self):
        self.assertEqual(cb(MON, date_kind="absolute_date", month=11, day=20), "2026-11-20T11:00:00+05:30")
        self.assertEqual(cb(MON, date_kind="absolute_date", month=11, day=2), "2027-11-02T11:00:00+05:30")  # next occurrence
        self.assertIsNone(cb(MON, date_kind="absolute_date", month=11, day=2, year=2026))                  # explicit past

    def test_day_of_month_only(self):
        self.assertEqual(cb(MON, date_kind="absolute_date", day=15), "2026-11-15T11:00:00+05:30")
        self.assertEqual(cb(MON, date_kind="absolute_date", day=5), "2026-12-05T11:00:00+05:30")    # already passed -> next month
        self.assertEqual(cb(MON, date_kind="absolute_date", day=31), "2026-12-31T11:00:00+05:30")   # November has no 31st

    def test_past_same_day_time_rejected(self):
        self.assertIsNone(cb(MON, date_kind="today", time_kind="clock", hour=11, meridiem="am"))

    def test_intervals_keep_seconds(self):
        self.assertEqual(cb("2026-11-09T14:00:30+05:30", date_kind="in_n_hours", n=2), "2026-11-09T16:00:30+05:30")

    def test_unresolved_is_none(self):
        self.assertIsNone(cb(MON, date_kind="unresolved"))


class TestRules(unittest.TestCase):
    def test_ex2_vague_deferral_plus3(self):
        r = decide(ex(vague_postponement=True), MON)
        self.assertEqual((r["disposition"], r["sub_disposition"]), ("Follow-up Required", "Vague Deferral"))
        self.assertEqual(r["next_call_at"], "2026-11-12T11:00:00+05:30")
        self.assertEqual(r["lead_quality"], "Medium")

    def test_ex1_specific_callback(self):
        r = decide(ex(callback={"agreed": True, "time": spec(date_kind="tomorrow", time_kind="clock", hour=4)}), MON)
        self.assertEqual(r["sub_disposition"], "Specific Callback")
        self.assertEqual(r["next_call_at"], "2026-11-10T16:00:00+05:30")

    def test_event_conditional_callback_is_vague(self):
        # "I'll call next week after Dussehra" + okay -> F12: vague -> +3 days, Vague Deferral
        r = decide(ex(callback={"agreed": True, "time": spec(date_kind="unresolved")}), MON)
        self.assertEqual((r["sub_disposition"], r["next_call_at"]), ("Vague Deferral", "2026-11-12T11:00:00+05:30"))
        r = decide(ex(callback={"agreed": True, "time": spec(date_kind="this_week")}), MON)
        self.assertEqual(r["next_call_at"], "2026-11-12T11:00:00+05:30")

    def test_past_callback_is_not_vague(self):
        r = decide(ex(callback={"agreed": True, "time": spec(date_kind="today", time_kind="clock", hour=11, meridiem="am")}), MON)
        self.assertEqual((r["sub_disposition"], r["next_call_at"]), ("Further Discussion", "2026-11-10T11:00:00+05:30"))

    def test_unacknowledged_callback_not_used(self):
        r = decide(ex(callback={"agreed": False, "time": spec(date_kind="tomorrow")}), MON)
        self.assertEqual(r["next_call_at"], "2026-11-10T11:00:00+05:30")   # +1 fallback (F8)

    def test_ex3_appointment_is_not_callback(self):
        r = decide(ex(consultation={"slot_confirmed": True, "has_clock_or_window": True, "mode": "clinic",
                                    "date": spec(date_kind="tomorrow", time_kind="clock", hour=3)}), MON)
        self.assertEqual((r["disposition"], r["sub_disposition"]), ("Appointment Scheduled", "Clinic Visit"))
        self.assertIsNone(r["next_call_at"])
        self.assertEqual(r["lead_quality"], "High")

    def test_ex4_unspecified_agent_call_plus1(self):
        r = decide(ex(), MON)
        self.assertEqual((r["sub_disposition"], r["next_call_at"]), ("Further Discussion", "2026-11-10T11:00:00+05:30"))

    def test_ex5_do_not_contact(self):
        r = decide(ex(final_refusal="do_not_contact", callback={"agreed": True, "time": spec(date_kind="tomorrow")}), MON)
        self.assertEqual((r["disposition"], r["sub_disposition"], r["lead_quality"], r["next_call_at"]),
                         ("Not Interested", "Do Not Contact", "Low", None))

    def test_ex6_severity_and_day7(self):
        r = decide(ex(blockers=["family_discussion"]), MON)
        self.assertEqual((r["sub_disposition"], r["lead_quality"]), ("Family Discussion", "Medium"))
        slot = {"slot_confirmed": True, "has_clock_or_window": True, "mode": "clinic"}
        six = decide(ex(consultation=dict(slot, date=spec(date_kind="in_n_days", n=6))), MON)
        seven = decide(ex(consultation=dict(slot, date=spec(date_kind="in_n_days", n=7))), MON)
        self.assertEqual((six["lead_quality"], seven["lead_quality"]), ("High", "Medium"))

    def test_appointment_variants(self):
        base = {"slot_confirmed": True, "has_clock_or_window": True, "date": spec(date_kind="tomorrow")}
        self.assertEqual(decide(ex(consultation=dict(base, mode="online")), MON)["sub_disposition"], "Online Consultation")
        self.assertEqual(decide(ex(consultation=dict(base, mode="online", replaces_previous=True)), MON)["sub_disposition"],
                         "Rescheduled")
        # no clock time or window -> not a booking
        self.assertEqual(decide(ex(consultation=dict(base, has_clock_or_window=False)), MON)["disposition"],
                         "Follow-up Required")

    def test_appointment_on_day_of_month_only(self):
        slot = {"slot_confirmed": True, "has_clock_or_window": True, "mode": "clinic",
                "date": spec(date_kind="absolute_date", day=12, time_kind="clock", hour=1, meridiem="pm")}
        r = decide(ex(consultation=slot), MON)    # call Mon 9 Nov; "the 12th" = offset 3
        self.assertEqual((r["disposition"], r["lead_quality"], r["next_call_at"]), ("Appointment Scheduled", "High", None))

    def test_appointment_with_distinct_callback(self):
        r = decide(ex(consultation={"slot_confirmed": True, "has_clock_or_window": True, "mode": "clinic",
                                    "date": spec(date_kind="in_n_days", n=3)},
                      callback={"agreed": True, "time": spec(date_kind="tomorrow", time_kind="clock", hour=5)}), MON)
        self.assertEqual(r["next_call_at"], "2026-11-10T17:00:00+05:30")

    def test_precedence_and_suppression(self):
        r = decide(ex(invalid_reasons=["no_pain_need", "test_enquiry"], final_refusal="explicit_refusal"), MON)
        self.assertEqual((r["disposition"], r["sub_disposition"], r["lead_quality"], r["next_call_at"]),
                         ("Invalid Lead", "Test Enquiry", "Not Qualified", None))
        r = decide({"relevant_discussion": False}, MON)
        self.assertEqual((r["disposition"], r["lead_quality"], r["next_call_at"]), ("Unable to Assess", "Not Assessable", None))

    def test_blocker_tiebreak_and_primary(self):
        self.assertEqual(decide(ex(blockers=["treatment_concern", "cost_concern"]), MON)["sub_disposition"], "Cost Concern")
        self.assertEqual(decide(ex(blockers=["treatment_concern", "cost_concern"], primary_blocker="treatment_concern"),
                                MON)["sub_disposition"], "Treatment Concern")

    def test_blocker_keeps_explicit_callback(self):
        r = decide(ex(blockers=["travel_constraint"], callback={"agreed": True, "time": spec(date_kind="weekday", weekday="friday")}), MON)
        self.assertEqual((r["sub_disposition"], r["next_call_at"]), ("Travel Constraint", "2026-11-13T11:00:00+05:30"))

    def test_low_for_long_deferral_and_exploratory(self):
        self.assertEqual(decide(ex(exploratory_only=True), MON)["lead_quality"], "Low")
        r = decide(ex(callback={"agreed": True, "time": spec(date_kind="in_n_months", n=2)}), MON)
        self.assertEqual(r["lead_quality"], "Low")

    def test_pairs_always_valid(self):
        for d, subs in VALID_PAIRS.items():
            self.assertTrue(subs)


if __name__ == "__main__":
    unittest.main()
