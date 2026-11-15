# Task 2 - Customer gender detection (rule-based, no ML)

Identifies the **customer's gender** (male / female / unknown) in each call transcript using transparent rules. No
transformer or any other machine-learning model, no name lists, no API. Every answer comes with a confidence level and
the exact transcript lines behind it.

## How to run

**Step 1 - get the code**
```
git clone https://github.com/Jash9603/anthropod-fde-assignment.git
cd anthropod-fde-assignment/task2_gender_detection
```

**Step 2 - one command**
```
python run_app.py
```

The first run creates a local environment and installs the dashboard (about a minute); later runs start immediately.
The dashboard opens at http://127.0.0.1:8502:
- upload your CSV in the sidebar (columns `transcript_id`, `transcript`);
- **All calls** shows a gender and confidence for every call;
- **Inspect a call**: pick an ID (type to search) to see the evidence lines and the transcript with them marked;
- **Session history** keeps what you inspected, downloadable as CSV; **Refresh data** picks up rows added to the CSV.

Needs Python 3.11 or newer. No API key.

**Batch mode** (standard library only, nothing to install):
```
python src/run.py --input calls.csv --output predictions.jsonl
```
Input: CSV or JSONL with `transcript_id` and `transcript`. Output, one line per call: `transcript_id`, `gender`,
`confidence` (high / medium / low / none), `male_score`, `female_score`, `reason`; the evidence lines go to
`<output>.evidence.jsonl`.

**Tests and scoring:**
```
python -m unittest discover -s tests -v
python scripts/evaluate.py --gold labels/gold_gender.csv --pred predictions.jsonl --show-errors
```

## Approach

The transcripts are English translations of Hindi/Hinglish calls, so gendered Hindi verb endings (*raha hoon* /
*rahi hoon*) are gone (0 of 50 calls). The usable signals are how the **agent addresses the customer** and how the
**customer describes themselves**.

```
transcript -> split into "Agent:" / "Customer:" lines -> check who really said each line
           -> find evidence (keyword patterns) -> add up the votes -> male / female / unknown + confidence
```

**1. Lines and roles.** The transcript is split at newlines; only lines starting with `Agent:` or `Customer:` are used.
Speaker labels can be wrong, so each line is checked for wording only the clinic uses about itself ("I am X from Aster
Vale", "our doctors", "consultation charges are ...") or only a customer uses ("my mother has knee pain", "how much is
it"). If the "Customer" lines are clearly the clinic, the labels are swapped for the call; a single clearly mislabeled
line is moved.

**2. Evidence.** Regular-expression patterns, matched as whole words:

| Evidence | Points to | Weight |
|---|---|---|
| The **agent** calls the customer "sir" / "ma'am", "madam" | male / female | 1 each time |
| The **agent** uses "Mr." / "Mrs.", "Miss", "Ms." before a name | male / female | 2 |
| The **agent** says "your wife" / "your husband" | male / female | 2 |
| The **customer** says "my wife", "I am X's husband" | male | 3 |
| The **customer** says "my husband", "I am X's wife", "I am pregnant", "I had a C-section", "I am a housewife" | female | 3 |

Deliberately **not** used:
- **What the customer calls the agent.** Customers say "sir" / "ma'am" to the agent (32 of 50 calls); that describes
  the agent, not the customer.
- **Third-person uses.** "*the* madam will tell you", "if ma'am *has* had tears", "Ma'am *and* Sir" (the parents).
- **Names.** A name alone does not establish gender.
- **Statements about someone else.** "My daughter is pregnant" says nothing about the speaker; only first-person
  statements count.

**3. Decision.**

| Situation | Answer |
|---|---|
| No evidence | unknown |
| Equal evidence for both genders (a tie) | unknown |
| Real evidence for both (weaker side 2+ points and 25%+ of the total): different people spoke during the call | unknown |
| Otherwise | the stronger side, with confidence **high** (5+ points, at most 10% the other way), **medium** (2+), **low** (1) |

All weights and thresholds are in [config.toml](config.toml).

## Results on the 50 supplied calls

| | |
|---|---|
| Agreement with the reviewed labels | **50 / 50** (34 male, 14 female, 2 unknown) |
| Answered male or female | 48 / 50 (96%); the 2 unknowns are a call where the speaker changes and a call with only a name |
| By confidence | high 37/37, medium 8/8, low 3/3 |

The labels were created for this task (none were supplied): drafted from the evidence lines of each call, then checked
and corrected by a human reviewer. Predictions: [outputs/predictions_50.jsonl](outputs/predictions_50.jsonl). How the
labels were made, and how the rules were fixed along the way: [docs/report.md](docs/report.md).

## Known limitations

- **The 100% is optimistic.** The rules were written after reading these 50 calls, and the labels rest on the same kind
  of evidence, so this is an upper bound, not a forecast for new calls. There is no independent held-out set; the unit
  tests use synthetic transcripts to check each rule in isolation.
- **It follows the agent.** 30 of the 50 calls are decided by "sir" / "ma'am" alone. If the agent misgenders the
  customer, or the transcription drops these words, the answer follows the agent.
- **Translated text only.** Gendered Hindi verb forms are lost in translation. A transcript in Hindi or Hinglish would
  need extra rules (*rahi hoon* / *raha hoon*, *karungi* / *karunga*).
- **Fixed phrase lists.** Self-descriptions are matched against a short list of phrases. An unusual phrasing is simply
  missed: the call then gets lower confidence or unknown, not a confident wrong answer.
- **One person per call.** When the phone changes hands the answer is unknown by design; it does not report each
  speaker separately.
- **Binary address forms.** It distinguishes only male and female forms of address and self-description, and says
  nothing about gender identity beyond that.
- **Role repair is lightly tested on real data.** After a fix it did not need to trigger on these 50 calls; it is
  covered by synthetic tests only.

## Files

| Path | What it is |
|---|---|
| `run_app.py` | one command: first-run setup, then the dashboard |
| `src/gender_rules.py` | the rules: line parsing, role repair, evidence patterns, decision |
| `src/run.py` | batch runner (CSV / JSONL in, predictions JSONL out) |
| `src/config.py`, `config.toml` | settings (weights, thresholds, ports), validated on load |
| `app/streamlit_app.py` | dashboard |
| `scripts/evaluate.py` | accuracy, coverage, confusion matrix, error list |
| `scripts/extract_evidence.py` | lists relevant lines per call, used to create the labels |
| `labels/gold_gender.csv` | reviewed labels for the 50 calls (IDs and genders only) |
| `tests/` | unit tests on synthetic transcripts |
| `docs/report.md` | detailed method, label process, iteration log |
