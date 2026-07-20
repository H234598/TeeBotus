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
  letzten Restart sind aktuell `19/20` Code-Commits vorhanden; naechster
  Restart nach 1 weiterem Plan-Commit.

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
  `Abgeschlossene Baupläne/Bauplan-Aktueller-Plan-Logikpruefung-2026-07-15.md`
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

### Reminder-Monatsnamen-nicht-als-Monatsnummer-verwechseln

- 2026-07-16: Parser verstand bisher nur numerische Daten. Bei
  `10. Mai um 14:30` griff dadurch `MONTH_DAY_RE`: Ergebnis wurde 10. des
  naechsten Monats um 09:00; `16. Maerz 2027` verlor Jahr und Uhrzeit.
- Deutsche Monatsnamen und Kurzformen werden jetzt mit optionalem Jahr und
  Uhrzeit geparst. Invalides Datum bleibt ohne Fallback auf einen anderen
  Monat; Subject entfernt Datum vollstaendig.
- Regression: `tests/test_reminder_intent.py` -> `27 passed`; Engine-Contract
  plus Modul -> `28 passed`; `py_compile` und `git diff --check` gruen.
  Kein Provider/API-Aufruf.
- Code-Commit: `7c259cb9 fix: parse German reminder month names`.

**Aktueller Laufstand:** Seit dem Restart `4/20` Commits. Kein Push.
Naechster Restart nach 16 weiteren Commits.

### Memory-Konsolidierung-inkrementell-und-retry-sicher

- 2026-07-16: Der Audit reproduzierte zwei zusammenhaengende Fehler in
  `consolidate_structured_memory()` und `run_memory_maintenance()`. Eine
  vierte Episode mit gleichem Keyword erzeugte eine zweite Summary statt die
  vorhandene Provenienz zu erweitern. Ein Rebuild-Fehler nach erfolgreicher
  Konsolidierung liess die Summary ebenfalls liegen; der Retry erzeugte dann
  ein Duplikat.
- Konsolidierungs-Fingerprints basieren jetzt auf kanonisch sortierten Source-
  IDs. Bestehende Summarys werden ueber `consolidation_key` oder ihr bisheriges
  Summary-Format erkannt und bei neuen Episoden in place aktualisiert. Der
  Index wird danach rebuildet; bei Schreib-/Rebuildfehlern wird der komplette
  alte Entries-/Indexstand wiederhergestellt.
- `run_memory_maintenance()` rebuildet zuerst und konsolidiert erst danach.
  Damit bleibt ein fehlgeschlagener Rebuild ohne neue Summarywirkung und ein
  Retry ist idempotent.
- Regressionen: inkrementelles Summary-Update und Rebuild-Fehler mit Retry;
  `tests/test_account_store.py` fokussiert `5 passed`, komplette Suite
  `279 passed in 7.04s`; Ruff, `py_compile` und `git diff --check` gruen.
  Kein Provider/API-Aufruf.
- Code-Commits: `7919d4d3 fix: update repeated memory consolidations`,
  `a5e7b944 fix: make memory maintenance retry safe`.

**Aktueller Laufstand:** Seit dem Restart `7/20` Code-Commits. Dieser
Plan-Commit macht `8/20`; kein Push. Naechster Restart nach 12 weiteren
Commits.

### Proactive-Reflection-Fingerprint-Race

- 2026-07-16: Der Reflection-Planner pruefte vorhandene Fingerprints und
  schrieb danach in mehreren einzelnen, verschachtelten Store-Aufrufen.
  Zwei gleichzeitig gestartete Scheduler-Laeufe konnten denselben Fingerprint
  sehen und dadurch neun Plan-Memories sowie einen Outbox-Eintrag doppelt
  erzeugen.
- Der oeffentliche Planner haelt jetzt `account_memory_lock(account_id)` ueber
  den kompletten Check-/Write-Ablauf. Die bestehenden Store-Locks bleiben fuer
  einzelne Aufrufe erhalten und sind reentrant.
- Regression mit zwei parallelen Threads: zusammen genau ein Outbox-Item und
  neun Plan-Memories; kompletter `tests/test_proactive_agent.py`-Lauf ->
  `121 passed`. Ruff, `py_compile` und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `8506e161 fix: serialize proactive reflection planning`.

**Aktueller Laufstand:** Seit dem Restart `9/20` Code-Commits. Dieser
Plan-Commit macht `10/20`; kein Push. Naechster Restart nach 10 weiteren
Commits.

### Proactive-Rezidiv-Intervalle-nach-Langverzug

- 2026-07-16: `_next_recurrence_due_at()` begrenzte das Nachholen faelliger
  Wiederholungen auf `366` Schleifendurchlaeufe. Bei `every 5 minutes` und
  laengerem Dispatcher-Ausfall wurde deshalb keine naechste Wiederholung mehr
  geplant; der Reminder verschwand nach dem ersten Versand aus dem Zyklus.
- Feste Intervalle (`daily`, `weekly`, `every N minutes|hours|days|weeks`)
  berechnen jetzt direkt den naechsten Zeitpunkt strikt nach `sent_at`. Monats-
  und Werktagsregeln laufen bis zum naechsten zukuenftigen Zeitpunkt weiter
  und brechen nur bei nicht fortschreitender/ungueltiger Regel ab.
- Regression mit Januar-bis-Juli-Verzug: 5-Minuten-, 2-Stunden- und Tages-
  intervalle; kompletter `tests/test_proactive_agent.py`-Lauf -> `122 passed`.
  Ruff, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `ac7a092d fix: preserve delayed proactive recurrences`.

**Aktueller Laufstand:** Seit dem Restart `11/20` Code-Commits. Dieser
Plan-Commit macht `12/20`; kein Push. Naechster Restart nach 8 weiteren
Commits.

### Proactive-Risiko-Validitaetsfenster

- 2026-07-16: `_risk_memory_is_active()` pruefte `valid_to` zuerst. Ein
  Risikosignal mit zukuenftigem `valid_from` und zukuenftigem `valid_to` galt
  dadurch vor seinem Start bereits als aktiv und blockierte Analyse, Tests,
  Reflection und Bilder.
- `valid_from` wird jetzt zuerst ausgewertet; zukuenftige Signale sind nicht
  aktiv. Danach entscheidet `valid_to`; ohne Zeitfenster bleibt der bisherige
  30-Tage-Lookback erhalten.
- Regression: zukuenftiges Fenster vor Start und genau zum Start; kompletter
  `tests/test_proactive_agent.py`-Lauf -> `123 passed`. Ruff, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `9f45edcc fix: respect proactive risk validity start`.

**Aktueller Laufstand:** Seit dem Restart `13/20` Code-Commits. Dieser
Plan-Commit macht `14/20`; kein Push. Naechster Restart nach 6 weiteren
Commits.

### Proactive-State-Setter-Read-Modify-Write

- 2026-07-16: `enable`, `disable`, `pause`, `resume`, Kategorien-, Zeitfenster-
  und Intervall-Setter lasen Agent-State ausserhalb eines gemeinsamen Locks
  und schrieben danach. Gleichzeitige Befehle aus mehreren Adaptern konnten
  dadurch die jeweils andere Aenderung verlieren.
- Alle sieben State-Setter halten jetzt `account_memory_lock(account_id)` um
  den kompletten Read-Normalize-Write-Ablauf. Der darunterliegende Write-Lock
  bleibt reentrant.
- Regression mit paralleler Kategorien-/Zeitfenster-Aenderung: Read-
  Parallelitaet bleibt `1`, beide Aenderungen sind im Endzustand vorhanden;
  kompletter `tests/test_proactive_agent.py`-Lauf -> `124 passed`. Ruff,
  `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `9861716a fix: serialize proactive state updates`.

**Aktueller Laufstand:** Seit dem Restart `15/20` Code-Commits. Dieser
Plan-Commit macht `16/20`; kein Push. Naechster Restart nach 4 weiteren
Commits.

### Proactive-Lock-Reihenfolge

- 2026-07-16: Der neue Planner-Account-Lock wurde gegen bestehende
  Outbox-Pfade geprueft. Diese verwenden `Outbox -> Memory`; ein Planner in
  `Memory -> Outbox`-Reihenfolge haette bei parallelem Queue-Schreiben
  deadlocken koennen.
- Reflection-Planner verwendet jetzt ebenfalls `Outbox -> Memory`. Nested
  Store-Locks bleiben reentrant; alle Read-/Write-Rennen bleiben serialisiert.
- Regressionen Planner/Setter -> `7 passed`; Ruff, `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `aae8371a fix: preserve proactive lock ordering`.

**Aktueller Laufstand:** Seit dem Restart `17/20` Code-Commits. Dieser
Plan-Commit macht `18/20`; kein Push. Naechster Restart nach 2 weiteren
Commits.

### Reminder-Numerisches-Datum-mit-Abschlusspunkt

- 2026-07-16: `DATE_RE` beendete ein deutsches Datum ohne Jahr bei
  `16.03.` vor der Uhrzeit. In `16.03. um 17:47` blieb der Punkt liegen;
  der Parser fiel auf Default `09:00` zurueck und verlor die explizite Zeit.
- Numerische Datumswerte akzeptieren jetzt optionalen Abschlusspunkt sowohl
  mit als auch ohne Jahr. Subject-Bereinigung nutzt dieselbe Regex weiter.
- Regression mit `16.03.2027. um 17:47` und `16.03. um 17:47`: Reminder-Suite
  `28 passed`, relevante Engine-Tests `3 passed`; Ruff, `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `9cb68bf9 fix: parse dotted numeric reminder dates`.

**Aktueller Laufstand:** Seit dem Restart `19/20` Code-Commits. Dieser
Plan-Commit macht `20/20`; kein Push. Restart jetzt faellig. Naechster
Push bleibt erst bei 100 Commits.

### Notification-Loudness-Dispatch-Race

- 2026-07-16: `notification_loudness_outbox_item_is_active()` las State und
  aktuelle Route ohne denselben Outbox-Lock wie Antwort- und Dispatch-Pfade.
  Eine Bestaetigung konnte deshalb zwischen Active-Check und Versand den
  Status aendern; ein bereits gecanceltes Item konnte noch extern gesendet
  werden.
- Der Active-Check laeuft jetzt unter dem Account-Outbox-Lock. Ein Worker-
  Claim (`dispatching`) gilt als bereits uebernommener Versand: Antworten
  canceln nur noch `queued`. Der Active-Recheck entscheidet damit sauber, ob
  die Bestaetigung vor oder nach dem Claim linearisiert wird; kein Versand aus
  einem danach als `cancelled` gespeicherten Zustand.
- Regression deckt beide Reihenfolgen ab: Antwort vor Recheck blockiert den
  Versand; Antwort nach Recheck laesst den uebernommenen Versand konsistent
  als `sent` abschliessen. `tests/test_notification_loudness.py` -> `165
  passed`; Ruff, `compileall` und `git diff --check` gruen. Kein Provider/API-
  Aufruf.
- Code-Commit: `18005ca7 fix: linearize notification loudness dispatch`.

**Aktueller Laufstand:** Seit dem Restart `1/20` Code-Commits. Dieser
Plan-Commit macht `2/20`; kein Push. Naechster Restart nach 18 weiteren
Commits. Naechster Push bleibt erst bei 100 Commits.

### Reminder-Named-Date-Late-Hour

- 2026-07-16: Die Stundenalternative im gemeinsamen Reminder-RegEx begann
  mit `[01]?\d`. Bei `23:59` gewann deshalb der einstellige Praefix `2`; ein
  named-date Reminder wie `31. Dezember um 23:59` wurde als `02:00` gespeichert.
- `_CLOCK_HOUR` prueft jetzt `2[0-3]` zuerst und erzwingt danach eine
  Nicht-Ziffer. Dadurch werden `23:59` und alle anderen Spaetstunden vollstaendig
  gelesen; `25:00` wird nicht als `2:00` still fehlinterpretiert, sondern als
  ungueltige explizite Zeit abgelehnt.
- Regression: gueltiges `31. Dezember um 23:59` sowie ungueltiges `25:00`;
  Reminder-Suite `30 passed`, Reminder-/Decision-Suite `59 passed`; Ruff,
  `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `6eac9d0b fix: parse late reminder hours correctly`.

**Aktueller Laufstand:** Seit dem Restart `3/20` Code-Commits. Dieser
Plan-Commit macht `4/20`; kein Push. Naechster Restart nach 16 weiteren
Commits. Naechster Push bleibt erst bei 100 Commits.

### Reminder-Subject-Datumsfalse-Positive

- 2026-07-16: Absolute Datumsregexe wurden auch im Subject ausgewertet.
  `morgen um 9 an 1.5 Liter Wasser` wurde dadurch als `01.05.` interpretiert;
  `morgen um 9 an Version 2026-06-01` wurde wegen eines vergangenen ISO-Datums
  komplett verworfen. Beide Nutzerwunsch-Termine waren falsch.
- Numeric-, ISO- und Monatsnamen-Daten hinter einem Subject-Marker `an` gelten
  jetzt nicht mehr als Zeitanker, ausser die Datumsangabe beginnt explizit mit
  `am`. Die Subject-Bereinigung bewahrt solche Decimal-/ISO-/Monatstexte.
  Explizite Formen wie `am 16.03.2027` und `am 1. um 10` bleiben aktiv.
- Regression: Decimal- und ISO-Subject plus explizite Datum- und Monatsfälle;
  Reminder-/Decision-Suite `61 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `ab1c79bb fix: ignore subject dates in reminder parsing`.

**Aktueller Laufstand:** Seit dem Restart `5/20` Code-Commits. Dieser
Plan-Commit macht `6/20`; kein Push. Naechster Restart nach 14 weiteren
Commits. Naechster Push bleibt erst bei 100 Commits.

### Bibliothekar-Decision-Fallback

- 2026-07-16: `build_runtime_structured_decision_runner()` liefert bei
  Provider-, Modell- oder Schemafehlern bewusst `None`. Die
  `BibliothekarQueryDecision` behandelte diesen Wert bisher wie den alten
  "kein Runner konfiguriert"-Fall und suchte deshalb jede normale Nachricht.
  Dadurch konnten irrelevante Bibliotheks-Chunks in den Hauptprompt gelangen.
- Ein vorhandener, aber fehlgeschlagener Structured-Runner faellt jetzt
  geschlossen ohne Bibliothekskontext zurueck. Explizite klassische Begriffe
  wie Buch, Quelle, Zitat oder Bibliothek werden weiterhin vor dem Runner
  erkannt und direkt gesucht. Der alte "kein Runner vorhanden"-Fallback bleibt
  fuer kompatible Installationen unveraendert.
- Regressionen: `tests/test_pydantic_decisions.py`
  und `tests/test_bibliothekar.py` zusammen -> `126 passed`; Ruff fuer
  betroffene Produktions-/Decision-Dateien, `compileall` und `git diff --check`
  gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c595ee00 fix: fail closed on library decision errors`.

**Aktueller Laufstand:** Seit dem manuellen Restart `5/20` Commits inklusive
Dokumentationscommit. Kein Push. Naechster manueller Restart nach 15 weiteren
Commits; naechster Push bleibt bei 100 Commits.

### Secret-Service-Retry

- 2026-07-16: `runtime_secret_provider()` konfigurierte zwar sechs Lookups,
  aber `SecretToolInstanceSecretProvider._lookup_with_retries()` wiederholte
  nur leere Lookup-Ergebnisse. Timeout, Secret-Service-Neustart oder ein
  kurzfristig nicht startbares `secret-tool` brachen beim ersten Versuch ab.
- Solche Transportfehler haben jetzt einen eigenen internen Fehlerpfad und
  werden bis zur konfigurierten Retrygrenze erneut versucht. Der interne
  Cooldown wird zwischen diesen Versuchen aufgehoben; die bestehende
  Schonung direkter Einzelaufrufe bleibt erhalten. Fehlende Secrets,
  ungueltige Schluessel und mehrdeutige Secret-Service-Eintraege werden nicht
  als transient behandelt.
- Regression: AccountStore-Suite -> `280 passed`; Runtime-Admin-/Codex-
  Secret-Suiten -> `199 passed`; Ruff, `compileall` und `git diff --check`
  gruen. Kein Provider/API-Aufruf.
- Code-Commit: `b3f43f95 fix: retry transient secret service failures`.

**Aktueller Laufstand:** Seit dem manuellen Restart `7/20` Commits inklusive
Dokumentationscommit. Kein Push. Naechster manueller Restart nach 13 weiteren
Commits; naechster Push bleibt bei 100 Commits.

### Telegram-RemoteDisconnect

- 2026-07-16: `RemoteDisconnected` aus `urllib` wurde beim Telegram-
  Polling nicht als `TelegramNetworkError` behandelt. Ein kurzzeitiger
  Verbindungsabbruch beendete deshalb den Hauptprozess; systemd musste ihn
  erst neu starten.
- Normale Requests, Multipart-Uploads und Datei-Downloads wandeln sonstige
  `OSError`-Netzwerkfehler jetzt nach `URLError` in `TelegramNetworkError`
  um. Der vorhandene Polling-Backoff greift dadurch auch bei vom Peer
  geschlossenen Verbindungen.
- Regression: `RemoteDisconnected` ohne Telegram-Aufruf sowie Timeout und
  Polling-Retry -> `3 passed`; Ruff, `compileall` und `git diff --check`
  gruen. Kein Provider/API-Aufruf.
- Code-Commit: `551e1479 fix: retry Telegram disconnects as network errors`.
- Der Dienst ist aktuell `active`, MainPID `514461`, nachdem systemd den
  vor dem Fix abgebrochenen Prozess automatisch neu gestartet hat.

**Aktueller Laufstand:** Seit dem manuellen Restart `2/20` Commits. Dieser
Plan-Commit macht `3/20`; kein Push. Naechster manueller Restart nach 17
weiteren Commits. Naechster Push bleibt erst bei 100 Commits.

### Wetter-Rate-Limit-und-Uhrsprung

- 2026-07-16: Das Wetter-Rate-Limit behandelte einen zukuenftigen
  `last_checked_at` als gueltigen Cache. Nach Uhrkorrektur oder korruptem
  Zeitstempel konnte der naechste externe Wettercheck bis zum alten
  Zukunftszeitpunkt blockiert bleiben.
- Rate-Limit gilt jetzt nur noch bei `0 <= elapsed < 2 Stunden`. Zukuenftige
  Zeitstempel loesen wieder einen Check aus; vorhandene Stadt- und
  Fehlerbehandlung bleibt unveraendert.
- Regression: zukuenftiger Wetterzeitstempel blockiert Recheck nicht;
  `tests/test_weather_context.py` -> `10 passed`. Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `064f86af fix: recover weather checks after clock rollback`.

**Aktueller Laufstand:** Seit dem Restart `18/20` Code-Commits. Dieser
Plan-Commit macht `19/20`; kein Push. Naechster Restart nach 1 weiterem
Commit. Naechster Push bleibt erst bei 100 Commits.

### Gemini-Free-Tier-Uhrsprung

- 2026-07-16: `GeminiFreeTierGuard` setzte RPM-/TPM- und RPD-Budget bei
  jedem anderen Zeit-Bucket zurueck. Eine rueckwaerts korrigierte Systemuhr
  konnte dadurch bereits verbrauchte Free-Tier-Anfragen erneut freigeben.
- Minute- und Tagesbucket wechseln jetzt nur vorwaerts. Bei Ruecksprung
  bleiben alte Zaehler aktiv; der Guard bleibt konservativ und gibt keine
  Zusatzanfragen frei.
- Regression: Vorwaertswechsel setzt Tagesbudget korrekt neu, Ruecksprung
  bleibt blockiert; Free-Tier-Fokus -> `3 passed`. Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `0b418e79 fix: preserve Gemini budgets across clock rollback`.
- Nach dem 20. Commit seit dem vorherigen Lauf wurde `teebotus.service`
  neu gestartet. Status `active`, MainPID `504988`, Exit `0`, Start
  `2026-07-16 20:39:19 CEST`.

**Aktueller Laufstand:** Seit dem Restart `0/20` Commits. Dieser
Plan-Commit ist der erste Commit des neuen Laufs; kein Push. Naechster
Restart nach 19 weiteren Commits. Naechster Push bleibt erst bei 100
Commits.

### Proactive-Tageslimit-bei-Wiederholungen

- 2026-07-16: Nach erfolgreichem Versand wird eine wiederkehrende Erinnerung
  als dieselbe `queued`-Outbox-Zeile mit neuem `due_at` weitergefuehrt. Die
  Tageszaehlung bevorzugte jedoch altes `sent_at` und uebersah dadurch die
  naechste faellige Wiederholung als Tagesreservierung.
