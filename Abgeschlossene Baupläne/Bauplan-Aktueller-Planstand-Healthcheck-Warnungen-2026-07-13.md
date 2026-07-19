# Bauplan: Aktueller Planstand Healthcheck-Warnungen und TeeBotus-Applet

**Stand:** 2026-07-13  
**Status:** Aktiv, noch nicht abgeschlossen  
**Quellstand:** TeeBotus `1.9.461`, Codecommit `78e2806a`
**Geltungsbereich:** `TeeBotus/cinnamon_applet.py`, Cinnamon-Applet,
Runtime-Healthpayload, LLM-Routen, Signal-Identitaet und Codex-History-Dispatch

## Auftrag

Die Warnungen und Probleme, die oben im TeeBotus-Cinnamon-Applet erscheinen,
werden bis zur Ursache geprueft. Echte Betriebsprobleme muessen sichtbar und
handlungsrelevant bleiben. Reine Fallback-, Free-Tier- oder
Delegationshinweise duerfen nicht als Defekt erscheinen, aber auch nicht aus
der Detaildiagnose verschwinden.

Der uebergeordnete Arbeitsauftrag lautet:

> Entwickle und finde Logikfehler. Bleibe moeglichst bei einer Datei bzw. einem
> Thema, um Token zu sparen.

## Leitplanken

- Sicherheit vor Bequemlichkeit: unbekannte, widerspruechliche oder nicht
  authentisierte Zustaende werden nicht als gesund behandelt.
- Keine kostenpflichtigen Provider- oder LLM-Aufrufe fuer Diagnose und Tests.
- Ein Fallback darf einen fachlich abgedeckten Hinweis herabstufen, aber keinen
  echten, ungeklarten Fehler verschlucken.
- Healthcheck und Applet lesen nur. Linking, Reconciliation, Requeue,
  Reparatur und Konfigurationsaenderungen bleiben explizite Aktionen.
- Secrets werden weder in Payloads, Plantexten, Logs noch Applet-Ausgaben
  ausgegeben.
- Benutzerdateien ausserhalb dieses Plans bleiben unangetastet:
  `.obsidian/`, `.stfolder/`, `Fusion_Packliste.txt`, `Unbenannt.base` und
  `Unbenannt.canvas`.
- Kein Push ohne ausdrueckliche Anforderung. Ein Bot- oder Service-Restart
  erfolgt nur an der vereinbarten 20-Commit-Grenze oder nach ausdruecklicher
  Freigabe.

## Ausgangslage und bereits erledigte Arbeit

### Health-Klassifikation

- `classification_version=2` trennt handlungsrelevante Probleme von
  informativen Hinweisen.
- Deklarative Listen wie `problem_statuses=broken:1` werden zusammen mit
  strukturierten Zaehlern ausgewertet.
- Stale oder widerspruechliche Gesamtzaehler koennen einen vorhandenen
  Einzelstatus nicht mehr auf `ok` herunterstufen.
- Quotes bei Statusnamen und numerischen Metadaten werden normalisiert.
- Negative Qdrant-Zaehler werden auf null begrenzt.
- Sekundaerstatus wie `semantic=unknown` oder `models_feed=unknown` bleiben
  trotz eines Fallbacks sichtbar und koennen nicht durch eine
  Informations-Sonderregel verdeckt werden.
- Ein nicht-neutraler expliziter `error=`-Wert bleibt auch in den speziellen
  Informationsfaellen fuer Identity, Codex-History, Structured Decision und
  generische Fallback-Zeilen handlungsrelevant.
- `gemini_free_tier_limits status=fallback_defaults` bleibt bei der bekannten
  konservativen Default-Ursache ein Hinweis, solange kein zusaetzlicher echter
  Fehler in derselben Zeile vorliegt.

### Applet und Installation

- Das Applet verwendet die strukturierte Healthpayload und zeigt
  kategorisierte Zaehler sowie Detailursachen statt nur `Health defekt`.
- Quell- und Installationskopie von `applet.js` stimmen ueberein.
- Installationspfad:
  `/home/teladi/.local/share/cinnamon/applets/teebotus@H234598`
- Ein Applet-Reload ist nach der aktuellen Python-only-Aenderung nicht noetig.
- Die Python-Seite der aktuellen Klassifikationskorrektur ist lokal committed;
  die installierte Runtime kann bis zum naechsten erlaubten Restart einen
  aelteren Stand verwenden.

### Verifikation

- Fokussierter Regressionstest fuer explizite Fehler in Fallback-Sonderfaellen:
  `5 passed, 209 deselected`.
- Vollstaendige `tests/test_cinnamon_applet.py`:
  `214 passed in 39.92s`.
- `git diff --check`: erfolgreich.
- Plan- und Klassifikationsnachweis zuletzt in Commit `7bb5d3d1`
  dokumentiert.

## Aktueller Live-Befund

Die letzte kostenfreie, lesende Live-Probe mit TeeBotus `1.9.443` liefert:

- Gesamtstatus: `warning`
- handlungsrelevant: `warning:1`
- informative Befunde: `23`
- Qdrant: erreichbar; User-Memory-Vektor `64D` und
  Bibliothekar-Vektor `1024D` sind `ready`
- Signal-Services: registriert und erreichbar; die Account-Verknuepfung fehlt
  fuer einen Runtime-Slot
- `hard_reasoning`: `configured`; die LiteLLM-OpenAI-Route nutzt einen
  instanzbezogenen Key-Fallback, ohne Secret-Ausgabe
- HF-Pool: deaktiviert; Structured Decision faellt lokal auf Ollama zurueck
- TBL-History: erklaerte `queued`-/`skipped`- und `no_private_route`-Befunde
  bleiben sichtbar, werden aber nicht als actionable Top-Level-Defekt gezaehlt

Die einzige actionable Ursache ist damit:

### Depressionsbot ohne verknuepfte Signal-Identitaet

Signal ist als Runtime-Slot konfiguriert und erreichbar, aber die beobachtete
Signal-Identitaet ist keinem vorhandenen Account zugeordnet. Die Telegram-
Accounts allein rechtfertigen keine automatische Signal-Verknuepfung.

**Naechste Aktion:** die bestehende Account-ID und das vorgesehene Secret nur
ueber den bestaetigten `/login <account_id> <secret>`- beziehungsweise
Linking-Flow verknuepfen. Erst danach darf der Healthcheck die Warnung als
behoben ausweisen.

Die TBL-History bleibt ein informativer Reconciliation-Kandidat. Es werden
keine Summarys, Outbox-Zeilen oder Dispatch-Resultate ohne separaten Dry-Run
geloescht oder pauschal requeued.

## Befund 92: Verifizierte Fallback-Fehler wurden ueberklassifiziert

Die explizite Fehlerbehandlung aus Befund 91 schuetzte echte Fehler korrekt,
zaehlte aber auch funktionierende Ersatzrouten als Top-Level-Problem. Das
betraf live die deaktivierte HF-Structured-Decision-Route und die fehlende
Groq-Konfiguration, obwohl jeweils `effective_status=configured` und ein
lokaler Fallback vorhanden waren.

### Umsetzung

- Ein technischer `error=`-Text wird bei einer Fallback-Zeile nur dann
  informativ, wenn der Ersatz durch gesunden `effective_status`, eine echte
  Fallback-Referenz und einen bekannten problematischen Primar-/Routenstatus
  belegt ist.
- Ohne effektiven Gesundheitsnachweis bleibt der Fehler actionable.
- Blockierende Statuswerte wie `unknown` und `broken` werden nicht durch den
  Fallback unterdrueckt.
- Die Rohzeile und ihre Fehlerursache bleiben in der Detaildiagnose erhalten.

### Nachweis

- Fokussiert: `2 passed, 213 deselected`.
- Vollstaendige Applet-Suite: `215 passed in 46.34s`.
- Live danach: `actionable=missing_key:1,warning:2`,
  `informational=23`, Qdrant ohne Probleme.
- SemVer `1.9.436`, Commit `8dc23e83`.

## Befund 93: Unbegruendete History-Skips wurden nicht fail-closed behandelt

Eine leere `skip_reasons`-Angabe wurde bisher immer als informativer Zustand
behandelt. Bei `skipped>0` fehlte damit der Nachweis, warum die Zustellung
ausgelassen wurde.

### Umsetzung und Nachweis

- Reine `queued`-Zeilen ohne Skips bleiben Hinweise.
- Ein Skip ohne Grund wird als actionable `warning` sichtbar.
- Der bekannte terminale Grund `no_private_route` bleibt informativ.
- Regression: `4 passed, 212 deselected`.
- Vollstaendige Applet-Suite: `216 passed in 46.70s`.
- Live unveraendert: `actionable=missing_key:1,warning:2`, Qdrant gesund.
- SemVer `1.9.437`, Commit `1f2eefdc`.

## Befund 94: Der History-Detailkandidat war nicht nach Schwere priorisiert

Wenn zuerst eine `warning`- und danach eine `broken`-Zeile erschien, blieb die
Warnung als `codex_history`-Detail stehen, obwohl die Zaehler den schwereren
Befund bereits erfassten.

### Umsetzung und Nachweis

- Problemstatus erhalten eine feste Prioritaet fuer die Auswahl der
  angezeigten History-Zeile.
- Schwerere spaetere Befunde ersetzen leichtere; Gleichstand bleibt stabil.
- Regression: `6 passed, 211 deselected`.
- Vollstaendige Applet-Suite: `217 passed in 38.03s`.
- Live unveraendert bei `actionable=missing_key:1,warning:2`, Qdrant gesund.
- SemVer `1.9.438`, Commit `a6bdbaf8`.

## Informative Befunde, die nicht als Defekt hochgestuft werden sollen

- HF-Pool ist bewusst deaktiviert; Structured Decision nutzt den lokalen
  Ollama-Fallback.
- Groq-Key fehlt, die Route besitzt aber einen lokalen Fallback.
- Gemini-Free-Tier-Limits werden teilweise aus konservativen Defaults gebildet,
  weil die oeffentliche Quelle keine vollstaendigen Modelllimits liefert.
