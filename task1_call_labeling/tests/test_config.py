"""Configuration tests (no network). Run from task1_call_labeling/:  python -m unittest discover -s tests -v"""
import inspect
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from config import DEFAULTS, extractor_kwargs, load_config, prompts_dir  # noqa: E402
from llm_client import GroqExtractor, LLMResult                          # noqa: E402
from pipeline import process_record                                      # noqa: E402
from schema import Extraction                                            # noqa: E402


def write_toml(text):
    d = tempfile.TemporaryDirectory()
    p = Path(d.name) / "c.toml"
    p.write_text(text, encoding="utf-8")
    return d, p


class TestLoadConfig(unittest.TestCase):
    def test_committed_config_matches_built_in_defaults(self):
        # the shipped config.toml and the code defaults must never drift apart
        self.assertEqual(load_config(ROOT / "config.toml"), DEFAULTS)

    def test_missing_explicit_file_is_an_error(self):
        with self.assertRaises(FileNotFoundError):
            load_config(ROOT / "does_not_exist.toml")

    def test_overrides_are_applied_and_the_rest_keeps_defaults(self):
        d, p = write_toml('[llm]\ntemperature = 0.3\nmodel = "openai/gpt-oss-120b"\n[retries]\nmax_attempts = 2\n'
                          '[guardrails]\nmin_alpha_chars = 5\n')
        with d:
            cfg = load_config(p)
        self.assertEqual((cfg["llm"]["temperature"], cfg["llm"]["model"]), (0.3, "openai/gpt-oss-120b"))
        self.assertEqual((cfg["retries"]["max_attempts"], cfg["guardrails"]["min_alpha_chars"]), (2, 5))
        self.assertEqual(cfg["llm"]["seed"], DEFAULTS["llm"]["seed"])               # untouched
        self.assertEqual(DEFAULTS["llm"]["temperature"], 0.0)                       # defaults are never mutated

    def test_env_variable_selects_the_file(self):
        d, p = write_toml("[llm]\nseed = 99\n")
        with d, mock.patch.dict(os.environ, {"LABELING_CONFIG": str(p)}):
            self.assertEqual(load_config()["llm"]["seed"], 99)

    def test_unknown_keys_and_wrong_types_are_rejected(self):
        for bad in ("[llm]\ntempreture = 0.1\n", "[nope]\nx = 1\n", '[llm]\nmax_tokens = "many"\n',
                    "[llm]\nmax_tokens = 1.5\n", "[llm]\njson_mode = 1\n", '[llm]\ntemperature = "hot"\n',
                    "[retries]\nmax_attempts = true\n"):
            d, p = write_toml(bad)
            with d, self.assertRaises(ValueError, msg=bad):
                load_config(p)

    def test_int_is_accepted_for_a_float_setting(self):
        d, p = write_toml("[llm]\ntemperature = 1\ntimeout_s = 30\n")
        with d:
            cfg = load_config(p)
        self.assertEqual((cfg["llm"]["temperature"], cfg["llm"]["timeout_s"]), (1.0, 30.0))
        self.assertIsInstance(cfg["llm"]["temperature"], float)

    def test_app_models_table_is_replaced_not_merged(self):
        d, p = write_toml('[app.models]\n"openai/gpt-oss-20b" = "low"\n')
        with d:
            self.assertEqual(load_config(p)["app"]["models"], {"openai/gpt-oss-20b": "low"})
        d, p = write_toml("[app.models]\n")
        with d, self.assertRaises(ValueError):
            load_config(p)

    def test_prompts_dir_relative_and_absolute(self):
        self.assertEqual(prompts_dir(load_config(ROOT / "config.toml")), ROOT / "prompts")
        cfg = load_config(ROOT / "config.toml")
        cfg["prompts"]["dir"] = str(ROOT / "other")
        self.assertEqual(prompts_dir(cfg), ROOT / "other")