- Die Zaehllogik nutzt fuer `sent` den Versandtag, fuer `queued` und
  `dispatching` den Faelligkeitstag; bei wiederkehrenden Zeilen wird der
  aktuelle Versandtag zusaetzlich beruecksichtigt. Damit blockiert eine
  faellige Wiederholung keine weitere Nachricht zu spaet.
- Regression: Wiederholungszeile mit Folgetermin am aktuellen Tag blockiert
  zweite Nachricht bei `max_messages_per_day=1`; Fokus -> `4 passed`; Ruff,
  `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `887c85cb fix: count recurring reminders in daily limits`.

**Aktueller Laufstand:** Seit dem Restart `10/20` Code-Commits. Dieser
Plan-Commit macht `11/20`; kein Push. Naechster Restart nach 9 weiteren
Commits. Naechster Push bleibt erst bei 100 Commits.

### Proactive-Pause-als-harte-Planner-Grenze

- 2026-07-16: `/proactive pause` blockierte Queue/Dispatch, aber Reflection-,
  LLM- und Tool-Planner prueften nur `enabled`. Pausierte Accounts konnten
  deshalb weiter Provideraufrufe ausloesen und direkte LLM-Plan-Anwendung
  konnte interne Planner-Memories schreiben.
- Pause wird jetzt vor allen Plannerpfaden geprueft: Reflection liefert
  `proactive_paused`, Modell-/Tool-Planner rufen keinen Client auf, der
  Scheduler startet keinen Modellplaner und direkte LLM-Plan-Anwendung wird
  abgewiesen. `resume` hebt die Grenze weiterhin auf.
- Regression: alle Plannerpfade plus direkte Anwendung mit Client-Assertions;
  Fokus -> `12 passed`; Ruff, `compileall` und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `ea996b93 fix: honor proactive pause in planners`.

**Aktueller Laufstand:** Seit dem Restart `12/20` Code-Commits. Dieser
Plan-Commit macht `13/20`; kein Push. Naechster Restart nach 7 weiteren
Commits. Naechster Push bleibt erst bei 100 Commits.

### Notification-Loudness-Zeitmetadaten

- 2026-07-16: `queue_due_notification_loudness_prompts(now=...)` schrieb
  Route-State mit dem gelieferten Zeitpunkt, aber Outbox-Erstellung und
  Statushistorie mit `utc_now()`. Replays, Healthchecks und Tests konnten
  dadurch widerspruechliche Zeitachsen sehen.
- System-Prompts schreiben `created_at`, `updated_at`, `due_at` und ersten
  `status_history.at` jetzt aus demselben aufgeloesten `now`.
- Regression: deterministischer Scheduler-Zeitpunkt bleibt in allen vier
  Metadatenfeldern; Scheduler/Outbox-Fokus -> `25 passed`; Ruff,
  `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `2205b449 fix: preserve loudness prompt timestamps`.

**Aktueller Laufstand:** Seit dem Restart `14/20` Code-Commits. Dieser
Plan-Commit macht `15/20`; kein Push. Naechster Restart nach 5 weiteren
Commits. Naechster Push bleibt erst bei 100 Commits.

### Status-Gemini-Service-Tier-Instanzkontext

- 2026-07-16: Statusaufbau reichte `instance_name` bis zum API-Budget-Helfer,
  aber Bibliothekar-Aktivzeile und Budget-Service-Tier-Resolver nutzten ihn
  nicht. Instanzspezifisches Gemini-Flex konnte dadurch als global oder leer
  erscheinen.
- `_llm_category_status_lines()`, `_route_status_label()` und
  `_api_budget_label_for_route()` reichen den Instanznamen jetzt bis
  `resolve_gemini_service_tier()` weiter.
- Regression: globales Tier `none`, Depressionsbot-Tier `flex`; relevante
  Status/Gemini-Fokus -> `9 passed`; Ruff, `compileall` und `git diff --check`
  gruen. Kein Provider/API-Aufruf.
- Code-Commit: `1913a5d2 fix: use instance Gemini tier in status`.

**Aktueller Laufstand:** Seit dem Restart `16/20` Code-Commits. Dieser
Plan-Commit macht `17/20`; kein Push. Naechster Restart nach 3 weiteren
Commits. Naechster Push bleibt erst bei 100 Commits.

### RouteTo-Purpose-Ziel

- 2026-07-16: Explorer-Biene fand widerspruechliche Discovery. Die
  Fehlermeldung listete `purpose:structured_decision`, der Resolver entfernte
  den `purpose:`-Praefix aber nicht. Angezeigtes Ziel war dadurch nicht
  nutzbar.
- Resolver erkennt `purpose:<name>` jetzt explizit vor Token-Normalisierung.
- Regression: Alias, Profil, Purpose und explizites Purpose-Ziel; RouteTo-Suite
  -> `8 passed`; Ruff, `compileall` und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `d1825707 fix: resolve explicit RouteTo purposes`.

### RouteTo-Cancel-Kontext

- 2026-07-16: `/cancel` loeschte eine Pending-Route accountweit. Ein
  verbundener Chat desselben Accounts konnte damit eine Route aus einem
  anderen Chat abbrechen.
- `/cancel` wird jetzt nur noch akzeptiert, wenn Channel, Adapter-Slot,
  Chat-ID und Identity zum Pending-Kontext passen. Fremde Chats erhalten
  keinen Abbruchhinweis und lassen Pending unveraendert.
- Regression: Fremdchat-Cancel plus lokaler Cancel; RouteTo-Suite -> `9
  passed`; Ruff, `compileall` und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `17268349 fix: bind RouteTo cancellation to chat context`.

**Aktueller Laufstand:** Seit dem Restart `8/20` Code-Commits. Dieser
Plan-Commit macht `9/20`; kein Push. Naechster Restart nach 11 weiteren
Commits. Naechster Push bleibt erst bei 100 Commits.

### Codex-Bare-Status-Im-Legacy-Pfad

- 2026-07-16: Der Legacy-Telegram-Handler behandelte bare `/codex` vor dem
  Executor als Usage. Der Parser und der moderne Executor definieren bare
  `/codex` jedoch als Statusabfrage. Dadurch war der Codex-Schalter im
  Legacy-Pfad fuer autorisierte Accounts nicht erreichbar.
- Die vorgezogene Argument-Guard ist entfernt. Auch der Legacy-Pfad reicht
  bare `/codex` jetzt an `execute_codex_admin_command` weiter; die
  Admin-Pruefung bleibt davor unveraendert.
- Regression: autorisierter Legacy-Account mit bare `/codex` erreicht den
  Status-Executor; bestehender Resume-Test und `tests/test_codex_command.py`
  -> `9 passed`. Ruff, `compileall` und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `e8a87643 fix: expose bare codex status in legacy path`.

**Aktueller Laufstand:** Seit dem Restart `7/20` Code-Commits. Dieser
Plan-Commit macht `8/20`; kein Push. Naechster Restart nach 12 weiteren
Commits. Naechster Push bleibt erst bei 100 Commits.

### Proactive-Monatsanker

- 2026-07-16: Monats-Wiederholungen klebten nach einem kurzen Monat am
  gekappten Tag. Ein Reminder am 31. Januar lief dadurch ueber 28. Februar
  dauerhaft am 28. weiter und kehrte nie zum 31. zurueck.
- Monatliche Regeln speichern jetzt urspruenglichen Kalendertag und ob der
  Starttag Monatsende war. Tag 30 bleibt nach Februar am 30.; ein Start am
  Monatsende nutzt in kurzen Monaten das Monatsende und danach wieder den
  letzten Tag des Zielmonats.
- Bestehende Items ohne Anker werden beim ersten erfolgreichen Versand aus
  ihrem vorhandenen `due_at` reparierbar abgeleitet. Die Regel gilt fuer
  `monthly` und `every N months`; Tages-, Wochen- und Werktagsregeln bleiben
  unveraendert.
- Regression fuer 31->28->31, 30->28->30 sowie Dispatch-Persistenz;
  `tests/test_proactive_agent.py` -> `125 passed`; Reminder-/Engine-Fokus ->
  `39 passed`; Ruff, `compileall` und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `1acaf25a fix: preserve monthly recurrence calendar day`.

**Aktueller Laufstand:** Seit dem Restart `9/20` Code-Commits. Dieser
Plan-Commit macht `10/20`; kein Push. Naechster Restart nach 10 weiteren
Commits. Naechster Push bleibt erst bei 100 Commits.

### Proactive-DST-Zeitzone

- 2026-07-16: Wiederkehrende Kalenderregeln speicherten nur den aktuellen
  Offset. `_parse_proactive_datetime()` macht aus `Europe/Berlin`-Zeitstempeln
  jedoch einen festen `+01:00`-Offset. Ein Reminder am 28. Maerz um 10:00
  lief deshalb am Folgetag als 10:00 `+01:00` statt lokal 10:00 `+02:00`.
- Neue wiederkehrende Items speichern den passenden IANA-Zeitzonennamen, wenn
  der gespeicherte Offset zur konfigurierten Zone passt. Kalenderregeln
  (`daily`, `weekdays`, `weekly`, Tage/Wochen/Monate) rechnen vor dem naechsten
  Termin in dieser Zone; explizite UTC-Termine bleiben unveraendert UTC.
- Bestehende Items ohne Zone erhalten den Anker beim ersten erfolgreichen
  Versand, sofern `due_at` zur konfigurierten Zone passt. Unbekannte oder
  unpassende Zonen fallen kontrolliert auf bisherigen Offset-Betrieb zurueck.
- Regression: DST `+01 -> +02`, Queue-Persistenz und Monatsanker;
  `tests/test_proactive_agent.py` -> `127 passed`; Reminder-/Engine-Fokus ->
  `39 passed`; Ruff, `compileall` und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `4d191384 fix: preserve recurrence timezone rules`.

**Aktueller Laufstand:** Seit dem Restart `11/20` Code-Commits. Dieser
Plan-Commit macht `12/20`; kein Push. Naechster Restart nach 8 weiteren
Commits. Naechster Push bleibt erst bei 100 Commits.

### Reminder-Subject-und-Expliziter-Monatsanker

- 2026-07-16: Der Reverse-Reminder-Pfad entfernte bei `Kannst du mich ... an`
  den Subject-Marker vor der Subject-Bereinigung. Ein ISO-Datum im Subject,
  etwa `Version 2026-06-01`, wurde danach faelschlich als Datumstermin aus
  dem Subject geloescht. Marker bleiben bis nach dem Datums-Schutz erhalten;
  `an`/`daran`-Subjects werden ohne fuehrende Leerzeichen ausgegeben.
- Folgeaudit durch Biene Curie: Ein expliziter `28.`-Monatstermin, der im
  Folgemonat zufaellig auf den 28. faellt, wurde als Monatsende gespeichert.
  `28. Februar -> 31. Maerz` war falsch. Der Parser reicht gewuenschten
  Kalendertag und Monatsende-Absicht bis in die Outbox; nur expliziter `31.`
  nutzt Monatsende-Semantik.
- Structured- und klassischer Reminder-Pfad tragen die Metadaten. Alte Items
  ohne expliziten Anker bleiben rueckwaertskompatibel und werden wie bisher
  aus `due_at` abgeleitet.
- Regression: Reverse-Subject mit ISO-Datum, `an`/`daran`, klassischer
  Monats-28-Reminder und direkte Folgeplanung; Reminder + Proactive ->
  `161 passed`; Decision-/Engine-Fokus -> `14 passed`; Ruff, `compileall`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e0e097ee fix: preserve explicit monthly reminder day`.

**Aktueller Laufstand:** Seit dem Restart `13/20` Code-Commits. Dieser
Plan-Commit macht `14/20`; kein Push. Naechster Restart nach 6 weiteren
Commits. Naechster Push bleibt erst bei 100 Commits.

### Reminder-Optionaler-Datumszeit-Crash

- 2026-07-16: `_has_invalid_explicit_time()` konvertierte optionale
  Datumsstunden ohne Vorhandensein. Ein Subject wie `16. Maerz 2027` im Satz
  `Kannst du mich in 2 Stunden an ... erinnern?` loeste deshalb
  `TypeError: int(None)` aus statt die relative Erinnerung anzulegen.
- Die Validierung ueberspringt Datums-/Monatstreffer ohne explizite Stunde;
  vorhandene Stunden und Minuten werden weiterhin auf gueltige Werte geprueft.
- Regression fuer deutsches Monatsdatum ohne Uhrzeit; Reminder-Suite ->
  `35 passed`; Decision-/Engine-Fokus -> `14 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `698b8e5e fix: ignore missing reminder date hour`.

**Aktueller Laufstand:** Seit dem Restart `15/20` Code-Commits. Dieser
Plan-Commit macht `16/20`; kein Push. Naechster Restart nach 4 weiteren
Commits. Naechster Push bleibt erst bei 100 Commits.

### Reminder-Monatsintervall-Startanker

- 2026-07-16: `alle 1 Monate` ohne expliziten Tag startete am 28., 29., 30.
  oder 31. Januar jeweils am 28. Februar. Die Outbox leitete aus diesem
  gekappten Folgetermin faelschlich Monatsende-Semantik ab; ein 28.-Start
  lief danach als 31. Maerz weiter.
- Bei Monatsregeln ohne Datumstext wird der Starttag jetzt aus `now`
  uebernommen. Bei explizitem Datum bleibt dessen Tag und `31.`-Monatsende-
  Absicht autoritativ. Parser reicht beides in die Outbox.
- Regression fuer 28.-Januar-Intervall plus bestehende direkte Folgeplanung;
  Reminder + Proactive -> `163 passed`; Decision-/Engine-Fokus -> `14
  passed`; Ruff, `compileall` und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `2a29c075 fix: preserve interval month start day`.

**Aktueller Laufstand:** Seit dem Restart `17/20` Code-Commits. Dieser
Plan-Commit macht `18/20`; kein Push. Naechster Restart nach 2 weiteren
Commits. Naechster Push bleibt erst bei 100 Commits.

### Gemini-Instanz-Keyring-im-Profilpfad

- 2026-07-16: `build_profiled_text_llm_client()` uebergab den
  `instance_name` nicht an `resolve_gemini_api_key_ring()`. Profilbasierte
  Gemini-Routen und Gemini-Fallbacks ignorierten dadurch
  `TEEBOTUS_GEMINI_API_KEYS_<INSTANCE>_*` und konnten den globalen Keyring
  verwenden.
- Der Profilpfad reicht den Instanznamen jetzt weiter. Rollen-/Scope-Keyrings
  bleiben im Runtime-Pfad unveraendert; der Fix verhindert nur den falschen
  globalen Rueckfall.
- Regression: Profilbasierter Gemini-Fallback bevorzugt Instanz-Keyring vor
  globalem Keyring; gezielter Test -> `1 passed`; Ruff und `compileall` gruen.
  Kein Provider/API-Aufruf.
- Code-Commit: `c7b4929e fix: preserve instance Gemini key rings in profile routes`.

**Aktueller Laufstand:** Seit dem Restart `19/20` Code-Commits. Dieser
Plan-Commit macht `20/20`; danach User-Service-Restart. Kein Push. Naechster
Push bleibt erst bei 100 Commits.

### Gemini-Instanz-Limits-im-Profilpfad

- 2026-07-16: Nach dem Keyring-Fix wurden im selben Profilpfad weiterhin
  `instance_name` bei Free-Tier-Limits und `service_tier` unterschlagen.
  Profilbasierte Gemini-Routen konnten daher globale RPM/TPM/RPD- und Flex-
  Einstellungen statt Instanzwerten verwenden.
- Beide Resolver erhalten jetzt den Instanznamen. Runtime-Routen hatten diese
  Weitergabe bereits.
- Regression: Instanz-Keyring, instanzspezifisches RPM und instanzspezifisches
  Flex vor globalen Werten; `tests/test_llm_router.py -k 'profiled_text_client and gemini'`
  -> `3 passed`; Ruff und `compileall` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `65ea6747 fix: preserve instance Gemini limits in profile routes`.

### Reminder-Structured-Entscheidungskosten

- 2026-07-16: Der Engine-Pfad rief den Structured-Decision-Runner fuer jede
  adressierte Nicht-Command-Nachricht auf, sobald er aktiviert war. Das war
  ein unnötiger Provideraufruf pro normaler Nachricht.
- Ein lokaler, konservativer Reminder-Hinweisfilter laesst den Runner nur bei
  Erinnerungssignalen wie `erinnern`, `remind`, `dran`, `daran`, `stupsen`,
  `bescheid`, `nicht vergessen` oder `auf dem Schirm` laufen. Klassische
  Treffer bleiben unveraendert; direkte freie Reminderformulierungen mit
  diesen Signalen erreichen weiterhin den LLM-Fallback.
- Regression: normale Terminfrage ruft Runner nicht auf; Reminder-Suite ->
  `37 passed`; Ruff, `compileall` und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `5ac383e6 fix: gate structured reminder classification locally`.

**Aktueller Laufstand:** Seit dem Restart `2/20` Code-Commits. Dieser
Plan-Commit macht `3/20`; kein Push. Naechster Restart nach 17 weiteren
Commits. Naechster Push bleibt erst bei 100 Commits.

### Reminder-Erstperson-False-Positive

- 2026-07-16: Der klassische Parser behandelte `Ich erinnere mich an ...`
  und `Ich denke daran ...` als Erinnerungsauftrag. Ohne Zeit folgte eine
  falsche Rueckfrage; mit Zeit konnte sogar eine Erinnerung angelegt werden.
- Die beiden Imperativzweige ignorieren jetzt Treffer direkt nach `ich `.
  Imperative wie `Erinnere mich ...` und `Denk bitte daran ...` bleiben
  unveraendert.
- Regression: Erstperson-Aussagen werden abgewiesen; Reminder-Suite ->
  `38 passed`; Ruff, `compileall` und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `5178a113 fix: ignore first-person reminder statements`.

### Reminder-Kurzwortlaut

- 2026-07-16: `Denk an den Termin morgen` wurde nicht als Reminder erkannt.
  Zusaetzlich fehlte `vergiss nicht` im lokalen Gate nach der Umstellung der
  Structured-Reminder-Klassifikation.
- Der direkte Parser akzeptiert `Denk an ...`; der Structured-Runner-Gate
  erkennt auch `vergiss nicht`, ohne normale `Ich denke an ...`-Aussagen zu
  aktivieren.
- Regression: direkte Kurzform plus bestehende Reminderpfade -> `39 passed`;
  Ruff, `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c0b4f661 fix: accept direct reminder wording`.

### Fallback-Warnrate-bei-Teilreparatur

- 2026-07-16: `_clear_recovered_if_clean()` loeschte bei jedem erfolgreichen
  Vorgang saemtliche Warn-Zeitstempel des Accounts. Ein gesunder Index-Write
  konnte dadurch den weiterhin defekten Entry-Fallback entdrosseln; der
  naechste Entry-Zugriff meldete denselben Primary-Fehler sofort erneut.
- Warn-Zeitstempel bleiben jetzt erhalten, solange irgendein Memory-Teil des
  Accounts stale, dirty, sync_failed oder unrecoverable ist. Erst wenn der
  gesamte Account wieder sauber ist, wird Warnzustand inklusive Rate-Limit
  zurueckgesetzt. Erfolgreiche Einzeloperationen duerfen weiterhin ihren
  eigenen Sync-Fehler entfernen.
- Regression: gezielter Cross-Operation-Warnlauf plus bestehender Rate-Limit-
  Test -> `2 passed`; komplette `tests/test_account_store.py` -> `281 passed`.
  Ruff, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `59be1fb9 fix: preserve fallback warning cooldowns`.

**Aktueller Laufstand:** Seit dem Restart `8/20` Commits. Kein Push. Naechster
Restart nach 12 weiteren Commits.

### Secondary-Only-Collection-Namen

- 2026-07-16: Bei einem Primary-Ausfall gab `read_collection_names()` eine
  nichtleere Collection-Liste aus dem Secondary zurueck, setzte aber keinen
  Reparaturmarker. Nach Primary-Erholung wurde deshalb erneut nur die alte
  Primary-Liste gelesen; Secondary-only Collections verschwanden wieder aus
  dem sichtbaren Zustand.
- Wenn beide Backends echten Collection-Read und -Write/Repair anbieten,
  markiert der Fallback die ausgegebene Namensliste jetzt als pending. Der
  naechste gesunde Name-Read kopiert fehlende Collections aus dem Secondary
  zurueck in den Primary und loest den Warnzustand erst danach. Name-only-
  Adapter ohne Reparaturvertrag behalten Kompatibilitaet und werden nicht
  faelschlich als reparierbar markiert.
- Regression: Secondary-only-Collection mit Recovery plus bestehende
  Name-Failure-Pfade -> `4 passed`; komplette `tests/test_account_store.py` ->
  `282 passed`. Ruff, `py_compile` und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `18885852 fix: repair fallback collection name reads`.