- Einzelne Codex-Usage-Konten liefern nur Teilmetriken.
- Delegierte Codex-History-Quellen werden im Bridge-Modus nicht als lokale
  Fehler gemeldet.
- Terminale `no_private_route`-Skips sind nachvollziehbare Nichtzustellungen,
  solange kein neuer privater Empfaengerweg eingerichtet wurde.

## Befund 95: Quoted Healthwerte liefen zwischen Python und Applet auseinander

Der Python-Parser normalisiert Status- und Zahlenwerte auch bei einfachen,
doppelten und Backtick-Quotes. Das Cinnamon-Applet uebernahm diese Werte zwar
beim Feldparsing, erkannte aber beispielsweise `route_status="unknown"` nicht
als Problem und wertete `stale_hours="24"` nicht als veraltet. Dadurch konnten
Header und Detailmenue denselben Runtime-Befund unterschiedlich darstellen.

### Umsetzung und Nachweis

- Das Applet verwendet jetzt eine gemeinsame Normalisierung fuer aeussere
  Statusquotes bei Problemstatus und Flagwerten.
- Die numerische Statusnormalisierung entfernt dieselben Quotes, bevor
  Healthzaehler und Stale-Pruefungen ausgewertet werden.
- Regression fuer gequoteten unbekannten Status, gequotete Stale-Stunden,
  gequotete Integer und gequotete Warnflags.
- Vollstaendige `tests/test_cinnamon_applet.py`: `218 passed in 44.40s`.
- Applet lokal installiert; Quell- und Installationskopie sind byte-identisch.
- SemVer `1.9.439`, Commit `bfd641a8`.

### Aktuelle Live-Probe nach dem Fix

- Der lesende Runtime-Status bleibt `warning` mit
  `missing_key:1,warning:2`; das ist kein Parserfehler.
- Qdrant und der History-Dispatcher sind gesund; dessen zentrale Queue ist
  `0`.
- Die offenen Ursachen bleiben bewusst sichtbar: fehlender
  `hard_reasoning`-Key, fehlende Depressionsbot-Signal-Identitaet und lokale
  TBL-History-Zeilen mit `queued=84` sowie terminalen
  `no_private_route`-Skips.
- Kein Secret, keine Account-Verknuepfung, keine Outbox-Zeile und kein
  Servicezustand wurde durch die Diagnose veraendert.

## Befund 96: Codex-History-Aggregat bewertete erklaerte Skips zu streng

Die einzelnen `codex_history_repo`-Zeilen stuften eine ausschliesslich aus
`queued`/`skipped` bestehende History mit dem bekannten terminalen Grund
`no_private_route` bereits als Hinweis ein. Die aggregierte
`codex_history=...`-Zeile blieb dagegen handlungsbeduerftig und hob den
Applet-Healthstatus dadurch erneut auf `warning`.

### Umsetzung und Nachweis

- Die Aggregatklassifikation folgt jetzt derselben Regel wie die Repozeilen,
  aber nur bei explizitem `problem_statuses`-Feld.
- `failed>0`, Fehler, unbekannte Gruende, fehlende Skipgruende und nicht
  dokumentierte Queue-Aggregate bleiben actionable.
- Fokussierte Codex-History-Suite: `8 passed, 212 deselected`.
- Vollstaendige `tests/test_cinnamon_applet.py`: `220 passed in 36.27s`.
- SemVer `1.9.440`, Commit `13eed576` (`Classify explained history aggregates as informational`).

### Live-Ergebnis nach der Klassifikationskorrektur

Die Korrektur ist im Quellstand getestet; eine lesende Live-Probe gegen den
unveraenderten Dienst bestaetigt bereits `actionable_problem_count=2` mit
`missing_key:1,warning:1` statt vorher `missing_key:1,warning:2`. Der laufende
Botprozess stammt noch aus der Zeit vor dem Fix, wurde aber fuer diese reine
Parserauswertung nicht neu gestartet. Key- und Signalbefund bleiben davon
unberuehrt.

## Befund 97: Unvollstaendiger v2-Payload konnte Rohwarnungen verschlucken

Wenn das Applet `classification_version=2` und
`total_problem_count=0` erhielt, aber die dazugehoerigen Action-/Infofelder
fehlten, ignorierte es `runtime.status_counts`. Ein Rohwert wie
`warning:1` konnte dadurch als `Health ok` erscheinen.

### Umsetzung und Nachweis

- Der Applet-Pfad erkennt jetzt, ob v2-Klassifikationsfelder tatsaechlich
  vorhanden sind.
- Fehlen sie, werden Rohproblemstatusse fail-closed als actionable behandelt.
- Explizit deklarierte Informationsstatusse werden weiterhin nicht
  hochgestuft.
- Der konkrete Status wird auch im Header-Breakdown angezeigt.
- Fokussierter v2-Test: `4 passed, 217 deselected`.
- Vollstaendige `tests/test_cinnamon_applet.py`: `221 passed in 33.45s`.
- Applet lokal installiert und byte-identisch verifiziert.
- SemVer `1.9.441`, Commit `ccb511cc`.

