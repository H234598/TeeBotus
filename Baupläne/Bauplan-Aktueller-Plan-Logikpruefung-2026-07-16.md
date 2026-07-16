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
  Restart sind aktuell `7/20` Commits vorhanden; naechster Restart nach 13
  weiteren Commits.

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
- `mark_structured_memory_accessed()` stellt bei Indexfehlern ebenfalls den
  vorherigen Entries-/Indexstand wieder her.
- `rebuild_structured_memory_index()` stellt bei Fehlern nach einer
  Normalisierung ebenfalls den vorherigen Entries-/Indexstand wieder her.
- Der laufende strukturierte Memorypfad akzeptiert keine Plaintext-
  `User_Memory_Index.json` oder `User_Memory_Entries.jsonl` mehr als stillen
  Fallback. Dedizierte Legacy-/SQL-Importer behalten ihren expliziten
  Plaintext-Migrationspfad.
- Fehlgeschlagene Rollbacks werden als eigene Inkonsistenzfehler gemeldet.
- Account-Store-Suite zuletzt: `203 passed in 9.57s`.
- Letzter Commit: `dfb99cb2 fix: rollback account memory resets`.

## Letzter Nachweis

- 2026-07-16: Eine Biene fand in `mark_structured_memory_accessed()` einen
  Teilfehler: Entries wurden vor dem Index geschrieben. Bei einem
  Indexfehler blieben `access_count` und `last_accessed_at` neu, waehrend
  `accessed_ids` und Index-Entries alt blieben.
- Der Zugriffspfad liest nun beide vorherigen Staende vor der Mutation und
  rollt Entries sowie Index bei jedem Schreibfehler zurueck. Ein fehlgeschla-
  gener Rollback wird als eigener Inkonsistenzfehler sichtbar.
- Regression fuer simulierten Index-Schreibfehler ergaenzt. Fokussiert:
  `2 passed, 201 deselected`; vollstaendig: `203 passed in 9.57s`.
- Naechster belegter Kandidat: `rebuild_structured_memory_index()` mit
-  derselben getrennten Entries-/Index-Schreibreihenfolge. Dieser Befund ist
  inzwischen behoben.
- 2026-07-16: Eine Biene bestaetigte den Rebuild-Teilfehler: normalisierte
  Entries wurden vor dem Index geschrieben. Ein Indexfehler konnte deshalb
  neue Rows mit altem Index hinterlassen.
- Der Rebuild sichert jetzt beide Staende vor der Normalisierung und rollt
  bei Fehlern Entries und Index zurueck. Regression fuer Indexfehler nach dem
  Entries-Write ergaenzt; fokussiert `5 passed`, vollstaendig `204 passed in
  7.85s`.
- Naechster offener Kandidat aus dem Bienen-Suchlauf: die getrennte
  Konsolidierung in `run_memory_maintenance()` ist bewusst tolerierter
  Teilfortschritt und braucht keinen Fix. Der Plaintext-Legacy-Fallback war
  dagegen ein echter Stale-/Secret-Fehlerpfad und ist behoben.
- 2026-07-16: Eine Biene reproduzierte, dass `_read_json*_with_fallback()` bei
  Klartextdateien einen Vault-/Secretfehler verdecken konnte. Structured
  Memory liest nun strikt verschluesselt; bei Klartext oder falschem Secret
  wird der Fehler sichtbar statt stale Daten zu liefern.
- Regression fuer Klartext-Index und Klartext-Entries ergaenzt. AccountStore-
  Suite: `205 passed in 6.40s`; Legacy-/SQL-Migrationssuiten: `49 passed`.
- 2026-07-16: Bienenbefund bei Identity-Link bestaetigt: Nach erfolgreichem
  Mapping-Write und fehlgeschlagenem Profil-Write blieb ein Retry auf
  `already_linked` stehen und reparierte das Profil nicht. Der bereits
  gemappte Pfad synchronisiert das Profil jetzt vor dem Return.
- `link_identity()` und `rotate_secret()` verwenden dieselbe Identity-Sperre;
  dadurch liegt Secret-Pruefung nicht mehr ausserhalb der Link-Serialisierung.
  Regression fokussiert `7 passed`; AccountStore-Suite danach `206 passed in
  9.55s`.
- 2026-07-16: Zwei Bienen bestaetigten den High-Priority-Befund bei
  `merge_accounts()`: ein Fehler nach Zielschreibungen konnte beim Retry
  doppelte Memories/Habit-Abschnitte erzeugen; ein Fehler nach Tombstone-Write
  konnte Cleanup blockieren.
- JSONL-Merge dedupliziert jetzt nach Memory-ID/identischem Payload, Habit-
  Merge prueft vorhandene Abschnitte, und ein Tombstone fuer dasselbe Ziel
  setzt Index-Entfernung und Quellverzeichnis-Cleanup fort. Retries bleiben
  dadurch sicher wiederholbar.
- Regressionen fuer Identity-Write-Fehler und fehlgeschlagenes Tombstone-
  Cleanup ergaenzt. Fokussiert `4 passed`; AccountStore-Suite `208 passed in
  7.37s`; Logik-Audit-Suite `10 passed`.
- Offener Bienenbefund: `unlink_identity()` hat weiterhin getrennte Profil-,
- Index- und Mapping-Writes. Eine Biene reproduzierte die drei Teilfehler;
  die bestehende Reihenfolge konvergiert beim Retry bereits sicher, daher kein
  Runtime-Fix noetig.
