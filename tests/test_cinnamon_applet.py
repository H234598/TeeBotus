from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

import TeeBotus.cinnamon_applet as cinnamon_applet
from TeeBotus.cinnamon_applet import FREE_TEXT_STATUS_FIELD_BOUNDARIES
from TeeBotus.cinnamon_applet import FLAG_PROBLEM_STATUS_FIELDS
from TeeBotus.cinnamon_applet import FORCED_PROBLEM_STATUS_FIELDS
from TeeBotus.cinnamon_applet import NEUTRAL_FLAG_VALUES
from TeeBotus.cinnamon_applet import PROBLEM_STATUSES
from TeeBotus.cinnamon_applet import SECONDARY_PROBLEM_STATUS_FIELDS
from TeeBotus.cinnamon_applet import STATUS_FIELD_BOUNDARY_KEYS
from TeeBotus.cinnamon_applet import STATUS_FIELD_BOUNDARY_VALUES
from TeeBotus.cinnamon_applet import build_status_payload, parse_runtime_status
from TeeBotus.cinnamon_applet import CONFIRMED_ACTIVE_SUBSTATES
from TeeBotus.runtime.version_marker import read_runtime_version_status, write_runtime_version_marker


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APPLET_DIR = PROJECT_ROOT / "files" / "teebotus@H234598"


def _js_const_array_values(source: str, name: str) -> set[str]:
    match = re.search(rf"const {re.escape(name)} = \[(.*?)\];", source, re.DOTALL)
    assert match is not None
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def _js_const_object_keys(source: str, name: str) -> set[str]:
    match = re.search(rf"const {re.escape(name)} = \{{(.*?)\n\}};", source, re.DOTALL)
    assert match is not None
    return set(re.findall(r"\n\s*([A-Za-z_][A-Za-z0-9_]*):", match.group(1)))


def _js_status_label_keys(source: str) -> set[str]:
    match = re.search(r"let labels = \{(.*?)\n    \};", source, re.DOTALL)
    assert match is not None
    return set(re.findall(r"\n\s*([A-Za-z_][A-Za-z0-9_]*):", match.group(1)))


def _run_js_applet_expression(expression: str) -> object:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not available for Cinnamon applet behavior check")
    script = f"""
const vm = require("vm");
const source = require("fs").readFileSync(process.env.TEEBOTUS_APPLET_SOURCE, "utf8");
const TextIconApplet = function() {{}};
TextIconApplet.prototype = {{}};
const context = {{
  console: console,
  imports: {{
    ui: {{
      applet: {{ TextIconApplet: TextIconApplet }},
      modalDialog: {{}},
      popupMenu: {{}},
      settings: {{}}
    }},
        gi: {{
          Clutter: {{}},
          St: {{}},
          Gio: {{}},
          Pango: {{
            EllipsizeMode: {{ NONE: "none", END: "end" }},
            WrapMode: {{ WORD_CHAR: "word_char" }}
          }},
          GLib: {{
            FileTest: {{ IS_EXECUTABLE: 1 }},
            get_home_dir: () => "/tmp",
            build_filenamev: (parts) => parts.join("/"),
            find_program_in_path: (name) => name === "gnome-terminal" ? "/usr/bin/gnome-terminal" : null,
            file_test: (path, flag) => flag === 1 && ["/usr/bin/bash", "/usr/bin/gnome-terminal", "/usr/bin/python3", "/tmp/TeeBotus/.venv-py313/bin/python", "/usr/bin/systemctl", "/usr/bin/xterm", "/tmp/.local/bin/codex-usage", "/tmp/.local/bin/custom-tool", "/tmp/.local/bin/constructor"].includes(path),
        shell_parse_argv: (raw) => [true, String(raw || "").split(/\\s+/).filter(Boolean)]
      }}
    }},
    mainloop: {{
      source_remove: () => {{}},
      timeout_add: () => 0,
      timeout_add_seconds: () => 0
    }}
  }}
}};
vm.createContext(context);
vm.runInContext(source + "\\nglobalThis.__TeeBotusApplet = TeeBotusApplet;", context);
const applet = Object.create(context.__TeeBotusApplet.prototype);
const result = (function() {{
  return (
    {expression}
  );
}})();
console.log(JSON.stringify(result));
"""
    env = os.environ.copy()
    env["TEEBOTUS_APPLET_SOURCE"] = str(APPLET_DIR / "applet.js")
    completed = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True, timeout=10, env=env)
    return json.loads(completed.stdout)


def _run_gjs_spawn_smoke(
    *,
    child_code: str = "import sys; sys.stdout.write('x'*10000); sys.stderr.write('e'*2000)",
    max_stdout_chars: int = 1000,
    max_stderr_chars: int = 100,
) -> dict[str, object]:
    gjs = shutil.which("gjs")
    if not gjs:
        pytest.skip("gjs is not available for Gio subprocess behavior check")
    script = f"""
const Gio = imports.gi.Gio;
const GLib = imports.gi.GLib;
const appletSource = imports.byteArray.toString(GLib.file_get_contents(GLib.getenv("TEEBOTUS_APPLET_SOURCE"))[1]);
function load(fakeImports) {{
  const imports = fakeImports;
  eval(appletSource + "\\nglobalThis.__TeeBotusApplet = TeeBotusApplet;");
}}
load({{
  ui: {{applet: {{TextIconApplet: function() {{}}}}, modalDialog: {{}}, popupMenu: {{}}, settings: {{}}}},
  gi: {{Clutter: {{}}, St: {{}}, Gio: Gio, GLib: GLib, Pango: {{EllipsizeMode: {{NONE: 0, END: 1}}, WrapMode: {{WORD_CHAR: 0}}}}}},
  mainloop: {{source_remove: function() {{}}, timeout_add: function() {{return 0;}}, timeout_add_seconds: function() {{return 0;}}}}
}});
let applet = Object.create(globalThis.__TeeBotusApplet.prototype);
applet._resolveSpawnArgv = function(argv) {{ return argv; }};
applet.spawnGeneration = 0;
applet.spawnProcesses = [];
applet.appletRemoved = false;
let loop = new GLib.MainLoop(null, false);
  applet._spawn(
  ["/usr/bin/python3", "-c", {json.dumps(child_code)}],
  function(stdout, stderr, ok) {{
    print(JSON.stringify({{ok: ok, stdout: stdout.length, stderr: stderr.length, error: stderr}}));
    loop.quit();
  }},
  null,
  {{maxStdoutChars: {max_stdout_chars}, maxStderrChars: {max_stderr_chars}, outputLimitError: "bounded"}}
);
loop.run();
"""
    env = os.environ.copy()
    env["TEEBOTUS_APPLET_SOURCE"] = str(APPLET_DIR / "applet.js")
    completed = subprocess.run([gjs, "-c", script], check=True, capture_output=True, text=True, timeout=10, env=env)
    return json.loads(completed.stdout)


def _run_gjs_spawn_success_query_failure_smoke() -> dict[str, object]:
    gjs = shutil.which("gjs")
    if not gjs:
        pytest.skip("gjs is not available for Gio subprocess behavior check")
    script = f"""
const GLib = imports.gi.GLib;
const appletSource = imports.byteArray.toString(GLib.file_get_contents(GLib.getenv("TEEBOTUS_APPLET_SOURCE"))[1]);
function FakeBytes() {{}}
FakeBytes.prototype.get_size = function() {{ return 0; }};
function FakeStream() {{}}
FakeStream.prototype.read_bytes_async = function(size, priority, cancellable, callback) {{
  GLib.idle_add(GLib.PRIORITY_DEFAULT, function() {{
    callback(this, {{}});
    return false;
  }}.bind(this));
}};
FakeStream.prototype.read_bytes_finish = function(result) {{ return new FakeBytes(); }};
function FakeProcess() {{}}
FakeProcess.prototype.get_stdout_pipe = function() {{ return new FakeStream(); }};
FakeProcess.prototype.get_stderr_pipe = function() {{ return new FakeStream(); }};
FakeProcess.prototype.get_if_exited = function() {{ return true; }};
FakeProcess.prototype.force_exit = function() {{}};
FakeProcess.prototype.wait_async = function(cancellable, callback) {{
  GLib.idle_add(GLib.PRIORITY_DEFAULT, function() {{
    callback(this, {{}});
    return false;
  }}.bind(this));
}};
FakeProcess.prototype.wait_finish = function(result) {{}};
FakeProcess.prototype.get_successful = function() {{ throw new Error("success query failed"); }};
function FakeLauncher() {{}}
FakeLauncher.prototype.set_cwd = function(cwd) {{}};
FakeLauncher.prototype.spawnv = function(argv) {{ return new FakeProcess(); }};
const Gio = {{
  SubprocessFlags: {{STDOUT_PIPE: 1, STDERR_PIPE: 2}},
  SubprocessLauncher: {{new: function(flags) {{ return new FakeLauncher(); }}}}
}};
function load(fakeImports) {{
  const imports = fakeImports;
  eval(appletSource + "\\nglobalThis.__TeeBotusApplet = TeeBotusApplet;");
}}
load({{
  ui: {{applet: {{TextIconApplet: function() {{}}}}, modalDialog: {{}}, popupMenu: {{}}, settings: {{}}}},
  gi: {{Clutter: {{}}, St: {{}}, Gio: Gio, GLib: GLib, Pango: {{EllipsizeMode: {{NONE: 0, END: 1}}, WrapMode: {{WORD_CHAR: 0}}}}}},
  mainloop: {{source_remove: function() {{}}, timeout_add: function() {{return 0;}}, timeout_add_seconds: function() {{return 0;}}}}
}});
let applet = Object.create(globalThis.__TeeBotusApplet.prototype);
applet._resolveSpawnArgv = function(argv) {{ return argv; }};
applet.spawnGeneration = 0;
applet.spawnProcesses = [];
applet.appletRemoved = false;
let loop = new GLib.MainLoop(null, false);
applet._spawn(
  ["fake"],
  function(stdout, stderr, ok) {{
    print(JSON.stringify({{ok: ok, stdout: stdout, stderr: stderr}}));
    loop.quit();
  }},
  null,
  {{}}
);
loop.run();
"""
    env = os.environ.copy()
    env["TEEBOTUS_APPLET_SOURCE"] = str(APPLET_DIR / "applet.js")
    completed = subprocess.run([gjs, "-c", script], check=True, capture_output=True, text=True, timeout=10, env=env)
    return json.loads(completed.stdout)


def _run_js_parse_fields(line: str) -> dict[str, str]:
    return _run_js_applet_expression(f"applet._parseFields({json.dumps(line)})")  # type: ignore[return-value]


def test_cinnamon_applet_refresh_timer_clears_itself_when_auto_refresh_stops() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not available for Cinnamon applet timer check")
    script = f"""
const vm = require("vm");
const source = require("fs").readFileSync(process.env.TEEBOTUS_APPLET_SOURCE, "utf8");
let timerCallback = null;
let removed = [];
const TextIconApplet = function() {{}};
TextIconApplet.prototype = {{}};
const context = {{
  imports: {{
    ui: {{
      applet: {{ TextIconApplet: TextIconApplet }},
      modalDialog: {{}},
      popupMenu: {{}},
      settings: {{}}
    }},
    gi: {{
      Clutter: {{}},
      St: {{}},
      Gio: {{}},
      GLib: {{
        get_home_dir: () => "/tmp",
        build_filenamev: (parts) => parts.join("/"),
        find_program_in_path: () => null,
        shell_parse_argv: (raw) => [true, String(raw || "").split(/\\s+/).filter(Boolean)]
      }}
    }},
    mainloop: {{
      source_remove: (id) => removed.push(id),
      timeout_add: () => 0,
      timeout_add_seconds: (seconds, callback) => {{
        timerCallback = callback;
        return 42;
      }}
    }}
  }}
}};
vm.createContext(context);
vm.runInContext(source + "\\nglobalThis.__TeeBotusApplet = TeeBotusApplet;", context);
const applet = Object.create(context.__TeeBotusApplet.prototype);
applet.autoRefresh = true;
applet.statusRefreshSeconds = 15;
applet._refreshStatus = function() {{
  this.autoRefresh = false;
}};
applet._scheduleRefresh();
const before = applet.statusTimer;
const keepRunning = timerCallback();
console.log(JSON.stringify({{before, after: applet.statusTimer, keepRunning, removed}}));
"""
    env = os.environ.copy()
    env["TEEBOTUS_APPLET_SOURCE"] = str(APPLET_DIR / "applet.js")
    completed = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True, timeout=10, env=env)
    result = json.loads(completed.stdout)

    assert result == {"before": 42, "after": 0, "keepRunning": False, "removed": []}


def test_cinnamon_applet_refresh_interval_is_bounded() -> None:
    result = _run_js_applet_expression(
        "({high: (applet.statusRefreshSeconds = 999999, applet._boundedInt(applet.statusRefreshSeconds, 60, 15, 3600)), "
        "low: (applet.statusRefreshSeconds = 1, applet._boundedInt(applet.statusRefreshSeconds, 60, 15, 3600))})"
    )

    assert result == {"high": 3600, "low": 60}


def test_cinnamon_applet_menu_labels_have_bounded_layout() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          const item = {
            label: {
              styles: [],
              clutter_text: {},
              set_style: function(style) { this.styles.push(style); }
            }
          };
          applet._styleMenuItemLabel(item, { maxWidthEm: 31, wrap: true });
          return {
            styles: item.label.styles,
            wrap: item.label.clutter_text.line_wrap,
            wrapMode: item.label.clutter_text.line_wrap_mode,
            ellipsize: item.label.clutter_text.ellipsize
          };
        })()
        """
    )

    assert result == {
        "styles": ["max-width: 31em;"],
        "wrap": True,
        "wrapMode": "word_char",
        "ellipsize": "none",
    }


def test_cinnamon_applet_files_are_present_and_wired() -> None:
    metadata = json.loads((APPLET_DIR / "metadata.json").read_text(encoding="utf-8"))
    schema = json.loads((APPLET_DIR / "settings-schema.json").read_text(encoding="utf-8"))
    source = (APPLET_DIR / "applet.js").read_text(encoding="utf-8")

    assert metadata["uuid"] == "teebotus@H234598"
    assert metadata["name"] == "TB"
    assert metadata["icon"] == "teebotus"
    assert (APPLET_DIR / "icon.svg").is_file()
    assert (APPLET_DIR / "SettingsLogo.py").is_file()
    assert (APPLET_DIR / "assets" / "teebotus.svg").is_file()
    assert (APPLET_DIR / "assets" / "settings-header-logo.svg").is_file()
    assert (APPLET_DIR / "assets" / "settings-about-logo.svg").is_file()
    assert (APPLET_DIR / "stylesheet.css").is_file()
    assert "new Settings.AppletSettings(this, UUID, instanceId)" in source
    assert "main-page" in schema["layout"]["pages"]
    assert "actions-page" in schema["layout"]["pages"]
    assert "settings-logo-header-section" in schema["layout"]["main-page"]["sections"]
    assert schema["settings-logo-header"]["type"] == "custom"
    assert schema["settings-logo-header"]["file"] == "SettingsLogo.py"
    assert schema["settings-logo-header"]["widget"] == "HeaderLogo"
    assert schema["about-logo"]["type"] == "custom"
    assert schema["about-logo"]["widget"] == "AboutLogo"
    assert schema["repo-path"]["default"] == "/home/teladi/TeeBotus"
    assert schema["channels"]["default"] == "telegram,signal"
    assert schema["runtime-unit"]["default"] == "teebotus.service"
    assert schema["qdrant-unit"]["default"] == "teebotus-qdrant.service"
    assert schema["qdrant-url"]["default"] == "http://127.0.0.1:6333"
    assert schema["status-refresh-seconds"]["default"] == 60
    assert "const DEFAULT_STATUS_REFRESH_SECONDS = 60;" in source
    assert "this.statusRefreshSeconds = DEFAULT_STATUS_REFRESH_SECONDS;" in source
    assert "STATUS_REFRESH_MAX_SECONDS = 3600" in source
    assert "this._boundedInt(this.statusRefreshSeconds, DEFAULT_STATUS_REFRESH_SECONDS, STATUS_REFRESH_MIN_SECONDS, STATUS_REFRESH_MAX_SECONDS)" in source
    assert "const CODEX_USAGE_STALE_WARNING_HOURS = 24;" in source
    assert schema["status-timeout-seconds"]["default"] == 30
    assert "const DEFAULT_STATUS_TIMEOUT_SECONDS = 30;" in source
    assert "this.statusTimeoutSeconds = DEFAULT_STATUS_TIMEOUT_SECONDS;" in source
    assert "this._statusTimeoutSeconds()" in source
    assert "STATUS_TIMEOUT_MAX_SECONDS = 300" in source
    assert "STATUS_TIMEOUT_GRACE_SECONDS = 5" in source
    assert "STATUS_HELPER_OVERHEAD_SECONDS = 30" in source
    assert "const MAX_HELPER_JSON_CHARS = 1000000;" in source
    assert "const MAX_SUBPROCESS_STDOUT_CHARS = MAX_HELPER_JSON_CHARS;" in source
    assert "const MAX_SUBPROCESS_STDERR_CHARS = 20000;" in source
    assert "read_bytes_async(SUBPROCESS_READ_CHUNK_BYTES" in source
    assert "process.wait_async" in source
    assert "communicate_utf8_async" not in source
    assert "if (text.length > MAX_HELPER_JSON_CHARS)" in source
    assert "const MAX_COMMAND_ARG_CHARS = 4096;" in source
    assert "const MAX_COMMAND_ARG_COUNT = 128;" in source
    assert "const MAX_COMMAND_CHARS = 32768;" in source
    assert "const MAX_MENU_LINE_CHARS = 2000;" in source
    assert "const MAX_PANEL_STATUS_CHARS = 500;" in source
    assert "let text = this._shortText(String(label || \"\"), MAX_MENU_LINE_CHARS);" in source
    assert "const MAX_UNIT_TOKEN_CHARS = 96;" in source
    assert "_boundedInt: function(value, fallback, minValue, maxValue)" in source
    assert "_nonNegativeInt: function(value, fallback)" in source
    assert "_strictInt: function(value)" in source
    assert "new PopupMenu.PopupMenuManager(this)" in source
    assert "new Applet.AppletPopupMenu(this, orientation)" in source
    assert "this.menuManager.addMenu(this.menu)" in source
    assert "Gio.SubprocessLauncher.new" in source
    assert "}, this._repoPath(), { timeoutMs:" in source
    assert "this._spawn(argv, (stdout, stderr, ok) => {" in source
    assert "this._refreshMenuContents();" in source
    assert "_refreshMenuContents: function()" in source
    assert "const TRUSTED_SPAWN_DIRS = " in source
    assert "const TRUSTED_USER_LOCAL_COMMANDS = " in source
    assert "_resolveSpawnArgv: function(argv)" in source
    assert "_normalizeCommandArgv: function(argv, throwOnError)" in source
    assert "_trustedExecutablePath: function(command)" in source
    assert "_trustedAbsoluteExecutablePath: function(path)" in source
    assert "_findTrustedProgramInPath: function(command)" in source
    assert "Object.prototype.hasOwnProperty.call(TRUSTED_USER_LOCAL_COMMANDS, name)" in source
    assert "launcher.spawnv(resolvedArgv)" in source
    assert "options = options || {};" in source
    assert "process.force_exit();" in source
    assert "launcher.set_cwd(String(cwd))" in source
    assert "const ModalDialog = imports.ui.modalDialog;" in source
    assert "const Clutter = imports.gi.Clutter;" in source
    assert "const Pango = imports.gi.Pango;" in source
    assert "MENU_LABEL_WIDTH_EM = 42" in source
    assert "_applyMenuLayout: function()" in source
    assert "_styleMenuItemLabel: function(item, options)" in source
    assert "item.label.clutter_text.ellipsize" in source
    assert "this.appletRemoved = false;" in source
    assert "this.spawnGeneration = 0;" in source
    assert "this.spawnProcesses = [];" in source
    assert "applet.spawnProcesses.push(process);" in source
    assert "let runningProcesses = this.spawnProcesses || [];" in source
    assert "process.force_exit();" in source
    assert "let spawnGeneration = this.spawnGeneration;" in source
    assert "if (applet.appletRemoved || applet.spawnGeneration !== spawnGeneration) {" in source
    assert "this.appletRemoved = true;" in source
    assert "this.spawnGeneration += 1;" in source
    assert "_commandArgs: function(value, fallback)" in source
    assert "GLib.shell_parse_argv(raw)" in source
    assert "const SYSTEM_PYTHON = \"/usr/bin/python3\";" in source
    assert "const DEFAULT_VENV_BIN = GLib.build_filenamev([DEFAULT_REPO_PATH, \".venv-py313\", \"bin\"]);" in source
    assert "let configured = String(this.pythonCommand || \"\").trim();" in source
    assert "let fallback = GLib.file_test(DEFAULT_PYTHON, GLib.FileTest.IS_EXECUTABLE) ? [DEFAULT_PYTHON] : [SYSTEM_PYTHON];" in source
    assert "this._codexUsageArgs().concat(args || [])" in source
    assert "this._safeExecutableArgs(configured, [])" in source
    assert "_terminalCommandArgs: function(parsed)" in source
    assert "_terminalCommandHasEmbeddedCommand: function(argv)" in source
    assert "_safeExecutableArgs: function(value, fallback)" in source
    assert "_safePythonArgs: function(value, fallback)" in source
    assert "_isSafeExecutable: function(value)" in source
    assert "const SAFE_PYTHON_PREFIX_FLAGS = " in source
    assert "_safeLocalPath: function(value, fallback)" in source
    assert "_libraryPath: function()" in source
    assert "_safeProjectUrl: function(value, fallback)" in source
    assert "_projectUrlHasUnsafePathSegment: function(url)" in source
    assert "_githubUrl: function()" in source
    assert "_commitsUrl: function()" in source
    assert "_runtimeUnit: function()" in source
    assert "_qdrantUnit: function()" in source
    assert "_safeSystemdUnit: function(value, fallback)" in source
    assert 'unit.charAt(0) === "-"' in source
    assert 'unit.indexOf("/") >= 0' in source
    assert 'service|timer|socket|target|path' in source
    assert 'if (last === "--" || last === "-e")' in source
    assert 'if (binary === "xterm" || binary === "konsole")' in source
    assert 'return argv.concat(["-e"]);' in source
    assert 'return argv.concat(["--"]);' in source
    assert (PROJECT_ROOT / "scripts" / "install_cinnamon_applet.py").is_file()


def test_cinnamon_applet_main_menu_exposes_teebotus_features() -> None:
    source = (APPLET_DIR / "applet.js").read_text(encoding="utf-8")
    schema = json.loads((APPLET_DIR / "settings-schema.json").read_text(encoding="utf-8"))

    assert "teebotus-cinnamon-applet" not in source
    assert "TeeBotus.cinnamon_applet" in source
    assert 'this.statusMenu = new PopupMenu.PopupSubMenuMenuItem(_("Status & Diagnose"))' in source
    assert "this._statusDetailLines(payload)" in source
    assert "const MENU_LINE_WRAP_THRESHOLD = 110;" in source
    assert "this._menuLine(values[i], false)" in source
    assert 'this.messengerMenu = new PopupMenu.PopupSubMenuMenuItem(_("Messenger"))' in source
    assert 'this.llmMenu = new PopupMenu.PopupSubMenuMenuItem(_("LLM & Dienste"))' in source
    assert 'this.apiMenu = new PopupMenu.PopupSubMenuMenuItem(_("API Keys & Usage"))' in source
    assert 'this.memoryMenu = new PopupMenu.PopupSubMenuMenuItem(_("Memory & Speicher"))' in source
    assert 'this.bibliothekarMenu = new PopupMenu.PopupSubMenuMenuItem(_("Bibliothekar"))' in source
    assert 'this.proactiveMenu = new PopupMenu.PopupSubMenuMenuItem(_("Proaktiv"))' in source
    assert 'this.actionsMenu = new PopupMenu.PopupSubMenuMenuItem(_("Bot-Steuerung"))' in source
    assert 'this.quickCommandsMenu = new PopupMenu.PopupSubMenuMenuItem(_("Schnellbefehle"))' in source
    assert "systemctl" in source
    assert "journalctl" in source
    assert "TeeBotus.bibliothekar" in source
    assert "TeeBotus.proactive" in schema["proactive-command"]["default"]
    assert "_formatMessengerLine" in source
    assert "_formatLlmLine" in source
    assert 'sections["Accounts und Entscheidungen"]' in source
    assert 'sections["Lokale Dienste"]' in source
    assert "let llmStatusGroups = this._splitProblemStatusLines" in source
    assert 'let localServiceLines = this._problemStatusLines(sections["Lokale Dienste"] || []);' in source
    assert "llmStatusGroups.problem" in source
    assert "llmStatusGroups.normal" in source
    assert "_formatApiBudgetLine" in source
    assert "_formatProjectHistoryLine" in source
    assert 'sections["Projekt-History"]' in source
    assert "summary.codex_history_instances" in source
    assert "summary.codex_history_repos" in source
    assert "summary.codex_history_run_summaries" in source
    assert "summary.codex_history_strategies" in source
    assert "summary.codex_history_graphs" in source
    assert "summary.codex_history_problem_status_count" in source
    assert "fields.codex_history_repo" in source
    assert "_appendProjectHistoryDrilldown" in source
    assert "_codexHistoryRepoDetails" in source
    assert "_codexHistoryKindLabel" in source
    assert "_formatMemoryLine" in source
    assert "_formatAccountLine" in source
    assert "_accountStatusLines" in source
    assert '"Account-Memory-Legacy-Recovery " + fields.account_memory_recovery_legacy' in source
    assert "_problemStatusLines: function(lines, isForcedProblem)" in source
    assert "_splitProblemStatusLines: function(lines, isForcedProblem)" in source
    assert "return this._problemStatusLines(lines);" in source
    assert "let accountStatusGroups = this._splitProblemStatusLines" in source
    assert 'let accountStatusGroups = this._splitProblemStatusLines(sections["Tools und Account-Memory"] || []);' in source
    assert 'let memoryStatusLines = this._problemStatusLines(sections["Memory und semantische Suche"] || []);' in source
    assert "accountStatusGroups.problem" in source
    assert "accountStatusGroups.normal" in source
    assert 'sections["Tools und Account-Memory"]' in source
    assert "_errorText: function(fields)" in source
    assert '"; Fehler " + value' in source
    assert '"; Warnung " + warning' in source
    assert "this._errorText(fields)" in source
    assert "_fieldValueEnd: function(text, matches, index)" in source
    assert "_sectionProblemText: function(value)" in source
    assert '" | Probleme " + String(count)' in source
    assert 'this._problemStatusLines(sections["API Keys, Limits und Kosten"] || [])' in source
    assert "Ersatz bei Modell-/Key-/Limitfehlern" in source
    assert "codex-usage latest" in source
    assert "_codexUsageIsStale: function(fields)" in source
    assert 'let status = this._codexUsageIsStale(fields) ? "stale" : fields.status;' in source
    assert "Qdrant-Status" in source
    assert "Usermemory-Vektoranzahl" in source
    assert "TeeBotus.embedding" in source
    assert "Codex-History Report" in source
    assert "Codex-History Index jetzt" in source
    assert "Codex-History Strategie jetzt" in source
    assert "Codex-History Timer aktivieren" in source
    assert "_openCodexHistoryTimerEnable" in source
    assert "TeeBotus.codex_history_systemd" in source
    assert "--index-strategic-analysis" in source
    assert "--index-graph-svg-engine" in source
    assert '"auto"' in source
    assert "--index-graph-queue-svg" in source
    assert "--index-dispatch" in source
    assert "/status" in source
    assert "/voicemodel" in source
    assert 'this.set_applet_label("TB")' in source
    assert '"HF-Pool " + fields.hf_pool + " / " + fields.target' in source
    assert '"HF-Pool " + fields.hf_pool + ": "' in source
    assert '"Account-LLM " + fields.llm' in source
    assert '"Account-Entscheider " + fields.structured_decision' in source
    assert '"Lokale Transkription " + fields.local_transcription' in source
    assert '"Bibliothekar " + fields.bibliothekar' in source
    assert '"; Feed " + this._statusWord(fields.models_feed)' in source
    assert "const SECONDARY_PROBLEM_STATUS_FIELDS = [" in source
    assert "this._statusFieldHasProblem(values, key)" in source
    assert '"; Kontext " + fields.context_length' in source
    assert "_healthProblemTotal: function(health, summary, counts)" in source
    assert "_problemStatusCount: function(counts)" in source
    assert "_problemBreakdownText: function(value)" in source
    assert "_commandProblemBreakdownText: function(health)" in source
    assert "_qdrantProblemBreakdownText: function(health)" in source
    assert "_healthDetailText: function(health, summary, counts, effectiveStatus, additionalProblemCount)" in source
    assert "this._styleMenuItemLabel(this.summaryItem, { maxWidthEm: SUBMENU_LABEL_WIDTH_EM, wrap: true });" in source
    assert "this._styleMenuItemLabel(this.versionItem, { maxWidthEm: SUBMENU_LABEL_WIDTH_EM, wrap: true });" in source
    assert "qdrant_runtime_problem_count" in source
    assert '"Runtime:" + String(runtimeCount)' in source
    assert '" | Probleme "' in source
    assert '" | Kommando:"' in source
    assert '" | Qdrant "' in source
    assert "const PROBLEM_STATUSES = [" in source
    for status in sorted(PROBLEM_STATUSES):
        assert f'"{status}"' in source
    assert "payload.health" in source
    assert '"Health "' in source
    assert 'broken: "defekt"' in source
    assert 'cooldown: "Cooldown"' in source
    assert 'available: "verfuegbar"' in source
    assert 'degraded: "eingeschraenkt"' in source
    assert 'no_limits_found: "keine Limits gefunden"' in source
    assert 'never: "noch nie aktualisiert"' in source
    assert 'needed: "benoetigt"' in source
    assert 'schema_mismatch: "Schema passt nicht"' in source
    assert 'stale: "veraltet"' in source
    assert 'unknown: "unbekannt"' in source
    assert 'unsupported: "nicht unterstuetzt"' in source


def test_cinnamon_applet_problem_status_constants_match_helper() -> None:
    source = (APPLET_DIR / "applet.js").read_text(encoding="utf-8")

    assert _js_const_array_values(source, "PROBLEM_STATUSES") == set(PROBLEM_STATUSES)
    assert _js_const_array_values(source, "SECONDARY_PROBLEM_STATUS_FIELDS") == set(SECONDARY_PROBLEM_STATUS_FIELDS)
    assert _js_const_object_keys(source, "STATUS_FIELD_BOUNDARY_KEYS") == set(STATUS_FIELD_BOUNDARY_KEYS)
    assert _js_const_object_keys(source, "STATUS_FIELD_NEUTRAL_BOUNDARY_VALUES") == (
        set(STATUS_FIELD_BOUNDARY_VALUES) - set(PROBLEM_STATUSES)
    )
    assert "_quotedCharacterIndexes: function(text)" in source
    assert "key && !quoted[keyStart]" in source
    assert _js_const_array_values(source, "FLAG_PROBLEM_STATUS_FIELDS") == set(FLAG_PROBLEM_STATUS_FIELDS)
    assert NEUTRAL_FLAG_VALUES == frozenset({"0", "false", "no", "none", "off"})
    for value in NEUTRAL_FLAG_VALUES:
        assert f'"{value}": true' in source
    assert "const FORCED_PROBLEM_STATUS_FIELDS = {" in source
    for field, status in FORCED_PROBLEM_STATUS_FIELDS.items():
        assert f"{field}: \"{status}\"" in source
    assert set(PROBLEM_STATUSES) <= _js_status_label_keys(source)
    assert set(STATUS_FIELD_BOUNDARY_VALUES) <= _js_status_label_keys(source)
    assert 'action: { warning: true }' in source
    assert 'command: { apply_command: true }' in source
    assert 'error: { warning: true }' in source
    assert 'message: { action: true, warning: true }' in source
    assert "route_error: {" in source
    assert "fallback_base_url: true" in source
    assert "remote_fallback: true" in source
    assert FREE_TEXT_STATUS_FIELD_BOUNDARIES["action"] == frozenset({"warning"})
    assert FREE_TEXT_STATUS_FIELD_BOUNDARIES["error"] == frozenset({"warning"})
    assert FREE_TEXT_STATUS_FIELD_BOUNDARIES["message"] == frozenset({"action", "warning"})
    assert FREE_TEXT_STATUS_FIELD_BOUNDARIES["route_error"] == frozenset(
        {
            "fallback",
            "fallback_api_key",
            "fallback_base_url",
            "fallback_model",
            "fallback_models",
            "fallback_profile",
            "remote_fallback",
            "warning",
        }
    )
    assert FREE_TEXT_STATUS_FIELD_BOUNDARIES["command"] == frozenset({"apply_command"})


def test_cinnamon_applet_js_parser_matches_python_parser_for_status_edges() -> None:
    lines = [
        'account_memory=Demo path="/tmp/\\" status=broken warning=fake" status=ok warning=real',
        'account_memory=Demo path="/tmp/status=hidden status=broken warning=real',
        'account_memory=Demo message= "hello status=broken warning=real" status=ok warning=retry',
        "structured_decision=demo/telegram status=enabled route_status=unavailable "
        "route_error=provider status=500 fallback=local_ollama fallback_model=llama3 "
        "remote_fallback=enabled warning=retry",
        "llm_route=demo error=provider status=constructor warning=retry",
        "llm_route=demo error=provider status=toString warning=retry",
        "llm_route=demo error=provider status=__proto__ warning=retry",
        "account_memory=Demo message=hello constructor=bad warning=retry",
        "account_memory=Demo message=hello toString=bad warning=retry",
        "account_memory=Demo message=hello __proto__=bad warning=retry",
        "account_identity_warning=Demo code=runtime_channel_without_identity "
        "message=Use option foo=bar only after login. "
        "action=First run /register, then confirm status=ok manually",
        "route_status=UNAVAILABLE status=WARNING semantic=READY",
        "service=demo error=provider status=routable warning=retry",
        "service=demo error=provider status=accepted warning=retry",
        "service=demo error=provider status=queued warning=retry",
        "service=demo error=provider status=skipped warning=retry",
        "service=demo error=provider status=none warning=retry",
        "service=demo error=provider models_feed=empty warning=retry",
        "service=demo error=provider status=partial warning=retry",
    ]

    for line in lines:
        assert _run_js_parse_fields(line) == cinnamon_applet._parse_status_fields(line)

    spaced_quote_line = 'account_memory=Demo message= "hello status=broken warning=real" status=ok warning=retry'
    parsed = cinnamon_applet._parse_status_fields(spaced_quote_line)
    assert parsed["message"] == '"hello status=broken warning=real"'
    assert parsed["status"] == "ok"
    assert parsed["warning"] == "retry"


def test_cinnamon_applet_js_label_maps_do_not_use_prototype_keys() -> None:
    result = _run_js_applet_expression(
        "({status: applet._statusWord('constructor'), kind: applet._codexHistoryKindLabel('constructor')})"
    )

    assert result == {"status": "constructor", "kind": "constructor"}


def test_cinnamon_applet_settings_cover_visible_sections_and_safety() -> None:
    source = (APPLET_DIR / "applet.js").read_text(encoding="utf-8")
    schema = json.loads((APPLET_DIR / "settings-schema.json").read_text(encoding="utf-8"))

    assert schema["layout"]["sections-section"]["keys"] == [
        "show-messenger-section",
        "show-llm-section",
        "show-api-section",
        "show-memory-section",
        "show-bibliothekar-section",
        "show-proactive-section",
        "show-actions-section",
        "show-quick-commands-section",
        "show-project-section",
    ]
    assert schema["confirm-service-actions"]["default"] is True
    assert "native Cinnamon confirmation dialog" in schema["confirm-service-actions"]["tooltip"]
    assert "_confirmServiceAction: function(action, unit, completionCallback)" in source
    assert "new ModalDialog.ModalDialog()" in source
    assert "dialog.contentLayout.add_child(new St.Label" in source
    assert "dialog.setButtons([" in source
    assert "key: Clutter.KEY_Escape" in source
    assert "if (!dialog.open()) {" in source
    assert "Service confirmation dialog could not be opened." in source
    assert '"zenity"' not in source
    assert schema["enable-service-actions"]["default"] is True
    assert schema["terminal-command"]["default"] == ""
    assert "gnome-terminal" in schema["terminal-command"]["tooltip"]
    assert "xterm and konsole use -e" in schema["terminal-command"]["tooltip"]
    assert schema["codex-usage-path"]["default"] == "/home/teladi/codex-usage"
    assert schema["codex-usage-command"]["default"] == "codex-usage"


def test_cinnamon_applet_qdrant_actions_keep_url_local_only() -> None:
    source = (APPLET_DIR / "applet.js").read_text(encoding="utf-8")
    schema = json.loads((APPLET_DIR / "settings-schema.json").read_text(encoding="utf-8"))

    assert schema["qdrant-url"]["default"] == "http://127.0.0.1:6333"
    assert "Must stay local" in schema["qdrant-url"]["tooltip"]
    assert "const ALLOWED_CHANNELS = " in source
    assert "_channels: function()" in source
    assert 'ALLOWED_CHANNELS.indexOf(channel) < 0' in source
    assert "return this._safeLocalHttpUrl(this.qdrantUrl, DEFAULT_QDRANT_URL);" in source
    assert "_safeLocalHttpUrl: function(value, fallback)" in source
    assert '["127.0.0.1", "localhost", "::1"].indexOf(normalizedHost)' in source
    assert "match[5] || match[6]" in source
    assert "port > 0 && port <= 65535" in source
    assert 'this._qdrantUrl() + "/collections"' in source
    assert 'this._qdrantUrl() + "/collections/teebotus_user_memory/points/count"' in source


def test_cinnamon_applet_sanitizes_systemd_units_from_settings() -> None:
    result = _run_js_applet_expression(
        """
        [
          applet._safeSystemdUnit("teebotus.service", "fallback.service"),
          applet._safeSystemdUnit("teebotus-proactive-depressionsbot.timer", "fallback.service"),
          applet._safeSystemdUnit("teebotus@Depressionsbot.service", "fallback.service"),
          applet._safeSystemdUnit("--force", "fallback.service"),
          applet._safeSystemdUnit("../bad.service", "fallback.service"),
          applet._safeSystemdUnit("teebotus", "fallback.service"),
          applet._safeUnitToken("---"),
          applet._safeUnitToken(".."),
          applet._safeUnitToken(" Mondbot!! "),
          applet._safeUnitToken("Bot_der.Wahrheit@prod"),
          applet._safeUnitToken("x".repeat(400)).length,
          (function() {
            applet.runtimeUnit = "--force";
            applet.qdrantUnit = "../qdrant.service";
            applet.pythonCommand = "/usr/bin/python3";
            applet.repoPath = "/repo";
            applet.channels = "telegram,signal";
            applet.qdrantUrl = "http://127.0.0.1:6333";
            applet.statusTimeoutSeconds = 30;
            return applet._statusCommand();
          })()
        ]
        """
    )

    assert result[:11] == [
        "teebotus.service",
        "teebotus-proactive-depressionsbot.timer",
        "teebotus@Depressionsbot.service",
        "fallback.service",
        "fallback.service",
        "fallback.service",
        "depressionsbot",
        "depressionsbot",
        "mondbot",
        "bot_der.wahrheit@prod",
        96,
    ]
    command = result[11]
    assert command[command.index("--unit") + 1] == "teebotus.service"
    assert command[command.index("--qdrant-unit") + 1] == "teebotus-qdrant.service"
    assert "--force" not in command
    assert "../qdrant.service" not in command


def test_cinnamon_applet_sanitizes_status_command_channels_and_qdrant_url() -> None:
    result = _run_js_applet_expression(
        """
        [
          (function() {
            applet.channels = "Signal, telegram, signal, bad, --help, matrix";
            applet.qdrantUrl = "https://example.com:6333";
            applet.runtimeUnit = "teebotus.service";
            applet.qdrantUnit = "teebotus-qdrant.service";
            applet.pythonCommand = "/usr/bin/python3";
            applet.repoPath = "/repo";
            applet.statusTimeoutSeconds = 30;
            return applet._statusCommand();
          })(),
          (function() {
            applet.channels = "bad,--help";
            return applet._channels();
          })(),
          (function() {
            applet.channels = "matrix,telegram,matrix";
            return applet._channels();
          })()
        ]
        """
    )

    command = result[0]
    assert command[command.index("--channels") + 1] == "signal,telegram,matrix"
    assert command[command.index("--qdrant-url") + 1] == "http://127.0.0.1:6333"
    assert "bad" not in command
    assert "--help" not in command
    assert "https://example.com:6333" not in command
    assert result[1] == "telegram,signal"
    assert result[2] == "matrix,telegram"


def test_cinnamon_applet_proactive_command_uses_argv_quoting() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let captured = null;
          applet._openTerminalShell = function(cwd, command) {
            captured = {cwd: cwd, command: command};
          };
          applet.repoPath = "/repo";
          applet.proactiveCommand = "/usr/bin/python3 -m TeeBotus.proactive --instance Depressionsbot ; touch /tmp/teebotus-pwned";
          applet._runProactiveOnce();
          return captured;
        })()
        """
    )

    assert result["cwd"] == "/repo"
    assert "'/usr/bin/python3'" in result["command"]
    assert "';'" in result["command"]
    assert "'touch'" in result["command"]
    assert "'/tmp/teebotus-pwned'" in result["command"]
    assert "; touch /tmp/teebotus-pwned" not in result["command"]


