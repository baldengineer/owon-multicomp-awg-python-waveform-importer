"""Native ArbDraw bridge adapter for the OWON XDG3000 importer."""

from __future__ import annotations

import math
from importlib.resources import files
from typing import Any

import awg_import


def _number(value: Any, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"options.{name} must be a number")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0):
        adjective = "positive finite" if positive else "finite"
        raise ValueError(f"options.{name} must be {adjective}")
    return result


def send_waveform(request: dict[str, Any]) -> dict[str, Any]:
    """Validate, encode, and upload one in-memory ArbDraw document."""
    if not isinstance(request, dict):
        raise ValueError("request must be an object")
    resource = request.get("resource")
    if not isinstance(resource, str) or not resource:
        raise ValueError("resource must be a non-empty string")
    if not resource.upper().startswith("USB"):
        raise ValueError("bulk waveform uploads require a USBTMC resource")
    document = request.get("waveform")
    options = request.get("options", {})
    if not isinstance(document, dict):
        raise ValueError("waveform must be an object")
    if not isinstance(options, dict):
        raise ValueError("options must be an object")
    allowed = {"channel", "persist", "user_slot", "enable_output", "timeout_ms", "frequency_hz", "amplitude_vpp", "offset_voltage"}
    unknown = sorted(set(options) - allowed)
    if unknown:
        raise ValueError(f"unknown option: {unknown[0]}")
    channel = options.get("channel", 1)
    if isinstance(channel, bool) or channel not in (1, 2):
        raise ValueError("options.channel must be 1 or 2")
    persist = options.get("persist", False)
    enable = options.get("enable_output", False)
    if not isinstance(persist, bool) or not isinstance(enable, bool):
        raise ValueError("options.persist and options.enable_output must be boolean")
    timeout = options.get("timeout_ms", 60000)
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
        raise ValueError("options.timeout_ms must be a positive integer")
    slot = options.get("user_slot")
    if slot is not None and (isinstance(slot, bool) or not isinstance(slot, int) or not 0 <= slot <= 31):
        raise ValueError("options.user_slot must be an integer from 0 through 31 or null")
    if slot is not None and not persist:
        raise ValueError("options.user_slot requires options.persist=true")
    config = awg_import.Config.from_defaults({**_defaults(), "timeout_ms": timeout})
    waveform = awg_import.waveform_from_document(document, config)
    payload = awg_import.encode_dab(waveform, config)
    frequency = waveform.frequency_hz if options.get("frequency_hz") is None else _number(options["frequency_hz"], "frequency_hz", positive=True)
    amplitude = waveform.amplitude_vpp if options.get("amplitude_vpp") is None else _number(options["amplitude_vpp"], "amplitude_vpp", positive=True)
    offset = waveform.offset_voltage if options.get("offset_voltage") is None else _number(options["offset_voltage"], "offset_voltage")
    result = awg_import.upload_waveform(resource, timeout, waveform, payload, slot if persist else None, channel, enable, amplitude, offset, frequency, config)
    return {"status": "sent", "message": f"Loaded {result['points']} points into EMEMory on channel {channel}; output is {'on' if result['output'] == '1' else 'off'}.", "adapter": "owon-xdg3000", "identity": result["identity"], "points": int(result["points"]), "channel": channel, "output_enabled": result["output"] == "1", "persistent_memory": result["user_memory"] or None}


def _defaults() -> dict[str, Any]:
    try:
        resource = files("owon_xdg3000").joinpath("defaults.toml")
        return awg_import.load_defaults(resource)
    except (OSError, TypeError, ValueError):
        return {}
