# Bauplan: Aktueller Healthcheck- und Applet-Logikstand

**Stand:** 2026-07-13
**Status:** Aktiv, noch nicht abgeschlossen
**Geltungsbereich:** TeeBotus Healthcheck, Cinnamon-Applet, Runtime-Status, LLM-Routen, Signal-Identitaet und Codex-History-Dispatcher

## Ziel

Der Healthcheck soll echte Betriebsprobleme von erwartbaren Hinweisen und
funktionierenden Fallbacks trennen. Das Cinnamon-Applet soll oben den
tatsaechlichen Zustand mit Zaehlern und einer kurzen Ursache anzeigen. Die
Detailansicht muss die betroffene Komponente, Route, Statusursache und eine
sichere naechste Aktion erhalten.

Keine Diagnose darf durch eine reine Textkuerzung zu `Health defekt` werden.
Die Rohzeilen bleiben fuer die Detailansicht und die Admin-Diagnose erhalten.

## Arbeitsregeln

1. Sicherheit vor Bequemlichkeit: fehlende Authentisierung, Datenfehler und
   nicht erreichbare Pflichtdienste bleiben handlungsrelevant.
2. Ein konfigurierter und funktionierender Fallback unterdrueckt keinen
   Originalfehler, stuft ihn aber als Hinweis ein, wenn der Betrieb dadurch
   nicht eingeschraenkt ist.
3. Healthcheck, `/status` und Applet verwenden dieselbe Klassifikation.
4. Healthchecks lesen nur. Reparaturen, Reconciliation, Linking und
   Konfigurationsaenderungen sind explizite Aktionen.
5. Keine kostenpflichtigen Provider- oder LLM-Aufrufe fuer diese Pruefung.
6. Secrets werden weder in Plan, Applet noch Statusausgabe geschrieben.
7. Tests, Version, Commit und Live-Nachweise werden fortlaufend ergaenzt.

## Aktueller Quell- und Laufzeitstand

- Quellstand: TeeBotus `1.9.425`, Commit `2332583e`.
- Worktree: nur bekannte unversionierte Benutzerdateien; keine davon wird
  durch diesen Plan angefasst.
- Laufender Dienst: `teebotus.service` aktiv, aber noch auf dem vorher
  gestarteten Runtime-Stand `1.9.404`; deshalb kein automatischer Restart in
  diesem Audit.
- Qdrant: Service aktiv, beide benoetigten Collections `ready`.
- Codex-History-Collector: aktiv; Bridge-Modus mit Follow und Dispatch.
- Healthcheck-Kommando: erfolgreich, Runtime-Ausgabe strukturiert.

## Live-Befund vom 2026-07-13

Der lokale Healthcheck liefert aktuell:

- `status=warning`
- `total_problem_count=3`
- `actionable_problem_count=3`
- `actionable_problem_statuses=missing_key:1,warning:2`
- `informational_problem_count=23`
- `qdrant_problem_count=0`
- `command_ok=true`

Die drei handlungsrelevanten Signale sind konkret:

1. `llm_route=hard_reasoning`: Profil `openai_premium` hat keinen
   `OPENAI_API_KEY` und keinen wirksamen Fallback.
2. `account_identity_warning=Depressionsbot`: Signal ist als Runtime-Slot
   konfiguriert, aber noch keiner Signal-Identitaet zugeordnet.
3. `codex_history=TeeBotus_Logger`: `queued=46`, `skipped=101`, davon
   `skip_reasons=no_private_route:101`. Die Skips sind terminale, begruendete
   Nichtzustellungen und keine fehlgeschlagenen Zustellungen; der offene
   lokale Queue-Rueckstand muss trotzdem kontrolliert geklaert werden.

Weitere sichtbare Zustande sind derzeit Hinweise, keine Top-Level-Defekte:

- HF-Pool ist deaktiviert, strukturierte Entscheidungen fallen lokal auf
  Ollama zurueck.
- Groq-Key fehlt, aber die Route hat einen lokalen Fallback.
- Gemini-Free-Tier-Limits kommen teilweise aus konservativen Defaults.
- einzelne Codex-Usage-Konten liefern nur Teilmetriken.
- die delegierten Codex-History-Queues der Quellen werden im Bridge-Modus
  nicht als lokale Fehler gemeldet.

