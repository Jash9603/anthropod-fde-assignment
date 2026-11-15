# Task 1 - Error analysis and iteration log

## System under test
Groq **`qwen/qwen3.8-27b`**, `temperature=0`, `seed=7`, `reasoning_effort=none`, JSON mode, `max_tokens=4096`.
One LLM call per transcript extracts typed evidence (pydantic schema); deterministic Python applies the policy
(precedence, valid pairs, lead quality, all date arithmetic). Prompts: `prompts/system.md`, `prompts/user.md`.
Submitted predictions: `outputs/predictions_50.jsonl` (with `.trace.jsonl` evidence/usage log and `.summary.json`).

How the submitted file was produced: one 50-record run (a temporary script that spread the records over several
Groq keys to save time; same pipeline, prompt and settings as `src/run.py`, since removed) plus a separate re-run of
AVT-049, because the daily token quota ran out on the last record of the main run. Qwen is deterministic here (see
"Determinism"), so merging the re-run is equivalent to one uninterrupted run.

## Results (50 supplied calls)

| Field | **Qwen (submitted)** | gpt-oss-120b (low), full 50 |
|---|---|---|
| disposition | **96.0%** (48/50) | 96.0% |
| sub_disposition | **80.0%** (40/50) | 72.0% |
| lead_quality | **92.0%** (46/50) | 94.0% |
| next_call_at | **94.0%** (47/50) | 80.0% |
| whole-record exact match | **74.0%** (37/50) | 62.0% |
| weighted label score | **63.0 / 70** | 58.9 / 70 |

Development vs held-out. Records 1-30 were used to develop the prompt (on gpt-oss-120b errors); records 31-50 were
not looked at until the prompt was frozen.

| | records 1-30 (development) | records 31-50 (held out) |
|---|---|---|
| Qwen exact match / label score | 73.3% / 65.0 | **75.0% / 60.0** |
| gpt-oss-120b exact match / label score | 73.3% / 62.8 | 45.0% / 53.0 |

Qwen shows no development-to-held-out drop, whereas gpt-oss-120b did (73% to 45%), i.e. the prompt had been fitted to
gpt-oss-120b's quirks. **Honest expectation for the private set: about 55-62 / 70 on labels (roughly 60-75% exact
match).** Only 20 held-out records exist, so the uncertainty is about +/-10 points.

## Model comparison
**Full 50 records:** Qwen vs gpt-oss-120b, table above. Qwen is better on sub_disposition (+8 pts) and next_call_at
(+14 pts), equal on disposition, slightly worse on lead_quality (-2 pts).

**Three models on 10 records (31-40) only.** Because of free-tier quota, the third model could not be run on all 50
calls, so this comparison is indicative, not statistically conclusive (one record = 10 pts).

| Model | Disposition | Sub-disp. | Lead quality | Next call | Exact | Label score | Tokens in / out |
|---|---|---|---|---|---|---|---|
| `openai/gpt-oss-120b` (reasoning low) | 80% | 40% | 80% | 60% | 3/10 | 44.0 / 70 | 57,447 / 7,196 |
| `openai/gpt-oss-20b` (reasoning low) | 80% | 40% | 60% | 70% | 3/10 | 43.0 / 70 | 57,447 / 5,238 |
| **`qwen/qwen3.8-27b`** (reasoning none) | **100%** | **80%** | **100%** | **100%** | **8/10** | **66.0 / 70** | 59,581 / 5,090 |

The prompt was iterated on gpt-oss-120b errors and never on Qwen output, so the comparison, if anything, favoured
gpt-oss. Qwen was chosen on this evidence and confirmed on all 50 records. Reasoning effort `medium` on gpt-oss-120b was
tested on 30 records and was worse than `low` (60% vs 70-73% exact) at about 3x the output tokens.

## Determinism
Two complete 50-record Qwen runs with identical settings produced **identical predictions for all 50 records**.
gpt-oss-120b, in contrast, changed labels between runs (for example AVT-015 and AVT-030 flipped between three
different sub-dispositions across three runs), so its measured accuracy carried about +/-1-2 records of noise per 30.

## Main failure patterns (Qwen, 13 of 50 records not exactly right)

1. **Sub-disposition judgement calls (8 records on a correct disposition: AVT-001, 013, 015, 020, 030, 032, 038, 049).**
   When several reasons are mentioned the policy asks for the customer's "main" blocker, and the gold label is often
   not the one a reader would pick. Confusions: Travel Constraint vs Family Discussion (001, 020: a husband/companion
   is away or timing is a problem), Current Treatment vs Travel Constraint or Treatment Concern (030, 038), Cost Concern
   vs Family Discussion or Vague Deferral (049, 032), Information Requested vs Travel (013), Further Discussion vs
   Treatment Concern (015). Some gold labels are not mutually consistent (013 and 015 end almost identically but get
   different labels), which caps the achievable accuracy. Not fixed.
