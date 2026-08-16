# Copyright (c) 2026 James Lewis (james@baldengineer.com)
# SPDX-License-Identifier: MIT
"""Stress-test the AWG edit-memory point limit without enabling its output."""

from __future__ import annotations

import math
import socket
import sys
import time

from awg_idn import DEFAULT_HOST, DEFAULT_PORT, ScpiSocket, require_no_scpi_error


POINTS = 100_000
POINTS_TO_WRITE = 100
BATCH_SIZE = 1
COMMAND_DELAY_SECONDS = 0.002
TIMEOUT_SECONDS = 15.0


def clear_errors(instrument: ScpiSocket) -> None:
    for _ in range(65):
        if instrument.query("SYSTem:ERRor:NEXT?").lstrip().startswith("0"):
            return
    raise RuntimeError("SCPI error queue did not clear")


def main() -> int:
    try:
        with ScpiSocket(
            DEFAULT_HOST, DEFAULT_PORT, TIMEOUT_SECONDS
        ) as instrument:
            instrument._connection.setsockopt(
                socket.IPPROTO_TCP, socket.TCP_NODELAY, 1
            )
            print(instrument.query("*IDN?"), flush=True)
            clear_errors(instrument)

            instrument.write("OUTP1 OFF")
            require_no_scpi_error(instrument, "disabling channel 1")

            instrument.write(f"DATA:POINts EMEMory,{POINTS}")
            require_no_scpi_error(instrument, f"allocating {POINTS} points")
            print(
                f"Allocated {instrument.query('DATA:POINts? EMEMory')} points",
                flush=True,
            )

            started_at = time.monotonic()
            for batch_start in range(1, POINTS_TO_WRITE + 1, BATCH_SIZE):
                batch_stop = min(
                    batch_start + BATCH_SIZE - 1, POINTS_TO_WRITE
                )
                for point in range(batch_start, batch_stop + 1):
                    voltage = math.sin(2.0 * math.pi * (point - 1) / POINTS)
                    instrument.write(
                        f"DATA:DATA:VALue EMEMory,{point},{voltage:.9g}V"
                    )
                    time.sleep(COMMAND_DELAY_SECONDS)
                require_no_scpi_error(
                    instrument, f"writing points {batch_start}-{batch_stop}"
                )
                if batch_stop % 10 == 0:
                    print(f"Loaded {batch_stop} points", flush=True)

            elapsed = time.monotonic() - started_at
            last_value = instrument.query(
                f"DATA:DATA:VALue? EMEMory,{POINTS_TO_WRITE}"
            )
            print(
                f"Point {POINTS_TO_WRITE} reads back as {last_value}",
                flush=True,
            )
            print(
                f"Loaded {POINTS_TO_WRITE} points in {elapsed:.1f} seconds",
                flush=True,
            )
            print(f"Connection check: {instrument.query('*IDN?')}", flush=True)

            instrument.write(f"DATA:POINts EMEMory,{POINTS + 1}")
            over_limit_status = instrument.query("SYSTem:ERRor:NEXT?")
            print(
                f"Request for {POINTS + 1} points: {over_limit_status}",
                flush=True,
            )
            print(f"Final point count: {instrument.query('DATA:POINts? EMEMory')}")
            print(f"Channel 1 output: {instrument.query('OUTP1?')}")
    except (OSError, RuntimeError) as exc:
        print(f"Point-limit probe failed: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