**Aktueller Laufstand:** Seit dem Restart `10/20` Commits. Kein Push. Naechster
Restart nach 10 weiteren Commits.

### Collection-Read-trotz-Name-Reparatur

- 2026-07-16: Der neue Pending-Marker fuer eine aus dem Secondary gelieferte
  Collection-Namensliste wurde von `_operation_has_unsafe_fallback()` auch auf
  konkrete `read_collection()`-Aufrufe angewendet. Dadurch war bekannte,
  lesbare Secondary-Nutzlast nicht mehr erreichbar, obwohl sie den Primary
  reparieren konnte.
- Der Marker blockiert jetzt nur unsichere Collection-Name-/Write-Pfade.
  Explizite Collection-Reads duerfen Secondary nutzen und reparieren den
  Primary weiterhin; echte Collection-`sync_failed`-/`unrecoverable`- oder
  Clear-Wildcard-Zustaende bleiben fail-closed.
- Regression: direkter Read waehrend ausstehender Name-Reparatur plus bestehende
  Name-Failure-Pfade -> `3 passed`; komplette `tests/test_account_store.py` ->
  `283 passed`. Ruff, `py_compile` und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `c60a64cd fix: keep named collection fallback reads available`.

### SQLite-Keyscan-bei-korrupter-Datei

- 2026-07-16: `_sqlite_memory_has_instance_payload_rows()` erkannte eine
  unlesbare SQLite-Datei konservativ als vorhandenen Payload. Der nachfolgende
  `_sqlite_memory_account_ids()`-Scan fing denselben Datenbankfehler aber ab und
  lieferte `()`. Bei fehlendem Key-Manifest konnte dadurch ein falscher
  Secret-Service-Key als gueltig manifestiert werden; verschluesselte Memorys
  waeren danach dauerhaft unlesbar gewesen.
- Der Account-ID-Scan wirft bei SQLite-Diagnosefehlern jetzt einen harten
  `AccountStoreError`. Unlesbare Daten bleiben damit Fail-closed; kein
  Fingerprint- oder Manifest-Write.
- Regression: falsche Schluessel- und korrupte SQLite-Datei -> `2 passed`;
  komplette `tests/test_account_store.py` -> `284 passed`. Ruff,
  `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `f4f38abf fix: fail closed on corrupt sqlite key scans`.

**Aktueller Laufstand:** Seit dem Restart `14/20` Commits. Kein Push. Naechster
Restart nach 6 weiteren Commits. Naechster Push bleibt erst bei 100 Commits.

### Partial-Read-darf-Primary-nicht-leeren

- 2026-07-16: `read_entries_by_ids()` behandelte eine Primary-Ausnahme mit
  leerem Secondary als selektiv leere Antwort. Der anschliessende Full-Read des
  leeren Secondary wurde als Reparaturdaten benutzt und konnte vorhandene
  Primary-Eintraege loeschen.
- Bei `partial_result=True` und leerem Full-Read des Secondary wird jetzt keine
  leere Menge in Primary geschrieben. Der Account wird als unrecoverable
  markiert und bleibt bis erfolgreicher Primary-Recovery schreibgeschuetzt;
  normale selektive Reads mit nichtleerer Full-Menge reparieren weiter.
- Regression: alle `entries_by_ids`-Fallbackpfade -> `5 passed`; komplette
  `tests/test_account_store.py` -> `285 passed`. Ruff, `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `58167ac0 fix: protect primary entries during partial fallback reads`.

**Aktueller Laufstand:** Seit dem Restart `17/20` Code-Commits. Dieser
Plan-Commit macht `18/20`. Kein Push. Restart nach 2 weiteren Commits.
Naechster Push bleibt erst bei 100 Commits.

### Merge-prueft-Source-und-Target-getrennt

- 2026-07-16: `merge_accounts()` las Source-Entries, dann Target-Entries und
  pruefte erst danach den gemeinsamen Diagnosezustand. Ein sauberer Target-Read
  konnte damit einen partiell unlesbaren Source-Read maskieren; Source-Daten
  waeren anschliessend zusammengefuehrt und beim Tombstone-Cleanup geloescht
  worden.
- Source- und Target-Entries werden jetzt direkt nach ihrem jeweiligen Read
  fail-closed geprueft. Erst zwei saubere Reads erlauben Merge/Loeschpfad.
- Regression: Merge-Suite -> `8 passed`; komplette `tests/test_account_store.py`
  -> `286 passed`. Ruff, `py_compile` und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `8cb00919 fix: validate source memory before account merge`.

**Aktueller Laufstand:** Seit dem Restart `19/20` Code-Commits. Dieser
Plan-Commit macht `20/20`; danach Restart. Kein Push. Naechster Push bleibt
erst bei 100 Commits.

### SQL-Keyscan-leere-Account-ID

- 2026-07-17: `_sqlite_memory_account_ids()` und der analoge PostgreSQL-Scan
  filterten leere `account_id`-Werte still heraus. Bei einer Datenbank, die nur
  solche malformed Payload-Rows enthielt, konnte ein neuer/falscher Key ohne
  Entschluesselungspruefung manifestiert werden.
- Leere oder nur aus Whitespace bestehende Account-IDs sind jetzt harte
  Diagnosefehler. Kein Secret-Fingerprint wird geschrieben, solange SQL-
  Payload nicht vollstaendig adressierbar ist.
- Regression: falscher Key, korrupte Datei und malformed SQLite-Account-ID ->
  `3 passed`; komplette `tests/test_account_store.py` -> `287 passed`. Ruff,
  `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `3908d69c fix: reject malformed sql memory account ids`.

**Aktueller Laufstand:** Seit dem Restart `2/20` Commits. Kein Push. Naechster
Restart nach 18 weiteren Commits. Naechster Push bleibt erst bei 100 Commits.

### Ranking-bei-kaputtem-Index

- 2026-07-17: `rank_structured_memory_ids()` und
  `select_structured_memory()` normalisierten einen leeren Rueckgabewert trotz
  `last_index_read_error`. Kaputter/verschluesselungsbedingt unlesbarer Index
  wurde dadurch wie leerer Index behandelt.
- Beide Pfade pruefen Index-Diagnose jetzt direkt nach dem Read und brechen
  fail-closed mit `AccountStoreError` ab. Ein leerer, fehlerfreier Erstindex
  bleibt gueltig.
- Regression: Mutation/Ranking/Auswahl gegen unlesbaren Index plus komplette
  `tests/test_account_store.py` -> `287 passed`. Ruff, `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `95483ed3 fix: fail closed on unreadable memory indexes`.

**Aktueller Laufstand:** Seit dem Restart `4/20` Commits. Kein Push. Naechster
Restart nach 16 weiteren Commits. Naechster Push bleibt erst bei 100 Commits.

### SQLite-WAL-Sidecars-beim-Keyscan

- 2026-07-17: `_sqlite_memory_has_instance_payload_rows()` ignorierte
  nichtleere `Account_Memory.sqlite3-wal`/`-shm`-Dateien, wenn die Hauptdatei
  fehlte oder leer war. Der Key-Guard konnte dadurch vorhandenen, nicht
  checkpointeten Payload uebersehen.
- Nicht aufloesbare, nichtleere SQLite-Sidecars gelten jetzt als vorhandener,
  aber uninspectierbarer Payload. Secret-Autocreate und Manifest-Fingerprint
  brechen fail-closed ab; Sidecars werden nicht veraendert.
- Regression: vier SQL-Key-Guard-Faelle -> `4 passed`; komplette
  `tests/test_account_store.py` -> `288 passed`. Ruff, `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `7f6f3121 fix: guard sqlite sidecar payloads`.

**Aktueller Laufstand:** Seit dem Restart `5/20` Commits. Kein Push. Naechster
Restart nach 15 weiteren Commits. Naechster Push bleibt erst bei 100 Commits.

### Metadata-Quarantaene-nur-betroffene-Accounts

- 2026-07-17: `_quarantine_instance_unreadable_metadata()` verschob bei einem
  unlesbaren Account-Profil den kompletten `accounts/`-Elternordner. Dadurch
  konnten lesbare aktive Accounts zusammen mit dem defekten Profil aus dem
  aktiven Store verschwinden.
- Die Quarantaene verschiebt jetzt bei `kind=accounts_dir` nur die konkret
  gemeldeten betroffenen Account-Verzeichnisse nach `metadata/<timestamp>/accounts/`.
  `Account_Index.json`, `Account_Identities.json`, `Account_Secrets.json` und
  nicht betroffene Account-Verzeichnisse bleiben am aktiven Ort.
- Regression: Metadata-Quarantaene -> `3 passed`; komplette
  `tests/test_admin_accounts.py` -> `64 passed`. Ruff, `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e10b8b11 fix: quarantine unreadable account dirs individually`.

**Aktueller Laufstand:** Seit dem Restart `8/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 12 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### History-Dispatcher-Spool-Invaliddateien-duerfen-Batch-nicht-blockieren

- 2026-07-17: `CallbackSpool.events()` begrenzte vor dem Parsen auf die ersten
  100 Dateinamen. 100 defekte oder uebergrosse JSON-Dateien konnten dadurch
  gueltige Events hinter ihnen dauerhaft aus dem aktuellen Flush ausschliessen.
- Das Limit gilt jetzt nur fuer erfolgreich gelesene Dict-Events; ungueltige,
  Symlink- oder Nicht-Datei-Eintraege verbrauchen keinen Batchplatz.
- Regression: `tests/test_history_dispatcher_bridge.py` `6 passed`; Ruff,
  `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `21ed2d25 fix: prevent invalid dispatcher spool starvation`.

**Aktueller Laufstand:** Seit dem Restart `10/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 10 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Codex-History-Scan-Limit-im-Eventpfad

- 2026-07-17: Der Watchdog-/Eventpfad importierte bei einem Event-Burst alle
  veraenderten JSONL-Dateien und umging damit `limit` (obwohl die Option als
  maximale Dateien pro Scan dokumentiert ist).
- Event-Batches werden jetzt bei `limit > 0` nach neuestem `mtime` begrenzt und
  anschliessend chronologisch verarbeitet; `limit=0` bleibt unbegrenzt.
- Regression: Codex-History-Fokus `183 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `2951da9d fix: enforce codex scan limit for event batches`.

**Aktueller Laufstand:** Seit dem Restart `6/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 14 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Codex-History-Tail-Record-an-exakter-Byte-Grenze

- 2026-07-17: Der Large-File-Reader verwarf nach `seek(tail_start)` immer die
  erste Zeile. Lag `tail_start` exakt auf einem JSONL-Record-Anfang, ging ein
  vollstaendiger Record verloren.
- Der Reader erkennt jetzt `LF`, einzelnes `CR` und `CRLF` als echte
  Record-Grenzen; nur ein angeschnittener erster Tail-Record wird verworfen.
- Regression mit exakter Head-/Tail-Grenze: Codex-History-Fokus `184 passed`;
  Ruff, `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `882de4fa fix: preserve codex tail record at boundary`.

**Aktueller Laufstand:** Seit dem Restart `8/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 12 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Codex-Dispatch-Receipt-darf-Multi-Admin-Retry-nicht-blockieren

- 2026-07-17: Der Dispatcher hatte in der oeffentlichen Python-Funktion und im
  Bridge-Pfad noch `limit=100`, obwohl CLI/Systemd bereits `0 = alle` nutzten.
  Direkte Aufrufer verloren dadurch ab Summary 101 Eintraege.
- Ein Receipt oder Reply von Admin A setzte das gesamte Item ausserdem auf
  `delivered`/`acknowledged`, obwohl Admin B noch mit retry-faehigem
  `send_error` fehlgeschlagen war. Das Item wurde dadurch nicht mehr
  dispatchbar und B bekam keinen Retry.
- Beide Dispatcher-Defaults nutzen jetzt `CODEX_HISTORY_DEFAULT_DISPATCH_LIMIT`
  (`0`). Receipt-/Reply-Status wird aus dem neuesten Ergebnis je Empfaenger
  aggregiert; Append-Reihenfolge ist fuer Event-Status autoritativ. Ein anderer
  transient fehlgeschlagener Empfaenger haelt Item bei `queued`.
- Timestamp-basierte Auswahl fuer bereits erfolgreiche Empfaenger bleibt
  unveraendert; sie ist bestehender Vertrag fuer Retry-Deduplizierung.
- Regression: komplette `tests/test_codex_history.py` -> `181 passed`; Ruff mit
  bestehender `E402`-Ausnahme, `compileall` und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `45557634 fix: preserve codex dispatch retries after receipts`.

**Aktueller Laufstand:** Seit dem Restart `2/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 18 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Codex-Manueller-Ack-respektiert-offene-Retries

- 2026-07-17: `acknowledge_codex_history_item()` setzte Item ungeachtet
  anderer Empfaenger direkt auf `acknowledged`. Ein manueller Ack von Admin A
  konnte damit den retry-faehigen Fehler von Admin B verdecken und weitere
  Zustellung verhindern.
- Manueller Ack nutzt jetzt dieselbe per-Empfaenger-Aggregation wie Receipt und
  Reply. Offener transienter Fehler haelt Item bei `queued`; Einzel-Ack bleibt
  im Dispatch-Result und API-Response sichtbar.
- Regression: kompletter `tests/test_codex_history.py`-Lauf -> `182 passed`;
  Ruff mit bestehender `E402`-Ausnahme, `compileall` und `git diff --check`
  gruen. Kein Provider/API-Aufruf.
- Code-Commit: `5501b81a fix: keep codex retries open after manual ack`.

**Aktueller Laufstand:** Seit dem Restart `4/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 16 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Applet-Fallback-Positiv-und-Negativfall-fixiert

- 2026-07-17: Der Applet-Fallback-Fix bekam einen expliziten Paar-Test fuer
  beide Richtungen: blosses `fallback=local` bleibt handlungsrelevant;
  `effective_status=configured` wird als bestaetigte Ersatzroute informativ.
- Regression: Positiv-/Negativfall -> `2 passed`; komplette Applet-Suite nach
  dem eigentlichen Fix -> `240 passed`. Ruff mit bekannten alten `F541`-Warnungen
  ausgenommen und Diff-Check gruen. Kein Provider/API-Aufruf.
- Test-Commit: `0673f76e test: pin verified decision fallback classification`.

**Aktueller Laufstand:** Seit dem Restart `19/20` Commits. Dieser Plan-Commit
zaehlt mit: `20/20`. Kein Push. Restart jetzt. Naechster Push bleibt erst bei
100 Commits.

### SQLite-Schema-Probe-behandelt-IO-Fehler

- 2026-07-17: Der stabile SQLite-Open-/FD-Guard kann beim Schema-Probeweg
  `OSError` liefern. `_missing_schema_table()` fing bisher nur
  `sqlite3.Error`; dadurch erreichte Fallback-Recovery nicht die vorhandene
  fail-closed-Diagnose `schema is unreadable`, sondern warf rohe IO-Fehler.
- Schema-Probe klassifiziert jetzt `sqlite3.Error` und `OSError` gemeinsam als
  `<unreadable>`. Automatische Reparatur bleibt bei vorhandener Sekundaer-DB
  verweigert; Daten bleiben unangetastet.
- Regression: SQLite-Schema-Reparatur mit stabilem Open-`OSError` -> `2 passed`;
  komplette `tests/test_cinnamon_applet.py` -> `240 passed`. Ruff,
  `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `4e3788d3 fix: classify sqlite schema probe io failures`.

**Aktueller Laufstand:** Seit dem Restart `15/20` Commits. Kein Push. Restart
nach 5 weiteren Commits. Naechster Push bleibt erst bei 100 Commits.

### Applet-Health-verlangt-bestaetigten-LLM-Fallback

- 2026-07-17: Der Applet-Classifier stufte `structured_decision` mit
  `route_status=unavailable` als Information ein, sobald irgendein
  `fallback=...` gesetzt war. Ein bloss konfigurierter Fallback belegt aber
  nicht, dass Ersatzroute funktioniert oder aktiv ist.
- Downgrade zu Information erfolgt jetzt nur bei verifiziertem
  `effective_status` aus der gesunden Statusmenge. Unverifizierte
  Provider-/Routenfehler bleiben im Healthkopf handlungsrelevant.
- Regression: gezielter Fallback-/Health-Fokus -> `31 passed`; komplette
  `tests/test_cinnamon_applet.py` -> `240 passed`. Ruff mit bekannten alten
  `F541`-Warnungen ausgenommen, `compileall` und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `b55f4b32 fix: require verified applet fallback status`.

**Aktueller Laufstand:** Seit dem Restart `17/20` Commits. Dieser Plan-Commit
zaehlt mit: `18/20`. Kein Push. Restart nach 2 weiteren Commits. Naechster
Push bleibt erst bei 100 Commits.

### Applet-Health-bei-Runtime-Timeouts-nicht-leer-werfen

- 2026-07-17: `TeeBotus.cinnamon_applet._run()` verwarf bei einem Timeout alle
  bereits gelesenen stdout-Diagnosen. Der Applet-Header bekam dadurch nur ein
  leeres/defektes Health-Payload, obwohl Runtime-Sektionen schon ausgegeben
  waren.
- Timeout-Ausgaben werden jetzt weiterhin redigiert und begrenzt erhalten.
  Returncode 124 bleibt bewusst kritisch; nur Diagnoseverlust ist behoben.
- Regression: fokussierter Timeout-/Payload-Check -> `3 passed`; kompletter
  `tests/test_cinnamon_applet.py`-Lauf -> `239 passed`; echter 7-Sekunden-
  Timeout behielt Runtime-Sektionen und redigierte Secrets. Kein Provider/API-
  Aufruf.
- Code-Commit: `279ed74c fix: preserve partial applet diagnostics on timeout`.

**Aktueller Laufstand:** Seit dem Restart `7/20` Commits. Dieser Plan-Commit
zaehlt mit: `8/20`. Kein Push. Restart nach 12 weiteren Commits. Naechster
Push bleibt erst bei 100 Commits.

### SQLite-Read-Cipher-nicht-pro-Zeile-neu-auflösen

- 2026-07-17: Jeder entschluesselte SQLite-Read rief bisher erneut den
  Secret-Service-Provider auf. Grosse Codex-History-Collections erzeugten so
  tausende identische Key-/Manifestpruefungen und konnten den Applet-Health-
  Check in einen Timeout treiben.
- Entries-, Entry-ID-, Index- und Collection-Reads verwenden jetzt einen
  Cipher-Snapshot je Read-Vorgang. Secret-Rotation bleibt wirksam, weil jeder
  neue Read den aktuellen Provider-Schluessel erneut aufloest.
- Regression: `tests/test_account_store.py` -> `312 passed`,
  Codex-History-Status -> `7 passed`, Ruff und Compileall gruen. Echter
  `--runtime-status` fiel von ca. 17 auf ca. 5,4 Sekunden. Kein Provider/API-
  Aufruf.
- Code-Commit: `61fcfc02 perf: snapshot sqlite read cipher`.

**Aktueller Laufstand:** Seit dem Restart `9/20` Commits. Dieser Plan-Commit
zaehlt mit: `10/20`. Kein Push. Restart nach 10 weiteren Commits. Naechster
Push bleibt erst bei 100 Commits.

### Codex-History-Status-bleibt-read-only

- 2026-07-17: Der Statuspfad nutzte den normalen Codex-History-Read. Bei
  vorhandener Legacy-JSONL-Datei konnte ein Healthcheck dadurch mergen,
  zurueckschreiben, verifizieren und die Legacy-Datei loeschen.
- `AccountStore.read_codex_history_outbox_readonly()` liest SQL-Daten ohne
  Migration; `codex_history_status_lines()` bevorzugt diesen Pfad. Writer und
  explizite Migrationsreads behalten bisheriges Verhalten.
- Regression: SQLite-Read-only-Migration plus bestehende Legacy-Migration ->
  `3 passed`; Codex-History-Status -> `8 passed`; kompletter AccountStore-
  Lauf -> `313 passed`; Ruff, Compileall und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `5c4963af fix: keep codex history status reads read-only`.

**Aktueller Laufstand:** Seit dem Restart `11/20` Commits. Dieser Plan-Commit
zaehlt mit: `12/20`. Kein Push. Restart nach 8 weiteren Commits. Naechster
Push bleibt erst bei 100 Commits.

### Applet-Timeout-Payload-integriert-abgesichert

- 2026-07-17: Neben dem niedrigen `_run()`-Test fehlte ein
  Payload-Regressionstest fuer strukturierte Teil-Ausgabe bei Returncode 124.
- Der Test stellt sicher, dass Health kritisch bleibt, Runtime-Sektionen und
  Timeout-Diagnose aber im JSON-Payload sichtbar bleiben.
- Regression: neuer Payload-Test plus Timeout-Test -> `2 passed`; bestehende
  Applet-Suite zuvor -> `239 passed`. `ruff --ignore F541` und Diff-Check gruen;
  zwei alte F541-Warnungen im Testfile bleiben unveraendert. Kein Provider/API-
  Aufruf.
- Test-Commit: `3ab87ceb test: cover partial applet status payloads`.

**Aktueller Laufstand:** Seit dem Restart `13/20` Commits. Dieser Plan-Commit
zaehlt mit: `14/20`. Kein Push. Restart nach 6 weiteren Commits. Naechster
Push bleibt erst bei 100 Commits.

### PostgreSQL-Memory-Schema-vor-Initialisierung-validieren

- 2026-07-17: `_ensure_schema_locked()` markierte PostgreSQL als initialisiert,
  sobald `CREATE TABLE IF NOT EXISTS` und Index-DDL ohne Fehler liefen. Eine
  bereits vorhandene, unvollstaendige Tabelle wurde dadurch nicht erkannt;
  fehlende Spalten wie `last_accessed_at` schlugen erst spaeter mit PostgreSQL-
  Fehler `42703` fehl.
- Der Backend-Guard prueft jetzt nach der DDL alle Pflichtspalten in
  `information_schema.columns`. Fehlende Tabellen/Spalten werden als
  `AccountStoreError` gemeldet; `_initialized` bleibt `False`, damit kein
  falsches Health-Signal entsteht und kein spaeterer Schreibpfad blind laeuft.
- Regression: PostgreSQL-Fokus -> `16 passed`; AccountStore plus
  Memory-Benchmark -> `327 passed`; `compileall` und `git diff --check` gruen.
  Kein Provider/API-Aufruf.
- Code-Commit: `c3fd0b9f fix: validate postgres memory schema columns`.

**Aktueller Laufstand:** Seit dem Restart `20/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart jetzt. Naechster Push bleibt erst bei 100
Commits.

