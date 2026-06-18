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
const DEFAULT_UNIT = "teebotus.service";
const DEFAULT_CHANNELS = "telegram,signal";
const DEFAULT_QDRANT_UNIT = "teebotus-qdrant.service";
const DEFAULT_QDRANT_URL = "http://127.0.0.1:6333";
const DEFAULT_CODEX_USAGE_PATH = GLib.build_filenamev([GLib.get_home_dir(), "codex-usage"]);
const DEFAULT_CODEX_USAGE_COMMAND = "codex-usage";
const DEFAULT_STATUS_REFRESH_SECONDS = 60;
const DEFAULT_STATUS_TIMEOUT_SECONDS = 30;
const STATUS_REFRESH_MIN_SECONDS = 15;
const MENU_LINE_LIMIT = 14;
const PROBLEM_STATUSES = [
  "broken",
  "config_conflict",
  "degraded",
  "error",
  "failed",
  "fallback_defaults",
  "invalid",
  "missing",
  "missing_key",
  "never",
  "no_limits_found",
  "schema_mismatch",
  "unknown",
  "unavailable",
  "unreachable",
  "warning"
];
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
    this.githubUrl = "https://github.com/H234598/TeeBotus";
    this.commitsUrl = "https://github.com/H234598/TeeBotus/commits/main";
    this.codexUsagePath = DEFAULT_CODEX_USAGE_PATH;
    this.codexUsageCommand = DEFAULT_CODEX_USAGE_COMMAND;
    this.clipboard = St.Clipboard.get_default();
    this.statusPayload = null;
    this.statusText = "";
    this.statusTimer = 0;
    this.statusRunning = false;
    this.lastError = "";

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
    this._populateStaticMenus();
    this._populateDynamicMenus();
    this._updateHeader();
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
    let summary = runtime.summary || {};
    let runtimeLines = [];
    if (summary.instances || summary.channels) {
      runtimeLines.push("Instanzen: " + String(summary.instances || "?") + " | Kanaele: " + String(summary.channels || this.channels || DEFAULT_CHANNELS));
    }
    runtimeLines = runtimeLines.concat(this._formatLines((sections["Konfiguration"] || []).concat(sections["Start"] || []), (line) => this._formatRuntimeLine(line)));
    this._populateLines(this.runtimeMenu.menu, runtimeLines, this._dynamicEmptyText(_("Runtime-Konfiguration wird geladen.")));

    let messengerLines = [];
    if (summary.telegram_slots || summary.signal_accounts || summary.matrix_homeservers) {
      messengerLines.push("Uebersicht: Telegram-Slots " + String(summary.telegram_slots || 0) + " | Signal-Accounts " + String(summary.signal_accounts || 0) + " | Matrix-Homeserver " + String(summary.matrix_homeservers || 0));
    }
    messengerLines = messengerLines.concat(this._formatLines(sections["Messenger"] || [], (line) => this._formatMessengerLine(line)));
    this._populateLines(this.messengerMenu.menu, messengerLines, this._dynamicEmptyText(_("Messenger-Diagnose wird geladen.")));

    let llmLines = [];
    if (summary.llm_routes || summary.hf_pool || summary.gemini_free_tier) {
      llmLines.push("Uebersicht: LLM-Routen " + String(summary.llm_routes || 0));
    }
    llmLines = llmLines.concat(this._formatLines(sections["LLM-Routen und Backends"] || [], (line) => this._formatLlmLine(line)));
    this._populateLines(this.llmMenu.menu, llmLines, this._dynamicEmptyText(_("LLM-Diagnose wird geladen.")));

    if (this.showApiSection) {
      let apiLines = [];
      if (summary.api_budgets || summary.codex_usage_accounts) {
        apiLines.push("Uebersicht: API-Routen " + String(summary.api_budgets || 0) + " | codex-usage Accounts " + String(summary.codex_usage_accounts || 0));
      }
      apiLines = apiLines.concat(this._formatLines(sections["API Keys, Limits und Kosten"] || [], (line) => this._formatApiBudgetLine(line)));
      this._populateLines(this.apiMenu.menu, apiLines, this._dynamicEmptyText(_("API-/Usage-Diagnose wird geladen.")));
      this._appendCodexUsageActions();
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
      );
    }
    if (qdrant.unit) {
      memoryLines.push("Qdrant-Service " + String(qdrant.unit.name || this.qdrantUnit || DEFAULT_QDRANT_UNIT) + ": " + this._statusWord(qdrant.unit.active_state || "unknown") + " / " + String(qdrant.unit.sub_state || "unknown"));
    }
    if (bibliothekarPoints > 0) {
      memoryLines.push("Bibliothekar-Vektoren: " + String(bibliothekarPoints));
    }
    memoryLines = memoryLines.concat(this._formatLines(sections["Memory und semantische Suche"] || [], (line) => this._formatMemoryLine(line)));
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

  _dynamicEmptyText: function(loadingText) {
    if (this.statusRunning || !this.statusPayload) {
      return loadingText;
    }
    return _("Keine passenden Statuszeilen im Runtime-Status.");
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
      return "Telegram " + fields.telegram_slot + ": " + this._statusWord(fields.status) + "; Token " + String(fields.token || "unbekannt");
    }
    if (fields.signal_account) {
      let phone = fields.phone ? "; Telefon " + fields.phone : "";
      return "Signal " + fields.signal_account + ": " + this._statusWord(fields.status) + phone + "; REST " + String(fields.target || "unbekannt");
    }
    if (fields.signal_service) {
      return "Signal-REST " + fields.signal_service + ": " + this._statusWord(fields.status) + " auf " + String(fields.target || "unbekannt");
    }
    if (fields.matrix_homeserver) {
      return "Matrix " + fields.matrix_homeserver + ": " + this._statusWord(fields.status) + "; " + String(fields.target || "");
    }
    return line;
  },

  _formatLlmLine: function(line) {
    let fields = this._parseFields(line);
    if (fields.hf_pool) {
      return "HF-Pool " + fields.hf_pool + ": " + this._statusWord(fields.status);
    }
    if (line.indexOf("gemini_free_tier_limits ") === 0 || fields.gemini_free_tier_limits !== undefined) {
      let source = fields.source ? "; Quelle " + fields.source : "";
      let models = fields.models ? "; Modelle " + fields.models : "";
      return "Gemini Free-Tier-Limits: " + this._statusWord(fields.status) + models + source;
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
      return text;
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
      return text;
    }
    if (fields.codex_usage) {
      let stale = fields.stale_hours ? "; Alter " + fields.stale_hours + "h" : "";
      return "codex-usage: " + this._statusWord(fields.status) + "; Snapshots " + String(fields.snapshots || "0") + stale;
    }
    if (fields.codex_usage_account) {
      return "codex-usage " + fields.codex_usage_account + ": " + this._statusWord(fields.status) + "; 5h " + String(fields.five_hour || "?") + "; Woche " + String(fields.weekly || "?");
    }
    return line;
  },

  _formatMemoryLine: function(line) {
    let fields = this._parseFields(line);
    if (fields.qdrant) {
      let fallback = fields.fallback ? "; Ersatzsuche: " + fields.fallback : "";
      return "Semantischer Index " + fields.qdrant + ": " + this._statusWord(fields.status) + fallback;
    }
    if (fields.qdrant_collection) {
      return "Qdrant Collection " + fields.qdrant_collection + ": " + this._statusWord(fields.status) + "; Vektor " + String(fields.vector_size || "?") + "; Embedding " + String(fields.embedding_model || "?");
    }
    if (fields.memory_index) {
      return "Memory Index " + fields.memory_index + ": " + this._statusWord(fields.status) + "; Backend " + String(fields.backend || "?") + "; Semantik " + String(fields.semantic || "?");
    }
    return line;
  },

  _statusWord: function(status) {
    let value = String(status || "unknown");
    let labels = {
      configured: "konfiguriert",
      config_conflict: "Konfigurationskonflikt",
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
      no_limits_found: "keine Limits gefunden",
      not_applicable: "nicht anwendbar",
      not_configured: "nicht konfiguriert",
      ok: "ok",
      planned: "geplant",
      reachable: "erreichbar",
      ready: "bereit",
      registered: "registriert",
      schema_mismatch: "Schema passt nicht",
      unknown: "unbekannt",
      unavailable: "nicht verfuegbar",
      unreachable: "nicht erreichbar",
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
    for (let part of String(line || "").split(/\s+/)) {
      let index = part.indexOf("=");
      if (index < 0) {
        continue;
      }
      let key = part.slice(0, index).trim();
      let value = part.slice(index + 1).trim();
      if (key) {
        fields[key] = value;
      }
    }
    return fields;
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
      this._buildMenu();
      this._updatePanel();
    }, this._repoPath());
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
      "--qdrant-unit",
      String(this.qdrantUnit || DEFAULT_QDRANT_UNIT),
      "--qdrant-url",
      String(this.qdrantUrl || DEFAULT_QDRANT_URL),
      "--python",
      this._pythonPath(),
      "--timeout",
      String(this._positiveInt(this.statusTimeoutSeconds, DEFAULT_STATUS_TIMEOUT_SECONDS))
    ]);
  },

  _statusSummary: function(payload) {
    let unit = payload.unit || {};
    let health = payload.health || {};
    let runtime = payload.runtime || {};
    let summary = runtime.summary || {};
    let counts = runtime.status_counts || {};
    let bad = parseInt(health.total_problem_count, 10);
    if (!(bad >= 0)) {
      bad = parseInt(summary.problem_status_count, 10);
    }
    if (!(bad >= 0)) {
      bad = this._problemStatusCount(counts);
    }
    let state = String(unit.active_state || "unknown");
    let instances = String(summary.instances || "?");
    let channels = String(summary.channels || this.channels || DEFAULT_CHANNELS);
    let qdrant = payload.qdrant || {};
    let vectors = this._qdrantCollectionCount(qdrant.collections || {}, "teebotus_user_memory");
    let vectorText = vectors > 0 ? " | Vektoren " + String(vectors) : "";
    let healthText = this._statusWord(health.status || (payload.ok ? "ok" : "warning"));
    return "Health " + healthText + " | Unit " + state + " | " + instances + " | " + channels + vectorText + " | Warnungen " + String(bad);
  },

  _problemStatusCount: function(counts) {
    let total = 0;
    for (let status of PROBLEM_STATUSES) {
      total += parseInt((counts || {})[status] || 0, 10) || 0;
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
    this.headerItem.label.set_text("TB " + String(payload.version || "?"));
    this.summaryItem.label.set_text(this.statusText || _("Status unbekannt"));
    let commit = repo.short_commit ? " | " + repo.short_commit : "";
    this.versionItem.label.set_text("Health: " + this._statusWord(health.status || "unknown") + " | Unit: " + String(unit.active_state || "unknown") + " / " + String(unit.sub_state || "unknown") + commit + " | LLM-Routen: " + String(summary.llm_routes || 0));
  },

  _updatePanel: function() {
    this.set_applet_label("TB");
    this.set_applet_tooltip(this.statusText || _("TB"));
  },

  _setPanelState: function(state) {
    if (state === "refreshing") {
      this.set_applet_label("TB");
    }
  },

  _spawnJson: function(argv, callback, cwd) {
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
    }, cwd);
  },

  _spawn: function(argv, callback, cwd) {
    try {
      let launcher = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE);
      if (cwd) {
        launcher.set_cwd(String(cwd));
      }
      let process = launcher.spawnv(argv);
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
    this._spawn(["zenity", "--question", "--title=TB", "--text=" + action + " " + unit + "?"], (stdout, stderr, ok) => {
      if (ok) {
        run();
      }
    }, this._repoPath());
  },

  _openRuntimeStatusTerminal: function() {
    this._openTerminalForCommand(this._repoPath(), this._pythonArgs().concat(["-m", "TeeBotus", "--runtime-status", "--channels", String(this.channels || DEFAULT_CHANNELS)]));
  },

  _openQdrantStatusTerminal: function() {
    this._openTerminalForCommand(this._repoPath(), ["systemctl", "--user", "status", String(this.qdrantUnit || DEFAULT_QDRANT_UNIT), "--no-pager"]);
  },

  _appendQdrantActions: function() {
    this.memoryMenu.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
    this.memoryMenu.menu.addMenuItem(this._actionItem(_("Qdrant-Status"), () => this._openQdrantStatusTerminal()));
    this.memoryMenu.menu.addMenuItem(this._actionItem(_("Qdrant-Collections JSON"), () => this._openTerminalForCommand(this._repoPath(), ["curl", "-fsS", this._qdrantUrl() + "/collections"])));
    this.memoryMenu.menu.addMenuItem(this._actionItem(_("Usermemory-Vektoranzahl"), () => this._openTerminalForCommand(this._repoPath(), ["curl", "-fsS", "-X", "POST", this._qdrantUrl() + "/collections/teebotus_user_memory/points/count", "-H", "Content-Type: application/json", "-d", "{\"exact\":true}"])));
    this.memoryMenu.menu.addMenuItem(this._actionItem(_("Usermemory-Vektoren rebuilden"), () => this._openTerminalForCommand(this._repoPath(), this._pythonArgs().concat(["-m", "TeeBotus.embedding", "memory-rebuild"]))));
  },

  _openCodexUsage: function(args) {
    this._openTerminalForCommand(this._codexUsagePath(), [this._codexUsageCommand()].concat(args || []));
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

  _codexUsagePath: function() {
    return String(this.codexUsagePath || DEFAULT_CODEX_USAGE_PATH).trim() || DEFAULT_CODEX_USAGE_PATH;
  },

  _codexUsageCommand: function() {
    return String(this.codexUsageCommand || DEFAULT_CODEX_USAGE_COMMAND).trim() || DEFAULT_CODEX_USAGE_COMMAND;
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
    let parsed = parseInt(item.count, 10);
    return parsed > 0 ? parsed : 0;
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
    let seconds = Math.max(STATUS_REFRESH_MIN_SECONDS, this._positiveInt(this.statusRefreshSeconds, DEFAULT_STATUS_REFRESH_SECONDS));
    this.statusTimer = Mainloop.timeout_add_seconds(seconds, () => {
      this._refreshStatus();
      return Boolean(this.autoRefresh);
    });
  },

  on_applet_clicked: function() {
    this._refreshStatus();
    if (this.menu) {
      this.menu.toggle();
    }
  },

  on_applet_removed_from_panel: function() {
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
