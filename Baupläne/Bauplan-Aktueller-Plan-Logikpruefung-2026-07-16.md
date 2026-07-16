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
- Bot-/Service-Restart erst an der vereinbarten 20-Commit-Grenze. Seit dem
  letzten Restart ist aktuell `9/20` Commits vorhanden; naechster Restart
  nach 11 weiteren Commits.

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
   jedem Fix erstellen. Nicht pushen und nicht vor Commit 20 restarten.

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
- 2026-07-16: Merge-Retry-Nachaudit reproduzierte einen Restfehler fuer alte
  Source-Rows ohne `id`: Zielnormalisierung konnte die gleiche Source-Zeile
  beim Retry erneut einfuegen. `merge_accounts()` normalisiert die Quelle
  jetzt vor dem ersten Merge. Tombstone-Cleanup loescht ausserdem zuerst das
  Quellverzeichnis und entfernt den Source-Index erst danach; bei Cleanup-
  Fehler bleibt der Index sichtbar und der Retry eindeutig.
- Regression fuer Legacy-Row-Duplikation und Cleanup-Reihenfolge ergaenzt;
  fokussiert `4 passed`, AccountStore-Suite danach `231 passed in 6.97s`.
  Code-Commit: `5900f36c`.
- 2026-07-16: SQL-Repro zeigte einen groesseren Merge-Fehler: Bei aktivem
  SQLite/Postgres-Backend kopierte `merge_accounts()` nur JSON-Dateien.
  Strukturierte Source-Entries blieben dadurch unsichtbar im Ziel und wurden
  nicht geloescht. SQL-Entries und Access-Reihenfolge werden jetzt ins Ziel
  uebernommen; Source-Collections werden erst nach Ziel-/Identity-Write
  geleert. Tombstone-Retry wiederholt das Leeren idempotent.
- Regression fuer SQL-Merge und Source-Clear ergaenzt; fokussiert `5 passed`,
  AccountStore-Suite danach `232 passed in 10.51s`. Code-Commit: `a9393974`.
- 2026-07-16: Folgeaudit zeigte, dass derselbe SQL-Mergefehler auch
  `LLM_State`, Agent-State, Status-Auth sowie Proactive-, Status- und
  Codex-Collections betraf. Der SQL-Merge dedupliziert JSONL-Collections,
  waehlt den neuesten LLM-State, merged Dokumente und behandelt
  Status-Auth als monotones OR. Source-Clear folgt erst danach.
- SQLite-Regression deckt strukturierte Entries, drei Dokumente und mehrere
  Outbox-Collections ab; fokussiert `5 passed`, AccountStore-Suite `232 passed`.
  Ruff, `py_compile` und `git diff --check` gruen. Code-Commit: `50688e74`.
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

### LLM-State-SQL/JSON-Audit

- 2026-07-16: Biene Herschel meldete einen vorzeitigen SQL-Return in
  `read_llm_state()`. Providerfreier Repro bestaetigte den Fehler: Der
  Dokument-Helper konnte einen neueren Legacy-Stand als scheinbar bestaetigten
  SQL-State zurueckgeben; danach loeschte `read_llm_state()` die Datei ohne
  eigenen Read-back-Nachweis.
- Der LLM-Read trennt SQL-Read und Legacy-Read, waehlt den neuesten Stand,
  schreibt ihn direkt in SQL und loescht `LLM_State.json`/
  `OpenAI_State.json` erst nach exakt verifiziertem SQL-Read-back. Stille
  Read-back-Verluste lassen Legacy liegen und bleiben retrybar.
- Regression fuer neuere Datei gegen aelteren SQL-State sowie stille
  Read-back-Verluste ergaenzt. Fokussiert `8 passed`; AccountStore- und
  RuntimeState-Suiten `311 passed`; Ruff, `py_compile` und
  `git diff --check` gruen. Code-Commit: `b35f57a3`.

### Fallback-Reparatur nach Partial-Read

- 2026-07-16: Der Audit fand einen destruktiven Reparaturpfad in
  `WarningFallbackAccountMemoryBackend._read()`. Ein gezielter
  `read_entries_by_ids()`-Read konnte gueltige Rows liefern, waehrend der
  anschliessende vollstaendige Primary-Read nur einen Teilbestand plus
  Decrypt-/Skip-Diagnose lieferte. Dieser Teilbestand konnte den validen
  Fallback ueberschreiben.
- Die Reparatur prueft jetzt Exceptions und Read-Diagnosen des vollstaendigen
  Primary-Reads. Bei Partial-Read bleibt der Fallback unveraendert; Repair wird
  als stale/sync_failed markiert und erst nach sauberem Full-Read erneut
  versucht. Der bereits erfolgreich gelesene Teilrequest bleibt unveraendert.
