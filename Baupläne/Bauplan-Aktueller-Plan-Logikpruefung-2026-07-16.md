# Bauplan: Aktuelle Logikpruefung und Memory-Konsistenz

**Stand:** 2026-07-16

**Status:** Aktiv

**Geltungsbereich:** TeeBotus-Runtime, AccountStore, strukturiertes
User-Memory, Working-Memory, Telegram-Adapter, Cinnamon-Healthcheck und
zugehoerige Regressionstests.

## Auftrag

Logikfehler reproduzieren, Ursache im gemeinsamen Pfad beheben und mit einer
kleinen Regression absichern. Fokus pro Arbeitsschritt auf einer Datei oder
einem eng zusammenhaengenden Thema. Keine Provider- oder LLM-Aufrufe fuer
Diagnose und Tests.

## Leitplanken

- Bestehende Benutzerdateien und fremde uncommittete Aenderungen nicht
  veraendern.
- Keine Secrets, Account-IDs oder privaten Nachrichteninhalte in Plan,
  Testausgabe oder Applet-Payload speichern.
- Account-Memory darf bei Lese-, Schreib- oder Rollback-Fehlern nicht still
  durch leeren Speicher ersetzt werden.
- Entries und Index muessen nach jeder strukturierten Memory-Operation
  konsistent bleiben; ein fehlgeschlagener Rollback muss sichtbar werden.
- Healthcheck und Status-Applet bleiben read-only.
- Tests bleiben providerfrei.
- Kein Push ohne ausdrueckliche Freigabe.
- Bot-/Service-Restart erst an der vereinbarten 20-Commit-Grenze. Seit letztem
  Restart sind aktuell 29 Commits vorhanden; naechster Restart ab Commit 40.

## Aktueller Plan

1. **AccountStore-Multi-Write-Pfade auditieren.**
   `mark_structured_memory_accessed()` und
   `rebuild_structured_memory_index()` auf Teilfehler zwischen Entries- und
   Indexschreibvorgang pruefen.
   Erfolg: jeder Fehlerfall und jeder bereits vorhandene Rollbackpfad ist
   konkret belegt.
2. **Nur belegte Inkonsistenz beheben.**
   Den kleinsten gemeinsamen Fix verwenden. Bei Schreibfehlern vorherigen
   Entries-/Indexstand wiederherstellen; fehlgeschlagenen Rollback separat
   melden.
   Erfolg: kein stiller halbgeschriebener Memory-Zustand.
3. **Regressionen ergaenzen.**
   Fuer jeden geaenderten Pfad einen simulierten Index-/Entries-Fehler testen
   und Byte-/Objektgleichheit des alten Zustands pruefen.
   Erfolg: fokussierte AccountStore-Suite gruen, ohne Provideraufrufe.
4. **Gesamtnachweis ausfuehren.**
   Relevante Tests, `py_compile` und `git diff --check` ausfuehren.
   Erfolg: Ergebnisse reproduzierbar dokumentiert.
5. **Plan und Git-Stand pflegen.**
   Befund, Fix, Commit und Testresultat hier eintragen. Lokalen Commit nach
   jedem Fix erstellen. Nicht pushen und nicht vor Commit 40 restarten.

## Bereits umgesetzt

### Healthcheck und Cinnamon-Applet

- Health-Klassifikation trennt actionable Probleme von informativen
  Hinweisen.
- Applet-Validator prueft Boolean-Konsistenz, Servicezustand, Qdrant-
  Collections, Runtime-Returncode und Health-Zaehler fail-closed.
- Read-only Live-Probe: Runtime `1.9.498`, Service aktiv, Qdrant `2/2 ready`,
  `actionable_problem_count=0`, `total_problem_count=0`.
- Sichtbare Hinweise sind erklaert; eine unbelegte Anzeige `Health defekt`
  wird nicht durch einen weiteren Quellpatch verdeckt.
- Cinnamon-Applet-Suite: `238 passed in 35.94s`.

### Telegram-Adapter

- Lange Textantworten werden Telegram-konform geteilt.
- Reply-Parameter bleiben bei Text, Attachment und Export erhalten.
- `SendEdit` reicht `text_mode` weiter.
- Kompatibilitaetsfallbacks greifen nur bei einer echten Meldung
  `unexpected keyword argument '<name>'`; echte `TypeError`s bleiben sichtbar.
- Adapter-Vollsuite zuletzt: `153 passed`; keine Provider-/LLM-Aufrufe.

### Working-Memory

- Lesefehler vorhandener Indexdateien ersetzen bestehenden Speicher nicht
  durch leeren Speicher.
- Moderne JSON-Indexschreibvorgaenge laufen ueber Flush, `fsync` und atomisches
  `os.replace`; temporaere Dateien werden bereinigt.
- Regressionen pruefen Byte-Erhalt bei Lese- und Replace-Fehlern.
- Angrenzende Suite zuletzt: `400 passed, 17 subtests passed`.

### Strukturiertes Account-Memory

- `append_structured_memory_entry()` stellt bei Indexfehlern vorherigen
  Entries-/Indexstand wieder her.
- `reset_structured_memory()` hat denselben Rollbackschutz.
- Fehlgeschlagene Rollbacks werden als eigene Inkonsistenzfehler gemeldet.
- Account-Store-Suite zuletzt: `202 passed in 7.02s`.
- Letzter Commit: `dfb99cb2 fix: rollback account memory resets`.

## Akzeptanzkriterien

- Kein geaenderter Pfad kann nach einem simulierten zweiten Schreibfehler
  einen stillen Teilzustand zuruecklassen.
- Erfolgreiche Append-, Reset-, Access- und Rebuild-Operationen behalten ihre
  bisherige Semantik.
- Alle neuen Fehlerfaelle sind mit kleinen providerfreien Regressionen
  abgesichert.
- Plan nennt exakt Commit, Testlauf und verbleibende offene Abnahme.
- Der Plan bleibt aktiv, bis die naechste Logikpruefung und ihre Tests fertig
  sind.

## Bezug

- Vorheriger Plan:
  `Baupläne/Bauplan-Aktueller-Plan-Logikpruefung-2026-07-15.md`
- Aktueller Arbeitsbaum: `/home/teladi/TeeBotus`

