# Copyright (c) 2026 James Lewis (james@baldengineer.com)
# SPDX-License-Identifier: MIT
"""Import JSON or CSV waveform samples into an OWON XDG3000-family AWG."""

from __future__ import annotations

import argparse
import csv
import json
import math
import struct
import sys
import time
import tomllib
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULTS_FILE = "defaults.toml"
EXPECTED_IDENTITY_PREFIX: str
MAX_POINT_COUNT: int
MAX_DAC_CODE: int


def load_defaults(path: str | Path) -> dict[str, Any]:
    """Load and validate the flat TOML defaults table."""
    try:
        with Path(path).open("rb") as stream:
            defaults = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"Could not read defaults TOML: {exc}") from exc
    if not isinstance(defaults, dict):
        raise ValueError("Defaults TOML must contain a table")
    required = {
        "usb_resource",
        "timeout_ms",
        "expected_identity_prefix",
        "max_point_count",
        "max_dac_code",
        "frequency_hz",
        "voltage_vpp",
        "offset_voltage",
        "channel",
        "enable_output",
        "persist",
    }
    missing = sorted(required - defaults.keys())
    if missing:
        raise ValueError(f"Defaults TOML is missing required keys: {', '.join(missing)}")
    return defaults


@dataclass(frozen=True)
class Waveform:
    """Validated waveform samples and metadata needed by the AWG."""

    name: str
    waveform_type: str
    values: tuple[float, ...]
    low_voltage: float
    high_voltage: float
    sample_rate_sa: float
    frequency_hz: float

    @property
    def sample_count(self) -> int:
        return len(self.values)

    @property
    def amplitude_vpp(self) -> float:
        return self.high_voltage - self.low_voltage

    @property
    def offset_voltage(self) -> float:
        return (self.high_voltage + self.low_voltage) / 2.0

def list_visa_resources() -> tuple[str, ...]:
    """Return detected VISA resource strings in backend-provided order."""
    try:
        import pyvisa
    except ImportError as exc:
        raise RuntimeError("PyVISA is required to list VISA resources") from exc

    try:
        resource_manager = pyvisa.ResourceManager()
        try:
            return tuple(resource_manager.list_resources())
        finally:
            resource_manager.close()
    except Exception as exc:
        raise RuntimeError(f"VISA backend error: {exc}") from exc


def _finite_number(value: Any, field: str) -> float:
    """Convert JSON numeric metadata while rejecting booleans and non-finite values."""
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite number")
    try:
        converted = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite number") from exc
    if not math.isfinite(converted):
        raise ValueError(f"{field} must be a finite number")
    return converted


def load_arbdraw_json(path: str | Path) -> Waveform:
    """Read and strictly validate the authoritative ArbDraw sample array."""
    source = Path(path)
    try:
        project = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read ArbDraw JSON: {exc}") from exc

    if not isinstance(project, dict):
        raise ValueError("ArbDraw project must be a JSON object")
    if project.get("schema") != "arbdraw.waveform":
        raise ValueError("Unsupported ArbDraw schema; expected arbdraw.waveform")
    if project.get("version") != 1:
        raise ValueError("Unsupported ArbDraw version; expected 1")

    waveform = project.get("waveform")
    if not isinstance(waveform, dict):
        raise ValueError("Missing waveform object")

    sample_count_number = _finite_number(
        waveform.get("sampleCount"), "waveform.sampleCount"
    )
    sample_count = math.floor(sample_count_number + 0.5)
    if not 2 <= sample_count <= MAX_POINT_COUNT:
        raise ValueError(
            f"waveform.sampleCount must resolve to 2 through {MAX_POINT_COUNT}"
        )

    values = waveform.get("values")
    if not isinstance(values, list) or len(values) != sample_count:
        raise ValueError("waveform.values length must equal waveform.sampleCount")

    converted_values: list[float] = []
    for index, value in enumerate(values):
        # ArbDraw requires actual JSON numbers in the sample array, not numeric strings.
        if isinstance(value, bool) or type(value) not in (int, float):
            raise ValueError(f"waveform.values[{index}] must be a finite JSON number")
        converted = float(value)
        if not math.isfinite(converted):
            raise ValueError(f"waveform.values[{index}] must be finite")
        converted_values.append(converted)

    low_voltage = _finite_number(
        waveform.get("lowVoltage"), "waveform.lowVoltage"
    )
    high_voltage = _finite_number(
        waveform.get("highVoltage"), "waveform.highVoltage"
    )
    if high_voltage <= low_voltage:
        raise ValueError("waveform.highVoltage must be greater than lowVoltage")

    tolerance = max(1.0, abs(low_voltage), abs(high_voltage)) * 1e-9
    for index, value in enumerate(converted_values):
        if value < low_voltage - tolerance or value > high_voltage + tolerance:
            raise ValueError(
                f"waveform.values[{index}]={value:g} is outside the declared "
                f"range {low_voltage:g} through {high_voltage:g}"
            )

    sample_rate_msa = _finite_number(
        waveform.get("sampleRateMSa"), "waveform.sampleRateMSa"
    )
    if sample_rate_msa <= 0:
        raise ValueError("waveform.sampleRateMSa must be greater than zero")

    frequency_hz = _finite_number(
        waveform.get("frequencyHz"), "waveform.frequencyHz"
    )
    if frequency_hz <= 0:
        raise ValueError("waveform.frequencyHz must be greater than zero")

    name = project.get("name", "Imported waveform")
    if not isinstance(name, str):
        name = str(name)
    waveform_type = waveform.get("type", "custom")
    if not isinstance(waveform_type, str):
        waveform_type = "custom"

    return Waveform(
        name=name,
        waveform_type=waveform_type,
        values=tuple(converted_values),
        low_voltage=low_voltage,
        high_voltage=high_voltage,
        sample_rate_sa=sample_rate_msa * 1_000_000.0,
        frequency_hz=frequency_hz,
    )