## Bereits umgesetzt

### Healthcheck und Applet

- `classification_version=2` trennt actionable Probleme von Informationen.
- Fallback-abgedeckte Routefehler werden im Detail sichtbar, aber nicht als
  Top-Level-Defekt gezaehlt.
- `missing_key` ohne Fallback bleibt handlungsrelevant.
- Applet-Header und Detailansicht zeigen Healthstatus, Zaehler,
  Problemdetails, Kommando-/Qdrant-Diagnose und Runtime-Version getrennt.
- Statuspayloads mit fehlerhaftem Dienst, Qdrant, Runtime-Returncode oder
  unstrukturierter Ausgabe werden fail-closed abgewiesen.

### Codex-History und Bridge

- lokale dispatchbare Outbox-Zeilen werden vor `dispatch.claim` idempotent in
  die zentrale Bridge nachgefuehrt.
- Dry-Run bleibt schreibfrei und meldet `would_mirror` beziehungsweise
  `would_sync`.
- terminale Dispatcher-Statuswerte werden lokal synchronisiert.
- erfolgreiche gemischte Ergebnisse (`accepted` plus `skipped`) behalten den
  Erfolgsstatus und keinen irrefuehrenden Skip-Grund als letzte Reason.
- `created_at` bestimmt stabil den neuesten History-Eintrag.
- unbekannte und malformierte Statuswerte werden nicht als Erfolg behandelt.

### Befund 67: Veralteter v2-Gesamtzaehler im Applet

`_healthProblemTotal()` vertraute bei `classification_version=2` bisher zu
stark auf `total_problem_count`. Wenn dieser Wert veraltet oder versehentlich
`0` war, konnten ein vorhandener `command_problem_count` und Qdrant-Probleme
im Applet-Kopf verschwinden. Die v2-Aggregation beruecksichtigt jetzt neben
dem Gesamtwert auch actionable Status, Kommandozaehler, Runtimezaehler und
Qdrant-Zaehler. Der bekannte Qdrant-Runtimezaehler wird dabei nicht doppelt
gezaehlt.

Nachweis:

- Regressionstest mit `total_problem_count=0`, `command_problem_count=1` und
  `qdrant_problem_count=2`: Ergebnis `3` statt `0`.
- Fokussierte Suite: `10 passed, 183 deselected`.
- Vollstaendige Applet-Suite: `193 passed in 36.48s`.
- SemVer-Bump auf `1.9.412`, Commit `5b3f0c26` (`Harden applet health aggregation`).

### Befund 68: Codex-History-Repofehler wurden als Hinweise verschluckt

Die Parserlogik stufte jede Zeile mit dem Praefix `codex_history_repo` als
rein informativ ein. Dadurch konnte ein Repo mit `failed:1`, `unknown` oder
anderen echten Fehlerstatuswerten den Top-Level-Healthcheck nicht erhoehen.
Die Ausnahme ist jetzt enger: reine `queued`-/`skipped`-Zustaende bleiben
Hinweise; fehlgeschlagene oder unklare Repo-Zustaende werden actionable.

Nachweis:

- Regressionstest mit einem `failed:1`-Repo und einem terminalen
  `skipped:1`-Repo: genau ein actionable und ein informativer Befund.
- Fokussierte Suite: `2 passed`.
- Vollstaendige Applet-Suite: `194 passed in 36.56s`.
- Live-Parser nach dem Fix: `actionable_problem_status_count=3`,
  `informational_problem_status_count=23`.
- SemVer-Bump auf `1.9.413`, Commit `80def506`
  (`Expose Codex history repository failures`).

### Befund 69: Unbekannte API- und Identitaetszustaende wurden als Hinweise behandelt

Die Duplikatunterdrueckung fuer `api_budget` und `account_identity` war zu
breit. Dadurch wurden ein `ready`-Datensatz mit Fehler sowie `unknown` bei
API-Route oder Account-Identitaet in den Informationszaehler verschoben. Die
Logik behandelt jetzt nur belegte, erwartbare Detailzustaende als Hinweis:
Fallback-abgedeckte API-Diagnosen sowie ein bekannter Identity-Warning mit
positivem `identity_warnings`-Zaehler. Unbekannte, fehlerhafte oder
unerreichbare Zustaende bleiben actionable.