## Befund 98: Gequotete Health-Breakdowns verloren ihre Paritaet

Python normalisiert bei `problem_statuses` aeussere Quotes und die
Gross-/Kleinschreibung des Statusnamens. Das Applet behandelte einen Wert wie
`"WARNING:1,BROKEN:2"` bisher teilweise als unbekannten Status. Dadurch waren
Anzeige, v2-Fallback und Zaehlung nicht durchgehend konsistent.

### Umsetzung und Nachweis

- Aeussere Quotes werden vor dem Split entfernt.
- Statusnamen werden bei Breakdown-Anzeige und v2-Rohfallback normalisiert.
- Quoted Counts bleiben ueber `_strictInt` numerisch nutzbar.
- Fokussierter Health/v2-Test: `5 passed, 217 deselected`.
- Vollstaendige `tests/test_cinnamon_applet.py`: `222 passed in 33.33s`.
- Applet lokal installiert und byte-identisch verifiziert.
- SemVer `1.9.442`, Commit `3896e7c3`.

## Befund 99: LiteLLM-OpenAI-Instanzschluessel wurden als fehlend gemeldet

Die Route `hard_reasoning` verwendet `provider=litellm` mit dem Modell
`openai/gpt-5.5` und `api_key_env=OPENAI_API_KEY`. Die Runtime hatte jedoch
nur instanzbezogene OpenAI-Schluessel, zum Beispiel
`OPENAI_API_KEY_<INSTANCE>`. Der Healthcheck pruefte fuer LiteLLM bisher nur
den generischen Variablennamen und meldete deshalb faelschlich
`missing_key`.

### Umsetzung und Nachweis

- LiteLLM-Routen mit `openai/*` verwenden jetzt dieselbe
  instanzbezogene Schluesselaufloesung wie direkte OpenAI-Routen.
- Account-, Route- und API-Budget-Status verwenden dieselbe Logik.
- Der Status zeigt die nichtgeheime Quelle `instance_fallback` an.
- Der Applet-Formatter zeigt diese Quelle als `instanzbezogener Fallback`.
- Regressionen fuer Runtime-Status und Applet-Formatierung ergaenzt.
- Vollstaendige Kompatibilitaets- und Applet-Suite: `359 passed in 86.82s`.
- `py_compile` und `git diff --check`: erfolgreich.
- Applet installiert; Quell- und Installationskopie sind byte-identisch.
- Live: `hard_reasoning` ist `configured`; actionable bleibt nur die
  fehlende Depressionsbot-Signal-Identitaet.
- SemVer `1.9.443`, Commit `2fd7bf6d`.

## Befund 100: Diagnose und Request-Pfad verwendeten unterschiedliche Keys

Nach Befund 99 meldete der Healthcheck den instanzbezogenen OpenAI-Key als
vorhanden. Die Runtime-Factory las beim Erzeugen des LiteLLM-Clients aber noch
direkt `source[OPENAI_API_KEY]`. Ohne globalen Key blieb der echte Client
damit leer, obwohl der Status `configured` meldete.

### Umsetzung und Nachweis

- Profil- und Purpose-Routen der Runtime-Factory loesen
  `OPENAI_API_KEY_<INSTANCE>` vor `OPENAI_API_KEY` auf.
- Die Sonderbehandlung gilt nur fuer OpenAI-kompatible LiteLLM-Modelle;
  lokale, Gemini- und andere Provider erben keinen OpenAI-Key.
- Regression prueft Profil- und Purpose-Route sowie die Instanz-vor-Global-
  Prioritaet ohne Provideraufruf.
- Router-Suite: `60 passed in 1.95s`.
- Factory-/Fallback-/Proactive-Suite: `50 passed in 1.86s`.
- Direkter Client-Probe: `api_key_matches_instance=True`.
- SemVer `1.9.444`, Commit `50278e3d`.

## Befund 101: Exportierter Profil-Builder blieb hinter dem Runtime-Builder

Der weiterhin exportierte `build_profiled_text_llm_client` hatte keinen
`instance_name`-Parameter und las deshalb bei OpenAI-Profilen nur den
globalen `api_key_env`. Damit konnte dieser öffentliche Kompatibilitätspfad
einen leeren Client-Key erzeugen, obwohl die Runtime-Factory bereits korrekt
auf den Instanz-Key fiel.

### Umsetzung und Nachweis

- Gemeinsame `resolve_profile_api_key`-Logik für Profil- und Runtime-Builder.
- `instance_name` ist beim exportierten Builder optional und
  rückwärtskompatibel.
- Instanz-Key gewinnt vor globalem Key; Nicht-OpenAI-Routen bleiben getrennt.
- Router-/Package-Suite: `68 passed in 1.97s`.
- Direkter Profil-Builder-Test mit Instanz-Key: erfolgreich.
- SemVer `1.9.445`, Commit `27338c58`.

## Befund 102: Kanal-/Slot-Key wurde vom Runtime-Builder ueberschrieben

