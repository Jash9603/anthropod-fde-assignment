# Task 1 - Call labeling

Labels each call transcript with **disposition, sub-disposition, lead quality and next call time** (Aster Vale Pain
Clinic policy `assignment-v2`).
Result on the 50 supplied calls: **63.0 / 70 label points, 74% exact match** ([error analysis](docs/error_analysis.md)).

## Run it

**Step 1 - get the code**
```
git clone https://github.com/Jash9603/anthropod-fde-assignment.git
cd anthropod-fde-assignment/task1_call_labeling
```

**Step 2 - add your Groq API key:** copy `.env.example` to `.env` and set `GROQ_API_KEY`.

**Step 3 - one command**
```
python run_app.py
```

The first run creates a local environment and installs everything (a minute or two). The dashboard then opens at
http://127.0.0.1:8501: upload your CSV in the sidebar, pick a transcript ID and press **Run pipeline**.
Needs Python 3.11 or newer. CSV columns: `transcript_id`, `call_started_at`, `transcript` (`timezone` optional).

## Batch mode (input JSONL to prediction JSONL)

```
.venv\Scripts\python src\run.py --input calls.jsonl --output predictions.jsonl      (Windows)
.venv/bin/python src/run.py --input calls.jsonl --output predictions.jsonl          (macOS / Linux)
```

Input lines: `transcript_id`, `call_started_at`, `timezone`, `transcript`. Output lines: `transcript_id`,
`disposition`, `sub_disposition`, `lead_quality`, `next_call_at`. The submitted predictions for the 50 calls are in
[outputs/predictions_50.jsonl](outputs/predictions_50.jsonl).

## Settings

All settings live in [config.toml](config.toml); command-line flags override them.

| | |
|---|---|
| Model | `qwen/qwen3.8-27b` on Groq |
| Generation | temperature 0, seed 7, max_tokens 4096, reasoning_effort none, JSON mode |
| Timeout and retries | 90 s per call; up to 4 attempts (an unusable reply is fed back to the model); rate-limit waits do not use attempts; an oversized request is shortened and resent |
| JSON parsing | the first JSON object in the reply is parsed and validated against a pydantic schema; replies missing most fields are retried |
| Dependencies | pinned in [requirements.txt](requirements.txt): pydantic 2.14.3, groq 1.7.0, python-dotenv 1.2.4, fastapi 0.163.0, uvicorn 0.54.0, python-multipart 0.0.33, requests 2.34.2, streamlit 1.67.0 |

## More
- How it works, configuration, guardrails and tests: [docs/design.md](docs/design.md)
- Results, model comparison and failure patterns: [docs/error_analysis.md](docs/error_analysis.md)
- Assignment requirements checklist: [docs/requirements_checklist.md](docs/requirements_checklist.md)
