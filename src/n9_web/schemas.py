"""Pydantic request models for the n9-web API."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


# ── Temperature ────────────────────────────────────────────────────────────────

class TemperatureTarget(BaseModel):
    target_c: float = Field(ge=0.0, le=60.0, description="PID setpoint (°C)")
    max_power_pct: Optional[float] = Field(default=None, gt=0.0, le=100.0)
    sensor_pin: Optional[int] = Field(default=None, ge=1, le=5)


# ── Spectral ───────────────────────────────────────────────────────────────────

class ScanRequest(BaseModel):
    board_ids: Optional[List[str]] = None


class SensorSettingsRequest(BaseModel):
    gain: int
    atime: int = Field(ge=0, le=255)
    astep: int = Field(ge=0, le=65535)


class BoardEnabledRequest(BaseModel):
    enabled: bool


class LedRequest(BaseModel):
    board_id: Optional[str] = None    # None = all connected boards
    on: bool


# ── Sample holder editing ──────────────────────────────────────────────────────

class SlotEditRequest(BaseModel):
    col: int = Field(ge=0)
    row: int = Field(ge=0)
    state: Literal["FRESH", "EMPTY", "USED", "CLEAN"]
    sample_type: str = "PC"


class AddSamplesRequest(BaseModel):
    count: int = Field(gt=0, le=90)
    sample_type: str = "PC"


# ── Robot / locations ─────────────────────────────────────────────────────────

class Location(BaseModel):
    type: Literal["holder", "pcb", "test_cell"]
    id: Optional[str] = None          # holder_id or sensing-station id
    col: Optional[int] = Field(default=None, ge=0)
    row: Optional[int] = Field(default=None, ge=0)


class MoveXYZ(BaseModel):
    x: float
    y: float
    z: float


class GripperRequest(BaseModel):
    action: Literal["open", "close"]


class TransferRequest(BaseModel):
    from_: Location = Field(alias="from")
    to: Location

    model_config = {"populate_by_name": True}


class PickPlaceRequest(BaseModel):
    location: Location


# ── Test cell ──────────────────────────────────────────────────────────────────

class TestCellInsert(BaseModel):
    from_: Location = Field(alias="from")

    model_config = {"populate_by_name": True}


class TestCellRetrieve(BaseModel):
    to: Location


class PistonRequest(BaseModel):
    engage: bool


class FillRequest(BaseModel):
    pump: Optional[str] = None
    volume_ml: float = Field(gt=0.0)


class DrainRequest(BaseModel):
    volume_ml: Optional[float] = Field(default=None, gt=0.0)


# ── Pumps ──────────────────────────────────────────────────────────────────────

class PeristalticRequest(BaseModel):
    volume_ml: float = Field(gt=0.0)


class StepperRequest(BaseModel):
    ml: float = Field(description="Volume (mL); negative = reverse")
    flow_rate: float = Field(default=0.02, gt=0.0, le=1.0)


class MultiStepperRequest(BaseModel):
    volumes: List[float] = Field(min_length=4, max_length=4)
    flow_rate: float = Field(default=0.02, gt=0.0, le=1.0)


class PrimeRequest(BaseModel):
    peristaltic_ml: float = Field(default=2.0, gt=0.0, le=25.0)
    stepper_ml: float = Field(default=1.0, gt=0.0, le=10.0)
    stepper_flow: float = Field(default=0.04, gt=0.0, le=1.0)


# ── Electrochemistry ──────────────────────────────────────────────────────────

class EchemRunRequest(BaseModel):
    technique: Literal["CV", "EIS", "CP", "CA", "OCP"]
    params: dict
    sample_id: str = ""     # optional: sample identity stored with the result


# ── Experiment ────────────────────────────────────────────────────────────────

class ExperimentStartRequest(BaseModel):
    experiment_path: str
    resume: bool = False


class ExperimentAbortRequest(BaseModel):
    hard: bool = False
