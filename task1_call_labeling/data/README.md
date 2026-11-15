# data/

CSV files uploaded from the dashboard are saved here. Everything in this folder except this README is git-ignored:
call transcripts and gold labels must not be published.

CSV columns: `transcript_id`, `call_started_at` (ISO timestamp with offset), `transcript` (multiline text is fine),
optional `timezone`, and optionally the gold columns `disposition`, `sub_disposition`, `lead_quality`, `next_call_at`
(shown for comparison only, never fed to the model).

For batch evaluation, convert a CSV to JSONL with `scripts/csv_to_jsonl.py` (see [docs/design.md](../docs/design.md)).