def load_csv(
    path: str | Path, *, delimiter: str = ",", value_column: int | None = None
) -> Waveform:
    """Load a headerless CSV waveform, optionally selecting its voltage column."""
    source = Path(path)
    if len(delimiter) != 1:
        raise ValueError("CSV delimiter must be exactly one character")
    if value_column is not None and value_column < 0:
        raise ValueError("CSV value column must be zero or greater")
    times: list[float] = []
    values: list[float] = []
    try:
        with source.open("r", encoding="utf-8-sig", newline="") as stream:
            for row_number, row in enumerate(
                csv.reader(stream, delimiter=delimiter), start=1
            ):
                if not row or all(not cell.strip() for cell in row):
                    continue
                if value_column is None and len(row) == 1:
                    selected_column = 0
                    time_value = len(values)
                elif value_column is None and len(row) == 2:
                    selected_column = 1
                    time_value = row[0].strip()
                elif value_column is not None and value_column < len(row):
                    selected_column = value_column
                    time_value = len(values)
                else:
                    raise ValueError(
                        f"CSV row {row_number} has no column {value_column}"
                    )
                times.append(
                    _finite_number(time_value, f"CSV row {row_number} time")
                )
                values.append(
                    _finite_number(
                        row[selected_column].strip(), f"CSV row {row_number} voltage"
                    )
                )
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ValueError(f"Could not read CSV: {exc}") from exc

    if not 2 <= len(values) <= MAX_POINT_COUNT:
        raise ValueError(f"CSV must contain 2 through {MAX_POINT_COUNT} samples")

    intervals = [later - earlier for earlier, later in zip(times, times[1:])]
    if any(interval <= 0 for interval in intervals):
        raise ValueError("CSV timestamps must be strictly increasing")
    interval = sum(intervals) / len(intervals)
    tolerance = max(abs(interval) * 1e-6, 1e-15)
    if any(abs(candidate - interval) > tolerance for candidate in intervals):
        raise ValueError("CSV timestamps must be uniformly spaced")

    low_voltage = min(values)
    high_voltage = max(values)
    if high_voltage <= low_voltage:
        raise ValueError("CSV voltages must span more than one value")
    sample_rate_sa = 1.0 / interval

    return Waveform(
        name=source.stem,
        waveform_type="csv",
        values=tuple(values),
        low_voltage=low_voltage,
        high_voltage=high_voltage,
        sample_rate_sa=sample_rate_sa,
        frequency_hz=sample_rate_sa / len(values),
    )


