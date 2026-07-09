const Applet = imports.ui.applet;
const ModalDialog = imports.ui.modalDialog;
const PopupMenu = imports.ui.popupMenu;
const Settings = imports.ui.settings;
const Clutter = imports.gi.Clutter;
const St = imports.gi.St;
const Gio = imports.gi.Gio;
const GLib = imports.gi.GLib;
const Pango = imports.gi.Pango;
const Mainloop = imports.mainloop;

const UUID = "teebotus@H234598";
const DEFAULT_REPO_PATH = GLib.build_filenamev([GLib.get_home_dir(), "TeeBotus"]);
const DEFAULT_PYTHON = "/usr/bin/python3";
const DEFAULT_UNIT = "teebotus.service";
const DEFAULT_CHANNELS = "telegram,signal";
const DEFAULT_QDRANT_UNIT = "teebotus-qdrant.service";
const DEFAULT_QDRANT_URL = "http://127.0.0.1:6333";
const DEFAULT_CODEX_USAGE_PATH = GLib.build_filenamev([GLib.get_home_dir(), "codex-usage"]);
const DEFAULT_CODEX_USAGE_COMMAND = "codex-usage";
const DEFAULT_GITHUB_URL = "https://github.com/H234598/TeeBotus";
const DEFAULT_COMMITS_URL = "https://github.com/H234598/TeeBotus/commits/main";
const DEFAULT_STATUS_REFRESH_SECONDS = 60;
const DEFAULT_STATUS_TIMEOUT_SECONDS = 30;
const STATUS_REFRESH_MIN_SECONDS = 15;
const STATUS_TIMEOUT_MIN_SECONDS = 1;
const STATUS_TIMEOUT_MAX_SECONDS = 300;
const STATUS_TIMEOUT_GRACE_SECONDS = 5;
const CODEX_USAGE_STALE_WARNING_HOURS = 24;
const MAX_HELPER_JSON_CHARS = 120000;
const MAX_COMMAND_ARG_CHARS = 4096;
const MAX_COMMAND_ARG_COUNT = 128;
const MAX_COMMAND_CHARS = 32768;
const MENU_MIN_WIDTH_EM = 34;
const MENU_LABEL_WIDTH_EM = 42;
const SUBMENU_MIN_WIDTH_EM = 44;
const SUBMENU_LABEL_WIDTH_EM = 48;
const MENU_LINE_LIMIT = 14;
const ALLOWED_CHANNELS = ["telegram", "signal", "matrix"];
const SAFE_PYTHON_PREFIX_FLAGS = ["-B", "-u", "-I", "-S", "-E", "-s", "-q", "-O", "-OO"];
const PROBLEM_STATUSES = [
  "broken",
  "config_conflict",
  "cooldown",
  "degraded",
  "error",
  "failed",
  "fallback_defaults",
  "invalid",
  "missing",
  "missing_key",
  "never",
  "needed",
  "no_limits_found",
  "schema_mismatch",
  "stale",
  "unknown",
  "unavailable",
  "unreachable",
  "unsupported",
  "warning"
];
const SECONDARY_PROBLEM_STATUS_FIELDS = [
  "models_feed",
  "route_status",
  "semantic"
];
const STATUS_FIELD_BOUNDARY_KEYS = {
  status: true,
  models_feed: true,
  route_status: true,
  semantic: true
};
const STATUS_FIELD_NEUTRAL_BOUNDARY_VALUES = {
  available: true,
  configured: true,
  disabled: true,
  enabled: true,
  healthy: true,
  installed: true,
  not_applicable: true,
  not_configured: true,
  ok: true,
  planned: true,
  reachable: true,
  ready: true,
  rebuilt: true,
  registered: true
};
const FREE_TEXT_STATUS_FIELDS = {
  action: true,
  command: true,
  error: true,
  message: true,
  route_error: true
};
const FREE_TEXT_STATUS_FIELD_BOUNDARIES = {
  action: { warning: true },
  command: { apply_command: true },
  error: { warning: true },
  message: { action: true, warning: true },
  route_error: {
    fallback: true,
    fallback_api_key: true,
    fallback_base_url: true,
    fallback_model: true,
    fallback_models: true,
    fallback_profile: true,
    remote_fallback: true,
    warning: true
  }
};
const FLAG_PROBLEM_STATUS_FIELDS = [
  "warning"
];
const FORCED_PROBLEM_STATUS_FIELDS = {
  account_identity_warning: "warning"
};
const QUICK_COMMANDS = [
  "/status",
  "/info",
  "/help",
  "/voicemodel",
  "/mimic_voice",
  "/register",
  "/memory_reset"
];
const MAX_UNIT_TOKEN_CHARS = 96;
const TRUSTED_SPAWN_DIRS = ["/usr/bin", "/usr/local/bin", "/bin"];
const TRUSTED_USER_LOCAL_SPAWN_DIR = GLib.build_filenamev([GLib.get_home_dir(), ".local", "bin"]);
const TRUSTED_USER_LOCAL_COMMANDS = {
  "codex-usage": true
};
const TERMINAL_CANDIDATES = [
  "gnome-terminal",
  "x-terminal-emulator",
  "kgx",
  "konsole",
  "xterm"
];

