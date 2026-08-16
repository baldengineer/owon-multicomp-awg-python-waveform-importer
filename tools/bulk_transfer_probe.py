# Copyright (c) 2026 James Lewis (james@baldengineer.com)
# SPDX-License-Identifier: MIT
"""Test the AWG's undocumented bulk waveform encoding."""

from __future__ import annotations

import math
import struct
import sys
import time

from awg_idn import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    ScpiSocket,
    require_no_scpi_error,
)


TIMEOUT_SECONDS = 15.0
KNOWN_VOLTAGES = [-1.0, -0.5, 0.0, 0.5, 1.0]
TEST_POINT_COUNT = 16
BYTE_PROBE_CODES = bytes((32, 64, 96, 128, 224))


def clear_errors(instrument: ScpiSocket) -> None:
    for _ in range(65):
        if instrument.query("SYSTem:ERRor:NEXT?").lstrip().startswith("0"):
            return
    raise RuntimeError("SCPI error queue did not clear")


def read_exact(instrument: ScpiSocket, byte_count: int) -> bytes:
    data = bytearray()
    while len(data) < byte_count:
        chunk = instrument._connection.recv(byte_count - len(data))
        if not chunk:
            raise RuntimeError("Instrument closed the socket during binary readback")
        data.extend(chunk)
    return bytes(data)


def query_ieee_block(instrument: ScpiSocket, command: str) -> bytes:
    instrument.write(command)
    if read_exact(instrument, 1) != b"#":
        raise RuntimeError("Binary response did not start with an IEEE block header")

    digit_byte = read_exact(instrument, 1)
    if not digit_byte.isdigit() or digit_byte == b"0":
        raise RuntimeError(f"Unsupported IEEE block length digit: {digit_byte!r}")

    length_digits = int(digit_byte)
    payload_length_text = read_exact(instrument, length_digits)
    if not payload_length_text.isdigit():
        raise RuntimeError("IEEE block byte count was not numeric")

    payload = read_exact(instrument, int(payload_length_text))
    terminator = read_exact(instrument, 1)
    if terminator not in (b"\n", b"\r"):
        raise RuntimeError(f"Unexpected byte after IEEE block: {terminator!r}")
    if terminator == b"\r":
        if read_exact(instrument, 1) != b"\n":
            raise RuntimeError("Malformed CRLF after IEEE block")
    return payload


def voltage_to_code(voltage: float) -> int:
    """Encode volts using the format suggested by the legacy file generator."""
    millivolts = round(voltage * 1000)
    code = millivolts + 10_000
    if not 0 <= code <= 20_000:
        raise ValueError(f"Voltage is outside the legacy +/-10 V range: {voltage}")
    return code


def encode_samples(samples: list[float]) -> bytes:
    return struct.pack(f"<{len(samples)}H", *(voltage_to_code(v) for v in samples))


def candidate_encodings(samples: list[float]) -> list[tuple[str, bytes]]:
    millivolts = [round(value * 1000) for value in samples]
    legacy_codes = [value + 10_000 for value in millivolts]
    return [
        ("legacy uint16 little-endian", struct.pack(f"<{len(samples)}H", *legacy_codes)),
        ("legacy uint16 big-endian", struct.pack(f">{len(samples)}H", *legacy_codes)),
        ("millivolt int16 little-endian", struct.pack(f"<{len(samples)}h", *millivolts)),
        ("millivolt int16 big-endian", struct.pack(f">{len(samples)}h", *millivolts)),
        ("float32 little-endian", struct.pack(f"<{len(samples)}f", *samples)),
        ("float32 big-endian", struct.pack(f">{len(samples)}f", *samples)),
        ("float64 little-endian", struct.pack(f"<{len(samples)}d", *samples)),
        ("float64 big-endian", struct.pack(f">{len(samples)}d", *samples)),
    ]


def write_ieee_block(instrument: ScpiSocket, command: str, payload: bytes) -> None:
    if len(payload) > 9_999:
        raise ValueError("Probe currently supports at most 9,999 payload bytes")
    # The manual describes general IEEE blocks but its only upload example uses
    # a four-digit count. Use that exact form for compatibility with this firmware.
    header = f"#4{len(payload):04d}".encode("ascii")
    instrument._connection.sendall(
        command.encode("ascii") + b"," + header + payload + b"\n"
    )
    time.sleep(1.0)


