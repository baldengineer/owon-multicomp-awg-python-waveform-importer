# Copyright (c) 2026 James Lewis (james@baldengineer.com)
# SPDX-License-Identifier: MIT
"""Develop SCPI control for an OWON XDG3000-compatible waveform generator."""

from __future__ import annotations

import argparse
import math
import socket
import sys


DEFAULT_HOST = "192.168.128.29"
DEFAULT_PORT = 3000
DEFAULT_TIMEOUT = 5.0
TERMINATOR = b"\n"


class ScpiSocket:
    """Minimal newline-terminated SCPI socket client."""

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self._connection = socket.create_connection((host, port), timeout=timeout)
        self._connection.settimeout(timeout)

    def __enter__(self) -> ScpiSocket:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self._connection.close()

    def write(self, command: str) -> None:
        self._connection.sendall(command.encode("ascii") + TERMINATOR)

    def query(self, command: str) -> str:
        self.write(command)
        response = bytearray()
        while not response.endswith(TERMINATOR):
            chunk = self._connection.recv(4096)
            if not chunk:
                break
            response.extend(chunk)
            if len(response) > 64 * 1024:
                raise RuntimeError("Instrument response exceeded 64 KiB")

        if not response:
            raise RuntimeError("Instrument closed the connection without a response")

        return response.rstrip(b"\r\n").decode("ascii", errors="replace")


def generate_sine(sample_count: int, amplitude_v: float) -> list[float]:
    """Generate one cycle without duplicating the first point at the endpoint."""
    return [
        amplitude_v * math.sin(2.0 * math.pi * index / sample_count)
        for index in range(sample_count)
    ]


def require_no_scpi_error(instrument: ScpiSocket, stage: str) -> str:
    """Read one error-queue entry and raise if a command failed."""
    status = instrument.query("SYSTem:ERRor:NEXT?")
    if not status.lstrip().startswith("0"):
        raise RuntimeError(f"SCPI error after {stage}: {status}")
    return status


def load_edit_memory(
    instrument: ScpiSocket, samples: list[float], user_slot: int
) -> dict[str, str]:
    """Load samples into edit memory, persist them in user memory, and select edit memory.

    Channel 1 is deliberately left disabled. Point indices are currently assumed to
    be one-based, matching the queries in the project's earlier control script.
    """
    # Discard any stale error so subsequent checks apply to this upload attempt.
    while not instrument.query("SYSTem:ERRor:NEXT?").lstrip().startswith("0"):
        pass

    instrument.write("OUTP1 OFF")
    require_no_scpi_error(instrument, "disabling channel 1")

    instrument.write(f"DATA:POINts EMEMory,{len(samples)}")
    require_no_scpi_error(instrument, "setting the edit-memory point count")

    for point, voltage in enumerate(samples, start=1):
        instrument.write(f"DATA:DATA:VALue EMEMory,{point},{voltage:.12g}V")
        require_no_scpi_error(instrument, f"writing point {point}")

    user_memory = f"USER{user_slot}"

    # DATA:COPY uses destination-first order. Save the completed volatile waveform
    # into a persistent user slot; EMEMory already contains the same waveform.
    instrument.write(f"DATA:COPY {user_memory},EMEMory")
    require_no_scpi_error(instrument, f"storing edit memory in {user_memory}")

    instrument.write("SOUR1:FUNCtion EMEMory")
    status = require_no_scpi_error(instrument, "selecting edit memory")

    result = {
        "user_memory": user_memory,
        "points": instrument.query("DATA:POINts? EMEMory"),
        "first_value": instrument.query("DATA:DATA:VALue? EMEMory,1"),
        "last_value": instrument.query(
            f"DATA:DATA:VALue? EMEMory,{len(samples)}"
        ),
        "function": instrument.query("SOUR1:FUNCtion?"),
        "error": status,
    }

    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Connect to an XDG3000-compatible AWG and develop SCPI control."
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="AWG IP address")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="AWG TCP port")
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="socket timeout in seconds",
    )
    parser.add_argument(
        "--load-test-waveform",
        action="store_true",
        help=(
            "load a generated sine wave into edit memory and persist it in USER "
            "memory; channel 1 remains off"
        ),
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=16,
        help="number of points in the generated test waveform (default: 16)",
    )
    parser.add_argument(
        "--amplitude",
        type=float,
        default=1.0,
        help="test-waveform peak amplitude in volts (default: 1.0)",
    )
    parser.add_argument(
        "--user-slot",
        type=int,
        choices=range(32),
        default=0,
        metavar="0..31",
        help="persistent USER memory slot for waveform uploads (default: 0)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not 2 <= args.samples <= 100_000:
        print("--samples must be between 2 and 100000", file=sys.stderr)
        return 2
    if not math.isfinite(args.amplitude) or args.amplitude <= 0:
        print("--amplitude must be a positive finite number", file=sys.stderr)
        return 2

    try:
        with ScpiSocket(args.host, args.port, args.timeout) as instrument:
            identity = instrument.query("*IDN?")
            print(identity)

            if args.load_test_waveform:
                samples = generate_sine(args.samples, args.amplitude)
                result = load_edit_memory(instrument, samples, args.user_slot)
                print(
                    f"Stored {result['points']} sine-wave points in "
                    f"{result['user_memory']} while retaining them in EMEMory at "
                    f"+/-{args.amplitude:g} V"
                )
                print(f"First point: {result['first_value']}")
                print(f"Last point:  {result['last_value']}")
                print(f"CH1 function: {result['function']}")
                print(f"SCPI status: {result['error']}")
                print("Channel 1 output remains OFF")
    except (OSError, RuntimeError) as exc:
        print(f"AWG communication failed: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
