# MCP Arbitrary Waveform Generator CLI

Command-line tools for working with the Multicomp Pro MP750290 arbitrary waveform
generator, a rebadged OWON XDG3000-series instrument.

The project is intended to support two operating modes:

1. Generate binary arbitrary-waveform files for manual transfer to the instrument.
2. Connect directly to the instrument over the network and control it with SCPI.

The direct-control mode currently supports an identity query and an opt-in development
upload. The included script can generate a small sine wave, write it point-by-point to
the instrument's edit memory, and select that memory as the channel 1 function.

## Hardware and connection

- Instrument: Multicomp Pro MP750290
- Compatible platform: OWON XDG3000 series
- Default address: `192.168.128.29`
- Default TCP port: `3000`
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

## Query the instrument identity

Run the script with its default connection settings:

```powershell
python .\awg_idn.py
```

Override the address, port, or timeout when needed:

```powershell
python .\awg_idn.py --host 192.168.128.29 --port 3000 --timeout 5
```

Show all command-line options:

```powershell
python .\awg_idn.py --help
```

The command exits with status `0` after receiving an identification response and
status `1` if the connection or query fails.

## Load the test waveform

Generate a 16-point, 1 V peak sine wave and load it into `EMEMory`:

```powershell
python .\awg_idn.py --load-test-waveform
```

The upload uses the documented `DATA:POINts` and `DATA:DATA:VALue` commands, reads
back the first and last samples, selects `EMEMory` for channel 1, and checks the SCPI
error queue. Channel 1 is disabled before the upload and is deliberately left off.

The point count and peak amplitude can be changed for development:

```powershell
python .\awg_idn.py --load-test-waveform --samples 32 --amplitude 0.5
```

## Reference material

The local `datasheets/` directory contains the XDG3000 SCPI programmer's manual used
to identify supported commands. That directory is intentionally excluded from Git.

The ignored `old code/` directory contains an earlier CSV-to-binary waveform converter
and exploratory PyVISA control code. It will serve as a reference while the two CLI
modes are developed.

## TODO

- Add support for selecting an arbitrary waveform file from the instrument's mass
  storage using the SCPI `SOURce:FUNCtion:EFILe` commands.

## Related links

- [Multicomp Pro MP750290 product page](https://www.newark.com/multicomp-pro/mp750290-us/arbitrary-waveform-generator-2ch/dp/74AH3017)
- [OWON XDG3000 product page](https://www.owon.com.hk/products_owon_xdg3000_series_2-ch_250mhz_arbitrary_waveform_generator)
- [Tektronix MSO22 MCP endpoint](http://192.168.128.241:8787/mcp)
