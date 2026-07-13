# Bauplan: Healthcheck, TeeBotus-Applet und Runtime-Warnungen

**Stand:** 2026-07-13  
**Status:** Klassifikations- und Applet-Fehler behoben; drei echte Betriebsbefunde offen
**Geltungsbereich:** TeeBotus Healthcheck, Cinnamon-Applet, Signal-Diagnose und Codex-History-Dispatch

## Ziel

Der Healthcheck soll zwischen echten Handlungsproblemen und reinen Hinweisen unterscheiden. Das Cinnamon-Applet soll diese Information kompakt und verständlich anzeigen, ohne eine gesunde Teilkomponente wegen nicht benötigter oder durch Fallback abgedeckter Konfiguration als defekt zu melden.

Die Diagnose muss außerdem die für den Betrieb relevanten Zustände sichtbar machen:

- LLM-Routen und verfügbare Fallbacks
- Signal-Identität und Login-Zustand
- Account-Store und Memory-Integrität
- Qdrant und semantische Nebenindizes
- Codex-History-Collector, Outbox und Dispatcher
- Applet-Installation und geladene Version

## Leitlinien

1. **Sicherheit vor Komfort:** fehlende Authentisierung, nicht erreichbare Pflichtdienste und Datenverlust-Risiken bleiben echte Warnungen.
2. **Fallbacks sind explizit:** eine fehlende optionale oder ersetzte Route darf nicht automatisch als Systemdefekt erscheinen.
3. **Rohdiagnose bleibt erhalten:** die Detailansicht muss den ursprünglichen Fehler, die betroffene Route und die verwendete Fallback-Kette weiterhin zeigen.
4. **Keine stillen Zustandsänderungen:** Healthcheck und Applet lesen Status; Reparaturen werden als konkrete Aktion ausgewiesen.
5. **Versionierte Nachweise:** Tests, Live-Probes und Runtime-Versionen werden im Plan fortgeschrieben.

## 1. Healthcheck-Modell

### 1.1 Problemklassen

Der Healthcheck klassifiziert jedes Ergebnis mindestens als:

- `actionable`: Benutzer- oder Administratoreingriff erforderlich
- `warning`: Betriebsfunktion eingeschränkt oder Identität fehlt
- `informational`: Hinweis, Fallback, Detailmetrik oder optionale Konfiguration

Die Zusammenfassung verwendet dafür getrennte Zähler:

- `actionable_problem_count`
- `warning_count`
- `informational_problem_count`

Die bestehende Rohdiagnose bleibt neben der normalisierten Klassifikation verfügbar. Die Klassifikationslogik ist versioniert (`classification_version=2`), damit Applet und Bot dieselbe Bedeutung anzeigen.

### 1.2 Nicht als Top-Level-Defekt zählen

Folgende Zustände werden als Detailhinweis geführt, sofern eine funktionierende Alternative vorhanden ist:

- fehlender Key für eine nicht aktiv genutzte oder durch Fallback ersetzte Route
- nicht belegte Gemini- oder Provider-Slots
- Free-Tier-Limit- und Retention-Hinweise
- teilweise verfügbare Codex-Usage-Daten
- doppelte Provider-, API- oder Token-Slot-Einträge, sofern der aktive Slot eindeutig ist
- optionale Bibliothekar-, Embedding- oder Indexkomponenten, die abgeschaltet sind

Diese Informationen dürfen nicht verschwinden. Sie werden im Detailmenü und in den Diagnose-Rohdaten angezeigt.

### 1.3 Weiterhin echte Probleme

Aktuell bleiben zwei Befunde absichtlich handlungsrelevant:

1. Die Route `hard_reasoning` hat keinen generischen `OPENAI_API_KEY` und keinen wirksamen Fallback.
2. Die Signal-Identität des `Depressionsbot` ist noch nicht verknüpft.

Beide Punkte dürfen nicht automatisch durch eine stille Konfigurationsänderung behoben werden. Für `hard_reasoning` muss die gewünschte Route oder ein expliziter Fallback entschieden werden. Für Signal muss die Identität über den vorgesehenen Login-/Linking-Flow verknüpft werden.

