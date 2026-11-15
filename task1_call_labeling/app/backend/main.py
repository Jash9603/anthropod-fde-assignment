"""FastAPI backend for the call-labeling pipeline.

Endpoints
    GET  /health                    service status (never returns the API key)
    GET  /models                    selectable Groq models
    GET  /files                     CSV files available to the dashboard
    GET  /records?file=<id>         records of a CSV (re-read from disk whenever the file changes)
    GET  /records/{transcript_id}   one full record
    POST /predict                   run the pipeline for one record -> the four labels
    POST /upload                    upload a CSV (saved next to the other data files, never overwrites)

The pipeline is exactly the one used by the CLI runner (pipeline.process_record); only the four input fields
(transcript_id, call_started_at, timezone, transcript) are passed to it. Gold label columns, if the CSV has them,
are returned for display only.
"""
import csv
import io
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]            # task1_call_labeling
REPO_ROOT = ROOT.parent
sys.path.insert(0, str(ROOT / "src"))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from llm_client import GroqExtractor    # noqa: E402
from pipeline import process_record     # noqa: E402

DATA_DIRS = [REPO_ROOT / "data", ROOT / "data"]       # CSV files are listed from these folders
UPLOAD_DIR = ROOT / "data"
REQUIRED_COLUMNS = ("transcript_id", "call_started_at", "transcript")
INPUT_FIELDS = ("transcript_id", "call_started_at", "timezone", "transcript")
GOLD_COLUMNS = ("disposition", "sub_disposition", "lead_quality", "next_call_at")
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MODEL_PRESETS = {                                     # model id -> reasoning_effort preset
    "qwen/qwen3.8-27b": "none",
    "openai/gpt-oss-120b": "low",
    "openai/gpt-oss-20b": "low",
}
DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "qwen/qwen3.8-27b")

app = FastAPI(title="Call labeling pipeline", version="1.0")

_CACHE: dict = {}                 # path -> ((mtime_ns, size), parsed)
_EXTRACTORS: dict = {}            # model -> GroqExtractor
_LOCK = threading.Lock()


# ---- files -----------------------------------------------------------------------------------------------
def _rel(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()


def list_csv_files():
    seen, out = set(), []
    for d in DATA_DIRS:
        if not d.exists():
            continue
        for p in sorted(d.glob("*.csv")):
            fid = _rel(p)
            if fid not in seen:
                seen.add(fid)
                st = p.stat()
                out.append({"id": fid, "name": p.name, "size_bytes": st.st_size, "modified": st.st_mtime})
    return out


def resolve_file(file_id: Optional[str]) -> Path:
    """Map a file id to a path, only inside the allowed data folders (no path traversal)."""
    if not file_id:
        files = list_csv_files()
        if not files:
            raise HTTPException(404, "No CSV files found. Upload one or place it in the data folder.")
        file_id = files[0]["id"]
    p = (REPO_ROOT / file_id).resolve()
    allowed = {d.resolve() for d in DATA_DIRS}
    if p.suffix.lower() != ".csv" or p.parent not in allowed or not p.is_file():
        raise HTTPException(404, f"Unknown data file: {file_id}")
    return p


def parse_csv_text(text: str):
    reader = csv.DictReader(io.StringIO(text, newline=""))
    header = [h.strip() for h in (reader.fieldnames or [])]
    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        raise ValueError(f"CSV is missing required column(s): {', '.join(missing)}")
    records, seen = [], set()
    for row in reader:
        row = {(k or "").strip(): (v or "") for k, v in row.items()}
        tid = row.get("transcript_id", "").strip()
        if not tid or tid in seen:
            continue                                     # skip blank ids and duplicates (first one wins)
        seen.add(tid)
        row["transcript_id"] = tid
        row["timezone"] = row.get("timezone", "").strip() or "Asia/Kolkata"
        records.append(row)
    return records, header


def load_records(path: Path):
    """Parsed (records, header). Re-read automatically whenever the file's mtime or size changes."""
    st = path.stat()
    key = (st.st_mtime_ns, st.st_size)
    cached = _CACHE.get(str(path))
    if cached and cached[0] == key:
        return cached[1]
    try:
        parsed = parse_csv_text(path.read_text(encoding="utf-8-sig"))
    except ValueError as e:
        raise HTTPException(422, str(e))
    except UnicodeDecodeError:
        raise HTTPException(422, "CSV is not valid UTF-8")
    _CACHE[str(path)] = (key, parsed)
    return parsed


def _gold(row):
    if not all(c in row for c in GOLD_COLUMNS):
        return None
    g = {c: row[c].strip() for c in GOLD_COLUMNS}
    if g["next_call_at"].lower() in ("", "null"):
        g["next_call_at"] = None
    return g


# ---- extractor -------------------------------------------------------------------------------------------------
def get_extractor(model: str):
    if model not in MODEL_PRESETS:
        raise HTTPException(400, f"Unsupported model. Choose one of: {', '.join(MODEL_PRESETS)}")
    if not os.environ.get("GROQ_API_KEY", "").strip():
        raise HTTPException(503, "GROQ_API_KEY is not configured on the server.")
    with _LOCK:
        if model not in _EXTRACTORS:
            pdir = ROOT / "prompts"
            _EXTRACTORS[model] = GroqExtractor(
                model=model,
                system_prompt=(pdir / "system.md").read_text(encoding="utf-8"),
                user_template=(pdir / "user.md").read_text(encoding="utf-8"),
                reasoning_effort=MODEL_PRESETS[model] or None,
            )
        return _EXTRACTORS[model]


# ---- API ---------------------------------------------------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok", "api_key_configured": bool(os.environ.get("GROQ_API_KEY", "").strip()),
            "default_model": DEFAULT_MODEL}


