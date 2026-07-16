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
- Bot-/Service-Restart erst an der vereinbarten 20-Commit-Grenze. Nach dem
  letzten Restart sind aktuell `2/20` Commits vorhanden; naechster Restart
  nach 18 weiteren Commits.

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

### Cross-Instance-External-Links

- 2026-07-16: `ensure_external_account()` kehrte bei bestehendem Profil zu
  frueh zurueck. Wenn derselbe Account aus mehreren Quellinstanzen bekannt
  wurde, blieb nur der erste `external_link` erhalten.
- Der Pfad serialisiert jetzt ueber die Identity-Sperre, fuegt neue
  `(source_instance, source_account_id)`-Paare dedupliziert an und schreibt
  Profil/Account-Index mit gemeinsamem Rollback. Wiederholungen bleiben
  idempotent.
- Auch die Erstanlage schreibt Profil und Account-Index transaktional:
  scheitert der Index, werden beide Metadaten zurueckgesetzt. Ein dabei neu
  entstandenes leeres Account-Verzeichnis wird entfernt; vorhandene Dateien
  bleiben unangetastet.
- Regressionen fuer zwei Quellen, Duplikat und Indexfehler ergaenzt;
  fokussiert `18 passed`, vollstaendig `234 passed`; Ruff, `py_compile` und
  `git diff --check` gruen.
- Code-Commits: `004293e8 fix: preserve external account source links`,
  `8bb48c2e fix: roll back external account creation`; kein Provider/API-
  Aufruf.

### Account-Creation-Rollback

- 2026-07-16: `resolve_or_create_account()` schrieb das Profil und die
  Identity-Map, bevor der Account-Index geschrieben wurde. Ein Indexfehler
  liess deshalb einen halb angelegten Account zurueck; der naechste Aufruf
  reparierte ihn nur zufaellig.
- Profil, Identity-Map und Index werden bei Erstanlage jetzt gemeinsam
  gesichert und bei jedem Teilfehler zurueckgesetzt. Der gemeinsame
  Rollback-Helfer entfernt danach nur ein leeres, neu entstandenes
  Account-Verzeichnis. Vorhandene Dateien bleiben unangetastet.
- Regression prueft Indexfehler auf komplett fehlenden Account und saubere
  Neuanlage beim Retry; fokussiert `18 passed`, vollstaendig `234 passed`;
  Ruff, `py_compile` und `git diff --check` gruen.
- Code-Commit: `4d5f7976 fix: roll back account creation metadata`; kein
  Provider/API-Aufruf.

### Privacy-Metadata-Rollback

- 2026-07-16: `confirm_privacy()` und `clear_privacy_confirmation()` schrieben
  Profil und Account-Index ohne gemeinsamen Fehlerpfad. Ein Indexfehler
  konnte bestaetigten Datenschutzstatus und Index auseinanderziehen.
- Beide Methoden laufen jetzt unter dem Identity-Lock und sichern Profil,
  Identity-Map sowie Index vor der Mutation. Bei Teilfehlern wird der alte
  Byte-Stand wiederhergestellt; Restore-Fehler bleiben sichtbar.
- Regressionen fuer Bestaetigung und Loeschung pruefen bytegleiche
  Wiederherstellung und erfolgreichen Retry; fokussiert `21 passed`,
  vollstaendig `235 passed`; Ruff, `py_compile` und `git diff --check` gruen.
- Code-Commit: `dbc93f34 fix: roll back privacy metadata updates`; kein
  Provider/API-Aufruf.

### Full-Memory-Reset-Rollback

- 2026-07-16: `reset_structured_memory()` schrieb Entries und leeren Index
  zuerst und loeschte Datenschutzbestaetigung erst danach. Ein Fehler beim
  zweiten Schritt konnte leeres Memory mit weiterhin bestaetigtem Datenschutz
  hinterlassen.
- Reset haelt jetzt Identity- und Account-Memory-Lock in konsistenter
  Reihenfolge, schreibt beide Memory-Dateien und Datenschutzstatus innerhalb
  eines gemeinsamen Fehlerpfads und stellt bei jedem Teilfehler alle alten
  Staende wieder her.
- Regression prueft Fehler beim Datenschutz-Indexschreiben bytegleich fuer
  Entries, Memory-Index, Profil und Account-Index; fokussiert `6 passed`,
  vollstaendig `236 passed`; Ruff, `py_compile` und `git diff --check` gruen.
- Code-Commit: `89e7c265 fix: roll back full memory reset`; kein
  Provider/API-Aufruf.

### Account-Merge-Locking

- 2026-07-16: `merge_accounts()` hielt nur die Identity-Sperre. Source- und
  Target-Memory konnten waehrend des Read-Merge-Write parallel beschrieben
  werden; besonders der JSON-Pfad schrieb Merge-Dateien ohne eigenen
  Ziel-Lock.
- Merge sperrt Source und Target jetzt in sortierter Reihenfolge unterhalb
  des Identity-Locks. Gleiche Account-Locks bleiben reentrant fuer die
  bestehenden Memory-Helfer; Lock-Order bleibt `Identity -> Memory`.
- Thread-Regression haelt Merge waehrend der Zwischenphase an und bestaetigt,
  dass Target-Append blockiert und danach beide Entries erhalten bleiben;
  Merge-Suite `5 passed`, vollstaendig `237 passed`; Ruff, `py_compile` und
  `git diff --check` gruen.
- Code-Commit: `dba4db7d fix: serialize account merges`; kein
  Provider/API-Aufruf.

### Profile-Identity-List-Validation

- 2026-07-16: `linked_identities` wurde in Profil-Mutationspfaden als
  beliebiger iterierbarer Wert behandelt. Ein korruptes Stringfeld konnte
  dadurch als Zeichenliste oder falscher Index-Count weitergeschrieben
  werden.
- `_profile_linked_identities()` akzeptiert jetzt nur eine Stringliste und
  wird vor Index-, Link-, Unlink- und Merge-Profilmutationen verwendet.
  Korruption wird sichtbar abgelehnt; kein stilles Normalisieren oder
  Datenverlust.
- Regression prueft korruptes Stringfeld auf unveraenderten Profil- und
  Index-Stand; fokussiert `10 passed`, vollstaendig `238 passed`; Ruff,
  `py_compile` und `git diff --check` gruen.
- Code-Commit: `91accd50 fix: validate account identity lists`; kein
  Provider/API-Aufruf.

### Account-Text-und-Agent-State-Locks

- 2026-07-16: Gewohnheitstext sowie `Agent_State` wurden ohne
  Account-Memory-Lock gelesen/geschrieben. Merge oder parallele Agent-
  Updates konnten dadurch Read-Modify-Write-Staende ueberholen.
- `read_account_text()`/`write_account_text()` sowie
  `read_agent_state()`/`write_agent_state()` verwenden jetzt denselben
  reentranten Account-Memory-Lock wie strukturierte Memorys und `LLM_State`.
- Fokustests fuer Gewohnheiten, Agent-State und Merge: `5 passed`; komplette
  AccountStore-Suite: `238 passed`; Ruff, `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commits: `c9e0b860 fix: lock account text memory`,
  `73ca3a41 fix: lock agent state memory`.

### JSON-Account-Collection-Merge

- 2026-07-16: Im JSON-Fallback von `merge_accounts()` wurden nur
  User-Memory, Profil, Habits und LLM-State uebernommen. Outbox-/Dispatch-
  Dateien, Codex-Projekte, Agent-State und Status-Auth wurden beim
  anschliessenden Source-Cleanup geloescht.
- JSON-Merge uebernimmt jetzt alle acht JSONL-Kollektionen sowie Agent-State
  und Status-Auth. Verschachtelte Dokumente werden wie im SQL-Pfad rekursiv
  zusammengefuehrt; `authorized` bleibt logisch OR.
- Regression deckt alle Kollektionen und Source-Cleanup ab; Merge-Suite
  `6 passed`, vollstaendig `239 passed`; Ruff, `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `96123b26 fix: merge json account collections`.

### Account-Collection-Locks-und-Event-Deduplizierung

- 2026-07-16: JSON-Merge hielt den Account-Memory-Lock, waehrend direkte
  Outbox-/Status-/Codex-Store-Zugriffe ihn umgehen konnten. Parallel laufende
  Dispatch- oder Review-Read-Modify-Write-Pfade konnten Merge-Daten
  ueberschreiben.
- Lesen/Schreiben aller Account-Kollektionen nimmt jetzt den gemeinsamen
  Account-Memory-Lock. Bestehende dedizierte Outbox-Locks bleiben erhalten;
  verschachtelte Nutzung ist reentrant.
- Breiter providerfreier Lauf: Proactive-/Notification-/Codex-Suiten
  `460 passed`; AccountStore `239 passed`; Ruff, `py_compile` und
  `git diff --check` gruen.
- Dabei wurde ein fehlerhafter Testdatensatz korrigiert: sechs historische
  Aktivitaetsereignisse hatten dieselbe `event_id` und wurden deshalb korrekt
  dedupliziert. Produktions-Deduplizierung unveraendert.
- Code-Commit: `c4d0fa3c fix: serialize account collection access`; kein
  Provider/API-Aufruf.

### Instance-State-Locks-und-Fallback-Reparatur

- 2026-07-16: `Version_Notifications` wurde ueber dieselbe SQL/JSON-
  Account-Memory-Infrastruktur gelesen und geschrieben wie Accountdaten,
  aber ohne den gemeinsamen Instance-State-Lock. Parallele Versions-
  Benachrichtigungen konnten dadurch Read-Modify-Write-Staende ueberholen.
- `read_instance_json_state()` und `write_instance_json_state()` verwenden
  jetzt den reentranten Lock des reservierten Instance-State-Accounts.
- Ein zusaetzlicher Recovery-Bug wurde behoben: Verifizierte Fallback-Daten
  durften eine korrupt gewordene Zielpartition nicht reparieren, weil der
  Destructive-Write-Guard genau diese kaputte Partition mitpruefte. Nur die
  explizit reparierte Entries-, Index- oder Collection-Partition wird beim
  Fallback-Recovery uebersprungen; alle anderen Payloads bleiben geschuetzt.
- Regressionen: Version-Notifications `215 passed`, AccountStore `239
  passed`, Proactive-/Notification-/Codex-Suiten `460 passed`; Ruff,
  `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `93511ccf fix: serialize and repair instance state`.

### Account-Registration-Lock

- 2026-07-16: `register_account()` las den Secret-Zustand vor dem
  Identity-Lock und delegierte erst danach an `rotate_secret()`. Parallele
  Registrierungen konnten beide die Vorpruefung als "kein aktives Secret"
  sehen und danach unerwartet nacheinander Secrets rotieren.
- Der Identity-Lock umfasst jetzt Vorpruefung und Rotation. Der innere
  `rotate_secret()`-Lock bleibt reentrant; direkte Rotationen behalten ihre
  bisherige Semantik.
- Regression prueft, dass Rotation erst innerhalb des gehaltenen Locks
  aufgerufen wird; fokussiert `2 passed`, AccountStore komplett `240 passed`.
  Ruff, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e8e7bde7 fix: serialize account registration`.