## 2. Cinnamon-Applet

### 2.1 Anzeige

Das Applet zeigt im Hauptbereich:

- Gesamtzustand: `Gesund`, `Hinweise` oder `Handlungsbedarf`
- Anzahl echter Probleme
- Anzahl Hinweise
- kurze, priorisierte Meldungen
- Zeitpunkt des letzten erfolgreichen Healthchecks

Die Detailansicht enthält zusätzlich die vollständige Diagnose mit Route, Provider, Fallback, Dienst und Originalfehler. Ein bloßes `Health defekt` ohne Healthdaten ist nicht zulässig.

### 2.2 Handlungsorientierte Einträge

Für die zwei offenen Befunde werden konkrete nächste Schritte angezeigt:

- `hard_reasoning`: Route konfigurieren oder bewussten Fallback setzen
- `Depressionsbot Signal`: `/login <account_id> <secret>` ausführen und Signal-Identität prüfen

Das Applet darf keine Secrets anzeigen. Es darf nur Namen, Status, Ziel und sichere nächste Aktion nennen.

### 2.3 Installation und Reload

Das Applet wird aus dem Repository installiert nach:

`/home/teladi/.local/share/cinnamon/applets/teebotus@H234598`

Nach Änderungen sind mindestens zu prüfen:

- Repository- und Installationsstand mit `diff -qr`
- Cinnamon `ReloadXlet` erfolgreich
- Statusmenü lädt nach Reload echte Healthdaten
- keine Überschneidung von Status-, Warnungs- und Detailtexten

## 3. Signal-Diagnose

Der Signal-Runtime-Zustand des `Depressionsbot` bleibt aktiviert und wird separat von Telegram und anderen Adaptern ausgewiesen.

Der Healthcheck unterscheidet:

- Signal-Backend erreichbar
- Account/Identität vorhanden
- Identität dem richtigen TeeBotus-Account zugeordnet
- Login- oder Linking-Secret fehlt beziehungsweise wurde abgelehnt
- Nachrichtenpfad aktiv oder pausiert

Ein fehlendes Signal-Linking ist eine Warnung, aber kein globaler Ausfall der übrigen Bot-Runtime.

## 4. Codex-History und Statusausgabe

### 4.1 Dispatcher und Kompaktierung

Der History-Dispatcher besitzt die Kompaktierungsfunktion `0.2.0`:

- alte Queue-Einträge werden projektweise gruppiert
- Originale bleiben verschlüsselt erhalten und werden auf `compacted` gesetzt
- `history_compaction_members` dokumentiert die Zugehörigkeit zum Digest
- Auditdaten bleiben nachvollziehbar
- Digests werden als formatierte Markdown-Dateien versendet
- Versandziele bleiben auf TeeBotus-Logger (`TBL`) beschränkt

Nachweis der letzten Runde:

- 310 Originale wurden zu 10 projektbezogenen Digests kompaktiert
- 2 neuere Einzel-Summaries zusätzlich verarbeitet
- 1 vorheriger Eintrag zugestellt
- Dispatcher-Queue: `0`
- Status: `310 compacted`, `13 delivered`
- Sicherung vor der Kompaktierung: `/home/teladi/.local/state/history-dispatcher/history.sqlite3.pre-compaction-20260712T215508Z`

### 4.2 Healthcheck-Anbindung

Der Healthcheck soll für den Dispatcher mindestens Queue-Größe, letzte erfolgreiche Verarbeitung, Fehleranzahl, Zielinstanz und Version zeigen. Ein leerer Queue-Zustand ist nur zusammen mit einem erfolgreichen letzten Lauf gesund.

## 5. Account-Store und Memory

Reine, nur durch einen transienten Lock erzeugte Account-Verzeichnisse werden im Bericht ignoriert. Echte profillose oder datenhaltige Verzeichnisse bleiben sichtbar und müssen separat geprüft werden.

