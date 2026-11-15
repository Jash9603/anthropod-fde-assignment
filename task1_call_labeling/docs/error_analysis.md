# Task 1 - Error analysis and iteration log

## System under test
Groq `openai/gpt-oss-120b`, `temperature=0`, `seed=7`, `reasoning_effort=low`, JSON mode, `max_tokens=4096`.
One LLM call per transcript extracts typed evidence (pydantic schema); deterministic Python applies the policy
(precedence, valid pairs, lead quality, all date arithmetic). Final prompt: `prompts/system.md` + `prompts/user.md`.
Submitted predictions: `outputs/predictions_50.jsonl` (with its `.trace.jsonl` evidence/usage log and `.summary.json`).

## Results (50 supplied calls)

| Field | v3 | **v4 (submitted)** |
|---|---|---|
| disposition | 96.0% | **96.0%** |
| sub_disposition | 72.0% | **72.0%** |
| lead_quality | 92.0% | **94.0%** |
| next_call_at | 82.0% | **80.0%** |
| whole-record exact match | 62.0% | **62.0%** (31/50) |
| weighted label score | 59.0 / 70 | **58.9 / 70** |

Development vs held-out (records 1-30 were used to develop the prompt; 31-50 were not looked at until v3 was frozen):

| | records 1-30 (dev) | records 31-50 (held out, v3) | records 31-50 (v4) |
|---|---|---|---|
| exact match | 73.3% | 45.0% | 45.0% |
| weighted label score | 62.8-64.2 | 51.2 | 53.0 |

**Honest expectation for the private set: about 50-55 / 70 on labels (roughly 45-60% exact match).**
The 73% dev figure is optimistic (tuned on those records). v4 edits were made after the held-out errors were
inspected, so 31-50 is no longer a perfectly clean estimate either.

## Noise floor
Three runs on the same 30 records with identical prompt/settings (low, low, medium effort):
exact match 22, 21 and 18 of 30. The two `low` runs differ by one record, and individual calls flip labels between runs
even at temperature 0 (e.g. AVT-015: Information Requested / Information Requested / Cost Concern). Differences of
one or two records between prompt versions are therefore not meaningful.
`reasoning_effort=medium` was worse (60% vs 70-73%) and used about 3x the output tokens, so `low` was kept.
Other models were compared on a small sample, see the next section.

## Model comparison (10 records, three models)
Same prompt, same code, records 31-40 (`--offset 30 --limit 10`), one Groq key, temperature 0, seed 7.
**Only 10 records were used because of the free-tier quota; running every model on all 50 calls would exhaust the daily
token limits.** One record is 10 percentage points, so treat this as indicative, not statistically conclusive.

| Model | Disposition | Sub-disp. | Lead quality | Next call | Exact match | Label score | Tokens in / out | Runtime |
|---|---|---|---|---|---|---|---|---|
| `openai/gpt-oss-120b` (reasoning low) | 80% | 40% | 80% | 60% | 3/10 | 44.0 / 70 | 57,447 / 7,196 | 370 s |
| `openai/gpt-oss-20b` (reasoning low) | 80% | 40% | 60% | 70% | 3/10 | 43.0 / 70 | 57,447 / 5,238 | 415 s |
| `qwen/qwen3.8-27b` (reasoning none) | **100%** | **80%** | **100%** | **100%** | **8/10** | **66.0 / 70** | 59,581 / 5,090 | 454 s |

- Qwen got both bookings (AVT-037, AVT-039) that both gpt-oss models missed, and made only two sub-disposition
  errors (AVT-032 Vague Deferral vs Cost Concern, AVT-038 Current Treatment vs Treatment Concern), both judgement calls.
- The prompt was iterated on gpt-oss-120b errors (including some of these records), never on Qwen output, so the
  comparison if anything favours gpt-oss. A 5-record exact-match gap is larger than the run-to-run noise measured earlier
  (about 1-2 records out of 30).
- Runtime is dominated by Groq's per-minute token limit on a single key (9-11 rate-limit waits per run), so it says
  little about model speed. Token usage is similar across models. Cost is not estimated here because current Groq
  prices for these models were not verified; apply the published prices to the token counts above.
- Settings actually used (from the run summaries): gpt-oss models `reasoning_effort=low`; Qwen `reasoning_effort=none`;
  JSON mode on for all three.
- **The submitted predictions (`outputs/predictions_50.jsonl`) were produced with `gpt-oss-120b`**, before this
  comparison. The comparison suggests Qwen would score higher; confirming that needs a full 50-record Qwen run.