function _(text) {
  return text;
}

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
    this.qdrantUnit = DEFAULT_QDRANT_UNIT;
    this.qdrantUrl = DEFAULT_QDRANT_URL;
    this.defaultInstance = "Depressionsbot";
    this.statusRefreshSeconds = DEFAULT_STATUS_REFRESH_SECONDS;
    this.statusTimeoutSeconds = DEFAULT_STATUS_TIMEOUT_SECONDS;
    this.showPanelLabel = true;
    this.panelLabelMode = "health";
    this.autoRefresh = true;
    this.showMessengerSection = true;
    this.showLlmSection = true;
    this.showApiSection = true;
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
    this.githubUrl = DEFAULT_GITHUB_URL;
    this.commitsUrl = DEFAULT_COMMITS_URL;
    this.codexUsagePath = DEFAULT_CODEX_USAGE_PATH;
    this.codexUsageCommand = DEFAULT_CODEX_USAGE_COMMAND;
    this.clipboard = St.Clipboard.get_default();
    this.statusPayload = null;
    this.statusText = "";
    this.statusTimer = 0;
    this.statusRunning = false;
    this.statusRefreshPending = false;
    this.lastError = "";
    this.appletRemoved = false;
    this.spawnGeneration = 0;

    this.set_applet_icon_path(this.metadata.path + "/icon.svg");
    this.set_applet_tooltip(_("TB"));
    this.set_applet_label("TB");
    this.menuManager = new PopupMenu.PopupMenuManager(this);
    this.menu = new Applet.AppletPopupMenu(this, orientation);
    this.menuManager.addMenu(this.menu);

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
    this.settings.bindProperty(Settings.BindingDirection.IN, "qdrant-unit", "qdrantUnit", this._onSettingsChanged, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "qdrant-url", "qdrantUrl", this._onSettingsChanged, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "default-instance", "defaultInstance", this._onSettingsChanged, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "status-refresh-seconds", "statusRefreshSeconds", this._onRefreshSettingsChanged, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "status-timeout-seconds", "statusTimeoutSeconds", this._onSettingsChanged, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "show-panel-label", "showPanelLabel", this._updatePanel, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "panel-label-mode", "panelLabelMode", this._updatePanel, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "auto-refresh", "autoRefresh", this._onRefreshSettingsChanged, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "show-messenger-section", "showMessengerSection", this._rebuildFromSettings, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "show-llm-section", "showLlmSection", this._rebuildFromSettings, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "show-api-section", "showApiSection", this._rebuildFromSettings, null);
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
    this.settings.bindProperty(Settings.BindingDirection.IN, "codex-usage-path", "codexUsagePath", null, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "codex-usage-command", "codexUsageCommand", null, null);
  },

  _buildMenu: function() {
    this.menu.removeAll();
    this.headerItem = this._menuLine(_("TB"), false);
    this.headerItem.actor.add_style_class_name("teebotus-status-label");
    this.menu.addMenuItem(this.headerItem);
    this.summaryItem = this._menuLine(_("Status wird geladen..."), false);
    this._styleMenuItemLabel(this.summaryItem, { maxWidthEm: SUBMENU_LABEL_WIDTH_EM, wrap: true });
    this.menu.addMenuItem(this.summaryItem);
    this.versionItem = this._menuLine("", false);
    this._styleMenuItemLabel(this.versionItem, { maxWidthEm: SUBMENU_LABEL_WIDTH_EM, wrap: true });
    this.menu.addMenuItem(this.versionItem);
    this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

    this.statusMenu = new PopupMenu.PopupSubMenuMenuItem(_("Status & Diagnose"));
    this.menu.addMenuItem(this.statusMenu);
    this.runtimeMenu = new PopupMenu.PopupSubMenuMenuItem(_("Runtime Details"));
    this.menu.addMenuItem(this.runtimeMenu);
    this.messengerMenu = new PopupMenu.PopupSubMenuMenuItem(_("Messenger"));
    this.llmMenu = new PopupMenu.PopupSubMenuMenuItem(_("LLM & Dienste"));
    this.apiMenu = new PopupMenu.PopupSubMenuMenuItem(_("API Keys & Usage"));
    this.memoryMenu = new PopupMenu.PopupSubMenuMenuItem(_("Memory & Speicher"));
    this.bibliothekarMenu = new PopupMenu.PopupSubMenuMenuItem(_("Bibliothekar"));
    this.proactiveMenu = new PopupMenu.PopupSubMenuMenuItem(_("Proaktiv"));
    this.actionsMenu = new PopupMenu.PopupSubMenuMenuItem(_("Bot-Steuerung"));
    this.quickCommandsMenu = new PopupMenu.PopupSubMenuMenuItem(_("Schnellbefehle"));
    this.projectMenu = new PopupMenu.PopupSubMenuMenuItem(_("Projekt"));
    if (this.showMessengerSection) this.menu.addMenuItem(this.messengerMenu);
    if (this.showLlmSection) this.menu.addMenuItem(this.llmMenu);
    if (this.showApiSection) this.menu.addMenuItem(this.apiMenu);
    if (this.showMemorySection) this.menu.addMenuItem(this.memoryMenu);
    if (this.showBibliothekarSection) this.menu.addMenuItem(this.bibliothekarMenu);
    if (this.showProactiveSection) this.menu.addMenuItem(this.proactiveMenu);
    if (this.showActionsSection) this.menu.addMenuItem(this.actionsMenu);
    if (this.showQuickCommandsSection) this.menu.addMenuItem(this.quickCommandsMenu);
    if (this.showProjectSection) this.menu.addMenuItem(this.projectMenu);
    this._applyMenuLayout();
    this._populateStaticMenus();
    this._populateDynamicMenus();
    this._updateHeader();
  },

  _applyMenuLayout: function() {
    this._stylePopupMenu(this.menu, MENU_MIN_WIDTH_EM);
    this._styleSubmenu(this.statusMenu);
    this._styleSubmenu(this.runtimeMenu);
    this._styleSubmenu(this.messengerMenu);
    this._styleSubmenu(this.llmMenu);
    this._styleSubmenu(this.apiMenu);
    this._styleSubmenu(this.memoryMenu);
    this._styleSubmenu(this.bibliothekarMenu);
    this._styleSubmenu(this.proactiveMenu);
    this._styleSubmenu(this.actionsMenu);
    this._styleSubmenu(this.quickCommandsMenu);
    this._styleSubmenu(this.projectMenu);
  },

  _stylePopupMenu: function(menu, widthEm) {
    let style = "min-width: " + String(widthEm) + "em;";
    if (menu && menu.box && menu.box.set_style) {
      menu.box.set_style(style);
    }
    if (menu && menu.actor && menu.actor.set_style) {
      menu.actor.set_style(style);
    }
  },

  _styleSubmenu: function(menuItem) {
    if (!menuItem || !menuItem.menu) {
      return;
    }
    this._styleMenuItemLabel(menuItem, { maxWidthEm: MENU_LABEL_WIDTH_EM });
    this._stylePopupMenu(menuItem.menu, SUBMENU_MIN_WIDTH_EM);
  },

  _styleMenuItemLabel: function(item, options) {
    options = options || {};
    if (!item || !item.label) {
      return item;
    }
    let maxWidth = Number(options.maxWidthEm || SUBMENU_LABEL_WIDTH_EM);
    if (item.label.set_style) {
      item.label.set_style("max-width: " + String(maxWidth) + "em;");
    }
    try {
      if (item.label.clutter_text) {
        if (options.wrap && Pango && Pango.WrapMode) {
          item.label.clutter_text.line_wrap_mode = Pango.WrapMode.WORD_CHAR;
        }
        item.label.clutter_text.line_wrap = Boolean(options.wrap);
        if (Pango && Pango.EllipsizeMode) {
          item.label.clutter_text.ellipsize = options.wrap ? Pango.EllipsizeMode.NONE : Pango.EllipsizeMode.END;
        }
      }
    } catch (err) {
      global.logError(err);
    }
    return item;
  },

  _populateStaticMenus: function() {
    this.statusMenu.menu.removeAll();
    this.statusMenu.menu.addMenuItem(this._actionItem(_("Status aktualisieren"), () => this._refreshStatus()));
    this.statusMenu.menu.addMenuItem(this._actionItem(_("Runtime-Status im Terminal"), () => this._openRuntimeStatusTerminal()));
    this.statusMenu.menu.addMenuItem(this._actionItem(_("Qdrant-Status im Terminal"), () => this._openQdrantStatusTerminal()));
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
    this.bibliothekarMenu.menu.addMenuItem(this._actionItem(_("Bibliothek-Ordner öffnen"), () => this._openPath(this._libraryPath())));
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
    this.projectMenu.menu.addMenuItem(this._actionItem(_("GitHub öffnen"), () => this._openUri(this._githubUrl())));
    this.projectMenu.menu.addMenuItem(this._actionItem(_("Commits öffnen"), () => this._openUri(this._commitsUrl())));
    this.projectMenu.menu.addMenuItem(this._actionItem(_("README im Terminal"), () => this._openTerminalForCommand(this._repoPath(), ["sed", "-n", "1,140p", "README.md"])));
    this.projectMenu.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
    this.projectMenu.menu.addMenuItem(this._actionItem(_("Codex-History Report"), () => this._openCodexHistoryReport()));
    this.projectMenu.menu.addMenuItem(this._actionItem(_("Codex-History Index jetzt"), () => this._openCodexHistoryIndex()));
    this.projectMenu.menu.addMenuItem(this._actionItem(_("Codex-History Strategie jetzt"), () => this._openCodexHistoryStrategy()));
    this.projectMenu.menu.addMenuItem(this._actionItem(_("Codex-History Timer aktivieren"), () => this._openCodexHistoryTimerEnable()));
    this.projectMenu.menu.addMenuItem(this._actionItem(_("Codex-History Timer Status"), () => this._openCodexHistoryTimerStatus()));
  },

  _populateDynamicMenus: function() {
    let payload = this.statusPayload || {};
    let runtime = payload.runtime || {};
    let sections = runtime.sections || {};
    let summary = runtime.summary || {};
    let runtimeLines = [];
    if (summary.instances || summary.channels) {
      runtimeLines.push("Instanzen: " + String(summary.instances || "?") + " | Kanaele: " + String(summary.channels || this._channels()));
    }
    runtimeLines = runtimeLines.concat(this._formatLines((sections["Konfiguration"] || []).concat(sections["Start"] || []), (line) => this._formatRuntimeLine(line)));
    this._populateLines(this.runtimeMenu.menu, runtimeLines, this._dynamicEmptyText(_("Runtime-Konfiguration wird geladen.")));

    let messengerLines = [];
    if (summary.telegram_slots || summary.signal_accounts || summary.matrix_homeservers) {
      messengerLines.push(
        "Uebersicht: Telegram-Slots " + String(summary.telegram_slots || 0)
        + " | Signal-Accounts " + String(summary.signal_accounts || 0)
        + " | Matrix-Homeserver " + String(summary.matrix_homeservers || 0)
        + this._sectionProblemText(summary.messenger_problem_status_count)
      );
    }
    messengerLines = messengerLines.concat(this._formatLines(sections["Messenger"] || [], (line) => this._formatMessengerLine(line)));
    this._populateLines(this.messengerMenu.menu, messengerLines, this._dynamicEmptyText(_("Messenger-Diagnose wird geladen.")));

    let llmLines = [];
    if (summary.llm_routes || summary.hf_pool || summary.gemini_free_tier) {
      llmLines.push("Uebersicht: LLM-Routen " + String(summary.llm_routes || 0) + this._sectionProblemText(summary.llm_problem_status_count));
    }
    let llmStatusGroups = this._splitProblemStatusLines((sections["LLM-Routen und Backends"] || []).concat(sections["Accounts und Entscheidungen"] || []));
    let localServiceLines = this._problemStatusLines(sections["Lokale Dienste"] || []);
    llmLines = llmLines.concat(this._formatLines(llmStatusGroups.problem, (line) => this._formatLlmLine(line)));
    llmLines = llmLines.concat(this._formatLines(localServiceLines, (line) => this._formatLlmLine(line)));
    llmLines = llmLines.concat(this._formatLines(llmStatusGroups.normal, (line) => this._formatLlmLine(line)));
    this._populateLines(this.llmMenu.menu, llmLines, this._dynamicEmptyText(_("LLM-Diagnose wird geladen.")));

    if (this.showApiSection) {
      let apiLines = [];
      if (summary.api_budgets || summary.codex_usage_accounts) {
        apiLines.push(
          "Uebersicht: API-Routen " + String(summary.api_budgets || 0)
          + " | codex-usage Accounts " + String(summary.codex_usage_accounts || 0)
          + this._sectionProblemText(summary.api_problem_status_count)
        );
      }
      apiLines = apiLines.concat(this._formatLines(this._problemStatusLines(sections["API Keys, Limits und Kosten"] || []), (line) => this._formatApiBudgetLine(line)));
      this._populateLines(this.apiMenu.menu, apiLines, this._dynamicEmptyText(_("API-/Usage-Diagnose wird geladen.")));
      this._appendCodexUsageActions();
    }

    if (this.showProjectSection && (summary.codex_history_instances || (sections["Projekt-History"] || []).length)) {
      let projectHistoryLines = [];
      projectHistoryLines.push(
        "Uebersicht: Codex-History Instanzen " + String(summary.codex_history_instances || 0)
        + " | Repos " + String(summary.codex_history_repos || 0)
        + " | Runs " + String(summary.codex_history_run_summaries || 0)
        + " | Strategie " + String(summary.codex_history_strategies || 0)
        + " | Graphen " + String(summary.codex_history_graphs || 0)
        + this._sectionProblemText(summary.codex_history_problem_status_count)
      );
      projectHistoryLines = projectHistoryLines.concat(this._formatLines(this._problemStatusLines(sections["Projekt-History"] || []), (line) => this._formatProjectHistoryLine(line)));
      this.projectMenu.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
      this._appendLines(this.projectMenu.menu, projectHistoryLines, _("Keine Codex-History-Statuszeilen."));
      this._appendProjectHistoryDrilldown(sections["Projekt-History"] || []);
    }

    let memoryLines = [];
    let qdrant = payload.qdrant || {};
    let qdrantCollections = qdrant.collections || {};
    let userMemoryPoints = this._qdrantCollectionCount(qdrantCollections, "teebotus_user_memory");
    let bibliothekarPoints = this._qdrantCollectionCount(qdrantCollections, "teebotus_bibliothekar_chunks");
    if (summary.memory_accounts || summary.qdrant || summary.qdrant_collections) {
      memoryLines.push(
        "Uebersicht: Account-Memorys " + String(summary.memory_accounts || 0)
        + " | Qdrant-Collections " + String(summary.qdrant_ready_collections || 0) + "/" + String(summary.qdrant_collections || 0)
        + " | Usermemory-Vektoren " + String(userMemoryPoints)
        + this._sectionProblemText(summary.memory_problem_status_count)
      );
    }
    if (qdrant.unit) {
      memoryLines.push("Qdrant-Service " + String(qdrant.unit.name || this._qdrantUnit()) + ": " + this._statusWord(qdrant.unit.active_state || "unknown") + " / " + String(qdrant.unit.sub_state || "unknown"));
    }
    if (bibliothekarPoints > 0) {
      memoryLines.push("Bibliothekar-Vektoren: " + String(bibliothekarPoints));
    }
    let accountStatusGroups = this._splitProblemStatusLines(sections["Tools und Account-Memory"] || []);
    let memoryStatusLines = this._problemStatusLines(sections["Memory und semantische Suche"] || []);
    memoryLines = memoryLines.concat(this._formatLines(accountStatusGroups.problem, (line) => this._formatAccountLine(line)));
    memoryLines = memoryLines.concat(this._formatLines(memoryStatusLines, (line) => this._formatMemoryLine(line)));
    memoryLines = memoryLines.concat(this._formatLines(accountStatusGroups.normal, (line) => this._formatAccountLine(line)));
    this._populateLines(this.memoryMenu.menu, memoryLines, this._dynamicEmptyText(_("Memory-Diagnose wird geladen.")));
    this._appendQdrantActions();
    if (this.showBibliothekarSection) {
      this.bibliothekarMenu.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
      this._appendLines(this.bibliothekarMenu.menu, this._filterLines(sections["Lokale Dienste"] || [], ["bibliothekar="]), _("Keine Bibliothekar-Statuszeilen."));
    }
    if (this.showProactiveSection) {
      this.proactiveMenu.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
      this._appendLines(this.proactiveMenu.menu, sections["Agenten-Piloten"] || [], _("Keine Agenten-Pilot-Zeilen."));
    }
  },

  _formatLines: function(lines, formatter) {
    let result = [];
    for (let line of lines || []) {
      result.push(formatter(String(line || "")));
    }
    return result;
  },

  _problemStatusLines: function(lines, isForcedProblem) {
    let groups = this._splitProblemStatusLines(lines, isForcedProblem);
    return groups.problem.concat(groups.normal);
  },

  _splitProblemStatusLines: function(lines, isForcedProblem) {
    let problem = [];
    let normal = [];
    for (let line of lines || []) {
      let fields = this._parseFields(line);
      if ((isForcedProblem && isForcedProblem(fields)) || this._lineHasProblemStatus(fields)) {
        problem.push(line);
      } else {
        normal.push(line);
      }
    }
    return { problem: problem, normal: normal };
  },

  _dynamicEmptyText: function(loadingText) {
    if (this.statusRunning || !this.statusPayload) {
      return loadingText;
    }
    return _("Keine passenden Statuszeilen im Runtime-Status.");
  },

  _sectionProblemText: function(value) {
    let count = this._nonNegativeInt(value, 0);
    return count > 0 ? " | Probleme " + String(count) : "";
  },

  _formatRuntimeLine: function(line) {
    let fields = this._parseFields(line);
    if (fields.instances) {
      return "Instanzen: " + fields.instances;
    }
    if (fields.channels) {
      return "Kanaele: " + fields.channels;
    }
    return line;
  },

  _formatMessengerLine: function(line) {
    let fields = this._parseFields(line);
    if (fields.telegram_slot) {
      return "Telegram " + fields.telegram_slot + ": " + this._statusWord(fields.status) + "; Token " + String(fields.token || "unbekannt") + this._errorText(fields);
    }
    if (fields.signal_account) {
      let phone = fields.phone ? "; Telefon " + fields.phone : "";
      return "Signal " + fields.signal_account + ": " + this._statusWord(fields.status) + phone + "; REST " + String(fields.target || "unbekannt") + this._errorText(fields);
    }
    if (fields.signal_service) {
      return "Signal-REST " + fields.signal_service + ": " + this._statusWord(fields.status) + " auf " + String(fields.target || "unbekannt") + this._errorText(fields);
    }
    if (fields.matrix_homeserver) {
      return "Matrix " + fields.matrix_homeserver + ": " + this._statusWord(fields.status) + "; " + String(fields.target || "") + this._errorText(fields);
    }
    return line;
  },

  _formatLlmLine: function(line) {
    let fields = this._parseFields(line);
    if (fields.hf_pool) {
      if (fields.target) {
        let text = "HF-Pool " + fields.hf_pool + " / " + fields.target + ": " + this._statusWord(fields.status);
        if (fields.model) {
          text += "; Modell " + fields.model;
        }
        if (fields.models_feed) {
          text += "; Feed " + this._statusWord(fields.models_feed);
        }
        if (fields.context_length) {
          text += "; Kontext " + fields.context_length;
        }
        if (fields.tools) {
          text += "; Tools " + fields.tools;
        }
        if (fields.structured_output) {
          text += "; Struktur " + fields.structured_output;
        }
        return text + this._errorText(fields);
      }
      return "HF-Pool " + fields.hf_pool + ": " + this._statusWord(fields.status) + this._errorText(fields);
    }
    if (line.indexOf("gemini_free_tier_limits ") === 0 || fields.gemini_free_tier_limits !== undefined) {
      let source = fields.source ? "; Quelle " + fields.source : "";
      let models = fields.models ? "; Modelle " + fields.models : "";
      return "Gemini Free-Tier-Limits: " + this._statusWord(fields.status) + models + source + this._errorText(fields);
    }
    if (fields.llm_route) {
      let primary = String(fields.provider || "provider?") + " / " + String(fields.model || "model?");
      let text = "Route " + fields.llm_route + ": " + primary + " (" + this._statusWord(fields.status) + ")";
      if (fields.profile) {
        text += "; Profil " + fields.profile;
      }
      if (fields.api_key_env && (fields.status === "missing_key" || fields.fallback_api_key === "missing")) {
        text += "; Key fehlt: " + fields.api_key_env;
      }
      if (fields.free_tier_guard) {
        text += "; Free-Tier-Waechter " + fields.free_tier_guard;
      }
      let fallbackName = fields.fallback_profile || fields.fallback || "";
      let fallbackModel = fields.fallback_model || "";
      if (fallbackName || fallbackModel) {
        text += "; Ersatz bei Modell-/Key-/Limitfehlern: " + String(fallbackName || "Fallback");
        if (fallbackModel) {
          text += " -> " + fallbackModel;
        }
      }
      return text + this._errorText(fields);
    }
    if (fields.llm) {
      return "Account-LLM " + fields.llm + ": " + String(fields.provider || "?") + " / " + String(fields.model || "?") + " (" + this._statusWord(fields.status) + ")" + this._errorText(fields);
    }
    if (fields.structured_decision) {
      let routeStatus = fields.route_status ? "; Route " + this._statusWord(fields.route_status) : "";
      let fallbackName = fields.fallback_profile || fields.fallback || "";
      let fallbackModel = fields.fallback_model || "";
      let fallback = "";
      if (fallbackName || fallbackModel) {
        fallback = "; Ersatz " + String(fallbackName || "Fallback");
        if (fallbackModel) {
          fallback += " -> " + fallbackModel;
        }
      }
      return "Account-Entscheider " + fields.structured_decision + ": " + this._statusWord(fields.status) + routeStatus + fallback + this._errorText(fields);
    }
    if (fields.local_transcription) {
      let backend = fields.backend ? "; Backend " + fields.backend : "";
      let model = fields.model ? "; Modell " + fields.model : "";
      let engine = fields.engine ? "; Engine " + fields.engine : "";
      return "Lokale Transkription " + fields.local_transcription + ": " + this._statusWord(fields.status) + backend + model + engine + this._errorText(fields);
    }
    if (fields.bibliothekar) {
      let backend = fields.backend ? "; Backend " + fields.backend : "";
      let store = fields.store ? "; Speicher " + fields.store : "";
      let collection = fields.collection ? "; Collection " + fields.collection : "";
      return "Bibliothekar " + fields.bibliothekar + ": " + this._statusWord(fields.status) + backend + store + collection + this._errorText(fields);
    }
    return line;
  },

  _formatApiBudgetLine: function(line) {
    let fields = this._parseFields(line);
    if (fields.api_budget) {
      let text = "Route " + fields.api_budget + ": " + String(fields.provider || "?") + " / " + String(fields.model || "?") + " (" + this._statusWord(fields.status) + ")";
      text += "; Key " + String(fields.key || "?");
      if (fields.key_env) {
        text += " via " + fields.key_env;
      }
      if (fields.key_ring) {
        text += "; Ring " + fields.key_ring;
      }
      if (fields.key_instances) {
        text += "; Instanzen " + fields.key_instances;
      }
      if (fields.google_mode) {
        text += "; Google " + fields.google_mode;
      }
      if (fields.limits) {
        text += "; Limits " + fields.limits;
      }
      if (fields.costs) {
        text += "; Kosten " + fields.costs;
      }
      return text + this._errorText(fields);
    }
    if (fields.codex_usage) {
      let stale = fields.stale_hours ? "; Alter " + fields.stale_hours + "h" : "";
      let status = this._codexUsageIsStale(fields) ? "stale" : fields.status;
      return "codex-usage: " + this._statusWord(status) + "; Snapshots " + String(fields.snapshots || "0") + stale;
    }
    if (fields.codex_usage_account) {
      return "codex-usage " + fields.codex_usage_account + ": " + this._statusWord(fields.status) + "; 5h " + String(fields.five_hour || "?") + "; Woche " + String(fields.weekly || "?");
    }
    return line;
  },

  _formatProjectHistoryLine: function(line) {
    let fields = this._parseFields(line);
    if (fields.codex_history_repo) {
      let repo = fields.repo || "?";
      let latestPrefix = fields.latest_prefix ? "; zuletzt " + String(fields.latest_prefix).replace(/_/g, " ") : "";
      let latestTitle = fields.latest_title ? " " + String(fields.latest_title).replace(/_/g, " ") : "";
      let latestStatus = fields.latest_status ? "; letzter Status " + this._statusWord(fields.latest_status) : "";
      let latestKind = fields.latest_kind ? "; Typ " + this._codexHistoryKindLabel(fields.latest_kind) : "";
      return "Repo-History " + repo + " (" + fields.codex_history_repo + "): " + this._statusWord(fields.status)
        + "; offen " + String(fields.queued || "0")
        + "; fehlgeschlagen " + String(fields.failed || "0")
        + "; gesamt " + String(fields.total || "0")
        + this._codexHistoryMixText(fields)
        + latestPrefix + latestTitle + latestStatus + latestKind + this._errorText(fields);
    }
    if (fields.codex_history) {
      let latestRepo = fields.latest_repo ? "; zuletzt " + fields.latest_repo : "";
      let latestPrefix = fields.latest_prefix ? " " + String(fields.latest_prefix).replace(/_/g, " ") : "";
      let latestKind = fields.latest_kind ? "; Typ " + this._codexHistoryKindLabel(fields.latest_kind) : "";
      return "Codex-History " + fields.codex_history + ": " + this._statusWord(fields.status)
        + "; offen " + String(fields.queued || "0")
        + "; fehlgeschlagen " + String(fields.failed || "0")
        + "; gesamt " + String(fields.total || "0")
        + this._codexHistoryMixText(fields)
        + latestRepo + latestPrefix + latestKind + this._errorText(fields);
    }
    return line;
  },

  _codexHistoryMixText: function(fields) {
    let parts = [];
    let runSummaries = this._nonNegativeInt((fields || {}).run_summaries, 0);
    let strategies = this._nonNegativeInt((fields || {}).strategies, 0);
    let graphs = this._nonNegativeInt((fields || {}).graphs, 0);
    let other = this._nonNegativeInt((fields || {}).other, 0);
    if (runSummaries > 0) {
      parts.push("Runs " + String(runSummaries));
    }
    if (strategies > 0) {
      parts.push("Strategie " + String(strategies));
    }
    if (graphs > 0) {
      parts.push("Graphen " + String(graphs));
    }
    if (other > 0) {
      parts.push("Sonstige " + String(other));
    }
    return parts.length > 0 ? "; " + parts.join(" / ") : "";
  },

  _codexHistoryKindLabel: function(kind) {
    let value = String(kind || "");
    let kindLabels = {
      codex_run_summary: "Run-Summary",
      codex_strategy_analysis: "Strategieanalyse",
      codex_graph_artifact: "Graph-Artefakt"
    };
    return kindLabels[value] || value.replace(/_/g, " ");
  },

  _appendProjectHistoryDrilldown: function(lines) {
    let repos = this._codexHistoryRepoDetails(lines);
    if (repos.length === 0) {
      return;
    }
    this.projectMenu.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
    this.projectMenu.menu.addMenuItem(this._menuLine(_("Codex-History Drilldown"), false));
    for (let i = 0; i < repos.length && i < MENU_LINE_LIMIT; i++) {
      let repo = repos[i];
      let item = new PopupMenu.PopupSubMenuMenuItem(this._shortText("Repo " + repo.repo + " (" + repo.instance + ")", 72));
      this._styleSubmenu(item);
      item.menu.addMenuItem(this._menuLine("Status: " + this._statusWord(repo.status), false));
      item.menu.addMenuItem(this._menuLine("Queue: offen " + String(repo.queued) + " | fehlgeschlagen " + String(repo.failed) + " | gesamt " + String(repo.total), false));
      item.menu.addMenuItem(this._menuLine("Typen: " + repo.mix, false));
      item.menu.addMenuItem(this._menuLine("Letzter Eintrag: " + repo.latest, false));
      this.projectMenu.menu.addMenuItem(item);
    }
    if (repos.length > MENU_LINE_LIMIT) {
      this.projectMenu.menu.addMenuItem(this._menuLine(_("Weitere Repos: ") + String(repos.length - MENU_LINE_LIMIT), false));
    }
  },

  _codexHistoryRepoDetails: function(lines) {
    let repos = [];
    for (let line of lines || []) {
      let fields = this._parseFields(line);
      if (!fields.codex_history_repo) {
        continue;
      }
      let latestParts = [];
      if (fields.latest_prefix) {
        latestParts.push(String(fields.latest_prefix).replace(/_/g, " "));
      }
      if (fields.latest_title) {
        latestParts.push(String(fields.latest_title).replace(/_/g, " "));
      }
      if (fields.latest_status) {
        latestParts.push(this._statusWord(fields.latest_status));
      }
      if (fields.latest_kind) {
        latestParts.push(this._codexHistoryKindLabel(fields.latest_kind));
      }
      repos.push({
        instance: fields.codex_history_repo || "?",
        repo: fields.repo || "?",
        status: fields.status || "unknown",
        queued: this._nonNegativeInt(fields.queued, 0),
        failed: this._nonNegativeInt(fields.failed, 0),
        total: this._nonNegativeInt(fields.total, 0),
        mix: (this._codexHistoryMixText(fields).replace(/^; /, "") || "keine Typdaten"),
        latest: latestParts.join(" | ") || "kein Eintrag"
      });
    }
    repos.sort((left, right) => {
      let severity = this._statusValueIsProblem(right.status) - this._statusValueIsProblem(left.status);
      if (severity !== 0) {
        return severity;
      }
      return String(left.repo).localeCompare(String(right.repo)) || String(left.instance).localeCompare(String(right.instance));
    });
    return repos;
  },

  _formatMemoryLine: function(line) {
    let fields = this._parseFields(line);
    if (fields.qdrant) {
      let fallback = fields.fallback ? "; Ersatzsuche: " + fields.fallback : "";
      return "Semantischer Index " + fields.qdrant + ": " + this._statusWord(fields.status) + fallback + this._errorText(fields);
    }
    if (fields.qdrant_collection) {
      return "Qdrant Collection " + fields.qdrant_collection + ": " + this._statusWord(fields.status) + "; Vektor " + String(fields.vector_size || "?") + "; Embedding " + String(fields.embedding_model || "?") + this._errorText(fields);
    }
    if (fields.memory_index) {
      return "Memory Index " + fields.memory_index + ": " + this._statusWord(fields.status) + "; Backend " + String(fields.backend || "?") + "; Semantik " + String(fields.semantic || "?") + this._errorText(fields);
    }
    return line;
  },

  _accountStatusLines: function(lines) {
    return this._problemStatusLines(lines);
  },

  _lineHasProblemStatus: function(fields) {
    let values = fields || {};
    if (this._codexUsageIsStale(values)) {
      return true;
    }
    if (this._statusFieldHasProblem(values, "status")) {
      return true;
    }
    for (let key of SECONDARY_PROBLEM_STATUS_FIELDS) {
      if (this._statusFieldHasProblem(values, key)) {
        return true;
      }
    }
    for (let key of FLAG_PROBLEM_STATUS_FIELDS) {
      if (values[key]) {
        return true;
      }
    }
    for (let key in FORCED_PROBLEM_STATUS_FIELDS) {
      if (values[key]) {
        return true;
      }
    }
    return false;
  },

  _statusFieldHasProblem: function(fields, key) {
    let value = (fields || {})[key];
    if (!value) {
      return false;
    }
    return this._statusValueIsProblem(value);
  },

  _statusValueIsProblem: function(value) {
    for (let status of PROBLEM_STATUSES) {
      if (value === status) {
        return true;
      }
    }
    return false;
  },

  _codexUsageIsStale: function(fields) {
    let staleHours = this._strictInt((fields || {}).stale_hours);
    return Boolean((fields || {}).codex_usage) && staleHours >= CODEX_USAGE_STALE_WARNING_HOURS;
  },

  _formatAccountLine: function(line) {
    let fields = this._parseFields(line);
    if (fields.account_identity_warning) {
      let message = fields.message ? "; " + fields.message : "";
      let action = fields.action ? "; Aktion " + fields.action : "";
      return "Account-Identitaet " + fields.account_identity_warning + ": Warnung" + message + action;
    }
    if (fields.account_identity) {
      return "Account-Identitaet " + fields.account_identity + ": " + this._statusWord(fields.status) + "; Runtime " + String(fields.runtime_slots || "?") + "; Identitaeten " + String(fields.identities || "?") + this._errorText(fields);
    }
    if (fields.account_memory_recovery) {
      let command = fields.command ? "; Kommando " + fields.command : "";
      return "Account-Memory-Recovery " + fields.account_memory_recovery + ": " + this._statusWord(fields.status) + command + this._errorText(fields);
    }
    if (fields.account_memory_recovery_legacy) {
      let command = fields.command ? "; Preflight " + fields.command : "";
      let applyCommand = fields.apply_command ? "; Import " + fields.apply_command : "";
      let sourceCount = fields.sources ? "; Quellen " + fields.sources : "";
      let entryCount = fields.entries ? "; Eintraege " + fields.entries : "";
      return "Account-Memory-Legacy-Recovery " + fields.account_memory_recovery_legacy + ": " + this._statusWord(fields.status) + sourceCount + entryCount + command + applyCommand + this._errorText(fields);
    }
    if (fields.account_memory) {
      return "Account-Memory " + fields.account_memory + ": " + this._statusWord(fields.status) + this._errorText(fields);
    }
    if (fields.account_crypto) {
      return "Account-Crypto " + fields.account_crypto + ": " + this._statusWord(fields.status) + "; Mapping " + String(fields.mapping || "?") + "; Memory " + String(fields.memory || "?") + "; Keyring " + String(fields.keyring || "?") + this._errorText(fields);
    }
    if (fields.account_storage_preflight) {
      return "Account-Storage: " + this._statusWord(fields.status) + this._errorText(fields);
    }
    if (fields.mcp_tools) {
      return "MCP-Tools " + fields.mcp_tools;
    }
    return line;
  },

  _errorText: function(fields) {
    let value = String((fields || {}).error || (fields || {}).route_error || "").trim();
    let warning = String((fields || {}).warning || "").trim();
    let text = value ? "; Fehler " + value : "";
    return warning ? text + "; Warnung " + warning : text;
  },

  _statusWord: function(status) {
    let value = String(status || "unknown");
    let labels = {
      available: "verfuegbar",
      broken: "defekt",
      configured: "konfiguriert",
      config_conflict: "Konfigurationskonflikt",
      cooldown: "Cooldown",
      degraded: "eingeschraenkt",
      disabled: "deaktiviert",
      enabled: "aktiv",
      error: "Fehler",
      failed: "fehlgeschlagen",
      fallback_defaults: "konservative Ersatzwerte",
      invalid: "ungueltig",
      missing_key: "Key fehlt",
      missing: "fehlt",
      never: "noch nie aktualisiert",
      needed: "benoetigt",
      no_limits_found: "keine Limits gefunden",
      not_applicable: "nicht anwendbar",
      not_configured: "nicht konfiguriert",
      ok: "ok",
      planned: "geplant",
      reachable: "erreichbar",
      ready: "bereit",
      registered: "registriert",
      schema_mismatch: "Schema passt nicht",
      stale: "veraltet",
      unknown: "unbekannt",
      unavailable: "nicht verfuegbar",
      unreachable: "nicht erreichbar",
      unsupported: "nicht unterstuetzt",
      warning: "Warnung"
    };
    return labels[value] || value;
  },

  _appendCodexUsageActions: function() {
    this.apiMenu.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
    this.apiMenu.menu.addMenuItem(this._actionItem(_("codex-usage latest"), () => this._openCodexUsage(["latest"])));
    this.apiMenu.menu.addMenuItem(this._actionItem(_("codex-usage latest JSON"), () => this._openCodexUsage(["latest", "--format", "json"])));
    this.apiMenu.menu.addMenuItem(this._actionItem(_("codex-usage paths"), () => this._openCodexUsage(["paths"])));
    this.apiMenu.menu.addMenuItem(this._actionItem(_("codex-usage Repo oeffnen"), () => this._openPath(this._codexUsagePath())));
  },

  _parseFields: function(line) {
    let fields = {};
    let text = String(line || "");
    let matches = [];
    let quoted = this._quotedCharacterIndexes(text);
    let pattern = /(^|\s)([A-Za-z_][A-Za-z0-9_-]*)=/g;
    let match = null;
    while ((match = pattern.exec(text)) !== null) {
      let keyStart = match.index + String(match[1] || "").length;
      let key = String(match[2] || "").trim();
      if (key && !quoted[keyStart]) {
        matches.push({
          key: key,
          keyStart: keyStart,
          valueStart: keyStart + key.length + 1
        });
      }
    }
    for (let i = 0; i < matches.length; i++) {
      let valueEnd = this._fieldValueEnd(text, matches, i);
      fields[matches[i].key] = text.slice(matches[i].valueStart, valueEnd).trim();
      while (i + 1 < matches.length && matches[i + 1].keyStart < valueEnd) {
        i++;
      }
    }
    return fields;
  },

  _quotedCharacterIndexes: function(text) {
    let indexes = {};
    for (let i = 0; i < text.length; i++) {
      let value = text.charAt(i);
      let nextValue = i + 1 < text.length ? text.charAt(i + 1) : "";
      if (value === "=" && (nextValue === "\"" || nextValue === "'" || nextValue === "`")) {
        let quote = nextValue;
        let quoteIndex = i + 1;
        let candidate = {};
        let closed = false;
        while (quoteIndex < text.length) {
          candidate[quoteIndex] = true;
          if (text.charAt(quoteIndex) === "\\" && quoteIndex + 1 < text.length) {
            candidate[quoteIndex + 1] = true;
            quoteIndex += 2;
            continue;
          }
          if (quoteIndex > i + 1 && text.charAt(quoteIndex) === quote) {
            closed = true;
            break;
          }
          quoteIndex++;
        }
        if (closed) {
          for (let key in candidate) {
            indexes[key] = true;
          }
          i = quoteIndex;
        }
      }
    }
    return indexes;
  },

  _fieldValueEnd: function(text, matches, index) {
    let key = String((matches[index] || {}).key || "");
    if (!FREE_TEXT_STATUS_FIELDS[key]) {
      return index + 1 < matches.length ? matches[index + 1].keyStart : text.length;
    }
    let boundaries = FREE_TEXT_STATUS_FIELD_BOUNDARIES[key] || {};
    for (let i = index + 1; i < matches.length; i++) {
      if (boundaries[matches[i].key] || this._fieldMatchIsStructuredBoundary(text, matches, i)) {
        return matches[i].keyStart;
      }
    }
    return text.length;
  },

  _fieldMatchIsStructuredBoundary: function(text, matches, index) {
    let match = matches[index] || {};
    if (!STATUS_FIELD_BOUNDARY_KEYS[match.key]) {
      return false;
    }
    let valueEnd = index + 1 < matches.length ? matches[index + 1].keyStart : text.length;
    let value = text.slice(match.valueStart, valueEnd).trim();
    return this._statusValueIsProblem(value) || Boolean(STATUS_FIELD_NEUTRAL_BOUNDARY_VALUES[value]);
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
      this.statusRefreshPending = true;
      return;
    }
    this.statusRunning = true;
    this.statusRefreshPending = false;
    this._setPanelState("refreshing");
    this._spawnJson(this._statusCommand(), (payload, error) => {
      this.statusRunning = false;
      if (error) {
        this.lastError = error;
        if (this.statusPayload) {
          this.statusText = this._statusSummary(this.statusPayload) + " | " + _("Statusfehler: ") + this._shortText(error, 80);
        } else {
          this.statusPayload = null;
          this.statusText = _("Statusfehler: ") + this._shortText(error, 80);
        }
      } else {
        this.statusPayload = payload;
        this.lastError = "";
        this.statusText = this._statusSummary(payload);
      }
      this._buildMenu();
      this._updatePanel();
      if (this.statusRefreshPending && !this.appletRemoved) {
        this.statusRefreshPending = false;
        this._refreshStatus();
      }
    }, this._repoPath(), { timeoutMs: (this._statusTimeoutSeconds() + STATUS_TIMEOUT_GRACE_SECONDS) * 1000 });
  },

  _statusCommand: function() {
    return this._pythonArgs().concat([
      "-m",
      "TeeBotus.cinnamon_applet",
      "status",
      "--repo-root",
      this._repoPath(),
      "--channels",
      this._channels(),
      "--unit",
      this._runtimeUnit(),
      "--qdrant-unit",
      this._qdrantUnit(),
      "--qdrant-url",
      this._qdrantUrl(),
      "--python",
      this._pythonPath(),
      "--timeout",
      String(this._statusTimeoutSeconds())
    ]);
  },

  _statusSummary: function(payload) {
    let unit = payload.unit || {};
    let health = payload.health || {};
    let runtime = payload.runtime || {};
    let summary = runtime.summary || {};
    let counts = runtime.status_counts || {};
    let bad = this._healthProblemTotal(health, summary, counts);
    let state = String(unit.active_state || "unknown");
    let instances = String(summary.instances || "?");
    let channels = String(summary.channels || this._channels());
    let qdrant = payload.qdrant || {};
    let vectors = this._qdrantCollectionCount(qdrant.collections || {}, "teebotus_user_memory");
    let vectorText = vectors > 0 ? " | Vektoren " + String(vectors) : "";
    let healthText = this._statusWord(health.status || (payload.ok ? "ok" : "warning"));
    let breakdown = this._problemBreakdownText(health.problem_statuses || summary.problem_statuses || this._problemStatusesFromCounts(counts || {}));
    let commandBreakdown = this._commandProblemBreakdownText(health);
    let qdrantBreakdown = this._qdrantProblemBreakdownText(health);
    if (bad > 0) {
      return "Warnungen " + String(bad) + breakdown + commandBreakdown + qdrantBreakdown + " | Health " + healthText + " | Unit " + state + " | " + instances + " | " + channels + vectorText;
    }
    return "Health " + healthText + " | Unit " + state + " | " + instances + " | " + channels + vectorText + breakdown + commandBreakdown + qdrantBreakdown;
  },

  _healthProblemTotal: function(health, summary, counts) {
    let total = this._nonNegativeInt((health || {}).total_problem_count, null);
    if (total !== null && total > 0) {
      return total;
    }
    let runtimeTotal = this._nonNegativeInt((health || {}).runtime_problem_count, null);
    let runtimeDerived = false;
    if (runtimeTotal === null || runtimeTotal <= 0) {
      runtimeTotal = this._nonNegativeInt((summary || {}).problem_status_count, 0);
      runtimeDerived = true;
      runtimeTotal = Math.max(runtimeTotal, this._problemStatusCount(counts));
    }
    if (runtimeDerived) {
      runtimeTotal = Math.max(0, runtimeTotal - this._nonNegativeInt((health || {}).qdrant_runtime_problem_count, 0));
    }
    let commandTotal = this._nonNegativeInt((health || {}).command_problem_count, 0);
    let qdrantTotal = this._nonNegativeInt((health || {}).qdrant_problem_count, 0);
    if (qdrantTotal <= 0) {
      qdrantTotal = Math.max(
        this._nonNegativeInt((health || {}).qdrant_runtime_problem_count, 0),
        this._nonNegativeInt((health || {}).qdrant_probe_problem_count, 0) +
        this._nonNegativeInt((health || {}).qdrant_unit_problem_count, 0)
      );
    }
    let derivedTotal = runtimeTotal + commandTotal + qdrantTotal;
    return derivedTotal;
  },

  _problemBreakdownText: function(value) {
    let pairs = [];
    for (let part of String(value || "").split(",")) {
      let index = part.indexOf(":");
      if (index < 1) {
        continue;
      }
      let status = part.slice(0, index).trim();
      let count = this._nonNegativeInt(part.slice(index + 1), 0);
      if (!status || !(count > 0)) {
        continue;
      }
      pairs.push({ status: status, count: count });
    }
    if (pairs.length === 0) {
      return "";
    }
    pairs.sort((left, right) => right.count - left.count || left.status.localeCompare(right.status));
    let rendered = [];
    for (let i = 0; i < pairs.length && i < 4; i++) {
      rendered.push(this._statusWord(pairs[i].status) + ":" + String(pairs[i].count));
    }
    if (pairs.length > 4) {
      rendered.push("+" + String(pairs.length - 4));
    }
    return " | Probleme " + rendered.join(", ");
  },

  _problemStatusesFromCounts: function(counts) {
    let pairs = [];
    for (let status of Object.keys(counts || {}).sort()) {
      if (PROBLEM_STATUSES.indexOf(status) < 0) {
        continue;
      }
      let count = this._nonNegativeInt((counts || {})[status], 0);
      if (count > 0) {
        pairs.push(status + ":" + String(count));
      }
    }
    return pairs.join(",");
  },

  _commandProblemBreakdownText: function(health) {
    let count = this._nonNegativeInt((health || {}).command_problem_count, 0);
    return count > 0 ? " | Kommando:" + String(count) : "";
  },

  _qdrantProblemBreakdownText: function(health) {
    let runtimeCount = this._nonNegativeInt((health || {}).qdrant_runtime_problem_count, 0);
    let probeCount = this._nonNegativeInt((health || {}).qdrant_probe_problem_count, 0);
    let unitCount = this._nonNegativeInt((health || {}).qdrant_unit_problem_count, 0);
    if (runtimeCount <= 0 && probeCount <= 0 && unitCount <= 0) {
      return "";
    }
    let parts = [];
    if (runtimeCount > 0) {
      parts.push("Runtime:" + String(runtimeCount));
    }
    if (probeCount > 0) {
      parts.push("Probe:" + String(probeCount));
    }
    if (unitCount > 0) {
      parts.push("Service:" + String(unitCount));
    }
    return " | Qdrant " + parts.join(", ");
  },

  _healthDetailText: function(health, summary, counts) {
    let total = this._healthProblemTotal(health, summary, counts || {});
    let text = total > 0 ? " | Probleme " + String(total) : "";
    text += this._healthProblemDetailsText(health, summary, counts);
    return text;
  },

  _healthProblemDetailsText: function(health, summary, counts) {
    let text = "";
    text += this._problemBreakdownText((health || {}).problem_statuses || (summary || {}).problem_statuses || this._problemStatusesFromCounts(counts || {}));
    text += this._commandProblemBreakdownText(health);
    text += this._qdrantProblemBreakdownText(health);
    return text;
  },

  _problemStatusCount: function(counts) {
    let total = 0;
    for (let status of PROBLEM_STATUSES) {
      total += this._nonNegativeInt((counts || {})[status], 0);
    }
    return total;
  },

  _updateHeader: function() {
    let payload = this.statusPayload || {};
    let repo = payload.repo || {};
    let unit = payload.unit || {};
    let health = payload.health || {};
    let runtime = payload.runtime || {};
    let summary = runtime.summary || {};
    let counts = runtime.status_counts || {};
    this.headerItem.label.set_text("TB " + String(payload.version || "?"));
    this.summaryItem.label.set_text(this.statusText || _("Status unbekannt"));
    let commit = repo.short_commit ? " | " + repo.short_commit : "";
    let problemTotal = this._healthProblemTotal(health, summary, counts);
    let healthWord = this._statusWord(health.status || "unknown");
    let prefix = problemTotal > 0 ? "Probleme " + String(problemTotal) + " | " : "";
    this.versionItem.label.set_text(
      prefix +
        "Health: " +
        healthWord +
        this._healthProblemDetailsText(health, summary, counts) +
        " | Unit: " +
        String(unit.active_state || "unknown") +
        " / " +
        String(unit.sub_state || "unknown") +
        commit +
        " | LLM-Routen: " +
        String(summary.llm_routes || 0)
    );
  },

  _updatePanel: function() {
    this.set_applet_label("TB");
    this.set_applet_tooltip(this.statusText || _("TB"));
  },

  _setStatusText: function(text) {
    this.statusText = String(text || "");
    this._updatePanel();
    if (this.headerItem && this.summaryItem && this.versionItem) {
      this._updateHeader();
    }
  },

  _setPanelState: function(state) {
    if (state === "refreshing") {
      this.set_applet_label("TB");
    }
  },

  _spawnJson: function(argv, callback, cwd, options) {
    this._spawn(argv, (stdout, stderr, ok) => {
      if (!ok) {
        callback(null, stderr || _("Command failed"));
        return;
      }
      let text = String(stdout || "");
      if (text.length > MAX_HELPER_JSON_CHARS) {
        callback(null, _("Helper JSON output too large"));
        return;
      }
      try {
        let payload = JSON.parse(text);
        if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
          callback(null, _("Invalid JSON object from helper"));
          return;
        }
        callback(payload, null);
      } catch (err) {
        callback(null, _("Invalid JSON from helper: ") + String(err));
      }
    }, cwd, options);
  },

  _spawn: function(argv, callback, cwd, options) {
    options = options || {};
    let applet = this;
    let spawnGeneration = this.spawnGeneration;
    let done = false;
    let timeoutId = 0;
    let process = null;
    let finish = function(stdout, stderr, ok) {
      if (done) {
        return;
      }
      done = true;
      if (timeoutId) {
        Mainloop.source_remove(timeoutId);
        timeoutId = 0;
      }
      if (applet.appletRemoved || applet.spawnGeneration !== spawnGeneration) {
        return;
      }
      callback(stdout, stderr, ok);
    };
    try {
      let resolvedArgv = this._resolveSpawnArgv(argv);
      let launcher = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE);
      if (cwd) {
        launcher.set_cwd(String(cwd));
      }
      process = launcher.spawnv(resolvedArgv);
      let timeoutMs = Number(options.timeoutMs || 0);
      if (timeoutMs > 0) {
        timeoutId = Mainloop.timeout_add(Math.max(250, timeoutMs), () => {
          try {
            if (process && !process.get_if_exited()) {
              process.force_exit();
            }
          } catch (err) {
            global.logError(err);
          }
          finish("", _("Command timed out"), false);
          return false;
        });
      }
      process.communicate_utf8_async(null, null, (proc, result) => {
        try {
          let [, stdout, stderr] = proc.communicate_utf8_finish(result);
          finish(String(stdout || ""), String(stderr || ""), proc.get_successful());
        } catch (err) {
          finish("", String(err), false);
        }
      });
    } catch (err) {
      finish("", String(err), false);
    }
  },

  _serviceAction: function(action) {
    if (!this.enableServiceActions) {
      return;
    }
    let unit = this._runtimeUnit();
    if (!unit) {
      return;
    }
    let run = () => {
      this._spawn(["systemctl", "--user", action, unit], (stdout, stderr, ok) => {
        this._setStatusText(ok ? _("Service action completed: ") + action : _("Service action failed: ") + (stderr || stdout));
        this._refreshStatus();
      });
    };
    if (!this.confirmServiceActions) {
      run();
      return;
    }
    this._confirmServiceAction(action, unit, (confirmed) => {
      if (confirmed) {
        run();
      }
    });
  },

  _confirmServiceAction: function(action, unit, completionCallback) {
    let dialog = new ModalDialog.ModalDialog();
    let completed = false;
    let complete = (result) => {
      if (completed) {
        return;
      }
      completed = true;
      if (typeof completionCallback === "function") {
        completionCallback(result === true);
      }
    };
    dialog.contentLayout.add_child(new St.Label({
      text: _("Service action ausfuehren?"),
      x_expand: true
    }));
    dialog.contentLayout.add_child(new St.Label({
      text: String(action || "") + " " + String(unit || ""),
      x_expand: true
    }));
    dialog.setButtons([
      {
        label: _("Abbrechen"),
        key: Clutter.KEY_Escape,
        action: function() {
          dialog.close();
          this._setStatusText(_("Service action cancelled."));
          complete(false);
        }.bind(this),
      },
      {
        label: _("Ausfuehren"),
        action: function() {
          dialog.close();
          complete(true);
        }.bind(this),
      }
    ]);
    if (!dialog.open()) {
      this._setStatusText(_("Service confirmation dialog could not be opened."));
      complete(false);
    }
  },

  _openRuntimeStatusTerminal: function() {
    this._openTerminalForCommand(this._repoPath(), this._pythonArgs().concat(["-m", "TeeBotus", "--runtime-status", "--channels", this._channels()]));
  },

  _openQdrantStatusTerminal: function() {
    this._openTerminalForCommand(this._repoPath(), ["systemctl", "--user", "status", this._qdrantUnit(), "--no-pager"]);
  },

  _openCodexHistoryReport: function() {
    this._openTerminalForCommand(this._repoPath(), this._codexHistoryAdminArgs(["report"]));
  },

  _openCodexHistoryIndex: function() {
    this._openTerminalForCommand(
      this._repoPath(),
      this._codexHistoryAdminArgs(["index", "--qdrant", "--qdrant-ensure", "--graph", "--graph-svg"])
    );
  },

  _openCodexHistoryStrategy: function() {
    this._openTerminalForCommand(
      this._repoPath(),
      this._codexHistoryAdminArgs(["strategic-analysis", "--profile", "local_ollama"])
    );
  },

  _openCodexHistoryTimerEnable: function() {
    this._openTerminalForCommand(
      this._repoPath(),
      this._pythonArgs().concat([
        "-m",
        "TeeBotus.codex_history_systemd",
        "--repo-root",
        this._repoPath(),
        "--index-timer",
        "--index-graph",
        "--index-graph-svg",
        "--index-graph-svg-engine",
        "auto",
        "--index-graph-queue-svg",
        "--index-strategic-analysis",
        "--index-dispatch",
        "--enable"
      ])
    );
  },

  _openCodexHistoryTimerStatus: function() {
    this._openTerminalForCommand(
      this._repoPath(),
      ["systemctl", "--user", "status", "teebotus-codex-history-index.timer", "teebotus-codex-history-index.service", "--no-pager"]
    );
  },

  _codexHistoryAdminArgs: function(args) {
    return this._pythonArgs().concat([
      "-m",
      "TeeBotus.admin",
      "codex-history",
    ]).concat(args || []).concat([
      "--instances-dir",
      GLib.build_filenamev([this._repoPath(), "instances"])
    ]);
  },

  _appendQdrantActions: function() {
    this.memoryMenu.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
    this.memoryMenu.menu.addMenuItem(this._actionItem(_("Qdrant-Status"), () => this._openQdrantStatusTerminal()));
    this.memoryMenu.menu.addMenuItem(this._actionItem(_("Qdrant-Collections JSON"), () => this._openTerminalForCommand(this._repoPath(), ["curl", "-fsS", this._qdrantUrl() + "/collections"])));
    this.memoryMenu.menu.addMenuItem(this._actionItem(_("Usermemory-Vektoranzahl"), () => this._openTerminalForCommand(this._repoPath(), ["curl", "-fsS", "-X", "POST", this._qdrantUrl() + "/collections/teebotus_user_memory/points/count", "-H", "Content-Type: application/json", "-d", "{\"exact\":true}"])));
    this.memoryMenu.menu.addMenuItem(this._actionItem(_("Usermemory-Vektoren rebuilden"), () => this._openTerminalForCommand(this._repoPath(), this._pythonArgs().concat(["-m", "TeeBotus.embedding", "memory-rebuild"]))));
  },

  _openCodexUsage: function(args) {
    this._openTerminalForCommand(this._codexUsagePath(), this._codexUsageArgs().concat(args || []));
  },

  _openLogsTerminal: function() {
    this._openTerminalForCommand(this._repoPath(), ["journalctl", "--user", "-u", this._runtimeUnit(), "-n", "120", "-f"]);
  },

  _openBibliothekarStatus: function() {
    this._openTerminalForCommand(
      this._repoPath(),
      this._pythonArgs().concat(["-m", "TeeBotus.bibliothekar", "--instance", String(this.bibliothekarInstance || this.defaultInstance || "Depressionsbot"), "status"])
    );
  },

  _runProactiveOnce: function() {
    let args = this._commandArgs(this.proactiveCommand, []);
    if (args.length === 0) {
      args = this._pythonArgs().concat([
        "-m",
        "TeeBotus.proactive",
        "--instance",
        String(this.proactiveInstance || "Depressionsbot"),
        "--dispatch",
        "--plan",
        "--tool-plan"
      ]);
    }
    this._openTerminalForCommand(this._repoPath(), args);
  },

  _openTerminalForCommand: function(cwd, argv) {
    let resolvedArgv;
    try {
      resolvedArgv = this._resolveSpawnArgv(argv);
    } catch (err) {
      this._setStatusText(_("Terminal command unavailable: ") + String(err));
      return;
    }
    this._openTerminalShell(cwd, resolvedArgv.map((part) => this._safeShellWord(part)).join(" "));
  },

  _openTerminalShell: function(cwd, command) {
    let terminal = this._terminalArgs();
    if (!terminal) {
      this._setStatusText(_("No terminal found."));
      return;
    }
    let shell = this._trustedExecutablePath("bash");
    if (!shell) {
      this._setStatusText(_("No trusted shell found."));
      return;
    }
    let shellCommand = "cd " + this._safeShellWord(cwd) + " && " + command + "; printf '\\n'; read -r -p 'Enter zum Schliessen...'";
    let argv = terminal.concat([shell, "-lc", shellCommand]);
    this._spawn(argv, (stdout, stderr, ok) => {
      if (!ok) {
        this._setStatusText(_("Terminal launch failed: ") + (stderr || stdout || _("Command failed")));
      }
    });
  },

  _terminalArgs: function() {
    let configured = String(this.terminalCommand || "").trim();
    if (configured) {
      let parsed = this._safeExecutableArgs(configured, []);
      if (parsed.length > 0) {
        let resolvedCommand = this._trustedExecutablePath(parsed[0]);
        if (!resolvedCommand) {
          parsed = [];
        } else {
          parsed[0] = resolvedCommand;
        }
      }
      if (parsed.length > 0) {
        let terminalArgs = this._terminalCommandArgs(parsed);
        if (terminalArgs) {
          return terminalArgs;
        }
      }
    }
    for (let candidate of TERMINAL_CANDIDATES) {
      let resolved = this._findTrustedProgramInPath(candidate);
      if (!resolved) {
        continue;
      }
      if (candidate === "xterm") {
        return [resolved, "-e"];
      }
      if (candidate === "konsole") {
        return [resolved, "-e"];
      }
      return [resolved, "--"];
    }
    return null;
  },

  _terminalCommandArgs: function(parsed) {
    let argv = (parsed || []).slice();
    if (argv.length === 0) {
      return null;
    }
    if (this._terminalCommandHasEmbeddedCommand(argv)) {
      return null;
    }
    let last = String(argv[argv.length - 1] || "");
    if (last === "--" || last === "-e") {
      return argv;
    }
    let binary = String(argv[0] || "").split("/").pop();
    if (binary === "xterm" || binary === "konsole") {
      return argv.concat(["-e"]);
    }
    return argv.concat(["--"]);
  },

  _terminalCommandHasEmbeddedCommand: function(argv) {
    for (let index = 1; index < (argv || []).length; index++) {
      let value = String(argv[index] || "");
      let isFinal = index === argv.length - 1;
      if ((value === "--" || value === "-e") && isFinal) {
        continue;
      }
      if (value === "--" || value === "-e" || value === "-x" || value === "--execute" || value.indexOf("--execute=") === 0 || value === "--command" || value.indexOf("--command=") === 0) {
        return true;
      }
    }
    return false;
  },

  _copyStatusJson: function() {
    this._copyText(JSON.stringify(this.statusPayload || {}, null, 2));
  },

  _copyText: function(text) {
    this.clipboard.set_text(St.ClipboardType.CLIPBOARD, String(text || ""));
    this._setStatusText(_("Kopiert."));
  },

  _openAppletSettings: function() {
    this._spawnAndReportFailure(["cinnamon-settings", "applets", UUID], _("Settings launch failed: "));
  },

  _openPath: function(path) {
    this._spawnAndReportFailure(["gio", "open", this._safeLocalPath(path, this._repoPath())], _("Open path failed: "));
  },

  _openUri: function(uri) {
    this._spawnAndReportFailure(["gio", "open", this._safeProjectUrl(uri, DEFAULT_GITHUB_URL)], _("Open link failed: "));
  },

  _spawnAndReportFailure: function(argv, failurePrefix) {
    this._spawn(argv, (stdout, stderr, ok) => {
      if (!ok) {
        this._setStatusText(String(failurePrefix || _("Command failed: ")) + (stderr || stdout || _("Command failed")));
      }
    });
  },

  _menuLine: function(label, reactive) {
    return this._styleMenuItemLabel(
      new PopupMenu.PopupMenuItem(String(label || ""), { reactive: Boolean(reactive) }),
      { maxWidthEm: SUBMENU_LABEL_WIDTH_EM }
    );
  },

  _actionItem: function(label, callback) {
    let item = new PopupMenu.PopupMenuItem(String(label || ""));
    this._styleMenuItemLabel(item, { maxWidthEm: SUBMENU_LABEL_WIDTH_EM });
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
    return this._safePythonArgs(this.pythonCommand, [DEFAULT_PYTHON]);
  },

  _pythonPath: function() {
    return this._pythonArgs().map((part) => this._safeShellWord(part)).join(" ");
  },

  _repoPath: function() {
    return this._safeLocalPath(this.repoPath, DEFAULT_REPO_PATH);
  },

  _libraryPath: function() {
    return this._safeLocalPath(this.libraryPath, GLib.build_filenamev([this._repoPath(), "instances", "Depressionsbot", "data", "Bibliothek"]));
  },

  _runtimeUnit: function() {
    return this._safeSystemdUnit(this.runtimeUnit, DEFAULT_UNIT);
  },

  _qdrantUnit: function() {
    return this._safeSystemdUnit(this.qdrantUnit, DEFAULT_QDRANT_UNIT);
  },

  _channels: function() {
    let result = [];
    let seen = {};
    for (let part of String(this.channels || DEFAULT_CHANNELS).split(",")) {
      let channel = String(part || "").trim().toLowerCase();
      if (ALLOWED_CHANNELS.indexOf(channel) < 0 || seen[channel]) {
        continue;
      }
      seen[channel] = true;
      result.push(channel);
    }
    return result.length > 0 ? result.join(",") : DEFAULT_CHANNELS;
  },

  _codexUsagePath: function() {
    return this._safeLocalPath(this.codexUsagePath, DEFAULT_CODEX_USAGE_PATH);
  },

  _githubUrl: function() {
    return this._safeProjectUrl(this.githubUrl, DEFAULT_GITHUB_URL);
  },

  _commitsUrl: function() {
    return this._safeProjectUrl(this.commitsUrl, DEFAULT_COMMITS_URL);
  },

  _codexUsageCommand: function() {
    return this._codexUsageArgs().join(" ");
  },

  _codexUsageArgs: function() {
    return this._safeExecutableArgs(this.codexUsageCommand, [DEFAULT_CODEX_USAGE_COMMAND]);
  },

  _commandArgs: function(value, fallback) {
    let fallbackArgs = (fallback || []).slice();
    let raw = String(value || "").trim();
    if (!raw || this._hasCommandControlChars(raw)) {
      return fallbackArgs;
    }
    try {
      let [, argv] = GLib.shell_parse_argv(raw);
      if (argv && argv.length > 0) {
        return this._normalizeCommandArgv(argv, false);
      }
    } catch (err) {
      return fallbackArgs;
    }
    return fallbackArgs;
  },

  _hasCommandControlChars: function(value) {
    let text = String(value || "").toLowerCase();
    if (text.indexOf("\\n") >= 0 || text.indexOf("\\r") >= 0 || text.indexOf("\\u000a") >= 0 || text.indexOf("\\u000d") >= 0) {
      return true;
    }
    for (let index = 0; index < text.length; index++) {
      let code = text.charCodeAt(index);
      if (code < 0x20 || code === 0x7f) {
        return true;
      }
    }
    return false;
  },

  _safeExecutableArgs: function(value, fallback) {
    let fallbackArgs = (fallback || []).slice();
    let args = this._commandArgs(value, fallbackArgs);
    if (args.length === 0 || !this._isSafeExecutable(args[0])) {
      return fallbackArgs;
    }
    return args;
  },

  _safePythonArgs: function(value, fallback) {
    let fallbackArgs = (fallback || []).slice();
    let args = this._commandArgs(value, fallbackArgs);
    if (args.length === 0 || !this._isSafeExecutable(args[0])) {
      return fallbackArgs;
    }
    for (let index = 1; index < args.length; index++) {
      if (SAFE_PYTHON_PREFIX_FLAGS.indexOf(String(args[index] || "")) < 0) {
        return fallbackArgs;
      }
    }
    return args;
  },

  _resolveSpawnArgv: function(argv) {
    let normalized = this._normalizeCommandArgv(argv, true);
    let command = String(normalized[0] || "").trim();
    if (!this._isSafeExecutable(command)) {
      throw new Error("Command is not executable");
    }
    let resolvedCommand = this._trustedExecutablePath(command);
    if (!resolvedCommand) {
      throw new Error("Command is not in a trusted system path");
    }
    normalized[0] = resolvedCommand;
    return normalized;
  },

  _normalizeCommandArgv: function(argv, throwOnError) {
    let fail = function(message) {
      if (throwOnError) {
        throw new Error(message);
      }
      return [];
    };
    if (!Array.isArray(argv) || argv.length === 0 || argv.length > MAX_COMMAND_ARG_COUNT) {
      return fail(!Array.isArray(argv) || argv.length === 0 ? "Command arguments are empty" : "Too many command arguments");
    }
    let normalized = [];
    let totalChars = 0;
    for (let index = 0; index < argv.length; index++) {
      if (argv[index] === null || argv[index] === undefined) {
        return fail("Command argument is missing");
      }
      let value = String(argv[index]);
      if (index === 0) {
        value = value.trim();
      }
      if (this._hasCommandControlChars(value) || value.length > MAX_COMMAND_ARG_CHARS) {
        return fail(this._hasCommandControlChars(value) ? "Command argument contains invalid control character" : "Command argument is too large");
      }
      totalChars += value.length;
      if (totalChars > MAX_COMMAND_CHARS) {
        return fail("Command is too large");
      }
      normalized.push(value);
    }
    return normalized;
  },

  _trustedExecutablePath: function(command) {
    let value = String(command || "").trim();
    if (!this._isSafeExecutable(value)) {
      return null;
    }
    if (value.indexOf("/") < 0) {
      return this._findTrustedProgramInPath(value);
    }
    return this._trustedAbsoluteExecutablePath(value);
  },

  _trustedAbsoluteExecutablePath: function(path) {
    let name = String(path || "").split("/").pop();
    if (!name || this._hasCommandControlChars(name) || !/^[A-Za-z0-9._+-]+$/.test(name)) {
      return null;
    }
    for (let directory of TRUSTED_SPAWN_DIRS) {
      if (path === GLib.build_filenamev([directory, name])) {
        return path;
      }
    }
    if (Object.prototype.hasOwnProperty.call(TRUSTED_USER_LOCAL_COMMANDS, name)) {
      let userLocalPath = GLib.build_filenamev([TRUSTED_USER_LOCAL_SPAWN_DIR, name]);
      if (path === userLocalPath) {
        return path;
      }
    }
    return null;
  },

  _findTrustedProgramInPath: function(command) {
    let name = String(command || "").trim();
    if (!name || name.indexOf("/") >= 0 || this._hasCommandControlChars(name) || !/^[A-Za-z0-9._+-]+$/.test(name)) {
      return null;
    }
    for (let directory of TRUSTED_SPAWN_DIRS) {
      let path = GLib.build_filenamev([directory, name]);
      if (GLib.file_test(path, GLib.FileTest.IS_EXECUTABLE)) {
        return path;
      }
    }
    if (Object.prototype.hasOwnProperty.call(TRUSTED_USER_LOCAL_COMMANDS, name)) {
      let path = GLib.build_filenamev([TRUSTED_USER_LOCAL_SPAWN_DIR, name]);
      if (GLib.file_test(path, GLib.FileTest.IS_EXECUTABLE)) {
        return path;
      }
    }
    return null;
  },

  _isSafeExecutable: function(value) {
    let command = String(value || "").trim();
    if (!command || command.charAt(0) === "-" || command.indexOf("\u0000") >= 0 || command.length > 4096) {
      return false;
    }
    if (/^[A-Za-z][A-Za-z0-9+.-]*:\/\//.test(command)) {
      return false;
    }
    if (command.indexOf("/") >= 0) {
      return command.charAt(0) === "/" && GLib.file_test(command, GLib.FileTest.IS_EXECUTABLE);
    }
    if (command === "." || command === "..") {
      return false;
    }
    return /^[A-Za-z0-9._+-]+$/.test(command);
  },

  _qdrantUrl: function() {
    return this._safeLocalHttpUrl(this.qdrantUrl, DEFAULT_QDRANT_URL);
  },

  _safeLocalHttpUrl: function(value, fallback) {
    let defaultValue = String(fallback || DEFAULT_QDRANT_URL).trim() || DEFAULT_QDRANT_URL;
    let raw = String(value || defaultValue).trim() || defaultValue;
    let match = raw.match(/^(https?):\/\/(\[[^\]]+\]|[^/:?#]+):([0-9]+)(\/[^?#]*)?(\?[^#]*)?(#.*)?$/i);
    if (!match) {
      return defaultValue;
    }
    let host = String(match[2] || "").toLowerCase();
    let normalizedHost = host.replace(/^\[/, "").replace(/\]$/, "");
    if (["127.0.0.1", "localhost", "::1"].indexOf(normalizedHost) < 0) {
      return defaultValue;
    }
    if ((match[4] || "") && match[4] !== "/") {
      return defaultValue;
    }
    if (match[5] || match[6]) {
      return defaultValue;
    }
    let port = parseInt(match[3], 10);
    if (!(port > 0 && port <= 65535)) {
      return defaultValue;
    }
    return String(match[1]).toLowerCase() + "://" + host + ":" + String(port);
  },

  _qdrantCollectionCount: function(collections, name) {
    let item = collections ? collections[name] : null;
    if (!item) {
      return 0;
    }
    let parsed = this._nonNegativeInt(item.count, 0);
    return parsed > 0 ? parsed : 0;
  },

  _positiveInt: function(value, fallback) {
    let parsed = this._strictInt(value);
    return parsed > 0 ? parsed : fallback;
  },

  _nonNegativeInt: function(value, fallback) {
    let parsed = this._strictInt(value);
    return parsed !== null && parsed >= 0 ? parsed : fallback;
  },

  _boundedInt: function(value, fallback, minValue, maxValue) {
    let parsed = this._strictInt(value);
    if (!(parsed >= minValue)) {
      parsed = fallback;
    }
    if (parsed < minValue) {
      parsed = minValue;
    }
    if (parsed > maxValue) {
      parsed = maxValue;
    }
    return parsed;
  },

  _strictInt: function(value) {
    let text = String(value === null || value === undefined ? "" : value).trim();
    if (!/^[0-9]+$/.test(text)) {
      return null;
    }
    return parseInt(text, 10);
  },

  _statusTimeoutSeconds: function() {
    return this._boundedInt(this.statusTimeoutSeconds, DEFAULT_STATUS_TIMEOUT_SECONDS, STATUS_TIMEOUT_MIN_SECONDS, STATUS_TIMEOUT_MAX_SECONDS);
  },

  _safeUnitToken: function(value) {
    let token = String(value || "").trim().toLowerCase().replace(/[^a-z0-9_.@-]+/g, "-").replace(/[-.]{2,}/g, "-").replace(/^[^a-z0-9]+|[^a-z0-9]+$/g, "");
    if (token.length > MAX_UNIT_TOKEN_CHARS) {
      token = token.slice(0, MAX_UNIT_TOKEN_CHARS).replace(/[^a-z0-9]+$/g, "");
    }
    return token || "depressionsbot";
  },

  _safeSystemdUnit: function(value, fallback) {
    let fallbackUnit = String(fallback || DEFAULT_UNIT).trim() || DEFAULT_UNIT;
    let unit = String(value || fallbackUnit).trim() || fallbackUnit;
    if (unit.charAt(0) === "-" || unit.indexOf("/") >= 0 || unit.length > 256) {
      return fallbackUnit;
    }
    if (!/^[A-Za-z0-9_.@:-]+\.(service|timer|socket|target|path)$/.test(unit)) {
      return fallbackUnit;
    }
    return unit;
  },

  _safeLocalPath: function(value, fallback) {
    let fallbackPath = String(fallback || DEFAULT_REPO_PATH).trim() || DEFAULT_REPO_PATH;
    let path = String(value || fallbackPath).trim() || fallbackPath;
    if (path.charAt(0) !== "/" || /[\u0000-\u001F\u007F]/.test(path) || path.length > 4096) {
      return fallbackPath;
    }
    if (/^[A-Za-z][A-Za-z0-9+.-]*:\/\//.test(path)) {
      return fallbackPath;
    }
    return path;
  },

  _safeProjectUrl: function(value, fallback) {
    let fallbackUrl = String(fallback || DEFAULT_GITHUB_URL).trim() || DEFAULT_GITHUB_URL;
    let url = String(value || fallbackUrl).trim() || fallbackUrl;
    if (url.length > 2048 || /[\u0000-\u001F\u007F\s]/.test(url)) {
      return fallbackUrl;
    }
    if (!/^https:\/\/github\.com\/H234598\/TeeBotus(?:\/[A-Za-z0-9._~!$&'()*+,;=:@%/-]*)?(?:\?[A-Za-z0-9._~!$&'()*+,;=:@%/?-]*)?$/.test(url)) {
      return fallbackUrl;
    }
    if (this._projectUrlHasUnsafePathSegment(url)) {
      return fallbackUrl;
    }
    return url;
  },

  _projectUrlHasUnsafePathSegment: function(url) {
    let base = "https://github.com/H234598/TeeBotus";
    let path = String(url || "").split("?")[0].slice(base.length);
    for (let segment of path.split("/")) {
      if (!segment) {
        continue;
      }
      let decoded = segment;
      try {
        decoded = decodeURIComponent(segment);
      } catch (err) {
        return true;
      }
      if (segment === "." || segment === ".." || decoded === "." || decoded === ".." || decoded.indexOf("/") >= 0 || decoded.indexOf("\\") >= 0) {
        return true;
      }
    }
    return false;
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
    let seconds = Math.max(STATUS_REFRESH_MIN_SECONDS, this._positiveInt(this.statusRefreshSeconds, DEFAULT_STATUS_REFRESH_SECONDS));
    this.statusTimer = Mainloop.timeout_add_seconds(seconds, () => {
      this._refreshStatus();
      if (!this.autoRefresh) {
        this.statusTimer = 0;
        return false;
      }
      return true;
    });
  },

  on_applet_clicked: function() {
    this._refreshStatus();
    if (this.menu) {
      this.menu.toggle();
    }
  },

  on_applet_removed_from_panel: function() {
    this.appletRemoved = true;
    this.spawnGeneration += 1;
    this.statusRunning = false;
    this.statusRefreshPending = false;
    if (this.statusTimer) {
      Mainloop.source_remove(this.statusTimer);
      this.statusTimer = 0;
    }
    if (this.menu) {
      this.menu.destroy();
      this.menu = null;
    }
  }
};

function main(metadata, orientation, panelHeight, instanceId) {
  return new TeeBotusApplet(metadata, orientation, panelHeight, instanceId);
}
