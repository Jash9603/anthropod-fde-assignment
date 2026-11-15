"""Unit tests on SYNTHETIC transcripts (one rule or trap per test). Run from task2_gender_detection/:
    python -m unittest discover -s tests -v
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from config import DEFAULTS, load_config                    # noqa: E402
from gender_rules import assign_roles, detect, parse_lines  # noqa: E402

CFG = load_config(ROOT / "config.toml")


def call(*lines):
    return "\n".join(lines)


def g(*lines):
    return detect(call(*lines), CFG)


class TestEvidence(unittest.TestCase):
    def test_agent_sir_is_male(self):
        r = g("Agent: Hi sir, I am Ravi calling from Aster Vale Care.", "Customer: Yes.",
              "Agent: Sir, what is the problem?", "Customer: Knee pain.", "Agent: Okay sir.")
        self.assertEqual((r["gender"], r["male_score"]), ("male", 3.0))

    def test_agent_maam_madam_mam_are_female(self):
        r = g("Agent: Hello ma'am.", "Customer: Yes.", "Agent: Madam, our doctors are available.", "Agent: Yes mam.")
        self.assertEqual((r["gender"], r["female_score"]), ("female", 3.0))

    def test_curly_apostrophe_is_normalised(self):
        self.assertEqual(g("Agent: Okay ma’am, thank you.")["gender"], "female")

    def test_customer_addressing_the_agent_is_ignored(self):
        # 'sir'/'ma'am' on CUSTOMER lines describe the agent, never the customer
        r = g("Agent: Hello, Aster Vale Care here.", "Customer: Yes sir, tell me sir.", "Customer: Okay sir.")
        self.assertEqual(r["gender"], "unknown")
        self.assertEqual(r["evidence"], [])

    def test_third_person_uses_are_ignored(self):
        r = g("Agent: Exactly, the madam will tell you the charges.",
              "Agent: Bring the reports for Ma'am and Sir.",
              "Agent: If ma'am has had tears twice, there is a reason.",
              "Agent: I have already told ma'am about it.",
              "Agent: Actually, sir was saying that she has back pain.")
        self.assertEqual(r["evidence"], [])

    def test_titles(self):
        self.assertEqual(g("Agent: Am I speaking with Mr. Kumar?")["gender"], "male")
        self.assertEqual(g("Agent: Thank you, Miss Rao.")["gender"], "female")
        self.assertEqual(g("Agent: Hello Mrs. Iyer.")["gender"], "female")

    def test_agent_relation(self):
        self.assertEqual(g("Agent: Please discuss it with your husband.")["gender"], "female")
        self.assertEqual(g("Agent: You can bring your wife tomorrow.")["gender"], "male")

    def test_self_statements(self):
        self.assertEqual(g("Customer: I will consult my wife and tell you.")["gender"], "male")
        self.assertEqual(g("Customer: Yes, I am Asha's husband speaking.")["gender"], "male")
        self.assertEqual(g("Customer: My husband is away this week.")["gender"], "female")
        self.assertEqual(g("Customer: I had a C-section two years ago.")["gender"], "female")

    def test_pregnancy_c_section_housewife_count_only_in_first_person(self):
        # about the speaker -> female vote
        for line in ("Customer: I am pregnant, so I need a safe treatment.",
                     "Customer: I'm five months pregnant.",
                     "Customer: The pain started after my pregnancy.",
                     "Customer: I had a C-section two years ago.",
                     "Customer: I am a housewife, I can come any time."):
            r = g(line)
            self.assertEqual((r["gender"], r["female_score"]), ("female", 3.0), line)
        # about someone else (or negated) -> no vote at all
        for line in ("Customer: My daughter is pregnant.",
                     "Customer: My daughter-in-law is pregnant, so she cannot come.",
                     "Customer: My mother is a housewife.",
                     "Customer: My sister had a C-section last year.",
                     "Customer: I am not pregnant, it is my back."):
            r = g(line)
            self.assertEqual(r["evidence"], [], line)

    def test_my_wife_had_a_c_section_is_male_not_a_conflict(self):
        r = g("Customer: My wife had a C-section, and now I have back pain.")
        self.assertEqual((r["gender"], r["male_score"], r["female_score"]), ("male", 3.0, 0))

    def test_self_statements_on_agent_lines_are_ignored(self):
        self.assertEqual(g("Agent: My wife also had knee pain, so I understand.")["gender"], "unknown")


class TestDecision(unittest.TestCase):
    def test_no_evidence_is_unknown(self):
        r = g("Agent: Hello, Aster Vale Care.", "Customer: I have back pain.")
        self.assertEqual((r["gender"], r["confidence"]), ("unknown", "none"))

    def test_a_tie_is_unknown(self):
        # 1 vs 1 is below the conflict threshold, but it must not default to either gender
        r = g("Agent: Okay sir.", "Agent: Yes ma'am.")
        self.assertEqual((r["gender"], r["confidence"]), ("unknown", "none"))
        self.assertIn("tied", r["reason"])

    def test_a_name_alone_is_not_evidence(self):
        # reviewer rule: a name cannot establish gender
        r = g("Agent: What is your name?", "Customer: My name is Zayan.", "Agent: Okay Zayan, Priya ji, Rahul.")
        self.assertEqual(r["gender"], "unknown")

    def test_speaker_change_gives_unknown(self):
        # reviewer rule: different people spoke -> do not label
        r = g("Customer: I am Renu's husband speaking.", "Agent: Okay sir.",
              "Customer: Wait, let me talk to my husband.", "Agent: Yes ma'am.", "Agent: Ma'am, grade three.",
              "Agent: Right, ma'am.", "Agent: Okay sir.")
        self.assertEqual(r["gender"], "unknown")
        self.assertIn("conflicting", r["reason"])

    def test_a_single_stray_opposite_term_does_not_flip_or_block(self):
        lines = ["Agent: Yes sir."] * 12 + ["Agent: Okay ma'am."]
        r = g(*lines)
        self.assertEqual((r["gender"], r["confidence"]), ("male", "high"))

    def test_confidence_levels(self):
        self.assertEqual(g("Agent: Okay sir.")["confidence"], "low")
        self.assertEqual(g("Agent: Okay sir.", "Agent: Yes sir.")["confidence"], "medium")
        self.assertEqual(g(*["Agent: Yes sir."] * 5)["confidence"], "high")


class TestRoles(unittest.TestCase):
    def test_whole_call_swap_is_repaired(self):
        # labels reversed: the 'Customer' is clearly the clinic, and it says 'ma'am'
        t = call("Customer: Hi ma'am, I am Neha calling from Aster Vale Care.",
                 "Agent: Yes, tell me.",
                 "Customer: Ma'am, our doctors treat knee pain without surgery. We have four centers.",
                 "Agent: My knee hurts a lot.",
                 "Customer: The consultation fee is 1000 rupees, ma'am. I will share the location.")
        r = detect(t, CFG)
        self.assertEqual(r["gender"], "female")
        self.assertTrue(any("swapped" in n for n in r["notes"]))

    def test_customer_mentioning_the_clinic_does_not_trigger_a_swap(self):
        # regression: customers also say "Aster Vale" and ask "where are you speaking from?"
        t = call("Agent: Yes, I am speaking from Aster Vale Pain Clinic. Tell me.",
                 "Customer: Where are you speaking from? Aster Vale?",
                 "Customer: I am asking where is Aster Vale Pain Clinic located?",
                 "Customer: Are you speaking from Aster Vale, sir? What are you saying, sir?",
                 "Agent: Okay, sir.")
        lines, notes = assign_roles(parse_lines(t), CFG["roles"])
        self.assertEqual(notes, [])
        r = detect(t, CFG)
        self.assertEqual((r["gender"], r["male_score"]), ("male", 1.0))   # only the agent's own 'sir'

    def test_single_line_override(self):
        # one mislabeled clinic line inside an otherwise correctly labeled call
        t = call("Agent: Hello.", "Customer: My mother has knee pain.",
                 "Customer: Mr. Sharma, our doctors are specialists and we have four centers.",
                 "Agent: Okay.")
        r = detect(t, CFG)
        self.assertEqual(r["gender"], "male")
        self.assertTrue(any("re-assigned" in n for n in r["notes"]))


class TestConfig(unittest.TestCase):
    def test_committed_config_matches_defaults(self):
        self.assertEqual(load_config(ROOT / "config.toml"), DEFAULTS)

    def test_bad_config_is_rejected(self):
        for bad in ("[weights]\nagent_adress = 1.0\n", "[decision]\nmin_total = \"x\"\n", "[nope]\na = 1\n"):
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / "c.toml"
                p.write_text(bad, encoding="utf-8")
                with self.assertRaises(ValueError, msg=bad):
                    load_config(p)

    def test_weights_change_the_decision(self):
        cfg = load_config(ROOT / "config.toml")
        cfg["decision"]["min_total"] = 5.0
        self.assertEqual(detect("Agent: Okay sir.", cfg)["gender"], "unknown")


if __name__ == "__main__":
    unittest.main()