def load_waveform(
    path: str | Path, *, csv_delimiter: str = ",", csv_value_column: int | None = None
) -> Waveform:
    """Load a waveform according to its filename extension."""
    source = Path(path)
    if source.suffix.lower() == ".csv":
        return load_csv(
            source, delimiter=csv_delimiter, value_column=csv_value_column
        )
    return load_arbdraw_json(source)


def encode_dab(waveform: Waveform) -> bytes:
    """Encode samples as verified unsigned 14-bit big-endian AWG codes."""
    span = waveform.amplitude_vpp
    codes = []
    for value in waveform.values:
        normalized = (value - waveform.low_voltage) / span
        normalized = min(1.0, max(0.0, normalized))
        code = int(normalized * MAX_DAC_CODE + 0.5)
        codes.append(code)
    return struct.pack(f">{len(codes)}H", *codes)


def make_ieee_block(payload: bytes) -> bytes:
    """Wrap payload bytes in an IEEE 488.2 definite-length block."""
    byte_count = str(len(payload)).encode("ascii")
    return b"#" + str(len(byte_count)).encode("ascii") + byte_count + payload


def _query_nonempty(instrument: Any, command: str) -> str:
    """Query USBTMC and retry transient empty end-of-message responses."""
    for _ in range(3):
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="read string doesn't end with termination characters",
                category=UserWarning,
            )
            response = instrument.query(command).strip()
        if response:
            return response
        time.sleep(0.25)
    raise RuntimeError(f"Instrument returned an empty response to {command}")


def query_visa_identity(resource: str, timeout_ms: int) -> str:
    """Open one VISA resource and return its response to ``*IDN?``."""
    try:
        import pyvisa
    except ImportError as exc:
        raise RuntimeError("PyVISA is required to query a VISA resource") from exc

    try:
        resource_manager = pyvisa.ResourceManager()
        instrument = None
        try:
            instrument = resource_manager.open_resource(resource)
            instrument.timeout = timeout_ms
            instrument.read_termination = "\n"
            instrument.write_termination = "\n"
            return _query_nonempty(instrument, "*IDN?")
        finally:
            if instrument is not None:
                instrument.close()
            resource_manager.close()
    except Exception as exc:
        raise RuntimeError(f"VISA communication error: {exc}") from exc


def set_output_state(resource: str, timeout_ms: int, channel: int, enabled: bool) -> None:
    """Send only the channel output command to a VISA resource."""
    try:
        import pyvisa
    except ImportError as exc:
        raise RuntimeError("PyVISA is required to control a VISA resource") from exc

    resource_manager = None
    instrument = None
    try:
        resource_manager = pyvisa.ResourceManager()
        instrument = resource_manager.open_resource(resource)
        instrument.timeout = timeout_ms
        instrument.write_termination = "\n"
        instrument.write(f"OUTP{channel} {'ON' if enabled else 'OFF'}")
    except Exception as exc:
        raise RuntimeError(f"VISA output control error: {exc}") from exc
    finally:
        if instrument is not None:
            instrument.close()
        if resource_manager is not None:
            resource_manager.close()


def _require_no_scpi_error(instrument: Any, stage: str) -> str:
    status = _query_nonempty(instrument, "SYSTem:ERRor:NEXT?")
    if not status.lstrip().startswith("0"):
        raise RuntimeError(f"SCPI error after {stage}: {status}")
    return status


def _clear_scpi_errors(instrument: Any) -> None:
    for _ in range(64):
        if _query_nonempty(instrument, "SYSTem:ERRor:NEXT?").startswith("0"):
            return
    raise RuntimeError("SCPI error queue did not clear")


