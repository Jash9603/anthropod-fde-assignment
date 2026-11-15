# outputs/

The submitted predictions for the 50 supplied calls.

| File | Committed | Contents |
|---|---|---|
| `predictions_50.jsonl` | yes | one JSON object per call with exactly `transcript_id`, `disposition`, `sub_disposition`, `lead_quality`, `next_call_at` (the submission file) |
| `predictions_50.jsonl.summary.json` | yes | model, settings, record counts, token usage, runtime |
| `predictions_50.jsonl.trace.jsonl` | no (git-ignored) | per-record extracted evidence, status, retries and tokens; it quotes transcript text, so it stays local |

Run your own experiments into this folder; everything here except this README and the two committed files above is
git-ignored.

## Provenance of `predictions_50.jsonl`
- Model `qwen/qwen3.8-27b`, `reasoning_effort=none`, `temperature=0`, `seed=7`, prompts in `../prompts/`.
- Generated with the same pipeline, prompts and settings as `src/run.py`. To save time the 50 records were spread over
  several Groq keys by a temporary script (since deleted), which does not change any per-record logic.
- One record (AVT-049) hit the daily token quota during that run and was **re-run through the same pipeline** a few
  minutes later; its result replaced the fallback line. It was not edited by hand. Qwen is deterministic here (two
  complete runs gave identical predictions for all 50 records), so the merged file equals an uninterrupted run.
- Re-verified: 50 lines, 50 unique IDs matching the source CSV, five keys each, valid parent/child pairs, ISO
  timestamps ending `+05:30`, 15 real JSON nulls.
- Score against the gold labels: `python scripts/evaluate.py --gold data/gold_50.jsonl --pred outputs/predictions_50.jsonl --split 30`
  gives 63.0 / 70 (74% exact match). See `../docs/error_analysis.md`.

To regenerate with the plain runner (about 35-45 minutes on one free-tier key):
`python src/run.py --input data/inputs_50.jsonl --output outputs/predictions_50.jsonl`