2. **Tentative visit plan plus "callback to confirm" over-read as a booking or commitment (AVT-041, AVT-026).**
   AVT-041: the customer said he was planning to come on Friday 4-5 pm and the agent proposed a Wednesday call to confirm
   the time; the model marked the slot as confirmed, so the call became Appointment Scheduled / High (4 fields wrong).
   Under D3 a tentative plan with a callback to confirm is not a booking. AVT-026: a similar pattern inflated lead quality
   to High instead of Medium. In AVT-041 the evidence object also quoted a travel and a treatment concern while the
   `blockers` list stayed empty, i.e. the model's own flags were inconsistent with its evidence.
3. **Spurious refusal (AVT-042).** An irritated, hard-of-hearing customer said "Forget it"; the model read it as an
   unconditional refusal (Not Interested). Gold: Follow-up / Treatment Concern, lead quality Not Assessable. All three
   models made this error in some run (4 fields).
4. **Event-qualified relative date (AVT-024).** The agent said "I will call you back once next week after Dussehra" and
   the customer agreed. Rule F12 makes that vague (+3 days); the model extracted plain `next_week` and the rules produced
   the next Monday. This is a prompt gap (the F12 case is not spelled out) that was found only after the prompt was
   frozen; fixing it requires a full re-run, which the exhausted daily quota did not allow.
5. **Lead quality Low vs Medium (AVT-022).** The customer said they did not want "that treatment"; gold treats this as
   Low. Judgement call.

## Changes made during iteration

| Step | Change | Effect |
|---|---|---|
| Baseline (gpt-oss-120b, 15 calls) | first prompt | 53% exact |
| Code | day-of-month-only dates ("on the 15th") resolve to the next occurrence | fixed a booking that was rejected for lack of a month |
| Prompt | unresolved means unresolved over the whole call; sharper Current Treatment / Treatment Concern; `exploratory_only` defaults false | removed false Low lead quality |
| Prompt | Travel Constraint covers "temporarily away / can only come later"; Cost Concern covers discounts and insurance | fewer missed blockers |
| Prompt | one evidence slot per blocker category | model examines all five |
| Code | agreed callback tied to an unresolved event is vague (+3 days), per F10/F12 | correct fallback for event-conditional callbacks |
| Prompt (v4) | a booking the customer accepts counts even if day and time were agreed in different parts of the call; "I will tell you in 15 minutes" is an interval callback | fixed two missed bookings and one interval callback on gpt-oss |
| Infra | rate-limit waits do not consume attempts; daily-quota detection (fail fast) | no hung or failed records from throttling |
| Model | switched from gpt-oss-120b to Qwen after the 10-record comparison, confirmed on all 50 | 58.9 to 63.0 label score; held-out exact 45% to 75% |
| Code | `413 Request too large`: the client shortens the transcript (keeps the start and the end) and resends | fixed a deterministic failure on one long Hinglish transcript (AVT-020, 8000 chars kept) |
| Code | the pipeline converts any unexpected extractor exception into a valid fallback record | a client bug can no longer lose a record |

Rejected: more reasoning effort (worse), further prompt tuning against single calls (overfitting).

## Runtime, tokens, cost (final 50-call run)
- 296,724 prompt + 25,343 completion tokens in total (about 5.9k in / 0.5k out per call; the system prompt is about 3.6k
  tokens of that). One transcript was shortened after a 413 (AVT-020).
- Wall-clock: 467 s for the main run over 5 keys, plus 2 s for the AVT-049 re-run. Average per-call latency 44 s, which
  is dominated by rate-limit waits; a single key on the free tier runs at roughly one call per minute, so a sequential
  50-call run takes about 35-45 minutes.
- Cost: not estimated. Current Groq prices for this model were not verified; apply the published per-token prices to the
  token counts above.
- 50 of 50 records ok, 0 invalid outputs.

## Limitations and risks
- Only 50 labeled calls, with some inconsistent gold labels: measurement is noisy and easy to overfit.
- The prompt was developed on gpt-oss-120b outputs and then used with Qwen unchanged; Qwen-specific tuning might help
  further but was not attempted. Qwen was run with reasoning disabled (`reasoning_effort=none`).
- The model comparison on all 50 calls covers two models; `gpt-oss-20b` was only compared on 10 records.
- Daily token quota: three full 50-call runs in one day (about 900k tokens) exhausted several keys. A full run costs
  about 320k tokens, which can exceed a single free-tier key's daily limit. The runner then marks the key exhausted and
  writes safe fallback records (`llm_failed` in the trace) instead of hanging.
- Long transcripts: after a 413 the middle of the transcript is dropped, so evidence from the middle of such a call can
  be lost (the end, which carries the final state, is always kept).
- Known unfixed prompt gaps: event-qualified relative dates ("next week after Dussehra") and tentative plans with a
  callback to confirm (patterns 2 and 4 above).