### Leere-Fallback-Collection-Namen-als-Reparaturzustand-behandeln

- 2026-07-17: Nach einem Primary-Ausfall wurde eine leere, diagnostikfreie
  Fallback-Liste als endgueltig leer akzeptiert. War der Primary nur temporaer
  unlesbar, blieben dort vorhandene Collections unsichtbar und wurden nie in
  den Fallback gespiegelt.
- Bei verfuegbarer Collection-Reparatur setzt eine leere Fallback-Liste jetzt
  einen Pending-State. Nach Primary-Recovery werden Primary-only-Collections
  ueber einen sauberen Collection-Read in den Fallback gespiegelt. Fehlt die
  Reparatur-API, bleibt der bisherige einfache Empty-Backend-Vertrag erhalten.
- Regression: Fallback-Fokus -> `75 passed`; kompletter
  `tests/test_account_store.py`-Lauf -> `310 passed`; `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `20525b13 fix: retain empty fallback collection repair state`.

**Aktueller Laufstand:** Seit dem Restart `2/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 18 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### SQLite-Primary-mit-fehlender-Pflichtspalte-blockieren

- 2026-07-17: Eine bestehende SQLite-Primary-DB ohne Fallback konnte nach
  Entfernen einer Pflichtspalte durch `CREATE TABLE IF NOT EXISTS` passieren;
  der spaetere `INSERT` endete erst mit `OperationalError`, waehrend
  `_initialized` bereits `True` war.
- Fehlende Spalten werden jetzt unabhaengig von Fallback-Konfiguration vor
  jeder DDL blockiert. Fehlende Tabellen ohne Fallback bleiben bewusst im
  vorhandenen Erzeugungspfad; fehlende Tabellen mit Fallback bleiben
  fail-closed.
- Regression: Schema-Fokus -> `8 passed`; kompletter
  `tests/test_account_store.py`-Lauf -> `311 passed`; `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `5e84590c fix: reject incomplete sqlite memory columns`.

**Aktueller Laufstand:** Seit dem Restart `4/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 16 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### PostgreSQL-Schema-Invalidierung-bei-fehlender-Spalte-retrybar

- 2026-07-17: Der PostgreSQL-Retry erkannte bisher nur SQLSTATE `42P01`
  (fehlende Relation). Wurde eine Pflichtspalte nach bereits gesetztem
  `_initialized=True` entfernt, lief der Read/Write-Pfad mit `42703` direkt
  in den Fehler.
- SQLSTATE `42703` wird jetzt wie `42P01` als Schema-Invalidierung behandelt:
  `_initialized` wird einmal verworfen, der Schema-Guard erneut ausgefuehrt;
  die Pflichtspaltenpruefung meldet anschliessend sauber `AccountStoreError`,
  statt einen falschen gesunden Zustand zu behalten.
- Regression: PostgreSQL-Fokus -> `17 passed`; AccountStore plus
  Memory-Benchmark -> `330 passed`; `compileall` und `git diff --check` gruen.
  Kein Provider/API-Aufruf.
- Code-Commit: `1cb09991 fix: retry postgres missing schema columns`.

**Aktueller Laufstand:** Seit dem Restart `6/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 14 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Status-meldet-uninitialisiertes-SQL-Memory

- 2026-07-17: /status deaktivierte das konfigurierte SQLite-Backend, wenn
  Primary und Fallback noch nicht existierten. Dadurch blieb ein absichtlich
  leeres Konto zwar korrekt pruefbar, aber die fehlende SQL-Initialisierung
  unsichtbar; der Status meldete schlicht status=ok.
- Die Legacy-JSON-Auswahl bleibt erhalten, damit vorhandene JSON-Artefakte
  weiterhin diagnostiziert werden und der Status keine Datenbank anlegt.
  Zusaetzlich meldet er jetzt warning=memory_database_uninitialized, wenn
  ein SQLite-Backend konfiguriert, aber noch keine Primary-/Fallback-Datei
  vorhanden ist. Bereits aktiver Fallback-Sync und Backend-Diagnosen bleiben
  getrennt sichtbar; kombinierte Warnungen werden nicht verschluckt.
- Regression: Status-Fokus -> 4 passed; kompletter
  tests/test_version_notifications.py-Lauf -> 218 passed; kompletter
  tests/test_account_store.py-Lauf -> 308 passed; zusaetzlicher
  Engine-Status-Fokus -> 3 passed; compileall und git diff --check
  gruen. Kein Provider/API-Aufruf.
- Code-Commit: 5f85a9c4 fix: surface uninitialized memory backend in status.

**Aktueller Laufstand:** Seit dem Restart `16/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 4 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### SQLite-Memory-Connect-gegen-Path-TOCTOU-haerten

- 2026-07-17: Nach der statischen Symlink-Pruefung oeffneten `_connect()` und
  `_connect_readonly()` SQLite erneut ueber den Dateipfad. Ein Parent- oder
  Datei-Tausch zwischen Pruefung und `sqlite3.connect()` konnte dadurch ein
  fremdes SQLite-Ziel auswaehlen.
- SQLite-Parent wird jetzt komponentenweise mit `O_NOFOLLOW|O_DIRECTORY`
  geoeffnet. Die Zieldatei wird relativ dazu mit `O_NOFOLLOW` geoeffnet und
  als regulaere Datei mit genau einem Hardlink geprueft. SQLite nutzt den
  stabilen Parent-FD; Inode/Typ/Hardlinkzahl werden vor und nach `connect()`
  verglichen. Symlink-WAL/SHM-Sidecars blockieren.
- Regression: simulierter Datenbanktausch vor `connect()` wird als
  `OSError` abgewiesen und liest keine Ersatzdaten; Fokus -> `4 passed`;
  komplette `tests/test_account_store.py` -> `295 passed`. Ruff,
  `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `d885a901 fix: open sqlite memory through stable descriptors`.

**Aktueller Laufstand:** Seit dem Restart `10/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 10 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Legacy-Memory-Loeschung-ueber-stabilen-Parent-FD

- 2026-07-17: `_unlink_migrated_account_file()` loeschte nach einer
  vorherigen Root-Pruefung wieder per `path.unlink()`. Ein Parent-Swap konnte
  dadurch beim JSONL-Import eine fremde Datei loeschen.
- Migration loescht jetzt relativ zu einem komponentenweise mit
  `O_NOFOLLOW|O_DIRECTORY` geoeffneten Parent-FD. Finales Ziel muss regulaer,
  nicht symlinked und Single-Link sein; Parent-/Final-Swap blockiert fail-closed.
- Regression: Parent-Swap waehrend der Legacy-Loeschung -> `2 passed`; Ruff,
  `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `90aef583 fix: remove migrated files through stable parents`.

**Aktueller Laufstand:** Seit dem Restart `12/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 8 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### SQLite-Secret-Inspektion-ueber-stabile-Deskriptoren

- 2026-07-17: Secret-/Manifest-Guards lasen SQLite-Payload-Existenz und
  Account-IDs ueber `path.resolve()`/`sqlite3.connect(path)`. Ein Datei-Swap
  konnte dadurch die falsche Datenbank fuer Autocreate-/Keywechsel-Entscheide
  liefern.
- Beide Inspektionspfade nutzen jetzt stabilen Parent-/Target-FD mit
  Inode-Pruefung vor und nach `connect()`; Symlink-Sidecars und unsichere
  Targets blockieren fail-closed.
- Regression: simulierter Pfadtausch waehrend Secret-Inspektion -> `5 passed`;
  Ruff, `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `ad7a84f8 fix: inspect sqlite memory through stable descriptors`.

**Aktueller Laufstand:** Seit dem Restart `14/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 6 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### PostgreSQL-Memory-Blob-Typen-fail-closed-behandeln

- 2026-07-17: PostgreSQL-Read-/Guard-Pfade konvertierten BYTEA-Werte direkt
  mit `bytes(...)`. Defekte TEXT-/NULL-/andere Werte konnten dadurch als
  ungefangener `TypeError` aus dem Memorypfad ausbrechen.
- Payload-Coercion akzeptiert jetzt nur `bytes`, `bytearray` und `memoryview`;
  andere Typen werden als `AccountStoreError` klassifiziert. Read, Index,
  Collection und destruktive Write-Guards behandeln sie damit wie korrupte
  Payloads und loeschen nichts ungeprueft.
- Regression: PostgreSQL-Korruptionsfokus -> `3 passed`; Ruff, `compileall`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c5ff9946 fix: classify malformed postgres payloads as corrupt`.

**Aktueller Laufstand:** Seit dem Restart `16/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 4 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Atomare-Memory-Schreibpfade-ueber-stabile-Parent-FDs

- 2026-07-17: `_atomic_write_bytes()` pruefte das Elternverzeichnis per Pfad,
  erzeugte Temp-Datei und `os.replace()` danach ebenfalls per Pfad. Ein
  Parent-Swap konnte dadurch atomare Memory-/State-Schreibvorgaenge auf ein
  fremdes Ziel umlenken.
- Fehlende Verzeichnisse werden jetzt komponentenweise relativ zu stabilen
  `O_NOFOLLOW|O_DIRECTORY`-Deskriptoren angelegt. Temp-Datei, Replace,
  Aufraeumen und Directory-`fsync` bleiben an denselben Parent-FD gebunden.
- Regression: Parent-Swap waehrend `os.replace()` -> `2 passed`; kompletter
  `tests/test_account_store.py`-Lauf -> `298 passed`. Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `eef537e9 fix: anchor atomic memory writes to stable directory fds`.

**Aktueller Laufstand:** Seit dem Restart `18/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 2 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Verschluesselte-Vault-Reads-ueber-stabile-Datei-FDs

- 2026-07-17: `EncryptedJsonVault.read_text()` und der Existing-Payload-Guard
  lasen nach einer Pfadpruefung per `Path.read_bytes()`. Finaler Datei- oder
  Parent-Swap konnte dadurch fremde verschluesselte Daten in Memory-/Secret-
  Entscheidungen bringen.
- Reads oeffnen Parent und regulare Single-Link-Zieldatei jetzt stabil mit
  `O_NOFOLLOW`; gelesen wird ueber den Datei-FD. Fehlende Dateien bleiben
  normaler Default-Fall, unsichere oder beschaedigte Ziele blockieren
  fail-closed.
- Regression: finaler/Parent-Swap beim Vault-Read -> `3 passed`; kompletter
  `tests/test_account_store.py`-Lauf -> `299 passed`. Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e47b6cde fix: read encrypted memory files through stable descriptors`.

**Aktueller Laufstand:** Seit dem Restart `20/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart jetzt. Naechster Push bleibt erst bei 100
Commits.

### Unverschluesselte-Account-Text-Reads-ueber-stabile-Datei-FDs

- 2026-07-17: `read_account_text()` las Account-Notizen nach Account-/Datei-
  Validierung wieder per `Path.read_text()`. Ein Parent-Swap konnte dadurch
  fremde Notizen in Profil-, Versions- oder Botkontext bringen.
- Der Read nutzt jetzt denselben stabilen Parent-/Datei-FD wie verschluesselte
  Vault-Reads; regulaere Single-Link-Datei und UTF-8-Dekodierung bleiben
  erhalten. Fehlende Notiz bleibt leerer Default.
- Regression: Account-Text-Parent-Swap -> `4 passed`; kompletter
  `tests/test_account_store.py`-Lauf -> `300 passed`. Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `47c89419 fix: read account text through stable descriptors`.

**Aktueller Laufstand:** Seit dem Restart `2/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 18 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Keyring-Manifest-Read-ueber-stabile-Datei-FDs

- 2026-07-17: `_KeyringManifestSecretProvider._load_manifest()` las das
  Secret-Verifier-Manifest nach keiner stabilen Parent-Pruefung per Pfad.
  Ein Verzeichnis-Swap konnte dadurch fremde Instance-/Purpose-Daten in
  Secret-Service-Guards einbringen.
- Manifest-Parent und regulare Single-Link-Zieldatei werden jetzt ueber
  `O_NOFOLLOW`-FD geoeffnet; JSON-/UTF-8-Fehler bleiben als invalides Manifest
  fail-closed klassifiziert.
- Regression: Keyring-Manifest-Parent-Swap -> `5 passed`; kompletter
  `tests/test_account_store.py`-Lauf -> `301 passed`. Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a0065220 fix: read keyring manifests through stable descriptors`.

**Aktueller Laufstand:** Seit dem Restart `4/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 16 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Verschluesselte-Payload-und-Verifier-Inspektion-ueber-stabile-FDs

- 2026-07-17: `_looks_like_teebotus_encrypted_payload()`,
  `_secret_verifier_file_has_payload()` und der Candidate-Secret-Guard lasen
  Markerdateien nach einer Pfadpruefung per `Path.read_bytes()`. Ein Swap
  konnte dadurch Secret-Autocreate- und Keywechsel-Entscheide beeinflussen.
- Alle drei Pfade lesen jetzt ueber stabilen Parent-/Datei-FD mit
  `O_NOFOLLOW`; externe Ersatzdateien werden nicht als lokale Payload
  akzeptiert. Fehlende Dateien bleiben False, unsichere Dateien fail-closed.
- Regression: Payload-Parent-Swap -> `6 passed`; kompletter
  `tests/test_account_store.py`-Lauf -> `302 passed`. Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `62218861 fix: inspect encrypted payloads through stable descriptors`.

**Aktueller Laufstand:** Seit dem Restart `6/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 14 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Legacy-JSON-und-JSONL-Reads-ueber-stabile-FDs

- 2026-07-17: `_read_json_object()` und `_read_jsonl_plain()` lasen die
  plaintext Legacy-Fallbacks direkt per Pfad. Ein Parent-Swap konnte damit
  externe Fallback-Daten in Account-/State-Migration einbringen.
- Beide Reader nutzen jetzt stabilen Parent-/Datei-FD mit `O_NOFOLLOW`;
  fehlende Dateien bleiben leere Defaults, Decode-/Schemafehler bleiben
  fail-closed. Der bestehende Legacy-Fallback bleibt unveraendert aktiv.
- Regression: JSON-/JSONL-Parent-Swap -> `8 passed`; kompletter
  `tests/test_account_store.py`-Lauf -> `304 passed`. Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `79f7748a fix: read legacy account files through stable descriptors`.

**Aktueller Laufstand:** Seit dem Restart `8/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 12 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Secret-Rotation-Verifier-Rollback-ueber-stabile-Pfade

- 2026-07-17: `rotate_secret()` las den alten Verifier mit
  `exists()+read_bytes()` und entfernte einen neu erzeugten Verifier im
  Rollback per `Path.unlink()`. Datei-/Parent-Swap konnte dadurch falschen
  Zustand lesen oder fremde Ziele loeschen.
- Der alte Verifier wird jetzt ueber stabilen Datei-FD gelesen. Wenn keiner
  existiert, nutzt Rollback den bereits FD-gebundenen, regularen
  Single-Link-Unlink-Helfer.
- Regression: Rotation-/Rollback-Fokus -> `5 passed`; kompletter
  `tests/test_account_store.py`-Lauf -> `304 passed`. Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c5d28dce fix: make secret rotation verifier rollback path-safe`.

**Aktueller Laufstand:** Seit dem Restart `10/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 10 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Identity-Metadata-Snapshots-und-Rollbacks-ueber-stabile-Pfade

- 2026-07-17: Identity-Alias-Reparatur und allgemeine Identity-Rollbacks
  lasen Snapshot-Dateien per `path.read_bytes()` und entfernten fehlende
  Ziele per `path.unlink()`. Ein Swap konnte damit fremde Metadaten lesen oder
  loeschen.
- Snapshot-Reads nutzen jetzt stabile Parent-/Datei-FDs; fehlende
  Rollback-Ziele werden ueber den FD-gebundenen, regularen Single-Link-Unlink
  entfernt. Atomare Wiederherstellung bleibt erhalten.
- Regression: Identity-/Merge-/Rollback-Fokus -> `16 passed`; kompletter
  `tests/test_account_store.py`-Lauf -> `304 passed`. Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `3460b601 fix: make identity metadata rollback path-safe`.

**Aktueller Laufstand:** Seit dem Restart `12/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 8 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Account-Text-Merge-Reads-ueber-stabile-FDs

- 2026-07-17: `_merge_text()` las Quell- und Zielnotizen nach
  `exists()`-Pruefung per `Path.read_text()`. Ein Swap waehrend Legacy-/Account-
  Merge konnte fremde Habits in den Account schreiben.
- Source und Target werden jetzt ueber stabile Parent-/Datei-FDs gelesen;
  fehlendes Target bleibt leer, fehlende Source bleibt Merge-Noop. Der bereits
  atomare Ziel-Write bleibt unveraendert.
- Regression: Merge-/Alias-Fokus -> `10 passed`; kompletter
  `tests/test_account_store.py`-Lauf -> `304 passed`. Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `acc544b3 fix: read merged account text through stable descriptors`.

**Aktueller Laufstand:** Seit dem Restart `14/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 6 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Account-Merge-Cleanup-ueber-stabile-FDs

- 2026-07-17: `_delete_dir_contents_except()` nutzte `iterdir()`,
  `shutil.rmtree()` und `Path.unlink()` auf dem Account-Verzeichnis. Ein
  Parent-/Child-Swap konnte dadurch fremde Dateien oder Verzeichnisse
  loeschen.
- Cleanup laeuft jetzt rekursiv relativ zu stabilen
  `O_NOFOLLOW|O_DIRECTORY`-Deskriptoren. Symlink-Children werden nur als Link
  entfernt; externe Zielverzeichnisse werden nicht verfolgt. Keep-Liste bleibt
  erhalten, Race-Fehler blockieren fail-closed.
- Regression: Cleanup-/Merge-Fokus -> `11 passed`; kompletter
  `tests/test_account_store.py`-Lauf -> `305 passed`. Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `273d222b fix: clean merged account directories through stable fds`.

**Aktueller Laufstand:** Seit dem Restart `16/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 4 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Account-Discovery-ueber-stabile-Child-Directory-FDs

- 2026-07-17: Account-Discovery und Secret-Payload-Generatoren nutzten
  `iterdir().is_dir()`. Symlinked Account-Verzeichnisse konnten dadurch als
  lokale Memory-/Secret-Quellen erscheinen.
- Child-Verzeichnisse werden jetzt aus stabilem Parent-FD gelesen und mit
  `O_NOFOLLOW|O_DIRECTORY` bestaetigt. Symlinks und Race-verlorene Eintraege
  werden ignoriert; spaetere Datei-Reads bleiben separat FD-gebunden.
- Regression: Discovery-/Merge-Fokus -> `11 passed`; kompletter
  `tests/test_account_store.py`-Lauf -> `306 passed`. Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `bf42611a fix: ignore symlinked account directories during discovery`.

**Aktueller Laufstand:** Seit dem Restart `18/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 2 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Account-Verzeichnisse-werden-ueber-stabile-FDs-erstellt

- 2026-07-17: `_prepare_account_memory_directory()` pruefte Root,
  `accounts/` und Account-Verzeichnis und nutzte danach `mkdir()` per Pfad.
  Ein Redirect-Race konnte Verzeichnisse ausserhalb des vorgesehenen Baums
  anlegen.
