# Anthropod FDE Assignment

| Task | Folder | Status |
|------|--------|--------|
| 1. Label call transcripts (disposition, sub-disposition, lead quality, next call time) | [`task1_call_labeling/`](task1_call_labeling/) | done |
| 2. Customer gender detection, rule-based (no transformer / ML models) | [`task2_gender_detection/`](task2_gender_detection/) | done |

Get the code:
```
git clone https://github.com/Jash9603/anthropod-fde-assignment.git
cd anthropod-fde-assignment
```

## Run Task 1
1. `cd task1_call_labeling`
2. Copy `.env.example` to `.env` and set `GROQ_API_KEY`.
3. `python run_app.py`, then upload your CSV in the dashboard (http://127.0.0.1:8501).

Details: [Task 1 README](task1_call_labeling/README.md).

## Run Task 2
1. `cd task2_gender_detection`
2. `python run_app.py`, then upload your CSV in the dashboard (http://127.0.0.1:8502). No API key needed.

Details: [Task 2 README](task2_gender_detection/README.md).
