"""Dashboard for the rule-based gender detector. Start it with:  python run_app.py

Upload a CSV, see the records with a predicted gender for every call, pick an ID to see the evidence behind the
decision, and keep a history of the session. Everything runs locally with no model and no API key.
"""
import csv
import io
import re
import sys
import time
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from config import load_config      # noqa: E402
from gender_rules import detect     # noqa: E402

CFG = load_config()
DATA_DIRS = [ROOT.parent / "data", ROOT / "data"]
UPLOAD_DIR = ROOT / "data"
GOLD = ROOT / "labels" / "gold_gender.csv"
ICON = {"male": "Male", "female": "Female", "unknown": "Unknown"}

st.set_page_config(page_title="Customer gender detection", layout="wide")
ss = st.session_state
ss.setdefault("history", [])


# ---- data ---------------------------------------------------------------------------------------
def csv_files():
    seen, out = set(), []
    for d in DATA_DIRS:
        if d.exists():
            for p in sorted(d.glob("*.csv")):
                if p.resolve() not in seen:
                    seen.add(p.resolve())
                    out.append(p)
    return out


def read_csv(path: Path):
    """Re-read whenever the file changes (mtime/size), so rows added to the CSV show up on Refresh."""
    st_ = path.stat()
    key = (str(path), st_.st_mtime_ns, st_.st_size)
    cache = ss.setdefault("_csv_cache", {})
    if key not in cache:
        text = path.read_text(encoding="utf-8-sig")
        reader = csv.DictReader(io.StringIO(text, newline=""))
        if not reader.fieldnames or "transcript_id" not in reader.fieldnames or "transcript" not in reader.fieldnames:
            raise ValueError("the CSV needs the columns transcript_id and transcript")
        rows, seen = [], set()
        for r in reader:
            tid = (r.get("transcript_id") or "").strip()
            if tid and tid not in seen:
                seen.add(tid)
                rows.append({**r, "transcript_id": tid})
        cache.clear()
        cache[key] = rows
    return cache[key]


def save_upload(up):
    data = up.getvalue()
    if len(data) > CFG["app"]["max_upload_mb"] * 1024 * 1024:
        raise ValueError("file too large")
    text = data.decode("utf-8-sig")
    header = next(csv.reader(io.StringIO(text)), [])
    if "transcript_id" not in header or "transcript" not in header:
        raise ValueError("the CSV needs the columns transcript_id and transcript")
    stem = re.sub(r"[^A-Za-z0-9._-]", "_", Path(up.name).stem)[:60] or "upload"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target = UPLOAD_DIR / f"{stem}.csv"
    if target.exists():                                         # never overwrite
        target = UPLOAD_DIR / f"{stem}_{time.strftime('%Y%m%d_%H%M%S')}.csv"
    target.write_bytes(data)
    return target


def load_gold():
    if not GOLD.exists():
        return {}
    with open(GOLD, encoding="utf-8-sig", newline="") as f:
        return {r["transcript_id"]: r["gender"] for r in csv.DictReader(f)}


# ---- sidebar ------------------------------------------------------------------------------------------
st.sidebar.header("Data")
files = csv_files()
with st.sidebar.expander("Upload a CSV", expanded=not files):
    st.caption("Columns: transcript_id, transcript (others are ignored).")
    up = st.file_uploader("CSV file", type=["csv"], key="uploader")
    if up is not None and ss.get("_last_upload") != (up.name, up.size):
        ss["_last_upload"] = (up.name, up.size)
        try:
            saved = save_upload(up)
            ss["file_choice"] = str(saved)
            st.success(f"Saved {saved.name}")
            files = csv_files()
        except (ValueError, UnicodeDecodeError) as e:
            st.error(f"Upload rejected: {e}")

st.title("Customer gender detection")
if not files:
    st.info("No data yet. Upload your CSV with the **Upload a CSV** box in the sidebar "
            "(columns: transcript_id, transcript).")
    st.stop()

paths = {str(p): p for p in files}
if ss.get("file_choice") not in paths:
    ss["file_choice"] = next(iter(paths))
choice = st.sidebar.selectbox("Data file", list(paths), key="file_choice", format_func=lambda s: Path(s).name)
if st.sidebar.button("Refresh data", help="Re-read the CSV from disk"):
    st.rerun()

