# OWON XDG3000 / MP750290 Waveform Importer

Released under the [MIT License](LICENSE). Copyright © 2026 James Lewis
(james@baldengineer.com).

Command-line tools for working with the Multicomp Pro MP750290 arbitrary waveform
generator, a rebadged OWON XDG3000-series instrument.

The project is intended to support two operating modes:

1. Generate binary arbitrary-waveform files for manual transfer to the instrument.
2. Connect directly to the instrument over USBTMC or the network and control it with
   SCPI.

The importer currently accepts ArbDraw JSON as its input format. The command and
instrument-control layers are kept separate so additional formats such as CSV and WFM
can be added later without changing the OWON XDG3000/MP750290 control path.

The direct-control tools support identity queries, a point-by-point development upload,
and fast USBTMC import of ArbDraw JSON waveforms. Imported waveforms are stored in a
selectable persistent `USER` slot, retained in edit memory, and selected as the channel 1
function by default while the selected channel output remains off.

## Hardware and connection

- Instrument: Multicomp Pro MP750290
- Compatible platform: OWON XDG3000 series
- USBTMC VISA resource: `USB0::0x5345::0x1235::2025332::INSTR`
- LAN control uses the instrument's configured IP address on TCP port `3000`.
- SCPI command terminator: newline (`\n`)

The current test instrument identifies itself as:

```text
Newark,MP750290,2025332,SCPI:99.0 FV:V2.7.0
```

Channel 1 of the waveform generator is connected to channel 1 of a Tektronix MSO22
for development and verification.

## Setup

Create and activate a virtual environment, then install the project dependency:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install pyvisa
```

The initial socket test uses only the Python standard library. PyVISA is installed for
later instrument-control work.

List all detected VISA resources, one copy/paste-ready resource string per line:

```powershell
python .\awg_import.py --list-resources
```

Use any returned string with the importer's `--resource` option.

Query the identity of any listed VISA resource by pasting its resource string. The
example below uses the USBTMC resource format; use the resource returned by your own
instrument:

```powershell
python .\awg_import.py --idn "USB0::0x5345::0x1235::2025332::INSTR"
```

The command prints the instrument's `*IDN?` response. Use `--visa-timeout-ms` to override
the default 60-second VISA timeout.

The importer requires `defaults.toml` in the working directory. Copy it or provide an
alternate configuration with `--defaults-file`:

```powershell
python .\awg_import.py --defaults-file .\my-awg.toml .\waveform.json
```

The TOML file is the sole source of application defaults. Command-line options override
its values, but a missing file or missing required setting causes the importer to exit.

Both discovery actions can be combined. The resource list is printed first, followed
by the selected instrument's identity:

```powershell
python .\awg_import.py --list-resources `
    --idn "USB0::0x5345::0x1235::2025332::INSTR"
```

## Query the instrument identity

Run the script with its configured connection settings:

```powershell
python .\tools\awg_idn.py
```

Override the host, port, or timeout when needed:

```powershell
python .\tools\awg_idn.py --host <instrument-ip-address> --port 3000 --timeout 5
```

Show all command-line options:

```powershell
python .\tools\awg_idn.py --help
```

The command exits with status `0` after receiving an identification response and
status `1` if the connection or query fails.

## Load the test waveform

Generate a 16-point, 1 V peak sine wave and load it into `EMEMory`:

```powershell
python .\tools\awg_idn.py --load-test-waveform
```

The upload uses the documented `DATA:POINts` and `DATA:DATA:VALue` commands, stores
the completed edit-memory waveform in `USER0`, selects the existing `EMEMory` copy for
channel 1, and checks the SCPI error queue. No copy back is needed because the waveform
must already be in `EMEMory` before it can be stored. The persistent user-memory copy
survives when `EMEMory` is cleared during a power cycle. Channel 1 is disabled before
the upload and is deliberately left off.

The point count and peak amplitude can be changed for development:

```powershell
python .\tools\awg_idn.py --load-test-waveform --samples 32 --amplitude 0.5
```

Choose a persistent waveform slot from `USER0` through `USER31` with `--user-slot`:

```powershell
python .\tools\awg_idn.py --load-test-waveform --user-slot 4
```

The default is `--user-slot 0`. Values outside `0` through `31` are rejected before
the instrument connection is opened.

## Import a waveform

Validate and preview how an ArbDraw JSON file will be encoded without contacting the
instrument:

```powershell
python .\awg_import.py .\examples\sample_waveform_01_funky_sine.json --dry-run
```

Upload the waveform over USBTMC, persist it in `USER1`, and select the existing
`EMEMory` waveform on the selected channel (channel 1 by default):

```powershell
python .\awg_import.py .\examples\sample_waveform_01_funky_sine.json
```

Channel 1 remains off by default. Enable it only after a completely successful import:

```powershell
python .\awg_import.py .\examples\sample_waveform_01_funky_sine.json --enable-output
```

