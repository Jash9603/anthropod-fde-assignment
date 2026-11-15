"""Convert the labeled CSV into runner-ready JSONL files.

Outputs
  --inputs-out : input-only records (transcript_id, call_started_at, timezone, transcript).
                 This is the ONLY file the prediction workflow may read.
  --gold-out   : gold labels (transcript_id + 4 labels), used only by evaluate.py.

The sheet literal "null" (or an empty cell) in next_call_at becomes JSON null.
Usage:
    python scripts/csv_to_jsonl.py --input ../data/Data_Calls.csv \
        --inputs-out data/inputs_50.jsonl --gold-out data/gold_50.jsonl
"""
import argparse
import csv
import json
import os

INPUT_FIELDS = ["transcript_id", "call_started_at", "timezone", "transcript"]
GOLD_FIELDS = ["disposition", "sub_disposition", "lead_quality", "next_call_at"]


def _null(value):
    value = (value or "").strip()
    return None if value == "" or value.lower() == "null" else value


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--inputs-out", required=True)
    ap.add_argument("--gold-out", default=None)
    args = ap.parse_args()

    # newline="" preserves multiline transcript text inside quoted cells
    with open(args.input, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    for path in (args.inputs_out, args.gold_out):
        if path:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    with open(args.inputs_out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps({k: r[k] for k in INPUT_FIELDS}, ensure_ascii=False) + "\n")

    if args.gold_out:
        with open(args.gold_out, "w", encoding="utf-8") as f:
            for r in rows:
                rec = {"transcript_id": r["transcript_id"]}
                for k in GOLD_FIELDS:
                    rec[k] = _null(r[k]) if k == "next_call_at" else r[k].strip()
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"{len(rows)} records -> {args.inputs_out}" + (f", {args.gold_out}" if args.gold_out else ""))


if __name__ == "__main__":
    main()
