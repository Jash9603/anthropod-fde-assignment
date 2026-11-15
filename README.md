# Anthropod FDE Assignment

Two independent tasks. Each folder is self-contained (own README, requirements, outputs).

| Task | Folder | Goal | Status |
|------|--------|------|--------|
| 1 | `task1_call_labeling/` | Label call transcripts: disposition, sub_disposition, lead_quality, next_call_at (Groq LLM + deterministic rules) | done |
| 2 | `task2_gender_detection/` | Rule-based customer gender detection, no transformer models | not started |

## Data
The assignment transcripts are the hiring team's material and are **not committed** (see `.gitignore`).
Place the exported CSV at `data/Data_Calls.csv`, then generate the task inputs:

```powershell
cd task1_call_labeling
python scripts\csv_to_jsonl.py --input ..\data\Data_Calls.csv --inputs-out data\inputs_50.jsonl --gold-out data\gold_50.jsonl
```

## Quick start (web app: FastAPI backend + Streamlit dashboard)

```powershell
cd task1_call_labeling
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-ui.txt
$env:GROQ_API_KEY = "your key"      # or copy .env.example to .env
python run_app.py
```

Then open http://127.0.0.1:8501. Put your CSV (columns `transcript_id`, `call_started_at`, `transcript`) in a `data/`
folder or upload it in the sidebar. `run_app.py` only starts the app; it does not run tests or the batch pipeline.

See `task1_call_labeling/README.md` for the batch runner (`src/run.py`), settings and the web app details, and
`task1_call_labeling/docs/error_analysis.md` for results.
