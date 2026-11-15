"""Score prediction files against the gold labels (same rules as the assignment's scoring contract).

    python scripts/evaluate.py --gold data/gold_50.jsonl --pred outputs/a.jsonl [outputs/b.jsonl] [--show-errors]
        [--split 30]                           # also report records 1-30 (dev) and 31-50 (held out) separately
        [--subset]                             # score only ids present in each prediction file
        [--price-in 0.15 --price-out 0.60]     # USD per 1M tokens, optional cost estimate

Scoring: disposition exact; sub_disposition counts only when the disposition is also correct;
lead_quality exact; next_call_at exact (null == null). Missing / duplicate ids score 0.
"""
import argparse
import json
from collections import Counter
from pathlib import Path

FIELDS = ["disposition", "sub_disposition", "lead_quality", "next_call_at"]
WEIGHTS = {"disposition": 15, "sub_disposition": 20, "lead_quality": 15, "next_call_at": 20}


def load(path):
    rows, dup = {}, set()
    for line in open(path, encoding="utf-8"):
        if line.strip():
            r = json.loads(line)
            if r["transcript_id"] in rows:
                dup.add(r["transcript_id"])
            rows[r["transcript_id"]] = r
    return rows, dup


def score(gold, pred, dup):
    correct, errors = Counter(), []
    for tid, g in gold.items():
        p = pred.get(tid)
        if p is None or tid in dup:
            errors.append((tid, "MISSING/DUPLICATE", None, None))
            continue
        ok = {
            "disposition": p.get("disposition") == g["disposition"],
            "lead_quality": p.get("lead_quality") == g["lead_quality"],
            "next_call_at": p.get("next_call_at") == g["next_call_at"],
        }
        ok["sub_disposition"] = ok["disposition"] and p.get("sub_disposition") == g["sub_disposition"]
        for f in FIELDS:
            correct[f] += ok[f]
            if not ok[f]:
                errors.append((tid, f, g[f], p.get(f)))
        correct["exact"] += all(ok.values())
    return correct, errors


def report(title, gold, pred, dup, show_errors):
    n = len(gold)
    if n == 0:
        return
    correct, errors = score(gold, pred, dup)
    points = sum(WEIGHTS[f] * correct[f] / n for f in FIELDS)
    print(f"\n=== {title}  (n={n}) ===")
    for f in FIELDS:
        print(f"  {f:16s} {correct[f]:3d}/{n}  {100 * correct[f] / n:5.1f}%")
    print(f"  {'exact match':16s} {correct['exact']:3d}/{n}  {100 * correct['exact'] / n:5.1f}%")
    print(f"  weighted label score: {points:.1f} / 70")
    if show_errors:
        for tid, f, g, p in errors:
            print(f"    {tid} {f}: gold={g!r} pred={p!r}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", required=True)
    ap.add_argument("--pred", nargs="+", required=True)
    ap.add_argument("--show-errors", action="store_true")
    ap.add_argument("--subset", action="store_true", help="score only ids present in each prediction file")
    ap.add_argument("--split", type=int, default=None, help="also report the first K gold records and the rest separately")
    ap.add_argument("--price-in", type=float, default=None)
    ap.add_argument("--price-out", type=float, default=None)
    args = ap.parse_args()

    all_gold, _ = load(args.gold)
    for path in args.pred:
        pred, dup = load(path)
        gold = {k: v for k, v in all_gold.items() if k in pred} if args.subset else all_gold
        report(path, gold, pred, dup, args.show_errors)
        if args.split:
            ids = list(gold)
            report(f"{path} :: first {args.split} (used for prompt development)",
                   {k: gold[k] for k in ids[:args.split]}, pred, dup, args.show_errors)
            report(f"{path} :: records {args.split + 1}+ (HELD OUT - never used to tune the prompt)",
                   {k: gold[k] for k in ids[args.split:]}, pred, dup, args.show_errors)
        sp = Path(path + ".summary.json")
        if sp.exists():
            s = json.loads(sp.read_text(encoding="utf-8"))
            line = (f"\n  model={s.get('model')}  reasoning={s.get('reasoning_effort')}  runtime={s.get('runtime_s')}s  "
                    f"tokens in/out={s.get('prompt_tokens')}/{s.get('completion_tokens')}  failed={s.get('llm_failed', 0)}")
            if args.price_in is not None and args.price_out is not None:
                cost = (s["prompt_tokens"] * args.price_in + s["completion_tokens"] * args.price_out) / 1e6
                line += f"  est. cost=${cost:.4f}"
            print(line)


if __name__ == "__main__":
    main()