- Root, `accounts/` und Account-Verzeichnis werden jetzt komponentenweise
  relativ zu `O_NOFOLLOW|O_DIRECTORY`-Deskriptoren erstellt und sofort wieder
  geschlossen. Keine Pfad-basierte Verzeichnisanlage mehr im Account-Lock-
  Vorlauf.
- Regression: kompletter `tests/test_account_store.py`-Lauf -> `306 passed`;
  Ruff, `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `31de19e2 fix: create account directories through stable fds`.

**Aktueller Laufstand:** Seit dem Restart `20/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart jetzt. Naechster Push bleibt erst bei 100
Commits.

### Account-Locks-ueber-stabile-Parent-FDs

- 2026-07-17: `_safe_account_lock_handle()` pruefte den Lock und oeffnete ihn
  danach absolut per Pfad. Auch `account_memory_lock_for_root()` und
  `account_identity_lock()` legten Verzeichnisse per `mkdir()` an.
- Lock-Parent wird jetzt stabil mit `O_NOFOLLOW|O_DIRECTORY` geoeffnet; finaler
  Lock wird relativ dazu mit `O_NOFOLLOW` erstellt/geoeffnet und auf regulaere
  Single-Link-Datei geprueft. Lock-Verzeichnisse werden komponentenweise FD-
  gebunden angelegt.
- Regression: Lock-/Parent-Swap-Fokus -> `28 passed`; kompletter
  `tests/test_account_store.py`-Lauf -> `307 passed`. Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `9773a7cd fix: anchor account locks to stable parent fds`.

**Aktueller Laufstand:** Seit dem Restart `2/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 18 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Initialisierungs-und-Merge-Verzeichnisse-ueber-stabile-FDs

- 2026-07-17: `AccountStore.__post_init__()`, `merge_accounts()` und
  `_merge_jsonl()` legten `accounts/` oder Zielverzeichnisse noch per
  `Path.mkdir()` nach Pfadpruefung an.
- Alle drei Pfade nutzen jetzt komponentenweise
  `O_NOFOLLOW|O_DIRECTORY`-FD-Erstellung. Redirects koennen keine externen
  Merge-/Memory-Ziele anlegen.
- Regression: Init-/Merge-Fokus und kompletter
  `tests/test_account_store.py`-Lauf -> jeweils `307 passed`; Ruff,
  `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `f9befc33 fix: create merge and store directories through stable fds`.

**Aktueller Laufstand:** Seit dem Restart `4/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 16 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Leere-Account-Verzeichnisse-im-Rollback-ueber-stabile-FDs

- 2026-07-17: `_restore_new_account_metadata()` pruefte leeres Verzeichnis
  per `exists()+iterdir()` und entfernte es danach per `rmdir()` ueber den
  Pfad. Ein Redirect-Race konnte fremde leere Verzeichnisse betreffen.
- Rollback oeffnet Parent und Child jetzt stabil mit
  `O_NOFOLLOW|O_DIRECTORY`, prueft Leere ueber Child-FD und entfernt relativ
  zum Parent-FD. Unsichere Ziele werden als Rollback-Fehler gemeldet.
- Regression: Rollback-/Merge-Fokus -> `13 passed`; kompletter
  `tests/test_account_store.py`-Lauf -> `307 passed`. Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `6b2389b8 fix: remove empty account directories through stable fds`.

**Aktueller Laufstand:** Seit dem Restart `6/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 14 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Account-Store-Root-ohne-unsichere-Aufloesung

- 2026-07-17: `AccountStore.__post_init__()` pruefte `raw_root`, rief danach
  aber `raw_root.resolve()` auf. Ein zwischenzeitlich gesetzter Symlink konnte
  den Store-Root vor der FD-Sicherung umbiegen.
- Root wird jetzt nur lexikalisch absolut normalisiert; komponentenweise
  `O_NOFOLLOW|O_DIRECTORY`-Erstellung/Oeffnung entscheidet ueber den echten
  Zielpfad und blockiert Redirects.
- Regression: kompletter `tests/test_account_store.py`-Lauf -> `307 passed`;
  Ruff, `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `95b929ee fix: keep account store roots lexically stable`.

**Aktueller Laufstand:** Seit dem Restart `8/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 12 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### PostgreSQL-Collection-Replacement-validiert-Binary-Payloads

- 2026-07-17: `replace_collection_item()` konvertierte vorhandene BYTEA-Werte
  direkt mit `bytes(...)` und umging dadurch die zentrale Validierung. Defekte
  TEXT-/NULL-/andere Werte konnten den Updatepfad mit uneinheitlichen Fehlern
  verlassen.
- Der bestehende Collection-Payload wird jetzt vor dem Entschluesseln ueber
  dieselbe strikte BYTEA-Coercion wie alle anderen PostgreSQL-Lese- und
  Guard-Pfade geprueft. Unsichere Daten blockieren den Replace fail-closed.
- Regression: PostgreSQL-Korruptionsfokus -> `4 passed`; kompletter
  `tests/test_account_store.py`-Lauf -> `307 passed`; `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `6cdf8c7e fix: validate postgres collection replacement payloads`.

**Aktueller Laufstand:** Seit dem Restart `10/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 10 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### SQLite-Parent-Erstellung-ueber-stabile-Directory-FDs

- 2026-07-17: `SQLiteAccountMemoryBackend._connect()` legte fehlende
  Parent-Verzeichnisse mit `Path.mkdir()` an und oeffnete sie erst danach
  stabil. Ein Parent-Redirect-Race konnte dadurch Verzeichnisse ausserhalb des
  vorgesehenen Baums erzeugen.
- Der stabile SQLite-Directory-Walker erzeugt fehlende Komponenten jetzt
  relativ zu bereits geprueften `O_NOFOLLOW|O_DIRECTORY`-FDs. Read-only-Pfade
  erzeugen weiterhin nichts; Symlink-Komponenten bleiben blockiert.
- Regression: SQLite-Parent-/Symlink-Fokus -> `3 passed`; kompletter
  `tests/test_account_store.py`-Lauf -> `308 passed`; `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `4a12f7bf fix: create sqlite parents through stable descriptors`.

**Aktueller Laufstand:** Seit dem Restart `12/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 8 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Leere-Fallback-Collection-Liste-ist-gueltiger-Zustand

- 2026-07-17: `WarningFallbackAccountMemoryBackend.read_collection_names()`
  behandelte eine erfolgreich gelesene leere Liste aus dem Fallback als
  „keine recoverbaren Daten“. Accounts ohne Collections wurden dadurch trotz
  intakter Sicherung hart blockiert.
- Eine frische, diagnostikfreie leere Fallback-Liste wird jetzt als gueltiger
  leerer Zustand zurueckgegeben. Bereits offene Reparaturen oder Dirty-
  Collections bleiben fail-closed und werden nicht durch leere Daten
  quittiert.
- Regression: Collection-Name-Fokus -> `5 passed`; kompletter
  `tests/test_account_store.py`-Lauf -> `308 passed`; `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `90ac50c6 fix: accept empty fallback collection lists`.

**Aktueller Laufstand:** Seit dem Restart `14/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 6 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Identity-Mapping-Ownership

- 2026-07-17: `_identity_payload_for_key()` pruefte `account_id` und Profil,
  ignorierte aber ein explizites fremdes `instance`-Feld im Identity-Mapping.
  Ein kopiertes/falsch zugeordnetes Mapping konnte dadurch lokalen Account
  referenzieren.
- Kandidaten mit explizit anderer Instanz werden jetzt vor Auswahl und
  Alias-Reparatur verworfen. Historische Mappings ohne `instance` bleiben als
  Legacy-Fallback lesbar; es wird kein fremdes Mapping automatisch repariert.
- Regression: Identity-Lookup inklusive Fremdinstanz -> `5 passed`; komplette
  `tests/test_account_store.py` -> `291 passed`. Ruff, `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `b549cfec fix: reject foreign identity instance mappings`.

**Aktueller Laufstand:** Seit dem Restart `10/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 10 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Identity-Listen-mit-Instanzfilter

- 2026-07-17: `get_account_for_identity()` ignorierte explizite fremde
  Instanz-Mappings, aber `_active_identities_for_account()` zaehlte sie weiter
  als lokal. Account-Summary, Adminzaehler und Routing konnten damit
  unterschiedliche Identitaetsmengen melden.
- Die lokale Identitaetsliste filtert jetzt denselben expliziten
  `instance`-Besitzvertrag. Fehlendes Feld bleibt Legacy-kompatibel; fremde
  Instanz wird weder gelistet noch fuer lokale Operationen verwendet.
- Regression: Identity-Lookup/-Liste -> `5 passed`; komplette
  `tests/test_account_store.py` -> `291 passed`. Ruff, `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `f80ab4fe fix: filter foreign identities from account lists`.

**Aktueller Laufstand:** Seit dem Restart `12/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 8 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Quarantaene-Mehrfachquellen-vor-Delete-snapshotten

- 2026-07-17: `_quarantine_instance_unrecoverable()` mischte Snapshot und
  Delete pro SQLite-Quelle. Wenn eine spaetere Quelle scheiterte, konnten Rows
  frueherer Quellen bereits geloescht sein; JSON-Moves liefen erst danach.
- Apply snapshot't jetzt alle SQL-Quellen zuerst ueber den geschuetzten
  read-only Probeweg. Erst danach werden JSON-Artefakte bewegt und SQL-Rows
  geloescht. Snapshot-Fehler verhindern jeden SQL-Delete; Snapshots sichern
  bereits erhaltene Daten auch bei spaeterem Folgefehler.
- Regression: Quarantaene-/Snapshot-Fokus -> `14 passed`; kompletter
  `tests/test_admin_accounts.py` -> `71 passed`. Ruff, `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `32ee119f fix: snapshot recovery sources before deletion`.

**Aktueller Laufstand:** Seit dem Restart `14/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 6 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Metadata-Quarantaene-bei-Secret-Fehlern

- 2026-07-17: `_unreadable_metadata_items()` meldete fehlendes, nicht
  erreichbares oder geaendertes Secret ebenso wie echte Payload-Korruption als
  `AccountStoreError`. `--apply --quarantine-unreadable-metadata` haette
  dadurch gueltige verschluesselte Daten aus dem aktiven Store bewegen koennen.
- Quarantaene-Apply laeuft jetzt nur bei bekannten Korruptionssignaturen wie
  Authentication-Tag-Fehlern, malformed/unsupported Envelopes oder invalidem
  verschluesseltem JSON. Secret-Service-, Keyring-, Provider-, Missing-Key- und
  unbekannte Fehler blockieren den gesamten Instance-Apply. Dateien bleiben
  unangetastet; Ergebnisstatus ist `blocked`.
- Regression: Metadata-Quarantaene inklusive fehlendem Secret -> `4 passed`;
  komplette `tests/test_admin_accounts.py` -> `65 passed`. Ruff,
  `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `69497d4d fix: block metadata quarantine on secret failures`.

**Aktueller Laufstand:** Seit dem Restart `10/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 10 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Account-Profil-Ownership

- 2026-07-17: `_account_is_resolvable()` akzeptierte jedes lesbare Profil,
  solange `status` nicht `tombstoned` war. Ein Profil mit fehlender oder
  fremder `account_id` bzw. falscher Instanz konnte dadurch als aktiver Account
  verwendet und in den Index geschrieben werden.
- Resolvability verlangt jetzt ein Dict-Profil mit exakt passender
  normalisierter `account_id`, passendem `instance`-Wert und nicht-tombstoned
  Status. Verdächtige Profile bleiben unresolvable und werden nicht automatisch
  überschrieben.
- Regression: Profile mit fehlender/fremder Ownership -> `2 passed`; komplette
  `tests/test_account_store.py` -> `289 passed`. Ruff, `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `78e51423 fix: validate account profile ownership`.

**Aktueller Laufstand:** Seit dem Restart `12/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 8 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Account-Index-Ownership

- 2026-07-17: `_upsert_account_index()` vertraute dem uebergebenen Profil und
  schrieb `profile["account_id"]` ohne Ownership-/Instanzpruefung. Ein
  manipuliertes oder falsch zusammengefuehrtes Profil konnte damit einen
  fremden Account in den Index schreiben, obwohl Resolvability bereits
  geschuetzt war.
- Der zentrale Index-Write validiert jetzt SHA-512-Account-ID und exakte
  Instanzzugehoerigkeit vor jedem Index-Read/Write. Bei Fehler bleibt der
  bestehende Index unveraendert.
- Regression: Profile- und Index-Ownership -> `3 passed`; komplette
  `tests/test_account_store.py` -> `290 passed`. Ruff, `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `1a94b319 fix: enforce profile ownership on index writes`.

**Aktueller Laufstand:** Seit dem Restart `14/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 6 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Metadata-Quarantaene-bei-Auth-Fehlern

- 2026-07-17: Authentication-Tag-Fehler waren als bekannte Korruption fuer
  Quarantaene-Apply zugelassen. Ein geaenderter oder falscher Secret-Service-
  Key erzeugt denselben Fehler; Apply konnte damit gueltige Metadata aus dem
  aktiven Store bewegen.
- Auth-Fehler sind jetzt explizit unsafe und blockieren Apply. Nur eindeutig
  malformed/unsupported Envelope- oder JSON-Fehler bleiben fuer selektive
  Quarantaene zugelassen. Kein automatisches Verschieben bei Key-Mismatch.
- Regression: Key-Mismatch blockiert, malformed Profil wird selektiv bewegt ->
  `5 passed`; komplette `tests/test_admin_accounts.py` -> `65 passed`. Ruff,
  `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `dc50a897 fix: block metadata quarantine on auth failures`.

**Aktueller Laufstand:** Seit dem Restart `16/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 4 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### SQLite-Recovery-Quelle-verschwindet-waehrend-Probe

- 2026-07-17: Die Recovery-Probes fingen bei Datei-/Sidecar-Races nur
  `sqlite3.Error`, nicht `OSError`. Ein Backup-Cleanup oder paralleler Move
  zwischen Discovery und `copy2()` konnte damit den gesamten Admin-Report
  abbrechen.
- `_sqlite_account_ids()`, `_sqlite_raw_counts()` und der Payload-Reader
  behandeln solche OS-Fehler jetzt als leere bzw. fehlerhafte Quelle. Der
  Report bleibt erzeugbar und markiert die Snapshot-Quelle mit `sqlite:`-Fehler;
  keine automatische Reparatur oder Datenveraenderung.
- Regression: verschwindende SQLite-Quelle -> `2 passed`; komplette
  `tests/test_admin_accounts.py` -> `66 passed`. Ruff, `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `5313ebd1 fix: tolerate disappearing sqlite recovery sources`.

**Aktueller Laufstand:** Seit dem Restart `18/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 2 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### SQLite-Recovery-lehnt-Symlinks-ab

- 2026-07-17: `_connect_sqlite_readonly()` folgte SQLite-Hauptdatei und
  `-wal`/`-shm`-Sidecars ueber Symlinks. Recovery-Scan und moeglicher Apply
  konnten dadurch Daten ausserhalb des Account-Store-Kontexts lesen oder
  kopieren.
- Hauptdatei und Sidecars werden jetzt vor `copy2()` auf Symlinks geprueft;
  Treffer werden als `sqlite:`-Fehler gemeldet und nicht gelesen, repariert
  oder verschoben.
- Regression: symlinked Hauptdatei und WAL-Sidecar -> `3 passed`; komplette
  `tests/test_admin_accounts.py` -> `67 passed`. Ruff, `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `ce69d017 fix: reject symlinked sqlite recovery files`.

**Aktueller Laufstand:** Seit dem Restart `20/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart jetzt erforderlich. Naechster Push bleibt erst
bei 100 Commits.

### Metadata-Quarantaene-gekuerzte-Fehlerliste

- 2026-07-17: Bei mehr als fuenf unlesbaren Profilen wurde nur der erste
  Fehlertext in `accounts_dir.error` gespeichert. Ein Auth-Fehler hinter dem
  Limit konnte dadurch im Apply-Guard unsichtbar werden; bekannte Malformed-
  Fehler haetten Quarantaene freigegeben.
- Der interne Item-Marker `quarantine_safe` ist jetzt nur wahr, wenn jeder
  einzelne Profilfehler sicher klassifizierbar ist. Gekuerzter Text bleibt fuer
  Darstellung erlaubt, aber jeder unbekannte/Auth-Fehler blockiert Apply.
- Regression: sechs Profile mit Auth-Fehler an Position 6 -> `6 passed` im
  Metadata-Fokus; kompletter `tests/test_admin_accounts.py` -> `68 passed`.
  Ruff, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a3b7f6a5 fix: preserve quarantine safety across truncated errors`.

**Aktueller Laufstand:** Seit dem Restart `2/20` Commits. Kein Push. Restart
nach 18 weiteren Commits. Naechster Push bleibt erst bei 100 Commits.

### Metadata-Quarantaene-Unsupported-Envelope

- 2026-07-17: `version/algorithm/kind unsupported` war als sichere Korruption
  klassifiziert. Das kann aber valide alte, inkompatible oder falsch benannte
  Payload sein; Quarantaene-Apply haette sie aus dem aktiven Store entfernt.
- Diese Fehler sind jetzt ebenfalls unsicher und blockieren Apply. Zulassung
  bleibt auf eindeutig strukturell malformed/invalid Envelope- oder JSON-
  Fehler begrenzt. Keine automatische Migration oder Verschiebung unbekannter
  Formate.
- Regression: unsupported Envelope blockiert plus Metadata-Sicherheitsmatrix ->
  `7 passed`; kompletter `tests/test_admin_accounts.py` -> `69 passed`. Ruff,
  `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `344e51e9 fix: block unsupported metadata envelopes`.

**Aktueller Laufstand:** Seit dem Restart `4/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 16 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Account-Reports-ignorieren-Symlink-Ordner

- 2026-07-17: `_account_dirs()` akzeptierte symlinked Account-Verzeichnisse,
  wenn ihr Name wie eine Account-ID aussah. Dadurch konnten externe Daten in
  Admin-Reports einbezogen werden.
- Symlinked Account-Verzeichnisse werden jetzt vor `account_summary()` und vor
  der Zaehllogik verworfen.
- Regression: symlinked Account-Ordner -> `2 passed`; komplette
  `tests/test_admin_accounts.py` -> `86 passed`. Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `21d551f5 fix: ignore symlinked account directories`.

**Aktueller Laufstand:** Seit dem Restart `5/20` Commits. Kein Push. Restart
nach 15 weiteren Commits. Naechster Push bleibt erst bei 100 Commits.

### Quarantaene-Zielpfad-ohne-Symlinks

- 2026-07-17: `_prepare_private_dir()` folgte bei `--quarantine-dir` bereits
  existierenden Symlinks. Ein Ziel ausserhalb des vorgesehenen Quarantaene-
  Baums konnte dadurch unbemerkt als Ablage dienen.
- Zielpfad und alle vorhandenen Eltern werden jetzt vor `mkdir`, `chmod` und
  Move auf Symlinks geprueft. Symlink-Ziel blockiert mit `AccountStoreError`,
  bevor irgendeine Quelle bewegt wird.
- Regression: symlinked Quarantaeneziel -> `8 passed` im Metadata-Fokus;
  kompletter `tests/test_admin_accounts.py` -> `70 passed`. Ruff,
  `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `4e6d6c57 fix: reject symlinked quarantine destinations`.

**Aktueller Laufstand:** Seit dem Restart `6/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 14 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Account-Profilstatus-nur-bekannte-Zustaende

- 2026-07-17: `_account_is_resolvable()` behandelte jeden Profilstatus ausser
  `tombstoned` als aktiv. Auch `_upsert_account_index()` akzeptierte unbekannte
  Statuswerte. Beschädigte oder fremde Status konnten damit nutzbare Accounts
  und Indexeintraege erzeugen.
- Resolvability und Index-Write akzeptieren jetzt nur `active` und `orphaned`.
  Unbekannte, leere und sonstige Statuswerte blockieren; Tombstone-/Cleanup-
  Pfade bleiben separat.
- Regression: Ownership-/Status-Guard -> `3 passed`; komplette
  `tests/test_account_store.py` -> `290 passed`. Ruff, `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `14eb7203 fix: reject unknown account profile statuses`.

**Aktueller Laufstand:** Seit dem Restart `8/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 12 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### JSON-Recovery-ignoriert-Symlink-Accountdirs

- 2026-07-17: `_json_memory_files_for_accounts()` folgte Symlink-Accountdirs.
  Ein Account-Verzeichnis konnte dadurch auf Dateien ausserhalb des aktiven
  `accounts/`-Baums zeigen; Quarantaene haette diese Dateien als Memory-Artefakte
  behandeln koennen.
- Symlink- oder nicht existente Accountdirs werden beim JSON-Recovery jetzt
  fail-closed uebersprungen. Externe Dateien werden weder gelesen noch
  verschoben; normale Verzeichnisse bleiben unveraendert.
- Regression: externes Ziel hinter Symlink bleibt erhalten und liefert keine
  Recovery-Datei; gezielter Quarantaene-/Snapshot-Fokus -> `15 passed`;
  komplette `tests/test_admin_accounts.py` -> `72 passed`. Ruff,
  `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `5542c432 fix: ignore symlinked account directories in recovery`.