### Account-Memory-Read-Locks

- 2026-07-16: Drei direkte User-Memory-Reads (`read_memory_index()`,
  `read_memory_entries()` und `read_memory_entries_by_ids()`) umgingen den
  Account-Memory-Lock. SQL-/Fallback-Diagnosen und JSON-Datei-Reads konnten
  dadurch parallel zu Writes oder Repairs laufen.
- Alle drei Reads verwenden jetzt denselben reentranten Lock wie die
  Schreib- und Read-Modify-Write-Pfade. Der lockfreie Backend-Read ist damit
  auch fuer den JSON-Fallback ausgeschlossen.
- Regression prueft Lock-Haltung waehrend aller drei Backend-Reads;
  fokussiert `2 passed`, AccountStore komplett `241 passed`. Ruff,
  `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `dd8a336a fix: serialize account memory reads`.

### Identity-Secret-Transaction-Lock

- 2026-07-16: `unlink_identity_and_rotate_secret()` hielt den
  Identity-Lock nur indirekt, jeweils separat in Unlink und Secret-Rotation.
  Ein paralleler Identity-Write konnte zwischen beiden Schritten eintreten;
  ein fehlgeschlagenes Rotations-Rollback haette diesen Zwischenstand
  ueberschreiben koennen.
- Der Gesamtpfad verwendet jetzt einen reentranten Identity-Lock. Die
  bestehenden Unterpfade bleiben einzeln geschuetzt und koennen innerhalb
  dieses Locks weiterlaufen.
- Regression prueft Lock-Haltung waehrend Unlink und Rotation sowie den
  bestehenden Rollbackfall; fokussiert `2 passed`, AccountStore komplett
  `242 passed`. Ruff, `py_compile` und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `c51babf0 fix: serialize identity secret rotation`.

### Account-Summary-Snapshot-Lock

- 2026-07-16: `account_summary()` las Profil, Secret-Map und aktive
  Identitaeten ohne gemeinsamen Identity-Lock. Waehrend einer Secret-Rotation
  konnte der Status deshalb voruebergehend `registered=true` mit
  `secret_exists=false` oder einem alten Identity-Bestand kombinieren.
- Der Status-Snapshot verwendet jetzt den reentranten Identity-Lock. Der
  bereits geschuetzte Read der aktiven Identitaeten bleibt kompatibel.
- Regression prueft Profile-Read unter gehaltenem Lock; fokussiert `2
  passed`, AccountStore komplett `243 passed`. Ruff, `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `669baaf9 fix: serialize account summaries`.

### Memory-Retrieval-Snapshot-Lock

- 2026-07-16: `rank_structured_memory_ids()`,
  `select_structured_memory()` und `select_structured_memory_by_ids()` lasen
  Entries und Index ohne gemeinsamen Account-Memory-Lock. Parallel laufende
  Append-/Rebuild-Pfade konnten dadurch gemischte Staende ranken; Selection
  konnte anschliessend einen nicht mehr passenden Stand als gelesen markieren.
- Alle drei Retrieval-Einstiege verwenden jetzt denselben reentranten Lock.
  Verschachtelte Reads, Habit-Reads und Access-Updates bleiben kompatibel.
- Regression prueft Lock-Haltung waehrend aller drei Retrieval-Pfade;
  fokussiert `1 passed`, AccountStore komplett `244 passed`. Ruff,
  `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a26c5d44 fix: serialize memory retrieval`.

### Auth-und-Privacy-Read-Locks

- 2026-07-16: `verify_secret()` und `has_privacy_confirmation()` lasen
  Secret- bzw. Profil-Metadata ohne den Identity-Lock, waehrend Rotation,
  Bestaetigung oder Reset dieselben Dateien schrieben. Einzelne atomare Reads
  waren zwar lesbar, aber Auth- und Privacy-Entscheidungen konnten einen
  Zwischenstand sehen.
- Beide Reads verwenden jetzt den reentranten Identity-Lock. Damit bleiben
  Secret-Pruefung und Privacy-Entscheidung gegen laufende Metadata-Writes
  linearisiert.
- Regression prueft beide Reads unter gehaltenem Lock; fokussiert `2
  passed`, AccountStore komplett `245 passed`. Ruff, `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `12d05cce fix: serialize auth and privacy reads`.

### Version-Notification-Backend-Lock

- 2026-07-16: Zwei Hilfsfunktionen in `core/version_notifications.py` lasen
  bzw. loeschten `version_notifications` direkt ueber
  `account_memory_backend`. Sie umgingen damit den neuen Instance-State-Lock
  von `AccountStore.read_instance_json_state()` und
  `write_instance_json_state()`.
- Read- und Clear-Helfer nehmen jetzt denselben reservierten
  Instance-State-Lock. Fehlende Lock-Unterstuetzung bei kleinen Test-/Fake-
  Stores bleibt ueber `nullcontext()` kompatibel.
- Regression prueft beide direkten Helfer unter gehaltenem Lock; fokussiert
  `1 passed`, Version-Notifications komplett `216 passed`. Ruff,
  `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `62d73474 fix: lock version notification state`.

### Account-Memory-Backend-Lazy-Init

- 2026-07-16: `account_memory_backend` wurde bei parallelem Erstzugriff
  ohne Initialisierungs-Lock erzeugt. Mehrere Threads konnten getrennte
  SQLite-/Fallback-/Postgres-Objekte bauen; zuletzt zugewiesenes Objekt
  konnte den Zustand des anderen verlieren.
- Backend-Erzeugung liegt jetzt in `_create_account_memory_backend()` und
  wird per globalem reentrantem Lock mit Double-Check einmalig installiert.
  Bereits injizierte Test-/Spezial-Backends bleiben unangetastet.
- Regression prueft Konstruktion innerhalb des Locks und genau einen
  Factory-Aufruf; fokussiert `2 passed`, AccountStore komplett `246 passed`.
  Ruff, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `46558ca2 fix: serialize memory backend initialization`.

### Version-Notification-Identity-Lock

- 2026-07-16: Notification-Matching und `recent_telegram_recipients()`
  lasen die verschluesselte Identity-Map direkt ueber `_load_identities()`.
  Parallel laufende Route-/Identity-Aenderungen konnten dadurch einen
  veralteten oder gemischten Empfaenger-Snapshot erzeugen.
- Beide Pfade verwenden jetzt einen gemeinsamen lockenden Identity-Map-
  Helper. Verarbeitung und Versand bleiben ausserhalb des Locks; nur der
  konsistente Snapshot ist geschuetzt.
- Regression prueft Identity-Read unter gehaltenem Lock; fokussiert `2
  passed`, Version-Notifications komplett `217 passed`. Ruff,
  `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `95d1a5d7 fix: lock version notification identities`.

### Account-Listing-Identity-Lock

- 2026-07-16: `list_account_ids()` und
  `list_identities_for_account()` lasen Account-/Identity-Metadata ohne
  aeusseren Identity-Lock. Status- und Routing-Aufrufer konnten dadurch
  waehrend Account-Erstellung, Merge oder Tombstoning einen halben Snapshot
  sehen.
- Beide Listing-Pfade halten jetzt den reentranten Identity-Lock ueber
  Validierung und Ausgabe. Unterliegende aktive-Identity-Reads bleiben
  kompatibel.
- Regression prueft Index- und Profil-Read unter gehaltenem Lock; fokussiert
  `2 passed`, AccountStore komplett `247 passed`. Ruff, `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `64b00d15 fix: serialize account listing reads`.

### Status-Memory-Size-Snapshot

- 2026-07-16: `account_memory_payload_size()` las Entries und Index in zwei
  getrennten Reads. Parallel laufende Memory-Writes oder Rebuilds konnten
  dadurch fuer `/status` einen gemischten Payload-Snapshot liefern.
- Entries- und Index-Read laufen jetzt unter demselben reentranten
  Account-Memory-Lock. Backend-Diagnose und Serialisierung bleiben innerhalb
  desselben Snapshots; der Legacy-Dateifallback bleibt unveraendert.
- Regression prueft beide Reads unter gehaltenem Lock; fokussiert `2 passed`.
  Komplette `tests/test_engine_identity_flows.py`: `184 passed`. Ruff,
  `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a3a211e4 fix: serialize status memory size snapshot`.

### Outbox-Append-Snapshot-Locks

- 2026-07-16: Die sieben `append_*`-Methoden fuer Proactive-, Status- und
  Codex-History-Outbox hielten bisher Spezial-Lock, aber den
  Account-Memory-Lock nur waehrend einzelner Read-/Write-Aufrufe. Ein
  paralleler Read-Modify-Write-Aufrufer konnte dadurch zwischen Read und
  Write eintreten und einen Append verlieren.
- Jeder Append haelt jetzt Spezial-Lock und Account-Memory-Lock gemeinsam
  ueber den gesamten Read-Modify-Write-Abschnitt. Lock-Reihenfolge bleibt
  `Spezial-Lock -> Account-Memory-Lock`, damit bestehende Aufrufer wie
  Notification-Loudness nicht invertiert werden.
- Deterministische Regression blockiert den ersten Append-Read und prueft,
  dass ein paralleler direkter Read-Modify-Write wartet und danach alle drei
  Eintraege erhalten bleiben; fokussiert `2 passed`. AccountStore komplett
  `248 passed`. Ruff, `py_compile` und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `e41c2597 fix: serialize outbox append snapshots`.

### Fallback-Diagnose-Snapshot-Lock

- 2026-07-16: Biene Sartre fand einen echten Cross-Account-Race. SQLite und
  PostgreSQL liefern Read-Diagnosen ueber mutable `last_*`-Felder. Zwischen
  Primary-Callback und `_copy_diagnostics()` konnte ein sauberer Read von
  Account B die Partial-/Decrypt-Diagnose von Account A loeschen. A bekam
  dann Teilbestand statt Fallback-Daten.
- `WarningFallbackAccountMemoryBackend` haelt jetzt einen pro Wrapper
  reentranten Operation-Lock ueber Callback, Diagnose-Capture,
  Failover-Entscheidung und Reparatur. Direkte Collection-Name-Reads,
  `read_entries_by_ids()` inklusive leerem Request und Account-Clear sind
  ebenfalls geschuetzt. Der Lock serialisiert Fallback-Operationen innerhalb
  eines Prozesses; dadurch bleibt die bestehende Backend-Schnittstelle fuer
  SQLite und PostgreSQL unveraendert.
