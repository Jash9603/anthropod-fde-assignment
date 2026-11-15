# Requirements checklist (assignment sheet, policy `assignment-v2`)

Each row of the sheet's *Assignment* tab, checked against this repository. Status: **met**, or **met with a note**.

| Sheet item | Requirement | Where / how it is met | Status |
|---|---|---|---|
| Model access | Open model on Groq, own account and key, record the exact model ID | `qwen/qwen3.8-27b` on Groq; key read from `GROQ_API_KEY`; model ID in `README.md`, in the runner defaults and in `outputs/predictions_50.jsonl.summary.json` | met |
| Build | Own prompt and a small reproducible runner; no per-record hardcoding, external search, source-system access or manual correction | `prompts/` + `src/run.py`. No transcript IDs appear in any code or prompt (checked). No network access other than the Groq call. Predictions are pipeline output only (one record was re-run through the same pipeline after a quota error, not edited by hand; see `outputs/README.md`) | met |
| Input contract | Feed only `transcript_id`, `call_started_at`, `timezone`, `transcript`; gold labels never an input | `io_models.InputRecord` drops every other key; gold files are used only by `scripts/evaluate.py`; the web app passes four fields and shows gold afterwards for comparison only | met |
| Output contract | Exactly five keys; allowed labels; valid child label; ISO with `+05:30` or JSON null | `io_models.OutputRecord` validates every record before it is written (pair check, exact ISO pattern); the submitted file was re-verified: 50 lines, 5 keys each, valid pairs, 15 real JSON nulls | met |
| Prompt ownership | Submit complete system/user prompt templates, examples, pre/post-processing and deterministic logic; no lookups by ID, hash or personal details | `prompts/system.md`, `prompts/user.md` (complete); preprocessing in `pipeline.py`; post-processing and policy logic in `schema.py`, `rules.py`, `callback_time.py`. Only short synthetic examples are used; no label lookups | met |
| Reproducibility | README with one command taking an input JSONL path and writing prediction JSONL; key from env; dependency versions, model ID, temperature and other settings, retries, JSON parsing, timeouts | `README.md` (*Run the batch pipeline*, *Configuration*, *Model and generation settings*); all settings in `config.toml`; versions pinned in `requirements.txt` | met |
| Testing | Develop and test on the labeled 50; report per-field accuracy, whole-record exact match, failure patterns, changes made; training-set performance alone is not the score | `docs/error_analysis.md`: per-field table, exact match, development vs held-out split (records 31-50 never used to tune the prompt), five failure patterns, full iteration log | met, with a note: the 20 held-out records are few, and were used once to pick the model |
| Submission | Source code, final prompts, README, predictions for all 50, concise error analysis with runtime, token usage and estimated cost where available; no API keys or secrets | All present. Tokens and runtime reported. **Cost is not estimated**: current Groq prices for the model were not verified, so the report gives token counts instead. `.env` is git-ignored and must be left out of any archive | met, cost not estimated |
| Private evaluation | Frozen submission is run on 50 unseen calls under the same rules | The same one-command runner takes any input JSONL; no per-record state; guardrails and fallbacks keep a record from being lost | met |
| Evaluation weights | Label accuracy (70), reliable runnable implementation (15), error analysis and iteration (10), clarity and reproducibility (5) | Unit tests, retry / rate-limit / 413 / quota handling and fallback records; `docs/error_analysis.md`; README, per-folder READMEs and this checklist | met |
| Fairness | Settings are recorded; no silent model substitution | The client never changes the model. If the model rejects an optional setting (`reasoning_effort`, JSON mode) the client drops that setting and logs it; the settings actually used are written to the run summary | met |
| Policy version | `assignment-v2`, supplied definitions authoritative, each call stands alone | Rules implemented from the *Label Rules* tab (D1-D6, SUB, LQ, F1-F12); the sheet's boundary examples EX1-EX6 are unit tests; no CRM or history is assumed | met |
| Scoring contract | Unique IDs, valid pairs, real JSON null, ISO with seconds and `+05:30`; correct sub-disposition only counts with the correct parent | Output validation enforces all of it; `scripts/evaluate.py` scores exactly this way | met |
| Data format and access | Export CSV preserving multiline text; translate the sheet's `null` to JSON null; infer roles from dialogue without editing the transcript | `scripts/csv_to_jsonl.py` reads with `newline=""` (multiline preserved) and converts `null`; transcripts are passed unedited except length-capping and control-character removal for safety | met |
| Delivery | Predictions for the 50 supplied IDs as JSONL, one object per line; evaluator supplies unseen input-only records through the same runner | `outputs/predictions_50.jsonl`; runner accepts input-only JSONL | met |
| Approach hint (recommended) | Smaller evidence questions for the LLM, then Python combines them into the four labels | This is the architecture: typed evidence schema (`schema.py`) plus deterministic `rules.py` / `callback_time.py` | followed |