def test_cinnamon_applet_terminal_commands_use_resolved_executables() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let captured = [];
          applet._openTerminalShell = function(cwd, command) {
            captured.push({cwd: cwd, command: command, statusText: applet.statusText || ""});
          };
          applet.repoPath = "/repo";
          applet.codexUsagePath = "/repo/codex-usage";
          applet.codexUsageCommand = "codex-usage";
          applet._setStatusText = function(text) {
            this.statusText = String(text || "");
          };
          applet._openTerminalForCommand("/repo", ["systemctl", "--user", "status", "teebotus.service"]);
          applet._openCodexUsage(["latest"]);
          applet._openTerminalForCommand("/repo", ["missing-tool", "--help"]);
          return {
            captured: captured,
            statusText: applet.statusText
          };
        })()
        """
    )

    assert result["captured"] == [
        {
            "cwd": "/repo",
            "command": "'/usr/bin/systemctl' '--user' 'status' 'teebotus.service'",
            "statusText": "",
        },
        {
            "cwd": "/repo/codex-usage",
            "command": "'/tmp/.local/bin/codex-usage' 'latest'",
            "statusText": "",
        },
    ]
    assert result["statusText"] == "Terminal command unavailable: Error: Command is not in a trusted system path"


def test_cinnamon_applet_terminal_shell_uses_trusted_bash() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let spawned = [];
          applet._spawn = function(argv) {
            spawned.push(argv);
          };
          applet.terminalCommand = "gnome-terminal";
          applet._setStatusText = function(text) {
            this.statusText = String(text || "");
          };
          applet._openTerminalShell("/repo", "'/usr/bin/systemctl' '--user' 'status'");
          return {
            spawned: spawned,
            statusText: applet.statusText || ""
          };
        })()
        """
    )

    assert result["spawned"] == [
        [
            "/usr/bin/gnome-terminal",
            "--",
            "/usr/bin/bash",
            "-lc",
            "cd '/repo' && '/usr/bin/systemctl' '--user' 'status'; printf '\\n'; read -r -p 'Enter zum Schliessen...'",
        ]
    ]
    assert result["statusText"] == ""


def test_cinnamon_applet_terminal_shell_reports_spawn_failures() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let spawned = [];
          applet._spawn = function(argv, callback) {
            spawned.push(argv);
            callback("", "spawn failed", false);
          };
          applet.terminalCommand = "gnome-terminal";
          applet._setStatusText = function(text) {
            this.statusText = String(text || "");
          };
          applet._openTerminalShell("/repo", "'/usr/bin/systemctl' '--user' 'status'");
          return {
            spawned: spawned,
            statusText: applet.statusText || ""
          };
        })()
        """
    )

    assert result["spawned"][0][0] == "/usr/bin/gnome-terminal"
    assert result["statusText"] == "Terminal launch failed: spawn failed"


def test_cinnamon_applet_sanitizes_local_paths_from_settings() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let opened = [];
          applet._spawn = function(argv) {
            opened.push(argv);
          };
          applet.repoPath = "relative/repo";
          applet.libraryPath = "file:///etc/passwd";
          applet.codexUsagePath = "--help";
          let newlinePath = applet._safeLocalPath("/tmp/good\\nbad", "fallback");
          let tabPath = applet._safeLocalPath("/tmp/good\\tbad", "fallback");
          let spacePath = applet._safeLocalPath("/tmp/good path", "fallback");
          applet._openPath(applet._repoPath());
          applet._openPath(applet._libraryPath());
          applet._openPath(applet._codexUsagePath());
          return {
            repo: applet._repoPath(),
            library: applet._libraryPath(),
            codex: applet._codexUsagePath(),
            newlinePath: newlinePath,
            tabPath: tabPath,
            spacePath: spacePath,
            opened: opened
          };
        })()
        """
    )

    assert result["repo"].endswith("/TeeBotus")
    assert result["library"].endswith("/TeeBotus/instances/Depressionsbot/data/Bibliothek")
    assert result["codex"].endswith("/codex-usage")
    assert result["newlinePath"] == "fallback"
    assert result["tabPath"] == "fallback"
    assert result["spacePath"] == "/tmp/good path"
    opened_targets = [entry[2] for entry in result["opened"]]
    assert "relative/repo" not in opened_targets
    assert "file:///etc/passwd" not in opened_targets
    assert "--help" not in opened_targets
    assert all(target.startswith("/") for target in opened_targets)


def test_cinnamon_applet_sanitizes_project_urls_from_settings() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let opened = [];
          applet._spawn = function(argv) {
            opened.push(argv);
          };
          applet.githubUrl = "--help";
          applet.commitsUrl = "file:///etc/passwd";
          let validCommit = applet._safeProjectUrl("https://github.com/H234598/TeeBotus/commit/abcdef", "fallback");
          let foreign = applet._safeProjectUrl("https://example.com/H234598/TeeBotus", "fallback");
          let credential = applet._safeProjectUrl("https://user@github.com/H234598/TeeBotus", "fallback");
          let traversal = applet._safeProjectUrl("https://github.com/H234598/TeeBotus/../../settings/profile", "fallback");
          let encodedTraversal = applet._safeProjectUrl("https://github.com/H234598/TeeBotus/%2e%2e/settings", "fallback");
          let encodedSlash = applet._safeProjectUrl("https://github.com/H234598/TeeBotus/commit%2fabcdef", "fallback");
          let malformedPercent = applet._safeProjectUrl("https://github.com/H234598/TeeBotus/%ZZ", "fallback");
          applet._openUri(applet._githubUrl());
          applet._openUri(applet._commitsUrl());
          return {
            github: applet._githubUrl(),
            commits: applet._commitsUrl(),
            validCommit: validCommit,
            foreign: foreign,
            credential: credential,
            traversal: traversal,
            encodedTraversal: encodedTraversal,
            encodedSlash: encodedSlash,
            malformedPercent: malformedPercent,
            opened: opened
          };
        })()
        """
    )

    assert result["github"] == "https://github.com/H234598/TeeBotus"
    assert result["commits"] == "https://github.com/H234598/TeeBotus/commits/main"
    assert result["validCommit"] == "https://github.com/H234598/TeeBotus/commit/abcdef"
    assert result["foreign"] == "fallback"
    assert result["credential"] == "fallback"
    assert result["traversal"] == "fallback"
    assert result["encodedTraversal"] == "fallback"
    assert result["encodedSlash"] == "fallback"
    assert result["malformedPercent"] == "fallback"
    opened_targets = [entry[2] for entry in result["opened"]]
    assert "--help" not in opened_targets
    assert "file:///etc/passwd" not in opened_targets
    assert opened_targets == [
        "https://github.com/H234598/TeeBotus",
        "https://github.com/H234598/TeeBotus/commits/main",
    ]


def test_cinnamon_applet_reports_open_action_failures() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let statuses = [];
          applet._spawn = function(argv, callback) {
            callback("", argv[0] + " failed", false);
          };
          applet._setStatusText = function(text) {
            statuses.push(String(text || ""));
          };
          applet._openAppletSettings();
          applet._openPath("/repo");
          applet._openUri("https://example.invalid");
          return statuses;
        })()
        """
    )

    assert result == [
        "Settings launch failed: cinnamon-settings failed",
        "Open path failed: gio failed",
        "Open link failed: gio failed",
    ]


def test_cinnamon_applet_sanitizes_executable_settings() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          applet.pythonCommand = "--help";
          applet.codexUsageCommand = "file:///tmp/tool";
          applet.terminalCommand = "--bad-terminal";
          let invalidStatusCommand = applet._statusCommand();
          let invalidCodex = applet._codexUsageArgs();
          let invalidTerminal = applet._terminalArgs();
          applet.pythonCommand = "/tmp/missing-python -B";
          applet.terminalCommand = "/tmp/missing-terminal --";
          let missingAbsoluteStatusCommand = applet._statusCommand();
          let missingAbsoluteTerminal = applet._terminalArgs();
          applet.pythonCommand = "/usr/bin/python3 -c print(1)";
          let dangerousPythonCommand = applet._statusCommand();
          applet.pythonCommand = "/usr/bin/python3 -m other";
          let moduleOverrideCommand = applet._statusCommand();
          applet.pythonCommand = "/usr/bin/python3 -B";
          applet.codexUsageCommand = "codex-usage --profile daily";
          applet.terminalCommand = "xterm -hold";
          let validStatusCommand = applet._statusCommand();
          let validTerminal = applet._terminalArgs();
          applet.terminalCommand = "xterm -hold -e";
          let validTerminalWithFinalMarker = applet._terminalArgs();
          applet.terminalCommand = "gnome-terminal -- bash -lc bad";
          let embeddedCommandTerminal = applet._terminalArgs();
          applet.terminalCommand = "xterm --execute=bad";
          let embeddedExecuteEqualsTerminal = applet._terminalArgs();
          return {
            invalidStatusCommand: invalidStatusCommand,
            invalidCodex: invalidCodex,
            invalidTerminal: invalidTerminal,
            missingAbsoluteStatusCommand: missingAbsoluteStatusCommand,
            missingAbsoluteTerminal: missingAbsoluteTerminal,
            dangerousPythonCommand: dangerousPythonCommand,
            moduleOverrideCommand: moduleOverrideCommand,
            validStatusCommand: validStatusCommand,
            validCodex: applet._codexUsageArgs(),
            validTerminal: validTerminal,
            validTerminalWithFinalMarker: validTerminalWithFinalMarker,
            embeddedCommandTerminal: embeddedCommandTerminal,
            embeddedExecuteEqualsTerminal: embeddedExecuteEqualsTerminal,
            unsafeChecks: [
              applet._isSafeExecutable("--help"),
              applet._isSafeExecutable("file:///tmp/tool"),
              applet._isSafeExecutable("../python"),
              applet._isSafeExecutable("/tmp/missing-python"),
              applet._isSafeExecutable("/usr/bin/python3"),
              applet._isSafeExecutable("python3")
            ]
          };
        })()
        """
    )

    assert result["invalidStatusCommand"][0] == "/tmp/TeeBotus/.venv-py313/bin/python"
    assert result["invalidStatusCommand"][result["invalidStatusCommand"].index("--python") + 1] == "'/tmp/TeeBotus/.venv-py313/bin/python'"
    assert result["invalidCodex"] == ["codex-usage"]
    assert result["invalidTerminal"] == ["/usr/bin/gnome-terminal", "--"]
    assert result["missingAbsoluteStatusCommand"][0] == "/tmp/TeeBotus/.venv-py313/bin/python"
    assert "/tmp/missing-python" not in result["missingAbsoluteStatusCommand"]
    assert result["missingAbsoluteTerminal"] == ["/usr/bin/gnome-terminal", "--"]
    assert result["dangerousPythonCommand"][0] == "/tmp/TeeBotus/.venv-py313/bin/python"
    assert "-c" not in result["dangerousPythonCommand"]
    assert "print(1)" not in result["dangerousPythonCommand"]
    assert result["moduleOverrideCommand"][0] == "/tmp/TeeBotus/.venv-py313/bin/python"
    assert "other" not in result["moduleOverrideCommand"]
    assert result["validStatusCommand"][:2] == ["/usr/bin/python3", "-B"]
    assert result["validStatusCommand"][result["validStatusCommand"].index("--python") + 1] == "'/usr/bin/python3' '-B'"
    assert result["validCodex"] == ["codex-usage", "--profile", "daily"]
    assert result["validTerminal"] == ["/usr/bin/xterm", "-hold", "-e"]
    assert result["validTerminalWithFinalMarker"] == ["/usr/bin/xterm", "-hold", "-e"]
    assert result["embeddedCommandTerminal"] == ["/usr/bin/gnome-terminal", "--"]
    assert result["embeddedExecuteEqualsTerminal"] == ["/usr/bin/gnome-terminal", "--"]
    assert result["unsafeChecks"] == [False, False, False, False, True, True]


def test_cinnamon_applet_resolves_spawn_commands_to_trusted_paths() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let missingError = "";
          let controlError = "";
          let tooManyError = "";
          let tooLargeArgError = "";
          let tooLargeCommandError = "";
          let userLocalDisallowedError = "";
          let absoluteUserLocalDisallowedError = "";
          let prototypeDisallowedError = "";
          let manyArgs = ["gnome-terminal"];
          for (let index = 0; index < 128; index++) {
            manyArgs.push("x");
          }
          let totalArgs = ["gnome-terminal"];
          for (let index = 0; index < 40; index++) {
            totalArgs.push("x".repeat(1000));
          }
          try {
            applet._resolveSpawnArgv(["unknown-tool", "--help"]);
          } catch (err) {
            missingError = String(err);
          }
          try {
            applet._resolveSpawnArgv(["gnome-terminal", "bad\\narg"]);
          } catch (err) {
            controlError = String(err);
          }
          try {
            applet._resolveSpawnArgv(manyArgs);
          } catch (err) {
            tooManyError = String(err);
          }
          try {
            applet._resolveSpawnArgv(["gnome-terminal", "x".repeat(4097)]);
          } catch (err) {
            tooLargeArgError = String(err);
          }
          try {
            applet._resolveSpawnArgv(totalArgs);
          } catch (err) {
            tooLargeCommandError = String(err);
          }
          try {
            applet._resolveSpawnArgv(["custom-tool"]);
          } catch (err) {
            userLocalDisallowedError = String(err);
          }
          try {
            applet._resolveSpawnArgv(["/tmp/.local/bin/custom-tool"]);
          } catch (err) {
            absoluteUserLocalDisallowedError = String(err);
          }
          try {
            applet._resolveSpawnArgv(["constructor"]);
          } catch (err) {
            prototypeDisallowedError = String(err);
          }
          return {
            bare: applet._resolveSpawnArgv(["gnome-terminal", "--"]),
            absolute: applet._resolveSpawnArgv(["/usr/bin/python3", "-m", "TeeBotus"]),
            trustedBare: applet._trustedExecutablePath("gnome-terminal"),
            userLocalBare: applet._trustedExecutablePath("codex-usage"),
            userLocalAbsolute: applet._trustedExecutablePath("/tmp/.local/bin/codex-usage"),
            userLocalDisallowedBare: applet._trustedExecutablePath("custom-tool"),
            userLocalDisallowedAbsolute: applet._trustedExecutablePath("/tmp/.local/bin/custom-tool"),
            prototypeDisallowedBare: applet._trustedExecutablePath("constructor"),
            prototypeDisallowedAbsolute: applet._trustedExecutablePath("/tmp/.local/bin/constructor"),
            shellBare: applet._trustedExecutablePath("bash"),
            trustedAbsolute: applet._trustedExecutablePath("/usr/bin/python3"),
            venvAbsolute: applet._trustedExecutablePath("/tmp/TeeBotus/.venv-py313/bin/python"),
            missingAbsolute: applet._trustedExecutablePath("/tmp/missing-python"),
            trusted: applet._findTrustedProgramInPath("gnome-terminal"),
            unsafeName: applet._findTrustedProgramInPath("../gnome-terminal"),
            missingError: missingError,
            controlError: controlError,
            tooManyError: tooManyError,
            tooLargeArgError: tooLargeArgError,
            tooLargeCommandError: tooLargeCommandError,
            userLocalDisallowedError: userLocalDisallowedError,
            absoluteUserLocalDisallowedError: absoluteUserLocalDisallowedError,
            prototypeDisallowedError: prototypeDisallowedError
          };
        })()
        """
    )

    assert result == {
        "bare": ["/usr/bin/gnome-terminal", "--"],
        "absolute": ["/usr/bin/python3", "-m", "TeeBotus"],
        "trustedBare": "/usr/bin/gnome-terminal",
        "userLocalBare": "/tmp/.local/bin/codex-usage",
        "userLocalAbsolute": "/tmp/.local/bin/codex-usage",
        "userLocalDisallowedBare": None,
        "userLocalDisallowedAbsolute": None,
        "prototypeDisallowedBare": None,
        "prototypeDisallowedAbsolute": None,
        "shellBare": "/usr/bin/bash",
        "trustedAbsolute": "/usr/bin/python3",
        "venvAbsolute": "/tmp/TeeBotus/.venv-py313/bin/python",
        "missingAbsolute": None,
        "trusted": "/usr/bin/gnome-terminal",
        "unsafeName": None,
        "missingError": "Error: Command is not in a trusted system path",
        "controlError": "Error: Command argument contains invalid control character",
        "tooManyError": "Error: Too many command arguments",
        "tooLargeArgError": "Error: Command argument is too large",
        "tooLargeCommandError": "Error: Command is too large",
        "userLocalDisallowedError": "Error: Command is not in a trusted system path",
        "absoluteUserLocalDisallowedError": "Error: Command is not in a trusted system path",
        "prototypeDisallowedError": "Error: Command is not in a trusted system path",
    }


def test_cinnamon_applet_bounds_configured_command_arguments() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let manyArgs = ["codex-usage"];
          for (let index = 0; index < 129; index++) {
            manyArgs.push("x");
          }
          let totalArgs = ["codex-usage"];
          for (let index = 0; index < 40; index++) {
            totalArgs.push("x".repeat(1000));
          }
          return {
            tooLong: applet._safeExecutableArgs("codex-usage " + "x".repeat(4097), ["codex-usage"]),
            tooMany: applet._safeExecutableArgs(manyArgs.join(" "), ["codex-usage"]),
            tooLarge: applet._safeExecutableArgs(totalArgs.join(" "), ["codex-usage"]),
            controlChar: applet._safeExecutableArgs("codex-usage bad\\\\narg", ["codex-usage"]),
            newline: applet._safeExecutableArgs("codex-usage bad\\narg", ["codex-usage"]),
            valid: applet._safeExecutableArgs("codex-usage latest --format json", ["codex-usage"])
          };
        })()
        """
    )

    assert result == {
        "tooLong": ["codex-usage"],
        "tooMany": ["codex-usage"],
        "tooLarge": ["codex-usage"],
        "controlChar": ["codex-usage"],
        "newline": ["codex-usage"],
        "valid": ["codex-usage", "latest", "--format", "json"],
    }


def test_cinnamon_applet_rejects_partial_integer_settings() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          applet.statusTimeoutSeconds = "30abc";
          let malformedSummary = applet._statusSummary({
            ok: false,
            unit: { active_state: "active" },
            health: {
              status: "warning",
              total_problem_count: "1abc",
              command_problem_count: "2abc",
              qdrant_runtime_problem_count: "3abc",
              qdrant_probe_problem_count: "4",
              problem_statuses: "warning:5abc,broken:6"
            },
            runtime: {
              summary: {
                instances: "1",
                channels: "telegram",
                problem_status_count: "7abc"
              },
              status_counts: {
                warning: "8abc",
                broken: "9"
              }
            },
            qdrant: {
              collections: {
                teebotus_user_memory: { count: "10abc" }
              }
            }
          });
          return {
            positiveJunk: applet._positiveInt("12abc", 7),
            positiveFloat: applet._positiveInt("12.9", 7),
            positiveValid: applet._positiveInt("0012", 7),
            nonNegativeJunk: applet._nonNegativeInt("0abc", 5),
            nonNegativeValid: applet._nonNegativeInt("0", 5),
            boundedJunk: applet._boundedInt("30abc", 10, 1, 60),
            boundedFloat: applet._boundedInt("30.9", 10, 1, 60),
            boundedValid: applet._boundedInt("0030", 10, 1, 60),
            hugeInteger: applet._nonNegativeInt("999999999999999999999999999999", 5),
            timeoutJunk: applet._statusTimeoutSeconds(),
            staleJunk: applet._codexUsageIsStale({ codex_usage: "local", stale_hours: "48abc" }),
            staleValid: applet._codexUsageIsStale({ codex_usage: "local", stale_hours: "48" }),
            malformedSummary: malformedSummary
          };
        })()
        """
    )

    assert result == {
        "positiveJunk": 7,
        "positiveFloat": 7,
        "positiveValid": 12,
        "nonNegativeJunk": 5,
        "nonNegativeValid": 0,
        "boundedJunk": 10,
        "boundedFloat": 10,
        "boundedValid": 30,
        "hugeInteger": 5,
        "timeoutJunk": 30,
        "staleJunk": False,
        "staleValid": True,
        "malformedSummary": (
            "Warnungen 13 | Probleme defekt:6 | Qdrant Probe:4 | Health Warnung | Unit active | 1 | telegram"
        ),
    }