Nachweis:

- Regressionstest fuer `api_budget status=ready error=...`,
  `api_budget status=unknown`, `account_identity status=unknown` und einen
  legitimen `identity_warnings=1`-Hinweis.
- Fokussierte Suite: `2 passed`.
- Vollstaendige Applet-Suite: `195 passed in 38.41s`.
- SemVer-Bump auf `1.9.414`, Commit `a4388030`
  (`Tighten applet diagnostic classification`).

### Befund 70: Fehlerdiagnosen ohne explizites `status=` wurden im Python-Parser ignoriert

Eine Runtime-Diagnosezeile wie `service=demo error=provider_failed` enthielt
einen echten Fehler, aber keinen der bekannten Statuswerte. Der Python-Parser
erzeugte dafuer bisher weder `status_counts` noch einen actionable Befund. Der
Parser leitet deshalb jetzt fuer eine solche Zeile `warning` ab. Bereits
klassifizierte Problemstatus wie `broken` oder
`unavailable` erhalten keine zusaetzliche Warnung; neutrale Werte wie
`error=none` bleiben gesund.

Nachweis:

- Regressionstest mit Fehler ohne Status, neutralem Fehler, `status=ok` plus
  Fehler und `status=broken` plus Fehler: `broken:1,warning:2` und insgesamt
  drei Problemstatus.
- Fokussierte Parser-/Health-Suite: `32 passed, 164 deselected`.
- Vollstaendige Applet-Suite: `196 passed in 39.72s`.
- SemVer-Bump auf `1.9.415`, Commit `245030e7`
  (`Detect error-only applet diagnostics`).

### Befund 71: Python- und JavaScript-Klassifikation liefen bei Fehlerzeilen auseinander

Nach Befund 70 meldete der Python-Healthpayload `service=demo
error=provider_failed` korrekt als `warning`, waehrend das JavaScript-Applet
die Zeile weiterhin nur bei `status=ready` plus Fehler als Problemzeile
sortierte. Dadurch konnte der Healthkopf eine Warnung anzeigen, waehrend der
konkrete Eintrag im Menue unter den normalen Zeilen blieb. Der gemeinsame
Klassifikator prueft jetzt in beiden Pfaden jedes nicht-neutrale `error` direkt;
die bisherige Ready-Sonderbehandlung ist entfallen.

Nachweis:

- JS-Regressionstest fuer `error=provider_failed` ohne `status=`; zusammen mit
  den bestehenden Ready-/Neutralfaellen: `3 passed, 194 deselected`.
- Vollstaendige Applet-Suite: `197 passed in 42.73s`.
- SemVer-Bump auf `1.9.416`, Commit `1acfb5c2`
  (`Align applet error classification`).

### Befund 72: Codex-History-Fehlermetadaten konnten bei neutralem Status verschwinden

Eine History-Zeile kann neben dem primaeren Status auch aggregierte Metadaten
tragen. Bei `status=skipped failed=1` oder bei
`status=ok problem_statuses=failed:1` enthielt die Zeile einen echten Fehler,
aber der Parser uebernahm nur den neutralen Primaerstatus. Dadurch blieb der
Fehler aus `status_counts`, der Projekt-Health und der actionable Aufteilung
heraus. Die Parserlogik erkennt fuer `codex_history` und
`codex_history_repo` jetzt positive `failed`-Zaehler sowie Problemmetadaten
ausserhalb von `queued`/`skipped` als `warning`. Reine Queue-/Skip-Metadaten
bleiben informativ bzw. neutral.

Nachweis:

- Regressionstest mit `status=skipped failed=1`,
  `status=ok problem_statuses=failed:1,skipped:2` und einer reinen
  `queued`-/`skipped`-Zeile: zwei actionable Warnungen, keine informative
  Fehlklassifikation.
- Fokussierte Codex-History-Suite: `3 passed, 195 deselected`.
- Vollstaendige Applet-Suite: `198 passed in 46.65s`.
- SemVer-Bump auf `1.9.417`, Commit `d5f73b50`
  (`Classify codex history failure metadata`).

### Befund 73: Stale v2-Healthzaehler konnten echte Runtime-Probleme verbergen

