# Anthropod FDE Assignment

| Task | Folder | Status |
|------|--------|--------|
| 1. Label call transcripts (disposition, sub-disposition, lead quality, next call time) | [`task1_call_labeling/`](task1_call_labeling/) | done |
| 2. Rule-based customer gender detection (no transformer models) | [`task2_gender_detection/`](task2_gender_detection/) | not started |

## Run Task 1

1. Get the code:
   ```
   git clone https://github.com/Jash9603/anthropod-fde-assignment.git
   cd anthropod-fde-assignment/task1_call_labeling
   ```
2. Copy `.env.example` to `.env` and set `GROQ_API_KEY`.
3. Run:
   ```
   python run_app.py
   ```

The dashboard opens at http://127.0.0.1:8501; upload your CSV there. Details: [Task 1 README](task1_call_labeling/README.md).
