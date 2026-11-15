"""Intermediate extraction schema (the contract between the LLM and rules.py), in pydantic v2.

The LLM answers small evidence-backed questions and fills `Extraction`.
Python (rules.py / callback_time.py) turns it into the four final labels.

Design rule: NEVER raise on messy LLM output. Every field has a lenient
`before` validator: unknown / malformed values fall back to a neutral default,
so one bad value cannot cost us a whole record. `normalize_extraction` is
additionally wrapped so that even a totally broken payload yields defaults.
"""
from typing import Annotated, Any, Dict, List, Literal, Optional, get_args

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

# ---- allowed values (list order matters where it is a tie-break order) ------------
InvalidReason = Literal["test_enquiry", "wrong_contact", "no_pain_need", "policy_exclusion", "outside_service_area"]
Blocker = Literal["family_discussion", "cost_concern", "travel_constraint", "current_treatment", "treatment_concern"]
Refusal = Literal["none", "explicit_refusal", "do_not_contact"]
Mode = Literal["clinic", "online", "unknown"]
Need = Literal["yes", "no", "unclear"]
Weekday = Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
DateKind = Literal[
    "none", "today", "tomorrow", "day_after_tomorrow", "in_n_days", "weekday", "this_weekday",
    "next_weekday", "next_week", "this_week", "absolute_date", "in_n_months", "next_month",
    "in_n_minutes", "in_n_hours", "unresolved",
]
TimeKind = Literal["none", "clock", "morning", "afternoon", "evening", "lunch"]
Meridiem = Literal["am", "pm"]

INVALID_REASONS = list(get_args(InvalidReason))
BLOCKERS = list(get_args(Blocker))
REFUSALS = list(get_args(Refusal))
MODES = list(get_args(Mode))
NEED = list(get_args(Need))
WEEKDAYS = list(get_args(Weekday))
DATE_KINDS = list(get_args(DateKind))
TIME_KINDS = list(get_args(TimeKind))
MERIDIEMS = list(get_args(Meridiem))


# ---- lenient coercion helpers ------------------------------------------------------
def _clean(v: Any) -> str:
    return str(v).strip().lower().replace(" ", "_").replace("-", "_") if v is not None else ""


def _to_int(v: Any) -> Optional[int]:
    if isinstance(v, bool) or v is None:
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _to_bool(v: Any) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("true", "yes", "y", "1")
    return bool(v)


def _enum_or(allowed, default):
    def f(v: Any):
        v = _clean(v)
        return v if v in allowed else default
    return f


def _enum_list(allowed):
    def f(v: Any):
        if not isinstance(v, (list, tuple)):
            return []
        out = []
        for x in v:
            x = _clean(x)
            if x in allowed and x not in out:
                out.append(x)
        return out
    return f


def _str_dict(v: Any):
    if not isinstance(v, dict):
        return {}
    return {str(k)[:40]: str(x)[:300] for k, x in v.items() if x is not None}


def _dict_or_empty(v: Any):
    return v if isinstance(v, (dict, BaseModel)) else {}


Int = Annotated[Optional[int], BeforeValidator(_to_int)]
Bool = Annotated[bool, BeforeValidator(_to_bool)]


# ---- models ------------------------------------------------------------------------
class TimeSpec(BaseModel):
    """How a spoken day/time is described. Python resolves it to a real datetime."""
    model_config = ConfigDict(extra="ignore")

    date_kind: Annotated[DateKind, BeforeValidator(_enum_or(DATE_KINDS, "none"))] = "none"
    n: Int = None                      # for in_n_days / in_n_months / in_n_minutes / in_n_hours
    weekday: Annotated[Optional[Weekday], BeforeValidator(_enum_or(WEEKDAYS, None))] = None
    month: Int = None                  # absolute_date
    day: Int = None
    year: Int = None
    time_kind: Annotated[TimeKind, BeforeValidator(_enum_or(TIME_KINDS, "none"))] = "none"
    hour: Int = None                   # time_kind == clock
    minute: Int = None
    meridiem: Annotated[Optional[Meridiem], BeforeValidator(_enum_or(MERIDIEMS, None))] = None


class Consultation(BaseModel):
    """Evidence about an actual consultation booking or commitment."""
    model_config = ConfigDict(extra="ignore")

    slot_confirmed: Bool = False           # both sides agreed a consultation slot
    has_clock_or_window: Bool = False      # a clock time or bounded window was agreed
    mode: Annotated[Mode, BeforeValidator(_enum_or(MODES, "unknown"))] = "unknown"
    replaces_previous: Bool = False        # replaces an existing / missed appointment
    explicit_commitment: Bool = False      # customer explicitly committed to come
    date: Annotated[TimeSpec, BeforeValidator(_dict_or_empty)] = Field(default_factory=TimeSpec)


class Callback(BaseModel):
    """A future call between clinic and customer (not the consultation itself)."""
    model_config = ConfigDict(extra="ignore")

    agreed: Bool = False                   # proposed by one side AND acknowledged by the other
    time: Annotated[TimeSpec, BeforeValidator(_dict_or_empty)] = Field(default_factory=TimeSpec)


class Extraction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    evidence: Annotated[Dict[str, str], BeforeValidator(_str_dict)] = Field(default_factory=dict)  # audit only; rules ignore it
    invalid_reasons: Annotated[List[InvalidReason], BeforeValidator(_enum_list(INVALID_REASONS))] = Field(default_factory=list)
    final_refusal: Annotated[Refusal, BeforeValidator(_enum_or(REFUSALS, "none"))] = "none"
    relevant_discussion: Bool = False
    pain_need: Annotated[Need, BeforeValidator(_enum_or(NEED, "unclear"))] = "unclear"
    consultation: Annotated[Consultation, BeforeValidator(_dict_or_empty)] = Field(default_factory=Consultation)
    blockers: Annotated[List[Blocker], BeforeValidator(_enum_list(BLOCKERS))] = Field(default_factory=list)
    primary_blocker: Annotated[Optional[Blocker], BeforeValidator(_enum_or(BLOCKERS, None))] = None
    info_review_pending: Bool = False
    callback: Annotated[Callback, BeforeValidator(_dict_or_empty)] = Field(default_factory=Callback)
    vague_postponement: Bool = False
    exploratory_only: Bool = False
    defers_over_30_days: Bool = False

    @model_validator(mode="after")
    def _primary_in_blockers(self):
        if self.primary_blocker and self.primary_blocker not in self.blockers:
            self.blockers.append(self.primary_blocker)
        return self


# ---- public API (names used by rules.py / tests / runner) ----------------------------
def normalize_timespec(raw: Any) -> dict:
    try:
        return TimeSpec.model_validate(raw if isinstance(raw, dict) else {}).model_dump()
    except Exception:
        return TimeSpec().model_dump()


def normalize_extraction(raw: Any) -> dict:
    """Any input -> a complete, valid extraction dict. Never raises."""
    try:
        return Extraction.model_validate(raw if isinstance(raw, dict) else {}).model_dump()
    except Exception:
        return Extraction().model_dump()