`resolve_openai_key()` loeste einen vorhandenen
`OPENAI_API_KEY_<INSTANCE>_<CHANNEL>_<SLOT>` korrekt auf. Die Runtime-Factory
verwendete danach aber den allgemeineren Profil-Fallback
`OPENAI_API_KEY_<INSTANCE>`. Dadurch konnten Healthcheck und Request-Pfad
verschiedene effektive Keys verwenden.

### Umsetzung und Nachweis

- Runtime-Factory priorisiert jetzt `override > resolved runtime key >
  profile fallback` in Profil- und Purpose-Routen.
- Nicht-OpenAI-Routen bleiben von der Sonderlogik getrennt.
- Slot-vor-Instanz-Regressionen fuer beide Factory-Pfade sind gruen.
- Router-/Package-Suite: `70 passed in 2.06s`; inklusive Metadaten `76 passed
  in 1.96s`.
- Read-only-Runtime-Probe: `hard_reasoning` bleibt `configured` mit
  `key_scope=instance_fallback`, ohne Provideraufruf.
- SemVer `1.9.446`, Commit `b877409f`.

## Befund 103: OpenAI-Fallback ignorierte den Instanz-Key

Der Runtime-Builder las den Key des OpenAI-Fallbacks bisher direkt aus dem
globalen `fallback_api_key_env`. Bei einer vorhandenen
`OPENAI_API_KEY_<INSTANCE>` konnte der Primaerpfad daher konfiguriert sein,
waehrend der Fallback-Client ohne Key blieb.

### Umsetzung und Nachweis

- Fallback-Keys werden in Runtime- und exportiertem Profil-Builder jetzt mit
  dem gemeinsamen instanzbezogenen Resolver aufgeloest.
- HF-Pool-zu-OpenAI-Fallbacks verwenden den Instanz-Key vor dem globalen Key.
- Router-, Package-, HF-Fallback-, Proactive- und Metadaten-Suite:
  `128 passed in 3.88s`.
- SemVer `1.9.447`, Commit `bdf427b4`.

## Befund 104: Unpraefixiertes OpenAI-Fallback-Profil blieb ohne Instanz-Key

Bei `provider=litellm`, `model=gpt-4.1-mini` und
`api_key_env=OPENAI_API_KEY` wurde das Profil als remote behandelt, aber der
Key-Resolver erkannte den OpenAI-Kontext nur am `openai/`-Praefix. Der
Instanz-Fallback blieb dadurch leer.

### Umsetzung und Nachweis

- Das explizite `OPENAI_API_KEY`-Env aktiviert die Instanz-Key-Aufloesung auch
  fuer unpraefixierte LiteLLM-OpenAI-Modelle.
- Regression mit `OPENAI_API_KEY_<INSTANCE>` ist gruen.
- Betroffene Suite: `128 passed in 3.37s`.
- SemVer `1.9.448`, Commit `de5bc5a6`.

## Befund 105: Healthcheck und Fallback-Status nutzten den falschen Key-Scope

Die Statusklassifikation erkannte bei LiteLLM nur `openai/...` als
OpenAI-Route. Ein unpraefixiertes OpenAI-Modell mit explizitem
`OPENAI_API_KEY`-Env konnte dadurch trotz vorhandenem Instanz-Key als fehlend
erscheinen. Die Fallback-Zeile pruefte den Key ausserdem nur global.

### Umsetzung und Nachweis

- Explizites `OPENAI_API_KEY`-Env ist nun auch im Healthcheck ein
  OpenAI-Signal.
- Primaer- und Fallback-Status verwenden Instanz-vor-Global-Aufloesung.
- Status-Regressionen fuer unpraefixierte Profile und OpenAI-Fallbacks sind
  gruen.
- Entrypoint-/Runtime-Status- und LLM-Suiten gruen; SemVer `1.9.449`, Commit
  `25151c00`.

## Befund 106: Structured-Decision-Status verlor den Instanz-Key-Kontext

Der normale LLM- und Entscheidungsstatus uebergab die Instanznamen an die
OpenAI-Keypruefung. Die separate `structured_decision`-Zeile rief dieselbe
Pruefung ohne Instanznamen auf und konnte deshalb
`OPENAI_API_KEY_<INSTANCE>` trotz vorhandenem Key als `missing_key` melden.

### Umsetzung und Nachweis

- `_runtime_status_structured_decision_line()` uebergibt jetzt den aktuellen
  Instanznamen an `_runtime_route_status()`.
- Providerfreier Repro: ohne Instanzkontext `missing_key`, mit
  `instance_names=(Demo,)` `configured`.
- Neue Regression fuer eine instanzbezogene OpenAI-Route ist gruen.
- Entrypoint-Suite: `139 passed in 42.61s`; `git diff --check` und
  `compileall` gruen.
- SemVer `1.9.450`, Commit `d29b8a4c`.

## Befund 107: `route_error` wurde nicht als Fehler klassifiziert

Der Applet-Parser erkannte in `_line_has_error()` nur das Feld `error`. Die
Runtime-Statuszeilen der per-Account-Structured-Decision verwenden jedoch
`route_error`. Eine nicht verfuegbare Route ohne nachgewiesenen effektiven
Fallback konnte dadurch als rein informativ erscheinen.