def upload_waveform(
    resource: str,
    timeout_ms: int,
    waveform: Waveform,
    payload: bytes,
    user_slot: int | None,
    channel: int,
    enable_output: bool,
    amplitude_vpp: float,
    offset_voltage: float,
    frequency_hz: float,
) -> dict[str, str]:
    """Bulk upload over USBTMC, persist it, select edit memory, and set final output."""
    try:
        import pyvisa
    except ImportError as exc:
        raise RuntimeError("PyVISA is required for instrument uploads") from exc

    resource_manager = pyvisa.ResourceManager()
    instrument = None
    panel_locked = False
    completed = False
    output_command = f"OUTP{channel}"
    source_command = f"SOUR{channel}"
    try:
        instrument = resource_manager.open_resource(resource)
        instrument.timeout = timeout_ms
        instrument.read_termination = "\n"
        instrument.write_termination = "\n"

        identity = _query_nonempty(instrument, "*IDN?")
        if EXPECTED_IDENTITY_PREFIX and not identity.startswith(
            EXPECTED_IDENTITY_PREFIX
        ):
            raise RuntimeError(f"Unexpected instrument identity: {identity}")

        _clear_scpi_errors(instrument)
        instrument.write(f"{output_command} OFF")
        _require_no_scpi_error(instrument, f"disabling channel {channel}")
        if _query_nonempty(instrument, f"{output_command}?") != "0":
            raise RuntimeError(f"Channel {channel} did not turn off")

        # Prevent front-panel changes from racing the multi-step import. The finally
        # block releases the lock if any upload or configuration command fails.
        instrument.write("SYSTem:KLOCk ON")
        panel_locked = True
        _require_no_scpi_error(instrument, "locking the front panel")

        instrument.write(f"DATA:POINts EMEMory,{waveform.sample_count}")
        _require_no_scpi_error(instrument, "allocating edit memory")
        allocated_points = _query_nonempty(instrument, "DATA:POINts? EMEMory")
        if allocated_points != str(waveform.sample_count):
            raise RuntimeError(
                f"AWG allocated {allocated_points} points; expected "
                f"{waveform.sample_count}"
            )

        message = b"DATA:DATA EMEMory," + make_ieee_block(payload) + b"\n"
        instrument.write_raw(message)
        time.sleep(2.0)
        _require_no_scpi_error(instrument, "bulk waveform upload")

        user_memory = "" if user_slot is None else f"USER{user_slot}"
        if user_memory:
            instrument.write(f"DATA:COPY {user_memory},EMEMory")
            # Large persistent copies can take longer than the USB transfer itself.
            time.sleep(5.0)
            _require_no_scpi_error(instrument, f"storing waveform in {user_memory}")

        instrument.write(f"{source_command}:FUNCtion EMEMory")
        time.sleep(0.5)
        _require_no_scpi_error(
            instrument, f"selecting edit memory on channel {channel}"
        )
        selected_function = _query_nonempty(
            instrument, f"{source_command}:FUNCtion?"
        )
        if selected_function.lower() != "ememory":
            raise RuntimeError(
                f"Channel {channel} selected {selected_function}; expected EMEMory"
            )

        instrument.write(f"{source_command}:VOLTage {amplitude_vpp:.12g}Vpp")
        _require_no_scpi_error(instrument, f"setting channel {channel} amplitude")
        instrument.write(
            f"{source_command}:VOLTage:OFFSet {offset_voltage:.12g}V"
        )
        _require_no_scpi_error(instrument, f"setting channel {channel} offset")
        instrument.write(f"{source_command}:FREQuency {frequency_hz:.12g}Hz")
        status = _require_no_scpi_error(instrument, "setting record repetition rate")

        # Enabling the physical output is deliberately the final instrument change.
        # Any failure before completed becomes true triggers the output-off safeguard.
        instrument.write(f"{output_command} {'ON' if enable_output else 'OFF'}")
        _require_no_scpi_error(
            instrument, f"setting final channel {channel} output state"
        )
        output = _query_nonempty(instrument, f"{output_command}?")
        expected_output = "1" if enable_output else "0"
        if output != expected_output:
            raise RuntimeError(
                f"Channel {channel} output state is {output}; expected {expected_output}"
            )

        instrument.write("SYSTem:KLOCk OFF")
        _require_no_scpi_error(instrument, "unlocking the front panel")
        panel_locked = False

        result = {
            "identity": identity,
            "points": _query_nonempty(instrument, "DATA:POINts? EMEMory"),
            "user_memory": user_memory,
            "channel": str(channel),
            "function": selected_function,
            "output": output,
            "error": status,
        }
        completed = True
        return result
    finally:
        if instrument is not None:
            try:
                if not completed or not enable_output:
                    instrument.write(f"{output_command} OFF")
            finally:
                try:
                    if panel_locked:
                        instrument.write("SYSTem:KLOCk OFF")
                finally:
                    instrument.close()
        resource_manager.close()