## Main failure patterns (v4 errors)

1. **Sub-disposition judgement (12 of the 14 sub-disposition errors; the other 2 follow a wrong disposition).** The policy asks for the
   customer's "main" unresolved blocker, but calls often contain several (family + travel + treatment doubts).
   Typical confusions: Travel Constraint vs Family Discussion (AVT-001, 034, 048), Travel Constraint vs Treatment
   Concern (AVT-014, 047), Cost Concern vs Family Discussion/Specific Callback (AVT-032, 049, 029),
   Treatment Concern vs Vague Deferral (AVT-018). Several gold labels are not mutually consistent
   (AVT-013 and AVT-015 end the same way but get different labels), which caps achievable accuracy. Not fixed.
2. **Fallback callback +1 vs +3 days (AVT-013, 015, 022, 041, 048).** Whether "I'll send the details, you check"
   is a vague postponement is applied inconsistently by gold (19 of 24 fallback callbacks are +3, five are +1).
   A blanket "+3 unless the call ended abruptly" rule was tested on paper against gold and breaks even with the
   LLM-driven decision, so it was not adopted.
3. **Missed or contested bookings (AVT-037).** The customer says "don't confirm it ... but keep the appointment
   for 2 o'clock, I'll come". Gold counts it as booked; the model does not. One wrong disposition costs four fields.
4. **Callback amendments (AVT-040) and unacknowledged agent proposals (AVT-041).** The model sometimes keeps an
   earlier "after Diwali" vagueness when the customer later accepted "next week", and treats an unacknowledged
   agent proposal as vague.
5. **Spurious refusal (AVT-042, regressed in v4).** A hard-of-hearing, irritated customer ("Forget it") was read as
   Explicit Refusal; gold is Follow-up / Treatment Concern with lead quality Not Assessable.
   This call flipped between runs, so it is mostly noise.
6. **Callback time of day (AVT-011, 044).** A callback hour was missed in the evidence (gold 15:00 / 18:00, predicted 11:00).

## Changes made during iteration

| Step | Change | Effect |
|---|---|---|
| Baseline (15 calls) | first prompt | 53% exact |
| Code | day-of-month-only dates ("on the 15th") resolve to next occurrence | fixed a booking missed because no month was given |
| Prompt | unresolved means unresolved over the whole call; sharper Current/Treatment Concern; `exploratory_only` defaults false | removed false Low lead quality |
| Prompt | Travel Constraint covers "temporarily away / can only come later"; Cost Concern covers discounts and insurance questions | fewer missed blockers |
| Prompt | evidence slot for each blocker category | model examines all five |
| Code | agreed callback tied to an unresolved event is vague (+3 days), per F10/F12 | fixed AVT-024 |
| Infra | rate-limit waits do not consume attempts; daily-quota detection; shared work queue for parallel testing | no failed records in final runs |
| v4 prompt | booking accepted by the customer counts even if date and time were agreed in different parts of the call; definite "I'll tell you in 15 minutes" is an interval callback | fixed AVT-039 and AVT-047, net zero overall because of unrelated noise |

Rejected: more reasoning effort (worse), further prompt tuning against single calls (overfitting; changes fixed one call and broke another).

## Runtime, tokens, cost (final 50-call run, v4)
- 287,058 prompt + 33,873 completion tokens (about 5.7k in / 0.7k out per call; the system prompt is about 3.5k tokens).
- 273 s wall-clock, measured in a temporary parallel testing mode over 8 keys (since removed from the code).
  A single key is rate-limited to about one call per minute on the free tier, so a sequential run takes roughly
  30-40 minutes (about 35 s per call on average, measured per call in the trace).
- Estimated cost about $0.06 at an assumed $0.15 / $0.60 per million input/output tokens (list prices should be verified).
- 0 failed records, 0 invalid outputs; 53 rate-limit waits, all recovered.

## Limitations and known risks
- Only 50 labeled calls, with some inconsistent gold labels, so tuning is easy to overfit and measurement is noisy.
- Groq output is not exactly repeatable at temperature 0.
- Daily token quota: a 50-call run uses about 320k tokens, which can exceed a free-tier single-key daily limit.
  The runner then marks the key exhausted and returns safe fallback records (`llm_failed` in the trace) instead of hanging.
- The prompt is about 3.5k tokens; trimming it would reduce cost and quota risk.
- Only `gpt-oss-120b` was evaluated on all 50 calls; the other two models were compared on 10 records.