**Aktueller Laufstand:** Seit dem Restart `16/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 4 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### JSON-Recovery-lehnt-Symlink-Pfade-ab

- 2026-07-17: JSON-Recovery-Discovery und `_inspect_json_source()` konnten
  Symlink-Accountdirs oder einzelne Symlink-Dateien als externe JSON/JSONL-
  Quellen behandeln. Damit konnten Berichte fremde Dateien lesen; Discovery
  konnte solche Accounts ausserdem als lokale Accounts melden.
- Recovery-Accountdirs, aktive `accounts/`-Wurzeln, JSON/JSONL-Dateien und
  Snapshot-Symlinks werden jetzt fail-closed verworfen. Nur echte Verzeichnisse
  und Dateien werden gelesen oder zur Quarantaene vorgemerkt.
- Regression: Symlink-Accountdir, Discovery und Symlink-Memorydatei ->
  `6 passed` im JSON-Fokus; komplette `tests/test_admin_accounts.py` ->
  `74 passed`. Ruff, `compileall` und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `6ac6a9e8 fix: reject symlinked json recovery paths`.

**Aktueller Laufstand:** Seit dem Restart `18/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 2 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### SQLite-Snapshot-Ziel-exklusiv-reservieren

- 2026-07-17: `_snapshot_sqlite_database()` legte das Ziel direkt per
  `sqlite3.connect()` an. Ein bereits vorhandener Symlink im Quarantaene-
  Verzeichnis konnte dadurch auf eine externe Datei zeigen; ein vorhandenes
  Snapshot-Ziel wurde ausserdem still ueberschrieben.
- Snapshot-Ziele werden jetzt vor dem SQLite-Backup mit `O_CREAT|O_EXCL`
  exklusiv reserviert. Vorhandene Dateien und Symlinks blockieren; der externe
  Zielinhalt bleibt unveraendert.
- Regression: vorhandener Symlink als Snapshot-Ziel -> `2 passed` im
  Snapshot-Fokus; komplette `tests/test_admin_accounts.py` -> `75 passed`.
  Ruff, `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `5f4826e0 fix: reserve sqlite snapshot destinations exclusively`.

**Aktueller Laufstand:** Seit dem Restart `20/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart jetzt erforderlich. Naechster Push bleibt erst
bei 100 Commits.

### Metadata-Recovery-lehnt-Symlink-Pfade-ab

- 2026-07-17: `_unreadable_metadata_items()` folgte Symlinks bei
  `Account_Index.json`, anderen Metadata-Dateien, `accounts/` und
  `Account_Profile.json`. Recovery konnte dadurch externe Dateien lesen;
  Apply haette den Befund nicht als sicheren Korruptionsfall behandeln duerfen.
- Metadata-Dateien, Accounts-Wurzel und Accountdirs werden jetzt vor `exists()`
  oder Lesen auf Symlinks geprueft. Solche Pfade werden explizit als unsicher
  gemeldet und blockieren Apply; externe Inhalte bleiben unangetastet.
- Regression: Symlink-Metadata und Symlink-Accountdir -> `2 passed` im Fokus;
  komplette `tests/test_admin_accounts.py` -> `77 passed`. Ruff, `compileall`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `37777cde fix: block symlinked metadata recovery paths`.

**Aktueller Laufstand:** Seit dem Restart `2/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 18 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### SQLite-Recovery-lehnt-Hardlinks-ab

- 2026-07-17: SQLite-Recovery pruefte Symlinks, aber keine Hardlinks. Ein
  hardgelinktes `Account_Memory.sqlite3` teilt seine Inode mit externer DB;
  `_delete_sqlite_account_rows()` haette dadurch externe Daten veraendern
  koennen.
- Hauptdatei und WAL/SHM-Sidecars werden jetzt vor Probe, Snapshot und Delete
  auf `st_nlink > 1` geprueft. Hardlinks blockieren fail-closed; kein externer
  SQLite-Inode wird mutiert.
- Regression: hardgelinkte Quelle vor Probe/Delete -> `2 passed` im SQLite-
  Fokus; komplette `tests/test_admin_accounts.py` -> `78 passed`. Ruff,
  `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `ffbfeeeb fix: reject hardlinked sqlite recovery sources`.

**Aktueller Laufstand:** Seit dem Restart `4/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 16 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Quarantaene-Manifest-exklusiv-schreiben

- 2026-07-17: Quarantaene-Manifeste wurden per `Path.write_text()` geschrieben.
  Ein vorhandener `manifest.json`-Symlink konnte dadurch auf externe Datei
  zeigen und ueberschrieben werden.
- Beide Manifest-Pfade reservieren die Datei jetzt mit `O_CREAT|O_EXCL` und
  Modus `0600`. Vorhandene Dateien und Symlinks blockieren; kein externes
  Ziel wird verfolgt.
- Regression: Manifest-Symlink -> `3 passed` im Manifest-/Quarantaene-Fokus;
  komplette `tests/test_admin_accounts.py` -> `79 passed`. Ruff,
  `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `ac1d5a15 fix: reserve quarantine manifests exclusively`.

**Aktueller Laufstand:** Seit dem Restart `6/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 14 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Recovery-lehnt-Symlink-Pfadkomponenten-ab

- 2026-07-17: Link-Guards prueften bisher oft nur den letzten Pfadbestandteil.
  Ein Symlink-Elternordner konnte JSON-, Metadata- oder SQLite-Operationen auf
  externe Daten umlenken.
- Eine zentrale Komponentenpruefung laeuft jetzt ueber alle absoluten
  Pfadbestandteile. JSON-/Metadata-/SQLite-Reads, SQLite-Deletes und
  Quarantaene-Ziele blockieren bei Symlink-Eltern fail-closed.
- Regression: symlinked SQLite-Elternpfad plus bestehende JSON-/Metadata-
  Symlinktests -> `5 passed` im Fokus; komplette `tests/test_admin_accounts.py`
  -> `80 passed`. Ruff, `compileall` und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `06f86e97 fix: reject symlinked recovery path components`.

**Aktueller Laufstand:** Seit dem Restart `8/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 12 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Recovery-Accounts-Dir-Race-fail-closed

- 2026-07-17: `_discover_account_ids()` und
  `_unreadable_metadata_items()` konnten bei einem parallelen Move/Backup-
  Cleanup waehrend `iterdir()` mit `OSError` abbrechen.
- JSON-Discovery behandelt verschwundene Verzeichnisse jetzt als leere Quelle;
  Metadata-Recovery meldet den Race als unsicheren `accounts_dir`-Befund und
  blockiert Apply. Kein automatischer Read oder Move.
- Regression: simuliertes verschwundenes `accounts/` -> `11 passed` im
  Fokus; komplette `tests/test_admin_accounts.py` -> `81 passed`. Ruff,
  `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c093e02d fix: tolerate disappearing recovery account directories`.

**Aktueller Laufstand:** Seit dem Restart `10/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 10 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Recovery-Iterator-Race-im-try

- 2026-07-17: Der erste Directory-Race-Guard fing nur Fehler beim Aufruf von
  `Path.iterdir()` ab. `iterdir()` liefert aber lazy Generator; der eigentliche
  `OSError` kann erst beim `update()`/Iterieren auftreten.
- Discovery materialisiert Accountdirs jetzt innerhalb des `try`-Blocks.
  Race bleibt leere Quelle; Metadata-Recovery bleibt unsicher und blockiert
  Apply.
- Regression: Fehler erst beim Generator-Iterieren -> `1 passed` Fokus;
  komplette `tests/test_admin_accounts.py` -> `81 passed`. Ruff, `compileall`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `51b45353 fix: catch iterator races during account discovery`.

**Aktueller Laufstand:** Seit dem Restart `12/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 8 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Metadata-Probe-Fehler-fail-closed

- 2026-07-17: `_metadata_health_report()` fing nur `AccountStoreError`, der
  Quarantaene-Wrapper gar keine Probe-Fehler. Ein verschwundener oder nicht
  lesbarer Metadata-Pfad konnte den Admin-Lauf dadurch abbrechen.
- Healthcheck und Metadata-Quarantaene wandeln `AccountStoreError`/`OSError`
  jetzt in unsicheren `account_store`-Befund um. Apply blockiert; kein Move,
  keine automatische Reparatur.
- Regression: simulierter Metadata-Probe-Fehler -> `11 passed` im Fokus;
  komplette `tests/test_admin_accounts.py` -> `82 passed`. Ruff, `compileall`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `65700a44 fix: fail closed on metadata probe errors`.

**Aktueller Laufstand:** Seit dem Restart `14/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 6 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Quarantaene-SQL-Quellen-an-Accounts-Root-binden

- 2026-07-17: `quarantine_unrecoverable_account_memory()` vertraute auf
  Pfade aus uebergebenem Report. Ein manipulierter Report konnte damit
  beliebige SQLite-Dateien fuer Delete/Snapshot angeben.
- Aktive SQLite-Quellen werden jetzt nur akzeptiert, wenn sie unter dem
  nicht-symlinketen `accounts_root` liegen. Fehlender Root, Symlink-Root,
  `..`-Escape und externe Pfade liefern keine Delete-Quelle.
- Regression: externe Report-Quelle -> `2 passed` im Path-Fokus; komplette
  `tests/test_admin_accounts.py` -> `83 passed`. Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `82e548b6 fix: constrain quarantine sqlite sources to account root`.

**Aktueller Laufstand:** Seit dem Restart `16/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 4 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Automatische-Instanz-Discovery-ohne-Symlink

- 2026-07-17: `discover_instances()` nahm Symlink-Instanzen und symlinked
  `Bot_Verhalten.md` in automatische Admin-/Recovery-Reports auf. Ein
  externer Instruktionsbaum konnte damit als lokale Instanz gelten.
- Discovery materialisiert den Root-Scan innerhalb `try`, ueberspringt
  Symlink-Instanzen und verlangt echte Instruction-Datei. Race/OS-Fehler
  liefern leere automatische Discovery; explizite Instance-Auswahl bleibt
  unveraendert.
- Regression: Symlink-Instanz plus symlinked Instruction -> `1 passed`; komplette
  `tests/test_admin_accounts.py` -> `84 passed`. Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `0ada76b3 fix: ignore symlinked automatic instance discovery`.

**Aktueller Laufstand:** Seit dem Restart `18/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 2 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Quarantaene-Blocked-Status-nicht-zu-No-op

- 2026-07-17: Ein inkonsistenter Report mit leerem/unsicherem
  `accounts_root` wurde korrekt als Instance `blocked` markiert. Der aeussere
  Aggregator setzte danach bei null quarantainierten Accounts trotzdem den
  Gesamtstatus auf `no-op`.
- Der Gesamtstatus bleibt jetzt `blocked`, sobald eine Instance blockiert ist.
  Kein irrefuehrender Erfolgstatus bei verweigerter Quarantaene.
- Regression: fehlender Report-Root -> `1 passed`; komplette
  `tests/test_admin_accounts.py` -> `85 passed`. Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c9eaa5a9 fix: preserve blocked quarantine status`.

**Aktueller Laufstand:** Seit dem Restart `20/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart jetzt erforderlich. Naechster Push bleibt erst
bei 100 Commits.

### Explizite-Instanznamen-ohne-Pfadescape

- 2026-07-17: `discover_instances(explicit=...)` gab Namen ungeprueft zurueck.
  `../`, absolute oder symlinked Instanzziele konnten dadurch Admin-/Recovery-
  Aufrufer aus dem Instances-Baum herausfuehren.
- Explizite Namen verwerfen jetzt Punkt-/Separatornamen, Symlink-Instanzen und
  symlinked `Bot_Verhalten.md`. Sichere, noch nicht angelegte Namen bleiben fuer
  bestehende Bootstrap- und Missing-Instance-Reports kompatibel.
- Regression: Symlink plus `../`/absolute Namen -> `1 passed`; komplette
  `tests/test_admin_accounts.py` -> `85 passed`. Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `cf2e200d fix: validate explicit instance discovery names`.

**Aktueller Laufstand:** Seit dem Restart `2/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 18 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Instanz-Discovery-ohne-Symlink-Rootkomponenten

- 2026-07-17: Der Explicit-/Automatic-Guard pruefte Root-Symlinks, aber nicht
  symlinked Elternkomponenten. Ein Rootpfad konnte dadurch dennoch auf einen
  externen Instances-Baum zeigen.
- `discover_instances()` lehnt jetzt Symlink-Komponenten in `instances_dir`
  fuer automatische und explizite Auswahl ab. Sichere Missing-Instance-
  Auswahl bleibt kompatibel.
- Regression: symlinked Root plus automatische/explicit Auswahl -> `1 passed`;
  komplette `tests/test_admin_accounts.py` -> `85 passed`. Ruff, `compileall`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `36c76a41 fix: reject symlinked instance root components`.

**Aktueller Laufstand:** Seit dem Restart `4/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 16 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Account-Reports-melden-Scanfehler

- 2026-07-17: Verschwand `accounts/` waehrend `_account_dirs().iterdir()`,
  konnte der Admin-Report abbrechen statt einen belastbaren Fehlerstatus zu
  liefern.
- `_build_store_report()` faengt den Scanfehler ab, markiert den Store als
  `readable=false` und zaehlt ihn als `store_error`.
- Regression: gezielter Scanfehler plus Symlinktest -> `2 passed`; komplette
  `tests/test_admin_accounts.py` -> `87 passed`. Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a73ee9b1 fix: report account directory scan errors`.

**Aktueller Laufstand:** Seit dem Restart `10/20` Commits. Kein Push. Restart
nach 10 weiteren Commits. Naechster Push bleibt erst bei 100 Commits.

### Explizite-Instanznamen-nur-Verzeichnisse

- 2026-07-17: Ein vorhandener regulaerer File mit explizitem Instanznamen
  wurde als sichere Auswahl akzeptiert. Nachfolgende Pfadlogik konnte ihn
  dadurch wie einen Instanzbaum behandeln.
- Explizite Auswahl verwirft jetzt vorhandene Nicht-Verzeichnisse. Noch nicht
  angelegte, sichere Namen bleiben fuer Bootstrap- und Missing-Instance-
  Reports kompatibel.
- Regression: regulaeres File plus Pfad-/Symlinknamen -> `3 passed`; komplette
  `tests/test_admin_accounts.py` -> `87 passed`. Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `4e2fcdcf fix: reject explicit file instance paths`.

**Aktueller Laufstand:** Seit dem Restart `12/20` Commits. Kein Push. Restart
nach 8 weiteren Commits. Naechster Push bleibt erst bei 100 Commits.

### Status-Auth-Bootstrap-nutzt-Discovery-Guard

- 2026-07-17: `bootstrap_status_auth_secrets()` umging `discover_instances()`.
  Explizite Pfadnamen wie `../outside` konnten dadurch Secret-Bootstrap
  ausserhalb des Instances-Baums erreichen.
- Bootstrap nutzt jetzt dieselbe sichere explizite Discovery. Sichere fehlende
  Instanznamen bleiben fuer den bestehenden Missing-Instance-Report erlaubt.
- Regression: Pfad-Escape plus Bootstrap-Fokus -> `5 passed`; komplette
  `tests/test_admin_accounts.py` -> `88 passed`. Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `29e91ad6 fix: constrain status auth bootstrap instances`.

**Aktueller Laufstand:** Seit dem Restart `13/20` Commits. Kein Push. Restart
nach 7 weiteren Commits. Naechster Push bleibt erst bei 100 Commits.

### Status-Auth-Report-fangt-Store-Init-Fehler

- 2026-07-17: `build_instance_status_auth_report()` liess
  `AccountStore(...)`-Fehler ungefangen. Fehlende oder inkompatible Keys
  konnten dadurch den gesamten Status-Auth-Report abbrechen.
- Store-Initialisierungsfehler werden jetzt als `status_auth.errors` mit
  `store_errors`-Totals erfasst; andere Instanzen bleiben berichtbar.
- Regression: erzwungener Init-Fehler plus Status-Auth-Fokus -> `10 passed`;
  komplette `tests/test_admin_accounts.py` -> `89 passed`. Ruff, `compileall`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `5f4d0c4a fix: report status auth store init failures`.

**Aktueller Laufstand:** Seit dem Restart `15/20` Commits. Kein Push. Restart
nach 5 weiteren Commits. Naechster Push bleibt erst bei 100 Commits.

### Account-Report-fangt-Store-Init-Fehler

- 2026-07-17: `build_instance_admin_report()` liess
  `AccountStore(...)`-Fehler ungefangen. Fehlende oder inkompatible Keys
  konnten dadurch den gesamten Account-Report abbrechen.
- Store-Initialisierungsfehler werden jetzt als `account_store.errors` mit
  `store_errors`-Totals erfasst. Identity-Health meldet dazu eine Warnung;
  andere Instanzen bleiben berichtbar.
- Regression: erzwungener Init-Fehler plus Store-Error-Fokus -> `2 passed`;
  komplette `tests/test_admin_accounts.py` -> `90 passed`. Ruff, `compileall`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `6670cfeb fix: report account store initialization failures`.

**Aktueller Laufstand:** Seit dem Restart `17/20` Commits. Kein Push. Restart
nach 3 weiteren Commits. Naechster Push bleibt erst bei 100 Commits.

### Direkte-Status-Auth-Helfer-validieren-Instanznamen

- 2026-07-17: `bootstrap_instance_status_auth_secrets()` und
  `build_instance_status_auth_report()` bauten Pfade direkt aus ihrem
  `instance_name`. Der sichere High-Level-Discovery-Guard galt bei direkten
  Aufrufen nicht.
- Beide Helfer validieren jetzt den Namen ueber `discover_instances()`, bevor
  ein Store-Pfad konstruiert wird. Unsichere Escapes liefern `ValueError`.
- Regression: beide direkten Path-Escape-Tests plus Bootstrap-/Report-Fokus ->
  `16 passed`; komplette `tests/test_admin_accounts.py` -> `91 passed`. Ruff,
  `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `61984917 fix: validate direct status auth instance paths`.

**Aktueller Laufstand:** Seit dem Restart `19/20` Commits. Kein Push. Restart
nach 1 weiterem Commit. Naechster Push bleibt erst bei 100 Commits.

### Account-Report-faengt-Read-Races

- 2026-07-17: Datei-/Account-Races, Permission-Fehler und ValueErrors wurden
  im Account-Report nur teilweise behandelt. `account_summary()` konnte den
  Report deshalb trotz vorheriger Guards abbrechen.
- Metadata-Leseoperationen und Account-Summary fangen jetzt
  `AccountStoreError`, `OSError` und `ValueError`; der Store wird als
  `readable=false` gemeldet.
- Regression: Summary-`OSError` plus Store-Error-Fokus -> `3 passed`; komplette
  `tests/test_admin_accounts.py` -> `92 passed`. Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `7687debb fix: tolerate account report read races`.

**Aktueller Laufstand:** Seit dem Restart `2/20` Commits. Kein Push. Restart
nach 18 weiteren Commits. Naechster Push bleibt erst bei 100 Commits.

### Recovery-Metadata-ValueErrors-fail-closed

- 2026-07-17: Metadata-Probe-`ValueError` wurde im Recovery-Health-Report
  und im Quarantaenepfad nicht abgefangen. Eine Parser-/Schemaabweichung
  konnte die taegliche Recovery abbrechen.
- Health- und Quarantaenepfad erfassen jetzt `ValueError` wie andere Probe-
  Fehler. Der Eintrag bleibt unlesbar; Apply wird nicht automatisch erlaubt.
- Regression: Metadata-`ValueError` plus Block-Fokus -> `2 passed`; komplette
  `tests/test_admin_accounts.py` -> `93 passed`. Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `bcc39275 fix: keep recovery metadata value errors reportable`.

**Aktueller Laufstand:** Seit dem Restart `5/20` Commits. Kein Push. Restart
nach 15 weiteren Commits. Naechster Push bleibt erst bei 100 Commits.

### Status-Auth-Export-verweigert-Symlink-Basis

- 2026-07-17: `_safe_output_path()` pruefte den `base_dir` erst nach
  `resolve()`. Ein symlinked Instances-Root konnte dadurch als gueltige
  Exportbasis erscheinen, obwohl Discovery ihn ablehnte.
- Die Basis wird jetzt vor Aufloesung auf Symlink-Komponenten geprueft und bei
  unsicherem Root abgelehnt.
- Regression: Output-Symlink-Basis plus Status-Auth-Fokus -> `8 passed`;
  komplette `tests/test_admin_accounts.py` -> `103 passed`. Ruff, `compileall`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `972876bc fix: reject symlinked status auth output bases`.

**Aktueller Laufstand:** Seit dem Restart `6/20` Commits. Kein Push. Restart
nach 14 weiteren Commits. Naechster Push bleibt erst bei 100 Commits.

### Direkter-Recovery-Report-validiert-Instanznamen

- 2026-07-17: `build_instance_recovery_report()` war direkt aufrufbar und
  baute `accounts_root` ohne Discovery-Validierung. Ein Pfad-Escape konnte
  externe Recovery-Quellen scannen.
- Der Helfer validiert den normalisierten Instanznamen jetzt ueber
  `discover_instances()`, bevor Recovery-Pfade entstehen.
- Regression: direkter Recovery-Path-Escape plus Metadata-Fokus -> `2 passed`;
  komplette `tests/test_admin_accounts.py` -> `94 passed`. Ruff, `compileall`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e8429193 fix: validate direct recovery instance paths`.

