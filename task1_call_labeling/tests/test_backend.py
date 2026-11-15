"""Backend API tests (no network). Skipped automatically if the UI dependencies are not installed.
Run from task1_call_labeling/:  python -m unittest discover -s tests -v
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

try:
    import multipart  # noqa: F401  (python-multipart)
    from fastapi.testclient import TestClient
    from app.backend import main
    HAVE_DEPS = True
except Exception:                       # pragma: no cover
    HAVE_DEPS = False

from llm_client import LLMResult        # noqa: E402

HEADER = "transcript_id,call_started_at,timezone,transcript,disposition,sub_disposition,lead_quality,next_call_at\n"
ROW1 = 'T1,2026-11-09T14:00:00+05:30,Asia/Kolkata,"Agent: Hello this is the clinic.\nCustomer: I want a consultation for back pain.",Follow-up Required,Further Discussion,Medium,null\n'
ROW2 = 'T2,2026-11-09T15:00:00+05:30,Asia/Kolkata,"Agent: Hello again from the clinic.\nCustomer: Please call me tomorrow.",Follow-up Required,Further Discussion,Medium,null\n'


class FakeExtractor:
    def __init__(self):
        self.seen = []

    def extract(self, call_started_at, call_weekday, transcript):
        self.seen.append((call_started_at, transcript))
        return LLMResult(extraction={"relevant_discussion": True, "pain_need": "yes"}, attempts=1,
                         prompt_tokens=11, completion_tokens=7)


@unittest.skipUnless(HAVE_DEPS, "fastapi UI dependencies not installed (pip install -r requirements-ui.txt)")
class TestBackend(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "data").mkdir()
        self.csv = root / "data" / "calls.csv"
        self.csv.write_text(HEADER + ROW1, encoding="utf-8")
        (root / "secret.csv").write_text(HEADER + ROW1, encoding="utf-8")
        self.patches = [
            mock.patch.object(main, "REPO_ROOT", root), mock.patch.object(main, "DATA_DIRS", [root / "data"]),
            mock.patch.object(main, "UPLOAD_DIR", root / "data"),
            mock.patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}),
        ]
        for p in self.patches:
            p.start()
        main._CACHE.clear()
        self.fake = FakeExtractor()
        self.get_ex = mock.patch.object(main, "get_extractor", return_value=self.fake)
        self.get_ex.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.get_ex.stop()
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_health_hides_key(self):
        r = self.client.get("/health").json()
        self.assertTrue(r["api_key_configured"])
        self.assertNotIn("test-key", str(r))

    def test_files_and_records(self):
        self.assertEqual([f["id"] for f in self.client.get("/files").json()["files"]], ["data/calls.csv"])
        r = self.client.get("/records", params={"file": "data/calls.csv"}).json()
        self.assertEqual((r["count"], r["has_gold"]), (1, True))
        self.assertEqual(r["records"][0]["transcript_id"], "T1")

    def test_new_rows_appear_after_refresh(self):
        self.assertEqual(self.client.get("/records", params={"file": "data/calls.csv"}).json()["count"], 1)
        with open(self.csv, "a", encoding="utf-8", newline="") as f:      # user appends a record to the CSV
            f.write(ROW2)
        r = self.client.get("/records", params={"file": "data/calls.csv"}).json()
        self.assertEqual((r["count"], [x["transcript_id"] for x in r["records"]]), (2, ["T1", "T2"]))

    def test_path_traversal_rejected(self):
        for bad in ("../secret.csv", "data/../secret.csv", "secret.csv", "data/calls.txt"):
            self.assertEqual(self.client.get("/records", params={"file": bad}).status_code, 404, bad)

    def test_predict_returns_four_labels_and_feeds_only_input_fields(self):
        r = self.client.post("/predict", json={"transcript_id": "T1", "file": "data/calls.csv"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(set(body["prediction"]), {"transcript_id", "disposition", "sub_disposition",
                                                   "lead_quality", "next_call_at"})
        self.assertEqual((body["prompt_tokens"], body["completion_tokens"]), (11, 7))
        self.assertEqual(body["gold"]["lead_quality"], "Medium")          # shown for comparison only
        self.assertEqual(len(self.fake.seen), 1)
        self.assertNotIn("Follow-up Required", self.fake.seen[0][1])      # gold never reaches the LLM input

    def test_predict_unknown_id(self):
        r = self.client.post("/predict", json={"transcript_id": "NOPE", "file": "data/calls.csv"})
        self.assertEqual(r.status_code, 404)

    def test_upload(self):
        good = HEADER + ROW1
        r = self.client.post("/upload", files={"file": ("my calls.csv", good.encode(), "text/csv")})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["count"], 1)
        again = self.client.post("/upload", files={"file": ("my calls.csv", good.encode(), "text/csv")})
        self.assertNotEqual(again.json()["file"], r.json()["file"])      # never overwrites
        bad = self.client.post("/upload", files={"file": ("bad.csv", b"a,b\n1,2\n", "text/csv")})
        self.assertEqual(bad.status_code, 422)


if __name__ == "__main__":
    unittest.main()