def test_cinnamon_applet_status_refresh_uses_bounded_spawn_timeout() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let captured = null;
          applet.statusTimeoutSeconds = 999999;
          applet.repoPath = "/repo";
          applet._setPanelState = function() {};
          applet._buildMenu = function() {};
          applet._updatePanel = function() {};
          applet._spawn = function(argv, callback, cwd, options) {
            captured = {argv: argv, cwd: cwd, options: options, runningBeforeCallback: applet.statusRunning};
            callback(JSON.stringify({ok: true, command_ok: true, repo: {}, unit: {active_state: "active", sub_state: "running", returncode: 0}, health: {status: "ok", command_ok: true}, qdrant: {unit: {active_state: "active", sub_state: "running", returncode: 0}, collections: {teebotus_user_memory: {status: "ready", count: 0}, teebotus_bibliothekar_chunks: {status: "ready", count: 0}}}, runtime: {returncode: 0, sections: {}, summary: {}, status_counts: {}}}), "", true);
          };
          applet._refreshStatus();
          return {
            captured: captured,
            runningAfterCallback: applet.statusRunning,
            statusText: applet.statusText
          };
        })()
        """
    )

    command = result["captured"]["argv"]
    assert command[command.index("--timeout") + 1] == "300"
    assert result["captured"]["cwd"] == "/repo"
    assert result["captured"]["options"]["timeoutMs"] == 335000
    assert result["captured"]["runningBeforeCallback"] is True
    assert result["runningAfterCallback"] is False
    assert result["statusText"].startswith("Health")


def test_cinnamon_applet_rejects_isolated_python_mode_for_repo_module_commands() -> None:
    result = _run_js_applet_expression(
        "({isolated: applet._safePythonArgs('/usr/bin/python3 -I', ['/usr/bin/python3']), "
        "noSite: applet._safePythonArgs('/usr/bin/python3 -S', ['/usr/bin/python3']), "
        "noUserSite: applet._safePythonArgs('/usr/bin/python3 -s', ['/usr/bin/python3'])})"
    )

    assert result == {
        "isolated": ["/usr/bin/python3"],
        "noSite": ["/usr/bin/python3"],
        "noUserSite": ["/usr/bin/python3"],
    }


def test_cinnamon_applet_status_refresh_rejects_non_object_json() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          applet.statusTimeoutSeconds = 30;
          applet.repoPath = "/repo";
          applet._setPanelState = function() {};
          applet._buildMenu = function() {};
          applet._updatePanel = function() {};
          applet._spawn = function(argv, callback, cwd, options) {
            callback("null", "", true);
          };
          applet._refreshStatus();
          return {
            running: applet.statusRunning,
            statusPayload: applet.statusPayload,
            statusText: applet.statusText,
            lastError: applet.lastError
          };
        })()
        """
    )

    assert result["running"] is False
    assert result["statusPayload"] is None
    assert result["statusText"] == "Statusfehler: Invalid JSON object from helper"
    assert result["lastError"] == "Invalid JSON object from helper"


def test_cinnamon_applet_status_refresh_rejects_large_json_output() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          applet.statusTimeoutSeconds = 30;
          applet.repoPath = "/repo";
          applet._setPanelState = function() {};
          applet._buildMenu = function() {};
          applet._updatePanel = function() {};
          applet._spawn = function(argv, callback, cwd, options) {
            callback(" ".repeat(1000001), "", true);
          };
          applet._refreshStatus();
          return {
            running: applet.statusRunning,
            statusPayload: applet.statusPayload,
            statusText: applet.statusText,
            lastError: applet.lastError
          };
        })()
        """
    )

    assert result["running"] is False
    assert result["statusPayload"] is None
    assert result["statusText"] == "Statusfehler: Helper JSON output too large"
    assert result["lastError"] == "Helper JSON output too large"


def test_cinnamon_applet_gio_spawn_bounds_stdout_and_stderr() -> None:
    result = _run_gjs_spawn_smoke()

    assert result == {"ok": False, "stdout": 0, "stderr": 7, "error": "bounded"}


def test_cinnamon_applet_gio_spawn_stops_after_output_overflow() -> None:
    result = _run_gjs_spawn_smoke(child_code="import sys,time; sys.stdout.write('x'*4096); sys.stdout.flush(); time.sleep(30)")

    assert result == {"ok": False, "stdout": 0, "stderr": 7, "error": "bounded"}


def test_cinnamon_applet_gio_spawn_reports_success_query_failure() -> None:
    result = _run_gjs_spawn_success_query_failure_smoke()

    assert result["ok"] is False
    assert result["stdout"] == ""
    assert "success query failed" in result["stderr"]


def test_cinnamon_applet_status_refresh_accepts_escaped_payload_within_bound() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let result = {};
          let payload = {
            ok: false,
            command_ok: true,
            repo: {},
            unit: {active_state: "active", sub_state: "running", returncode: 0},
            health: {status: "warning", command_ok: true},
            qdrant: {
              unit: {active_state: "active", sub_state: "running", returncode: 0},
              collections: {}
            },
            runtime: {
              returncode: 0,
              sections: {Diagnose: [String.fromCharCode(92).repeat(70000)]},
              summary: {},
              status_counts: {}
            }
          };
          applet._spawn = function(argv, callback, cwd, options) {
            let text = JSON.stringify(payload);
            result.size = text.length;
            callback(text, "", true);
          };
          applet._spawnJson([], function(value, error) {
            result.accepted = Boolean(value);
            result.error = error;
          });
          return result;
        })()
        """
    )

    assert result["size"] > 120000
    assert result["size"] < 1000000
    assert result["accepted"] is True
    assert result["error"] is None


def test_cinnamon_applet_menu_text_is_bounded() -> None:
    result = _run_js_applet_expression("applet._shortText('x'.repeat(5000), 2000)")

    assert len(result) == 2000
    assert result.endswith("…")


def test_cinnamon_applet_panel_status_summary_is_bounded() -> None:
    result = _run_js_applet_expression(
        "applet._statusSummary({ok: true, unit: {active_state: 'active'}, health: {status: 'ok'}, runtime: {summary: {instances: 'x'.repeat(5000), channels: 'telegram'}, status_counts: {}}, qdrant: {collections: {}}})"
    )

    assert len(result) <= 500
    assert "…" in result


def test_cinnamon_applet_optional_history_dispatcher_mirror_is_wired() -> None:
    source = (APPLET_DIR / "applet.js").read_text(encoding="utf-8")
    schema = json.loads((APPLET_DIR / "settings-schema.json").read_text(encoding="utf-8"))
    assert schema["show-history-dispatcher-section"]["default"] is False
    assert "history-dispatcher-section" in schema["layout"]["main-page"]["sections"]
    assert "historyDispatcherPayload" in source
    assert "_refreshHistoryDispatcherStatus" in source
    assert "_runHistoryDispatcherConfigApply" in source
    assert "_confirmHistoryDispatcherDelete" in source
    assert "load_contents_async" in source
    assert "spawn_sync" not in source


def test_cinnamon_applet_status_refresh_keeps_previous_payload_on_error() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          applet.statusTimeoutSeconds = 30;
          applet.repoPath = "/repo";
          applet.statusPayload = {
            version: "1.2.3",
            repo: { short_commit: "abc1234" },
            unit: { active_state: "active", sub_state: "running" },
            health: {
              status: "warning",
              runtime_problem_count: 2,
              problem_statuses: "warning:2",
              command_problem_count: 0,
              qdrant_problem_count: 0,
              qdrant_probe_problem_count: 0,
              qdrant_unit_problem_count: 0,
              qdrant_runtime_problem_count: 0,
              total_problem_count: 2
            },
            runtime: {
              summary: {
                instances: "Demo",
                channels: "telegram",
                problem_status_count: 2,
                problem_statuses: "warning:2",
                llm_routes: 0
              },
              status_counts: { warning: 2 }
            }
          };
          applet._setPanelState = function() {};
          applet._buildMenu = function() {};
          applet._updatePanel = function() {};
          applet._spawnJson = function(_argv, callback) {
            callback(null, "timeout");
          };
          applet._refreshStatus();
          return {
            statusPayload: applet.statusPayload,
            statusText: applet.statusText,
            lastError: applet.lastError
          };
        })()
        """
    )

    assert result["statusPayload"]["health"]["runtime_problem_count"] == 2
    assert "Warnungen 2" in result["statusText"]
    assert "Statusfehler: timeout" in result["statusText"]
    assert result["lastError"] == "timeout"


def test_cinnamon_applet_status_displays_runtime_diagnostics() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let payload = {
            ok: false,
            version: "1.2.3",
            repo: {short_commit: "abc1234"},
            unit: {active_state: "active", sub_state: "running"},
            health: {status: "broken", command_problem_count: 1},
            qdrant: {collections: {}},
            runtime: {
              returncode: 124,
              stderr: "TimeoutExpired: command timed out after 10 seconds",
              summary: {instances: "Demo", channels: "telegram"},
              status_counts: {},
              sections: {}
            }
          };
          return {
            summary: applet._statusSummary(payload),
            details: applet._statusDetailLines(payload)
          };
        })()
        """
    )

    assert "Runtime Returncode 124" in result["summary"]
    assert "TimeoutExpired" in result["summary"]
    assert "Runtime Returncode 124" in result["details"][-1]
    assert "TimeoutExpired" in result["details"][-1]


def test_cinnamon_applet_status_refresh_queues_changes_while_running() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let calls = [];
          applet.statusTimeoutSeconds = 30;
          applet.repoPath = "/old-repo";
          applet._setPanelState = function() {};
          applet._buildMenu = function() {};
          applet._updatePanel = function() {};
          applet._spawn = function(argv, callback, cwd, options) {
            calls.push({argv: argv, cwd: cwd, pending: applet.statusRefreshPending});
            if (calls.length === 1) {
              applet.repoPath = "/new-repo";
              applet._refreshStatus();
            }
            callback(JSON.stringify({ok: true, command_ok: true, repo: {}, unit: {active_state: "active", sub_state: "running", returncode: 0}, health: {status: "ok", command_ok: true}, qdrant: {unit: {active_state: "active", sub_state: "running", returncode: 0}, collections: {teebotus_user_memory: {status: "ready", count: 0}, teebotus_bibliothekar_chunks: {status: "ready", count: 0}}}, runtime: {returncode: 0, sections: {}, summary: {}, status_counts: {}}}), "", true);
          };
          applet._refreshStatus();
          return {
            calls: calls,
            running: applet.statusRunning,
            pending: applet.statusRefreshPending
          };
        })()
        """
    )

    assert len(result["calls"]) == 2
    assert result["calls"][0]["cwd"] == "/old-repo"
    assert result["calls"][0]["pending"] is False
    assert result["calls"][1]["cwd"] == "/new-repo"
    second_command = result["calls"][1]["argv"]
    assert second_command[second_command.index("--repo-root") + 1] == "/new-repo"
    assert result["running"] is False
    assert result["pending"] is False


def test_cinnamon_applet_status_refresh_rejects_structurally_invalid_payload() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          applet.statusTimeoutSeconds = 30;
          applet.repoPath = "/repo";
          applet._setPanelState = function() {};
          applet._buildMenu = function() {};
          applet._updatePanel = function() {};
          applet._spawn = function(argv, callback, cwd, options) {
            callback(JSON.stringify({ok: true, repo: {}, unit: {}, health: {}, qdrant: {collections: {}}, runtime: {sections: [], summary: {}, status_counts: {}}}), "", true);
          };
          applet._refreshStatus();
          return {
            running: applet.statusRunning,
            statusPayload: applet.statusPayload,
            statusText: applet.statusText,
            lastError: applet.lastError
          };
        })()
        """
    )

    assert result["running"] is False
    assert result["statusPayload"] is None
    assert result["statusText"] == "Statusfehler: Invalid status payload from helper"
    assert result["lastError"] == "Invalid status payload from helper"


def test_cinnamon_applet_status_payload_requires_boolean_ok() -> None:
    result = _run_js_applet_expression(
        "applet._isStatusPayload({ok: 'false', repo: {}, unit: {}, health: {}, qdrant: {collections: {}}, runtime: {sections: {}, summary: {}, status_counts: {}}})"
    )

    assert result is False


def test_cinnamon_applet_status_payload_requires_health_status_and_consistent_ok() -> None:
    missing_status = _run_js_applet_expression(
        "applet._isStatusPayload({ok: true, repo: {}, unit: {}, health: {}, qdrant: {collections: {}}, runtime: {sections: {}, summary: {}, status_counts: {}}})"
    )
    inconsistent_status = _run_js_applet_expression(
        "applet._isStatusPayload({ok: true, repo: {}, unit: {}, health: {status: 'broken'}, qdrant: {collections: {}}, runtime: {sections: {}, summary: {}, status_counts: {}}})"
    )

    assert missing_status is False
    assert inconsistent_status is False


def test_cinnamon_applet_status_payload_requires_consistent_command_status() -> None:
    missing_command = _run_js_applet_expression(
        "applet._isStatusPayload({ok: true, repo: {}, unit: {}, health: {status: 'ok'}, qdrant: {collections: {}}, runtime: {sections: {}, summary: {}, status_counts: {}}})"
    )
    mismatched_command = _run_js_applet_expression(
        "applet._isStatusPayload({ok: true, command_ok: false, repo: {}, unit: {}, health: {status: 'ok', command_ok: true}, qdrant: {collections: {}}, runtime: {sections: {}, summary: {}, status_counts: {}}})"
    )
    failed_ok = _run_js_applet_expression(
        "applet._isStatusPayload({ok: true, command_ok: false, repo: {}, unit: {}, health: {status: 'ok', command_ok: false}, qdrant: {collections: {}}, runtime: {sections: {}, summary: {}, status_counts: {}}})"
    )

    assert missing_command is False
    assert mismatched_command is False
    assert failed_ok is False


def test_cinnamon_applet_status_payload_requires_healthy_unit_for_health_ok() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let payload = {
            ok: true,
            command_ok: true,
            repo: {},
            unit: {active_state: "active", sub_state: "running", returncode: 0},
            health: {status: "ok", command_ok: true},
            qdrant: {collections: {
              teebotus_user_memory: {status: "ready", count: 0},
              teebotus_bibliothekar_chunks: {status: "ready", count: 0}
            }, unit: {active_state: "active", sub_state: "running", returncode: 0}},
            runtime: {returncode: 0, sections: {}, summary: {}, status_counts: {}}
          };
          let healthy = applet._isStatusPayload(payload);
          payload.unit = {active_state: "failed", sub_state: "failed", returncode: 0};
          let failed = applet._isStatusPayload(payload);
          payload.unit = {active_state: "active", sub_state: "typo", returncode: 0};
          let unknown = applet._isStatusPayload(payload);
          payload.unit = {active_state: "active", sub_state: "running", returncode: 1};
          let failedReturncode = applet._isStatusPayload(payload);
          payload.unit = {active_state: "active", sub_state: "running", returncode: 0};
          payload.qdrant.unit = {active_state: "failed", sub_state: "failed", returncode: 0};
          let failedQdrant = applet._isStatusPayload(payload);
          payload.qdrant.unit = {active_state: "active", sub_state: "running", returncode: 0};
          payload.runtime.returncode = 1;
          let failedRuntime = applet._isStatusPayload(payload);
          return {healthy: healthy, failed: failed, unknown: unknown, failedReturncode: failedReturncode, failedQdrant: failedQdrant, failedRuntime: failedRuntime};
        })()
        """
    )

    assert result == {"healthy": True, "failed": False, "unknown": False, "failedReturncode": False, "failedQdrant": False, "failedRuntime": False}


def test_cinnamon_applet_status_payload_requires_ready_qdrant_collections_for_health_ok() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let payload = {
            ok: true,
            command_ok: true,
            repo: {},
            unit: {active_state: "active", sub_state: "running", returncode: 0},
            health: {status: "ok", command_ok: true},
            qdrant: {collections: {
              teebotus_user_memory: {status: "ready", count: 0},
              teebotus_bibliothekar_chunks: {status: "ready", count: 0}
            }, unit: {active_state: "active", sub_state: "running", returncode: 0}},
            runtime: {returncode: 0, sections: {}, summary: {}, status_counts: {}}
          };
          let healthy = applet._isStatusPayload(payload);
          payload.qdrant.collections.teebotus_user_memory.error = "probe failed";
          let collectionError = applet._isStatusPayload(payload);
          payload.qdrant.collections.teebotus_user_memory.error = "";
          payload.qdrant.error = "probe failed";
          let error = applet._isStatusPayload(payload);
          payload.qdrant.error = "";
          payload.qdrant.collections.teebotus_user_memory.status = "unreachable";
          let failed = applet._isStatusPayload(payload);
          delete payload.qdrant.collections.teebotus_user_memory;
          let missing = applet._isStatusPayload(payload);
          payload.qdrant.collections.teebotus_user_memory = {status: "ready", count: 0};
          payload.runtime.summary.output_truncated = true;
          let truncated = applet._isStatusPayload(payload);
          return {healthy: healthy, collectionError: collectionError, error: error, failed: failed, missing: missing, truncated: truncated};
        })()
        """
    )

    assert result == {"healthy": True, "collectionError": False, "error": False, "failed": False, "missing": False, "truncated": False}


def test_cinnamon_applet_status_payload_rejects_ok_with_problem_counts() -> None:
    explicit_total = _run_js_applet_expression(
        "applet._isStatusPayload({ok: true, repo: {}, unit: {}, health: {status: 'ok', total_problem_count: 1}, qdrant: {collections: {}}, runtime: {sections: {}, summary: {}, status_counts: {}}})"
    )
    runtime_count = _run_js_applet_expression(
        "applet._isStatusPayload({ok: true, repo: {}, unit: {}, health: {status: 'ok'}, qdrant: {collections: {}}, runtime: {sections: {}, summary: {}, status_counts: {broken: 1}}})"
    )
    status_text = _run_js_applet_expression(
        "applet._isStatusPayload({ok: true, command_ok: true, repo: {}, unit: {active_state: 'active', sub_state: 'running', returncode: 0}, health: {status: 'ok', command_ok: true, problem_statuses: 'broken:1'}, qdrant: {unit: {active_state: 'active', sub_state: 'running', returncode: 0}, collections: {teebotus_user_memory: {status: 'ready', count: 0}, teebotus_bibliothekar_chunks: {status: 'ready', count: 0}}}, runtime: {returncode: 0, sections: {}, summary: {}, status_counts: {}}})"
    )

    assert explicit_total is False
    assert runtime_count is False
    assert status_text is False


def test_cinnamon_applet_status_payload_rejects_invalid_health_status() -> None:
    result = _run_js_applet_expression(
        "applet._isStatusPayload({ok: true, repo: {}, unit: {}, health: {status: 'false'}, qdrant: {collections: {}}, runtime: {sections: {}, summary: {}, status_counts: {}}})"
    )

    assert result is False


def test_cinnamon_applet_removal_terminates_running_helpers() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let forced = 0;
          applet.menu = null;
          applet.statusTimer = 0;
          applet.spawnGeneration = 0;
          applet.spawnProcesses = [
            {get_if_exited: function() { return false; }, force_exit: function() { forced += 1; }},
            {get_if_exited: function() { return true; }, force_exit: function() { forced += 1; }}
          ];
          applet.on_applet_removed_from_panel();
          return {
            forced: forced,
            remaining: applet.spawnProcesses.length,
            removed: applet.appletRemoved,
            generation: applet.spawnGeneration
          };
        })()
        """
    )

    assert result == {"forced": 1, "remaining": 0, "removed": True, "generation": 1}


def test_cinnamon_applet_refreshes_existing_menu_in_place() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let calls = [];
          applet.menu = {};
          applet.statusMenu = {};
          applet.runtimeMenu = {};
          applet.historyDispatcherMenu = {};
          applet.messengerMenu = {};
          applet.llmMenu = {};
          applet.apiMenu = {};
          applet.memoryMenu = {};
          applet.bibliothekarMenu = {};
          applet.proactiveMenu = {};
          applet.actionsMenu = {};
          applet.quickCommandsMenu = {};
          applet.projectMenu = {};
          applet._populateStaticMenus = function() { calls.push("static"); };
          applet._populateDynamicMenus = function() { calls.push("dynamic"); };
          applet._updateHeader = function() { calls.push("header"); };
          applet._buildMenu = function() { calls.push("rebuild"); };
          applet._refreshMenuContents();
          return calls;
        })()
        """
    )

    assert result == ["static", "dynamic", "header"]


def test_cinnamon_applet_dispatcher_last_error_is_not_reported_ready() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let lines = [];
          applet.historyDispatcherMenu = {menu: {
            removeAll: function() {},
            addMenuItem: function(item) { lines.push(item); }
          }};
          applet.historyDispatcherPayload = {
            schema_version: 1,
            ok: true,
            generated_at: new Date().toISOString(),
            last_error: "dispatch failed",
            queued: 0,
            total: 1,
            collector: {},
            dispatch: {}
          };
          applet.historyDispatcherError = "";
          applet._menuLine = function(text) { return String(text); };
          applet._shortText = function(text) { return String(text); };
          applet._populateHistoryDispatcherMenu();
          return lines;
        })()
        """
    )

    assert result[0] == "Status: Warnung"
    assert "Letzter Fehler: dispatch failed" in result


def test_cinnamon_applet_dispatcher_snapshot_read_error_is_not_reported_ready() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let lines = [];
          applet.historyDispatcherMenu = {menu: {
            removeAll: function() {},
            addMenuItem: function(item) { lines.push(item); }
          }};
          applet.historyDispatcherPayload = {
            schema_version: 1,
            ok: true,
            generated_at: new Date().toISOString(),
            queued: 0,
            total: 0,
            collector: {},
            dispatch: {}
          };
          applet.historyDispatcherError = "Ungültiger Dispatcher-Snapshot";
          applet._menuLine = function(text) { return String(text); };
          applet._shortText = function(text) { return String(text); };
          applet._populateHistoryDispatcherMenu();
          return lines;
        })()
        """
    )

    assert result[0] == "Status: Warnung"
    assert "Ungültiger Dispatcher-Snapshot" in result


def test_cinnamon_applet_dispatcher_malformed_ok_is_not_reported_ready() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let lines = [];
          applet.historyDispatcherMenu = {menu: {
            removeAll: function() {},
            addMenuItem: function(item) { lines.push(item); }
          }};
          applet.historyDispatcherPayload = {
            schema_version: 1,
            ok: "false",
            generated_at: new Date().toISOString(),
            queued: 0,
            total: 0,
            collector: {},
            dispatch: {}
          };
          applet.historyDispatcherError = "";
          applet._menuLine = function(text) { return String(text); };
          applet._shortText = function(text) { return String(text); };
          applet._populateHistoryDispatcherMenu();
          return lines;
        })()
        """
    )

    assert result[0] == "Status: Warnung"


def test_cinnamon_applet_dispatcher_future_timestamp_is_not_reported_ready() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let lines = [];
          applet.historyDispatcherMenu = {menu: {
            removeAll: function() {},
            addMenuItem: function(item) { lines.push(item); }
          }};
          applet.historyDispatcherPayload = {
            schema_version: 1,
            ok: true,
            generated_at: new Date(Date.now() + 2 * 60 * 60 * 1000).toISOString(),
            queued: 0,
            total: 0,
            collector: {},
            dispatch: {}
          };
          applet.historyDispatcherError = "";
          applet._menuLine = function(text) { return String(text); };
          applet._shortText = function(text) { return String(text); };
          applet._populateHistoryDispatcherMenu();
          return lines;
        })()
        """
    )

    assert result[0] == "Status: Warnung"


def test_cinnamon_applet_dispatcher_malformed_sections_are_not_reported_ready() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let lines = [];
          applet.historyDispatcherMenu = {menu: {
            removeAll: function() {},
            addMenuItem: function(item) { lines.push(item); }
          }};
          applet.historyDispatcherPayload = {
            schema_version: 1,
            ok: true,
            generated_at: new Date().toISOString(),
            queued: 0,
            total: 0,
            collector: "broken",
            dispatch: [],
            queue_preview: []
          };
          applet.historyDispatcherError = "";
          applet._menuLine = function(text) { return String(text); };
          applet._shortText = function(text) { return String(text); };
          applet._populateHistoryDispatcherMenu();
          return lines;
        })()
        """
    )

    assert result[0] == "Status: Warnung"


def test_cinnamon_applet_dispatcher_string_booleans_are_not_reported_ready() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let lines = [];
          applet.historyDispatcherMenu = {menu: {
            removeAll: function() {},
            addMenuItem: function(item) { lines.push(item); }
          }};
          applet.historyDispatcherPayload = {
            schema_version: 1,
            ok: true,
            generated_at: new Date().toISOString(),
            queued: 0,
            total: 0,
            collector: {enabled: "false", sources: 0},
            dispatch: {enabled: true, paused: "false"},
            queue_preview: []
          };
          applet.historyDispatcherError = "";
          applet._menuLine = function(text) { return String(text); };
          applet._shortText = function(text) { return String(text); };
          applet._populateHistoryDispatcherMenu();
          return lines;
        })()
        """
    )

    assert result[0] == "Status: Warnung"


def test_cinnamon_applet_dispatcher_refresh_queues_while_read_is_running() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          applet.showHistoryDispatcherSection = true;
          applet.appletRemoved = false;
          applet.historyDispatcherRunning = true;
          applet.historyDispatcherRefreshPending = false;
          applet._refreshHistoryDispatcherStatus();
          return applet.historyDispatcherRefreshPending;
        })()
        """
    )

    assert result is True


def test_cinnamon_applet_top_health_includes_dispatcher_warning() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let values = {};
          applet.showHistoryDispatcherSection = true;
          applet.historyDispatcherPayload = {
            schema_version: 1,
            ok: true,
            generated_at: new Date().toISOString(),
            last_error: "dispatch failed",
            queued: 0,
            total: 1,
            collector: {enabled: true, sources: 1},
            dispatch: {enabled: true, paused: false},
            queue_preview: []
          };
          applet.historyDispatcherError = "";
          applet.statusPayload = {
            ok: true,
            version: "1.2.3",
            repo: {short_commit: "abc123"},
            unit: {active_state: "active", sub_state: "running", returncode: 0},
            health: {status: "ok", classification_version: 2, total_problem_count: 0, command_ok: true},
            runtime: {returncode: 0, summary: {instances: "Demo", channels: "telegram"}, status_counts: {}},
            qdrant: {collections: {teebotus_user_memory: {status: "ready", count: 1}, teebotus_bibliothekar_chunks: {status: "ready", count: 1}}}
          };
          values.statusSummary = applet._statusSummary(applet.statusPayload);
          applet.headerItem = {label: {set_text: function(value) { values.header = value; }}};
          applet.summaryItem = {label: {set_text: function(value) { values.summary = value; }}};
          applet.versionItem = {label: {set_text: function(value) { values.version = value; }}};
          applet._updateHeader();
          return values;
        })()
        """
    )

    assert result["statusSummary"].startswith("Warnungen 1")
    assert "Dispatcher Warnung" in result["statusSummary"]
    assert "Health Warnung" in result["statusSummary"]
    assert "Warnungen 1" in result["version"]
    assert "Health: Warnung" in result["version"]
    assert "Dispatcher Warnung" in result["version"]


def test_cinnamon_applet_spawn_json_does_not_reinvoke_throwing_consumer() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let calls = [];
          applet._spawn = function(argv, callback, cwd, options) {
            callback(JSON.stringify({ok: true, command_ok: true, repo: {}, unit: {active_state: "active", sub_state: "running", returncode: 0}, health: {status: "ok", command_ok: true}, qdrant: {unit: {active_state: "active", sub_state: "running", returncode: 0}, collections: {teebotus_user_memory: {status: "ready", count: 0}, teebotus_bibliothekar_chunks: {status: "ready", count: 0}}}, runtime: {returncode: 0, sections: {}, summary: {}, status_counts: {}}}), "", true);
          };
          try {
            applet._spawnJson([], function(payload, error) {
              calls.push({payload: Boolean(payload), error: error});
              if (payload) {
                throw new Error("consumer failed");
              }
            });
          } catch (err) {
            return {calls: calls, thrown: String(err)};
          }
          return {calls: calls, thrown: ""};
        })()
        """
    )

    assert result["thrown"] == "Error: consumer failed"
    assert result["calls"] == [{"payload": True, "error": None}]


def test_cinnamon_applet_local_status_text_updates_menu_header() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let values = {};
          applet.statusPayload = {
            version: "1.2.3",
            unit: {},
            health: {status: "ok"},
            runtime: {summary: {llm_routes: 2}}
          };
          applet.set_applet_label = function(value) { values.panelLabel = value; };
          applet.set_applet_tooltip = function(value) { values.tooltip = value; };
          applet.headerItem = {label: {set_text: function(value) { values.header = value; }}};
          applet.summaryItem = {label: {set_text: function(value) { values.summary = value; }}};
          applet.versionItem = {label: {set_text: function(value) { values.version = value; }}};
          applet._setStatusText("Kopiert.");
          values.statusText = applet.statusText;
          return values;
        })()
        """
    )

    assert result["statusText"] == "Kopiert."
    assert result["tooltip"] == "Kopiert."
    assert result["summary"] == "Kopiert."
    assert result["header"] == "TB 1.2.3"
    assert "LLM-Routen: 2" in result["version"]


