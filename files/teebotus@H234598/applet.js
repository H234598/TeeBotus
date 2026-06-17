const Applet = imports.ui.applet;
const PopupMenu = imports.ui.popupMenu;
const Settings = imports.ui.settings;
const St = imports.gi.St;
const Gio = imports.gi.Gio;
const GLib = imports.gi.GLib;
const Mainloop = imports.mainloop;

const UUID = "teebotus@H234598";
const DEFAULT_REPO_PATH = GLib.build_filenamev([GLib.get_home_dir(), "TeeBotus"]);
const DEFAULT_PYTHON = "/usr/bin/python3";
const DEFAULT_UNIT = "teebotus-runtime.service";
const DEFAULT_CHANNELS = "telegram,signal";
const STATUS_REFRESH_MIN_SECONDS = 15;
const MENU_LINE_LIMIT = 14;
const QUICK_COMMANDS = [
  "/status",
  "/info",
  "/help",
  "/voicemodel",
  "/mimic_voice",
  "/register",
  "/memory_reset"
];
const TERMINAL_CANDIDATES = [
  "gnome-terminal",
  "x-terminal-emulator",
  "kgx",
  "konsole",
  "xterm"
];

function TeeBotusApplet(metadata, orientation, panelHeight, instanceId) {
  this._init(metadata, orientation, panelHeight, instanceId);
}