- Fault-Injection-Regression fuer Profil-, Index- und Mapping-Writefehler
  ergaenzt. Fokussiert `4 passed`; AccountStore-Suite danach `211 passed in
  10.18s`.
- 2026-07-16: Eine Biene reproduzierte eine inkonsistente Secret-Rotation:
  `Account_Secrets.json` wurde vor Verifier, Profil und Index geschrieben.
  Ein spaeter Fehler deaktivierte damit altes Secret trotz abgebrochener
  Rotation.
- Rotation schreibt Secrets erst nach den abhaengigen Metadaten und stellt bei
  jedem Fehler Secrets, Verifier, Profil und Index auf den vorherigen Stand
  zurueck. Ein fehlgeschlagener Rollback bleibt als eigener Fehler sichtbar.
  Regression fokussiert `3 passed`; AccountStore-Suite danach `212 passed in
  7.82s`.
- 2026-07-16: Eine Biene fand zwei Account-Erzeugungs-Teilfehler:
  `resolve_or_create_account()` konnte nach einem Mappingfehler ein
  verwaistes Profil hinterlassen und nach einem Indexfehler den fehlenden
  Index beim Retry nicht reparieren. `ensure_external_account()` gab bei
  vorhandenem Profil ohne Index zu frueh zurueck.
- Neue Accounts entfernen ihr Profil bei fehlgeschlagenem Identity-Write;
  bestehende Accounts und External-Accounts reparieren den Account-Index beim
  naechsten Retry. Regression fokussiert `3 passed`; AccountStore-Suite danach
  `215 passed in 9.60s`.
- 2026-07-16: Eine Biene reproduzierte einen weiteren Retry-Fehler in
  `clear_privacy_confirmation()`: Nach erfolgreichem Profil-Write und
  fehlgeschlagenem Index-Write war Privacy bereits geloescht, sodass der
  naechste Lauf den Index nicht mehr anfasste.
- Der Pfad upsertet den Account-Index jetzt auch ohne erneute Privacy-Aenderung.
  Regression fuer den einmaligen Indexfehler ergaenzt; fokussiert `2 passed`,
  AccountStore-Suite danach `216 passed in 14.67s`.
- Commit `ca101c09`; nach Commit 40 wurde die korrekte User-Unit
  `teebotus.service` erfolgreich neu gestartet. Status `active/running`, neue
  PID `4023650`, Start `2026-07-16 01:40:29 CEST`.
- 2026-07-16: Eine Biene reproduzierte einen Teilfehler bei
  Identity-Alias-Normalisierung: Profil wurde vor dem Identity-Write
  kanonisiert. Ein fehlgeschlagener Lookup konnte dadurch Mapping und Profil
  auseinanderziehen.
- Alias-Reparatur sichert jetzt Identity-Datei, Account-Index und betroffene
  Profile als Rohbytes und stellt sie bei Fehlern gemeinsam wieder her.
  Regression prueft unveraenderte Bytes; fokussiert `4 passed`,
  AccountStore-Suite danach `217 passed in 6.61s`.
- Offener naechster Auditpunkt bleibt die systematische Pruefung weiterer
  mehrteiliger Account-Metadatenwrites; bisher kein neuer belegter Befund.

### SQL-Fallback und Legacy-Migration

- 2026-07-16: Zwei Bienen bestaetigten, dass gueltige SQL-Rows mit
  `last_collection_read_error` oder `last_collection_skipped` vorher als
  Totalausfall behandelt wurden. Stale JSON konnte dadurch gueltige SQL-Daten
  ersetzen.
- JSON-Dokumente nutzen bei Partial-Reads direkt gueltige SQL-Rows. JSONL
  ergaenzt Legacy nur im Speicher. In beiden Faellen gibt es keinen
  destruktiven Write und keine Legacy-Loeschung bei laufender Diagnose.
- Saubere Migrationen pruefen den Readback exakt. Bei stillem Verlust oder
  erneutem Fehler bleibt Legacy erhalten. `read_llm_state()` entfernt bei
  unbestaetigter `LLM_State.json`-Migration auch `OpenAI_State.json` nicht.
- Commit `aa6663d9`; Fokus `29 passed`, AccountStore-Suite `224 passed in
  6.50s`, Ruff, `py_compile` und `git diff --check` gruen.
- Neuer fokussierter Bauplan:
  `Baupläne/Bauplan-SQL-Fallback-und-Migrationsschutz-2026-07-16.md`.

### Identity-Metadaten und Compound-Retry

- 2026-07-16: Eine Biene reproduzierte, dass `link_identity_to_account()`
  Identity-Map vor Profil/Index und `unlink_identity()` Profil/Index vor Map
  speichern konnte. Teilfehler liessen widerspruechliche Rohzustaende zurueck.
- Link/Unlink sichern `Account_Identities`, `Account_Index` und betroffene
  Profile als Rohbytes. Jeder Teilfehler stellt alle drei Dateien wieder her;
  fehlgeschlagener Restore bleibt sichtbar.
- `unlink_identity_and_rotate_secret()` prueft jetzt Zielaccount vor dem
  Unlink und stellt Metadaten wieder her, wenn Secret-Rotation fehlschlaegt.
- Fokustests: `32 passed`; AccountStore-Suite: `228 passed in 6.69s`;
  Ruff, `py_compile` und `git diff --check` gruen. Commit:
  `5770bf8f fix: rollback identity metadata updates`.

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
