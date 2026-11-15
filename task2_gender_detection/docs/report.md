# Task 2 - Customer gender detection: method, evaluation and limitations

## Summary
- **Task:** identify the customer's gender from each call transcript without a transformer-based model.
- **Approach:** weighted, explainable rules over what the agent calls the customer and what the customer says about
  themselves; standard library only (no ML of any kind, no name lists, no API).
- **Result on the 50 calls:** 50/50 agree with the reviewed labels (34 male, 14 female, 2 unknown); 96% of calls get an
  answer, and the 2 unknowns are the calls the reviewer also judged unknowable.
- **Caveat:** the rules were written after reading these 50 calls, and the labels were drafted from the same kind of
  evidence, so 100% here is an upper bound, not an estimate for new calls. See *Limitations*.

## What the data allows
The transcripts are English translations of Hindi/Hinglish calls. The strongest Hindi signal, gendered verb endings
(*raha hoon* / *rahi hoon*), does not survive translation: it appears in 0 of 50 calls. What remains:

| Signal | Calls (of 50) |
|---|---|
| Agent says "sir" | 34 |
| Agent says "ma'am" / "madam" | 17 |
| Agent uses Mr. / Mrs. / Miss / Ms. | 8 |
| Customer says "my wife" / "my husband" / similar | 10 |

Two traps found while reading the calls shaped the design:
1. **The customer also says "sir" and "ma'am"** (to the agent) in 32 of 50 calls. Counting these terms over the whole
   transcript would mostly measure the agent's gender. Only the agent's lines are used for address terms.
2. **Speaker labels can be wrong.** In AVT-049 the labels are reversed from the first line (the "Agent" says "I'm a
   retired officer"). Roles are therefore checked from content.

## Method
For each call:
1. **Roles.** Lines are parsed as Agent / Customer. If the "Customer" lines carry clearly more clinic-side wording
   (the clinic talking about itself: "I am X from Aster Vale", "our doctors", "consultation charges are...") than the
   "Agent" lines, the labels are swapped for the call; a single line with strong wording of the other role is
   re-assigned. Merely mentioning the clinic or asking "where are you speaking from?" is *not* clinic wording, because
   customers say both.
2. **Evidence** (weights in `config.toml`):

   | Kind | Example | Vote | Weight |
   |---|---|---|---|
   | `agent_address` | Agent: "Okay **sir**" | male | 1 |
   | `agent_address` | Agent: "Yes **ma'am**" | female | 1 |
   | `agent_title` | Agent: "**Mr.** Kartik" / "**Miss** Kavita" | male / female | 2 |
   | `agent_relation` | Agent: "discuss it with **your husband**" | female | 2 |
   | `self_statement` | Customer: "I will consult **my wife**", "I am Renu's **husband**" / "**my husband** is away", "**I am pregnant**", "**I had a C-section**", "**I am a housewife**" | male / female | 3 |

   Self-descriptions count only in the first person: "my daughter is pregnant" or "my mother is a housewife" says
   nothing about the speaker and gives no vote; "my wife had a C-section" is a male vote (from "my wife") only.

   Ignored on purpose: names (reviewer rule: a name alone cannot identify gender); anything on customer lines except
   self-statements; third-person uses ("**the madam** will tell you", "if **ma'am has** had tears", "**Ma'am and Sir**"
   meaning the parents).
3. **Decision.** No evidence, or a tie, gives **unknown**. If the weaker side has at least 2 points and at least 25%
   of all points, the call is **unknown**: different people spoke (reviewer rule). Otherwise the stronger side wins, with confidence
   **high** (5+ points, at most 10% for the other side), **medium** (2+ points) or **low** (1 point).

Every prediction lists its evidence lines with line numbers, so any decision can be checked by hand.

## Gold labels
No gender labels exist for these calls, so they were created for evaluation, independently of the classifier:
1. A helper script (`scripts/extract_evidence.py`) listed every potentially relevant line of each call.
2. I read those lines and drafted a label for each call (before the classifier existed).
3. The reviewer (the candidate) checked all 50 rows and changed two, introducing two rules that the classifier then
   adopted: **a call where the speaker changes is unknown** (AVT-008: the husband speaks, then the wife, then the
   husband again), and **a name alone is not evidence** (AVT-039: the only clue is the name "Zayan").

Final labels (`labels/gold_gender.csv`): 34 male, 14 female, 2 unknown.

## Results (50 calls)

| Metric | Value |
|---|---|
| Overall agreement (unknown counts only when the label is unknown) | 50 / 50 |
| Coverage (answered male / female) | 48 / 50 = 96% |
| Accuracy on answered calls | 48 / 48 |
| By confidence | high 37/37, medium 8/8, low 3/3, unknown 2/2 |

Evidence used: agent address terms in 48 calls (30 calls were decided by them alone), customer self-statements in 10,
titles in 8, "your husband / wife" in 3.

## Iteration
- First version: also 50/50, but **one call was right for the wrong reason**. In AVT-048 the code decided the labels
  were swapped for the whole call and took the customer's "What is your name, sir?" as the agent addressing the
  customer. Cause: "Aster Vale" and "where are you speaking from?" were treated as clinic-side wording, but customers
  say them too. Fix: clinic cues must be the clinic speaking about itself, and a whole-call swap needs clearly lopsided
  evidence. After the fix AVT-048 is decided by the agent's own "Okay, sir", no call is swapped by mistake, and an audit
  confirms no agent evidence is taken from a line labeled Customer. A regression test covers it.
- Two reviewer rules (speaker change gives unknown; names are not evidence) replaced the earlier plan to report the
  main speaker and use names as a fallback.
- A code review found two problems that the 50 calls did not expose: a 1-vs-1 tie silently became "female", and
  "pregnant" / "C-section" / "housewife" voted female even when said about someone else ("my daughter is pregnant",
  or "my wife had a C-section", which created a false conflict). Fixed: a tie is unknown, and these phrases count only
  in the first person ("I am pregnant", "I had a C-section", "I am a housewife"). Tests cover each case; results on
  the 50 calls are unchanged.

## Limitations
- **Optimistic score.** The rules were designed after reading these 50 calls and the labels lean on the same evidence,
  so the 100% is an upper bound. The unit tests use synthetic transcripts to check each rule in isolation, but there is
  no independent held-out set.
- **Depends on the agent's address terms.** 30 of 50 calls are decided by "sir" / "ma'am" alone. If an agent misgenders
  a customer, or the speech-to-text drops these words, the answer follows the agent.
- **Translation and transcription.** Gendered Hindi verbs are lost in translation; a transcript in Hinglish or Hindi
  would need extra rules (for example *rahi hoon* / *raha hoon*, *karungi* / *karunga*).
- **Fixed vocabulary.** Self-statements are matched with a short list of phrases; unusual phrasings are missed and
  then count as no evidence (the call becomes unknown or low confidence, never a confident wrong answer).
- **Binary labels.** The method only distinguishes male and female address forms; it says nothing about gender identity
  beyond how the customer is addressed or describes themselves.
- **Role repair is conservative.** It did not need to trigger on these calls after the AVT-048 fix; it is covered by
  synthetic tests but untested on real swapped calls with address terms on the swapped lines.