The importer does not enable the output until waveform upload, persistent storage,
waveform selection, and channel configuration have all succeeded. Any failure still
forces the selected channel off and unlocks the front panel.

Configure channel 2 instead of the default channel 1 with `--channel`:

```powershell
python .\awg_import.py .\examples\sample_waveform_01_funky_sine.json --channel 2
```

Only channels `1` and `2` are accepted. Output safety, waveform selection, channel
settings, final output state, and cleanup all apply to the selected channel. The default
persistent destination is `USER1` for channel 1 and `USER2` for channel 2.

Override the JSON-derived channel settings when needed:

```powershell
python .\awg_import.py .\examples\sample_waveform_01_funky_sine.json `
    --frequency 1000 --amplitude 2.5 --offset 0.25
```

Frequency is specified in hertz, amplitude in Vpp, and offset in volts. The explicit
aliases `--frequency-hz`, `--amplitude-vpp`, and `--offset-v` are also accepted. The
configured defaults come from `defaults.toml`; command-line values take precedence.

Choose another persistent slot with `--user-slot 0..31`; an explicit slot overrides the
channel-based default. The importer validates the schema, version, point count, finite
sample values, declared voltage range, and the 100,000-point hardware limit before
opening the instrument.

Skip persistent user memory and leave the waveform only in volatile `EMEMory` with:

```powershell
python .\awg_import.py .\examples\sample_waveform_01_funky_sine.json --no-persist
```

`--no-persist` and `--user-slot` are mutually exclusive. A no-persist waveform is lost
when edit memory is cleared, including when the AWG is power-cycled.

JSON voltage values are normalized into the AWG's unsigned 14-bit bulk format using
`lowVoltage` as code `0` and `highVoltage` as code `16383`. The importer configures
the selected channel's amplitude and offset from those levels. It reports
`sampleRateMSa` as the sample rate and sets the AWG frequency from the JSON
`frequencyHz` value, unless overridden on the command line or in `defaults.toml`. The
output is kept off throughout
the import. The importer locks the front panel while uploading, storing, selecting, and
configuring the waveform, then unlocks it when finished. Its cleanup path also unlocks
the panel if an import command fails.

## Bulk waveform data (`<DAB>`)

The programmer's manual calls the binary portion of a bulk waveform upload `<DAB>`.
In practical terms, it is the complete list of waveform heights packed into bytes. It
does not contain output voltages: each point is a normalized shape value that the AWG
later scales using the channel's amplitude and offset settings.

The MP750290 expects each point to be an unsigned 14-bit number from `0` through
`16383`, stored in a two-byte big-endian integer. Code `0` represents the bottom of the
waveform, `8192` is approximately the center, and `16383` represents the top. To convert
a bipolar shape value from `-1.0` through `+1.0`:

```python
code = round(((value + 1.0) / 2.0) * 16383)
sample_bytes = struct.pack(">H", code)
```

Concatenate the two-byte samples, then prefix them with an IEEE 488.2 definite-length
block header. The header starts with `#`, gives the number of decimal digits used for
the byte count, and then gives the payload byte count itself. For example, 1,000 points
occupy 2,000 bytes, so their header is `#42000`:

```text
DATA:POINts EMEMory,1000
DATA:DATA EMEMory,#42000<2000 bytes of waveform data>
```

This format was verified over USBTMC with a 1,000-point sine wave. The AWG's front-panel
preview showed the expected waveform. On the tested firmware, individual ASCII point
queries returned misleading zeros after a bulk upload, so use the SCPI error queue and
point count together with the front-panel preview or an oscilloscope for verification.

### USBTMC versus LAN

Use USBTMC for bulk binary waveform uploads. The verified format successfully transferred
1,000-, 10,000-, and 100,000-point waveforms over USBTMC; 100,000 points is the confirmed
edit-memory limit on firmware `FV:V2.7.0`.

The raw TCP connection at port `3000` works for ASCII SCPI, including identity queries,
output control, memory allocation, and carefully paced point-by-point writes. It does not
accept the same binary block reliably. A 1,000-point block that worked over USBTMC returned
`-101,"Invalid character"` over LAN, although the AWG remained responsive and channel 1
stayed off. Binary data can contain newline and other control bytes, so the likely cause is
a conflict with the socket's LF-delimited command parser; this has not been proven.

## TODO

- Add support for selecting an arbitrary waveform file from the instrument's mass
  storage using the SCPI `SOURce:FUNCtion:EFILe` commands.
- Add support for configuring waveform rise and fall times.
- Add support for configuration through environment variables.
- Support other file formats (CSV, BIN, WFM, etc.)

## Related links

- [Multicomp Pro MP750290 product page](https://www.newark.com/multicomp-pro/mp750290-us/arbitrary-waveform-generator-2ch/dp/74AH3017)
- [OWON XDG3000 product page](https://www.owon.com.hk/products_owon_xdg3000_series_2-ch_250mhz_arbitrary_waveform_generator)