- Regression fuer Partial-Full-Read: fokussiert `5 passed`; AccountStore-Suite
  `229 passed in 6.27s`; Ruff, `py_compile` und `git diff --check` gruen.
  Code-Commit: `d1f55162 fix: reject partial fallback repair reads`.
- 2026-07-16: Eine Biene fand einen Folgefehler: Nach fehlgeschlagener Primary-
  Reparatur wurde nur `stale`, nicht `sync_failed` gesetzt. Beim naechsten
  Primary-Ausfall konnte der veraltete Fallback dadurch wieder ausgeliefert
  werden.
- Der Reparaturfehler markiert jetzt `sync_failed`; Folgezugriff bleibt
  fail-closed, bis eine erfolgreiche Synchronisierung den Zustand bereinigt.
  Regression geaendert; fokussiert `5 passed`, AccountStore-Suite danach
  `229 passed in 7.75s`. Code-Commit: `0c1da884 fix: block stale fallback after repair failure`.

### RuntimeState-Reset-Retry

- 2026-07-16: Eine Biene fand drei zusammenhaengende Fehler in
  `RuntimeStateStore`: Ein Reset ueberschrieb einen bereits vorhandenen
  fehlgeschlagenen Set-Retry-Marker; Reset verglich bei gleicher Response-ID
  den Provider-/Model-Scope nicht; verwaiste Scope-Felder ohne Response-ID
  wurden beim Retry wegen Kurzschluss nicht geloescht.
- Retry-Marker enthalten jetzt Response-ID und Scope. Vorhandene Marker bleiben
  beim Reset erhalten. Nur derselbe persistierte ID-/Scope-Stand darf geloescht
  werden; gleiche ID mit neuem Scope bleibt erhalten. Expliziter Reset bereinigt
  auch verwaiste oder unvollstaendige Scope-Felder.
- Drei Regressionen ergaenzt; `tests/test_runtime_state.py`: `81 passed in
  1.14s`; Ruff und `py_compile` gruen. Commit:
  `4e4ffc5d fix: preserve response scope during reset retries`.

### Telegram-Offset und Dispatch-Journal

- 2026-07-16: Der Audit fand einen Ack-Reihenfolgefehler in `run_polling()`.
  Nach erfolgreicher Action-Ausfuehrung wurde der Update-Offset persistiert,
  danach konnte das Dispatch-Journal-Cleanup scheitern. Der Code liess dann
  den In-Memory-Offset alt und behandelte ein bereits bestaetigtes Update bei
  jedem Poll erneut. Bei dauerhaft defektem Journal konnte der Poller dadurch
  endlos am selben Update haengen.
- Nach erfolgreicher Offset-Persistenz gilt Update als bestaetigt. Ein
  fehlgeschlagenes Journal-Cleanup wird sichtbar geloggt, aber nicht mehr als
  retrybarer Updatefehler behandelt. At-least-once-Action-Recovery bleibt vor
  Offset-Persistenz unveraendert.
- Regression fuer Cleanup-Fehler ergaenzt. `tests/test_bot.py`: `199 passed,
  17 subtests passed in 3.65s`; Ruff, `py_compile` und `git diff --check`
  gruen. Commit: `7e9c73e2 fix: stop retrying acknowledged telegram updates`.

### Notification-Loudness-Outbox

- 2026-07-16: Der Audit fand einen Teilfehler bei
  `queue_due_notification_loudness_prompts()`: Outbox-Item wurde zuerst
  geschrieben, danach konnte `write_agent_state()` scheitern. Der persistierte
  Outbox-Eintrag schuetzte nur solange er `queued` war. Nach Versand fehlte der
  Wake-Window-Marker und derselbe Prompt konnte im selben Fenster erneut
  entstehen.
- Der Outbox-Zeitpunkt (`due_at`, danach Erstell-/Updatezeit) wird jetzt als
  Recovery-Marker fuer Route und Wake-Window geprueft. Das verhindert
  Duplikate auch nach State-Write-Teilfehlern, ohne Folgefenster zu blockieren.
- Regression fuer fehlgeschlagenen State-Write plus anschliessenden Versand:
  `tests/test_notification_loudness.py` `164 passed in 11.72s`; Ruff,
  `py_compile` und `git diff --check` gruen. Commit:
  `6a30a0f1 fix: recover loudness wake window from outbox`.

### Activity-Profile und Poller-Replay

