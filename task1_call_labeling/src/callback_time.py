"""Deterministic date/time resolution (rules F1-F12).

Input: a normalized timespec (see schema.py) and the call timestamp.
Output: a timezone-aware datetime in IST, or None when the expression is
vague, unresolvable, or explicitly in the past (F6: never silently repaired).
"""
import calendar
from datetime import datetime, timedelta, timezone, date

IST = timezone(timedelta(hours=5, minutes=30))
WEEKDAY_INDEX = {n: i for i, n in enumerate(
    ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"])}
DEFAULT_TIME = (11, 0)
PART_OF_DAY = {"morning": (10, 0), "afternoon": (15, 0), "evening": (18, 0), "lunch": (13, 0)}


def parse_call_time(call_started_at):
    """Parse call_started_at and express it in Asia/Kolkata (F1)."""
    dt = datetime.fromisoformat(str(call_started_at).strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=IST)
    return dt.astimezone(IST)


def format_iso(dt):
    """ISO 8601 with seconds and +05:30 exactly."""
    return dt.astimezone(IST).strftime("%Y-%m-%dT%H:%M:%S+05:30")


def resolve_clock(spec):
    """(hour, minute) from the time part of a spec, or None if no time given (F5)."""
    tk = spec.get("time_kind", "none")
    if tk in PART_OF_DAY:
        return PART_OF_DAY[tk]
    if tk != "clock" or spec.get("hour") is None:
        return None
    h, m = spec["hour"], spec.get("minute") or 0
    if not (0 <= h <= 24 and 0 <= m <= 59):
        return None
    mer = spec.get("meridiem")
    if mer == "am":
        h = 0 if h == 12 else h
    elif mer == "pm":
        h = h + 12 if h < 12 else h
    elif 1 <= h <= 7:      # no AM/PM: 1-7 -> PM
        h += 12
    # 8-11 -> AM, 12 -> noon, 0 or 13-23 as stated
    if h == 24:
        h = 0
    if not (0 <= h <= 23):
        return None
    return (h, m)


def _add_months(d, months):
    idx = d.year * 12 + (d.month - 1) + months
    y, m = divmod(idx, 12)
    m += 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _next_monday(today):
    return today + timedelta(days=7 - today.weekday())


def resolve_date(spec, now, clock=None):
    """Calendar date a spec refers to, ignoring time-of-day unless needed to
    decide today-vs-later. Returns a date or None (vague / unresolvable).
    `clock` = (h, m) used only for 'this weekday' and absolute dates without a year.
    """
    kind = spec.get("date_kind", "none")
    today = now.date()
    n = spec.get("n")
    wd = WEEKDAY_INDEX.get(spec.get("weekday") or "")

    if kind == "today":
        return today
    if kind == "tomorrow":
        return today + timedelta(days=1)
    if kind == "day_after_tomorrow":
        return today + timedelta(days=2)
    if kind == "in_n_days":
        return today + timedelta(days=n) if n is not None and n >= 0 else None
    if kind == "weekday":                       # nearest strictly future occurrence
        if wd is None:
            return None
        return today + timedelta(days=((wd - today.weekday()) % 7) or 7)
    if kind == "this_weekday":                  # today or later, with a future time
        if wd is None:
            return None
        h, m = clock or DEFAULT_TIME
        d0 = today + timedelta(days=(wd - today.weekday()) % 7)
        if datetime(d0.year, d0.month, d0.day, h, m, tzinfo=IST) > now:
            return d0
        return d0 + timedelta(days=7)
    if kind == "next_weekday":                  # following Monday-Sunday week
        if wd is None:
            return None
        return _next_monday(today) + timedelta(days=wd)
    if kind == "next_week":                     # next week alone = next Monday
        return _next_monday(today)
    if kind == "in_n_months":
        return _add_months(today, n) if n is not None and n >= 0 else None
    if kind == "next_month":
        first = _add_months(today.replace(day=1), 1)
        return first
    if kind == "absolute_date":
        month, day, year = spec.get("month"), spec.get("day"), spec.get("year")
        h, m = clock or DEFAULT_TIME
        if day and not month and not year:
            # day-of-month only ("on the 15th"): nearest future occurrence of that day number
            y, mo = today.year, today.month
            for _ in range(14):
                try:
                    if datetime(y, mo, day, h, m, tzinfo=IST) > now:
                        return date(y, mo, day)
                except ValueError:              # that month has no such day (e.g. 31 in November)
                    pass
                y, mo = (y + 1, 1) if mo == 12 else (y, mo + 1)
            return None
        if not month or not day:
            return None
        try:
            if year:
                return date(year, month, day)
            for y in (today.year, today.year + 1, today.year + 2, today.year + 4):
                try:
                    d = date(y, month, day)
                except ValueError:          # e.g. 29 Feb
                    continue
                if datetime(y, month, day, h, m, tzinfo=IST) > now:
                    return d
            return None
        except ValueError:
            return None
    # none, this_week (vague), unresolved, in_n_minutes/hours (not a calendar date)
    return None


def resolve_callback(spec, now):
    """Resolve a callback timespec to a future datetime, or None."""
    kind = spec.get("date_kind", "none")
    n = spec.get("n")

    if kind in ("in_n_minutes", "in_n_hours"):          # F10: keep seconds
        if n is None or n < 0:
            return None
        dt = now + (timedelta(minutes=n) if kind == "in_n_minutes" else timedelta(hours=n))
        return dt if dt > now else None

    clock = resolve_clock(spec)

    if kind == "none":                                   # time only (F5)
        if clock is None:
            return None
        cand = now.replace(hour=clock[0], minute=clock[1], second=0, microsecond=0)
        return cand if cand > now else cand + timedelta(days=1)

    d = resolve_date(spec, now, clock)
    if d is None:
        return None
    h, m = clock or DEFAULT_TIME
    cand = datetime(d.year, d.month, d.day, h, m, tzinfo=IST)
    return cand if cand > now else None                  # F6: reject past, no repair


def fallback_call(now, days):
    """F7 / F8 fallback: call date + N calendar days at 11:00."""
    d = now.date() + timedelta(days=days)
    return datetime(d.year, d.month, d.day, *DEFAULT_TIME, tzinfo=IST)
