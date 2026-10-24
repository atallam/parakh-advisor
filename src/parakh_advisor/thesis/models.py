"""The thesis as an immutable, versioned object (design section 6.1)."""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class DriverStatus(StrEnum):
    OK = "OK"
    WATCH = "WATCH"
    BROKEN = "BROKEN"
    UNKNOWN = "UNKNOWN"


class Stance(StrEnum):
    STRONG = "STRONG"
    INTACT = "INTACT"
    WEAKENING = "WEAKENING"
    BROKEN = "BROKEN"
    INSUFFICIENT = "INSUFFICIENT"


class Confidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ChangeDecision(StrEnum):
    NEW = "NEW"
    REAFFIRM = "REAFFIRM"
    AMEND = "AMEND"
    REPLACE = "REPLACE"


class Driver(BaseModel):
    """Something that must stay true for the reason to own the stock to hold."""

    id: str
    statement: str
    kind: str = Field(pattern="^(metric|qualitative)$")
    indicator: str | None = None  # metric key, e.g. "roe"; metric drivers only
    direction: str | None = Field(default=None, pattern="^(gte|lte)$")  # which way is good
    warn_threshold: float | None = None
    break_threshold: float | None = None
    status: DriverStatus = DriverStatus.UNKNOWN
    evidence_ids: list[str] = []


class KillCriterion(BaseModel):
    """A measurable condition that, once tripped, breaks the thesis. Fixed at creation."""

    id: str
    description: str
    indicator: str
    op: str = Field(pattern="^(<|>)$")
    threshold: float
    tripped: bool = False


class Risk(BaseModel):
    statement: str
    evidence_ids: list[str] = []


class Change(BaseModel):
    field: str
    from_value: str
    to_value: str
    new_evidence_ids: list[str] = []


class Thesis(BaseModel):
    model_config = ConfigDict(frozen=True)

    instrument_id: str
    version: int
    as_of_data_date: date
    model: str
    prompt_version: str
    inputs_digest: str
    business_summary: str
    why_own: str
    drivers: list[Driver]
    kill_criteria: list[KillCriterion]
    risks: list[Risk]
    stance: Stance = Stance.INSUFFICIENT
    confidence: Confidence = Confidence.LOW
    skeptic_counter_case: str | None = None
    change_decision: ChangeDecision = ChangeDecision.NEW
    change_log: list[Change] = []
    rejected_changes: list[str] = []  # changes the code refused, kept for audit
