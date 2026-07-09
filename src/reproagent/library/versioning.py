"""semver bump + dedup_hash。"""

from __future__ import annotations

import hashlib
from typing import Literal

from reproagent.models.factor_def import FactorDefinition


def compute_dedup_hash(factor: FactorDefinition) -> str:
    """sha256(formula + sorted(input_fields))。"""
    key = factor.formula + "|" + "|".join(sorted(factor.input_fields))
    return hashlib.sha256(key.encode()).hexdigest()


def bump(version: str, level: Literal["major", "minor", "patch"]) -> str:
    """semver bump。"""
    parts = version.split(".")
    if len(parts) != 3:
        raise ValueError(f"非法 semver: {version}")
    major, minor, patch = (int(p) for p in parts)
    if level == "major":
        return f"{major + 1}.0.0"
    if level == "minor":
        return f"{major}.{minor + 1}.0"
    if level == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise ValueError(f"未知 level: {level}")
