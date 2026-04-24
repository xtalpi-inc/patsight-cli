from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml

from patsight_cli.exceptions import ConfigError


def load_yaml_config(path: str | None) -> Dict[str, Any]:
    if not path:
        return {}
    file_path = Path(path)
    if not file_path.exists():
        raise ConfigError(f"Config file not found: {path}")
    with file_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ConfigError("Config root must be a mapping")
    return data


def resolve_profile(config: Dict[str, Any], profile_name: str | None) -> Dict[str, Any]:
    if not profile_name:
        return {}
    profiles = config.get("profiles", {})
    if profile_name not in profiles:
        raise ConfigError(f"Profile '{profile_name}' not found in config")
    profile = profiles[profile_name]
    if not isinstance(profile, dict):
        raise ConfigError(f"Profile '{profile_name}' must be a mapping")
    return profile


def merge_client_kwargs(cli_kwargs: Dict[str, Any], profile_kwargs: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(profile_kwargs)
    for k, v in cli_kwargs.items():
        if v is not None and v != "":
            merged[k] = v
    return merged
