---
name: control-mp750290-awg
description: Safely connect to, query, program, and diagnose the Multicomp Pro MP750290 arbitrary waveform generator (a rebadged OWON XDG3000) over USBTMC or its raw TCP SCPI socket. Use for AWG identity checks, channel control, fast 14-bit bulk waveform uploads, edit/user-memory copying, point-limit tests, SCPI error diagnosis, ArbDraw waveform integration, or MSO22 verification.
---

# Control the MP750290 AWG

Treat live commands as hardware side effects. Keep unconfirmed binary formats isolated
in diagnostic tools; never promote an experimental encoding without readback or scope
verification.

## Connect

- Preferred USBTMC VISA resource: `USB0::0x5345::0x1235::2025332::INSTR`
- Host: `192.168.128.29`
- Raw TCP port: `3000`
- Terminator: LF (`\n`)
- Expected identity prefix: `Newark,MP750290`
- Existing client: `awg_idn.py`

Prefer USBTMC for bulk transfers. Open it with PyVISA, set finite timeouts plus LF read
and write termination, and query `*IDN?` before changing state. The tested VISA backend
is the system library at `C:\Windows\system32\visa32.dll`.

Use `socket.create_connection`, a finite timeout, one ASCII command plus LF per write,
and LF-terminated query reads. Start with `*IDN?`. Do not reset the instrument unless
the user explicitly requests it.

Use LAN for ASCII SCPI only. On firmware `FV:V2.7.0`, the same verified 1,000-point
binary block that works over USBTMC returned `-101,"Invalid character"` over the raw
TCP socket. The allocation succeeded and the instrument stayed responsive, but the
waveform did not upload. Binary payload bytes may conflict with the socket's LF-delimited
parser; treat that explanation as likely, not proven. Do not retry LAN bulk transfer
unless explicitly investigating the transport failure.

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

Never run `DATA:DATA? EMEMory` casually. On firmware `FV:V2.7.0`, it timed out over
the raw socket and left the socket server unavailable until power-cycled.

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

`DATA:COPY` uses the unusual **destination-first** order. Copy edit memory into
`USER0` and select it with:

```text
DATA:COPY USER0,EMEMory
SOUR1:FUNCtion USER0
```

Load `USER0` into edit memory with:

```text
DATA:COPY EMEMory,USER0
```

Slots `USER0` through `USER31` exist. `DATA:COPY` is the store/load operation; no
additional save or commit command is required. The destination-first order is confirmed
by the manual and live sine/triangle copies between `USER0`, `EMEMory`, and `USER4`.

Mass-storage selection is documented but untested:

```text
SOUR1:FUNCtion:EFILe "<case-sensitive/path>"
SOUR1:FUNCtion EFILe
```

Do not claim this works until verified on the instrument.

## Upload waveforms in bulk over USBTMC

Treat USBTMC as required for this workflow. Do not send the block through the raw LAN
socket merely because ASCII SCPI works there.

Use the verified `<DAB>` representation:

- one unsigned 14-bit code per waveform point;
- store each code in a two-byte unsigned integer;
- transmit the two bytes in big-endian order;
- map normalized values from `0.0` through `1.0` onto codes `0` through `16383`; and
- wrap the payload in an IEEE 488.2 definite-length block.

For a bipolar shape value in `[-1.0, 1.0]`, use:

```python
code = round(((value + 1.0) / 2.0) * 16383)
sample_bytes = struct.pack(">H", code)
```

Clamp source values and codes to their valid ranges. For `N` points, concatenate the
two-byte samples into a payload of `2 * N` bytes and construct the header as:

```python
payload_length = len(payload)
header = f"#{len(str(payload_length))}{payload_length}".encode("ascii")
message = b"DATA:DATA EMEMory," + header + payload + b"\n"
```

For 1,000 points, the payload length is 2,000 bytes and the header is `#42000`:

```text
OUTP1 OFF
DATA:POINts EMEMory,1000
DATA:DATA EMEMory,#42000<2000-byte payload><LF>
SYSTem:ERRor:NEXT?
DATA:POINts? EMEMory
```

Send the binary message with PyVISA `write_raw`. A 1,000-point full-scale sine uploaded
successfully over USBTMC and appeared correctly in the front-panel `EMEMory` preview.
Keep it volatile unless the user asks to store it; use `DATA:COPY USER<n>,EMEMory` to
store it persistently.

Do not use `DATA:DATA:VALue?` to validate a bulk-loaded waveform. On this firmware,
ASCII point queries returned zero even while the front-panel preview showed the actual
binary-loaded waveform. Validate the point count and error queue, then use the front-panel
preview or an oscilloscope for shape verification.

Do not use these disproven encodings: IEEE float16, IEEE float32, signed 16-bit integers,
little-endian unsigned integers, or the legacy waveform-file encoding (`10000 = 0`, one
count per millivolt). Little-endian float16 data produced a distinctive byte-swapped
preview rather than a sine.

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
