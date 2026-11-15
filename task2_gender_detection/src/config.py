"""Configuration: built-in defaults < config.toml < command-line flags (standard library only)."""
import copy
import os
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config.toml"

DEFAULTS = {
    "weights": {"agent_address": 1.0, "agent_title": 2.0, "agent_relation": 2.0, "self_statement": 3.0},
    "decision": {"min_total": 1.0, "conflict_min_minority": 2.0, "conflict_min_share": 0.25},
    "confidence": {"high_min_total": 5.0, "high_max_minority_share": 0.1, "medium_min_total": 2.0},
    "roles": {"swap_min_cues": 3, "swap_min_ratio": 2.0, "line_override_min_cues": 2},
    "app": {"host": "127.0.0.1", "port": 8502, "max_upload_mb": 20},
}


def _check(default, value, name):
    if isinstance(default, bool):
        ok = isinstance(value, bool)
    elif isinstance(default, int):
        ok = isinstance(value, int) and not isinstance(value, bool)
    elif isinstance(default, float):
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        value = float(value) if ok else value
    else:
        ok = isinstance(value, str)
    if not ok:
        raise ValueError(f"config {name}: wrong type {value!r}")
    return value


def _apply(base, over, path=()):
    for key, value in over.items():
        name = ".".join(path + (key,))
        if key not in base:
            raise ValueError(f"config: unknown setting '{name}'")
        if isinstance(base[key], dict):
            if not isinstance(value, dict):
                raise ValueError(f"config {name}: expected a table")
            _apply(base[key], value, path + (key,))
        else:
            base[key] = _check(base[key], value, name)


def load_config(path=None) -> dict:
    explicit = path or os.environ.get("GENDER_CONFIG")
    p = Path(explicit) if explicit else DEFAULT_CONFIG_PATH
    cfg = copy.deepcopy(DEFAULTS)
    if p.exists():
        with open(p, "rb") as f:
            _apply(cfg, tomllib.load(f))
    elif explicit:
        raise FileNotFoundError(f"config file not found: {p}")
    return cfg
