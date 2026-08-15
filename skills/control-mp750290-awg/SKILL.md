---
name: control-mp750290-awg
description: Safely connect to, query, program, and diagnose the Multicomp Pro MP750290 arbitrary waveform generator (a rebadged OWON XDG3000) over its raw TCP SCPI socket. Use for AWG identity checks, channel control, edit-memory waveform loading, point-limit tests, SCPI error diagnosis, binary-block experiments, ArbDraw waveform integration, or MSO22 verification.
---

# Control the MP750290 AWG

Treat live commands as hardware side effects. Keep unconfirmed binary formats isolated
in diagnostic tools; never promote an experimental encoding without readback or scope
verification.

## Connect

- Host: `192.168.128.29`
- Raw TCP port: `3000`
- Terminator: LF (`\n`)
- Expected identity prefix: `Newark,MP750290`
- Existing client: `awg_idn.py`

Use `socket.create_connection`, a finite timeout, one ASCII command plus LF per write,
and LF-terminated query reads. Start with `*IDN?`. Do not reset the instrument unless
the user explicitly requests it.

## Apply live-operation safety

1. Query `*IDN?` before modifying state.
2. Send `OUTP1 OFF` before changing channel 1 waveform memory.
3. Check writes with `SYSTem:ERRor:NEXT?`. Clear stale errors before a test.
4. Send one command per TCP write. This firmware does not reliably parse several
   LF-delimited commands in one burst.
5. Insert query/response boundaries for pacing. A burst of 1,000 point commands made
   the server unresponsive; a burst of 50 produced `-102`.
6. Leave output off after diagnostics unless the user asks to enable it.
7. After a timeout, close the socket and retry `*IDN?` through a new connection. Stop
   if unavailable and ask for a power cycle. Send a desktop alert if the user requested
   restart notifications.

Never run `DATA:DATA? EMEMory` casually. On firmware `FV:V2.7.0`, it timed out and
left the socket server unavailable until power-cycled.

## Control output

Enable channel 1 only when requested, then verify it:

```text
OUTP1 ON
OUTP1?
SYSTem:ERRor:NEXT?
```

`OUTP1?` returns `1` for on and `0` for off.

## Load edit memory point-by-point

Use verified 1-based point indices:

```text
OUTP1 OFF
DATA:POINts EMEMory,<count>
DATA:DATA:VALue EMEMory,1,<voltage>V
...
DATA:DATA:VALue EMEMory,<count>,<voltage>V
SOUR1:FUNCtion EMEMory
```

Verify with `DATA:POINts? EMEMory`, selected `DATA:DATA:VALue?` queries,
`SOUR1:FUNCtion?`, and `SYSTem:ERRor:NEXT?`.

The accepted range is 2 through 100,000 points. Requesting 100,001 produces
`-108,"Parameter not allowed"`. Strict pacing is slow: 100 points took about 73
seconds.

Point data defines shape; these settings control actual output:

```text
SOUR1:FREQuency <frequency>Hz
SOUR1:VOLTage <amplitude>V
SOUR1:VOLTage:OFFSet <offset>V
OUTP1:IMPedance?
```

## Use persistent memory or mass storage

Copy edit memory into `USER0` and select it with:

```text
DATA:COPY USER0,EMEMory
SOUR1:FUNCtion USER0
```

Slots `USER0` through `USER31` exist. The unusual copy argument order is confirmed by
the manual.

Mass-storage selection is documented but untested:

```text
SOUR1:FUNCtion:EFILe "<case-sensitive/path>"
SOUR1:FUNCtion EFILe
```

Do not claim this works until verified on the instrument.

## Treat bulk transfer as experimental

The manual documents `DATA:DATA EMEMory,#<length-header><DAB payload>` but never
defines `<DAB>` width, byte order, or scaling.

- Legacy file encoding (unsigned 16-bit little-endian, `10000 = 0 V`, one code per mV)
  is not the SCPI encoding; a 16-point upload read back as zeros.
- Signed/unsigned 16-bit and one-byte probes have not produced valid values.
- Short and fixed-four-digit headers have encountered timeouts.
- The server often recovers after disconnect, but binary readback required a reboot.

Do not send large binary blocks. Prefer capturing an upload from OWON's PC software or
obtaining a vendor example. Keep experiments small, output-off, and followed by ASCII
point queries.

## Verify with MSO22

AWG channel 1 is connected to MSO22 channel 1. The Tektronix MCP endpoint is
`http://192.168.128.241:8787/mcp`; the scope resource is
`TCPIP::192.168.128.233::INSTR`.

Use screenshot and waveform-statistics operations serially, never concurrently. Compare
shape, amplitude, frequency, and offset with AWG queries. A 16-point sine should show 16
voltage steps per cycle.

## Use project resources

- `awg_idn.py`: primary client and safe small upload.
- `ArbDraw_JSON_Format.md` and `sample_json_waveform.json`: saved waveform format.
- `tools/point_limit_probe.py`: paced capacity test.
- `tools/bulk_transfer_probe.py`: experimental block probe; inspect before use.
- `tools/README.md`: observed test behavior and failures.
- `datasheets/XDG_Waveform_Generator_SCPI_Protocol.pdf`: ignored local manual.

Run tools from the repository root with the local virtual environment. Do not commit
oscilloscope screenshots unless explicitly requested.