try:
    records = read_csv(paths[choice])
except (ValueError, UnicodeDecodeError) as e:
    st.error(f"Cannot read {Path(choice).name}: {e}")
    st.stop()
prev = ss.get(f"count::{choice}")
st.sidebar.caption(f"{len(records)} records - loaded {time.strftime('%H:%M:%S')}")
if prev is not None and len(records) > prev:
    st.sidebar.success(f"{len(records) - prev} new record(s) since the last refresh")
ss[f"count::{choice}"] = len(records)

results = {r["transcript_id"]: detect(r.get("transcript") or "", CFG) for r in records}   # fast: rules only
gold = load_gold()

tab_data, tab_one, tab_hist = st.tabs(["All calls", "Inspect a call", f"Session history ({len(ss['history'])})"])

# ---- all calls ----------------------------------------------------------------------------------------
with tab_data:
    q = st.text_input("Filter", placeholder="Filter by ID or transcript text")
    table = []
    for r in records:
        if q and q.lower() not in r["transcript_id"].lower() and q.lower() not in (r.get("transcript") or "").lower():
            continue
        res = results[r["transcript_id"]]
        row = {"transcript_id": r["transcript_id"], "gender": res["gender"], "confidence": res["confidence"],
               "reason": res["reason"]}
        if r["transcript_id"] in gold:
            row["gold"] = gold[r["transcript_id"]]
        table.append(row)
    counts = {k: sum(1 for x in results.values() if x["gender"] == k) for k in ("male", "female", "unknown")}
    c1, c2, c3 = st.columns(3)
    c1.metric("Male", counts["male"])
    c2.metric("Female", counts["female"])
    c3.metric("Unknown", counts["unknown"])
    labeled = [t for t in results if t in gold]
    if labeled:
        ok = sum(results[t]["gender"] == gold[t] for t in labeled)
        st.caption(f"Agreement with the reviewed labels in labels/gold_gender.csv: {ok}/{len(labeled)}")
    st.dataframe(table, use_container_width=True, hide_index=True)

# ---- one call -------------------------------------------------------------------------------------------
with tab_one:
    ids = [r["transcript_id"] for r in records]
    sel = st.selectbox("Transcript ID (type to search)", ids, index=None, placeholder="Select or type an ID ...")
    if sel:
        res = results[sel]
        a, b, c = st.columns(3)
        a.metric("Gender", ICON[res["gender"]])
        b.metric("Confidence", res["confidence"])
        c.metric("Score (male / female)", f"{res['male_score']:g} / {res['female_score']:g}")
        st.write(res["reason"])
        for n in res["notes"]:
            st.warning(n)
        if sel in gold:
            st.caption(f"Reviewed label: {gold[sel]}")
        if st.button("Add to session history"):
            ss["history"].insert(0, {"time": time.strftime("%H:%M:%S"), "transcript_id": sel,
                                     "gender": res["gender"], "confidence": res["confidence"], "reason": res["reason"]})
            st.rerun()
        st.subheader("Evidence")
        if res["evidence"]:
            st.dataframe([{k: e[k] for k in ("line", "speaker", "kind", "vote", "weight", "text")}
                          for e in res["evidence"]], use_container_width=True, hide_index=True)
        else:
            st.caption("No evidence lines.")
        with st.expander("Transcript (evidence lines marked with >>)"):
            marked = {e["line"] for e in res["evidence"]}
            text = next(r.get("transcript") or "" for r in records if r["transcript_id"] == sel)
            st.text("\n".join((">> " if i in marked else "   ") + line
                              for i, line in enumerate(text.splitlines(), 1)))

# ---- history ----------------------------------------------------------------------------------------------
with tab_hist:
    if not ss["history"]:
        st.info("Nothing yet. Inspect a call and press **Add to session history**.")
    else:
        st.dataframe(ss["history"], use_container_width=True, hide_index=True)
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(ss["history"][0]))
        w.writeheader()
        w.writerows(ss["history"])
        d1, d2 = st.columns(2)
        d1.download_button("Download history (CSV)", buf.getvalue(), file_name="gender_session.csv")
        if d2.button("Clear history"):
            ss["history"] = []
            st.rerun()