- Deterministische Race-Regression prueft, dass Account B waehrend eines
  blockierten Partial-Reads von A nicht dazwischenkommt und A beide
  Fallback-Entries zurueckgibt. Fokussiert `1 passed`; AccountStore komplett
  `249 passed`. Ruff, `py_compile` und `git diff --check` gruen. Kein
  Provider/API-Aufruf. Kein separates `tests/test_memory_fallback.py`
  vorhanden.
- Code-Commit: `cee5b3b1 fix: serialize fallback diagnostic capture`.

### Fallback-Health-Snapshot

- 2026-07-16: `/status` las stale Entries, Index, Collections und den
  Fehlertext einzeln. Eine parallele Fallback-Reparatur konnte daraus einen
  gemischten Warnzustand erzeugen oder waehrend einer Dict-Iteration einen
  `RuntimeError` ausloesen.
- Der Fallback-Wrapper liefert jetzt einen atomaren
  `fallback_diagnostics_for_account()`-Snapshot unter demselben reentranten
  Operation-Lock. `/status` verwendet ihn, wenn vorhanden; einfache Fake- oder
  Fremd-Backends behalten den bisherigen Kompatibilitaetspfad.
- Regression prueft, dass `/status` den Snapshot statt ungeschuetzter Einzel-
  Reader nutzt. Status-/Engine-Suite `185 passed`, AccountStore komplett
  `249 passed`, Fallback-Teilmenge `60 passed`; Ruff, `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `5db8d63a fix: snapshot fallback health diagnostics`.

### Collection-Name-Fail-Closed

- 2026-07-16: `read_collection_names()` gab bei einem fehlerhaften Primary
  und fehlender Secondary `()` zurueck, obwohl die Primary-Datenbank existiert.
  Aufrufer konnten dadurch „keine Collections“ annehmen und Memory-/State-
  Daten ueberspringen.
- Wenn beide Datenbanken wirklich uninitialisiert sind, bleibt leerer Start
  erlaubt. Wenn Primary existiert, Secondary aber fehlt, wirft der Pfad jetzt
  einen sichtbaren `AccountStoreError`; kein stiller leerer Snapshot.
- Regression fuer fehlende Secondary bei vorhandener Primary sowie bestehende
  Collection-Name-Reparatur: fokussiert `4 passed`, AccountStore komplett
  `250 passed`. Ruff, `py_compile` und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `e218298f fix: block unsafe collection name failover`.

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

### Working-Memory-Korruptionsschutz

- 2026-07-16: Beim Lesen eines indexierten JSONL-Eintrags wurde
  `UnicodeDecodeError` nicht abgefangen. Ein einzelnes ungueltiges Byte konnte
  dadurch den kompletten Working-Memory-Promptpfad abbrechen.
- Beide Implementierungen behandeln den Eintrag jetzt wie andere korrupte
  Entries: loggen, Entry ueberspringen, keinen Prompt erzwingen. Die
  Indexdatei und Rohdaten bleiben zur Diagnose erhalten.
- Regression fuer beide `WorkingMemoryStore`-Klassen: `tests/test_working_memory.py`:
  `10 passed`; Ruff, `py_compile` und `git diff --check` gruen.
- Code-Commit: `d474c0b7 fix: tolerate corrupt working memory entries`; kein
  Provider/API-Aufruf.

### Working-Memory-Ranking-Drift

- 2026-07-16: Vergleich beider Working-Memory-Pfade zeigte echte
  Verhaltensdrift. Moderne Runtime fuegte nach Keyword-Treffern aktuelle
  `recent_ids` an; Telegram-Kompatibilitaet liess sie weg.
- Telegram-Pfad nutzt jetzt dieselbe Reihenfolge: Keyword-Relevanz zuerst,
  danach aktuelle Eintraege ohne Duplikate. Damit bleibt gewuenschte
  `Ranking + Recent`-Semantik erhalten.
- Regression parametrisiert ueber beide Store-Klassen: Working-Memory `11
  passed`, Telegram-Working-Memory `4 passed`; Ruff, `py_compile` und
  `git diff --check` gruen.
- Code-Commit: `f40fc1c1 fix: preserve recent working memory ranking`; kein
  Provider/API-Aufruf.

### Working-Memory-Index-Typfehler

- 2026-07-16: Ein syntaktisch gueltiges JSON-Array oder anderer Nicht-Objekt-
  Top-Level wurde bisher still als leerer Working-Memory-Index ersetzt. Der
  alte Inhalt war danach ohne Backup verloren.
- Beide Pfade verschieben solche Dateien jetzt zuerst nach
  `Working_Memorys.json.corrupt.*`, loggen den Reset und schreiben erst dann
  einen neuen Objektindex.
- Regression fuer beide Store-Klassen: `tests/test_working_memory.py`:
  `13 passed`; Telegram-Working-Memory `4 passed`; Ruff, `py_compile` und
  `git diff --check` gruen.
- Code-Commit: `a4d26531 fix: preserve malformed working memory indexes`; kein
  Provider/API-Aufruf.

### Working-Memory-Index-Teilstruktur

- 2026-07-16: Gueltiges JSON mit falscher Index-Teilstruktur wurde bisher
  ebenfalls still repariert. `keywords`, `recent_ids` oder `entries` mit
  falschem Typ konnten dadurch den bisherigen Indexinhalt verlieren.
- Vor Normalisierung pruefen beide Pfade jetzt vorhandene Teilstrukturen.
  Falsche Typen werden wie Korruption nach
  `Working_Memorys.json.corrupt.*` verschoben; fehlende optionale Felder
  bleiben normalisierbar.
- Regression fuer Array-Index sowie alle drei falschen Teilstrukturtypen,
  jeweils in beiden Store-Klassen: `tests/test_working_memory.py`:
  `21 passed`; Telegram-Working-Memory `4 passed`; Ruff, `py_compile` und
  `git diff --check` gruen.
- Code-Commit: `1f9add4c fix: quarantine malformed working memory indexes`;
  kein Provider/API-Aufruf.

### Working-Memory-Append-Rollback

- 2026-07-16: `append_manual()` schrieb Entry-JSONL vor dem atomaren
  Index-Write. Bei einem Indexfehler blieb ein verwaistes JSONL-Entry hinter
  dem alten Index liegen und wuchs bei jedem Retry weiter.
- Der alte JSONL-Dateioffset wird jetzt gesichert. Scheitert Entry-Write oder
  Index-Write, wird auf diesen Offset zurueckgesetzt; scheitert auch der
  Rollback, bleibt der Fehler sichtbar geloggt.
- Regression fuer beide Store-Klassen prueft unveraenderten Index und leere
  JSONL-Datei nach simuliertem Indexfehler: `tests/test_working_memory.py`:
  `23 passed`; Telegram-Working-Memory `4 passed`; Ruff, `py_compile` und
  `git diff --check` gruen.
- Code-Commit: `2f4b1813 fix: roll back working memory append failures`; kein
  Provider/API-Aufruf.

### Working-Memory-Parallelzugriff

- 2026-07-16: Zwei Runner-Store-Objekte fuer dieselbe Instanz hatten bisher
  je einen eigenen `threading.Lock`. Paralleltests meldeten 100 erfolgreiche
  Appends, im Index blieben aber nur 51 Entries.
- Locks werden jetzt pro kanonischem Working-Memory-Pfad prozessweit geteilt.
  Telegram-, Signal- und Matrix-Store-Objekte serialisieren dadurch ihre
  gemeinsamen Index-/JSONL-Schreibvorgaenge; der Append-Rollback bleibt
  aktiv.
- Regression mit zwei Store-Objekten und 40 parallelen Appends in beiden
  Implementierungen: `tests/test_working_memory.py`: `25 passed`;
  Telegram-Working-Memory `4 passed`; separater 100er-Repro ergibt
  `indexed_entries=100`. Ruff, `py_compile` und `git diff --check` gruen.
- Code-Commit: `e05caa13 fix: serialize shared working memory paths`; kein
  Provider/API-Aufruf. Lock gilt fuer diesen gemeinsamen Prozess; keine
  unnoetige externe Prozesskoordination eingefuehrt.

### Working-Memory-Symlink-Locks

- 2026-07-16: Der prozessweite Lockkey nutzte zunaechst nur `abspath`.
  Dasselbe Working-Memory konnte ueber einen Symlink dadurch zwei Locks
  erhalten. Repro: 100 erfolgreiche parallele Appends, nur 53 indexierte
  Entries.
- Lockkeys nutzen jetzt `realpath`; direkte und symlinkte Pfade teilen
  denselben Lock. Das betrifft beide Working-Memory-Implementierungen.
- Symlink-Parallelregression mit 40 Appends je Store-Klasse gruen;
  `tests/test_working_memory.py`: `27 passed`; Telegram-Working-Memory
  `4 passed`; Ruff, `py_compile` und `git diff --check` gruen.
- Code-Commit: `c071636c fix: canonicalize working memory lock paths`; kein
  Provider/API-Aufruf.

### Working-Memory-Index-UTF8

- 2026-07-16: `read_text(encoding="utf-8")` konnte bei ungueltigen Bytes in
  `Working_Memorys.json` einen ungefangenen `UnicodeDecodeError` werfen.
  Engine-/Adapter-Aufruf konnte dadurch statt leerem Arbeitskontext komplett
  abbrechen.
- Der Lesepfad behandelt `UnicodeDecodeError` jetzt wie JSON-Korruption,
  verschiebt Originalbytes nach `Working_Memorys.json.corrupt.*` und erzeugt
  erst danach neuen Index.
- Regression in beiden Store-Klassen prueft Byte-genaues Backup:
  `tests/test_working_memory.py`: `29 passed`; Telegram-Working-Memory
  `4 passed`; Ruff, `py_compile` und `git diff --check` gruen.
- Code-Commit: `5d441d80 fix: quarantine invalid utf8 working memory indexes`;
  kein Provider/API-Aufruf.

### Working-Memory-Reparatur bei Read/Prepare

- 2026-07-16: `prepare()` verschob einen korrupten Index zwar nach
  `Working_Memorys.json.corrupt.*`, schrieb den neu erzeugten Index aber nur
  indirekt bei `ensure()` oder dem naechsten Append. Nach Prozessabbruch blieb
  damit kein aktiver Index bestehen.
- Beide Working-Memory-Pfade persistieren den reparierten Index jetzt direkt
  in `_load_or_initialize()`. Original bleibt quarantiniert; Read/Prepare ist
  danach crash-resistenter und wiederholbar.
- Regression parametrisiert ueber Runtime- und Telegram-Store:
  `tests/test_working_memory.py`: `31 passed`; Ruff, `py_compile` und
  `git diff --check` gruen.
- Code-Commit: `5234fe0a fix: persist working memory repairs from reads`;
  kein Provider/API-Aufruf.

### Working-Memory-Index-Rebuild aus JSONL

- 2026-07-16: Ein korruptes Index-JSON wurde zwar ersetzt, valide Eintraege
  in `Working_Memorys.entries.jsonl` blieben aber ohne Indexreferenz und waren
  fuer Retrieval unsichtbar.
- Reparatur baut `entries`, Keyword-Buckets und `recent_ids` jetzt aus jeder
  gueltigen JSONL-Zeile neu auf. Ungueltige Zeilen bleiben unveraendert und
  werden nur protokolliert; Rohdaten werden nicht geloescht.
- Gemeinsamer Helper wird von Runtime- und Telegram-Store verwendet.
  Regression parametrisiert ueber beide Stores:
  `tests/test_working_memory.py`: `33 passed`; Ruff, `py_compile` und
  `git diff --check` gruen.
- Code-Commit: `5fa1eb3d fix: rebuild working memory index from entries`;
  kein Provider/API-Aufruf.

### Working-Memory-Normalisierung bei Prepare

- 2026-07-16: `prepare()` normalisierte veraltete oder fremde Metadaten nur
  im Speicher. Nach Prozessende konnte derselbe inkonsistente Index erneut
  geladen werden.
- Persistiert werden jetzt nur tatsaechliche Normalisierungsveraenderungen;
  unveraenderte Read-Pfade bleiben schreibfrei. Entfernte Legacy-/Privacy-
  Felder bleiben entfernt.
- Regression parametrisiert ueber beide Stores: `tests/test_working_memory.py`:
  `35 passed`; Ruff, `py_compile` und `git diff --check` gruen.
- Code-Commit: `7ff3a0a3 fix: persist working memory metadata normalization`;
  kein Provider/API-Aufruf.

### Working-Memory-Nested-Index-Schema

- 2026-07-16: Die bisherige Validierung pruefte nur Container. Ein String
  statt ID-Liste in einem Keyword-Bucket blieb gueltig und machte Treffer
  still unsichtbar.
- Keyword-Buckets, `recent_ids` und Entry-Metadaten werden jetzt bis zur
  naechsten Strukturgrenze typgeprueft. Bei Fehler greift Quarantaene plus
  JSONL-Rebuild; gueltige Entry-Rohdaten bleiben erhalten.
- Regression parametrisiert ueber beide Stores: `tests/test_working_memory.py`:
  `37 passed`; Ruff, `py_compile` und `git diff --check` gruen.
- Code-Commit: `a565f51a fix: validate nested working memory indexes`;
  kein Provider/API-Aufruf.

### Working-Memory-Privacy beim Lesen

- 2026-07-16: Neue Eintraege werden beim Append sanitisiert, alte/importierte
  JSONL-Zeilen aber beim Prompt-Lesen ungeprueft ausgegeben. Damit konnten
  Handles, URLs oder Telefonnummern aus Legacy-Rohdaten in den Kontext
  gelangen.
- Beide Stores sanitizen den gelesenen Entry jetzt vor Prompt-Erzeugung und
  berechnen Keywords neu. JSONL-Rohdaten und Byte-Offsets bleiben unveraendert
  fuer Diagnose und Rebuild.
- Regression parametrisiert ueber beide Stores: `tests/test_working_memory.py`:
  `39 passed`; Ruff, `py_compile` und `git diff --check` gruen.
- Code-Commit: `d7b6d601 fix: sanitize working memory entries on read`;
  kein Provider/API-Aufruf.

### Working-Memory-Entry-Metadaten

- 2026-07-16: Entry-Metadaten wurden bisher nur als Dict validiert. Kaputte
  `offset`-/`length`-Werte machten einzelne JSONL-Eintraege still unlesbar.
- Offset und Laenge werden jetzt auf nichtnegative, numerisch lesbare Werte
  geprueft; Laenge null ist ungueltig. Bei Fehler baut der Store Index aus
  JSONL neu auf. Numerische Legacy-Strings bleiben kompatibel.
- Regression parametrisiert ueber beide Stores: `tests/test_working_memory.py`:
  `41 passed`; Ruff, `py_compile` und `git diff --check` gruen.
- Code-Commit: `117aaedf fix: validate working memory entry offsets`;
  kein Provider/API-Aufruf.

### Account-JSONL-Row-Typen

- 2026-07-16: SQL-JSONL-Reads reichten Nicht-Dict-Rows ungefiltert an
  Outbox-/Audit-Consumer weiter. Ein korruptes SQL-Objekt konnte dadurch
  spaeter bei `row.get()` den Consumer abbrechen.
- Der AccountStore filtert JSONL-Collection-Reads jetzt auf Dict-Rows; eine
  ungueltige Row wird nicht als Outbox-Datensatz ausgegeben und loest keinen
  stillen Rewrite aus.
- `tests/test_account_store.py`: `251 passed`; Ruff, `py_compile` und
  `git diff --check` gruen.
- Code-Commit: `2883551a fix: filter invalid account collection rows`;
  kein Provider/API-Aufruf.

### SQL-Schema-Initialisierung

- 2026-07-16: SQLite- und PostgreSQL-Backends konnten bei parallelem ersten
  Zugriff dieselbe Schema-Initialisierung gleichzeitig ausfuehren. Bei SQLite
  konnte daraus ein `database is locked` entstehen; PostgreSQL bekam
  unnoetige konkurrierende DDL-Transaktionen.
- Beide Backends serialisieren Schema-Pruefung und DDL jetzt ueber einen
  gemeinsamen Prozess-Lock. Das gilt fuer mehrere Backend-Objekte innerhalb
  desselben Bot-Prozesses; getrennte Prozesse verlassen sich weiter auf die
  Transaktions-/Lock-Semantik der Datenbank.
- Regression: Ein blockierter erster SQLite-DDL-Lauf darf keinen zweiten
  parallelen DDL-Lauf starten. AccountStore `252 passed`, Benchmark-Suite
  `14 passed`; Ruff, `py_compile` und `git diff --check` gruen.
- Code-Commit: `3134bd27 fix: serialize SQL schema initialization`;
  kein Provider/API-Aufruf.

### PostgreSQL-Schema-Retry

- 2026-07-16: Bei gleichzeitigem `42P01`-Fehler konnte ein zweiter Request
  die bereits laufende Schema-Reparatur als `_initialized=False` sehen und
  ohne Retry abbrechen.
- Schema-Invalidierung, Reparatur-Aufruf und betroffener Retry laufen jetzt
  unter demselben Prozess-Lock. Ein paralleler Request wartet und versucht
  danach erneut; Fremdfehler ohne PostgreSQL-Schema-SQLSTATE bleiben
  unveraendert Fehler.
- Regression fuer die kontrollierte Reihenfolge zweier paralleler Reads:
  `tests/test_memory_store_benchmark.py`: `15 passed`; Ruff, `py_compile` und
  `git diff --check` gruen.
- Code-Commit: `a511a866 fix: serialize PostgreSQL schema retries`;
  kein Provider/API-Aufruf.

### Fallback-Datenbank-Diagnose

- 2026-07-16: Der `WarningFallbackAccountMemoryBackend` reichte
  Entry-/Index-/Collection-Diagnosen durch, verlor aber
  `last_database_missing`. Wenn Primaer- und Fallback-SQLite fehlten, konnte
  ein Wrapper-Consumer den leeren Zustand deshalb nicht von einem gesunden
  leeren Account unterscheiden.
- Der Wrapper fuehrt das Feld jetzt selbst, kopiert es aus dem zuletzt
  gelesenen Backend und stellt bei beiden fehlenden Datenbanken den
  Primaerzustand wieder her. Fallback-Sync-Fehler bleiben separat erhalten;
  kein automatisches Loeschen oder Ueberschreiben vorhandener Daten.
- Regression: `tests/test_account_store.py` Fallback-Block `55 passed`;
  Ruff, `py_compile` und `git diff --check` gruen.
- Code-Commit: `ef984a36 fix: preserve fallback database diagnostics`;
  kein Provider/API-Aufruf.

### Fallback-Collection-Name-Diagnose

- 2026-07-16: `read_collection_names()` synchronisierte den Wrapper-Status
  nicht. Nach einem vorherigen Missing-Database-Read konnte ein spaeter
  erfolgreicher Primary- oder Fallback-Name-Read den alten
  `last_database_missing`-Wert stehen lassen.
- Erfolgreiche Name-Reads kopieren jetzt Diagnosen vom tatsaechlich gelesenen
  Backend; beide fehlenden Datenbanken setzen den Primary-Missing-Status
  explizit. Das verhindert stale Health-/Migrationssignale ohne Datenrewrite.
- Regression mit vorherigem Missing-State und anschliessendem Erfolgs-Read:
  Fallback-Block `56 passed`; gesamte `tests/test_account_store.py` danach
  `254 passed`; Ruff, `py_compile` und `git diff --check` gruen.
- Code-Commit: `22f69b2e fix: refresh fallback collection diagnostics`;
  kein Provider/API-Aufruf.

### Structured-Memory-Index-Reparatur-beim-Append

- 2026-07-16: `append_structured_memory_entry()` aktualisierte bei leerem
  oder teilbeschaedigtem Index nur den neuen Datensatz. Alte Live-Entries
  blieben dadurch aus Keyword- und semantischem Cache-Retrieval verschwunden.
- Append stellt fehlende Live-IDs jetzt inkrementell wieder her. Fehlende
  Keywords werden aus `user_text`/`bot_text`/`text` abgeleitet; semantische
  Cache-Metadaten werden nur fuer fehlende IDs berechnet. Kein Voll-Rebuild
  bei gesundem Index.
- Regression: Index-/Ranking-Block `42 passed`; Ruff, `py_compile` und
  `git diff --check` gruen.
- Code-Commit: `8a2335fb fix: repair missing memory index entries`;
  kein Provider/API-Aufruf.

### Structured-Memory-Rebuild-bei-unlesbaren-Entries

- 2026-07-16: Rebuild und Append konnten nach einem partiellen SQL-Read mit
  nur lesbaren Rows weiterarbeiten. Bei anschliessender Normalisierung waere
  eine unlesbare, aber noch vorhandene Row durch einen destruktiven Write
  verschwunden.
- Beide Pfade brechen jetzt bei `last_entry_read_error` oder
  `last_entry_skipped` fail-closed ab. Ein sauberer Fallback darf weiterhin
  vorher ueber den Warning-Backend reparieren; der isolierte Primary schreibt
  keine Teilmenge zurueck.
- Regression mit realer korrupter SQLite-Ciphertext-Row: Rebuild und Append
  blockiert, beide SQL-Rows bleiben erhalten; Index-/Account-Regressionen
  gruen. Gesamte `tests/test_account_store.py`: `256 passed`; Ruff,
  `py_compile` und `git diff --check` gruen.
- Code-Commit: `bfd653aa fix: block memory rebuilds on unreadable rows`;
  kein Provider/API-Aufruf.

### Teilreads-in-Account-Memory-Pfaden

- 2026-07-16: SQL-Backends liefern bei korrupten Ciphertext-Zeilen bewusst
  sichtbare Rows plus `last_entry_read_error`/`last_entry_skipped`. Mehrere
  nachgelagerte Pfade ignorierten diese Diagnose: Ranking, Memory-Auswahl,
  Access-Tracking, ID-Reads, Legacy-Append und Account-Merge konnten mit einer
  unvollstaendigen Row-Menge weiterarbeiten. Ein anschliessender Write haette
  die unlesbare Zeile aus dem SQL-Backend entfernen koennen.
- Gemeinsamer Guard in `AccountStore` bricht diese Pfade fail-closed ab. Ein
  gesunder Warning-Fallback darf weiterhin vorher reparieren; ein isolierter
  partieller Primary-Read wird weder als Kontext verwendet noch zur Grundlage
  eines destruktiven Writes.
- Regression deckt alle sechs betroffenen Read-/Modify-/Retrieval-Pfade ab und
  prueft, dass kein Entry-Write erfolgt. Gesamte `tests/test_account_store.py`:
  `257 passed`; Ruff, `py_compile` und `git diff --check` gruen.
- Code-Commit: `b00fcea1 fix: refuse partial account memory reads`;
  kein Provider/API-Aufruf.

### Leere-Collection-Namen-im-Fallback

- 2026-07-16: `WarningFallbackAccountMemoryBackend.read_collection_names()`
  gab nach einem Primary-Ausfall eine leere Liste aus dem Secondary als
  erfolgreichen Read zurueck. Damit konnten vorhandene SQL-Collections des
  Primary unsichtbar werden; ein leerer Secondary ist kein Nachweis fuer einen
  leeren Account.
- Leere Secondary-Namen setzen den Account jetzt auf unsicheren Fallback-
  Zustand, erzeugen `read_collection_names: fallback has no recoverable data`
  und blockieren Folgezugriffe bis eine verifizierbare Liste vorliegt. Der
  Sonderfall zweier wirklich nicht initialisierter Datenbanken bleibt erlaubt.
- Regression: gesamte `tests/test_account_store.py` `258 passed`; Ruff,
  `py_compile` und `git diff --check` gruen.
- Code-Commit: `8dfa5a38 fix: block empty collection fallback`;
  kein Provider/API-Aufruf.

### Partial-Read-By-IDs-im-Fallback

- 2026-07-16: Der `read_entries_by_ids()`-Pfad markierte
  `partial_result=True`. Bei diagnostischem Primary-Teilread und leerem
  Secondary wurde dadurch die Schutzbedingung fuer leere Fallback-Daten
  uebersprungen. Der Primary konnte anschliessend durch eine leere
  Fallback-Menge ersetzt werden; relevante Entries waeren verloren gegangen.
- Die Leere-Fallback-Pruefung beruecksichtigt jetzt Entry-Read-Fehler und
  `skipped` unabhaengig vom partiellen Ergebnis. Primary bleibt unveraendert,
  Fallback wird als unrecoverable markiert; `AccountStore` verweigert die
  Nutzung der Teilmenge.
- Regression mit gutem und korruptem Primary-Entry plus leerem Secondary;
  gesamte `tests/test_account_store.py` `259 passed`; Ruff, `py_compile` und
  `git diff --check` gruen.
- Code-Commit: `3df7a961 fix: preserve primary on partial id fallback`;
  kein Provider/API-Aufruf.

### Leeres-JSON-Memoryartefakt-im-Healthcheck

- 2026-07-16: Ein JSON-Account mit vorhandenem, aber leerem
  `User_Memory_Index.json` (`{}`) wurde wie ein frischer Account ohne
  Memoryartefakte als gesund bewertet. Dadurch konnten fehlendes `scope` und
  fehlendes verschachteltes `index`-Schema unbemerkt bleiben.
- Health-Check akzeptiert den leeren Sonderfall jetzt nur noch, wenn im
  JSON-Backend weder Entries- noch Indexdatei existiert. SQL-Neuaccounts ohne
  gespeicherte Memoryzeilen behalten bisherige gesunde Semantik.
- Regression fuer frischen SQL-Account und leeres JSON-Artefakt; gesamte
  `tests/test_account_store.py` `260 passed`; Ruff, `py_compile` und
  `git diff --check` gruen.
- Code-Commit: `557df26f fix: detect empty memory index artifacts`;
  kein Provider/API-Aufruf.

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
- Nach Commit 20 erneut ausgefuehrt: `teebotus.service` `active/running`,
  PID `358493`, Start `2026-07-16 04:20:43 CEST`, Runtime-Version `1.9.498`.
  Signal-REST `/v1/about` meldet Version `0.100`; `--runtime-status` meldet
  Signal erreichbar, Qdrant `ready` und Account-Memorys `ok`. Kein
  providerseitiger Testaufruf.
- Nach Commit 20 dieses Blocks erneut ausgefuehrt: `teebotus.service`
  `active/running`, PID `1574082`, Start `2026-07-16 10:48:36 CEST`.
  `--runtime-status` meldet Signal erreichbar, Qdrant `ready` und alle
  Account-Crypto-/Memory-Pruefungen `ok`; Depressionsbot-Signal bleibt ohne
  verknuepfte Identity und meldet deshalb die bekannte separate-Account-
  Notice. Kein Provider/API-Aufruf.

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

**Laufstand:** Seit dem letzten Restart `20/20` Commits; Restart jetzt faellig,
kein Push ausgeloest.

- Restart nach Commit 20 ausgefuehrt ueber die aktive User-Unit
  `teebotus.service`: `active/running`, PID `1847835`, Start
  `2026-07-16 12:05:21 CEST`. Die systemweite Unit ist erwartungsgemaess
  nicht aktiv; Bot laeuft unter User-Systemd. Providerfreier
  `--runtime-status` meldet Signal erreichbar, Qdrant `ready` und alle
  Account-Crypto-/Memory-Pruefungen `ok`. Bekannte Konfigurationszustaende:
  HF-Pool deaktiviert, GROQ-Key fehlt, Depressionsbot-Signal ohne verknuepfte
  Identity. Kein Provider/API-Aufruf.

**Laufstand nach Restart:** Seit dem Restart `1/20` Commits; kein Push
ausgeloest. Naechster Restart nach 19 weiteren Commits.

### Index-Read-Guard-vor-Structured-Mutationen

- 2026-07-16: Rebuild war gegen unlesbare Indexe geschuetzt, aber
  strukturierter Append, Access-Markierung und Memory-Reset lasen den Index
  danach ohne denselben Guard. Diese Pfade konnten einen defekten Index
  ebenfalls ersetzen oder bei Reset Metadaten veraendern.
- Alle drei Read-Modify-Write-Pfade pruefen Index-Diagnose direkt nach dem
  Read und stoppen vor jedem Entry-/Index-Write. Fehlende Erst-DB bleibt
  zulaessig; Entschluesselungs-/Skip-Diagnosen bleiben blockierend.
- Regression fuer Append, Access, Reset und Rebuild mit Write-Zaehlern;
  gesamte `tests/test_account_store.py` `267 passed`; Ruff, `py_compile`
  und `git diff --check` gruen.
- Code-Commit: `e3671b6c fix: guard structured mutations on index read errors`;
  kein Provider/API-Aufruf.

**Laufstand nach Fix:** Seit dem Restart `3/20` Commits; kein Push
ausgeloest. Naechster Restart nach 17 weiteren Commits.

### Empty-By-ID-Read-muss-Diagnosen-zuruecksetzen

- 2026-07-16: `AccountStore.read_memory_entries_by_ids()` gab bei leerer
  ID-Liste sofort `[]` zurueck. Direkte Backend-Read-Diagnosen aus einem
  vorherigen Fehler blieben dadurch stehen; der Backend-eigene Empty-Read-
  Reset wurde nie erreicht.
- AccountStore ruft bei vorhandener Backend-API den kostenfreien Empty-Read-
  Reset auf; Adapter ohne diese API erhalten best-effort denselben Entry-
  Diagnose-Reset. Keine DB-/Fallback-Abfrage fuer leere Anfrage.
- Regression fuer direkten AccountStore-Aufruf; gesamte
  `tests/test_account_store.py` `268 passed`; Ruff, `py_compile` und
  `git diff --check` gruen.
- Code-Commit: `4dee118d fix: clear diagnostics on empty memory id reads`;
  kein Provider/API-Aufruf.

**Laufstand nach Fix:** Seit dem Restart `5/20` Commits; kein Push
ausgeloest. Naechster Restart nach 15 weiteren Commits.

### Leere-Secondary-Collection-nicht-promoten

- 2026-07-16: Fallback-Recovery pruefte bei SQL-Collections nur
  `last_collection_skipped`, nicht `last_collection_read_error`. Zusaetzlich
  wurde die Leere der Primary-Resultmenge statt der Recovery-Menge bewertet.
  Primary-Teilrows plus leerer Secondary konnten dadurch als erfolgreiche
  Recovery gelten und Primary-Collection leeren.
- Recovery wertet jetzt `repair_data`/Secondary und Fehlertext oder Skip als
  Unrecoverable-Kriterium. Bei leerem Secondary bleibt Rueckgabe fail-closed;
  kein Repair-Write auf Primary. Bestehende Semantik fuer bewusst leere,
  fehlerfreie Secondary-Daten bleibt unveraendert.
- Regression mit sichtbarer Primary-Teilrow, Fehlertext ohne Skip und leerem
  Secondary; bestehende Entry-/Index-Schutztests; gesamte
  `tests/test_account_store.py` `269 passed`; Ruff, `py_compile` und
  `git diff --check` gruen.
- Code-Commit: `7eb48c15 fix: block empty fallback collection promotion`;
  kein Provider/API-Aufruf.

**Laufstand nach Fix:** Seit dem Restart `7/20` Commits; kein Push
ausgeloest. Naechster Restart nach 13 weiteren Commits.

### Account-Merge-Index-vor-Entry-Write-validieren

- 2026-07-16: `merge_accounts()` schrieb Ziel-Entries vor dem Read und
  Diagnosecheck von Source-/Target-Index. Bei defektem Zielindex konnte Merge
  mit halbem Zielzustand abbrechen; wiederholter Merge musste danach einen
  Zwischenstand behandeln.
- Beide Indexe werden jetzt vor dem ersten Ziel-Entry-Write gelesen und
  fail-closed validiert. Keine Zielmutation bei unlesbarem Index; vorhandene
  Entry-/Index-Rollbacklogik bleibt zusaetzlich aktiv.
- Regression prueft defekten Zielindex und protokolliert keine Ziel-Writes;
  gesamte `tests/test_account_store.py` `270 passed`; Ruff, `py_compile` und
  `git diff --check` gruen.
- Code-Commit: `323c0895 fix: validate merge indexes before writes`;
  kein Provider/API-Aufruf.

**Laufstand nach Fix:** Seit dem Restart `9/20` Commits; kein Push
ausgeloest. Naechster Restart nach 11 weiteren Commits.

### Leerer-By-ID-Read-und-stale-Missing-Diagnose

- 2026-07-16: `WarningFallbackAccountMemoryBackend.read_entries_by_ids()`
  setzte bei leerer Anfrage Entry-Fehler zurueck, liess aber
  `last_database_missing=True` stehen. Nach einer vorherigen DB-Stoerung
  konnten Status-/Doctor-Ausgaben dadurch weiter eine falsche Missing-Lage
  anzeigen.
- Leere By-ID-Anfrage setzt jetzt alle Entry-Read-Diagnosen einschliesslich
  `last_database_missing` konsistent zurueck. Kein Datenzugriff, kein
  Fallback-Sync und kein Provider-Aufruf.
- Regression zusammen mit SQLite-Gegenprobe; gesamte
  `tests/test_account_store.py` `260 passed`; Ruff, `py_compile` und
  `git diff --check` gruen.
- Code-Commit: `d61d7a7c fix: clear stale fallback missing diagnostics`;
  kein Provider/API-Aufruf.

### Partielle-SQL-Collections-vor-Append

- 2026-07-16: Outbox-, Audit-, Dispatch- und Codex-History-Append-Pfade lasen
  eine SQL-Collection und schrieben anschliessend den Gesamtbestand. Bei
  `last_collection_read_error`/`last_collection_skipped` konnten sichtbare
  Rows plus unlesbare Rows dadurch die unlesbaren Rows beim Write entfernen.
- Gemeinsamer Guard in `AccountStore` blockiert jetzt alle sieben Append-Pfade
  vor ID-Vergabe und Write. Das verhindert auch doppelte IDs im atomaren
  Codex-Dispatch-Append, wenn der vorherige Read nur teilweise war.
- Regression fuer Proactive-Outbox, Proactive-Audit, Proactive-Dispatch,
  Status-Outbox, Status-Dispatch, Codex-History und Codex-History-Dispatch;
  gesamte `tests/test_account_store.py` `261 passed`; Ruff, `py_compile` und
  `git diff --check` gruen.
- Code-Commit: `955dfc0f fix: block partial collection appends`;
  kein Provider/API-Aufruf.

### Partielle-SQL-Collections-vor-Account-Merge

- 2026-07-16: `_merge_sql_account_memory_collections()` las Quelle und Ziel
  und konnte danach aus partiellen Row-Mengen einen neuen Zielbestand
  schreiben. Korrupte Collection-Rows waeren dabei aus dem Ziel verschwunden.
- Guard prueft jetzt jede Quelle und jedes Ziel unmittelbar nach dem Read.
  Merge stoppt fail-closed vor dem ersten Collection-Write; gesundes
  Fallback-Recovery bleibt davor moeglich.
- Regression mit partieller Quelle und partiellem Ziel; gesamte
  `tests/test_account_store.py` `262 passed`; Ruff, `py_compile` und
  `git diff --check` gruen.
- Code-Commit: `8de2da94 fix: block partial collection merges`;
  kein Provider/API-Aufruf.

### Partielle-SQL-Collections-vor-direktem-Write

- 2026-07-16: Direkte Ersatzschreiber fuer JSONL-Collections,
  Account-Zustandsdokumente und Instanz-JSON prueften bisher keine
  partiellen SQL-Lese-Diagnosen. Ein Aufruf wie `write_proactive_outbox()`
  konnte dadurch unlesbare bestehende Rows durch einen neuen Gesamtbestand
  ersetzen.
- Gemeinsamer fail-closed Guard sitzt jetzt unmittelbar vor jedem direkten
  `write_collection()` in diesen drei Schreibpfaden. Append-, Status-,
  History-, LLM-, Agent-, Auth- und Instanz-Status-Schreiber behalten ihre
  bisherige API und schreiben bei unvollstaendiger Collection nicht.
- Regression erweitert: sieben Append-Pfade plus direkte Outbox-, LLM-,
  Agent-, Auth- und Instanz-JSON-Schreiber; gesamte
  `tests/test_account_store.py` `262 passed`; Ruff, `py_compile` und
  `git diff --check` gruen.
- Code-Commit: `09e8cb99 fix: guard direct account collection writes`;
  kein Provider/API-Aufruf.

**Laufstand nach Fix:** Seit dem Restart `8/20` Commits; kein Push
ausgeloest. Naechster Restart nach 12 weiteren Commits.

### Codex-Summary-vollstaendig-und-Kommentare-einklappbar

- 2026-07-16: `Bauplaene!/Summarys.md` forderte ungekürzte Summarys, bis zu
  zehn Kommentare und einklappbare Kommentarueberschriften. Der Formatter
  zeigte vorher nur fünf Zwischenantworten, kuerzte jede auf 900 Zeichen und
  speicherte beim Session-Import nur acht Bullet-Zeilen mit je 240 Zeichen.
- Session-Imports speichern den vollstaendigen redigierten Finaltext jetzt in
  `summary.text` und rendern ihn vollstaendig im Abschnitt `Zusammenfassung`.
  Zwischenantworten werden nicht mehr auf 1000/900 Zeichen gekuerzt; maximal
  zehn werden als sichere HTML-`<details>`-Bloecke angezeigt.
- Regression: Volltext laenger als 1400 Zeichen, 12 Kommentare und alter
  Importpfad getestet; `3 passed`, `py_compile`, Diff-Check und relevante
  Ruff-Regeln gruen. Kein Provider/API-Aufruf.
- Code-Commit: `22be8ae5 fix: preserve full codex summaries`.

**Laufstand nach Fix:** Seit dem Restart `16/20` Commits; dieser
Dokumentationscommit erhoeht auf `17/20`. Kein Push. Naechster Restart nach
3 weiteren Commits.

### Vollsuite-nach-Store-Guard

- 2026-07-16: Zweiter Vollsuite-Lauf nach dem minimalen Store-Guard ist
  vollstaendig gruen: `3864 passed, 2 skipped, 1 warning, 17 subtests
  passed` in `270.54s`. Die acht Codex-History-Regressionsfehler sind weg.
- Verbleibender Hinweis: LangChain importiert Pydantic-V1-Kompatibilitaet,
  die Python 3.14 als inkompatibel meldet. Kein Testfehler und keine
  Runtime-Umstellung ohne gezielte Kompatibilitaetspruefung.
- Kein Provider/API-Aufruf.

**Aktueller Laufstand:** Seit dem letzten Restart `14/20` Commits; dieser
Dokumentationscommit erhoeht auf `15/20`. Kein Push. Naechster Restart nach
5 weiteren Commits.

### Modern-Engine-Tracker-Test-im-Persistenz-Scope-halten

- 2026-07-16: Der Modern-Engine-Test pruefte gespeicherte Message-Refs erst
  nach Ende seines `TemporaryDirectory`. Der Tracker verwirft bei fehlender
  Persistenz absichtlich stale Refs; dadurch war der Test falsch gescoped und
  meldete einen Produktionsfehler.
- Assertion in den temporaeren Verzeichnis-Scope verschoben. Produktionscode
  unveraendert; bestehender Schutz gegen geloeschte/ungueltige Tracker-Dateien
  bleibt aktiv.
- Regression: Modern-Engine-Test plus `tests/test_message_tracking.py`:
  `9 passed`; Ruff, `py_compile` und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Test-Commit: `795dc983 test: keep tracker assertion within fixture`.

**Laufstand nach Fix:** Seit dem Restart `10/20` Commits; kein Push
ausgeloest. Naechster Restart nach 10 weiteren Commits.

### Editable-Installation-auf-Quellversion-angleichen

- 2026-07-16: Lokale Metadaten enthielten parallel `TeeBotus` `1.8.0` und
  die Quellversion `1.9.498`. Ursache war eine alte editable Installation in
  `/home/teladi/.local/lib/python3.14/site-packages`.
- `python3 -m pip install --no-deps --editable .` aktualisierte die lokale
  Installation auf `1.9.498`; Dependencies und Repo-Dateien blieben
  unangetastet.
- `tests/test_pyproject_metadata.py`: `7 passed`; danach nur noch eine
  sichtbare TeeBotus-Distribution mit `1.9.498`. Kein Provider/API-Aufruf.

**Laufstand nach Fix:** Seit dem Restart `12/20` Commits; kein Push
ausgeloest. Naechster Restart nach 8 weiteren Commits.

### Admin-Directory-Guard-mit-minimalen-Store-Doubles

- 2026-07-16: Vollsuite lief bis auf acht Codex-History-Tests durch:
  `3856 passed, 8 failed`. Der neue Phantom-Account-Guard rief bei einem
  bewusst minimalen Dispatcher-Store ohne `account_dir` direkt eine nicht
  vorhandene Methode auf.
- `_account_dir_exists()` behandelt Stores ohne `account_dir` jetzt als
  nicht-lokal. Echte `AccountStore`-Routen bleiben unveraendert; der
  Codex-Dispatcher bleibt mit seinem schlanken Store-Double kompatibel.
- Regression: acht zuvor fehlschlagende Codex-History-Tests plus Admin-Suite:
  `40 passed`; Ruff, `py_compile` und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `9c94aa74 fix: tolerate minimal admin store doubles`.

**Laufstand nach Fix:** Seit dem Restart `13/20` Commits; kein Push
ausgeloest. Naechster Restart nach 7 weiteren Commits.

### Erstschreibpfad-bei-fehlender-SQLite-Datenbank

- 2026-07-16: `read_entries()` meldet bei einer noch nicht angelegten
  SQLite-Datenbank `last_database_missing=True` und eine technische
  Missing-Diagnose. Der AccountStore behandelte diese leere
  Erstinitialisierung wie korrupte Entries und blockierte dadurch den ersten
  Memory-Write.
- Der Append-Guard ignoriert Missing-Diagnose nur bei explizit fehlender
  Datenbank. Partielle Reads, Entschluesselungsfehler und uebersprungene Rows
  bleiben unveraendert fail-closed.
- Regression: Strukturierter Append auf neuem SQLite-Pfad legt DB an und
  liest den normalisierten Entry danach wieder; gesamte
  `tests/test_account_store.py` `263 passed`; Ruff, `py_compile` und
  `git diff --check` gruen.
- Code-Commit: `086c3c1b fix: allow first memory write on missing database`;
  kein Provider/API-Aufruf.
- Testpraezisierung: `c8a9006c test: cover structured first memory append`;
  kein Provider/API-Aufruf.

**Laufstand nach Fix:** Seit dem Restart `12/20` Commits; kein Push
ausgeloest. Naechster Restart nach 8 weiteren Commits.

### Stale-Read-Diagnosen-nach-erfolgreichem-Write

- 2026-07-16: SQLite-Reads auf fehlender DB hinterliessen
  `last_*_read_error`. Ein anschliessender erfolgreicher Write legte die DB
  zwar an, loeschte die alten Read-Diagnosen aber nicht. Der Fallback-Router
  kopierte sie danach erneut; Status und Folge-Guards konnten so eine bereits
  behobene Stoerung weiter melden.
- SQLite-, PostgreSQL- und Fallback-Write-Erfolgspfad setzt jetzt jeweils nur
  die betroffene Entry-, Index- oder Collection-Diagnose sowie das
  Datenbank-Missing-Flag zurueck. Fehler vor/nach dem Write bleiben sichtbar;
  kein pauschales Loeschen fremder Operation-Diagnosen.
- Regression mit strukturiertem Erstwrite auf direktem SQLite-Backend und
  konfiguriertem SQLite-Fallback; gesamte `tests/test_account_store.py`
  `263 passed`; Ruff, `py_compile` und `git diff --check` gruen.
- Code-Commit: `8a2cbe35 fix: clear stale memory diagnostics after writes`;
  kein Provider/API-Aufruf.

**Laufstand nach Fix:** Seit dem Restart `14/20` Commits; kein Push
ausgeloest. Naechster Restart nach 6 weiteren Commits.

### Partielle-Dokument-Collections-vor-Merge

- 2026-07-16: SQL-JSONL-Merge pruefte Quelle und Ziel direkt nach dem
  Collection-Read. Der separate Dokument-Merge fuer LLM-State, Agent-State
  und Status-Auth pruefte bisher nur indirekt beim Write. Ein partieller
  Quell-Read konnte durch anschliessenden sauberen Ziel-Read seine Diagnose
  verlieren und als vollstaendiger Zustand in Ziel-Account gelangen.
- Dokument-Merge prueft jetzt Quelle und Ziel unmittelbar nach jedem Read;
  Merge stoppt vor dem ersten Ziel-Write bei unlesbaren Rows. Ziel-Fehler
  bleiben ebenfalls fail-closed.
- Regression fuer partielle Quell-Dokument-Collection plus bestehende
  Quell-/Ziel-Collection-Regression; gesamte `tests/test_account_store.py`
  `264 passed`; Ruff, `py_compile` und `git diff --check` gruen.
- Code-Commit: `51fe5b54 fix: guard partial document merges`;
  kein Provider/API-Aufruf.

**Laufstand nach Fix:** Seit dem Restart `16/20` Commits; kein Push
ausgeloest. Naechster Restart nach 4 weiteren Commits.

### Healthcheck-muss-auch-stille-Skips-melden

- 2026-07-16: `check_structured_memory_index()` nahm
  `last_entry_skipped` nur zusammen mit nichtleerem Fehlertext ernst. Ein
  Backend konnte Rows ueberspringen, aber keinen Detailtext liefern; Health
  blieb dann trotz unvollstaendiger Entry-Menge scheinbar gesund.
- Health wertet jetzt `entry_read_error` **oder** `entry_skipped > 0` als
  Datenbankfehler und verwendet bei fehlendem Detailtext `error=unspecified`.
- Regression mit zwei uebersprungenen Rows ohne Fehlertext; gesamte
  `tests/test_account_store.py` `265 passed`; Ruff, `py_compile` und
  `git diff --check` gruen.
- Code-Commit: `d1ff530c fix: report skipped memory rows in health check`;
  kein Provider/API-Aufruf.

**Laufstand nach Fix:** Seit dem Restart `18/20` Commits; kein Push
ausgeloest. Naechster Restart nach 2 weiteren Commits.

### Rebuild-vor-unlesbarem-Index-stoppen

- 2026-07-16: `rebuild_structured_memory_index()` validierte Entry-Reads,
  las den bestehenden Index danach aber ohne Diagnose-Guard. Ein
  unlesbarer Index konnte so durch einen Rebuild ersetzt werden; Backend-
  Schutz war nicht fuer jeden Adapter garantiert.
- Rebuild prueft den Index direkt nach dem Read und stoppt fail-closed vor
  Entry- oder Index-Write. Eine explizit fehlende, noch nicht initialisierte
  DB bleibt als leerer Erstzustand zulaessig.
- Regression mit unlesbarem Index und Write-Zaehlern; gesamte
  `tests/test_account_store.py` `266 passed`; Ruff, `py_compile` und
  `git diff --check` gruen.
- Code-Commit: `7bcd96d4 fix: refuse rebuild with unreadable memory index`;
  kein Provider/API-Aufruf.

**Laufstand nach Fix:** Seit dem Restart `20/20` Commits; Restart jetzt
faellig, kein Push ausgeloest.

- Nach Commit 20 erneut ausgefuehrt: `teebotus.service` `active/running`,
  PID `449932`, Start `2026-07-16 04:47:43 CEST`, Runtime-Version `1.9.498`.
  `/v1/about` meldet Signal REST `0.100` im JSON-RPC-Modus;
  `--runtime-status` meldet Signal erreichbar, Qdrant `ready` und alle
  Account-Crypto-/Memory-Pruefungen `ok`. HF-Pool bleibt deaktiviert und
  wird laut Status lokal ueber Ollama ersetzt; kein Provider-Testaufruf.

- Nach Commit 20 dieses Auditblocks: `teebotus.service` `active/running`,
  PID `1705677`, Start `2026-07-16 11:26:21 CEST`. Providerfreier
  `--runtime-status` meldet Signal `reachable`, Qdrant `ready` und alle
  Account-Crypto-/Memory-Pruefungen `ok`. HF-Pool bleibt deaktiviert,
  GROQ-Key fehlt; beides sind bestehende Konfigurationszustaende. Kein
  Provider/API-Aufruf.

- Nach Commit 20 dieses Auditblocks erneut ueber die aktive User-Unit
  `teebotus.service` neugestartet: `active/running`, PID `96400`,
  `ActiveEnterTimestamp=2026-07-16 13:48:49 CEST`. Die erste unmittelbare
  Statusprobe sah Signal noch im Start-Rennen als `connection refused`;
  Folgeprobe nach Bereitschaft meldete beide Signal-Services `reachable` und
  beide Accounts `registered`. Qdrant blieb `ready`; kein Provider/API-
  Aufruf. Die systemweite Unit blieb erwartungsgemaess unbeteiligt.

**Laufstand nach Restart:** Seit dem Restart `1/20` Commits; kein Push
ausgeloest. Naechster Restart nach 19 weiteren Commits.

### Collection-Diagnose-nach-Item-Replacement-zuruecksetzen

- 2026-07-16: `replace_collection_item()` schrieb erfolgreiche Status- und
  Outbox-Updates in SQLite und PostgreSQL, loeschte aber keine vorherige
  `last_collection_read_error`-, Skip- oder Database-Missing-Diagnose. Ein
  alter Fehler konnte dadurch nach erfolgreicher Reparatur weiter im
  Healthcheck erscheinen.
- SQLite und PostgreSQL setzen Collection-Diagnosen nur nach einer wirklich
  ersetzten Zeile zurueck. Ungueltige Keys, nicht gefundene Zeilen und
  Write-Fehler behalten ihre Diagnose unveraendert.
- Regression fuer SQLite-Replacement mit vorheriger stale Diagnose;
  gesamte `tests/test_account_store.py`: `271 passed`; Ruff, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `dd017f53 fix: clear collection diagnostics after replacement`.

**Laufstand nach Fix:** Seit dem Restart `11/20` Commits; kein Push
ausgeloest. Naechster Restart nach 9 weiteren Commits.

### Fallback-Mirror-Fehler-bei-Item-Replacement-sichtbar-machen

- 2026-07-16: Der Fallback-Router ignorierte `False` vom sekundären
  `replace_collection_item()`. Wenn Primary die Zeile erfolgreich ersetzte,
  sie im Fallback aber fehlte, wurde kein Fehlerzustand gesetzt; beide
  Datenbanken konnten dadurch unbemerkt auseinanderlaufen.
- Nach erfolgreichem Primary-Replacement wird ein fehlender Fallback-Artikel
  jetzt als `stale` und `sync_failed` markiert und periodisch gewarnt. Ein
  normales `False` vom Primary bleibt unveraendert ein „nicht gefunden“ ohne
  falschen Sync-Fehler.
- Regression mit vorhandenem Primary-Artikel und leerem Fallback; gesamte
  `tests/test_account_store.py`: `272 passed`; Ruff, `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e2da0666 fix: flag missing fallback replacement mirrors`.

**Laufstand nach Fix:** Seit dem Restart `13/20` Commits; kein Push
ausgeloest. Naechster Restart nach 7 weiteren Commits.

### Keine-partiellen-Primary-Rows-in-stale-Fallback-spiegeln

- 2026-07-16: Der stale-Repair fuer `replace_collection_item()` las die
  komplette Collection aus Primary und schrieb sie direkt in den Fallback.
  Bei einem partiellen Primary-Read konnten gueltige Fallback-Rows dadurch
  geloescht werden.
- Mirror-Reparaturen validieren den Quell-Read jetzt ueber Read-Error und
  Skip-Diagnosen. Bei nicht sauberem Read wird keine Fallback-Collection
  geschrieben; stale/sync-failed bleibt aktiv und erzwingt spaetere Reparatur.
- Regression mit erfolgreichem Primary-Replacement, partieller Primary-Read-
  Diagnose und unveraendertem Fallback; gesamte `tests/test_account_store.py`:
  `273 passed`; Ruff, `py_compile` und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `d36df6c7 fix: block partial fallback mirror repairs`.

**Laufstand nach Fix:** Seit dem Restart `15/20` Commits; kein Push
ausgeloest. Naechster Restart nach 5 weiteren Commits.

### Keine-partiellen-Primary-Rows-in-stale-Fallback-Append-spiegeln

- 2026-07-16: Der stale-Repair fuer `append_collection_items()` hatte
  denselben unsicheren Voll-Read wie der Replace-Pfad. Ein partieller
  Primary-Read konnte beim Append-Repair komplette gueltige Fallback-Daten
  ueberschreiben.
- Append-Repairs validieren den Quell-Read jetzt ebenfalls vor dem Write.
  Auch der generische Backend-Fallback ohne native Append-Methode nutzt den
  sauberen Collection-Read; Diagnose bedeutet Sync-Fehler statt Datenverlust.
- Regression mit stale Fallback und partieller Primary-Read-Diagnose; gesamte
  `tests/test_account_store.py`: `274 passed`; Ruff, `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `77120ba3 fix: guard partial fallback append repairs`.