def discover_upload_encoding(instrument: ScpiSocket) -> str:
    for name, payload in candidate_encodings(KNOWN_VOLTAGES):
        instrument.write(f"DATA:POINts EMEMory,{len(KNOWN_VOLTAGES)}")
        require_no_scpi_error(instrument, f"allocating points for {name}")
        write_ieee_block(instrument, "DATA:DATA EMEMory", payload)
        require_no_scpi_error(instrument, f"uploading {name}")

        actual = [
            float(instrument.query(f"DATA:DATA:VALue? EMEMory,{point}"))
            for point in range(1, len(KNOWN_VOLTAGES) + 1)
        ]
        print(f"{name:32} -> {actual}")
        if all(
            math.isclose(observed, expected, abs_tol=0.001)
            for observed, expected in zip(actual, KNOWN_VOLTAGES)
        ):
            print(f"Confirmed SCPI bulk encoding: {name}")
            return name

    raise RuntimeError("None of the tested numeric encodings matched")


def probe_byte_encoding(instrument: ScpiSocket) -> list[float]:
    instrument.write(f"DATA:POINts EMEMory,{len(BYTE_PROBE_CODES)}")
    require_no_scpi_error(instrument, "allocating byte-probe points")
    write_ieee_block(instrument, "DATA:DATA EMEMory", BYTE_PROBE_CODES)
    require_no_scpi_error(instrument, "uploading one-byte sample codes")

    actual = [
        float(instrument.query(f"DATA:DATA:VALue? EMEMory,{point}"))
        for point in range(1, len(BYTE_PROBE_CODES) + 1)
    ]
    print(f"One-byte codes:       {list(BYTE_PROBE_CODES)}")
    print(f"Voltage readback (V): {actual}")
    if all(value == 0.0 for value in actual):
        raise RuntimeError("One-byte payload also produced an all-zero waveform")
    return actual


def establish_encoding(instrument: ScpiSocket) -> None:
    instrument.write(f"DATA:POINts EMEMory,{len(KNOWN_VOLTAGES)}")
    require_no_scpi_error(instrument, "allocating encoding-probe points")

    for point, voltage in enumerate(KNOWN_VOLTAGES, start=1):
        instrument.write(f"DATA:DATA:VALue EMEMory,{point},{voltage}V")
        require_no_scpi_error(instrument, f"writing encoding-probe point {point}")

    payload = query_ieee_block(instrument, "DATA:DATA? EMEMory")
    expected = encode_samples(KNOWN_VOLTAGES)
    print(f"Readback payload ({len(payload)} bytes): {payload.hex(' ')}")
    print(f"Expected payload ({len(expected)} bytes): {expected.hex(' ')}")

    if payload != expected:
        if len(payload) % 2 == 0:
            little_endian = struct.unpack(f"<{len(payload) // 2}H", payload)
            big_endian = struct.unpack(f">{len(payload) // 2}H", payload)
            print(f"Unsigned 16-bit little-endian view: {little_endian}")
            print(f"Unsigned 16-bit big-endian view:    {big_endian}")
        raise RuntimeError("Readback did not confirm the legacy sample encoding")

    print("Confirmed: unsigned 16-bit little-endian, 10000 = 0 V, 1 code = 1 mV")


def test_bulk_upload(instrument: ScpiSocket) -> None:
    samples = [
        math.sin(2.0 * math.pi * index / TEST_POINT_COUNT)
        for index in range(TEST_POINT_COUNT)
    ]
    payload = encode_samples(samples)

    instrument.write(f"DATA:POINts EMEMory,{len(samples)}")
    require_no_scpi_error(instrument, "allocating bulk-upload points")
    write_ieee_block(instrument, "DATA:DATA EMEMory", payload)
    require_no_scpi_error(instrument, "bulk waveform upload")

    print(f"Bulk uploaded {len(samples)} points in {len(payload)} bytes")
    for point in (1, 5, 9, 13, 16):
        actual = instrument.query(f"DATA:DATA:VALue? EMEMory,{point}")
        print(f"Point {point:2}: expected {samples[point - 1]: .6f} V, read {actual}")

    instrument.write("SOUR1:FUNCtion EMEMory")
    require_no_scpi_error(instrument, "selecting edit memory")
    print(f"CH1 function: {instrument.query('SOUR1:FUNCtion?')}")
    print(f"CH1 output: {instrument.query('OUTP1?')} (expected 0/off)")
    print(f"Connection check: {instrument.query('*IDN?')}")


def main() -> int:
    try:
        with ScpiSocket(
            DEFAULT_HOST, DEFAULT_PORT, TIMEOUT_SECONDS
        ) as instrument:
            print(instrument.query("*IDN?"))
            clear_errors(instrument)
            instrument.write("OUTP1 OFF")
            require_no_scpi_error(instrument, "disabling channel 1")
            probe_byte_encoding(instrument)
            print("Byte mapping observed; sine upload awaits encoder integration")
    except (OSError, RuntimeError, ValueError, struct.error) as exc:
        print(f"Bulk-transfer probe failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
