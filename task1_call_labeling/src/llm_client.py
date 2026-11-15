"""Groq chat client with strict JSON handling, retries and usage tracking.

GroqExtractor.extract(...) never raises: it returns an LLMResult whose `extraction`
is None when every attempt failed (the pipeline then uses safe defaults).
"""
import json
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from schema import Extraction

EXPECTED_KEYS = list(Extraction.model_fields.keys())
MIN_KEYS_PRESENT = 8        # a reply with fewer expected top-level keys is treated as malformed


def parse_json_object(text: str) -> dict:
    """Parse the first JSON object in `text` (tolerates code fences / surrounding prose)."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("empty reply")
    t = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I).strip()   # reasoning models
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.I)
    try:
        obj = json.loads(t)
    except json.JSONDecodeError:
        a, b = t.find("{"), t.rfind("}")
        if a == -1 or b <= a:
            raise ValueError("no JSON object found")
        obj = json.loads(t[a:b + 1])
    if not isinstance(obj, dict):
        raise ValueError("JSON is not an object")
    return obj


def shrink_transcript(text: str, factor: float = 0.7, head: int = 3000) -> str:
    """Keep the start and (mostly) the end of a transcript, dropping the middle, so it is ~`factor` of its size."""
    target = max(int(len(text) * factor), head + 1000)
    if len(text) <= target:
        return text
    return text[:head] + "\n[... middle of transcript omitted ...]\n" + text[-(target - head):]


def looks_complete(obj: dict) -> bool:
    return sum(k in obj for k in EXPECTED_KEYS) >= MIN_KEYS_PRESENT


@dataclass
class LLMResult:
    extraction: Optional[dict] = None
    raw: str = ""
    attempts: int = 0
    latency_s: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    error: Optional[str] = None
    rate_limit_waits: int = 0
    shrinks: int = 0
    events: list = field(default_factory=list)


class GroqExtractor:
    def __init__(self, model, system_prompt, user_template, temperature=0.0, max_tokens=4096,
                 timeout=90.0, max_attempts=4, seed=7, client=None, reasoning_effort=None, max_rate_limit_waits=12,
                 max_shrinks=3):
        self.max_rate_limit_waits = max_rate_limit_waits
        self.max_shrinks = max_shrinks       # how many times an oversized request may be shortened and resent
        self.max_rate_limit_wait = 120.0     # longer waits than this (seconds) mean the quota is spent
        self.exhausted = False               # set when the key's daily/long rate limit is hit
        self.reasoning_effort = reasoning_effort     # "low" | "medium" | "high" for reasoning models
        self.model, self.system_prompt, self.user_template = model, system_prompt, user_template
        self.temperature, self.max_tokens, self.max_attempts, self.seed = temperature, max_tokens, max_attempts, seed
        self.json_mode = True
        if client is None:
            from groq import Groq                      # imported lazily so unit tests need no network/package
            client = Groq(timeout=timeout, max_retries=0)   # we do our own retries
        self.client = client

    # ---- prompt -------------------------------------------------------------------
    def build_messages(self, call_started_at, call_weekday, transcript):
        user = (self.user_template
                .replace("{{CALL_STARTED_AT}}", call_started_at)
                .replace("{{CALL_WEEKDAY}}", call_weekday)
                .replace("{{TRANSCRIPT}}", transcript))
        return [{"role": "system", "content": self.system_prompt}, {"role": "user", "content": user}]

    # ---- one chat call --------------------------------------------------------------
    def _chat(self, messages):
        kw = dict(model=self.model, messages=messages, temperature=self.temperature,
                  max_tokens=self.max_tokens, seed=self.seed)
        if self.json_mode:
            kw["response_format"] = {"type": "json_object"}
        if self.reasoning_effort:
            kw["extra_body"] = {"reasoning_effort": self.reasoning_effort}
        return self.client.chat.completions.create(**kw)

    @staticmethod
    def _retry_after(exc):
        try:
            return float(exc.response.headers.get("retry-after"))
        except Exception:
            return None

    def _rate_limit_wait(self, exc):
        """Seconds to wait after a 429: retry-after header, else 'try again in 1m3.2s' from the message, else 20s."""
        wait = self._retry_after(exc)
        if wait is None:
            m = re.search(r"try again in (?:(\d+)m)?\s*([\d.]+)s", str(exc))
            if m:
                wait = int(m.group(1) or 0) * 60 + float(m.group(2))
        return (wait if wait is not None else 20.0) + 1.0

    # ---- public ------------------------------------------------------------------------
    def extract(self, call_started_at, call_weekday, transcript) -> LLMResult:
        res = LLMResult()
        if self.exhausted:                               # key already spent: fail fast, do not hammer the API
            res.error = "key exhausted (daily/long rate limit)"
            return res
        current = transcript
        messages = self.build_messages(call_started_at, call_weekday, current)
        t0 = time.time()
        attempt = 0
        while attempt < self.max_attempts:
            attempt += 1
            res.attempts = attempt
            try:
                resp = self._chat(messages)
            except Exception as e:                      # network, rate limit, 4xx/5xx, timeout
                name, msg = type(e).__name__, str(e)
                res.events.append(f"attempt {attempt}: {name}: {msg[:120]}")
                res.error = f"{name}: {msg[:200]}"
                if name == "RateLimitError":
                    wait = self._rate_limit_wait(e)
                    if "per day" in msg.lower() or "(tpd)" in msg.lower() or wait > self.max_rate_limit_wait:
                        # daily quota (or a very long wait): this key is spent, waiting would only stall the run
                        self.exhausted = True
                        res.error = f"key exhausted (daily/long rate limit, wait={wait:.0f}s)"
                        res.events.append(res.error)
                        break
                    if res.rate_limit_waits < self.max_rate_limit_waits:
                        # ordinary per-minute throttling: wait as told and retry WITHOUT using an attempt
                        res.rate_limit_waits += 1
                        attempt -= 1
                        time.sleep(wait)
                        continue
                if (getattr(e, "status_code", None) == 413 or "request too large" in msg.lower()) \
                        and res.shrinks < self.max_shrinks:
                    # request exceeds the model's per-request token limit: shorten the transcript (the end, which holds
                    # the final evidence, is kept) and resend; this does not use an attempt
                    shorter = shrink_transcript(current, 0.7)
                    if len(shorter) < len(current):
                        res.shrinks += 1
                        current = shorter
                        messages = self.build_messages(call_started_at, call_weekday, current)
                        res.events.append(f"request too large: transcript shortened to {len(current)} chars")
                        attempt -= 1
                        continue
                if name == "BadRequestError" and "json_validate_failed" not in msg:
                    # unsupported option: drop reasoning_effort first, then JSON mode, and retry
                    if self.reasoning_effort:
                        self.reasoning_effort = None
                        res.events.append("dropped reasoning_effort (rejected by model)")
                        continue
                    if self.json_mode:
                        self.json_mode = False
                        res.events.append("disabled json_mode (rejected by model)")
                        continue
                if name in ("AuthenticationError", "PermissionDeniedError", "NotFoundError"):
                    break                               # retrying cannot help
                wait = self._retry_after(e) or min(2 ** attempt * 2, 60)
                if attempt < self.max_attempts:
                    time.sleep(min(wait, 90))
                continue

            usage = getattr(resp, "usage", None)
            res.prompt_tokens += getattr(usage, "prompt_tokens", 0) or 0
            res.completion_tokens += getattr(usage, "completion_tokens", 0) or 0
            text = (resp.choices[0].message.content or "") if resp.choices else ""
            res.raw = text
            try:
                obj = parse_json_object(text)
                if not looks_complete(obj):
                    raise ValueError("JSON missing most expected keys")
                res.extraction, res.error = obj, None
                break
            except ValueError as e:
                res.error = f"bad output: {e}"
                res.events.append(f"attempt {attempt}: {res.error}")
                # feed the problem back so the model can self-correct
                messages = messages + [
                    {"role": "assistant", "content": text[:4000]},
                    {"role": "user", "content": f"Your reply was not usable ({e}). Return ONLY one complete JSON "
                                                "object with all required keys, exactly in the specified format."},
                ]
        res.latency_s = round(time.time() - t0, 2)
        return res
