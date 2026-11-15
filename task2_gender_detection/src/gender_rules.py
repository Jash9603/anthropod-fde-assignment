"""Rule-based detection of the customer's gender from a call transcript. No ML model of any kind.

detect(transcript, cfg) -> {gender, confidence, male_score, female_score, reason, evidence}

Evidence (all weights in config.toml):
  1. the AGENT addresses the customer: "sir" -> male, "ma'am"/"madam" -> female
     (third-person uses such as "the madam will tell you" or "if ma'am has had tears" are ignored)
  2. the AGENT uses a title: "Mr. X" -> male, "Mrs./Miss/Ms. X" -> female
  3. the AGENT names the customer's spouse: "your husband" -> female, "your wife" -> male
  4. the CUSTOMER describes themselves: "my wife", "I am X's husband" -> male;
     "my husband", "I am X's wife", "I am pregnant", "I had a C-section", "I am a housewife" -> female
     (first person only: "my daughter is pregnant" says nothing about the speaker)
Not used on purpose: names (a name alone does not establish gender) and anything the CUSTOMER calls the agent
("sir"/"ma'am" on customer lines describes the agent, not the customer).

Speaker labels may be wrong, so each line's role is checked against clinic-side and customer-side cues.
Decision: no evidence -> unknown; a tie -> unknown; strong evidence for BOTH genders -> unknown (different
people spoke); otherwise the side with more evidence, with a confidence level.
"""
import re

SPEAKER = re.compile(r"^\s*(agent|customer)\s*:\s*(.*)$", re.I)

# --- address terms (agent lines) -----------------------------------------------------------------
ADDRESS = re.compile(r"\b(sir|ma'am|maam|madam|mam)\b", re.I)
THIRD_BEFORE = re.compile(r"\b(the|that|this|your|our|his|her|my|to|and|or|tell|told|ask|asked|about)\s*$", re.I)
THIRD_AFTER = re.compile(r"^\s*(has|have|had|is|was|were|will|would|said|says|told|and|or|sits|sitting|who)\b", re.I)
TITLE = re.compile(r"\b(Mr|Mrs|Miss|Ms)\b\.?\s+(?=[A-Z])")
AGENT_RELATION = re.compile(r"\byour (husband|wife)\b", re.I)

# --- self statements (customer lines) ------------------------------------------------------------
SELF_MALE = [re.compile(p, re.I) for p in (
    r"\bmy wife('s)?\b",
    r"\b(i am|i'm)\s+(\w+'s\s+)husband\b",
    r"\b(i am|i'm)\s+(her|the)\s+husband\b",
)]
SELF_FEMALE = [re.compile(p, re.I) for p in (
    r"\bmy husband('s)?\b",
    r"\b(i am|i'm)\s+(\w+'s\s+)wife\b",
    r"\b(i am|i'm)\s+(his|the)\s+wife\b",
    # Only FIRST-PERSON statements count: "I am pregnant" is the speaker, "my daughter is pregnant" is not.
    r"\b(i am|i'm|i was)\s+(?!not\b)(\w+\s+){0,3}pregnant\b",       # "I am pregnant", "I'm five months pregnant"
    r"\bmy pregnancy\b",
    r"\bi (had|have had|underwent|got) (a |an |my )?(c-section|caesarean)\b",
    r"\bmy (c-section|caesarean)\b",
    r"\b(i am|i'm) (a )?housewife\b",
)]

# --- role cues (to repair wrong speaker labels) -----------------------------------------------
# Clinic-side cues are things the clinic says ABOUT ITSELF. Merely mentioning the clinic ("are you speaking from Aster
# Vale?") or asking "where are you speaking from?" is not a cue: customers say both.
CLINIC_CUES = [re.compile(p, re.I) for p in (
    r"\b(i am|i'm|this is|we are)\b[^.?!]{0,40}\b(from|at)\s+(the\s+)?(aster vale|doctor'?s'? team)",
    r"\b(calling|speaking) from (the )?(aster vale|doctor'?s'? team)\b(?![^.?!]*\?)",
    r"\bour (doctor|doctors|clinic|clinics|center|centre|centers|treatment|treatments|procedure|procedures|team|"
    r"hospital|main|senior|specialists?)\b",
    r"\bwe (treat|provide|offer)\b",
    r"\bwe have (a |our |more than |four |multiple |centers|doctors|specialist|non-surgical|clinics)",
    r"\bconsultation (fee|fees|charge|charges) (is|are|will)\b",
    r"\bi will (book|share|send|whatsapp|message)\b",
    r"\b(what is|what's|what would be) (the patient's|your) (good )?(age|name)\b",
    r"\bthe procedures that we\b",
)]
CUSTOMER_CUES = [re.compile(p, re.I) for p in (
    r"\bmy (mother|mom|father|dad|wife|husband|son|daughter|knee|knees|back|leg|legs|pain|reports?)\b",
    r"\bi (have|had) (a |some |severe |back |knee )?(pain|problem)\b",
    r"\bi('m| am) (suffering|taking|a retired)\b",
    r"\bi saw your\b",
    r"\byour (clinic|doctors?|center|centre|ad)\b",
    r"\bhow much (is|will|does)\b",
    r"\bis (it|this) covered\b",
)]