`_health_summary()` verwendete bei vorhandener v2-Klassifikation den
deklarierten `actionable_problem_status_count` ungeprueft. Wenn dieser Wert
stale oder inkonsistent `0` war, waehrend `actionable_status_counts` bereits
`warning:1` enthielt, wurde der Top-Level-Healthstatus faelschlich als `ok`
berechnet. Die Python-Aggregation nimmt jetzt fuer Problem-, actionable- und
informative Zaehler jeweils das Maximum aus deklarierter Zusammenfassung und
den strukturierten Detailzaehlern. Damit bleibt die robuste JS-Aggregation
auch im Payload-Erzeuger erhalten.

Nachweis:

- Regressionstest mit v2-Zusammenfassung `actionable=0` und Detailzaehler
  `warning=1`: Ergebnis `status=warning`, `actionable=1`, `total=1`.
- Fokussierte Payload-Suite: `3 passed, 196 deselected`.
- Vollstaendige Applet-Suite: `199 passed in 37.85s`.
- SemVer-Bump auf `1.9.418`, Commit `ee4ce348`
  (`Harden Python health aggregation`).

### Befund 74: API-Budgetfehler wurden auch ohne korrespondierende Route unterdrueckt

Die Duplikatlogik behandelte jeden nicht-`ready`-Status einer
`api_budget`-Zeile als Hinweis. Ein alleinstehendes
`api_budget=orphan status=missing_key` wurde dadurch nicht actionable,
obwohl keine `llm_route=orphan` existierte, die denselben Fehler bereits
meldete. Der Parser sammelt jetzt zuerst die vorhandenen LLM-Routennamen und
unterdrueckt API-Budgetprobleme nur noch, wenn eine passende Route oder ein
funktionierender Fallback nachweisbar ist. Die Reihenfolge der Zeilen ist
dabei unerheblich.

Nachweis:

- Regressionstest mit einer orphan API-Budgetzeile und einer passenden
  Duplikatzeile: orphan `missing_key` actionable, passende Zeile informativ;
  die korrespondierende Route bleibt ebenfalls actionable.
- Fokussierter Test: `1 passed, 199 deselected` nach der abschliessenden
  Parserbereinigung.
- Vollstaendige Applet-Suite vor der rein mechanischen Parserbereinigung:
  `200 passed in 35.26s`; danach fokussierter Test erneut gruen.
- SemVer-Bump auf `1.9.419`, Commit `b8ee21cf`
  (`Require matching route for API budget suppression`).

### Befund 75: Gesunde Route konnte einen widerspruechlichen API-Budgetfehler verdecken

Die neue Namenspruefung aus Befund 74 war noch zu schwach: Schon eine
gleichnamige `llm_route` reichte aus, um den `api_budget`-Fehler als Duplikat zu
behandeln. Bei `llm_route=conflict status=configured` und
`api_budget=conflict status=missing_key` wurde damit ein echter
Statuswiderspruch nicht actionable. Der Parser sammelt jetzt pro Route auch
die Problemstatus. Eine API-Budgetzeile wird nur dann unterdrueckt, wenn die
korrespondierende Route selbst einen Problemstatus oder einen wirksamen
Fallbackpfad ausweist. Eine gesunde Route macht den Budgetwiderspruch sichtbar.

Nachweis:

- Regressionstest mit orphan, matched-failing und matched-healthy/conflicting
  Route: zwei API-Budgetbefunde actionable, nur das echte Duplikat informativ.
- Fokussierte Klassifikationssuite: `3 passed, 197 deselected`.
- Vollstaendige Applet-Suite: `200 passed in 36.27s`.
- SemVer-Bump auf `1.9.420`, Commit `6f9ed0f5`
  (`Expose API budget route conflicts`).

### Befund 76: Unbekannter Structured-Decision-Zustand wurde durch Fallback verschluckt

Die Fallback-Klassifikation behandelte eine Zeile mit
`route_status=unknown fallback=local` als informativen Fallback-Hinweis. Ein
unbekannter Primärzustand ist aber kein belegter Ausfall, den der Fallback
zuverlaessig abdeckt. Dadurch konnte ein realer Routing-/Konfigurationsfehler
aus dem actionable Healthzaehler verschwinden. `unknown` ist jetzt ein
Fallback-Suppression-Blocker. Der erwartete `route_status=unavailable`-Fall
mit lokalem Fallback bleibt weiterhin informativ.

