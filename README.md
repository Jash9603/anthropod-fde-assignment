# Anthropod FDE Assignment

Two independent tasks. Each folder is self-contained (own README, requirements, outputs); nothing is shared except the
raw CSV, which is not committed.

| Task | Folder | Goal | Status |
|------|--------|------|--------|
| 1 | [`task1_call_labeling/`](task1_call_labeling/) | Label call transcripts: disposition, sub_disposition, lead_quality, next_call_at (Groq LLM + deterministic rules) | done |
| 2 | [`task2_gender_detection/`](task2_gender_detection/) | Rule-based customer gender detection, no transformer models | not started |

## Task 1 quick start

```powershell
cd task1_call_labeling
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:GROQ_API_KEY = "your key"          # or copy .env.example to .env

python src\run.py --input <input.jsonl> --output <predictions.jsonl>     # batch pipeline (the assignment's one command)
python run_app.py                                                        # web app: FastAPI backend + Streamlit dashboard
```

See [`task1_call_labeling/README.md`](task1_call_labeling/README.md) for the design, settings and guardrails,
[`docs/error_analysis.md`](task1_call_labeling/docs/error_analysis.md) for results, and
[`docs/requirements_checklist.md`](task1_call_labeling/docs/requirements_checklist.md) for the assignment requirements.

## Data
The assignment transcripts are the hiring team's material and are **not committed** (see `.gitignore`). Put the exported
CSV at `data/Data_Calls.csv`; the details are in [`task1_call_labeling/data/README.md`](task1_call_labeling/data/README.md).

## Secrets
API keys live only in a local `.env` (git-ignored) or the `GROQ_API_KEY` environment variable. Do not include `.env`
in a submission archive.