### Umsetzung und Nachweis

- `_line_has_error()` prueft jetzt `error` und `route_error` gemeinsam.
- Providerfreier Parser-Repro klassifiziert die Route nun als actionable
  `unavailable:1` statt informational.
- Vollstaendige Applet-Suite: `224 passed in 36.13s`.
- Read-only Live-Probe zeigt die fuenf tatsaechlichen Structured-Decision-
  Slotprobleme jetzt explizit als `unavailable`; belegte Fallbacks bleiben
  informational.
- SemVer `1.9.451`, Commit `7eb2efa3`.

## Befund 108: Per-Account-Structured-Decision meldete keinen effektiven Fallback

Die aggregierte Route konnte den lokalen Fallback als konfiguriert ausweisen,
die per-Account-Zeile enthielt dagegen nur `route_status=unavailable`. Dem
Applet fehlte damit der Nachweis, dass `local_ollama` den Ausfall uebernimmt.

### Umsetzung und Nachweis

- `bot.py` loest das konkrete Fallbackprofil jetzt instanzbezogen auf und
  schreibt `effective_status` in die per-Account-Zeile.
- Fallback-Key- und Poolfehler bleiben actionable; ein belegtes
  `effective_status=configured` wird nur informational klassifiziert.
- Live-Parser: nur die echte Signal-Identitaetswarnung bleibt actionable;
  die HF-Pool-Ausfaelle mit lokalem Fallback sind informational.
- Entrypoint-Suite: `140 passed in 44.13s`; Applet-Suite: `225 passed in
  36.26s`.
- SemVer `1.9.452`, Commit `34729c1b`.

## Befund 109: Fallback- und Offload-Fehlerfelder wurden nicht bewertet

Der Applet-Parser behandelte `fallback_error` und `offload_error` nicht als
Fehlertext. Ein defektes Fallback mit `effective_status=broken` konnte dadurch
trotz `route_status=unavailable` als informational gelten.

### Umsetzung und Nachweis

- Freitextparser und `_line_has_error()` erkennen jetzt `fallback_error` und
  `offload_error` zusaetzlich zu `error` und `route_error`.
- Mehrteilige Fehlertexte bleiben bis zum naechsten strukturierten Feld
  erhalten.
- Providerfreier Repro fuer einen kaputten Fallback ist actionable; ein
  verifiziert konfigurierter Fallback bleibt informational.
- Applet-Suite: `226 passed in 35.69s`.
- SemVer `1.9.453`, Commit `417ef2ad`.

## Befund 110: `effective_status=degraded` wurde uebersehen

`effective_status` konnte `degraded`, `broken` oder `unavailable` enthalten,
war aber weder in der Python- noch in der JS-Liste der sekundaren
Problemstatusfelder. Ein gesunder Primaerstatus mit degradierter
Offload-/Fallbackschicht konnte deshalb als gesund erscheinen.

### Umsetzung und Nachweis

- `effective_status` ist jetzt in Python und im Cinnamon-Applet ein
  sekundaeres Statusfeld.
- Die JS-Konstanten und die Fehlerfelder bleiben mit dem Python-Parser
  synchron.
- Providerfreier Repro fuer `status=configured effective_status=degraded`
  ergibt jetzt `degraded:1` actionable.
- Applet-Suite: `227 passed in 34.09s`; `node --check` gruen.
- SemVer `1.9.454`, Commit `a11e716a`.

## Befund 111: Statusprovider umging die Secret-Service-Retry-Policy

`_runtime_status_secret_provider()` erzeugte direkt einen
`SecretToolInstanceSecretProvider` mit `lookup_retries=0`. Die Runtime-Policy
mit Wiederholungen, Delay und Timeout wurde dadurch fuer Status, Preflight und
Codex-History nicht verwendet. Ein intermittierender Lookup konnte so als
AccountStore-Fehler erscheinen.

### Umsetzung und Nachweis

- Die Statusfactory verwendet jetzt `runtime_secret_provider()` und bleibt
  mit `create_if_missing=False` strikt read-only.
- Env-gesteuerte Retry-, Delay- und Timeout-Werte sind providerfrei getestet.
- Entrypoint-Suite: `141 passed in 42.41s`.
- Read-only Live-Probe: Depressionsbot-History `status=ok`; nur die bekannte
  Signal-Identitaetswarnung bleibt actionable.
- SemVer `1.9.455`, Commit `bc3941c7`.

## Befund 112: Direkte Status-Provider umgingen die Runtime-Retry-Policy

Neben dem gemeinsamen Runtime-Statusprovider erzeugten mehrere Standalone-
Pruefungen in `TeeBotus/core/status.py` ihren Secret-Service-Provider direkt
mit den impliziten Nullwerten fuer Retries und Delay. Ein kurzzeitiger
Secret-Service-Lookupfehler konnte deshalb in Codex-History-, Account- und
Memory-Status als echter Store-/Decrypt-Fehler erscheinen, obwohl der normale
Runtimepfad bereits eine Retry-Policy besass.

