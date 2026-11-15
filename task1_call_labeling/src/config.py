"""Configuration: built-in defaults < config.toml < command-line flags.

`config.toml` (repo folder `task1_call_labeling/`) holds every tunable setting. A different file can be selected with
`--config path` or the LABELING_CONFIG environment variable. Secrets (the API key) are NOT configuration: they come from
the GROQ_API_KEY environment variable or a local .env file.

Unknown keys and values of the wrong type raise ValueError, so a typo cannot silently do nothing.
Only the standard library is used (tomllib, Python 3.11+).
"""
import copy
import os
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config.toml"

DEFAULTS = {
    "llm": {
        "model": "qwen/qwen3.8-27b",
        "reasoning_effort": "none",       # "" = not sent; qwen: none|default; gpt-oss: low|medium|high
        "temperature": 0.0,
        "max_tokens": 4096,               # includes hidden reasoning tokens
        "seed": 7,
        "json_mode": True,                # response_format=json_object
        "timeout_s": 90.0,                # per API call
        "min_expected_keys": 8,           # a reply with fewer expected top-level keys is retried
    },
    "retries": {
        "max_attempts": 4,                # per record: API errors and malformed replies
        "max_rate_limit_waits": 12,       # 429 waits per record (do not use an attempt)
        "quota_wait_threshold_s": 120.0,  # a 429 asking for a longer wait means the quota is spent
        "max_shrinks": 3,                 # times a 413 request is shortened and resent
        "shrink_factor": 0.7,             # each shortening keeps ~this fraction of the transcript
        "shrink_head_chars": 3000,        # start of the transcript always kept when shortening
    },
    "guardrails": {
        "max_transcript_chars": 40000,    # longer transcripts are truncated (start and end kept)
        "head_chars": 4000,               # start kept when truncating
        "min_alpha_chars": 15,            # fewer letters than this: skip the LLM, record is Unable to Assess
    },
    "prompts": {
        "dir": "prompts",                 # relative to task1_call_labeling/ (or absolute)
    },
    "app": {
        "default_model": "qwen/qwen3.8-27b",
        "host": "127.0.0.1",
        "backend_port": 8000,
        "frontend_port": 8501,
        "max_upload_mb": 20,
        # models offered in the web app -> reasoning_effort sent for that model ("" = not sent).
        # A [app.models] table in config.toml REPLACES this one.
        "models": {
            "qwen/qwen3.8-27b": "none",
            "openai/gpt-oss-120b": "low",
            "openai/gpt-oss-20b": "low",
        },
    },
}


def _check(default, value, path):
    """Return value coerced to the default's type, or raise ValueError."""
    name = ".".join(path)
    if isinstance(default, bool):
        if not isinstance(value, bool):
            raise ValueError(f"config {name}: expected true/false, got {value!r}")
        return value
    if isinstance(default, int):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"config {name}: expected an integer, got {value!r}")
        return value
    if isinstance(default, float):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"config {name}: expected a number, got {value!r}")
        return float(value)
    if isinstance(default, str):
        if not isinstance(value, str):
            raise ValueError(f"config {name}: expected a string, got {value!r}")
        return value
    return value


def _apply(base: dict, over: dict, path: tuple):
    for key, value in over.items():
        here = path + (key,)
        if key not in base:
            raise ValueError(f"config: unknown setting '{'.'.join(here)}'")
        if here == ("app", "models"):                      # free-form table: replaced, not merged
            if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
                raise ValueError("config app.models: expected a table of model id = reasoning_effort strings")
            if not value:
                raise ValueError("config app.models: must list at least one model")
            base[key] = dict(value)
        elif isinstance(base[key], dict):
            if not isinstance(value, dict):
                raise ValueError(f"config {'.'.join(here)}: expected a table")
            _apply(base[key], value, here)
        else:
            base[key] = _check(base[key], value, here)


def load_config(path=None) -> dict:
    """Defaults, overlaid with the TOML file at `path` (or $LABELING_CONFIG, or config.toml if it exists)."""
    explicit = path or os.environ.get("LABELING_CONFIG")
    p = Path(explicit) if explicit else DEFAULT_CONFIG_PATH
    cfg = copy.deepcopy(DEFAULTS)
    if p.exists():
        with open(p, "rb") as f:
            _apply(cfg, tomllib.load(f), ())
    elif explicit:
        raise FileNotFoundError(f"config file not found: {p}")
    return cfg


def clean_api_key(value) -> str:
    """The API key, or "" when it is missing or still the placeholder copied from .env.example."""
    v = (value or "").strip()
    return "" if not v or v.lower().startswith("your_") else v


def prompts_dir(cfg: dict) -> Path:
    d = Path(cfg["prompts"]["dir"])
    return d if d.is_absolute() else ROOT / d


def extractor_kwargs(cfg: dict, model=None, reasoning_effort=None) -> dict:
    """Keyword arguments for llm_client.GroqExtractor (everything except the prompts and the client).

    `model` / `reasoning_effort` override the [llm] values when given (reasoning_effort "" means not sent)."""
    llm, rt = cfg["llm"], cfg["retries"]
    effort = llm["reasoning_effort"] if reasoning_effort is None else reasoning_effort
    return {
        "model": model or llm["model"],
        "reasoning_effort": effort or None,
        "temperature": llm["temperature"],
        "max_tokens": llm["max_tokens"],
        "seed": llm["seed"],
        "json_mode": llm["json_mode"],
        "timeout": llm["timeout_s"],
        "min_expected_keys": llm["min_expected_keys"],
        "max_attempts": rt["max_attempts"],
        "max_rate_limit_waits": rt["max_rate_limit_waits"],
        "quota_wait_threshold_s": rt["quota_wait_threshold_s"],
        "max_shrinks": rt["max_shrinks"],
        "shrink_factor": rt["shrink_factor"],
        "shrink_head_chars": rt["shrink_head_chars"],
    }
