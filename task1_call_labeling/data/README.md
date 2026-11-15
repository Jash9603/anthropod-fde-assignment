# data/

Local data files. Everything here except this README and `.gitkeep` is **git-ignored**: the call transcripts and gold
labels are the hiring team's assignment material and must not be published.

| File | What it is | How to get it |
|---|---|---|
| `inputs_50.jsonl` | the 50 calls, input fields only (`transcript_id`, `call_started_at`, `timezone`, `transcript`) | generated from the CSV (below) |
| `gold_50.jsonl` | gold labels for the same calls, used only by `scripts/evaluate.py` | generated from the CSV (below) |
| `*.csv` | CSV files shown in the web app (also read from the repository-level `data/` folder) | export the sheet's *50 Labeled Calls* tab, or upload one in the app |

Generate the JSONL files from the exported CSV (kept at `../data/Data_Calls.csv`, outside this folder):

```powershell
python scripts\csv_to_jsonl.py --input ..\data\Data_Calls.csv --inputs-out data\inputs_50.jsonl --gold-out data\gold_50.jsonl
```

CSV format: columns `transcript_id`, `call_started_at` (ISO timestamp with offset), `timezone`, `transcript`
(multiline text is fine) and optionally the four gold columns `disposition`, `sub_disposition`, `lead_quality`,
`next_call_at`. The sheet's literal `null` becomes JSON null. Gold columns are never fed to the model.
