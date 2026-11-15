# prompts/

The complete, final prompt templates sent to the model. They are plain Markdown read at run time by `src/run.py` and
`app/backend/main.py` (folder set by `[prompts] dir` in `config.toml`); nothing else is added to the prompt.

| File | Role |
|---|---|
| `system.md` | System prompt: task and security rules, how to read a transcript (final-state rule, mutual agreement), a definition for every field of the evidence form, the time-expression guide, the exact output template, and a few short **synthetic** examples |
| `user.md` | User template with three placeholders: `{{CALL_STARTED_AT}}`, `{{CALL_WEEKDAY}}`, `{{TRANSCRIPT}}` (the transcript is wrapped in `<transcript>` tags and treated as data) |

Design notes:
- The model returns **evidence, not labels** (see `src/schema.py` for the schema). `src/rules.py` and
  `src/callback_time.py` turn that evidence into the four labels, so precedence, valid pairs and all date
  arithmetic live in tested Python, not in the prompt.
- The prompt is written from the policy rules (`assignment-v2`) only. It contains no real transcript text, IDs or
  per-call tuning; the examples are made up to illustrate rules.
- `tests/test_pipeline.py` checks that every field of the schema is documented in `system.md`, so the prompt and the
  validator cannot drift apart.
- The model is told to treat the transcript as untrusted data and to ignore instructions inside it.
