"""Shared router helpers: app-state accessors.

Hardware-layer exceptions (ExperimentActive → 409, DeviceBusy → 423,
DeviceUnavailable → 503, KeyError/ValueError → 400) are mapped to HTTP
responses by app-level exception handlers registered in n9_web.app.
"""

from __future__ import annotations

from fastapi import Request

from n9_web.hardware import HardwareManager


def get_hw(request: Request) -> HardwareManager:
    return request.app.state.hw


def get_experiment_service(request: Request):
    return request.app.state.experiment_service


def get_echem_service(request: Request):
    return request.app.state.echem_service
