"""Streamlit front end for the call-labeling pipeline.

    streamlit run app/streamlit_app.py

Pick a transcript id from the loaded records, press "Run pipeline", and get the four predicted labels.
The app runs exactly the same code as the CLI runner (pipeline.process_record) and only passes the four
input fields (transcript_id, call_started_at, timezone, transcript) to it. Gold labels, if a gold file is present,
are shown afterwards for comparison only and are never given to the pipeline.
"""
import json
import os
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from io_models import read_jsonl            # noqa: E402
from llm_client import GroqExtractor        # noqa: E402
from pipeline import process_record         # noqa: E402

INPUT_FIELDS = ("transcript_id", "call_started_at", "timezone", "transcript")
INPUTS_PATH = ROOT / "data" / "inputs_50.jsonl"
GOLD_PATH = ROOT / "data" / "gold_50.jsonl"
# model id -> reasoning_effort preset ("" = not sent)
MODEL_PRESETS = {
    "openai/gpt-oss-120b": "low",
    "openai/gpt-oss-20b": "low",
    "qwen/qwen3.8-27b": "none",
}

st.set_page_config(page_title="Call labeling pipeline", layout="wide")


@st.cache_data
def load_records(path: str):
    return [r for _, r, _ in read_jsonl(path) if r is not None]


@st.cache_data
def load_gold(path: str):
    if not Path(path).exists():
        return {}
    return {json.loads(l)["transcript_id"]: json.loads(l) for l in open(path, encoding="utf-8") if l.strip()}


@st.cache_resource
def get_extractor(model: str):
    pdir = ROOT / "prompts"
    return GroqExtractor(
        model=model,
        system_prompt=(pdir / "system.md").read_text(encoding="utf-8"),
        user_template=(pdir / "user.md").read_text(encoding="utf-8"),
        reasoning_effort=MODEL_PRESETS.get(model) or None,
    )


# ---- sidebar ---------------------------------------------------------------------------------------
st.sidebar.header("Settings")
model = st.sidebar.selectbox("Groq model", list(MODEL_PRESETS), index=0)
show_gold = st.sidebar.checkbox("Compare with gold labels (if available)", value=True)
if not os.environ.get("GROQ_API_KEY", "").strip():
    st.sidebar.error("GROQ_API_KEY is not set (export it or put it in .env).")

# ---- data ------------------------------------------------------------------------------------------------
records = load_records(str(INPUTS_PATH)) if INPUTS_PATH.exists() else []
if not records:
    st.title("Call labeling pipeline")
    st.info("No records found at `data/inputs_50.jsonl`. Generate them with `scripts/csv_to_jsonl.py` "
            "(see the README), or upload an input JSONL below.")
    up = st.file_uploader("Input JSONL (transcript_id, call_started_at, timezone, transcript)", type=["jsonl"])
    if up is not None:
        records = [json.loads(l) for l in up.getvalue().decode("utf-8").splitlines() if l.strip()]
    if not records:
        st.stop()

by_id = {r["transcript_id"]: r for r in records}

st.title("Call labeling pipeline")
st.caption("Select a call, run the pipeline, and get disposition, sub-disposition, lead quality and next call time.")

tid = st.selectbox("Transcript ID", list(by_id))
rec = by_id[tid]
c1, c2 = st.columns(2)
c1.markdown(f"**Call started at:** `{rec['call_started_at']}`")
c2.markdown(f"**Timezone:** `{rec.get('timezone', 'Asia/Kolkata')}`")
with st.expander("Transcript", expanded=False):
    st.text(rec.get("transcript", ""))

if st.button("Run pipeline", type="primary", disabled=not os.environ.get("GROQ_API_KEY", "").strip()):
    payload = {k: rec.get(k) for k in INPUT_FIELDS}          # only the four input fields are fed to the workflow
    with st.spinner(f"Running {model} ..."):
        out, trace = process_record(payload, get_extractor(model))
    st.session_state["result"] = (tid, model, out, trace)

res = st.session_state.get("result")
if res and res[0] == tid:
    _, used_model, out, trace = res
    st.subheader("Predicted labels")
    a, b, c, d = st.columns(4)
    a.metric("Disposition", out["disposition"])
    b.metric("Sub-disposition", out["sub_disposition"])
    c.metric("Lead quality", out["lead_quality"])
    d.metric("Next call at", out["next_call_at"] or "null")

    if trace["status"] != "ok":
        st.warning(f"Pipeline status: {trace['status']} - {'; '.join(trace.get('notes', []))[:300]}")

    gold = load_gold(str(GOLD_PATH)).get(tid) if show_gold else None
    if gold:
        rows = []
        for f in ("disposition", "sub_disposition", "lead_quality", "next_call_at"):
            g, p = gold[f], out[f]
            rows.append({"field": f, "predicted": p, "gold": g, "match": "yes" if g == p else "NO"})
        st.markdown("**Comparison with gold (not used by the pipeline)**")
        st.table(rows)

    with st.expander("Extracted evidence (what the LLM reported)"):
        st.json(trace.get("extraction", {}))
    with st.expander("Run details"):
        st.json({"model": used_model, "status": trace["status"], "attempts": trace.get("attempts"),
                 "rate_limit_waits": trace.get("rate_limit_waits"), "latency_s": trace.get("latency_s"),
                 "prompt_tokens": trace.get("prompt_tokens"), "completion_tokens": trace.get("completion_tokens")})
    st.download_button("Download prediction (JSON)", json.dumps(out, indent=2), file_name=f"{tid}.json")