**Laufstand nach Fix:** Seit dem Restart `17/20` Commits; kein Push
ausgeloest. Naechster Restart nach 3 weiteren Commits.

### Direkten-Codex-Outbox-Replacement-Guarden

- 2026-07-16: `replace_codex_history_outbox_item()` rief das Backend direkt
  auf und umging damit den bestehenden Collection-Diagnose-Guard. Ein
  vorheriger Decrypt- oder Skip-Fehler konnte so zu einem destruktiven
  Outbox-Write fuehren.
- Der direkte Codex-Replacement-Pfad prueft jetzt vor dem Backend-Aufruf
  `last_collection_read_error`, Skip-Count und Database-Missing-Zustand.
  Bei unlesbarer Collection bleibt Backend unveraendert.
- Regression beweist Abbruch vor Backend-Aufruf; gesamte
  `tests/test_account_store.py`: `275 passed`; Ruff, `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `dd6e2476 fix: guard direct codex outbox replacement`.

**Laufstand nach Fix:** Seit dem Restart `19/20` Commits; kein Push
ausgeloest. Naechster Code-Commit loest Restart aus.

### Keine-divergente-Fallback-Zeile-bei-Primary-Miss-mutieren

- 2026-07-16: Bei `replace_collection_item()` durfte Primary `False`
  zurueckgeben, waehrend Fallback eine zusaetzliche gleichnamige Zeile
  besass. Der Router konnte diese Fallback-Zeile dann trotzdem aktualisieren
  und den Unterschied ohne Warnung bestehen lassen.
- Wenn Primary die Zeile nicht findet, prueft der Router Fallback vor einer
  Mutation. Eine widerspruechliche Extra-Zeile wird nicht veraendert und
  erzeugt `stale`/`sync_failed`; wenn beide Seiten die Zeile nicht haben,
  bleibt `False` ein normaler Nichtgefunden-Fall.
- Regression mit leerem Primary und vorhandener Fallback-Zeile; gesamte
  `tests/test_account_store.py`: `276 passed`; Ruff, `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `69f28aa2 fix: prevent divergent fallback replacements`.