### Umsetzung und Nachweis

- Eine read-only `_status_secret_provider()`-Factory verwendet jetzt dieselben
  env-gesteuerten Lookup-Retries, Delays und Timeouts wie die Runtime.
- `create_if_missing=False` bleibt unveraendert; der Healthcheck legt keine
  Secrets an und veraendert keine Accountdaten.
- Der direkte Factory-Aufruf ist providerfrei mit `2` Retries, `0.25` Sekunden
  Delay und `4` Sekunden Timeout getestet.
- Entrypoint-Suite: `142 passed`.
- Relevante Status-/Account-/Codex-History-Tests: `31 passed`.
- Vollstaendige Version-/Statussuite: `215 passed`.
- `git diff --check`: erfolgreich.
- Live read-only: `status=warning`, actionable `warning:1`,
  `codex_history=Depressionsbot status=ok`; Qdrant und Messenger-Dienste
  erreichbar.
- Der einzige actionable Befund bleibt die fehlende Signal-Identitaet des
  Depressionsbots. Die bestehende Account-ID wird nicht automatisch mit einem
  Signal-Absender verknuepft; dafuer bleibt der bestaetigte Linking-Flow
  erforderlich.
- Applet erneut lokal installiert; `applet.js` aus Quelle und Installation
  sind byte-identisch; `node --check` erfolgreich.
- SemVer `1.9.456`, Codecommit `893899eb`.

## Befund 113: JS-Healthbreakdowns akzeptierten unbekannte Statusnamen

Die Python-Aggregation filterte `problem_statuses` bereits auf die bekannte
Status-Allowlist. Der JS-Appletparser zaehlte dagegen jeden Text vor einem
Integer, auch wenn der Status unbekannt war. Ein fehlerhaftes oder erweitertes
Payload konnte dadurch den Header kuenstlich aufblasen und einen falschen
Healthbefund anzeigen.

### Umsetzung und Nachweis

- `_problemBreakdownText()` und `_problemBreakdownCount()` akzeptieren jetzt
  ausschliesslich `PROBLEM_STATUSES`, synchron zur Python-Seite.
- Unbekannte Statuswerte werden weder gerendert noch in Healthzaehler
  eingerechnet; bekannte Statuswerte bleiben erhalten.
- Regression fuer `bogus:999,warning:1`: `2 passed` fokussiert.
- Vollstaendige `tests/test_cinnamon_applet.py`: `228 passed`.
- `node --check` und `git diff --check`: erfolgreich.
- SemVer `1.9.457`, Codecommit `f8e3881e`.

## Befund 114: Partielles v2-Klassifikationspayload stufte Hinweise hoch

Python erkannte die v2-Klassifikation bisher nur ueber den actionable
Zaehler. Nach der Erkennung weiterer v2-Felder blieb der Default fuer einen
fehlenden actionable-Zaehler jedoch auf dem gesamten Rohproblemzaehler. Ein
Payload mit ausschliesslich `informational_problem_statuses` konnte dadurch
weiterhin als actionable Warnung im Applet erscheinen.

### Umsetzung und Nachweis

- Die v2-Erkennung prueft jetzt alle actionable- und informationalen
  Zaehler-/Breakdown-Felder.
- Bei partieller v2-Klassifikation wird ein fehlender actionable-Zaehler nur
  aus der expliziten actionable-Liste abgeleitet; ohne v2-Felder bleibt die
  alte fail-closed Ableitung bestehen.
- Regression fuer eine rein informative Warnung: `5 passed` fokussiert.
- Vollstaendige `tests/test_cinnamon_applet.py`: `229 passed`.
- `compileall`, `node --check` und `git diff --check`: erfolgreich.
- SemVer `1.9.458`, Codecommit `4285217b`.

## Befund 115: Standalone-Admin-Healthcheck nutzte keine Runtime-Retries

Der normale Botlauf injiziert bereits einen gemeinsamen Runtime-Provider. Der
eigenstaendige Fallbackpfad in `runtime/admin_accounts.py` erzeugte jedoch
noch einen read-only Provider mit impliziten Null-Retries. Ein transienter
Secret-Service-Fehler konnte deshalb bei direkter Admin-Gruppenpruefung weiter
als Store-/Routewarnung erscheinen.

### Umsetzung und Nachweis

- `_default_account_store()` verwendet jetzt `runtime_secret_provider()`.
- `create_if_missing=False` und der Account-Keyring-Guard bleiben erhalten.
- Der Delegate-Provider ist mit env-gesteuerten Retries, Delay und Timeout
  getestet.
- Admin-Account-Suite: `27 passed`.
- Entrypoint-Suite: `142 passed`.
- Status-/Version-/Secret-Hygiene-Suite: `221 passed`.
- SemVer `1.9.459`, Codecommit `26688145`.

## Befund 116: Codex-History-Fallbacks umgingen die Runtime-Secret-Policy

