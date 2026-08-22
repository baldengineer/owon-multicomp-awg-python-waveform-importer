import json
from importlib.resources import files

import pytest

import awg_import
from arbdraw_bridge_adapter import send_waveform


def config(**overrides):
    values = {"max_point_count": 8, "max_dac_code": 16383, "expected_identity_prefix": ""}
    values.update(overrides)
    return awg_import.Config.from_defaults(values)


def document(values=None):
    values = [0.0, 1.0, 0.0, -1.0] if values is None else values
    return {"schema": "arbdraw.waveform", "version": 1, "name": "test", "waveform": {
        "type": "custom", "highVoltage": 1.0, "lowVoltage": -1.0,
        "sampleRateMSa": 1.0, "frequencyHz": 1000.0, "sampleCount": len(values), "values": values}}


def test_in_memory_loader_and_file_loader_share_validation(tmp_path):
    cfg = config()
    assert awg_import.waveform_from_document(document(), cfg).values == (0.0, 1.0, 0.0, -1.0)
    path = tmp_path / "waveform.json"
    path.write_text(json.dumps(document()), encoding="utf-8")
    assert awg_import.load_arbdraw_json(path, cfg).values == awg_import.waveform_from_document(document(), cfg).values


def test_public_modules_and_packaged_defaults_are_importable():
    from arbdraw_bridge_adapter import send_waveform as imported_sender

    assert callable(imported_sender)
    assert callable(awg_import.waveform_from_document)
    assert files("owon_xdg3000").joinpath("defaults.toml").is_file()
    assert awg_import.load_defaults("defaults.toml")["max_point_count"] == 100000


@pytest.mark.parametrize("change", [
    {"schema": "bad"}, {"version": 2},
])
def test_invalid_schema_or_version(change):
    project = document()
    project.update(change)
    with pytest.raises(ValueError):
        awg_import.waveform_from_document(project, config())


def test_sample_count_and_sample_validation():
    project = document()
    project["waveform"]["sampleCount"] = 3
    with pytest.raises(ValueError):
        awg_import.waveform_from_document(project, config())
    for value in [True, "1", float("nan"), float("inf"), 2.0]:
        with pytest.raises(ValueError):
            awg_import.waveform_from_document(document([0.0, value, 0.0, -1.0]), config())


def test_dac_encoding_and_ieee_block():
    waveform = awg_import.waveform_from_document(document(), config())
    assert awg_import.encode_dab(waveform, config()) == bytes.fromhex("20003fff20000000")
    payload = b"1234"
    assert awg_import.make_ieee_block(payload) == b"#14" + payload


@pytest.mark.parametrize("options", [
    {"channel": 3}, {"persist": 1}, {"enable_output": 1}, {"timeout_ms": 0},
    {"user_slot": 0}, {"user_slot": 32, "persist": True}, {"frequency_hz": True},
    {"unknown": 1},
])
def test_bridge_rejects_invalid_options(options):
    with pytest.raises(ValueError):
        send_waveform({"resource": "USB0::INSTR", "waveform": document(), "options": options})