**Laufstand vor Restart:** `20/20` Commits seit letztem Restart; kein Push.

- Danach `systemctl --user restart teebotus.service`: `active/running`,
  PID `191417`, Start `2026-07-16 14:17:38 CEST`.
- Providerfreier `--runtime-status` nach Bereitschaft: Signal beide
  Accounts `reachable` und `registered`, Qdrant `ready`, Account-Crypto und
  Memory `ok`. HF-Pool deaktiviert, GROQ-Key fehlt und Depressionsbot-Signal
  hat weiterhin keine verknuepfte Signal-Identitaet; bestehende Hinweise,
  kein Provider/API-Aufruf.

**Laufstand nach Restart:** Seit dem Restart `1/20` Commits; kein Push
ausgeloest. Naechster Restart nach 19 weiteren Commits.

### Direkte-Structured-Memory-Writes-vor-partial-Reads-schuetzen

- 2026-07-16: `write_memory_entries()` und `write_memory_index()` konnten
  SQL-Inhalte direkt vollstaendig ersetzen, ohne die aktuellen Entry-/Index-
  Read-Diagnosen zu pruefen. Ein direkter Aufrufer konnte damit korrupte oder
  partiell gelesene Memorys ueberschreiben.
- Beide Pfade pruefen jetzt vor Backend-Write auf Decrypt-Fehler und Skips;
  eine wirklich fehlende, noch nicht initialisierte SQLite-DB bleibt als
  sauberer Erstwrite zulaessig. SQLite/PostgreSQL loeschen beim ersten
  erfolgreichen Write nach DB-Initialisierung auch bereinigte Missing-DB-
  Diagnosen aus anderen Teilbereichen.