def test_cinnamon_applet_menu_header_includes_health_details() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let values = {};
          applet.statusPayload = {
            version: "1.2.3",
            repo: { short_commit: "abc1234" },
            unit: { active_state: "active", sub_state: "running" },
            health: {
              status: "broken",
              total_problem_count: 3,
              command_problem_count: 1,
              qdrant_runtime_problem_count: 2,
              qdrant_probe_problem_count: 0,
              qdrant_unit_problem_count: 1,
              problem_statuses: "broken:2,warning:1"
            },
            runtime: { summary: { llm_routes: 2 } }
          };
          applet.headerItem = {label: {set_text: function(value) { values.header = value; }}};
          applet.summaryItem = {label: {set_text: function(value) { values.summary = value; }}};
          applet.versionItem = {label: {set_text: function(value) { values.version = value; }}};
          applet._updateHeader();
          return values;
        })()
        """
    )

    assert result["header"] == "TB 1.2.3"
    assert result["summary"] == "Status unbekannt"
    assert "Health: defekt" in result["version"]
    assert "Probleme 3" in result["version"]
    assert "Probleme defekt:2, Warnung:1" in result["version"]
    assert "Kommando:1" in result["version"]
    assert "Qdrant Runtime:2, Service:1" in result["version"]
    assert "LLM-Routen: 2" in result["version"]


def test_cinnamon_applet_status_menu_detail_lines_include_health_and_runtime_data() -> None:
    result = _run_js_applet_expression(
        """
        applet._statusDetailLines({
          ok: false,
          version: "1.2.3",
          repo: {short_commit: "abc1234"},
          unit: {name: "teebotus.service", active_state: "active", sub_state: "running", returncode: 0},
          health: {status: "broken", total_problem_count: 2, problem_statuses: "missing_key:2"},
          qdrant: {
            url: "http://127.0.0.1:6333",
            error: "probe failed",
            collections: {
              teebotus_user_memory: {status: "ready", count: 162, error: ""},
              teebotus_bibliothekar_chunks: {status: "unreachable", count: 0, error: "connection refused"}
            }
          },
          runtime: {
            summary: {instances: "Demo", channels: "telegram", problem_status_count: 2},
            status_counts: {missing_key: 2}
          }
        })
        """
    )

    assert result == [
        "Health: defekt | Probleme 2 | Probleme Key fehlt:2",
        "Unit: teebotus.service active / running; Returncode 0",
        "Qdrant: http://127.0.0.1:6333; Collections 1/2; Fehler probe failed",
        "Runtime: Demo | Kanaele telegram | Version 1.2.3 | Commit abc1234",
    ]


def test_cinnamon_applet_warning_health_uses_warning_label_in_detail() -> None:
    result = _run_js_applet_expression(
        """
        applet._statusDetailLines({
          ok: false,
          version: "1.2.3",
          health: {
            status: "warning",
            classification_version: 2,
            total_problem_count: 2,
            actionable_problem_count: 2,
            actionable_problem_statuses: "warning:2"
          },
          unit: {active_state: "active", sub_state: "running", returncode: 0},
          qdrant: {collections: {}},
          runtime: {summary: {}, status_counts: {}}
        })
        """
    )

    assert result[0] == "Health: Warnung | Warnungen 2 | Probleme Warnung:2"


def test_cinnamon_applet_status_detail_includes_dispatcher_warning() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          applet.showHistoryDispatcherSection = true;
          applet.historyDispatcherPayload = {
            schema_version: 1,
            ok: true,
            generated_at: new Date().toISOString(),
            last_error: "dispatch failed",
            queued: 0,
            total: 1,
            collector: {enabled: true, sources: 1},
            dispatch: {enabled: true, paused: false},
            queue_preview: []
          };
          applet.historyDispatcherError = "";
          return applet._statusDetailLines({
            ok: true,
            health: {status: "ok", classification_version: 2, total_problem_count: 0},
            unit: {active_state: "active", sub_state: "running", returncode: 0},
            qdrant: {collections: {}},
            runtime: {summary: {}, status_counts: {}}
          })[0];
        })()
        """
    )

    assert result == "Health: Warnung | Warnungen 1 | Dispatcher Warnung"


def test_cinnamon_applet_status_detail_distinguishes_source_and_runtime_version() -> None:
    result = _run_js_applet_expression(
        """
        applet._statusDetailLines({
          ok: true,
          version: "1.9.406",
          runtime_version: {status: "matched", version: "1.9.404"},
          repo: {short_commit: "abc1234"},
          unit: {name: "teebotus.service", active_state: "active", sub_state: "running", returncode: 0},
          health: {status: "ok", total_problem_count: 0},
          qdrant: {collections: {}},
          runtime: {summary: {instances: "Demo", channels: "telegram"}, status_counts: {}}
        })
        """
    )

    assert result[-1] == "Runtime: Demo | Kanaele telegram | Version 1.9.406 | Runtime-Version 1.9.404 | Commit abc1234"


def test_runtime_version_marker_matches_active_unit(tmp_path: Path) -> None:
    marker = write_runtime_version_marker(
        tmp_path,
        version="1.9.406",
        pid=1234,
        invocation_id="invocation-1",
        started_at="2026-07-13T06:41:32+00:00",
    )

    assert marker is not None
    result = read_runtime_version_status(
        tmp_path,
        {"main_pid": "1234", "invocation_id": "invocation-1"},
    )

    assert result["status"] == "matched"
    assert result["version"] == "1.9.406"


def test_runtime_version_marker_rejects_stale_unit_identity(tmp_path: Path) -> None:
    marker = write_runtime_version_marker(
        tmp_path,
        version="1.9.406",
        pid=1234,
        invocation_id="invocation-1",
    )

    assert marker is not None
    assert read_runtime_version_status(
        tmp_path,
        {"main_pid": "1235", "invocation_id": "invocation-1"},
    )["reason"] == "pid_mismatch"
    assert read_runtime_version_status(
        tmp_path,
        {"main_pid": "1234", "invocation_id": "invocation-2"},
    )["reason"] == "invocation_mismatch"


def test_cinnamon_applet_formats_runtime_slot_and_admin_status_lines() -> None:
    result = _run_js_applet_expression(
        """
        ({
          runtime: applet._formatLlmLine("runtime_slot=Demo/signal status=not_configured reason=missing_signal_credentials"),
          group: applet._formatAccountLine("admin_accounts=Demo status=configured source=default accounts=2 local=1 cross_instance=1 not_local=1 routable=2 warnings=0 invalid=0"),
          account: applet._formatAccountLine("admin_account=Demo/abcdefghijklmnopqrstuvwxyz0123456789 status=routable channel=telegram slot=1 source_instance=Demo")
        })
        """
    )

    assert result == {
        "runtime": "Runtime-Slot Demo/signal: nicht konfiguriert; Grund missing_signal_credentials",
        "group": "Admin-Gruppe Demo: konfiguriert; Accounts 2; Lokal 1; Cross-Instanz 1; Nicht-lokal 1; Routbar 2; Warnungen 0; Ungueltig 0; Quelle default",
        "account": "Admin-Konto Demo/abcdefghijklmnopqrstuvwxyz0123456789: routbar; Kanal telegram; Slot 1; Quelle Demo",
    }


def test_cinnamon_applet_formats_signal_identity_action_as_concrete_login_steps() -> None:
    result = _run_js_applet_expression(
        """
        applet._formatAccountLine(
          "account_identity_warning=Depressionsbot code=runtime_channel_without_identity channel=signal "
          + "message=signal runtime is configured action=legacy"
        )
        """
    )

    assert result == (
        "Signal-Verknuepfung Depressionsbot: erforderlich; "
        "1. in einem bereits verknuepften privaten Chat /register oder /rotate_secret ausfuehren; "
        "2. im privaten Signal-Chat /login <account_id> <secret> senden; "
        "/register in Signal nur fuer ein absichtlich getrenntes Konto verwenden"
    )


def test_cinnamon_applet_usage_formatters_keep_error_details() -> None:
    result = _run_js_applet_expression(
        """
        ({
          summary: applet._formatApiBudgetLine("codex_usage=local status=broken snapshots=2 error=snapshot_failed"),
          account: applet._formatApiBudgetLine("codex_usage_account=Demo status=unavailable five_hour=? weekly=? error=account_unreachable")
        })
        """
    )

    assert result == {
        "summary": "codex-usage: defekt; Snapshots 2; Fehler snapshot_failed",
        "account": "codex-usage Demo: nicht verfuegbar; 5h ?; Woche ?; Fehler account_unreachable",
    }


def test_cinnamon_applet_status_formatters_keep_backend_and_budget_metadata() -> None:
    result = _run_js_applet_expression(
        """
        ({
          decision: applet._formatLlmLine("structured_decision=Demo status=enabled source=text_llm_enabled profile=hf_pool_structured provider=hf_pool model=pool:default#structured_decision route_status=unavailable fallback=local_ollama fallback_model=ollama_chat/llama3.2:3b"),
          budget: applet._formatApiBudgetLine("api_budget=demo profile=gemini_flash_stateful provider=litellm_gemini_stateful model=gemini/gemini-3.5-flash status=configured key=configured key_env=GEMINI_API_KEY google_mode=stateful store=true billing=free-tier limits=on costs=local tokens=provider_usage_response max_output_tokens=700")
        })
        """
    )

    assert result == {
        "decision": "Account-Entscheider Demo: aktiv; Quelle text_llm_enabled; Profil hf_pool_structured; Backend hf_pool / pool:default#structured_decision; Route nicht verfuegbar; Ersatz local_ollama -> ollama_chat/llama3.2:3b",
        "budget": "Route demo: litellm_gemini_stateful / gemini/gemini-3.5-flash (konfiguriert); Profil gemini_flash_stateful; Key configured via GEMINI_API_KEY; Google stateful; Store ja; Abrechnung free-tier; Limits on; Kosten local; Tokens provider_usage_response; Max-Output 700",
    }


def test_cinnamon_applet_history_status_labels_are_localized() -> None:
    result = _run_js_applet_expression(
        """
        ({
          acknowledged: applet._statusWord("acknowledged"),
          accepted: applet._statusWord("accepted"),
          cancelled: applet._statusWord("cancelled"),
          delivered: applet._statusWord("delivered"),
          dispatching: applet._statusWord("dispatching"),
          duplicate: applet._statusWord("duplicate"),
          imported: applet._statusWord("imported"),
          mixed: applet._statusWord("mixed"),
          queued: applet._statusWord("queued"),
          sent: applet._statusWord("sent"),
          skipped: applet._statusWord("skipped"),
          history: applet._formatProjectHistoryLine("codex_history_repo=Demo repo=TeeBotus status=warning queued=1 failed=0 total=2 latest_status=queued latest_kind=codex_run_summary")
        })
        """
    )

    assert result == {
        "acknowledged": "bestaetigt",
        "accepted": "akzeptiert",
        "cancelled": "abgebrochen",
        "delivered": "zugestellt",
        "dispatching": "wird gesendet",
        "duplicate": "Duplikat",
        "imported": "importiert",
        "mixed": "gemischt",
        "queued": "wartet",
        "sent": "gesendet",
        "skipped": "uebersprungen",
        "history": "Repo-History TeeBotus (Demo): Warnung; offen 1; fehlgeschlagen 0; gesamt 2; letzter Status wartet; Typ Run-Summary",
    }


def test_cinnamon_applet_history_status_shows_skip_reason() -> None:
    result = _run_js_applet_expression(
        'applet._formatProjectHistoryLine("codex_history=TBL status=warning queued=0 failed=0 total=1467 skipped=101 problem_statuses=skipped:101 skip_reasons=no_private_route:101")'
    )

    assert result == (
        "Codex-History TBL: Warnung; offen 0; fehlgeschlagen 0; gesamt 1467; "
        "uebersprungen 101; Grund no private route:101"
    )


def test_cinnamon_applet_formats_runtime_directory_and_agent_pilot_lines() -> None:
    result = _run_js_applet_expression(
        """
        ({
          directory: applet._formatRuntimeLine("instances_dir=instances"),
          pilot: applet._formatAgentPilotLine("crew_pilot=source_quality_expedition status=planned dependency=missing enabled_by_default=false roles=harvester,formatter workflow=discover,format")
        })
        """
    )

    assert result == {
        "directory": "Instanzen-Verzeichnis: instances",
        "pilot": "Agenten-Pilot source_quality_expedition: geplant; Abhaengigkeit fehlt; Standard nein; Rollen harvester, formatter; Ablauf discover -> format",
    }


def test_cinnamon_applet_menu_header_omits_zero_problem_total() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let values = {};
          applet.statusPayload = {
            version: "1.2.3",
            repo: { short_commit: "abc1234" },
            unit: { active_state: "active", sub_state: "running" },
            health: {
              status: "ok",
              total_problem_count: 0,
              problem_statuses: ""
            },
            runtime: { summary: { llm_routes: 0 } }
          };
          applet.headerItem = {label: {set_text: function(value) { values.header = value; }}};
          applet.summaryItem = {label: {set_text: function(value) { values.summary = value; }}};
          applet.versionItem = {label: {set_text: function(value) { values.version = value; }}};
          applet._updateHeader();
          return values;
        })()
        """
    )

    assert result["header"] == "TB 1.2.3"
    assert "Probleme 0" not in result["version"]
    assert result["version"].startswith("Health: ok")
    assert "LLM-Routen: 0" in result["version"]


def test_cinnamon_applet_status_summary_keeps_problem_count_for_empty_unhealthy_payload() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let payload = {
            ok: false,
            unit: {active_state: "unknown", sub_state: "unknown"},
            health: {status: "broken", total_problem_count: 0},
            runtime: {summary: {}, status_counts: {}},
            qdrant: {collections: {}}
          };
          let broken = applet._statusSummary(payload);
          payload.health.status = "warning";
          let warning = applet._statusSummary(payload);
          return {broken: broken, warning: warning};
        })()
        """
    )

    assert result["broken"].startswith("Probleme 1")
    assert "Health defekt" in result["broken"]
    assert result["warning"].startswith("Warnungen 1")
    assert "Health Warnung" in result["warning"]


def test_cinnamon_applet_menu_header_derives_total_from_command_and_qdrant_problems() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let values = {};
          applet.statusPayload = {
            version: "1.2.3",
            repo: { short_commit: "abc1234" },
            unit: { active_state: "active", sub_state: "running" },
            health: {
              status: "warning",
              command_problem_count: 1,
              qdrant_problem_count: 1,
              qdrant_runtime_problem_count: 1,
              qdrant_probe_problem_count: 1,
              qdrant_unit_problem_count: 0,
              problem_statuses: ""
            },
            runtime: { summary: { problem_status_count: 0, llm_routes: 0 } }
          };
          values.statusSummary = applet._statusSummary(applet.statusPayload);
          applet.headerItem = {label: {set_text: function(value) { values.header = value; }}};
          applet.summaryItem = {label: {set_text: function(value) { values.summary = value; }}};
          applet.versionItem = {label: {set_text: function(value) { values.version = value; }}};
          applet._updateHeader();
          return values;
        })()
        """
    )

    assert "Warnungen 2" in result["statusSummary"]
    assert "Warnungen 2" in result["version"]
    assert "Kommando:1" in result["version"]
    assert "Qdrant Runtime:1, Probe:1" in result["version"]


def test_cinnamon_applet_menu_header_derives_total_from_zeroed_summary_fields() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let values = {};
          applet.statusPayload = {
            version: "1.2.3",
            repo: { short_commit: "abc1234" },
            unit: { active_state: "active", sub_state: "running" },
            health: {
              status: "warning",
              command_problem_count: 0,
              qdrant_problem_count: 0,
              qdrant_runtime_problem_count: 1,
              qdrant_probe_problem_count: 0,
              qdrant_unit_problem_count: 0,
              problem_statuses: ""
            },
            runtime: {
              summary: { problem_status_count: 0, llm_routes: 0 },
              status_counts: { warning: 3 }
            }
          };
          values.statusSummary = applet._statusSummary(applet.statusPayload);
          return values;
        })()
        """
    )

    assert "Warnungen 3" in result["statusSummary"]


def test_cinnamon_applet_menu_header_uses_runtime_counts_in_detail_text() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let values = {};
          applet.statusPayload = {
            version: "1.2.3",
            repo: { short_commit: "abc1234" },
            unit: { active_state: "active", sub_state: "running" },
            health: {
              status: "warning",
              problem_statuses: "warning:1"
            },
            runtime: {
              summary: { problem_status_count: 0, llm_routes: 0 },
              status_counts: { warning: 3, broken: 1 }
            }
          };
          applet.headerItem = {label: {set_text: function(value) { values.header = value; }}};
          applet.summaryItem = {label: {set_text: function(value) { values.summary = value; }}};
          applet.versionItem = {label: {set_text: function(value) { values.version = value; }}};
          applet._updateHeader();
          return values;
        })()
        """
    )

    assert "Warnungen 4" in result["version"]
    assert "Warnung:1" in result["version"]


def test_cinnamon_applet_menu_header_keeps_authoritative_total_problem_count() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let values = {};
          applet.statusPayload = {
            version: "1.2.3",
            repo: { short_commit: "abc1234" },
            unit: { active_state: "active", sub_state: "running" },
            health: {
              status: "warning",
              total_problem_count: 1,
              problem_statuses: "warning:1"
            },
            runtime: {
              summary: { problem_status_count: 0, llm_routes: 0 },
              status_counts: { warning: 3, broken: 1 }
            }
          };
          values.statusSummary = applet._statusSummary(applet.statusPayload);
          return values;
        })()
        """
    )

    assert "Warnungen 1" in result["statusSummary"]


def test_cinnamon_applet_health_v2_keeps_information_visible_without_promoting_it_to_problem() -> None:
    result = _run_js_applet_expression(
        """
        ({
          total: applet._healthProblemTotal(
            {classification_version: 2, status: "ok", total_problem_count: 0, informational_problem_count: 3},
            {problem_status_count: 9, problem_statuses: "unavailable:9"},
            {unavailable: 9}
          ),
          summary: applet._statusSummary({
            ok: true,
            unit: {active_state: "active"},
            health: {
              classification_version: 2,
              status: "ok",
              total_problem_count: 0,
              actionable_problem_statuses: "",
              informational_problem_count: 3,
              informational_problem_statuses: "unavailable:3"
            },
            runtime: {summary: {instances: "Demo", channels: "telegram"}, status_counts: {unavailable: 9}},
            qdrant: {collections: {}}
          })
        })
        """
    )

    assert result["total"] == 0
    assert result["summary"].startswith("Health ok | Hinweise nicht verfuegbar:3 | Unit active")
    assert "Probleme" not in result["summary"]
    assert "Warnungen" not in result["summary"]


def test_cinnamon_applet_health_v2_does_not_hide_actionable_status_behind_stale_total() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let health = {
            classification_version: 2,
            status: "warning",
            total_problem_count: 0,
            actionable_problem_count: 0,
            actionable_problem_statuses: "missing_key:1"
          };
          return {
            total: applet._healthProblemTotal(health, {actionable_problem_statuses: "missing_key:1"}, {}),
            summary: applet._statusSummary({
              ok: false,
              unit: {active_state: "active"},
              health: health,
              runtime: {summary: {instances: "Demo", channels: "telegram"}, status_counts: {}},
              qdrant: {collections: {}}
            }),
            accepted: applet._isStatusPayload({
              ok: true,
              repo: {},
              unit: {active_state: "active", sub_state: "running", returncode: 0},
              health: {
                classification_version: 2,
                status: "ok",
                total_problem_count: 0,
                actionable_problem_count: 0,
                actionable_problem_statuses: "missing_key:1",
                command_ok: true
              },
              qdrant: {collections: {}},
              runtime: {returncode: 0, sections: {}, summary: {}, status_counts: {}}
            })
          };
        })()
        """
    )

    assert result["total"] == 1
    assert result["summary"].startswith("Warnungen 1")
    assert "Probleme Key fehlt:1" in result["summary"]
    assert result["accepted"] is False


def test_cinnamon_applet_health_v2_fails_closed_when_classification_fields_are_missing() -> None:
    result = _run_js_applet_expression(
        """
        ({
          total: applet._healthProblemTotal(
            {classification_version: 2, status: "ok", total_problem_count: 0},
            {},
            {warning: 1}
          ),
          summary: applet._statusSummary({
            ok: true,
            unit: {active_state: "active"},
            health: {classification_version: 2, status: "ok", total_problem_count: 0},
            runtime: {summary: {}, status_counts: {warning: 1}},
            qdrant: {collections: {}}
          })
        })
        """
    )

    assert result["total"] == 1
    assert result["summary"].startswith("Warnungen 1")
    assert "Warnung:1" in result["summary"]


def test_cinnamon_applet_health_v2_does_not_hide_command_or_qdrant_counts_behind_stale_total() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let health = {
            classification_version: 2,
            status: "warning",
            total_problem_count: 0,
            actionable_problem_count: 0,
            actionable_problem_statuses: "",
            command_problem_count: 1,
            qdrant_problem_count: 2,
            qdrant_runtime_problem_count: 0,
            qdrant_probe_problem_count: 2,
            qdrant_unit_problem_count: 0
          };
          return {
            total: applet._healthProblemTotal(health, {}, {}),
            summary: applet._statusSummary({
              ok: false,
              unit: {active_state: "active"},
              health: health,
              runtime: {summary: {instances: "Demo", channels: "telegram"}, status_counts: {}},
              qdrant: {collections: {}}
            })
          };
        })()
        """
    )

    assert result["total"] == 3
    assert result["summary"].startswith("Warnungen 3")
    assert "Kommando:1" in result["summary"]
    assert "Qdrant Probe:2" in result["summary"]


def test_cinnamon_applet_menu_header_does_not_trust_zero_total_problem_count() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let values = {};
          applet.statusPayload = {
            version: "1.2.3",
            repo: { short_commit: "abc1234" },
            unit: { active_state: "active", sub_state: "running" },
            health: {
              status: "warning",
              total_problem_count: 0,
              command_problem_count: 1,
              problem_statuses: ""
            },
            runtime: { summary: { problem_status_count: 0, llm_routes: 0 } }
          };
          values.statusSummary = applet._statusSummary(applet.statusPayload);
          return values;
        })()
        """
    )

    assert "Warnungen 1" in result["statusSummary"]


def test_cinnamon_applet_menu_header_does_not_double_count_qdrant_runtime_problems() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let values = {};
          applet.statusPayload = {
            version: "1.2.3",
            repo: { short_commit: "abc1234" },
            unit: { active_state: "active", sub_state: "running" },
            health: {
              status: "warning",
              problem_statuses: "",
              qdrant_runtime_problem_count: 1,
              qdrant_probe_problem_count: 0,
              qdrant_unit_problem_count: 0,
              qdrant_problem_count: 0
            },
            runtime: { summary: { problem_status_count: 1, llm_routes: 0 } }
          };
          values.statusSummary = applet._statusSummary(applet.statusPayload);
          return values;
        })()
        """
    )

    assert "Warnungen 1" in result["statusSummary"]
    assert "Qdrant Runtime:1" in result["statusSummary"]


def test_cinnamon_applet_menu_header_warns_on_qdrant_runtime_only_fallback() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let values = {};
          applet.statusPayload = {
            version: "1.2.3",
            repo: { short_commit: "abc1234" },
            unit: { active_state: "active", sub_state: "running" },
            health: {
              status: "warning",
              qdrant_runtime_problem_count: 1,
              qdrant_probe_problem_count: 0,
              qdrant_unit_problem_count: 0,
              qdrant_problem_count: 0,
              problem_statuses: ""
            },
            runtime: { summary: { problem_status_count: 0, llm_routes: 0 } }
          };
          values.statusSummary = applet._statusSummary(applet.statusPayload);
          return values;
        })()
        """
    )

    assert "Warnungen 1" in result["statusSummary"]


def test_cinnamon_applet_menu_header_uses_maximum_qdrant_problem_signal() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let values = {};
          applet.statusPayload = {
            version: "1.2.3",
            repo: { short_commit: "abc1234" },
            unit: { active_state: "active", sub_state: "running" },
            health: {
              status: "warning",
              problem_statuses: "",
              qdrant_problem_count: 1,
              qdrant_runtime_problem_count: 2,
              qdrant_probe_problem_count: 0,
              qdrant_unit_problem_count: 0
            },
            runtime: { summary: { problem_status_count: 2, llm_routes: 0 } }
          };
          values.statusSummary = applet._statusSummary(applet.statusPayload);
          return values;
        })()
        """
    )

    assert result["statusSummary"].startswith("Warnungen 2")
    assert "Qdrant Runtime:2" in result["statusSummary"]


def test_cinnamon_applet_menu_header_prefers_payload_runtime_problem_count() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let values = {};
          applet.statusPayload = {
            version: "1.2.3",
            repo: { short_commit: "abc1234" },
            unit: { active_state: "active", sub_state: "running" },
            health: {
              status: "warning",
              runtime_problem_count: 2,
              problem_statuses: "",
              qdrant_problem_count: 0,
              qdrant_probe_problem_count: 0,
              qdrant_unit_problem_count: 0,
              qdrant_runtime_problem_count: 0
            },
            runtime: { summary: { problem_status_count: 0, llm_routes: 0 } }
          };
          values.statusSummary = applet._statusSummary(applet.statusPayload);
          return values;
        })()
        """
    )

    assert "Warnungen 2" in result["statusSummary"]


def test_cinnamon_applet_menu_header_uses_health_problem_count_when_runtime_summary_is_missing() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let values = {};
          applet.statusPayload = {
            version: "1.2.3",
            repo: { short_commit: "abc1234" },
            unit: { active_state: "active", sub_state: "running" },
            health: {
              status: "broken",
              problem_status_count: 4,
              problem_statuses: "broken:4",
              qdrant_runtime_problem_count: 0,
              qdrant_problem_count: 0
            },
            runtime: {}
          };
          values.statusSummary = applet._statusSummary(applet.statusPayload);
          return values;
        })()
        """
    )

    assert result["statusSummary"].startswith("Probleme 4")
    assert "Probleme defekt:4" in result["statusSummary"]


def test_cinnamon_applet_menu_header_does_not_let_zero_health_count_hide_summary_count() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let values = {};
          applet.statusPayload = {
            version: "1.2.3",
            repo: { short_commit: "abc1234" },
            unit: { active_state: "active", sub_state: "running" },
            health: {
              status: "warning",
              problem_status_count: 0,
              problem_statuses: "warning:3",
              qdrant_runtime_problem_count: 0,
              qdrant_problem_count: 0
            },
            runtime: { summary: { problem_status_count: 3 } }
          };
          values.statusSummary = applet._statusSummary(applet.statusPayload);
          return values;
        })()
        """
    )

    assert result["statusSummary"].startswith("Warnungen 3")


def test_cinnamon_applet_menu_header_uses_status_counts_for_problem_breakdown_when_missing() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let values = {};
          applet.statusPayload = {
            version: "1.2.3",
            repo: { short_commit: "abc1234" },
            unit: { active_state: "active", sub_state: "running" },
            health: {
              status: "warning",
              runtime_problem_count: 2,
              problem_statuses: "",
              command_problem_count: 0,
              qdrant_problem_count: 0,
              qdrant_probe_problem_count: 0,
              qdrant_unit_problem_count: 0,
              qdrant_runtime_problem_count: 0
            },
            runtime: { summary: { problem_status_count: 0, llm_routes: 0 }, status_counts: { warning: 2, broken: 1 } }
          };
          values.statusSummary = applet._statusSummary(applet.statusPayload);
          applet.headerItem = {label: {set_text: function(value) { values.header = value; }}};
          applet.summaryItem = {label: {set_text: function(value) { values.summary = value; }}};
          applet.versionItem = {label: {set_text: function(value) { values.version = value; }}};
          applet._updateHeader();
          return values;
        })()
        """
    )

    assert "Probleme Warnung:2, defekt:1" in result["version"]