Der Healthcheck darf keine Memory-Dateien löschen oder reparieren. Recovery, Quarantäne und Import bleiben eigene, explizite Admin-Aktionen.

## 6. Nachweise der letzten Umsetzung

### Tests

- TeeBotus: `3540 passed, 2 skipped, 17 subtests passed in 195.67s`
- History-Dispatcher: `29 passed`

### Live-Probe

- `actionable_problem_count=2`
- Statusverteilung: `missing_key: 1`, `warning: 1`
- `informational_problem_count=22`
- Qdrant gesund
- Healthcheck-Kommando erfolgreich
- Applet installiert und nach Reload geladen

### Aktuelle Logikprüfung

- Ein `status=broken` bleibt handlungsrelevant, auch wenn dieselbe Zeile einen Fallback nennt.
- Ein Codex-History-`warning` wird nicht mehr wegen `queued=0` und `failed=0` ausgeblendet.
- Das v2-Applet verwendet bei `classification_version>=2` ausschließlich die getrennten actionable-Status und zeigt reine Hinweise nicht zusätzlich als Probleme.
- TBL-Codex-History zeigt die 101 terminalen `no_private_route`-Skips explizit; delegierte Queues werden nicht als Problemstatus ausgegeben.
- Malformierte History-Zeilen werden als `problem_statuses=malformed:N` ausgewiesen.
- Applet-Testdatei: `178 passed`
- Nach der Korrektur meldet der Live-Healthcheck `actionable_problem_count=3` und `informational_problem_count=21`.

### Versionen

- TeeBotus-Baseline: `1.9.372`, Commit `a732f5c8` (`Clarify applet health diagnostics`)
- TeeBotus aktueller Fixstand: `1.9.375`
- History-Dispatcher: `0.2.0`, Commit `b818cc1` (`Add encrypted history queue compaction`)

## 7. Offene Arbeitspakete

### A. `hard_reasoning` bewusst konfigurieren

- gewünschtes Modell und Provider festlegen
- generischen Key korrekt zuordnen oder expliziten Fallback definieren
- Healthcheck muss danach `actionable_problem_count` reduzieren
- Test für fehlenden Key ohne Fallback und für erfolgreichen Fallback ergänzen

### B. Depressionsbot-Signalidentität verknüpfen

- Account-ID und Signal-Identität prüfen
- Linking/Login über den vorgesehenen Flow durchführen
- Live-Nachricht testen
- Healthcheck und Applet müssen danach keinen offenen Signal-Befund mehr zeigen

### C. TBL-Codex-History-Warnung auflösen

- nicht erfolgreiche Statuswerte in der TBL-History aus dem SQL-/Account-Store ermitteln
- unterscheiden zwischen absichtlich übersprungenen, kompaktierten und fehlerhaften Einträgen
- fehlerhafte oder unzustellbare Einträge reparieren beziehungsweise explizit quarantänisieren
- danach Dispatcher- und Live-Healthcheck-Probe wiederholen

### D. Regelmäßige Laufzeitprüfung

- Healthcheck im Applet periodisch aktualisieren
- Dispatcher-Erfolg und Queue-Alter überwachen
- bei neuem echten Fehler zuerst Detaildiagnose und betroffene Komponente anzeigen
- Fallback- und Free-Tier-Hinweise nicht als Defekt hochstufen

## 8. Abschlusskriterien

Der Bauplan gilt erst als abgeschlossen, wenn:

- alle drei offenen Befunde behoben oder bewusst dokumentiert entschieden sind
- die Healthcheck-Suite und die History-Dispatcher-Suite erfolgreich laufen
- eine Live-Probe ohne falschen Top-Level-Defekt erfolgreich ist
- das Applet nach Reload die echten Daten anzeigt
- Runtime-Versionen und Commit-IDs im Plan aktualisiert sind
- die Nachweise im Plan eingetragen sind

Bis dahin bleibt dieser Plan unter `Baupläne/` aktiv und wird nicht in ein Archiv verschoben.