- Regression fuer direkte Write-Blockade und frische SQLite-Initialisierung;
  gesamte `tests/test_account_store.py`: `277 passed`; Ruff, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `294ea77b fix: guard direct memory writes`.

**Laufstand nach Fix:** Seit dem Restart `3/20` Commits; kein Push
ausgeloest. Naechster Restart nach 17 weiteren Commits.

### SQLite-Backup-gegen-verschwindende-WAL-Sidecars-haerten

- 2026-07-16: Backup-Sync sammelte SQLite-Hauptdatei, `-wal` und `-shm`
  zuerst als Dateifamilie und kopierte danach. SQLite kann Sidecars zwischen
  diesen beiden Schritten checkpointen oder loeschen; ein verschwundenes
  Sidecar brach den gesamten Backup-Sync mit `FileNotFoundError` ab.
- Sidecar-Kopien sind jetzt best-effort. Verschwindendes `-wal`/`-shm` wird
  uebersprungen; verschwindende Hauptdatei bleibt fatal. Backup-Zaehler
  entspricht tatsaechlich kopierten Dateien.
- Regression simuliert verschwundenes Sidecar; `tests/test_sqlite_backup_sync.py`:
  `12 passed`; Ruff, `py_compile` und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `dd9cb882 fix: tolerate disappearing sqlite sidecars`.

