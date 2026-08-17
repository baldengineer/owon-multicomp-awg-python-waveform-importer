# OWON XDG3000 / MP750290 Waveform Importer
Command-line tools for working with the Multicomp Pro MP750290 arbitrary waveform
generator, a rebadged OWON XDG3000-series instrument.

The python project connects to the instrument via pyVISA using USBTMC or the network and control it with SCPI.

The importer accepts ArbDraw JSON and headerless two-column `x,y` CSV files, where `x`
is time in seconds and `y` is voltage in volts. 

The direct-control tools support identity queries, a point-by-point development upload,
and fast USBTMC import of ArbDraw JSON and CSV waveforms. Imported waveforms are
Persistence is controlled by `defaults.toml` (`persist = true` currently); use
`--persist` or `--no-persist` to override it for an individual import. Persistent
waveforms are copied into a selectable `USER` slot, while non-persistent imports stay
in volatile edit memory. The selected channel output remains off by default.

## Hardware and connection

- Instrument: Multicomp Pro MP750290 or OWON XDG3000 series
- MP75's USBTMC VISA resource: `USB0::0x5345::0x1235::2025332::INSTR`
- LAN control uses the instrument's configured IP address on TCP port `3000`.
- SCPI command terminator: newline (`\n`)

The current test instrument identifies itself as:
```text
Newark,MP750290,2025332,SCPI:99.0 FV:V2.7.0

```
### USBTMC versus LAN

```Use USBTMC for bulk binary waveform uploads. The verified format successfully transferred```

USBTMC supports up to 100,000 waveform points.

Uploads over LAN will fail!

The raw TCP connection at port `3000` works for ASCII SCPI, including identity queries,
output control, memory allocation, and carefully paced point-by-point writes. It does not
accept the same binary block reliably. A 1,000-point block that worked over USBTMC returned
`-101,"Invalid character"` over LAN, although the AWG remained responsive and channel 1
stayed off. Binary data can contain newline and other control bytes, so the likely cause is
a conflict with the socket's LF-delimited command parser; this has not been proven.

## Setup

Install Python 3.11 or newer, then open a terminal in the repository root. Create the
project virtual environment with:

```powershell
python -m venv .venv
```

Activate it in Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks the activation script, allow locally created scripts for your user
account and activate the environment again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

For Windows Command Prompt, use:

```bat
.venv\Scripts\activate.bat
```

For macOS or Linux, use:

```bash
source .venv/bin/activate
```

When activation succeeds, the terminal prompt normally starts with `(.venv)`. Install
the project dependencies after activation:

```powershell
python -m pip install -r requirements.txt
```

To leave the virtual environment when finished, run:

```text
deactivate
```

The initial socket test uses only the Python standard library. The requirements file
installs PyVISA for instrument-control work over USBTMC. PyVISA also requires a VISA
backend on the host system; install and configure the vendor's VISA implementation
before using USBTMC resource discovery or waveform uploads.

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

## TODO

- Add support for saving user-specific settings in a local TOML file under the user's
  home directory, with those settings layered over the project `defaults.toml` without
  modifying the repository defaults.

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

CSV files normally use exactly two columns (`x,y`) with no header. The `x` values are timestamps
in seconds and the `y` values are voltages in volts; timestamps must be strictly
increasing and uniformly spaced. Single-column CSV files are also accepted; each row is
treated as a voltage sample and its `x` position is generated from the sample index.
Use `--csv-column INDEX` to select a voltage column from a wider CSV, and
`--csv-delimiter CHAR` for a delimiter other than comma. CSV files may contain up to
100,000 points. Validate or upload one exactly like an ArbDraw JSON file:

```powershell
python .\awg_import.py .\examples\hello_world_56700.csv --dry-run
```

For CSV input, the importer derives sample rate from timestamp spacing, voltage range
from the samples, and repetition frequency from the full record length. Settings in
`defaults.toml` and command-line overrides continue to take precedence for channel
frequency, amplitude, and offset.

Upload the waveform to volatile `EMEMory` and select it on the selected channel
(channel 1 by default):

```powershell
python .\awg_import.py .\examples\sample_waveform_01_funky_sine.json
```

Channel 1 remains off by default. To enable it, only after a completely successful import:

```powershell
python .\awg_import.py .\examples\sample_waveform_01_funky_sine.json --enable-output
```

The importer only turns channel output on if waveform upload, waveform selection, and
channel configuration have all succeeded. When `--persist` is used, persistent storage
must also succeed before output is enabled.

Configure channel 2 instead of the default channel 1 with `--channel`:

```powershell
python .\awg_import.py .\examples\sample_waveform_01_funky_sine.json --channel 2
```

Only channels `1` and `2` are accepted.

Use `--persist` to enable persistent storage (or set `persist = true` in
`defaults.toml`). Its default destination is `USER1` for channel 1 and `USER2` for
channel 2.

Override the JSON-derived channel settings when needed:

```powershell
python .\awg_import.py .\examples\sample_waveform_01_funky_sine.json `
    --frequency 1000 --amplitude 2.5 --offset 0.25
```

Frequency is specified in hertz, amplitude in Vpp, and offset in volts. (Explicit
aliases `--frequency-hz`, `--amplitude-vpp`, and `--offset-v` are also accepted.) The
configured defaults come from `defaults.toml`; command-line values take precedence.

Choose another persistent slot with `--persist --user-slot 0..31`; an explicit slot
overrides the channel-based default. The importer validates the schema, version, point
count, finite sample values, declared voltage range, and the 100,000-point hardware
limit before opening the instrument.

`--user-slot` requires persistence to be enabled. Use `--no-persist` to leave a
waveform only in volatile `EMEMory`; it is lost when edit memory is cleared, including
when the AWG is power-cycled.

JSON voltage values are normalized into the AWG's unsigned 14-bit bulk format using
`lowVoltage` as code `0` and `highVoltage` as code `16383`. The importer configures
the selected channel's amplitude and offset from those levels. It reports
`sampleRateMSa` as the sample rate and sets the AWG frequency from the JSON
`frequencyHz` value, unless overridden on the command line or in `defaults.toml`. The
output is kept off throughout the import. The importer locks the front panel while uploading, storing, selecting, and
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


## Related links

- [Multicomp Pro MP750290 product page](https://www.newark.com/multicomp-pro/mp750290-us/arbitrary-waveform-generator-2ch/dp/74AH3017)
- [OWON XDG3000 product page](https://www.owon.com.hk/products_owon_xdg3000_series_2-ch_250mhz_arbitrary_waveform_generator)

Released under the [MIT License](LICENSE). Copyright © 2026 James Lewis
(james@baldengineer.com).
