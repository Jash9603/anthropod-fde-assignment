"""Streamlit frontend. Talks to the FastAPI backend over HTTP (BACKEND_URL, default http://127.0.0.1:8000).

Start everything with:  python run_app.py   (from task1_call_labeling/)
"""
import csv
import io
import os
import time

import requests
import streamlit as st

BACKEND = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
LABELS = ("disposition", "sub_disposition", "lead_quality", "next_call_at")

st.set_page_config(page_title="Call labeling dashboard", layout="wide")


# ---- backend helpers -------------------------------------------------------------------------------
def api(method, path, **kw):
    """Call the backend; returns parsed JSON or raises RuntimeError with a readable message."""
    try:
        r = requests.request(method, BACKEND + path, timeout=kw.pop("timeout", 30), **kw)
    except requests.RequestException as e:
        raise RuntimeError(f"Cannot reach the backend at {BACKEND}: {e}")
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except ValueError:
            detail = r.text
        raise RuntimeError(f"{r.status_code}: {detail}")
    return r.json()


def history_csv(rows):
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return buf.getvalue()


ss = st.session_state
ss.setdefault("history", [])
ss.setdefault("last_result", None)

# ---- backend status ------------------------------------------------------------------------------------
try:
    health = api("GET", "/health")
    models = api("GET", "/models")
except RuntimeError as e:
    st.title("Call labeling dashboard")
    st.error(str(e))
    st.info("Start the app with `python run_app.py` so the backend and frontend run together.")
    st.stop()

# ---- sidebar ----------------------------------------------------------------------------------------------
st.sidebar.header("Data")

with st.sidebar.expander("Upload a CSV"):
    st.caption("Required columns: transcript_id, call_started_at, transcript (timezone optional). "
               "Gold label columns, if present, are shown for comparison only.")
    up = st.file_uploader("CSV file", type=["csv"], key="uploader")
    if up is not None and ss.get("_last_upload") != (up.name, up.size):
        ss["_last_upload"] = (up.name, up.size)
        try:
            res = api("POST", "/upload", files={"file": (up.name, up.getvalue(), "text/csv")})
            ss["file_choice"] = res["file"]                       # switch to the uploaded file
            st.success(f"Uploaded {res['count']} records.")
        except RuntimeError as e:
            st.error(str(e))

files = api("GET", "/files")["files"]
if not files:
    st.title("Call labeling dashboard")
    st.info("No CSV files found. Upload one in the sidebar, or put a CSV (with columns transcript_id, "
            "call_started_at, transcript) in the `data/` folder and press Refresh.")
    if st.sidebar.button("Refresh data"):
        st.rerun()
    st.stop()

ids = [f["id"] for f in files]
if ss.get("file_choice") not in ids:
    ss["file_choice"] = ids[0]
file_id = st.sidebar.selectbox("Data file", ids, key="file_choice")

if st.sidebar.button("Refresh data", help="Re-read the CSV from disk"):
    st.rerun()                                                   # every rerun re-fetches from the backend

try:
    data = api("GET", "/records", params={"file": file_id})
except RuntimeError as e:
    st.title("Call labeling dashboard")
    st.error(str(e))
    st.stop()

records = data["records"]
count_key = f"count::{file_id}"
prev = ss.get(count_key)
st.sidebar.caption(f"{data['count']} records - loaded {time.strftime('%H:%M:%S')}")
if prev is not None and data["count"] > prev:
    st.sidebar.success(f"{data['count'] - prev} new record(s) since the last refresh")
elif prev is not None and data["count"] < prev:
    st.sidebar.warning(f"{prev - data['count']} record(s) removed since the last refresh")
ss[count_key] = data["count"]

st.sidebar.header("Model")
model_ids = [m["id"] for m in models["models"]]
model = st.sidebar.selectbox("Groq model", model_ids,
                             index=model_ids.index(models["default"]) if models["default"] in model_ids else 0)