**Laufstand nach Fix:** Seit dem Restart `4/20` Commits; kein Push
ausgeloest. Naechster Restart nach 16 weiteren Commits.

### Recovery-Report-Instanz-State-Account-ausfiltern

- 2026-07-16: Recovery-Report filterte die zentrale
  `INSTANCE_STATE_ACCOUNT_ID` beim SQL-Account-Scan, nahm denselben
  Instanz-State-Account aber aus dem JSON-`accounts/`-Verzeichnis als
  normalen User auf. Reports konnten dadurch falsche Account-Anzahlen und
  Recovery-Eintraege zeigen.
- JSON- und SQL-Discovery schliessen zentrale Instanz-State-ID jetzt gleich
  aus. Bestehende User-Account-Verzeichnisse bleiben unveraendert.
- Regression `test_memory_recovery_report_counts_sqlite_collections_and_skips_instance_state_account` gruen;
  Ruff und `py_compile` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a3bec7ee fix: exclude instance state from recovery accounts`.

**Laufstand nach Fix:** Seit dem Restart `6/20` Commits; kein Push
ausgeloest. Naechster Restart nach 14 weiteren Commits.

## Bezug

- Vorheriger Plan:
  `Baupläne/Bauplan-Aktueller-Plan-Logikpruefung-2026-07-15.md`
- Aktueller Arbeitsbaum: `/home/teladi/TeeBotus`

### Admin-Status-Remote-IDs-nicht-als-lokal-anlegen

- 2026-07-16: Der Kandidatenpfad fuer Runtime-Status-Admins las den
  Opt-out-State fuer jede konfigurierte ID. Der Account-Memory-Lock legt beim
  Lesen das Account-Verzeichnis an. Eine nur remote vorhandene Admin-ID wurde
  dadurch als lokaler Phantom-Account erkannt; Status wurde als
  `route:...:AccountStoreError` statt `not_local` gemeldet.
- Opt-out wird jetzt nur fuer bereits lokale Account-Verzeichnisse gelesen.
  Remote konfigurierte IDs bleiben fuer den Cross-Instance-Route-Scan
  sichtbar, erzeugen aber keine lokale Memory-Struktur.
- Regression: vier Admin-Status-/Notify-Tests gruen; zusaetzlicher Assert
  bestaetigt, dass keine Phantom-Directory entsteht. Ruff, `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `4cca4082 fix: avoid phantom remote admin accounts`.