def test_cinnamon_applet_status_summary_uses_status_counts_for_problem_breakdown_when_missing() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let values = {};
          applet.statusPayload = {
            version: "1.2.3",
            repo: { short_commit: "abc1234" },
            unit: { active_state: "active", sub_state: "running" },
            health: {
              status: "warning",
              runtime_problem_count: 2,
              problem_statuses: "",
              command_problem_count: 0,
              qdrant_problem_count: 0,
              qdrant_probe_problem_count: 0,
              qdrant_unit_problem_count: 0,
              qdrant_runtime_problem_count: 0
            },
            runtime: {
              summary: {
                instances: "Demo",
                channels: "telegram",
                problem_status_count: 0,
                problem_statuses: "",
                llm_routes: 0
              },
              status_counts: { warning: 2, broken: 1 }
            }
          };
          values.statusSummary = applet._statusSummary(applet.statusPayload);
          return values;
        })()
        """
    )

    assert result["statusSummary"].startswith("Warnungen 2")
    assert "Warnungen 2" in result["statusSummary"]
    assert "Probleme Warnung:2, defekt:1" in result["statusSummary"]


def test_cinnamon_applet_menu_header_problem_counts_come_before_health_status() -> None:
    result = _run_js_applet_expression(
        """
        (function() {
          let values = {};
          applet.statusPayload = {
            version: "1.2.3",
            repo: { short_commit: "abc1234" },
            unit: { active_state: "active", sub_state: "running" },
            health: {
              status: "warning",
              runtime_problem_count: 2,
              problem_statuses: "",
              command_problem_count: 0,
              qdrant_problem_count: 0,
              qdrant_probe_problem_count: 0,
              qdrant_unit_problem_count: 0,
              qdrant_runtime_problem_count: 0
            },
            runtime: {
              summary: {
                instances: "Demo",
                channels: "telegram",
                problem_status_count: 0,
                problem_statuses: "",
                llm_routes: 0
              },
              status_counts: { warning: 2, broken: 1 }
            }
          };
          applet.statusText = applet._statusSummary(applet.statusPayload);
          applet.headerItem = {label: {set_text: function(value) { values.header = value; }}};
          applet.summaryItem = {label: {set_text: function(value) { values.summary = value; }}};
          applet.versionItem = {label: {set_text: function(value) { values.version = value; }}};
          applet._updateHeader();
          return values;
        })()
        """
    )

    assert result["summary"].startswith("Warnungen 2")
    assert result["version"].startswith("Warnungen 2")
    assert result["version"].index("Warnungen 2") < result["version"].index("Health: Warnung")


def test_cinnamon_applet_helper_parses_runtime_status_sections() -> None:
    parsed = parse_runtime_status(
        """
        TeeBotus runtime configuration resolves.

        [Konfiguration]
        instances=Bote_der_Wahrheit,Depressionsbot
        channels=telegram,signal

        [LLM-Routen und Backends]
        hf_pool=default status=disabled
        hf_pool=default target=primary status=cooldown model=provider/model models_feed=ok context_length=8192 tools=true structured_output=true
        gemini_free_tier_limits status=no_limits_found source=ai.google.dev/gemini-api/docs/rate-limits
        llm_route=bibliothekar_answer status=configured

        [Memory und semantische Suche]
        qdrant=127.0.0.1:6333 status=reachable
        qdrant_collection=teebotus_user_memory target=127.0.0.1:6333 status=ready vector_size=64 embedding_model=teebotus-account-memory-hash
        qdrant_collection=teebotus_bibliothekar_chunks target=127.0.0.1:6333 status=ready vector_size=1024 embedding_model=BAAI/bge-m3
        memory_index=Depressionsbot backend=keyword status=ready semantic=ready

        [API Keys, Limits und Kosten]
        api_budget=bibliothekar_answer status=configured key=configured
        codex_usage=local status=ready snapshots=2
        codex_usage_account=BW_Work status=ok five_hour=1/100 weekly=5/100

        [Messenger]
        telegram_slot=Depressionsbot/telegram:1 status=configured token=configured
        signal_account=Depressionsbot/signal:1 status=registered

        [Tools und Account-Memory]
        account_memory=Depressionsbot/example status=ok
        """
    )

    assert parsed["summary"]["instances"] == "Bote_der_Wahrheit,Depressionsbot"
    assert parsed["summary"]["channels"] == "telegram,signal"
    assert parsed["summary"]["telegram_slots"] == 1
    assert parsed["summary"]["signal_accounts"] == 1
    assert parsed["summary"]["messenger_problem_status_count"] == 0
    assert parsed["summary"]["memory_accounts"] == 1
    assert parsed["summary"]["memory_problem_status_count"] == 0
    assert parsed["summary"]["llm_routes"] == 1
    assert parsed["summary"]["llm_problem_status_count"] == 2
    assert parsed["summary"]["api_budgets"] == 1
    assert parsed["summary"]["api_problem_status_count"] == 0
    assert parsed["summary"]["codex_usage"].startswith("codex_usage=local")
    assert parsed["summary"]["codex_usage_accounts"] == 1
    assert parsed["summary"]["gemini_free_tier"].startswith("gemini_free_tier_limits")
    assert parsed["summary"]["hf_pool"] == "hf_pool=default status=disabled"
    assert parsed["summary"]["qdrant"].startswith("qdrant=127.0.0.1:6333")
    assert parsed["summary"]["qdrant_collections"] == 2
    assert parsed["summary"]["qdrant_problem_status_count"] == 0
    assert parsed["summary"]["qdrant_ready_collections"] == 2
    assert parsed["summary"]["memory_semantic_ready"] == 1
    assert parsed["status_counts"]["configured"] == 3
    assert parsed["status_counts"]["cooldown"] == 1
    assert parsed["status_counts"]["ready"] == 4
    assert "Messenger" in parsed["sections"]


def test_cinnamon_applet_runtime_parser_marks_truncated_output_as_warning() -> None:
    parsed = parse_runtime_status(
        """
        [Konfiguration]
        instances=Demo
        <truncated>
        """
    )

    assert parsed["summary"]["output_truncated"] is True
    assert parsed["status_counts"]["warning"] == 1
    assert parsed["summary"]["problem_status_count"] == 1
    assert parsed["summary"]["problem_statuses"] == "warning:1"


def test_cinnamon_applet_runtime_parser_counts_section_problems() -> None:
    parsed = parse_runtime_status(
        """
        [Messenger]
        telegram_slot=Demo/telegram:1 status=missing

        [LLM-Routen und Backends]
        gemini_free_tier_limits status=fallback_defaults
        structured_decision=Demo status=enabled route_status=unavailable

        [Accounts und Entscheidungen]
        structured_decision=Demo/telegram:1 status=enabled route_status=unavailable fallback=local_ollama fallback_model=ollama_chat/llama3.2:3b

        [Lokale Dienste]
        local_transcription=Demo status=broken error=faster-whisper missing
        bibliothekar=Demo status=ready

        [API Keys, Limits und Kosten]
        api_budget=hard_reasoning status=missing_key key=missing
        codex_usage=local status=ready snapshots=2 stale_hours=24

        [Memory und semantische Suche]
        qdrant_collection=demo status=unavailable
        memory_index=Demo backend=keyword status=ready semantic=unsupported

        [Tools und Account-Memory]
        account_identity=Demo status=warning identity_warnings=1
        account_memory_recovery=Demo status=needed command="python3 -m TeeBotus.admin memory-recovery"
        """
    )

    assert parsed["summary"]["messenger_problem_status_count"] == 1
    assert parsed["summary"]["llm_problem_status_count"] == 4
    assert parsed["summary"]["api_problem_status_count"] == 2
    assert parsed["summary"]["memory_problem_status_count"] == 4
    assert parsed["summary"]["problem_status_count"] == 11
    assert parsed["summary"]["problem_statuses"] == (
        "broken:1,fallback_defaults:1,missing:1,missing_key:1,needed:1,stale:1,unavailable:3,unsupported:1,warning:1"
    )


def test_cinnamon_applet_runtime_parser_does_not_hide_codex_repo_failures_as_info() -> None:
    parsed = parse_runtime_status(
        """
        [Projekt-History]
        codex_history_repo=Demo repo=TeeBotus status=warning queued=0 failed=1 total=1 problem_statuses=failed:1
        codex_history_repo=Demo repo=Docs status=warning queued=0 failed=0 skipped=1 total=1 problem_statuses=skipped:1 skip_reasons=no_private_route:1
        """
    )

    assert parsed["summary"]["actionable_problem_status_count"] == 1
    assert parsed["summary"]["actionable_problem_statuses"] == "warning:1"
    assert parsed["summary"]["informational_problem_status_count"] == 1
    assert parsed["summary"]["informational_problem_statuses"] == "warning:1"


def test_cinnamon_applet_runtime_parser_does_not_hide_unknown_codex_skip_reasons() -> None:
    parsed = parse_runtime_status(
        """
        [Projekt-History]
        codex_history_repo=Demo repo=Unknown status=warning queued=0 failed=0 skipped=1 total=1 problem_statuses=skipped:1 skip_reasons=unknown:1
        codex_history_repo=Demo repo=Route status=warning queued=0 failed=0 skipped=1 total=1 problem_statuses=skipped:1 skip_reasons=no_private_route:1
        codex_history_repo=Demo repo=Malformed status=warning queued=0 failed=0 skipped=1 total=1 problem_statuses=skipped:1 skip_reasons=no_private_route:1,malformed
        """
    )

    assert parsed["summary"]["actionable_problem_status_count"] == 2
    assert parsed["summary"]["actionable_problem_statuses"] == "warning:2"
    assert parsed["summary"]["informational_problem_status_count"] == 1
    assert parsed["summary"]["informational_problem_statuses"] == "warning:1"


def test_cinnamon_applet_runtime_parser_requires_a_reason_for_skipped_repo_rows() -> None:
    parsed = parse_runtime_status(
        """
        [Projekt-History]
        codex_history_repo=Demo repo=MissingReason status=warning queued=0 failed=0 skipped=1 total=1 problem_statuses=skipped:1
        codex_history_repo=Demo repo=QueuedOnly status=warning queued=1 failed=0 skipped=0 total=1 problem_statuses=queued:1
        codex_history_repo=Demo repo=KnownReason status=warning queued=0 failed=0 skipped=1 total=1 problem_statuses=skipped:1 skip_reasons=no_private_route:1
        """
    )

    assert parsed["summary"]["actionable_problem_statuses"] == "warning:1"
    assert parsed["summary"]["informational_problem_statuses"] == "warning:2"


def test_cinnamon_applet_runtime_parser_normalizes_quoted_codex_history_metadata() -> None:
    parsed = parse_runtime_status(
        """
        [Projekt-History]
        codex_history_repo=Demo repo=failed status=ok problem_statuses="failed:1,skipped:2"
        codex_history_repo=Demo repo=queue status=warning queued=0 skipped=2 problem_statuses="queued:1,skipped:2" skip_reasons="no_private_route:2"
        """
    )

    assert parsed["status_counts"]["ok"] == 1
    assert parsed["status_counts"]["warning"] == 2
    assert parsed["summary"]["actionable_problem_statuses"] == "warning:1"
    assert parsed["summary"]["informational_problem_statuses"] == "warning:1"


def test_cinnamon_applet_runtime_parser_classifies_explained_codex_history_aggregate_as_info() -> None:
    parsed = parse_runtime_status(
        """
        [Projekt-History]
        codex_history=Logger status=warning queued=86 failed=0 skipped=101 total=1555 problem_statuses=queued:86,skipped:101 skip_reasons=no_private_route:101
        """
    )

    assert parsed["summary"]["actionable_problem_status_count"] == 0
    assert parsed["summary"]["actionable_problem_statuses"] == ""
    assert parsed["summary"]["informational_problem_status_count"] == 1
    assert parsed["summary"]["informational_problem_statuses"] == "warning:1"


def test_cinnamon_applet_runtime_parser_keeps_undocumented_codex_history_aggregate_actionable() -> None:
    parsed = parse_runtime_status(
        """
        [Projekt-History]
        codex_history=Logger status=warning queued=1 failed=0 total=1
        """
    )

    assert parsed["summary"]["actionable_problem_statuses"] == "warning:1"
    assert parsed["summary"]["informational_problem_statuses"] == ""


def test_cinnamon_applet_runtime_parser_normalizes_quoted_codex_history_counts() -> None:
    parsed = parse_runtime_status(
        """
        [Projekt-History]
        codex_history_repo=Demo status=skipped failed="1" total="3"
        """
    )

    assert parsed["status_counts"]["skipped"] == 1
    assert parsed["status_counts"]["warning"] == 1
    assert parsed["summary"]["actionable_problem_statuses"] == "warning:1"


def test_cinnamon_applet_runtime_parser_does_not_hide_unknown_api_or_identity_statuses() -> None:
    parsed = parse_runtime_status(
        """
        [API Keys, Limits und Kosten]
        api_budget=ready_with_error status=ready error=provider_failed
        api_budget=unknown_route status=unknown

        [Tools und Account-Memory]
        account_identity=broken_identity status=unknown error=doctor_failed
        account_identity=known_warning status=warning identity_warnings=1
        """
    )

    assert parsed["summary"]["actionable_problem_status_count"] == 3
    assert parsed["summary"]["actionable_problem_statuses"] == "unknown:2,warning:1"
    assert parsed["summary"]["informational_problem_status_count"] == 1
    assert parsed["summary"]["informational_problem_statuses"] == "warning:1"


def test_cinnamon_applet_runtime_parser_only_suppresses_api_budget_with_matching_route() -> None:
    parsed = parse_runtime_status(
        """
        [API Keys, Limits und Kosten]
        api_budget=orphan status=missing_key error=missing api_key_env=ORPHAN_KEY
        api_budget=matched status=missing_key error=missing api_key_env=MATCHED_KEY
        api_budget=conflict status=missing_key error=missing api_key_env=CONFLICT_KEY
        [LLM-Routen und Backends]
        llm_route=matched status=missing_key error=missing api_key_env=MATCHED_KEY
        llm_route=conflict status=configured
        """
    )

    assert parsed["summary"]["api_actionable_problem_status_count"] == 2
    assert parsed["summary"]["api_informational_status_count"] == 1
    assert parsed["summary"]["actionable_problem_statuses"] == "missing_key:3"
    assert parsed["summary"]["informational_problem_statuses"] == "missing_key:1"


def test_cinnamon_applet_runtime_parser_does_not_hide_unknown_decision_route_behind_fallback() -> None:
    parsed = parse_runtime_status(
        """
        [LLM-Routen und Backends]
        structured_decision=orphan status=enabled route_status=unknown fallback=local
        structured_decision=expected status=enabled route_status=unavailable fallback=local
        """
    )

    assert parsed["summary"]["actionable_problem_statuses"] == "unknown:1"
    assert parsed["summary"]["informational_problem_statuses"] == "unavailable:1"


def test_cinnamon_applet_runtime_parser_does_not_hide_unknown_secondary_status_behind_fallback() -> None:
    parsed = parse_runtime_status(
        """
        [LLM-Routen und Backends]
        structured_decision=mixed status=enabled route_status=unavailable semantic=unknown effective_status=configured fallback=local_ollama
        """
    )

    assert parsed["summary"]["actionable_problem_statuses"] == "unavailable:1,unknown:1"
    assert parsed["summary"]["informational_problem_statuses"] == ""


def test_cinnamon_applet_runtime_parser_blockers_override_informational_special_cases() -> None:
    parsed = parse_runtime_status(
        """
        [LLM-Routen und Backends]
        structured_decision=defaults status=fallback_defaults semantic=unknown
        [Tools und Account-Memory]
        account_identity=mixed status=warning identity_warnings=1 route_status=unknown
        [API Keys, Limits und Kosten]
        codex_usage_account=mixed status=partial semantic=unknown
        """
    )

    assert parsed["summary"]["actionable_problem_statuses"] == "fallback_defaults:1,partial:1,unknown:3,warning:1"
    assert parsed["summary"]["informational_problem_statuses"] == ""


def test_cinnamon_applet_runtime_parser_does_not_hide_explicit_errors_in_fallback_special_cases() -> None:
    parsed = parse_runtime_status(
        """
        [Tools und Account-Memory]
        account_identity=Demo status=warning identity_warnings=1 error=doctor_failed
        [Projekt-History]
        codex_history_repo=Demo repo=TeeBotus status=warning queued=0 failed=0 skipped=1 total=1 problem_statuses=skipped:1 skip_reasons=no_private_route:1 error=dispatcher_failed
        [LLM-Routen und Backends]
        structured_decision=Demo status=enabled route_status=unavailable fallback=local error=provider_failed
        llm_route=generic status=unavailable fallback=local error=provider_failed
        gemini_free_tier_limits status=fallback_defaults error=public_source_incomplete
        """
    )

    assert parsed["summary"]["actionable_problem_statuses"] == "unavailable:2,warning:2"
    assert parsed["summary"]["informational_problem_statuses"] == "fallback_defaults:1"


def test_cinnamon_applet_runtime_parser_suppresses_errors_only_for_verified_fallbacks() -> None:
    parsed = parse_runtime_status(
        """
        [LLM-Routen und Backends]
        llm_route=structured_decision status=unavailable effective_status=configured fallback=local error=HFPoolUnavailable
        llm_route=cheap_fast status=missing_key effective_status=configured fallback=local error=missing api_key_env GROQ_API_KEY
        llm_route=unverified status=unavailable fallback=local error=provider_failed
        llm_route=blocked status=unknown effective_status=configured fallback=local error=provider_failed
        """
    )

    assert parsed["summary"]["actionable_problem_statuses"] == "unavailable:1,unknown:1"
    assert parsed["summary"]["informational_problem_statuses"] == "missing_key:1,unavailable:1"


def test_cinnamon_applet_runtime_parser_does_not_treat_fallback_sentinels_as_configured() -> None:
    parsed = parse_runtime_status(
        """
        [LLM-Routen und Backends]
        structured_decision=none status=enabled route_status=unavailable fallback=none
        structured_decision=disabled status=enabled route_status=unavailable fallback=disabled
        structured_decision=unknown status=enabled route_status=unavailable fallback=unknown
        structured_decision=valid status=enabled route_status=unavailable fallback=local_ollama
        """
    )

    assert parsed["summary"]["actionable_problem_statuses"] == "unavailable:3"
    assert parsed["summary"]["informational_problem_statuses"] == "unavailable:1"


def test_cinnamon_applet_runtime_parser_prioritizes_explicit_fallback_sentinel() -> None:
    parsed = parse_runtime_status(
        """
        [LLM-Routen und Backends]
        structured_decision=disabled status=enabled route_status=unavailable fallback=disabled fallback_model=local_ollama
        structured_decision=none status=enabled route_status=unavailable fallback=none fallback_profile=local_ollama
        structured_decision=profile_none status=enabled route_status=unavailable fallback_profile=none fallback_model=local_ollama
        structured_decision=model_only status=enabled route_status=unavailable fallback_model=local_ollama
        """
    )

    assert parsed["summary"]["actionable_problem_statuses"] == "unavailable:3"
    assert parsed["summary"]["informational_problem_statuses"] == "unavailable:1"


def test_cinnamon_applet_runtime_parser_normalizes_quoted_fallback_sentinels() -> None:
    parsed = parse_runtime_status(
        """
        [LLM-Routen und Backends]
        structured_decision=double status=enabled route_status=unavailable fallback="none"
        structured_decision=single status=enabled route_status=unavailable fallback='disabled'
        structured_decision=backtick status=enabled route_status=unavailable fallback=`unknown`
        structured_decision=valid status=enabled route_status=unavailable fallback="local_ollama"
        """
    )

    assert parsed["summary"]["actionable_problem_statuses"] == "unavailable:3"
    assert parsed["summary"]["informational_problem_statuses"] == "unavailable:1"


def test_cinnamon_applet_runtime_parser_normalizes_quoted_status_values() -> None:
    parsed = parse_runtime_status(
        """
        [LLM-Routen und Backends]
        structured_decision=quoted_unknown status=enabled route_status="unknown" fallback=local_ollama
        structured_decision=quoted_effective status=enabled route_status=unavailable fallback=local_ollama effective_status="configured"
        """
    )

    assert parsed["status_counts"]["unknown"] == 1
    assert parsed["summary"]["actionable_problem_statuses"] == "unknown:1"
    assert parsed["summary"]["informational_problem_statuses"] == "unavailable:1"


def test_cinnamon_applet_runtime_parser_marks_error_without_status_as_problem() -> None:
    parsed = parse_runtime_status(
        """
        [Diagnose]
        service=missing_status error=provider_failed
        service=neutral_error error=none
        service=ok_with_error status=ok error=provider_failed
        service=broken_with_error status=broken error=provider_failed
        """
    )

    assert parsed["status_counts"]["warning"] == 2
    assert parsed["status_counts"]["broken"] == 1
    assert parsed["summary"]["problem_status_count"] == 3
    assert parsed["summary"]["problem_statuses"] == "broken:1,warning:2"


def test_cinnamon_applet_runtime_parser_promotes_codex_history_failure_metadata() -> None:
    parsed = parse_runtime_status(
        """
        [Projekt-History]
        codex_history_repo=Demo repo=neutral status=skipped failed=1 total=3
        codex_history_repo=Demo repo=metadata status=ok failed=0 total=3 problem_statuses=failed:1,skipped:2
        codex_history_repo=Demo repo=queue status=ok failed=0 total=3 problem_statuses=queued:1,skipped:2
        """
    )

    assert parsed["status_counts"]["warning"] == 2
    assert parsed["summary"]["codex_history_problem_status_count"] == 2
    assert parsed["actionable_status_counts"]["warning"] == 2
    assert parsed["informational_status_counts"] == {}


def test_cinnamon_applet_runtime_summary_counts_problem_statuses() -> None:
    parsed = parse_runtime_status(
        """
        [Diagnose]
        identity=Demo status=warning
        llm_route=demo status=degraded
        qdrant=local status=invalid
        qdrant_collection=demo status=schema_mismatch
        memory_index=demo status=config_conflict
        api_budget=demo status=missing_key
        service=demo status=unavailable
        account_memory=demo/abc status=broken
        gemini_free_tier_limits status=fallback_defaults
        gemini_free_tier_limits status=no_limits_found
        gemini_free_tier_limits status=never
        runtime_slot=demo status=not_configured
        structured_decision=demo status=not_applicable
        hf_pool=default status=disabled
        qdrant_collection=ok status=ready
        account_identity=Demo status=unknown error=doctor_unavailable
        structured_decision=demo status=enabled route_status=unavailable fallback=local_ollama
        account_memory_recovery=Demo status=needed command="python3 -m TeeBotus.admin memory-recovery"
        hf_pool=default target=secondary status=cooldown until=2999-01-01T00:00:00+00:00
        codex_usage=local status=ready snapshots=2 stale_hours=48
        memory_index=semantic_down backend=keyword status=ready semantic=unavailable
        memory_index=semantic_bad_backend backend=keyword status=ready semantic=unsupported
        """
    )

    assert parsed["summary"]["problem_status_count"] == 18
    assert parsed["summary"]["problem_statuses"] == (
        "broken:1,config_conflict:1,cooldown:1,degraded:1,fallback_defaults:1,invalid:1,"
        "missing_key:1,needed:1,never:1,no_limits_found:1,schema_mismatch:1,stale:1,unavailable:3,"
        "unknown:1,unsupported:1,warning:1"
    )
    assert parsed["status_counts"]["enabled"] == 1
    assert parsed["summary"]["qdrant_problem_status_count"] == 2
    assert parsed["status_counts"]["not_configured"] == 1
    assert parsed["status_counts"]["not_applicable"] == 1
    assert parsed["status_counts"]["disabled"] == 1
    assert parsed["status_counts"]["ready"] == 4


def test_cinnamon_applet_runtime_parser_counts_semantic_secondary_status() -> None:
    parsed = parse_runtime_status(
        """
        [Memory und semantische Suche]
        memory_index=missing_vector backend=keyword status=ready semantic=unavailable
        memory_index=unsupported_backend backend=keyword status=ready semantic=unsupported
        memory_index=disabled_profile backend=keyword status=disabled semantic=ready
        memory_index=healthy_profile backend=keyword status=ready semantic=ready
        """
    )

    assert parsed["summary"]["memory_semantic_ready"] == 1
    assert parsed["summary"]["problem_status_count"] == 2
    assert parsed["summary"]["problem_statuses"] == "unavailable:1,unsupported:1"
    assert parsed["status_counts"]["ready"] == 3
    assert parsed["status_counts"]["disabled"] == 1
    assert parsed["status_counts"]["unavailable"] == 1
    assert parsed["status_counts"]["unsupported"] == 1


def test_cinnamon_applet_runtime_parser_classifies_qdrant_secondary_status() -> None:
    parsed = parse_runtime_status(
        """
        [Memory und semantische Suche]
        qdrant_collection=teebotus_user_memory status=ready semantic=unavailable
        qdrant_collection=teebotus_bibliothekar_chunks status=unreachable semantic=unsupported
        """
    )

    assert parsed["summary"]["qdrant_problem_status_count"] == 3
    assert parsed["summary"]["problem_status_count"] == 3
    assert parsed["summary"]["problem_statuses"] == "unavailable:1,unreachable:1,unsupported:1"


def test_cinnamon_applet_runtime_parser_normalizes_structured_status_case() -> None:
    parsed = parse_runtime_status(
        """
        [API Keys, Limits und Kosten]
        api_budget=demo status=WARNING

        [Memory und semantische Suche]
        qdrant_collection=teebotus_user_memory status=READY
        memory_index=demo status=READY semantic=UNAVAILABLE
        """
    )

    assert parsed["summary"]["problem_status_count"] == 2
    assert parsed["summary"]["problem_statuses"] == "unavailable:1,warning:1"
    assert parsed["summary"]["qdrant_ready_collections"] == 1
    assert parsed["summary"]["memory_semantic_ready"] == 0


def test_cinnamon_applet_runtime_parser_does_not_count_ready_status_with_error() -> None:
    parsed = parse_runtime_status(
        """
        [Memory und semantische Suche]
        qdrant_collection=teebotus_user_memory status=READY error=stale collection metadata
        memory_index=demo status=READY semantic=READY error=qdrant probe failed
        """
    )

    assert parsed["summary"]["qdrant_collections"] == 1
    assert parsed["summary"]["qdrant_ready_collections"] == 0
    assert parsed["summary"]["memory_semantic_ready"] == 0
    assert parsed["summary"]["problem_status_count"] == 2
    assert parsed["summary"]["problem_statuses"] == "warning:2"
    assert parsed["summary"]["qdrant_problem_status_count"] == 1


def test_cinnamon_applet_runtime_parser_marks_any_ready_status_with_error() -> None:
    parsed = parse_runtime_status(
        """
        [Lokale Dienste]
        service=demo status=READY error=worker returned an error
        memory_index=demo status=READY semantic=UNAVAILABLE error=qdrant probe failed
        """
    )

    assert parsed["summary"]["problem_status_count"] == 2
    assert parsed["summary"]["problem_statuses"] == "unavailable:1,warning:1"


def test_cinnamon_applet_js_parser_normalizes_structured_status_case() -> None:
    fields = _run_js_parse_fields("route_status=UNAVAILABLE status=WARNING semantic=READY")
    result = _run_js_applet_expression(
        "({problem: applet._lineHasProblemStatus({status: 'WARNING', route_status: 'UNAVAILABLE'}), word: applet._statusWord('WARNING')})"
    )

    assert fields == {"route_status": "unavailable", "status": "warning", "semantic": "ready"}
    assert result == {"problem": True, "word": "Warnung"}


def test_cinnamon_applet_js_health_helpers_normalize_quoted_status_and_numbers() -> None:
    result = _run_js_applet_expression(
        "({"
        "quotedStatus: applet._lineHasProblemStatus(applet._parseFields('route_status=\"unknown\" status=enabled')),"
        "quotedStale: applet._codexUsageIsStale(applet._parseFields('codex_usage=local status=ready stale_hours=\"24\"')),"
        "quotedNumber: applet._nonNegativeInt('\"12\"', -1),"
        "quotedFlag: applet._statusFlagIsSet('\"warning\"')"
        "})"
    )

    assert result == {
        "quotedStatus": True,
        "quotedStale": True,
        "quotedNumber": 12,
        "quotedFlag": True,
    }


def test_cinnamon_applet_js_marks_ready_memory_lines_with_errors_as_problems() -> None:
    result = _run_js_applet_expression(
        "({qdrant: applet._lineHasProblemStatus(applet._parseFields('qdrant_collection=demo status=READY error=probe failed')), "
        "semantic: applet._lineHasProblemStatus(applet._parseFields('memory_index=demo status=READY semantic=READY error=probe failed')), "
        "healthy: applet._lineHasProblemStatus(applet._parseFields('memory_index=demo status=READY semantic=READY'))})"
    )

    assert result == {"qdrant": True, "semantic": True, "healthy": False}


def test_cinnamon_applet_js_marks_any_ready_line_with_error_as_problem() -> None:
    result = _run_js_applet_expression(
        "applet._lineHasProblemStatus(applet._parseFields('service=demo status=READY error=worker failed'))"
    )

    assert result is True


def test_cinnamon_applet_js_marks_error_without_status_as_problem() -> None:
    result = _run_js_applet_expression(
        "applet._lineHasProblemStatus(applet._parseFields('service=demo error=provider_failed'))"
    )

    assert result is True


def test_cinnamon_applet_runtime_parser_counts_models_feed_secondary_status() -> None:
    parsed = parse_runtime_status(
        """
        [LLM-Routen und Backends]
        hf_pool=default target=primary status=configured model=provider/model models_feed=unavailable context_length=8192
        hf_pool=default target=secondary status=unavailable model=provider/model models_feed=unavailable
        hf_pool=default target=healthy status=configured model=provider/model models_feed=ok
        """
    )

    assert parsed["summary"]["llm_problem_status_count"] == 2
    assert parsed["summary"]["problem_status_count"] == 2
    assert parsed["summary"]["problem_statuses"] == "unavailable:2"
    assert parsed["status_counts"]["configured"] == 2
    assert parsed["status_counts"]["unavailable"] == 2
    assert "ok" not in parsed["status_counts"]


def test_cinnamon_applet_runtime_parser_counts_secondary_status_after_free_text_error() -> None:
    parsed = parse_runtime_status(
        """
        [LLM-Routen und Backends]
        structured_decision=demo status=enabled error=provider down route_status=unavailable fallback=local
        hf_pool=default status=configured error=models feed down models_feed=unavailable
        structured_decision=demo/telegram status=enabled route_status=unavailable route_error=provider status=500 fallback=local_ollama fallback_model=llama3 remote_fallback=enabled warning=retry

        [Memory und semantische Suche]
        memory_index=demo status=ready error=qdrant down semantic=unavailable
        """
    )

    route_fields = cinnamon_applet._parse_status_fields(parsed["sections"]["LLM-Routen und Backends"][0])
    hf_fields = cinnamon_applet._parse_status_fields(parsed["sections"]["LLM-Routen und Backends"][1])
    route_error_fields = cinnamon_applet._parse_status_fields(parsed["sections"]["LLM-Routen und Backends"][2])
    memory_fields = cinnamon_applet._parse_status_fields(parsed["sections"]["Memory und semantische Suche"][0])

    assert route_fields["error"] == "provider down"
    assert route_fields["route_status"] == "unavailable"
    assert route_fields["fallback"] == "local"
    assert hf_fields["error"] == "models feed down"
    assert hf_fields["models_feed"] == "unavailable"
    assert route_error_fields["route_error"] == "provider status=500"
    assert route_error_fields["fallback"] == "local_ollama"
    assert route_error_fields["fallback_model"] == "llama3"
    assert route_error_fields["remote_fallback"] == "enabled"
    assert route_error_fields["warning"] == "retry"
    assert memory_fields["error"] == "qdrant down"
    assert memory_fields["semantic"] == "unavailable"
    assert parsed["summary"]["llm_problem_status_count"] == 4
    assert parsed["summary"]["memory_problem_status_count"] == 1
    assert parsed["summary"]["problem_status_count"] == 5
    assert parsed["summary"]["problem_statuses"] == "unavailable:4,warning:1"
    assert parsed["status_counts"]["enabled"] == 2
    assert parsed["status_counts"]["configured"] == 1
    assert parsed["status_counts"]["ready"] == 1
    assert parsed["status_counts"]["unavailable"] == 4
    assert parsed["status_counts"]["warning"] == 1


def test_cinnamon_applet_runtime_parser_deduplicates_same_problem_status_per_line() -> None:
    parsed = parse_runtime_status(
        """
        [LLM-Routen und Backends]
        structured_decision=demo status=enabled route_status=warning warning=fallback
        hf_pool=default status=configured models_feed=warning warning=fallback
        llm_route=demo status=broken route_status=unavailable warning=fallback

        [Memory und semantische Suche]
        memory_index=demo status=ready semantic=warning warning=fallback
        """
    )

    assert parsed["status_counts"]["warning"] == 4
    assert parsed["status_counts"]["broken"] == 1
    assert parsed["status_counts"]["unavailable"] == 1
    assert parsed["summary"]["problem_status_count"] == 6
    assert parsed["summary"]["problem_statuses"] == "broken:1,unavailable:1,warning:4"


def test_cinnamon_applet_runtime_parser_separates_actions_from_fallback_information() -> None:
    parsed = parse_runtime_status(
        """