def parse_args() -> argparse.Namespace:
    global EXPECTED_IDENTITY_PREFIX, MAX_POINT_COUNT, MAX_DAC_CODE
    defaults_parser = argparse.ArgumentParser(add_help=False)
    defaults_parser.add_argument("--defaults-file", type=Path, default=DEFAULTS_FILE)
    defaults_args, _ = defaults_parser.parse_known_args()
    try:
        defaults = load_defaults(defaults_args.defaults_file)
    except ValueError as exc:
        defaults_parser.error(str(exc))
    EXPECTED_IDENTITY_PREFIX = defaults["expected_identity_prefix"]
    MAX_POINT_COUNT = defaults["max_point_count"]
    MAX_DAC_CODE = defaults["max_dac_code"]

    parser = argparse.ArgumentParser(
        description=(
            "Import an ArbDraw JSON or headerless x,y CSV waveform into an OWON "
            "XDG3000-family AWG "
            "over USBTMC."
        )
    )
    parser.add_argument(
        "--defaults-file",
        type=Path,
        default=defaults_args.defaults_file,
        help=f"TOML defaults file (default: {DEFAULTS_FILE})",
    )
    parser.add_argument(
        "waveform_file",
        type=Path,
        nargs="?",
        help="ArbDraw JSON or headerless x,y CSV (x seconds, y volts) waveform file",
    )
    parser.add_argument(
        "--csv-delimiter",
        default=",",
        help="CSV field delimiter (default: comma)",
    )
    parser.add_argument(
        "--csv-column",
        dest="csv_value_column",
        type=int,
        metavar="INDEX",
        help="zero-based CSV voltage column; single-column CSVs use column 0",
    )
    parser.add_argument(
        "--list-resources",
        action="store_true",
        help="list detected VISA resource strings, one per line",
    )
    parser.add_argument(
        "--idn",
        metavar="RESOURCE",
        help="query *IDN? on the given VISA resource after optional discovery",
    )
    parser.add_argument(
        "--output",
        choices=("on", "off"),
        help="send only an output state command to --channel",
    )
    parser.add_argument(
        "--resource",
        default=defaults["usb_resource"],
        help="VISA resource",
    )
    parser.add_argument(
        "--visa-timeout-ms",
        type=int,
        default=defaults["timeout_ms"],
        help="VISA timeout in milliseconds",
    )
    parser.add_argument(
        "--persist",
        action=argparse.BooleanOptionalAction,
        default=defaults["persist"],
        help="copy the waveform into persistent USER memory (default: defaults.toml)",
    )
    parser.add_argument(
        "--user-slot",
        type=int,
        choices=range(32),
        metavar="0..31",
        help="persistent USER memory slot; requires --persist (default: channel-based)",
    )
    parser.add_argument(
        "--channel",
        type=int,
        choices=(1, 2),
        default=defaults["channel"],
        help="AWG output channel to configure",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and encode the file without contacting the AWG",
    )
    parser.add_argument(
        "--enable-output",
        action=argparse.BooleanOptionalAction,
        default=defaults["enable_output"],
        help="leave the selected channel enabled after a completely successful import",
    )
    parser.add_argument(
        "--frequency",
        "--frequency-hz",
        dest="frequency_hz",
        type=float,
        default=defaults["frequency_hz"],
        help="override the JSON frequencyHz value in Hz",
    )
    parser.add_argument(
        "--amplitude",
        "--amplitude-vpp",
        dest="amplitude_vpp",
        type=float,
        default=defaults["voltage_vpp"],
        help="override the JSON-derived channel amplitude in Vpp",
    )
    parser.add_argument(
        "--offset",
        "--offset-v",
        dest="offset_voltage",
        type=float,
        default=defaults["offset_voltage"],
        help="override the JSON-derived channel offset in volts",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if (args.list_resources or args.idn is not None or args.output is not None) and args.waveform_file is not None:
        print(
            "Do not provide a waveform file with --list-resources, --idn, or --output",
            file=sys.stderr,
        )
        return 2

    if args.list_resources:
        try:
            resources = list_visa_resources()
        except (RuntimeError, OSError) as exc:
            print(f"Could not list VISA resources: {exc}", file=sys.stderr)
            return 1
        if not resources:
            print("No VISA resources found", file=sys.stderr)
        else:
            print(*resources, sep="\n")

    if args.idn is not None:
        if args.visa_timeout_ms <= 0:
            print("--visa-timeout-ms must be greater than zero", file=sys.stderr)
            return 2
        try:
            print(query_visa_identity(args.idn, args.visa_timeout_ms))
        except RuntimeError as exc:
            print(f"Could not query VISA resource: {exc}", file=sys.stderr)
            return 1
        return 0

    if args.list_resources:
        return 0

    if args.output is not None:
        if args.visa_timeout_ms <= 0:
            print("--visa-timeout-ms must be greater than zero", file=sys.stderr)
            return 2
        try:
            set_output_state(
                args.resource,
                args.visa_timeout_ms,
                args.channel,
                args.output == "on",
            )
        except RuntimeError as exc:
            print(f"Could not set channel {args.channel} output: {exc}", file=sys.stderr)
            return 1
        print(f"Channel {args.channel} output: {args.output.upper()}")
        return 0

    if args.waveform_file is None:
        print("A waveform file is required", file=sys.stderr)
        return 2

    if args.visa_timeout_ms <= 0:
        print("--visa-timeout-ms must be greater than zero", file=sys.stderr)
        return 2
    if args.frequency_hz is not None and (
        not math.isfinite(args.frequency_hz) or args.frequency_hz <= 0
    ):
        print("--frequency must be a positive finite number", file=sys.stderr)
        return 2
    if args.amplitude_vpp is not None and (
        not math.isfinite(args.amplitude_vpp) or args.amplitude_vpp <= 0
    ):
        print("--amplitude must be a positive finite number", file=sys.stderr)
        return 2
    if args.offset_voltage is not None and not math.isfinite(args.offset_voltage):
        print("--offset must be a finite number", file=sys.stderr)
        return 2
    if args.csv_value_column is not None and args.csv_value_column < 0:
        print("--csv-column must be zero or greater", file=sys.stderr)
        return 2
    if args.user_slot is not None and not args.persist:
        print("--user-slot requires --persist", file=sys.stderr)
        return 2

    try:
        waveform = load_waveform(
            args.waveform_file,
            csv_delimiter=args.csv_delimiter,
            csv_value_column=args.csv_value_column,
        )
        payload = encode_dab(waveform)
        block = make_ieee_block(payload)
        amplitude_vpp = (
            waveform.amplitude_vpp
            if args.amplitude_vpp is None
            else args.amplitude_vpp
        )
        offset_voltage = (
            waveform.offset_voltage
            if args.offset_voltage is None
            else args.offset_voltage
        )
        frequency_hz = (
            waveform.frequency_hz
            if args.frequency_hz is None
            else args.frequency_hz
        )
        user_slot = (
            args.channel if args.user_slot is None else args.user_slot
        ) if args.persist else None

        print(f"Name: {waveform.name}")
        print(f"Type: {waveform.waveform_type}")
        print(f"Points: {waveform.sample_count}")
        print(f"Payload: {len(payload)} bytes")
        print(f"IEEE header: {block[: 2 + len(str(len(payload)))].decode('ascii')}")
        print(f"Channel: {args.channel}")
        print(
            "Persistent memory: disabled"
            if user_slot is None
            else f"Persistent memory: USER{user_slot}"
        )
        print(f"Amplitude: {amplitude_vpp:g} Vpp")
        print(f"Offset: {offset_voltage:g} V")
        print(f"Sample rate: {waveform.sample_rate_sa / 1_000_000:g} MSa/s")
        print(f"Frequency: {frequency_hz:g} Hz")

        if args.dry_run:
            print("Dry run complete; the instrument was not contacted")
            return 0

        result = upload_waveform(
            args.resource,
            args.visa_timeout_ms,
            waveform,
            payload,
            user_slot,
            args.channel,
            args.enable_output,
            amplitude_vpp,
            offset_voltage,
            frequency_hz,
        )
        print(result["identity"])
        if result["user_memory"]:
            print(
                f"Stored {result['points']} points in {result['user_memory']} and "
                f"selected {result['function']} on CH{result['channel']}"
            )
        else:
            print(
                f"Loaded {result['points']} volatile points into EMEMory and "
                f"selected {result['function']} on CH{result['channel']}"
            )
        print(f"SCPI status: {result['error']}")
        if result["output"] == "1":
            print(f"Channel {result['channel']} output: ON")
        else:
            print(
                f"Channel {result['channel']} output: OFF "
                "(add --enable-output to turn it on after import)"
            )
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
