# Copyright (c) 2026 James Lewis (james@baldengineer.com)
# SPDX-License-Identifier: MIT
"""Terminal UI for discovering an AWG and sending waveform files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import awg_import as importer
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Center, Container, Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Button, DirectoryTree, Footer, Header, Input, Label, RichLog, Select, Static


CONFIG_KEYS = (
    "usb_resource", "timeout_ms", "expected_identity_prefix", "max_point_count",
    "max_dac_code", "frequency_hz", "voltage_vpp", "offset_voltage", "channel",
    "enable_output", "persist",
)
BOOL_KEYS = {"enable_output", "persist"}


class ConfirmExitScreen(ModalScreen[bool]):
    """Confirmation prompt shown before leaving the TUI."""

    BINDINGS = [("escape", "cancel", "Cancel")]
    CSS = """
    ConfirmExitScreen { align: center middle; }
    #exit-dialog { width: 48; height: auto; padding: 2; border: round $accent; background: $surface; }
    #exit-dialog Static { width: 1fr; content-align: center middle; margin-bottom: 2; }
    #exit-dialog Horizontal { width: 1fr; align: center middle; }
    #exit-dialog Button { margin: 0 1; }
    """

    def compose(self) -> ComposeResult:
        with Center(id="exit-dialog"):
            yield Static("Exit the AWG terminal UI?")
            with Horizontal():
                yield Button("Exit", id="confirm-exit", variant="error")
                yield Button("Cancel", id="cancel-exit")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm-exit")

    def action_cancel(self) -> None:
        self.dismiss(False)


class FileBrowserScreen(ModalScreen[Path | None]):
    """Browse for a JSON or CSV waveform from the project directory."""

    BINDINGS = [("escape", "cancel", "Cancel")]
    CSS = """
    FileBrowserScreen { align: center middle; }
    #file-dialog { width: 80; height: 80%; padding: 1 2; border: round $accent; background: $surface; }
    #file-dialog .dialog-title { height: 2; text-style: bold; color: $accent; }
    #file-tree { height: 1fr; border: round $secondary; }
    #file-dialog #file-note { height: 2; color: $text-muted; }
    """

    def __init__(self, root: Path) -> None:
        super().__init__()
        self.root = root

    def compose(self) -> ComposeResult:
        with Container(id="file-dialog"):
            yield Static("Select waveform file", classes="dialog-title")
            yield DirectoryTree(self.root, id="file-tree")
            yield Static("Choose a .json or .csv file. Press Esc to cancel.", id="file-note")

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        path = Path(event.path)
        if path.suffix.lower() not in {".json", ".csv"}:
            self.notify("Select a .json or .csv waveform file", severity="warning")
            return
        self.dismiss(path)

    def action_cancel(self) -> None:
        self.dismiss(None)


class AwgTui(App[None]):
    """Keyboard-friendly Textual front end for awg_import.py."""

    TITLE = "AWG waveform terminal"
    SUB_TITLE = "TOML configuration and VISA waveform sender"
    BINDINGS = [("escape", "request_quit", "Quit")]
    CSS = """
    Screen { layout: vertical; }
    #main { height: 1fr; layout: horizontal; }
    #left, #right { height: 1fr; padding: 1 2; border: round $accent; }
    #left { width: 2fr; }
    #left { overflow-y: auto; }
    #right { width: 3fr; }
    .section-title { text-style: bold; color: $accent; margin: 0 0 1 0; }
    .field { height: 3; layout: horizontal; }
    .field Label { width: 28; padding: 1 0; }
    .field Input, .field Select { width: 1fr; }
    #resource-row { height: 3; layout: horizontal; }
    #resource-row Select { width: 1fr; }
    #resource-row Button { width: 12; margin-left: 1; }
    #resource-row #query-idn { width: 10; }
    #file-row { height: 3; layout: horizontal; }
    #file-row Select { width: 1fr; }
    #file-row Button { width: 12; margin-left: 1; }
    #file-row #browse-files { width: 10; }
    #output-row { height: 3; layout: horizontal; }
    #output-row Button { width: 12; margin-right: 1; }
    #console { height: 12; border: round $secondary; margin: 1 2 0 2; }
    #hint { color: $text-muted; margin: 1 0; }
    """

    config_dir = reactive(Path.cwd())

    def __init__(self) -> None:
        super().__init__()
        self.configs: dict[str, Path] = {}
        self.defaults: dict[str, Any] = {}
        self.current_config: Path | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="main"):
            with VerticalScroll(id="left"):
                yield Static("Configuration", classes="section-title")
                yield Label("TOML profile")
                yield Select([], id="config-select", allow_blank=True)
                yield Static("Loaded values can be edited before sending.", id="hint")
                for key in CONFIG_KEYS:
                    with Horizontal(classes="field"):
                        yield Label(key)
                        if key in BOOL_KEYS:
                            yield Select([("true", True), ("false", False)], id=f"field-{key}", allow_blank=False)
                        else:
                            yield Input(id=f"field-{key}")
            with Vertical(id="right"):
                yield Static("Instrument", classes="section-title")
                with Horizontal(id="resource-row"):
                    yield Select([], id="resource-select", allow_blank=True)
                    yield Button("Refresh", id="refresh-resources")
                    yield Button("*IDN?", id="query-idn", variant="primary")
                yield Static("Waveform file", classes="section-title")
                with Horizontal(id="file-row"):
                    yield Select([], id="file-select", allow_blank=True)
                    yield Button("Browse", id="browse-files")
                    yield Button("Send", id="send-file", variant="success")
                yield Static("Channel output", classes="section-title")
                with Horizontal(id="output-row"):
                    yield Button("CH1 ON", id="ch1-on", variant="success")
                    yield Button("CH1 OFF", id="ch1-off", variant="error")
                    yield Button("CH2 ON", id="ch2-on", variant="success")
                    yield Button("CH2 OFF", id="ch2-off", variant="error")
                yield Static("Files are read from the project directory.", id="file-hint")
        yield RichLog(id="console", highlight=True, markup=False, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        self._log("AWG TUI started")
        self._load_config_profiles()
        self._refresh_files()
        self._refresh_resources()

    def action_request_quit(self) -> None:
        self.push_screen(ConfirmExitScreen(), self._exit_after_confirmation)

    def _exit_after_confirmation(self, confirmed: bool | None) -> None:
        if confirmed:
            self.exit()

    def _log(self, message: str) -> None:
        self.query_one("#console", RichLog).write(message)

    def _load_config_profiles(self) -> None:
        paths = sorted(self.config_dir.glob("*.toml"), key=lambda p: (p.name != "defaults.toml", p.name.lower()))
        self.configs = {path.name: path for path in paths}
        select = self.query_one("#config-select", Select)
        select.set_options([(name, name) for name in self.configs])
        if not paths:
            self._load_config(importer.packaged_defaults_resource())
            self._log("No local TOML files found; loaded packaged defaults")
            return
        self._load_config(paths[0])
        select.value = paths[0].name

    def _load_config(self, path: Path) -> None:
        try:
            values = importer.load_defaults(path)
        except (OSError, ValueError) as exc:
            self._log(f"Config error ({path.name}): {exc}")
            return
        self.defaults = values
        self.current_config = path
        for key in CONFIG_KEYS:
            widget = self.query_one(f"#field-{key}")
            value = values[key]
            widget.value = value if key in BOOL_KEYS else str(value)
        self._log(f"Loaded {path.name}")

    def _refresh_files(self) -> None:
        paths = sorted([*self.config_dir.glob("*.json"), *self.config_dir.glob("*.csv")], key=lambda p: p.name.lower())
        select = self.query_one("#file-select", Select)
        select.set_options([(path.name, str(path)) for path in paths])
        if paths:
            select.value = str(paths[0])
            self._log(f"Found {len(paths)} waveform file(s)")
        else:
            self._log("No .json or .csv waveform files found")

    def _refresh_resources(self) -> None:
        self._refresh_resources_worker()

    @work(thread=True)
    def _refresh_resources_worker(self) -> None:
        try:
            resources = importer.list_visa_resources()
            self.call_from_thread(self._set_resources, resources)
            self.call_from_thread(self._log, f"Found {len(resources)} VISA resource(s)")
        except RuntimeError as exc:
            self.call_from_thread(self._log, f"VISA discovery failed: {exc}")

    def _set_resources(self, resources: tuple[str, ...]) -> None:
        configured = str(self.defaults.get("usb_resource", ""))
        options = list(dict.fromkeys([*resources, configured] if configured else resources))
        select = self.query_one("#resource-select", Select)
        select.set_options([(resource, resource) for resource in options])
        if options:
            select.value = configured if configured in options else options[0]

    def _file_browser_selected(self, path: Path | None) -> None:
        if path is None:
            return
        select = self.query_one("#file-select", Select)
        path_value = str(path)
        paths = sorted(
            [*self.config_dir.glob("*.json"), *self.config_dir.glob("*.csv")],
            key=lambda item: item.name.lower(),
        )
        if path not in paths:
            paths.append(path)
        select.set_options([(item.name, str(item)) for item in paths])
        select.value = path_value
        self._log(f"Selected {path}")

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "config-select" and event.value is not Select.BLANK:
            path = self.configs.get(str(event.value))
            if path:
                self._load_config(path)

    def _config_values(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for key in CONFIG_KEYS:
            widget = self.query_one(f"#field-{key}")
            raw = widget.value
            if key in BOOL_KEYS:
                values[key] = raw is True or raw == "true"
            elif key in {"timeout_ms", "max_point_count", "max_dac_code", "channel"}:
                values[key] = int(str(raw))
            elif key in {"frequency_hz", "voltage_vpp", "offset_voltage"}:
                values[key] = float(str(raw))
            else:
                values[key] = str(raw)
        return values

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "refresh-resources":
            self._log("Refreshing VISA resources...")
            self._refresh_resources()
        elif button_id == "browse-files":
            self.push_screen(FileBrowserScreen(self.config_dir), self._file_browser_selected)
        elif button_id in {"ch1-on", "ch1-off", "ch2-on", "ch2-off"}:
            resource = self.query_one("#resource-select", Select).value
            if resource is Select.BLANK:
                self._log("Select a VISA resource first")
                return
            try:
                values = self._config_values()
                channel = 1 if button_id.startswith("ch1") else 2
                enabled = button_id.endswith("on")
                self._set_output_worker(str(resource), values["timeout_ms"], channel, enabled)
            except (TypeError, ValueError) as exc:
                self._log(f"Invalid configuration: {exc}")
        elif button_id == "query-idn":
            resource = self.query_one("#resource-select", Select).value
            if resource is not Select.BLANK:
                try:
                    self._query_idn_worker(str(resource), self._config_values())
                except (TypeError, ValueError) as exc:
                    self._log(f"Invalid configuration: {exc}")
        elif button_id == "send-file":
            file_value = self.query_one("#file-select", Select).value
            resource = self.query_one("#resource-select", Select).value
            if file_value is not Select.BLANK and resource is not Select.BLANK:
                try:
                    self._send_worker(Path(str(file_value)), str(resource), self._config_values())
                except (TypeError, ValueError) as exc:
                    self._log(f"Invalid configuration: {exc}")

    @work(thread=True)
    def _set_output_worker(self, resource: str, timeout_ms: int, channel: int, enabled: bool) -> None:
        try:
            importer.set_output_state(resource, timeout_ms, channel, enabled)
            self.call_from_thread(self._log, f"Channel {channel} output: {'ON' if enabled else 'OFF'}")
        except RuntimeError as exc:
            self.call_from_thread(self._log, f"Output control failed: {exc}")

    @work(thread=True)
    def _query_idn_worker(self, resource: str, values: dict[str, Any]) -> None:
        try:
            identity = importer.query_visa_identity(resource, values["timeout_ms"])
            self.call_from_thread(self._log, f"{resource} -> {identity}")
        except (RuntimeError, ValueError) as exc:
            self.call_from_thread(self._log, f"*IDN? failed: {exc}")

    @work(thread=True)
    def _send_worker(self, path: Path, resource: str, values: dict[str, Any]) -> None:
        try:
            config = importer.Config.from_defaults(values)
            waveform = importer.load_waveform(path, config)
            payload = importer.encode_dab(waveform, config)
            user_slot = values["channel"] if values["persist"] else None
            self.call_from_thread(self._log, f"Sending {path.name} ({waveform.sample_count} points)...")
            result = importer.upload_waveform(resource, values["timeout_ms"], waveform, payload, user_slot,
                                               values["channel"], values["enable_output"], values["voltage_vpp"],
                                               values["offset_voltage"], values["frequency_hz"], config)
            self.call_from_thread(self._log, f"Complete: {result['identity']} | CH{result['channel']} output={result['output']}")
        except (RuntimeError, ValueError, OSError) as exc:
            self.call_from_thread(self._log, f"Send failed: {exc}")


if __name__ == "__main__":
    AwgTui().run()