[LLM-Routen und Backends]
llm_route=structured status=unavailable fallback=local fallback_model=ollama effective_status=configured
llm_route=hard status=missing_key error=missing_key
[API Keys, Limits und Kosten]
api_budget=hard status=missing_key error=missing_key
structured_decision=Demo/telegram:1 status=enabled route_status=unavailable fallback=local
gemini_free_tier_limits status=fallback_defaults error=public_source_incomplete
codex_usage_account=Demo status=partial five_hour=none weekly=50
[Projekt-History]
codex_history=Legacy status=warning queued=3 failed=0 total=3
codex_history_repo=Legacy repo=TeeBotus status=warning queued=3 failed=0 total=3
codex_history=Logger status=warning queued=0 failed=0 total=10
[Tools und Account-Memory]
account_identity=Demo status=warning identity_warnings=2
account_identity_warning=Demo code=account_store_integrity_warning message=cleanup_needed
account_identity_warning=Demo code=runtime_channel_without_identity channel=signal message=link_needed
"""
    )

    assert parsed["summary"]["problem_status_count"] == 12
    assert parsed["summary"]["actionable_problem_status_count"] == 5
    assert parsed["summary"]["actionable_problem_statuses"] == "missing_key:1,warning:4"
    assert parsed["summary"]["informational_problem_status_count"] == 7
    assert parsed["summary"]["informational_problem_statuses"] == (
        "fallback_defaults:1,missing_key:1,partial:1,unavailable:2,warning:2"
    )
    assert parsed["summary"]["llm_actionable_problem_status_count"] == 1
    assert parsed["summary"]["llm_informational_status_count"] == 1
    assert parsed["summary"]["api_actionable_problem_status_count"] == 0
    assert parsed["summary"]["api_informational_status_count"] == 4
    assert parsed["summary"]["codex_history_actionable_problem_status_count"] == 2
    assert parsed["summary"]["codex_history_informational_status_count"] == 1
    assert parsed["summary"]["memory_actionable_problem_status_count"] == 2
    assert parsed["summary"]["memory_informational_status_count"] == 1


def test_cinnamon_applet_runtime_parser_does_not_hide_broken_route_behind_fallback() -> None:
    parsed = parse_runtime_status(
        """