- 2026-07-16: Der Audit fand einen At-least-once-Fehler im Aktivitaetsprofil.
  Telegram-, Signal- und Matrix-Events tragen stabile `event_id`s. Nach einem
  Poller-/Dispatch-Replay wurde dieselbe Nachricht erneut als Aktivitaet
  gespeichert und konnte Wach-/Ruhezeitprofile messbar verfaelschen.
- `record_account_activity()` speichert die `event_id` mit jeder neuen
  Beobachtung und ignoriert bereits vorhandene IDs im selben Profil. Alte
  Beobachtungen ohne ID bleiben lesbar; das Verhalten ist damit
  rueckwaertskompatibel.
- Replay-Regression ergaenzt. `tests/test_activity_profile.py`: `13 passed in
  0.80s`; `py_compile` und `git diff --check` gruen. Code-Commit:
  `be4ce9d9 fix: deduplicate replayed activity events`.
- Nach Plan-Commit `e884a09d` wurde der vereinbarte lokale Restart ausgefuehrt;
  `teebotus.service` ist `active`, MainPID `132170`, Start `2026-07-16
  03:14:52 CEST`.
- Folgeaudit: Telegram-`message_id`s sind nur innerhalb eines Chats eindeutig.
  Deduplizierung vergleicht jetzt `event_id` plus `route_key`, damit zwei
  verschiedene Chats derselben Accountgruppe nicht kollabieren.
- Regression fuer gleiche ID auf verschiedenen Routen ergaenzt.
  `tests/test_activity_profile.py`: `14 passed in 0.89s`; Ruff,
  `py_compile` und `git diff --check` gruen. Commit:
  `eb4f2475 fix: scope activity replay deduplication`.

### Healthcheck-/Applet-Datenvertrag

- 2026-07-16: Nachaudit der aktuellen Health-Klassifikation und des Cinnamon-
  Applets ausgefuehrt. Quell-Applet und installierte Kopie sind bytegleich;
  kein Installationsdrift.
- Kein neuer belegter Quellfehler: V2-Health-Validator, Qdrant-Ueberlappungs-
  zaehlung, informative Fallback-Zustaende und actionable Detailzeilen sind
  durch vorhandene Regressionen abgedeckt. `tests/test_cinnamon_applet.py`:
  `238 passed in 30.23s`.
- Kein Patch fuer eine unbelegte Anzeige erstellt. Seit dem Restart stehen
  `17/20` Commits an; kein weiterer Restart erforderlich.
- Live-Status danach ohne Provideraufruf reproduziert: Service
  `active/running`, Qdrant `2/2 ready`, `health=ok`,
  `total_problem_count=0`, `actionable_problem_count=0`. Die 20 gezählten
  Hinweise bleiben `informational_problem_count`; darunter bewusst aktive
  lokale Fallbacks und fehlende optionale Groq-/HF-Konfiguration. Kein neuer
  Health-Quellfehler belegt.

### Reminder-Intent und Werktags-Rekurrenz

- 2026-07-16: Der Audit reproduzierte einen stillen Semantikfehler:
  `jeden Werktag`, `jeden Wochentag` und englische `weekdays` wurden als
  einmalige Erinnerung fuer den naechsten Uhrzeitpunkt behandelt. Die
  Wiederholung ging verloren; Freitag konnte dadurch auf Samstag fallen.
- Der klassische Parser liefert jetzt `recurrence=weekdays`, verschiebt die
  erste Faelligkeit auf Montag bis Freitag und entfernt Wiederholungswoerter
  aus dem Betreff. Der Proactive-Dispatcher plant Folgefaelligkeiten ebenfalls
  ueber das Wochenende hinweg.
- Regressionen pruefen Freitag und Samstag als Startpunkt sowie Dispatcher-
  Fortschreibung. `tests/test_reminder_intent.py`: `24 passed`; komplette
  `tests/test_proactive_agent.py`: `117 passed in 2.51s`; Ruff, `py_compile`
  und `git diff --check` gruen. Commit:
  `bf603317 fix: preserve weekday reminder recurrence`.

### Wetterkontext und City-Memory

- 2026-07-16: Eine Biene bestaetigte den Ablauf `City-Memory schreiben ->
  Wetter-State schreiben` als Replay-Luecke. Fiel der State-Write nach dem
  Memory-Write aus, sah der Retry dieselbe Stadt erneut als neu. Der
  AccountStore vergab bei der bereits belegten Wunsch-ID eine neue ID; so
  entstanden doppelte Wohnort-Memories.
