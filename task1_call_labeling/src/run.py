"""One-command runner.

    python src/run.py --input data/inputs_50.jsonl --output outputs/predictions.jsonl

Reads GROQ_API_KEY from the environment (or task1_call_labeling/.env).
Writes: <output>            one 5-key prediction per input record, in input order
        <output>.trace.jsonl  extracted evidence, status, retries and token usage per record
        <output>.summary.json model, settings, counts, tokens, runtime
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from io_models import read_jsonl, fallback_output   # noqa: E402
from llm_client import GroqExtractor                # noqa: E402
from pipeline import process_record                 # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True, help="input JSONL: transcript_id, call_started_at, timezone, transcript")
    ap.add_argument("--output", required=True, help="prediction JSONL to write")
    ap.add_argument("--model", default="openai/gpt-oss-120b", help="exact Groq model id")
    ap.add_argument("--reasoning-effort", default="low", help="low|medium|high for reasoning models; '' to disable")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--max-tokens", type=int, default=4096, help="includes hidden reasoning tokens")
    ap.add_argument("--timeout", type=float, default=90.0, help="seconds per API call")
    ap.add_argument("--max-attempts", type=int, default=4, help="attempts per record (API errors and bad JSON)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--offset", type=int, default=0, help="skip the first N records (debugging)")
    ap.add_argument("--limit", type=int, default=None, help="process at most N records (debugging)")
    ap.add_argument("--prompts-dir", default=str(ROOT / "prompts"))
    args = ap.parse_args()

    if not os.environ.get("GROQ_API_KEY", "").strip():
        sys.exit("GROQ_API_KEY is not set (export it, or put it in task1_call_labeling/.env)")

    pdir = Path(args.prompts_dir)
    extractor = GroqExtractor(
        model=args.model,
        system_prompt=(pdir / "system.md").read_text(encoding="utf-8"),
        user_template=(pdir / "user.md").read_text(encoding="utf-8"),
        temperature=args.temperature, max_tokens=args.max_tokens, timeout=args.timeout,
        max_attempts=args.max_attempts, seed=args.seed, reasoning_effort=args.reasoning_effort or None,
    )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    stats = {"records": 0, "ok": 0, "llm_failed": 0, "invalid_input": 0, "rules_error": 0,
             "prompt_tokens": 0, "completion_tokens": 0, "retries": 0, "rate_limit_waits": 0}
    seen, warned = set(), False
    t0 = time.time()

    with open(out_path, "w", encoding="utf-8") as fo, \
            open(str(out_path) + ".trace.jsonl", "w", encoding="utf-8") as ft:
        for idx, (line_no, rec, err) in enumerate(read_jsonl(args.input)):
            if idx < args.offset:
                continue
            if args.limit is not None and stats["records"] >= args.limit:
                break
            if rec is None:
                out, trace = fallback_output(f"LINE_{line_no}"), {"status": "invalid_input", "notes": [err]}
            else:
                out, trace = process_record(rec, extractor)

            if out["transcript_id"] in seen:
                print(f"warning: duplicate transcript_id {out['transcript_id']}", file=sys.stderr)
            seen.add(out["transcript_id"])
            if extractor.exhausted and not warned:
                warned = True
                print("warning: API quota exhausted; remaining records get the safe fallback output", file=sys.stderr)

            stats["records"] += 1
            stats[trace["status"]] = stats.get(trace["status"], 0) + 1
            stats["prompt_tokens"] += trace.get("prompt_tokens", 0)
            stats["completion_tokens"] += trace.get("completion_tokens", 0)
            stats["retries"] += max(trace.get("attempts", 1) - 1, 0)
            stats["rate_limit_waits"] += trace.get("rate_limit_waits", 0)

            fo.write(json.dumps(out, ensure_ascii=False) + "\n"); fo.flush()
            ft.write(json.dumps(trace, ensure_ascii=False) + "\n"); ft.flush()
            print(f"[{stats['records']}] {out['transcript_id']}: {out['disposition']} / {out['sub_disposition']} "
                  f"/ {out['lead_quality']} / {out['next_call_at']}  ({trace['status']})", flush=True)

    summary = {
        "model": args.model, "reasoning_effort": args.reasoning_effort, "temperature": args.temperature,
        "max_tokens": args.max_tokens, "timeout_s": args.timeout, "max_attempts": args.max_attempts,
        "seed": args.seed, "reasoning_effort_used": extractor.reasoning_effort, "json_mode_used": extractor.json_mode,
        "runtime_s": round(time.time() - t0, 1), **stats,
    }
    Path(str(out_path) + ".summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("\nsummary:", json.dumps(summary))


if __name__ == "__main__":
    main()