TeeBotusApplet.prototype = {
  __proto__: Applet.TextIconApplet.prototype,

  _init: function(metadata, orientation, panelHeight, instanceId) {
    Applet.TextIconApplet.prototype._init.call(this, orientation, panelHeight, instanceId);
    this.metadata = metadata;
    this.repoPath = DEFAULT_REPO_PATH;
    this.pythonCommand = DEFAULT_PYTHON;
    this.channels = DEFAULT_CHANNELS;
    this.runtimeUnit = DEFAULT_UNIT;
    this.defaultInstance = "Depressionsbot";
    this.statusRefreshSeconds = 60;
    this.statusTimeoutSeconds = 20;
    this.showPanelLabel = true;
    this.panelLabelMode = "health";
    this.autoRefresh = true;
    this.showMessengerSection = true;
    this.showLlmSection = true;
    this.showMemorySection = true;
    this.showBibliothekarSection = true;
    this.showProactiveSection = true;
    this.showActionsSection = true;
    this.showQuickCommandsSection = true;
    this.showProjectSection = true;
    this.enableServiceActions = true;
    this.confirmServiceActions = true;
    this.terminalCommand = "";
    this.bibliothekarInstance = "Depressionsbot";
    this.libraryPath = GLib.build_filenamev([DEFAULT_REPO_PATH, "instances", "Depressionsbot", "data", "Bibliothek"]);
    this.proactiveInstance = "Depressionsbot";
    this.proactiveCommand = DEFAULT_PYTHON + " -m TeeBotus.proactive --instance Depressionsbot --dispatch --plan --tool-plan";
    this.githubUrl = "https://github.com/H234598/TeeBotus";
    this.commitsUrl = "https://github.com/H234598/TeeBotus/commits/main";
    this.clipboard = St.Clipboard.get_default();
    this.statusPayload = null;
    this.statusText = "";
    this.statusTimer = 0;
    this.statusRunning = false;
    this.lastError = "";

    this.set_applet_icon_path(this.metadata.path + "/icon.svg");
    this.set_applet_tooltip(_("TeeBotus"));
    this.set_applet_label("");

    this.settings = new Settings.AppletSettings(this, UUID, instanceId);
    this._bindSettings();
    this._buildMenu();
    this._refreshStatus();
    this._scheduleRefresh();
  },

  _bindSettings: function() {
    this.settings.bindProperty(Settings.BindingDirection.IN, "repo-path", "repoPath", this._onSettingsChanged, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "python-command", "pythonCommand", this._onSettingsChanged, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "channels", "channels", this._onSettingsChanged, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "runtime-unit", "runtimeUnit", this._onSettingsChanged, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "default-instance", "defaultInstance", this._onSettingsChanged, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "status-refresh-seconds", "statusRefreshSeconds", this._onRefreshSettingsChanged, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "status-timeout-seconds", "statusTimeoutSeconds", this._onSettingsChanged, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "show-panel-label", "showPanelLabel", this._updatePanel, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "panel-label-mode", "panelLabelMode", this._updatePanel, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "auto-refresh", "autoRefresh", this._onRefreshSettingsChanged, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "show-messenger-section", "showMessengerSection", this._rebuildFromSettings, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "show-llm-section", "showLlmSection", this._rebuildFromSettings, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "show-memory-section", "showMemorySection", this._rebuildFromSettings, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "show-bibliothekar-section", "showBibliothekarSection", this._rebuildFromSettings, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "show-proactive-section", "showProactiveSection", this._rebuildFromSettings, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "show-actions-section", "showActionsSection", this._rebuildFromSettings, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "show-quick-commands-section", "showQuickCommandsSection", this._rebuildFromSettings, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "show-project-section", "showProjectSection", this._rebuildFromSettings, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "enable-service-actions", "enableServiceActions", this._rebuildFromSettings, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "confirm-service-actions", "confirmServiceActions", null, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "terminal-command", "terminalCommand", null, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "bibliothekar-instance", "bibliothekarInstance", this._rebuildFromSettings, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "library-path", "libraryPath", null, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "proactive-instance", "proactiveInstance", this._rebuildFromSettings, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "proactive-command", "proactiveCommand", null, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "github-url", "githubUrl", null, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "commits-url", "commitsUrl", null, null);
  },

  _buildMenu: function() {
    this.menu.removeAll();
    this.headerItem = this._menuLine(_("TeeBotus"), false);
    this.headerItem.actor.add_style_class_name("teebotus-status-label");
    this.menu.addMenuItem(this.headerItem);
    this.summaryItem = this._menuLine(_("Status wird geladen..."), false);
    this.menu.addMenuItem(this.summaryItem);
    this.versionItem = this._menuLine("", false);
    this.menu.addMenuItem(this.versionItem);
    this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

    this.statusMenu = new PopupMenu.PopupSubMenuMenuItem(_("Status & Diagnose"));
    this.menu.addMenuItem(this.statusMenu);
    this.runtimeMenu = new PopupMenu.PopupSubMenuMenuItem(_("Runtime Details"));
    this.menu.addMenuItem(this.runtimeMenu);
    this.messengerMenu = new PopupMenu.PopupSubMenuMenuItem(_("Messenger"));
    this.llmMenu = new PopupMenu.PopupSubMenuMenuItem(_("LLM & Dienste"));
    this.memoryMenu = new PopupMenu.PopupSubMenuMenuItem(_("Memory & Speicher"));
    this.bibliothekarMenu = new PopupMenu.PopupSubMenuMenuItem(_("Bibliothekar"));
    this.proactiveMenu = new PopupMenu.PopupSubMenuMenuItem(_("Proaktiv"));
    this.actionsMenu = new PopupMenu.PopupSubMenuMenuItem(_("Bot-Steuerung"));
    this.quickCommandsMenu = new PopupMenu.PopupSubMenuMenuItem(_("Schnellbefehle"));
    this.projectMenu = new PopupMenu.PopupSubMenuMenuItem(_("Projekt"));
    if (this.showMessengerSection) this.menu.addMenuItem(this.messengerMenu);
    if (this.showLlmSection) this.menu.addMenuItem(this.llmMenu);
    if (this.showMemorySection) this.menu.addMenuItem(this.memoryMenu);
    if (this.showBibliothekarSection) this.menu.addMenuItem(this.bibliothekarMenu);
    if (this.showProactiveSection) this.menu.addMenuItem(this.proactiveMenu);
    if (this.showActionsSection) this.menu.addMenuItem(this.actionsMenu);
    if (this.showQuickCommandsSection) this.menu.addMenuItem(this.quickCommandsMenu);
    if (this.showProjectSection) this.menu.addMenuItem(this.projectMenu);
    this._populateStaticMenus();
    this._populateDynamicMenus();
  },

  _populateStaticMenus: function() {
    this.statusMenu.menu.removeAll();
    this.statusMenu.menu.addMenuItem(this._actionItem(_("Status aktualisieren"), () => this._refreshStatus()));
    this.statusMenu.menu.addMenuItem(this._actionItem(_("Runtime-Status im Terminal"), () => this._openRuntimeStatusTerminal()));
    this.statusMenu.menu.addMenuItem(this._actionItem(_("Status JSON kopieren"), () => this._copyStatusJson()));
    this.statusMenu.menu.addMenuItem(this._actionItem(_("Applet-Einstellungen"), () => this._openAppletSettings()));

    this.actionsMenu.menu.removeAll();
    if (!this.enableServiceActions) {
      this.actionsMenu.menu.addMenuItem(this._menuLine(_("Service-Actions sind in den Einstellungen deaktiviert."), false));
    } else {
      this.actionsMenu.menu.addMenuItem(this._actionItem(_("Bot starten"), () => this._serviceAction("start")));
      this.actionsMenu.menu.addMenuItem(this._actionItem(_("Bot neu starten"), () => this._serviceAction("restart")));
      this.actionsMenu.menu.addMenuItem(this._actionItem(_("Bot stoppen"), () => this._serviceAction("stop")));
    }
    this.actionsMenu.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
    this.actionsMenu.menu.addMenuItem(this._actionItem(_("Logs im Terminal"), () => this._openLogsTerminal()));

    this.bibliothekarMenu.menu.removeAll();
    this.bibliothekarMenu.menu.addMenuItem(this._actionItem(_("Bibliothekar-Status im Terminal"), () => this._openBibliothekarStatus()));
    this.bibliothekarMenu.menu.addMenuItem(this._actionItem(_("Bibliothek-Ordner öffnen"), () => this._openPath(this.libraryPath)));
    this.bibliothekarMenu.menu.addMenuItem(this._actionItem(_("Bibliothekar-Hilfe im Terminal"), () => this._openTerminalForCommand(this._repoPath(), this._pythonArgs().concat(["-m", "TeeBotus.bibliothekar", "--help"]))));

    this.proactiveMenu.menu.removeAll();
    this.proactiveMenu.menu.addMenuItem(this._actionItem(_("Proaktiv einmal ausführen"), () => this._runProactiveOnce()));
    this.proactiveMenu.menu.addMenuItem(this._actionItem(_("Proaktiv-Timer Status"), () => this._openTerminalForCommand(this._repoPath(), ["systemctl", "--user", "status", "teebotus-proactive-" + this._safeUnitToken(this.proactiveInstance) + ".timer"])));
    this.proactiveMenu.menu.addMenuItem(this._actionItem(_("Proaktiv-Logs"), () => this._openTerminalForCommand(this._repoPath(), ["journalctl", "--user", "-u", "teebotus-proactive-" + this._safeUnitToken(this.proactiveInstance) + ".service", "-n", "80", "--no-pager"])));

    this.quickCommandsMenu.menu.removeAll();
    for (let command of QUICK_COMMANDS) {
      this.quickCommandsMenu.menu.addMenuItem(this._actionItem(_("Kopieren: ") + command, () => this._copyText(command)));
    }
    this.quickCommandsMenu.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
    this.quickCommandsMenu.menu.addMenuItem(this._actionItem(_("Alle Schnellbefehle kopieren"), () => this._copyText(QUICK_COMMANDS.join("\n"))));

    this.projectMenu.menu.removeAll();
    this.projectMenu.menu.addMenuItem(this._actionItem(_("Repo-Ordner öffnen"), () => this._openPath(this._repoPath())));
    this.projectMenu.menu.addMenuItem(this._actionItem(_("GitHub öffnen"), () => this._openUri(this.githubUrl)));
    this.projectMenu.menu.addMenuItem(this._actionItem(_("Commits öffnen"), () => this._openUri(this.commitsUrl)));
    this.projectMenu.menu.addMenuItem(this._actionItem(_("README im Terminal"), () => this._openTerminalForCommand(this._repoPath(), ["sed", "-n", "1,140p", "README.md"])));
  },

  _populateDynamicMenus: function() {
    let payload = this.statusPayload || {};
    let runtime = payload.runtime || {};
    let sections = runtime.sections || {};
    this._populateLines(this.runtimeMenu.menu, (sections["Konfiguration"] || []).concat(sections["Start"] || []), _("Keine Runtime-Konfiguration geladen."));
    this._populateLines(this.messengerMenu.menu, sections["Messenger"] || [], _("Keine Messenger-Zeilen."));
    this._populateLines(this.llmMenu.menu, sections["LLM-Routen und Backends"] || [], _("Keine LLM-Diagnose."));
    this._populateLines(this.memoryMenu.menu, sections["Memory und semantische Suche"] || [], _("Keine Memory-Diagnose."));
    if (this.showBibliothekarSection) {
      this.bibliothekarMenu.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
      this._appendLines(this.bibliothekarMenu.menu, this._filterLines(sections["Lokale Dienste"] || [], ["bibliothekar="]), _("Keine Bibliothekar-Statuszeilen."));
    }
    if (this.showProactiveSection) {
      this.proactiveMenu.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
      this._appendLines(this.proactiveMenu.menu, sections["Agenten-Piloten"] || [], _("Keine Agenten-Pilot-Zeilen."));
    }
  },

  _populateLines: function(menu, lines, emptyText) {
    menu.removeAll();
    this._appendLines(menu, lines, emptyText);
  },

  _appendLines: function(menu, lines, emptyText) {
    let values = lines || [];
    if (values.length === 0) {
      menu.addMenuItem(this._menuLine(emptyText, false));
      return;
    }
    for (let i = 0; i < values.length && i < MENU_LINE_LIMIT; i++) {
      menu.addMenuItem(this._menuLine(this._shortText(values[i], 110), false));
    }
    if (values.length > MENU_LINE_LIMIT) {
      menu.addMenuItem(this._menuLine(_("Weitere Zeilen: ") + String(values.length - MENU_LINE_LIMIT), false));
    }
  },

  _refreshStatus: function() {
    if (this.statusRunning) {
      return;
    }
    this.statusRunning = true;
    this._setPanelState("refreshing");
    this._spawnJson(this._statusCommand(), (payload, error) => {
      this.statusRunning = false;
      if (error) {
        this.lastError = error;
        this.statusPayload = null;
        this.statusText = _("Statusfehler: ") + this._shortText(error, 80);
      } else {
        this.statusPayload = payload;
        this.lastError = "";
        this.statusText = this._statusSummary(payload);
      }
      this._updatePanel();
      this._updateHeader();
      this._buildMenu();
    });
  },

  _statusCommand: function() {
    return this._pythonArgs().concat([
      "-m",
      "TeeBotus.cinnamon_applet",
      "status",
      "--repo-root",
      this._repoPath(),
      "--channels",
      String(this.channels || DEFAULT_CHANNELS),
      "--unit",
      String(this.runtimeUnit || DEFAULT_UNIT),
      "--python",
      this._pythonPath(),
      "--timeout",
      String(this._positiveInt(this.statusTimeoutSeconds, 20))
    ]);
  },

  _statusSummary: function(payload) {
    let unit = payload.unit || {};
    let runtime = payload.runtime || {};
    let summary = runtime.summary || {};
    let counts = runtime.status_counts || {};
    let bad = (counts.broken || 0) + (counts.unavailable || 0) + (counts.unreachable || 0) + (counts.missing || 0) + (counts.missing_key || 0);
    let state = String(unit.active_state || "unknown");
    let instances = String(summary.instances || "?");
    let channels = String(summary.channels || this.channels || DEFAULT_CHANNELS);
    return "Unit " + state + " | " + instances + " | " + channels + " | Warnungen " + String(bad);
  },

  _updateHeader: function() {
    let payload = this.statusPayload || {};
    let repo = payload.repo || {};
    let unit = payload.unit || {};
    let runtime = payload.runtime || {};
    let summary = runtime.summary || {};
    this.headerItem.label.set_text("TeeBotus " + String(payload.version || "?"));
    this.summaryItem.label.set_text(this.statusText || _("Status unbekannt"));
    let commit = repo.short_commit ? " | " + repo.short_commit : "";
    this.versionItem.label.set_text("Unit: " + String(unit.active_state || "unknown") + " / " + String(unit.sub_state || "unknown") + commit + " | LLM-Routen: " + String(summary.llm_routes || 0));
  },

  _updatePanel: function() {
    if (!this.showPanelLabel || this.panelLabelMode === "icon") {
      this.set_applet_label("");
      return;
    }
    let payload = this.statusPayload || {};
    let runtime = payload.runtime || {};
    let summary = runtime.summary || {};
    let unit = payload.unit || {};
    if (this.panelLabelMode === "version") {
      this.set_applet_label("TB " + String(payload.version || "?"));
    } else if (this.panelLabelMode === "instances") {
      this.set_applet_label("TB " + String(summary.instances || "?"));
    } else {
      this.set_applet_label("TB " + String(unit.active_state || "…"));
    }
    this.set_applet_tooltip(this.statusText || _("TeeBotus"));
  },

  _setPanelState: function(state) {
    if (state === "refreshing") {
      this.set_applet_label(this.showPanelLabel ? "TB …" : "");
    }
  },

  _spawnJson: function(argv, callback) {
    this._spawn(argv, (stdout, stderr, ok) => {
      if (!ok) {
        callback(null, stderr || _("Command failed"));
        return;
      }
      try {
        callback(JSON.parse(stdout), null);
      } catch (err) {
        callback(null, _("Invalid JSON from helper: ") + String(err));
      }
    });
  },

  _spawn: function(argv, callback) {
    try {
      let process = Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE);
      process.communicate_utf8_async(null, null, (proc, result) => {
        try {
          let [, stdout, stderr] = proc.communicate_utf8_finish(result);
          callback(String(stdout || ""), String(stderr || ""), proc.get_successful());
        } catch (err) {
          callback("", String(err), false);
        }
      });
    } catch (err) {
      callback("", String(err), false);
    }
  },

  _serviceAction: function(action) {
    if (!this.enableServiceActions) {
      return;
    }
    let unit = String(this.runtimeUnit || DEFAULT_UNIT).trim();
    if (!unit) {
      return;
    }
    let run = () => {
      this._spawn(["systemctl", "--user", action, unit], (stdout, stderr, ok) => {
        this.statusText = ok ? _("Service action completed: ") + action : _("Service action failed: ") + (stderr || stdout);
        this._refreshStatus();
      });
    };
    if (!this.confirmServiceActions) {
      run();
      return;
    }
    if (!GLib.find_program_in_path("zenity")) {
      this.statusText = _("Install zenity or disable confirmation to run service actions.");
      this._updatePanel();
      this._updateHeader();
      return;
    }
    this._spawn(["zenity", "--question", "--title=TeeBotus", "--text=" + action + " " + unit + "?"], (stdout, stderr, ok) => {
      if (ok) {
        run();
      }
    });
  },

  _openRuntimeStatusTerminal: function() {
    this._openTerminalForCommand(this._repoPath(), this._pythonArgs().concat(["-m", "TeeBotus", "--runtime-status", "--channels", String(this.channels || DEFAULT_CHANNELS)]));
  },

  _openLogsTerminal: function() {
    this._openTerminalForCommand(this._repoPath(), ["journalctl", "--user", "-u", String(this.runtimeUnit || DEFAULT_UNIT), "-n", "120", "-f"]);
  },

  _openBibliothekarStatus: function() {
    this._openTerminalForCommand(
      this._repoPath(),
      this._pythonArgs().concat(["-m", "TeeBotus.bibliothekar", "--instance", String(this.bibliothekarInstance || this.defaultInstance || "Depressionsbot"), "status"])
    );
  },

  _runProactiveOnce: function() {
    let command = String(this.proactiveCommand || "").trim();
    if (!command) {
      command = this._pythonPath() + " -m TeeBotus.proactive --instance " + this._safeShellWord(this.proactiveInstance || "Depressionsbot") + " --dispatch --plan --tool-plan";
    }
    this._openTerminalShell(this._repoPath(), command);
  },

  _openTerminalForCommand: function(cwd, argv) {
    this._openTerminalShell(cwd, argv.map((part) => this._safeShellWord(part)).join(" "));
  },

  _openTerminalShell: function(cwd, command) {
    let terminal = this._terminalArgs();
    if (!terminal) {
      this.statusText = _("No terminal found.");
      this._updatePanel();
      return;
    }
    let shellCommand = "cd " + this._safeShellWord(cwd) + " && " + command + "; printf '\\n'; read -r -p 'Enter zum Schliessen...'";
    let argv = terminal.concat(["bash", "-lc", shellCommand]);
    this._spawn(argv, () => {});
  },

  _terminalArgs: function() {
    let configured = String(this.terminalCommand || "").trim();
    if (configured) {
      return [configured, "--"];
    }
    for (let candidate of TERMINAL_CANDIDATES) {
      if (!GLib.find_program_in_path(candidate)) {
        continue;
      }
      if (candidate === "xterm") {
        return [candidate, "-e"];
      }
      if (candidate === "konsole") {
        return [candidate, "-e"];
      }
      return [candidate, "--"];
    }
    return null;
  },

  _copyStatusJson: function() {
    this._copyText(JSON.stringify(this.statusPayload || {}, null, 2));
  },

  _copyText: function(text) {
    this.clipboard.set_text(St.ClipboardType.CLIPBOARD, String(text || ""));
    this.statusText = _("Kopiert.");
    this._updatePanel();
  },

  _openAppletSettings: function() {
    this._spawn(["cinnamon-settings", "applets", UUID], () => {});
  },

  _openPath: function(path) {
    this._spawn(["gio", "open", String(path || this._repoPath())], () => {});
  },

  _openUri: function(uri) {
    this._spawn(["gio", "open", String(uri || this.githubUrl)], () => {});
  },

  _menuLine: function(label, reactive) {
    return new PopupMenu.PopupMenuItem(String(label || ""), { reactive: Boolean(reactive) });
  },

  _actionItem: function(label, callback) {
    let item = new PopupMenu.PopupMenuItem(String(label || ""));
    item.connect("activate", callback);
    return item;
  },

  _filterLines: function(lines, prefixes) {
    let result = [];
    for (let line of lines || []) {
      for (let prefix of prefixes || []) {
        if (String(line).indexOf(prefix) === 0) {
          result.push(line);
          break;
        }
      }
    }
    return result;
  },

  _pythonArgs: function() {
    return [this._pythonPath()];
  },

  _pythonPath: function() {
    return String(this.pythonCommand || DEFAULT_PYTHON).trim() || DEFAULT_PYTHON;
  },

  _repoPath: function() {
    return String(this.repoPath || DEFAULT_REPO_PATH).trim() || DEFAULT_REPO_PATH;
  },

  _positiveInt: function(value, fallback) {
    let parsed = parseInt(value, 10);
    return parsed > 0 ? parsed : fallback;
  },

  _safeUnitToken: function(value) {
    return String(value || "").trim().toLowerCase().replace(/[^a-z0-9_.@-]+/g, "-") || "depressionsbot";
  },

  _safeShellWord: function(value) {
    return "'" + String(value || "").replace(/'/g, "'\\''") + "'";
  },

  _shortText: function(value, limit) {
    let text = String(value || "").replace(/\s+/g, " ").trim();
    let max = limit || 80;
    if (text.length <= max) {
      return text;
    }
    return text.slice(0, max - 1) + "…";
  },

  _onSettingsChanged: function() {
    this._refreshStatus();
  },

  _onRefreshSettingsChanged: function() {
    this._scheduleRefresh();
    this._refreshStatus();
  },

  _rebuildFromSettings: function() {
    this._buildMenu();
  },

  _scheduleRefresh: function() {
    if (this.statusTimer) {
      Mainloop.source_remove(this.statusTimer);
      this.statusTimer = 0;
    }
    if (!this.autoRefresh) {
      return;
    }
    let seconds = Math.max(STATUS_REFRESH_MIN_SECONDS, this._positiveInt(this.statusRefreshSeconds, 60));
    this.statusTimer = Mainloop.timeout_add_seconds(seconds, () => {
      this._refreshStatus();
      return Boolean(this.autoRefresh);
    });
  },

  on_applet_clicked: function() {
    this._refreshStatus();
    this.menu.toggle();
  },

  on_applet_removed_from_panel: function() {
    if (this.statusTimer) {
      Mainloop.source_remove(this.statusTimer);
      this.statusTimer = 0;
    }
  }
};

function main(metadata, orientation, panelHeight, instanceId) {
  return new TeeBotusApplet(metadata, orientation, panelHeight, instanceId);
}
