"""Pull every gender-relevant line out of each call, for HUMAN labeling (not used by the classifier).

    python scripts/extract_evidence.py --input ../data/Data_Calls.csv [--ids AVT-001,AVT-002] [--out labels/evidence.txt]

For each call it prints, in order, the lines (with their speaker label and line number) that contain an address term
(sir, ma'am, madam), a title (Mr, Mrs, Miss, Ms), a "<name> ji", a name introduction, or a family word
(husband, wife, mother, son, ...). The output quotes transcript text, so it is git-ignored.
"""
import argparse
import csv
import re
import sys

PATTERN = re.compile(
    r"\b(sir|ma'?am|madam|mam|mr|mrs|miss|ms|ji|husband|wife|mother|father|mom|dad|son|daughter|brother|sister|"
    r"bhaiya|didi|aunty|uncle|beta|my name|i am|i'm|speaking|lady|gentleman|myself|herself|himself)\b", re.I)


def evidence_lines(transcript, width=150):
    out = []
    for n, line in enumerate(transcript.splitlines(), 1):
        if PATTERN.search(line):
            out.append(f"  {n:>3} {line.strip()[:width]}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--ids", default=None, help="comma-separated transcript ids (default: all)")
    ap.add_argument("--out", default=None, help="write to this file instead of stdout")
    args = ap.parse_args()

    want = set(args.ids.split(",")) if args.ids else None
    with open(args.input, encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f) if not want or r["transcript_id"] in want]
    text = []
    for r in rows:
        lines = r["transcript"].splitlines()
        text.append(f"===== {r['transcript_id']}  ({len(lines)} lines)")
        text += evidence_lines(r["transcript"]) or ["  (no matching lines)"]
    out = "\n".join(text) + "\n"
    if args.out:
        open(args.out, "w", encoding="utf-8").write(out)
    else:
        sys.stdout.write(out)


if __name__ == "__main__":
    main()