[LLM-Routen und Backends]
structured_decision=Demo status=broken route_status=broken fallback=local_ollama fallback_model=ollama_chat/llama3.2:3b
llm_route=Demo status=broken effective_status=configured fallback=local_ollama
[Projekt-History]
codex_history=Logger status=warning queued=0 failed=0 total=4
"""
    )

    assert parsed["summary"]["actionable_problem_statuses"] == "broken:2,warning:1"
    assert parsed["summary"]["informational_problem_statuses"] == ""


def test_cinnamon_applet_runtime_parser_keeps_fresh_codex_usage_neutral() -> None:
    parsed = parse_runtime_status(
        """
        [API Keys, Limits und Kosten]
        codex_usage=local status=ready snapshots=2 stale_hours=23
        """
    )

    assert parsed["status_counts"]["ready"] == 1
    assert "stale" not in parsed["status_counts"]
    assert parsed["summary"]["problem_status_count"] == 0
    assert parsed["summary"]["problem_statuses"] == ""


def test_cinnamon_applet_runtime_parser_deduplicates_codex_usage_stale_status() -> None:
    parsed = parse_runtime_status(
        """
        [API Keys, Limits und Kosten]
        codex_usage=local status=stale snapshots=2 stale_hours=48
        """
    )

    assert parsed["status_counts"]["stale"] == 1
    assert parsed["summary"]["api_problem_status_count"] == 1
    assert parsed["summary"]["problem_status_count"] == 1
    assert parsed["summary"]["problem_statuses"] == "stale:1"


def test_cinnamon_applet_runtime_parser_summarizes_codex_history() -> None:
    parsed = parse_runtime_status(
        """
        [Projekt-History]
        codex_history=Depressionsbot status=warning queued=1 failed=1 total=3 latest_repo=TeeBotus latest_prefix=v1.8.0_#0003 latest_kind=codex_graph_artifact run_summaries=1 strategies=1 graphs=1 other=0
        codex_history_repo=Depressionsbot repo=TeeBotus status=warning queued=1 failed=1 total=3 run_summaries=1 strategies=1 graphs=1 other=0 latest_prefix=v1.8.0_#0003 latest_status=queued latest_kind=codex_graph_artifact latest_title=Noch_offen
        codex_history=Bote_der_Wahrheit status=ok queued=0 failed=0 total=2 latest_repo=Docs latest_prefix=v1.0.0_#0002 latest_kind=codex_run_summary run_summaries=2 strategies=0 graphs=0 other=0
        codex_history_repo=Bote_der_Wahrheit repo=Docs status=ok queued=0 failed=0 total=2 run_summaries=2 strategies=0 graphs=0 other=0 latest_prefix=v1.0.0_#0002 latest_status=accepted latest_kind=codex_run_summary latest_title=Dokumentiert
        """
    )

    assert parsed["summary"]["codex_history_instances"] == 2
    assert parsed["summary"]["codex_history_repos"] == 2
    assert parsed["summary"]["codex_history_run_summaries"] == 3
    assert parsed["summary"]["codex_history_strategies"] == 1
    assert parsed["summary"]["codex_history_graphs"] == 1
    assert parsed["summary"]["codex_history_other"] == 0
    assert parsed["summary"]["codex_history_problem_status_count"] == 2
    assert parsed["summary"]["codex_history"] == (
        "codex_history=Depressionsbot status=warning queued=1 failed=1 total=3 "
        "latest_repo=TeeBotus latest_prefix=v1.8.0_#0003 latest_kind=codex_graph_artifact "
        "run_summaries=1 strategies=1 graphs=1 other=0"
    )
    assert parsed["status_counts"]["warning"] == 2
    assert parsed["status_counts"]["ok"] == 2


def test_cinnamon_applet_runtime_parser_prefers_later_codex_history_problem() -> None:
    parsed = parse_runtime_status(
        """
        [Projekt-History]
        codex_history=Healthy status=ok queued=0 failed=0 total=1
        codex_history=Broken status=broken queued=1 failed=1 total=2
        """
    )

    assert parsed["summary"]["codex_history"] == "codex_history=Broken status=broken queued=1 failed=1 total=2"


def test_cinnamon_applet_runtime_parser_prefers_more_severe_codex_history_problem() -> None:
    parsed = parse_runtime_status(
        """
        [Projekt-History]
        codex_history=Warning status=warning queued=1 failed=0 total=2
        codex_history=Broken status=broken queued=1 failed=1 total=2
        """
    )

    assert parsed["summary"]["codex_history"] == "codex_history=Broken status=broken queued=1 failed=1 total=2"


def test_cinnamon_applet_payload_ok_reflects_runtime_health(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        cinnamon_applet,
        "_runtime_status",
        lambda *_args, **_kwargs: {"returncode": 0, "stdout": "[Diagnose]\nllm_route=demo status=warning\n", "stderr": ""},
    )
    monkeypatch.setattr(cinnamon_applet, "_systemd_unit_status", lambda _unit: {"active_state": "active", "sub_state": "running", "returncode": 0})
    monkeypatch.setattr(cinnamon_applet, "_qdrant_status", lambda _url: {"url": "http://127.0.0.1:6333", "collections": {}, "error": ""})
    monkeypatch.setattr(cinnamon_applet, "_repo_status", lambda _root: {"path": str(tmp_path), "short_commit": "abc1234"})

    payload = build_status_payload(
        repo_root=tmp_path,
        channels="telegram,signal",
        unit_name="teebotus.service",
        python_executable="/usr/bin/python3",
        timeout_seconds=1,
    )

    assert payload["command_ok"] is True
    assert payload["ok"] is False
    assert payload["health"] == {
        "classification_version": 2,
        "status": "warning",
        "command_ok": True,
        "command_problem_count": 0,
        "problem_status_count": 1,
        "problem_statuses": "warning:1",
        "actionable_problem_count": 1,
        "actionable_problem_statuses": "warning:1",
        "informational_problem_count": 0,
        "informational_problem_statuses": "",
        "runtime_problem_count": 1,
        "qdrant_problem_count": 0,
        "qdrant_probe_problem_count": 0,
        "qdrant_runtime_problem_count": 0,
        "qdrant_unit_problem_count": 0,
        "total_problem_count": 1,
        "severe_status_count": 0,
    }


def test_cinnamon_applet_health_summary_does_not_hide_stale_v2_actionable_count() -> None:
    health = cinnamon_applet._health_summary(
        command_ok=True,
        parsed_runtime={
            "summary": {
                "problem_status_count": 0,
                "actionable_problem_status_count": 0,
                "informational_problem_status_count": 0,
            },
            "status_counts": {"warning": 1},
            "actionable_status_counts": {"warning": 1},
            "informational_status_counts": {},
        },
        qdrant={"collections": {}, "error": ""},
        qdrant_unit={"active_state": "active", "sub_state": "running", "returncode": 0},
    )

    assert health["status"] == "warning"
    assert health["problem_status_count"] == 1
    assert health["actionable_problem_count"] == 1
    assert health["runtime_problem_count"] == 1
    assert health["total_problem_count"] == 1


def test_cinnamon_applet_health_summary_uses_declared_actionable_statuses_for_severity() -> None:
    health = cinnamon_applet._health_summary(
        command_ok=True,
        parsed_runtime={
            "summary": {
                "problem_status_count": 0,
                "problem_statuses": "",
                "actionable_problem_status_count": 0,
                "actionable_problem_statuses": "broken:1",
                "informational_problem_status_count": 0,
            },
            "status_counts": {},
            "actionable_status_counts": {},
            "informational_status_counts": {},
        },
        qdrant={"collections": {}, "error": ""},
        qdrant_unit={"active_state": "active", "sub_state": "running", "returncode": 0},
    )

    assert health["status"] == "broken"
    assert health["actionable_problem_count"] == 1
    assert health["runtime_problem_count"] == 1
    assert health["total_problem_count"] == 1
    assert health["severe_status_count"] == 1


def test_cinnamon_applet_health_summary_classifies_uncovered_problem_statuses_actionable() -> None:
    health = cinnamon_applet._health_summary(
        command_ok=True,
        parsed_runtime={
            "summary": {
                "problem_status_count": 1,
                "problem_statuses": "broken:1",
                "actionable_problem_status_count": 0,
                "actionable_problem_statuses": "",
                "informational_problem_status_count": 0,
                "informational_problem_statuses": "",
            },
            "status_counts": {"broken": 1},
            "actionable_status_counts": {},
            "informational_status_counts": {},
        },
        qdrant={"collections": {}, "error": ""},
        qdrant_unit={"active_state": "active", "sub_state": "running", "returncode": 0},
    )

    assert health["status"] == "broken"
    assert health["problem_statuses"] == "broken:1"
    assert health["actionable_problem_statuses"] == "broken:1"
    assert health["actionable_problem_count"] == 1
    assert health["runtime_problem_count"] == 1
    assert health["total_problem_count"] == 1
    assert health["severe_status_count"] == 1


def test_cinnamon_applet_health_summary_clamps_negative_qdrant_runtime_count() -> None:
    health = cinnamon_applet._health_summary(
        command_ok=True,
        parsed_runtime={
            "summary": {
                "qdrant_actionable_problem_status_count": -5,
                "actionable_problem_status_count": 0,
            },
            "status_counts": {},
            "actionable_status_counts": {},
            "informational_status_counts": {},
        },
        qdrant={"collections": {}, "error": ""},
        qdrant_unit={"active_state": "active", "sub_state": "running", "returncode": 0},
    )

    assert health["status"] == "ok"
    assert health["qdrant_runtime_problem_count"] == 0
    assert health["runtime_problem_count"] == 0
    assert health["total_problem_count"] == 0


def test_cinnamon_applet_payload_rejects_empty_runtime_output(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cinnamon_applet, "_runtime_status", lambda *_args, **_kwargs: {"returncode": 0, "stdout": "  \n", "stderr": ""})
    monkeypatch.setattr(cinnamon_applet, "_systemd_unit_status", lambda _unit: {"active_state": "active", "sub_state": "running", "returncode": 0})
    monkeypatch.setattr(cinnamon_applet, "_qdrant_status", lambda _url: {"url": "http://127.0.0.1:6333", "collections": {}, "error": ""})
    monkeypatch.setattr(cinnamon_applet, "_repo_status", lambda _root: {"path": str(tmp_path), "short_commit": "abc1234"})

    payload = build_status_payload(
        repo_root=tmp_path,
        channels="telegram,signal",
        unit_name="teebotus.service",
        python_executable="/usr/bin/python3",
        timeout_seconds=1,
    )

    assert payload["command_ok"] is False
    assert payload["ok"] is False
    assert payload["health"]["status"] == "broken"
    assert payload["health"]["command_problem_count"] == 1
    assert payload["health"]["total_problem_count"] == 1


def test_cinnamon_applet_payload_rejects_unstructured_runtime_output(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        cinnamon_applet,
        "_runtime_status",
        lambda *_args, **_kwargs: {"returncode": 0, "stdout": "runtime unavailable\n", "stderr": ""},
    )
    monkeypatch.setattr(cinnamon_applet, "_systemd_unit_status", lambda _unit: {"active_state": "active", "sub_state": "running", "returncode": 0})
    monkeypatch.setattr(cinnamon_applet, "_qdrant_status", lambda _url: {"url": "http://127.0.0.1:6333", "collections": {}, "error": ""})
    monkeypatch.setattr(cinnamon_applet, "_repo_status", lambda _root: {"path": str(tmp_path), "short_commit": "abc1234"})

    payload = build_status_payload(
        repo_root=tmp_path,
        channels="telegram,signal",
        unit_name="teebotus.service",
        python_executable="/usr/bin/python3",
        timeout_seconds=1,
    )

    assert payload["command_ok"] is False
    assert payload["ok"] is False
    assert payload["health"]["status"] == "broken"
    assert payload["health"]["command_problem_count"] == 1


def test_cinnamon_applet_runtime_status_structure_requires_section_and_fields() -> None:
    assert cinnamon_applet._runtime_status_output_is_structured("[Start]\nstatus=ready\n") is True
    assert cinnamon_applet._runtime_status_output_is_structured("[Start]\n") is False
    assert cinnamon_applet._runtime_status_output_is_structured("[Start]\nfoo=bar\n") is False
    assert cinnamon_applet._runtime_status_output_is_structured("runtime unavailable\n") is False


def test_cinnamon_applet_payload_rejects_boolean_runtime_returncode(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        cinnamon_applet,
        "_runtime_status",
        lambda *_args, **_kwargs: {"returncode": False, "stdout": "[Diagnose]\nservice=demo status=ready\n", "stderr": ""},
    )
    monkeypatch.setattr(cinnamon_applet, "_systemd_unit_status", lambda _unit: {"active_state": "active", "sub_state": "running", "returncode": 0})
    monkeypatch.setattr(cinnamon_applet, "_qdrant_status", lambda _url: {"url": "http://127.0.0.1:6333", "collections": {}, "error": ""})
    monkeypatch.setattr(cinnamon_applet, "_repo_status", lambda _root: {"path": str(tmp_path), "short_commit": "abc1234"})

    payload = build_status_payload(
        repo_root=tmp_path,
        channels="telegram,signal",
        unit_name="teebotus.service",
        python_executable="/usr/bin/python3",
        timeout_seconds=1,
    )

    assert payload["command_ok"] is False
    assert payload["ok"] is False
    assert payload["health"]["status"] == "broken"
    assert payload["health"]["command_problem_count"] == 1
    assert payload["health"]["total_problem_count"] == 1


def test_cinnamon_applet_payload_health_reports_command_and_qdrant_failures(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cinnamon_applet, "_runtime_status", lambda *_args, **_kwargs: {"returncode": 124, "stdout": "", "stderr": "timeout"})
    monkeypatch.setattr(cinnamon_applet, "_systemd_unit_status", lambda unit: {"active_state": "missing", "sub_state": "dead", "returncode": 0} if unit == "teebotus.service" else {"active_state": "active", "sub_state": "running", "returncode": 0})
    monkeypatch.setattr(
        cinnamon_applet,
        "_qdrant_status",
        lambda _url: {
            "url": "http://127.0.0.1:6333",
            "collections": {"teebotus_user_memory": {"status": "unreachable", "count": 0, "error": "connection refused"}},
            "error": "teebotus_user_memory: connection refused",
        },
    )
    monkeypatch.setattr(cinnamon_applet, "_repo_status", lambda _root: {"path": str(tmp_path), "short_commit": "abc1234"})

    payload = build_status_payload(
        repo_root=tmp_path,
        channels="telegram,signal",
        unit_name="teebotus.service",
        python_executable="/usr/bin/python3",
        timeout_seconds=1,
    )

    assert payload["command_ok"] is False
    assert payload["ok"] is False
    assert payload["health"]["status"] == "broken"
    assert payload["health"]["command_problem_count"] == 1
    assert payload["health"]["qdrant_problem_count"] == 1
    assert payload["health"]["qdrant_probe_problem_count"] == 1
    assert payload["health"]["qdrant_runtime_problem_count"] == 0
    assert payload["health"]["qdrant_unit_problem_count"] == 0
    assert payload["health"]["total_problem_count"] == 2


def test_cinnamon_applet_payload_rejects_failed_systemd_query_with_active_output(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        cinnamon_applet,
        "_runtime_status",
        lambda *_args, **_kwargs: {"returncode": 0, "stdout": "", "stderr": ""},
    )
    monkeypatch.setattr(
        cinnamon_applet,
        "_systemd_unit_status",
        lambda unit: {
            "name": unit,
            "active_state": "active",
            "sub_state": "running",
            "returncode": 1,
            "stderr": "systemctl query failed",
        },
    )
    monkeypatch.setattr(cinnamon_applet, "_qdrant_status", lambda _url: {"url": "http://127.0.0.1:6333", "collections": {}, "error": ""})
    monkeypatch.setattr(cinnamon_applet, "_repo_status", lambda _root: {"path": str(tmp_path), "short_commit": "abc1234"})

    payload = build_status_payload(
        repo_root=tmp_path,
        channels="telegram,signal",
        unit_name="teebotus.service",
        python_executable="/usr/bin/python3",
        timeout_seconds=1,
    )

    assert payload["command_ok"] is False
    assert payload["health"]["status"] == "broken"
    assert payload["health"]["command_problem_count"] == 1
    assert payload["health"]["qdrant_unit_problem_count"] == 1
    assert payload["health"]["total_problem_count"] == 2


def test_cinnamon_applet_rejects_malformed_systemd_returncode() -> None:
    assert cinnamon_applet._status_query_ok({"active_state": "active", "returncode": "0"}) is True
    assert cinnamon_applet._status_query_ok({"active_state": "active", "returncode": "1abc"}) is False
    assert cinnamon_applet._status_query_ok({"active_state": "active", "returncode": True}) is False
    assert cinnamon_applet._status_query_ok({"active_state": "active"}) is False


def test_cinnamon_applet_safe_int_rejects_boolean_and_overflow_values() -> None:
    assert cinnamon_applet._safe_int(True, 7) == 7
    assert cinnamon_applet._safe_int(False, 7) == 7
    assert cinnamon_applet._safe_int(float("inf"), 7) == 7
    assert cinnamon_applet._safe_int(float("-inf"), 7) == 7
    assert cinnamon_applet._safe_int("12", 7) == 12
    assert cinnamon_applet._safe_int('"12"', 7) == 12
    assert cinnamon_applet._safe_int("'12'", 7) == 12
    assert cinnamon_applet._safe_int("`12`", 7) == 12


def test_cinnamon_applet_rejects_active_unit_with_failed_substate() -> None:
    unit = {"active_state": "active", "sub_state": "failed", "returncode": 0}
    assert cinnamon_applet._unit_state_ok(unit) is False
    assert cinnamon_applet._unit_problem_count(unit) == 1


def test_cinnamon_applet_rejects_active_unit_without_confirmed_substate() -> None:
    assert cinnamon_applet._unit_state_ok({"active_state": "active", "sub_state": ""}) is False
    assert cinnamon_applet._unit_state_ok({"active_state": "active", "sub_state": "unknown"}) is False
    assert cinnamon_applet._unit_state_ok({"active_state": "active", "sub_state": "typo"}) is False
    assert cinnamon_applet._unit_state_ok({"active_state": "unknown", "sub_state": "unknown"}) is False
    assert cinnamon_applet._unit_state_ok({"active_state": "unknown", "sub_state": "failed"}) is False
    assert cinnamon_applet._unit_state_ok({"active_state": "unknown", "sub_state": "running"}) is False
    for sub_state in CONFIRMED_ACTIVE_SUBSTATES:
        assert cinnamon_applet._unit_state_ok({"active_state": "active", "sub_state": sub_state}) is True


def test_cinnamon_applet_rejects_successful_systemd_query_without_states(monkeypatch) -> None:
    monkeypatch.setattr(
        cinnamon_applet,
        "_run",
        lambda *_args, **_kwargs: {"returncode": 0, "stdout": "", "stderr": ""},
    )

    unit = cinnamon_applet._systemd_unit_status("teebotus.service")

    assert unit["active_state"] == "unknown"
    assert unit["sub_state"] == "unknown"
    assert cinnamon_applet._status_query_ok(unit) is True
    assert cinnamon_applet._unit_problem_count(unit) == 1


def test_cinnamon_applet_empty_systemd_unit_is_not_healthy() -> None:
    unit = cinnamon_applet._systemd_unit_status("")
    assert unit["returncode"] != 0
    assert cinnamon_applet._status_query_ok(unit) is False
    assert cinnamon_applet._unit_problem_count(unit) == 1


def test_cinnamon_applet_payload_counts_command_failure_without_other_problems(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cinnamon_applet, "_runtime_status", lambda *_args, **_kwargs: {"returncode": 124, "stdout": "", "stderr": "timeout"})
    monkeypatch.setattr(cinnamon_applet, "_systemd_unit_status", lambda _unit: {"active_state": "active", "sub_state": "running", "returncode": 0})
    monkeypatch.setattr(cinnamon_applet, "_qdrant_status", lambda _url: {"url": "http://127.0.0.1:6333", "collections": {}, "error": ""})
    monkeypatch.setattr(cinnamon_applet, "_repo_status", lambda _root: {"path": str(tmp_path), "short_commit": "abc1234"})

    payload = build_status_payload(
        repo_root=tmp_path,
        channels="telegram,signal",
        unit_name="teebotus.service",
        python_executable="/usr/bin/python3",
        timeout_seconds=1,
    )

    assert payload["command_ok"] is False
    assert payload["ok"] is False
    assert payload["health"]["status"] == "broken"
    assert payload["health"]["command_problem_count"] == 1
    assert payload["health"]["problem_status_count"] == 0
    assert payload["health"]["qdrant_problem_count"] == 0
    assert payload["health"]["total_problem_count"] == 1


def test_cinnamon_applet_runtime_status_splits_python_command(monkeypatch, tmp_path) -> None:
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **_kwargs: object) -> dict[str, object]:
        calls.append(argv)
        return {"returncode": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(cinnamon_applet, "_run", fake_run)

    result = cinnamon_applet._runtime_status(tmp_path, channels="telegram,signal", python_executable="/usr/bin/python3 -B", timeout_seconds=1)

    assert result["returncode"] == 0
    assert calls == [["/usr/bin/python3", "-B", "-m", "TeeBotus", "--runtime-status", "--channels", "telegram,signal"]]


def test_cinnamon_applet_runtime_status_clamps_timeout(monkeypatch, tmp_path) -> None:
    timeouts: list[int] = []

    def fake_run(_argv: list[str], **kwargs: object) -> dict[str, object]:
        timeouts.append(int(kwargs["timeout_seconds"]))
        return {"returncode": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(cinnamon_applet, "_run", fake_run)

    cinnamon_applet._runtime_status(tmp_path, channels="telegram", python_executable="/usr/bin/python3", timeout_seconds=999999)
    cinnamon_applet._runtime_status(tmp_path, channels="telegram", python_executable="/usr/bin/python3", timeout_seconds=0)

    assert timeouts == [cinnamon_applet.MAX_STATUS_TIMEOUT_SECONDS, 1]


def test_cinnamon_applet_payload_counts_qdrant_unit_health(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cinnamon_applet, "_runtime_status", lambda *_args, **_kwargs: {"returncode": 0, "stdout": "[Diagnose]\nservice=demo status=ready\n", "stderr": ""})
    monkeypatch.setattr(cinnamon_applet, "_systemd_unit_status", lambda unit: {"active_state": "active", "sub_state": "running", "returncode": 0} if unit == "teebotus.service" else {"active_state": "failed", "sub_state": "failed", "returncode": 0})
    monkeypatch.setattr(cinnamon_applet, "_qdrant_status", lambda _url: {"url": "http://127.0.0.1:6333", "collections": {}, "error": ""})
    monkeypatch.setattr(cinnamon_applet, "_repo_status", lambda _root: {"path": str(tmp_path), "short_commit": "abc1234"})

    payload = build_status_payload(
        repo_root=tmp_path,
        channels="telegram,signal",
        unit_name="teebotus.service",
        python_executable="/usr/bin/python3",
        timeout_seconds=1,
    )

    assert payload["command_ok"] is True
    assert payload["ok"] is False
    assert payload["health"]["status"] == "warning"
    assert payload["health"]["command_problem_count"] == 0
    assert payload["health"]["problem_status_count"] == 0
    assert payload["health"]["qdrant_problem_count"] == 1
    assert payload["health"]["qdrant_probe_problem_count"] == 0
    assert payload["health"]["qdrant_runtime_problem_count"] == 0
    assert payload["health"]["qdrant_unit_problem_count"] == 1
    assert payload["health"]["total_problem_count"] == 1


def test_cinnamon_applet_payload_total_problems_includes_qdrant_health(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cinnamon_applet, "_runtime_status", lambda *_args, **_kwargs: {"returncode": 0, "stdout": "[Diagnose]\nservice=demo status=ready\n", "stderr": ""})
    monkeypatch.setattr(cinnamon_applet, "_systemd_unit_status", lambda _unit: {"active_state": "active", "sub_state": "running", "returncode": 0})
    monkeypatch.setattr(
        cinnamon_applet,
        "_qdrant_status",
        lambda _url: {
            "url": "http://127.0.0.1:6333",
            "collections": {"teebotus_user_memory": {"status": "unreachable", "count": 0, "error": "connection refused"}},
            "error": "",
        },
    )
    monkeypatch.setattr(cinnamon_applet, "_repo_status", lambda _root: {"path": str(tmp_path), "short_commit": "abc1234"})

    payload = build_status_payload(
        repo_root=tmp_path,
        channels="telegram,signal",
        unit_name="teebotus.service",
        python_executable="/usr/bin/python3",
        timeout_seconds=1,
    )

    assert payload["command_ok"] is True
    assert payload["ok"] is False
    assert payload["health"]["status"] == "warning"
    assert payload["health"]["command_problem_count"] == 0
    assert payload["health"]["problem_status_count"] == 0
    assert payload["health"]["qdrant_problem_count"] == 1
    assert payload["health"]["qdrant_probe_problem_count"] == 1
    assert payload["health"]["qdrant_runtime_problem_count"] == 0
    assert payload["health"]["qdrant_unit_problem_count"] == 0
    assert payload["health"]["total_problem_count"] == 1


def test_cinnamon_applet_payload_counts_malformed_qdrant_collection_health(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cinnamon_applet, "_runtime_status", lambda *_args, **_kwargs: {"returncode": 0, "stdout": "[Diagnose]\nservice=demo status=ready\n", "stderr": ""})
    monkeypatch.setattr(cinnamon_applet, "_systemd_unit_status", lambda _unit: {"active_state": "active", "sub_state": "running", "returncode": 0})
    monkeypatch.setattr(
        cinnamon_applet,
        "_qdrant_status",
        lambda _url: {
            "url": "http://127.0.0.1:6333",
            "collections": {"teebotus_user_memory": "malformed"},
            "error": "",
        },
    )
    monkeypatch.setattr(cinnamon_applet, "_repo_status", lambda _root: {"path": str(tmp_path), "short_commit": "abc1234"})

    payload = build_status_payload(
        repo_root=tmp_path,
        channels="telegram,signal",
        unit_name="teebotus.service",
        python_executable="/usr/bin/python3",
        timeout_seconds=1,
    )

    assert payload["ok"] is False
    assert payload["health"]["status"] == "warning"
    assert payload["health"]["qdrant_probe_problem_count"] == 1
    assert payload["health"]["qdrant_problem_count"] == 1
    assert payload["health"]["total_problem_count"] == 1


def test_cinnamon_applet_payload_rejects_qdrant_ready_collection_with_error(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cinnamon_applet, "_runtime_status", lambda *_args, **_kwargs: {"returncode": 0, "stdout": "[Diagnose]\nservice=demo status=ready\n", "stderr": ""})
    monkeypatch.setattr(cinnamon_applet, "_systemd_unit_status", lambda _unit: {"active_state": "active", "sub_state": "running", "returncode": 0})
    monkeypatch.setattr(
        cinnamon_applet,
        "_qdrant_status",
        lambda _url: {
            "url": "http://127.0.0.1:6333",
            "collections": {
                "teebotus_user_memory": {"status": "READY", "count": 4, "error": "stale collection metadata"},
            },
            "error": "",
        },
    )
    monkeypatch.setattr(cinnamon_applet, "_repo_status", lambda _root: {"path": str(tmp_path), "short_commit": "abc1234"})

    payload = build_status_payload(
        repo_root=tmp_path,
        channels="telegram,signal",
        unit_name="teebotus.service",
        python_executable="/usr/bin/python3",
        timeout_seconds=1,
    )

    assert payload["ok"] is False
    assert payload["health"]["status"] == "warning"
    assert payload["health"]["qdrant_probe_problem_count"] == 1
    assert payload["health"]["qdrant_problem_count"] == 1
    assert payload["health"]["total_problem_count"] == 1


def test_cinnamon_applet_payload_does_not_double_count_runtime_qdrant_failure(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        cinnamon_applet,
        "_runtime_status",
        lambda *_args, **_kwargs: {
            "returncode": 0,
            "stdout": (
                "[Memory und semantische Suche]\n"
                "qdrant=127.0.0.1:6333 status=unreachable fallback=keyword_memory_search\n"
                "qdrant_collection=teebotus_user_memory target=127.0.0.1:6333 status=unavailable vector_size=64\n"
            ),
            "stderr": "",
        },
    )
    monkeypatch.setattr(cinnamon_applet, "_systemd_unit_status", lambda _unit: {"active_state": "active", "sub_state": "running", "returncode": 0})
    monkeypatch.setattr(
        cinnamon_applet,
        "_qdrant_status",
        lambda _url: {
            "url": "http://127.0.0.1:6333",
            "collections": {"teebotus_user_memory": {"status": "unreachable", "count": 0, "error": "connection refused"}},
            "error": "teebotus_user_memory: connection refused",
        },
    )
    monkeypatch.setattr(cinnamon_applet, "_repo_status", lambda _root: {"path": str(tmp_path), "short_commit": "abc1234"})

    payload = build_status_payload(
        repo_root=tmp_path,
        channels="telegram,signal",
        unit_name="teebotus.service",
        python_executable="/usr/bin/python3",
        timeout_seconds=1,
    )

    assert payload["command_ok"] is True
    assert payload["ok"] is False
    assert payload["health"]["status"] == "warning"
    assert payload["health"]["command_problem_count"] == 0
    assert payload["health"]["problem_status_count"] == 2
    assert payload["health"]["runtime_problem_count"] == 0
    assert payload["health"]["qdrant_runtime_problem_count"] == 2
    assert payload["health"]["qdrant_probe_problem_count"] == 1
    assert payload["health"]["qdrant_problem_count"] == 2
    assert payload["health"]["total_problem_count"] == 2


def test_cinnamon_applet_payload_does_not_add_qdrant_service_failure_to_probe_failure(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        cinnamon_applet,
        "_runtime_status",
        lambda *_args, **_kwargs: {
            "returncode": 0,
            "stdout": (
                "[Memory und semantische Suche]\n"
                "qdrant=127.0.0.1:6333 status=unreachable\n"
                "qdrant_collection=teebotus_user_memory status=unavailable\n"
            ),
            "stderr": "",
        },
    )
    monkeypatch.setattr(
        cinnamon_applet,
        "_systemd_unit_status",
        lambda unit: (
            {"active_state": "active", "sub_state": "running", "returncode": 0}
            if unit == "teebotus.service"
            else {"active_state": "failed", "sub_state": "failed", "returncode": 0}
        ),
    )
    monkeypatch.setattr(
        cinnamon_applet,
        "_qdrant_status",
        lambda _url: {
            "url": "http://127.0.0.1:6333",
            "collections": {
                "teebotus_user_memory": {"status": "unreachable", "count": 0},
                "teebotus_bibliothekar_chunks": {"status": "unreachable", "count": 0},
            },
            "error": "connection refused",
        },
    )
    monkeypatch.setattr(cinnamon_applet, "_repo_status", lambda _root: {"path": str(tmp_path), "short_commit": "abc1234"})

    payload = build_status_payload(
        repo_root=tmp_path,
        channels="telegram,signal",
        unit_name="teebotus.service",
        python_executable="/usr/bin/python3",
        timeout_seconds=1,
    )

    assert payload["health"]["runtime_problem_count"] == 0
    assert payload["health"]["qdrant_runtime_problem_count"] == 2
    assert payload["health"]["qdrant_probe_problem_count"] == 2
    assert payload["health"]["qdrant_unit_problem_count"] == 1
    assert payload["health"]["qdrant_problem_count"] == 2
    assert payload["health"]["total_problem_count"] == 2


def test_cinnamon_applet_payload_warns_when_only_qdrant_runtime_count_is_present(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cinnamon_applet, "_runtime_status", lambda *_args, **_kwargs: {"returncode": 0, "stdout": "[Start]\nstatus=ready\n", "stderr": ""})
    monkeypatch.setattr(cinnamon_applet, "_systemd_unit_status", lambda _unit: {"active_state": "active", "sub_state": "running", "returncode": 0})
    monkeypatch.setattr(
        cinnamon_applet,
        "_qdrant_status",
        lambda _url: {"url": "http://127.0.0.1:6333", "collections": {}, "error": ""},
    )
    monkeypatch.setattr(
        cinnamon_applet,
        "_repo_status",
        lambda _root: {"path": str(tmp_path), "short_commit": "abc1234"},
    )

    original = cinnamon_applet.parse_runtime_status
    monkeypatch.setattr(
        cinnamon_applet,
        "parse_runtime_status",
        lambda _output: {
            "sections": {},
            "summary": {
                "instances": "",
                "channels": "",
                "problem_status_count": 0,
                "problem_statuses": "",
                "qdrant_problem_status_count": 1,
            },
            "status_counts": {},
        },
    )

    try:
        payload = build_status_payload(
            repo_root=tmp_path,
            channels="telegram,signal",
            unit_name="teebotus.service",
            python_executable="/usr/bin/python3",
            timeout_seconds=1,
        )
    finally:
        monkeypatch.setattr(cinnamon_applet, "parse_runtime_status", original)

    assert payload["ok"] is False
    assert payload["health"]["status"] == "warning"
    assert payload["health"]["runtime_problem_count"] == 0
    assert payload["health"]["qdrant_problem_count"] == 1
    assert payload["health"]["total_problem_count"] == 1


def test_cinnamon_applet_payload_uses_status_counts_when_problem_status_count_is_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cinnamon_applet, "_runtime_status", lambda *_args, **_kwargs: {"returncode": 0, "stdout": "[Start]\nstatus=ready\n", "stderr": ""})
    monkeypatch.setattr(cinnamon_applet, "_systemd_unit_status", lambda _unit: {"active_state": "active", "sub_state": "running", "returncode": 0})
    monkeypatch.setattr(cinnamon_applet, "_qdrant_status", lambda _url: {"url": "http://127.0.0.1:6333", "collections": {}, "error": ""})
    monkeypatch.setattr(cinnamon_applet, "_repo_status", lambda _root: {"path": str(tmp_path), "short_commit": "abc1234"})

    original = cinnamon_applet.parse_runtime_status
    monkeypatch.setattr(
        cinnamon_applet,
        "parse_runtime_status",
        lambda _output: {
            "sections": {},
            "summary": {
                "instances": "",
                "channels": "",
                "problem_status_count": 0,
                "problem_statuses": "",
                "qdrant_problem_status_count": 0,
            },
            "status_counts": {"warning": 3},
        },
    )

    try:
        payload = build_status_payload(
            repo_root=tmp_path,
            channels="telegram,signal",
            unit_name="teebotus.service",
            python_executable="/usr/bin/python3",
            timeout_seconds=1,
        )
    finally:
        monkeypatch.setattr(cinnamon_applet, "parse_runtime_status", original)

    assert payload["health"]["runtime_problem_count"] == 3
    assert payload["health"]["problem_statuses"] == "warning:3"
    assert payload["health"]["total_problem_count"] == 3


def test_cinnamon_applet_payload_problem_statuses_from_counts_match_parser_order(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cinnamon_applet, "_runtime_status", lambda *_args, **_kwargs: {"returncode": 0, "stdout": "[Start]\nstatus=ready\n", "stderr": ""})
    monkeypatch.setattr(cinnamon_applet, "_systemd_unit_status", lambda _unit: {"active_state": "active", "sub_state": "running", "returncode": 0})
    monkeypatch.setattr(cinnamon_applet, "_qdrant_status", lambda _url: {"url": "http://127.0.0.1:6333", "collections": {}, "error": ""})
    monkeypatch.setattr(cinnamon_applet, "_repo_status", lambda _root: {"path": str(tmp_path), "short_commit": "abc1234"})

    original = cinnamon_applet.parse_runtime_status
    monkeypatch.setattr(
        cinnamon_applet,
        "parse_runtime_status",
        lambda _output: {
            "sections": {},
            "summary": {
                "instances": "",
                "channels": "",
                "problem_status_count": 0,
                "problem_statuses": "",
                "qdrant_problem_status_count": 0,
            },
            "status_counts": {"never": 1, "needed": 2},
        },
    )

    try:
        payload = build_status_payload(
            repo_root=tmp_path,
            channels="telegram,signal",
            unit_name="teebotus.service",
            python_executable="/usr/bin/python3",
            timeout_seconds=1,
        )
    finally:
        monkeypatch.setattr(cinnamon_applet, "parse_runtime_status", original)

    assert payload["health"]["problem_statuses"] == "needed:2,never:1"


def test_cinnamon_applet_payload_counts_top_level_qdrant_error_without_collections(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cinnamon_applet, "_runtime_status", lambda *_args, **_kwargs: {"returncode": 0, "stdout": "[Diagnose]\nservice=demo status=ready\n", "stderr": ""})
    monkeypatch.setattr(cinnamon_applet, "_systemd_unit_status", lambda _unit: {"active_state": "active", "sub_state": "running", "returncode": 0})
    monkeypatch.setattr(cinnamon_applet, "_qdrant_status", lambda _url: {"url": "https://qdrant.example", "collections": {}, "error": "invalid local qdrant url"})
    monkeypatch.setattr(cinnamon_applet, "_repo_status", lambda _root: {"path": str(tmp_path), "short_commit": "abc1234"})

    payload = build_status_payload(
        repo_root=tmp_path,
        channels="telegram,signal",
        unit_name="teebotus.service",
        python_executable="/usr/bin/python3",
        timeout_seconds=1,
    )

    assert payload["command_ok"] is True
    assert payload["ok"] is False
    assert payload["health"]["status"] == "warning"
    assert payload["health"]["command_problem_count"] == 0
    assert payload["health"]["problem_status_count"] == 0
    assert payload["health"]["qdrant_problem_count"] == 1
    assert payload["health"]["qdrant_probe_problem_count"] == 1
    assert payload["health"]["qdrant_runtime_problem_count"] == 0
    assert payload["health"]["qdrant_unit_problem_count"] == 0
    assert payload["health"]["total_problem_count"] == 1


def test_cinnamon_applet_qdrant_status_redacts_invalid_url_secrets() -> None:
    secret_url = "https://user:plainpass@example.test/path?api_key=plain-secret#access_token=fragment-secret"

    status = cinnamon_applet._qdrant_status(secret_url)

    rendered = json.dumps(status, sort_keys=True)
    assert status["error"] == "invalid local qdrant url"
    assert status["collections"] == {}
    assert "plainpass" not in rendered
    assert "plain-secret" not in rendered
    assert "fragment-secret" not in rendered
    assert status["url"].startswith("https://<redacted>@example.test/path")
    assert "api_key=<redacted>" in status["url"]


def test_cinnamon_applet_qdrant_status_rejects_invalid_local_ports() -> None:
    for url in ("http://127.0.0.1:0", "http://127.0.0.1:99999"):
        status = cinnamon_applet._qdrant_status(url)

        assert status["error"] == "invalid local qdrant url"
        assert status["collections"] == {}


def test_cinnamon_applet_qdrant_status_rejects_userinfo_and_params() -> None:
    for url in ("http://:@127.0.0.1:6333", "http://127.0.0.1:6333/;params"):
        status = cinnamon_applet._qdrant_status(url)

        assert status["error"] == "invalid local qdrant url"
        assert status["collections"] == {}


def test_cinnamon_applet_repo_status_does_not_fail_open_on_git_status(monkeypatch, tmp_path) -> None:
    porcelain_result = {"returncode": 1, "stdout": "", "stderr": "not a git repository"}

    def fake_run(argv: list[str], **_kwargs: object) -> dict[str, object]:
        if argv[1] == "branch":
            return {"returncode": 0, "stdout": "main\n", "stderr": ""}
        if argv[1] == "rev-parse":
            return {"returncode": 0, "stdout": "abcdef123456\n", "stderr": ""}
        return porcelain_result

    monkeypatch.setattr(cinnamon_applet, "_run", fake_run)

    failed = cinnamon_applet._repo_status(tmp_path)
    porcelain_result = {"returncode": 0, "stdout": "## main...origin/main\n<truncated>\n", "stderr": ""}
    truncated = cinnamon_applet._repo_status(tmp_path)

    assert failed["dirty"] is True
    assert truncated["dirty"] is True


def test_cinnamon_applet_repo_status_rejects_empty_successful_git_output(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        cinnamon_applet,
        "_run",
        lambda *_args, **_kwargs: {"returncode": 0, "stdout": "", "stderr": ""},
    )

    status = cinnamon_applet._repo_status(tmp_path)

    assert status["dirty"] is True
    assert status["ahead_behind"] == ""


def test_cinnamon_applet_repo_status_rejects_failed_metadata_queries(monkeypatch, tmp_path) -> None:
    def fake_run(argv: list[str], **_kwargs: object) -> dict[str, object]:
        if argv[1] == "branch":
            return {"returncode": 1, "stdout": "", "stderr": "branch failed"}
        if argv[1] == "rev-parse":
            return {"returncode": 1, "stdout": "", "stderr": "rev-parse failed"}
        return {"returncode": 0, "stdout": "## main\n", "stderr": ""}

    monkeypatch.setattr(cinnamon_applet, "_run", fake_run)

    status = cinnamon_applet._repo_status(tmp_path)

    assert status["dirty"] is True


def test_cinnamon_applet_qdrant_point_count_rejects_unexpected_success_payloads(monkeypatch) -> None:
    class FakeResponse:
        status = 200

        def __init__(self, payload: object) -> None:
            self.payload = payload

        def read(self, _size: int = -1) -> bytes:
            return json.dumps(self.payload).encode("utf-8")

        def close(self) -> None:
            return None

    payloads: list[object] = [
        {"status": "ok", "result": {"count": 7}},
        {"status": "ok", "result": {}},
        {"status": "ok", "result": {"count": "not-a-number"}},
        {"status": "ok", "result": {"count": -1}},
        {"status": "error", "result": {"count": 0}},
        ["not", "a", "dict"],
    ]

    def fake_urlopen(_request: object, timeout: int) -> FakeResponse:
        assert timeout == 2
        return FakeResponse(payloads.pop(0))

    monkeypatch.setattr(cinnamon_applet, "urlopen", fake_urlopen)

    ready = cinnamon_applet._qdrant_point_count("http://127.0.0.1:6333", "demo")
    missing_count = cinnamon_applet._qdrant_point_count("http://127.0.0.1:6333", "demo")
    invalid_count = cinnamon_applet._qdrant_point_count("http://127.0.0.1:6333", "demo")
    negative_count = cinnamon_applet._qdrant_point_count("http://127.0.0.1:6333", "demo")
    error_status = cinnamon_applet._qdrant_point_count("http://127.0.0.1:6333", "demo")
    non_object = cinnamon_applet._qdrant_point_count("http://127.0.0.1:6333", "demo")

    assert ready == {"status": "ready", "count": 7, "error": ""}
    assert missing_count == {"status": "broken", "count": 0, "error": "missing Qdrant count result"}
    assert invalid_count == {"status": "broken", "count": 0, "error": "invalid Qdrant count result"}
    assert negative_count == {"status": "broken", "count": 0, "error": "negative Qdrant count result"}
    assert error_status == {"status": "broken", "count": 0, "error": "unexpected Qdrant status: error"}
    assert non_object == {"status": "broken", "count": 0, "error": "unexpected JSON payload"}


def test_cinnamon_applet_qdrant_point_count_uses_code_when_status_is_missing(monkeypatch) -> None:
    class FakeResponse:
        status = None
        code = 503

        def read(self, _size: int = -1) -> bytes:
            return b'{"status":"ok","result":{"count":1}}'

        def close(self) -> None:
            return None

    monkeypatch.setattr(cinnamon_applet, "urlopen", lambda _request, timeout: FakeResponse())

    result = cinnamon_applet._qdrant_point_count("http://127.0.0.1:6333", "demo")

    assert result == {"status": "unreachable", "count": 0, "error": "HTTP 503"}


def test_cinnamon_applet_qdrant_point_count_rejects_response_outside_local_origin(monkeypatch) -> None:
    class FakeResponse:
        status = 200
        url = "https://qdrant.example.test/collections/demo/points/count"

        def read(self, _size: int = -1) -> bytes:
            return b'{"status":"ok","result":{"count":1}}'

        def close(self) -> None:
            return None

    monkeypatch.setattr(cinnamon_applet, "urlopen", lambda _request, timeout: FakeResponse())

    assert cinnamon_applet._qdrant_point_count("http://127.0.0.1:6333", "demo") == {
        "status": "broken",
        "count": 0,
        "error": "Qdrant response redirected outside local origin",
    }


def test_cinnamon_applet_qdrant_point_count_rejects_broken_response_url_metadata(monkeypatch) -> None:
    class FakeResponse:
        status = 200

        def geturl(self) -> str:
            raise RuntimeError("response URL unavailable")

        def read(self, _size: int = -1) -> bytes:
            raise AssertionError("response body must not be read")

        def close(self) -> None:
            return None

    monkeypatch.setattr(cinnamon_applet, "urlopen", lambda _request, timeout: FakeResponse())

    assert cinnamon_applet._qdrant_point_count("http://127.0.0.1:6333", "demo") == {
        "status": "broken",
        "count": 0,
        "error": "invalid Qdrant response URL: RuntimeError",
    }


def test_cinnamon_applet_qdrant_opener_rejects_redirects() -> None:
    request = cinnamon_applet.Request("http://127.0.0.1:6333/collections/demo/points/count")

    with pytest.raises(cinnamon_applet.HTTPError) as raised:
        cinnamon_applet._NoRedirectHandler().redirect_request(request, None, 302, "redirect", {}, "https://example.test")

    assert raised.value.code == 302


def test_cinnamon_applet_qdrant_point_count_rejects_non_integer_http_status(monkeypatch) -> None:
    class FakeResponse:
        status = 200.9

        def read(self, _size: int = -1) -> bytes:
            return b'{"status":"ok","result":{"count":1}}'

        def close(self) -> None:
            return None

    monkeypatch.setattr(cinnamon_applet, "urlopen", lambda _request, timeout: FakeResponse())

    assert cinnamon_applet._qdrant_point_count("http://127.0.0.1:6333", "demo") == {
        "status": "unreachable",
        "count": 0,
        "error": "ValueError: invalid Qdrant HTTP status",
    }


def test_cinnamon_applet_qdrant_point_count_rejects_non_bytes_response_body(monkeypatch) -> None:
    class FakeResponse:
        status = 200

        def __init__(self, body: object) -> None:
            self.body = body

        def read(self, _size: int = -1) -> object:
            return self.body

        def close(self) -> None:
            return None

    bodies = ["{\"status\":\"ok\"}", None]
    monkeypatch.setattr(cinnamon_applet, "urlopen", lambda _request, timeout: FakeResponse(bodies.pop(0)))

    assert cinnamon_applet._qdrant_point_count("http://127.0.0.1:6333", "demo") == {
        "status": "broken",
        "count": 0,
        "error": "invalid Qdrant response body",
    }
    assert cinnamon_applet._qdrant_point_count("http://127.0.0.1:6333", "demo") == {
        "status": "broken",
        "count": 0,
        "error": "invalid Qdrant response body",
    }


def test_cinnamon_applet_qdrant_point_count_rejects_non_string_status(monkeypatch) -> None:
    class FakeResponse:
        status = 200

        def __init__(self, payload: object) -> None:
            self.payload = payload

        def read(self, _size: int = -1) -> bytes:
            return json.dumps(self.payload).encode("utf-8")

        def close(self) -> None:
            return None

    payloads: list[object] = [
        {"status": False, "result": {"count": 1}},
        {"status": 0, "result": {"count": 1}},
        {"status": None, "result": {"count": 1}},
    ]
    monkeypatch.setattr(cinnamon_applet, "urlopen", lambda _request, timeout: FakeResponse(payloads.pop(0)))

    for _ in range(3):
        assert cinnamon_applet._qdrant_point_count("http://127.0.0.1:6333", "demo") == {
            "status": "broken",
            "count": 0,
            "error": "invalid Qdrant status",
        }


def test_cinnamon_applet_qdrant_point_count_normalizes_status_whitespace(monkeypatch) -> None:
    class FakeResponse:
        status = 200

        def read(self, _size: int = -1) -> bytes:
            return b'{"status":"  OK  ","result":{"count":4}}'

        def close(self) -> None:
            return None

    monkeypatch.setattr(cinnamon_applet, "urlopen", lambda _request, timeout: FakeResponse())

    assert cinnamon_applet._qdrant_point_count("http://127.0.0.1:6333", "demo") == {
        "status": "ready",
        "count": 4,
        "error": "",
    }


def test_cinnamon_applet_qdrant_point_count_rejects_empty_api_status(monkeypatch) -> None:
    class FakeResponse:
        status = 200

        def read(self, _size: int = -1) -> bytes:
            return b'{"status":"  ","result":{"count":4}}'

        def close(self) -> None:
            return None

    monkeypatch.setattr(cinnamon_applet, "urlopen", lambda _request, timeout: FakeResponse())

    assert cinnamon_applet._qdrant_point_count("http://127.0.0.1:6333", "demo") == {
        "status": "broken",
        "count": 0,
        "error": "unexpected Qdrant status: ",
    }


def test_cinnamon_applet_qdrant_point_count_rejects_deep_json(monkeypatch) -> None:
    class FakeResponse:
        status = 200

        def read(self, _size: int = -1) -> bytes:
            return b"{}"

        def close(self) -> None:
            return None

    def raise_recursion(_raw: object) -> object:
        raise RecursionError("deep JSON")

    monkeypatch.setattr(cinnamon_applet, "urlopen", lambda _request, timeout: FakeResponse())
    monkeypatch.setattr(cinnamon_applet.json, "loads", raise_recursion)

    result = cinnamon_applet._qdrant_point_count("http://127.0.0.1:6333", "demo")

    assert result == {"status": "broken", "count": 0, "error": "invalid JSON: RecursionError"}


def test_cinnamon_applet_qdrant_point_count_rejects_non_integer_counts(monkeypatch) -> None:
    class FakeResponse:
        status = 200

        def __init__(self, payload: object) -> None:
            self.payload = payload

        def read(self, _size: int = -1) -> bytes:
            return json.dumps(self.payload).encode("utf-8")

        def close(self) -> None:
            return None

    payloads = [
        {"status": "ok", "result": {"count": 7.9}},
        {"status": "ok", "result": {"count": True}},
        {"status": "ok", "result": {"count": "7abc"}},
    ]

    def fake_urlopen(_request: object, timeout: int) -> FakeResponse:
        assert timeout == 2
        return FakeResponse(payloads.pop(0))

    monkeypatch.setattr(cinnamon_applet, "urlopen", fake_urlopen)

    assert cinnamon_applet._qdrant_point_count("http://127.0.0.1:6333", "demo")["error"] == "invalid Qdrant count result"
    assert cinnamon_applet._qdrant_point_count("http://127.0.0.1:6333", "demo")["error"] == "invalid Qdrant count result"
    assert cinnamon_applet._qdrant_point_count("http://127.0.0.1:6333", "demo")["error"] == "invalid Qdrant count result"


def test_cinnamon_applet_qdrant_point_count_rejects_unsafe_large_counts(monkeypatch) -> None:
    class FakeResponse:
        status = 200

        def __init__(self, raw: bytes) -> None:
            self.raw = raw

        def read(self, _size: int = -1) -> bytes:
            return self.raw

        def close(self) -> None:
            return None

    payloads = [
        {"status": "ok", "result": {"count": "9" * (len(str(cinnamon_applet.MAX_QDRANT_COUNT)) + 1)}},
        {"status": "ok", "result": {"count": cinnamon_applet.MAX_QDRANT_COUNT + 1}},
    ]

    def fake_urlopen(_request: object, timeout: int) -> FakeResponse:
        assert timeout == 2
        return FakeResponse(json.dumps(payloads.pop(0)).encode("utf-8"))

    monkeypatch.setattr(cinnamon_applet, "urlopen", fake_urlopen)

    assert cinnamon_applet._qdrant_point_count("http://127.0.0.1:6333", "demo")["error"] == "unsafe Qdrant count result"
    assert cinnamon_applet._qdrant_point_count("http://127.0.0.1:6333", "demo")["error"] == "unsafe Qdrant count result"


def test_cinnamon_applet_qdrant_point_count_rejects_json_integer_limit_error(monkeypatch) -> None:
    class FakeResponse:
        status = 200

        def read(self, _size: int = -1) -> bytes:
            return (b'{"status":"ok","result":{"count":' + b"9" * 4301 + b"}}")

        def close(self) -> None:
            return None

    monkeypatch.setattr(cinnamon_applet, "urlopen", lambda _request, timeout: FakeResponse())

    result = cinnamon_applet._qdrant_point_count("http://127.0.0.1:6333", "demo")

    assert result["status"] == "broken"
    assert result["error"].startswith("invalid JSON:")


def test_cinnamon_applet_qdrant_point_count_rejects_oversized_response(monkeypatch) -> None:
    class FakeResponse:
        status = 200
        closed = False

        def read(self, size: int = -1) -> bytes:
            assert size == cinnamon_applet.MAX_QDRANT_COUNT_RESPONSE_BYTES + 1
            return b"{" + (b"x" * cinnamon_applet.MAX_QDRANT_COUNT_RESPONSE_BYTES)

        def close(self) -> None:
            self.closed = True

    response = FakeResponse()

    def fake_urlopen(_request: object, timeout: int) -> FakeResponse:
        assert timeout == 2
        return response

    monkeypatch.setattr(cinnamon_applet, "urlopen", fake_urlopen)

    result = cinnamon_applet._qdrant_point_count("http://127.0.0.1:6333", "demo")

    assert result == {"status": "broken", "count": 0, "error": "Qdrant count response too large"}
    assert response.closed is True


def test_cinnamon_applet_qdrant_point_count_rejects_unbounded_response_reader(monkeypatch) -> None:
    class FakeResponse:
        status = 200
        closed = False

        def read(self) -> bytes:
            return b'{"status":"ok","result":{"count":1}}'

        def close(self) -> None:
            self.closed = True

    response = FakeResponse()
    monkeypatch.setattr(cinnamon_applet, "urlopen", lambda _request, timeout: response)

    result = cinnamon_applet._qdrant_point_count("http://127.0.0.1:6333", "demo")

    assert result == {
        "status": "broken",
        "count": 0,
        "error": "Qdrant response reader does not support bounded reads",
    }
    assert response.closed is True


def test_cinnamon_applet_qdrant_point_count_closes_response_when_read_fails(monkeypatch) -> None:
    class FakeResponse:
        status = 200
        closed = False

        def read(self, size: int = -1) -> bytes:
            raise OSError("read failed")

        def close(self) -> None:
            self.closed = True

    response = FakeResponse()

    monkeypatch.setattr(cinnamon_applet, "urlopen", lambda _request, timeout: response)

    result = cinnamon_applet._qdrant_point_count("http://127.0.0.1:6333", "demo")

    assert result == {"status": "unreachable", "count": 0, "error": "read failed"}
    assert response.closed is True


def test_cinnamon_applet_qdrant_point_count_closes_http_error_response(monkeypatch) -> None:
    from urllib.error import HTTPError

    class FakeHTTPError(HTTPError):
        closed = False

        def close(self) -> None:
            self.closed = True

    error = FakeHTTPError("http://127.0.0.1:6333", 503, "unavailable", {}, None)
    monkeypatch.setattr(cinnamon_applet, "urlopen", lambda _request, timeout: (_ for _ in ()).throw(error))

    result = cinnamon_applet._qdrant_point_count("http://127.0.0.1:6333", "demo")

    assert result == {"status": "unreachable", "count": 0, "error": "HTTP 503"}
    assert error.closed is True


def test_cinnamon_applet_run_redacts_stdout_before_truncating() -> None:
    secret = "sk-test-placeholder-value-12345"
    stdout = "x" * (cinnamon_applet.MAX_CAPTURE_CHARS - len(secret) - 2) + " " + secret + "tail"

    result = cinnamon_applet._run([sys.executable, "-c", f"import sys; sys.stdout.write({stdout!r})"])

    assert secret not in result["stdout"]
    assert "sk-" not in result["stdout"]


def test_cinnamon_applet_run_redacts_secret_arguments_in_diagnostic_argv() -> None:
    secret = "plain-secret-argument"
    result = cinnamon_applet._run(["demo", "--api-key", secret, "--password=inline-secret", "--verbose"])
    rendered_argv = " ".join(result["argv"])

    assert secret not in rendered_argv
    assert "inline-secret" not in rendered_argv
    assert "<redacted>" in rendered_argv


def test_cinnamon_applet_run_bounds_child_output_before_returning() -> None:
    result = cinnamon_applet._run(
        [
            sys.executable,
            "-c",
            f"import sys; output = 'x' * {cinnamon_applet.MAX_CAPTURE_CHARS * 2}; sys.stdout.write(output); sys.stderr.write(output)",
        ]
    )

    assert result["returncode"] == 0
    assert len(result["stdout"]) <= cinnamon_applet.MAX_CAPTURE_CHARS + len("\n<truncated>")
    assert len(result["stderr"]) <= cinnamon_applet.MAX_ERROR_CHARS + len("\n<truncated>")
    assert result["stdout"].endswith("<truncated>")
    assert result["stderr"].endswith("<truncated>")


def test_cinnamon_applet_run_preserves_truncation_after_redaction() -> None:
    secret = "sk-" + "A" * 20
    repetitions = (cinnamon_applet.MAX_CAPTURE_CHARS + cinnamon_applet.MAX_REDACTION_GUARD_BYTES) // len(secret) + 100
    result = cinnamon_applet._run(
        [sys.executable, "-c", f"import sys; sys.stdout.write({(' ' + secret) * repetitions!r})"]
    )

    assert result["stdout"].endswith("<truncated>")
    assert secret not in result["stdout"]


def test_cinnamon_applet_run_terminates_timed_out_child() -> None:
    result = cinnamon_applet._run([sys.executable, "-c", "import time; time.sleep(5)"], timeout_seconds=1)

    assert result == {
        "argv": [sys.executable, "-c", "'import time; time.sleep(5)'"],
        "returncode": 124,
        "stdout": "",
        "stderr": "TimeoutExpired: command timed out after 1 seconds",
    }


def test_cinnamon_applet_run_timeout_kills_child_process_group(tmp_path) -> None:
    child_pid_file = tmp_path / "child.pid"
    script = (
        "import pathlib, subprocess, sys, time; "
        f"pathlib.Path({str(child_pid_file)!r}).write_text(str(subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']).pid)); "
        "time.sleep(30)"
    )

    result = cinnamon_applet._run([sys.executable, "-c", script], timeout_seconds=1)

    assert result["returncode"] == 124
    child_pid = int(child_pid_file.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)


def test_cinnamon_applet_redaction_does_not_backtrack_on_large_url_without_credentials() -> None:
    value = "url=" + ("x" * cinnamon_applet.MAX_CAPTURE_CHARS)

    assert cinnamon_applet._redact(value) == value


def test_cinnamon_applet_runtime_parser_redacts_secrets_without_losing_safe_metadata() -> None:
    github_token = "ghp_" + "1234567890ABCDEFGHIJK"
    google_oauth_token = "ya29.a0AfH6SMabcdefghijklmnopqrstuvwxyz1234567890"
    slack_bot_token = "xox" + "b-123456789012-123456789012-abcdefghijklmnopqrstuvwx"
    jwt_like_token = "abcdefghijklmnopqrstuvwx.ABCDEF.abcdefghijklmnopqrstuvwxyz1234567890"

    parsed = parse_runtime_status(
        f"""
        [LLM-Routen und Backends]
        llm_route=normal_chat status=broken api_key={github_token} client_secret="plain secret value" password='another secret phrase' bearer_token=`third secret value` private_key="plain private key" service_account_private_key=plain-private-key signing_key=`plain signing key` refresh_token=plain multi word token escaped_api_key="secret\\"still-secret" escaped_password='secret\\'still-password' escaped_token=`secret\\`still-token` api_key_env=GEMINI_API_KEY api_key_ring=3 error=password:nested-secret google_oauth={google_oauth_token} slack={slack_bot_token} jwt={jwt_like_token}

        [API Keys, Limits und Kosten]
        api_budget=normal_chat status=configured tokens=provider_usage_response+local_guard max_output_tokens=700 private_key=-----BEGIN PRIVATE KEY----- message=(client_secret=structured-secret) details=[api_key="bracket secret value"] meta={{password=curly-secret}} hint=<token=angle-secret> diagnostic_json={{"api_key":"json-secret-value","client_secret":"json spaced secret","api_key_env":"GEMINI_API_KEY","api_key_ring":"3"}}

        [Messenger]
        telegram_slot=Demo/telegram:1 status=configured token=configured target=https://user:plainpass@example.test/path
        """
    )
    rendered = json.dumps(parsed, sort_keys=True)
    api_line = parsed["sections"]["API Keys, Limits und Kosten"][0]

    assert github_token not in rendered
    assert "nested-secret" not in rendered
    assert google_oauth_token not in rendered
    assert slack_bot_token not in rendered
    assert jwt_like_token not in rendered
    assert "plain secret value" not in rendered
    assert "another secret phrase" not in rendered
    assert "third secret value" not in rendered
    assert "plain private key" not in rendered
    assert "plain-private-key" not in rendered
    assert "plain signing key" not in rendered
    assert "plain multi word token" not in rendered
    assert "still-secret" not in rendered
    assert "still-password" not in rendered
    assert "still-token" not in rendered
    assert "-----BEGIN PRIVATE KEY-----" not in rendered
    assert "structured-secret" not in rendered
    assert "bracket secret value" not in rendered
    assert "curly-secret" not in rendered
    assert "angle-secret" not in rendered
    assert "json-secret-value" not in rendered
    assert "json spaced secret" not in rendered
    assert "user:plainpass" not in rendered
    assert "api_key=<redacted-secret>" in rendered
    assert "client_secret=<redacted>" in rendered
    assert "password=<redacted>" in rendered
    assert "bearer_token=<redacted>" in rendered
    assert "private_key=<redacted>" in rendered
    assert "service_account_private_key=<redacted>" in rendered
    assert "signing_key=<redacted>" in rendered
    assert "refresh_token=<redacted>" in rendered
    assert "escaped_api_key=<redacted>" in rendered
    assert "escaped_password=<redacted>" in rendered
    assert "escaped_token=<redacted>" in rendered
    assert "message=(client_secret=<redacted>)" in rendered
    assert "details=[api_key=<redacted>]" in rendered
    assert "meta={password=<redacted>}" in rendered
    assert "hint=<token=<redacted>>" in rendered
    assert '"api_key":"<redacted>"' in api_line
    assert '"client_secret":"<redacted>"' in api_line
    assert '"api_key_env":"GEMINI_API_KEY"' in api_line
    assert '"api_key_ring":"3"' in api_line
    assert "api_key_env=GEMINI_API_KEY" in rendered
    assert "api_key_ring=3" in rendered
    assert "password:<redacted>" in rendered
    assert "tokens=provider_usage_response+local_guard" in rendered
    assert "max_output_tokens=700" in rendered
    assert "token=configured" in rendered
    assert "target=https://<redacted>@example.test/path" in rendered
    assert parsed["status_counts"]["broken"] == 1
    assert parsed["status_counts"]["configured"] == 2
    assert parsed["summary"]["llm_routes"] == 1
    assert parsed["summary"]["api_budgets"] == 1
    assert parsed["summary"]["telegram_slots"] == 1
    assert cinnamon_applet._redact('"api_key":"start-secret"') == '"api_key":"<redacted>"'
    assert cinnamon_applet._redact("'client_secret':'start secret'") == "'client_secret':'<redacted>'"
    assert cinnamon_applet._redact('"api_key_env":"GEMINI_API_KEY"') == '"api_key_env":"GEMINI_API_KEY"'
    assert cinnamon_applet._redact('"authorization":"plain-secret"') == '"authorization":"<redacted>"'
    assert cinnamon_applet._redact("authorization=plain-secret") == "authorization=<redacted>"
    telegram_bot_token = "123456789:" + "A" * 35
    assert cinnamon_applet._redact(telegram_bot_token) == "<redacted-secret>"
    assert cinnamon_applet._redact(f"https://api.telegram.org/bot{telegram_bot_token}/getMe") == (
        "https://api.telegram.org/<redacted-secret>/getMe"
    )
    assert cinnamon_applet._redact("Authorization: Bearer x") == "Authorization: Bearer <redacted-secret>"
    assert cinnamon_applet._redact("authorization=Bearer x") == "authorization=Bearer <redacted-secret>"
    assert cinnamon_applet._redact('{"authorization":"Bearer x"}') == '{"authorization":"Bearer <redacted-secret>"}'
    assert cinnamon_applet._redact("command=tool --password plain-secret --api-key 'api secret' --token --verbose") == (
        "command=tool --password <redacted> --api-key <redacted> --token <redacted>"
    )
    assert cinnamon_applet._redact("command=tool -password plain-secret -api-key 'api secret' -token --verbose") == (
        "command=tool -password <redacted> -api-key <redacted> -token <redacted>"
    )
    assert cinnamon_applet._redact("command=tool --password=plain-secret -api-key='api secret' --token=--verbose") == (
        "command=tool --password=<redacted> -api-key=<redacted> --token=<redacted>"
    )
    assert cinnamon_applet._redact("token_usage=plain-secret free_tier_guard=on(rpm=5,tpm=1)") == (
        "token_usage=<redacted> free_tier_guard=on(rpm=5,tpm=1)"
    )
    assert cinnamon_applet._redact("--password secret,more;still-secret") == "--password <redacted>"
    assert cinnamon_applet._redact("--password=-leading-secret") == "--password=<redacted>"
    assert cinnamon_applet._redact("--password -leading-secret") == "--password <redacted>"
    assert cinnamon_applet._redact("--password --api-key plain-secret") == "--password --api-key <redacted>"
    assert cinnamon_applet._redact("api_key=>plain-secret") == "api_key=><redacted>"
    assert cinnamon_applet._redact('"api_key"=>"plain-secret"') == '"api_key"=>"<redacted>"'
    pem = "-----BEGIN PRIVATE KEY-----\nMIIEplainsecret\n-----END PRIVATE KEY-----"
    assert cinnamon_applet._redact(pem) == "<redacted-secret>"
    assert cinnamon_applet._redact("-----BEGIN PRIVATE KEY-----\nMIIEplainsecret") == "<redacted-secret>\n<truncated>"


def test_cinnamon_applet_runtime_parser_redacts_multiline_pem_private_keys() -> None:
    pem_body = "MIIEplainsecret"
    parsed = parse_runtime_status(
        "[Diagnose]\n"
        "error=before\n"
        "-----BEGIN RSA PRIVATE KEY-----\n"
        f"{pem_body}\n"
        "-----END RSA PRIVATE KEY-----\n"
        "service=demo status=ready\n"
    )

    rendered = json.dumps(parsed, sort_keys=True)
    assert pem_body not in rendered
    assert "<redacted-secret>" in rendered


def test_cinnamon_applet_runtime_parser_warns_on_unclosed_pem_private_key() -> None:
    parsed = parse_runtime_status(
        "[Diagnose]\n"
        "service=demo status=ready\n"
        "-----BEGIN PRIVATE KEY-----\n"
        "MIIEplainsecret\n"
    )

    assert parsed["summary"]["output_truncated"] is True
    assert parsed["status_counts"]["warning"] == 1


def test_cinnamon_applet_redacted_argv_hides_dash_prefixed_values_without_swallowing_options() -> None:
    assert cinnamon_applet._redacted_argv(["demo", "--api-key", "-leading-secret", "--verbose"]) == [
        "demo",
        "--api-key",
        "'<redacted>'",
        "--verbose",
    ]
    assert cinnamon_applet._redacted_argv(["demo", "--password", "--api-key", "plain-secret"]) == [
        "demo",
        "--password",
        "--api-key",
        "'<redacted>'",
    ]


@pytest.mark.parametrize(
    "option",
    (
        "--client-secret",
        "--refresh-token",
        "--telegram-token",
        "--bot-token",
        "--service-account-private-key",
        "--openai-api-key",
    ),
)
def test_cinnamon_applet_redacts_compound_secret_options(option: str) -> None:
    assert cinnamon_applet._redact(f"{option} plain-secret") == f"{option} <redacted>"
    assert cinnamon_applet._redacted_argv(["demo", option, "plain-secret"]) == [
        "demo",
        option,
        "'<redacted>'",
    ]


def test_cinnamon_applet_does_not_treat_token_usage_or_file_options_as_secret_values() -> None:
    assert cinnamon_applet._redact("--token-usage 123 --token-file /tmp/token") == (
        "--token-usage 123 --token-file /tmp/token"
    )


def test_cinnamon_applet_runtime_parser_redacts_nested_key_and_cookie_headers() -> None:
    nested_secret = "nested-plain-secret-value"
    cookie_secret = "cookie-plain-secret-value"
    json_cookie_secret = "json-cookie-plain-secret-value"

    parsed = parse_runtime_status(
        f"""
        [Tools und Account-Memory]
        account_memory=Demo status=broken error=diagnostic:api_key={nested_secret}; Cookie: session={cookie_secret}
        account_memory=Demo/second status=broken error={{"cookie":"{json_cookie_secret}"}}
        """
    )
    rendered = json.dumps(parsed, sort_keys=True)

    assert nested_secret not in rendered
    assert cookie_secret not in rendered
    assert json_cookie_secret not in rendered
    assert "diagnostic:api_key=<redacted>" in rendered
    assert "Cookie: <redacted-secret>" in rendered
    assert '"cookie":"<redacted>"' in parsed["sections"]["Tools und Account-Memory"][1]
    for prefix, secret in (
        ("metadata.", "dot-secret-value"),
        ("payload|", "pipe-secret-value"),
        ("error=>", "angle-secret-value"),
        ("env/", "slash-secret-value"),
    ):
        assert secret not in cinnamon_applet._redact(f"{prefix}api_key={secret}")


def test_cinnamon_applet_runtime_parser_redacts_url_and_bearer_edge_cases() -> None:
    bearer_token = "abcdefghijklmnopqrstuvwxyz123456"
    bare_bearer_token = "barebearerabcdefghijklmnopqrstuvwxyz123456"
    lowercase_bearer_token = "lowerbearerabcdefghijklmnopqrstuvwxyz123456"
    lowercase_basic_token = "lowerbasicabcdefghijklmnopqrstuvwxyz123456"
    lowercase_apikey_token = "lowerapikeyabcdefghijklmnopqrstuvwxyz123456"
    uppercase_apikey_token = "upperapikeyabcdefghijklmnopqrstuvwxyz123456"
    basic_token = "QWxhZGRpbjpvcGVuIHNlc2FtZQ=="
    api_key_header_token = "apikeyheaderabcdefghijklmnopqrstuvwxyz123456"
    token_header_token = "tokenheaderabcdefghijklmnopqrstuvwxyz123456"
    json_bearer_token = "jsonbearerabcdefghijklmnopqrstuvwxyz123456"
    json_proxy_token = "jsonproxyabcdefghijklmnopqrstuvwxyz123456"
    fragment_token = "fragment-secret-value"
    url_userinfo_token = "plain-userinfo-token-123"

    parsed = parse_runtime_status(
        f"""
        [LLM-Routen und Backends]
        llm_route=normal_chat status=broken target=redis://:redis-password@example.test/0 authorization=Bearer {bearer_token}

        [API Keys, Limits und Kosten]
        api_budget=normal_chat status=broken target=https://example.test/path?api_key=plain-secret&ok=1#access_token={fragment_token} authorization=Basic {basic_token}

        [Messenger]
        signal_service=Demo target=https://{url_userinfo_token}@signal.example.test/v1 status=unreachable error=Bearer {bare_bearer_token}; bearer {lowercase_bearer_token}; basic {lowercase_basic_token}; apikey {lowercase_apikey_token}; APIKEY {uppercase_apikey_token}; token GEMINI_API_KEY api_key_ring=3; Authorization: ApiKey {api_key_header_token}; Proxy-Authorization: Token {token_header_token}; diagnostic_headers={{"authorization":"Bearer {json_bearer_token}","Proxy-Authorization":"Token {json_proxy_token}"}}
        """
    )
    rendered = json.dumps(parsed, sort_keys=True)
    messenger_line = parsed["sections"]["Messenger"][0]

    assert "redis-password" not in rendered
    assert bearer_token not in rendered
    assert bare_bearer_token not in rendered
    assert lowercase_bearer_token not in rendered
    assert lowercase_basic_token not in rendered
    assert lowercase_apikey_token not in rendered
    assert uppercase_apikey_token not in rendered
    assert basic_token not in rendered
    assert api_key_header_token not in rendered
    assert token_header_token not in rendered
    assert json_bearer_token not in rendered
    assert json_proxy_token not in rendered
    assert fragment_token not in rendered
    assert "plain-secret" not in rendered
    assert url_userinfo_token not in rendered
    assert "target=redis://<redacted>@example.test/0" in rendered
    assert "authorization=Bearer <redacted-secret>" in rendered
    assert "error=Bearer <redacted-secret>; bearer <redacted-secret>; basic <redacted-secret>; apikey <redacted-secret>; APIKEY <redacted-secret>; token GEMINI_API_KEY api_key_ring=3; Authorization" in rendered
    assert "authorization=Basic <redacted-secret>" in rendered
    assert "authorization=Basic <redacted-secret>==" not in rendered
    assert "Authorization: ApiKey <redacted-secret>" in rendered
    assert "Proxy-Authorization: Token <redacted-secret>" in rendered
    assert '"authorization":"Bearer <redacted-secret>"' in messenger_line
    assert '"Proxy-Authorization":"Token <redacted-secret>"' in messenger_line
    assert "target=https://example.test/path?api_key=<redacted>&ok=1#access_token=<redacted>" in rendered
    assert "target=https://<redacted>@signal.example.test/v1" in rendered
    assert parsed["status_counts"]["broken"] == 2
    assert parsed["status_counts"]["unreachable"] == 1
    assert parsed["summary"]["llm_routes"] == 1
    assert parsed["summary"]["api_budgets"] == 1


def test_cinnamon_applet_runtime_parser_keeps_free_text_field_values() -> None:
    parsed = parse_runtime_status(
        """
        [LLM-Routen und Backends]
        llm_route=structured_decision status=unavailable error=provider returned status=500 and retry_after=30

        [Tools und Account-Memory]
        account_identity_warning=Demo code=runtime_channel_without_identity message=Use option foo=bar only after login. action=First run /register, then confirm status=ok manually
        """
    )

    llm_fields = cinnamon_applet._parse_status_fields(parsed["sections"]["LLM-Routen und Backends"][0])
    warning_fields = cinnamon_applet._parse_status_fields(parsed["sections"]["Tools und Account-Memory"][0])

    assert llm_fields["error"] == "provider returned status=500 and retry_after=30"
    assert "retry_after" not in llm_fields
    assert warning_fields["message"] == "Use option foo=bar only after login."
    assert warning_fields["action"] == "First run /register, then confirm status=ok manually"
    assert "foo" not in warning_fields
    assert parsed["status_counts"]["unavailable"] == 1


def test_cinnamon_applet_runtime_parser_ignores_fields_inside_quotes() -> None:
    parsed = parse_runtime_status(
        """
        [Tools und Account-Memory]
        account_memory=Demo/path path="/tmp/status=broken warning=fake" status=ok
        account_memory=Demo/message status=ok message="quoted warning=fake" warning=real
        account_memory_recovery=Demo status=needed command="python tool.py --note status=broken warning=fake" apply_command="python tool.py --apply"
        account_memory=Demo/single note='status=broken warning=fake' status=ok
        account_memory=Demo/backtick note=`warning=fake` status=ok warning=real
        account_memory=Demo/escaped path="/tmp/\\" status=broken warning=fake" status=ok warning=real
        account_memory=Demo/escaped-single note='it\\'s status=broken warning=fake' status=ok warning=real
        account_memory=Demo/unclosed path="/tmp/status=hidden status=broken warning=real
        """
    )

    path_fields = cinnamon_applet._parse_status_fields(parsed["sections"]["Tools und Account-Memory"][0])
    message_fields = cinnamon_applet._parse_status_fields(parsed["sections"]["Tools und Account-Memory"][1])
    recovery_fields = cinnamon_applet._parse_status_fields(parsed["sections"]["Tools und Account-Memory"][2])
    single_fields = cinnamon_applet._parse_status_fields(parsed["sections"]["Tools und Account-Memory"][3])
    backtick_fields = cinnamon_applet._parse_status_fields(parsed["sections"]["Tools und Account-Memory"][4])
    escaped_fields = cinnamon_applet._parse_status_fields(parsed["sections"]["Tools und Account-Memory"][5])
    escaped_single_fields = cinnamon_applet._parse_status_fields(parsed["sections"]["Tools und Account-Memory"][6])
    unclosed_fields = cinnamon_applet._parse_status_fields(parsed["sections"]["Tools und Account-Memory"][7])

    assert path_fields["path"] == '"/tmp/status=broken warning=fake"'
    assert path_fields["status"] == "ok"
    assert "warning" not in path_fields
    assert message_fields["message"] == '"quoted warning=fake"'
    assert message_fields["warning"] == "real"
    assert recovery_fields["command"] == '"python tool.py --note status=broken warning=fake"'
    assert recovery_fields["apply_command"] == '"python tool.py --apply"'
    assert single_fields["note"] == "'status=broken warning=fake'"
    assert single_fields["status"] == "ok"
    assert backtick_fields["note"] == "`warning=fake`"
    assert backtick_fields["warning"] == "real"
    assert escaped_fields["path"] == '"/tmp/\\" status=broken warning=fake"'
    assert escaped_fields["status"] == "ok"
    assert escaped_fields["warning"] == "real"
    assert escaped_single_fields["note"] == "'it\\'s status=broken warning=fake'"
    assert escaped_single_fields["status"] == "ok"
    assert escaped_single_fields["warning"] == "real"
    assert unclosed_fields["path"] == '"/tmp/status=hidden'
    assert unclosed_fields["status"] == "broken"
    assert unclosed_fields["warning"] == "real"
    assert parsed["status_counts"]["ok"] == 6
    assert parsed["status_counts"]["needed"] == 1
    assert parsed["status_counts"]["broken"] == 1
    assert parsed["status_counts"]["warning"] == 5
    assert parsed["summary"]["problem_status_count"] == 7
    assert parsed["summary"]["problem_statuses"] == "broken:1,needed:1,warning:5"


def test_cinnamon_applet_runtime_parser_keeps_apostrophes_in_free_text_neutral() -> None:
    parsed = parse_runtime_status(
        """
        [Lokale Dienste]
        service=demo error=can't connect status=unreachable warning=retry

        [Tools und Account-Memory]
        account_memory=Demo/message status=ok message=can't load warning=real
        account_memory=Demo/action status=ok action=don't retry warning=again
        account_memory=Demo/note note=can't status=ok warning=note
        """
    )

    service_fields = cinnamon_applet._parse_status_fields(parsed["sections"]["Lokale Dienste"][0])
    message_fields = cinnamon_applet._parse_status_fields(parsed["sections"]["Tools und Account-Memory"][0])
    action_fields = cinnamon_applet._parse_status_fields(parsed["sections"]["Tools und Account-Memory"][1])
    note_fields = cinnamon_applet._parse_status_fields(parsed["sections"]["Tools und Account-Memory"][2])

    assert service_fields["error"] == "can't connect"
    assert service_fields["status"] == "unreachable"
    assert service_fields["warning"] == "retry"
    assert message_fields["message"] == "can't load"
    assert message_fields["warning"] == "real"
    assert action_fields["action"] == "don't retry"
    assert action_fields["warning"] == "again"
    assert note_fields["note"] == "can't"
    assert note_fields["status"] == "ok"
    assert note_fields["warning"] == "note"
    assert parsed["status_counts"]["unreachable"] == 1
    assert parsed["status_counts"]["warning"] == 4
    assert parsed["summary"]["problem_statuses"] == "unreachable:1,warning:4"


def test_cinnamon_applet_runtime_parser_ignores_neutral_warning_flags() -> None:
    parsed = parse_runtime_status(
        """
        [Lokale Dienste]
        service=zero status=ok warning=0
        service=false status=ok warning=false
        service=off status=ok warning=off
        service=double status=ok warning="false"
        service=single status=ok warning='off'
        service=backtick status=ok warning=`none`
        service=real status=ok warning="retry"
        """
    )

    assert parsed["status_counts"]["warning"] == 1
    assert parsed["summary"]["problem_status_count"] == 1
    assert parsed["summary"]["problem_statuses"] == "warning:1"


def test_cinnamon_applet_js_ignores_neutral_warning_flags() -> None:
    for value, expected in (
        ("0", False),
        ("false", False),
        ("OFF", False),
        ('"false"', False),
        ("'OFF'", False),
        ("`none`", False),
        ("constructor", True),
        ("__proto__", True),
        ('"retry"', True),
    ):
        result = _run_js_applet_expression(
            f"applet._lineHasProblemStatus({{status: 'ok', warning: {json.dumps(value)}}})"
        )
        assert result is expected


def test_cinnamon_applet_js_does_not_render_neutral_warning_flags() -> None:
    result = _run_js_applet_expression(
        """
        ({
          zero: applet._errorText({warning: "0"}),
          quoted: applet._errorText({warning: '\"false\"'}),
          real: applet._errorText({warning: "retry"}),
          errorAndNeutral: applet._errorText({error: "network", warning: "off"})
        })
        """
    )

    assert result == {
        "zero": "",
        "quoted": "",
        "real": "; Warnung retry",
        "errorAndNeutral": "; Fehler network",
    }


def test_cinnamon_applet_runtime_parser_counts_status_field_after_free_text_error() -> None:
    parsed = parse_runtime_status(
        """
        [Lokale Dienste]
        service=demo error=network down status=unreachable warning=retry
        service=http status=unavailable error=provider returned status=500 and retry_after=30
        """
    )

    late_status_fields = cinnamon_applet._parse_status_fields(parsed["sections"]["Lokale Dienste"][0])
    embedded_status_fields = cinnamon_applet._parse_status_fields(parsed["sections"]["Lokale Dienste"][1])

    assert late_status_fields["error"] == "network down"
    assert late_status_fields["status"] == "unreachable"
    assert late_status_fields["warning"] == "retry"
    assert embedded_status_fields["error"] == "provider returned status=500 and retry_after=30"
    assert parsed["status_counts"]["unreachable"] == 1
    assert parsed["status_counts"]["unavailable"] == 1
    assert parsed["status_counts"]["warning"] == 1
    assert parsed["summary"]["llm_problem_status_count"] == 3
    assert parsed["summary"]["problem_status_count"] == 3
    assert parsed["summary"]["problem_statuses"] == "unavailable:1,unreachable:1,warning:1"


def test_cinnamon_applet_runtime_parser_counts_warning_field_after_error() -> None:
    parsed = parse_runtime_status(
        """
        [Tools und Account-Memory]
        account_memory=Demo/ok status=ok warning=fallback_sync_stale:entries
        account_memory=Demo/broken status=broken error=index mismatch warning=fallback_sync_stale:index
        account_memory=Demo/message status=ok message=loaded warning=fallback_sync_stale:message
        account_memory=Demo/action status=ok action=review memory warning=fallback_sync_stale:action
        """
    )

    ok_fields = cinnamon_applet._parse_status_fields(parsed["sections"]["Tools und Account-Memory"][0])
    broken_fields = cinnamon_applet._parse_status_fields(parsed["sections"]["Tools und Account-Memory"][1])
    message_fields = cinnamon_applet._parse_status_fields(parsed["sections"]["Tools und Account-Memory"][2])
    action_fields = cinnamon_applet._parse_status_fields(parsed["sections"]["Tools und Account-Memory"][3])

    assert ok_fields["warning"] == "fallback_sync_stale:entries"
    assert broken_fields["error"] == "index mismatch"
    assert broken_fields["warning"] == "fallback_sync_stale:index"
    assert message_fields["message"] == "loaded"
    assert message_fields["warning"] == "fallback_sync_stale:message"
    assert action_fields["action"] == "review memory"
    assert action_fields["warning"] == "fallback_sync_stale:action"
    assert parsed["status_counts"]["ok"] == 3
    assert parsed["status_counts"]["broken"] == 1
    assert parsed["status_counts"]["warning"] == 4
    assert parsed["summary"]["memory_problem_status_count"] == 5
    assert parsed["summary"]["problem_status_count"] == 5
    assert parsed["summary"]["problem_statuses"] == "broken:1,warning:4"


def test_cinnamon_applet_runtime_parser_counts_account_identity_warning_lines() -> None:
    parsed = parse_runtime_status(
        """
        [Tools und Account-Memory]
        account_identity_warning=Demo code=runtime_channel_without_identity message=signal runtime is configured action=run login
        """
    )

    assert parsed["status_counts"]["warning"] == 1
    assert parsed["summary"]["memory_problem_status_count"] == 1
    assert parsed["summary"]["problem_status_count"] == 1
    assert parsed["summary"]["problem_statuses"] == "warning:1"


def test_cinnamon_applet_runtime_parser_splits_legacy_recovery_commands() -> None:
    parsed = parse_runtime_status(
        """
        [Tools und Account-Memory]
        account_memory_recovery_legacy=Demo status=available sources=1 entries=2 path=/tmp/TeeBotus_Backups/TeeBotus.bak2/instances.bak command="python3 scripts/import_legacy_user_memory.py --json-output /tmp/import.json --markdown-output /tmp/import.md" apply_command="python3 scripts/import_legacy_user_memory.py --apply"
        """
    )

    line = parsed["sections"]["Tools und Account-Memory"][0]
    fields = cinnamon_applet._parse_status_fields(line)

    assert fields["account_memory_recovery_legacy"] == "Demo"
    assert fields["status"] == "available"
    assert fields["sources"] == "1"
    assert fields["entries"] == "2"
    assert fields["command"] == '"python3 scripts/import_legacy_user_memory.py --json-output /tmp/import.json --markdown-output /tmp/import.md"'
    assert fields["apply_command"] == '"python3 scripts/import_legacy_user_memory.py --apply"'
    assert parsed["status_counts"]["available"] == 1
    assert parsed["summary"]["problem_status_count"] == 0


def test_pyproject_declares_cinnamon_applet_helper_script() -> None:
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["scripts"]["teebotus-cinnamon-applet"] == "TeeBotus.cinnamon_applet:main"


def test_cinnamon_applet_install_script_targets_user_applet_dir() -> None:
    source = (PROJECT_ROOT / "scripts" / "install_cinnamon_applet.py").read_text(encoding="utf-8")

    assert 'APPLET_UUID = "teebotus@H234598"' in source
    assert 'SETTINGS_ICON_NAME = "teebotus.svg"' in source
    assert '".local" / "share" / "cinnamon" / "applets"' in source
    assert '".local" / "share" / "icons" / "hicolor" / "scalable" / "apps"' in source
    assert "shutil.copytree(source, target)" in source
    assert "shutil.rmtree(target)" in source
    assert "shutil.copy2(icon_source, icon_target)" in source
    assert "gtk-update-icon-cache" in source