Nachweis:

- Regressionstest mit `route_status=unknown` und `route_status=unavailable`,
  jeweils mit Fallback: nur `unknown:1` actionable, `unavailable:1` informativ.
- Fokussierte Fallback-Suite: `3 passed, 198 deselected`.
- Vollstaendige Applet-Suite: `201 passed in 42.64s`.
- SemVer-Bump auf `1.9.421`, Commit `cd8a5761`
  (`Do not hide unknown decision routes`).

### Befund 77: Fallback-Sentinelwerte wurden als echte Fallbacks gewertet

Die Unterdrueckung pruefte nur, ob eines der Fallbackfelder nicht leer war.
Damit galten `fallback=none`, `disabled` oder `unknown` als konfigurierter
Fallback und konnten einen `route_status=unavailable`-Fehler verschlucken.
Die gemeinsame Fallbackpruefung verwirft jetzt diese Sentinelwerte sowie
`missing`, `unconfigured`, `not_configured` und `not_applicable`. Nur eine
konkrete Referenz wie `local_ollama` kann noch zur Fallbackklassifikation
beitragen.

Nachweis:

- Regressionstest mit drei Sentinelwerten und einem echten lokalen Fallback:
  drei `unavailable`-Befunde actionable, genau einer informativ.
- Fokussierte Fallback-Suite: `3 passed, 199 deselected`.
- Vollstaendige Applet-Suite: `202 passed in 40.21s`.
- SemVer-Bump auf `1.9.422`, Commit `ea2df35f`
  (`Reject disabled fallback references`).

### Befund 78: Explizite Fallback-Deaktivierung wurde von Modellfeldern ueberstimmt

Die Sentinelpruefung aus Befund 77 akzeptierte weiterhin widerspruechliche
Mehrfachfelder: `fallback=disabled fallback_model=local_ollama` wurde als
wirksamer Fallback gewertet, weil irgendein spaeteres Teilfeld plausibel war.
Jetzt entscheidet das erste explizit gesetzte Fallbackfeld. Ein Sentinelwert
beendet die Fallbackannahme; nur wenn kein frueheres Feld gesetzt ist, kann ein
Profil-, Modell- oder Offload-Feld den Nachweis liefern.

Nachweis:

- Regressionstest mit `fallback=disabled` plus Modell,
  `fallback=none` plus Profil, `fallback_profile=none` plus Modell und einem
  reinen Modellfallback: drei Befunde actionable, einer informativ.
- Fokussierte Fallback-Suite: `3 passed, 200 deselected`.
- Vollstaendige Applet-Suite: `203 passed in 41.79s`.
- SemVer-Bump auf `1.9.423`, Commit `049a0427`
  (`Prioritize explicit fallback disablement`).

### Befund 79: Gequotete Fallback-Sentinels wurden nicht normalisiert

Die Sentinelpruefung erkannte `none`, `disabled` und `unknown` nur ohne
Umschliessungszeichen. Statuszeilen mit `fallback="none"`,
`fallback='disabled'` oder ``fallback=`unknown` `` konnten deshalb weiterhin
als wirksame Fallbacks gelten. Die Fallbackreferenz entfernt jetzt passende
einfach-, doppelt- oder backtick-gequotete Umfassungen, bevor sie gegen die
Sentinelliste prueft.

Nachweis:

- Regressionstest mit allen drei Quoteformen und einem quotierten echten
  `local_ollama`-Fallback: drei Befunde actionable, einer informativ.
- Fokussierte Fallback-Suite: `3 passed, 201 deselected`.
- Vollstaendige Applet-Suite: `204 passed in 40.03s`.
- SemVer-Bump auf `1.9.424`, Commit `61b63e20`
  (`Normalize quoted fallback sentinels`).

### Befund 80: Gequotete Statuswerte wurden aus der Problemklassifikation verloren

`_normalized_status_value()` entfernte bisher keine umschliessenden Quotes.
Dadurch wurde `route_status="unknown"` nicht als `unknown` erkannt und konnte
komplett aus `status_counts` und actionable Health verschwinden. Die zentrale
Normalisierung entfernt jetzt einfache, doppelte und Backtick-Quotes fuer
primaere, sekundare und effektive Statuswerte. Die Fallbacknormalisierung
bleibt damit konsistent zur Statusklassifikation.