MALE, FEMALE = "male", "female"


def _norm(text):
    return (text or "").replace("’", "'").replace("‘", "'")


def parse_lines(transcript):
    """[(line_no, label, text)] for lines that start with a speaker label."""
    out = []
    for n, raw in enumerate(_norm(transcript).splitlines(), 1):
        m = SPEAKER.match(raw)
        if m:
            out.append((n, m.group(1).lower(), m.group(2)))
    return out


def _cues(text, patterns):
    return sum(1 for p in patterns if p.search(text))


def assign_roles(lines, roles_cfg):
    """Return ([(line_no, role, text)], notes). Repairs swapped speaker labels using content cues."""
    notes = []
    clinic_by_label = {"agent": 0, "customer": 0}
    for _, label, text in lines:
        clinic_by_label[label] += _cues(text, CLINIC_CUES)
    swap = (clinic_by_label["customer"] >= roles_cfg["swap_min_cues"]
            and clinic_by_label["customer"] >= roles_cfg["swap_min_ratio"] * max(clinic_by_label["agent"], 1))
    if swap:
        notes.append("speaker labels look swapped for the whole call; roles reversed")
    k = roles_cfg["line_override_min_cues"]
    out, moved = [], 0
    for n, label, text in lines:
        role = {"agent": "customer", "customer": "agent"}[label] if swap else label
        clinic, cust = _cues(text, CLINIC_CUES), _cues(text, CUSTOMER_CUES)
        if role == "customer" and clinic >= k and cust == 0:
            role, moved = "agent", moved + 1
        elif role == "agent" and cust >= k and clinic == 0:
            role, moved = "customer", moved + 1
        out.append((n, role, text))
    if moved:
        notes.append(f"{moved} line(s) re-assigned to the other speaker from their content")
    return out, notes


def _is_direct_address(text, start, end):
    return not (THIRD_BEFORE.search(text[:start]) or THIRD_AFTER.search(text[end:]))


def collect_evidence(roled_lines, weights):
    ev = []

    def add(n, role, kind, vote, text):
        ev.append({"line": n, "speaker": role, "kind": kind, "vote": vote, "weight": weights[kind],
                   "text": text.strip()[:160]})

    for n, role, text in roled_lines:
        if role == "agent":
            for m in ADDRESS.finditer(text):
                if _is_direct_address(text, m.start(), m.end()):
                    add(n, role, "agent_address", MALE if m.group(1).lower() == "sir" else FEMALE, text)
            for m in TITLE.finditer(text):
                add(n, role, "agent_title", MALE if m.group(1) == "Mr" else FEMALE, text)
            for m in AGENT_RELATION.finditer(text):
                add(n, role, "agent_relation", FEMALE if m.group(1).lower() == "husband" else MALE, text)
        else:
            if any(p.search(text) for p in SELF_MALE):
                add(n, role, "self_statement", MALE, text)
            if any(p.search(text) for p in SELF_FEMALE):
                add(n, role, "self_statement", FEMALE, text)
    return ev


def decide(evidence, cfg):
    male = sum(e["weight"] for e in evidence if e["vote"] == MALE)
    female = sum(e["weight"] for e in evidence if e["vote"] == FEMALE)
    total, minority = male + female, min(male, female)
    d, c = cfg["decision"], cfg["confidence"]
    if total < d["min_total"]:
        return "unknown", "none", "no usable evidence (no address term, title or self-description)"
    share = minority / total
    if minority >= d["conflict_min_minority"] and share >= d["conflict_min_share"]:
        return "unknown", "none", (f"conflicting evidence (male {male:g} vs female {female:g}): "
                                   "most likely different people spoke during the call")
    if male == female:                                   # a tie gives no answer (was silently "female" before)
        return "unknown", "none", f"tied evidence (male {male:g} vs female {female:g})"
    gender = MALE if male > female else FEMALE
    if total >= c["high_min_total"] and share <= c["high_max_minority_share"]:
        conf = "high"
    elif total >= c["medium_min_total"]:
        conf = "medium"
    else:
        conf = "low"
    kinds = sorted({e["kind"] for e in evidence if e["vote"] == gender})
    return gender, conf, f"{gender}: score {max(male, female):g} vs {minority:g} from " + ", ".join(kinds)


def detect(transcript, cfg):
    lines = parse_lines(transcript)
    roled, notes = assign_roles(lines, cfg["roles"])
    evidence = collect_evidence(roled, cfg["weights"])
    gender, confidence, reason = decide(evidence, cfg)
    return {
        "gender": gender,
        "confidence": confidence,
        "male_score": sum(e["weight"] for e in evidence if e["vote"] == MALE),
        "female_score": sum(e["weight"] for e in evidence if e["vote"] == FEMALE),
        "reason": reason,
        "notes": notes,
        "evidence": evidence,
    }
