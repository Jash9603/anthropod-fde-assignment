"""Strict input / output contracts (pydantic).

InputRecord  : the ONLY fields the workflow may read (extra keys such as gold labels are dropped).
OutputRecord : exactly the five keys required by the submission contract, with valid
               disposition / sub_disposition pairing and the exact ISO format.
"""
import json
import re
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from callback_time import parse_call_time
from rules import VALID_PAIRS

ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+05:30$")


class InputRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")      # gold-label columns, if present, are discarded

    transcript_id: str
    call_started_at: str
    timezone: str = "Asia/Kolkata"
    transcript: str = ""

    @field_validator("transcript_id", mode="before")
    @classmethod
    def _id(cls, v):
        v = "" if v is None else str(v).strip()
        if not v:
            raise ValueError("transcript_id is empty")
        return v

    @field_validator("transcript", mode="before")
    @classmethod
    def _text(cls, v):
        return "" if v is None else str(v)

    @field_validator("call_started_at")
    @classmethod
    def _ts(cls, v):
        parse_call_time(v)                         # raises ValueError if not an ISO timestamp
        return v


class OutputRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transcript_id: str
    disposition: Literal["Appointment Scheduled", "Follow-up Required", "Not Interested",
                         "Invalid Lead", "Unable to Assess"]
    sub_disposition: str
    lead_quality: Literal["High", "Medium", "Low", "Not Qualified", "Not Assessable"]
    next_call_at: Optional[str] = None

    @model_validator(mode="after")
    def _consistent(self):
        if self.sub_disposition not in VALID_PAIRS[self.disposition]:
            raise ValueError(f"invalid pair {self.disposition} / {self.sub_disposition}")
        if self.next_call_at is not None and not ISO_RE.match(self.next_call_at):
            raise ValueError("next_call_at must be ISO with seconds and +05:30")
        return self


def fallback_output(transcript_id) -> dict:
    """Safe, schema-valid record used when a record cannot be processed at all."""
    return OutputRecord(
        transcript_id=str(transcript_id), disposition="Unable to Assess",
        sub_disposition="Incomplete Conversation", lead_quality="Not Assessable", next_call_at=None,
    ).model_dump()


def read_jsonl(path):
    """Yield (line_no, dict_or_None, error_or_None) so one bad line never aborts the run."""
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
                yield i, (obj if isinstance(obj, dict) else None), (None if isinstance(obj, dict) else "not an object")
            except json.JSONDecodeError as e:
                yield i, None, f"invalid JSON: {e}"