@app.get("/models")
def models():
    return {"default": DEFAULT_MODEL, "models": [{"id": m, "reasoning_effort": r} for m, r in MODEL_PRESETS.items()]}


@app.get("/files")
def files():
    return {"files": list_csv_files()}


@app.get("/records")
def records(file: Optional[str] = Query(None)):
    path = resolve_file(file)
    recs, header = load_records(path)
    has_gold = all(c in header for c in GOLD_COLUMNS)
    rows = []
    for r in recs:
        item = {"transcript_id": r["transcript_id"], "call_started_at": r["call_started_at"], "timezone": r["timezone"],
                "transcript_chars": len(r["transcript"]), "transcript_preview": r["transcript"][:160].replace("\n", " ")}
        if has_gold:
            item.update({f"gold_{c}": v for c, v in (_gold(r) or {}).items()})
        rows.append(item)
    return {"file": _rel(path), "count": len(rows), "has_gold": has_gold,
            "modified": path.stat().st_mtime, "records": rows}


@app.get("/records/{transcript_id}")
def record(transcript_id: str, file: Optional[str] = Query(None)):
    recs, _ = load_records(resolve_file(file))
    for r in recs:
        if r["transcript_id"] == transcript_id:
            return {**{k: r[k] for k in INPUT_FIELDS}, "gold": _gold(r)}
    raise HTTPException(404, f"Unknown transcript_id: {transcript_id}")


class PredictRequest(BaseModel):
    transcript_id: str
    file: Optional[str] = None
    model: Optional[str] = None


@app.post("/predict")
def predict(req: PredictRequest):
    model = req.model or DEFAULT_MODEL
    recs, _ = load_records(resolve_file(req.file))
    row = next((r for r in recs if r["transcript_id"] == req.transcript_id), None)
    if row is None:
        raise HTTPException(404, f"Unknown transcript_id: {req.transcript_id}")
    extractor = get_extractor(model)
    extractor.exhausted = False        # a long-lived server must retry: quotas reset (one quick 429 if still spent)
    payload = {k: row[k] for k in INPUT_FIELDS}          # ONLY the four input fields reach the workflow
    t0 = time.time()
    out, trace = process_record(payload, extractor)
    return {
        "prediction": out, "status": trace["status"], "notes": trace.get("notes", []), "model": model,
        "extraction": trace.get("extraction", {}), "attempts": trace.get("attempts"),
        "rate_limit_waits": trace.get("rate_limit_waits", 0), "latency_s": round(time.time() - t0, 2),
        "prompt_tokens": trace.get("prompt_tokens", 0), "completion_tokens": trace.get("completion_tokens", 0),
        "gold": _gold(row),                              # display only, never used by the pipeline
    }


@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large (max 20 MB).")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(422, "CSV is not valid UTF-8")
    try:
        recs, _ = parse_csv_text(text)
    except ValueError as e:
        raise HTTPException(422, str(e))
    stem = re.sub(r"[^A-Za-z0-9._-]", "_", Path(file.filename or "upload").stem)[:60] or "upload"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target = UPLOAD_DIR / f"{stem}.csv"
    if target.exists():                                   # never overwrite an existing file
        target = UPLOAD_DIR / f"{stem}_{time.strftime('%Y%m%d_%H%M%S')}.csv"
    target.write_bytes(data)
    return {"file": _rel(target), "count": len(recs)}
