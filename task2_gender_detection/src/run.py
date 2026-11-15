"""Batch runner: transcripts in, one gender prediction per call out. Standard library only, runs offline.

    python src/run.py --input calls.csv --output outputs/predictions.jsonl

Input: a CSV (columns transcript_id, transcript; other columns are ignored) or a JSONL file with the same keys.
Output: <output> one JSON object per call: transcript_id, gender (male|female|unknown), confidence
        (high|medium|low|none), male_score, female_score, reason.
        <output>.evidence.jsonl the evidence lines behind each decision (quotes transcript text).
"""
import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import load_config   # noqa: E402
from gender_rules import detect  # noqa: E402


def read_records(path):
    p = Path(path)
    if p.suffix.lower() == ".jsonl":
        with open(p, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def predict_all(records, cfg):
    """[(prediction, evidence_record)] for every record that has a transcript_id."""
    out = []
    for r in records:
        tid = str(r.get("transcript_id") or "").strip()
        if not tid:
            continue
        res = detect(r.get("transcript") or "", cfg)
        pred = {"transcript_id": tid, **{k: res[k] for k in
                                          ("gender", "confidence", "male_score", "female_score", "reason")}}
        out.append((pred, {"transcript_id": tid, "notes": res["notes"], "evidence": res["evidence"]}))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True, help="CSV or JSONL with transcript_id and transcript")
    ap.add_argument("--output", required=True, help="prediction JSONL to write")
    ap.add_argument("--config", default=None, help="config file (default: config.toml, or $GENDER_CONFIG)")
    args = ap.parse_args()

    try:
        cfg = load_config(args.config)
    except (ValueError, FileNotFoundError) as e:
        sys.exit(str(e))
    results = predict_all(read_records(args.input), cfg)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fo, open(str(out) + ".evidence.jsonl", "w", encoding="utf-8") as fe:
        for pred, ev in results:
            fo.write(json.dumps(pred, ensure_ascii=False) + "\n")
            fe.write(json.dumps(ev, ensure_ascii=False) + "\n")
    counts = Counter(p["gender"] for p, _ in results)
    print(f"{len(results)} calls -> {out}  |  " + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())))


if __name__ == "__main__":
    main()