if not health["api_key_configured"]:
    st.sidebar.error("GROQ_API_KEY is not configured on the server; predictions are disabled.")

# ---- main ------------------------------------------------------------------------------------------------------
st.title("Call labeling dashboard")
tab_data, tab_predict, tab_history = st.tabs(["Data", "Predict", f"Session history ({len(ss['history'])})"])

with tab_data:
    st.caption(f"`{data['file']}` - {data['count']} records"
               + (" (gold label columns detected; for comparison only)" if data["has_gold"] else ""))
    q = st.text_input("Filter", placeholder="Filter by ID or transcript text", key="filter")
    rows = [r for r in records if not q or q.lower() in r["transcript_id"].lower()
            or q.lower() in r["transcript_preview"].lower()]
    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.caption(f"Showing {len(rows)} of {len(records)}. Add rows to the CSV and press **Refresh data** in the sidebar.")

with tab_predict:
    if not records:
        st.info("The selected file has no records.")
    else:
        sel = st.selectbox("Transcript ID (type to search)", [r["transcript_id"] for r in records],
                           index=None, placeholder="Select or type an ID ...")
        if sel:
            try:
                rec = api("GET", f"/records/{sel}", params={"file": file_id})
            except RuntimeError as e:
                st.error(str(e))
                st.stop()
            c1, c2 = st.columns(2)
            c1.markdown(f"**Call started at:** `{rec['call_started_at']}`")
            c2.markdown(f"**Timezone:** `{rec['timezone']}`")
            with st.expander("Transcript"):
                st.text(rec["transcript"])

            if st.button("Run pipeline", type="primary", disabled=not health["api_key_configured"]):
                with st.spinner(f"Running {model} (this can take a while if the API is rate limited) ..."):
                    try:
                        res = api("POST", "/predict", json={"transcript_id": sel, "file": file_id, "model": model},
                                  timeout=900)
                    except RuntimeError as e:
                        st.error(str(e))
                        res = None
                if res:
                    ss["last_result"] = res
                    ss["history"].insert(0, {
                        "time": time.strftime("%H:%M:%S"), "transcript_id": sel, "model": res["model"],
                        **{k: res["prediction"][k] for k in LABELS}, "status": res["status"],
                        "latency_s": res["latency_s"], "tokens_in": res["prompt_tokens"],
                        "tokens_out": res["completion_tokens"],
                    })

            res = ss.get("last_result")
            if res and res["prediction"]["transcript_id"] == sel:
                st.subheader("Predicted labels")
                p = res["prediction"]
                a, b, c, d = st.columns(4)
                a.metric("Disposition", p["disposition"])
                b.metric("Sub-disposition", p["sub_disposition"])
                c.metric("Lead quality", p["lead_quality"])
                d.metric("Next call at", p["next_call_at"] or "null")
                if res["status"] != "ok":
                    st.warning(f"Pipeline status: {res['status']} - {'; '.join(res['notes'])[:300]}")
                if res.get("gold"):
                    st.markdown("**Comparison with gold (not used by the pipeline)**")
                    st.table([{"field": k, "predicted": p[k], "gold": res["gold"][k],
                               "match": "yes" if p[k] == res["gold"][k] else "NO"} for k in LABELS])
                with st.expander("Extracted evidence (what the LLM reported)"):
                    st.json(res["extraction"])
                with st.expander("Run details"):
                    st.json({k: res[k] for k in ("model", "status", "attempts", "rate_limit_waits", "latency_s",
                                                 "prompt_tokens", "completion_tokens")})

with tab_history:
    hist = ss["history"]
    if not hist:
        st.info("No predictions yet in this session.")
    else:
        st.dataframe(hist, use_container_width=True, hide_index=True)
        d1, d2 = st.columns(2)
        d1.download_button("Download history (CSV)", history_csv(hist), file_name="session_predictions.csv")
        if d2.button("Clear history"):
            ss["history"], ss["last_result"] = [], None
            st.rerun()
