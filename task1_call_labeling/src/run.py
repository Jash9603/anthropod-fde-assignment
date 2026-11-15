"""One-command runner.

    python src/run.py --input data/inputs_50.jsonl --output outputs/predictions.jsonl

All settings come from config.toml (model, temperature, retries, timeouts, guardrails, prompts folder, ...);
command-line flags override the file. The API key is read from GROQ_API_KEY (environment or task1_call_labeling/.env).
Writes: <output>              one 5-key prediction per input record, in input order
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

from config import extractor_kwargs, load_config, prompts_dir   # noqa: E402
from io_models import read_jsonl, fallback_output               # noqa: E402
from llm_client import GroqExtractor                            # noqa: E402
from pipeline import process_record                             # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True, help="input JSONL: transcript_id, call_started_at, timezone, transcript")
    ap.add_argument("--output", required=True, help="prediction JSONL to write")
    ap.add_argument("--config", default=None, help="config file (default: config.toml, or $LABELING_CONFIG)")
    # Overrides of config.toml (None = use the config value)
    ap.add_argument("--model", default=None, help="[llm] model")
    ap.add_argument("--reasoning-effort", default=None, help="[llm] reasoning_effort ('' = not sent)")
    ap.add_argument("--temperature", type=float, default=None, help="[llm] temperature")
    ap.add_argument("--max-tokens", type=int, default=None, help="[llm] max_tokens")
    ap.add_argument("--timeout", type=float, default=None, help="[llm] timeout_s (seconds per API call)")
    ap.add_argument("--seed", type=int, default=None, help="[llm] seed")
    ap.add_argument("--max-attempts", type=int, default=None, help="[retries] max_attempts")
    ap.add_argument("--prompts-dir", default=None, help="[prompts] dir")
    ap.add_argument("--offset", type=int, default=0, help="skip the first N records (debugging)")
    ap.add_argument("--limit", type=int, default=None, help="process at most N records (debugging)")
    args = ap.parse_args()

    if not os.environ.get("GROQ_API_KEY", "").strip():
        sys.exit("GROQ_API_KEY is not set (export it, or put it in task1_call_labeling/.env)")

    try:
        cfg = load_config(args.config)
    except (ValueError, FileNotFoundError) as e:
        sys.exit(str(e))
    for flag, section, key in [("temperature", "llm", "temperature"), ("max_tokens", "llm", "max_tokens"),
                               ("timeout", "llm", "timeout_s"), ("seed", "llm", "seed"),
                               ("max_attempts", "retries", "max_attempts")]:
        if getattr(args, flag) is not None:
            cfg[section][key] = getattr(args, flag)
    if args.prompts_dir is not None:
        cfg["prompts"]["dir"] = args.prompts_dir

    kwargs = extractor_kwargs(cfg, model=args.model, reasoning_effort=args.reasoning_effort)
    pdir = prompts_dir(cfg)
    extractor = GroqExtractor(
        system_prompt=(pdir / "system.md").read_text(encoding="utf-8"),
        user_template=(pdir / "user.md").read_text(encoding="utf-8"),
        **kwargs,
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
                out, trace = process_record(rec, extractor, cfg["guardrails"])

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
        "model": kwargs["model"], "reasoning_effort": kwargs["reasoning_effort"] or "",
        "temperature": kwargs["temperature"], "max_tokens": kwargs["max_tokens"], "timeout_s": kwargs["timeout"],
        "max_attempts": kwargs["max_attempts"], "seed": kwargs["seed"],
        "reasoning_effort_used": extractor.reasoning_effort, "json_mode_used": extractor.json_mode,
        "config_file": str(Path(args.config or os.environ.get("LABELING_CONFIG") or "config.toml")),
        "settings": {"llm": cfg["llm"], "retries": cfg["retries"], "guardrails": cfg["guardrails"]},
        "runtime_s": round(time.time() - t0, 1), **stats,
    }
    Path(str(out_path) + ".summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("\nsummary:", json.dumps({k: v for k, v in summary.items() if k != "settings"}))


if __name__ == "__main__":
    main()