**Laufstand nach Fix:** Seit dem Restart `8/20` Commits; kein Push
ausgeloest. Naechster Restart nach 12 weiteren Commits.

### Debug-Level-Nutzerhinweis

- 2026-07-16: Der Planpunkt war bisher nicht umgesetzt: Log-Level-Parsing
  existierte, aber Nutzer bekamen keinen Hinweis auf moegliche Einsicht in
  Nachrichteninhalte durch Debug-/Diagnosepfade.
- Level `1`, `2`, `debug_all`, `debug-all`, `all` und `finest` aktivieren jetzt
  eine Warnung. Sie wird pro Account und Kanal einmal je Engine-Prozess vor
  der ersten echten Antwort gesendet. TBL bleibt vor erfolgreicher
  Status-Authentifizierung durch das fruehe Gate stumm.
- Kein globaler Push an inaktive Accounts: Die channel-neutrale Engine kennt
  keine vollstaendige Senderliste. Aktive Nutzer werden beim naechsten
  beantworteten Turn informiert; Gruppen erhalten denselben sichtbaren
  Hinweis.
- Regression: `tests/test_runtime_maintenance.py` und
  `tests/test_engine_identity_flows.py` -> `341 passed`; `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c52d7250 fix: warn users about debug message visibility`.

**Aktueller Laufstand:** Seit dem letzten Restart `19/20` Commits. Kein Push.
Naechster Restart nach einem weiteren Commit.

### LLM-Proactive-Planer-keine-veralteten-Termine

- 2026-07-16: Der LLM-Proactive-Queue-Pfad uebernahm `due_at` ungeprueft.
  Vergangene oder nicht parsebare Zeitpunkte konnten so als queued Outbox
  landen und beim naechsten Dispatcher-Lauf sofort versendet werden.
- Vor dem Outbox-Write werden explizite LLM-Zeitpunkte jetzt validiert:
  parsebar und strikt in der Zukunft. Fehler werden als
  `invalid_due_at` oder `due_at_not_future` abgelehnt.
- Regression mit `2023-03-16T17:47:00+00:00` und kaputtem Text-Zeitpunkt;
  `tests/test_proactive_agent.py` -> `120 passed`; `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e7bcea07 fix: reject stale proactive planner reminders`.

**Aktueller Laufstand:** Seit dem Restart `0/20` Commits. Kein Push.
Naechster Restart nach 20 weiteren Commits.

### Proactive-Default-Zeit-in-Userzeitzone

- 2026-07-16: `_default_proactive_due_at()` setzte automatische Folge-
  erinnerungen auf `10:00` in UTC. Bei konfigurierter Europe/Berlin-Zeit
  wurde dadurch lokal `11:00` oder `12:00` geplant.
- Default-Folgezeit wird jetzt zuerst mit `to_local()` in die konfigurierte
  Userzeitzone umgerechnet und danach auf lokalen Folgetag `10:00` gesetzt.
- Regression im LLM-Plan-Test erwartet `2026-06-16T10:00:00+02:00`;
  `tests/test_proactive_agent.py` -> `120 passed`; `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `863985ee fix: schedule proactive defaults in local time`.

**Aktueller Laufstand:** Seit dem Restart `2/20` Commits. Kein Push.
Naechster Restart nach 18 weiteren Commits.
