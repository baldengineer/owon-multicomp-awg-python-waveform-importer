"""Query the identity of an OWON XDG3000-compatible waveform generator."""

from __future__ import annotations

import argparse
import socket
import sys


DEFAULT_HOST = "192.168.128.29"
DEFAULT_PORT = 3000
DEFAULT_TIMEOUT = 5.0
TERMINATOR = b"\n"


def query_idn(host: str, port: int, timeout: float) -> str:
    """Connect to the generator and return its response to ``*IDN?``."""
    with socket.create_connection((host, port), timeout=timeout) as connection:
        connection.settimeout(timeout)
        connection.sendall(b"*IDN?" + TERMINATOR)

        response = bytearray()
        while not response.endswith(TERMINATOR):
            chunk = connection.recv(4096)
            if not chunk:
                break
            response.extend(chunk)
            if len(response) > 64 * 1024:
                raise RuntimeError("Instrument response exceeded 64 KiB")

    if not response:
        raise RuntimeError("Instrument closed the connection without a response")

    return response.rstrip(b"\r\n").decode("ascii", errors="replace")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Connect to an XDG3000-compatible AWG and issue *IDN?."
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="AWG IP address")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="AWG TCP port")
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="socket timeout in seconds",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        identity = query_idn(args.host, args.port, args.timeout)
    except (OSError, RuntimeError) as exc:
        print(f"AWG communication failed: {exc}", file=sys.stderr)
        return 1

    print(identity)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
