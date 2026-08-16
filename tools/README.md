# Development tools

These scripts exercise the physical waveform generator and are intended for manual
development and diagnostics. Run them from the repository root with the project's
virtual environment active.

## `point_limit_probe.py`

Probes the SCPI edit-memory limit and point-write behavior of the Multicomp Pro
MP750290/OWON XDG3000-series AWG.

The tool:

- connects to the AWG using the client in `tools/awg_idn.py`;
- disables channel 1 and leaves it disabled;
- allocates the documented 100,000-point edit memory;
- writes and verifies 100 generated sine-wave points with strict command/response
  pacing;
- confirms that requesting 100,001 points produces a SCPI error; and
- verifies that the instrument remains responsive after the test.

Run it with:

```powershell
python -m tools.point_limit_probe
```

The test modifies the waveform in `EMEMory`. It does not enable the output or copy the
waveform to persistent user memory. On the tested instrument, writing 100 individual
points takes approximately 73 seconds. Increasing `POINTS_TO_WRITE` substantially is
not recommended until bulk binary transfer is implemented.

Earlier experiments showed that sending many point commands in one TCP burst can
produce a syntax error or make the SCPI connection temporarily unresponsive. Keep
strict pacing enabled when adapting this tool.

## `bulk_transfer_probe.py`

Tests the binary sample encoding used by `DATA:DATA EMEMory` with a small waveform.

The tool assumes the unsigned 16-bit little-endian format used by the legacy
waveform-file generator, where code 10000 represents 0 V and each code represents
1 mV. It uploads a 16-point sine wave as a definite-length IEEE block, verifies selected
points through ordinary ASCII queries, selects `EMEMory`, and confirms that the
instrument remains responsive. Channel 1 is disabled and left off.

Run it with:

```powershell
python -m tools.bulk_transfer_probe
```

Do not enable the unused `DATA:DATA? EMEMory` readback experiment without expecting
to power-cycle the instrument. On the tested firmware, that binary query timed out and
left the SCPI socket server unresponsive even with only five edit-memory points.

### Current bulk-transfer findings

- A 16-point, 32-byte upload using the legacy unsigned 16-bit little-endian file
  encoding returned no SCPI error, but all points read back as `0 V`. The file encoding
  is therefore not the SCPI `<DAB>` encoding.
- Five-byte payloads timed out with both a normal short IEEE header and the manual
  example's fixed four-digit `#4NNNN` header. The socket server recovered after the
  client disconnected.
- Two-byte signed and unsigned candidates did not produce the expected voltages;
  some candidates caused a temporary command timeout.
- The programmer's manual does not define the size, byte order, or scaling of `<DAB>`.
  Obtain clarification or a working vendor example before testing larger binary
  payloads.