## Policy rule coverage (*Label Rules* tab)
Where each rule lives. "Code" = deterministic and unit-tested; "prompt" = the LLM extracts the evidence and Python
applies the rule. The sheet's boundary examples EX1-EX6 are unit tests (`tests/test_rules.py`).

| Rule | What it says (short) | Implemented in | Status |
|---|---|---|---|
| PAIR | valid disposition / sub-disposition pairs | `rules.VALID_PAIRS`; enforced again by `io_models.OutputRecord` | met |
| D1, SUB (Invalid Lead) | wrong contact, no pain need, test, under-15, outside area; distance alone is not invalid; missing age/duration is not exclusion | prompt (evidence `invalid_reasons`); label and tie-break order in `rules.py` | met (no invalid case exists in the 50 calls, so it is untested on real data) |
| D2 | unconditional final refusal / stop contact; objections and "let me think" are not refusal; reversed refusal superseded | prompt (final-state rule, `final_refusal`); `rules.decide_disposition` | met |
| D3 | booking needs a mutually confirmed date and a clock time or window; offers, tentative plans and "callback to confirm" are not bookings; Online / Rescheduled | prompt (`consultation.*`); `rules._appointment_confirmed`, modality and Rescheduled precedence | **partly**: the model sometimes reads a tentative plan plus "callback to confirm" as a booking (AVT-041) |
| D4, D5 | Follow-up = open relevant discussion; Unable to Assess = no meaningful evidence | prompt (`relevant_discussion`); `rules.decide_disposition` | met |
| D6 | outcome precedence Invalid > Not Interested > Appointment > Follow-up > Unable | order of checks in `rules.decide_disposition`; `test_precedence_and_suppression` | met |
| SUB (Follow-up) and tie-breaking | final main blocker; otherwise Specific Callback, Information Requested, Vague Deferral, Further Discussion; fixed tie-break order | `rules.followup_sub` (`primary_blocker`, then the policy order); `test_blocker_tiebreak_and_primary` | met (choosing the "main" blocker is a judgement call and the largest error source, see the error analysis) |
| LQ (all) | Not Qualified / Not Assessable / Low / High / Medium in the published order; High only for a feasible commitment on date offsets 0-6 with no blocker; offset 7 is Medium | `rules.decide_lead_quality`; `test_ex6_severity_and_day7` | met |
| F1, F2 | IST reference time; null for Invalid, Not Interested, Unable to Assess | `callback_time.parse_call_time`; `rules.decide_next_call` | met |
| F3 | final callback proposed by either side and acknowledged; consultation slot or sending info is not a callback; callback may coexist with an appointment | prompt (`callback.agreed`); `rules._specific_callback`; `test_appointment_with_distinct_callback` | met |
| F4, F5 | relative days, weekdays, next/this week, 11:00 default, 1-7 PM / 8-11 AM / 12 noon, part-of-day times | `callback_time.resolve_date` / `resolve_clock`; `TestCallbackTime` | met |
| F6 | month/day without year = next future occurrence; reject past dates and past same-day times, no silent repair | `callback_time.resolve_callback`; `test_absolute_dates`, `test_past_same_day_time_rejected` | met |
| F7, F8 | +3 days at 11:00 for an explicit vague postponement; +1 day for other Follow-up; null for an appointment without a distinct callback | `rules._is_vague`, `decide_next_call`; `test_ex2`, `test_ex4`, `test_past_callback_is_not_vague` | met |
| F9 | only the final next-step agreement; vague cancellation of a specific time invokes F7 | prompt (final state; `agreed=false` plus `vague_postponement`); `rules.decide_next_call` | met |
| F10 | intervals keep seconds; two-date window takes the earliest; "after 5" and "around 5" use the stated time; unbounded after-event is vague | `callback_time` (`in_n_minutes/hours`, `unresolved`); prompt for the windows; `test_intervals_keep_seconds` | met |
| F11 | one month = same day next month, clamped, 11:00; bare "next month" = the 1st | `callback_time.resolve_date`; `test_months` | met (the "loose restatement of an accepted interval" clause relies on the prompt's final-state / amendment wording only) |
| F12 | "may call", opening hours, contact-person availability are not callbacks; definite "will call tomorrow" + ack is one; **next week qualified by an unresolved event is vague** | prompt; `rules._is_vague` (an agreed callback with an unresolved date counts as vague) | **partly**: the event-qualified "next week after Dussehra" case is not spelled out in the prompt, so the model resolved it to Monday (AVT-024) |

## Known limitations (also in the error analysis)
- Cost is not estimated (price not verified).
- Two prompt gaps were found after the prompt was frozen and are not fixed: event-qualified relative dates ("next week
  after Dussehra") and tentative plans with a callback to confirm.
- Only `qwen/qwen3.8-27b` and `openai/gpt-oss-120b` were evaluated on all 50 calls; `openai/gpt-oss-20b` only on 10.
- The daily free-tier token quota limits how often the full 50-call run can be repeated.