Report-, Watch-, Index- und Dispatch-Fallbacks in
`admin/codex_history.py` erzeugten eigene read-only Provider. Diese hatten
weder die Runtime-Retries noch den zentralen Account-Keyring-Guard. Ein
transienter Secret-Service-Lookup konnte deshalb in einem Standalone-
Codex-History-Lauf anders ausfallen als im Botstatus.

### Umsetzung und Nachweis

- Alle Default-Provider in den Codex-History-Pfaden verwenden jetzt
  `runtime_secret_provider()`.
- Explizit uebergebene Provider bleiben unveraendert moeglich.
- Codex-History-Suite und Runtime-Admin: `157 passed`.
- SemVer `1.9.460`, Codecommit `65126428`.

## Befund 117: Read-only Admin-Provider hatten keine Retry-/Timeout-Policy

Der spezielle Recovery-Provider darf absichtlich keinen Manifest-Guard
erzwingen: Er muss gerade unlesbare oder mit einem alten Schluessel
verschluesselte Artefakte diagnostizieren koennen. Er hatte aber bisher auch
keine Retries und kein subprocess-Timeout. Dadurch konnten transiente
Secret-Service-Probleme Recovery- und Adminberichte verfaelschen oder haengen.

### Umsetzung und Nachweis

- Normale Accounts- und Status-Auth-Reports verwenden jetzt den zentralen
  Runtime-Provider.
- Der Recovery-Provider behielt seine tolerante read-only Semantik, nutzt aber
  dieselben env-gesteuerten Retries, Delays und Timeouts.
- Ein Lookup-Transientenfall ist providerfrei getestet; der zuvor gebrochene
  Recovery-CLI-Fall bleibt gruen.
- Admin-/Recovery-Suite: `63 passed`.
- Entrypoint-/Status-Suite: `357 passed`.
- SemVer `1.9.461`, Codecommit `78e2806a`.

## Arbeitsplan

1. **Healthpayload und Applet weiter synchron halten**
   - Jede neue Statusregel in Python, Applet und Regressionstest abbilden.
   - Detailursache, betroffene Route und sichere Aktion anzeigen.
   - Keine reine Kurzmeldung ohne zugrunde liegende Healthdaten zulassen.

2. **`hard_reasoning` abgeschlossen**
   - Instanzbezogene Key-Aufloesung ist implementiert und getestet.
   - Kanal-/Slot-spezifische Runtime-Keys werden nicht mehr durch einen
     allgemeineren Instanz-Fallback ersetzt.
   - Kein generischer Key und kein kostenpflichtiger Provideraufruf wurden
     fuer die Korrektur aktiviert.

3. **Signal-Linking kontrolliert abschliessen**
   - Keine automatische Zuordnung anhand einer UUID oder Telegram-ID.
   - Bestaetigten Login-/Linking-Flow ausfuehren.
   - Danach Account-Store und Live-Healthcheck read-only pruefen.

4. **TBL-Reconciliation vorbereiten und nach Freigabe ausfuehren**
   - Dry-Run fuer lokale und zentrale Outbox erstellen.
   - Dedupe-Keys, Statuszeitpunkte, Empfaenger und Fehlergruende vergleichen.
   - Nur eindeutig zuordenbare Eintraege synchronisieren.
   - Nicht reparierbare oder widerspruechliche Eintraege quarantainisieren,
     nicht loeschen.

5. **Nachweise aktualisieren**
   - fokussierte Healthcheck- und Applet-Tests
   - relevante Gesamtsuite ohne Provideraufrufe
   - `git diff --check`
   - lesende Live-Probe
   - Applet-Quell-/Installationsvergleich nach JS-Aenderungen
   - Version, Commit und Ergebnis hier eintragen

## Invarianten

- Ein echter Fehler wird nicht durch Fallback, leere Queue oder stale Zaehler
  unsichtbar.
- Ein unbekannter oder widerspruechlicher Status wird nicht als Erfolg
  klassifiziert.
- Terminale Zustellungen und begruendete Skips werden nicht endlos versendet.
- Healthcheck und Applet zaehlen denselben Zustand nicht doppelt, verlieren
  aber keine deklarative Statusart.
- Diagnose veraendert weder Account-Memory, Outbox, Secrets noch Signal-
  Verknuepfungen.
- Tests verursachen keine echten OpenAI-, Gemini-, HF- oder sonstigen
  kostenpflichtigen Provideraufrufe.

## Abschlusskriterien

Der Bauplan bleibt aktiv, bis:

- `hard_reasoning` bewusst konfiguriert oder bewusst lokal ersetzt ist,
- die Depressionsbot-Signalidentitaet ueber den bestaetigten Flow verknuepft
  oder die Deaktivierung bewusst dokumentiert ist,
- der TBL-History-Rueckstand kontrolliert reconciliert oder begruendet
  quarantainisiert ist,
- die Tests und eine Live-Probe ohne falschen Top-Level-Defekt erfolgreich
  sind,
- das Applet die echten Healthdaten nach einem erforderlichen Reload anzeigt,
- Version, Commit und alle Nachweise im Plan aktualisiert sind.

Bis dahin bleibt dieser Plan unter `Abgeschlossene Baupläne/` aktiv.
