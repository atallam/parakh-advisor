"""Your risk policy (config/policy.yaml). Parameters live in config, never in code."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class Policy(BaseModel):
    version: int = 1
    single_name_cap_pct: float = Field(10.0, gt=0, le=100)
    top3_cap_pct: float = Field(35.0, gt=0, le=100)
    single_sector_cap_pct: float = Field(30.0, gt=0, le=100)
    dust_pct: float = Field(0.1, ge=0, le=100)
    hysteresis_buffer_pp: float = Field(2.0, ge=0)
    dcf_discount_rate: dict[str, float] = Field(default_factory=lambda: {"US": 0.10, "IN": 0.15})


def load_policy(path: str | Path = "config/policy.yaml") -> Policy:
    p = Path(path)
    if not p.exists():
        return Policy()
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return Policy(**data)
