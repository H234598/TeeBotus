# Bauplan: Aktueller Planstand Healthcheck-Warnungen und TeeBotus-Applet

**Stand:** 2026-07-13  
**Status:** Aktiv, noch nicht abgeschlossen  
**Quellstand:** TeeBotus `1.9.435`, Commit `97513246`  
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

Der letzte kostenfreie, lesende Runtime-Status liefert:

- Gesamtstatus: `warning`
- handlungsrelevant: `missing_key:1,warning:2`
- informative Befunde: `23`
- Qdrant: erreichbar; User-Memory-Vektor `64D` und
  Bibliothekar-Vektor `1024D` sind `ready`
- Signal-Services: registriert und erreichbar; die Account-Verknuepfung fehlt
  jedoch fuer einen Runtime-Slot
- HF-Pool: deaktiviert; Structured Decision faellt lokal auf Ollama zurueck

Die drei handlungsrelevanten Ursachen sind:

### 1. `hard_reasoning` ohne bewusst verfuegbare Authentisierung

Die Route verwendet das Profil `openai_premium` mit
`openai/gpt-5.5`, erwartet `OPENAI_API_KEY` und hat aktuell keinen wirksamen
Fallback. Der konfigurierte Gemini-Fallback wird bei deaktivierten Remote-
Fallbacks absichtlich nicht als aktiver Ersatz gewertet.

**Naechste Aktion:** bewusst entscheiden, ob

- ein dafuer vorgesehener generischer Key bereitgestellt wird, oder
- ein expliziter lokaler Fallback fuer diese Route konfiguriert wird.

Ein Key einer anderen Instanz oder eines anderen Zwecks darf nicht still
wiederverwendet werden. Wegen der frueheren OpenAI-Kostenprobleme wird hier
nichts automatisch aktiviert.

### 2. Depressionsbot ohne verknuepfte Signal-Identitaet

Signal ist als Runtime-Slot konfiguriert und erreichbar, aber die beobachtete
Signal-Identitaet ist keinem vorhandenen Account zugeordnet. Die Telegram-
Accounts allein rechtfertigen keine automatische Signal-Verknuepfung.

**Naechste Aktion:** die bestehende Account-ID und das vorgesehene Secret nur
ueber den bestaetigten `/login <account_id> <secret>`- beziehungsweise
Linking-Flow verknuepfen. Erst danach darf der Healthcheck die Warnung als
behoben ausweisen.

### 3. TBL-Codex-History: lokale Queue und zentrale Bridge abgleichen

Die TBL-History zeigt terminale `no_private_route`-Skips. Diese sind begruendet
und duerfen nicht endlos erneut versucht werden. Zusaetzlich besteht eine
Abweichung zwischen dem zentralen Dispatcher und dem lokalen TeeBotus-Store:

- zentraler Bridge-Status: Queue `0`
- lokaler read-only Report: `outbox_items=1545`, darunter
  `queued=76`, `skipped=101`, `accepted=1366`, `delivered=2`
- im Live-Payload wurden waehrend der letzten Probe `queued=75` und
  `total=1544` beobachtet; die Snapshot-Differenz ist zu dokumentieren und
  nicht als still behoben zu werten

**Naechste Aktion:** erst einen Dry-Run mit Dedupe-Key, lokaler und zentraler
ID, Empfaengerresultaten, Status und Versuchszahl ausfuehren. Danach getrennt
behandeln:

- `no_private_route`: terminaler, begruendeter Skip
- `compacted`: terminaler Archiv-/Digest-Zustand
- echte `failed`-Resultate: kontrollierter Retry oder Quarantaene
- lokale `queued`-Zeilen ohne zentrale Entsprechung: Reconciliation-Fall

Keine Summary, Outbox-Zeile oder Dispatch-Resultat darf ohne explizite
Entscheidung geloescht oder pauschal requeued werden.

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

## Arbeitsplan

1. **Healthpayload und Applet weiter synchron halten**
   - Jede neue Statusregel in Python, Applet und Regressionstest abbilden.
   - Detailursache, betroffene Route und sichere Aktion anzeigen.
   - Keine reine Kurzmeldung ohne zugrunde liegende Healthdaten zulassen.

2. **`hard_reasoning` explizit klaeren**
   - Konfiguration read-only pruefen.
   - Entweder vorgesehenen Key oder lokalen Fallback bewusst eintragen.
   - Tests fuer fehlenden Key, lokalen Fallback und absichtlich deaktivierten
     Remote-Fallback ergaenzen.

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

Bis dahin bleibt dieser Plan unter `Baupläne/` aktiv.
