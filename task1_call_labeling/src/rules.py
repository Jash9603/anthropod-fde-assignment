"""Combine LLM-extracted evidence into the four final labels (policy assignment-v2).

decide(extraction, call_started_at) -> dict with exactly:
    disposition, sub_disposition, lead_quality, next_call_at
"""
from callback_time import (
    parse_call_time, format_iso, resolve_callback, resolve_date, resolve_clock, fallback_call,
)
from schema import INVALID_REASONS, BLOCKERS, normalize_extraction

VALID_PAIRS = {
    "Appointment Scheduled": ["Clinic Visit", "Online Consultation", "Rescheduled"],
    "Follow-up Required": ["Specific Callback", "Vague Deferral", "Family Discussion", "Cost Concern",
                           "Travel Constraint", "Current Treatment", "Treatment Concern",
                           "Information Requested", "Further Discussion"],
    "Not Interested": ["Explicit Refusal", "Do Not Contact"],
    "Invalid Lead": ["Wrong Contact", "No Pain Need", "Outside Service Area", "Policy Exclusion", "Test Enquiry"],
    "Unable to Assess": ["Incomplete Conversation"],
}
INVALID_LABEL = {
    "test_enquiry": "Test Enquiry", "wrong_contact": "Wrong Contact", "no_pain_need": "No Pain Need",
    "policy_exclusion": "Policy Exclusion", "outside_service_area": "Outside Service Area",
}
BLOCKER_LABEL = {
    "family_discussion": "Family Discussion", "cost_concern": "Cost Concern",
    "travel_constraint": "Travel Constraint", "current_treatment": "Current Treatment",
    "treatment_concern": "Treatment Concern",
}


def _appointment_confirmed(ex):
    """D3: confirmed slot needs a date and a clock time or bounded window."""
    c = ex["consultation"]
    return bool(c["slot_confirmed"] and c["has_clock_or_window"]
                and c["date"]["date_kind"] not in ("none", "unresolved", "this_week"))


def decide_disposition(ex):
    """D6 precedence: Invalid > Not Interested > Appointment > Follow-up > Unable.

    Precedence is implemented by the ORDER of the checks below: the first one that
    matches returns, so a higher-ranked outcome always beats a lower-ranked one.
      rank 1  Invalid Lead           (D1)
      rank 2  Not Interested         (D2)
      rank 3  Appointment Scheduled  (D3)
      rank 4  Follow-up Required     (D4)  \\ mutually exclusive: split by
      rank 5  Unable to Assess       (D5)  / `relevant_discussion`, so ranks 4/5 are checked
                                           in the opposite order for simplicity.
    "Final evidence after corrections" (D6, last sentence) is the LLM prompt's job: it must
    report the FINAL state of each field (e.g. a refusal later reversed => final_refusal "none").
    """
    if ex["invalid_reasons"]:
        reason = next(r for r in INVALID_REASONS if r in ex["invalid_reasons"])   # tie-break order
        return "Invalid Lead", INVALID_LABEL[reason]
    if ex["final_refusal"] != "none":
        return "Not Interested", "Do Not Contact" if ex["final_refusal"] == "do_not_contact" else "Explicit Refusal"
    if _appointment_confirmed(ex):
        c = ex["consultation"]
        if c["replaces_previous"]:
            return "Appointment Scheduled", "Rescheduled"
        return "Appointment Scheduled", "Online Consultation" if c["mode"] == "online" else "Clinic Visit"
    if not ex["relevant_discussion"]:
        return "Unable to Assess", "Incomplete Conversation"
    return "Follow-up Required", None   # sub-disposition needs the callback result


def _specific_callback(ex, now):
    """F3: acknowledged callbackv that resoles to a future datetime, else None."""
    cb = ex["callback"]
    if not cb["agreed"]:
        return None
    return resolve_callback(cb["time"], now)


def _is_vague(ex):
    """F7 / F10 / F12: explicit vague postponement. An acknowledged callback whose timing is tied to an
    unresolved event ("after Dussehra") or is only "this week" is vague too. A callback that merely
    resolved to a past time is NOT vague (F6/F7: a rejected specific callback does not imply deferral)."""
    cb = ex["callback"]
    unresolvable = cb["agreed"] and cb["time"]["date_kind"] in ("unresolved", "this_week")
    return bool(ex["vague_postponement"] or unresolvable)


def followup_sub(ex, specific_cb):
    """Final unresolved blocker, else Specific Callback / Info / Vague / Further (tie-break order)."""
    blockers = ex["blockers"]
    if ex["primary_blocker"]:
        return BLOCKER_LABEL[ex["primary_blocker"]]
    for b in BLOCKERS:                      # tie-break when several are equally primary
        if b in blockers:
            return BLOCKER_LABEL[b]
    if specific_cb is not None:
        return "Specific Callback"
    if ex["info_review_pending"]:
        return "Information Requested"
    if _is_vague(ex):
        return "Vague Deferral"
    return "Further Discussion"


def decide_next_call(disposition, specific_cb, ex, now):
    """F2 / F3 / F7 / F8 / F9."""
    if disposition in ("Invalid Lead", "Not Interested", "Unable to Assess"):
        return None
    if specific_cb is not None:
        return specific_cb
    if disposition == "Appointment Scheduled":
        return None                                       # reminders are not inferred
    if _is_vague(ex):
        return fallback_call(now, 3)                      # F7
    return fallback_call(now, 1)                          # F8


def decide_lead_quality(disposition, ex, now, specific_cb):
    """Order: Not Qualified, Not Assessable, Low, High, Medium."""
    if disposition == "Invalid Lead":
        return "Not Qualified"
    if disposition == "Unable to Assess" or ex["pain_need"] == "unclear":
        return "Not Assessable"

    appointment = disposition == "Appointment Scheduled"
    if disposition == "Not Interested" or ex["exploratory_only"]:
        return "Low"
    if not appointment:
        long_defer = ex["defers_over_30_days"]
        if specific_cb is not None and (specific_cb.date() - now.date()).days > 30:
            long_defer = True
        if long_defer:
            return "Low"

    c = ex["consultation"]
    if (appointment or c["explicit_commitment"]) and not ex["blockers"]:
        d = resolve_date(c["date"], now, resolve_clock(c["date"]))
        if d is not None and 0 <= (d - now.date()).days <= 6:
            return "High"
    return "Medium"


def decide(extraction, call_started_at):
    ex = normalize_extraction(extraction)
    now = parse_call_time(call_started_at)

    disposition, sub = decide_disposition(ex)
    specific_cb = _specific_callback(ex, now)
    if disposition == "Follow-up Required":
        sub = followup_sub(ex, specific_cb)

    lead_quality = decide_lead_quality(disposition, ex, now, specific_cb)
    next_call = decide_next_call(disposition, specific_cb, ex, now)

    assert sub in VALID_PAIRS[disposition], (disposition, sub)
    return {
        "disposition": disposition,
        "sub_disposition": sub,
        "lead_quality": lead_quality,
        "next_call_at": format_iso(next_call) if next_call else None,
    }
