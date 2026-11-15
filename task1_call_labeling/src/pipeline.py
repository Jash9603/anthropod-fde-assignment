"""Per-record workflow: validate input -> guardrails -> LLM extraction -> rules -> validate output.

process_record never raises; it always returns a schema-valid output dict plus a trace dict.
"""
import re

from pydantic import ValidationError

from callback_time import parse_call_time
from io_models import InputRecord, OutputRecord, fallback_output
from rules import decide
from schema import normalize_extraction

MAX_CHARS = 40000          # ~10k tokens; far above a typical call, protects against abusive input
HEAD_CHARS = 4000          # when truncating keep the start and, above all, the END (final evidence)
MIN_ALPHA_CHARS = 15       # fewer letters than this -> nothing to assess, skip the LLM call


def sanitize_transcript(text: str, max_chars: int = MAX_CHARS):
    """Remove control chars, neutralise tag break-outs, bound the length. Returns (text, truncated)."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = re.sub(r"</?\s*transcript\s*>", "[tag removed]", text, flags=re.I)
    truncated = len(text) > max_chars
    if truncated:
        text = text[:HEAD_CHARS] + "\n[... middle of transcript omitted ...]\n" + text[-(max_chars - HEAD_CHARS):]
    return text.strip(), truncated


def has_content(text: str) -> bool:
    return len(re.findall(r"[^\W\d_]", text)) >= MIN_ALPHA_CHARS


def process_record(raw_record, extractor):
    trace = {"transcript_id": None, "status": "ok", "notes": []}
    rid = raw_record.get("transcript_id") if isinstance(raw_record, dict) else None
    trace["transcript_id"] = None if rid is None else str(rid)

    # 1. validate input
    try:
        rec = InputRecord.model_validate(raw_record)
    except (ValidationError, ValueError, TypeError) as e:
        trace.update(status="invalid_input", notes=[str(e)[:300]])
        return fallback_output(rid if rid not in (None, "") else "UNKNOWN"), trace

    text, truncated = sanitize_transcript(rec.transcript)
    if truncated:
        trace["notes"].append("transcript truncated")

    # 2. extraction (skip LLM when there is nothing to read)
    extraction, llm = None, None
    if not has_content(text):
        trace["notes"].append("empty/near-empty transcript: LLM skipped")
    else:
        now = parse_call_time(rec.call_started_at)
        llm = extractor.extract(rec.call_started_at, now.strftime("%A"), text)
        extraction = llm.extraction
        if llm.events:
            trace["events"] = llm.events[-6:]     # retries / rate limits, kept even when the record succeeded
        trace.update(attempts=llm.attempts, rate_limit_waits=llm.rate_limit_waits, latency_s=llm.latency_s,
                     prompt_tokens=llm.prompt_tokens, completion_tokens=llm.completion_tokens)
        if extraction is None:
            trace.update(status="llm_failed")
            trace["notes"] += llm.events[-3:]

    clean = normalize_extraction(extraction)          # validates / repairs; never raises
    trace["extraction"] = clean

    # 3. deterministic decision + output validation
    try:
        labels = decide(clean, rec.call_started_at)
        out = OutputRecord(transcript_id=rec.transcript_id, **labels).model_dump()
    except Exception as e:                            # defensive: should be unreachable
        trace.update(status="rules_error", notes=trace["notes"] + [f"{type(e).__name__}: {e}"[:300]])
        out = fallback_output(rec.transcript_id)
    return out, trace