**Aktueller Laufstand:** Seit dem Restart `7/20` Commits. Kein Push. Restart
nach 13 weiteren Commits. Naechster Push bleibt erst bei 100 Commits.

### Recovery-JSON-Probe-ohne-Memory-Backend

- 2026-07-17: `_JsonProbeStore` initialisierte standardmaessig auch das
  Account-Memory-Backend. PostgreSQL-/SQLite-Probleme konnten dadurch eine
  reine JSON-Recovery stoeren; Store-Init-Fehler wurden nicht als Source
  gemeldet.
- JSON-Probe laeuft jetzt mit `memory_backend_enabled=False`. Init- und
  Leseprobleme werden pro JSON-Source als unlesbar erfasst.
- Regression: JSON-Source-Init-Fehler plus JSON-Fokus -> `3 passed`; komplette
  `tests/test_admin_accounts.py` -> `95 passed`. Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `0ecb9b8d fix: isolate JSON recovery probes from memory backend`.

**Aktueller Laufstand:** Seit dem Restart `9/20` Commits. Kein Push. Restart
nach 11 weiteren Commits. Naechster Push bleibt erst bei 100 Commits.

### Recovery-Quarantaene-blockt-unsicheren-Instances-Root

- 2026-07-17: `quarantine_unreadable_account_metadata()` behandelte
  symlinked/ungueltige Instances-Roots als leere Discovery und meldete danach
  `no-op`. Das konnte einen falschen Erfolg signalisieren.
- Symlinked oder vorhandene Nicht-Verzeichnis-Roots blockieren jetzt den
  Quarantaene-Scan explizit; kein Zielpfad wird angelegt.
- Regression: symlinked Root plus Metadata-Quarantaene-Fokus -> `10 passed`;
  komplette `tests/test_admin_accounts.py` -> `96 passed`. Ruff, `compileall`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a73526e7 fix: block quarantine on unsafe instances roots`.

**Aktueller Laufstand:** Seit dem Restart `11/20` Commits. Kein Push. Restart
nach 9 weiteren Commits. Naechster Push bleibt erst bei 100 Commits.

### Recovery-Snapshot-Scan-faengt-Glob-Fehler

- 2026-07-17: `_discover_snapshot_sqlite_sources()` liess
  `Path.glob()`-`OSError` ungefangen. Ein verschwundenes oder nicht lesbares
  Snapshot-Verzeichnis konnte den Recovery-Report abbrechen.
- Snapshot-Scanfehler liefern jetzt keine Snapshot-Kandidaten; aktive Quellen
  bleiben separat auswertbar.
- Regression: Snapshot-Glob-Fehler plus Snapshot-Fokus -> `6 passed`; komplette
  `tests/test_admin_accounts.py` -> `97 passed`. Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `268e1be8 fix: tolerate recovery snapshot scan races`.

**Aktueller Laufstand:** Seit dem Restart `13/20` Commits. Kein Push. Restart
nach 7 weiteren Commits. Naechster Push bleibt erst bei 100 Commits.

### Recovery-Snapshot-Scan-ueberspringt-Resolve-Fehler

- 2026-07-17: Snapshot-Discovery rief `Path.resolve()` vor dem Symlink-
  Filter auf. Symlink-Schleifen in alten Backups konnten dadurch einen
  `RuntimeError` und Report-Abbruch ausloesen.
- Unaufloesbare Snapshot-Kandidaten werden jetzt uebersprungen; aktive Quellen
  und andere Snapshots bleiben auswertbar.
- Regression: Glob- und Symlink-Loop-Fokus -> `2 passed`; komplette
  `tests/test_admin_accounts.py` -> `98 passed`. Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `24afd085 fix: skip unresolved recovery snapshots`.

**Aktueller Laufstand:** Seit dem Restart `15/20` Commits. Kein Push. Restart
nach 5 weiteren Commits. Naechster Push bleibt erst bei 100 Commits.

### Recovery-Source-Probes-isolieren-Fehler

- 2026-07-17: `_inspect_source()` liess Probe-Ausnahmen aus einzelnen
  SQLite-/JSON-Quellen bis zur Instanzliste durch. Eine fehlerhafte Source
  konnte dadurch den gesamten Recovery-Report stoppen.
- Probe-Ausnahmen werden jetzt in ein standardisiertes unlesbar-Source-
  Ergebnis umgewandelt; andere Accounts und Quellen bleiben auswertbar.
- Regression: Source-Probe-Fehler plus Snapshot-/JSON-Fokus -> `9 passed`;
  komplette `tests/test_admin_accounts.py` -> `99 passed`. Ruff, `compileall`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `2dd34a6e fix: isolate recovery source probe failures`.

**Aktueller Laufstand:** Seit dem Restart `17/20` Commits. Kein Push. Restart
nach 3 weiteren Commits. Naechster Push bleibt erst bei 100 Commits.

### Recovery-Quarantaene-fangt-Instanzfehler

- 2026-07-17: Fehler bei Snapshot, Delete oder Move konnten
  `quarantine_unrecoverable_account_memory()` trotz Sicherheitspruefungen als
  Exception verlassen. Ein einzelner Account-/Instanzfehler stoppte den Lauf.
- Fehler werden jetzt pro Instanz als `blocked` mit Fehlertext gemeldet;
  weitere Instanzen koennen separat bewertet werden. Keine Delete-Aktion nach
  fehlgeschlagenem Snapshot.
- Regression: Snapshot-Fehler plus Quarantaene-Fokus -> `4 passed`; komplette
  `tests/test_admin_accounts.py` -> `100 passed`. Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a227ca24 fix: report unrecoverable quarantine failures`.

**Aktueller Laufstand:** Seit dem Restart `19/20` Commits. Kein Push. Restart
nach 1 weiterem Commit. Naechster Push bleibt erst bei 100 Commits.

### Recovery-Metadata-Quarantaene-fangt-Instanzfehler

- 2026-07-17: Metadata-Quarantaene hatte noch keinen Per-Instanz-Exception-
  Guard. Fehler bei Move, Manifest oder Zielpfad konnten den Prozess abbrechen.
- Fehler werden jetzt pro Instanz als `blocked` gemeldet; aktive Daten bleiben
  bei fehlgeschlagenem Quarantaene-Schritt unangetastet.
- Regression: Metadata-Quarantaene-Fehler plus bestehende Recovery-Fokus-
  tests -> `4 passed`; komplette `tests/test_admin_accounts.py` -> `101
  passed`. Ruff, `compileall` und `git diff --check` gruen. Kein Provider/API-
  Aufruf.
- Code-Commit: `fdd3bdf8 fix: report metadata quarantine failures`.

**Aktueller Laufstand:** Seit dem Restart `1/20` Commits. Kein Push. Restart
nach 19 weiteren Commits. Naechster Push bleibt erst bei 100 Commits.

### Status-Auth-Export-verweigert-Symlink-Ziele

- 2026-07-17: `_safe_output_path()` loeste bestehende Symlinks innerhalb des
  erlaubten Roots auf. Export konnte dadurch ein anderes Ziel ueberschreiben;
  `Path.open()` bot keinen finalen No-Follow-Schutz.
- Symlink-Komponenten werden jetzt abgelehnt; der Export oeffnet Dateien mit
  `O_NOFOLLOW`.
- Regression: Symlink-Output-Fokus plus Status-Auth-Fokus -> `11 passed`;
  komplette `tests/test_admin_accounts.py` -> `102 passed`. Ruff, `compileall`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `26e44590 fix: refuse symlinked status auth output paths`.

**Aktueller Laufstand:** Seit dem Restart `3/20` Commits. Kein Push. Restart
nach 17 weiteren Commits. Naechster Push bleibt erst bei 100 Commits.

### Signal-Sync-Read-Receipts-aus-Raw-Payload

- 2026-07-17: `_signal_receipt_message_refs()` las nur geparste
  `message.read_messages` und `envelope.receiptMessage`. SignalBot kann bei
  `SYNC_MESSAGE`-Read-Receipts aber nur `envelope.syncMessage.readMessages`
  liefern; dann wurde kein Receipt verarbeitet.
- Raw-`syncMessage.readMessages` wird jetzt mit denselben Timestamp-Feldern wie
  der geparste Pfad ausgewertet. Doppelte Referenzen bleiben durch den
  bestehenden Receipt-Pfad idempotent.
- Regression: vorhandener Sync-Read-Test läuft jetzt ohne
  `message.read_messages` und prüft nur Raw-JSON; Signal-Adapter-/Runner-Suite
  `245 passed`; Ruff, `compileall` und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `ca8a8465 fix: parse signal sync read receipts from raw payload`.

**Aktueller Laufstand:** Seit dem Restart `0/20` Code-Commits. Kein Push.
Restart nach 20 weiteren Commits. Naechster Push bleibt erst bei 100 Commits.

### Signal-Reply-Text-aus-Raw-Envelope

- 2026-07-17: Der Signal-Adapter setzte `reply_to_text` nur aus dem geparsten
  `.quote`-Objekt. Signalbot kann dieses Objekt leer lassen, obwohl das
  Raw-Envelope die Quote unter `dataMessage.quote.text` liefert; Replys kamen
  dann ohne Bezugstext im Engine-Kontext an.
- Die Normalisierung liest jetzt als Fallback das Raw-Envelope. Ein vorhandenes
  geparstes Quote-Objekt bleibt bevorzugt; ungueltiges JSON oder fehlende Quote
  bleibt ohne Replytext.
- Regression: kompletter Adapter-/Signal-Runner-Lauf -> `245 passed`; Ruff,
  `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `938f5885 fix: preserve signal raw reply quotes`.

**Aktueller Laufstand:** Seit dem Restart `5/20` Code-Commits. Plan-Commit
zaehlt als naechster Commit. Kein Push. Restart nach 15 weiteren Commits.
Naechster Push bleibt erst bei 100 Commits.

### Codex-Worker-Pools-vollstaendig-scannen

- 2026-07-17: Der normale `codex-history`-Defaultscan akzeptierte unter
  `.codex-agents` nur exakt zweistellige Namen wie `a1`, `b1`, `c1`. Alle
  weiteren nummerierten Arbeiterbienen (`a2..a100`, `bX`, `cX`) fehlten dort;
  der Rootscan des Systemdienstes war davon nicht betroffen.
- Der Defaultfilter erlaubt jetzt nur bekannte Pools `a`, `b`, `c` mit einer
  positiven Nummer. Nicht-Pool-Verzeichnisse wie `templates` und `a0` bleiben
  ausgeschlossen.
- Regression: Codex-History-Fokus `13 passed`; komplette
  `tests/test_codex_history.py` -> `179 passed`; Ruff mit bestehender E402-
  Ausnahme, `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `20aef92d fix: scan all codex worker pools`.

**Aktueller Laufstand:** Seit dem Restart `7/20` Code-Commits. Plan-Commit
zaehlt als naechster Commit. Kein Push. Restart nach 13 weiteren Commits.
Naechster Push bleibt erst bei 100 Commits.

### Status-Auth-Export-vermeidet-Short-Write

- 2026-07-17: `_write_status_auth_report()` nutzte einen einzelnen
  `os.write()`-Aufruf und ignorierte moegliche Short Writes. Grosse JSON-/Text-
  Reports konnten dadurch unvollstaendig auf Disk landen.
- Export nutzt jetzt den gepufferten File-Handle-Schreibpfad bei weiterhin
  aktivem `O_NOFOLLOW`.
- Regression: Status-Auth-CLI-Fokus -> `7 passed`; komplette
  `tests/test_admin_accounts.py` -> `102 passed`. Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `2a055e22 fix: complete status auth report writes`.

**Aktueller Laufstand:** Seit dem Restart `5/20` Commits. Kein Push. Restart
nach 15 weiteren Commits. Naechster Push bleibt erst bei 100 Commits.

### JSON-Recovery-erkennt-dangling-Symlinks

- 2026-07-17: JSON-Recovery pruefte Entries-/Index-Dateien erst nach
  `exists()`. Dangling Symlinks wurden dadurch wie fehlende Dateien als leer
  behandelt und konnten einen falschen leeren Recovery-Befund erzeugen.
- `is_symlink()` wird jetzt vor `exists()` geprueft. Dangling JSON-Symlinks
  blockieren die Recovery fail-closed und werden nicht verschoben.
- Regression: JSON-Recovery-Symlink-Fokus -> `2 passed`; Ruff, `compileall`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `de5df753 fix: reject dangling json recovery symlinks`.

**Aktueller Laufstand:** Seit dem Restart `8/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 12 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### SQLite-Recovery-Delete-bleibt-auf-stabilem-FD

- 2026-07-17: `_delete_sqlite_account_rows()` pruefte Source und Sidecars,
  oeffnete danach aber erneut per Pfadnamen. Ein Pfadwechsel zwischen Guard und
  `sqlite3.connect()` konnte Rows in einer fremden SQLite-Datei loeschen.
- Delete oeffnet die Quelle jetzt einmal mit `O_NOFOLLOW`, prueft regulaeren
  Datei-Inode und `st_nlink == 1` und verbindet ueber stabilen
  `/proc/self/fd`-URI. WAL-Verhalten bleibt erhalten; Pfadwechsel blockiert.
- Regression: gezielter Hardlink-/Race-Fokus -> `2 passed`; komplette
  `tests/test_admin_accounts.py` -> `105 passed`. Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `21e0e3c4 fix: delete sqlite recovery rows through stable fd`.

**Aktueller Laufstand:** Seit dem Restart `10/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 10 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### SQLite-Recovery-Delete-verweigert-Parent-Symlink-Race

- 2026-07-17: `O_NOFOLLOW` am finalen SQLite-Dateinamen schuetzte nicht vor
  einem gleichzeitig umgebogenen Parent-Verzeichnis. Ein Pfadwechsel konnte
  dadurch weiterhin eine externe Datei oeffnen.
- Parent-Komponenten werden jetzt einzeln relativ zu Directory-FDs mit
  `O_NOFOLLOW|O_DIRECTORY` geoeffnet. Der finale Descriptor bleibt stabil;
  Parent-Symlink-Races blockieren fail-closed.
- Regression: finaler Source-Race plus Parent-Directory-Swap -> `3 passed`;
  komplette `tests/test_admin_accounts.py` -> `106 passed`. Ruff,
  `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `cd887156 fix: open sqlite recovery parents without symlink traversal`.

**Aktueller Laufstand:** Seit dem Restart `12/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 8 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Quarantaene-Dateien-ueber-stabile-Parent-FDs-reservieren

- 2026-07-17: Snapshot- und Manifest-Ziele wurden nach sicherer
  Verzeichnispruefung wieder per absolutem Pfad mit `os.open()` angelegt. Ein
  Parent-Swap konnte dadurch die Zielerstellung umleiten.
- Snapshot und Manifest reservieren Dateien jetzt exklusiv relativ zu einem
  stabil geoeffneten Parent-FD mit `O_NOFOLLOW`; Snapshot-SQLite nutzt den
  stabilen Descriptor direkt. Kein unsicherer Cross-Filesystem-Fallback.
- Regression: Snapshot-/Manifest-/Quarantaene-Fokus -> `28 passed`; komplette
  `tests/test_admin_accounts.py` -> `106 passed`. Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `d71e22f7 fix: reserve quarantine files through stable parent fds`.

**Aktueller Laufstand:** Seit dem Restart `14/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 6 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Quarantaene-Manifest-vor-Move-reservieren

- 2026-07-17: Quarantaene schrieb Manifest erst nach allen Moves. Scheiterte
  der letzte Schreibschritt, konnten bereits verschobene Daten ohne belastbare
  Dokumentation bleiben.
- Manifest wird vor dem ersten Move exklusiv reserviert, als `in_progress`
  geschrieben und ueber denselben stabilen FD finalisiert. Bei Zwischenfehlern
  bleibt mindestens ein nachvollziehbarer unvollstaendiger Zustand erhalten.
- Regression: Snapshot-/Manifest-/Quarantaene-Fokus -> `28 passed`; komplette
  `tests/test_admin_accounts.py` -> `106 passed`. Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `92fda508 fix: reserve quarantine manifests before moving data`.

**Aktueller Laufstand:** Seit dem Restart `16/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 4 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### Recovery-Discovery-behaelt-dangling-SQLite-Quellen

- 2026-07-17: Primary-/Fallback-Symlinks wurden wegen `exists()` nicht als
  Recovery-Quellen aufgenommen. Zusaetzlich konnte `source.path.resolve()` bei
  einer Symlink-Schleife den gesamten Report abbrechen.
- Symlink-Quellen werden jetzt auch dangling erfasst und spaeter als unlesbar
  geprüft. `resolve()`-Fehler pro Quelle werden isoliert; der Report laeuft
  weiter und verschweigt keine kaputten SQLite-Artefakte.
- Regression: dangling-/looped-SQLite-Source-Discovery plus Snapshot-Fokus ->
  `3 passed`; komplette `tests/test_admin_accounts.py` -> `107 passed`. Ruff,
  `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `846a4ba2 fix: retain broken sqlite sources during recovery discovery`.

**Aktueller Laufstand:** Seit dem Restart `18/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 2 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### SQLite-Recovery-Read-kopiert-ueber-stabile-FDs

- 2026-07-17: `_connect_sqlite_readonly()` kopierte Source und WAL/SHM per
  `shutil.copy2(path)` nach einer vorigen Pfadpruefung. Ein Race konnte dadurch
  fremde SQLite-Daten in den Recovery-Report einlesen.
- SQLite-Datei und Sidecars werden jetzt aus stabilen, no-follow geoeffneten
  FDs kopiert; Inode, Regular-File-Status und Hardlinkzahl werden erneut
  geprueft. Source-Swap blockiert fail-closed.
- Regression: stabiler Read-Source-Swap plus SQLite-FD-Fokus -> `3 passed`;
  komplette `tests/test_admin_accounts.py` -> `108 passed`. Ruff, `compileall`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `3527ca98 fix: copy sqlite recovery sources through stable fds`.

**Aktueller Laufstand:** Seit dem Restart `20/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart jetzt. Naechster Push bleibt erst bei 100
Commits.

### Status-Auth-Export-schreibt-ueber-stabile-Parent-FDs

- 2026-07-17: `_write_status_auth_report()` pruefte Output-Basis und Ziel,
  oeffnete danach aber wieder per absolutem Pfad. Ein Parent-Swap konnte den
  Status-Report auf ein fremdes Ziel umlenken.
- Output-Parent-Komponenten werden jetzt einzeln mit `O_NOFOLLOW|O_DIRECTORY`
  geoeffnet; die Zieldatei wird relativ zum stabilen Parent-FD mit
  `O_NOFOLLOW` geschrieben. Systeme ohne diese Schutzflags blockieren.
- Regression: Status-Auth-Report-Fokus -> `13 passed`; komplette
  `tests/test_admin_accounts.py` -> `109 passed`. Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e43b05d6 fix: write status auth reports through stable parent fds`.

**Aktueller Laufstand:** Seit dem Restart `2/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 18 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### SQLite-Memory-Config-verweigert-Symlink-Pfade

- 2026-07-17: SQLite-Primary/Fallback-Pfade konnten ueber Symlink-Komponenten
  konfiguriert werden. `_connect()` haette danach fremde Ziele verfolgen und
  Memory-Daten ausserhalb des vorgesehenen Baums schreiben koennen.
- Backend-Init verweigert jetzt Symlink-Komponenten und unsichere
  `resolve()`-Fehler fail-closed; bestehende Hardlink-Pruefung bleibt aktiv.
- Regression: SQLite-Config-Fokus -> `5 passed`; komplette
  `tests/test_account_store.py` -> `292 passed`. Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `96cec064 fix: reject symlinked sqlite memory paths`.

**Aktueller Laufstand:** Seit dem Restart `4/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 16 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### SQLite-Memory-Guard-prueft-auch-Primary-ohne-Fallback

