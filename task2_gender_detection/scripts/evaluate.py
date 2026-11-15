"""Score gender predictions against the gold labels.

    python scripts/evaluate.py --gold labels/gold_gender.csv --pred outputs/predictions.jsonl [--show-errors]

Reports: overall accuracy (an 'unknown' is correct only when the gold label is also unknown), coverage (share of
calls answered male/female), accuracy on the calls that were answered, and the confusion matrix.
"""
import argparse
import csv
import json

LABELS = ["male", "female", "unknown"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", required=True)
    ap.add_argument("--pred", required=True)
    ap.add_argument("--show-errors", action="store_true")
    args = ap.parse_args()

    gold = {r["transcript_id"]: r["gender"] for r in csv.DictReader(open(args.gold, encoding="utf-8-sig"))}
    pred = {}
    for line in open(args.pred, encoding="utf-8"):
        if line.strip():
            p = json.loads(line)
            pred[p["transcript_id"]] = p

    n = len(gold)
    missing = [t for t in gold if t not in pred]
    correct = sum(1 for t, g in gold.items() if t in pred and pred[t]["gender"] == g)
    answered = [t for t in gold if t in pred and pred[t]["gender"] != "unknown"]
    answered_ok = sum(1 for t in answered if pred[t]["gender"] == gold[t])

    print(f"calls: {n}   missing predictions: {len(missing)}")
    print(f"overall accuracy : {correct}/{n} = {100 * correct / n:.1f}%")
    print(f"coverage         : {len(answered)}/{n} = {100 * len(answered) / n:.1f}% answered male/female")
    if answered:
        print(f"answered accuracy: {answered_ok}/{len(answered)} = {100 * answered_ok / len(answered):.1f}%")
    print("\nconfusion (rows = gold, columns = predicted)")
    print(f"{'':10s}" + "".join(f"{c:>9s}" for c in LABELS))
    for g in LABELS:
        row = [sum(1 for t in gold if gold[t] == g and pred.get(t, {}).get("gender") == c) for c in LABELS]
        print(f"{g:10s}" + "".join(f"{v:>9d}" for v in row))
    conf = {}
    for t in gold:
        if t in pred:
            k = pred[t]["confidence"]
            conf.setdefault(k, [0, 0])
            conf[k][0] += 1
            conf[k][1] += pred[t]["gender"] == gold[t]
    print("\nby confidence: " + ", ".join(f"{k} {ok}/{tot}" for k, (tot, ok) in sorted(conf.items())))
    if args.show_errors:
        print("\nerrors:")
        for t, g in gold.items():
            p = pred.get(t)
            if p is None or p["gender"] != g:
                print(f"  {t}: gold={g} pred={p and p['gender']} ({p and p['confidence']}) - {p and p['reason']}")


if __name__ == "__main__":
    main()