Nachweis:

- Regressionstest mit `route_status="unknown"` und
  `effective_status="configured"`: `unknown:1` actionable,
  `unavailable:1` informativ.
- Fokussierte Status-/Fallback-Suite: `3 passed, 202 deselected`.
- Vollstaendige Applet-Suite: `205 passed in 45.24s`.
- SemVer-Bump auf `1.9.425`, Commit `2332583e`
  (`Normalize quoted health statuses`).

## Naechste Arbeitspakete

### 1. `hard_reasoning` bewusst entscheiden

- pruefen, ob die Route aktuell wirklich verwendet werden soll.
- entweder den dafuer vorgesehenen Key korrekt bereitstellen oder im Profil
  einen expliziten lokalen Fallback konfigurieren.
- keinen generischen Key aus einem anderen Zweck oder einer anderen Instanz
  still uebernehmen.
- Regressionstest fuer `missing_key` ohne Fallback und fuer einen gesunden
  Fallback ergaenzen.

### 2. Depressionsbot-Signal verknuepfen

- bestehende Telegram-Account-ID und das vorgesehene Linking-Verfahren
  verwenden.
- Signal-Identitaet nur ueber den bestaetigten `/login`-/Linking-Flow
  zuordnen.
- anschliessend einen lesenden Healthcheck und einen kontrollierten
  Nachrichtenpfad testen.
- bis dahin die Warnung sichtbar lassen.

### 3. TBL-History-Rueckstand klaeren

- lokale und zentrale Statuswerte, Dedupe-Keys und Empfaengerresultate
  vergleichen.
- `no_private_route`, `compacted`, terminale Skips und echte Fehler getrennt
  behandeln.
- zuerst Dry-Run; der aktuelle Nachweis meldete `would_mirror=40` und
  `would_sync=4` bei `44` lokalen queued-Zeilen.
- einen echten Reconciliation-Lauf nur nach ausdruecklicher Freigabe
  ausfuehren.
- keine Summary, kein Artefakt und keine lokale Outbox-Zeile still loeschen.

### 4. Applet- und Installationsnachweis

- nach Codeaenderungen Repository-Applet mit der installierten Kopie
  vergleichen.
- Applet nur bei tatsaechlicher Applet-Aenderung reloaden.
- oben muessen Status, Healthzaehler und Ursachen sichtbar sein; reine
  Hinweise duerfen nicht als `Health defekt` erscheinen.

### 5. Verifikation und Abschluss

- fokussierte Healthcheck-/Applet-/Codex-History-Tests ausfuehren.
- relevante Gesamtsuite ausfuehren, sofern sie ohne Provideraufrufe bleibt.
- Live-Status erneut lesen und Version/Commit dokumentieren.
- Plan erst abschliessen, wenn die drei offenen Befunde behoben oder bewusst
  entschieden und nachvollziehbar dokumentiert sind.

## Invarianten

- Ein echter Fehler wird nicht durch einen Fallback oder `queued=0`
  unsichtbar.
- Ein terminaler Erfolg wird nicht erneut versendet.
- Ein terminaler `no_private_route`-Skip wird nicht endlos erneut versucht.
- Keine unbekannte Payload oder Statusform wird als gesund angenommen.
- Der Healthcheck veraendert weder Account-Memory noch Outbox.
- Status- und Applet-Zaehler zaehlen ueberlappende Qdrant-Signale nur einmal,
  zeigen die Detailfelder aber weiterhin getrennt.

## Abschlusskriterien

Der Bauplan bleibt aktiv, bis:

- `hard_reasoning` konfigurationsseitig geklaert ist,
- die Depressionsbot-Signalidentitaet bewusst verknuepft oder als bewusst
  deaktiviert dokumentiert ist,
- der TBL-History-Rueckstand kontrolliert reconciliert oder begruendet
  quarantainiert ist,
- Tests und Live-Probe ohne falschen Top-Level-Defekt erfolgreich sind,
- das installierte Applet nach Reload die echten Healthdaten anzeigt,
- Version, Commit und Nachweise hier aktualisiert sind.