- 2026-07-17: Der neue Symlink-Guard kehrte bei `fallback_path=None` zu frueh
  zurueck. Primary-only SQLite konnte deshalb weiterhin ueber einen Symlink
  geoeffnet und beschrieben werden.
- Primary wird jetzt immer auf Symlink-Komponenten und sichere Aufloesbarkeit
  geprueft; Fallback-Distanzpruefung bleibt optional danach.
- Regression: SQLite-Config-Fokus inklusive Primary-only -> `6 passed`; komplette
  `tests/test_account_store.py` -> `293 passed`. Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `0aca51a6 fix: guard primary-only sqlite memory paths`.

**Aktueller Laufstand:** Seit dem Restart `6/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 14 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

### SQLite-Memory-Blob-Typen-fail-closed-behandeln

### Nichtleere-schemalose-SQLite-DB-wird-diagnostiziert

- 2026-07-17: SQLite-Reads akzeptierten eine vorhandene, nichtleere Datenbank
  ohne Memory-Schema als leeres Memory, solange kein Fallback existierte.
  Dadurch konnten echte oder beschaedigte Datenbanken im Status unsichtbar
  bleiben.
- Eine 0-Byte-Erststartdatei bleibt kompatibel und liefert weiterhin leere
  Ergebnisse. Bei vorhandener Dateisubstanz wird fehlendes
  memory_entries-/Index-/Collection-Schema als Read-Diagnose gemeldet;
  Fallback-Recovery bleibt unveraendert.
- Regression: SQLite-Schema-Fokus -> 4 passed; kompletter
  tests/test_account_store.py-Lauf -> 309 passed; compileall und
  git diff --check gruen. Kein Provider/API-Aufruf.
- Code-Commit: f5a123a7 fix: diagnose nonempty sqlite databases without schema.

**Aktueller Laufstand:** Seit dem Restart 18/20 Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 2 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.

- 2026-07-17: Read-/Guard-Pfade konvertierten Non-BLOB-Werte direkt mit
  `bytes(...)`. Beschaedigte TEXT-/NULL-Spalten konnten dadurch per `TypeError`
  aus dem Memorypfad ausbrechen.
- Payload-Coercion laeuft jetzt zentral ueber `AccountStoreError`; Read, Index,
  Collection und destruktive Write-Guards behandeln falsche BLOB-Typen als
  korrupt und schuetzen vor ungeprueftem Weiterarbeiten.
- Regression: Blob-Korruptionsfokus -> `2 passed`; komplette
  `tests/test_account_store.py` -> `294 passed`. Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `01ef5c49 fix: classify malformed sqlite blobs as corrupt`.

**Aktueller Laufstand:** Seit dem Restart `8/20` Commits. Dieser Plan-Commit
zaehlt mit. Kein Push. Restart nach 12 weiteren Commits. Naechster Push bleibt
erst bei 100 Commits.
### SQL-only-Accounts-im-Status

- 2026-07-17: `account_memory_index_health_lines()` leitete zu pruefende
  Accounts nur aus `accounts/<account_id>`-Verzeichnissen ab. Entries/Indices
  in SQLite oder PostgreSQL ohne Profil wurden deshalb als `status=none`
  unsichtbar.
- Status entdeckt Account-IDs jetzt read-only aus aktiven SQL-Backends und
  vereinigt sie mit Profil-Accounts. Fehlendes Profil bei vorhandenen
  Datenbankdaten wird als `status=broken error=profile_missing_for_database_account`
  gemeldet; Instance-State bleibt separat.
- Regression: SQL-only-Account-Health plus bestehende Status-Health-Tests ->
  `17 passed`; komplette `tests/test_version_notifications.py` -> `220 passed`.
  Ruff, `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `97e138af fix: report database-only memory accounts`.

**Aktueller Laufstand:** Seit dem Restart `1/20` Commits. Kein Push. Restart
nach 19 weiteren Commits. Naechster Push bleibt erst bei 100 Commits.
### Read-only-Memory-Health-fuer-SQL

- 2026-07-17: PostgreSQL-`read_entries()` und `read_index()` initialisierten
  beim Statuscheck fehlende Tabellen per `CREATE TABLE/INDEX`. Der Fallback-
  Reader konnte bei Healthchecks ausserdem die Primary-Datenbank reparieren.
- Healthchecks verwenden jetzt eigene read-only Reader. PostgreSQL prueft nur
  `information_schema`; SQLite bleibt read-only; der Fallback nutzt Secondary-
  Daten ohne Promotion/Repair und meldet ausstehende Reparatur sichtbar.
- Regressionen: PostgreSQL read-only ohne Schema-DDL -> `3 passed`; Fallback-
  Read-only ohne Repair -> `3 passed`; komplette `tests/test_account_store.py`
  -> `315 passed`; Memory-Benchmark plus Status/Notifications -> `240 passed`.
  Ruff, `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `62f8c633 fix: keep memory health checks read-only`.

**Aktueller Laufstand:** Seit dem Restart `3/20` Commits. Kein Push. Restart
nach 17 weiteren Commits. Naechster Push bleibt erst bei 100 Commits.

### Telegram-Gruppen-Callback-Buttons

- 2026-07-17: Bei Telegram-`callback_query` wurde `message.from` (der Bot)
  durch `callback_query.from` (klickender Nutzer) ersetzt. In Gruppen verlor
  die Buttonantwort dadurch `reply_to_bot`; der Eingangsfilter konnte sie als
  nicht adressierte freie Nachricht verwerfen.
- Die synthetische Callback-Nachricht bewahrt die originale Bot-Quelle unter
  internem Feld. `_is_reply_to_bot()` nutzt diese Quelle für Gruppenrouting;
  normale Replies bleiben unveraendert.
- Regression: Callback-Fokus `3 passed`; komplette Adapter-/Bot-Suite
  `356 passed` plus `17 subtests`; Ruff, `compileall` und `git diff --check`
  gruen. Kein Provider/API-Aufruf.
- Code-Commit: `3a9857bb fix: preserve telegram callback bot origin`.

**Aktueller Laufstand:** Seit dem Restart `2/20` Commits. Kein Push. Restart
nach 18 weiteren Commits. Naechster Push bleibt erst bei 100 Commits.

### SQL-Artefakt-Accounts-blockieren-keinen-Startup-mehr

- 2026-07-17: `_sqlite_memory_account_ids()` und das PostgreSQL-Gegenstück
  nahmen alle `account_jsonl_collections` als Memory-Accounts. Status-, Codex-
  und andere Outbox-Zeilen ohne Account-Profil wurden dadurch als
  `profile_missing_for_database_account` markiert; Preflight blockierte den
  gesamten Service, obwohl strukturierte Memorytabellen gesund waren.
- Account-ID-Ermittlung für Memory-Health beschränkt sich jetzt auf
  `memory_entries`, `memory_indexes` und `memory_keywords`. Die separate
  Payload-Existenzprüfung für Secret-Schutz behält Collections ausdrücklich.
- Regression: SQLite-Artifact-only-Health plus bestehender Test -> `2 passed`;
  kompletter Status-/Account-Store-Lauf `536 passed`; Runtime-Status Exit `0`
  ohne falsche `profile_missing`-Zeilen; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `3376b89c fix: ignore artifact-only accounts in memory health`.
- Service danach ohne Emergency-Override neu gestartet: `active/running`,
  Exit `0`, PID `3221260`.

**Aktueller Laufstand:** Seit dem letzten Restart `0/20` Code-Commits. Kein
Push. Plan-Commit zaehlt als naechster Commit. Restart nach 20 weiteren
Commits. Naechster Push bleibt erst bei 100 Commits.

### Proactive-Outbox-Claim-ohne-Selbstdeadlock

- 2026-07-17: `_claim_proactive_worker_job_if_allowed()` hielt den
  Proactive-Outbox-Lock und rief danach `claim_proactive_worker_job()` auf.
  Dieses rief die oeffentliche Statusfunktion mit demselben Lock erneut auf.
  Bei einem normalen `threading.Lock` hing der Worker vor
  `queued -> dispatching`.
- Statusuebergang in lock-internen Helper extrahiert. Oeffentliche Funktion
  validiert weiter Eingaben; der Policy-Claim schreibt atomar im bereits
  gehaltenen Lock. Keine Abhaengigkeit von `RLock`-Reentranz.
- Regression: normaler `threading.Lock` plus Policy-Claim reproduziert und
  behoben; fokussierte Claim-/Dispatch-Tests `3 passed`; kompletter
  `tests/test_proactive_agent.py`-Lauf `130 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `1fd9579a fix: avoid proactive outbox claim deadlock`.

**Aktueller Laufstand:** Seit dem letzten Restart `2/20` Code-Commits. Kein
Push. Restart nach 18 weiteren Commits. Naechster Push bleibt erst bei 100
Commits.

### Stateful-LLM-State-pro-Chat-Scope

- 2026-07-17: `previous_response_id` wurde nur unter
  `(instance_name, account_id)` gehalten. Verknuepfte Telegram-/Signal-
  Identitaeten und verschiedene Chats konnten deshalb Stateful-Kontext teilen;
  `/reset` loeschte ausserdem accountweit.
- Engine bildet jetzt Scope aus Kanal, Adapter-Slot, Chattyp und Chat-ID.
  Stateful Lookup, Write, stale-Recovery und `/reset` nutzen denselben Scope.
  Account-Memory bleibt absichtlich geteilt. Persistenz liegt verschluesselt in
  `LLM_State.json` bzw. SQL-Collection unter
  `previous_response_conversations`; alte top-level Felder bleiben als
  Legacy-Spiegel erhalten.
- Scoped State nutzt 3-Tuple-In-Memory-Keys. Scoped Reset entfernt nur Ziel-
  Scope; unscoped Reset bleibt accountweit kompatibel. Alte top-level States
  werden nur solange als Legacy-Fallback gelesen, bis Mapping existiert.
- Regression: State-/Persistenzfokus `82 passed` ohne zwei bekannte,
  themenfremde Account-Lock-Symlinkfehler; Engine-State-/Scope-Fokus `4
  passed`; Ruff, `compileall` und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `7864b276 fix: scope stateful llm context per chat`.

**Aktueller Laufstand:** Seit dem letzten Restart `4/20` Code-Commits. Kein
Push. Restart nach 16 weiteren Commits. Naechster Push bleibt erst bei 100
Commits.

### Account-Lock-Symlink-Fehler-unter-Python-3-14

- 2026-07-17: Der sichere Account-Pfad oeffnete bei Symlink-Komponenten unter
  Python 3.14/Linux nicht nur `ELOOP`, sondern auch `ENOTDIR`. Dadurch konnten
  unsichere Lock-Pfade als rohe `NotADirectoryError` nach aussen gelangen.
- `ELOOP` und `ENOTDIR` werden jetzt einheitlich als `AccountStoreError`
  gemeldet. Der bereits geoeffnete Descriptor wird vor jeder Weitergabe
  geschlossen. Die Migration alter Artefakte bewahrt ihren kontextreichen
  Fehlertext.
- Tests: Symlink-/Hardlink-Fokus `3 passed`, kompletter
  `tests/test_account_store.py`-Lauf `315 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `9abdb440 fix: normalize unsafe account lock path errors`.

**Aktueller Laufstand:** Seit dem letzten Restart `6/20` Code-Commits. Kein
Push. Restart nach 14 weiteren Commits. Naechster Push bleibt erst bei 100
Commits.

### Residence-Memory-Schreibfehler-wiederholen

- 2026-07-17: Wetterkontext speicherte eine erkannte Stadt im Runtime-State,
  verschluckte aber einen fehlgeschlagenen Memory-Append. Bei derselben Stadt
  wurde danach wegen des bereits gesetzten Statewerts nie erneut versucht.
- Explizite Stadterkennung versucht den deduplizierten Memory-Append jetzt bei
  jeder passenden Nachricht erneut; der Helper verhindert weiterhin Duplikate.
- Tests: Weather-Fokus `11 passed`; Ruff und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `44e9ff8b fix: retry residence memory persistence`.

**Aktueller Laufstand:** Seit dem letzten Restart `8/20` Code-Commits. Kein
Push. Restart nach 12 weiteren Commits. Naechster Push bleibt erst bei 100
Commits.

### Unvollstaendige-Proactive-Claims-recovern

- 2026-07-17: `dispatching`-Items ohne parsebaren Claim-Zeitstempel wurden
  dauerhaft uebersprungen. Sie blieben unsichtbar, obwohl kein aktiver Lease
  mehr nachweisbar war.
- Recovery nimmt solche Items jetzt ebenfalls nach Lease-Grenze zurueck nach
  `queued` und kennzeichnet den Audit-Grund mit
  `_missing_claim_timestamp`. Aktive, junge Claims bleiben geschuetzt.
- Tests: Proactive-Fokus `131 passed`; Ruff und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `48179737 fix: recover incomplete proactive claims`.

**Aktueller Laufstand:** Seit dem letzten Restart `9/20` Code-Commits. Kein
Push. Restart nach 11 weiteren Commits. Naechster Push bleibt erst bei 100
Commits.

### Proactive-Policy-Block-nicht-terminalisieren

- 2026-07-17: Due-Items wurden bei Pause, Zeitfenster, Tageslimit,
  Mindestabstand, adaptiver Ruhezeit oder fehlender Route terminal als
  `skipped` markiert. Spaetere gueltige Zustellung war dadurch verloren.
- Transiente Policy-Gruende lassen das Item jetzt unveraendert `queued`; harte
  Sicherheits-, Einwilligungs- und Strukturfehler bleiben terminal.
- Tests: Regression prueft ausserhalb/innerhalb Zeitfenster; Proactive-Fokus
  gruen. Kein Provider/API-Aufruf.
- Code-Commit: `370ac1f3 fix: retain proactive jobs across transient policy blocks`.

**Aktueller Laufstand:** Seit dem letzten Restart `10/20` Code-Commits. Kein
Push. Restart nach 10 weiteren Commits. Naechster Push bleibt erst bei 100
Commits.

### Proactive-Senderfehler-retry

- 2026-07-17: Ein transienter Timeout-/Netzwerkfehler setzte ein bereits
  geclaimtes Item direkt terminal auf `failed`; `dispatch_attempts` wurde nicht
  fuer Wiederholung genutzt.
- Retryfaehige Timeout-/Netzwerk-/429-/5xx-Fehler gehen jetzt hoechstens zwei
  Mal mit 60/120 Sekunden Backoff zurueck nach `queued`. `retry_at` wird im
  Due-Filter und Health-Check beruecksichtigt; Versuch drei bleibt terminal
  `failed`.
- Tests: `tests/test_proactive_agent.py` und
  `tests/test_notification_loudness.py`: `299 passed`; Ruff und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `39d8ca91 fix: retry transient proactive send failures`.

**Aktueller Laufstand:** Seit dem letzten Restart `11/20` Code-Commits. Kein
Push. Restart nach 9 weiteren Commits. Naechster Push bleibt erst bei 100
Commits.

### Fallback-Mirror-Audit-false-positive

- 2026-07-17: Biene meldete, `_mirror_write()` loesche nach erfolgreicher
  Reparatur den `unrecoverable`-Marker nicht.
- Gegenpruefung: Der globale `_write()`-Guard blockiert jeden normalen Write vor
 `_mirror_write()`, solange der Account unrecoverable ist. Marker-Loeschung im
 Mirror waere daher heute unerreichbar und koennte den Fail-Closed-Schutz
 verwischen. Kein Code-Fix.

### Telegram-Journal-Cleanup-wiederholen

- 2026-07-17: Nach erfolgreichem Telegram-Offset-Write wurde ein fehlgeschlagenes
  `TelegramDispatchJournal.complete()` nur geloggt. Der Update-Offset war schon
  bestaetigt, aber der alte Journal-Eintrag blieb ohne weiteren Cleanup-Versuch.
- Fehlgeschlagene Cleanup-Keys werden jetzt im Runtime-Kontext gesammelt und vor
  jedem weiteren Poll erneut finalisiert. Der Update-Handler laeuft dabei nicht
  erneut; nur Journal-Aufraeumung wird wiederholt.
- Tests: Telegram-Polling-Fokus `2 passed`; Ruff und `git diff --check` gruen.
  Kein Provider/API-Aufruf.
- Code-Commit: `83cdafb6 fix: retry Telegram journal cleanup`.

**Aktueller Laufstand:** Seit dem letzten Restart `14/20` Commits. Kein Push.
Restart nach 6 weiteren Commits. Naechster Push bleibt erst bei 100 Commits.

### Admin-Status-Outbox-Fehlerisolierung

- 2026-07-17: `_record_runtime_status_dispatch()` kapselte nur das Schreiben
  von `status_dispatch_results`. Fehler beim Status-Outbox-Read/Write brachen
  die gesamte Admin-Schleife ab; nachfolgende Admins erhielten keinen Versand.
- Outbox-Statusupdate und Dispatch-Result-Persistenz sind jetzt getrennt
  best-effort gekapselt. Ein kaputtes Konto stoppt keine weiteren Empfaenger.
- Tests: Runtime-Admin-Fokus `3 passed`; Ruff und `git diff --check` gruen.
  Kein Provider/API-Aufruf.
- Code-Commit: `63a586f4 fix: isolate status outbox persistence failures`.

### Cross-Instance-Admin-Opt-out

- 2026-07-17: Bei Cross-Instance-Routen wurde `admin_opt_out` nur im lokalen
  TBL-Store geprueft. Abmeldung in Quellinstanz `Depressionsbot` konnte deshalb
  weiterhin Status-/Benchmark-Nachrichten ausloesen.
- Routen tragen jetzt ihren Quellstore; vor Queue und Versand wird Opt-out am
  tatsaechlichen Quellstore geprueft. Abgemeldete Accounts werden nicht queued.
- Tests: Runtime-Admin-Fokus `4 passed`; Ruff und `git diff --check` gruen.
  Kein Provider/API-Aufruf.
- Code-Commit: `875e0b93 fix: honor cross-instance admin opt-out`.

**Aktueller Laufstand:** Seit dem letzten Restart `17/20` Commits. Kein Push.
Restart nach 3 weiteren Commits. Naechster Push bleibt erst bei 100 Commits.

### Vollstaendiger-Offline-Regressionslauf

- 2026-07-17: Nach allen Fixes vollstaendigen Testbestand erneut ausgefuehrt.
- Ergebnis: `4023 passed`, `3 skipped`, `17 subtests passed`; kein Failure.
- Einziger Hinweis: externe LangChain/Pydantic-V1-Warnung unter Python 3.14.
  Kein Provider-/API-Aufruf und keine Netzsendung.

**Aktueller Laufstand:** Seit dem letzten Restart `7/20` Code-Commits. Kein
Push. Restart nach 13 weiteren Commits. Naechster Push bleibt erst bei 100
Commits.

### Veraltete-Reminder-Erwartung-im-Identity-Test

- 2026-07-17: `test_engine_uses_structured_memory_candidate_for_safe_semantic_memory`
  erwartete noch einen `ReminderDecision`-Aufruf fuer jede freie Nachricht.
  Seit `5ac383e6` wird dieser teure Pfad lokal durch Erinnerungshinweise
  gegated; die getestete Nachricht enthaelt keinen solchen Hinweis.
- Test auf den tatsaechlichen Vertrag korrigiert: genau ein
  `MemoryCandidate`-Aufruf. Produktionscode unveraendert.
- Tests: `tests/test_engine_identity_flows.py` `189 passed`,
  `tests/test_reminder_intent.py` `39 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Test-Commit: `73c5d0b7 test: align structured memory call expectation`.

**Aktueller Laufstand:** Seit dem letzten Restart `9/20` Code-Commits. Kein
Push. Restart nach 11 weiteren Commits. Naechster Push bleibt erst bei 100
Commits.

### SQLite-Recovery-Symlink-Guard-vor-Backend-Konstruktion

- 2026-07-17: `_read_sqlite_snapshot_payloads()` konstruierte den SQLite-
  Backend-Wrapper vor dem Recovery-eigenen Sicherheitsguard. Symlink-/Hardlink-
  Pfade wurden dadurch zwar abgelehnt, aber als generische Backend-
  Validierungsfehler zurueckgegeben; der Recovery-Vertrag mit genauer
  Fail-Closed-Diagnose ging verloren.
- `_reject_unsafe_sqlite_link(path, label="source")` laeuft jetzt vor der
  Backend-Konstruktion. Sicherheitsfehler werden als Recovery-Fehler gesammelt;
  leere Payloads bleiben erhalten. Sidecar-Pruefung bleibt im read-only
  Connector.
- Tests: Symlink-/Hardlink-Fokus `3 passed`, kompletter
  `tests/test_admin_accounts.py`-Lauf `109 passed`; Ruff und `compileall`
  gruen. Kein Provider/API-Aufruf.