class TestExtractorKwargs(unittest.TestCase):
    def test_every_kwarg_is_a_real_client_parameter(self):
        # drift guard: a config key renamed on one side only would fail here
        params = set(inspect.signature(GroqExtractor.__init__).parameters)
        kw = extractor_kwargs(load_config(ROOT / "config.toml"))
        self.assertLessEqual(set(kw), params, set(kw) - params)

    def test_cli_style_overrides_and_empty_effort(self):
        cfg = load_config(ROOT / "config.toml")
        kw = extractor_kwargs(cfg, model="openai/gpt-oss-20b", reasoning_effort="low")
        self.assertEqual((kw["model"], kw["reasoning_effort"]), ("openai/gpt-oss-20b", "low"))
        self.assertIsNone(extractor_kwargs(cfg, reasoning_effort="")["reasoning_effort"])    # "" = not sent
        self.assertEqual(extractor_kwargs(cfg)["reasoning_effort"], cfg["llm"]["reasoning_effort"])

    def test_config_values_reach_the_client(self):
        d, p = write_toml("[llm]\njson_mode = false\nmin_expected_keys = 3\ntemperature = 0.2\n"
                          "[retries]\nquota_wait_threshold_s = 30.0\nmax_shrinks = 1\nshrink_factor = 0.5\n"
                          "shrink_head_chars = 500\n")
        with d:
            cfg = load_config(p)
        ex = GroqExtractor(system_prompt="s", user_template="{{TRANSCRIPT}}", client=object(), **extractor_kwargs(cfg))
        self.assertEqual((ex.json_mode, ex.min_expected_keys, ex.temperature), (False, 3, 0.2))
        self.assertEqual((ex.max_rate_limit_wait, ex.max_shrinks, ex.shrink_factor, ex.shrink_head_chars),
                         (30.0, 1, 0.5, 500))

    def test_json_mode_off_and_temperature_are_sent_to_the_api(self):
        sent = {}

        class Client:
            def __init__(self):
                self.chat = type("Chat", (), {"completions": self})()

            def create(self, **kw):
                sent.update(kw)
                msg = type("M", (), {"content": json.dumps(Extraction().model_dump())})()
                return type("R", (), {"choices": [type("C", (), {"message": msg})()],
                                      "usage": type("U", (), {"prompt_tokens": 1, "completion_tokens": 1})()})()

        cfg = load_config(ROOT / "config.toml")
        cfg["llm"].update(json_mode=False, temperature=0.4, max_tokens=123, seed=5)
        ex = GroqExtractor(system_prompt="s", user_template="{{TRANSCRIPT}}", client=Client(),
                           **extractor_kwargs(cfg, reasoning_effort="low"))
        self.assertIsNotNone(ex.extract("2026-11-09T14:00:00+05:30", "Monday", "hello").extraction)
        self.assertNotIn("response_format", sent)
        self.assertEqual((sent["temperature"], sent["max_tokens"], sent["seed"]), (0.4, 123, 5))
        self.assertEqual(sent["extra_body"], {"reasoning_effort": "low"})


class TestGuardrailConfig(unittest.TestCase):
    REC = {"transcript_id": "T1", "call_started_at": "2026-11-09T14:00:00+05:30", "timezone": "Asia/Kolkata",
           "transcript": "Agent: Hello this is the clinic. Customer: I want to book a consultation please."}

    class Fake:
        def __init__(self):
            self.calls = 0

        def extract(self, *a):
            self.calls += 1
            return LLMResult(extraction={"relevant_discussion": True}, attempts=1)

    def test_min_alpha_chars_comes_from_the_guardrail_config(self):
        fake = self.Fake()
        process_record(dict(self.REC), fake, {"min_alpha_chars": 5})
        self.assertEqual(fake.calls, 1)
        fake = self.Fake()
        process_record(dict(self.REC), fake, {"min_alpha_chars": 10000})       # nothing is "enough" text: LLM skipped
        self.assertEqual(fake.calls, 0)

    def test_transcript_length_cap_comes_from_the_guardrail_config(self):
        seen = []

        class Spy(self.Fake):
            def extract(self, started, weekday, text):
                seen.append(text)
                return super().extract()

        rec = dict(self.REC, transcript="a" * 5000 + "b" * 5000 + " THE END")
        process_record(rec, Spy(), {"max_transcript_chars": 2000, "head_chars": 500})
        self.assertLess(len(seen[0]), 2100)
        self.assertTrue(seen[0].endswith("THE END"))


if __name__ == "__main__":
    unittest.main()