- `_append_city_memory()` prueft die deterministische `mem_residence_city_*`
  ID jetzt vor dem Append. Der Check laeuft unter dem Account-Memory-Lock und
  bleibt bei bestehenden Eintraegen idempotent.
- Regression fuer State-Write-Fehler nach erfolgreichem Memory-Append:
  `tests/test_weather_context.py`: `9 passed`; Ruff, `py_compile` und
  `git diff --check` gruen. Commit:
  `0a526527 fix: deduplicate residence city memories`.

### Runtime-Status-Dispatch und Audit-Write

- 2026-07-16: Der Audit fand einen Fehler nach externer Zustellung: Outbox
  stand bereits auf `sent`, aber ein fehlgeschlagener Write in
  `status_dispatch_results` liess `_record_runtime_status_dispatch()` eine
  Exception werfen. Dadurch konnte die Admin-Schleife nach bereits erfolgter
  Zustellung abbrechen und `sent` falsch als Fehler erscheinen.
- Outbox-Zustand bleibt jetzt massgeblich fuer die Zustellung. Ein fehlge-
  schlagener Audit-Write wird mit Account-/Item-Kontext geloggt und blockiert
  keine weiteren Empfaenger. Die fehlende Audit-Zeile bleibt dadurch sichtbar
  als Persistenzwarnung statt als falscher Versandfehler.
- Regression ohne Provider-Aufruf: `tests/test_runtime_admin_accounts.py`:
  `28 passed`; Ruff, `py_compile` und `git diff --check` gruen. Commit:
  `baa62d09 fix: keep status delivery visible when audit write fails`.

### Bienenkoordination

- Vorhandene Bienenberichte zu AccountStore, RuntimeState, Fallback,
  Telegram-Ack, Activity-Profil, Applet-Health und Reminder wurden jeweils
  gegen den aktuellen Quellstand geprueft und in diesem Plan verarbeitet.
- Zwei neue, disjunkte Explorationsauftraege fuer Wetter und Reminder konnten
  wegen voller Agentinnen-Threadgrenze nicht gestartet werden. Es wurde kein
  Delegationsresultat erfunden; der Wetterbefund wurde lokal reproduziert und
  abgesichert.

### MessageTracker-Persistenz

- 2026-07-16: Der Audit fand einen stale-read Fehler: Wenn die persistierte
  `Sent_Message_Refs.json` waehrend laufender Runtime geloescht oder unlesbar
  wurde, behielt `MessageTracker` seine alten In-Memory-Refs. Cleanup konnte
  dadurch veraltete Nachrichten-IDs weiterverwenden.
- Fehlende oder ungueltige Persistenz leert den Tracker jetzt fail-closed.
  Neue Refs koennen danach normal wieder aufgezeichnet werden; alte Refs
  werden nicht gegen aktuelle Chats eingesetzt.
- Providerfreie Regressionen fuer kaputtes File und verschwundenes Parent:
  `tests/test_message_tracking.py`: `8 passed`; Ruff, `py_compile` und
  `git diff --check` gruen. Commit:
  `4857c518 fix: clear stale message refs after storage loss`.

### Ausgeschriebene Reminder-Zeitangaben

- 2026-07-16: Der Reminder-Parser erkannte `in einer Stunde`, `in einer
  halben Stunde` und vergleichbare ausgeschriebene Intervalle als Anfrage,
  liess `due_at` aber leer und behielt die Zeitangabe im Betreff.
- Ein kleiner lokaler Parser deckt deutsche Zahlwoerter bis zehn sowie
  Minuten, Stunden, Tage, Wochen, Halb- und Viertelintervalle ab. Explizite
  Uhrzeiten bleiben bei Tages-/Wochenintervallen erhalten; Betreff wird von
  der Intervallphrase bereinigt.
- Regression: `tests/test_reminder_intent.py`: `25 passed`; zusaetzlicher
  Direktcheck fuer Stunde, halbe Stunde, Viertelstunde, fuenf Minuten und
  zwei Wochen. Ruff, `py_compile` und `git diff --check` gruen. Code-Commit:
  `630c5192 fix: parse written reminder intervals`.

### Proactive-Dispatch nach externer Zustellung

- 2026-07-16: Der Audit fand einen Post-Send-Fehler: Nach erfolgreicher
  externer Zustellung konnten Outbox-Statuswrite oder Message-Tracker-Write
  ungefangen den Dispatcher abbrechen. Die Nachricht war dann bereits beim
  Empfaenger, aber Runtime meldete keinen stabilen Versandabschluss.
- Statuspersistenzfehler werden jetzt pro Item abgefangen, mit Account-,
  Item-, Kanal- und Message-Referenz geloggt und als
  `status_update_failed` zur Dispatch-Result-Persistenz weitergereicht. Das
  Item bleibt `dispatching`; die vorhandene Lease-Recovery kann es spaeter
  erneut aufnehmen. Ein Trackerfehler downgradet ein bereits als `sent`
  markiertes Outbox-Item nicht.
- Regressionen fuer Outbox-Writefehler nach Sendererfolg und Trackerfehler
  ergaenzt. `tests/test_proactive_agent.py`: `119 passed`; CLI-Suite:
  `48 passed`; Ruff, `py_compile` und `git diff --check` gruen. Code-Commit:
  `d134d41d fix: preserve proactive delivery after post-send errors`.

### Dotenv-Aufloesung

- 2026-07-16: Der angrenzende Secret-/Konfigurationspfad wurde auf
  Prozesswert-Prioritaet, verschachtelte `instances`-Pfade und den optionalen
  Fallback-Parser geprueft. Kein neuer reproduzierbarer Ladefehler.
- Prozesswerte bleiben vor `.env`-Defaults; fehlende Dateien veraendern die
  Umgebung nicht; `export`, Quotes und Inline-Kommentare sind abgesichert.
  `tests/test_runtime_dotenv.py`: `7 passed`; Ruff gruen. Kein Runtime-Patch.

### Telegram-Offset und Dispatch-Journal-Nachaudit

- 2026-07-16: Offset wird erst nach erfolgreicher Updateverarbeitung und
  erfolgreichem Offset-Write im Speicher weitergeschoben. Bei Handler- oder
  Offsetfehler bleibt Update retrybar; nach Offset-Erfolg blockiert ein
  Journal-Cleanupfehler die Bestaetigung nicht erneut.
- Die bestehende Journal-Recovery verhindert bei erneuter Zustellung doppelte
  Aktionen; Cleanup bleibt bei Fehler sichtbar pending. Kein neuer
  reproduzierbarer Replay- oder Ack-Reihenfolgefehler.
- Vorhandene Regressionen in `tests/test_bot.py` decken diese Pfade ab;
  kein Runtime-Patch.

### Working-Memory-Instanzscope

- 2026-07-16: Die Bienenpruefung fand zwei nahezu gleiche
  Working-Memory-Implementierungen: `runtime/working_memory.py` und den
  Telegram-Kompatibilitaetspfad. Beide akzeptierten bisher einen bereits
  gesetzten, fremden `instance_name` aus einer kopierten oder alten
  Indexdatei.
- Das ist ein Scope-Fehler: Datei liegt zwar unter aktueller Instanz, der
  Prompt konnte aber fremde Instanzmetadaten ausgeben. Normalisierung setzt
  `instance_name` jetzt immer auf aktuelle Store-Instanz; beide Pfade bleiben
  verhaltensgleich.
- Regression fuer beide `WorkingMemoryStore`-Klassen: `tests/test_working_memory.py`:
  `8 passed`; Ruff, `py_compile` und `git diff --check` gruen.
- Code-Commit: `15d3e0e0 fix: enforce working memory instance scope`; kein
  Provider/API-Aufruf.

### Restart-Checkpoint

- Providerfreie Nachweise dieses Auditblocks: Reminder `25 passed`,
  Proactive-Agent `119 passed`, Proactive-CLI `48 passed`, Cinnamon-Applet
  `238 passed`, Dotenv `7 passed`; Ruff, `py_compile` und
  `git diff --check` gruen.
- Codeaenderungen sind committed. Untracked Obsidian-/Arbeitsdateien bleiben
  unangetastet. Nach lokalem Restart Status erneut auf `active/running` und
  Health-Daten pruefen.
- Restart ausgefuehrt: `teebotus.service` `active/running`, PID `247193`,
  Start `2026-07-16 03:49:25 CEST`, Runtime-Version `1.9.498`. Erste
  unmittelbare Probe sah Signal noch waehrend Autostart als `unreachable`;
  Folgeprobe nach Bereitschaft meldete Signal `2/2 reachable`,
  `health=ok`, `actionable_problem_count=0`. Das ist ein bestaetigter
  transienter Startzustand, kein dauerhafter Health-Fehler.

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

**Laufstand:** Seit dem letzten Restart `11/20` Commits; Restart erledigt,
kein Push ausgeloest. Naechster Restart nach 9 weiteren Commits.

## Bezug

- Vorheriger Plan:
  `Baupläne/Bauplan-Aktueller-Plan-Logikpruefung-2026-07-15.md`
- Aktueller Arbeitsbaum: `/home/teladi/TeeBotus`
