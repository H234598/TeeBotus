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
- Code-Commit: `30940718 fix: fail closed on sqlite recovery path validation`.

**Aktueller Laufstand:** Seit dem letzten Restart `11/20` Code-Commits. Kein
Push. Restart nach 9 weiteren Commits. Naechster Push bleibt erst bei 100
Commits.

### Memory-Reset-Flow-verschluckt-keine-Fremd-Chats-mehr

- 2026-07-17: Ein offener `/reset_memorys`-Flow in Chat A lieferte bei einem
  Event aus Chat/Kanal B `[]`. Der aufrufende Engine-Pfad wertete diese leere
  Liste als `handled=True`; normale Nachrichten im fremden Scope wurden
  dadurch lautlos verworfen.
- Scope-Mismatch liefert jetzt `None`. Dadurch laeuft fremdes Event normal
  weiter; bestaetigen oder loeschen kann weiterhin nur Original-Scope.
- Regression erweitert: fremder Chat sendet `/ping`, erhaelt zehn `Pong`s,
  Memory bleibt unveraendert. Identity-Suite `189 passed`; Ruff, `compileall`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `80c7dadf fix: let foreign memory reset chats continue`.

**Aktueller Laufstand:** Seit dem letzten Restart `13/20` Code-Commits. Kein
Push. Restart nach 7 weiteren Commits. Naechster Push bleibt erst bei 100
Commits.

### Pending-Flows-nach-Conversation-Scope

- 2026-07-17: `RuntimeState` hatte nur einen Pending-Slot je
  `(instance, account_id, flow_type)`. Startete derselbe Account denselben
  Flow in Chat B, wurde Chat A still ueberschrieben; Follow-up in A lief ins
  Leere.
- Pending-Key akzeptiert jetzt optionalen Scope aus Kanal, Adapter-Slot,
  Chattyp, Chat-ID und Identity. Engine und AccountCommandHandler reichen ihn
  fuer RouteTo, Admin, Account-Edit, Emergency, Memory-Reset und YouTube durch.
  Mehrere gleiche Flows bleiben parallel isoliert.
- Unscoped Legacy-API bleibt kompatibel: eindeutiger scoped Flow wird gelesen,
  mehrere scoped Flows werden absichtlich nicht geraten; alte 3-Tuple-States
  bleiben lesbar.
- Tests: Runtime-State `85 passed`, Engine-Identity `190 passed`; Ruff,
  `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c0fe55ae fix: scope pending flows per conversation`.

**Aktueller Laufstand:** Seit dem letzten Restart `15/20` Code-Commits. Kein
Push. Restart nach 5 weiteren Commits. Naechster Push bleibt erst bei 100
Commits.

### Offline-Benchmarks-respektieren-Produktions-Gates

- 2026-07-17: Der Decision/Qdrant-Benchmark erzeugte normalen Schlaf-/Struktur-
  Text ohne Reminder-Cue. Die Produktion ueberspringt damit absichtlich den
  strukturierten Reminder-Providerpfad; der Benchmark erwartete trotzdem
  `ReminderDecision` und meldete alle Decision-Pfade als fehlerhaft.
- Benchmark-Text nutzt jetzt einen lokalen Cue (`auf dem Schirm`) ohne faellige
  Erinnerung. Der Fake-Runner prueft dadurch den strukturierten Decision-Pfad
  weiter, ohne Provider/API-Aufruf oder Netzsendung.
- Proactive-Benchmark plante bei `10:30` zwei Nachrichten fuer `10:00` und
  konnte wegen der echten `due_at`-Validierung nichts queuen. Fixture trennt
  jetzt Planzeit `09:30` und Dispatchzeit `10:30`; `10:00` bleibt faellig.
- Tests: fokussierte Benchmark-Regression `3 passed`; Decision-Matrix und
  Proactive-Plan/Dispatch jeweils `ok=True`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `65ff4a26 fix: align offline benchmarks with runtime gates`.

**Aktueller Laufstand:** Seit dem letzten Restart `17/20` Code-Commits. Kein
Push. Restart nach 3 weiteren Commits. Naechster Push bleibt erst bei 100
Commits.

### Proactive-CLI-stellt-Prozessumgebung-wieder-her

- 2026-07-17: `TeeBotus.proactive.main()` lud `.env`-Werte in globale
  `os.environ`, stellte sie bei direktem Funktionsaufruf aber nicht wieder her.
  Das verursachte Test- und eingebettete-CLI-Leaks.
- Oeffentliche Funktion snapshotet die Umgebung, nutzt geladene Werte waehrend
  des Laufs und stellt danach den vorherigen Prozesszustand wieder her.
- Tests: Proactive-CLI-Fokus `3 passed`; Ruff und `compileall` gruen.
  Kein Provider/API-Aufruf.
- Code-Commit: `4caee093 fix: restore environment after proactive cli`.

**Aktueller Laufstand:** Seit dem letzten Restart `18/20` Code-Commits. Kein
Push. Restart nach 2 weiteren Commits. Naechster Push bleibt erst bei 100
Commits.

### Proactive-Due-At-Testvertrag

- 2026-07-17: Drei Proactive-Tests erwarteten alte UTC-Defaultwerte oder
  faellige Items trotz `due_at`-Fail-Closed-Validierung. Lokale Defaultzeit
  traegt korrekt den konfigurierten Europe/Berlin-Offset.
- Erwartungen auf `+02:00` und zukuenftige Queue-Items angepasst. Planner plant;
  derselbe Zyklus versendet noch nicht faellige Items nicht.
- Tests: Proactive-Zeitfokus `3 passed`; Ruff und `git diff --check` gruen.
  Kein Provider/API-Aufruf.
- Test-Commit: `5d9b5e6d test: align proactive due time expectations`.

**Aktueller Laufstand:** Seit dem letzten Restart `19/20` Code-Commits. Kein
Push. Restart nach 1 weiterem Commit. Naechster Push bleibt erst bei 100
Commits.

### Status-Metadaten-faengt-ValueError

- 2026-07-17: `/status` fing beim Lesen von Account-Metadaten nur
  `AccountStoreError` und `OSError`. Malformed/decryptetes, aber syntaktisch
  ungueltiges JSON konnte `ValueError` bis in den Applet-Status propagieren.
- Metadata- und Profilprobe faengt jetzt auch `ValueError` und meldet
  `account_memory_metadata=... status=broken`; Status bleibt strukturiert.
- Regression plus Status-/Notification-Suite: `222 passed`; Ruff,
  `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `26e52310 fix: report malformed metadata in status health`.
- Nach `20/20` Commit wurde `teebotus.service` neu gestartet: `active`,
  `SubState=running`, `ExecMainStatus=0`.

**Aktueller Laufstand:** Seit dem letzten Restart `0/20` Code-Commits. Kein
Push. Restart nach 20 weiteren Commits. Naechster Push bleibt erst bei 100
Commits.

### Bot-Test-isoliert-Logging-Umgebung

- 2026-07-17: Ein unittest-Test rief privaten `_main_impl()` direkt auf,
  setzte dabei `TEEBOTUS_LOG_LEVEL=debug_all` und liess die Prozessumgebung fuer
  folgende Engine-Tests veraendert.
- `patch.dict(os.environ, ...)` begrenzt den absichtlichen Test-Override auf
  den Testkontext; Produktionswrapper bleibt unveraendert.
- Tests: Bot-/Engine-Fokus `191 passed`; Ruff und `git diff --check` gruen.
  Kein Provider/API-Aufruf.
- Test-Commit: `9025232f test: isolate bot logging environment`.

**Aktueller Laufstand:** Seit dem letzten Restart `1/20` Code-Commits. Kein
Push. Restart nach 19 weiteren Commits. Naechster Push bleibt erst bei 100
Commits.

### Account-Lock-erhaelt-Body-Fehler

- 2026-07-17: `_safe_account_lock_handle()` fing `OSError` auch ueber den
  `yield` hinweg. Ein absichtlicher Fehler aus dem geschuetzten Schreib-
  operation wurde dadurch als `could not open ... lock` maskiert.
- Open-/fdopen-/fstat-Fehler werden jetzt nur an ihren jeweiligen
  Systemaufrufen normalisiert; Exceptions aus dem Lock-Body propagieren
  unverfaelscht.
- Tests: AccountStore `316 passed` inklusive Weather-Schreibfehler; Ruff,
  `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `55602422 fix: preserve account lock body errors`.

**Aktueller Laufstand:** Seit dem letzten Restart `2/20` Code-Commits. Kein
Push. Restart nach 18 weiteren Commits. Naechster Push bleibt erst bei 100
Commits.

### Pending-Scope-bleibt-legacy-kompatibel

- 2026-07-17: Direkte Legacy-Event-Objekte ohne `adapter_slot` brachen beim
  neuen Pending-Flow-Scope mit `AttributeError`.
- Scope nutzt fuer alte Event-Objekte jetzt Slot `1` als bisherigen Default;
  echte `IncomingEvent`-Objekte behalten ihren konkreten Adapter-Slot.
- Tests: Signal-/Engine-Fokus `191 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `6eb78bd9 fix: keep pending flow scope legacy compatible`.

**Aktueller Laufstand:** Seit dem letzten Restart `3/20` Code-Commits. Kein
Push. Restart nach 17 weiteren Commits. Naechster Push bleibt erst bei 100
Commits.

### Loudness-Recheck-testet-lock-internen-Claim

- 2026-07-17: Dispatch nutzt nach Deadlock-Fix den lock-internen Claim-Helper;
  ein Regressionstest patchte noch den alten oeffentlichen Claim und pruefte
  dadurch keinen Race-Pfad.
- Test patcht jetzt den tatsaechlichen Helper, bestaetigt waehrend Claim
  `ja, laut` und prueft, dass der bereits beanspruchte Prompt storniert statt
  versendet wird.
- Tests: Notification-Loudness `166 passed`; Ruff und `git diff --check`
  gruen. Kein Provider/API-Aufruf.
- Test-Commit: `ba03ebce test: exercise loudness recheck after worker claim`.

**Aktueller Laufstand:** Seit dem letzten Restart `4/20` Code-Commits. Kein
Push. Restart nach 16 weiteren Commits. Naechster Push bleibt erst bei 100
Commits.

### Gemini-Fallback-Keyring-Prioritaet

- 2026-07-17: Der Gemini-Keyring kombiniert absichtlich instance-spezifische
  Buckets mit globalen Buckets gleicher Accountposition als Fallback. Ein
  Router-Test erwartete noch, dass globale Account-2-Schluessel komplett
  verschwinden.
- Erwartung auf reale Rotation `demo-a1, b1, demo-a2` angepasst. Globale
  Account-1-Schluessel werden bei vorhandener Instanzposition nicht doppelt
  eingefuegt; globale spaetere Positionen bleiben nutzbar.
- Tests: LLM-Router-/Gemini-Keyring-Fokus `89 passed`; Ruff und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Test-Commit: `6eb8332e test: align fallback keyring precedence`.

**Aktueller Laufstand:** Seit dem letzten Restart `6/20` Code-Commits. Kein
Push. Restart nach 14 weiteren Commits. Naechster Push bleibt erst bei 100
Commits.

### Admin-Status-Fehler-fail-closed

- 2026-07-17: Admin-Status-Routen liessen `ValueError` aus malformed/decrypteten
  Route-Dokumenten bis in `/status` und die Benachrichtigung laufen. Dadurch
  konnte Diagnose abbrechen statt den betroffenen Account als Warnung zu
  markieren.
- Route-Aufloesung faengt jetzt `ValueError` neben `AccountStoreError` und
  `OSError` ab. Statuszeilen bleiben strukturiert; einzelne kaputte Routen
  blockieren weder andere Admins noch den gesamten Runtime-Status.
- Unlesbares Admin-Opt-out wird jetzt fail-closed behandelt. Ein Speicher-
  oder Secret-Fehler darf keinen abgemeldeten Account versehentlich wieder fuer
  Status-/Benchmark-Versand aktivieren.
- Tests: `tests/test_runtime_admin_accounts.py` `32 passed`; Ruff,
  `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `924ec11f fix: fail closed on admin status state errors`.

### Proactive-Iteration-ueber-Store-IDs

- 2026-07-17: Der Proactive-Scheduler enumerierte Accounts nur ueber lokale
  Verzeichnisse. SQL-/Index-only Accounts aus `AccountStore.list_account_ids()`
  wurden dadurch weder geplant noch dispatcht.
- Scheduler nutzt jetzt die Union aus Verzeichnis- und Store-IDs; ungueltige
  IDs werden weiterhin verworfen, Backend-Lesefehler bleiben gegen den lokalen
  Scan isoliert.
- Tests: Proactive-/Admin-Fokus `81 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `6f7e2e72 fix: include store-only proactive accounts`.

### Status-Auth-Export-faengt-Route-ValueError

- 2026-07-17: Der Status-Auth-Export fing beim Route-Lookup nur
  `AccountStoreError` und `OSError`. Malformed/decryptete Routendokumente
  konnten als `ValueError` den gesamten Export abbrechen.
- Export meldet den Account jetzt strukturiert mit `route_error`, ohne andere
  Accounts zu verlieren.
- Tests: fokussierter Status-Auth-Report `2 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `881e0a44 fix: keep status auth reports structured`.

### Proactive-Review-nutzt-Store-IDs

- 2026-07-17: Die Human-Review-Liste scannte ebenfalls nur lokale
  Account-Verzeichnisse und verlor `review_pending`-Items von SQL-/Index-only
  Accounts.
- Review-Enumeration nutzt jetzt dieselbe Union aus Directory- und Store-IDs
  wie der Proactive-Scheduler.
- Tests: Proactive-Review-/CLI-Fokus `56 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e14bfe19 fix: include store-only review accounts`.

**Aktueller Laufstand:** Seit dem letzten Restart `4/20` Code-Commits. Kein
Push. Restart nach 16 weiteren Commits. Naechster Push bleibt erst bei 100
Commits.

### Memory-Health-faengt-ValueError

- 2026-07-17: Die per-Account-Pruefung las Profile und strukturierte Indizes
  ohne `ValueError`-Guard. Malformed JSON-/Decrypt-Daten konnten dadurch den
  gesamten `/status`-Healthblock abbrechen.
- Profile- und Indexfehler werden jetzt als `status=broken` mit Recovery-Hinweis
  ausgegeben; die Pruefung laeuft fuer weitere Accounts weiter.
- Tests: Version-/Admin-Status-Fokus `256 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `365f91e0 fix: keep memory health status diagnostic on value errors`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`7/20` Commits. Kein Push. Restart nach 13 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Worker meldet fehlgeschlagene Sender-Persistenz

- 2026-07-17: Wenn sich die Route erst nach dem Claim aenderte, behandelten
  drei Terminalpfade (`missing_sender`, `invalid_sender`, `invalid_file`) den
  Rueckgabewert des `dispatching -> failed`-Updates nicht. Ein Schreibfehler
  konnte dadurch als eigentliche Sender-/Dateifehlerursache erscheinen.
- Gemeinsamer Status-Guard prueft jetzt Vor- und Post-Claim-Rueckgabewert und
  Ausnahme. Bei fehlender Persistenz wird `status_update_failed` reportiert;
  Versand bleibt unterdrueckt.
- Test: `tests/test_proactive_agent.py` `180 passed`; gezielter
  Queue-/Route-Refresh-/Sender-Persistenztest gruen; Ruff und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `bd756088 fix: surface proactive status persistence failures`.

### Proactive-Worker meldet fehlgeschlagenen Policy-Recheck

- 2026-07-17: Der Policy-Recheck vor dem Claim konnte nach einem ersten Allow
  noch ablehnen. Sein `queued -> skipped`-Update ignorierte Schreibfehler;
  dadurch wurde weiterhin ein scheinbar sauberer Skip reportiert.
- Recheck nutzt jetzt gemeinsamen Status-Guard. Fehlende Persistenz erzeugt
  `failed/status_update_failed`; Item bleibt `queued`, Versand findet nicht
  statt.
- Test: `tests/test_proactive_agent.py` `181 passed`; gezielter Recheck-
  Persistenztest gruen; Ruff und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `bf6558a9 fix: report policy recheck persistence failures`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`13/20` Commits. Kein Push. Restart nach 7 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`11/20` Commits. Kein Push. Restart nach 9 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Worker meldet fehlgeschlagene Sender-Persistenz

- 2026-07-17: Wenn sich die Route erst nach dem Claim aenderte, behandelten
  drei Terminalpfade (`missing_sender`, `invalid_sender`, `invalid_file`) den
  Rueckgabewert des `dispatching -> failed`-Updates nicht. Ein Schreibfehler
  konnte dadurch als eigentliche Sender-/Dateifehlerursache erscheinen.
- Gemeinsamer Post-Claim-Guard prueft jetzt Rueckgabewert und Ausnahme. Bei
  fehlender Persistenz wird `status_update_failed` reportiert; Item bleibt
  sichtbar und Versand bleibt unterdrueckt.
- Test: `tests/test_proactive_agent.py` `179 passed`; gezielter
  Route-Refresh-/Sender-Persistenztest gruen; Ruff und `git diff --check`
  gruen. Kein Provider/API-Aufruf.
- Code-Commit: `934bcc7b fix: report claimed sender persistence failures`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`9/20` Commits. Kein Push. Restart nach 11 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Memory-Health-Datenbankfehler

- 2026-07-17: Die Ermittlung von Account-IDs aus dem Memory-Backend konnte bei
  malformed Konfigurationen `ValueError` bis in den `/status`-Collector werfen.
- Der Datenbankfehler wird jetzt als `database_account_discovery_failed`
  ausgegeben; Verzeichnis-Accounts werden trotzdem weiter geprueft.
- Test: fokussierter Memory-Health-Fokus `21 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `64cf5409 fix: keep database health diagnostics on value errors`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`9/20` Commits. Kein Push. Restart nach 11 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-und-Fallback-Status-faengt-ValueError

- 2026-07-17: Proactive-State und Memory-Fallback-Backend konnten bei
  malformed Daten/Konfigurationen `ValueError` bis aus dem `/status`-Collector
  laufen lassen.
- Beide Stellen melden jetzt den bestehenden strukturierten Lesefehler und
  lassen den restlichen Status weiterlaufen.
- Tests: fokussierter Proactive-/Fallback-Status `5 passed`; Ruff,
  `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `7e2153b2 fix: keep proactive status diagnostic on value errors`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`11/20` Commits. Kein Push. Restart nach 9 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Memory-Payload-Status-faengt-ValueError

- 2026-07-17: Payload-Groesse und Verschluesselungsanzeige lasen das
  Memory-Backend ohne `ValueError`-Guard. Malformed Backend-Konfigurationen
  konnten dadurch den normalen Statusaufbau abbrechen.
- Beide Ausleser melden jetzt `nicht verfuegbar` und lassen den restlichen
  `/status`-Reply intakt.
- Tests: Memory-Status-Fokus `9 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `dedaf06e fix: keep memory size status diagnostic on value errors`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`13/20` Commits. Kein Push. Restart nach 7 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Status-Discovery-validiert-DB-Account-IDs

- 2026-07-17: Die SQL-Discovery uebernahm beliebige nichtleere
  `account_id`-Werte. Malformed Werte konnten in Profilpfade und Statuszeilen
  gelangen; Proactive-Discovery filterte bereits korrekt.
- Status-Discovery akzeptiert jetzt nur lowercase 128-Zeichen-SHA-512-IDs.
  Ungueltige DB-Werte werden verworfen, ohne andere Accounts zu verlieren.
- Test: Memory-Health-/DB-Discovery-Fokus `22 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `87638b52 fix: validate database memory account ids`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`15/20` Commits. Kein Push. Restart nach 5 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Qdrant-Redirect-akzeptiert-lokale-Aliase

- 2026-07-17: Der Applet-Qdrant-Check verglich Redirect-Hosts bytegenau.
  Lokale Redirects zwischen `127.0.0.1`, `localhost` und `::1` wurden dadurch
  als fremde Origin verworfen.
- Nur diese drei lokalen Alias-Hosts gelten jetzt bei gleichem Schema und Port
  als gleiche lokale Origin; externe Hosts bleiben blockiert.
- Biene pruefte zusaetzlich Timeout-/Qdrant-Unit-Klassifikation. Diese Logik
  bleibt unveraendert, weil Timeout und Supervisorfehler echte Diagnosefehler
  sind.
- Tests: Qdrant-Applet-Fokus `19 passed`; Produktions-Ruff, `compileall` und
  `git diff --check` gruen. Testfile hat zwei alte `F541`-Befunde, ausserhalb
  des Patches; verifiziert mit `--ignore F541`. Kein Provider/API-Aufruf.
- Code-Commit: `ab0328fd fix: accept local qdrant redirect aliases`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`17/20` Commits. Kein Push. Restart nach 3 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Account-Metadaten-Shape-validiert

- 2026-07-17: Der Metadata-Healthcheck pruefte nur JSON-Lesbarkeit. Listen
  oder ein `Account_Index.accounts`-Array konnten syntaktisch lesbar, aber
  strukturell unbrauchbar bleiben.
- Account-Metadaten muessen jetzt Objekte sein; `Account_Index.accounts` muss
  zusaetzlich ein Objekt/Mapping sein. Fehler erscheinen als strukturierte
  `account_memory_metadata=... status=broken`-Zeile.
- Tests: fokussierter Metadata-Health-Fokus `3 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commits: `ac3f9b85 fix: validate account metadata document shapes`,
  `1888d082 fix: validate account index container shape`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`20/20` Commits. Kein Push. Restart jetzt. Naechster Zyklus startet danach
bei `0/20`; Naechster Push bleibt erst bei 100 Commits.

### Proactive-Dispatch reportiert korrupte Claim-Zustaende

- 2026-07-17: Ein wegen kaputter `status_history` oder
  `dispatch_attempts` abgelehnter Worker-Claim erschien als harmloses
  `skipped:worker_claim_failed`. Scheduler-/Cycle-Health konnte dadurch gruen
  bleiben, obwohl Item blockiert war.
- Bekannte Korruptionsgruende werden jetzt als `failed` im Dispatch-Report
  ausgegeben. Item bleibt unveraendert und der Sender wird nicht aufgerufen;
  Reparatur/Quarantaene kann den Rohzustand weiterhin auswerten.
- Test: `tests/test_proactive_agent.py` `171 passed`; Claim-Korruptionsfokus
  `6 passed`; Ruff, `compileall` und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `0c777967 fix: surface corrupt proactive claim state`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`2/20` Commits. Kein Push. Restart nach 18 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Worker meldet fehlgeschlagene Stale-Route-Aufraeumung

- 2026-07-17: Nach einem erfolgreichen Worker-Claim kann die private Route
  zwischenzeitlich veralten. Wenn das anschliessende Persistieren von
  `cancelled/stale_route_after_claim` fehlschlug, wurde trotzdem `skipped`/
  `stale_route` gemeldet; das Item blieb `dispatching` und konnte nach Lease-
  Recovery erneut aufgegriffen werden.
- Der Cancel-Schritt prueft jetzt Rueckgabewert und Ausnahme. Bei fehlender
  Persistenz wird `failed/status_update_failed` reportiert; Versand bleibt
  unterdrueckt.
- Test: `tests/test_proactive_agent.py` `178 passed`; gezielter Race-/Persistenz-
  Test gruen; Ruff und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `4048f798 fix: report stale route cancellation failures`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`5/20` Commits. Kein Push. Restart nach 15 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Notification-Loudness-Outbox bewahrt kaputte Statushistorien

- 2026-07-17: Der Loudness-Abbruch mutierte `queued`-Outbox-Items direkt zu
  `cancelled` und ersetzte eine kaputte `status_history` durch eine leere
  Liste. Damit umging dieser Sonderpfad die zentrale Outbox-Integritaetspruefung.
- Der Pfad verwendet jetzt dieselbe zentrale History-Validierung wie der
  Proactive-Dispatcher. Bei kaputter History bleibt das Item unveraendert;
  gueltige Items werden weiter sauber storniert. Lazy-Import vermeidet den
  bestehenden Importzyklus zwischen Loudness und Proactive-Agent.
- Test: `tests/test_notification_loudness.py` `167 passed`; fokussierter
  Regressionstest fuer kaputte History gruen; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `60cbfb7c fix: preserve loudness outbox history`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`2/20` Commits. Kein Push. Restart nach 18 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Runtime-Status-Outbox bewahrt kaputte Statushistorien

- 2026-07-17: Der Runtime-/Benchmark-Statusversand setzte bei einer nicht
  listenfoermigen `status_history` eine neue leere Liste. Vorhandene
  Auditdaten gingen dadurch beim Versandstatus-Update verloren.
- Status wird weiterhin auf `sent`, `failed` oder `skipped` gesetzt. Eine
  kaputte History bleibt unveraendert; nur fehlende oder listenfoermige
  Histories erhalten den neuen Eintrag.
- Test: `tests/test_runtime_admin_accounts.py` `33 passed`; Regressionstest,
  Ruff, `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `7f6d2bd9 fix: preserve runtime status history`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`4/20` Commits. Kein Push. Restart nach 16 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Codex-History bewahrt kaputte Statushistorien

- 2026-07-17: Codex-Status-Update und Worker-Claim ersetzten eine nicht
  listenfoermige `status_history` durch `[]`. Damit konnten Auditdaten von
  Summarys beim normalen Versand verloren gehen.
- Beide Mutationspfade setzen Status und Versandmetadaten weiterhin, lassen
  eine kaputte History aber unveraendert. Fehlende bzw. listenfoermige
  Histories erhalten den neuen Status-Eintrag.
- Tests: `tests/test_codex_history.py` `187 passed`; zwei Regressionstests,
  Ruff mit bestehendem `E402`-Importbefund ausgenommen, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e036e9e5 fix: preserve codex history audit`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`6/20` Commits. Kein Push. Restart nach 14 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Claim lehnt kaputte Versuchszahler ab

- 2026-07-17: Der zentrale `queued -> dispatching`-Pfad behandelte einen
  nicht numerischen `dispatch_attempts`-Wert wie `0` und schrieb still `1`.
  Damit konnte ein kaputter Retry-Zustand unbemerkt werden.
- Worker-Claims mit ungueltigem Versuchszahler brechen jetzt vor jeder
  Mutation ab. Der Outbox-Status und Rohwert bleiben fuer Diagnose und
  Reparatur erhalten. Negative numerische Werte bleiben wie bisher auf `0`
  geklemmt.
- Test: `tests/test_proactive_agent.py` `167 passed`; Retry-Fokus `3 passed`;
  Ruff, `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `917e0d3b fix: fail closed on corrupt proactive attempts`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`8/20` Commits. Kein Push. Restart nach 12 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Codex-History lehnt kaputte Delivery-Metadaten ab

- 2026-07-17: Codex-Statusupdate und Worker-Claim ersetzten einen vorhandenen
  nicht-dict `delivery`-Container durch `{}`. Attempt-/Receipt-Rohdaten konnten
  dadurch beim Versand verschwinden.
- Items ohne `delivery` bleiben kompatibel und erhalten den Standardcontainer.
  Vorhandene kaputte Container blockieren Statusupdate und Claim fail-closed;
  Originaldaten bleiben unveraendert fuer Diagnose/Repair.
- Test: `tests/test_codex_history.py` `188 passed`; Delivery-/History-Fokus
  `3 passed`; Ruff mit bestehendem `E402`-Importbefund ausgenommen,
  `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `64a3edcb fix: reject corrupt codex delivery metadata`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`10/20` Commits. Kein Push. Restart nach 10 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Sendefehler lehnt kaputte Snapshot-Versuchszahler ab

- 2026-07-17: Der Sender-Exceptionpfad berechnete Retry-Anzahl erneut mit
  einer Default-Normalisierung. Ein zwischen Claim und Fehler veraenderter
  Snapshot mit kaputtem `dispatch_attempts` konnte dadurch Retry ausloesen.
- Sendefehler mit kaputtem Snapshot-Zaehler markieren das Item jetzt direkt
  als `failed`; kein Retry. Der zentrale Claim bleibt weiterhin fail-closed.
- Tests: `tests/test_proactive_agent.py` `168 passed`; Attempt-Fokus `5 passed`;
  Ruff, `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `34947856 fix: fail closed on send attempt corruption`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`12/20` Commits. Kein Push. Restart nach 8 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Accountloop reportiert Fabrikfehler strukturiert

- 2026-07-17: Der Account-Loop fing nur bekannte Store-/Value-Fehler. Ein
  `RuntimeError` aus Sender- oder Tracker-Fabrik konnte den ganzen Scheduler
  ohne Report abbrechen.
- Der aeussere Account-Guard faengt jetzt sonstige `Exception`-Fehler ab und
  schreibt sie als `account.error`. Andere Accounts und der Top-Level-Report
  bleiben auswertbar; `ok` wird korrekt `false`.
- Test: `tests/test_proactive_cli.py` `60 passed`; Fabrikfehler-Fokus `3
  passed`; Ruff, `compileall` und `git diff --check` gruen. Kein Provider/API-
  Aufruf.
- Code-Commit: `7839244a fix: report proactive factory failures`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`14/20` Commits. Kein Push. Restart nach 6 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Sendefehler reportieren fehlgeschlagene Statuspersistenz

- 2026-07-17: Nach einem Senderfehler wurden Retry-/Fail-Statusupdates nicht
  ausgewertet. Bei fehlgeschlagener Persistenz meldete der Dispatcher trotzdem
  `send_error`, obwohl das Item real weiter `dispatching` blieb.
- Beide Fehlerzweige pruefen jetzt das Ergebnis und fangen Persistenzfehler
  strukturiert ab. Ergebnisgrund ist dann `status_update_failed`; Lease-Recovery
  kann den realen Outbox-Zustand spaeter uebernehmen.
- Test: `tests/test_proactive_agent.py` `169 passed`; Persistenz-Fokus `3
  passed`; Ruff, `compileall` und `git diff --check` gruen. Kein Provider/API-
  Aufruf.
- Code-Commit: `eddecdef fix: report proactive status persistence failures`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`16/20` Commits. Kein Push. Restart nach 4 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Instanz- und Storefehler bleiben reportierbar

- 2026-07-17: `store_factory` und `_account_ids` fingen nur bekannte
  Store-/Value-Fehler. Unerwartete Backend-Fehler konnten den gesamten
  Proactive-Scheduler ohne strukturierten Report beenden.
- Instanz- und Account-Discovery faengt jetzt sonstige `Exception` ab und
  setzt `instance.error`. Andere Instanzen bleiben auswertbar; Top-Level
  `ok` wird korrekt `false`.
- Test: `tests/test_proactive_cli.py` `61 passed`; Factory-/Store-Fokus `4
  passed`; Ruff, `compileall` und `git diff --check` gruen. Kein Provider/API-
  Aufruf.
- Code-Commit: `2f149469 fix: report proactive store failures`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`18/20` Commits. Kein Push. Restart nach 2 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Review reportiert unerwartete Aktionsfehler

- 2026-07-17: `review_proactive_item` fing bei `approve`/`reject` nur
  bekannte Store-/Value-Fehler. Unerwartete Policy-/Backend-Fehler konnten
  den CLI-/JSON-Aufruf ohne Zielmetadaten abbrechen.
- Aktionsfehler werden jetzt als `review_store_error:<Typ>: <Text>` mit
  Instanz, Account und Item strukturiert ausgegeben. Erfolgs- und
  Ablehnungslogik bleibt unveraendert.
- Test: `tests/test_proactive_review.py` `14 passed`; Runtime-Fehler-Fokus `5
  passed`; Ruff, `compileall` und `git diff --check` gruen. Kein Provider/API-
  Aufruf.
- Code-Commit: `12fde513 fix: report proactive review failures`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`20/20` Commits. Kein Push. Restart jetzt. Naechster Zyklus startet danach
bei `0/20`; naechster Push bleibt erst bei 100 Commits.

### Proactive-Consentzustand fail-closed bei korruptem enabled-State

- 2026-07-17: Ein inkonsistenter Agent-State mit `enabled=true`, aber leerem
  `consent.categories`, wurde vom Healthcheck erkannt, konnte jedoch noch
  Provider-Aufrufe sowie interne Memory-, Cancel- und Snooze-Mutationen
  ausloesen.
- Alle Proactive-Planner-Einstiegspunkte stoppen jetzt bei fehlendem Consent
  mit `proactive_no_consent`; direkte LLM-Entscheidungen schreiben oder
  veraendern dann ebenfalls nichts. Normale deaktivierte und pausierte Zustaende
  behalten ihre bisherigen Gruende.
- Test: `tests/test_proactive_agent.py` + `tests/test_proactive_cli.py`
  `221 passed`; Consent-Fokus `5 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `d88546da fix: fail closed on missing proactive consent`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`10/20` Commits. Kein Push. Restart nach 10 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Stale-Recovery respektiert Retry-Limit

- 2026-07-17: Stale `dispatching`-Claims wurden nach Worker-Crash immer wieder
  auf `queued` gesetzt. Das umging `PROACTIVE_DISPATCH_MAX_ATTEMPTS` und konnte
  bei wiederholten Crashes unbegrenzt erneute Sendungen ausloesen.
- Recovery setzt Claims am Versuchslimit jetzt fail-closed auf `failed`,
  entfernt den Lease und schreibt die Begrenzung in `status_history`. Der
  reine Recovery-Fall persistiert auch dann, wenn kein Claim requeued wird.
- Test: `tests/test_proactive_agent.py` + `tests/test_proactive_cli.py`
  `222 passed`; Crash-Recovery-Fokus `4 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `b10182ab fix: cap stale proactive dispatch recovery`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`12/20` Commits. Kein Push. Restart nach 8 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Stale-Recovery lehnt kaputte Versuchszahler ab

- 2026-07-17: Ein nicht numerischer `dispatch_attempts`-Altwert wurde in der
  Crash-Recovery wie `0` behandelt. Health meldete den Fehler, Recovery konnte
  das Retry-Limit aber trotzdem umgehen.
- Stale Claims mit kaputtem Versuchszahler werden jetzt fail-closed auf
  `failed` gesetzt, der Rohwert bleibt fuer Diagnose erhalten. Fehlende oder
  negative Werte bleiben kompatibel normalisiert; negative Werte koennen das
  Limit nicht mehr umgehen.
- Test: `tests/test_proactive_agent.py` + `tests/test_proactive_cli.py`
  `223 passed`; Recovery-Fokus `4 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `bf04eb89 fix: reject corrupt proactive attempt counters`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`14/20` Commits. Kein Push. Restart nach 6 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Outbox bewahrt kaputte Statushistorien

- 2026-07-17: Mehrere Outbox-Mutationen ersetzten nicht-listenfoermige oder
  inhaltlich ungueltige `status_history` durch `[]`. Dadurch gingen Auditdaten
  verloren, obwohl der Healthcheck den Datensatz bereits als defekt meldete.
- Statuswechsel, Recovery, Ablauf-, Invalidierungs-, Review- und Snooze-Pfade
  pruefen die Historie jetzt vor dem Write. Bei Fehler bleibt der Datensatz
  unveraendert und der bestehende Befund fuer Diagnose/Repair erhalten.
  Fehlende Historie bleibt als reparierbarer Altbestand zulaessig.
- Test: `tests/test_proactive_agent.py` + `tests/test_proactive_cli.py`
  `224 passed`; Statushistorien-/Recovery-Fokus `5 passed`; Ruff,
  `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `2408f28a fix: preserve corrupt proactive status history`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`16/20` Commits. Kein Push. Restart nach 4 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Instanz-Discovery lehnt Symlinks ab

- 2026-07-17: Der Proactive-Scheduler akzeptierte symlinkartige Instanzordner
  und konnte dadurch bei einem sicheren Einzelnamen ausserhalb des
  Instances-Baums lesen oder schreiben. Admin-Discovery hatte diesen Schutz
  bereits.
- Der Instances-Root darf kein Symlink sein; automatische Discovery ignoriert
  Symlink-Instanzen. Explizit selektierte Symlinks werden als
  `selected_instance_symlink` gemeldet und erreichen nie die Store-Factory.
- Test: `tests/test_proactive_agent.py` + `tests/test_proactive_cli.py`
  `225 passed`; Discovery-Fokus `4 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `93c508f3 fix: reject symlinked proactive instances`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`18/20` Commits. Kein Push. Restart nach 2 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Review-Discovery lehnt Symlinks ab

- 2026-07-17: Human-Review-`list` sowie `approve`/`reject` folgten
  symlinkartigen Instanzen, obwohl der normale Admin-Discoverypfad solche
  Ordner ignoriert.
- Review-Discovery ignoriert Symlink-Instanzen, selektierte Links melden
  `selected_instance_symlink`, direkte Aktionen `instance_symlink`; ein
  symlinkartiger Instances-Root wird ebenfalls abgelehnt. Store-Factory wird
  vor diesen Fehlern nie aufgerufen.
- Test: `tests/test_proactive_agent.py` + `tests/test_proactive_cli.py` +
  `tests/test_proactive_review.py` `238 passed`; Review-Symlink-Fokus `3 passed`;
  Ruff, `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `57459b84 fix: reject symlinked proactive review instances`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`20/20` Commits. Kein Push. Restart jetzt. Naechster Zyklus startet danach
bei `0/20`; Naechster Push bleibt erst bei 100 Commits.

### Runtime-Status zeigt Legacy-OpenAI-Modell

- 2026-07-17: Legacy-Konfiguration aus `Bot_Verhalten.md` verwendete im
  Runtime-Status den Platzhalter `<Bot_Verhalten/OpenAI>`, obwohl die Runtime-
  Factory bereits `openai_model` als effektives Modell nutzte.
- Direkte Legacy-OpenAI-Routen zeigen jetzt das konfigurierte
  `instructions.openai_model`; Profile- und Purpose-Routen bleiben unveraendert.
- Regressionstest: `tests/test_entrypoint_compatibility.py` fokussiert `8 passed`;
  Ruff, `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e9c6ebce fix: show legacy OpenAI model in runtime status`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`2/20` Commits. Kein Push. Restart nach 18 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Route nach Worker-Claim aktualisiert

- 2026-07-17: Alte Outbox-Items ohne gespeicherte `route` liessen beim Claim
  eine frische Identitaetsroute zu. Der Dispatcher verwendete danach trotzdem
  die vor dem Claim gewaehlte Route und stornierte oder adressierte falsch.
- Nach erfolgreichem Claim werden Route, Kanal, Chat-ID, Sender und Action aus
  der tatsaechlichen Claim-Entscheidung aktualisiert. Eine explizit stale
  gewordene Route bleibt weiterhin geschuetzt und wird nach Claim storniert.
- Tests: `tests/test_proactive_agent.py` `145 passed`; fokussierter Race-Test
  und bestehende Stale-Route-Tests gruen. Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `b3389f22 fix: refresh proactive route after claim`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`4/20` Commits. Kein Push. Restart nach 16 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Risikofenster fail-closed bei kaputten Zeitgrenzen

- 2026-07-17: `_risk_memory_is_active` behandelte nicht parsebare, nichtleere
  `valid_from`-/`valid_to`-Werte wie fehlende Grenzen. Bei altem `updated_at`
  konnte ein Risiko-Memory dadurch aus dem Schutzfenster fallen.
- Kaputte Zeitgrenzen gelten jetzt als aktiv. Der Proactive-Risikopfad bleibt
  damit sicher blockierend, bis Daten repariert oder bewusst entfernt wurden.
- Test: `tests/test_proactive_agent.py` `146 passed`; fokussierter Risiketest
  `5 passed`; Ruff, `compileall` und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `862713b3 fix: fail closed on malformed proactive risk windows`.

### Proactive-Risikofenster prueft alle Grenzen vor Zeitvergleich

- 2026-07-17: Ein zukuenftiges `valid_from` konnte einen gleichzeitig kaputten
  `valid_to`-Wert verdecken; der Pfad lieferte dann faelschlich `False` statt
  fail-closed aktiv.
- Beide nichtleeren Grenzen werden jetzt zuerst validiert, erst danach wird
  `valid_from` gegen den aktuellen Zeitpunkt verglichen.
- Test: `tests/test_proactive_agent.py` `146 passed`; fokussierter Risiketest
  `5 passed`; Ruff, `compileall` und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `d33dea83 fix: validate all proactive risk bounds before comparison`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`8/20` Commits. Kein Push. Restart nach 12 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Dispatch-Lease meldet kaputten Claim-Zeitstempel

- 2026-07-17: Bei `dispatching` konnte ein ungueltiges `dispatching_at` durch
  ein gueltiges `updated_at` verdeckt werden. Health meldete den Lease dann
  scheinbar gesund.
- Ein nichtleeres, nicht parsebares `dispatching_at` wird jetzt explizit als
  `invalid claim timestamp` gemeldet. Fehlende Legacy-Felder nutzen weiterhin
  den bisherigen Fallback.
- Test: `tests/test_proactive_agent.py` `147 passed`; Health-Fokus `21 passed`;
  Ruff, `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `da07bfd1 fix: report malformed proactive claim timestamps`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`10/20` Commits. Kein Push. Restart nach 10 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Dispatch-Lease meldet zukuenftigen Claim-Zeitstempel

- 2026-07-17: Ein `dispatching_at` in der Zukunft wurde als frischer Lease
  behandelt und blieb ohne Health-Befund potenziell haengen.
- Health meldet zukuenftige Claim-Zeitstempel jetzt explizit. Recovery bleibt
  konservativ und reclaimt sie nicht automatisch, um keine laufende Sendung
  zu duplizieren.
- Test: `tests/test_proactive_agent.py` `148 passed`; Health-Fokus `22 passed`;
  Ruff, `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `67b4cb06 fix: report future proactive claim timestamps`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`12/20` Commits. Kein Push. Restart nach 8 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Risikofenster lehnt invertierte Grenzen ab

- 2026-07-17: Ein `valid_to` vor `valid_from` wurde als noch nicht aktives
  Fenster behandelt. Bei altem `updated_at` konnte der Schutz dadurch fehlen.
- Widerspruechliche, aber parsebare Zeitgrenzen gelten jetzt ebenfalls als
  aktiv und blockieren den Proactive-Risikopfad bis zur Reparatur.
- Test: `tests/test_proactive_agent.py` `148 passed`; fokussierter Risiketest
  `5 passed`; Ruff, `compileall` und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `6b09e8aa fix: reject inverted proactive risk windows`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`14/20` Commits. Kein Push. Restart nach 6 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Human-Review validiert Outbox-Payload vor Approval

- 2026-07-17: `approve_proactive_review_item` konnte beschaedigte
  `review_pending`-Zeilen direkt zu `queued` machen. Pflichtfelder wurden erst
  beim Dispatch erkannt.
- Approval prueft jetzt `intent`, `message_text`, `due_at`, `recurrence` und
  `file` vor jeder Mutation. Ungueltige Items bleiben `review_pending`.
- Test: `tests/test_proactive_agent.py` `149 passed`; Human-Review-Fokus
  `5 passed`; Ruff, `compileall` und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `4e50f568 fix: validate approved proactive review payloads`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`16/20` Commits. Kein Push. Restart nach 4 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Tool-Agent meldet abgeschnittene Tool-Calls

- 2026-07-17: `apply_proactive_agent_tool_calls` verwarf Tool-Calls oberhalb
  des Limits fuenf still. LLM-Plan-JSON meldete dieselbe Begrenzung bereits.
- Tool-Agent meldet jetzt `too_many_tool_calls_truncated` und schreibt einen
  Audit-Eintrag mit der urspruenglichen Anzahl; die ersten fuenf validierten
  Calls bleiben unveraendert verarbeitet.
- Test: `tests/test_proactive_agent.py` `150 passed`; Tool-Agent-Fokus
  `9 passed`; Ruff, `compileall` und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `cb1f8424 fix: audit truncated proactive tool calls`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`18/20` Commits. Kein Push. Restart nach 2 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Tool-Agent gibt Teilresultate des JSON-Fallbacks zurueck

- 2026-07-17: Bei JSON-Fallback ohne Tool-Calls wurde eine gueltige Aktion
  angewendet, aber bei einer weiteren ungueltigen Entscheidung nur
  `no_tool_calls` zurueckgegeben. Erzeugte IDs und Validatorfehler fehlten im
  Schedulerreport.
- Der Fallback gibt jetzt immer das echte `ProactiveLLMPlanningResult` zurueck,
  auch bei Teilfehlern. Mutationen und Fehler bleiben damit sichtbar und
  auditierbar.
- Test: `tests/test_proactive_agent.py` `151 passed`; Tool-Agent-Fokus
  `10 passed`; Ruff, `compileall` und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `08180520 fix: preserve partial proactive tool plan results`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`20/20` Commits. Kein Push. Restart jetzt. Naechster Push bleibt erst bei
100 Commits.

### Proactive-Tool-Agent verwirft malformed Responses-Calls nicht mehr

- 2026-07-17: Responses-API-Tool-Calls mit kaputten Pflichtargumenten wurden
  beim Extrahieren still verworfen. Der Runner meldete dadurch faelschlich
  `no_tool_calls`; Ursache und Call-ID fehlten im Audit.
- Erkennbar als Tool-Call bleibende, aber ungueltige Provider-Payloads werden
  jetzt bis zum bestehenden Validator durchgereicht. Der Runner liefert
  `tool_0_invalid_tool_call` und schreibt `tool_call_rejected`; echte
  Nicht-Tool-Ausgaben bleiben ignoriert.
- Test: `tests/test_proactive_agent.py` `152 passed`; Regression fokussiert
  `2 passed`; Ruff, `compileall` und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `2fe5791e fix: audit malformed proactive tool calls`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`1/20` Commits. Kein Push. Restart nach 19 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Tool-Agent lehnt kaputtes Argument-JSON ab

- 2026-07-17: `_tool_call_arguments` wandelte ungueltiges JSON in `{}` um.
  Besonders `proactive_noop` wurde dadurch als gueltiger No-op akzeptiert und
  Providerfehler blieben unsichtbar.
- JSON-Argumente muessen jetzt ein Objekt sein und parsebar bleiben. Fehlende
  Argumente behalten ihre bisherige Semantik; kaputte oder nicht-objektartige
  JSON-Payloads laufen als `tool_0_invalid_tool_call` durch Audit und Resultat.
- Test: `tests/test_proactive_agent.py` `153 passed`; Regression fokussiert
  `2 passed`; Ruff, `compileall` und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `29b5c578 fix: reject malformed proactive tool arguments`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`4/20` Commits. Kein Push. Restart nach 16 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Outbox validiert Zeitfelder vor Ablaufmarkierung

- 2026-07-17: `dispatch_due_proactive_outbox_items` liess alte Items zuerst
  ablaufen. Ein altes Item mit kaputtem `due_at` wurde dadurch `expired`, bevor
  `invalid_due_at` greifen konnte; fehlerhafte Daten verschwanden aus dem
  reparierbaren Queue-Pfad.
- Dispatch validiert `due_at`, `retry_at`, `recurrence` und `risk_gate` jetzt
  vor der Ablaufmarkierung. Der direkte Expirer ueberspringt kaputte, nichtleere
  `due_at`-Werte ebenfalls; Health-/Fail-Closed-Pfade behalten die Zeile sichtbar.
- Test: `tests/test_proactive_agent.py` `154 passed`; Ablauf-/Invalidierungs-
  Fokus `6 passed`; Ruff, `compileall` und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `c8b9f870 fix: validate proactive timestamps before expiry`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`6/20` Commits. Kein Push. Restart nach 14 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Tool-Agent faellt bei leerem Wrapper-Cache auf Responses-Output zurueck

- 2026-07-17: Ein Adapter mit `tool_calls=[]` konnte gleichzeitig echte
  Responses-API-Function-Calls in `output` liefern. Der Extraktor nahm die
  leere Liste als endgueltig und meldete faelschlich keinen Tool-Call.
- Leere Listen/Tupel aus Wrappern pruefen jetzt ebenfalls den strukturierten
  `output`-Pfad. Nichtleere explizite Tool-Call-Listen behalten Vorrang.
- Test: `tests/test_proactive_agent.py` `155 passed`; Responses-Fokus `3 passed`;
  Ruff, `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `edea927d fix: recover proactive tool calls from response output`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`8/20` Commits. Kein Push. Restart nach 12 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Tool-Agent akzeptiert nur Objekt-Argumente

- 2026-07-17: Neben kaputtem JSON wurden auch Listen und Zahlen bei
  `arguments` zu `{}` normalisiert. `proactive_noop` konnte dadurch erneut
  malformed Providerdaten als gueltigen No-op behandeln.
- Explizite Argumente muessen jetzt Mapping/Objekt, parsebares JSON-Objekt oder
  kompatibles `None` sein. Andere Typen werden als
  `tool_0_invalid_tool_call` auditiert.
- Test: `tests/test_proactive_agent.py` `156 passed`; Parser-Fokus `2 passed`;
  Ruff, `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `44133ce5 fix: reject non-object proactive tool arguments`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`10/20` Commits. Kein Push. Restart nach 10 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Scheduler versteckt ungueltige Items nicht vor Fail-Closed

- 2026-07-17: Der uebergeordnete Cycle rief den Expirer vor dem Dispatcher
  auf. Kaputte `recurrence`, `retry_at` oder `risk_gate`-Werte konnten dadurch
  als alte Items `expired` werden, bevor die strukturierten Invalidierungs-
  pfade liefen.
- Der gemeinsame Expirer ueberspringt jetzt alle bekannten ungueltigen,
  nichtleeren Zeit-/Regel-/Risk-Felder. Dispatch- und Scheduler-Reihenfolge
  validiert diese Felder vor Ablaufmarkierung; Fehler bleiben sichtbar und
  reparierbar.
- Tests: `tests/test_proactive_agent.py` + `tests/test_proactive_cli.py`
  `212 passed`; Cycle-Regression `2 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `f6efd20a fix: keep invalid proactive items visible before expiry`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`12/20` Commits. Kein Push. Restart nach 8 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Tool-Agent akzeptiert Singleton-Tool-Call-Responses

- 2026-07-17: Adapter, die `tool_calls` als einzelnes Call-Objekt statt Liste
  lieferten, wurden vom Extraktor als nicht iterierbar verworfen und fuehrten
  zu falschem `no_tool_calls`.
- Ein erkennbares einzelnes Tool-Call-Objekt wird jetzt als Eintrag verarbeitet.
  Nicht-Tool-Mappings und Strings bleiben verworfen; Listen/Tupel behalten ihre
  bisherige Verarbeitung.
- Tests: `tests/test_proactive_agent.py` + `tests/test_proactive_cli.py`
  `213 passed`; Tool-Extraktionsfokus `3 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `7fe8580e fix: accept singleton proactive tool call responses`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`14/20` Commits. Kein Push. Restart nach 6 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Consent deaktiviert Agent bei null Kategorien

- 2026-07-17: `set_proactive_categories(..., ())` liess den Agenten aktiviert,
  obwohl kein Consent-Kanal mehr vorhanden war. Health meldete dadurch
  `proactive enabled without consent categories`; Scheduler blieb wirkungslos.
- Leere Kategorien setzen jetzt `proactive.enabled=False` und loeschen keinen
  Consent-Verlauf. `resume`/`enable` mit Kategorien aktiviert gezielt wieder;
  kein implizites Reaktivieren.
- Test: `tests/test_proactive_agent.py` + `tests/test_proactive_cli.py`
  `214 passed`; Consent-Fokus `2 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `d5f6bdde fix: disable proactive agent without consent categories`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`16/20` Commits. Kein Push. Restart nach 4 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-LLM-Planner liest Mapping-Responses korrekt

- 2026-07-17: `run_proactive_llm_planner` nutzte `getattr(response, "text", ...)`.
  Bei Provider-/Test-Responses als `{"text": "..."}` wurde dadurch das ganze
  Mapping als Text serialisiert und als kaputtes JSON abgelehnt.
- LLM-Planner und Tool-Fallback nutzen jetzt denselben strukturierten
  Response-Text-Parser; direkte String-Responses bleiben kompatibel.
- Test: `tests/test_proactive_agent.py` + `tests/test_proactive_cli.py`
  `215 passed`; Mapping-Response-Fokus `2 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `3d2968c7 fix: parse mapping responses in proactive llm planner`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`18/20` Commits. Kein Push. Restart nach 2 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Tool-Fallback liest Mapping-Text korrekt

- 2026-07-17: Der text-only Fallback in `TeeBotus/proactive.py` benutzte
  ebenfalls `getattr(response, "text", response)`. Provider-Responses als
  `{"text": "..."}` wurden dadurch als gesamtes Mapping weitergereicht.
- Fallback nutzt jetzt denselben zentralen Response-Text-Parser wie der
  Proactive-LLM-Planner. String- und Objekt-Responses bleiben kompatibel.
- Test: `tests/test_proactive_agent.py` + `tests/test_proactive_cli.py`
  `216 passed`; Tool-Fallback-Fokus `2 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a3f436d8 fix: parse mapping text in tool planner fallback`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`20/20` Commits. Kein Push. Restart jetzt. Naechster Push bleibt erst bei
100 Commits.

### Proactive-Human-Review lehnt kaputte Statushistorie ab

- 2026-07-17: `approve_proactive_review_item` pruefte Payload-Felder, aber
  keine vorhandene `status_history`. Beschaedigte Review-Zeilen konnten dadurch
  `queued` werden; Health erkannte den Fehler erst nach der Mutation.
- Approval validiert die vorhandene Statushistorie jetzt vor Policy-/Write-
  Mutation. Ungueltige Historie bleibt `review_pending` mit
  `invalid_status_history`.
- Test: `tests/test_proactive_agent.py` + `tests/test_proactive_cli.py`
  `217 passed`; Human-Review-Fokus `3 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e11a2ca9 fix: reject corrupt proactive review history`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`1/20` Commits. Kein Push. Restart nach 19 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-LLM-Plan blockiert Outbox-Mutationen bei deaktiviertem Agent

- 2026-07-17: `apply_proactive_llm_plan` blockierte Memory/Queue bereits
  indirekt, aber Cancel/Snooze konnten bei deaktiviertem Proactive-Agent noch
  bestehende Outbox-Items mutieren.
- Cancel/Snooze pruefen den Enable-Zustand jetzt vor Store-Mutation und liefern
  `decision_<n>_proactive_disabled`. Schema-, Tool- und Payloadfehler werden
  weiterhin zuerst normal validiert und auditiert.
- Test: `tests/test_proactive_agent.py` + `tests/test_proactive_cli.py`
  `218 passed`; Disabled-Gate-Fokus `13 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `f4bcb1e3 fix: block proactive mutations when disabled`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`4/20` Commits. Kein Push. Restart nach 16 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Cycle isoliert Planner-Providerfehler pro Account

- 2026-07-17: Eine Exception aus LLM-/Tool-Planner oder Planner-Factory
  verliess den Account-Cycle. Ein einzelner Providerfehler konnte dadurch
  Dispatch fuer denselben und folgende Accounts verhindern.
- Plannerfehler werden jetzt pro Account als
  `planner_error:<ExceptionType>` im jeweiligen Report markiert; `_cycle_ok`
  bleibt bewusst `False`. Nach Fehler laeuft Outbox-Recovery, Due-Report und
  Dispatch weiter. Fehlermeldungen werden nicht in den Reporttext kopiert.
- Test: `tests/test_proactive_agent.py` + `tests/test_proactive_cli.py`
  `219 passed`; Exception-/Continue-Fokus `2 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a716b03e fix: isolate proactive planner exceptions`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`6/20` Commits. Kein Push. Restart nach 14 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Response-Parser faellt bei leerem Output auf Text zurueck

- 2026-07-17: Provider-Wrapper konnten `output=[]` und gleichzeitig ein
  gueltiges `.text`/`{"text": ...}` liefern. Der Parser gab dann leeren Text
  zurueck; LLM- und Tool-Fallback meldeten faelschlich kein bzw. kaputtes JSON.
- Strukturierter Output-Text hat weiterhin Vorrang. Nur wenn daraus kein Text
  entsteht, wird das direkte Textfeld verwendet.
- Test: `tests/test_proactive_agent.py` + `tests/test_proactive_cli.py`
  `220 passed`; Empty-Output-Fokus `2 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `b890544e fix: preserve proactive response text on empty output`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`8/20` Commits. Kein Push. Restart nach 12 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Outbox-`retry_at` fail-closed

- 2026-07-17: Ein nicht parsebarer, nichtleerer `retry_at`-Wert wurde von der
  Faelligkeitsauswahl still uebersprungen, aber nicht als Fehler markiert.
  Solcher Altbestand konnte dadurch dauerhaft `queued` bleiben.
- Der Dispatch markiert ungueltige `retry_at`-Werte jetzt vor der Auswahl als
  `failed/invalid_retry_at`; `due_at` und `retry_at` verwenden denselben
  atomaren, lockgeschuetzten Fail-Closed-Pfad. Leeres `retry_at` bleibt erlaubt.
- Test: `tests/test_proactive_agent.py` `138 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `986a103d fix: fail closed on invalid proactive retry timestamps`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`8/20` Commits. Kein Push. Restart nach 12 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Outbox-Wiederholung aus Altbestand fail-closed

- 2026-07-17: Neue Queue-Eintraege lehnen ungueltige Wiederholungsregeln ab,
  alte Zeilen konnten aber `every fortnight` o. ae. enthalten. Dispatch haette
  sie einmal gesendet und danach ohne naechste Faelligkeit terminal beendet.
- Ungueltige nichtleere `recurrence`-Werte werden vor Due-Auswahl als
  `failed/invalid_recurrence` markiert. Health meldet sie ebenfalls explizit;
  leere Wiederholung bleibt eine gueltige Einmal-Nachricht.
- Test: `tests/test_proactive_agent.py` `139 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `bca60818 fix: fail closed on invalid proactive recurrence`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`10/20` Commits. Kein Push. Restart nach 10 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Risk-Gate strikt validiert

- 2026-07-17: `risk_gate` wurde nur normalisiert. Unbekannte Werte wie
  `red-ish` konnten dadurch die Risikopruefung umgehen und als erlaubte
  proaktive Nachricht weiterlaufen.
- Bekannte Gates sind jetzt explizit begrenzt. Neue unbekannte Werte werden
  abgelehnt; queued Altbestand wird vor Due-Auswahl als
  `failed/invalid_risk_gate` markiert. Health meldet unbekannte Gates.
- Test: `tests/test_proactive_agent.py` `140 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `35f9f55f fix: reject unknown proactive risk gates`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`12/20` Commits. Kein Push. Restart nach 8 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Reattempts pro Wiederholung zurueckgesetzt

- 2026-07-17: `dispatch_attempts` blieb bei recurring Items ueber erfolgreiche
  Sendungen erhalten. Nach drei historischen Fehlversuchen wurde die naechste
  Wiederholung ohne Retry direkt `failed`.
- Bei erfolgreichem Recurrence-Requeue wird der Versuchzaehler jetzt auf null
  gesetzt. Jede Wiederholung erhaelt wieder ihr eigenes Retry-Budget; Einmal-
  Items behalten ihren bisherigen Zaehler.
- Test: `tests/test_proactive_agent.py` `141 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `14f9d798 fix: reset proactive retry attempts per recurrence`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`14/20` Commits. Kein Push. Restart nach 6 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Claim gegen stale Snapshots abgesichert

- 2026-07-17: Zwischen Due-Snapshot und Worker-Claim konnten `due_at`, Route
  oder Nachricht geaendert werden. Der Worker haette dann den alten Payload
  senden koennen, obwohl Item bereits snoozed oder inhaltlich ersetzt war.
- Claim liest unter Outbox-Lock frischen Due-Zustand und vergleicht send- und
  policy-relevante Felder. Abweichung bleibt `queued` und ergibt
  `skipped/stale_outbox_item`; kein alter Payload wird gesendet.
- Test: `tests/test_proactive_agent.py` `142 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `9d012afe fix: reject stale proactive claim snapshots`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`16/20` Commits. Kein Push. Restart nach 4 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Route unmittelbar vor Versand erneut geprueft

- 2026-07-17: Route konnte nach Claim, aber vor Sender-Aufruf wechseln. Der
  Worker haette dann an den alten privaten Chat senden koennen.
- Vor Versand wird die geclaimte Route nochmals gegen aktuelle Account-
  Identitaeten geprueft. Bei Abweichung kein Sender-Aufruf; Item wird mit
  `cancelled/stale_route_after_claim` sichtbar beendet.
- Test: `tests/test_proactive_agent.py` `143 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `cdc40f72 fix: recheck proactive route before send`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`18/20` Commits. Kein Push. Restart nach 2 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Dispatch-Attempts gegen negative Altwerte gehaertet

- 2026-07-17: Negative `dispatch_attempts` aus kaputtem Altbestand konnten
  unter null bleiben und dadurch das Retry-Limit fuer viele weitere Versuche
  aushebeln.
- Claim und Sendefehlerpfad klemmen Werte jetzt auf mindestens null; Health
  meldet negative oder nicht numerische `dispatch_attempts` explizit.
- Test: `tests/test_proactive_agent.py` `144 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `1917838d fix: clamp proactive dispatch attempts`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`20/20` Commits. Kein Push. Restart jetzt. Naechster Zyklus startet danach
bei `0/20`; Naechster Push bleibt erst bei 100 Commits.

### Proactive-Wiederholungsregel-validiert

- 2026-07-17: Nicht parsebare Wiederholungen wie `every fortnight` wurden
  still verworfen; Nutzer-/LLM-Absicht wurde als Einmal-Reminder gespeichert.
- Nichtleere, unbekannte Regeln werden jetzt als `invalid_recurrence`
  abgelehnt. Leerer Wert bedeutet weiterhin bewusst keine Wiederholung.
- Test: `tests/test_proactive_agent.py` `135 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `bc04b6c9 fix: reject invalid proactive recurrence rules`.

**Aktueller Laufstand:** Nach dem Restart seit dem letzten Plan-Commit
`2/20` Commits. Kein Push. Restart nach 18 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Faelligkeitszeit vor Write validiert

- 2026-07-17: Beliebiger nicht parsebarer `due_at`-Text wurde als Outbox-
  Eintrag gespeichert und erst beim Dispatch als `invalid_due_at` markiert.
- Nichtleere Zeitstempel werden jetzt nach Policy-Gate vor Outbox-Write
  validiert. Kaputter Altbestand bleibt weiterhin im Dispatch-Fail-Closed-Pfad
  pruefbar und wird dort als `failed/invalid_due_at` markiert.
- Test: `tests/test_proactive_agent.py` `136 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e32f7628 fix: reject invalid proactive due timestamps`.

**Aktueller Laufstand:** Nach dem Restart seit dem letzten Plan-Commit
`4/20` Commits. Kein Push. Restart nach 16 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Policy-Check atomar vor Outbox-Append

- 2026-07-17: Die erste Policy-Pruefung lag vor dem Outbox-Lock. Parallele
  Queue-Aufrufe konnten beide Tageslimit/Minutenabstand passieren und danach
  doppelt schreiben.
- Vor `append_proactive_outbox_item` wird Policy jetzt unter demselben
  Outbox-Lock erneut geprueft; zwischenzeitliche Sperre verhindert Append.
  Route wird ebenfalls aus finaler Entscheidung geschrieben.
- Test: `tests/test_proactive_agent.py` `137 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `cff1d0df fix: recheck proactive policy before append`.

**Aktueller Laufstand:** Nach dem Restart seit dem letzten Plan-Commit
`6/20` Commits. Kein Push. Restart nach 14 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Instanzen isolieren-AccountStore-Fehler

- 2026-07-17: Der Proactive-Zyklus erzeugte den `AccountStore` vor dem
  Account-Loop ohne Fehlerfang. Ein Secret-Service-, SQL- oder
  Metadatenfehler in einer aktivierten Instanz konnte dadurch den gesamten
  Lauf abbrechen und nachfolgende Instanzen ueberspringen.
- Der Fehler wird jetzt als `instance_report["error"]` gemeldet; der Zyklus
  laeuft mit naechster Instanz weiter. `_cycle_ok` bleibt dabei korrekt
  `False`, damit Monitoring den Lauf weiterhin als fehlerhaft erkennt.
- Test: `tests/test_proactive_cli.py` `50 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `808670d2 fix: isolate proactive store errors per instance`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`2/20` Commits. Kein Push. Restart nach 18 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Account-Discovery-isoliert

- 2026-07-17: `_account_ids(store)` lief ebenfalls ausserhalb des
  Instanz-Guards. Fehler beim Lesen von `accounts/` konnten den Proactive-Lauf
  trotz erfolgreicher Store-Erzeugung abbrechen.
- Account-Discovery-Fehler werden jetzt pro Instanz als `instance_report`-
  Fehler ausgegeben; folgende Instanzen bleiben erreichbar. `_cycle_ok` bleibt
  `False`.
- Test: `tests/test_proactive_cli.py` `51 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `547f68e7 fix: isolate proactive account discovery errors`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`4/20` Commits. Kein Push. Restart nach 16 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Account-Discovery-fail-closed

- 2026-07-17: `_account_ids` ignorierte Fehler aus `store.list_account_ids`.
  SQL-/Index-only-Accounts konnten dadurch fehlen, waehrend der Proactive-
  Report faelschlich gesund blieb.
- Store-Discovery-Fehler werden jetzt an Instanz-Guard weitergereicht und als
  `instance_report["error"]` sichtbar. Physische Account-Verzeichnisse gelten
  nicht stillschweigend als vollstaendiger Ersatz fuer SQL-/Index-Discovery.
- Test: `tests/test_proactive_cli.py` `52 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `4aaee84f fix: surface proactive account discovery failures`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`6/20` Commits. Kein Push. Restart nach 14 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Instanz-Auswahl-dedupliziert

- 2026-07-17: Wiederholte `--instance`-Argumente wurden unveraendert als
  mehrere Durchlaeufe verarbeitet. Bei `--plan` konnte dieselbe Instanz dadurch
  doppelte Reflection-/Outbox-Arbeit ausloesen.
- Ausgewaehlte Instanznamen werden jetzt stabil dedupliziert; Reihenfolge bleibt
  erhalten und einzelne Instanz wird genau einmal verarbeitet.
- Test: `tests/test_proactive_cli.py` `53 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `edfb0897 fix: deduplicate proactive instance selection`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`8/20` Commits. Kein Push. Restart nach 12 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Instanzpfad-validiert

- 2026-07-17: Ausgewaehlte Instanznamen wurden direkt an `instances_dir`
  angehaengt. Path-like Werte wie `../outside` konnten dadurch ausserhalb des
  erwarteten Instances-Baums landen.
- Ausgewaehlte Namen muessen jetzt einzelne Ordnernamen sein; ungueltige Werte
  werden als `invalid_instance_name` gemeldet und nie an `store_factory`
  weitergereicht. Gueltige Instanzen laufen weiter.
- Test: `tests/test_proactive_cli.py` `54 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `7170fb5c fix: reject unsafe proactive instance names`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`10/20` Commits. Kein Push. Restart nach 10 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Instanz-Discovery-Fehler strukturiert

- 2026-07-17: Ein nichtverzeichnisartiges `instances_dir` liess
  `Path.iterdir()` ungefangen abbrechen. Der Scheduler lieferte dadurch keinen
  maschinenlesbaren Fehlerreport.
- Discovery-Fehler werden jetzt als Top-Level-
  `instance_discovery_failed` mit `ok=False` ausgegeben; Store-Erzeugung wird
  nicht versucht. Fehlendes Verzeichnis bleibt weiterhin leere Discovery.
- CLI-Textreport zeigt den Top-Level-Fehler explizit.
- Test: `tests/test_proactive_cli.py` `55 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `1fecdc90 fix: report proactive instance discovery errors`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`12/20` Commits. Kein Push. Restart nach 8 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Review-Instanzgrenzen gehaertet

- 2026-07-17: Das Review-Modul akzeptierte Path-Traversal bei `--instance` und
  Einzel-Review. Fehlende Instanzen konnten ausserdem durch `AccountStore`-
  Konstruktion neue Verzeichnisse erzeugen.
- Review-Auswahl akzeptiert nur einzelne Ordnernamen, prueft vorhandene
  `data/accounts`-Struktur und meldet `invalid_instance_name` bzw.
  `selected_instance_not_found`. Store wird in diesen Faellen nicht geoeffnet.
- `list_proactive_review_items` verschluckt `list_account_ids`-Fehler nicht
  mehr; Report bleibt `ok=False`.
- Tests: `tests/test_proactive_review.py` `10 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `2048842e fix: harden proactive review instance boundaries`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`14/20` Commits. Kein Push. Restart nach 6 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Review-Aktion vor Store-I/O validiert

- 2026-07-17: `review_proactive_item` oeffnete Store vor der Validierung der
  Aktion. Ungueltige Aktionen konnten dadurch Secret-/SQL-I/O ausloesen und bei
  fehlender Instanz den falschen Fehler melden.
- `approve`/`reject` werden jetzt zuerst normalisiert und validiert;
  ungueltige Aktionen liefern `unsupported_action` ohne Store-Zugriff.
  Reports verwenden den normalisierten Instanznamen.
- Test: `tests/test_proactive_review.py` `11 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `444f73ee fix: validate proactive review actions before I/O`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`16/20` Commits. Kein Push. Restart nach 4 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Review-Storefehler mit Zielmetadaten

- 2026-07-17: Der Store-Factory-Fehlerpfad von `review_proactive_item` lieferte
  nur Aktion und Grund. Betroffene Instanz, Account und Outbox-Item fehlten
  fuer CLI-/JSON-Consumer.
- Fehlerreports enthalten jetzt dasselbe Zielschema wie Review-Fehler nach
  Store-Erzeugung: `instance`, `account_id`, `item_id`, `route` und `reason`.
- Test: `tests/test_proactive_review.py` `12 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `65be5024 fix: preserve proactive review error targets`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`18/20` Commits. Kein Push. Restart nach 2 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Outbox-Pflichtfelder vor Write validiert

- 2026-07-17: `queue_proactive_message` konnte leeren `intent` oder leeren
  Nachrichtentext als `queued` speichern. Dispatch scheiterte erst spaeter,
  Outbox-/Health-Zustand wurde unnoetig defekt.
- Nach erfolgreichem Policy-Gate werden Pflichtfelder jetzt vor jedem Outbox-
  Write validiert. Fehler: `missing_intent` bzw. `missing_message_text`.
- Test: `tests/test_proactive_agent.py` `134 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `937e56ef fix: reject empty proactive message content`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`20/20` Commits. Kein Push. Restart jetzt. Naechster Zyklus startet danach
bei `0/20`; Naechster Push bleibt erst bei 100 Commits.

### Proactive-Health meldet unerwartete Backend-Fehler

- 2026-07-17: `check_proactive_agent_account` fing bei Agent-State, Outbox
  und Route-Matching nur bekannte Store-/I/O-Fehler. Unerwartete SQL- oder
  Backend-Ausnahmen konnten dadurch Healthcheck, Doctor oder Applet abbrechen.
- Alle drei Health-Reads melden jetzt auch unerwartete `Exception`-Fehler als
  `ok=False` mit Typ und Grund. Der Check mutiert dabei keine Daten.
- Tests: `tests/test_proactive_agent.py` `174 passed`; Fokus fuer State-,
  Outbox- und Route-Backendfehler `5 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `6b65af5f fix: report proactive health backend failures`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`3/20` Commits. Kein Push. Restart nach 17 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Dispatch kapselt Route-Backendfehler

- 2026-07-17: Route-Matching konnte im Policy-Gate oder nach Worker-Claim
  unerwartet scheitern. Vor Claim crashte Dispatch; nach Claim blieb das Item
  ungeplant in `dispatching`.
- Route-Fehler werden vor Claim als `queued:route_check_unavailable`
  zurueckgestellt. Nach Claim wird das Item mit `failed` markiert; wenn auch
  dieser Status-Write scheitert, meldet der Report `status_update_failed`.
  Kein Senderaufruf bei unbekanntem Route-Zustand.
- Loudness-State-Fehler verwenden im Policy- und Post-Claim-Pfad ebenfalls
  einen fail-closed-`Exception`-Guard.
- Tests: `tests/test_proactive_agent.py` plus
  `tests/test_notification_loudness.py` `343 passed`; Route-/Loudness-Fokus
  `4 passed`; Ruff, `compileall` und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `27f332f6 fix: contain proactive route backend failures`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`5/20` Commits. Kein Push. Restart nach 15 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Notification-Loudness faengt unerwartete Backendfehler

- 2026-07-17: Antwort-, Prompt- und Scheduler-Pfade fingen nur bekannte
  `AccountStoreError`-/I/O-/Value-Fehler. Unerwartete SQL-, Secret- oder
  Wrapper-Ausnahmen konnten Message-Handler und Scheduler verlassen.
- Alle drei oeffentlichen Loudness-Pfade behandeln unerwartete `Exception`-
  Fehler jetzt fail-closed: keine Antwort, kein Prompt und keine Outbox-
  Mutation bei unlesbarem Backend.
- Test: `tests/test_notification_loudness.py` `167 passed`; Ruff,
  `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e0cde3e2 fix: fail closed on loudness backend errors`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`7/20` Commits. Kein Push. Restart nach 13 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-LLM-Cancel/Snooze meldet Persistenzfehler

- 2026-07-17: LLM-Cancel meldete ein fehlgeschlagenes Status-Update als
  `item_not_queued`; LLM-Snooze meldete eine fehlgeschlagene Due-At-Schreibung
  als `item_not_found`. Dadurch war ein weiterhin `queued`-Item nicht von einem
  echten Race oder einem fehlenden/terminalen Item unterscheidbar.
- Beide Mutationen fangen Schreibausnahmen ab und pruefen nach einem falschen
  Rueckgabewert den real gespeicherten Outbox-Zustand. Ein weiterhin queued Item
  liefert `status_update_failed`; ein zwischenzeitlich terminales oder fehlendes
  Item behaelt den bisherigen Race-Fehlercode.
- Test: `tests/test_proactive_agent.py` `183 passed`; zwei neue Regressionstests
  fuer Cancel/Snooze-Persistenzfehler; Ruff und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `26ca1f09 fix: report proactive llm mutation persistence failures`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`15/20` Commits. Kein Push. Restart nach 5 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-LLM-Plan kapselt Memory-/Queue-Schreibfehler

- 2026-07-17: `apply_proactive_llm_plan` liess Ausnahmen aus
  `append_structured_memory_entry` und `append_proactive_outbox_item` bis zum
  Aufrufer durch. Ein einzelner SQL-/JSON-Schreibfehler brach dadurch den Plan
  ab und unterdrueckte spaetere Entscheidungen sowie deren Audit-Eintraege.
- Memory- und Queue-Mutationen melden Schreibausnahmen jetzt als
  `storage_write_failed`; `apply_proactive_llm_plan` verarbeitet danach weitere
  Entscheidungen. Kein Erfolg wird bei unsicherer Persistenz behauptet.
- Test: `tests/test_proactive_agent.py` `185 passed`; Regressionen fuer beide
  Schreibpfade und Fortsetzung nach Memory-Fehler; Ruff und `git diff --check`
  gruen. Kein Provider/API-Aufruf.
- Code-Commit: `6d185489 fix: contain proactive llm write failures`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`17/20` Commits. Kein Push. Restart nach 3 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-LLM-Plan ueberlebt Audit-Persistenzfehler

- 2026-07-17: Fehlerpfade und erfolgreiche Cancel-/Snooze-Entscheidungen
  riefen den Audit-Write synchron auf. Ein kaputtes Audit-Backend konnte damit
  den Plan nach bereits ausgefuehrter Fachaktion abbrechen; leere Rueckgaben
  wurden ausserdem als Audit-IDs weitergereicht.
- LLM-Audit-Persistenz ist jetzt best-effort mit Exception-Logging. Erfolgreiche
  Fachaktionen bleiben erhalten; nicht gespeicherte Audit-IDs werden aus dem
  Resultat entfernt, statt als gueltige IDs zu erscheinen.
- Test: `tests/test_proactive_agent.py` `186 passed`; Regression fuer
  Auditfehler nach Cancel und Folgeentscheidung; Ruff und `git diff --check`
  gruen. Kein Provider/API-Aufruf.
- Code-Commit: `871ad94a fix: keep proactive plans alive when audit fails`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`8507bab8 docs: record proactive audit guard` machte `20/20` voll; Restart ist
erfolgt. Seit diesem Plan-Commit neuer Zyklus `1/20` Commits. Kein Push.
Naechster Restart nach 19 weiteren Commits. Naechster Push bleibt erst bei 100
Commits.

### Proactive-Safety-Hold ueberlebt Audit-Persistenzfehler

- 2026-07-17: Der Safety-Dispatch setzte riskante Items korrekt auf `skipped`,
  liess danach aber einen Audit-Schreibfehler ungefangen. Dadurch konnte ein
  bereits sicher blockierter Dispatch-Cycle trotzdem abbrechen.
- Safety-Audit ist jetzt best-effort mit Exception-Logging. Item bleibt
  `skipped`, Versand bleibt unterdrueckt; fehlendes Audit wird nicht als
  erfolgreicher Audit-Write behauptet.
- Test: `tests/test_proactive_agent.py` `187 passed`; Regression fuer
  Auditfehler bei `risk_gate=crisis`; Ruff und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `f992185f fix: keep proactive safety holds on audit failure`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`3/20` Commits. Kein Push. Restart nach 17 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Dispatch kapselt Housekeeping-Fehler

- 2026-07-17: Die sechs Dispatch-Vorstufen fuer Recovery, kaputte Zeitfelder,
  Recurrence, Risk-Gates und Ablauf liessen Backend-Ausnahmen ungefangen. Ein
  einzelner fehlgeschlagener Schreibvorgang konnte dadurch den gesamten
  `dispatch_due_proactive_outbox_items`-Lauf ohne Ergebnis abbrechen.
- Jede Vorstufe laeuft jetzt isoliert weiter und meldet bei Fehler
  `housekeeping_failed:<step>`. Normale Due-Items bleiben anschliessend
  pruefbar; keine Sendung wird aus einem Housekeeping-Fehler heraus behauptet.
- Test: `tests/test_proactive_agent.py` `188 passed`; Regression fuer
  fehlgeschlagenes `invalid_due_at`-Housekeeping; Ruff und `git diff --check`
  gruen. Kein Provider/API-Aufruf.
- Code-Commit: `072ff237 fix: contain proactive housekeeping failures`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`5/20` Commits. Kein Push. Restart nach 15 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Human-Review meldet Persistenzfehler

- 2026-07-17: Approve/Reject mutierten Review-Items im Speicher und liessen
  `write_proactive_outbox`-Ausnahmen ungefangen. Ein Fehler konnte damit den
  Aufrufer werfen lassen, obwohl keine Review-Entscheidung bestaetigt werden
  durfte.
- Beide Pfade liefern bei fehlender Persistenz jetzt
  `status_update_failed`; das gespeicherte Item bleibt `review_pending` und
  wird nicht als approved oder rejected gemeldet.
- Test: `tests/test_proactive_agent.py` `190 passed`; Regressionen fuer
  Approve und Reject bei Write-Ausfall; Ruff und `git diff --check` gruen.
  Kein Provider/API-Aufruf.
- Code-Commit: `80c98283 fix: report proactive review persistence failures`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`7/20` Commits. Kein Push. Restart nach 13 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Reflection rollt Teilbatches zurueck

- 2026-07-17: Der deterministische Reflection-Planner schrieb neun Memories
  einzeln. Ein Fehler in der Mitte liess Teilentries mit gleichem Fingerprint
  liegen; der naechste Lauf uebersprang dadurch die Quelle dauerhaft.
- Planner sichert Memory-Entries, Index und Outbox pro Quelle. Bei Memory-,
  Queue- oder Policy-Fehlern wird der Batch zurueckgerollt; bei erfolgreicher
  Wiederherstellung bleibt Quelle mit `memory_persistence_failed` oder
  `queue_persistence_failed` retrybar. Rollbackfehler werden separat gemeldet.
- Test: `tests/test_proactive_agent.py` `192 passed`; Regressionen fuer
  Teilbatch- und Queue-Fehler; Ruff und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `b372ff55 fix: rollback partial proactive reflections`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`9/20` Commits. Kein Push. Restart nach 11 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Engine meldet Proactive-Kommando-Speicherfehler

- 2026-07-17: Der Engine-Grenzpunkt rief `/proactive` ohne Ausnahmebehandlung
  auf. Fehler beim Lesen/Schreiben von Agent_State konnten den Command-Pfad
  abbrechen, statt Nutzerfeedback zu liefern.
- Proactive-Kommandos werden jetzt am Engine-Grenzpunkt abgefangen. Nutzer
  erhalten eine klare Speicherfehlerantwort; kein Erfolg wird behauptet und
  kein LLM-Fallback wird gestartet.
- Test: `tests/test_engine_identity_flows.py` plus
  `tests/test_proactive_agent.py` `386 passed`; Ruff und `git diff --check`
  gruen. Kein Provider/API-Aufruf.
- Code-Commit: `1494ec44 fix: surface proactive command storage failures`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`11/20` Commits. Kein Push. Restart nach 9 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Notification-Loudness bestaetigt trotz Outbox-Cleanup-Fehler

- 2026-07-17: Der Response-Handler persistierte `confirmed`/`declined` zuerst
  im Agent-State, liess danach aber einen Outbox-Cleanupfehler nach aussen
  laufen. Dadurch bekam Nutzer keine Bestaetigung und Engine behandelte die
  Antwort weiter als normale Nachricht.
- Cleanupfehler werden jetzt geloggt und von der bereits sicheren Terminal-
  Entscheidung getrennt. Nutzer bekommt Bestaetigung; der Dispatcher blockiert
  weitere Loudness-Sendungen ueber den terminalen Agent-State.
- Test: `tests/test_notification_loudness.py` `169 passed`; Regression fuer
  Outbox-Write-Fehler nach Bestaetigung; Ruff und `git diff --check` gruen.
  Kein Provider/API-Aufruf.
- Code-Commit: `0e20d447 fix: preserve loudness confirmations after cleanup errors`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`13/20` Commits. Kein Push. Restart nach 7 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Reminder-Classifier fail-open bei Backendfehler

- 2026-07-17: Der optionale strukturierte Reminder-Classifier fing nur
  Parsefehler. Provider-/Wrapper-Ausnahmen konnten bis in Engine laufen und
  normale Chatverarbeitung abbrechen.
- Unerwartete Classifier-Fehler werden jetzt geloggt und als kein sicher
  erkennbarer Reminder behandelt. Keine Erinnerung wird aus unsicherem Output
  angelegt; normaler Chatpfad bleibt verfuegbar.
- Test: `tests/test_reminder_intent.py` plus
  `tests/test_engine_identity_flows.py` `234 passed`; Ruff und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `d3a8c142 fix: fail open on reminder classifier errors`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`15/20` Commits. Kein Push. Restart nach 5 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Engine kapselt natuerliche Reminder-Backendfehler

- 2026-07-17: `_natural_reminder_reply` fing nur bekannte Storage-/Value-
  Fehler. Unerwartete Backend- oder Wrapper-Ausnahmen konnten den normalen
  Message-Loop abbrechen.
- Engine faengt solche Fehler jetzt am User-facing Reminder-Grenzpunkt ab,
  loggt sie und liefert die bekannte Speicherfehlerantwort. Kein falscher
  Reminder-Erfolg; anschliessende Verarbeitung bleibt moeglich.
- Test: `tests/test_engine_identity_flows.py` `195 passed`; Regression fuer
  unerwarteten Reminder-Backendfehler; Ruff und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `0707afce fix: contain natural reminder backend failures`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`17/20` Commits. Kein Push. Restart nach 3 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Admin-Status kapselt Route-Backendfehler

- 2026-07-17: Admin-Statuszeilen sowie Runtime- und Benchmark-Summary-
  Benachrichtigungen fingen Route-Fehler nur typbezogen. Unerwartete SQL-,
  Secret- oder Wrapper-Ausnahmen konnten Statusdiagnose und Versand abbrechen.
- Lokale und instanzuebergreifende Route-Aufloesung meldet jetzt auch
  unerwartete `Exception`-Fehler strukturiert. Betroffene Admins erhalten
  `warning`/`failed`; andere Accounts und Statusausgaben laufen weiter.
- Test: `tests/test_runtime_admin_accounts.py` `33 passed`; Ruff,
  `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `2abd6e67 fix: contain admin route backend failures`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`9/20` Commits. Kein Push. Restart nach 11 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Cycle bewahrt Dispatch-Diagnose bei Auditfehlern

- 2026-07-17: Ein unerwarteter Fehler beim Persistieren von
  `dispatch_results` fiel in den aeusseren Account-Catch. Dadurch konnte der
  erfolgreiche Versand im Report nur noch als allgemeiner Account-Fehler
  erscheinen.
- Audit-Persistenzfehler werden jetzt separat als
  `dispatch_persistence_error` gemeldet. `dispatch_results` bleiben erhalten;
  andere Account- und Instanzzyklen laufen weiter.
- Test: `tests/test_proactive_cli.py` `62 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `fffaa8e9 fix: preserve proactive dispatch diagnostics`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`11/20` Commits. Kein Push. Restart nach 9 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Review meldet kaputte Outbox-Shapes

- 2026-07-17: Der Review-Scanner iterierte jede lesbare Outbox blind. Ein
  Mapping statt Liste oder ein nicht-objektartiger Listeneintrag wurde still
  uebersprungen; kaputte Reviewdaten erschienen als gesunder Leerstand.
- Nicht-listige Outboxen und kaputte Eintraege erzeugen jetzt strukturierte
  Fehler. Gueltige Items werden weiterhin gesammelt; Report `ok` wird false.
- Test: `tests/test_proactive_review.py` `15 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `9ad3061d fix: report corrupt proactive review outbox`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`13/20` Commits. Kein Push. Restart nach 7 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Due-Auswahl lehnt kaputte Outbox-Container ab

- 2026-07-17: `due_proactive_outbox_items` iterierte einen Mapping-Container
  als Schluessel und lieferte dadurch scheinbar korrekt `0` Faelliges. Ein
  Scheduler-Dry-Run konnte eine kaputte Outbox so als gesund erscheinen lassen.
- Die Containerform wird vor der Due-Auswahl auf `list` geprueft. Andere
  Container liefern jetzt `ValueError: proactive_outbox is not a list`; die
  aufrufende Cycle-Schicht kann den Accountfehler strukturiert reportieren.
- Test: `tests/test_proactive_agent.py` `177 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `b83ccae2 fix: reject malformed proactive outbox container`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`15/20` Commits. Kein Push. Restart nach 5 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Status-Auth ueberschreibt keinen unlesbaren State

- 2026-07-17: `authorize_status_recipient` und
  `deauthorize_status_recipient` ersetzten bei Read-Fehlern den vorhandenen
  Auth-State durch `{}` und schrieben neue Flags. Das konnte kaputte oder
  schluesselbedingt unlesbare Admindaten zerstoeren.
- Read-Fehler werden jetzt vor jeder Mutation weitergegeben. Autorisierungs-
  und Opt-out-Pruefung bleiben fail-closed; Engine und Telegram-Pre-Gate
  melden Speicherfehler statt zu crashen.
- Test: `tests/test_engine_identity_flows.py` `193 passed`; Ruff,
  `compileall` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `6edf3d47 fix: preserve unreadable status auth state`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`17/20` Commits. Kein Push. Restart nach 3 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Discovery reportiert unerwartete Filesystemfehler

- 2026-07-17: Die Instanz-Discovery fing nur erwartete `OSError`-/`ValueError`-
  Fehler. Eine unerwartete Filesystem- oder Wrapper-Ausnahme konnte den
  gesamten Proactive-Cycle vor dem strukturierten Report abbrechen.
- Discovery faengt jetzt jede normale `Exception` und liefert weiterhin
  `instance_discovery_failed` mit leerer Instanzliste. Store-Zugriff erfolgt
  nicht.
- Test: `tests/test_proactive_cli.py` `63 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `3fa026c4 fix: report unexpected proactive discovery errors`.

**Aktueller Laufstand:** Nach dem anschliessenden Plan-Commit
`3b31b0bd docs: record proactive discovery guard` waren `20/20` Commits
erreicht. Kein Push. Restart ist erfolgt; neuer Zyklus steht nach dieser
Korrektur bei `1/20`.
Naechster Push bleibt erst bei 100 Commits.

### Proactive-Review-Discovery reportiert unerwartete Filesystemfehler

- 2026-07-17: Die Review-CLI fing bei Instanz-Discovery nur erwartete
  `OSError`-/`ValueError`-Fehler. Unerwartete Filesystem-/Wrapper-Fehler
  konnten den Review-Scan ohne JSON-Report abbrechen.
- Review-Discovery liefert jetzt ebenfalls `instance_discovery_failed` mit
  `ok=false` und leerer Itemliste; Store-Zugriff erfolgt nicht.
- Test: `tests/test_proactive_review.py` `16 passed`; Ruff, `compileall` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `8bf07b5e fix: report unexpected review discovery errors`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`2/20` Commits. Kein Push. Restart nach 18 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Proactive-Worker meldet fehlgeschlagene Loudness-Persistenz

- 2026-07-17: Nach dem Worker-Claim behandelte der Loudness-Dispatch sowohl
  `notification_loudness_state_unavailable` als auch
  `notification_loudness_decided` ohne das Persistenzresultat zu pruefen.
  Ein fehlgeschlagener Statuswechsel liess das Item `dispatching` und konnte
  spaeter erneut aufgegriffen werden.
- Beide post-claim Uebergaenge pruefen jetzt Rueckgabewert und Ausnahme. Bei
  fehlender Persistenz wird `failed/status_update_failed` reportiert; Versand
  bleibt unterdrueckt.
- Test: `tests/test_notification_loudness.py` `168 passed`; gezielter
  Loudness-Persistenztest gruen; Ruff und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `c2348a5f fix: report loudness dispatch persistence failures`.

### Status-Auth-Gate faengt Persistenzfehler adapteruebergreifend ab

- 2026-07-17: Der gemeinsame `TeeBotusEngine`-Pfad liess Fehler beim
  Anlegen/Route-Speichern/Autorisieren eines Status-Auth-Accounts aus dem
  Gate laufen. Telegram hatte dafuer bereits einen Schutz; Signal, Matrix
  und direkte Engine-Aufrufe konnten den Secret-Versuch dadurch abbrechen.
- Das Gate behandelt unerwartete Persistenzfehler jetzt fail-closed. Es gibt
  keine falsche Bestaetigung und keinen Status-/Adminzugriff; der Account
  bleibt unauthorisiert. Ein spaeterer Versuch bleibt moeglich.
- Test: `pytest -q tests/test_engine_identity_flows.py -k 'status_auth'` `11
  passed`; Ruff und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `4e2797dd fix: fail closed on status auth persistence errors`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`19/20` Commits. Kein Push. Restart nach einem weiteren Plan-Commit.

### Zyklusabschluss

Dieser Plan-Commit macht Zyklus `20/20` voll. Kein Push. Dienst-Neustart jetzt;
danach neuer Zyklus bei `0/20`. Naechster Push bleibt erst bei 100 Commits.

### Voice-Provider kapselt unerwartete Fehler

- 2026-07-17: `/voice` fing nur `OpenAIAPIError`. Generische LiteLLM-,
  Provider- oder Wrapper-Ausnahmen konnten Sprachgenerierung und Bot-Loop
  abbrechen.
- Voice-Generierung behandelt unerwartete Fehler jetzt wie bekannte
  Providerfehler: Log plus bestehender Voice-Fehlertext. Kein falscher
  Audio-Versand.
- Test: `tests/test_engine_identity_flows.py` `206 passed`; Ruff und
  `git diff --check` gruen. Kein echter Provider/API-Aufruf.
- Code-Commit: `3b7a82b5 fix: contain voice provider failures`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem letzten Restart
`1/20` Commits. Kein Push. Restart nach 19 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `2/20` voll.

### LLM-Memory-Postprocessing blockiert keine Antwort

- 2026-07-17: Nach erfolgreicher LLM-Antwort konnten Interaction-Write,
  semantischer Nebenindex oder optionaler Memory-Classifier unerwartete
  Backend-/Wrapperfehler nach oben werfen. Dadurch verlor Nutzer Antwort,
  obwohl LLM bereits erfolgreich geantwortet hatte.
- Alle drei Schritte sind jetzt best-effort: Fehler werden geloggt,
  Memory/Index bleiben retry-/rebuildbar, Reply wird weiter ausgeliefert.
- Test: `tests/test_engine_identity_flows.py` `208 passed`; Ruff und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c7b4d364 fix: isolate memory postprocessing failures`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem letzten Restart
`3/20` Commits. Kein Push. Restart nach 17 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `4/20` voll.

### Bildpfad kapselt Quota- und Providerfehler

- 2026-07-17: Bild-Quota-State-Read/Write und `generate_image` fingen nur
  bekannte Fehler. Generische Backend-/Providerfehler konnten nach
  erfolgreicher Textantwort den gesamten LLM-Reply abbrechen.
- Bildproviderfehler werden jetzt als Bildfehler behandelt; vorhandener Text
  bleibt sichtbar. Quota-State-Fehler verweigern Bildgenerierung fail-closed;
  kein unkontrollierter Bildversand.
- Test: `tests/test_engine_identity_flows.py` `209 passed`; Ruff und
  `git diff --check` gruen. Kein echter Provider/API-Aufruf.
- Code-Commit: `83f1b59b fix: contain image quota and provider failures`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem letzten Restart
`5/20` Commits. Kein Push. Restart nach 15 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `6/20` voll.

### RouteTo kapselt Admin- und Factoryfehler

- 2026-07-17: RouteTo-Admin-Check und Client-Factory fingen nur bekannte
  Fehler. Kaputtes Admin-Memory oder LiteLLM-/Backend-Setup konnte den
  direkten Routing-Command abbrechen.
- Admin-Lookup fail-closed; Factoryfehler werden geloggt und als kontrollierte
  Route-Initialisierungsantwort zurueckgegeben. Kein unautorisierter Route-
  Zugriff und kein Runtime-Abbruch.
- Test: `tests/test_route_to_llm_command.py` `10 passed`; zusammen mit
  Engine-Regressionen `219 passed`; Ruff und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `6fa1594d fix: contain route initialization failures`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem letzten Restart
`7/20` Commits. Kein Push. Restart nach 13 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `8/20` voll.

### WTF-Sicherheitsmutation behauptet keinen Teilerfolg

- 2026-07-17: WTF-Flow pruefte Link, rotierte Secret, trennte Identitaet und
  loeschte Notification ohne generischen Fehlerfang. Ein SQL-/Secret-/State-
  Fehler konnte Loop-Abbruch oder falschen Erfolg nach Teilmutation erzeugen.
- Kritische Schritte fail-closed: Fehler werden geloggt, kein Erfolgstext
  gesendet; Link bleibt bei Teilfehler bestehen und erneuter WTF-Versuch ist
  moeglich. Linkpruefung ist ebenfalls fail-closed.
- Test: WTF-Fokus `3 passed`; Engine+Route `220 passed`; Ruff und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `9788b9ce fix: contain wtf security mutation failures`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem letzten Restart
`9/20` Commits. Kein Push. Restart nach 11 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `10/20` voll.

### Primaerer Login kapselt Backendfehler

- 2026-07-17: Lokales `link_identity` fing nur `AccountStoreError`. Ein
  generischer SQL-, Secret- oder Wrapperfehler konnte `/login` abbrechen.
- Login-Backendfehler werden jetzt geloggt und als kontrollierte Antwort
  behandelt. Kein Account-Link und kein falscher Erfolg; erneuter Versuch
  bleibt moeglich.
- Test: Login-Fokus `2 passed`; Engine+Route `221 passed`; Ruff und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `b4f1ac55 fix: contain primary login failures`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem letzten Restart
`11/20` Commits. Kein Push. Restart nach 9 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `12/20` voll.

### Account-Registrierung kapselt Secret-Backendfehler

- 2026-07-17: `/register` fing nur `AccountStoreError`. Generische Secret-,
  SQL- oder Crypto-Wrapperfehler konnten Command-Handling abbrechen.
- Registrierung meldet unerwartete Fehler jetzt kontrolliert und gibt nie
  Secret-Ausgabe aus. Kein falscher Erfolg; erneuter Versuch bleibt moeglich.
- Test: Register-Fokus `2 passed`; Engine+Route `222 passed`; Ruff und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `9d61d06e fix: contain account registration failures`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem letzten Restart
`13/20` Commits. Kein Push. Restart nach 7 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `14/20` voll.

### Secret-Rotation kapselt Backendfehler

- 2026-07-17: `/rotate_secret` und Account-Edit-Secretrotation fingen
  generische Secret-/SQL-/Crypto-Fehler nicht. Ein Fehler konnte Bot-Loop
  abbrechen oder Rotation ohne klare Antwort lassen.
- Beide Pfade melden Rotationfehler kontrolliert, geben kein neues Secret aus
  und behalten bestehenden Flow/Secretzustand bei. Kein falscher Erfolg.
- Test: Rotation-Fokus `2 passed`; Engine+Route `223 passed`; Ruff und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `bf8cc99e fix: contain secret rotation failures`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem letzten Restart
`15/20` Commits. Kein Push. Restart nach 5 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `16/20` voll.

### Account-Anzeige kapselt Backendfehler

- 2026-07-17: `/account` und `/linked_accounts` liessen unerwartete
  SQL-/Crypto-/Dateifehler aus `account_summary()` bis in den Identity-Flow
  laufen. Ein defektes Account-Backend konnte dadurch die Befehlsverarbeitung
  abbrechen.
- Beide Ausgaben melden jetzt kontrolliert, dass Accountdaten gerade nicht
  gelesen werden konnten. Kein falscher Accountstatus und kein Bot-Loop-Abbruch.
- Test: fokussierter Account-Fehlerpfad `3 passed`; Ruff und `git diff --check`
  gruen. Kein Provider/API-Aufruf.
- Code-Commit: `b5b3ff48 fix: contain account summary failures`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem letzten Restart
`17/20` Commits. Kein Push. Restart nach 3 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `18/20` voll.

### Kanal-Trennung kapselt Backendfehler

- 2026-07-17: Direkte `/unlink_this_channel`- und bestätigte
  `/account_edit`-Trennung liessen unerwartete Fehler aus `unlink_identity()`
  ungefangen bis in den Identity-Flow laufen.
- Beide Pfade melden Trennfehler kontrolliert. Der Account bleibt verknüpft;
  der bestätigte Bearbeitungsflow bleibt für einen Retry erhalten. Kein
  falscher Erfolg.
- Test: fokussierter Trennfehlerpfad `4 passed`; Ruff und `git diff --check`
  gruen. Kein Provider/API-Aufruf.
- Code-Commit: `65ffce7f fix: contain account unlink failures`.

### Help-Admin-Prüfung fail-closed

- 2026-07-17: `_account_is_help_admin()` fing nur erwartete Storefehler. Ein
  unerwarteter Fehler in der Admin-Prüfung konnte `/help` abbrechen.
- Unerwartete Prüfungsfehler werden jetzt protokolliert und als Nicht-Admin
  behandelt. Keine Admin-Hilfe bei unklarer Berechtigung.
- Test: fokussierter Adminfehlerpfad `3 passed`; Ruff und `git diff --check`
  gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c59b4ca4 fix: fail closed on help admin lookup`.
- Restart nach `20/20`: Service `active`, MainPID `4187238`,
  `ExecMainStatus=0`; keine neuen Startfehler.

**Aktueller Laufstand:** Nach dem Restart `1/20` Commits. Kein Push.
Restart nach 19 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `1/20` sichtbar.

### Account-Identitätslookup kapselt Backendfehler

- 2026-07-17: `process_identity_flows()` liess Fehler aus
  `resolve_or_create_account()` ungefangen. Ein Ausfall beim Identity-Store
  konnte jede eingehende Nachricht vor einer Antwort abbrechen.
- Der Eintrittspunkt meldet Account-Backendfehler kontrolliert und bleibt ohne
  Account-ID. Kein falscher Accountkontext und kein Bot-Loop-Abbruch.
- Test: fokussierter Identity-Fehlerpfad `4 passed`; Ruff und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `20521bab fix: contain account identity lookup failures`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem Restart `2/20`
Commits. Kein Push. Restart nach 18 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `3/20` sichtbar.

### Metadaten-Healthcheck kapselt unerwartete Vaultfehler

- 2026-07-17: `_account_metadata_health_lines` fing beim Lesen von Account-
  Index und Profil nur bekannte Store-/I/O-/Value-Fehler. Ein unerwarteter
  Vault- oder Wrapperfehler konnte den gesamten `/status`-Healthcheck abbrechen.
- Jeder betroffene Metadatensatz wird jetzt als `status=broken` gemeldet;
  weitere Metadaten und Accounts werden weiter geprüft. Kein falscher
  Gesundheitsstatus und kein Prozessabbruch.
- Test: `tests/test_version_notifications.py -k 'account_memory_index_health or account_metadata_health_lines'`
  `25 passed`; Ruff und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a800affa fix: contain unexpected metadata health failures`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem Restart `4/20`
Commits. Kein Push. Restart nach 16 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `5/20` sichtbar.

### Codex-History-Status lehnt kaputte Container ab

- 2026-07-17: Die Codex-History-Statuslogik behandelte ein Backend-Ergebnis
  wie `dict` oder `None` implizit als Iterable. Dadurch konnte eine kaputte
  Outbox als gueltige History mit falscher `total`-Zahl erscheinen.
- Der Read-Grenzpunkt akzeptiert jetzt nur Listen und meldet andere Formen als
  `status=unknown`. Keine falsche Health-Zusage und kein Status-Abbruch.
- Test: `tests/test_version_notifications.py -k 'codex_history_status'`
  `9 passed`; Ruff und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `f801cef2 fix: reject malformed codex history containers`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem Restart `6/20`
Commits. Kein Push. Restart nach 14 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `7/20` sichtbar.

### Optionale Kontext-Backends blockieren keine Antwort

- 2026-07-17: Working Memory und Bibliothekar-Kontext fingen nur `OSError`;
  semantische Account-Memory-Suche fing kein beliebiges Provider-/Adapter-
  Ergebnis. Unerwartete Backendfehler konnten den Hauptantwortpfad abbrechen.
- Alle drei optionalen Kontextquellen loggen unerwartete Fehler und fallen auf
  keinen Zusatzkontext bzw. lokale Memory-Suche zurück. Hauptantwort bleibt
  erreichbar; Qdrant-/Bibliothekar-Caches bleiben optional.
- Test: `tests/test_engine_memory_search.py` `5 passed`; Bibliothekar-
  Kontexttests `6 passed`; Ruff und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `c2735bc5 fix: fail open for optional context backends`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem Restart `8/20`
Commits. Kein Push. Restart nach 12 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `9/20` sichtbar.

### Audio-Anhang blockiert Antwort nicht bei Transkriptfehler

- 2026-07-17: `_build_attachment_context` fing Audio-Transkriptionsfehler
  nur für bekannte API-/Local-Exceptions. Ein unerwarteter Whisper- oder
  Wrapperfehler konnte die gesamte Nachricht vor der LLM-Antwort abbrechen.
- Jeder einzelne Audioanhang meldet jetzt kontrolliert fehlende Transkription
  und lässt weitere Anhänge sowie die normale Antwort weiterlaufen. Auch
  optionale TTS-Stilbeobachtung bleibt best-effort.
- Test: `tests/test_engine_identity_flows.py -k 'audio_attachment or transcription'`
  `7 passed`; Ruff und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `5a33c5ad fix: keep replies available on attachment transcription failure`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem Restart `10/20`
Commits. Kein Push. Restart nach 10 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `11/20` sichtbar.

### Emergency-Aktivierung prueft Cooldown-Persistenz

- 2026-07-17: `/Call_a_Teladi` ignorierte das Ergebnis von
  `_mark_teladi_emergency_used`. Bei fehlgeschlagener State-Persistenz wurde
  trotzdem der Bestätigungs-Prompt gesendet; ein späterer Versand konnte ohne
  gesicherten Cooldown erfolgen.
- Pending-Flow und Cooldown werden jetzt als Aktivierung behandelt. Bei
  fehlendem State-Schreiben gibt es nur den Fehlertext; Pending-State wird
  best-effort entfernt. Kein falsches Versandversprechen.
- Test: `tests/test_engine_identity_flows.py -k 'teladi'` `5 passed`; Ruff und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `3d43e455 fix: fail closed on emergency cooldown persistence`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem Restart `12/20`
Commits. Kein Push. Restart nach 8 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `13/20` sichtbar.

### Emergency-Dispatch prueft Pending-Cleanup

- 2026-07-17: Nach der Emergency-Bestaetigung wurde der Pending-Flow entfernt,
  ohne das Ergebnis zu pruefen. Bei Statefehler oder verschwundenem Pending-
  Datensatz konnte die Nachricht trotzdem an Teladi gesendet werden; Wieder-
  holungen und Status waren dann unklar.
- Dispatch erfolgt jetzt nur nach erfolgreichem Pending-Pop. Cancel meldet
  einen fehlenden Cooldown-Reset explizit; kein falsches Abbruchversprechen.
- Test: `tests/test_engine_identity_flows.py -k 'teladi'` `6 passed`; Ruff und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `8a05b17f fix: prevent emergency dispatch on state cleanup failure`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem Restart `14/20`
Commits. Kein Push. Restart nach 6 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `15/20` sichtbar.

### Memory-Reset verlangt persistierte Bestaetigung

- 2026-07-17: `/reset_memorys` entfernte Pending-State ungeprueft und loeste
  danach den destruktiven Reset aus. Bei State-Race/-Fehler konnte ein
  bestaetigender Text ohne noch vorhandenen Pending-Flow Memory loeschen;
  Setup-/Lookupfehler konnten zudem in den allgemeinen Fehlerpfad fallen.
- Lookup, Pending-Entfernung und Initial-Setup werden jetzt fail-closed
  behandelt. Der destruktive Reset startet nur nach tatsaechlich entferntem
  Bestaetigungs-State; kein falscher Erfolg.
- Test: `tests/test_engine_identity_flows.py -k 'memory_reset'` `11 passed`;
  Ruff und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `33636335 fix: require persisted memory reset confirmation`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem Restart `16/20`
Commits. Kein Push. Restart nach 4 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `17/20` sichtbar.

### YouTube-Link-Follow-up verlangt persistierten Pending-State

- 2026-07-17: `/youtube_transcript` ohne URL meldete den Follow-up-Prompt auch
  dann, wenn `set_pending_flow()` scheiterte. Der nachfolgende Link konnte
  dadurch nicht sicher zugeordnet werden und lief in einen anderen Pfad.
- Der Prompt wird nur noch nach erfolgreichem State-Setup gesendet; bei
  Fehlern kommt ein kontrollierter Vorbereitungsfehler. Kein falsches
  Transkriptversprechen.
- Test: `tests/test_engine_identity_flows.py -k 'youtube_transcript_requires_link or youtube_transcript_reports_pending_state_failure'`
  `2 passed`; Ruff und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `f7cd1d85 fix: require persisted youtube link followup state`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem Restart `18/20`
Commits. Kein Push. Restart nach 2 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `19/20` sichtbar.

### YouTube-Follow-ups validieren State-Cleanup vor dem Job

- 2026-07-17: Link- und Options-Follow-ups entfernten Pending-State ohne
  Rueckgabewert-/Ausnahmepruefung. Bei Statefehler lief Transkription oder
  lokaler Job trotzdem an; kaputte Follow-ups blieben zudem wiederholbar.
- Lookup und Pop beider YouTube-Follow-up-Flows sind jetzt fail-closed. Nur
  nach bestaetigtem State-Cleanup startet Transkription bzw. Local-Job.
- Test: `tests/test_engine_identity_flows.py -k 'youtube_transcript'`
  `19 passed`; Ruff und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `ab3f0437 fix: require youtube followup state cleanup`.
- Restart nach `20/20`: `teebotus.service active`, MainPID `780895`,
  `ExecMainStatus=0`, ActiveEnter `2026-07-17 19:45:50 CEST`.

**Aktueller Laufstand:** Nach dem Restart `0/20` Commits. Kein Push.
Restart nach 20 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `1/20` sichtbar.

### YouTube-Background-Submit behauptet keinen falschen Start

- 2026-07-17: `_youtube_run_local_transcript_actions` meldete „gestartet“,
  obwohl `youtube_job_runner.submit()` einen Executor-/Shutdown-Fehler werfen
  konnte. Nutzer bekamen dadurch keinen klaren Fehler und keinen Job.
- Submit ist jetzt geschützt; bei Fehler gibt es eine kontrollierte
  Startfehlerantwort. Erfolgreiche Jobs behalten bisheriges Verhalten.
- Test: `tests/test_engine_identity_flows.py -k 'youtube_background or background_submission'`
  `3 passed`; Ruff und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e001dd1e fix: report youtube job submission failures`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem Restart `2/20`
Commits. Kein Push. Restart nach 18 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `3/20` sichtbar.

### Login kapselt Rückgabe- und Notificationfehler

- 2026-07-17: Primäres Login vertraute blind auf `result["account_id"]` und
  liess Fehler aus `record_link_notification()` nach erfolgreicher
  Verknüpfung eskalieren. Ein malformed Backendresultat oder kaputter
  Runtime-State konnte den Login-Flow abbrechen.
- Ungültige Backendresultate melden kontrollierten Loginfehler. Optionale
  Link-Benachrichtigungen werden einzeln protokolliert und übersprungen;
  erfolgreiche Account-Verknüpfung bleibt erfolgreich. Cross-Instance-Resultate
  sind ebenfalls abgesichert.
- Test: fokussierter Loginpfad `4 passed`; Ruff und `git diff --check` gruen.
  Kein Provider/API-Aufruf.
- Code-Commit: `82bbb004 fix: contain login result and notification failures`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem Restart `4/20`
Commits. Kein Push. Restart nach 16 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `5/20` sichtbar.

### WTF-Link-Notification-State fail-closed

- 2026-07-17: `_handle_wtf()` liess Notification-Lookup, Listing und Cleanup
  ungefangen. Defekter Runtime-State konnte `WTF?` ohne Antwort abbrechen oder
  einen falschen „keine Verknüpfung“-No-op melden.
- Sicherheitslookup und Aufräumen melden jetzt kontrollierten Fehler. Eine
  unklare State-Lage autorisiert keine Rotation und behauptet keine Änderung.
- Test: fokussierter WTF-Statepfad `5 passed`; Ruff und `git diff --check`
  gruen. Kein Provider/API-Aufruf.
- Code-Commit: `55de7953 fix: contain WTF notification state failures`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem Restart `6/20`
Commits. Kein Push. Restart nach 14 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `7/20` sichtbar.

### Status-Auth-Identity-Lookup fail-closed

- 2026-07-17: `evaluate_status_auth_gate()` las die Identity-Zuordnung
  geschützter Instanzen ungefangen. Ein kaputter Auth-State konnte den
  Logger-Flow vor der absichtlichen Stille abbrechen.
- Identity-Lesefehler liefern jetzt `status_auth_store_error`: kein Account
  wird autorisiert, keine Nachricht wird freigeschaltet, kein Bot-Loop-Abbruch.
- Test: Status-Auth-Fokus `12 passed`; Ruff und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `71cfaa2e fix: contain status auth identity lookup failures`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem Restart `8/20`
Commits. Kein Push. Restart nach 12 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `9/20` sichtbar.

### Admin-Flow-State am Dispatcher gekapselt

- 2026-07-17: `_admin_membership_actions()` griff mehrfach auf persistierten
  Runtime-State zu. Fehler bei Pending-Flows konnten nach erfolgreichem
  Accountlookup jede Nachricht abbrechen.
- Die Dispatcher-Grenze fängt unerwartete Admin-Statefehler, meldet sie
  kontrolliert und autorisiert bei unklarer Lage nichts. Normale Verarbeitung
  bricht nicht mehr aus.
- Test: fokussierter Admin-Statepfad `14 passed`; Ruff und `git diff --check`
  gruen. Kein Provider/API-Aufruf.
- Code-Commit: `8e91672b fix: contain admin flow state failures`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem Restart `10/20`
Commits. Kein Push. Restart nach 10 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `11/20` sichtbar.

### Globaler Message-Safety-Rand

- 2026-07-17: `process_result()` liess unerwartete Dispatcher-, Observation-
  und Auth-Gatefehler aus dem obersten Runtime-Eintrittspunkt laufen.
- Auth-Gatefehler bleiben stumm und fail-closed. Unerwartete Fehler in normaler
  Nachrichtenverarbeitung werden geloggt und als kontrollierte Antwort
  zurückgegeben; der Bot-Loop läuft weiter.
- Test: fokussierter Safety-Rand `15 passed`; Ruff und `git diff --check`
  gruen. Kein Provider/API-Aufruf.
- Code-Commit: `004963e1 fix: add runtime message safety boundary`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem Restart `12/20`
Commits. Kein Push. Restart nach 8 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `13/20` sichtbar.

### Stateful-LLM-Antwort bleibt bei lokalem Statefehler erhalten

- 2026-07-17: `_previous_response_id_for_client()` und die persistente
  Speicherung neuer Response-IDs konnten bei Runtime-Statefehlern die gültige
  Providerantwort bis zum globalen Safety-Rand verschlucken.
- Unlesbarer State startet Anfrage ohne Vor-ID. Schreiben der neuen Vor-ID ist
  best-effort und wird geloggt; Antwort bleibt sichtbar. Stateful-Kontext kann
  dadurch einmalig verloren gehen, Bot bleibt aber nutzbar.
- Test: fokussierter LLM-Statepfad `3 passed`; Ruff und `git diff --check`
  gruen. Kein Provider/API-Aufruf.
- Code-Commit: `9bb1e8e3 fix: preserve replies when local llm state fails`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem Restart `14/20`
Commits. Kein Push. Restart nach 6 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `15/20` sichtbar.

### Stale-LLM-State-Recovery bleibt retryfähig

- 2026-07-17: `_create_reply_with_state_recovery()` brach bei einem Fehler
  von `reset_state()` vor dem vorgesehenen Retry ohne alte Response-ID ab.
- Cleanup ist jetzt best-effort. Auch bei lokalem Statefehler wird der
  Provider einmal ohne stale Vor-ID gefragt; Cleanupfehler werden geloggt.
- Test: fokussierter Recoverypfad `3 passed`; Ruff und `git diff --check`
  gruen. Kein Provider/API-Aufruf.
- Code-Commit: `8acdd4c0 fix: retry stale llm state cleanup failures`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem Restart `16/20`
Commits. Kein Push. Restart nach 4 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `17/20` sichtbar.

### YouTube-LLM-Antwort bleibt bei Statefehler erhalten

- 2026-07-17: Der YouTube-LLM-Pfad speicherte neue Response-IDs ungefangen.
  Ein lokaler Runtime-Statefehler konnte fertige Transkriptanalyse bis zum
  globalen Safety-Rand verschlucken.
- Response-State wird jetzt best-effort gespeichert und bei Fehler geloggt;
  die fertige YouTube-Antwort bleibt sichtbar.
- Test: fokussierter YouTube-Statepfad `3 passed`; Ruff und `git diff --check`
  gruen. Kein Provider/API-Aufruf.
- Code-Commit: `78343c38 fix: preserve youtube replies on state failure`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem Restart `18/20`
Commits. Kein Push. Restart nach 2 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `19/20` sichtbar.

### LLM-Reset behauptet keinen falschen Erfolg

- 2026-07-17: `/reset` meldete `llm_reset` auch dann, wenn
  `reset_previous_response_id()` im lokalen Runtime-State fehlschlug.
- Resetfehler werden jetzt geloggt und kontrolliert gemeldet. Kein falscher
  „Kontext gelöscht“-Erfolg; der Bot-Loop bleibt aktiv.
- Test: fokussierter Resetpfad `3 passed`; Ruff und `git diff --check` gruen.
  Kein Provider/API-Aufruf.
- Code-Commit: `42f1c849 fix: report llm reset state failures`.
- Restart nach `20/20`: Service `active`, MainPID `248383`,
  `ExecMainStatus=0`; keine neuen Startfehler.

**Aktueller Laufstand:** Nach dem Restart `1/20` Commits. Kein Push.
Restart nach 19 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `1/20` sichtbar.

### WTF-Notification bleibt bei fehlgeschlagener Mutation retryfähig

- 2026-07-17: `_handle_wtf()` entfernte Link-Notifications vor Rotation und
  Unlink. Nach einem Mutationsfehler war erneuter Sicherheitsretry unmöglich.
  Zusätzlich wurde ein `None`-Ergebnis von `unlink_identity_if_linked_to()`
  ignoriert.
- Lookup nutzt jetzt nicht-destruktives Listing. Notification-Cleanup erfolgt
  erst nach erfolgreicher Mutation; `None` gilt als fehlgeschlagene Mutation.
  Cleanupfehler melden das neue Secret trotzdem, statt Security-Erfolg zu
  verschlucken.
- Test: fokussierter WTF-Pfad `7 passed`; Ruff und `git diff --check` gruen.
  Kein Provider/API-Aufruf.
- Code-Commit: `55a2afc7 fix: preserve WTF notifications across failed mutations`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem Restart `2/20`
Commits. Kein Push. Restart nach 18 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `3/20` sichtbar.

### `/status` bleibt bei Accountlookup-Fehler verfügbar

- 2026-07-17: `_resolve_status_account_id()` fing unerwartete Fehler aus dem
  Account-Store nicht. Ein SQL-/Vault-Fehler konnte den gesamten Statusdialog
  abbrechen.
- Status-Accountlookup fail-safe: Bei unbekannter Zuordnung zeigt `/status`
  weiterhin System-/LLM-/Healthdaten und markiert Nutzermemory als
  „Account nicht zugeordnet“.
- Test: fokussierter Statuspfad `39 passed`; Ruff und `git diff --check`
  gruen. Kein Provider/API-Aufruf.
- Code-Commit: `6fc31298 fix: keep status available on account lookup failure`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem Restart `4/20`
Commits. Kein Push. Restart nach 16 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `5/20` sichtbar.

### Status-Health-Backendreads diagnostizieren unerwartete Fehler

- 2026-07-17: Status-Accountverzeichnis und Proactive-Health fingen nur
  bekannte Store-/OS-Fehler. Unerwartete Backendfehler konnten den gesamten
  `/status`-Aufbau abbrechen.
- Beide Helfer liefern jetzt ihre bestehende Fehlerdiagnose auch bei
  unerwarteten Exceptions. Andere Statusbereiche bleiben sichtbar.
- Test: fokussierter Statuspfad `41 passed`; Ruff und `git diff --check`
  gruen. Kein Provider/API-Aufruf.
- Code-Commit: `4f243212 fix: harden status health backend reads`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem Restart `6/20`
Commits. Kein Push. Restart nach 14 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `7/20` sichtbar.

### Memory-Backend-Status diagnostiziert Auflösungsfehler

- 2026-07-17: `account_memory_payload_size()` und
  `memory_encryption_status()` fingen unerwartete Exceptions bei der
  Backendauflösung nicht. Ein kaputter SQL-/Memory-Adapter konnte `/status`
  abbrechen.
- Backendauflösung liefert jetzt bei unbekanntem Fehler die vorhandenen
  „nicht verfügbar“-Diagnosen. Keine falsche Memorygröße oder Verschlüsselung.
- Test: fokussierter Statuspfad `42 passed`; Ruff und `git diff --check`
  gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a5f67d49 fix: diagnose memory backend status failures`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem Restart `8/20`
Commits. Kein Push. Restart nach 12 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `9/20` sichtbar.

### Status-Memory-Lock bleibt diagnostisch

- 2026-07-17: Status-Senderlookup und Erzeugung des Account-Memory-Locks
  fingen unerwartete Fehler nicht. Ein defekter Lock-/Storeadapter konnte
  Memorystatus und damit `/status` abbrechen.
- Beide Punkte liefern bei Fehlern `None` bzw. bestehende Nichtverfügbar-
  Diagnose. Keine falsche Memorygröße.
- Test: fokussierter Statuspfad `43 passed`; Ruff und `git diff --check`
  gruen. Kein Provider/API-Aufruf.
- Code-Commit: `f4565838 fix: contain status memory lock failures`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem Restart `10/20`
Commits. Kein Push. Restart nach 10 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `11/20` sichtbar.

### Malformed-WTF-Notification rotiert kein Secret

- 2026-07-17: Eine vorhandene Link-Notification ohne `new_identity_key` fiel
  in `_handle_wtf()` in den normalen Secret-Rotationszweig. Wiederholtes
  `WTF?` konnte dadurch Secret ohne verifizierte Zielidentität rotieren.
- Malformed Notifications werden jetzt protokolliert und fail-closed
  abgewiesen. Keine Rotation ohne Zielidentität.
- Test: fokussierter WTF-Pfad `8 passed`; Ruff und `git diff --check` gruen.
  Kein Provider/API-Aufruf.
- Code-Commit: `9a01b786 fix: reject malformed WTF notifications`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem Restart `12/20`
Commits. Kein Push. Restart nach 8 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `13/20` sichtbar.

### Account-Trennung prüft erfolgreiche Mutation

- 2026-07-17: Direkte und bestätigte Kanaltrennung behandelten
  `unlink_identity() == None` als Erfolg. Race-/Backendzustand konnte dadurch
  falsche Trennbestätigung liefern.
- Beide Pfade verlangen jetzt echte Mutation. Fehlendes Ergebnis meldet
  kontrollierten Fehler; bestätigter Account-Edit bleibt retryfähig.
- Test: fokussierter Kanaltrennpfad `4 passed`; Ruff und `git diff --check`
  gruen. Kein Provider/API-Aufruf.
- Code-Commit: `aea978b0 fix: reject unsuccessful account unlink mutations`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem Restart `14/20`
Commits. Kein Push. Restart nach 6 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `15/20` sichtbar.

### WTF-Teilmutation gibt rotiertes Secret aus

- 2026-07-17: WTF rotierte Secret vor Unlink. Bei anschließendem Unlinkfehler
  wurde nur ein generischer Fehler gemeldet; vertrauenswürdiger Absender konnte
  neues Secret nicht erhalten.
- Rotation und Unlink werden getrennt behandelt. Nach erfolgter Rotation wird
  neues Secret kontrolliert ausgegeben, Verknüpfungsstatus als unklar markiert;
  Notification bleibt für Retry erhalten. Kein falscher Vollzug.
- Test: fokussierter WTF-Pfad `8 passed`; Ruff und `git diff --check` gruen.
  Kein Provider/API-Aufruf.
- Code-Commit: `f02d3548 fix: expose rotated secret after WTF partial failure`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem Restart `16/20`
Commits. Kein Push. Restart nach 4 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `17/20` sichtbar.

### Account-Edit-Teilmutationen bleiben sichtbar

- 2026-07-17: `/account_edit` konnte Secret rotieren oder Kanal trennen und
  danach bei `pop_pending_flow()` scheitern. Globaler Safety-Rand meldete dann
  keinen erfolgten Change bzw. verschluckte neues Secret.
- Post-Mutation-Cleanup ist jetzt best-effort. Neues Secret bzw. erfolgte
  Trennung werden mit Hinweis auf offenen internen Status ausgegeben.
- Test: fokussierter Account-Edit-Pfad `7 passed`; Ruff und `git diff --check`
  gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c54d34f7 fix: preserve account edit mutations on cleanup failure`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem Restart `18/20`
Commits. Kein Push. Restart nach 2 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `19/20` sichtbar.

### Account-Edit-Setup kapselt Statefehler

- 2026-07-17: `/account_edit` und Start der Unlink-Bestätigung setzten
  Pending-State ungefangen. Runtime-Statefehler konnten dadurch nur globalen
  Fehlertext liefern oder den Flowzustand unklar lassen.
- Beide Setup-Punkte melden kontrolliert und bewahren bestehenden Flow. Kein
  falscher Start und keine unklare Bestätigung.
- Test: fokussierter Account-Edit-Setup-Pfad `5 passed`; Ruff und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `56360b99 fix: contain account edit flow setup failures`.
- Restart nach `20/20`: Service `active`, MainPID `399677`,
  `ExecMainStatus=0`; keine neuen Startfehler.

**Aktueller Laufstand:** Nach dem Restart `1/20` Commits. Kein Push.
Restart nach 19 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `1/20` sichtbar.

### Admin-Status kapselt Account-Verzeichnisfehler

- 2026-07-17: `_account_dir_exists` liess unerwartete Dateisystem- und
  Store-Ausnahmen nach oben laufen. Admin-Status und Summary-Versand konnten
  dadurch bei einem einzelnen kaputten Account-Backend komplett abbrechen.
- Der Verzeichnischeck fail-closed jetzt auf `False`, loggt den Fehlertyp und
  laesst Route-/Statusdiagnose fuer weitere Accounts weiterlaufen. Kein
  Account wird dadurch autorisiert oder neu angelegt.
- Test: `tests/test_runtime_admin_accounts.py` `34 passed`; Ruff und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `87af7cdc fix: contain admin account directory errors`.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`1/20` Commits. Kein Push. Restart nach 19 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `2/20` voll.

### Engine isoliert Beobachtungs-Hook-Fehler

- 2026-07-17: Activity-Profil, Wetterkontext und TTS-Dialektbeobachtung
  fingen nur erwartete Store-/I/O-/Value-Fehler. Unerwartete SQL-, Secret-
  oder Wrapper-Ausnahmen konnten normale Nachrichten vor ihrer Antwort
  abbrechen.
- Alle drei Beobachtungs-Hooks loggen unerwartete Fehler jetzt und laufen
  fail-open weiter. Beobachtungsdaten koennen fehlen; Nutzerantwort,
  Reminder- und LLM-Pfad bleiben erreichbar.
- Test: `tests/test_engine_identity_flows.py` `198 passed`; Ruff und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `5c73902a fix: isolate observation hook failures`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem letzten Restart
`3/20` Commits. Kein Push. Restart nach 17 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `4/20` voll.

### Datenschutz-Bestaetigung faengt Persistenzfehler ab

- 2026-07-17: `confirm_privacy` fing im Engine-Pfad nur bekannte Store-/I/O-
  Fehler. Ein unerwarteter Backendfehler konnte als unbehandelte Nachricht
  in den LLM-Pfad fallen; Nutzer erhielt weder sichere Bestaetigung noch
  klare Fehlermeldung.
- Jeder Persistenzfehler wird jetzt geloggt und als explizite
  Nicht-gespeichert-Antwort behandelt. Keine falsche Zustimmung, kein
  LLM-Fallback; erneuter Versuch bleibt moeglich.
- Test: `tests/test_engine_identity_flows.py` `199 passed`; Ruff und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `78b364b8 fix: report privacy confirmation persistence errors`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem letzten Restart
`5/20` Commits. Kein Push. Restart nach 15 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `6/20` voll.

### Memory-Reset kapselt unerwartete Backendfehler

- 2026-07-17: `/reset_memorys` fing beim Entfernen von semantischem Index
  und strukturiertem Memory nur bekannte Fehler. Unerwartete SQL-, Qdrant-,
  Secret- oder Wrapper-Ausnahmen konnten den Engine-Loop abbrechen.
- Der Resetpfad loggt jetzt jeden normalen Backendfehler und liefert die
  bekannte Reset-Fehlermeldung. Kein falscher Erfolg; erneuter Versuch bleibt
  moeglich. Ein bereits geloeschter Nebenindex bleibt rebuildbar.
- Test: `tests/test_engine_identity_flows.py` `200 passed`; Ruff und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `aded8c34 fix: contain memory reset backend failures`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem letzten Restart
`7/20` Commits. Kein Push. Restart nach 13 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `8/20` voll.

### Cross-Instance-Login isoliert kaputte Quellen

- 2026-07-17: Quellinstanz-Discovery und Secret-Verifikation fingen nur
  bekannte Store-/I/O-/Value-Fehler. Ein defektes SQL-, Secret- oder Wrapper-
  Backend konnte `/login` fuer alle weiteren Quellen abbrechen.
- Discoveryfehler werden jetzt fail-closed behandelt; einzelne kaputte
  Quellinstanzen werden geloggt und uebersprungen. Zielinstanz antwortet
  kontrolliert mit Loginfehler statt Prozessabbruch oder falschem Link.
- Test: `tests/test_engine_identity_flows.py` `201 passed`; Ruff und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `6239525b fix: isolate cross instance login failures`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem letzten Restart
`9/20` Commits. Kein Push. Restart nach 11 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `10/20` voll.

### Telegram-Poller toleriert Minimal-Runtime-Contexts

- 2026-07-17: Dispatch-Journal-Replay las `instance_name` und `adapter_slot`
  direkt aus `runtime_context`. Test-/Kompatibilitaets-Contexts ohne diese
  Felder liessen Poller nach einem Updatefehler vor Offset-/Journalpflege
  abbrechen.
- Retry-Key-Bildung nutzt jetzt sichere Defaults (`""`, Slot `1`). Voll
  aufgebaute Runtime-Contexts behalten ihre Werte; fehlgeschlagene Updates
  werden wiederholbar verarbeitet.
- Test: `tests/test_bot.py` `202 passed`, 17 Subtests; Ruff und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `ac3c43a5 fix: tolerate minimal telegram runtime contexts`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem letzten Restart
`11/20` Commits. Kein Push. Restart nach 9 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `12/20` voll.

### Start-Flow kapselt Privacy-Button-Lesefehler

- 2026-07-17: `/start` las den Privacy-State fuer Legal-Buttons nur mit
  bekanntem Fehlerfang. Unerwartete SQL-, Secret- oder Wrapper-Ausnahmen
  konnten die normale Startantwort abbrechen.
- Der optionale Button-Check fail-closed jetzt auf keine Buttons und loggt
  den Fehler. Startantwort bleibt erreichbar; es wird keine Zustimmung
  behauptet oder gespeichert.
- Test: `tests/test_engine_identity_flows.py` `202 passed`; Ruff und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `86459ca7 fix: isolate start privacy button lookup`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem letzten Restart
`13/20` Commits. Kein Push. Restart nach 7 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `14/20` voll.

### Bot-Alias-Discovery kapselt Memory-Backendfehler

- 2026-07-17: Alias-Lookup aus Agent-State, Memory-Index und Entries fing
  unerwartete Backendfehler nicht. Gruppenrouting und Adress-Erkennung
  konnten dadurch vor der eigentlichen Nachricht abbrechen.
- Jeder optionale Alias-Read fail-opens jetzt auf bekannte Namen ohne neue
  Aliasdaten; Fehler werden geloggt. Keine falsche Adressierung, keine
  Antwortunterdrueckung durch kaputten Memory-Read.
- Test: `tests/test_engine_identity_flows.py` `203 passed`; Ruff und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a89bc697 fix: isolate bot alias lookup failures`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem letzten Restart
`15/20` Commits. Kein Push. Restart nach 5 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `16/20` voll.

### Voice-Einstellungsbefehle kapseln Backendfehler

- 2026-07-17: `/voicemodel` und `/mimic_voice` fingen nur bekannte
  Store-/I/O-/Value-Fehler. Unerwartete SQL-, Secret- oder Wrapper-
  Ausnahmen konnten Command-Verarbeitung und Bot-Loop abbrechen.
- Beide Commands loggen unerwartete Fehler jetzt und liefern die jeweilige
  Speicherfehlerantwort. Keine falsche Einstellung und kein Voice-API-Aufruf.
- Test: `tests/test_engine_identity_flows.py` `204 passed`; Ruff und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `cb6a6f09 fix: contain voice preference backend failures`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem letzten Restart
`17/20` Commits. Kein Push. Restart nach 3 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `18/20` voll.

### Account-Export kapselt unerwartete Backendfehler

- 2026-07-17: `/export` fing nur bekannte Export-/Store-/I/O-Fehler. Ein
  unerwarteter SQL-, Secret- oder Wrapperfehler konnte Command-Verarbeitung
  und Bot-Loop abbrechen.
- Export-Backendfehler werden jetzt geloggt und als klare Exportfehlerantwort
  behandelt. Kein falscher Dateiversand und kein Prozessabbruch.
- Test: `tests/test_engine_identity_flows.py` `205 passed`; Ruff und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `525a62ef fix: contain account export backend failures`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem letzten Restart
`19/20` Commits. Kein Push. Restart nach einem weiteren Plan-Commit.

### Zyklusabschluss

Dieser Plan-Commit macht Zyklus `20/20` voll. Kein Push. Dienst-Neustart jetzt;
danach neuer Zyklus bei `0/20`. Naechster Push bleibt erst bei 100 Commits.

**Aktueller Laufstand:** Nach diesem Plan-Commit seit dem letzten Restart
`7/20` Commits. Kein Push. Restart nach 13 weiteren Commits. Naechster Push
bleibt erst bei 100 Commits.

### Status-Healthcheck kapselt unerwartete Backendfehler

- 2026-07-17: Der Account-Memory-Healthcheck fing bei Verzeichnisauflistung,
  Datenbank-Account-Discovery, Profil- und Indexpruefung nur bekannte Fehler.
  Unerwartete SQL-, Secret-, Wrapper- oder defekte Backend-Ausnahmen konnten
  `/status` vor dem Bericht abbrechen.
- Alle vier Healthcheck-Grenzen melden kaputte Teilbereiche kontrolliert und
  pruefen weitere Accounts weiter. Auch die Fallback-Diagnose bleibt bei einem
  unvollstaendigen Backend auskunftsfaehig. Keine falsche Health-Zusage.
- Test: `tests/test_engine_identity_flows.py -k 'status or memory_health'`
  `46 passed`; Ruff und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `00f129d8 fix: contain unexpected status health failures`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem Restart `2/20`
Commits. Kein Push. Restart nach 18 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `3/20` sichtbar.

### RouteTo-Pending-State fail-closed behandeln

- 2026-07-17: `/RouteTo` las, setzte und entfernte seinen Pending-State ohne
  Fehler- oder Rueckgabewertpruefung. SQL-/Runtime-State-Fehler konnten den
  Engine-Loop abbrechen, einen falschen Bereit-Prompt senden oder trotz
  fehlender Zustandsloeschung direkt routen.
- Lesen, Setzen, Abbrechen und einmaliger Verbrauch sind jetzt geschuetzt.
  Unbekannter oder nicht entfernbarer Zustand ergibt eine kontrollierte
  RouteTo-Fehlermeldung; Backend-LLM wird dann nicht aufgerufen.
- Test: `tests/test_route_to_llm_command.py` `13 passed`; Ruff und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `ef8074df fix: contain route pending state failures`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem Restart `4/20`
Commits. Kein Push. Restart nach 16 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `5/20` sichtbar.

### Admin-Authentifizierung verlangt intakten Pending-State

- 2026-07-17: `/admin yes` meldete den Secret-Prompt auch bei fehlgeschlagenem
  State-Setup. Bei verschwundenem oder nicht entfernbarem Pending-State konnte
  ein Secret zudem noch autorisieren oder `/cancel` einen falschen Erfolg melden.
- Admin-Pending-State wird beim Setzen, Abbrechen und einmaligen Verbrauch
  geprüft. Bei Fehler oder fehlendem Datensatz: keine Autorisierung, kein
  falscher Cancel-/Deaktiviert-Erfolg.
- Test: `tests/test_engine_identity_flows.py -k 'admin'` `22 passed`; Ruff und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e9bf6e98 fix: fail closed on admin auth state failures`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem Restart `6/20`
Commits. Kein Push. Restart nach 14 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `7/20` sichtbar.

### Account-Edit verlangt validierten Pending-State

- 2026-07-17: `/account_edit` behandelte `get_pending_flow()`-Fehler als
  allgemeinen Loopfehler. Cancel und unbekannte Schritte konnten bei
  `pop_pending_flow() == None` trotzdem Erfolg melden; Rotation und Unlink
  erkannten verschwundenen Cleanup-State nicht.
- Lookup, Cancel und Reset sind jetzt fail-closed. Rotation und Unlink
  bleiben nach erfolgreicher Account-Aktion sichtbar, melden fehlenden
  Cleanup-State aber ausdrücklich. Kein falscher State-Erfolg.
- Test: `tests/test_engine_identity_flows.py -k 'account_edit or channel_unlink'`
  `14 passed`; Ruff und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `4d606fb8 fix: validate account edit state transitions`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem Restart `8/20`
Commits. Kein Push. Restart nach 12 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `9/20` sichtbar.

### Emergency-State verlangt sichere Cancellation

- 2026-07-17: `Call_a_Teladi` fing Pending-Lesefehler nicht ab und wertete
  `pop_pending_flow() == None` beim `/cancel` als Erfolg. Ein unerwarteter
  Cooldown-Fehler konnte ebenfalls in den generischen Loopfehler fallen.
- Emergency-Pending-State und Cooldown-Cleanup werden jetzt getrennt geprüft.
  Bei unklarem Zustand kein Versand und keine falsche Abbruchmeldung.
- Test: `tests/test_engine_identity_flows.py -k 'teladi'` `9 passed`; Ruff und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `8f35800a fix: fail closed on emergency state failures`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem Restart `10/20`
Commits. Kein Push. Restart nach 10 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `11/20` sichtbar.

### Memory-Reset verlangt validierten Cleanup-State

- 2026-07-17: `/reset_memorys` prüfte beim Bestätigen bereits den Pop, aber
  Cancel, verbotene globale Ziele und sonstiger Text ignorierten noch
  `pop=None` bzw. Exceptions. Dadurch waren falsche Cancel-/Schutzantworten
  oder ein Fall-through in den LLM-Pfad möglich.
- Jeder Pending-State-Verbrauch ist jetzt fail-closed. Bei unklarem Cleanup
  kommt die Reset-Fehlermeldung; kein falscher Cancel-Erfolg und kein
  Weiterreichen an LLM.
- Test: `tests/test_engine_identity_flows.py -k 'memory_reset'` `14 passed`;
  Ruff und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `ea94dc18 fix: validate memory reset state cleanup`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem Restart `12/20`
Commits. Kein Push. Restart nach 8 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `13/20` sichtbar.

### YouTube-Options-State validiert fehlende URL beim Cleanup

- 2026-07-17: Der korrupte `youtube_options`-Zweig mit fehlender URL rief
  `pop_pending_flow()` ungefangen auf und meldete danach trotzdem einen
  Transkriptfehler. State-Fehler konnten den Engine-Loop abbrechen.
- Cleanup wird jetzt geprüft. Bei Exception oder verschwundenem State kommt
  der kontrollierte Pending-State-Fehler; kein falsches Ergebnis und kein Job.
- Test: `tests/test_engine_identity_flows.py -k 'youtube_transcript'`
  `21 passed`; Ruff und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `f29c42ab fix: contain malformed youtube option state`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem Restart `14/20`
Commits. Kein Push. Restart nach 6 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `15/20` sichtbar.

### Emergency-Dispatch verifiziert persistierten Cooldown

- 2026-07-17: Wenn Cooldown-Persistenz und anschließendes Pending-Cleanup
  gleichzeitig scheiterten, blieb ein Emergency-Pending-State liegen. Der
  nächste Text konnte ohne nachgewiesenes `used_at` an Teladi gehen.
- Vor Emergency-Dispatch wird jetzt ein persistierter Cooldown-Zeitpunkt
  verlangt. Fehlender oder unlesbarer Cooldown blockiert den Versand.
- Test: `tests/test_engine_identity_flows.py -k 'teladi'` `10 passed`; Ruff und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `163ae191 fix: verify emergency cooldown before dispatch`.

**Aktueller Laufstand:** Nach diesem Code-Commit seit dem Restart `16/20`
Commits. Kein Push. Restart nach 4 weiteren Commits.

**Plan-Commit:** Dieser Plan-Commit macht den neuen Zyklus `17/20` sichtbar.

### Optionaler Wetterkontext darf LLM-Antwort nicht blockieren

- 2026-07-17: `weather_context_text()` wurde in Freitext- und YouTube-LLM-Pfad
  direkt gelesen. Ein defekter Agent-State konnte dadurch eine ansonsten
  erfolgreiche Antwort in den generischen Engine-Fehler umleiten.
- Beide Pfade nutzen jetzt einen best-effort Wrapper. Wetter bleibt optional;
  bei Lesefehler läuft die Antwort ohne Wetterkontext weiter.
- Test: `tests/test_engine_identity_flows.py -k
  'unexpected_weather_context_failure or youtube_transcript_natural_request_uses_llm_pipeline'`
  `3 passed`; Ruff und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `abf21c3f fix: keep llm replies on weather context failure`.

### Key-Ring-Metadaten dürfen Stateful-LLM nicht blockieren

- 2026-07-17: Die Ermittlung des Key-Fingerprints rief
  `api_key_ring.ordered_keys()` ungefangen auf. Ein defekter Metadatenzugriff
  konnte dadurch vor oder nach dem Provideraufruf die Antwort verwerfen.
- Key-Ring-Inspektion ist jetzt best-effort. Fehlende Metadaten verlieren nur
  den State-Scope; die LLM-Antwort bleibt auslieferbar.
- Test: `tests/test_engine_identity_flows.py -k
  'unexpected_key_ring_scope_failure or unexpected_local_response_state_failure or
  engine_persists_previous_response_id_for_stateful_gemini_alias'` `4 passed`;
  Ruff und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `ceb0d5a5 fix: keep llm replies on key ring metadata failure`.

**Aktueller Laufstand:** Nach den beiden Code-Commits seit dem Restart `19/20`
Commits. Dieser Plan-Commit macht `20/20` sichtbar. Kein Push. Restart jetzt.

### Engine-Lauf: optionale Fehler dürfen Hauptpfade nicht brechen

- 2026-07-17: Neun weitere Guards geschlossen: Admin-Pending-State,
  Emergency-Cooldown-Lesen, YouTube-Optionsklassifizierung, dynamische
  Instructions, `/codex`, `/status`, unerwartete LLM-Adapterfehler,
  Response-Metadaten und Built-in-Reply-Matcher.
- Prinzip: Sicherheitsaktionen fail-closed; optionale Kontext-, Diagnose- und
  Adapterpfade liefern kontrollierte Antworten oder erlauben sicheren Fallback.
  Ein kaputter Nebenpfad darf keine fertige LLM-/Transkriptantwort verwerfen.
- Tests: Admin `22`, Emergency `11`, YouTube-Optionen `3`, Codex `4`, Status
  `7`, LLM-/State-Guards `5`, Handler-/Fallback-Guards `3` jeweils gruen;
  Ruff und `git diff --check` gruen. Kein echter Provider/API-Aufruf.
- Code-Commits: `7a78c9f9`, `1d672b2d`, `3d821625`, `23e3f903`, `45c1d0df`,
  `fe1756ce`, `61e9840e`, `6826762d`, `d83ace28`.

**Aktueller Laufstand:** Seit dem Restart `9/20` Code-Commits. Dieser
Plan-Commit zählt als `10/20`. Kein Push. Restart jetzt.

### Reply-Routing: Gruppen-Replies müssen Bot-Ziel erkennen

- 2026-07-17: Matrix- und Signal-Gruppen-Replies wurden vor der
  Adressierungsprüfung nicht als Bot-Replies markiert. Matrix lud zwar den
  Quote-Text, wertete den Zielsender aber nicht aus; Signal ignorierte Quote-
  Autoren vollständig. Solche Antworten wurden trotz Reply auf Bot-Nachricht
  verworfen.
- Matrix prüft den referenzierten Event-Sender gegen `matrix_user_id` und lädt
  Reply-Metadaten vor dem Gruppen-Ignore. Signal prüft Quote-Autor,
  Telefonnummer und UUID gegen konfigurierte Bot-Identitäten. Fremde Quotes
  bleiben unbeantwortet.
- Tests: Matrix Reply-Lookup `3 passed`; Signal Gruppenrouting `3 passed` plus
  Adapter-Quote-Test `1 passed`; Ruff und `git diff --check` gruen. Kein echter
  Provider/API-Aufruf.
- Code-Commits: `41d9a1e7 fix: recognize matrix replies to bot`,
  `52cdd1ad fix: recognize signal replies to bot`.

**Aktueller Laufstand:** Seit dem Restart `13/20` Code-Commits. Dieser
Plan-Commit zählt als `14/20`. Kein Push. Restart erst bei `20/20`.

### Engine- und AccountStore-Kontext: Aufgeloester Account und Nested-Rollback

- 2026-07-17: Nach Identity-Aufloesung wurde der aufgeloeste Account nicht
  konsequent in das Engine-Event uebernommen. Dadurch konnten First-Contact-
  LLM-Metadaten noch den vorlaeufigen Account referenzieren. Das Event wird
  jetzt vor der Verarbeitung auf den aufgeloesten Account synchronisiert.
- 2026-07-17: `_normalized_memory_index()` kopierte nur die oberste Ebene,
  veraenderte aber verschachtelte Rollback-Daten. Nach einem fehlgeschlagenen
  Indexschreiben konnte ein Rollback dadurch bereits neue `recent`, `keyword`
  oder `entries`-Daten enthalten. Mutierende Append-, Rebuild- und
  Access-Pfade arbeiten jetzt mit `deepcopy(previous_index)`; reine
  Ranking-/Select-Lesepfade bleiben shallow, damit grosse Semantic-Caches
  nicht bei jeder Abfrage kopiert werden.
- Tests: Engine-Account-Kontext `2 passed`; Append-/Rebuild-/Access-Rollback
  und AccountStore-Fokus gruen; komplette `tests/test_account_store.py`:
  `315 passed in 38.63s`; Ruff und `git diff --check` gruen. Kein echter
  Provider/API-Aufruf.
- Code-Commits: `0d6e0e03`, `1fe4cb8a`, `d8c5bc87`.

**Aktueller Laufstand:** Seit dem Restart `17/20` Code-Commits. Dieser
Plan-Commit zaehlt als `18/20`. Kein Push. Restart erst bei `20/20`.

### SQL-Account-Merge: Partielle Zielschreibungen zurueckrollen

- 2026-07-17: Der SQL-Merge schrieb Outbox-, Dispatch-, History- und
  Zustands-Collections einzeln. Ein spaeter Schreibfehler liess fruehere
  Zielschreibungen stehen. Retry war zwar meist deduplizierend, der Zustand
  blieb bis dahin aber partiell.
- Vor dem Merge werden Ziel-Snapshots aller SQL-Collections gelesen. Bei
  jedem Fehler werden bereits geaenderte Collections rueckwaerts auf diesen
  Snapshot geschrieben. Scheitert auch der Rollback, wird ein sichtbarer
  `AccountStoreError` mit moeglicher Inkonsistenz gemeldet.
- Test: gezielter spaeter Collection-Schreibfehler stellt alle Ziel-
  Collections wieder her; SQL-Merge-Fokus `5 passed`; Ruff und
  `git diff --check` gruen. Kein echter Provider/API-Aufruf.
- Code-Commit: `d0169967 fix: rollback partial sql account merges`.

**Aktueller Laufstand:** Seit dem Restart `19/20` Code-Commits. Dieser
Plan-Commit zaehlt als `20/20`. Kein Push. Restart jetzt.

### Neuer Lauf: Loudness- und Account-Memory-Invarianten

- 2026-07-17: Scheduler- und Antwortpfade fuer Loudness-Pruefungen nutzten
  teilweise die echte aktuelle Zeit statt des vom Aufrufer vorgegebenen
  Zykluszeitpunkts. Dadurch konnten Tests und Recovery-Metadaten Zeitstempel
  verschieben. Beide Pfade verwenden jetzt den aufgeloesten `now`-Wert.
- 2026-07-17: Wake-Window-Deduplizierung brach nach einem alten `due_at` zu
  frueh ab und pruefte `created_at`/`updated_at` nicht mehr. Alle vorhandenen
  Outbox-Zeitfelder werden jetzt geprueft.
- 2026-07-17: Retention-Trim in
  `append_structured_memory_entry(max_entries=...)` liess geloeschte IDs in
  `index.accessed_ids`. Das Indexupdate entfernt nun verwaiste und doppelte
  Access-IDs.
- 2026-07-17: `reset_structured_memory()` konnte partielle Entry-Reads
  zuruecksetzen und dadurch unlesbare/gute Restdaten mit leerem Speicher
  ueberschreiben. Der bestehende Entry-Diagnose-Guard laeuft nun vor jedem
  Reset-Write. Tombstoned Accounts werden vor dem Reset abgewiesen.
- 2026-07-17: Append- und Access-Pfade liessen doppelte `recent_ids`,
  Keyword-IDs oder bestehende `accessed_ids` nach einer alten Indexkorruption
  stehen. Das gemeinsame Indexupdate und der Access-Write deduplizieren und
  trimmen diese Listen jetzt auf vorhandene IDs.
- Tests: Notification-Loudness `172 passed`; AccountStore-Fokus fuer neue
  Pfade gruen; komplette AccountStore-Suite `322 passed`; Ruff,
  `py_compile` und `git diff --check` gruen. Kein echter Provider/API-Aufruf.
- Code-Commits: `62350e29`, `cd3fcfea`, `f5bf4034`, `aa695b8e`, `551dcc80`,
  `a7540989`, `28876e42`.

**Aktueller Laufstand:** Seit dem letzten Restart `7/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### 2026-07-18: Aktuelle Wohnort-/Stadtlabels erkennen

- `Mein aktueller Wohnort ist Berlin`, `Meine aktuelle Stadt ist Hamburg`
  und `Mein jetziger Ort ist Potsdam` wurden bisher nicht erkannt.
- Attribute `aktuell`/`jetzig` werden jetzt vor `Wohnort`, `Stadt` oder `Ort`
  akzeptiert.
- Verifikation: `tests/test_weather_context.py` -> `22 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `76c4ff8e fix: parse labeled current residence cities`.

**Aktueller Laufstand:** Seit dem letzten Restart `8/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### YouTube-Parser-Misses: JSONL-Schreibzugriffe serialisieren

- 2026-07-17: Engine und Telegram konnten dieselbe
  `YouTube_Parser_Misses.jsonl` gleichzeitig erweitern. O_APPEND verhindert
  nicht jede Zeilen-/Flush-Kollision ueber mehrere Prozesse.
- Parser-Miss-Writes verwenden jetzt Thread-Lock plus POSIX-Dateisperre.
  Pfad bleibt append-only; Lese- und Reportlogik unveraendert.
- Test: lokale Transkriptionssuite -> `5 passed`, Lock-Aufruf verifiziert;
  Ruff, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `8103f503 fix: serialize YouTube parser miss writes`.

**Aktueller Laufstand:** Seit dem letzten Restart `8/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### YouTube-Transcript-Cache: parallele Cache-Writes sichern

- 2026-07-17: Gleichzeitige Transkriptionsjobs im selben Prozess verwendeten
  dieselbe PID-Tempdatei fuer eine URL. Ein Thread konnte die Datei eines
  anderen ueberschreiben oder dessen `replace` stoeren.
- Cache-Writes verwenden jetzt URL-bezogenen Thread-/POSIX-Lock, eindeutige
  PID-/Thread-/UUID-Tempdatei, `fsync` und atomisches `os.replace`.
- Test: lokale Transkriptionssuite -> `6 passed`, inklusive Cache-Write;
  Ruff, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `f60fa7ff fix: serialize YouTube transcript cache writes`.

**Aktueller Laufstand:** Seit dem letzten Restart `9/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### 2026-07-18: Wohnortwechsel mit `aber jetzt` erkennen

- `Ich wohne in Berlin, aber jetzt in Hamburg` und negierte Varianten mit
  `aber jetzt` wurden vom generischen ersten Wohnortmatch auf Berlin gekuerzt.
- Klare Wechselmarker `aber`/`jetzt` werden jetzt vor dem generischen Muster
  ausgewertet. `Ich wohne in Berlin, aber arbeite jetzt in Hamburg` bleibt
  bewusst Berlin, weil dort kein zweiter Wohnortanker folgt.
- Verifikation: `tests/test_weather_context.py` -> `22 passed`,
  `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a550c1bf fix: parse residence change wording`.

**Aktueller Laufstand:** Seit dem letzten Restart `10/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### 2026-07-18: Qualifizierte Zuhause- und Haushaltsangaben erkennen

- `Ich bin aktuell in Potsdam zuhause`, `Ich bin seit kurzem in Leipzig zu
  Hause` und `Ich lebe seit einiger Zeit bei meiner Freundin in Dresden`
  wurden bisher verworfen. Wohnortlabels mit `Wohnort: Stadt` ebenfalls.
- Der Parser akzeptiert begrenzte Zeit-/Aktuell-Qualifizierer vor Zuhause- und
  Haushaltsangaben sowie `:` als Labelseparator. Eine unvollstaendige
  `bei ...`-Angabe ohne Stadt bleibt ungueltig.
- Verifikation: `tests/test_weather_context.py` -> `22 passed`,
  `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `b1f13cba fix: parse qualified home residences`.

**Aktueller Laufstand:** Seit dem letzten Restart `11/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### 2026-07-18: Explizite Wohnsitz- und Zuhause-Labels erkennen

- `Wohnort: Dresden`, `Ich habe meinen Wohnsitz in München`, `Ich bin in Köln
  wohnhaft` und `Mein Zuhause ist Dresden` wurden bisher nicht erkannt.
- Explizite Labels und sichere Zuhause-/Daheim-Formulierungen werden jetzt
  ausgewertet. `Heimatstadt` bleibt ausgeschlossen; daraus folgt keine
  aktuelle Wohnstadt.
- Verifikation: `tests/test_weather_context.py` -> `22 passed`,
  `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `313073d4 fix: parse explicit residence labels`.

**Aktueller Laufstand:** Seit dem letzten Restart `12/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### 2026-07-18: Wohnortwechsel mit `inzwischen` erkennen

- `Ich wohne in Berlin, aber inzwischen in Hamburg` und `... lebe aber
  inzwischen in Potsdam` wurden vom ersten Wohnortmatch auf Berlin gekuerzt.
- `inzwischen` und `mittlerweile` gelten jetzt als Wechselmarker, auch bei
  negiertem Ausgangsort und ohne wiederholtes `wohne/lebe`. Arbeitsortsaetze
  mit `arbeite inzwischen in ...` bleiben beim Wohnort Berlin.
- Verifikation: `tests/test_weather_context.py` -> `22 passed`,
  `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `ef0fcdc3 fix: parse updated residence markers`.

**Aktueller Laufstand:** Seit dem letzten Restart `13/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### 2026-07-18: Zeitqualifizierer im Wohnortparser vereinheitlichen

- `seit zwei Jahren`, `schon seit 2020`, `schon lange`, `momentan`,
  `vorübergehend` und `seitdem` wurden in direkten, Zuhause- und
  Haushaltsangaben teilweise verworfen. Vorangestellte Formen wie `Seit 2024
  bin ich ...` fehlten ebenfalls.
- Ein gemeinsames lokales Regex-Fragment deckt nun begrenzte Dauerangaben,
  aktuelle Zeitmarker und übliche Wortstellungen ab. Die bestehenden
  Negativregeln für Arbeitsort und Herkunft bleiben erhalten.
- Verifikation: `tests/test_weather_context.py` -> `22 passed`,
  `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `90854ed3 fix: normalize residence time qualifiers`.

**Aktueller Laufstand:** Seit dem letzten Restart `14/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### 2026-07-18: Deiktische und nahe Wohnorte erkennen

- `Ich wohne hier in Berlin`, `Ich lebe direkt in Hamburg`, `Ich wohne in der
  Umgebung von Potsdam`, `im Raum Leipzig` und `unweit von Dresden` wurden
  bisher verworfen.
- Der Parser akzeptiert nun begrenzte Ortsadverbien und klare
  Naeheformulierungen. Die Erkennung bleibt an ein Wohn-/Lebensverb oder eine
  Zuhause-/Haushaltsphrase gebunden.
- Verifikation: `tests/test_weather_context.py` -> `22 passed`,
  `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e2bc1fbf fix: parse nearby residence locations`.

**Aktueller Laufstand:** Seit dem letzten Restart `15/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### 2026-07-18: Umgekehrte Wohnsitzlabels erkennen

- `Berlin ist mein Wohnort`, `Wohnhaft in Hamburg` und `Ich bin ansässig in
  Potsdam` wurden bisher nicht als Wohnstadt erkannt.
- Umgekehrte Labels sowie explizite `wohnhaft`-/`ansässig`-Formulierungen sind
  jetzt abgedeckt. `Arbeitsort` und `Herkunftsort` werden nicht übernommen.
- Verifikation: `tests/test_weather_context.py` -> `22 passed`,
  `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `160f34f9 fix: parse inverted residence labels`.

**Aktueller Laufstand:** Seit dem letzten Restart `16/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### 2026-07-18: Offene Wohnort-Dauern erkennen

- `Ich lebe seit Jahren in Köln` und `Ich wohne seit Monaten in Dresden`
  wurden wegen fehlender Zahl vor der Zeiteinheit verworfen.
- Eigenständige Einheiten wie `Tagen`, `Wochen`, `Monaten` und `Jahren` sind
  nun gültige begrenzte Zeitqualifizierer.
- Verifikation: `tests/test_weather_context.py` -> `22 passed`,
  `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `9ca1f067 fix: parse open-ended residence durations`.

**Aktueller Laufstand:** Seit dem letzten Restart `17/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### 2026-07-18: Zeit- und Begleitkontext aus Stadtnamen entfernen

- Generische Sätze wie `Ich wohne in Berlin schon seit Jahren`, `in Potsdam
  für zwei Jahre`, `in Berlin während meines Studiums` und `in München
  zusammen mit meinen Eltern` lieferten bisher verschmutzte Stadtnamen.
- Die bestehende Trailing-Stop-Logik beendet den Stadtnamen jetzt auch vor
  diesen Zeit-/Begleitphrasen. Wortgrenzen schützen Stadtnamen wie `Fürth`.
- Verifikation: `tests/test_weather_context.py` -> `22 passed`,
  `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `668f86be fix: trim residence context qualifiers`.

**Aktueller Laufstand:** Seit dem letzten Restart `18/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### 2026-07-18: Präpositionalen Wohnortkontext abschneiden

- `Ich wohne in Berlin in einer WG`, `auf dem Land`, `neben meinen Eltern`,
  `nahe der Innenstadt` und `innerhalb der Stadt` lieferten bisher keinen
  sauberen Stadtnamen.
- Diese Begleitpräpositionen werden nun als Trailing-Stop erkannt. Die
  Wortgrenze verhindert Treffer mitten in Ortsnamen.
- Verifikation: `tests/test_weather_context.py` -> `22 passed`,
  `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `5b7fb503 fix: trim prepositional residence context`.

**Aktueller Laufstand:** Seit dem letzten Restart `19/20` Code-Commits. Kein
Push. Restart nach dem nächsten Code-Fix.

### 2026-07-18: Wohnort in expliziter Stadtphrase erkennen

- `Ich wohne in der Stadt Berlin` wurde vom Naehe-/Wohnortparser bisher nicht
  erkannt.
- `in der Stadt <Ort>` ist nun eine sichere explizite Wohnortphrase; die
  bestehende Bindung an `wohne/lebe` bleibt erhalten.
- Verifikation: `tests/test_weather_context.py` -> `22 passed`,
  `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `ffc4b259 fix: parse city residence phrases`.

**Aktueller Laufstand:** Seit dem letzten Restart `20/20` Code-Commits.
Restart jetzt faellig. Kein Push.

### Gemini-Keyring: Cursor nach Route/Modell isolieren

- 2026-07-17: `RotatingAPIKeyRing` nahm zwar `name` entgegen, Registry-State
  war aber nur nach Keyliste indiziert. Stateful/Stateless oder verschiedene
  Gemini-Modelle mit gleichen Keys konnten dadurch gegenseitig Rotation
  ausloesen.
- Registry-State ist jetzt nach `(name, keys)` getrennt. Spaete Ergebnisse
  bleiben weiterhin geschuetzt; gleiche Route teilt ihren Cursor, andere
  Route nicht.
- Test: 31 fokussierte und 27 komplette Gemini-Keyring-Tests, Ruff,
  `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `49e5a349 fix: scope Gemini key rings by route`.

**Aktueller Laufstand:** Seit dem letzten Restart `10/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### Codex-History-Import: Project-Upserts unter Outbox-Lock

- 2026-07-17: Session-Import schrieb neue Summarys unter
  `codex_history_outbox_lock`, aktualisierte `codex_history_projects` danach
  aber ausserhalb. Parallele Collector-/Importlaeufe konnten dadurch
  `summary_count` und letzte Summarydaten verlieren.
- Project-Upserts importierter Batches laufen jetzt nochmals unter demselben
  Outbox-Lock. Einzelne Append-/Graph-/Strategiepfade behalten ihre bestehende
  Lock-Reihenfolge.
- Test: komplette `tests/test_codex_history.py` -> `188 passed`; Compile und
  `git diff --check` gruen. Ruff meldet nur neun bestehende E402-Warnungen im
  fcntl-Importblock. Kein Provider/API-Aufruf.
- Code-Commit: `ec5702b2 fix: serialize Codex project imports`.

**Aktueller Laufstand:** Seit dem letzten Restart `11/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### 2026-07-18: Legacy-Identity-Routen beim Lesen validieren

- Bereits gespeicherte Identity-Maps konnten ungueltige `adapter_slot`-Werte
  enthalten. Neue Schreibvalidierung allein reparierte diesen Altbestand nicht;
  Routing erkannte ihn erst spaet oder verwirft ihn je nach Pfad.
- `get_identity_route()` normalisiert positive Dezimalstrings und gibt bei
  ungueltigem, booleschem oder nichtpositivem Slot keine Route zurueck. Die
  Normalisierung wird beim Schreiben wiederverwendet.
- Verifikation: Identity-Route-Fokus `7 passed`, `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `202752fa fix: reject corrupt identity routes on read`.

**Aktueller Laufstand:** Seit dem letzten Restart `12/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### 2026-07-18: Reminder-Tageszeiten und Wochenanker korrekt behandeln

- `Denk bitte heute Abend an den Einkauf` wurde trotz Tageszeit als `09:00`
  geplant. Tageszeitwoerter liefern jetzt konservative Defaults: frueh 09,
  vormittags 10, mittags 12, nachmittags 15, abends 18, nachts 21.
- `naechste Woche`/`nächste Woche` blieb im Betreff und `an den Antrag` verlor
  durch ein zu loses Lookahead den Artikel `den`. Wochenanker werden aus dem
  Betreff entfernt; das ungenaue Zeitfenster bleibt `missing_time`, und
  Lookaheads erkennen nur ganze Woerter.
- Verifikation: `tests/test_reminder_intent.py` -> `52 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `03f5d6f4 fix: parse reminder dayparts and week anchors`.

**Aktueller Laufstand:** Seit dem letzten Restart `13/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### 2026-07-18: Reminder-Aufmerksamkeitsformulierung erkennen

- `Mach mich morgen um 9 auf den Termin aufmerksam` war weder klassischer
  Reminder noch strukturierter Cue und wurde deshalb nicht geplant.
- Eindeutige `mach ... auf ... aufmerksam`-Formulierungen werden jetzt
  deterministisch erkannt; Zeitmarker und Betreff bleiben getrennt.
- Verifikation: `tests/test_reminder_intent.py` -> `53 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `fe1635bf fix: parse reminder attention wording`.

**Aktueller Laufstand:** Seit dem letzten Restart `14/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### 2026-07-18: Reminder mit Nicht-Vergessen-Formulierung erkennen

- `Bitte nicht vergessen, mich morgen an den Termin zu erinnern` wurde trotz
  eindeutigem Auftrag nur als strukturierter Cue behandelt und konnte ohne
  Planner verloren gehen.
- `nicht vergessen` sowie `vergiss bitte nicht` werden jetzt klassisch
  erkannt. Ein abschliessendes `zu erinnern` landet nicht mehr im Betreff.
- Verifikation: `tests/test_reminder_intent.py` -> `55 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `d4f78ae9 fix: parse do-not-forget reminders`.

**Aktueller Laufstand:** Seit dem letzten Restart `15/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### 2026-07-18: Zusammengeschriebene Reminder-Tageszeiten erkennen

- `Erinnere mich am Freitagabend an den Arzt` wurde als Freitag `09:00`
  erkannt, weil `Abend` direkt am Wochentag stand.
- Tageszeitmarker werden jetzt auch in Komposita wie `Freitagabend` erkannt;
  Wortgrenze am Ende verhindert weiterhin Treffer in `Abendbrot`.
- Verifikation: `tests/test_reminder_intent.py` -> `56 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `2b03d222 fix: parse compound reminder dayparts`.

**Aktueller Laufstand:** Seit dem letzten Restart `16/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### 2026-07-18: Zeitpraeposition vor Reminder-Tagesanker bereinigen

- `Erinnere mich fuer morgen an den Termin` wurde korrekt terminiert, aber
  `fuer` blieb im Betreff.
- `fuer/für` wird jetzt nur direkt vor einem erkannten Tagesanker entfernt;
  ein normales `für` im eigentlichen Thema bleibt erhalten.
- Verifikation: `tests/test_reminder_intent.py` -> `57 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `2af71277 fix: clean reminder time prepositions`.

**Aktueller Laufstand:** Seit dem letzten Restart `17/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### 2026-07-18: Geschriebene deutsche Uhrzeiten im Reminder-Parser

- `um acht`, `um halb acht` und `Viertel nach acht` fielen bisher auf
  `09:00` und blieben teilweise im Betreff.
- Der Parser versteht jetzt geschriebene Stunden sowie `halb`, `Viertel nach`
  und `Viertel vor`; numerische Uhrzeiten behalten Vorrang.
- Verifikation: `tests/test_reminder_intent.py` -> `58 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `10507e5d fix: parse written reminder clock times`.

**Aktueller Laufstand:** Seit dem letzten Restart `18/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### 2026-07-18: Morgen-Tageszeit bei relativen Kalender-Remindern

- `Erinnere mich in zwei Wochen morgens an den Termin` uebernahm bisher
  aktuelle Uhrzeit `12:34`, weil `morgens` kein Tageszeitmarker war.
- `morgens` wird jetzt als `09:00` auf den relativen Kalendertag angewendet;
  der Datumsanker `morgen` bleibt davon getrennt.
- Verifikation: `tests/test_reminder_intent.py` -> `59 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c669af38 fix: apply morning daypart to relative reminders`.

**Aktueller Laufstand:** Seit dem letzten Restart `19/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### 2026-07-18: Kommende Komposit-Wochentage in Folgewoche verschieben

- `Erinnere mich kommenden Montagabend ...` wurde am aktuellen Montagabend
  statt am naechsten Montag geplant, weil `Montagabend` die Wochentaggrenze
  brach.
- `kommenden/nächsten + Wochentag` verschiebt jetzt immer auf die Folgewoche;
  Tageszeit-Suffixe bleiben fuer die Uhrzeit auswertbar.
- Verifikation: `tests/test_reminder_intent.py` -> `60 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `1d5191e8 fix: advance compound future weekdays`.

**Aktueller Laufstand:** Seit dem letzten Restart `20/20` Code-Commits. Kein
Push. Restart jetzt faellig.

### 2026-07-18: Naehe-Ortsangaben im Wetterparser

- `Ich wohne in der Naehe von Berlin` wurde als Stadt `der Naehe von Berlin`
  gespeichert; `Ich lebe nahe Hamburg` wurde gar nicht erkannt.
- Spezifische `in der Naehe von`-/`nahe`-Muster laufen jetzt vor dem generischen
  Wohnsatz und liefern den Referenzort.
- Verifikation: `tests/test_weather_context.py` -> `15 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `7564c771 fix: parse nearby residence cities`.

**Aktueller Laufstand:** Seit dem letzten Restart `1/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### 2026-07-18: Zeitqualifizierte Wohnsaetze erkennen

- `Seit 2024 lebe ich in Hamburg` und `Ich lebe seit 2024 in Potsdam` wurden
  nicht als Wohnort erkannt.
- Wohn-/Lebenssaetze mit Jahresanker werden jetzt vor dem generischen Pattern
  erkannt; reine Herkunftssaetze bleiben weiterhin ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `16 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `bc6bd9db fix: parse time-qualified residence cities`.

**Aktueller Laufstand:** Seit dem letzten Restart `2/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### 2026-07-18: Zuhause-Wohnortangaben erkennen

- `Ich bin in Berlin zuhause` und `Ich bin in Hamburg zu Hause` wurden nicht
  erkannt. Ein Satz wie `Ich bin bei meiner Freundin zuhause` darf dagegen
  keine Personenbezeichnung als Stadt speichern.
- Der Wetterparser erkennt jetzt explizite Zuhause-Muster; der Negativfall
  bleibt durch bestehende City-Bereinigung ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `17 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `14ff92b2 fix: parse home residence phrases`.

**Aktueller Laufstand:** Seit dem letzten Restart `3/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### 2026-07-18: Wohnort nach Haushalts-/Personenphrase erkennen

- `Ich wohne bei meiner Freundin in Berlin` und `Ich lebe bei meinen Eltern
  in Hamburg` wurden wegen des vorangestellten `bei`-Teils verworfen.
- Ein spezifisches `bei ... in <Stadt>`-Pattern extrahiert jetzt den
  nachfolgenden Ort; `Ich wohne bei meiner Freundin` ohne Stadt bleibt leer.
- Verifikation: `tests/test_weather_context.py` -> `18 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `d6883997 fix: parse residence after household phrase`.

**Aktueller Laufstand:** Seit dem letzten Restart `4/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### 2026-07-18: Wohnortwechsel mit einfacher Negation erkennen

- `Ich lebe nicht in Berlin, sondern in Hamburg` wurde nicht als neuer
  Wohnort erkannt; ohne `sondern` bleibt ein reiner Negationssatz weiterhin
  leer.
- Der Wetterparser verarbeitet jetzt `nicht in/bei <alt>, sondern in/bei
  <neu>` vor generischen Wohnmustern.
- Verifikation: `tests/test_weather_context.py` -> `19 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `47392de0 fix: parse plain residence negation changes`.

**Aktueller Laufstand:** Seit dem letzten Restart `5/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### 2026-07-18: Umzugsziel als aktuellen Wohnort erkennen

- `Ich bin von Berlin nach Hamburg gezogen` und `Ich bin umgezogen von Berlin
  nach Potsdam` wurden nicht erkannt.
- Klare Umzugsformen extrahieren jetzt nur das Ziel; auch `Ich bin nach
  Leipzig gezogen` wird unterstuetzt. Herkunft bleibt unberuehrt.
- Verifikation: `tests/test_weather_context.py` -> `20 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `8f8f3d89 fix: parse residence move destinations`.

**Aktueller Laufstand:** Seit dem letzten Restart `6/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### 2026-07-18: Wechsel zwischen Wohnen und Leben auswerten

- `Ich wohne in Berlin, lebe aber jetzt in Hamburg` blieb bisher bei Berlin.
- Ein Wechsel zwischen `wohnen` und `leben` nach einem Komma wird jetzt als
  neuer Wohnort erkannt; `arbeite jetzt in Hamburg` loest keinen Wechsel aus.
- Verifikation: `tests/test_weather_context.py` -> `21 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e09fa850 fix: parse residence wohnen leben changes`.

**Aktueller Laufstand:** Seit dem letzten Restart `7/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### SourceHarvester: parallele Harvest-/Promotion-Schreibzugriffe serialisieren

- 2026-07-17: Duplicate-Hash-Pruefung, Zielauswahl, Kopie und Manifest-Append
  waren nicht atomar zusammengefasst. Zwei Harvest-Prozesse konnten denselben
  Inhalt gleichzeitig als neu sehen und dieselbe Zieldatei bzw. widerspruechliche
  Manifestzeilen erzeugen. Promotion hatte dieselbe Luecke bei Zielauswahl und
  Manifest.
- `SourceHarvester` verwendet jetzt pro Bibliothekswurzel einen Thread- und
  POSIX-Dateisperren-Lock. Harvest und Promotion halten ihn ueber Pruefung,
  Zielauswahl, Kopie, Manifest-Append und optionales Quell-Loeschen.
- Test: 41 SourceHarvester-Tests, inklusive paralleler Duplicate-Pruefung;
  Ruff, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `03097430 fix: serialize source harvesting writes`.

**Aktueller Laufstand:** Seit dem letzten Restart `12/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### Bibliothekar-Chunk-Store: leeren Index gegen alte Chunks pruefen

- 2026-07-17: `_chunk_store_is_stale()` behandelte `chunk_count=0` immer als
  gueltig. Nach einem abgebrochenen Rebuild konnten dadurch alte, nicht zum
  leeren Index gehoerende Chunks ueber `read_snapshot()` oder optionale
  Backends weitergereicht werden.
- Ein leerer Index ist nur gueltig, wenn `chunks.jsonl` fehlt oder wirklich
  leer ist. Negative Counts erzwingen ebenfalls Rebuild.
- Test: komplette Bibliothekar-Suite -> `99 passed`; Produktions-Ruff,
  `py_compile` und `git diff --check` gruen. Ein bestehender Test-Rufffehler
  `SimpleSelection` blieb unberuehrt. Kein Provider/API-Aufruf.
- Code-Commit: `1383330c fix: detect stale empty bibliothekar chunks`.

**Aktueller Laufstand:** Seit dem letzten Restart `13/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### Runtime-LLM-Profile: Instruktions-Fallbacks erhalten

- 2026-07-18: Der Runtime-Profilpfad verwendete bei leerer Runtime-Konfiguration
  keine `llm_fallback_models` aus `BotInstructions`. Dadurch konnten Fallbacks
  aus `Bot_Verhalten.md` bei explizit gewaehltem Profil verschwinden, obwohl
  Direktrouten dieselbe Einstellung nutzten.
- Profil-Clients verwenden jetzt bei leerem Runtime-Wert die Instruktions-
  Fallbacks und filtern sie weiterhin anhand von `allow_remote_fallback`.
  Explizite Runtime-Fallbacks bleiben vorrangig. Keyring-, Free-Tier- und
  Service-Tier-Aufloesung nutzen dieselbe effektive Liste.
- Test: vollstaendige `tests/test_llm_router.py` -> `66 passed`; neuer
  Regressionstest deckt leere Runtime-Konfiguration ab. Ruff, `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `3cf92d08 fix: preserve instruction fallbacks for runtime profiles`.

**Aktueller Laufstand:** Seit dem letzten Restart `14/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### Proactive-Dispatch-Results: `dispatch_id` idempotent speichern

- 2026-07-18: Parallele Recovery-/Dispatch-Laeufe konnten denselben Versand
  mehrfach auditieren. Die Recovery sah nur nach `id`; bei bereits belegter
  Ergebnis-ID wurde fuer dieselbe `dispatch_id` eine neue ID erzeugt.
- `append_proactive_dispatch_results()` fuehrt jetzt vorhandene
  `dispatch_id`-Werte als Idempotenzschluessel. Wiederholte Ergebnisse werden
  nicht erneut gespeichert und liefern die bestehende Ergebnis-ID zurueck.
- Tests: `tests/test_account_store.py tests/test_proactive_cli.py` -> `389
  passed`; fokussierter Idempotenztest enthalten. Ruff, `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c59f76df fix: deduplicate proactive dispatch results`.

**Aktueller Laufstand:** Seit dem letzten Restart `15/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### Account-Memory-Diagnostik: parallele Accounts nicht vermischen

* 2026-07-18: SQLite- und PostgreSQL-Backends hielten Read-Diagnostik in
  gemeinsamen `last_*`-Feldern. Parallele Account-Reads konnten dadurch die
  Fehlerdiagnose eines anderen Accounts sehen; Healthchecks meldeten dann
  falsche Memory-Fehler oder uebersahen echte Fehler.
* Account-Memory-, Pair- und Instance-State-Operationen halten jetzt den
  Backend-Operationslock ueber Backend-Read/Write und Diagnoseauswertung.
  SQLite und PostgreSQL besitzen dafuer einen reentranten Backend-Lock.
* Test: `tests/test_account_store.py` -> `326 passed`; zusaetzlich
  `tests/test_sqlite_backup_sync.py tests/test_account_memory_migration.py` ->
  `15 passed, 1 skipped`; Ruff, Compile und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
* Code-Commit: `350b7304 fix: serialize account memory diagnostics`.

**Aktueller Laufstand:** Seit dem letzten Restart `18/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### Arbeitsgedaechtnis: Index muss zur JSONL passen

- 2026-07-17: `WorkingMemoryStore` und der noch vorhandene Telegram-Store
  pruefen jetzt nicht nur die Form des Index, sondern rekonstruieren den
  Indexvergleich aus der JSONL. Nach einem Abbruch zwischen JSONL-Append und
  atomischem Index-Replace werden stale oder fehlende Offsets damit repariert;
  die alte Indexdatei bleibt als `.corrupt.*` erhalten.
- Kann die JSONL nicht gelesen werden, bleibt der vorhandene Index erhalten;
  kein stilles Leeren bei temporaeren Berechtigungs-/I/O-Fehlern.
- Test: `tests/test_working_memory.py` -> `43 passed`; Ruff, `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `7d2d95da fix: rebuild stale working memory indexes`.

**Aktueller Laufstand:** Seit dem letzten Restart `8/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### Lokaler YouTube-Whisper-Fallback: Sprache nicht hart verdrahten

- 2026-07-17: Der lokale `whisper`-CLI-Fallback setzte bisher immer
  `--language English`. Das verschlechterte deutsche und andere Audios ohne
  Untertitel. Die feste Vorgabe ist entfernt; Whisper erkennt Sprache wieder
  selbst.
- Test: `tests/test_local_transcription.py` -> `4 passed`; Ruff,
  `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `562f9aa5 fix: let local whisper detect audio language`.

**Aktueller Laufstand:** Seit dem letzten Restart `9/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### YouTube-Prozessregistry: parallele Updates und Abbruch sichern

- 2026-07-17: `YouTube_Transcription_Processes.json` wird bei Register-,
  Unregister- und Cleanup-Operationen mit einem Prozess-Lock geschuetzt.
  Schreibvorgaenge laufen ueber temporaere Datei, `fsync` und atomisches
  `os.replace`; ein Abbruch hinterlaesst dadurch keine halbe JSON-Datei.
- Test: Prozessregistry-Suite `7 passed`; Ruff, `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c67764a3 fix: protect youtube process registry writes`.

**Aktueller Laufstand:** Seit dem letzten Restart `10/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### YouTube-Optionsparser: explizite Werte vor gelernten Defaults

- 2026-07-17: Deterministische `live`-/`llm`-Angaben werden vor gelernten
  Parser-Miss-Formulierungen ausgewertet. Gelernte Werte fuellen nur noch
  Felder, die der aktuelle Parser nicht bestimmen konnte; alte Antworten
  koennen aktuelle Nutzerkorrekturen damit nicht mehr ueberschreiben.
- Test: YouTube-Optionsparser `10 passed` (14 Subtests); Ruff, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `38a2795d fix: prioritize explicit youtube options`.

**Aktueller Laufstand:** Seit dem letzten Restart `11/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### MessageTracker: ungueltiges JSON-Schema darf keine alten Refs behalten

- 2026-07-17: Ein valides JSON ohne `refs`-Liste setzte den geladenen
  Trackerzustand bisher nicht zurueck. Der Tracker konnte danach veraltete
  In-Memory-Refs wieder persistieren. Ungueltiges Schema leert den geladenen
  Zustand jetzt wie unlesbares JSON.
- Test: `tests/test_message_tracking.py` -> `9 passed`; Ruff, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `f73d996f fix: clear tracker state on invalid schema`.

**Aktueller Laufstand:** Seit dem letzten Restart `12/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### Memory-Access: kompletter Index-Rebuild beim Access-Write

- 2026-07-17: `mark_structured_memory_accessed()` baut den Index jetzt aus
  allen aktuellen Rows neu auf. Damit koennen stale Keywords, Entries,
  Typen, Graph-Links und Semantic-Cache-Projektionen nicht durch einen
  normalen Access-Write erhalten oder erneut gespeichert werden.
- Zugriffsreihenfolge und `access_count`/`last_accessed_at` bleiben erhalten;
  angefragte IDs landen zuletzt in `accessed_ids`.
- Tests: fokussiert `4 passed`, komplette AccountStore-Suite `323 passed`;
  Ruff, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `50ca27f4 fix: rebuild memory projections on access`.

**Aktueller Laufstand:** Seit dem letzten Restart `13/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### Access-Recency: Zeitzonen korrekt vergleichen

- 2026-07-17: `_rebuild_account_memory_accessed_ids()` vergleicht
  `last_accessed_at` jetzt als UTC-normalisierte Datetimes. ISO-Strings mit
  unterschiedlichen Offsets werden dadurch nach ihrem tatsaechlichen
  Zeitpunkt sortiert, nicht nach lokaler Textdarstellung.
- Test: Access-Recency-Suite `3 passed`; Ruff, `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `566f4a2b fix: order memory access timestamps by instant`.

**Aktueller Laufstand:** Seit dem letzten Restart `14/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### Proactive-Dispatch-Results: Audit-Luecke nach Outbox-Versand schliessen

- 2026-07-17: Nach externem Versand wurde zuerst der Outbox-Status `sent` und
  erst danach das separate Dispatch-Result geschrieben. Ein Prozessabbruch
  dazwischen liess den Versand dauerhaft ohne Audit-Result; der naechste Lauf
  sah kein faelliges Item mehr und konnte nichts rekonstruieren.
- Erfolgreiche Sendungen erhalten jetzt eine `dispatch_id`, die in Outbox-
  Dispatchmetadaten und Dispatch-Result identisch bleibt. Jeder Dispatch-Lauf
  sucht vor neuem Versand nach solchen fehlenden Result-Zeilen und stellt sie
  aus dem Outbox wieder her. Vorhandene Resultate werden ueber ID dedupliziert.
- Test: Proactive-Suite `256 passed`; fokussierter Recovery-Test gruen; Ruff,
  `py_compile` und `git diff --check` gruen. Kein echter Provider/API-Aufruf.
- Code-Commit: `8776193a fix: recover proactive dispatch audit results`.

**Aktueller Laufstand:** Seit dem letzten Restart `15/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### Proactive-Audit: Secret-Payloads nicht persistieren

- 2026-07-17: Abgewiesene Planner-/Tool-Payloads wurden fuer
  `Proactive_Audit` nur gekuerzt, nicht redigiert. Secretwerte konnten dadurch
  trotz abgewiesener Aktion in der Auditspur landen.
- Mapping-Schluessel mit Secret-Bedeutung, Secret-Zuweisungen, Provider-Token-
  formen, URL-Zugangsdaten, Bearer/Basic/ApiKey/Token-Header, Telegram-Tokens,
  JWTs und PEM-Private-Keys werden vor der Auditpersistenz redigiert.
  Vorhandene Registrierungscode-Redaktion wird wiederverwendet.
- Test: `tests/test_proactive_agent.py` -> `192 passed`; Secret-Fokus und
  Tool-Agent-Fokus gruen; Ruff, `py_compile` und `git diff --check` gruen.
  Kein echter Provider/API-Aufruf.
- Code-Commit: `24901283 fix: redact proactive planner audit secrets`.

**Aktueller Laufstand:** Seit dem letzten Restart `16/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### Aktueller Stand nach Restart: Notification-Loudness-State gesichert

- Code-Commit `1e661f0d` schuetzt Loudness-Prompt, Antwort und Scheduler mit
  `proactive_outbox -> account_memory`; konkurrierende Agent-State-Updates
  bleiben erhalten.
- Verifikation: Loudness `173 passed`, Engine `284 passed`, Compile und
  Diff-Check gruen; kein Provider/API-Aufruf.
- Restart: `systemctl --user restart teebotus.service` erfolgreich,
  Service `active`.

**Aktueller Laufstand:** Seit dem Restart `0/20` Code-Commits. Kein Push.
Restart nach weiteren 20 Code-Fixes.

## Aktueller Lauf nach Restart: Wetter-/Wohnortlogik

- Restart `systemctl --user restart teebotus.service` am 2026-07-18 war
  erfolgreich; Service ist `active`, `.env`-Check und Signal-CLI starten.
- Seit diesem Restart: `3/20` Code-Commits, kein Push.
- Neue Fixes: `e0246899` ersetzt veraltete generierte Wohnort-Memories mit
  Snapshot/Rollback, `2f6f3584` bereinigt bereits vorhandene Geschwister bei
  erneuter Ortsnennung, `ec0f3431` schneidet Gedankenstrich-Kontext sauber ab.
- Verifikation: Wetterparser `25 passed`; Structured-Memory-Fokus `11 passed`;
  zusätzlicher SQLite-Wetter-Rebuild-Smoke-Test gruen. Kein Provider/API-
  Aufruf.
- Naechster Restart bei Code-Fix `20/20`; kein Push ohne ausdrueckliche
  Freigabe.

### 2026-07-18: Veraltete generierte Wohnort-Memories ersetzen

- Nach Berlin -> Potsdam blieben beide automatisch erzeugten
  `mem_residence_city_*`-Eintraege aktiv; die Memory-Auswahl lieferte dadurch
  zwei aktuelle Wohnorte.
- Beim Wechsel werden alte generierte Wohnort-Entries jetzt atomar aus
  Entries/Index entfernt, bevor der neue aktuelle Eintrag geschrieben wird.
  Snapshot/Rollback schuetzt den alten Zustand bei Schreibfehlern.
- Verifikation: `tests/test_weather_context.py` -> `24 passed`,
  `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e0246899 fix: replace stale residence memories`.
- Restart: `systemctl --user restart teebotus.service` erfolgreich; Service
  `active`.

**Aktueller Laufstand:** Seit dem Restart `1/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Artikel- und Deiktika-Descriptoren verwerfen

- `der/die/das Berlin`, `dieser Berlin` und `dort Berlin` wurden als Stadt
  uebernommen.
- Der enge `_clean_city()`-Guard verwirft nun solche Starts; Wortgrenzen
  lassen Komposita wie `Dortmund` weiterhin zu.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `9ef3aff0 fix: reject residence article descriptors`.

**Aktueller Laufstand:** Seit dem Restart `2/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Weitere Determinierer vor Stadttext verwerfen

- `den/dem Berlin`, `welcher Berlin` und `mehrere Berlin` wurden als Wohnort
  uebernommen.
- Der bestehende Descriptor-Guard verwirft nun weitere Artikel, Pronomen und
  Mengenangaben vor dem Stadtnamen.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `d10f95a1 fix: reject residence determiner descriptors`.

**Aktueller Laufstand:** Seit dem Restart `3/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Slash-/Ampersand-Wohnortalternativen verwerfen

- `Berlin/Brandenburg` und `Hamburg & Berlin` wurden am ersten Ort gekappt
  und dadurch fälschlich als eindeutiger Wohnort gespeichert.
- Unaufgeloeste `/`- und `&`-Separatoren werden nun vor Satzende verworfen;
  Bindestrich-Orte wie `Berlin-Brandenburg` bleiben erlaubt.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `7c18b6ee fix: reject slash and ampersand residence alternatives`.

**Aktueller Laufstand:** Seit dem Restart `4/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Slash-/Ampersand-Aktivitaetsanschluesse erhalten

- Der neue `/&`-Guard verwarf `Berlin / arbeite ...` und `Berlin & meine
  Arbeit ...` zu streng.
- Bekannte Aktivitaetsanschluesse werden nun durchgelassen; echte
  Ortsalternativen mit zweitem Ortswort bleiben unentschieden.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `5d08d5c4 fix: preserve residence before activity separators`.

**Aktueller Laufstand:** Seit dem Restart `5/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Aktuellen Marker `nun` zentral erkennen

- `Ich wohne nun in Berlin`, `Wohnort ist nun Hamburg` und `Zuhause bleibt
  nun Potsdam` wurden bisher leer oder mit `nun` als Stadt erkannt.
- `nun` ist jetzt zentraler aktueller Marker; `heute` bleibt bewusst
  temporaer und ueberschreibt Wohnort nicht.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a823e158 fix: parse current residence marker nun`.

**Aktueller Laufstand:** Seit dem Restart `6/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Nachgestellte Zeitmarker aus Stadttext entfernen

- `Berlin zurzeit`, `Hamburg momentan`, `Potsdam derzeit` und
  `Köln derzeit bei ...` wurden mit Kontextsuffix gespeichert.
- Der City-Trailing-Stop erkennt nun nachgestellte aktuelle/temporäre
  Zeitmarker inklusive `zur Zeit`.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `3c36731b fix: trim trailing residence time markers`.

**Aktueller Laufstand:** Seit dem Restart `7/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Primaere Wohnsynonyme erkennen

- `Lebensmittelpunkt`, `Hauptwohnsitz` und `lebe ueberwiegend/hauptsaechlich`
  wurden bisher nicht erkannt.
- Eindeutige Primaerwohnanker werden nun verarbeitet; `Heimat` bleibt als
  Herkunftsbegriff ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `f84eb2e7 fix: parse primary residence synonyms`.

**Aktueller Laufstand:** Seit dem Restart `8/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Primaere Wohnsynonyme auch bei Korrekturen

- `Lebensmittelpunkt/Hauptwohnsitz` wurden nach der Grundunterstuetzung bei
  `jetzt`, Negation, Historie und Verlegung noch nicht korrekt aktualisiert.
- Ein eigener Aliaspfad deckt diese Korrekturen ab; Naeheangaben nutzen weiter
  den spezifischen Naeheparser.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `6c4eecd2 fix: apply residence correction paths to primary synonyms`.

**Aktueller Laufstand:** Seit dem Restart `9/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Primaerwohnlabel mit Verb oder Doppelpunkt

- `Lebensmittelpunkt:` und `Hauptwohnsitz:` waren trotz funktionierendem
  `ist/liegt`-Pfad leer.
- Der Aliasparser akzeptiert nun beide Separatorformen ohne doppelte oder
  fehlende Leerzeichen.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `63c551d1 fix: parse primary residence label separators`.

**Aktueller Laufstand:** Seit dem Restart `10/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Dauerhafte Wohnortangaben

- `dauerhaft` wurde als Teil der Stadt gespeichert; `fester Wohnsitz` wurde
  nicht erkannt.
- Dauer-/Permanentmarker sind nun zentrale Qualifizierer; feste, staendige
  und permanente Wohnsitzformulierungen werden als Wohnanker erkannt.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `823d5753 fix: parse permanent residence qualifiers`.

**Aktueller Laufstand:** Seit dem Restart `11/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: `den`-Besitzsatz fuer Primaerwohnanker

- `Ich habe den Hauptwohnsitz/Lebensmittelpunkt ...` wurde leer erkannt,
  waehrend `meinen` funktionierte.
- Der bestehende Alias-Besitzpfad akzeptiert nun `meinen|den` sowie `in|bei`.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `7b9cf67a fix: parse dative residence ownership phrasing`.

**Aktueller Laufstand:** Seit dem Restart `12/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Weitere Dauerqualifizierer abdecken

- `seit fast zwei Jahren`, `seit circa/ca. drei Monaten`, `seit rund vier
  Jahren` und `seit mindestens einem Jahr` wurden bisher nicht erkannt.
- Der Dauerbaustein akzeptiert nun diese gaengigen Naeherungs- und
  Untergrenzenangaben.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `eb5fdf1a fix: parse approximate residence durations`.

**Aktueller Laufstand:** Seit dem Restart `2/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Qualifizierte Zuhause- und Wohnhaft-Labels

- `weiterhin in Potsdam wohnhaft`, `seit 2020 ... ansässig`, `Mein Zuhause
  bleibt in Köln` und `Zuhause liegt nach wie vor in München` wurden bisher
  leer oder mit Qualifizierer als Stadt erkannt.
- Wohnhaft-/Ansässig-Labels und relationale Zuhause-Labels akzeptieren nun
  Zeitqualifizierer sowie die Wortstellung `bin ich`.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c68e2ce5 fix: parse qualified home and residence labels`.

**Aktueller Laufstand:** Seit dem Restart `3/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Zuhause-Korrekturen erkennen

- `Mein Zuhause ist nicht Berlin, sondern Hamburg`, `liegt ... inzwischen`
  und `war Berlin und ist jetzt Hamburg` wurden bisher leer oder mit altem
  Ort erkannt.
- Die vorhandenen Label-Korrekturpfade decken nun auch `Zuhause`, `zu Hause`
  und `Daheim` sowie `liegt/befindet sich` ab; Arbeitsortsaetze bleiben
  ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `3a7e340b fix: parse home label corrections`.

**Aktueller Laufstand:** Seit dem Restart `4/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Umgangssprachliches `wohn` mit Zeitangabe

- `Ich wohn seit zwei Jahren in Köln`, `ich wohn weiterhin ...` und `Wohn
  seit 2020 ...` wurden bisher nicht erkannt; `wohn jetzt` funktionierte.
- Der generische Wohn-/Lebenspfad akzeptiert nun auch die Kurzform `wohn`.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `cb1ed6eb fix: parse colloquial residence verb`.

**Aktueller Laufstand:** Seit dem Restart `5/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Historische Wohnzeitphrasen erkennen

- `seit dem letzten/vergangenen Jahr`, `seit meiner Kindheit/Geburt`, `seit
  dem Studium`, `seit jeher` und `seit letztem Sommer` wurden bisher nicht
  erkannt.
- Der feste Zeitbaustein akzeptiert diese Wohnzeitangaben inklusive Dativ-
  und ASCII-Varianten.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `38656492 fix: parse historical residence time phrases`.

**Aktueller Laufstand:** Seit dem Restart `6/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Erweiterte Umzugsformulierungen erkennen

- `Ich bin aus Berlin nach Hamburg gezogen/umgezogen` und `von ... nach
  ... umgezogen` wurden bisher nicht erkannt.
- Ein gemeinsamer Zielstadtpfad akzeptiert nun `von/aus` sowie beide
  Umzugsverben.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `8dcc3df5 fix: parse extended move phrases`.

**Aktueller Laufstand:** Seit dem Restart `7/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Abgeschlossene Relokationsverben erkennen

- `Ich zog von Berlin nach Hamburg`, `bin ... gewechselt/weggezogen` und
  `habe meinen Wohnort ... verlegt` wurden bisher nicht erkannt.
- Abgeschlossene Zielwechsel werden nun erkannt; Zukunft (`werde ziehen`) und
  reine Fahrt (`bin ... gefahren`) bleiben leer.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `ca377c23 fix: parse completed relocation verbs`.

**Aktueller Laufstand:** Seit dem Restart `8/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Konkurrierende Wohnorte nicht raten

- `Ich wohne in Berlin und Hamburg` sowie `... und lebe in Hamburg` wurden
  bisher faelschlich als Berlin gespeichert.
- Eindeutige Wechselpfade werden zuerst ausgewertet; danach verwirft ein
  enger Guard konkurrierende Wohnziele ohne Aktualitaetsmarker. Arbeits- und
  Alltagssätze bleiben gültig.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a7da6952 fix: reject ambiguous residence targets`.

**Aktueller Laufstand:** Seit dem Restart `9/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Aktivitaetszusatz nicht als Wohnortkonkurrenz werten

- Der Mehrfachwohnort-Guard verwarf `besuche`, `verbringe`, `treffe`, `reise`
  und `pendle` in einer zweiten Stadt faelschlich als unklar.
- Diese Aktivitaetsverben bleiben jetzt beim ersten Wohnort; konkurrierende
  `wohne/lebe`-Angaben bleiben weiterhin unentschieden.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `eac898c1 fix: preserve residence through activity clauses`.

**Aktueller Laufstand:** Seit dem Restart `10/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Wohnort-Modifikatoren und zeitqualifizierte Negation

- `Ich wohne nur/allein in Berlin` wurde bisher nicht erkannt.
- `momentan nicht in Berlin, sondern in Hamburg` wurde bisher nicht als
  aktueller Wechsel erkannt.
- `eher ... als`, `ausser ... auch` und andere konkurrierende Angaben bleiben
  bewusst unentschieden.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `207c49e5 fix: parse residence modifiers and negation`.

**Aktueller Laufstand:** Seit dem Restart `11/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Naeheangaben in Wohnortlabels priorisieren

- `Mein Wohnort ist in der Naehe von Berlin` wurde vom allgemeinen Labelpfad
  als `der Naehe von Berlin` erfasst; `im Raum` und `unweit` konnten ebenfalls
  falsch oder leer sein.
- Ein spezifischer Labelpfad verarbeitet jetzt Naehe-/Umgebungsangaben vor
  dem allgemeinen `in/bei`-Pfad und entfernt `von` korrekt.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c26c03d3 fix: prioritize nearby residence labels`.

**Aktueller Laufstand:** Seit dem Restart `12/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Unvollstaendige Wohnort-Descriptoren verwerfen

- `in der Stadt`, `in der Naehe`, `bei der Arbeit`, `nahe` und `ausserhalb
  von Berlin` wurden teils als Staedte gespeichert.
- `_clean_city()` entfernt nun versehentlich mitgecapturte `in/bei`-Praefixe
  und verwirft enge Descriptor-Starts; echte `Berlin`-/`Muenchen`-Werte
  bleiben gueltig.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `75e40033 fix: reject incomplete residence descriptors`.

**Aktueller Laufstand:** Seit dem Restart `13/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Wohnortlabel-Wechsel mit Aktualitaetsmarker

- `Wohnort ist in Berlin; jetzt/inzwischen in Hamburg` und die `und jetzt`
  Variante wurden bisher nicht aktualisiert.
- Labels mit Komma, Semikolon, Gedankenstrich oder `und` akzeptieren nun einen
  eindeutigen Aktualitaetsmarker plus verpflichtendes `in/bei`; Arbeitslabels
  bleiben unangetastet.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `1b7f3374 fix: parse labeled residence changes`.

**Aktueller Laufstand:** Seit dem Restart `14/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Explizite Wohnort-Relokationslabels

- `Wohnort wurde nach Hamburg verlegt`, `änderte sich zu`, `hat sich nach
  Hamburg geändert` und `Wohnort nach Hamburg verlegt` wurden bisher nicht
  erkannt.
- Abgeschlossene Änderungslabels werden jetzt erkannt; pauschale
  `Adresse`-Interpretation bleibt bewusst aus.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `f8ed3cc6 fix: parse explicit residence relocation labels`.

**Aktueller Laufstand:** Seit dem Restart `15/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Fuehrende Kontextpraepositionen verwerfen

- `Wohnort ist aus/für/wegen/neben Berlin` wurde vom optionalen Labelpfad als
  Stadt uebernommen.
- `_clean_city()` verwirft nun solche Kontextstarts sowie `mit/als/waehrend`
  und `auf/am/im`; Wortgrenzen schuetzen echte Komposita wie `Amberg`.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `b6d9bdb1 fix: reject residence context prefixes`.

**Aktueller Laufstand:** Seit dem Restart `16/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Historische Wohnortkorrekturen

- `Wohnort war frueher Berlin, jetzt in Hamburg` sowie `wohnte in Berlin,
  jetzt in Hamburg` wurden bisher nicht erkannt.
- Vergangenheitsformen mit eindeutigem Aktualitaetsmarker und Zielpraeposition
  liefern nun die neue Stadt; `jetzt arbeite ...` bleibt ohne Wohnortwert.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `9c648cd2 fix: parse historical residence corrections`.

**Aktueller Laufstand:** Seit dem Restart `17/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Satzgrenzen in Wohnort-Captures

- Bei `Berlin. Jetzt ...` wurde der Satzpunkt samt Folgesatz als Stadttext
  aufgenommen.
- `_clean_city()` trennt nun Satzzeichen mit folgendem Text; `St. Gallen`
  bleibt als legitimer Ortsname erhalten.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `1243c8de fix: trim sentence boundaries from residence captures`.

**Aktueller Laufstand:** Seit dem Restart `18/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Satzgetrennte Wohnortwechsel erkennen

- `Ich wohne in Berlin. Jetzt/Inzwischen lebe ich in Hamburg` und die
  entsprechende Label-/Zuhauseform wurden bisher auf Berlin gekuerzt.
- Satzgetrennte Aktualitaetsmarker akzeptieren nun beide Pronomenstellungen;
  ein Folgesatz mit `arbeite` bleibt beim alten Wohnort.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `1509cf3e fix: parse sentence-separated residence changes`.

**Aktueller Laufstand:** Seit dem Restart `19/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Satzgetrennte Wohnort-Kurzform

- `Ich wohne in Berlin. Jetzt/Inzwischen in Hamburg` und die entsprechende
  Wohnort-/Zuhause-Labelvariante wurden bisher auf Berlin gekuerzt.
- Eindeutige Aktualitaetsmarker mit `in/bei` werden nun auch ohne zweiten
  Wohn-/Lebensverb erkannt; `Jetzt arbeite ...` bleibt beim alten Ort.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `6b548514 fix: parse sentence-separated residence shorthand`.

**Aktueller Laufstand:** Seit dem Restart `20/20` Code-Commits.

### Restart 2026-07-18

- `systemctl --user restart teebotus.service` erfolgreich.
- Service aktiv, `MainPID 3950560`, Start `2026-07-18 04:59:30 CEST`.
- Neuer Zaehler seit diesem Restart: `0/20` Code-Commits. Kein Push.

### Folgefix 2026-07-18: Negierte Mehrsatz-Wohnortwechsel

- `Ich wohne nicht mehr in Berlin. Jetzt/Sondern in Hamburg` blieb bisher
  leer.
- Negierte Wohnsaetze akzeptieren nun Satzgrenze, Aktualitaetsmarker und
  Zielpraeposition; Arbeitsverben ohne `in/bei` werden nicht uebernommen.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `8afef100 fix: parse sentence-separated residence negation`.

**Aktueller Laufstand:** Seit dem Restart `1/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### 2026-07-18: Bestehende Wohnort-Duplikate auch bei Wiederholung bereinigen

- Der erste Fix konnte veraltete Wohnort-Entries entfernen, wenn ein neuer
  Ort hinzukam. Bei bereits vorhandenem Ziel-Entry führte ein früher Return die
  Bereinigung jedoch nicht aus.
- Wiederholte Nennung des aktuellen Orts entfernt jetzt ebenfalls alle alten
  generierten Geschwister; das Ziel-Entry wird nicht doppelt angelegt.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `2f6f3584 fix: clean stale residence siblings`.

**Aktueller Laufstand:** Seit dem Restart `2/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### 2026-07-18: Gedankenstrich-Kontext aus Wohnort entfernen

- `Ich wohne in Berlin - meine Arbeit ist in Hamburg` wurde wegen des
  Kontextworts `meine` verworfen.
- Bindestrich, Gedankenstrich und Geviertstrich gelten nun als
  Satztrenner nach dem Wohnort. Ortsnamen mit internem Bindestrich bleiben
  durch die Wortposition erhalten.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`,
  `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `ec0f3431 fix: trim dash residence context`.

**Aktueller Laufstand:** Seit dem Restart `3/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### 2026-07-18: Natuerliche Zeitangaben beim Wohnort erkennen

- `Ich wohne seit kurzem in Berlin`, `Ich lebe seit einiger Zeit in Leipzig`
  und `Ich wohne seit ein paar Jahren in Dresden` wurden bisher nicht als
  Wohnort erkannt. Auch `Ich wohne aktuell bei meiner Freundin in Potsdam`
  verlor den Zeitbezug vor der Haushaltsphrase.
- Der Wetterparser akzeptiert diese begrenzten Zeitqualifizierer und fuehrt
  optionale `jetzt`/`aktuell`/`derzeit`-Angaben vor `bei ... in <Stadt>` mit.
  Offene Personenangaben ohne Stadt bleiben weiterhin ungueltig.
- Verifikation: `tests/test_weather_context.py` -> `22 passed`,
  `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `2491af4f fix: parse natural residence time phrases`.

**Aktueller Laufstand:** Seit dem letzten Restart `9/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### 2026-07-18: Ungueltige Identity-Routen-Slots frueh ablehnen

- `AccountStore.update_identity_route()` speicherte `adapter_slot=0`, `False`
  oder nichtnumerische Werte. Downstream-Pruefungen verwarfen solche Routen;
  der Nutzer blieb dadurch still unerreichbar.
- Explizite Slots muessen jetzt positive Integer sein. Dezimalstrings wie
  `"2"` bleiben fuer alte Datenpfade zulaessig; ungueltige Werte werden vor
  dem Schreiben mit `AccountStoreError` abgelehnt.
- Verifikation: Identity-Route-Fokus `6 passed`, `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `4e7918c8 fix: reject invalid identity route slots`.

**Aktueller Laufstand:** Seit dem letzten Restart `11/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### 2026-07-18: Negierte Reminder duerfen keine Erinnerung anlegen

- `Erinnere mich bitte nicht morgen ...`, `Denk nicht an ...` und vergleichbare
  direkte Negationen wurden bisher als echte Reminder-Anfragen erkannt. Der
  Parser konnte dadurch ein falsches Proactive-Outbox-Item erzeugen.
- Direkte Negationen werden jetzt vor klassischem Parser und strukturiertem
  Reminder-Classifier verworfen. Eine Negation im eigentlichen Inhalt, etwa
  `Erinnere mich daran, nicht zu rauchen`, bleibt als Erinnerungsthema erlaubt.
- Verifikation: `tests/test_reminder_intent.py` -> `49 passed`; `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `d2a061c9 fix: reject negated reminder requests`.

**Aktueller Laufstand:** Seit dem letzten Restart `7/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### 2026-07-18: Zeitlich verneinte Reminder und Aussagesaetze sperren

- `Sag mir morgen nicht Bescheid` und `Denk morgen nicht an ...` konnten trotz
  Verneinung als Proactive-Reminder angelegt werden, weil `nicht` erst nach
  dem Zeitwort kam. Auch `Du erinnerst mich ...` wurde als Auftrag erkannt.
- Parser und optionaler strukturierter Classifier verwerfen jetzt solche
  Negationen bzw. Pronomen-Aussagen. Inhalt wie `Erinnere mich daran, nicht zu
  rauchen` bleibt weiterhin ein gueltiges Reminder-Thema.
- Verifikation: `tests/test_reminder_intent.py` -> `50 passed`; `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a4b04abd fix: reject temporal reminder negations`.

**Aktueller Laufstand:** Seit dem letzten Restart `8/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### 2026-07-18: Wohnortwechsel und Tageszeit im Wetterparser korrigieren

- `Ich wohne in Hamburg nachts` wurde bisher als Stadt `Hamburg nachts`
  gespeichert. Bei `Ich wohne in Berlin nicht mehr, jetzt in Hamburg` bzw.
  `nicht mehr bei meiner Mutter, jetzt in Hamburg` wurde der neue Wohnort
  nicht erkannt.
- Der Parser behandelt klare Wechselmuster vor dem allgemeinen Wohnsatz und
  beendet Stadtnamen an Tageszeitwoertern. Arbeits- und Reisesaetze wie
  `Ich wohne in Berlin und arbeite jetzt in Hamburg` bleiben bei Berlin.
- Verifikation: `tests/test_weather_context.py` -> `14 passed`; `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `288f989e fix: parse current city after residence changes`.

**Aktueller Laufstand:** Seit dem letzten Restart `9/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### 2026-07-18: Adapter-Slot bei Identity-Route-Updates erhalten

- `AccountStore.update_identity_route()` ersetzte bei ausgelassenem
  `adapter_slot` die Route ohne den bisher bekannten Slot. Aeltere Telegram-
  Pfade fuer Memory, Privacy und Voice rufen die Methode ohne Slot auf; ein
  Nutzer auf Telegram-Slot 2 konnte dadurch auf Slot 1 zurueckfallen.
- Bei ausgelassenem Parameter wird ein vorhandener gueltiger Slot jetzt
  normalisiert uebernommen. Neue Routen behalten weiterhin die implizite
  Defaultbelegung Slot 1.
- Verifikation: Identity-Route-Fokus `3 passed`, neuer Preserve-Slot-Test,
  `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `13ed9d80 fix: preserve adapter slots on route updates`.

**Aktueller Laufstand:** Seit dem letzten Restart `10/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### Reminder-Parser: leere Themen nach benanntem Datum normalisieren

- 2026-07-18: `Erinnere mich an den 20. Juni` entfernte das Datum, liess aber
  den Artikel `den` als Reminder-Thema zurueck. Numerische Datumsformen fielen
  bereits korrekt auf `deinen Termin` zurueck.
- Einzelne Artikelreste werden jetzt ebenfalls als leeres Thema behandelt.
  Das Datum und die Uhrzeit bleiben unveraendert.
- Verifikation: `tests/test_reminder_intent.py` -> `44 passed`; `py_compile`,
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `5a2ff9a3 fix: normalize empty reminder subjects`.

**Aktueller Laufstand:** Seit dem letzten Restart `3/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### Reminder-Parser: freie Bescheid- und Tageszeit-Formulierungen

- 2026-07-18: `Sag mir morgen um 9 Bescheid wegen ...` wurde nicht erkannt,
  weil `Bescheid` direkt auf `mir` folgen musste. `morgen frueh` liess
  `frueh` im Thema stehen.
- Die Bescheid-Erkennung erlaubt jetzt kurze Zeit-/Kontextwoerter zwischen
  `mir/uns` und `Bescheid`; typische Tageszeitwoerter werden aus dem Thema
  entfernt. Andere Themen bleiben unveraendert.
- Verifikation: `tests/test_reminder_intent.py` -> `46 passed`; `py_compile`,
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `37096a6e fix: parse natural reminder wording`.

**Aktueller Laufstand:** Seit dem letzten Restart `4/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### Reminder-Parser: Wiederholungsintervall mit Uhrzeit erhalten

- 2026-07-18: `alle 2 Tage um 9`, `alle 2 Wochen um 9` und `monatlich um 9`
  wurden wegen des Uhrzeit-Parsers am naechsten Tag eingeplant. Das verwarf
  das erkannte Wiederholungsintervall.
- Zeit-only-Wiederholungen berechnen den ersten Termin jetzt aus dem Intervall
  und setzen danach die explizite Uhrzeit. Explizite Tage, Daten und relative
  Anker bleiben autoritativ.
- Verifikation: `tests/test_reminder_intent.py` -> `47 passed`; `py_compile`,
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `26533381 fix: preserve reminder recurrence intervals`.

**Aktueller Laufstand:** Seit dem letzten Restart `5/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### Wettercache: Gross-/Kleinschreibung darf Rate-Limit nicht umgehen

- 2026-07-18: `Berlin` und `berlin` wurden als verschiedene Wohnstaedte
  behandelt. Eine erneute Nachricht konnte dadurch den Wettercheck innerhalb
  des 2-Stunden-Fensters unnoetig erneut ausloesen.
- Stadtvergleich erfolgt jetzt whitespace-normalisiert und casefolded. Bei
  gleicher Stadt bleibt die bisherige Darstellung erhalten; echte
  Stadtwechsel invalidieren weiterhin sofort.
- Verifikation: `tests/test_weather_context.py` -> `12 passed`; `py_compile`,
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `dbd6e00e fix: normalize weather city comparisons`.

**Aktueller Laufstand:** Seit dem letzten Restart `6/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### 2026-07-18: Wettercache bei Wohnortwechsel sofort erneuern

- Bei erkannter neuer Wohnstadt wurde der alte Wettertext zwar geloescht,
  aber `last_checked_at` blockierte den neuen Check noch bis zu zwei Stunden.
  Der User bekam dadurch fuer neue Stadt leeren Wetterkontext.
- Ein Wohnortwechsel invalidiert den alten Wettercache jetzt vollstaendig fuer
  den aktuellen Aufruf; normale Folgekontakte bleiben weiterhin auf maximal
  einen Check je zwei Stunden begrenzt.
- Verifikation: `tests/test_weather_context.py` -> `11 passed`; Compile und
  `git diff --check` gruen; kein Provider/API-Aufruf.
- Code-Commit: `aa5e120f fix: refresh weather after residence changes`.

**Aktueller Laufstand:** Seit dem letzten Restart `1/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### 2026-07-18: Numerische Reminder-Daten hinter `an den` korrekt auswerten

- `Erinnere mich an den 20.06. um 9 ...` wurde wegen der Subject-Schutzlogik
  als morgiger Termin um 09:00 gespeichert; das Datum landete im Betreff.
- Der Parser erkennt `an den <Datum>` und `an <Datum>` jetzt als Terminanker,
  wenn davor kein anderer Zeitanker steht. Bei `morgen/in 2 Stunden an den
  <Datum>` bleibt das Datum dagegen Betreffinhalt.
- Verifikation: `tests/test_reminder_intent.py` -> `42 passed`; Compile und
  `git diff --check` gruen; kein Provider/API-Aufruf.
- Code-Commit: `79c6d645 fix: parse dates after reminder markers`.

**Aktueller Laufstand:** Seit dem letzten Restart `2/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### Proactive-LLM-Plan: parallele identische Entscheidungen idempotent anwenden

- 2026-07-18: Zwei gleichzeitig laufende LLM-/Tool-Planner konnten denselben
  validierten Queue-Plan beide speichern. Einzelne Dateioperationen waren zwar
  gesperrt, aber die Gesamtentscheidung hatte keinen Idempotenzschluessel.
- `apply_proactive_llm_plan()` serialisiert Outbox und Account-Memory in der
  festen Reihenfolge `proactive_outbox -> account_memory`. Jede Memory- und
  Queue-Entscheidung erhaelt einen stabilen accountgebundenen Fingerprint.
  Aktive oder bereits gesendete gleiche Entscheidungen liefern die bestehende
  ID zurueck; fehlgeschlagene, abgebrochene oder abgelaufene Items blockieren
  keine spaetere Neuplanung.
- Test: parallele identische Plananwendung mit zwei Threads erzeugt eine
  gemeinsame Outbox-ID und genau einen Outbox-Eintrag; gesamte
  `tests/test_proactive_agent.py` -> `193 passed`; `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf. Ruff-Executable in
  aktueller Umgebung nicht installiert.
- Code-Commit: `c5902c0b fix: deduplicate concurrent proactive llm plans`.

**Aktueller Laufstand:** Seit dem letzten Restart `19/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### Notification-Loudness: Agent-State-Read-Modify-Write atomar sichern

- 2026-07-18: Loudness-Prompt, Loudness-Antwort und Scheduler hielten nur den
  Proactive-Outbox-Lock. Parallel laufende Aktivitaets-, Wetter- oder TTS-
  Updates konnten deshalb einen frisch geaenderten `Agent_State` mit einem
  alten Snapshot ueberschreiben.
- Alle drei Einstiegspunkte halten jetzt `proactive_outbox -> account_memory`
  gemeinsam. Verschachtelte State-/Outbox-Operationen bleiben reentrant und
  behalten die bestehende Lock-Reihenfolge.
- Test: paralleler State-Writer bleibt erhalten; komplette
  `tests/test_notification_loudness.py` -> `173 passed`; komplette
  `tests/test_engine_identity_flows.py` -> `284 passed`; `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf. Ruff-Executable in
  aktueller Umgebung nicht installiert.
- Code-Commit: `1e661f0d fix: serialize loudness agent state updates`.

**Aktueller Laufstand:** Seit dem Restart `0/20` Code-Commits. Kein Push.
Restart nach weiteren 20 Code-Fixes.

### Stateful-LLM-Lock: keinen Deadlock mit Proactive-Locks erzeugen

* 2026-07-18: Der Account-Memory-Lock aus Fix 16 hielt bei kompletter Engine-
  Verarbeitung. Proactive-Pfade verwenden aber die umgekehrte Reihenfolge
  `proactive_outbox -> account_memory`; parallele Nachrichten und Scheduler
  konnten dadurch gegenseitig warten.
* Stateful-LLM-Ketten verwenden jetzt separaten `.Account_LLM_Chain.lock`.
  Memory-, Proactive- und Status-Locks bleiben unabhängig; State-Persistenz
  wird innerhalb der LLM-Kettensperre weiterhin vom Account-Memory-Lock
  geschützt.
* Test: komplette Engine-Suite -> `284 passed`; Account-/State-Suite -> `410
  passed`; Ruff, Compile und `git diff --check` gruen. Kein Provider/API-Aufruf.
* Code-Commit: `3d270e1f fix: isolate stateful llm chain lock`.

**Aktueller Laufstand:** Seit dem letzten Restart `17/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### Working-Memory: Prozessuebergreifende Schreibzugriffe serialisieren

- 2026-07-17: `WorkingMemoryStore` nutzte nur einen prozesslokalen
  `threading.RLock`. Telegram, Signal und Matrix konnten denselben
  JSONL-/Indexbestand aus getrennten Prozessen gleichzeitig schreiben; dabei
  waren doppelte Offsets, verlorene Indexzeilen und stale Projektionen moeglich.
- Jede `ensure`, `prepare` und `append_manual`-Operation haelt jetzt neben dem
  Thread-Lock eine POSIX-Dateisperre. Der alte Telegram-Kompatibilitaetspfad
  nutzt dieselbe Sperrlogik.
- Test: `tests/test_working_memory.py` -> `44 passed`, inklusive echtem
  separatem Prozess mit nachgewiesenem Writer-Block; Ruff, `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a8d20df2 fix: serialize working memory across processes`.

**Aktueller Laufstand:** Seit dem letzten Restart `17/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### History-Dispatcher-Callback-Spool: Event-IDs nicht ueberschreiben

- 2026-07-17: `CallbackSpool.enqueue()` ersetzte vorhandene JSON-Dateien mit
  derselben Event-ID. Ein Retry oder ein fehlerhaft wiederverwendeter
  Event-Key konnte dadurch den urspruenglichen Payload verlieren.
- Spool-Enqueue ist jetzt atomar und nicht-ueberschreibend: identischer
  Payload ist idempotent, ein widerspruechlicher Payload wird mit Fehler
  abgelehnt. Temporardateien bleiben bei einem Abbruch unschaedlich.
- Test: `tests/test_history_dispatcher_bridge.py` -> `7 passed`; Ruff,
  `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `0274c374 fix: preserve conflicting dispatcher spool events`.

**Aktueller Laufstand:** Seit dem letzten Restart `18/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### History-Dispatcher-Callback-Spool: parallele Flushes serialisieren

- 2026-07-17: Mehrere Watcher/Threads konnten denselben Spool gleichzeitig
  lesen und dasselbe Delivery-Event parallel an den Dispatcher senden.
  Dadurch waren doppelte Zustellversuche trotz identischer Event-ID moeglich.
- `flush_spool()` verwendet jetzt einen Thread- und POSIX-Dateilock pro Spool.
  Bei Prozessabbruch bleibt das Event erhalten; der naechste Lauf kann es
  erneut senden.
- Test: `tests/test_history_dispatcher_bridge.py` -> `8 passed`, inklusive
  parallelem Flush-Test; Ruff, `py_compile` und `git diff --check` gruen.
  Kein Provider/API-Aufruf.
- Code-Commit: `79d5bcb7 fix: serialize dispatcher spool flushes`.

**Aktueller Laufstand:** Seit dem letzten Restart `19/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### History-Dispatcher-Callback: Application-Level-Fehler spulen

- 2026-07-17: `record_delivery()` spulte nur Socket-/Transportfehler. Eine
  erreichbare Dispatcher-Antwort mit `ok: false` oder ungueltigen Daten wurde
  direkt zurueckgegeben; das Delivery-Event war damit verloren.
- Jede nicht erfolgreiche Application-Level-Antwort wird jetzt mit derselben
  Event-ID in den Callback-Spool geschrieben. Deduplizierter Retry bleibt
  dadurch moeglich.
- Test: `tests/test_history_dispatcher_bridge.py` -> `9 passed`; Ruff,
  `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `24e7d8a4 fix: spool dispatcher application failures`.
- Restart-Regel: Code-Laufstand `20/20` erreicht. Die erste System-Unit-
  Annahme war falsch; `teebotus.service` ist eine User-Unit. Der korrekte
  Befehl `systemctl --user restart teebotus.service` lief erfolgreich.
  Telegram-, Signal-CLI- und Signal-REST-Prozesse wurden danach verifiziert.

**Aktueller Laufstand:** Seit dem letzten Restart `20/20` Code-Commits. Kein
Push. Restart abgeschlossen.

### Telegram-Dispatch-Journal: Prozessuebergreifende Schreibzugriffe sichern

- 2026-07-17: `TelegramDispatchJournal` hatte nur einen
  prozesslokalen `threading.RLock`. Getrennte Telegram-/Runtime-Prozesse
  konnten verschluesselte Journal-Read-Modify-Write-Zyklen ueberschreiben und
  bereits erledigte Aktionen wieder als offen persistieren.
- `load`, `create`, `mark_action_completed` und `complete` verwenden jetzt
  neben dem Thread-Lock eine Journal-Dateisperre. Lock-Fehler brechen fail
  closed mit `TelegramDispatchJournalError` ab.
- Test: separater Prozess-Locktest plus bestehende Journal-Retry-Tests ->
  `2 passed`; Ruff, `py_compile` und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `c617e89f fix: serialize telegram dispatch journal writes`.

**Aktueller Laufstand:** Seit dem letzten Restart `1/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### Bibliothekar: Index- und Chunk-Snapshots atomar lesen und schreiben

- 2026-07-17: `BibliothekarStore.rebuild()` schrieb `index.json` und
  `chunks.jsonl` ohne Prozesslock und in getrennten direkten Schreibvorgaengen.
  Ein paralleler Leser konnte neue Index-Metadaten mit alten oder halb
  geschriebenen Chunks kombinieren.
- Rebuild, `ensure`, `ensure_current`, `select` und Chunk-/Index-Lesen nutzen
  jetzt Thread- plus POSIX-Dateisperre. Index und JSONL werden ueber temporaere
  Dateien mit `fsync` und `os.replace` geschrieben. Bibliothekar-Servicepfade
  verwenden den Store-Snapshot statt direkter Dateizugriffe.
- Test: `tests/test_bibliothekar.py` -> `97 passed`, inklusive deterministischem
  Rebuild-/Leser-Race-Test; Ruff fuer Produktionsdateien, `py_compile` und
  `git diff --check` gruen. Ein vorhandener Ruff-Fehler in Testzeile 2604
  (`SimpleSelection`) bleibt unberuehrt. Kein Provider/API-Aufruf.
- Code-Commit: `5200ea07 fix: serialize bibliothekar index snapshots`.

**Aktueller Laufstand:** Seit dem letzten Restart `2/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### Versionsbenachrichtigungen: Gesamten Versandlauf serialisieren

- 2026-07-17: Der Versand las den gemeinsamen Versions-State und schrieb ihn
  zwar pro Einzeloperation gelockt, hielt den Lock aber nicht ueber den ganzen
  Versandlauf. Zwei parallele Jobs konnten denselben Empfaenger vor der ersten
  Zustandsaktualisierung sehen und doppelt benachrichtigen.
- `notify_recent_telegram_users_for_version()` nutzt jetzt den bestehenden
  `INSTANCE_STATE_ACCOUNT_ID`-Account-Memory-Lock fuer den gesamten Lauf. Damit
  bleiben SQL- und Legacy-State sowie Versandentscheidung zusammenhaengend.
- Test: parallele Versandlaeufe -> `results == [0, 1]`, kein doppelter Versand;
  fokussierte Version-Notification-Tests `3 passed`; Ruff, `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e02e9a05 fix: serialize version notification runs`.

**Aktueller Laufstand:** Seit dem letzten Restart `3/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### Account-Memory-Read-only-Health: Primary-Diagnostik bei fehlendem Fallback erhalten

- 2026-07-17: Der read-only Fallbackpfad ueberschrieb einen Primary-
  Entschluesselungsfehler durch die Diagnose des fehlenden Backup-Datensatzes
  und meldete nur `fallback data has read diagnostics`. Der Healthcheck verlor
  dadurch die konkreten Entry-/Index-Fehler.
- Der Pfad bewahrt jetzt Primary-Ergebnis und Primary-Diagnostik, behandelt eine
  fehlende Secondary als separaten Reparaturhinweis und bleibt weiterhin
  schreibfrei. Kein Fallback wird als gesund oder promotierbar markiert.
- Tests: `tests/test_account_store.py` -> `324 passed`; kompletter
  `tests/test_version_notifications.py` -> `234 passed`; Ruff, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `4cf0bdf5 fix: preserve primary readonly memory diagnostics`.

**Aktueller Laufstand:** Seit dem letzten Restart `4/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### Gemini-Keyring: Veraltete parallele Ergebnisse duerfen Rotation nicht zuruecksetzen

- 2026-07-17: Gemeinsamer Keyring wird von parallelen LiteLLM-Requests genutzt.
  Ein Request konnte nach einer Rotation noch mit einem alten Schluessel
  erfolgreich sein oder ein Limit melden und den Cursor dadurch auf einen
  erschoepften Schluessel zuruecksetzen.
- `mark_success()` und `mark_limited()` bewegen den Cursor jetzt nur noch,
  wenn gemeldeter Schluessel aktuell aktiv ist. Spaete Ergebnisse werden
  ignoriert; die Rotation bleibt monoton bis zum naechsten Limit.
- Test: 29 relevante Gemini-Keyring-/LiteLLM-Tests, Ruff, `py_compile` und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `7895f30a fix: ignore stale Gemini key results`.

**Aktueller Laufstand:** Seit dem letzten Restart `5/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### Bibliothekar-Haystack-Rebuild: Index und Chunks aus gleicher Generation

- 2026-07-17: `HaystackBibliothekarBackend.rebuild()` rief erst
  `fallback_store.rebuild()` und danach separat `read_chunks()` auf. Ein
  paralleler Rebuild konnte dadurch Indexgeneration A mit Chunkgeneration B
  an Qdrant schicken.
- `BibliothekarStore.rebuild_snapshot()` erzeugt Index und liest Chunks unter
  demselben Prozess-/Dateilock. Haystack verwendet diesen Snapshot direkt.
- Test: Bibliothekar-Suite -> `98 passed`, inklusive Store-Snapshot-Vertrag;
  Ruff, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `5efc24ff fix: rebuild bibliothekar snapshots atomically`.

**Aktueller Laufstand:** Seit dem letzten Restart `6/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### Gemini-Free-Tier-Cache: parallele Refresh-Writes sichern

- 2026-07-17: Der gemeinsame Limitcache verwendete fuer alle Prozesse dieselbe
  `.tmp`-Datei. Parallele Refreshes konnten sich beim Schreiben ueberschreiben;
  ein `replace` konnte dann fehlschlagen oder falschen Zustand hinterlassen.
- Cache-Writes laufen jetzt unter POSIX-Dateisperre, mit PID-/Thread-/UUID-
  Tempdatei, `fsync` und atomischem `os.replace`. Nicht-POSIX bleibt ueber
  atomischen Rename ohne flock funktionsfaehig.
- Test: 26 Gemini-Keyring-/Refresh-Tests, eindeutige Tempdateien und keine
  Restdateien; Ruff, `py_compile` und `git diff --check` gruen. Kein
  Provider/API-Aufruf.
- Code-Commit: `031c8e3d fix: serialize Gemini limit cache writes`.

**Aktueller Laufstand:** Seit dem letzten Restart `7/20` Code-Commits. Kein
Push. Restart erst bei `20/20`.

### Stateful-LLM-Engine: Account-Kette ueber Provider-Aufruf hinweg serialisieren

* 2026-07-18: SignalBot startet drei Consumer. Der Engine-State wurde nur bei
  einzelnen Dateioperationen gesperrt; parallele Telegram-/Signal-/Matrix-
  Threads konnten daher denselben `previous_response_id` lesen und danach
  ihre Antworten ungeordnet speichern.
* `TeeBotusEngine.process_result()` haelt jetzt den bestehenden Account-
  Memory-Lock ueber Identitaetsfluss, LLM-Aufruf und State-Persistenz. Damit
  bleibt die Stateful-Kette pro Account auch zwischen Engine-Instanzen und
  Prozessen geordnet. Ungueltige oder noch nicht aufgeloeste Account-IDs
  behalten den bisherigen lockfreien First-Contact-Pfad.
* Test: zwei Engine-Instanzen mit parallelen Stateful-Anfragen -> kein
  Overlap, zweite Anfrage erhaelt erste `response_id`; komplette
  `tests/test_engine_identity_flows.py` -> `284 passed`; Ruff, Compile und
  `git diff --check` gruen. Kein Provider/API-Aufruf.
* Code-Commit: `34723ccc fix: serialize stateful llm account chains`.

### Aktueller Stand nach Restart: Notification-Loudness-State gesichert

- Code-Commit `1e661f0d` schuetzt Loudness-Prompt, Antwort und Scheduler mit
  `proactive_outbox -> account_memory`; konkurrierende Agent-State-Updates
  bleiben erhalten.
- Verifikation: Loudness `173 passed`, Engine `284 passed`, Compile und
  Diff-Check gruen; kein Provider/API-Aufruf.
- Restart: `systemctl --user restart teebotus.service` erfolgreich,
  Service `active`.

**Aktueller Laufstand:** Seit dem Restart `0/20` Code-Commits. Kein Push.
Restart nach weiteren 20 Code-Fixes.

## Aktueller Lauf nach dem letzten Restart

- Service-Restart am 2026-07-18 erfolgreich; `.env`-Check, Bot und
  Signal-CLI aktiv.
- Seit diesem Restart `3/20` Code-Commits, kein Push.
- `e0246899`: veraltete generierte Wohnort-Memories atomar ersetzen;
  `2f6f3584`: vorhandene stale Geschwister bei Wiederholung bereinigen;
  `ec0f3431`: Gedankenstrich-Kontext trimmen.
- Verifikation: Wetterparser `25 passed`, Structured-Memory-Fokus `11
  passed`, SQLite-Wetter-Smoke-Test gruen. Kein Provider/API-Aufruf.
- Naechster Restart bei `20/20`; Push nur nach ausdruecklicher Freigabe.

### Folgefix 2026-07-18: Getrennte Wohnortwechsel erkennen

- `Ich wohne in Berlin; jetzt in Hamburg` und `... – inzwischen in Potsdam`
  fielen bisher auf den alten Ort zurueck.
- Semikolon und Gedankenstrich werden nun als Wechseltrenner akzeptiert, aber
  nur mit eindeutigem aktuellem Wohnortanker. `aber arbeite jetzt in ...`
  bleibt unveraendert.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `5d5ab58c fix: parse separated residence changes`.

**Aktueller Laufstand:** Seit dem Restart `4/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Negierte Wohnortwechsel mit Separator erkennen

- `Ich wohne nicht in Berlin; sondern in Dresden` und `nicht mehr ... – jetzt
  in Leipzig` wurden bisher nicht als neuer Wohnort erkannt.
- Negierte Wechsel akzeptieren nun Komma, Semikolon und Gedankenstrich mit
  `sondern`/Aktualitaetsmarker. Ein reiner Arbeitsortzusatz bleibt leer.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `344a7b01 fix: parse negated residence changes`.

**Aktueller Laufstand:** Seit dem Restart `5/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Wohnortkorrektur mit `und lebe jetzt` erkennen

- `Ich wohne in Berlin und lebe jetzt in Hamburg` und die `inzwischen`-
  Variante wurden bisher auf Berlin gekuerzt.
- Ein zweiter `wohne/lebe`-Anker mit Aktualitaetsmarker nach `und` wird nun
  als Korrektur erkannt; `und arbeite jetzt ...` bleibt unberuehrt.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `81d67a9c fix: parse and residence corrections`.

**Aktueller Laufstand:** Seit dem Restart `6/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Zeitqualifizierte Wohnortkorrekturen erkennen

- `Ich wohne in Berlin, aber lebe seit 2020 in Dresden` und `... lebe aber
  seit kurzem in Leipzig` wurden bisher auf Berlin gekuerzt.
- Der zweite Wohn-/Lebensanker nutzt jetzt das gemeinsame Zeitqualifizierer-
  Fragment. Dabei wurden `inzwischen` und `mittlerweile` zentral nachgezogen;
  die Regression ist mitgetestet.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `49c21ea9 fix: parse timed residence corrections`.

**Aktueller Laufstand:** Seit dem Restart `7/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Pronomen in zeitqualifizierter Korrektur erlauben

- `Ich wohne in Berlin, seit 2020 lebe ich in Hamburg` wurde trotz erkanntem
  Zeitanker auf Berlin gekuerzt, weil `ich` hinter dem zweiten Verb fehlte.
- Das optionale Pronomen wird nun zwischen zweitem Wohn-/Lebensverb und
  aktuellem Ortsanker akzeptiert.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `50f69d34 fix: handle pronoun in timed residence corrections`.

**Aktueller Laufstand:** Seit dem Restart `8/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Ziel bei `bin ... umgezogen` erkennen

- `Ich bin nach Hamburg umgezogen` wurde bisher nicht als aktueller Wohnort
  erkannt; nur `gezogen` und `umgezogen von ... nach ...` waren abgedeckt.
- Die Zielphrase `bin nach/in <Ort> umgezogen` nutzt jetzt denselben Move-
  Parser wie die vorhandenen Umzugsformen.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `83c1acc9 fix: parse umgezogen residence targets`.

**Aktueller Laufstand:** Seit dem Restart `9/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Kontrastkorrekturen mit `zwar ... aber` erkennen

- `Ich wohne zwar in Berlin, aber aktuell in Hamburg` wurde bisher nicht
  erkannt; ein Arbeitsortzusatz durfte dagegen Berlin nicht überschreiben.
- `zwar` ist nun im Wohnanker erlaubt, und ein klares `aber ... in <Ort>`-
  Muster setzt den aktuellen Ort. `aber arbeite ...` bleibt beim Wohnort.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `1740bd75 fix: parse zwar residence corrections`.

**Aktueller Laufstand:** Seit dem Restart `10/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Begründungskontext aus Wohnort entfernen

- `Ich wohne in Berlin aus beruflichen Gründen`, `lebe in Hamburg wegen der
  Arbeit` und `wohne in Berlin als Student` lieferten teils verschmutzte
  Stadtnamen.
- `aus`, `wegen` und `als` sind nun Trailing-Stop-Wörter nach dem Wohnort;
  vorhandene `auf`-Behandlung deckt `aufgrund` ab.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `caddb1e0 fix: trim residence reason context`.

**Aktueller Laufstand:** Seit dem Restart `11/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Kontrastkontext trimmen und Ortsalternativen ablehnen

- `Berlin obwohl/wobei/denn/da ...` lieferte teils verschmutzte oder leere
  Ergebnisse. `Berlin oder Hamburg`/`sowie` konnte als scheinbar eindeutiger
  erster Ort gespeichert werden.
- Kontrast-/Begründungsmarker werden jetzt abgeschnitten; explizite
  Alternativmarker `oder`, `sowie`, `bzw.` und `beziehungsweise` führen zu
  keiner Wohnstadt statt zu einer falschen Auswahl.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e1debb2a fix: reject ambiguous residence alternatives`.

**Aktueller Laufstand:** Seit dem Restart `12/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Relationale Wohnortlabels erkennen

- `Mein Zuhause liegt in Berlin` lieferte bisher `in Berlin`; `Wohnort
  befindet sich in Hamburg` wurde gar nicht erkannt.
- Wohnort-/Zuhause-Labels mit `ist`, `liegt` oder `befindet sich` plus `in/bei`
  werden jetzt vor dem allgemeinen Labelparser ausgewertet.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `bb2da1f7 fix: parse relational residence labels`.

**Aktueller Laufstand:** Seit dem Restart `13/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: `Wohnstadt` und aktuelle Profiladjektive erkennen

- `Meine aktuelle Wohnstadt ist Dresden`, `mein derzeitiger Wohnort` und
  `mein gegenwärtiger Ort` wurden bisher nicht erkannt.
- `wohnstadt`, `derzeitig` und `gegenwärtig` sind nun in expliziten aktuellen
  Wohnlabels erlaubt; `Heimatstadt` bleibt bewusst ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e925add7 fix: parse Wohnstadt residence labels`.

**Aktueller Laufstand:** Seit dem Restart `14/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Geografische Wohnortzusätze trimmen

- `Berlin im Norden`, `Hamburg am Stadtrand`, `Potsdam am See` und `Leipzig
  im Zentrum` wurden mit Zusatz am Stadtnamen gespeichert.
- `im` sowie begrenzte `am ...`-Kontexte werden jetzt abgeschnitten.
  `Frankfurt am Main` bleibt als legitimer Ortsname erhalten.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `42001d5e fix: trim geographic residence qualifiers`.

**Aktueller Laufstand:** Seit dem Restart `15/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Kontinuitaetsformulierungen beim Wohnort erkennen

- `weiterhin`, `nach wie vor`, `noch immer` und `immer noch` werden jetzt als
  aktuelle Wohnortqualifizierung erkannt.
- `Mein Wohnort bleibt Hamburg` und entsprechende `ist weiterhin`-/`ist nach
  wie vor`-Labels liefern den genannten Ort; vergangene Formen bleiben
  ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `155531cd fix: parse residence continuity wording`.

**Aktueller Laufstand:** Seit dem Restart `16/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Praepositionen hinter Kontinuitaetsmarkern korrekt parsen

- `Mein Wohnort ist weiterhin in Hamburg` wurde als `in Hamburg` statt als
  `Hamburg` erkannt.
- Relationale Labels akzeptieren Zeitqualifizierer nun vor `in/bei`; der
  direkte Labelpfad behandelt dieselbe Form ohne doppelte Praeposition.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `3ef8e8e6 fix: keep residence prepositions out of city names`.

**Aktueller Laufstand:** Seit dem Restart `17/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Eindeutige Wohnortwechsel mit Konnektoren erkennen

- Unpunktuierte Formen wie `nicht in Berlin sondern in Hamburg` sowie
  `doch/jedoch jetzt in Hamburg` wurden bisher nicht als Wechsel erkannt.
- Diese eindeutigen Gegenueberstellungen werden jetzt erkannt; reine
  Arbeitsortsaetze bleiben ausserhalb des Wohnortpfads.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `469a79e3 fix: parse residence contrast connectors`.

**Aktueller Laufstand:** Seit dem Restart `18/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Kontrastkonnektoren nach weiteren Separatoren

- `doch/jedoch` nach Semikolon oder Gedankenstrich wurde bisher nicht als
  Wohnortwechsel erkannt.
- Der bestehende eindeutige Konnektorpfad akzeptiert nun Komma, Semikolon und
  Gedankenstrich.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e5e0d3e3 fix: parse residence connectors after separators`.

**Aktueller Laufstand:** Seit dem Restart `19/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

### Folgefix 2026-07-18: Wohnort-Labels mit alter und neuer Angabe korrigieren

- `Mein Wohnort ist nicht Berlin, sondern Hamburg`, `... ist Berlin, aber
  jetzt Hamburg` und `... war Berlin und ist jetzt Hamburg` lieferten bisher
  keinen oder den alten Ort.
- Eindeutige Label-Korrekturen werden jetzt vor allgemeinen Labels erkannt;
  `aber ich arbeite in Hamburg` bleibt beim Wohnort Berlin.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `d1831581 fix: parse residence label corrections`.

**Aktueller Laufstand:** Seit dem Restart `20/20` Code-Commits.

### Restart 2026-07-18

- `systemctl --user restart teebotus.service` erfolgreich.
- Service aktiv, `MainPID 3387406`, Start `2026-07-18 04:23:40 CEST`.
- Neuer Zaehler seit diesem Restart: `0/20` Code-Commits. Kein Push.

### Folgefix 2026-07-18: Qualifizierte Wohndauern erkennen

- `seit mehr als zwei Jahren`, `seit über einem Jahr`, `seit knapp drei
  Monaten` und ähnliche Angaben wurden bisher nicht erkannt.
- Der vorhandene Dauerbaustein akzeptiert nun Vergleichs- und
  Näherungsqualifizierer inklusive ASCII-Umschriften.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `fee1fd30 fix: parse qualified residence durations`.

**Aktueller Laufstand:** Seit dem Restart `1/20` Code-Commits. Kein Push.
Restart erst bei `20/20`.

## Aktueller Ledger 2026-07-18

- Letzter Restart: `systemctl --user restart teebotus.service`, aktiv,
  `MainPID 3950560`, Start `2026-07-18 04:59:30 CEST`.
- Seit diesem Restart: `6/20` Code-Commits. Kein Push.
- Code-Fixes: `8afef100`, `9ef3aff0`, `d10f95a1`, `7c18b6ee`, `5d08d5c4`,
  `a823e158`.
- Verifikation je Fix: `tests/test_weather_context.py` -> `25 passed`,
  `py_compile`, `git diff --check`; kein Provider/API-Aufruf.
- Naechster Restart bei `20/20`; Push nur nach ausdruecklicher Anweisung.

### Folgefix 2026-07-18: Plurale Wohnortformulierungen erkennen

- Plurale Aussagen wie `Wir wohnen in Berlin`, `Wir leben seit zwei Jahren in Hamburg`, `Seit 2020 sind wir in Leipzig wohnhaft` und `Wir haben unseren Wohnsitz in Dresden` wurden bisher nicht oder nur zufaellig erkannt.
- Eigene Muster fuer `wir wohnen/leben`, `sind wir ... wohnhaft` und `wir haben unseren Wohnort/Wohnsitz` ergaenzt.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `706fcb48 fix: parse plural residence wording`.

## Aktueller Ledger 2026-07-18-True-Tail

- Letzter Restart: `systemctl --user restart teebotus.service`, aktiv, `MainPID 3950560`, Start `2026-07-18 04:59:30 CEST`.
- Seit diesem Restart: `13/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Benennungsformen für Wohnort

- `Hamburg heißt/heisst mein Wohnort`, `wird als mein Wohnort genannt` und `nennt man meinen Wohnort` liefern `Hamburg`.
- Gleichlautende Arbeitsortformen bleiben abgelehnt.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, fünf Naming-Residence-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `ba521c39 fix: parse naming residence labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- `teebotus.service` aktiv, `MainPID 3246`, Start `2026-07-18 22:44:34 CEST`.
- Seit diesem Restart: `14/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Qualifizierte Benennungsformen

- `Hamburg heißt mein aktueller Wohnort`, `wird mein/als mein derzeitiger Wohnort genannt` und `nennt man meinen derzeitigen Wohnort` werden erkannt.
- Historisches `früherer Wohnort` bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, fünf Qualified-Naming-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `47e715e7 fix: parse qualified naming residence forms`.

## Aktueller Ledger 2026-07-18-Post-Restart

- `teebotus.service` aktiv, `MainPID 3246`, Start `2026-07-18 22:44:34 CEST`.
- Seit diesem Restart: `15/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: City-vor-Adresslabels

- `Hamburg ist meine Wohnadresse/Meldeadresse/Anschrift`, `Hamburg als Wohnadresse` und `Als Meldeadresse Hamburg` werden erkannt.
- `Arbeitsadresse` bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, sechs Address-Residence-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `324799c5 fix: parse residence address labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- `teebotus.service` aktiv, `MainPID 3246`, Start `2026-07-18 22:44:34 CEST`.
- Seit diesem Restart: `20/20` Code-Fixes. Restart jetzt fällig; kein Push.

### Folgefix 2026-07-18: Artikel bei Adresslabels

- `Die Wohnadresse/Meldeadresse/Anschrift/Adresse ... Hamburg` werden erkannt.
- Neutrale `der Wohnort/der Wohnsitz` bleiben wegen möglicher Fremdperson mehrdeutig und abgelehnt.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, sechs Neutral-Address-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `fbb9cfc5 fix: scope neutral address labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- `teebotus.service` aktiv, `MainPID 3246`, Start `2026-07-18 22:44:34 CEST`.
- Seit diesem Restart: `17/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Fragen und Modalbehauptungen

- Unbeantwortete Fragen mit abschließendem `?` speichern keinen Wohnort.
- `könnte/soll/wäre` werden nicht mehr als Stadtbestandteil akzeptiert.
- Antwortform `Wo wohnst du? Berlin.` bleibt gültig.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, sechs Question-Modal-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `dece3b48 fix: reject question and modal residence claims`.

## Aktueller Ledger 2026-07-18-Post-Restart

- `teebotus.service` aktiv, `MainPID 3246`, Start `2026-07-18 22:44:34 CEST`.
- Seit diesem Restart: `18/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Umschreibung des Geburtsorts

- `Berlin ist der/ein Ort meiner Geburt, Hamburg mein Wohnort` liefert `Hamburg`.
- Die Umschreibung wird nur als Herkunftsteil des expliziten Herkunft-/Wohnort-Paares verwendet.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, zwei Birth-Place-Paraphrase-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `9515e2ec fix: parse birth place residence paraphrases`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 3547275`, Start `2026-07-18 22:02:50 CEST`.
- Seit diesem Restart: `14/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Reverse-Herkunftslabels

- `Meine Heimat ist Berlin, Hamburg mein Wohnort`, Geburtsort-Variante und Semikolonform liefern `Hamburg`.
- Reverse-Labels werden separat erkannt; unbeschriftete Ortsfragmente bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, drei Reverse-Origin-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `d88e0b63 fix: parse reverse origin residence labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 3547275`, Start `2026-07-18 22:02:50 CEST`.
- Seit diesem Restart: `15/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Statusqualifizierter aktueller Wohnort

- `in/bei Hamburg wohnhaft/gemeldet/registriert` wird nach Herkunftsangabe als aktueller Wohnort erkannt.
- Vorwärts- und Reverse-Form teilen dieselbe Statuswortliste; unqualifizierte Präpositionsorte bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, drei Status-Residence-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `df8ebbe1 fix: parse status-qualified current residence`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 3547275`, Start `2026-07-18 22:02:50 CEST`.
- Seit diesem Restart: `16/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Semikolon bei Vorwärts-Herkunftslabels

- `Berlin ist meine Heimat; Hamburg mein Wohnort` und die statusqualifizierte Form werden korrekt gelesen.
- Der Semikolontrenner gilt nur im expliziten Herkunft-/Wohnort-Muster.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, zwei Semicolon-Origin-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `b1b50e52 fix: parse semicolon origin residence labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 3547275`, Start `2026-07-18 22:02:50 CEST`.
- Seit diesem Restart: `17/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Aktueller Wohnort nach Geburtsverb

- `Ich bin in Berlin geboren, Hamburg mein Wohnort` und die `und ... ist`-Form liefern `Hamburg` statt `Berlin geboren`.
- Geburtsort bleibt historischer Kontext; aktueller Wohnort gewinnt nur mit explizitem Wohnlabel.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, zwei Birth-Verb-Residence-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `aee627fd fix: prefer current residence after birth clause`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 3547275`, Start `2026-07-18 22:02:50 CEST`.
- Seit diesem Restart: `18/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Status-Wohnort nach Geburtsverb

- `Ich bin in Berlin geboren und in Hamburg wohnhaft` sowie `bei Hamburg gemeldet` liefern `Hamburg`.
- Die Statuswortliste bleibt auf explizite aktuelle Belege begrenzt.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, zwei Birth-Status-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `58890426 fix: parse status residence after birth clause`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 3547275`, Start `2026-07-18 22:02:50 CEST`.
- Seit diesem Restart: `19/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Doppelpunkt-Herkunftslabels

- `Geburtsort: Berlin` bzw. `Herkunftsort: Berlin` mit anschließendem aktuellem Wohnort werden korrekt auf `Hamburg` aufgelöst.
- Komma-, Semikolon- und Konjunktionsformen sowie Statuswörter werden unterstützt.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, drei Colon-Origin-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `16df7c5b fix: parse colon origin residence labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 3547275`, Start `2026-07-18 22:02:50 CEST`.
- Seit diesem Restart: `20/20` Code-Fixes. Kein Push. Restart jetzt faellig.

## Aktueller Ledger 2026-07-18-Post-Restart

- `teebotus.service` erfolgreich neu gestartet; `ActiveState=active`, `SubState=running`, `MainPID 3246`, Start `2026-07-18 22:44:34 CEST`.
- Seit diesem Restart: `0/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Herkunft ist kein zweiter Wohnort

- `Wohnort Hamburg, Geburtsort Berlin` und `Wohnort Hamburg, meine Heimat Berlin` bleiben bei `Hamburg`.
- Der Mehrfachort-Guard ignoriert bekannte Herkunftslabels als Konfliktquelle; echte `Wohnort: Berlin, Hamburg`-Konflikte bleiben abgelehnt.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, drei Origin-Conflict-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `11f089db fix: ignore origin labels as residence conflicts`.

## Aktueller Ledger 2026-07-18-Post-Restart

- `teebotus.service` aktiv, `MainPID 3246`, Start `2026-07-18 22:44:34 CEST`.
- Seit diesem Restart: `1/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Kompakte City-vor-Label-Form

- `Hamburg mein Wohnort` und die Reverse-Herkunftsform werden erkannt.
- Bindeverben (`ist`, `war`, `bleibt`, `wird`) sowie Datumsfragmente werden nicht als Stadtteile verschluckt.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, fünf Compact-Label-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `1f29d08e fix: constrain compact residence labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- `teebotus.service` aktiv, `MainPID 3246`, Start `2026-07-18 22:44:34 CEST`.
- Seit diesem Restart: `2/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Qualifizierte kompakte Wohnortlabels

- `Hamburg ist mein momentaner/aktueller/hauptsächlicher Wohnort` und `Hamburg, mein aktueller Wohnort` werden erkannt.
- Datumsangaben wie `Am 1. Januar ...` bleiben abgelehnt.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, fünf Qualified-Label-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `5f3a9448 fix: parse qualified compact residence labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- `teebotus.service` aktiv, `MainPID 3246`, Start `2026-07-18 22:44:34 CEST`.
- Seit diesem Restart: `3/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Als-Wohnortlabels

- `Hamburg als Wohnort/Hauptwohnsitz` sowie `Als Wohnort/Wohnsitz Hamburg` werden erkannt.
- `Hamburg als Arbeitsort` bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, fünf Als-Residence-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `4a483297 fix: parse als residence labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- `teebotus.service` aktiv, `MainPID 3246`, Start `2026-07-18 22:44:34 CEST`.
- Seit diesem Restart: `4/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Kompakte Sondern-Korrektur

- `Berlin nicht, sondern Hamburg ist mein Wohnort` liefert `Hamburg` statt `sondern Hamburg`.
- Diskursmarker werden nicht als Stadtpräfix akzeptiert; Negationskorrektur bleibt priorisiert.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, zwei Sondern-Correction-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `883a7a8d fix: parse compact sondern residence correction`.

## Aktueller Ledger 2026-07-18-Post-Restart

- `teebotus.service` aktiv, `MainPID 3246`, Start `2026-07-18 22:44:34 CEST`.
- Seit diesem Restart: `5/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Wohnort-Verb-Füllwörter

- `Mein Wohnort ist eigentlich/gegenwärtig Hamburg` liefert `Hamburg` statt des Füllworts.
- Zukunftsmarker wie `künftig` bleiben abgelehnt.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, drei Residence-Filler-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `fd760b0b fix: trim residence label fillers`.

## Aktueller Ledger 2026-07-18-Post-Restart

- `teebotus.service` aktiv, `MainPID 3246`, Start `2026-07-18 22:44:34 CEST`.
- Seit diesem Restart: `6/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Vorangestellte aktuelle Adverbien

- `Eigentlich/Aktuell/Derzeit/Momentan Hamburg ist mein Wohnort` liefert `Hamburg`.
- `Nächstes Jahr Hamburg ...` bleibt als Zukunftsfragment abgelehnt.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, fünf Leading-Adverb-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `37e6c5b2 fix: reject future year residence fragments`.

## Aktueller Ledger 2026-07-18-Post-Restart

- `teebotus.service` aktiv, `MainPID 3246`, Start `2026-07-18 22:44:34 CEST`.
- Seit diesem Restart: `7/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Temporale aktuelle Wohnortlabels

- `Eigentlich ist mein Wohnort Hamburg` und `Hamburg ist noch immer mein Wohnort` werden korrekt erkannt.
- Aktuelle Marker werden erweitert; historische und künftige Marker bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, vier Temporal-Residence-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `29ed3096 fix: parse temporal current residence labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- `teebotus.service` aktiv, `MainPID 3246`, Start `2026-07-18 22:44:34 CEST`.
- Seit diesem Restart: `8/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Erweiterte aktuelle Wohnortqualifier

- `gegenwärtig`, `vorläufig`, `dauerhaft`, `temporär` und `vorübergehend` werden in `Hamburg ist ... mein Wohnort` erkannt.
- Zukunftsmarker wie `künftig` bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, sechs Current-Qualifier-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `337152d1 fix: parse extended current residence qualifiers`.

## Aktueller Ledger 2026-07-18-Post-Restart

- `teebotus.service` aktiv, `MainPID 3246`, Start `2026-07-18 22:44:34 CEST`.
- Seit diesem Restart: `9/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Qualifier nach Possessivlabel

- `Hamburg ist mein jetziges/aktuelles Zuhause` wird korrekt erkannt.
- Historische Form `früheres Zuhause` bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, drei Post-Possessive-Qualifier-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `86bace30 fix: parse post-possessive residence qualifiers`.

## Aktueller Ledger 2026-07-18-Post-Restart

- `teebotus.service` aktiv, `MainPID 3246`, Start `2026-07-18 22:44:34 CEST`.
- Seit diesem Restart: `10/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Statuswort-Grenzen bei Wohnortlabels

- `gemeldeter Wohnsitz` wird nicht mehr in `er Wohnsitz` zerlegt; `Hamburg` bleibt Ergebnis.
- Statusverben werden nur noch an vollständigen Wortgrenzen erkannt.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, sechs Status-Adjective-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `b108919e fix: enforce residence status word boundaries`.

## Aktueller Ledger 2026-07-18-Post-Restart

- `teebotus.service` aktiv, `MainPID 3246`, Start `2026-07-18 22:44:34 CEST`.
- Seit diesem Restart: `11/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Neutrale der/ein-Wohnortlabels

- `Hamburg ist der Wohnort`, `der gemeldete Wohnsitz` und `ein fester Wohnort` werden erkannt.
- `dein/ihr/deren` bleiben ausgeschlossen; `Wohnort ist daheim` wird nicht als Stadt gelesen.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, sechs Neutral-Label-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `4b69367b fix: parse neutral residence labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- `teebotus.service` aktiv, `MainPID 3246`, Start `2026-07-18 22:44:34 CEST`.
- Seit diesem Restart: `12/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Deiktische Wohnortlabels

- `Hamburg, das/dort/hier/da ist mein Wohnort/Zuhause` wird erkannt.
- `Arbeitsort` bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, fünf Deictic-Residence-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `263fc772 fix: parse deictic residence labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- `teebotus.service` aktiv, `MainPID 3246`, Start `2026-07-18 22:44:34 CEST`.
- Seit diesem Restart: `13/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Zukunfts-/Unsicherheitspräfixe

- `Wohnort ist voraussichtlich/künftig/zukünftig Berlin` wird nicht als aktueller Wohnort gespeichert.
- `Wohnort ist wieder Potsdam` bleibt als aktuelle Behauptung gültig.
- Verifikation: `tests/test_weather_context.py` -> `147 passed`, fünf Future-Confidence-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `0265fa9d fix: reject future residence claims`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 2727920`, Start `2026-07-18 21:08:53 CEST`.
- Seit diesem Restart: `14/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Explizite Antwortpräfixe

- `Wo wohnst du? Antwort: Berlin`, `Antwort ist Hamburg` und `Antwort lautet: in Potsdam` werden korrekt extrahiert.
- Mehrfachorte im Antworttext bleiben durch die bestehende Ambiguitätsprüfung gesperrt.
- Verifikation: `tests/test_weather_context.py` -> `148 passed`, vier Answer-Prefix-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `959e2804 fix: parse explicit residence answer prefixes`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 2727920`, Start `2026-07-18 21:08:53 CEST`.
- Seit diesem Restart: `15/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Ungeklärte Labelzustände

- `Wohnort ist momentan unklar`, `aktuell unbekannt`, `derzeit egal` und `daheim` werden nicht als Orte gespeichert.
- Bestätigte temporale Angaben wie `Wohnort ist aktuell Berlin` bleiben gültig.
- Verifikation: `tests/test_weather_context.py` -> `149 passed`, fünf unresolved-state-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `d9f51922 fix: reject unresolved residence label states`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 2727920`, Start `2026-07-18 21:08:53 CEST`.
- Seit diesem Restart: `16/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Inverse Herkunfts-/Wohnortlabels

- `Berlin ist meine Heimat, Hamburg mein Wohnort` und die Variante mit `Geburtsort` liefern jetzt `Hamburg` als aktuellen Wohnort.
- Herkunft wird nicht als aktueller Wohnort überschrieben.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, zwei inverse-Origin-Residence-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `602f6199 fix: parse inverse origin residence labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 3547275`, Start `2026-07-18 22:02:50 CEST`.
- Seit diesem Restart: `4/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Herkunftslabel mit Konjunktion

- `Berlin ist meine Heimat und Hamburg mein Wohnort` sowie die Form mit `Geburtsort` und `ist` liefern `Hamburg`.
- Komma- und Konjunktionsform nutzen dieselbe aktuelle-Wohnort-Regel.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, zwei Konjunktions-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `aa14d99a fix: parse conjunction origin residence labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 3547275`, Start `2026-07-18 22:02:50 CEST`.
- Seit diesem Restart: `5/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Qualifizierte Herkunftslabels

- `frühere/fruehere/ehemalige/alte Heimat` und entsprechende Geburtsort-/Geburtsstadtformen werden als Herkunft erkannt; aktueller Wohnort bleibt Ergebnis.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, drei historische-Herkunfts-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `86d7e315 fix: parse qualified origin residence labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 3547275`, Start `2026-07-18 22:02:50 CEST`.
- Seit diesem Restart: `6/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Herkunftsstadt-Synonyme

- `Herkunftsort`, `Herkunftsstadt` und `Heimatstadt` werden wie Geburts-/Heimatlabels behandelt.
- Bei kombiniertem Herkunfts- und Wohnort bleibt aktueller Wohnort Ergebnis.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, zwei Herkunftssynonym-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `b37ee534 fix: parse origin city synonyms`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 3547275`, Start `2026-07-18 22:02:50 CEST`.
- Seit diesem Restart: `7/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Vergangenheitsform bei Herkunftslabels

- `Berlin war meine Heimat/Geburtsort, Hamburg mein Wohnort` liefert den aktuellen Wohnort `Hamburg`.
- `war` wird nur im expliziten Herkunft-zu-Wohnort-Muster akzeptiert; historische Einzelangaben bleiben geschützt.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, zwei Past-Origin-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `31a84537 fix: parse past origin residence labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 3547275`, Start `2026-07-18 22:02:50 CEST`.
- Seit diesem Restart: `8/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Sowie-Trennung bei Herkunftslabels

- `Berlin ist meine Heimat sowie Hamburg mein Wohnort` wird wie die klar disambiguierte `und`-Form gelesen.
- Allgemeine Mehrfachwohnorte bleiben unverändert geschützt.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, ein Sowie-Origin-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `1616c03f fix: parse sowie origin residence labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 3547275`, Start `2026-07-18 22:02:50 CEST`.
- Seit diesem Restart: `9/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Kontrastmarker bei Herkunftslabels

- `aber`, `doch` und `jedoch` zwischen Herkunft und aktuellem Wohnort werden korrekt übersprungen.
- Das Muster bleibt auf explizite Herkunft-/Wohnortpaare begrenzt; Mehrfachwohnorte ohne Labels bleiben geschützt.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, drei Kontrastmarker-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a9a523e6 fix: parse contrastive origin residence labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 3547275`, Start `2026-07-18 22:02:50 CEST`.
- Seit diesem Restart: `10/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Alternative Gegenstellungsmarker

- `dafür ist` und `stattdessen ist` werden zwischen Herkunft und aktuellem Wohnort korrekt übersprungen.
- Die Regel bleibt auf explizite Herkunft-/Wohnortpaare beschränkt.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, zwei Alternative-Contrast-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `b407b9a2 fix: parse alternative origin residence markers`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 3547275`, Start `2026-07-18 22:02:50 CEST`.
- Seit diesem Restart: `11/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Während-Trennung bei Herkunftslabels

- `Berlin ist meine Heimat, während Hamburg mein Wohnort ist` wird korrekt auf `Hamburg` aufgelöst.
- Komma- und direkte Während-Form werden unterstützt; Mehrfachwohnorte ohne Rollenlabels bleiben geschützt.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, zwei Während-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `cb70217d fix: parse waehrend origin residence labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 3547275`, Start `2026-07-18 22:02:50 CEST`.
- Seit diesem Restart: `12/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Herkunftsnegation mit Korrektur

- `Berlin ist meine Heimat, dort wohne ich nicht, sondern in Hamburg` liefert `Hamburg`.
- Herkunft wird als Negativkontext behandelt; `sondern in ...` wird als aktuelle Korrektur erkannt.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, ein Origin-Negation-Correction-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `10f57cba fix: parse origin negation corrections`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 3547275`, Start `2026-07-18 22:02:50 CEST`.
- Seit diesem Restart: `13/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Negierte Wohnortwechsel

- `Mein Wohnort ist keinesfalls Berlin, sondern Hamburg` liefert jetzt den aktuellen Ort `Hamburg`.
- `nicht ... aber ich arbeite in Hamburg` bleibt leer; Arbeitsort wird nicht als Wohnort umgedeutet.
- Verifikation: `tests/test_weather_context.py` -> `150 passed`, drei negated-label-change-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `79bc2e7c fix: resolve negated residence label changes`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 2727920`, Start `2026-07-18 21:08:53 CEST`.
- Seit diesem Restart: `17/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Inverse Wohnortlabel-Wechsel

- `Nicht mehr Berlin, jetzt Hamburg ist mein Wohnort` und `... ist mein Wohnsitz` werden erkannt.
- Enger Lookahead verhindert, dass `ist mein Wohnort` in Stadtwert gelangt.
- Verifikation: `tests/test_weather_context.py` -> `151 passed`, zwei inverse-label-change-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `d389bccb fix: parse inverted residence label changes`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 2727920`, Start `2026-07-18 21:08:53 CEST`.
- Seit diesem Restart: `18/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Temporale Wohnort-Suffixe

- `Wohnort Berlin ab morgen/künftig/früher` wird nicht als aktueller Wohnort gespeichert.
- `Wohnort Berlin seit heute/ab sofort` bleibt gültig; Roh-City-Suffixe werden vor Normalisierung geprüft.
- Verifikation: `tests/test_weather_context.py` -> `152 passed`, sechs temporal-suffix-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `3b72eacf fix: validate temporal residence suffixes`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 2727920`, Start `2026-07-18 21:08:53 CEST`.
- Seit diesem Restart: `19/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Temporale Bare-Labels

- `Mein Wohnort seit kurzem Berlin`, `Wohnort seit heute Hamburg` und `Wohnort: seit 2020 Potsdam` liefern den Ort statt Zeitfragment.
- Zukunftsform `Wohnort ab morgen Berlin` bleibt leer.
- Verifikation: `tests/test_weather_context.py` -> `153 passed`, vier temporal-bare-label-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `f381e649 fix: parse temporal residence labels`.

## Aktueller Ledger 2026-07-18-Vor-Restart

- Service bisher aktiv, `MainPID 2727920`, Start `2026-07-18 21:08:53 CEST`.
- Seit diesem Restart: `20/20` Code-Fixes. Kein Push.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 3547275`, Start `2026-07-18 22:02:50 CEST`.
- Seit diesem Restart: `0/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Erweiterte Ortsfragen

- `Wo genau wohnst du`, `Wo in Deutschland wohnst du`, `In welcher Stadt wohnst du` und `An welchem Ort lebst du` werden mit Antwort erkannt.
- Unbeantwortete Fragen und Mehrfachorte bleiben leer.
- Verifikation: `tests/test_weather_context.py` -> `154 passed`, sieben expanded-question-Smokes plus drei Mehrfachziel-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `257f698c fix: parse expanded residence questions`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 3547275`, Start `2026-07-18 22:02:50 CEST`.
- Seit diesem Restart: `1/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Explizite Nein-Korrekturen

- `Nein, nicht Berlin, sondern Hamburg` und `Nein: nicht in Berlin, sondern in Potsdam` liefern aktuellen Ort.
- Ein Arbeitsort-Nachsatz wie `ich arbeite in Hamburg` wird nicht als Wohnort übernommen.
- Verifikation: `tests/test_weather_context.py` -> `155 passed`, drei No-Correction-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `37035bd9 fix: parse explicit no residence corrections`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 3547275`, Start `2026-07-18 22:02:50 CEST`.
- Seit diesem Restart: `2/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Kurze Klarstellungsmarker

- `Wohnort ist Deutschland, genauer Berlin` und die `Mein Wohnort`-Variante werden erkannt.
- `genauer` funktioniert jetzt auch ohne ausgeschriebenes `gesagt`.
- Verifikation: `tests/test_weather_context.py` -> `156 passed`, zwei short-clarification-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c391d2a3 fix: parse short residence clarification markers`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 3547275`, Start `2026-07-18 22:02:50 CEST`.
- Seit diesem Restart: `3/20` Code-Fixes. Kein Push.
- Code-Fixes seit Restart: `8afef100`, `9ef3aff0`, `d10f95a1`, `7c18b6ee`, `5d08d5c4`, `a823e158`, `3c36731b`, `f84eb2e7`, `6c4eecd2`, `63c551d1`, `823d5753`, `7b9cf67a`, `706fcb48`.
- Naechster Restart bei `20/20`; Push nur nach ausdruecklicher Anweisung.

### Folgefix 2026-07-18: Plurale Wohnortwechsel und Aktivitaetsorte disambiguieren

- `Seit 2020 wohnen wir ...` und `Wir wohnen nicht ..., sondern ...` werden jetzt erkannt.
- `Wir wohnen in Berlin und leben in Hamburg` bleibt bewusst unbestimmt; Arbeits- und Studienorte werden nicht mehr als zweiter Wohnort fehlklassifiziert.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `bed7a733 fix: disambiguate plural residence statements`.

## Aktueller Ledger 2026-07-18-True-Tail-Final

- Letzter Restart: `systemctl --user restart teebotus.service`, aktiv, `MainPID 3950560`, Start `2026-07-18 04:59:30 CEST`.
- Seit diesem Restart: `14/20` Code-Fixes. Kein Push.
- Naechster Restart bei `20/20`; Push nur nach ausdruecklicher Anweisung.

### Folgefix 2026-07-18: Plurale Wohnortkorrekturen und Ansässigkeit

- Getrennte Formen wie `Wir wohnen nicht mehr in Berlin. Jetzt in Hamburg` und historische Formen wie `Wir wohnten in Berlin, jetzt in Hamburg` werden erkannt.
- `ansässig`/`ansaessig` ist jetzt auch für `wir sind ...` gültig.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `5669073b fix: parse plural residence changes`.

## Aktueller Ledger 2026-07-18-True-Tail-Final

- Letzter Restart: `systemctl --user restart teebotus.service`, aktiv, `MainPID 3950560`, Start `2026-07-18 04:59:30 CEST`.
- Seit diesem Restart: `15/20` Code-Fixes. Kein Push.
- Naechster Restart bei `20/20`; Push nur nach ausdruecklicher Anweisung.

### Folgefix 2026-07-18: Plurale relationale Wohnortangaben

- `Wir leben in der Nähe von Berlin`, `im Raum München`, `nahe Hamburg` und `rund um Köln` werden jetzt erkannt.
- `Wir sind dort in Potsdam ansässig` akzeptiert den Ortsadverb-Kontext.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `dc123d33 fix: parse plural relational residences`.

## Aktueller Ledger 2026-07-18-True-Tail-Final

- Letzter Restart: `systemctl --user restart teebotus.service`, aktiv, `MainPID 3950560`, Start `2026-07-18 04:59:30 CEST`.
- Seit diesem Restart: `16/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Frage-Antwort-Wohnortformen

- `Wo wohnst du? Berlin`, `Wohnort? Potsdam`, `Wohnsitz? Dresden`, `Adresse? Bonn` und `Wo ist dein Wohnort? Berlin` werden korrekt erkannt.
- Reine Fragen wie `Wohnst du in Hamburg?` bleiben leer; eine Frage wird nicht als bestätigter Wohnort gespeichert.
- Verifikation: `tests/test_weather_context.py` -> `135 passed`, sechs Question-Answer-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `1580a5a1 fix: parse residence question answer forms`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 1590772`, Start `2026-07-18 19:56:08 CEST`.
- Seit diesem Restart: `17/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Frage-Antworten mit Doppelpunkt

- `Wo wohnst du: Berlin`, `Wohnort ist? Potsdam` und `Dein Wohnort: Bonn` werden als Antwortformen erkannt.
- Der Frage-Antwort-Parser akzeptiert jetzt `?` oder `:`; reine Fragen wie `Wo wohnst du?` und `Ist dein Wohnort Berlin?` bleiben leer.
- Verifikation: `tests/test_weather_context.py` -> `135 passed`, erweiterte Question-Answer-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `ba76df8e fix: parse colon residence questions`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 1590772`, Start `2026-07-18 19:56:08 CEST`.
- Seit diesem Restart: `18/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Erweiterte Frage-Antwort-Wohnortformen

- `Wo ist dein Zuhause? Berlin` und `Wo wohnst du eigentlich: in Hamburg` nutzen nun dieselbe sichere Antwortlogik wie `Wohnort? Berlin`.
- Unterstützt werden zusätzliche Wohnortlabels, optionale Füllwörter und das Präfix `in/bei`; unbeantwortete Fragen bleiben leer.
- Verifikation: `tests/test_weather_context.py` -> `135 passed`, zwei erweiterte Question-Answer-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `f4aabf7e fix: parse expanded residence questions`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 1590772`, Start `2026-07-18 19:56:08 CEST`.
- Seit diesem Restart: `19/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Mehrfachziele in Frage-Antworten

- Antworten wie `Wo wohnst du? Berlin und Hamburg` oder `Berlin oder Potsdam` werden nicht mehr still auf ersten Ort gekürzt.
- Ein einzelner Ort mit Kontext `Berlin und Umgebung` bleibt gültig.
- Verifikation: `tests/test_weather_context.py` -> `135 passed`, drei Ambiguitäts-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a04e6046 fix: reject multiple residence question targets`.

## Aktueller Ledger 2026-07-18-Vor-Restart

- Service bisher aktiv, `MainPID 1590772`, Start `2026-07-18 19:56:08 CEST`.
- Seit diesem Restart: `20/20` Code-Fixes. Kein Push.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 2727920`, Start `2026-07-18 21:08:53 CEST`.
- Seit diesem Restart: `0/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Wohnort-Label-Füller

- `Wohnort bitte: Berlin` und `Wohnort aktuell Berlin` liefern jetzt `Berlin`, statt Fülltext als Stadt zu speichern.
- `Wohnort bitte` ohne Ortswert bleibt leer; ältere breite Pattern können `bitte` nicht mehr als Ort durchreichen.
- Verifikation: `tests/test_weather_context.py` -> `136 passed`, drei Label-Filler-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c79d3ef8 fix: skip residence label fillers`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 2727920`, Start `2026-07-18 21:08:53 CEST`.
- Seit diesem Restart: `1/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Wohnstatus-Frageformen

- `Wo bist du wohnhaft/ansässig? Berlin` sowie `Wo ist deine Wohnadresse/Meldeadresse? Potsdam` werden als beantwortete Wohnortfragen erkannt.
- Die Mehrfachzielprüfung nutzt dieselben neuen Frageformen; reine Fragen bleiben leer.
- Verifikation: `tests/test_weather_context.py` -> `136 passed`, vier Wohnstatus-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `8dacb769 fix: parse residence status questions`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 2727920`, Start `2026-07-18 21:08:53 CEST`.
- Seit diesem Restart: `2/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Meldeadress-Evidenz als Fülltext

- `Wohnort ist laut Meldeadresse Berlin` und `laut der Adresse Hamburg` speichern jetzt nur den Ort.
- Der vorhandene direkte Label-Parser überspringt dafür den expliziten Evidenz-Füller; keine Provider/API-Aufrufe.
- Verifikation: `tests/test_weather_context.py` -> `137 passed`, zwei Registration-Evidence-Smokes, `py_compile` und `git diff --check` gruen.
- Code-Commit: `20d72ada fix: parse residence registration evidence`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 2727920`, Start `2026-07-18 21:08:53 CEST`.
- Seit diesem Restart: `3/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Unzuverlässige Label-Füller

- `Wohnort ist laut Wikipedia/User Berlin` wird nicht mehr als Stadt gespeichert.
- `Wohnort: derzeitig Berlin` funktioniert; Füller vor und nach `:` werden vollständig entfernt, ohne Präfixrest `ig Berlin`.
- Verifikation: `tests/test_weather_context.py` -> `138 passed`, drei Untrusted-Filler-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `1ae5bea5 fix: reject untrusted residence label fillers`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 2727920`, Start `2026-07-18 21:08:53 CEST`.
- Seit diesem Restart: `4/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Mehrfachziele in Bare-Labels

- `Wohnort Berlin und Hamburg` wird nicht mehr still auf `Berlin` gekürzt.
- `Berlin und Umgebung` bleibt als einzelner Ortskontext gültig; Arbeitskontext nach `und` bleibt ebenfalls geschützt.
- Verifikation: `tests/test_weather_context.py` -> `139 passed`, drei Bare-Label-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e3283b72 fix: reject bare residence label conflicts`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 2727920`, Start `2026-07-18 21:08:53 CEST`.
- Seit diesem Restart: `5/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Confidence-Adverbien in Labels

- `Wohnort ist wahrscheinlich/wohl Berlin` wird verworfen, statt Unsicherheit als Fakt zu speichern.
- `Wohnort ist sicher/tatsächlich Berlin` entfernt das Adverb und speichert `Berlin`.
- Verifikation: `tests/test_weather_context.py` -> `140 passed`, vier Confidence-Label-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `8a67af00 fix: normalize residence confidence labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 2727920`, Start `2026-07-18 21:08:53 CEST`.
- Seit diesem Restart: `6/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Nachgestellte Evidenzhinweise

- `Wohnort: Berlin laut Meldeadresse/Profil` wird auf `Berlin` gekürzt.
- Führende unzuverlässige Quellenangaben wie `laut Wikipedia Berlin` bleiben verworfen.
- Verifikation: `tests/test_weather_context.py` -> `141 passed`, zwei Trailing-Evidence-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `920e5ff8 fix: trim trailing residence evidence`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 2727920`, Start `2026-07-18 21:08:53 CEST`.
- Seit diesem Restart: `7/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Direkte Registrierungslabels

- `Gemeldet: Frankfurt`, `Registriert: Leipzig` und `Aktuell gemeldet in Hamburg` werden jetzt erkannt.
- Historische Formen bleiben leer; Mehrfachziele wie `gemeldet in Berlin und Hamburg` werden abgewiesen.
- Verifikation: `tests/test_weather_context.py` -> `142 passed`, vier Registration-Label-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `fee5721e fix: parse direct registration labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 2727920`, Start `2026-07-18 21:08:53 CEST`.
- Seit diesem Restart: `8/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Punktuierte Q&A-Mehrfachziele

- `Wo wohnst du? Berlin, Hamburg` und `Berlin; Hamburg` werden nicht mehr auf ersten Ort gekürzt.
- `Berlin, Deutschland` bleibt als Ort plus Land gültig; Klarstellungs- und Adresspfade werden nicht überdehnt.
- Verifikation: `tests/test_weather_context.py` -> `143 passed`, drei punctuated-question-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `445b929d fix: reject punctuated residence question conflicts`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 2727920`, Start `2026-07-18 21:08:53 CEST`.
- Seit diesem Restart: `9/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Doppelte Wohnort-Memorys

- `_append_city_memory` dedupliziert gleiche `mem_residence_city_*`-IDs statt sie bei erneutem Hinweis liegenzulassen.
- Aktueller Wohnort bleibt erhalten, alte Wohnorte werden weiterhin entfernt; Schreibfehler behalten Rollback-Verhalten.
- Verifikation: `tests/test_weather_context.py` -> `144 passed`, ein Duplicate-Memory-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `0ab037f3 fix: deduplicate residence city memories`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 2727920`, Start `2026-07-18 21:08:53 CEST`.
- Seit diesem Restart: `10/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Fremde Wohnortlabels

- `Der/Sein/Ihr/Deren Wohnort/Zuhause` wird nicht mehr als Nutzer-Wohnort gespeichert.
- Präfixprüfung funktioniert auch, wenn Pattern an Leerzeichengrenzen starten; `Unser Wohnort` bleibt gültig.
- Verifikation: `tests/test_weather_context.py` -> `145 passed`, fünf Third-Party-Label-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `9c102dca fix: reject third-party residence labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 2727920`, Start `2026-07-18 21:08:53 CEST`.
- Seit diesem Restart: `11/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Fremde Possessivbehauptungen

- `Dein/Euer Wohnort ist ...` wird als fremde Behauptung verworfen.
- Antwortlabel `Dein Wohnort: Bonn` bleibt kompatibel; `Mein/Unser Wohnort` bleibt gültig.
- Verifikation: `tests/test_weather_context.py` -> `145 passed`, sechs Besitzlabel-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `65b8dbe3 fix: reject possessive third-party claims`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 2727920`, Start `2026-07-18 21:08:53 CEST`.
- Seit diesem Restart: `12/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Negierte feste Wohnorte

- `Kein fester Wohnort: Berlin` und `Keinen festen Wohnsitz: Hamburg` werden nicht mehr als Wohnortfakt übernommen.
- Der Präfixschutz funktioniert auch bei Pattern-Start direkt vor dem Label; positive `Mein Wohnort`-Labels bleiben gültig.
- Verifikation: `tests/test_weather_context.py` -> `146 passed`, drei Negation-Label-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `59be2873 fix: reject fixed residence negations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 2727920`, Start `2026-07-18 21:08:53 CEST`.
- Seit diesem Restart: `13/20` Code-Fixes. Kein Push.
- Naechster Restart bei `20/20`; Push nur nach ausdruecklicher Anweisung.

### Folgefix 2026-07-18: Letzten Wohnort bei Mehrfachwechseln wählen

- Mehrere Wechsel in einer Nachricht (`Berlin -> Hamburg -> Potsdam`) lieferten bisher den ersten aktuellen Ort.
- Treffer werden jetzt zusätzlich auf Satzsuffixen gesammelt und nach absoluter Position bewertet; Aktivitätsorte wie `arbeite jetzt in` bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `4c3616c3 fix: prefer latest residence mention`.

## Aktueller Ledger 2026-07-18-True-Tail-Final

- Letzter Restart: `systemctl --user restart teebotus.service`, aktiv, `MainPID 3950560`, Start `2026-07-18 04:59:30 CEST`.
- Seit diesem Restart: `17/20` Code-Fixes. Kein Push.
- Naechster Restart bei `20/20`; Push nur nach ausdruecklicher Anweisung.

### Folgefix 2026-07-18: Wiederholte Wohnortmarker erkennen

- `Jetzt wohne ich wieder in Hamburg` wurde wegen `wieder` zwischen Verb und Präposition bisher übersehen.
- `wieder` und `erneut` sind jetzt Zeitqualifizierer; Aktivitätsformen wie `arbeite wieder in` bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `dd95eebf fix: parse repeated residence markers`.

## Aktueller Ledger 2026-07-18-True-Tail-Final

- Letzter Restart: `systemctl --user restart teebotus.service`, aktiv, `MainPID 3950560`, Start `2026-07-18 04:59:30 CEST`.
- Seit diesem Restart: `18/20` Code-Fixes. Kein Push.
- Naechster Restart bei `20/20`; Push nur nach ausdruecklicher Anweisung.

### Folgefix 2026-07-18: Plurale Abhängigkeit-Wohnorte erkennen

- `Wir wohnen bei unseren Eltern in Köln` wurde bisher als `unseren Eltern` statt als Stadt erkannt.
- Ein pluraler `bei ... in Stadt`-Pfad behandelt Eltern/Familie und Zeitqualifizierer korrekt.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `2cf7ea37 fix: parse plural dependent residence`.

## Aktueller Ledger 2026-07-18-True-Tail-Final

- Letzter Restart: `systemctl --user restart teebotus.service`, aktiv, `MainPID 3950560`, Start `2026-07-18 04:59:30 CEST`.
- Seit diesem Restart: `19/20` Code-Fixes. Kein Push.
- Naechster Restart bei `20/20`; Push nur nach ausdruecklicher Anweisung.

### Folgefix 2026-07-18: Plurale Begleit-Wohnorte erkennen

- `Wir wohnen zusammen mit unseren Eltern in Leipzig` und `mit unseren Kindern in München` wurden bisher nicht erkannt.
- Ein pluraler `mit ... in Stadt`-Pfad ergänzt den bestehenden `bei ... in Stadt`-Pfad.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `eaaadeb9 fix: parse plural companion residences`.

## Aktueller Ledger 2026-07-18-True-Tail-Final

- Letzter Restart: steht nach diesem `20/20`-Fix an.
- Seit letztem Restart: `20/20` Code-Fixes. Kein Push.
- Restart jetzt ausführen; danach Zähler `0/20`.

## Aktueller Ledger 2026-07-18-Post-Restart

- `systemctl --user restart teebotus.service` erfolgreich.
- Service aktiv, `MainPID 620028`, Start `2026-07-18 05:52:25 CEST`.
- Neuer Zähler seit diesem Restart: `0/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Gemeinsame Wohnortlabels disambiguieren

- `Wir wohnen in Berlin und unser Wohnort ist Hamburg` wurde verworfen; `Unser Wohnort ist Berlin und Hamburg` wurde als Berlin übernommen.
- Explizite gemeinsame Wohnortlabels werden jetzt als letzter Wohnort berücksichtigt; Arbeitsortzusätze bleiben erlaubt, echte Doppelorte bleiben leer.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `25f2d3b2 fix: disambiguate shared residence labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 620028`, Start `2026-07-18 05:52:25 CEST`.
- Seit diesem Restart: `1/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Aktivitätsfragmente nicht als Wohnort werten

- `Jetzt in Hamburg arbeite ich` und `Inzwischen bei Hamburg arbeite ich` wurden als Wohnort erkannt.
- Aktivitätsverben werden in bereinigten City-Kandidaten verworfen; reine Kurzformen `Jetzt in Hamburg` bleiben gültig.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `0a858e46 fix: reject activity fragments as residences`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 620028`, Start `2026-07-18 05:52:25 CEST`.
- Seit diesem Restart: `2/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Kontextuelle aktuelle Wohnorte erkennen

- `Jetzt bei/mit ... in Hamburg`, `Jetzt im Raum Hamburg` und `Jetzt in Hamburg wohnhaft` wurden bisher nicht als aktueller Wohnort erkannt.
- Entsprechende Markerpfade ergänzt; `Jetzt in Hamburg bin ich im Urlaub` wird nicht als Wohnort übernommen.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `34922e53 fix: parse contextual current residences`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 620028`, Start `2026-07-18 05:52:25 CEST`.
- Seit diesem Restart: `3/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Singuläre Begleit-Wohnorte erkennen

- `Ich wohne zusammen mit meinen Eltern in Leipzig` und `Ich lebe mit Freunden in Dresden` wurden bisher nicht erkannt.
- Der singuläre `mit ... in Stadt`-Pfad ergänzt den pluralen Begleitpfad; mehrere Wohnanker bleiben unklar.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `3127b287 fix: parse singular companion residences`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 620028`, Start `2026-07-18 05:52:25 CEST`.
- Seit diesem Restart: `4/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Arbeits- und Studienkontext im Markerpfad sperren

- `... jetzt mit meiner Arbeit/mit meinem Studium in Hamburg` wurde als Wohnortwechsel fehlklassifiziert.
- Arbeits-, Studien- und Ausbildungsbegriffe werden im `bei/mit ... in Stadt`-Kontext ausgeschlossen; Familienkontext bleibt gültig.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `15cb01d6 fix: reject study context as residence`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 620028`, Start `2026-07-18 05:52:25 CEST`.
- Seit diesem Restart: `5/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Vorübergehende Reiseorte aus Wohnortwahl ausschließen

- `auf/im/zum Urlaub`, `als Tourist` und `zu Besuch` wurden als Wohnortwechsel übernommen.
- Besuchs- und Urlaubskontext wird nur im jeweiligen Satz ausgeschlossen; bestehende Wohnortangaben und `wohnhaft` bleiben gültig.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `0059d3c6 fix: ignore transient travel locations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 620028`, Start `2026-07-18 05:52:25 CEST`.
- Seit diesem Restart: `6/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Negierte und spätere Connector-Wohnorte

- `sondern bei ... in Stadt`, Label-Korrekturen mit `sondern bei` und `wohne aber bei` nach einem Umzug wurden bisher nicht oder falsch erkannt.
- Eigene Connectorpfade priorisieren den letzten expliziten Wohnanker; Arbeits- und Doppelwohnorte bleiben geschützt.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `3b0a2a39 fix: parse residence connector corrections`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 620028`, Start `2026-07-18 05:52:25 CEST`.
- Seit diesem Restart: `7/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Pendel- und `sind in`-Kontexte disambiguieren

- `pendeln` wurde wegen eines falschen Regex-Stamms als unklarer zweiter Wohnort gewertet.
- `Wir wohnen ... und sind in ...` bleibt unklar; `sind beruflich in ...` und Pendeln bleiben Aktivitätszusätze.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `753640a9 fix: refine residence activity disambiguation`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 620028`, Start `2026-07-18 05:52:25 CEST`.
- Seit diesem Restart: `8/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Region-/Land-Präfixe mit konkreter Stadt

- `in Deutschland, in Berlin`, `im Bundesland Bayern, in München` und `im Raum Berlin, in Potsdam` lieferten bisher Land/Region oder keinen Ort.
- Spezifischer Präfixpfad wählt konkrete Stadt; `Berlin, in Deutschland` bleibt beim Wohnort Berlin.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `95cc502f fix: parse regional residence qualifiers`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 620028`, Start `2026-07-18 05:52:25 CEST`.
- Seit diesem Restart: `9/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Regionale Wohnortwechsel priorisieren

- `Jetzt lebe ich in Deutschland, in Hamburg`, `im Raum Berlin, in Potsdam` und `bin ... wohnhaft` lieferten bisher Region/Land oder den alten Ort.
- Regionale Präfixe sind jetzt auch im Änderungszweig aktiv; konkrete Stadt gewinnt.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `0d4f416d fix: parse regional residence changes`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 620028`, Start `2026-07-18 05:52:25 CEST`.
- Seit diesem Restart: `10/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Aktuelle Wohnsitz-Synonyme

- `Ich residiere in Berlin`, `Ich bin in Leipzig gemeldet` und `Meine Bleibe ist in Potsdam` wurden bisher nicht erkannt.
- Diese aktuellen Wohnsitzformulierungen sind ergänzt; `beheimatet/heimisch` bleibt wegen Herkunftssemantik ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `be6c8f3f fix: parse residence synonym phrases`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 620028`, Start `2026-07-18 05:52:25 CEST`.
- Seit diesem Restart: `11/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Länder nicht als Städte speichern

- `Ich wohne in Deutschland/Österreich/der Schweiz` wurde bisher als City-Kandidat akzeptiert.
- Bekannte Länderbezeichnungen werden bei alleiniger Angabe verworfen; Land-plus-Stadt bleibt gültig.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `4e2347f4 fix: reject country-only residence candidates`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 620028`, Start `2026-07-18 05:52:25 CEST`.
- Seit diesem Restart: `12/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Präzisierende Land-/Regionsangaben

- `genauer gesagt`, `nämlich`, `und zwar`, `konkret` und ähnliche Präzisierungen nach Land/Region wurden bisher nicht bis zur Stadt verfolgt.
- Der bestehende Land-/Regionspfad akzeptiert diese Connectoren jetzt.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `7fa58a1b fix: parse residence clarification connectors`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 620028`, Start `2026-07-18 05:52:25 CEST`.
- Seit diesem Restart: `13/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Ortsdescriptoren mit konkreter Stadt

- `auf dem Land bei/in`, `Kleinstadt/Dorf nahe` sowie `Großstadt/Stadt, nämlich` wurden bisher nicht bis zur konkreten Stadt verfolgt.
- Der Descriptorpfad akzeptiert diese Ortsbeschreibung nur mit nachfolgender Stadt; alleinige Aussagen wie `Ich wohne auf dem Land` bleiben leer.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, 9 Descriptor-Smoke-Checks, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `bad7cf4e fix: parse residence place descriptors`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 620028`, Start `2026-07-18 05:52:25 CEST`.
- Seit diesem Restart: `14/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Aktuelle und flektierte Ortsdescriptoren

- Descriptoren mit `Jetzt`/`aktuell`, Pronomen nach dem Verb, Komma-Connectoren sowie `kleinen/großen Stadt` wurden bisher nicht erkannt.
- Unbestimmte Angaben wie `ohne konkrete Angabe` werden nicht mehr als Stadt gespeichert.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, 6 gezielte Current/Inflection/Negative-Smoke-Checks, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `6bee6c60 fix: handle current residence descriptors`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 620028`, Start `2026-07-18 05:52:25 CEST`.
- Seit diesem Restart: `15/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Siedlungsdescriptoren und Nähe-Relationen

- `im Dorf`, `kleines Dorf`, `Vorort/Vorstadt`, `Mein Wohnort ist ein Dorf` und `auf dem Land in der Nähe von ...` wurden bisher nicht erkannt.
- Spezifische Relationen werden vor dem generischen `in` geprüft; unvollständige Descriptoren ohne konkrete Stadt bleiben leer.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, 8 gezielte Settlement-Smoke-Checks, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e686876c fix: parse settlement residence descriptors`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 620028`, Start `2026-07-18 05:52:25 CEST`.
- Seit diesem Restart: `16/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Benennungsformulierungen für Wohnorte

- `Ort namens Berlin`, `Stadt genannt Hamburg` und `Mein Wohnort nennt sich Berlin` wurden bisher nicht sauber extrahiert.
- Namenspräfixe werden vor dem City-Feld entfernt; Negationen wie `nennt sich nicht ...` bleiben leer.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, 4 Naming-Smoke-Checks, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `2b6db020 fix: parse residence naming phrases`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 620028`, Start `2026-07-18 05:52:25 CEST`.
- Seit diesem Restart: `17/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Verkettete Wohnort-Qualifier

- Kombinationen wie `inzwischen dauerhaft`, `nur vorübergehend`, `seit 2020 dauerhaft` und `hier weiterhin` wurden bisher nicht bis zur Stadt verfolgt.
- Wiederholbare Zeit-/Ortsqualifier sind ergänzt; Urlaubskontext bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, 5 Qualifier-Chain-Smoke-Checks, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `0e7de60a fix: parse chained residence qualifiers`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 620028`, Start `2026-07-18 05:52:25 CEST`.
- Seit diesem Restart: `18/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Eigene Wohnadressformulierungen

- `Meine Adresse/Wohnadresse liegt in ...` und `Ich habe meine Anschrift in ...` wurden bisher nicht als Wohnort erkannt.
- Unqualifizierte eigene Wohnadresse/Anschrift ist ergänzt; Negationen und Geschäftsadressen bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, 5 Address-Smoke-Checks, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `5c6fd8c3 fix: parse residence address phrases`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 620028`, Start `2026-07-18 05:52:25 CEST`.
- Seit diesem Restart: `19/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Aktuelle Wohnadressen

- `aktuelle/jetzige Wohnadresse`, `derzeitige Anschrift` und vergleichbare aktuelle Adressangaben wurden bisher nicht erkannt.
- Aktuelle Adjektive sind erlaubt; `alte Adresse` bleibt bewusst ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, 4 Current-Address-Smoke-Checks, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a88975b1 fix: parse current residence addresses`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 620028`, Start `2026-07-18 05:52:25 CEST`.
- Seit diesem Restart: `20/20` Code-Fixes. Restart jetzt fällig. Kein Push.

## Aktueller Ledger 2026-07-18-Post-Restart

- `teebotus.service` nach 20 Code-Fixes erfolgreich neugestartet.
- Service aktiv, `MainPID 1480061`, Start `2026-07-18 06:45:34 CEST`.
- Seit diesem Restart: `0/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Negierte Wohnortalternativen

- `Ich wohne in Berlin und nicht in Hamburg` wurde fälschlich als mehrdeutiger Doppelwohnsitz verworfen.
- Negierter zweiter Ort wird jetzt als Ausschluss behandelt; zwei positive Wohnorte bleiben weiterhin leer.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, 4 Residence-Negation-Smoke-Checks, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c27bd5f0 fix: distinguish negated residence alternatives`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 1480061`, Start `2026-07-18 06:45:34 CEST`.
- Seit diesem Restart: `1/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Vergangene Wohnstatus nicht übernehmen

- `Ich war wohnhaft/ansässig in ...` wurde durch den freistehenden Statuspfad fälschlich als aktueller Wohnort gespeichert.
- Freistehende `Wohnhaft/Ansässig in ...`-Formen benötigen jetzt Satzanfang oder sicheren `bin/sind`-Präfix; `war/früher/ehemals` bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, 8 Past/Current-Wohnhaft-Smoke-Checks, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `caea6f4a fix: reject past residence status`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 1480061`, Start `2026-07-18 06:45:34 CEST`.
- Seit diesem Restart: `2/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Historische Wohnortlabels abweisen

- `Mein ehemaliger/früherer/alter Wohnort`, Wohnsitz oder Zuhause wurde wegen eines später startenden Regex-Matches als aktuell übernommen.
- Satzlokaler Historien-Guard verwirft solche Kandidaten; spätere aktuelle Wohnortangaben werden weiterhin ausgewählt.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, 7 historische/aktuelle Label-Smoke-Checks, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `4d263352 fix: reject historical residence labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 1480061`, Start `2026-07-18 06:45:34 CEST`.
- Seit diesem Restart: `3/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Eindeutig historische Adjektive

- `vormaliger` und `damaliger Wohnort/Wohnsitz` wurden bisher als aktuelle Labels akzeptiert.
- Eindeutig historische Adjektive werden verworfen; `bisheriger` bleibt wegen möglicher Gegenwartsbedeutung offen.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, 4 historische Adjektiv-Smoke-Checks, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c0fdc605 fix: reject unambiguous historical residence adjectives`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 1480061`, Start `2026-07-18 06:45:34 CEST`.
- Seit diesem Restart: `4/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Temporale Labelpräfixe disambiguieren

- `Heute/Nun/Seit heute ist mein Wohnort ...` wurde teilweise als City `Heute/Nun/Seit` fehlinterpretiert.
- Temporale Einzelkandidaten werden verworfen; explizite aktuelle Labelpräfixe liefern die nachfolgende Stadt.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, 8 Temporal-Label-Smoke-Checks, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `7851bd74 fix: disambiguate temporal residence labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 1480061`, Start `2026-07-18 06:45:34 CEST`.
- Seit diesem Restart: `5/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Rand- und Richtungsrelationen

- `außerhalb von`, `am Stadtrand`, `im Umland` sowie Himmelsrichtungen wurden bei Verbformen nicht erkannt.
- Relation ist für `wohne/lebe` und präzise Labels mit `liegt/befindet sich` ergänzt; pauschales `ist außerhalb` bleibt gemäß bestehender Negativsemantik leer.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, 8 Perimeter/Direction-Smoke-Checks, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `298cc36b fix: parse residence perimeter relations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 1480061`, Start `2026-07-18 06:45:34 CEST`.
- Seit diesem Restart: `6/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Dauer-Qualifier vor Wohnortlabels

- `Seit 2020/kurzem/einiger Zeit ist/liegt ... Wohnort/Wohnsitz ...` wurde bisher nicht erkannt; `Seit` konnte als Kandidat erscheinen.
- Dauer-Qualifier vor aktuellen Labels und deren negierter Änderungszweig sind ergänzt; `war` bleibt historisch ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, 7 Duration-Label-Smoke-Checks, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c0105219 fix: parse duration-qualified residence labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 1480061`, Start `2026-07-18 06:45:34 CEST`.
- Seit diesem Restart: `7/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Ambige Rand-/Richtungsangaben

- Nach dem neuen Relationpfad wurde `außerhalb von Berlin und Hamburg` fälschlich als Berlin gekürzt; zwei positive Randorte müssen unklar bleiben.
- Neuer Ambiguitätsguard erkennt Rand-/Richtungsrelationen und schützt Aktivitätszusätze (`arbeite`, `pendle`, `besuche`).
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, 6 Perimeter-Ambiguity-Smoke-Checks, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c000e67a fix: reject ambiguous perimeter residences`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 1480061`, Start `2026-07-18 06:45:34 CEST`.
- Seit diesem Restart: `8/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Ambige Referenzrelationen

- `rund um/nahe/unweit von/im Raum Berlin und Hamburg` wurde bei bestehenden Referenzpfaden teilweise auf Berlin gekürzt.
- Ambiguitätsguard deckt jetzt bestehende und neue Referenzrelationen ab; Aktivitätszusätze bleiben gültig.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, 7 Reference-Ambiguity-Smoke-Checks, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `394d5cf6 fix: reject ambiguous reference residences`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 1480061`, Start `2026-07-18 06:45:34 CEST`.
- Seit diesem Restart: `9/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Komma-Mehrfachorte und Präzisierungen

- `Berlin, Hamburg` wurde fälschlich auf Berlin gekürzt; `genauer gesagt/konkret in Hamburg` wurde nicht als Korrektur erkannt.
- Präzisierungswechsel priorisiert; rohe Mehrfachorte werden verworfen, bekannte Länder/Regionen als Nachsatz bleiben kompatibel.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, 8 Comma/Clarification-Smoke-Checks, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `35ab68ac fix: disambiguate comma residence phrases`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 1480061`, Start `2026-07-18 06:45:34 CEST`.
- Seit diesem Restart: `10/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Wohnortwechsel-Varianten

- Labelwechsel mit `nun/jetzt/seitdem`, `änderte sich von`, `wechselte von/zu` und `verlegte sich` wurden bisher teilweise nicht erkannt.
- Explizite Wohnort-/Wohnsitzwechsel sind ergänzt; generisches `Ich wechselte ...` bleibt ohne Wohnkontext leer.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, 10 Residence-Change-Smoke-Checks, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `5a483da5 fix: parse residence change variants`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 1480061`, Start `2026-07-18 06:45:34 CEST`.
- Seit diesem Restart: `11/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Regionale Wohnortlabels

- `Wohnort/Wohnsitz/Zuhause in Deutschland/Schweiz/Bundesland, ... konkrete Stadt` blieb bei Dauer- und Tagesprefixen leer.
- Regionaler Labelpfad verarbeitet jetzt `heute/seit heute` und Dauerqualifier; Länder-only und unverbundene Kommas bleiben leer.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, 7 Regional-Label-Smoke-Checks, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `16f4804d fix: parse regional residence labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 1480061`, Start `2026-07-18 06:45:34 CEST`.
- Seit diesem Restart: `12/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Regionale Wohnstatus-Formen

- `Wohnstadt bleibt weiterhin im Bundesland ...`, `Heute bin ich ... wohnhaft` und `Seit ... bin ich ... wohnhaft` blieben teilweise leer.
- Gegenwarts-`bin/sind` mit beiden Pronomenstellungen und Qualifier nach Labelverb sind ergänzt; Länder-only bleibt leer.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, 5 Regional-Status-Smoke-Checks, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `1d5fb21c fix: parse regional residence status`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 1480061`, Start `2026-07-18 06:45:34 CEST`.
- Seit diesem Restart: `13/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Verkürzte Wohnstatus-Sätze

- `Seit 2020 wohnhaft in ...`, `Derzeit ansässig in ...` und `Seit 2020 in ... wohnhaft` wurden bisher nicht erkannt.
- Gegenwartsqualifier vor Status und vor Ortspräposition sind ergänzt; `früher/ehemals/bis ...` bleiben leer.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, 9 Abbreviated-Status-Smoke-Checks, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `3e22b938 fix: parse abbreviated residence status`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 1480061`, Start `2026-07-18 06:45:34 CEST`.
- Seit diesem Restart: `14/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Ansiedlungs- und Einzugsverben

- `niedergelassen`, `angesiedelt`, `eingezogen`, `sesshaft geworden` und `ließ mich nieder` wurden bisher nicht als aktueller Wohnort erkannt.
- Abgeschlossene Ansiedlungsformen sind ergänzt; Zukunftsformen bleiben leer.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, 8 Settlement-Verb-Smoke-Checks, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e361b2ab fix: parse settlement and move verbs`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 1480061`, Start `2026-07-18 06:45:34 CEST`.
- Seit diesem Restart: `15/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Wohnobjekt-Zwischenphrasen

- `in meiner Wohnung/in meinem Haus/in einer WG in ...` wurde bisher nicht extrahiert; `unserem Haus` konnte als City-Kandidat stehen bleiben.
- Enger Objektpfad für `wohne/lebe` ergänzt; Besitzsätze ohne Wohnverb bleiben leer, `unser...` wird im Cleanup verworfen.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, 9 Residence-Object-Smoke-Checks, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `803eea8b fix: parse residence object phrases`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 1480061`, Start `2026-07-18 06:45:34 CEST`.
- Seit diesem Restart: `16/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Institutionelle Wohnobjekte

- `im Wohnheim`, `im Studentenwohnheim` und `im Internat in ...` wurden bisher nicht extrahiert.
- Dauerhafte institutionelle Wohnobjekte sind ergänzt; Hotel bleibt bewusst außerhalb des Wohnortpfads.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, 4 Institutional-Residence-Smoke-Checks, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `91cb439b fix: parse institutional residence objects`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 1480061`, Start `2026-07-18 06:45:34 CEST`.
- Seit diesem Restart: `17/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Haushaltsrelationen mit `bei`

- `mit meiner Familie bei Berlin`, `bei meinen Eltern bei Potsdam` und ähnliche Haushaltsformen wurden bisher nicht erkannt.
- Personen-/Haushaltsmuster akzeptieren jetzt `in` und `bei` als Zielpräposition; Aktivitätsverben bleiben geschützt.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, 6 Household-Relation-Smoke-Checks, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `590c0ec9 fix: parse household residence relations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 1480061`, Start `2026-07-18 06:45:34 CEST`.
- Seit diesem Restart: `18/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Stadtteil-/Bezirk-/Viertel-/Kiez-Zwischenorte

- `Stadtteil Kreuzberg in Berlin`, `Bezirk Neukölln bei Berlin`, `Viertel Altona in Hamburg`, `Kiez von Potsdam` und `Stadtteil von Leipzig` wurden bisher verpasst.
- Enger Parserpfad extrahiert nur bei explizitem Wohnverb/Wohnlabel plus Zielstadt; `Ich arbeite im Bezirk Mitte in Berlin` bleibt leer.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, 8 Neighborhood-Smoke-Checks, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `28fcbd3b fix: parse neighborhood residence phrases`.

### Folgefix 2026-07-18: Ortslabel-Grenzen und Aktivitätskontext

- `Ort`/`Stadt` wurden als Präfix in `Ortsteil`/`Stadtteil` erkannt; fehlende Zielstädte konnten dadurch falsche Orte erzeugen.
- Zwischenort-Labels um `Ortsteil`, `Quartier`, `Altstadt`, `Stadtzentrum`, `Zentrum` und `Innenstadt` erweitert; Aktivitäts-/Verbindungsphrasen vor dem Zieltrenner werden verworfen.
- Verifikation: `tests/test_weather_context.py` -> `25 passed`, 12 Neighborhood-Boundary-Smoke-Checks, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `9db8723a fix: guard neighborhood residence parsing`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 2415017`, Start `2026-07-18 07:42:32 CEST`.
- Seit diesem Restart: `0/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Invertierte und umgangssprachliche Wohnangaben

- `Wohnhaft bin ich in ...`, `Berlin bleibt mein Wohnort`, `Ich hab' meinen Wohnsitz in ...` und aktuelle Rückwechsel wurden bisher verpasst.
- Invertierte aktuelle Wohnlabels und `hab`-Formen ergänzt; `ehemals` blockiert neue invertierte Treffer weiterhin als historisch.
- Verifikation: `tests/test_weather_context.py` -> `26 passed`, 15 Inversion-/Historien-Smoke-Checks, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `d0020476 fix: parse inverted residence statements`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 2415017`, Start `2026-07-18 07:42:32 CEST`.
- Seit diesem Restart: `1/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Zukünftige Wohnorte nicht als aktuell speichern

- `Ab nächstem Jahr`, `bald`, `künftig`, `zukünftig` und `Nächstes Jahr ist mein Wohnort ...` wurden teilweise als aktueller Wohnort erkannt.
- Future-Prefix-Guard ergänzt; geplante Umzüge mit `ziehen` werden als Nicht-Wohnaktivität behandelt und überschreiben aktuelle Stadt nicht.
- Verifikation: `tests/test_weather_context.py` -> `27 passed`, 7 Future-Residence-Smoke-Checks, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `dff7a93f fix: reject future residence claims`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 2415017`, Start `2026-07-18 07:42:32 CEST`.
- Seit diesem Restart: `2/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Weitere vollzogene Wohnortwechsel

- `Ich wohne nicht mehr in Berlin, bin jetzt in Hamburg` und `Nach meinem Umzug bin ich nach Hamburg gezogen` wurden bisher verpasst.
- Konnektorlose `bin jetzt`-Wechsel und invertierte abgeschlossene `bin ich ... gezogen`-Formen ergänzt; Zukunftswechsel bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `28 passed`, 4 Change-Form-Smoke-Checks, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `3a1e4543 fix: parse additional residence changes`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 2415017`, Start `2026-07-18 07:42:32 CEST`.
- Seit diesem Restart: `3/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Richtungs- und Randlagen mit `von`

- `im Norden/Süden/Osten/Westen von ...` und `am Rand von ...` wurden bisher nicht als Wohnortrelation erkannt.
- Wohnverb-/Wohnlabel-Pfad ergänzt; zwei Zielstädte bleiben ambig, Arbeitskontext nach erster Stadt bleibt geschützt.
- Verifikation: `tests/test_weather_context.py` -> `29 passed`, 8 Direction-/Edge-Smoke-Checks, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `64781681 fix: parse directional residence relations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 2415017`, Start `2026-07-18 07:42:32 CEST`.
- Seit diesem Restart: `4/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Vollständige Wohnadressen

- Straßen-/Hausnummern in Wohnangaben wurden bisher als gesamter City-Kandidat verworfen; Kommaform wurde zusätzlich fälschlich als Ortsambiguität behandelt.
- Wohnverb-, Wohnlabel- und Anschrift-Muster extrahieren jetzt nur Zielstadt nach Straße/Nummer; Straßenbestandteile bleiben außerhalb Memory.
- Verifikation: `tests/test_weather_context.py` -> `30 passed`, 10 Address-/Ambiguity-Smoke-Checks, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `5f1335b9 fix: parse residential street addresses`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 2415017`, Start `2026-07-18 07:42:32 CEST`.
- Seit diesem Restart: `5/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Postleitzahlen in Wohnadressen

- `10115 Berlin` wurde als City-Kandidat verworfen; auch Straßenadressen mit Postleitzahl fielen aus.
- Postalpräfixe bei Wohnverb, Wohnlabel und Straße/Nummer ergänzt; Arbeitsangaben bleiben leer.
- Verifikation: `tests/test_weather_context.py` -> `30 passed`, 7 Postal-Address-Smoke-Checks, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `1a0f03c1 fix: parse postal residence addresses`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 2415017`, Start `2026-07-18 07:42:32 CEST`.
- Seit diesem Restart: `6/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Genitiv-Ortsrelationen

- `Nähe Berlins`, `unweit Dresdens`, `außerhalb Berlins`, `am Rand Dresdens`, `im Umland Potsdams` und `im Norden Berlins` wurden bisher verpasst.
- Direkte und deutsche Genitivformen ergänzt; unverändert auf `s` endende Ortsnamen werden konservativ nicht geraten.
- Verifikation: `tests/test_weather_context.py` -> `31 passed`, 8 Genitive-Relation-Smoke-Checks, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a84fe96b fix: parse genitive residence relations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 2415017`, Start `2026-07-18 07:42:32 CEST`.
- Seit diesem Restart: `7/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Widersprüchliche Privatadressen

- Spätere `Adresse`-/`Wohnadresse`-Treffer konnten expliziten Wohnort überschreiben; mehrere getrennte Privat-Wohnziele waren nicht konservativ behandelt.
- Konfliktguard für positive Wohn-/Wohnsitzangabe plus abweichendes Privatadresslabel nach Komma/Semikolon ergänzt; Arbeits-/Geschäfts-/Postadresse bleibt neutral.
- Verifikation: `tests/test_weather_context.py` -> `32 passed`, 10 Private-Address-Conflict-Smoke-Checks, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `9fa43c83 fix: guard conflicting residence addresses`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 2415017`, Start `2026-07-18 07:42:32 CEST`.
- Seit diesem Restart: `8/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Konsistente Wetter-State-Zeitstempel

- `updated_at` nutzte bisher reale Systemzeit trotz injiziertem `now`; Providerfehler setzten `updated_at` gar nicht.
- Success- und Error-Pfad verwenden jetzt `resolved_now` für `updated_at`, `last_checked_at` und City-Zeitbezug.
- Verifikation: `tests/test_weather_context.py` -> `33 passed`, State-Timestamp-Smoke gruen, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c00f48ff fix: use resolved weather timestamps`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 2415017`, Start `2026-07-18 07:42:32 CEST`.
- Seit diesem Restart: `9/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Kurze Wohnprofilangaben

- Formular-/Kurzformen wie `Wohnhaft: Berlin`, `Wohnort = Berlin`, `Wohne: Leipzig` und `Mein aktueller Wohnort Berlin` wurden bisher verpasst.
- Drei enge Kurzpfade ergänzt; Negativwörter, Future- und History-Guards verhindern falsche Treffer in `Lebensmittelpunkt`, `war wohnhaft` und Zukunftssätzen.
- Verifikation: `tests/test_weather_context.py` -> `34 passed`, Short-Profile-/History-Smoke-Checks, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `4b6cd6f8 fix: parse short residence profile forms`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 2415017`, Start `2026-07-18 07:42:32 CEST`.
- Seit diesem Restart: `10/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Invertierte Orts-/Wohnverbformen

- `In Berlin wohne ich`, `Bei meinen Eltern in Berlin wohne ich`, `In Berlin habe ich meinen Wohnsitz` und `In Berlin befindet sich mein Wohnort` wurden bisher verpasst; Kurzpfad las `ich` als City.
- Direkte, relationale, Haushalts- und Wohnlabel-Inversionen ergänzt; Negation und Arbeitsort bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `35 passed`, 12 Inverted-Location-Smoke-Checks, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `2b385355 fix: parse inverted residence locations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 2415017`, Start `2026-07-18 07:42:32 CEST`.
- Seit diesem Restart: `11/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Persistenter Mention-Zeitpunkt trotz Wetter-Rate-Limit

- Wiederholte Wohnstadt-Erwähnung innerhalb 2h aktualisierte `city_updated_at` bisher nur im RAM; die Rückgabe `rate_limited` verwarf diese Änderung.
- State wird bei erkannter Stadt vor `rate_limited` persistiert; stumme Nachrichten ohne Stadt erzeugen keinen unnötigen Write.
- Verifikation: `tests/test_weather_context.py` -> `36 passed`, Mention-Timestamp-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `51727687 fix: persist repeated residence mentions`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 2415017`, Start `2026-07-18 07:42:32 CEST`.
- Seit diesem Restart: `12/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Ambige Wohn-Kurzformen und Ortswechsel

- Freier Kurzpfad las in `wohne aber inzwischen in Hamburg`, `zwischen Berlin und Potsdam` und `irgendwo bei Berlin` falsche Wörter als Stadt.
- Kurzform ohne Präposition nur noch als klar begrenzter Satzkandidat; Wohnwechsel aus `komme aus ..., wohne ...` ergänzt; Mehrfachrelation `zwischen ... und ...` bleibt leer; `beheimatet` und `irgendwo bei` unterstützt.
- Verifikation: `tests/test_weather_context.py` -> `36 passed`, 6 Parser-Smoke-Checks, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `ffe5cf9c fix: reject ambiguous residence shorthand`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 2415017`, Start `2026-07-18 07:42:32 CEST`.
- Seit diesem Restart: `13/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Invertierte Wohn- und Länder-Klarstellungen

- `Berlin, dort wohne ich`, `In Berlin bin ich zu Hause` und `Ich lebe derzeit in Deutschland, genauer gesagt in Berlin` wurden nicht zuverlässig erkannt.
- Enge Inversions- und Länder-Klarstellungsmuster ergänzt; semikolon-getrennte widersprüchliche Selbstangaben bleiben konservativ ohne Stadt.
- Verifikation: `tests/test_weather_context.py` -> `36 passed`, 23 lokale Korpus-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `07c0cf07 fix: parse inverted residence statements`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 2415017`, Start `2026-07-18 07:42:32 CEST`.
- Seit diesem Restart: `14/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Wechselrhythmus und zukünftige Umzüge

- `mal/teils/abwechselnd`-Angaben, Plural-`Wohnorte`, `wohnen tue ich`, frühere/aktuelle Kurzangaben und Vergangenheitsformen von `ziehen` wurden teils falsch oder gar nicht erkannt.
- Ambige Mehrfachwohnsitze bleiben leer; `Ab morgen` wird nicht als aktueller Wohnort gespeichert; frühere/aktuelle sowie abgeschlossene Umzüge werden als aktueller Zielort erkannt.
- Verifikation: `tests/test_weather_context.py` -> `37 passed`, 49 lokale Korpus-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `0dd74eb2 fix: handle residence change timing`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 2415017`, Start `2026-07-18 07:42:32 CEST`.
- Seit diesem Restart: `15/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Profil-, Adress- und Studienangaben

- Invertiertes `wohnhaft`, Stadtteil-/Innenstadt-/Umland-Adjektive, genitive Nähe/Richtung, kurze Adresslabels und `während/nach dem Studium` wurden ergänzt.
- Arbeits-/Job-/Büro-/Studienkontext bei `bei ... in Stadt` wird nicht mehr als Wohnort übernommen; `Wohnadresse lautet` ist gültig.
- Verifikation: `tests/test_weather_context.py` -> `38 passed`, 48 lokale Korpus-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `37c244c7 fix: parse residence profile variants`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 2415017`, Start `2026-07-18 07:42:32 CEST`.
- Seit diesem Restart: `16/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Aktive Zeitmarker und Arbeitskontext

- `Früher wohnte ich ..., jetzt ...`, `neben`, `seit gestern`, `nunmehr`, `bereits`, `schon` und `noch` wurden ergänzt.
- `mit Arbeit/Studium` bleibt kein Wohnort; `In Zukunft` wird nicht als Stadt und nicht als aktueller Wohnort erkannt.
- Verifikation: `tests/test_weather_context.py` -> `39 passed`, 40 lokale Korpus-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `862b7e06 fix: distinguish active residence time markers`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 2415017`, Start `2026-07-18 07:42:32 CEST`.
- Seit diesem Restart: `17/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Wohnort-Klarstellungen und Labelvarianten

- Region-plus-Relation (`in Brandenburg bei Berlin`), Klarstellungen mit `aber` oder ohne zweites `in`, Komma nach Elternrelation sowie `wird genannt`/`heißt` werden jetzt korrekt aufgelöst.
- Spätere Präzisierung gewinnt gegenüber grober erster Ortsangabe; vorhandene Ambiguitätsguards bleiben aktiv.
- Verifikation: `tests/test_weather_context.py` -> `40 passed`, 13 Klarstellungs-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `5dfaa42d fix: parse residence clarification forms`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 2415017`, Start `2026-07-18 07:42:32 CEST`.
- Seit diesem Restart: `18/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Adresswechsel und widersprüchliche Selbst-Orte

- Aktuelle Wohnadressänderungen, PLZ-Adressen sowie `Privatadresse`/`Hauptadresse` ergänzt.
- Unterschiedliche direkte Wohnort-/Zuhause-/Lebensmittelpunkt-Angaben werden konservativ als Konflikt leer gelassen; explizite Korrekturen mit `aber`/`und ... Wohnort ist` gewinnen.
- Verifikation: `tests/test_weather_context.py` -> `41 passed`, 13 Adress-/Konflikt-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `606c175b fix: resolve current residence conflicts`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service weiterhin aktiv, `MainPID 2415017`, Start `2026-07-18 07:42:32 CEST`.
- Seit diesem Restart: `19/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Letzte Umzugs- und Zukunftsformen

- Invertierter Satz `Nicht mehr ... sondern ... wohne ich`, `früher war ... jetzt ist er ...`, zeitmarkierte Umzüge und `seit meinem Umzug` ergänzt.
- `Wird ab morgen`/`soll ... werden` werden nicht als aktueller Ort gespeichert.
- Verifikation: `tests/test_weather_context.py` -> `42 passed`, 33 finale Korpus-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a427f702 fix: parse final residence move forms`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3748148`, Start `2026-07-18 09:03:55 CEST`.
- Seit diesem Restart: `0/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Internationale Ortsnamen und Genitiv-Nähe

- `in der Nähe Paris` ergänzt, ohne bestehende `Berlins`-Genitivnormalisierung zu übersteuern.
- Weitere Länder-/Kontinentnamen (`Kanada`, `Japan`, `Amerika`, Großbritannien, Vereinigtes Königreich) werden nicht als Städte gespeichert; Land-plus-Stadt-Klarstellung bleibt möglich.
- Verifikation: `tests/test_weather_context.py` -> `43 passed`, 19 globale Orts-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `975bed1c fix: normalize global residence locations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3748148`, Start `2026-07-18 09:03:55 CEST`.
- Seit diesem Restart: `1/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Genitivrelationen bei `s`-Endungen

- `außerhalb/südlich/am Rand/im Umland/im Norden Paris` und weitere unveränderte `s`-Endungen werden jetzt als Paris statt als gekürzter/falscher Kandidat erkannt.
- `in der Nähe des Zentrums von Berlin` wird bis zur Zielstadt aufgelöst.
- Verifikation: `tests/test_weather_context.py` -> `44 passed`, 12 Relations-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `79c861fe fix: preserve s-ending relation cities`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3748148`, Start `2026-07-18 09:03:55 CEST`.
- Seit diesem Restart: `2/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Umgangssprachliche Wohnortformen

- `wohn/leb`, `grad`, `zurzeit`, `dahoam`, `I leb`, invertierte Formen und Bindestrich-Klarstellungen werden erkannt.
- Ungeankertes `Wohnsitz`-Matching wird auf Satzanfang begrenzt; dadurch wird Text wie `ha e meinen Wohnsitz in Berlin` nicht mehr fälschlich als Wohnort gespeichert.
- Negative invertierte Aussagen wie `In Berlin wohne ich nicht` bleiben leer; Genitiv-Nähe `Berlins Nähe` bleibt `Berlin`.
- Verifikation: `tests/test_weather_context.py` -> `45 passed`, 8 fokussierte Residence-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `bbc53b52 fix: parse colloquial residence forms`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3748148`, Start `2026-07-18 09:03:55 CEST`.
- Seit diesem Restart: `3/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Direkte Zuhause-Formen

- `Ich bin daheim/zuhause/zu Hause in Stadt` wird als aktuelle Wohnortangabe erkannt und nutzt das vorhandene `dahoam`-Muster.
- Besuchs- und Arbeitskontext bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `45 passed`, vier Home-Form-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `2fc67035 fix: parse direct home residence forms`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3748148`, Start `2026-07-18 09:03:55 CEST`.
- Seit diesem Restart: `4/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Semikolon-Konflikte

- Ambiguitätsprüfung erkennt jetzt auch `Ich wohne in Berlin; Hamburg` sowie Wohnortlabels mit Semikolon.
- Korrektursegmente nach `aber`, `jetzt` und ähnlichen Markern bleiben vom Konfliktguard ausgenommen und werden weiter vom Change-Pfad aufgelöst.
- Verifikation: `tests/test_weather_context.py` -> `46 passed`, vier Semikolon-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `54bccacf fix: reject semicolon residence conflicts`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3748148`, Start `2026-07-18 09:03:55 CEST`.
- Seit diesem Restart: `5/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Punktuierte Wohnort-Klarstellungen

- Klarstellungen mit Semikolon, Doppelpunkt und optionalem `in/bei` werden erkannt, z. B. `genauer gesagt: Potsdam`.
- Länder-/Grobraumangabe vor `genauer gesagt` wird nicht mehr fälschlich als Endort behalten.
- Verifikation: `tests/test_weather_context.py` -> `47 passed`, vier Klarstellungs-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `8b0dab86 fix: parse punctuated residence clarifications`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3748148`, Start `2026-07-18 09:03:55 CEST`.
- Seit diesem Restart: `6/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Bare-Label-Ortskonflikte

- `Wohnort Berlin, Hamburg` und `Wohnort: Berlin; Hamburg` werden als widersprüchlich verworfen, obwohl kein `ist` vorhanden ist.
- Volladressen, Länder-/Regionsangaben und `in/bei`-Präzisierungen bleiben gültig; Guard gilt nur für echte Stadt-zu-Stadt-Aufzählungen.
- Verifikation: `tests/test_weather_context.py` -> `48 passed`, sechs Bare-Label-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `b9aa0a5b fix: guard bare residence label conflicts`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3748148`, Start `2026-07-18 09:03:55 CEST`.
- Seit diesem Restart: `7/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Bare-Label-Klarstellungen und Ortswechsel

- Bare Labels wie `Wohnort Deutschland, genauer gesagt in Berlin` werden auf die konkrete Stadt aufgelöst.
- `Wohnort Berlin, aber jetzt Hamburg` und `Daheim: Berlin, aber jetzt Hamburg` verwenden den expliziten letzten Wohnort.
- Unmarkierte Aufzählungen bleiben durch den Konfliktguard leer.
- Verifikation: `tests/test_weather_context.py` -> `49 passed`, fünf Bare-Label-Change-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `db9047b0 fix: resolve bare residence label changes`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3748148`, Start `2026-07-18 09:03:55 CEST`.
- Seit diesem Restart: `8/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Heute- und Pronomen-Wohnortwechsel

- `Mein Wohnort war Berlin, jetzt/heute ist er Hamburg` wird sauber auf Hamburg gekürzt.
- `Früher wohnte/lebte ich in Berlin, heute in Hamburg` erkennt heute als aktuellen Zeitmarker.
- Verifikation: `tests/test_weather_context.py` -> `50 passed`, vier Zeitwechsel-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c65dfb98 fix: parse today residence transitions`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3748148`, Start `2026-07-18 09:03:55 CEST`.
- Seit diesem Restart: `9/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: `nimmer`-Wohnortwechsel

- `nimmer` wird als Negationsmarker erkannt und nicht mehr als Stadt gespeichert.
- `Ich wohne nimmer in Berlin, sondern/aber ...` wird auf den neuen Ort aufgelöst; bestehende `nicht mehr`-Formen bleiben unverändert.
- Verifikation: `tests/test_weather_context.py` -> `51 passed`, vier nimmer-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e7058157 fix: parse nimmer residence changes`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3748148`, Start `2026-07-18 09:03:55 CEST`.
- Seit diesem Restart: `10/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Klauselbezogene Zukunftsmarker

- Bei `Ab morgen ... Hamburg, derzeit ... Berlin` wird Berlin als aktueller Ort behalten.
- Zukunftsprüfung nutzt Boundary- und Stadtbeginn passend; historische Marker prüfen weiterhin Patternbeginn.
- Verifikation: `tests/test_weather_context.py` -> `52 passed`, sechs Zukunft/Aktuell-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `df0d3f6e fix: scope residence future markers`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3748148`, Start `2026-07-18 09:03:55 CEST`.
- Seit diesem Restart: `11/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Aktueller Ort vor historischem Nachsatz

- `Mein Wohnort ist Berlin, war aber früher Hamburg` und ähnliche Formulierungen behalten Berlin.
- Historische Nachsätze werden nicht als aktuelle Change-Kandidaten übernommen.
- Verifikation: `tests/test_weather_context.py` -> `53 passed`, drei Current-before-history-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `87f0ceda fix: preserve current residence before history`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3748148`, Start `2026-07-18 09:03:55 CEST`.
- Seit diesem Restart: `12/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Sofortiger versus geplanter Beginn

- `ab sofort` wird als aktueller Zeitmarker erkannt und extrahiert die Stadt.
- `ab morgen` und `ab nächstem Jahr` bleiben geplante Orte und werden nicht als aktueller Wohnort gespeichert.
- Verifikation: `tests/test_weather_context.py` -> `54 passed`, drei Sofort/Planstart-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e1c1eb47 fix: distinguish immediate residence start`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3748148`, Start `2026-07-18 09:03:55 CEST`.
- Seit diesem Restart: `13/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Aktuelles Label nach Zukunftskontext

- `Mein künftiger Wohnort wird Hamburg, derzeit ist Berlin mein Wohnort` liefert Berlin.
- Marker-Satz `Derzeit ist Berlin mein Wohnort` wird erkannt; `Arbeitsort` bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `55 passed`, drei Current-label-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `ef5caf3c fix: parse current residence label after future`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3748148`, Start `2026-07-18 09:03:55 CEST`.
- Seit diesem Restart: `14/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Direkte Zeitmarker-Synonyme

- Direkte Angaben mit `im Moment`, `gegenwärtig`, `derzeit noch` und `schon seit` werden korrekt auf die Stadt extrahiert.
- `ab sofort` bleibt aktuell; geplante `ab morgen`/`ab nächstem Jahr`-Angaben bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `56 passed`, sieben Zeitmarker-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `31509f65 fix: parse direct residence time synonyms`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3748148`, Start `2026-07-18 09:03:55 CEST`.
- Seit diesem Restart: `15/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Ortsadverb-Reihenfolge

- `Wohnsitz ist direkt in Berlin`, `Wohnort liegt hier in Berlin` und `Zuhause ist dort in Berlin` liefern Berlin statt Adverb.
- Gesprochene Kommaform sowie `hier in Berlin daheim` werden erkannt.
- Verifikation: `tests/test_weather_context.py` -> `57 passed`, sechs Ortsadverb-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `54ded6f2 fix: parse residence location adverb order`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3748148`, Start `2026-07-18 09:03:55 CEST`.
- Seit diesem Restart: `16/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Regionale Wohnortrelationen

- Genitiv-Umgebung (`Berlins Umgebung`), Distanz-Richtung, `um ... herum`, `außerhalb der Stadt` und nördliches Stadtgebiet werden auf Stadtbasis extrahiert.
- Genitiv-Normalisierung schützt bekannte echte s-Endungsstädte.
- Verifikation: `tests/test_weather_context.py` -> `58 passed`, zehn Relations-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `412c53c0 fix: parse residence relation forms`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3748148`, Start `2026-07-18 09:03:55 CEST`.
- Seit diesem Restart: `17/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Mehrfachziel- und Wochenort-Guards

- `Mein Zuhause ist in Berlin und Hamburg` wird als widersprüchlich verworfen.
- `werktags/wochentags` wird nicht als Stadt gespeichert; echte Hauptwohnsitzangaben mit Arbeits-/Nebenort bleiben gültig.
- Verifikation: `tests/test_weather_context.py` -> `59 passed`, vier Multiple-home-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `5ddc7eed fix: reject multiple home targets`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3748148`, Start `2026-07-18 09:03:55 CEST`.
- Seit diesem Restart: `18/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Direkte Wohnortbeziehungen

- `Ich nenne Berlin mein Zuhause`, `Berlin nenne ich mein Zuhause`, `Berlin als Wohnort` und `Ich bin in Berlin daheim` werden erkannt.
- Arbeitsort-Beziehungen bleiben ausgeschlossen; gieriger Capture wurde auf lazy Stadtgrenze korrigiert.
- Verifikation: `tests/test_weather_context.py` -> `60 passed`, fünf Home-Relationship-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a08616d2 fix: parse direct home relationships`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3748148`, Start `2026-07-18 09:03:55 CEST`.
- Seit diesem Restart: `19/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Zeitmarker in Wohnortlabels

- `Mein Wohnort ist gegenwärtig/ab sofort Berlin` und `Ab sofort ist mein Wohnort Berlin` werden korrekt extrahiert.
- Zukunftslabel `Mein künftiger Wohnort ist Hamburg` bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `61 passed`, vier Temporal-label-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `f4429701 fix: parse temporal residence labels`.

## Aktueller Ledger 2026-07-18-Pre-Restart

- Service weiterhin aktiv, `MainPID 3748148`, Start `2026-07-18 09:03:55 CEST`.
- Seit diesem Restart: `20/20` Code-Fixes. Kein Push.
- Regel erfüllt: Bot-/Service-Restart jetzt ausführen.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 595833`, Start `2026-07-18 10:07:18 CEST`.
- Seit diesem Restart: `0/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Wohnortrelationen in Labels

- Wohnortlabels mit `bei meinen Eltern`, Regionsbezug, Richtungsbezug, Genitiv-Umgebung und `Stadt namens` werden erkannt.
- Arbeits-/Studienbezug bleibt ausgeschlossen; `außerhalb von Berlin` bleibt ohne Stadtwert, weil Berlin dort nur Referenzgebiet ist.
- Verifikation: `tests/test_weather_context.py` -> `62 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `47946711 fix: parse label-based residence relations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 595833`, Start `2026-07-18 10:07:18 CEST`.
- Seit diesem Restart: `1/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Label-Regionen normalisieren

- `im/am <Stadt>er Umland/Stadtrand`, Genitiv-Umgebung, `in der Gegend um` und `um ... herum` liefern Referenzstadt statt Relationsrest.
- Verifikation: `tests/test_weather_context.py` -> `62 passed`, fünf Relations-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `f24e96bd fix: normalize labeled residence regions`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 595833`, Start `2026-07-18 10:07:18 CEST`.
- Seit diesem Restart: `2/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Wohnort vor Aktivitätskontext bewahren

- Label-Wohnorte bleiben erhalten, wenn danach Arbeit, Studium, Besuch, Reise oder Tagesaufenthalt genannt wird.
- Zweiter echter Wohnort (`ich lebe ...`) bleibt als Konflikt leer.
- Verifikation: `tests/test_weather_context.py` -> `63 passed`, sieben Aktivitäts-/Konflikt-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `81029653 fix: preserve labeled residence before activity`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 595833`, Start `2026-07-18 10:07:18 CEST`.
- Seit diesem Restart: `3/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Direkter Wohnort vor Aktivitätskontext

- `Ich wohne/lebe in Berlin und arbeite/studiere/besuche ...` behält Berlin als Wohnort.
- Zweite Wohnortangabe bleibt widersprüchlich und leer.
- Verifikation: `tests/test_weather_context.py` -> `64 passed`, sieben Aktivitäts-/Konflikt-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `901b5f74 fix: preserve direct residence before activity`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 595833`, Start `2026-07-18 10:07:18 CEST`.
- Seit diesem Restart: `4/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Nahe-Wohnortlabels normalisieren

- `unweit/nahe <Stadt>` sowie Genitivformen liefern Stadtwert statt Relationswort.
- Bekannte echte s-Endungsstadt `Paris` bleibt geschützt.
- Verifikation: `tests/test_weather_context.py` -> `65 passed`, vier Nahbereich-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e53bb5ef fix: normalize nearby residence labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 595833`, Start `2026-07-18 10:07:18 CEST`.
- Seit diesem Restart: `5/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Region- und Großraumlabels

- `in der Region`, `im Großraum` und `im <Stadt>er Großraum` werden als Referenzstadt extrahiert.
- Verifikation: `tests/test_weather_context.py` -> `66 passed`, drei Regions-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `04595808 fix: parse labeled residence regions`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 595833`, Start `2026-07-18 10:07:18 CEST`.
- Seit diesem Restart: `6/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Zuhause-Labels vor Aktivitätskontext

- `Mein Zuhause/Daheim ist in Berlin und ...` behält Berlin bei Arbeit oder Studium.
- Zweite Wohnortangabe bleibt widersprüchlich.
- Verifikation: `tests/test_weather_context.py` -> `67 passed`, drei Zuhause-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `acb116d3 fix: preserve home labels before activity`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 595833`, Start `2026-07-18 10:07:18 CEST`.
- Seit diesem Restart: `7/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Companion-Wohnort vor Aktivität

- `bei/mit Eltern, Familie oder Kindern in Berlin und ...` behält Berlin vor Arbeits-/Studienkontext.
- `bei meiner Arbeit` bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `68 passed`, sechs Companion-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e4f98526 fix: preserve companion residence before activity`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 595833`, Start `2026-07-18 10:07:18 CEST`.
- Seit diesem Restart: `8/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Komma-Companionformen

- `bei/mit ... , in Berlin und ...` wird wie die normale Companionform erkannt.
- Verifikation: `tests/test_weather_context.py` -> `69 passed`, vier Komma-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `9657dd91 fix: parse comma companion residence forms`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 595833`, Start `2026-07-18 10:07:18 CEST`.
- Seit diesem Restart: `9/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Umgekehrte Wohnortformulierungen

- `In Berlin bin ich wohnhaft/ansässig` sowie `Ich nenne/Berlin nenne ich meinen Wohnort/Wohnsitz` werden erkannt.
- Arbeitsortlabels bleiben ausgeschlossen; Possessivflexion `meinen` wird unterstützt.
- Verifikation: `tests/test_weather_context.py` -> `70 passed`, sieben Reversed-Form-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `1fabd5fc fix: parse reversed residence statements`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 595833`, Start `2026-07-18 10:07:18 CEST`.
- Seit diesem Restart: `10/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Maskuline Aktivitätslabels

- `mein Studium`, `mein Ausbildungsort`-nahe Form sowie weitere `mein/unser`-Flexionen werden hinter Wohnort korrekt als Nebenaktivität erkannt.
- Verifikation: `tests/test_weather_context.py` -> `70 passed`, zwei `mein Studium`-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `07936041 fix: handle masculine activity labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 595833`, Start `2026-07-18 10:07:18 CEST`.
- Seit diesem Restart: `11/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Zukunftsmarker vor Wohnort

- `Demnächst`, `seit morgen`, `künftig` und künftige Wohnortlabels werden nicht als aktueller Wohnort gespeichert.
- Prefixprüfung reicht bis Stadtbeginn; `ab/seit heute` bleiben gültig.
- Verifikation: `tests/test_weather_context.py` -> `71 passed`, sechs Zukunftsmarker-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `50648500 fix: reject future residence markers`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 595833`, Start `2026-07-18 10:07:18 CEST`.
- Seit diesem Restart: `12/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Historische Wohnhaft-Perfektformen

- `wohnhaft/ansässig gewesen/worden` wird nicht als aktueller Wohnort erkannt.
- Aktuelles `Ich bin in Berlin wohnhaft` bleibt Berlin.
- Verifikation: `tests/test_weather_context.py` -> `72 passed`, vier historische-Perfekt-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `ef9b6759 fix: reject historical residence perfect`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 595833`, Start `2026-07-18 10:07:18 CEST`.
- Seit diesem Restart: `13/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Nie-Negation

- `nie in Berlin, sondern in Hamburg` extrahiert Hamburg statt Negationswort.
- Reine `nie`-Wohnortangabe bleibt leer.
- Verifikation: `tests/test_weather_context.py` -> `73 passed`, drei Nie-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `022c5675 fix: handle never residence negation`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 595833`, Start `2026-07-18 10:07:18 CEST`.
- Seit diesem Restart: `14/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Relativsätze mit Wohnverb

- `Berlin ist die Stadt, in der ich wohne` und `Der Ort, an dem ich lebe, ist Berlin` werden extrahiert.
- `Arbeitsort` bleibt kein Wohnort.
- Verifikation: `tests/test_weather_context.py` -> `74 passed`, sechs Relativsatz-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `cab1c2a2 fix: parse relative residence sentences`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 595833`, Start `2026-07-18 10:07:18 CEST`.
- Seit diesem Restart: `15/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Nachgestellte Ortsadverbien

- `Es ist Berlin, wo ich wohne` sowie `Ich wohne in Berlin, dort/hier` werden erkannt.
- Relativsatz mit Arbeitsverb bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `75 passed`, fünf Nachstellungs-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `05cca64b fix: parse postposed residence adverbs`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 595833`, Start `2026-07-18 10:07:18 CEST`.
- Seit diesem Restart: `16/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Länderpräfixe ohne Komma

- `in Deutschland/Österreich/der Schweiz in/bei <Stadt>` wird als Zielstadt extrahiert.
- Länderkontext wird nicht selbst als Stadt gespeichert.
- Verifikation: `tests/test_weather_context.py` -> `76 passed`, vier Länder-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a2d6b5d3 fix: parse country residence prefixes`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 595833`, Start `2026-07-18 10:07:18 CEST`.
- Seit diesem Restart: `17/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Bundeslandpräfixe vor Zielstadt

- `in/im <Bundesland> bei/in <Stadt>` extrahiert Zielstadt statt Bundesland.
- Label- und Direktform inklusive `im Bundesland` werden erkannt.
- Verifikation: `tests/test_weather_context.py` -> `77 passed`, fünf Regionspräfix-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `2acec0a3 fix: parse regional residence prefixes`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 595833`, Start `2026-07-18 10:07:18 CEST`.
- Seit diesem Restart: `18/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Benannte Ortsgattungen

- `im Dorf/Ort`, `die/eine Gemeinde` und `namens/genannt` liefern konkrete Zielstadt.
- Unbestimmte Ortsgattung bleibt leer.
- Verifikation: `tests/test_weather_context.py` -> `78 passed`, fünf Ortsgattungs-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `4494b47c fix: parse named locality types`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 595833`, Start `2026-07-18 10:07:18 CEST`.
- Seit diesem Restart: `19/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Bare Wohnort-Adresslabels

- `Wohnort/Wohnsitz: Straße Nummer, Stadt` wird erkannt; Mehrfachstadt bleibt leer.
- Verifikation: `tests/test_weather_context.py` -> `79 passed`, drei Adress-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a95db38d fix: parse bare residence address labels`.

## Aktueller Ledger 2026-07-18-Pre-Restart

- Service aktiv, `MainPID 595833`, Start `2026-07-18 10:07:18 CEST`.
- Seit diesem Restart: `20/20` Code-Fixes. Kein Push.
- Regel erfüllt: Bot-/Service-Restart jetzt ausführen.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1517099`, Start `2026-07-18 11:01:58 CEST`.
- Seit diesem Restart: `0/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Wiederholter Wohnrelativsatz

- `Ich wohne in Berlin, wo ich lebe` und Pluralform behalten konkrete Stadt.
- Nachfolgende Arbeitsaktivität überschreibt Wohnort nicht.
- Verifikation: `tests/test_weather_context.py` -> `80 passed`, drei Wiederholungs-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `7308b5ce fix: preserve residence in repeated relative clause`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1517099`, Start `2026-07-18 11:01:58 CEST`.
- Seit diesem Restart: `1/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Label-Wohnort in Relativsatz

- `Mein Wohnort/Zuhause ist in Berlin, wo ich lebe/arbeite` behält Berlin.
- Verifikation: `tests/test_weather_context.py` -> `81 passed`, drei Label-Relativ-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `71328be7 fix: preserve labeled residence in relative clause`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1517099`, Start `2026-07-18 11:01:58 CEST`.
- Seit diesem Restart: `2/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Sicherheits- und Unsicherheitsadverbien

- `sicher/wirklich/tatsächlich` werden vor Stadt übersprungen; `vielleicht/vermutlich/angeblich` erzeugen keinen Memory-Ort.
- Bestehende `direkt/dort`-Formen bleiben gültig.
- Verifikation: `tests/test_weather_context.py` -> `82 passed`, acht Adverb-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `02603fc3 fix: classify residence confidence adverbs`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1517099`, Start `2026-07-18 11:01:58 CEST`.
- Seit diesem Restart: `3/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Weitere Wohnadverbien

- `erst/immer` werden vor Stadt übersprungen statt als Stadtwert gespeichert.
- Verifikation: `tests/test_weather_context.py` -> `83 passed`, zwei Adverb-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `7c8597a9 fix: parse additional residence adverbs`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1517099`, Start `2026-07-18 11:01:58 CEST`.
- Seit diesem Restart: `4/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Zeitliche Wohnadverbien

- `bisher/bislang/vorerst/zeitweise` werden vor Stadt übersprungen.
- `fast/beinahe` bleiben unsicher und erzeugen keinen Wohnort.
- Verifikation: `tests/test_weather_context.py` -> `84 passed`, sechs Zeitadverb-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e5901726 fix: classify temporal residence adverbs`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1517099`, Start `2026-07-18 11:01:58 CEST`.
- Seit diesem Restart: `5/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Restliche Label-Relationen

- `liegt außerhalb der Stadt <Stadt>` und `am <Stadt>er Rand` werden erkannt.
- Konservative Ausnahme `ist außerhalb von <Stadt>` bleibt leer.
- Verifikation: `tests/test_weather_context.py` -> `85 passed`, drei Label-Relations-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `303e1344 fix: parse remaining labeled residence relations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1517099`, Start `2026-07-18 11:01:58 CEST`.
- Seit diesem Restart: `6/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Label-Lokalbezirke

- Stadtteil/Bezirk/Viertel/Altstadt mit Referenzstadt werden aus Wohnortlabels extrahiert.
- Ortsteil ohne Referenzstadt bleibt leer.
- Verifikation: `tests/test_weather_context.py` -> `86 passed`, sechs District-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `44817c2d fix: parse labeled local districts`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1517099`, Start `2026-07-18 11:01:58 CEST`.
- Seit diesem Restart: `7/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Label-Zentrum und Innenstadt

- Innenstadt/Zentrum/Rand in Adjektiv- und Genitivrelation werden als Referenzstadt extrahiert.
- Verifikation: `tests/test_weather_context.py` -> `87 passed`, sechs Center-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `8dc68296 fix: parse labeled center relations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1517099`, Start `2026-07-18 11:01:58 CEST`.
- Seit diesem Restart: `8/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Label-Flächenrelationen

- Region/Gegend/Gebiet/Umgebung mit einer Zielstadt werden korrekt extrahiert.
- Keine Freigabe für zweite, unabhängige Stadtziele.
- Verifikation: `tests/test_weather_context.py` -> `88 passed`, sechs Area-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `55f6e05d fix: parse labeled area relations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1517099`, Start `2026-07-18 11:01:58 CEST`.
- Seit diesem Restart: `9/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Direkte Flächenrelationen

- `Ich wohne/lebe in Berlin und Umgebung`, Region und Gebiet liefern Berlin.
- Verifikation: `tests/test_weather_context.py` -> `89 passed`, fünf Direkt-Area-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c5e00b31 fix: parse direct area relations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1517099`, Start `2026-07-18 11:01:58 CEST`.
- Seit diesem Restart: `10/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Label-Richtungsrelationen

- Nördlich/westlich und kombinierte Richtungen werden als Stadtanker extrahiert.
- Adjektiv-, Stadtadjektiv- und Genitivform sind abgedeckt.
- Verifikation: `tests/test_weather_context.py` -> `90 passed`, sechs Richtungs-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `4fbc5cf9 fix: parse labeled direction relations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1517099`, Start `2026-07-18 11:01:58 CEST`.
- Seit diesem Restart: `11/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Gelabelte Entfernungsrelationen

- Entfernungsangaben vor Richtungsrelationen werden auch bei `Wohnort ... ist/liegt` erkannt.
- Genitiv- und `von`-Form sind abgedeckt.
- Verifikation: `tests/test_weather_context.py` -> `90 passed`, drei Distanz-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `0ae2fe17 fix: parse labeled distance relations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1517099`, Start `2026-07-18 11:01:58 CEST`.
- Seit diesem Restart: `12/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Attributive Flächenrelationen

- `Berlin-Nähe`, `Berliner Nähe`, `Berliner Raum` und `Berliner Umgebung` werden auf Berlin normalisiert.
- Verifikation: `tests/test_weather_context.py` -> `91 passed`, vier Area-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `368eb67e fix: normalize attributive area relations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1517099`, Start `2026-07-18 11:01:58 CEST`.
- Seit diesem Restart: `13/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Natürliche Distanzpräfixe

- `ca.`, `ungefähr`, Dezimalwerte, `Kilometer`, `ein paar` und `wenige` werden vor Richtungsrelationen erkannt.
- Verifikation: `tests/test_weather_context.py` -> `91 passed`, neun Distanz-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `b06c7802 fix: parse natural distance prefixes`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1517099`, Start `2026-07-18 11:01:58 CEST`.
- Seit diesem Restart: `14/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Bindestrich-Richtungsrelationen

- `nord-östlich`, `süd-westlich` und gebeugte bzw. substantivische Varianten werden erkannt.
- Verifikation: `tests/test_weather_context.py` -> `92 passed`, acht Richtungs-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `416c5ffe fix: parse hyphenated direction relations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1517099`, Start `2026-07-18 11:01:58 CEST`.
- Seit diesem Restart: `15/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Unsichere Richtungsrelationen

- `keineswegs`, Konjunktiv- und Modalformen werden nicht mehr als sichere Wohnortangabe extrahiert.
- Verifikation: `tests/test_weather_context.py` -> `93 passed`, vier Negations-/Modal-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `df232e3c fix: reject uncertain residence relations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1517099`, Start `2026-07-18 11:01:58 CEST`.
- Seit diesem Restart: `16/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Richtungsrelation vor Aktivitätskontext

- Stadt-Captures enden vor Konjunktionen; Arbeits-/Studienort wird nicht als zweites Wohnziel gewertet.
- Verifikation: `tests/test_weather_context.py` -> `94 passed`, sechs Aktivitäts-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `01a8fcb7 fix: bound directional residence captures`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1517099`, Start `2026-07-18 11:01:58 CEST`.
- Seit diesem Restart: `17/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Nachgestellte Flächensuffixe

- `Hamburg-Nähe`, `Hamburg Nähe` und `Hamburg-Umgebung` werden auf Hamburg normalisiert.
- Adjektivformen wie `Hamburger Umgebung` bleiben bewusst separater Prüfpunkt.
- Verifikation: `tests/test_weather_context.py` -> `95 passed`, drei Suffix-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `9ad6d734 fix: normalize postposed area suffixes`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1517099`, Start `2026-07-18 11:01:58 CEST`.
- Seit diesem Restart: `18/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Aktuelle attributive Flächenwechsel

- `jetzt im Hamburger Raum` und `jetzt in der Hamburger Umgebung` werden als aktueller Wohnortwechsel erkannt.
- Historische und Arbeitsort-Kontexte bleiben geschützt.
- Verifikation: `tests/test_weather_context.py` -> `96 passed`, sechs Übergangs-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `59f10982 fix: parse current attributive area changes`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1517099`, Start `2026-07-18 11:01:58 CEST`.
- Seit diesem Restart: `19/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Unregelmäßige Stadtadjektive

- `Münchner`, `Dresdner` und `Bremer` werden auf München, Dresden und Bremen normalisiert.
- Reguläre Stadtadjektive bleiben unverändert.
- Verifikation: `tests/test_weather_context.py` -> `97 passed`, fünf Adjektiv-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c06a9457 fix: normalize irregular city adjectives`.

## Restart-Ledger 2026-07-18

- Service läuft noch mit `MainPID 1517099`, Start `2026-07-18 11:01:58 CEST`.
- Seit diesem Restart: `20/20` Code-Fixes. User-Service-Restart jetzt fällig. Kein Push.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2408904`, Start `2026-07-18 11:55:13 CEST`.
- Seit diesem Restart: `0/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Großraum-von-Relation

- `im Großraum von München` extrahiert München statt `von München`.
- Verifikation: `tests/test_weather_context.py` -> `97 passed`, drei Großraum-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `88d4ebcb fix: parse grossraum von relations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2408904`, Start `2026-07-18 11:55:13 CEST`.
- Seit diesem Restart: `1/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Rund-um-herum-Relationen

- `rund um München herum` liefert München statt den Nachsatz `herum`.
- Direkte, gelabelte und aktuelle Wechsel-Form sind abgedeckt.
- Verifikation: `tests/test_weather_context.py` -> `98 passed`, vier Rund-um-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `ceb18ed9 fix: normalize rund um herum relations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2408904`, Start `2026-07-18 11:55:13 CEST`.
- Seit diesem Restart: `2/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Genitivisches Umland

- `Münchens Umland` wird wie Nähe und Umgebung auf München normalisiert.
- Verifikation: `tests/test_weather_context.py` -> `98 passed`, drei Genitiv-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `d632f1a7 fix: parse genitive umland relations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2408904`, Start `2026-07-18 11:55:13 CEST`.
- Seit diesem Restart: `3/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Direkter adjectivaler Rand

- `am Münchner Rand` wird wie `am Münchner Stadtrand` auf München normalisiert.
- Verifikation: `tests/test_weather_context.py` -> `99 passed`, drei Rand-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `01d91ae6 fix: parse direct adjectival rand relations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2408904`, Start `2026-07-18 11:55:13 CEST`.
- Seit diesem Restart: `4/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Stadtgebiet-Relationen

- `im Münchner Stadtgebiet` und `im Stadtgebiet von München` werden erkannt.
- Gelabelte und direkte Residence-Formen sind abgedeckt.
- Verifikation: `tests/test_weather_context.py` -> `100 passed`, vier Stadtgebiet-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `becc0f78 fix: parse stadtgebiet residence relations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2408904`, Start `2026-07-18 11:55:13 CEST`.
- Seit diesem Restart: `5/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Genitivisches Stadtgebiet

- `im Stadtgebiet Münchens` und `im Stadtgebiet Berlins` werden erkannt.
- Verifikation: `tests/test_weather_context.py` -> `100 passed`, drei Genitiv-Stadtgebiet-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `f871bf96 fix: parse genitive stadtgebiet relations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2408904`, Start `2026-07-18 11:55:13 CEST`.
- Seit diesem Restart: `6/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Innerhalb-Relationen

- `innerhalb des Stadtgebiets von München`, `innerhalb der Stadt München`, `innerhalb von München` und Genitivform werden erkannt.
- Genitiv wird vor Normalform priorisiert, damit `Berlins` nicht als Stadtwert endet.
- Verifikation: `tests/test_weather_context.py` -> `101 passed`, fünf Innerhalb-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `9104821b fix: parse innerhalb residence relations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2408904`, Start `2026-07-18 11:55:13 CEST`.
- Seit diesem Restart: `7/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Vorstadt-/Vorort-Relationen

- `Münchner Vorstadt`, `Münchner Vorort`, Genitiv- und plain-`in`-Formen werden auf München normalisiert.
- Verifikation: `tests/test_weather_context.py` -> `102 passed`, fünf Vorstadt-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `6982b466 fix: parse adjectival vorstadt relations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2408904`, Start `2026-07-18 11:55:13 CEST`.
- Seit diesem Restart: `8/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Gelabelte Gemeinde-Relationen

- Gemeindeangaben mit `nahe`, `unweit von`, `rund um` und direktem Stadtziel werden korrekt getrennt.
- Verifikation: `tests/test_weather_context.py` -> `103 passed`, vier Gemeinde-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `78c51241 fix: parse labeled gemeinde relations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2408904`, Start `2026-07-18 11:55:13 CEST`.
- Seit diesem Restart: `9/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Stadtmitte-Relationen

- `Münchner Stadtmitte`, `Stadtmitte Münchens` und `Stadtmitte von Berlin` werden erkannt.
- Verifikation: `tests/test_weather_context.py` -> `104 passed`, vier Stadtmitte-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `fdfa6b14 fix: parse stadtmitte residence relations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2408904`, Start `2026-07-18 11:55:13 CEST`.
- Seit diesem Restart: `10/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Außerhalb-Stadt-Relationen

- `außerhalb der Stadt München`, Genitiv und direkte Form werden erkannt.
- Bewusst ausgeschlossene Label-`außerhalb von`-Form und `Paris`-Genitivschutz bleiben erhalten.
- Verifikation: `tests/test_weather_context.py` -> `105 passed`, sechs Outside-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `b69c12ad fix: parse outside city relations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2408904`, Start `2026-07-18 11:55:13 CEST`.
- Seit diesem Restart: `11/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Direkte Stadtrand-Relationen

- `am Stadtrand München`, Genitiv und `von`-Form werden erkannt.
- Verifikation: `tests/test_weather_context.py` -> `106 passed`, fünf Stadtrand-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `5847071d fix: parse direct stadtrand relations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2408904`, Start `2026-07-18 11:55:13 CEST`.
- Seit diesem Restart: `12/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Genitivische Zentrum-Relationen

- `im Zentrum Münchens`, `in der Innenstadt Münchens`, `Münchens Zentrum/Innenstadt` und `im Zentrum von München` werden erkannt.
- Fehlcapture `d` aus Innenstadt-Genitiv ist beseitigt.
- Verifikation: `tests/test_weather_context.py` -> `107 passed`, sechs Zentrum-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a4de032e fix: parse genitive center relations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2408904`, Start `2026-07-18 11:55:13 CEST`.
- Seit diesem Restart: `13/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Benannte Residence-Klauseln

- `eine Stadt, die München heißt` und `München nennt sich mein Wohnort` werden erkannt.
- Verifikation: `tests/test_weather_context.py` -> `108 passed`, vier Benennungs-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `80d4ae11 fix: parse named residence clauses`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2408904`, Start `2026-07-18 11:55:13 CEST`.
- Seit diesem Restart: `14/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Lebensmittelpunkt-Flächenrelationen

- `Lebensmittelpunkt in der Münchner Region` und `außerhalb der Stadt München` werden erkannt.
- Bestehende Raumform bleibt unverändert.
- Verifikation: `tests/test_weather_context.py` -> `109 passed`, drei Lebensmittelpunkt-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `0468dbd4 fix: parse lebensmittelpunkt area relations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2408904`, Start `2026-07-18 11:55:13 CEST`.
- Seit diesem Restart: `15/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Regionsnamen als Nicht-Städte

- Vorhandene `_NON_CITY_REGION_NAMES` werden nun auch in `_clean_city` geprüft.
- Bayern, Brandenburg und Hessen werden nicht mehr als Städte gespeichert.
- Verifikation: `tests/test_weather_context.py` -> `110 passed`, vier Regions-Rejection-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c0453e4e fix: reject region names as cities`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2408904`, Start `2026-07-18 11:55:13 CEST`.
- Seit diesem Restart: `16/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Makroregionen als Nicht-Städte

- Nord-/Süd-/West-/Ost-/Mitteldeutschland, Ruhrgebiet und Rheinland werden als Regionen verworfen.
- Verifikation: `tests/test_weather_context.py` -> `110 passed`, zwei Makroregion-Rejection-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `92c7402a fix: reject macro regions as cities`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2408904`, Start `2026-07-18 11:55:13 CEST`.
- Seit diesem Restart: `17/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Direkte Adjektiv-Flächenarten

- Direkte Formen `im Münchner Raum/ Gebiet` werden erkannt und vor Folgesätzen begrenzt.
- Verifikation: `tests/test_weather_context.py` -> `110 passed`, vier Adjektiv-Area-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a57e17cc fix: parse direct adjectival area types`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2408904`, Start `2026-07-18 11:55:13 CEST`.
- Seit diesem Restart: `18/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Aktueller Ort nach historischer Area

- Aktuelle Sätze nach `war/früher`-Areaangaben werden wieder als Wohnort erkannt.
- Label- und direkte Form mit Zentrum/Area sind abgedeckt.
- Verifikation: `tests/test_weather_context.py` -> `111 passed`, vier historische-Area-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `3925c878 fix: preserve current after historical area`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2408904`, Start `2026-07-18 11:55:13 CEST`.
- Seit diesem Restart: `19/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: S-endende Städtenamen

- Genitivische Capture-Sonderfälle für Paris, Reims, Worms, Tours, Cannes und Lens werden auf vollständige Stadtnamen repariert.
- Verifikation: `tests/test_weather_context.py` -> `112 passed`, 18 s-ending-city-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e9a83b71 fix: preserve s-ending city names`.

## Restart-Ledger 2026-07-18

- Service läuft noch mit `MainPID 2408904`, Start `2026-07-18 11:55:13 CEST`.
- Seit diesem Restart: `20/20` Code-Fixes. User-Service-Restart jetzt fällig. Kein Push.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3246439`, Start `2026-07-18 12:48:04 CEST`.
- Seit diesem Restart: `0/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Negierte Wohnort-Kontraste

- `Nicht Berlin, sondern Hamburg ist mein Wohnort` wird korrekt auf Hamburg begrenzt.
- Generisches Muster nimmt bei `Berlin ist nicht mein Wohnort, ich lebe in Hamburg` nicht mehr den ganzen Folgesatz als Städtenamen; Arbeitsort bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `112 passed`, sieben Negations-/Kontrast-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `0a0f1468 fix: parse negated residence contrasts`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3246439`, Start `2026-07-18 12:48:04 CEST`.
- Seit diesem Restart: `1/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Genitivische Wohnort-Flächen

- Postponierte Genitivformen wie `in Berlins Stadtgebiet`, `Stadtrand`, `Stadtmitte`, `Vorstadt`, `Umland` und `Raum` werden auf Berlin reduziert.
- Adjektivformen bleiben erhalten; Regionen wie Bayern werden weiterhin nicht als Stadt akzeptiert.
- Verifikation: `tests/test_weather_context.py` -> `113 passed`, neun Genitiv-Area-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `b0d1390b fix: parse genitive residence areas`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3246439`, Start `2026-07-18 12:48:04 CEST`.
- Seit diesem Restart: `2/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Besitz-Zuhause

- `Ich habe mein/unser Zuhause in/bei Stadt` wird als aktueller Wohnort erkannt.
- Bestehende Negations- und Arbeitsort-Ausschlüsse bleiben unverändert.
- Verifikation: `tests/test_weather_context.py` -> `113 passed`, sechs Possessive-Home-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `5e63f83c fix: parse possessive home locations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3246439`, Start `2026-07-18 12:48:04 CEST`.
- Seit diesem Restart: `3/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Settlement-Labels

- Direkte Wohnortformen mit `Ortschaft`, `Gemeinde`, `Kommune`, `Metropole` und `Hauptstadt` werden erkannt.
- Ortsbezüge `nahe`, `unweit von` und `rund um` werden innerhalb dieser Formen korrekt extrahiert; Regionen bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `114 passed`, neun Settlement-Label-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `170393ca fix: parse settlement residence labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3246439`, Start `2026-07-18 12:48:04 CEST`.
- Seit diesem Restart: `4/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Herkunft plus aktueller Wohnort

- `stamme aus ...`, `lebe/wohne ...` wird wie bestehendes `komme aus ...` verarbeitet.
- Übergangswörter `aber` an beiden natürlichen Positionen und `heute` werden erkannt; reine Arbeitsangabe bleibt leer.
- Verifikation: `tests/test_weather_context.py` -> `114 passed`, fünf Origin/Current-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `90eee6f7 fix: parse stamme aus residence changes`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3246439`, Start `2026-07-18 12:48:04 CEST`.
- Seit diesem Restart: `5/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Geburtsort plus aktueller Wohnort

- `Ich wurde in ... geboren`, `Geboren wurde ich in ...` und `Geboren in ...` mit anschließendem `lebe/wohne heute/jetzt ...` liefern den aktuellen Ort.
- Geburtsort bleibt historische Herkunft; reine Arbeitsangaben bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `114 passed`, sieben Birth-Origin-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `62e62b6d fix: parse birth origin residence changes`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3246439`, Start `2026-07-18 12:48:04 CEST`.
- Seit diesem Restart: `6/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Benannte Settlement-Orte

- `Ortschaft/Gemeinde/Kommune/Metropole/Hauptstadt namens/genannt Stadt` entfernt Zwischenwort korrekt.
- Verifikation: `tests/test_weather_context.py` -> `114 passed`, fünf Named-Settlement-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `ead90539 fix: parse named settlement locations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3246439`, Start `2026-07-18 12:48:04 CEST`.
- Seit diesem Restart: `7/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Eindeutige Stadtflächen-Suffixe

- `Berlin-Mitte`, `Berlin Stadt`, `Berlin-Zentrum` und vergleichbare eindeutige Bezirkswörter werden auf Berlin reduziert.
- Himmelsrichtungs-Suffixe bleiben bewusst unangetastet; `Bad Homburg-Süd`, `Baden-Baden` und `Berlin-Brandenburg` bleiben erhalten.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, sieben City-Area-Suffix-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `0dc7b1dd fix: normalize unambiguous city area suffixes`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3246439`, Start `2026-07-18 12:48:04 CEST`.
- Seit diesem Restart: `8/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Vor-/Hinter-Ortsrelationen

- `wohne kurz vor Berlin`, `Wohnort liegt hinter der Stadt Berlin` werden als Berlin erkannt.
- Interne Mehrfachziele und Aktivitätssätze werden nicht als Einzelort gespeichert; Roh-Cities mit führendem `vor/hinter` werden verworfen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, acht Front/Back-Relation-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `84ce8f9c fix: parse bounded front back residence relations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3246439`, Start `2026-07-18 12:48:04 CEST`.
- Seit diesem Restart: `9/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Historischer Hauptwohnsitz ohne Präposition

- `Mein Lebensmittelpunkt/Hauptwohnsitz war Hamburg, jetzt Berlin` akzeptiert aktuellen Ort auch ohne `in/bei`.
- Arbeits- und Studienverben bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, fünf Primary-Label-History-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `da127eb8 fix: parse primary residence history without preposition`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3246439`, Start `2026-07-18 12:48:04 CEST`.
- Seit diesem Restart: `10/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Zeit vor inverser Wohnortangabe

- `Seit Jahren ist Berlin mein Wohnort` und analoge `Zuhause/Lebensmittelpunkt`-Formen werden erkannt.
- `Arbeitsort` und `Studienort` bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, fünf Temporal-Inverse-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `7b35ad5a fix: parse temporal inverse residence labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3246439`, Start `2026-07-18 12:48:04 CEST`.
- Seit diesem Restart: `11/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Präsentes Sesshaft-Signal

- `Ich bin in/bei Berlin sesshaft` wird wie `sesshaft geworden` erkannt.
- Besuchsformulierungen bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, fünf Sesshaft-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `cc3b7569 fix: parse present sesshaft residence`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3246439`, Start `2026-07-18 12:48:04 CEST`.
- Seit diesem Restart: `12/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Invertierte Meldeadresse

- `Ich bin gemeldet/registriert in/bei Berlin` wird erkannt.
- Mehrfachziel und reiner Arbeitsort bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, fünf invertierte-Registration-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `40d7937c fix: parse inverted registration residence`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3246439`, Start `2026-07-18 12:48:04 CEST`.
- Seit diesem Restart: `13/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Explizite Wohnformen

- `Meine/unsere Wohnung`, `WG` und `Unterkunft ist/liegt/befindet sich in/bei Stadt` werden erkannt.
- Alte Wohnungen und Mehrfachziele bleiben ausgeschlossen; Eigentums-/Hausannahmen wurden nicht erweitert.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, sechs Dwelling-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `345983a2 fix: parse explicit dwelling residences`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3246439`, Start `2026-07-18 12:48:04 CEST`.
- Seit diesem Restart: `14/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Registrierungsadress-Labels

- `Meldadresse`, `Meldeadresse`, `Meldeanschrift` und `Meldesitz` mit aktuellem Ort werden erkannt.
- Alte Registrierungsadresse bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, fünf Registration-Label-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `030f92bf fix: parse registration address labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3246439`, Start `2026-07-18 12:48:04 CEST`.
- Seit diesem Restart: `15/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Historische Registrierungsangabe

- `war in ... wohnhaft/ansässig/gemeldet/registriert, jetzt in Stadt` liefert aktuellen Ort.
- Arbeitsübergänge bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, fünf Historical-Registration-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `429d89b3 fix: parse historical registered residences`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3246439`, Start `2026-07-18 12:48:04 CEST`.
- Seit diesem Restart: `16/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Umgezogene Wohnort-Labels

- `Wohnort/Wohnsitz/Hauptwohnsitz wurde von/aus Altstadt nach Neuort verlegt` liefert Neuort statt Rohkette.
- Direkte `nach Neuort`-Form und falsches Verb bleiben getrennt geprüft.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, fünf Moved-Residence-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `b000e64c fix: parse moved residence labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3246439`, Start `2026-07-18 12:48:04 CEST`.
- Seit diesem Restart: `17/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Wechselnde Wohnort-Labels

- `Wohnort/Wohnsitz ist von/aus Altort nach Neuort gewechselt` liefert Neuort.
- Ungültige Rohkette mit `geblieben` wird verworfen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, vier Switched-Residence-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `896c4023 fix: parse switched residence labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3246439`, Start `2026-07-18 12:48:04 CEST`.
- Seit diesem Restart: `18/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Inverse historische Wohnortlabels

- `Berlin war mein Wohnort, jetzt Hamburg` sowie `Früher/Ehemals war Berlin ... heute/jetzt Hamburg` liefern Hamburg.
- Reine Arbeitsübergänge bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, fünf inverse-historical-label-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `7d0673c0 fix: parse inverse historical residence labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3246439`, Start `2026-07-18 12:48:04 CEST`.
- Seit diesem Restart: `19/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Aktueller Ort als Satzfragment

- `Ich wohnte in Berlin. Jetzt Hamburg` und `Berlin ist nicht mehr mein Wohnort. Jetzt Hamburg` werden erkannt.
- Arbeitsverb-Folgen bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, sechs Bare-Current-Transition-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `50b08e4f fix: parse bare current residence transitions`.

## Restart-Ledger 2026-07-18

- Service läuft noch mit `MainPID 3246439`, Start `2026-07-18 12:48:04 CEST`.
- Seit diesem Restart: `20/20` Code-Fixes. User-Service-Restart jetzt fällig. Kein Push.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2301`, Start `2026-07-18 13:46:09 CEST`.
- Seit diesem Restart: `0/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Historische Statuswörter

- `Früher ansässig/gemeldet/registriert in Altort, heute/jetzt in Neuort` liefert Neuort.
- Arbeitsübergänge bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, fünf Historical-Status-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `7648aeb8 fix: parse historical residence status`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2301`, Start `2026-07-18 13:46:09 CEST`.
- Seit diesem Restart: `1/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Ersatzrelationen

- `Hamburg statt/anstatt/anstelle von Berlin` wird auf Hamburg gekürzt.
- Ersatzwörter gehören jetzt zu den lokalen City-Trailing-Stops.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, fünf Replacement-Relation-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `abdfedb5 fix: trim replacement residence relations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2301`, Start `2026-07-18 13:46:09 CEST`.
- Seit diesem Restart: `2/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Expliziter Kontrast-Wohnsatz

- `Berlin ist nicht mein Wohnort, sondern ich lebe in Hamburg` liefert Hamburg statt `ich lebe`.
- Arbeitsverb bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, drei Contrast-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `3984d604 fix: parse explicit contrast residence clauses`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2301`, Start `2026-07-18 13:46:09 CEST`.
- Seit diesem Restart: `3/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Gegenwartsort nach Vergangenheitsform

- `Ich wohnte in Berlin, bin aber jetzt in Hamburg` und `Wir lebten bei Berlin, sind inzwischen in Potsdam` liefern den aktuellen Ort.
- `arbeite aber jetzt` bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, drei Past-to-Current-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `1b247f89 fix: parse current residence after past tense`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2301`, Start `2026-07-18 13:46:09 CEST`.
- Seit diesem Restart: `4/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Zeitlicher Nicht-mehr-Kontrast

- `Ich lebe nun nicht mehr in Berlin, sondern Hamburg` und `Wir wohnen aktuell nicht mehr bei Berlin, sondern bei Potsdam` liefern aktuellen Ort.
- Arbeitsverb im Ersatzteil bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, drei Timed-Contrast-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `62968cab fix: parse timed residence contrast clauses`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2301`, Start `2026-07-18 13:46:09 CEST`.
- Seit diesem Restart: `5/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Perfektform beim Wohnortwechsel

- `Ich habe in Berlin gewohnt, bin jetzt in Hamburg` und `Wir haben bei Berlin gelebt, sind inzwischen in Potsdam` liefern aktuellen Ort.
- Arbeitsverb im Folgesatz bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, drei Perfect-Transition-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `b9d53372 fix: parse perfect residence transitions`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2301`, Start `2026-07-18 13:46:09 CEST`.
- Seit diesem Restart: `6/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Kompakte Perfektform

- `Ich hab in Berlin gewohnt, jetzt Hamburg` und `Wir haben bei Berlin gelebt, heute Potsdam` liefern aktuellen Ort.
- Arbeitsverb nach Zeitmarker bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, drei Compact-Perfect-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `47e4479c fix: parse compact perfect residence transitions`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2301`, Start `2026-07-18 13:46:09 CEST`.
- Seit diesem Restart: `7/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Historisches Wohnortlabel mit Zeitadverb

- `Berlin war mein Wohnort, ich bin jetzt in Hamburg` und `Berlin war früher mein Wohnsitz, aber ich bin inzwischen bei Potsdam` liefern aktuellen Ort.
- Arbeitsverb im Folgesatz bleibt ausgeschlossen.
- Erster Testlauf fand fehlendes `früher` im Regex; danach erneut `115 passed`, drei Historical-Bin-Transition-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `45d66f40 fix: parse historical residence status with time adverb`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2301`, Start `2026-07-18 13:46:09 CEST`.
- Seit diesem Restart: `8/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Konjunktiver Wohnortwechsel

- `Berlin war mein Wohnort und ich lebe jetzt in Hamburg` sowie `... und ich wohne inzwischen bei Potsdam` liefern aktuellen Ort.
- Arbeitsverb nach `und ich` bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, drei Conjunctive-Transition-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `fb888d41 fix: parse conjunctive residence transitions`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2301`, Start `2026-07-18 13:46:09 CEST`.
- Seit diesem Restart: `9/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Verlagerter Wohnort

- `Mein Wohnort hat sich von Berlin nach Hamburg verlagert` und `Unser Wohnsitz hat sich aus Berlin nach Potsdam verschoben` liefern Zielort statt Restphrase.
- Arbeitsort bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, drei Relocation-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `655c364a fix: parse relocated residence transitions`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2301`, Start `2026-07-18 13:46:09 CEST`.
- Seit diesem Restart: `10/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Relokation mit expliziter Quelle

- `Mein Wohnort verlegte sich von Berlin nach Hamburg` und `Unser Wohnsitz verlegte sich aus Berlin nach Potsdam` liefern Zielort.
- Arbeitsort bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, drei Source-Relocation-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c62bc634 fix: parse residence relocation source`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2301`, Start `2026-07-18 13:46:09 CEST`.
- Seit diesem Restart: `11/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Zustandsendung nach Wohnort

- `Mein Wohnort ist Hamburg geworden` und `Mein Zuhause ist Potsdam geworden` werden auf den Ortsnamen gekürzt.
- `geworden` ist jetzt lokaler City-Trailing-Stop; keine Pattern-Kaskade nötig.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, zwei State-Suffix-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `7874fe9d fix: trim residence state suffix`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2301`, Start `2026-07-18 13:46:09 CEST`.
- Seit diesem Restart: `12/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Neue invertierte Wohnlabels

- `Hamburg ist mein neuer Wohnort` und `Potsdam ist unser neues Zuhause` liefern aktuellen Ort.
- `Arbeitsort` wird durch enges Wohnlabel-Pattern nicht übernommen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, drei New-Residence-Label-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `10b9c315 fix: parse new residence labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2301`, Start `2026-07-18 13:46:09 CEST`.
- Seit diesem Restart: `13/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Aktuelles invertiertes Wohnlabel

- `Hamburg ist jetzt mein Wohnort` und `Potsdam ist inzwischen unser Zuhause` liefern aktuellen Ort.
- `Arbeitsort` bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, drei Current-Inverted-Label-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e0e2a714 fix: parse current inverted residence labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2301`, Start `2026-07-18 13:46:09 CEST`.
- Seit diesem Restart: `14/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Beruflicher Kontext als Negativfall

- `Ich bin bei Hamburg beruflich ansässig` und `Ich bin bei Potsdam dienstlich wohnhaft` liefern keinen Wohnort.
- `beruflich/dienstlich` werden in der City-Bereinigung als Aktivitätskontext verworfen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, zwei Professional-Context-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `501e9111 fix: reject professional residence contexts`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2301`, Start `2026-07-18 13:46:09 CEST`.
- Seit diesem Restart: `15/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Nachgestelltes Registrierungslabel

- `Ich bin in Hamburg registriert` und `Wir sind bei Potsdam registriert` liefern Ortsnamen.
- `zur Schule registriert` bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, drei Postposed-Registration-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `04e25c2a fix: parse postposed registration residences`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2301`, Start `2026-07-18 13:46:09 CEST`.
- Seit diesem Restart: `16/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Passive verschobene Relokation

- `Mein Wohnort wurde von Berlin nach Hamburg verschoben` und `Mein Wohnsitz wurde nach Potsdam verschoben` liefern Zielort.
- Präsens-Zukunft `wird ... verschoben` bleibt leer.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, drei Passive-Shift-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `513354cf fix: parse shifted residence relocations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2301`, Start `2026-07-18 13:46:09 CEST`.
- Seit diesem Restart: `17/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Perfektpassive Relokation

- `Mein Wohnort ist nach Hamburg verlegt worden` und `Unser Wohnsitz ist von Berlin nach Potsdam verschoben worden` liefern Zielort.
- Präsens-Zukunft `wird ... verlegt` bleibt leer.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, drei Perfect-Passive-Relocation-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `6ccb50b7 fix: parse perfect passive residence relocations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2301`, Start `2026-07-18 13:46:09 CEST`.
- Seit diesem Restart: `18/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Persönlicher Umzug mit Aus-Quelle

- `Ich habe meinen Wohnsitz aus Berlin nach Hamburg verlegt` und `Ich habe den Wohnort aus Berlin nach Potsdam verlegt` liefern Zielort.
- Bestehender persönlicher Verlegungspfad akzeptiert jetzt `von` und `aus`.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, zwei Personal-Source-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `b5e13f1d fix: parse personal residence move from source`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2301`, Start `2026-07-18 13:46:09 CEST`.
- Seit diesem Restart: `19/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Mietzusatz im Wohnort

- `Ich wohne in Hamburg zur Miete` wird auf Hamburg gekürzt.
- `zur Miete` ist lokaler City-Trailing-Stop; Wohnort bleibt erhalten.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, ein Rental-Suffix-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `054f51b5 fix: trim rental residence suffix`.

## Restart-Ledger 2026-07-18

- Service aktiv, `MainPID 2301`, Start `2026-07-18 13:46:09 CEST`.
- Seit diesem Restart: `20/20` Code-Fixes. User-Service-Restart jetzt fällig. Kein Push.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 658107`, Start `2026-07-18 14:27:15 CEST`.
- Seit diesem Restart: `0/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Wetter-State bei Residence-Memory-Fehler

- Wenn neuer Wohnort-Memory nicht geschrieben werden kann, bleibt Wetter-State bei vorheriger Stadt.
- Ergebnis meldet `skipped_reason=memory_error`; kein Wetterprovider-Aufruf mit inkonsistenter Stadt.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, zusätzlicher Rollback-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `85973bd6 fix: keep weather state with residence memory`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 658107`, Start `2026-07-18 14:27:15 CEST`.
- Seit diesem Restart: `1/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Temporäre Miet- und Wohnzusätze

- `zur Untermiete`, `zur Zwischenmiete` und `nur vorübergehend` werden nach dem Ortsnamen abgeschnitten.
- Temporärer Wohnort bleibt als aktueller Wetterort erhalten.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, drei Temporary-Housing-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `4ff6dad3 fix: trim temporary housing suffixes`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 658107`, Start `2026-07-18 14:27:15 CEST`.
- Seit diesem Restart: `2/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Monatsnamen in Wohnzeitqualifiern

- `Ich wohne seit Januar in Hamburg` und `Ich lebe seit März 2025 bei Potsdam` werden korrekt erkannt.
- Monatsname plus optionales Jahr ist zentraler Residence-Duration-Bestandteil; generisches Fehlpattern greift nicht mehr.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, zwei Month-Duration-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `87dc1735 fix: parse month residence durations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 658107`, Start `2026-07-18 14:27:15 CEST`.
- Seit diesem Restart: `3/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Qualifizierte Monatsdaten in Wohnzeit

- `seit dem 1. Januar`, `seit Anfang Januar` und `seit letztem Januar` werden als Zeitqualifier erkannt; Stadt bleibt Hamburg.
- Der generische Ortsmatcher kann diese Zeitphrase nicht mehr als Stadt übernehmen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, drei Qualified-Month-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `0d1bf547 fix: parse qualified month residence durations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 658107`, Start `2026-07-18 14:27:15 CEST`.
- Seit diesem Restart: `4/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Saisonale Wohnzeitqualifier

- `seit dem Sommer`, `seit Weihnachten` und `seit Anfang 2024` werden vor dem Wohnort erkannt.
- Zeitphrase wird nicht mehr als Stadtkandidat übernommen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, drei Seasonal-Duration-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c6505e36 fix: parse seasonal residence durations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 658107`, Start `2026-07-18 14:27:15 CEST`.
- Seit diesem Restart: `5/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Einzugs- und Studienzeitanker

- `seit dem Einzug`, `seit Beginn meines Studiums` und `seit dem ersten Tag` werden als Residence-Duration erkannt.
- Restphrase wird nicht als Stadt übernommen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, drei Move-In-Duration-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `2125337b fix: parse move-in residence durations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 658107`, Start `2026-07-18 14:27:15 CEST`.
- Seit diesem Restart: `6/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Zeitlicher Nebensatz als Negativfall

- `Ich wohne seit ich in Hamburg arbeite in Hamburg` liefert keinen falschen Stadtrest `seit ich`.
- Unterstützte `seit <Dauer>`-Formen wie `seit Januar` und `seit dem Einzug` bleiben aktiv.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, ein Temporal-Subordinate-Smoke plus zwei Regression-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `fd044b96 fix: reject temporal subordinate residence fragments`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 658107`, Start `2026-07-18 14:27:15 CEST`.
- Seit diesem Restart: `7/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Zukunftsdatum vor Wohnlabel

- `Ab Januar wohne ich in Hamburg`, `Ab dem 1. Januar ... wohnhaft` und `Ab dem Sommer ist mein Wohnort Hamburg` liefern keinen aktuellen Ort.
- Monats-/Saisonpräfixe laufen durch Future-Guard und City-Bereinigung; `seit ...` bleibt gültig.
- Erster Testlauf fand den Satzanfangs-Label-Kandidaten `Ab dem Sommer`; danach erneut `115 passed`, fünf Future/Current-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `f1206a2f fix: reject future residence date prefixes`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 658107`, Start `2026-07-18 14:27:15 CEST`.
- Seit diesem Restart: `8/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Wohnort mit Grundpräfix

- `Ich wohne wegen der Arbeit in Hamburg` und `Ich lebe aufgrund meines Studiums bei Potsdam` liefern Wohnort.
- `Ich arbeite wegen der Arbeit in Hamburg` bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, drei Reason-Prefix-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `88c6f2b8 fix: parse residence reason prefixes`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 658107`, Start `2026-07-18 14:27:15 CEST`.
- Seit diesem Restart: `9/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Kalenderdatum vor Wohnlabel

- `Am 1. Januar ist mein Wohnort Hamburg` und `Am 1. Mai bin ich in Hamburg wohnhaft` liefern keinen aktuellen Wohnort.
- Monatsnamen sind Nicht-Ort-Kontext; `am <Tag.Monat>` wird zusätzlich als Future-/Kalenderpräfix erkannt.
- Erster Lauf fand den direkten `bin ... wohnhaft`-Pfad; danach erneut `115 passed`, vier Calendar-Date-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `7f66dafe fix: reject calendar date residence prefixes`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 658107`, Start `2026-07-18 14:27:15 CEST`.
- Seit diesem Restart: `10/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Saisonale Zeitpräfixe vor Wohnsatz

- `Im Januar wohne ich in Hamburg`, `Im Sommer ... wohnhaft` und `Zu Weihnachten wohne ich in Hamburg` liefern keinen aktuellen Ort.
- `Seit Januar` und `Seit dem Sommer` bleiben als vergangene Zeitanker gültig.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, fünf Seasonal-Prefix-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `504e6fea fix: reject seasonal residence time prefixes`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 658107`, Start `2026-07-18 14:27:15 CEST`.
- Seit diesem Restart: `11/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Relativsatz mit Leben-Verb

- `Hamburg ist der Ort, in dem ich lebe` und `Der Ort, in dem ich lebe, ist Hamburg` liefern Hamburg.
- `in dem ich arbeite` bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, drei Living-Relative-Clause-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c8804d56 fix: parse living relative clauses`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 658107`, Start `2026-07-18 14:27:15 CEST`.
- Seit diesem Restart: `12/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Benannter Wohnort als Ort

- `Ich wohne an einem Ort namens Hamburg` und `Wir leben an einem Ort namens Potsdam` liefern Stadt.
- `Ich arbeite an einem Ort namens Hamburg` bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, drei Named-Place-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `d794d6d9 fix: parse named residence places`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 658107`, Start `2026-07-18 14:27:15 CEST`.
- Seit diesem Restart: `13/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Wohnort-Klarstellung nach Komma

- `Ich wohne in Hamburg, dem Ort, den ich Zuhause nenne` wird als Klarstellung erkannt und liefert Hamburg.
- `Zuhause nenne` wird nicht mehr als zweiter Wohnortkandidat gelesen; echte zweite Adressen bleiben mehrdeutig und liefern leer.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, vier Clarification-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `8c0d6553 fix: ignore residence clarification clauses`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 658107`, Start `2026-07-18 14:27:15 CEST`.
- Seit diesem Restart: `14/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Wohnort mit Grundphrase `aus ... Gründen`

- `Ich wohne aus beruflichen Gründen in Hamburg` und familiäre/gesundheitliche Varianten liefern den Wohnort.
- `Ich arbeite aus beruflichen Gründen in Hamburg` bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, drei Reason-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `cb9d3c84 fix: parse residence reason clauses`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 658107`, Start `2026-07-18 14:27:15 CEST`.
- Seit diesem Restart: `15/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Mehrfachwohnorte vor Auswahl sperren

- `teilweise`, `oder`, `beziehungsweise`, `abwechselnd`, `zwischen` und echte Plural-Labels wie `Wohnorte` werden vor der City-Auswahl als unaufgelöst erkannt.
- Adress-/Wohnortkonflikte werden ebenfalls vor Change-Patterns geprüft; `Meine Adresse ist Hamburg, mein Wohnort Berlin` liefert leer.
- Aufgelöste Wechsel wie `Ich wohne in Berlin und lebe jetzt in Hamburg` bleiben aktiv.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, Multiplicity-/Conflict-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `5deb119e fix: guard residence multiplicity before selection`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 658107`, Start `2026-07-18 14:27:15 CEST`.
- Seit diesem Restart: `16/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Relativsatz `dort, wo ich arbeite`

- `Ich wohne dort, wo ich arbeite: in Hamburg` und die Komma-Variante liefern Hamburg.
- Auch die umgekehrte Aussage `Ich arbeite dort, wo ich wohne: in Hamburg` bleibt als Wohnortbezug erkennbar.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, vier Relative-Work-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `48a5e106 fix: parse residence relative work clauses`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 658107`, Start `2026-07-18 14:27:15 CEST`.
- Seit diesem Restart: `17/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Ortslabel `Hansestadt`

- `Ich wohne in der Hansestadt Hamburg` nutzt nun denselben Ortsartenpfad wie `Gemeinde`, `Metropole` und `Hauptstadt`.
- `Ich arbeite in der Hansestadt Hamburg` bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, Hansestadt-Positiv-/Negativ-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `af458edd fix: parse hansestadt residence labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 658107`, Start `2026-07-18 14:27:15 CEST`.
- Seit diesem Restart: `18/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Genitiv-Richtungsflächen

- `Ich wohne in Hamburgs Norden` und `Ich lebe in Berlins Westen` werden auf Hamburg/Berlin normalisiert.
- Bestehende `im Norden von ...`- und normale Städtenamen bleiben unverändert.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, vier Direction-Genitive-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `2f2856bd fix: normalize genitive directional residence areas`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 658107`, Start `2026-07-18 14:27:15 CEST`.
- Seit diesem Restart: `19/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Zeitqualifizierter Wohnortwechsel

- `Ich wohne aktuell in Hamburg, seit Januar in Berlin` erkennt Berlin als jüngeren aktuellen Wohnort.
- Erster Wohnort darf nun ebenfalls Zeitqualifier tragen; Zukunftsangaben und Arbeitsort-Wechsel bleiben korrekt getrennt.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, vier temporal-change-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `3b0d48bd fix: resolve residence changes with duration qualifiers`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1795209`, Start `2026-07-18 15:37:30 CEST`.
- Seit diesem Restart: `0/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Weitere Ortsarten

- `Hafenstadt`, `Universitätsstadt`, `Kreisstadt` und `Landeshauptstadt` werden als Wohnortpräfixe erkannt.
- Aktivitätskontext wie `Ich arbeite in der Hafenstadt Hamburg` bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, fünf City-Type-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `b65000d9 fix: parse additional city type labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1795209`, Start `2026-07-18 15:37:30 CEST`.
- Seit diesem Restart: `1/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Ausbildungs- und Lehrzeit

- `während der Ausbildung`, `nach der Ausbildung` und `nach der Lehre` werden wie bestehende Studienzeitphrasen als Wohnkontext erkannt.
- `Ich arbeite während der Ausbildung ...` bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, fünf Training-Time-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `5f2e407d fix: parse residence during vocational training`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1795209`, Start `2026-07-18 15:37:30 CEST`.
- Seit diesem Restart: `2/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Aktueller Zustand nach historischem Label

- `Hamburg war mein Wohnort, heute ist/bin/lebe ich in Berlin` liefert Berlin statt `ist es Berlin` oder einer Restphrase.
- Arbeitskontext wie `Berlin war mein Wohnort, ich arbeite jetzt in Hamburg` bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, sechs Historical-State-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `84ab346a fix: parse current state after historical residence`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1795209`, Start `2026-07-18 15:37:30 CEST`.
- Seit diesem Restart: `3/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Ausbildungs-/Abschluss-Daueranker

- `seit Beginn/Ende/Abschluss meiner Ausbildung`, `seit dem Abschluss meines Studiums`, `seit Beginn meiner Lehre` und `seit meiner Ausbildung` werden als Daueranker erkannt.
- Bestehende Studien-/Einzugsanker bleiben unverändert.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, sieben Duration-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e1502f1e fix: parse training and graduation residence durations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1795209`, Start `2026-07-18 15:37:30 CEST`.
- Seit diesem Restart: `4/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Qualifizierte Umzugsdauer

- `seit dem letzten Umzug`, `seit meinem vergangenen Umzug` und `seit dem ersten Einzug` werden als Daueranker erkannt.
- Einfacher `seit dem Umzug`-Pfad bleibt unverändert.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, vier Move-Duration-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `da12f153 fix: parse qualified move residence durations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1795209`, Start `2026-07-18 15:37:30 CEST`.
- Seit diesem Restart: `5/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Wohnzeit nach Umzug

- `Ich wohne nach meinem Umzug in Dresden` und `nach dem Umzug in Bonn` nutzen nun den vorhandenen Studien-/Ausbildungszeitpfad.
- Direkte Umzugsverben bleiben davon getrennt.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, vier Post-Move-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `2b927571 fix: parse residence after move context`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1795209`, Start `2026-07-18 15:37:30 CEST`.
- Seit diesem Restart: `6/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Begrenzte Wohnzeiträume vor Ortsangabe

- `für zwei Wochen/ein Jahr in ...` wird wie die bestehende Dauer nach der Ortsangabe erkannt.
- Nichtzeitliche Phrasen mit `für` werden nicht als Wohnort gewertet.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, vier Bounded-Duration-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `4513e5a3 fix: parse bounded residence durations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1795209`, Start `2026-07-18 15:37:30 CEST`.
- Seit diesem Restart: `7/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Dauer- und Befristungsadjektive

- `langfristig`, `kurzfristig`, `befristet`, `unbefristet`, `vorläufig` und Varianten werden vor dem Ortsnamen als Zeitkontext erkannt.
- Arbeitskontext bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, vier Duration-Adjective-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `1b72992c fix: parse residence duration adjectives`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1795209`, Start `2026-07-18 15:37:30 CEST`.
- Seit diesem Restart: `8/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Mietstatus vor Ortsangabe

- `zur Miete`, `zur Zwischenmiete` und `zur Untermiete` werden vor der Ortsangabe als Wohnkontext erkannt.
- Mietstatus in Arbeitsphrasen bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, fünf Rental-Status-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `77449118 fix: parse rental status before residence`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1795209`, Start `2026-07-18 15:37:30 CEST`.
- Seit diesem Restart: `9/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Übergangs- und Zwischenwohnung

- `in einer Übergangswohnung` und `in einer Zwischenwohnung` werden im bestehenden Housing-Type-Pattern erkannt.
- Reine Besitzangabe wie `Ich habe eine Übergangswohnung ...` bleibt kein Wohnortsignal.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, vier Housing-Type-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `27692136 fix: parse transitional housing residence`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1795209`, Start `2026-07-18 15:37:30 CEST`.
- Seit diesem Restart: `10/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Befristungs-Endanker

- `bis auf Weiteres`, `bis zum Ende des Monats/Jahres` und `bis Ende des Jahres` werden vor sowie nach der Ortsangabe als aktueller Wohnzeitraum erkannt.
- Arbeitskontext bleibt ausgeschlossen; zentrale City-Abbruchlogik entfernt Endanker hinter dem Ort.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, sechs End-Date-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `f8e7ba17 fix: parse residence end-date qualifiers`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1795209`, Start `2026-07-18 15:37:30 CEST`.
- Seit diesem Restart: `11/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Umzug mit vorgeschaltetem Umzugskontext

- `Ich bin nach dem Umzug nach Bonn gezogen` sowie `nach meinem Umzug in Bonn umgezogen` werden als aktueller Zielort erkannt.
- Bereits funktionierende Formen `Nach dem Umzug bin ich ...` bleiben unverändert.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, fünf Umzugs-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `9ef9208b fix: parse post-move destination wording`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1795209`, Start `2026-07-18 15:37:30 CEST`.
- Seit diesem Restart: `12/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Nominativische Dauerpluralformen

- Daueranker akzeptieren nun auch `Tage`, `Monate` und `Jahre`; flektierte Formen wie `Tagen`, `Monaten`, `Jahren` bleiben erhalten.
- Arbeitskontext wird weiterhin nicht als Wohnortsignal gewertet.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, sieben Duration-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a95f0a16 fix: parse nominative duration plurals`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1795209`, Start `2026-07-18 15:37:30 CEST`.
- Seit diesem Restart: `13/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Numerische Wohnzeit-Daten

- `seit dem 01.01.2025`, `seit dem 1.1.2025` und `seit dem 1.1.` werden als vergangene Zeitanker vor dem Wohnort erkannt.
- Arbeitsphrasen mit demselben Datum bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, vier Date-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `11dbe54e fix: parse numeric residence dates`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1795209`, Start `2026-07-18 15:37:30 CEST`.
- Seit diesem Restart: `14/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Zukünftige numerische Wohntermine

- `ab dem 01.01.2027`, `ab 01.01.2027` und `am 01.01.2027` blockieren nun Wohnortübernahme als Zukunftsangabe.
- Vergangene `seit dem 01.01.2025`-Angaben bleiben gültig.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, fünf Future-Date-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `962ca6c9 fix: reject future numeric residence dates`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1795209`, Start `2026-07-18 15:37:30 CEST`.
- Seit diesem Restart: `15/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Wohn-Relativsätze

- `Der Ort, in dem ich wohne, ist Berlin` und `Berlin ist der Ort, in dem ich wohne` werden nun wie `lebe` erkannt.
- `in dem ich arbeite` bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, drei Relativsatz-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `b1a3737e fix: parse wohnen relative residence clauses`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1795209`, Start `2026-07-18 15:37:30 CEST`.
- Seit diesem Restart: `16/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Aktivitätsziel nach Zwar-Aber-Wechsel

- `Ich wohne zwar in Berlin, aber in Hamburg lebe ich` begrenzt Zielort nun auf `Hamburg`; nachgestellte Verben werden nicht verschluckt.
- `in Hamburg arbeite/studiere ich` überschreibt Wohnort Berlin nicht.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, fünf Wechsel-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e9ac1eaf fix: keep activity after change target out`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1795209`, Start `2026-07-18 15:37:30 CEST`.
- Seit diesem Restart: `17/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Expliziter Zuhause-Wechsel

- Nach `Ich wohne in Berlin, aber mein Zuhause/Wohnort/Lebensmittelpunkt ist Hamburg` wird Hamburg als aktueller Wohnort priorisiert.
- `in/bei Hamburg` nach Label wird ebenfalls erkannt; Aktivitätskontext bleibt separat.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, fünf Home-Label-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `1bab39f8 fix: prioritize explicit home label changes`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1795209`, Start `2026-07-18 15:37:30 CEST`.
- Seit diesem Restart: `18/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Temporale Zuhause-Wechsel

- `war ... heute/heute liegt ...`, `ist ... jetzt aber ...` und entsprechende Wohnortvarianten werden als aktueller Wechsel erkannt.
- Historische Home-Angabe mit anschließendem Arbeitsort bleibt leer und wird nicht als Wohnort übernommen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, fünf Home-Zeit-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `9bc5493f fix: parse temporal home transitions`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1795209`, Start `2026-07-18 15:37:30 CEST`.
- Seit diesem Restart: `19/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Historische Wohnwechsel mit Prädikat

- `wohnte/lebte ... lebe/wohne/bin jetzt ...` sowie `war ... wohnhaft ... bin jetzt ...` erkennen aktuellen Zielort.
- `arbeite jetzt ...` bleibt als reiner Arbeitsort ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, fünf historische Wechsel-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `33363590 fix: parse historical residence transitions`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1795209`, Start `2026-07-18 15:37:30 CEST`.
- Seit diesem Restart: `20/20` Code-Fixes. Restart jetzt erforderlich.

## Restart-Ledger 2026-07-18

- `systemctl --user restart teebotus.service` erfolgreich.
- Service `active/running`, `MainPID 2665587`, Start `2026-07-18 16:33:14 CEST`.
- Neuer Zyklus: `0/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Umzug von/in nach Zielort

- `Ich bin in/bei Berlin nach Hamburg gezogen/umgezogen` liefert nun Hamburg statt des gesamten Ausgangssegments.
- Arbeitsform `Ich bin in Berlin und arbeite in Hamburg` bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, vier Move-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `92002f4c fix: parse in-to destination moves`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2665587`, Start `2026-07-18 16:33:14 CEST`.
- Seit diesem Restart: `1/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: First-Person-Wohnortwechsel

- `Ich wechselte/wechsle von Berlin nach Hamburg` und `Wir wechselten aus Berlin zu Hamburg` werden als Wohnortwechsel erkannt.
- Zusätze wie `beruflich` bleiben kein Wohnortsignal.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, drei Wechsel-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `7e014511 fix: parse first-person residence switches`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2665587`, Start `2026-07-18 16:33:14 CEST`.
- Seit diesem Restart: `2/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Verändern-Verb beim Wohnortwechsel

- `Wohnort/Wohnsitz hat sich ... verändert/veraendert` wird nun wie `geändert/geaendert` erkannt.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, drei Change-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c330a2e9 fix: parse residence change verb variants`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2665587`, Start `2026-07-18 16:33:14 CEST`.
- Seit diesem Restart: `3/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Neuer Wohnort mit Gegenwartsmarker

- `Hamburg ist jetzt mein neuer Wohnort` und `Berlin ist nun unser neuer Wohnsitz` werden erkannt.
- Zukunftsform `wird ... neuer Wohnort` bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, vier New-Residence-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `f8577340 fix: parse current new residence labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2665587`, Start `2026-07-18 16:33:14 CEST`.
- Seit diesem Restart: `4/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Temporales „als Wohnort“

- `Ich habe jetzt/nun/aktuell Hamburg als Wohnort/Wohnsitz` entfernt den Zeitmarker aus der City und speichert Hamburg.
- `als Arbeitsort` bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, vier Residence-as-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `0f2efd5c fix: parse temporal residence-as labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2665587`, Start `2026-07-18 16:33:14 CEST`.
- Seit diesem Restart: `5/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Unbestimmter fester Wohnsitz

- `Ich habe einen festen/ständigen/permanenten Wohnort/Wohnsitz/Hauptwohnsitz in/bei ...` wird erkannt.
- Arbeitsort bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, vier Fixed-Residence-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `7581007f fix: parse indefinite fixed residence labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2665587`, Start `2026-07-18 16:33:14 CEST`.
- Seit diesem Restart: `6/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Meldungsrichtung und Kontextschutz

- `gegenwärtig bei Potsdam gemeldet` und `Bei Leipzig bin ich gemeldet` werden erkannt.
- `zur Schule`, berufliche/dienstliche Registrierung und Mehrfachorte mit `und/oder` bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, sechs Registration-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `015d237c fix: guard residence registration contexts`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2665587`, Start `2026-07-18 16:33:14 CEST`.
- Seit diesem Restart: `7/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Residieren-Verbflexionen

- `Ich residiere`, `Wir residieren` und `Sie residiert` werden nun als Wohnortsignal erkannt.
- Beruflicher Zusatz bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, vier Residieren-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `7ec8716a fix: parse residence verb inflections`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2665587`, Start `2026-07-18 16:33:14 CEST`.
- Seit diesem Restart: `8/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Nackte Wohnadresslabels

- `Meldeadresse`, `Meldeanschrift`, `Meldesitz`, `Privatadresse` und `Privatanschrift` mit Doppelpunkt werden als Wohnortquelle erkannt.
- Arbeits-/Geschäfts-/Rechnungsadressen und Mehrfachorte bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, sechs Address-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `3ec18f41 fix: parse bare residence address labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2665587`, Start `2026-07-18 16:33:14 CEST`.
- Seit diesem Restart: `9/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Länderpräzisierung bei Wohnadressen

- `Adresse/Wohnadresse/Privatadresse ist in Deutschland/Österreich/der Schweiz, genauer gesagt in ...` liefert konkrete Stadt.
- Geschäftsadresse bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, vier Country-Address-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `2d67eb9b fix: parse country-qualified residence addresses`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2665587`, Start `2026-07-18 16:33:14 CEST`.
- Seit diesem Restart: `10/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Temporale Wohnangabe mit Doppelpunkt

- `Ich wohne aktuell: Dresden`, `Ich lebe derzeit: Bonn` und `Wir wohnen zur Zeit: Leipzig` werden erkannt.
- Arbeitsform mit Doppelpunkt bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, vier Colon-Residence-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c79fe3e4 fix: parse colon temporal residence statements`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2665587`, Start `2026-07-18 16:33:14 CEST`.
- Seit diesem Restart: `11/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Wohnort-Frage mit Antwort

- `Wo ich wohne? In Berlin`, `Wo lebe ich: in Hamburg` und `Wo wohnen wir? Bei Potsdam` werden als Wohnortantwort erkannt.
- Arbeitsfrage `Wo arbeite ich?` bleibt leer.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, vier Question-Answer-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `b2392aff fix: parse residence question answers`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2665587`, Start `2026-07-18 16:33:14 CEST`.
- Seit diesem Restart: `12/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Wohnort vor Geburtsort priorisieren

- `Geburtsort/Geburtsstadt ... Wohnort/Wohnsitz ...` liefert den Wohnort statt den Geburtsort.
- Arbeitsort-Kombinationen bleiben leer.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, fünf Birth-Residence-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `4fbf5650 fix: prioritize residence over birth place`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2665587`, Start `2026-07-18 16:33:14 CEST`.
- Seit diesem Restart: `13/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Relativsatz-Ortsformen

- `Berlin ist die Stadt wo/in der ich wohne/lebe` sowie `Berlin ist dort/da, wo ich wohne/lebe` werden erkannt.
- Arbeitsrelativsatz bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, fünf Relative-Locality-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `4ef75054 fix: parse relative locality residence clauses`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2665587`, Start `2026-07-18 16:33:14 CEST`.
- Seit diesem Restart: `14/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Ortsarten mit Dativpräposition

- `Ich wohne/lebe an/in dem Ort ...` wird erkannt.
- Arbeitsform `Ich arbeite an dem Ort ...` bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, vier Locality-Type-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `47540f15 fix: parse residence locality types`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2665587`, Start `2026-07-18 16:33:14 CEST`.
- Seit diesem Restart: `15/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Gelabelte Stadt-/Ort-Formen

- `Mein Zuhause ist die Stadt Hamburg` und `Mein Zuhause ist der Ort Potsdam` werden erkannt.
- `Mein Arbeitsort ist die Stadt Hamburg` bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, drei Labeled-City-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `906f3496 fix: parse labeled city residence forms`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2665587`, Start `2026-07-18 16:33:14 CEST`.
- Seit diesem Restart: `16/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Wohnverb mit Zuhause-Adverb

- `Ich wohne/lebe zu Hause/zuhause/daheim in ...` liefert den Ort statt des Adverbs.
- Arbeitsform `Ich arbeite zu Hause in ...` bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, drei Home-Adverb-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `1cad467b fix: parse home adverb residence forms`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2665587`, Start `2026-07-18 16:33:14 CEST`.
- Seit diesem Restart: `17/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Wohnort-Label „lautet“

- `Mein Wohnort lautet Berlin` wird als Berlin erkannt statt `lautet Berlin`.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, ein Label-Lautet-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `b31bb597 fix: parse residence label lautet`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2665587`, Start `2026-07-18 16:33:14 CEST`.
- Seit diesem Restart: `18/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Relativsatz mit „Platz“

- `Berlin ist der Platz, an dem ich wohne` und `Der Platz, an dem ich lebe, ist Hamburg` werden erkannt.
- Arbeitsrelativsatz bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, drei Place-Relative-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `d010fab8 fix: parse place relative residence clauses`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 2665587`, Start `2026-07-18 16:33:14 CEST`.
- Seit diesem Restart: `19/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Nachgestelltes „dahoam“

- `Ich bin in Hamburg dahoam` wird als Hamburg erkannt.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, ein Dahoam-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c054fed4 fix: parse dahoam residence suffix`.

## Aktueller Ledger 2026-07-18-Nach-20-Fixes

- Vor Restart: Service soll nach diesem 20. Code-Fix neu geladen werden.
- Seit letztem Restart: `20/20` Code-Fixes. Kein Push.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 168706`, Start `2026-07-18 18:24:15 CEST`.
- Seit diesem Restart: `0/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Elliptische Wohnlabel-Klauseln

- `Geburtsort ..., Arbeit ..., mein Zuhause Potsdam` liefert Potsdam.
- Mehrfach-Wohnlabel (`Wohnort Berlin, Zuhause Hamburg`) bleibt absichtlich leer; historische Wohn-/Arbeitsklauseln bleiben geschützt.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, fünf Elliptical-Residence-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a62f51a9 fix: parse elliptical residence label clauses`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 168706`, Start `2026-07-18 18:24:15 CEST`.
- Seit diesem Restart: `1/20` Code-Fixes. Kein Push.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3561310`, Start `2026-07-18 17:31:15 CEST`.
- Seit diesem Restart: `0/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Präpositionslose Wohnortlabels

- `Mein Wohnort befindet sich Berlin` und `Mein Wohnsitz liegt Hamburg` werden erkannt.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, zwei Unqualified-Label-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `f2a085fc fix: parse unqualified residence label locations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3561310`, Start `2026-07-18 17:31:15 CEST`.
- Seit diesem Restart: `1/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Zeitadverb vor Wohnverb mit Doppelpunkt

- `Aktuell wohne ich: Hamburg` und `Derzeit leben wir: Potsdam` werden erkannt.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, zwei Prefixed-Temporal-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `874fa374 fix: parse prefixed temporal residence labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3561310`, Start `2026-07-18 17:31:15 CEST`.
- Seit diesem Restart: `2/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Bare-Wohnhaft-Phrase

- `In Berlin wohnhaft` wird als Berlin erkannt.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, ein Bare-Residence-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `9ecc3087 fix: parse bare wohnhaft residence phrases`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3561310`, Start `2026-07-18 17:31:15 CEST`.
- Seit diesem Restart: `3/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Inverse Wohnort-Labels

- `Mein Zuhause/Wohnort nenne ich ...` wird erkannt.
- `Mein Arbeitsort nenne ich ...` bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, drei Inverse-Label-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `36cb826a fix: parse inverse residence labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3561310`, Start `2026-07-18 17:31:15 CEST`.
- Seit diesem Restart: `4/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Wohnort-Apposition

- `Berlin, mein Wohnort` und `Hamburg, unser Zuhause` werden erkannt.
- `Berlin, mein Arbeitsort` bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, drei Appositions-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `fc0ded1f fix: parse appositive residence statements`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3561310`, Start `2026-07-18 17:31:15 CEST`.
- Seit diesem Restart: `5/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Kontrahierte Ortsart „am Ort“

- `Ich wohne/lebe am Ort ...` wird erkannt; `Ich arbeite am Ort ...` bleibt leer.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, drei Am-Ort-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `3684152e fix: parse contracted residence locality forms`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3561310`, Start `2026-07-18 17:31:15 CEST`.
- Seit diesem Restart: `6/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Invertierte Registrierungs-Kontexte

- `Gemeldet/Registriert bin ich in ...` wird erkannt.
- Berufliche, dienstliche, Schul- und Arbeitskontexte bleiben ausgeschlossen; Schutz gilt auch bei Teilmatch ab `gemeldet/registriert`.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, sechs Registration-Inversion-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `ee6c7fe9 fix: guard reversed residence registration context`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3561310`, Start `2026-07-18 17:31:15 CEST`.
- Seit diesem Restart: `7/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Kopuläre Wohnort-Relativsätze

- `Berlin ist, wo ich wohne` und `Wo ich wohne, ist Berlin` werden erkannt.
- Arbeitsrelativsätze bleiben leer.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, vier Copular-Relative-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `1c6d2ae4 fix: parse copular residence relative clauses`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3561310`, Start `2026-07-18 17:31:15 CEST`.
- Seit diesem Restart: `8/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Zuhause-Label „lautet“

- `Mein Zuhause lautet Hamburg` wird erkannt.
- `Mein Arbeitsort lautet Hamburg` bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, zwei Zuhause-Lautet-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `2177efda fix: parse zuhause lautet labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3561310`, Start `2026-07-18 17:31:15 CEST`.
- Seit diesem Restart: `9/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Gegenrichtung „wird ... genannt“

- `Berlin wird mein Wohnort genannt` und `Hamburg wird unser Zuhause genannt` werden erkannt.
- Arbeitsort-Label bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, drei Reversed-Named-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `853ef32a fix: parse reversed named residence clauses`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3561310`, Start `2026-07-18 17:31:15 CEST`.
- Seit diesem Restart: `10/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Umgangssprachliche Verbendstellung

- `Wohnen tue ich in Berlin` und `In Hamburg leben tue ich` werden erkannt.
- Arbeitsverb bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, drei Verb-Final-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `cab5f208 fix: parse colloquial verb-final residence forms`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3561310`, Start `2026-07-18 17:31:15 CEST`.
- Seit diesem Restart: `11/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Einfache gemeinsame Wohnform

- `Wir wohnen zusammen in Potsdam` wird erkannt.
- `Wir arbeiten zusammen in Berlin` bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, zwei Shared-Residence-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `93809855 fix: parse simple shared residence forms`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3561310`, Start `2026-07-18 17:31:15 CEST`.
- Seit diesem Restart: `12/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Gemeinsam-Mit-Wohnform

- `Ich wohne gemeinsam mit meiner Freundin in Dresden` und Wir-Formen werden erkannt.
- Arbeitsverb bleibt ausgeschlossen; bestehender Kontextschutz bleibt aktiv.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, drei Gemeinsam-Mit-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e114510b fix: parse gemeinsam mit residence forms`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3561310`, Start `2026-07-18 17:31:15 CEST`.
- Seit diesem Restart: `13/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Neben-Personenrelation

- `Ich wohne neben meiner Familie in Berlin` und Wir-Formen werden erkannt.
- `neben meiner Arbeit` bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, drei Neben-Relation-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c1b6d4f9 fix: parse neben residence relations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3561310`, Start `2026-07-18 17:31:15 CEST`.
- Seit diesem Restart: `14/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Herzen-von-/Genitiv-Ortsform

- `Ich wohne im Herzen von Hamburg` und `Ich lebe im Herzen Berlins` werden erkannt und Genitiv normalisiert.
- Arbeitsverb bleibt ausgeschlossen; bekannte `-s`-Stadtnamen bleiben erhalten.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, vier Heart-of-City-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a0db5ddd fix: parse heart-of-city residence forms`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3561310`, Start `2026-07-18 17:31:15 CEST`.
- Seit diesem Restart: `15/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Genitiv-Regionsform

- `Ich wohne in Berlins Gegend` und `Ich lebe in Münchens Region` werden normalisiert erkannt.
- Arbeitsverb bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, drei Genitive-Area-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `619b0a12 fix: parse genitive residence area forms`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3561310`, Start `2026-07-18 17:31:15 CEST`.
- Seit diesem Restart: `16/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Nachgestellte Landmarken

- `Ich wohne in Berlin an der Spree` und `Ich lebe in Hamburg am Rhein` liefern die Stadt statt Landmarke.
- `Frankfurt am Main` bleibt als vollständiger Stadtname erhalten.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, vier Landmark-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `26698d15 fix: trim postposed landmark residence context`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3561310`, Start `2026-07-18 17:31:15 CEST`.
- Seit diesem Restart: `17/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Wohnform „am See bei ...“

- `Ich wohne am See bei Potsdam` und `Ich lebe am See nahe Berlin` werden erkannt.
- Arbeitsform bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, drei Am-See-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `55a8d08a fix: parse residence near lake forms`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3561310`, Start `2026-07-18 17:31:15 CEST`.
- Seit diesem Restart: `18/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Kompakte Enddatumsangaben

- `Ich wohne bis Jahresende/Monatsende in ...` wird als Wohnort erkannt.
- Arbeitsform bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, drei End-Date-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `d052a5e7 fix: parse compact residence end dates`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 3561310`, Start `2026-07-18 17:31:15 CEST`.
- Seit diesem Restart: `19/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Mehrfamilienhaus-Wohnform

- `Ich wohne in einem Mehrfamilienhaus in Bonn` wird erkannt.
- Arbeitsform bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, zwei Multifamily-Building-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `4599371e fix: parse multifamily residence buildings`.

## Aktueller Ledger 2026-07-18-Nach-20-Fixes

- Vor Restart: Service soll nach diesem 20. Code-Fix neu geladen werden.
- Seit letztem Restart: `20/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Qualifizierte Bleibe-Wohnform

- `Ich habe eine feste/dauerhafte/ständige/stabile Bleibe in/bei ...` wird erkannt.
- `Arbeitsbleibe` bleibt ausgeschlossen, damit Arbeitsort nicht als Wohnort gespeichert wird.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, drei Qualified-Bleibe-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `6328ff4e fix: parse qualified bleibe residence forms`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv nach dem planmaessigen Restart, `MainPID 168706`, Start `2026-07-18 18:24:15 CEST`.
- Seit diesem Restart: `2/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Zeitplan-Fragmente nicht als Wohnort werten

- Präpositionslose Sätze mit `von Montag bis Freitag`, `täglich`, `nachts`, `jeden Tag` und ähnlichen Zeitplanpräfixen liefern keinen Scheinstadtwert.
- Normale Sätze wie `Ich wohne weiterhin in Leipzig` und `Ich wohne in Berlin` bleiben unverändert.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, acht Schedule-Residence-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `d77e6495 fix: reject scheduled residence fragments`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv nach dem planmaessigen Restart, `MainPID 168706`, Start `2026-07-18 18:24:15 CEST`.
- Seit diesem Restart: `3/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Explizite Unterkunfts- und Mietformen

- `feste Unterkunft`, `Mietwohnung`, `miete eine Wohnung` und `in ... eine Bleibe` werden als Wohnortangabe erkannt.
- `Ich habe eine Wohnung in ...` und `Ich besitze eine Unterkunft in ...` bleiben Besitzangaben und liefern keinen Wohnort.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, acht Housing-Form-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `0aed1174 fix: parse explicit housing residence forms`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv nach dem planmaessigen Restart, `MainPID 168706`, Start `2026-07-18 18:24:15 CEST`.
- Seit diesem Restart: `4/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Herkunft mit bestätigtem Dort-Wohnen

- `Ich komme/stamme aus Berlin und wohne/lebe dort` liefert Berlin als aktuelle Residenz.
- `arbeite dort` bleibt ausgeschlossen und wird nicht als Wohnort fehlklassifiziert.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, drei Origin-and-There-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `bbb202d3 fix: parse origin residence confirmations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv nach dem planmaessigen Restart, `MainPID 168706`, Start `2026-07-18 18:24:15 CEST`.
- Seit diesem Restart: `5/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Erweiterte Herkunfts-Wohnbestätigung

- Kommaform, `weiterhin`/`immer noch` sowie `bin dort wohnhaft/ansässig` werden zusätzlich erkannt.
- `Ich komme aus Berlin, wohne aber jetzt in Hamburg` bleibt als Ortswechsel geschützt und liefert Hamburg.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, sieben Origin-and-There-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `2baacd88 fix: broaden origin residence confirmations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv nach dem planmaessigen Restart, `MainPID 168706`, Start `2026-07-18 18:24:15 CEST`.
- Seit diesem Restart: `6/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Ortsarten Landkreis und Dorf

- `auf dem/einem Dorf bei/in ...` sowie `im Kreis/Landkreis ...` werden als Ortsangabe erkannt.
- `arbeite im Landkreis ...` bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, fünf Locality-Form-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `7c7513b9 fix: parse district and village residence forms`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv nach dem planmaessigen Restart, `MainPID 168706`, Start `2026-07-18 18:24:15 CEST`.
- Seit diesem Restart: `7/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Postleitzahl-Suffixe normalisieren

- Fünfstellige Postleitzahl nach Stadt (`Berlin 10115`) wird entfernt, Stadt bleibt erhalten.
- Andere Ziffernformen bleiben ungültig; bestehende Adressformen bleiben unverändert.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, fünf Postal-Suffix-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `d8682f79 fix: normalize postal suffixes in residence cities`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv nach dem planmaessigen Restart, `MainPID 168706`, Start `2026-07-18 18:24:15 CEST`.
- Seit diesem Restart: `8/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Zeitplan- und Primärort-Kontext disambiguieren

- `nur am Wochenende` liefert keinen Scheinstadtwert.
- `manchmal` markiert Mehrfachwohnen; ein expliziter Primärortmarker (`hauptsächlich`, `überwiegend`, …) erlaubt weiterhin den Hauptort.
- `arbeite/studiere ... wo ich wohne/lebe` liefert die Stadt als Wohnort.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, sechs Schedule-Context-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `ca426e63 fix: disambiguate scheduled residence contexts`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv nach dem planmaessigen Restart, `MainPID 168706`, Start `2026-07-18 18:24:15 CEST`.
- Seit diesem Restart: `9/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Aktivitätsverknüpfte Wohnrelationen

- `arbeite/studiere ... wo/dort ich wohne/lebe` sowie `wohne dort, wo ich studiere/lerne` liefern den Wohnort.
- Ein bloßer Satz `Ich arbeite in ...` bleibt leer.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, sieben Activity-Residence-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `15aac3a9 fix: parse activity-linked residence relations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv nach dem planmaessigen Restart, `MainPID 168706`, Start `2026-07-18 18:24:15 CEST`.
- Seit diesem Restart: `10/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Copula-Labels für Zuhause und Bleibe

- `Das ist mein Zuhause in ...` sowie `... bleibt/ist unser Zuhause` werden erkannt.
- `... ist meine feste Bleibe` wird erkannt; Arbeitsort-/Arbeitsadresse-Labels bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, sieben Home-Label-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `fba9d52a fix: parse copular home labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv nach dem planmaessigen Restart, `MainPID 168706`, Start `2026-07-18 18:24:15 CEST`.
- Seit diesem Restart: `11/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Registrierungs-Qualifier und Schulkontext

- `offiziell/polizeilich/privat/dauerhaft/vorübergehend ... gemeldet/registriert/ansässig` wird auf die Stadt reduziert.
- `zur Schule` und `beruflich` bleiben Aktivitätskontext und werden nicht als Wohnort gespeichert.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, neun Registration-Context-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `d670b21a fix: normalize registration residence qualifiers`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv nach dem planmaessigen Restart, `MainPID 168706`, Start `2026-07-18 18:24:15 CEST`.
- Seit diesem Restart: `12/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Regionale Wohnortformen

- `Einzugsgebiet`, `Peripherie`, `Metropolregion` und `Gebiet um ...` werden auf Zielstadt normalisiert.
- `arbeite in der Peripherie ...` bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, fünf Regional-Form-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `7e4f4e1f fix: parse regional residence forms`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv nach dem planmaessigen Restart, `MainPID 168706`, Start `2026-07-18 18:24:15 CEST`.
- Seit diesem Restart: `13/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Inverse Zuhause- und Wohnsitzlabels

- `Stadt, daheim/dort bin/lebe ich` sowie `Ich habe in Stadt meinen Wohnsitz/meine Bleibe` werden erkannt.
- Unterschiedliche Wohnorte im selben Satz bleiben durch Konfliktprüfung leer.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, acht Inverse-Home-Label-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `1a8f0879 fix: parse inverse home labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv nach dem planmaessigen Restart, `MainPID 168706`, Start `2026-07-18 18:24:15 CEST`.
- Seit diesem Restart: `14/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Qualifizierte Wohnsitz- und Adresslabels

- Dauerhafter/privater/offizieller Wohnsitz mit `Ich habe ...` wird erkannt.
- Offizielle Adresse wird erkannt; dienstlicher/beruflicher Prefix bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, acht Qualified-Residence-Label-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `0538efed fix: parse qualified residence labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv nach dem planmaessigen Restart, `MainPID 168706`, Start `2026-07-18 18:24:15 CEST`.
- Seit diesem Restart: `15/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Qualifizierte Adresslabels

- Dauerhafte/feste/stabile Wohnadresse bzw. Wohnanschrift wird erkannt.
- Berufliche/Arbeitsadresse bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `115 passed`, fünf Qualified-Address-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `dab63ed7 fix: parse qualified address labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv nach dem planmaessigen Restart, `MainPID 168706`, Start `2026-07-18 18:24:15 CEST`.
- Seit diesem Restart: `16/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Absolute Wohnort-Negationen

- `keinesfalls/keineswegs/niemals/nirgendwo/nirgends/nie` wird nicht mehr als Stadt gespeichert.
- Negierte Korrekturen mit `sondern` liefern weiterhin den tatsächlichen Wohnort.
- Verifikation: `tests/test_weather_context.py` -> `116 passed`, fünf Absolute-Negation-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `ef592614 fix: reject absolute residence negations`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv nach dem planmaessigen Restart, `MainPID 168706`, Start `2026-07-18 18:24:15 CEST`.
- Seit diesem Restart: `17/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Häufigkeits- und Primärort-Kontext

- `oft/meist/gelegentlich/regelmäßig/selten/manchmal` wird nicht mehr als Stadtfragment gespeichert.
- `manchmal ... meistens/hauptsächlich/überwiegend ...` liefert den ausdrücklich priorisierten Ort.
- Verifikation: `tests/test_weather_context.py` -> `117 passed`, elf Frequency-Qualifier-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `4093bebb fix: disambiguate residence frequency qualifiers`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv nach dem planmaessigen Restart, `MainPID 168706`, Start `2026-07-18 18:24:15 CEST`.
- Seit diesem Restart: `18/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Personen- statt Ortsziele bei `bei`

- `bei Freunden/Bekannten/Kollegen/Eltern` ohne Stadt wird nicht mehr als Wohnort gespeichert.
- `bei Freunden in Berlin` und ähnliche Formen behalten die konkrete Stadt.
- Verifikation: `tests/test_weather_context.py` -> `118 passed`, fünf Person-Target-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `24037022 fix: reject person residence targets`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv nach dem planmaessigen Restart, `MainPID 168706`, Start `2026-07-18 18:24:15 CEST`.
- Seit diesem Restart: `19/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Gemeinsamer Haushaltskontext ohne Ort

- `gemeinsam mit Partnerin/Familie` ohne konkrete Stadt wird nicht mehr als Wohnort gespeichert.
- Die Form mit nachfolgender Stadt bleibt erkennbar.
- Verifikation: `tests/test_weather_context.py` -> `118 passed`, zwei Shared-Household-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `ae367502 fix: reject shared household context without city`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv vor dem planmaessigen Restart, `MainPID 168706`, Start `2026-07-18 18:24:15 CEST`.
- Seit diesem Restart: `20/20` Code-Fixes. Restart jetzt faellig. Kein Push.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 1590772`, Start `2026-07-18 19:56:08 CEST`.
- Seit diesem Restart: `0/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Zusammengesetzte Stadtnamen

- `Frankfurt an der Oder` und `Ludwigshafen am Rhein` werden nicht durch geografische Stopwörter gekürzt.
- Klammerzusätze wie `Halle (Saale)` bleiben erhalten; `Oder` wird nicht als Mehrfachort gewertet, wenn es Teil von `an der Oder` ist.
- Verifikation: `tests/test_weather_context.py` -> `119 passed`, sechs Compound-City-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `8693d919 fix: preserve compound residence city names`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 1590772`, Start `2026-07-18 19:56:08 CEST`.
- Seit diesem Restart: `1/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Stopwort-Prefixe in Stadtnamen

- Stopregex zerlegt Ortsnamen nicht mehr an Präpositionspräfixen wie `in`/`aus`/`als`/`unter`.
- `St. Ingbert`, `Ingolstadt`, `Immenstadt`, `Augsburg`, `Alsfeld`, `Unterhaching` und `Beilngries` bleiben vollständig.
- Verifikation: `tests/test_weather_context.py` -> `120 passed`, sieben Stopword-Prefix-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `76ea0940 fix: protect city names from stopword matching`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 1590772`, Start `2026-07-18 19:56:08 CEST`.
- Seit diesem Restart: `2/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Regionale Compound-Stadtnamen

- `Mülheim an der Ruhr`, `Brandenburg an der Havel`, `Wörth/Rüdesheim am Rhein`, `St. Georgen im Schwarzwald` und `Königstein im Taunus` bleiben vollständig.
- Kanonische Liste greift nur bei vollständigem Label; allgemeine geografische Stoplogik bleibt aktiv.
- Verifikation: `tests/test_weather_context.py` -> `121 passed`, sechs Regional-Compound-City-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `39be4513 fix: preserve regional compound city names`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 1590772`, Start `2026-07-18 19:56:08 CEST`.
- Seit diesem Restart: `3/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Parenthesized-Labels

- `Halle (Saale)` bleibt in Wohnort-, Wohnsitz-, Adress-, Besitz- und inversen Labels vollständig.
- Besitzbranch konsumiert `in/bei` jetzt mit Separator und greift dadurch auch bei `Ich habe ... in Halle (Saale)`.
- Verifikation: `tests/test_weather_context.py` -> `122 passed`, sechs Parenthetical-Label-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `d2bbe185 fix: preserve parenthetical residence labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 1590772`, Start `2026-07-18 19:56:08 CEST`.
- Seit diesem Restart: `4/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Kopulawörter als Fehlkandidaten

- In inversen Sätzen werden `ist/sind/bin` nicht mehr als Städte akzeptiert.
- Parenthesized-Inversformen wie `Halle (Saale) ist dort, wo ich wohne` liefern wieder den vollständigen Ort.
- Verifikation: `tests/test_weather_context.py` -> `123 passed`, fünf Parenthetical-Inverse-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e45145ae fix: reject copula words as residence cities`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 1590772`, Start `2026-07-18 19:56:08 CEST`.
- Seit diesem Restart: `5/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Parenthesized-Registration-Labels

- `Halle (Saale)` wird auch bei `gemeldet/ansässig`, `Bleibe` und `Ich habe in ... meinen Wohnsitz` erkannt.
- Arbeits- und Geburtsortlabels bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `124 passed`, sechs Parenthetical-Registration-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `59879672 fix: parse parenthetical registration labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 1590772`, Start `2026-07-18 19:56:08 CEST`.
- Seit diesem Restart: `6/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Unicode-Erstbuchstaben in Ortslabels

- Wohnort-/Adresslabels akzeptieren internationale Städte mit `Å/É/Č/Ž/Ø/Æ` und anderen Unicode-Buchstaben.
- Bestehende ASCII-/Sondermuster bleiben vorrangig; Arbeits- und Geburtslabels bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `125 passed`, sechs Unicode-Label-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a6c50589 fix: parse unicode residence label initials`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 1590772`, Start `2026-07-18 19:56:08 CEST`.
- Seit diesem Restart: `7/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Unbestimmte Labelwerte

- `irgendwo`, `unklar` und `egal` werden nicht mehr als Wohnort gespeichert.
- Konkrete Orte wie `Berlin` bleiben unverändert.
- Verifikation: `tests/test_weather_context.py` -> `126 passed`, vier Unknown-Label-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `efcb7044 fix: reject unknown residence label values`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 1590772`, Start `2026-07-18 19:56:08 CEST`.
- Seit diesem Restart: `8/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Nicht-Ort-Zustände

- `überall/ueberall`, `wechselnd`, `variabel`, `flexibel`, `offen`, `mobil` und `temporär` werden nicht als Wohnort gespeichert.
- Konkrete Städte bleiben unverändert.
- Verifikation: `tests/test_weather_context.py` -> `127 passed`, acht Non-Location-State-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `bfdf1fc2 fix: reject non-location residence states`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 1590772`, Start `2026-07-18 19:56:08 CEST`.
- Seit diesem Restart: `9/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Kontinental- und globale Regionen

- `Ausland`, `Inland`, `Europa`, `Afrika`, `Asien`, `Australien` und `Welt` werden nicht als Städte gespeichert.
- Konkrete Stadtlabels bleiben unverändert.
- Verifikation: `tests/test_weather_context.py` -> `128 passed`, zehn Continental-Region-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `d3e45aa4 fix: reject continental residence regions`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 1590772`, Start `2026-07-18 19:56:08 CEST`.
- Seit diesem Restart: `10/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Leere Regionsplatzhalter

- `Ich wohne in der Region` erzeugt keinen Einzelbuchstaben- oder Platzhalterort mehr.
- `Region Berlin` liefert weiterhin `Berlin`.
- Verifikation: `tests/test_weather_context.py` -> `129 passed`, drei Bare-Region-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `7498ab13 fix: reject bare residence region placeholders`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 1590772`, Start `2026-07-18 19:56:08 CEST`.
- Seit diesem Restart: `11/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Zitierte Wohnortlabels

- `Mein Wohnort lautet: Berlin`, deutsche Anführungszeichen, ASCII-Anführungszeichen und Klammerwerte werden korrekt gelesen.
- `lautet` wird nicht mehr als Stadtfragment gespeichert.
- Verifikation: `tests/test_weather_context.py` -> `130 passed`, sechs Quoted-Lautet-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `857c8667 fix: parse quoted residence labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 1590772`, Start `2026-07-18 19:56:08 CEST`.
- Seit diesem Restart: `12/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Benennungsverb-Fragmente

- `heißt/heisst/nennt/genannt` werden nicht mehr als Wohnortfragment gespeichert.
- Konkrete Formen wie `Mein Wohnort heißt Berlin` bleiben gültig.
- Verifikation: `tests/test_weather_context.py` -> `131 passed`, vier Naming-Verb-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `630bbda2 fix: reject residence naming verb fragments`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 1590772`, Start `2026-07-18 19:56:08 CEST`.
- Seit diesem Restart: `13/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Modale Wohnortbehauptungen

- `Mein Wohnort muss Berlin sein` wird nicht als sicherer Wohnort gespeichert.
- Direkte Tatsachenform `Mein Wohnort ist Berlin` bleibt gültig.
- Verifikation: `tests/test_weather_context.py` -> `132 passed`, zwei Modal-Residence-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c8c47112 fix: reject modal residence claims`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 1590772`, Start `2026-07-18 19:56:08 CEST`.
- Seit diesem Restart: `14/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Zitierte Compound- und Postleitzahlwerte

- `Halle (Saale)` und `10115 Berlin` werden in Wohnort-/Adresslabels korrekt normalisiert.
- Unausgeglichene schließende Klammern vor Satzzeichen werden bereinigt; echte Klammernamen bleiben erhalten.
- Verifikation: `tests/test_weather_context.py` -> `133 passed`, drei Quoted-Compound-Postal-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `31837154 fix: parse quoted compound postal residence values`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 1590772`, Start `2026-07-18 19:56:08 CEST`.
- Seit diesem Restart: `15/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Kompakte Gleichheitslabels

- `Mein Wohnort=„Bonn“` wird wie `Wohnort=...` korrekt erkannt.
- Keine Änderung an Konflikt- oder Negationslogik.
- Verifikation: `tests/test_weather_context.py` -> `134 passed`, ein Compact-Equals-Label-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c0ab6419 fix: parse compact residence equals labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 1590772`, Start `2026-07-18 19:56:08 CEST`.
- Seit diesem Restart: `16/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Rollen- und Korrekturformulierungen

- Korrekturen wie `Nicht Hamburg ist mein Wohnort, sondern Berlin` und `Hamburg ist nicht mein Wohnort, sondern Berlin` liefern nur aktuellen Wohnort Berlin.
- Expliziter `Lebensmittelpunkt`/`Hauptwohnsitz` überschreibt vorherige einfache Wohnangabe in derselben Aussage.
- `Geburtsort` und Arbeitsrollen werden bei strukturierten Wohnortlisten nicht fälschlich als zweiter Wohnort bewertet; unterschiedliche Wohn-/Arbeitsadressen bleiben Mehrdeutigkeitsfehler.
- Alte/aktuelle Wohnadressen werden in der Stadt-vor-Label-Form korrekt auf aktuellen Ort reduziert.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, acht gezielte Rollen-/Korrektur-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a122bab0 fix: resolve residence role corrections`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service nach planmaessigem Restart aktiv, `MainPID 3246`, Start `2026-07-18 22:44:34 CEST`.
- Seit diesem Restart: `19/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Widersprüchliche Wohn- und Meldeziele

- Zwei direkte aktuelle Wohnortlabels in getrennten Sätzen werden als Konflikt abgelehnt.
- `Meldeadresse` wird mit direktem Wohnort und Wohnadresse verglichen; unterschiedliche Angaben liefern keinen eindeutigen Ort.
- Arbeitsort/Geburtsort bleiben davon getrennt.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, sieben Konflikt-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `51a631b9 fix: reject conflicting residence records`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1080447`, Start `2026-07-18 23:52:22 CEST`.
- Seit diesem Restart: `0/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Direkte Labelkonflikte und Meldeadresse

- Direkte aktuelle Wohnort-/Zuhause-Labels werden vor Korrekturmustern auf Mehrfachkonflikte geprüft.
- `Meine Meldeadresse lautet Berlin` wird erkannt; abweichende Meldeadresse gegenüber Wohnort/Wohnadresse bleibt unbestimmt.
- Rollenangabe nach `/` (`Wohnort Berlin / Arbeitsort Hamburg`) wird nicht mehr als ungeklärter zweiter Wohnort gewertet.
- Historische Kompaktform `Hamburg war mein Wohnort, jetzt Berlin mein Wohnort` liefert Berlin.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, elf gezielte Konflikt-/Rollen-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `66d7f866 fix: guard direct residence label conflicts`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1080447`, Start `2026-07-18 23:52:22 CEST`.
- Seit diesem Restart: `1/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Kompakte Inversionen und Meldeadresslabels

- `Berlin wohne ich` und `Berlin lebe ich` werden mit Satzgrenze erkannt; Negation bleibt ausgeschlossen.
- Bare `Meldeadresse Berlin` wird wie die bestehende Doppelpunktform erkannt.
- Präzise Wohnortlabels bleiben von Arbeits-/Aufenthaltsformulierungen getrennt.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, zwölf gezielte Inversions-/Meldeadress-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `8c51fed1 fix: parse compact residence inversions`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1080447`, Start `2026-07-18 23:52:22 CEST`.
- Seit diesem Restart: `2/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Temporale und regionale Wohnortvarianten

- `Berlin war mein Wohnort, aber Hamburg ist jetzt mein Wohnort` liefert Hamburg ohne Konnektorfragment.
- Widerspruch `Mein Wohnort ist Berlin, bleibt aber Hamburg` wird sicher abgelehnt.
- Direkte Region `Ich wohne im Berliner Norden` und Adjektiv `vorübergehender Wohnort` werden korrekt normalisiert.
- Historische Wohnortangaben bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, sieben Zeit-/Region-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `5fd6ea26 fix: parse temporal residence variants`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1080447`, Start `2026-07-18 23:52:22 CEST`.
- Seit diesem Restart: `3/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Unsichere Wohnortbehauptungen

- Prefixe wie `Vielleicht`, `vermutlich`, `möglicherweise`, `eventuell`, `wahrscheinlich`, `wohl`, `angeblich` und `anscheinend` blockieren Speicherung sicherer Wohnorte.
- Der Guard arbeitet vor eigentlichen Regex-Matches und verhindert dadurch auch Matchverschiebung auf `wohne in ...`.
- Direkte Tatsachenformen und explizite Korrekturen bleiben gültig.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, sieben Unsicherheits-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `b44c2600 fix: reject uncertain residence claims`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1080447`, Start `2026-07-18 23:52:22 CEST`.
- Seit diesem Restart: `4/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Ausgeschriebene Entfernungsangaben

- Zahlwörter wie `fünf`, `zehn`, `zwanzig`, `hundert` und `tausend` sind im Distanzpräfix gültig.
- `fünf Kilometer von Berlin entfernt` und `fünf Kilometer außerhalb von Berlin` liefern Berlin.
- Arbeitskontext bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, sechs Distanz-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `85ffc991 fix: parse residence distance forms`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1080447`, Start `2026-07-18 23:52:22 CEST`.
- Seit diesem Restart: `5/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Gemeinsame und aktuelle Wohnformen

- `Wir haben Berlin als Wohnort` akzeptiert korrekte Pluralform.
- Aktuelle Wohnungsqualifier vor dem Nomen (`Meine jetzige Wohnung liegt in Berlin`) werden erkannt.
- Besitz einer beliebigen Wohnung und bloße Unterbringung bleiben ohne explizite Wohnbehauptung unzureichend.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, fünf Wohnform-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `03cffb5f fix: parse shared and current housing forms`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1080447`, Start `2026-07-18 23:52:22 CEST`.
- Seit diesem Restart: `6/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Persistente Zeitlabels und Pronomenkorrektur

- `schon immer` wird als aktuelle stabile Wohnangabe unterstützt.
- Zeitangaben zwischen Stadt und Label (`Berlin ist seit 2020 mein Wohnort`) werden erkannt.
- `weiterhin`, `vorerst` und `bis auf Weiteres` funktionieren auch nach `ist/bleibt`.
- `Berlin ist nicht mehr mein Wohnort, Hamburg ist es` liefert Hamburg.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, elf Zeit-/Pronomen-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `481cd6df fix: parse persistent residence time labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1080447`, Start `2026-07-18 23:52:22 CEST`.
- Seit diesem Restart: `7/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Strukturierte Wohnortprofile

- Bare `Meldeadresse Berlin` wird bei abweichendem `Wohnort Hamburg` als Konflikt behandelt.
- Country-Refinement `Wohnort Deutschland, Berlin` liefert Berlin.
- `genauer gesagt`, `konkret`, `nämlich` und `und zwar` werden dabei nicht als Stadtfragment gespeichert.
- Arbeits-/Geburtsort bleiben als nicht-residentielle Zusatzfelder zulässig.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, zehn strukturierte Label-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a61accb5 fix: resolve structured residence labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1080447`, Start `2026-07-18 23:52:22 CEST`.
- Seit diesem Restart: `8/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Umzugs- und Korrekturvarianten

- Korrekturformen wie `genau genommen` und `beziehungsweise in` liefern aktuellen Wohnort statt historischem Erstwert.
- Umzugs-/Ummeldungsformen, `Nach dem Umzug ...` und Wohnortwechsel mit `war ...; jetzt ...` werden erkannt.
- `endgültig`/`endgueltig` gilt als stabiler aktueller Wohnort-Qualifier.
- Mehrdeutiges `beziehungsweise` ohne `in/bei` bleibt abgelehnt.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, zehn gezielte Umzugs-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `8422982d fix: parse residence move corrections`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1080447`, Start `2026-07-18 23:52:22 CEST`.
- Seit diesem Restart: `9/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Widersprüchliche Gebietsziele

- `Berlin und Umgebung von Hamburg` sowie analoge `Region`-/`Nähe`-Formen werden nicht mehr fälschlich als Berlin gespeichert.
- Das gültige Einzelziel `Berlin und Umgebung` bleibt erhalten.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, vier Gebiets-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `ed1ea265 fix: reject conflicting area residence targets`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1080447`, Start `2026-07-18 23:52:22 CEST`.
- Seit diesem Restart: `10/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Unsichere Selbstvermutungen

- `Ich glaube/denke/vermute ...`, `Ich nehme an ...` und `Soweit ich weiß ...` werden nicht als sichere Wohnortangabe gespeichert.
- Breit matchende Label-Regexe können diese Präfixe nicht mehr als Scheinstadt zurückgeben.
- Sichere Form `Ich wohne sicher in Berlin` bleibt gültig.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, sieben Unsicherheits-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e6b53748 fix: reject uncertain residence claims`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1080447`, Start `2026-07-18 23:52:22 CEST`.
- Seit diesem Restart: `11/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Unsicherheitswörter als Scheinstädte

- Roh-Captures wie `scheinbar`, `angeblich` oder `vielleicht` können nicht mehr als Stadtwert durchrutschen.
- Unsichere Wohnortformulierungen bleiben leer; sichere Formulierungen bleiben gültig.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, vier Unsicherheitswort-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `32665ea5 fix: block uncertainty pseudo-cities`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1080447`, Start `2026-07-18 23:52:22 CEST`.
- Seit diesem Restart: `12/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Nahe Wohnortlabels

- `Ich bin in der Nähe/Umgebung von Berlin wohnhaft` sowie `nahe ... ansässig` werden korrekt erkannt.
- Berufliche und dienstliche `ansässig`-/`wohnhaft`-Formen bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, fünf Nearby-Residence-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `53859c82 fix: parse nearby resident labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1080447`, Start `2026-07-18 23:52:22 CEST`.
- Seit diesem Restart: `13/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Arbeits-gegen-Wohnort-Konjunktion

- `Ich arbeite in Berlin, obwohl ich in Hamburg wohne` liefert Hamburg.
- Der Arbeitsort bleibt bei `obwohl ich ... studiere` oder ähnlichen Nicht-Wohnformen ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, drei `obwohl`-Kontext-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `da23f3e2 fix: parse residence obwohl clauses`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1080447`, Start `2026-07-18 23:52:22 CEST`.
- Seit diesem Restart: `14/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Konnektor-Sätze mit Wohnortbezug

- `weil`, `da`, `denn`, `wobei` und `während` verbinden Aktivitätsort und expliziten Wohnort korrekt.
- `dort wohne` bezieht sich sicher auf den genannten Aktivitätsort.
- Reine Aktivität (`obwohl ich studiere`) bleibt ohne Wohnortwert.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, fünf Konnektor-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `5928b8f9 fix: parse connector residence clauses`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1080447`, Start `2026-07-18 23:52:22 CEST`.
- Seit diesem Restart: `15/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Umgekehrte Aktivitäts-/Wohnortstellung

- `In Berlin arbeite ich und in Hamburg lebe ich` liefert Hamburg.
- Gleiche Satzstellung mit `studieren` bleibt ohne Wohnortwert.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, drei Inversions-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `d55f7fe3 fix: parse inverted activity residence clauses`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1080447`, Start `2026-07-18 23:52:22 CEST`.
- Seit diesem Restart: `16/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Beschriftete Rollenpaare

- `Arbeitsort`-/`Wohnort`-Paare in Klammern werden in beiden Reihenfolgen erkannt.
- Nicht-residentielle Labels wie `Studienort` bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, drei Rollenpaar-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `01610020 fix: parse labeled residence role pairs`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1080447`, Start `2026-07-18 23:52:22 CEST`.
- Seit diesem Restart: `17/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Terse Zuhause-Labels

- `Berlin, daheim`, `Potsdam, zuhause` und `Leipzig, zu Hause` liefern den genannten Wohnort.
- Arbeitskontext `Berlin, dort arbeite ich` bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, vier Kurzform-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `6627adf3 fix: parse terse home labels`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1080447`, Start `2026-07-18 23:52:22 CEST`.
- Seit diesem Restart: `18/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Wohnort vor Konnektor

- `Mein Wohnsitz liegt in Hamburg, obwohl/während ich in Berlin arbeite` behält Hamburg.
- Der nachgestellte Aktivitätsort wird nicht als Wohnort überschrieben.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, drei Residence-First-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c1710423 fix: parse residence-first connectors`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1080447`, Start `2026-07-18 23:52:22 CEST`.
- Seit diesem Restart: `19/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-18: Kompakte Zuhause-Ausdrücke

- `In Berlin zuhause`, `Berlin daheim` und `Berlin zu Hause` werden als Wohnort erkannt.
- Breit matchende Regexe überschreiben keine bestehenden Formen wie `Potsdam ist inzwischen unser Zuhause` oder Frage-Antwort-Sätze.
- Unvollständiges Label `Wohnort ist daheim` bleibt leer.
- Verifikation: `tests/test_weather_context.py` -> `157 passed`, sechs Compact-Home-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e18d1b28 fix: parse compact home expressions`.

## Aktueller Ledger 2026-07-18-Post-Restart

- Service aktiv, `MainPID 1080447`, Start `2026-07-18 23:52:22 CEST`.
- Seit diesem Restart: `20/20` Code-Fixes. Kein Push.

## Aktueller Ledger 2026-07-19-Post-Restart

- `teebotus.service` aktiv/running, `MainPID 2292239`, Start `2026-07-19 01:09:27 CEST`.
- Seit diesem Restart: `0/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Bekannte Stadtteil-Basen

- `Berlin-Kreuzberg`, `Hamburg-Altona`, `Köln-Deutz` und `Berlin-Mitte` werden für Wetter-/Wohnortzwecke auf jeweilige Stadtbasis normalisiert.
- Bekannte echte Kompositstädte wie `Frankfurt am Main` und `Frankfurt an der Oder` bleiben vollständig erhalten.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, fünf District-Normalization-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `b8d26c77 fix: normalize known city districts`.

## Aktueller Ledger 2026-07-19-Post-Restart

- `teebotus.service` aktiv/running, `MainPID 2292239`, Start `2026-07-19 01:09:27 CEST`.
- Seit diesem Restart: `1/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Negative Wohnortkorrekturen

- `Ich wohne nicht in Berlin, aber ich wohne in Hamburg` liefert Hamburg statt Scheinstadt `ich wohne`.
- Ellipse `Berlin ist nicht mein Wohnort, Hamburg schon` wird als Hamburg erkannt.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, vier Negative-Correction-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `ac5e5ed1 fix: parse negative residence corrections`.

## Aktueller Ledger 2026-07-19-Post-Restart

- `teebotus.service` aktiv/running, `MainPID 2292239`, Start `2026-07-19 01:09:27 CEST`.
- Seit diesem Restart: `2/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Negative Wohnortellipsen

- `bleibt es`, `kein/keinesfalls/niemals`, `nicht als Wohnort` und `Nicht X, sondern Y wohne ich` liefern aktuelle Wohnstadt Y.
- Nicht-Wohnverben bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, sieben Negative-Ellipse-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `985d9a57 fix: parse negative residence ellipses`.

## Aktueller Ledger 2026-07-19-Post-Restart

- `teebotus.service` aktiv/running, `MainPID 2292239`, Start `2026-07-19 01:09:27 CEST`.
- Seit diesem Restart: `3/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Kontrast-Konnektoren

- `auch wenn`, `trotzdem` und Label-Kontraste zwischen Arbeitsort und Wohnort liefern Wohnstadt.
- Gleichartige Arbeitsortangaben ohne Wohnortlabel bleiben leer.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, vier Contrast-Connector-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `f4237586 fix: parse contrast residence connectors`.

## Aktueller Ledger 2026-07-19-Post-Restart

- `teebotus.service` aktiv/running, `MainPID 2292239`, Start `2026-07-19 01:09:27 CEST`.
- Seit diesem Restart: `4/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Unsichere Wohnort-Suffixe

- Nachgestellte Unsicherheit (`glaube ich`, `denke ich`, `vermute ich`, `nehme ich an`) blockiert Wohnortspeicherung.
- Sichere Zusätze bleiben gültig.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, fünf Uncertainty-Suffix-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `98b3ac88 fix: reject uncertain residence suffixes`.

## Aktueller Ledger 2026-07-19-Post-Restart

- `teebotus.service` aktiv/running, `MainPID 2292239`, Start `2026-07-19 01:09:27 CEST`.
- Seit diesem Restart: `5/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Länderzusätze in Klammern

- `Berlin (Deutschland)` wird auf Berlin normalisiert.
- Echte Kompositstadt `Halle (Saale)` bleibt unverändert.
- Länder/Regionen werden nicht als Städte erfunden.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, drei Parenthesized-Location-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `4f99b457 fix: normalize parenthesized country suffixes`.

## Aktueller Ledger 2026-07-19-Post-Restart

- `teebotus.service` aktiv/running, `MainPID 2292239`, Start `2026-07-19 01:09:27 CEST`.
- Seit diesem Restart: `6/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Postpositive Sicherheitsadverbien

- `Ich wohne in Berlin, wirklich/sicher/tatsächlich` wird nicht mehr als Mehrfachziel verworfen.
- Echte Zweitstadt `Ich wohne in Berlin, Hamburg` bleibt mehrdeutig und leer.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, vier Confidence-Suffix-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `ac41a20c fix: allow confidence residence suffixes`.

## Aktueller Ledger 2026-07-19-Post-Restart

- `teebotus.service` aktiv/running, `MainPID 2292239`, Start `2026-07-19 01:09:27 CEST`.
- Seit diesem Restart: `7/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Qualifizierte Meldeadressen

- `Meine offizielle/private Meldeadresse ist Berlin` wird als Berlin erkannt.
- `Meine geschäftliche Adresse ist Berlin` wird nicht mehr als Wohnort gespeichert.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, vier Address-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `bcb0ee81 fix: parse qualified registered addresses`.

## Aktueller Ledger 2026-07-19-Post-Restart

- `teebotus.service` aktiv/running, `MainPID 2292239`, Start `2026-07-19 01:09:27 CEST`.
- Seit diesem Restart: `8/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Registrierte Wohnadressen

- Qualifizierte Meldeanschriften mit Doppelpunkt und `eine offizielle Meldeadresse in ...` werden erkannt.
- `Ich bin in Berlin amtlich gemeldet` liefert nur Berlin, nicht `Berlin amtlich`.
- `Berlin ist meine gemeldete Adresse` wird erkannt; Geschäftsadressen bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, fünf Registered-Residence-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `171e1b76 fix: parse registered residence variants`.

## Aktueller Ledger 2026-07-19-Post-Restart

- `teebotus.service` aktiv/running, `MainPID 2292239`, Start `2026-07-19 01:09:27 CEST`.
- Seit diesem Restart: `9/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Qualifier registrierter Wohnsitz

- `amtlich gemeldet/registriert` behält nur Stadtnamen und verschluckt Qualifier nicht als Stadtteil.
- `aktuelle`, `amtliche`, `neue` und `gemeldete Meldeadresse` werden erkannt.
- Arbeits-/Geschäftsadressen bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, sechs Qualifier-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `dfbdf953 fix: cover qualified registered addresses`.

## Aktueller Ledger 2026-07-19-Post-Restart

- `teebotus.service` aktiv/running, `MainPID 2292239`, Start `2026-07-19 01:09:27 CEST`.
- Seit diesem Restart: `10/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Gemischte Wohnadress-Ziele

- Direkte Aussagen wie `Berlin ist meine Wohnadresse. Hamburg ist mein Wohnort.` werden als widersprüchlich verworfen.
- Arbeits-/Geschäftsadressen bleiben aus dem Wohnziel-Konflikt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, vier Direct-Conflict-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `69efcc20 fix: reject mixed residence address targets`.

## Aktueller Ledger 2026-07-19-Post-Restart

- `teebotus.service` aktiv/running, `MainPID 2292239`, Start `2026-07-19 01:09:27 CEST`.
- Seit diesem Restart: `11/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Unaufgelöste `sondern`-Wohnsätze

- Unvollständige Kontrastsätze wie `Ich wohne in Berlin, sondern in Hamburg` speichern keinen Wohnort.
- Valide Negationskorrekturen mit `nicht ..., sondern ...` bleiben unverändert.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, vier Separator-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `7535f23b fix: reject unresolved sondern residence clauses`.

## Aktueller Ledger 2026-07-19-Post-Restart

- `teebotus.service` aktiv/running, `MainPID 2292239`, Start `2026-07-19 01:09:27 CEST`.
- Seit diesem Restart: `12/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Unaufgelöste Kontrast-Orte

- `aber/doch/jedoch in <Stadt>` ohne Zeit-/Verbkontext wird nicht als Umzug fehlinterpretiert.
- Verkürzte Kontrastlabels wie `aber Hamburg mein Wohnort` werden bei mehreren Wohnzielen als Konflikt erkannt.
- Valide `aber jetzt in ...`-Umzüge und Arbeitsort-Kontraste bleiben erhalten.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, acht Contrast-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `2b2f7173 fix: guard unresolved residence contrasts`.

## Aktueller Ledger 2026-07-19-Post-Restart

- `teebotus.service` aktiv/running, `MainPID 2292239`, Start `2026-07-19 01:09:27 CEST`.
- Seit diesem Restart: `13/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Klauselgrenzen bei Arbeits-/Wohnorten

- `Berlin ist mein Arbeitsort, Hamburg mein Wohnort` liefert Hamburg statt leer.
- Nicht-residenter Präfix aus vorheriger Kommaklausel vergiftet Folge-Match nicht mehr.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, vier Work/Residence-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c29b7253 fix: isolate residence clause prefixes`.

## Aktueller Ledger 2026-07-19-Post-Restart

- `teebotus.service` aktiv/running, `MainPID 2292239`, Start `2026-07-19 01:09:27 CEST`.
- Seit diesem Restart: `14/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: PLZ in Meldeadressen

- `10115 Berlin` wird aus Meldeadresse und `in ... gemeldet/registriert` als Berlin extrahiert.
- PLZ landet nicht im gespeicherten Stadtwert.
- Arbeits-/Geschäftsadressen mit PLZ bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, sieben Postcode-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `4962d078 fix: parse postal registered addresses`.

## Aktueller Ledger 2026-07-19-Post-Restart

- `teebotus.service` aktiv/running, `MainPID 2292239`, Start `2026-07-19 01:09:27 CEST`.
- Seit diesem Restart: `15/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Zeitlicher Einschub vor Wohnsitz

- `Ich habe derzeit/aktuell meinen Wohnsitz in ...` wird erkannt.
- Gleichlautende Arbeitsort-Angaben bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, drei Time-Insertion-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `fa2c7d37 fix: parse timed residence declarations`.

## Aktueller Ledger 2026-07-19-Post-Restart

- `teebotus.service` aktiv/running, `MainPID 2292239`, Start `2026-07-19 01:09:27 CEST`.
- Seit diesem Restart: `16/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Zeitstellung bei Wohnsitz und Wohnung

- `Ich habe meinen Wohnsitz derzeit/seit 2020 in ...` wird erkannt.
- Aktuelle/neue `Wohnung` und `Unterkunft` mit Ortsangabe werden erkannt.
- Unklare Zweitwohnungsform `Ich habe derzeit eine Wohnung in ...` bleibt leer; historische und Arbeitsorte bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, acht Housing/Time-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `bae5820b fix: parse timed housing residence forms`.

## Aktueller Ledger 2026-07-19-Post-Restart

- `teebotus.service` aktiv/running, `MainPID 2292239`, Start `2026-07-19 01:09:27 CEST`.
- Seit diesem Restart: `17/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Nicht-residente Begleitkontexte

- `mit meiner Ausbildung` und `bei meiner Firma` werden nicht mehr als Wohnortkontext gespeichert.
- Familie, Eltern und Partner bleiben als Wohnkontext gültig.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, fünf Companion-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `1b4dbaf7 fix: reject nonresidential companion contexts`.

## Aktueller Ledger 2026-07-19-Post-Restart

- `teebotus.service` aktiv/running, `MainPID 2292239`, Start `2026-07-19 01:09:27 CEST`.
- Seit diesem Restart: `18/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Arbeitgeber als Begleitperson

- `bei meinem Chef/Arbeitgeber` wird nicht mehr als Wohnkontext missinterpretiert.
- Familiäre Begleiter und Gastfamilie bleiben gültige Wohnkontexte.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, vier Work-Companion-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `8b8e6d75 fix: reject employer companion contexts`.

## Aktueller Ledger 2026-07-19-Post-Restart

- `teebotus.service` aktiv/running, `MainPID 2292239`, Start `2026-07-19 01:09:27 CEST`.
- Seit diesem Restart: `19/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Qualifier im Possessiv-Wohnsitz

- `meinen aktuellen/gemeldeten Wohnsitz` und `meinen jetzigen Wohnort` werden erkannt.
- Historische Wohnsitze und Arbeitsorte bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, fünf Possessive-Qualifier-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `d8aa60f7 fix: parse qualified possessive residences`.
- Restart danach: `teebotus.service` `active/running`, `MainPID 3403613`, Start `2026-07-19 02:19:35 CEST`.

## Aktueller Ledger 2026-07-19-Post-Restart

- `teebotus.service` aktiv/running, `MainPID 3403613`, Start `2026-07-19 02:19:35 CEST`.
- Neuer Zyklus seit diesem Restart: `7/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Weitere Straßenarten

- `Damm`, `Kai`, `Deich`, `Höhe`, `Park` und `Gürtel` werden als Straßenarten erkannt.
- Straßenparser, Fallbacks, `_clean_city` und Ambiguitätsguard verwenden gemeinsamen `_STREET_TYPE`.
- Verifikation: `tests/test_weather_context.py` -> `175 passed`, sechs Additional-Street-Type-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c14d6455 fix: parse additional street types`.

### Folgefix 2026-07-19: Internationale PLZ-Präfixe

- `D-10115`, `DE-10115` und `D 10115` werden in Straßen- und Labeladressen erkannt.
- Direkte Wohnadresse mit abweichender Meldeadresse bleibt durch Konfliktguard leer.
- Verifikation: `tests/test_weather_context.py` -> `176 passed`, vier International-Postal-Prefix-Smokes plus Konflikt-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `ac20b363 fix: parse international postal prefixes`.

### Folgefix 2026-07-19: Zuhause-Satz ohne falschen Subjekt-Stadtwert

- `Ich wohne/lebe in Berlin zuhause/zu Hause/daheim` liefert Berlin statt fälschlich `Ich wohne`.
- Breites Daheim-Fallback wird für Subjekt+Wohnverb blockiert; direkter Wohnpfad bleibt zuständig.
- Verifikation: `tests/test_weather_context.py` -> `178 passed`, drei Home-Adverb-Smokes plus Subjekt-Negativsmoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `d84b1fc6 fix: reject residence subject as home city`.

### Folgefix 2026-07-19: Pluraler Zuhause-Status

- `Wir sind in Hamburg daheim/zuhause/zu Hause` liefert Hamburg statt `Wir sind`.
- Breites Daheim-Fallback blockiert jetzt auch `Ich/Wir bin/sind`; historische Negation bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `178 passed`, bestehende Home-Smokes plus Plural-Status-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `65472c67 fix: parse plural home status`.

### Folgefix 2026-07-19: Statussuffix nach Wohnverb

- `Ich wohne/lebe in Berlin wohnhaft/ansässig/gemeldet/registriert` liefert Berlin statt Statussuffix im Stadtwert.
- Historische Statussätze bleiben ausgeschlossen; Arbeitskontext bleibt zulässig.
- Verifikation: `tests/test_weather_context.py` -> `179 passed`, vier Residence-Verb-Status-Smokes plus Negativ-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `27bf9812 fix: stop residence city before status suffix`.

### Folgefix 2026-07-19: Komma vor Zuhause-Adverb

- `Ich wohne/bin in Berlin, zuhause/zu Hause/daheim` und Pluralvarianten liefern Berlin.
- Generisches Daheim-Fallback wird für direkte Wohnsätze und den eindeutigen Kommaabschluss nicht als falsche Subjekt-Stadt verwendet; Mehrfachorte bleiben leer.
- Verifikation: `tests/test_weather_context.py` -> `180 passed`, vier Comma-Home-Smokes plus zwei Ambiguitäts-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `3e29ca30 fix: parse comma home adverb sentences`.

### Folgefix 2026-07-19: Ortspräzisierung vor Straßenadresse

- `im nördlichen Berlin`, `im Norden Berlins` und `im Bezirk Kreuzberg in Berlin` mit Straßenadresse liefern übergeordneten Ort.
- Unbekannter Stadtteil ohne übergeordnete Stadt bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `181 passed`, vier Area-Qualifier-Before-Street-Smokes plus Negativ-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e7896830 fix: parse area qualifiers before streets`.

### Folgefix 2026-07-19: Verbfreie Wohnadress-Labels

- `Wohnadresse Berlin` wird erkannt; `Geburtsort` wird nicht als Wohnziel gewertet.
- Wohnadresse/Meldeadresse-Konflikte werden auch ohne Verb erkannt.
- Arbeitsadresse bleibt als nicht-residenter Kontext zulässig.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, fünf Address/Origin-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a6010b83 fix: track verbless residence address labels`.

### Folgefix 2026-07-19: Qualifizierte verbfreie Wohnlabels

- `aktuelle/offizielle/gemeldete Wohnadresse` und `offizieller/gemeldeter Wohnsitz` werden erkannt.
- Verb-Füller `war/liegt` werden nicht als Stadt übernommen.
- Wohnadresse/Meldeadresse-Konflikt bleibt leer.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, neun Qualified-Label-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `797aec0b fix: parse qualified verbless residence labels`.

### Folgefix 2026-07-19: Artikel bei verbfreien Wohnlabels

- `der/die/das/ein/eine` werden bei verbfreien Wohn-, Wohnadress- und Meldeadress-Labels erkannt.
- Widerspruechliche Artikel-Labels mit separater Meldeadresse liefern weiterhin keinen Wohnort.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, Artikel-/Konflikt-Smoke gruen, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `b857f7fa fix: handle article residence labels`.

### Folgefix 2026-07-19: Mehrfachziele bei verbfreien Labels

- `Wohnadresse Berlin und Hamburg` sowie Komma-Varianten liefern keinen erfundenen Einzelort.
- `Umgebung`, Arbeitsadresse und Geburtsstadt bleiben als nicht-residente Zusätze zulässig.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, sechs Multiplikitäts-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `ee52ad80 fix: reject multiple verbless residence targets`.

### Folgefix 2026-07-19: Präzisierung verbfreier Adresslabels

- `Wohnadresse/Meldeadresse Berlin, genauer gesagt Hamburg` liefert den präzisierten aktuellen Ort.
- Arbeitsadresse und Geburtsstadt nach Komma bleiben nicht-residente Zusätze.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, drei Adresspräzisierungs-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `9518c7eb fix: parse residence address clarifications`.

### Folgefix 2026-07-19: Separatorvarianten bei Adresspräzisierungen

- Präzisierungen nach `:`, `=` oder Komma werden auch bei Leerzeichen vor dem Separator erkannt.
- Bestehende Leerzeichen- und Konfliktformen bleiben unverändert.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, zwei Separator-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `7e2ff63e fix: accept separator variants in address changes`.

### Folgefix 2026-07-19: Klammerzusätze bei verbfreien Wohnlabels

- `Halle (Saale)` bleibt als bekannte zusammengesetzte Stadt erhalten.
- Länderzusätze wie `Berlin (Deutschland)` werden zu `Berlin` normalisiert.
- Konflikt- und Präzisierungslogik berücksichtigt Klammerzusätze ebenfalls.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, vier Parenthesized-Label-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `2cb779b0 fix: preserve parenthesized residence cities`.

### Folgefix 2026-07-19: Registrierte Adress-Aliase im Konfliktguard

- `Meldeanschrift` und `Meldesitz` werden bei widersprüchlichen Wohnzielen wie `Meldeadresse` behandelt.
- Arbeitsadressen lösen weiterhin keinen Wohnortkonflikt aus.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, drei Registered-Label-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a8b6348a fix: detect registered address aliases`.

### Folgefix 2026-07-19: Artikel und Qualifier bei Verb-Adresskonflikten

- `Die Wohnadresse ist ...` und `Die aktuelle Wohnadresse ist ...` werden im Konfliktguard erfasst.
- Widersprüche zu `Meldeadresse`, `Meldeanschrift`, `Meldesitz` und Arbeitsadresse werden nicht als aktueller Wohnort ausgegeben.
- Gleiche Wohn-/Melde-Stadt bleibt gültig.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, sechs Verb-Adress-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c9fe1e75 fix: detect article address conflicts`.

### Folgefix 2026-07-19: First-Person-Adressartikel

- `Ich habe eine Wohnadresse/einen Wohnsitz in Berlin` sowie aktuelle/offizielle Varianten werden erkannt.
- Arbeitsadresse, historische Adresse und mehrere Wohnziele bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, acht First-Person-Address-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a5e8400a fix: parse first-person residence addresses`.

### Folgefix 2026-07-19: First-Person-Adresskonflikte

- First-Person-Wohnadresse/Wohnsitz wird gegen persönliche Meldeadresse, Meldeanschrift, Meldesitz und Arbeitsadresse geprüft.
- Unterschiedliche Städte liefern leer; gleiche Stadt und Geburtsstadt bleiben zulässig.
- Generische Arbeitsadresslabels außerhalb dieses First-Person-Kontexts bleiben unverändert.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, vier First-Person-Conflict-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a37a0952 fix: guard first-person address conflicts`.

### Folgefix 2026-07-19: Postleitzahlen vor Wohnorten

- `10115 Berlin` wird in First-Person-, verbfreien und `wohnhaft`-Formen erkannt.
- Gespeicherter Stadtwert bleibt `Berlin`, nicht die Postleitzahl.
- Konflikte und Mehrfachziele mit PLZ bleiben geschützt.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, sechs Postal-Residence-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c0f3c357 fix: parse postal residence locations`.

### Folgefix 2026-07-19: PLZ bei Wohnort-Präzisierungen

- `10115 Berlin, genauer gesagt 20095 Hamburg` wird auch in First-Person-Adresssätzen als Wechsel nach Hamburg erkannt.
- Klammerzusätze und `in/bei` bleiben kompatibel.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, zwei Postal-Change-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `67433899 fix: parse postal residence changes`.

### Folgefix 2026-07-19: PLZ-Mehrfachziele

- `10115 Berlin und 20095 Hamburg` wird bei verbfreien und First-Person-Labels als mehrdeutig verworfen.
- `Umgebung`, Region/Nähe sowie Arbeits- und Geburtsortzusätze bleiben zulässig.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, drei Postal-Multiplicity-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `3b7dbce0 fix: reject postal residence multiplicity`.

### Folgefix 2026-07-19: Aktuelle Qualifier bei Possessivlabels

- `tatsächlicher`, `dauerhafter`, `vorübergehender`, `momentaner` und weitere aktuelle Qualifier werden vor Wohnort/Wohnsitz/Wohnadresse erkannt.
- Historische und künftige Qualifier bleiben ausgeschlossen.
- Konfliktcollector verwendet dieselbe Qualifiergruppe.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, acht Current-Qualifier-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `79a0140d fix: parse current residence qualifiers`.

## Aktueller Ledger 2026-07-19-Post-Restart

- `teebotus.service` aktiv/running, `MainPID 3403613`, Start `2026-07-19 02:19:35 CEST`.
- Seit diesem Restart: `16/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Straßenadress-Labels

- `Die Wohnadresse: Musterstraße 5, Berlin` und `Meldeadresse: Hauptweg 7, 10115 Berlin` werden erkannt.
- Optionaler Straßen-/PLZ-Teil wird nicht als Stadt gespeichert.
- Konfliktverknüpfung bleibt als Folgefix separat.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, drei Street-Address-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `efd23d0a fix: parse labeled street residence addresses`.

### Folgefix 2026-07-19: Straßenadress-Konflikte

- `Wohnadresse: Musterstraße 5, Berlin; Meldeadresse Hamburg` wird als widersprüchlich verworfen.
- `Meldeanschrift` und PLZ bei Straßenadressen werden im Konfliktguard berücksichtigt.
- Gleiche Wohn-/Melde-Stadt bleibt gültig; Arbeitsadresse bleibt davon getrennt.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, vier Street-Address-Conflict-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `4f139661 fix: guard street residence address conflicts`.

### Folgefix 2026-07-19: Separatoren bei Straßenadress-Labels

- Straßenadress-Labels akzeptieren `:`, `=` und Komma als Separator.
- PLZ, Hausnummer und Stadt werden weiterhin getrennt verarbeitet.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, zwei Separator-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `cea41f95 fix: accept street address label separators`.

### Folgefix 2026-07-19: Zusammengesetzte Hausnummern

- Hausnummern mit Bereich, Schrägstrich oder Buchstabenabstand (`5-7`, `5/7`, `5 b`) werden erkannt.
- Direkte Erkennung und Straßenadress-Konfliktguard verwenden dieselbe Variantenlogik.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, vier Compound-House-Number-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `fd28e27c fix: parse compound street house numbers`.

### Folgefix 2026-07-19: Abgekürzte Straßennamen

- `Musterstr. 5, Berlin` und `Hauptstr. 7, Berlin` werden erkannt.
- `_clean_city` verwirft Straßenfragmente wie `Musterstr. 5` nicht mehr als scheinbare Stadt.
- Konflikte mit abweichender Meldeadresse bleiben geschützt.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, vier Street-Abbreviation-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `b9ee8504 fix: support abbreviated street names`.

## Aktueller Ledger 2026-07-19-Post-Restart-2

- `teebotus.service` aktiv/running, `MainPID 434057`, Start `2026-07-19 03:36:33 CEST`.
- Neuer Zyklus seit diesem Restart: `20/20` Code-Fixes. Restart jetzt fällig; kein Push.

### Folgefix 2026-07-19: Präpositionale Straßennamen

- `Unter den Linden 5`, `Am Markt 5` und `Zur Alten Post 5` werden im Adresslabel erkannt.
- Gemeinsame Straßenadress-Regex wird für direkte Erkennung und Konfliktguard verwendet.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, vier Prepositional-Street-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `86842852 fix: parse prepositional street addresses`.

### Folgefix 2026-07-19: Whitespace-getrennte Straßenadressen

- `Musterstraße 5 10115 Berlin` und `Am Markt 5 Berlin` werden ohne Komma erkannt.
- PLZ bleibt von Stadtwert getrennt; abweichende Meldeadresse löst weiterhin Konflikt aus.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, drei Whitespace-Address-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `4d920905 fix: parse whitespace separated street addresses`.

### Folgefix 2026-07-19: Gebäudedetails in Straßenadressen

- `Hinterhaus`, Etagen (`2. OG`) und Wohnungsangaben werden zwischen Hausnummer und Stadt übersprungen.
- Direkte Erkennung und Konfliktguard verwenden dieselbe Detailliste.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, vier Building-Detail-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a8e492ab fix: skip street address building details`.

### Folgefix 2026-07-19: Zusammengesetzte Gebäudedetails

- `2. OG links`, `Wohnung 3 links` und `Hinterhaus rechts` werden vollständig übersprungen.
- Stadtwert bleibt stabil; keine Adressfragmente als Wohnort.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, drei Compound-Building-Detail-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `3ce4c531 fix: parse compound building address details`.

### Folgefix 2026-07-19: Weitere Gebäudedetails

- `1. Etage`, `Souterrain`, `Aufgang A` und `Haus A` werden als Adressdetails übersprungen.
- Gemeinsame Regex schützt direkte Stadt-Erkennung und Konfliktguard.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, vier Additional-Building-Detail-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `fcc4f05d fix: parse additional building address details`.

### Folgefix 2026-07-19: Ketten von Gebäudedetails

- Mehrere Details wie `Hinterhaus, 2. OG` oder `Aufgang A, Wohnung 3` werden vor Stadt/PLZ übersprungen.
- Unterschiedliche Meldeadresse bleibt trotz Detailkette Konflikt.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, vier Chained-Building-Detail-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `2128cbf2 fix: parse chained building address details`.

### Folgefix 2026-07-19: Hausnummern mit Buchstabenbereichen

- `5a-5b` und `5a/5b` werden als Hausnummern erkannt.
- `_clean_city` verwirft solche Straßenfragmente weiterhin als keine Stadt.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, drei Lettered-House-Range-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `2dcc52cf fix: parse lettered house number ranges`.

### Folgefix 2026-07-19: Verbale Straßenadress-Labels

- `Wohnadresse ist ...`, `Wohnadresse lautet ...`, `Meldeadresse befindet sich in ...` und `Wohnsitz liegt in ...` werden erkannt.
- Präpositionale Straßenadressen werden im Ambiguitätsguard nicht mehr als zwei Wohnziele gewertet.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, sechs Verbal-Street-Label-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `71285c5d fix: parse verbal street residence labels`.

### Folgefix 2026-07-19: Wohnortwechsel mit Straßenadressen

- `nicht mehr in Musterstraße 5, Berlin, sondern in Hauptweg 7, Hamburg` liefert Hamburg.
- Altadresse bleibt historisch; nur neue Stadt wird als aktueller Wohnort verwendet.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, ein Street-Address-Change-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `26dbd66c fix: parse street address residence changes`.

### Folgefix 2026-07-19: Straßenadresswechsel mit `auf`

- `Wohnadresse wechselte von Musterstraße 5, Berlin auf Hauptweg 7, Hamburg` liefert Hamburg.
- Alte Adresse bleibt als Wechselquelle; neuer Ort gewinnt.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, ein Switched-Street-Address-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `8247b5f3 fix: parse switched street residence addresses`.

### Folgefix 2026-07-19: Umzug mit Straßenadressen

- `Ich bin von Musterstraße 5, Berlin nach Hauptweg 7, Hamburg gezogen` liefert Hamburg.
- Verb `gezogen` bleibt außerhalb des Stadtwerts.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, ein Moved-Street-Address-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `085bb7ff fix: parse moved street residence addresses`.

### Folgefix 2026-07-19: Vorher-/Nachher-Straßenadresslabel

- `Wohnadresse: vorher Musterstraße 5, Berlin, jetzt Hauptweg 7, Hamburg` liefert Hamburg.
- Historischer Altort wird nicht als aktueller Wohnort gespeichert.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, ein Before-After-Street-Label-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `1ec33109 fix: parse before after street residence labels`.

### Folgefix 2026-07-19: Alte/neue Wohnadresse

- `Meine alte Wohnadresse war ..., meine neue ist ...` liefert neue Stadt.
- Historische Adresse bleibt ausgeschlossen; neue Straßenadresse gewinnt.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, ein Old-New-Street-Label-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c5a543cd fix: parse old new street residence labels`.

### Folgefix 2026-07-19: Verlagerte Straßenadressen

- `Wohnadresse/Wohnort hat sich von ... nach ... geändert/verlagert` liefert neue Stadt.
- Altadresse bleibt Quelle des Wechsels und wird nicht als aktuell gewertet.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, zwei Relocated-Street-Residence-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `f065001d fix: parse relocated street residences`.

### Folgefix 2026-07-19: Passive Straßenadressänderung

- `Adresse wurde von ... auf ... geändert` liefert neue Stadt.
- Hausnummern, PLZ und Altadresse werden korrekt aus Wechselquelle getrennt.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, ein Passive-Street-Address-Change-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `3ddfee20 fix: parse passive street address changes`.

### Folgefix 2026-07-19: Aktuelle Adresse vor `statt`

- `Wohnadresse ist jetzt Hauptweg 7, Hamburg statt Musterstraße 5, Berlin` liefert Hamburg.
- Aktueller Ort wird vor historischem Vergleichswert priorisiert.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, ein Current-First-Street-Change-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `7845e28d fix: parse current first street address changes`.

### Folgefix 2026-07-19: First-Person-Straßenadresswechsel

- `Ich habe meine Wohnadresse von ... auf ... geändert` liefert neue Stadt.
- Wechselwort und Altadresse werden nicht in den aktuellen Stadtwert gezogen.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, ein First-Person-Street-Change-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `77cf4061 fix: parse first person street address changes`.

### Folgefix 2026-07-19: Künftige Straßenadressen

- `künftige`/`zukünftige Wohnadresse` wird trotz Straßen-/PLZ-Komma nicht als aktueller Wohnort gespeichert.
- Ein späterer aktueller Wohnort im selben Satz bleibt erkennbar.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, vier Future-Street-Context-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `55e8b3fa fix: reject future street residence labels`.

### Folgefix 2026-07-19: Unsichere Straßenadressen

- `mögliche` und `wahrscheinliche Wohnadresse` werden nicht als Fakt gespeichert.
- Sichere Straßenadresse bleibt gültig.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, drei Uncertain-Street-Label-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `3ac3ddaa fix: reject uncertain street residence labels`.

### Folgefix 2026-07-19: Punktlose Straßenabkürzungen

- `Musterstr 5` und `Hauptstr 7` werden wie `Musterstr. 5` erkannt.
- Konfliktguard und `_clean_city` behandeln beide Schreibweisen konsistent.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, drei Unpunctuated-Street-Abbreviation-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `47051e03 fix: accept unpunctuated street abbreviations`.

## Aktueller Ledger 2026-07-19-Post-Restart-3

- `teebotus.service` aktiv/running, `MainPID 3691691`, Start `2026-07-19 16:41:08 CEST`.
- Neuer Zyklus seit diesem Restart: `20/20` Code-Fixes. Restart jetzt fällig; kein Push.

### Folgefix 2026-07-19: Freie Straßenadress-Sätze

- `Wir wohnen in Unter den Linden 5, Berlin`, `Ich wohne in Am Markt 5, Berlin` und `in ... wohnhaft` werden erkannt.
- Stadtwert bleibt Berlin; Straßenfragmente wie `in` werden nicht gespeichert.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, drei Freeform-Street-Sentence-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `b2862bfe fix: parse freeform street residence sentences`.

### Folgefix 2026-07-19: Qualifizierte freie Straßenadress-Sätze

- `Ich lebe momentan in ...` und `Ich wohne aktuell bei ...` werden erkannt.
- Aktuelle Zeitqualifier werden unterstützt, Zukunftsqualifier bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, zwei Qualified-Freeform-Street-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `11885dba fix: parse qualified freeform street residences`.

### Folgefix 2026-07-19: Besitz- und Statusformulierungen

- `Ich habe meinen Wohnsitz/meine Bleibe in ...` und `Ich bin wohnhaft/ansässig in ...` werden erkannt.
- Straßen-, PLZ- und Präpositionsvarianten bleiben gemeinsam nutzbar.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, vier Possession-Status-Street-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `91887ad3 fix: parse possession and residence status sentences`.

### Folgefix 2026-07-19: Qualifier bei Besitz-/Statusformulierungen

- `fester/offizieller/aktueller/dauerhafter Wohnsitz` und `offiziell/dauerhaft wohnhaft/ansässig` mit Straßenadresse werden erkannt.
- Vorhandene Current-Qualifier-Gruppe wird wiederverwendet; generische Wohnort-Labels bleiben geschützt.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, sechs Qualified-Possession-Status-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `3a698f04 fix: parse qualified residence status sentences`.

### Folgefix 2026-07-19: Hauptwohnsitz und Lebensmittelpunkt mit Straßenadresse

- Besitzsätze mit `Hauptwohnsitz` oder `Lebensmittelpunkt` plus Straßenadresse liefern die Stadt.
- Vorhandene Qualifier und bestehende generische Wohnort-Guards bleiben unverändert.
- Verifikation: `tests/test_weather_context.py` -> `159 passed`, drei Primary-Residence-Street-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `21346a8d fix: parse primary residence street labels`.

### Folgefix 2026-07-19: `Nr.`-Hausnummern

- `Musterstraße Nr. 5`, `Musterstraße Nr 5` und alphanumerische `Nr. 7a` werden als Straßenadresse erkannt.
- `_clean_city` und Ambiguitätsguard behandeln `Nr`-Adressen konsistent; Straßenfragmente werden nicht als Stadt gespeichert.
- Verifikation: `tests/test_weather_context.py` -> `160 passed`, drei Numbered-Street-Address-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `5b5e888c fix: parse numbered street addresses`.

### Folgefix 2026-07-19: Ausgeschriebene Hausnummernmarker

- `Nummer`, `Hausnummer`, `Hausnr.`, `Haus-Nr.` und `Hs.-Nr.` vor Hausnummer werden erkannt.
- Gemeinsamer Marker-Baustein hält Straßenparser, Fallbacks, `_clean_city` und Ambiguitätsguard synchron.
- Verifikation: `tests/test_weather_context.py` -> `161 passed`, fünf Written-House-Number-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a0760401 fix: parse written street number labels`.

### Folgefix 2026-07-19: Stadt vor Straßenadresse ohne Komma

- `Ich wohne in Berlin in der Musterstraße 5` und `an der ...` werden erkannt.
- Straßenadress-Kern ist vom nachfolgenden Trenner getrennt; mehrteilige Städte wie Frankfurt am Main bleiben korrekt.
- Verifikation: `tests/test_weather_context.py` -> `162 passed`, drei City-Before-Street-Smokes, Compound-City-Smokes und `py_compile`/`git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `f2ff3d79 fix: parse city before street addresses`.

### Folgefix 2026-07-19: Beschriftete Stadt-vor-Straße-Sätze

- `Wohnadresse/Wohnsitz/Wohnung liegt in Stadt in/an der Straße` und `ich bin wohnhaft in Stadt in/an der Straße` werden erkannt.
- Arbeits- und Geburtsadressen bleiben ausgeschlossen; mehrteilige Städte bleiben korrekt.
- Verifikation: `tests/test_weather_context.py` -> `163 passed`, vier Labeled-City-Before-Street-Smokes plus Negativ-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `8fc5d4c1 fix: parse labeled city before street`.

### Folgefix 2026-07-19: Nachgestellte Wohnstatusform

- `Ich bin in Stadt in/an der Straße wohnhaft/ansässig/gemeldet/registriert` wird erkannt.
- Komma- und Präpositionsvarianten funktionieren; `geschäftlich` und historische Statuszusätze bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `164 passed`, vier Postposed-Residence-Status-Smokes plus Negativ-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `6f121412 fix: parse postposed residence status`.

### Folgefix 2026-07-19: Beschriftete Statusadresse

- `Wohnhaft:`, `ansässig in`, `gemeldet in`, `registriert:` und `Ich bin aktuell wohnhaft:` mit Straßenadresse werden erkannt.
- Geschäftliche, historische und künftige Statusangaben bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `165 passed`, sechs Labeled-Residence-Status-Smokes plus Negativ-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `da55d3d6 fix: parse labeled residence status`.

### Folgefix 2026-07-19: Status vor Stadt-vor-Straße

- `offiziell/aktuell wohnhaft in Stadt in/an der Straße` wird erkannt.
- Geschäftliche, historische und künftige Statuszusätze bleiben ausgeschlossen; mehrteilige Städte bleiben korrekt.
- Verifikation: `tests/test_weather_context.py` -> `166 passed`, vier Status-City-Before-Street-Smokes plus Negativ-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `43d0fe3a fix: parse status city before street`.

### Folgefix 2026-07-19: Konfliktguard für registrierte Stadt-vor-Straße

- `Meldeadresse/Meldeanschrift/Privatadresse ist in Stadt in/an der Straße` wird erkannt.
- Unterschiedliche Wohn- und Meldeadressen mit Straßenangaben bleiben mehrdeutig und liefern leer; Arbeitsadressen bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `167 passed`, drei Registered-City-Before-Street-Smokes plus drei Konflikt-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `07cc0b18 fix: guard registered city street conflicts`.

### Folgefix 2026-07-19: Ortsart vor Straßenadresse

- `in der Stadt/Gemeinde/Landeshauptstadt Stadt in/an der Straße` und `im Stadtgebiet von Stadt ...` werden erkannt.
- Arbeitskontexte bleiben ausgeschlossen; bestehende Stadt- und Straßenparser bleiben unverändert.
- Verifikation: `tests/test_weather_context.py` -> `168 passed`, vier Locality-Type-Before-Street-Smokes plus Negativ-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `45828e45 fix: parse locality type before street`.

### Folgefix 2026-07-19: Konfliktguard für Ortsart-Adressen

- Beschriftete `Wohn-/Meldeadresse` mit `in der Stadt/im Stadtgebiet` werden erkannt.
- Unterschiedliche Wohn- und Meldeadressen bleiben auch bei Ortsart und Straßenangabe mehrdeutig und liefern leer.
- Verifikation: `tests/test_weather_context.py` -> `169 passed`, Ortsart-Positivsmokes und getrennte Konflikt-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `8048f91b fix: guard locality residence conflicts`.

### Folgefix 2026-07-19: Bare Stadt-vor-Straße-Labels

- `Meldeadresse: in Berlin in der Straße`, `Wohnadresse: Hamburg an der Straße` und `Privatadresse = in Köln ...` werden erkannt.
- Unterschiedliche Wohn-/Meldeadressen bleiben leer; gleiche Stadt und Arbeitsadresse bleiben zulässig.
- Verifikation: `tests/test_weather_context.py` -> `170 passed`, drei Bare-City-Before-Street-Smokes plus drei Konflikt-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `51e582b1 fix: parse bare city street labels`.

### Folgefix 2026-07-19: Bare Ortsart-Labels

- `Meldeadresse: in der Stadt Berlin`, `Wohnadresse: im Stadtgebiet von Hamburg ...` und `Privatadresse = in der Gemeinde Köln` werden erkannt.
- Unterschiedliche Wohn-/Meldeadressen bleiben auch in Ortsartform leer; Arbeitsadressen bleiben zulässig.
- Verifikation: `tests/test_weather_context.py` -> `171 passed`, drei Bare-Locality-Type-Smokes plus Konflikt-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `8747060d fix: parse bare locality street labels`.

### Folgefix 2026-07-19: Status-Ortsart

- `Wohnhaft/ansässig in der Stadt`, `im Stadtgebiet von` und `in der Gemeinde` werden erkannt, auch mit Straßenadresse.
- Geschäftliche, historische und künftige Statuszusätze bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `172 passed`, vier Status-Locality-Type-Smokes plus Negativ-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `ac0de80b fix: parse status locality labels`.

### Folgefix 2026-07-19: Zusammengesetzte Städte vor Straßenadresse

- `Brandenburg an der Havel`, `Frankfurt an der Oder`, `Mülheim an der Ruhr` und `Neustadt an der Weinstraße` bleiben vollständig erhalten.
- Bekannte Compound-City-Namen werden vor generischer `an der`-Straßeninterpretation priorisiert.
- Verifikation: `tests/test_weather_context.py` -> `173 passed`, vier Compound-City-Before-Street-Smokes plus kompletter Compound-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `d6eb0f87 fix: preserve compound cities before streets`.

### Folgefix 2026-07-19: Compound-City in Labels und Status

- Compound-City-Priorität gilt jetzt auch für Wohn-/Meldeadressen und Statussätze vor Straßenadresse.
- Konfliktprüfung bleibt aktiv; unterschiedliche Wohn-/Meldeadressen liefern leer.
- Verifikation: `tests/test_weather_context.py` -> `174 passed`, vier Compound-Labeled-Status-Smokes plus drei Konflikt-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e0f1fedb fix: preserve compound cities in labels`.

## Aktueller Ledger 2026-07-19-Post-Restart-4

- `teebotus.service` aktiv/running, `MainPID 3949354`, Start `2026-07-19 17:38:55 CEST`.
- Neuer Zyklus seit diesem Restart: `0/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Beschriftete Gebietspräzisierung vor Straßenadresse

- Wohnort-, Wohnadress-, Status- und Meldeadress-Formen mit `im nördlichen Berlin`, `im Norden Berlins` sowie `im Bezirk/Stadtteil ... in Berlin` liefern den übergeordneten Ort.
- Genitiv-`s` wird nicht im Stadtnamen gespeichert; unterschiedliche Gebiet-Wohn- und Meldeadressen bleiben mehrdeutig und liefern leer.
- Verifikation: `tests/test_weather_context.py` -> `182 passed`, sechs Gebiet- und Konflikt-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `21b6447f fix: parse labeled area street residences`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-2

- `teebotus.service` aktiv/running, `MainPID 3949354`, Start `2026-07-19 17:38:55 CEST`.
- Neuer Zyklus seit diesem Restart: `8/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Attributive Gebietspräzisierung vor Straßenadresse

- `Berliner/Hamburger/Münchner` vor `Bezirk`, `Stadtteil`, `Innenstadt`, `Zentrum` und ähnlichen Ortsarten mit Straßenadresse werden erkannt.
- Genitive Formen wie `Innenstadt Berlins` werden normalisiert; Wohn-/Meldeadresskonflikte bleiben mehrdeutig und liefern leer.
- Verifikation: `tests/test_weather_context.py` -> `183 passed`, sieben attributive/genitive Gebiet- und Konflikt-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `3264fa36 fix: parse attributive area street residences`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-3

- `teebotus.service` aktiv/running, `MainPID 3949354`, Start `2026-07-19 17:38:55 CEST`.
- Neuer Zyklus seit diesem Restart: `9/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Straßenadressdetails nicht als Stadt

- `Hinterhaus`, `Vorderhaus`, Etagen-, Wohnungs- und einzelne `links/rechts`-Details werden aus späteren Fallback-Kandidaten ausgeschlossen.
- Stadt-vor-Straßenadresse mit solchen Details behält korrekte Stadt; bestehende Detail- und Konfliktformen bleiben unverändert.
- Verifikation: `tests/test_weather_context.py` -> `184 passed`, drei Street-Detail-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `54447028 fix: reject street details as cities`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-4

- `teebotus.service` aktiv/running, `MainPID 3949354`, Start `2026-07-19 17:38:55 CEST`.
- Neuer Zyklus seit diesem Restart: `10/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: PLZ vor Stadt bei Straßenadressen

- `10115 Berlin`, `20095 Hamburg` usw. funktionieren jetzt vor Straßenadresse in Direkt-, Wohnort-, Status- und Meldeadressformen.
- Unterschiedliche PLZ-Wohn- und Meldeadressen bleiben mehrdeutig und liefern leer.
- Verifikation: `tests/test_weather_context.py` -> `185 passed`, vier PLZ-Positivformen plus Konflikt-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `69e83dc2 fix: parse postal city street residences`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-5

- `teebotus.service` aktiv/running, `MainPID 3949354`, Start `2026-07-19 17:38:55 CEST`.
- Neuer Zyklus seit diesem Restart: `11/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: PLZ-Status mit Straßenadresse

- `Ich bin in 10115 Berlin ... wohnhaft`, `Wohnhaft: 10115 Berlin, ...` und Varianten mit Komma/Leerzeichen werden erkannt.
- PLZ-Status mit abweichender Meldeadresse bleibt mehrdeutig und liefert leer.
- Verifikation: `tests/test_weather_context.py` -> `186 passed`, vier Status-Positivformen plus Konflikt-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c29f1a6f fix: parse postal status street forms`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-6

- `teebotus.service` aktiv/running, `MainPID 3949354`, Start `2026-07-19 17:38:55 CEST`.
- Neuer Zyklus seit diesem Restart: `12/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Straßenart `Markt`

- `am Markt 5` wird wie andere Straßenarten erkannt; Stadt bleibt aus Stadt-vor-Straßen-, Label- und Bare-Adressformen erhalten.
- Gemeinsamer `_STREET_TYPE` hält Parser, `_clean_city` und Guards synchron.
- Verifikation: `tests/test_weather_context.py` -> `187 passed`, drei Marktadress-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e43d1413 fix: parse markt street addresses`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-7

- `teebotus.service` aktiv/running, `MainPID 3949354`, Start `2026-07-19 17:38:55 CEST`.
- Neuer Zyklus seit diesem Restart: `13/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Weitere häufige Straßenarten

- `Wall`, `Tor`, `Brücke/Bruecke`, `Bogen`, `Zeile`, `Stein`, `Winkel`, `Kamp`, `Koppel`, `Dorf`, `Feld` und `Wiesen` werden zentral erkannt.
- Bestehende Street-Type-Tests bleiben aktiv; doppelter Testname wurde bereinigt, damit keine Testgruppe überschrieben wird.
- Verifikation: `tests/test_weather_context.py` -> `188 passed`, dreizehn zusätzliche Street-Type-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `001ed14a fix: parse extended street types`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-8

- `teebotus.service` aktiv/running, `MainPID 3949354`, Start `2026-07-19 17:38:55 CEST`.
- Neuer Zyklus seit diesem Restart: `14/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Kommagetrennte Gebietsadressen

- `im Bezirk Kreuzberg, Berlin, Musterstraße 5` und entsprechende Stadtteil-, Label- und Bare-Formen werden erkannt.
- Ambiguitäts- und Multiplicity-Guards akzeptieren vollständige Einzeladressen, blockieren aber weiterhin getrennte Wohn-/Meldeorte.
- Verifikation: `tests/test_weather_context.py` -> `189 passed`, vier Komma-Area-Smokes plus Konfliktfälle, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `f091ad33 fix: parse comma separated area addresses`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-9

- `teebotus.service` aktiv/running, `MainPID 3949354`, Start `2026-07-19 17:38:55 CEST`.
- Neuer Zyklus seit diesem Restart: `15/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Länderpräfixe vor PLZ und Straßenadresse

- `Deutschland`, `Österreich` und `Schweiz` vor Stadt/Straße werden erkannt; vier- und fünfstellige Länder-PLZ funktionieren.
- Multiplicity-/Ambiguity-Guards behandeln vollständige Länderadressen als ein Ziel; separate Meldeadresse bleibt konfliktbehaftet.
- Verifikation: `tests/test_weather_context.py` -> `190 passed`, sechs DE/AT/CH-Smokes plus Konflikt-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `d09799d5 fix: parse country postal street addresses`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-10

- `teebotus.service` aktiv/running, `MainPID 3949354`, Start `2026-07-19 17:38:55 CEST`.
- Neuer Zyklus seit diesem Restart: `16/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Normalisierung geklammerter Stadtteile

- Bekannte Formen wie `Berlin (Kreuzberg)`, `Berlin (Mitte)`, `Hamburg (Altona)` und `Frankfurt am Main (Sachsenhausen)` liefern die übergeordnete Stadt.
- `Halle (Saale)` bleibt als echter zusammengesetzter Ortsname vollständig erhalten.
- Verifikation: `tests/test_weather_context.py` -> `190 passed`, vier Parenthesized-District-Smokes plus Halle-Regression, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `4e13ad1a fix: normalize parenthesized city districts`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-11

- `teebotus.service` aktiv/running, `MainPID 3949354`, Start `2026-07-19 17:38:55 CEST`.
- Neuer Zyklus seit diesem Restart: `17/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Klammerform bei Gebiets-Straßenadressen

- Formen wie `im Bezirk Kreuzberg (Berlin), Musterstraße 5` werden intern in die bestehende Stadt-vor-Straße-Form normalisiert.
- Wohn-, Label-, Arbeitsadress- und Konfliktprüfungen bleiben auf demselben Parserpfad; historische und konkurrierende Adressen bleiben leer.
- Verifikation: `tests/test_weather_context.py` -> `191 passed`, vier Klammer-Gebiets-Smokes plus Konflikt-/Arbeits-/historischer Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `ec9d97b8 fix: normalize parenthesized area addresses`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-12

- `teebotus.service` aktiv/running, `MainPID 3949354`, Start `2026-07-19 17:38:55 CEST`.
- Neuer Zyklus seit diesem Restart: `18/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Geklammerte Straßenadressdetails

- Zusätze wie `(Hinterhaus)`, `(2. OG links)` und `(Wohnung B)` nach der Hausnummer werden vor der bestehenden Stadt-/Straßenanalyse als bekannte Adressdetails behandelt.
- Ortsklammern wie `Berlin (Kreuzberg)` bleiben davon getrennt; historische Wechsel, Arbeitsadressen und Wohn-/Meldekonflikte bleiben geschützt.
- Verifikation: `tests/test_weather_context.py` -> `192 passed`, vier Detail-Smokes plus Konflikt-, Arbeits- und historischer Wechsel-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `95771d14 fix: ignore parenthesized street details`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-13

- `teebotus.service` aktiv/running, `MainPID 3949354`, Start `2026-07-19 17:38:55 CEST`.
- Neuer Zyklus seit diesem Restart: `19/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Stadt-Kommaform und beschreibende Straßennamen

- `Ich wohne in Berlin, Musterstr. 5` wird als Stadt-vor-Straße-Adresse erkannt; der Ambiguitäts-Guard verwirft vollständige Einzeladressen nicht mehr.
- Straßennamen wie `Straße des 17. Juni` funktionieren direkt und nach Label; der Punkt in Datumsbestandteil wird nicht als Satzende fehlinterpretiert.
- Verifikation: `tests/test_weather_context.py` -> `193 passed`, direkte/Label-/Datumsstraßen-Smokes sowie Konflikt-, Arbeits- und historischer Wechsel-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `6dc25148 fix: parse comma city and descriptive streets`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-14

- `teebotus.service` wird nach diesem 20. Code-Fix neu gestartet; vorheriger Prozess: `MainPID 3949354`, Start `2026-07-19 17:38:55 CEST`.
- Neuer Zyklus seit diesem Restart: `0/20` Code-Fixes nach erfolgreicher Verifikation. Kein Push.

### Folgefix 2026-07-19: Zusammengesetzter Ortsname in Straßenadressen

- `Halle (Saale)` wird vor der Regex-Auswertung intern in eine parsebare Form überführt und durch `_KNOWN_COMPOUND_CITY_NAMES` wieder vollständig hergestellt.
- Straßen-, Label-, Melde-, Arbeits- und historische Wechselpfade behalten dadurch den vollständigen Ortsnamen; getrennte Ziele bleiben geschützt.
- Verifikation: `tests/test_weather_context.py` -> `194 passed`, vier Compound-Adress-Smokes plus Konflikt-/Arbeits-/historischer Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `54e929ee fix: preserve compound city names in addresses`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-15

- `teebotus.service` aktiv/running, `MainPID 113726`, Start `2026-07-19 18:58:24 CEST`.
- Neuer Zyklus seit diesem Restart: `1/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Labeladressen mit Stadt vor abgekürzter Straße

- `Wohnadresse`, `Wohnort` und `Meldeadresse` mit Formen wie `Berlin, Musterstr. 5` werden nicht mehr durch Multiplicity-/Ambiguitäts-Guards blockiert.
- Separate Meldeadressen bleiben Konfliktfälle; Arbeitsadressen und gleiche Wohn-/Melde-Stadt bleiben korrekt differenziert.
- Verifikation: `tests/test_weather_context.py` -> `195 passed`, drei Label-Smokes plus Konflikt-/Arbeits-/Unsicherheits-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `29831899 fix: accept labeled city street addresses`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-16

- `teebotus.service` aktiv/running, `MainPID 113726`, Start `2026-07-19 18:58:24 CEST`.
- Neuer Zyklus seit diesem Restart: `2/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Stadtteilklammern mit Straßenabkürzung

- Bekannte Formen wie `Berlin (Mitte)` und `Frankfurt am Main (Sachsenhausen)` werden vor der Auswertung auf die Oberstadt normalisiert, wenn danach eine Adresse folgt.
- `Halle (Saale)` bleibt als zusammengesetzter Ortsname separat erhalten; Wohn-/Melde- und Arbeitsadressschutz bleibt aktiv.
- Verifikation: `tests/test_weather_context.py` -> `196 passed`, 40 Stadtteil-/Straßenkombinationen plus Konflikt-/Arbeits-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `312dd42a fix: normalize district city address variants`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-17

- `teebotus.service` aktiv/running, `MainPID 113726`, Start `2026-07-19 18:58:24 CEST`.
- Neuer Zyklus seit diesem Restart: `3/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: PLZ- und Statusformen mit Straßenabkürzung

- `10115 Berlin, Musterstr. 5` und `Berlin, Musterstr. 5 wohnhaft` werden als vollständige Adressen akzeptiert.
- Ambiguitäts-Guard kennt direkte PLZ-/Statusadressen; getrennte Meldeadressen und unsichere Sätze bleiben geschützt.
- Verifikation: `tests/test_weather_context.py` -> `197 passed`, drei PLZ-/Status-Smokes plus Konflikt-/Unsicherheits-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `488a4938 fix: accept postal status address variants`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-18

- `teebotus.service` aktiv/running, `MainPID 113726`, Start `2026-07-19 18:58:24 CEST`.
- Neuer Zyklus seit diesem Restart: `4/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Genitiv-Gebietsadressen mit Komma

- Formen wie `im Bezirk Mitte Berlins, Musterstr. 5` werden als Berlin erkannt, statt Gebietsname und Stadt zu verkleben.
- Bekannter Bezirk `Kreuzberg` wird als Berlin normalisiert; nicht eindeutig bekannte Ortsteile bleiben ungeklärt.
- Verifikation: `tests/test_weather_context.py` -> `198 passed`, direkte/Label-/Genitiv-Smokes plus Konflikt- und unbekannter-Ortsteil-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `65c514cb fix: parse genitive area street addresses`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-19

- `teebotus.service` aktiv/running, `MainPID 113726`, Start `2026-07-19 18:58:24 CEST`.
- Neuer Zyklus seit diesem Restart: `5/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Gebiets-Suffix nach Straßenadresse

- `Berlin, Musterstr. 5 und Umgebung/Region/Nähe` bleibt als Berlin erkennbar.
- Der Multiplicity-Guard ignoriert den Punkt in `str.`, sodass `Umgebung von Hamburg` nicht fälschlich als Berlin durchrutscht.
- Verifikation: `tests/test_weather_context.py` -> `199 passed`, positive Suffix-Smokes und Mehrziel-Smokes mit `Musterstr.`/`Musterstraße`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `46bbb02c fix: handle area suffix after street address`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-20

- `teebotus.service` aktiv/running, `MainPID 113726`, Start `2026-07-19 18:58:24 CEST`.
- Neuer Zyklus seit diesem Restart: `6/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Stadtadjektiv plus Gebietsbegriff

- `Berliner/Hamburger Umgebung`, `Münchner Gegend`, `Kölner Nähe` und `Hamburger Region` werden mit anschließender Straße auf die bekannte Stadt normalisiert.
- Unbekannte Adjektive und Wohn-/Meldekonflikte bleiben ungeklärt bzw. leer.
- Verifikation: `tests/test_weather_context.py` -> `200 passed`, fünf positive Area-Smokes plus unbekannte-/Konflikt-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `dc6bf269 fix: normalize adjectival city area addresses`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-21

- `teebotus.service` aktiv/running, `MainPID 113726`, Start `2026-07-19 18:58:24 CEST`.
- Neuer Zyklus seit diesem Restart: `7/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Country-Statuslabels

- `Wohnhaft: Österreich, Wien, Musterstr. 5` und `Gemeldet: Schweiz, Zürich, Bahnhofstr. 3` nutzen jetzt denselben Country-Adresspfad wie Wohnadressen.
- Konflikt- und Arbeitsadressschutz wurde im lokalen Guard synchronisiert.
- Verifikation: `tests/test_weather_context.py` -> `201 passed`, Country-Status-Smokes plus Wohn-/Meldekonflikt und Arbeitsadresse, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `5cdc765d fix: parse country status labels`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-22

- `teebotus.service` aktiv/running, `MainPID 113726`, Start `2026-07-19 18:58:24 CEST`.
- Neuer Zyklus seit diesem Restart: `8/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Aktueller Status und Stadtwechsel mit Straßen

- `Ich bin jetzt in Berlin, Musterstr. 5 wohnhaft` wird erkannt.
- `Ich wohne nicht mehr in Berlin, Musterstr. 5, sondern in Hamburg, Hauptweg 7` liefert das neue Ziel.
- Der Konflikt-Guard übernimmt nur den neuen spezifischen Wechselmatch; historische Standardfälle bleiben unverändert und zusätzliche Meldeadressen blockieren.
- Verifikation: `tests/test_weather_context.py` -> `202 passed`, Current-/Change-Smokes plus Unsicherheit, Meldekonflikt und Regressionen, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `609343df fix: parse current and changed street residences`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-23

- `teebotus.service` aktiv/running, `MainPID 113726`, Start `2026-07-19 18:58:24 CEST`.
- Neuer Zyklus seit diesem Restart: `9/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Formulierte Stadtwechsel mit Stadt vor Straße

- `Wohnadresse wechselte/wurde ... von Berlin, Musterstr. 5 auf Hamburg, Hauptweg 7`, `hat sich ... nach ... verlagert` und `Ich bin ... von/nach ... gezogen` werden erkannt.
- Nur die drei neuen Stadt-vor-Straße-Change-Patterns werden im Konflikt-Guard wiederverwendet; alte/neue Adresse wird nicht fälschlich als parallele Wohnadresse behandelt. Eine zusätzliche `Meldeadresse` blockiert weiterhin.
- Verifikation: `tests/test_weather_context.py` -> `203 passed`, positive Move-Formen sowie Melde-/Arbeits-/Unsicherheits-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `5edf014c fix: parse formulated city street moves`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-24

- `teebotus.service` aktiv/running, `MainPID 113726`, Start `2026-07-19 18:58:24 CEST`.
- Neuer Zyklus seit diesem Restart: `10/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Weitere Stadt-vor-Straße-Wechsel

- `Wohnadresse ist jetzt ... statt ...`, `alte Wohnadresse war ..., neue ist ...`, `Wohnadresse: vorher ..., jetzt ...`, `Wohnadresse geändert: ... nach ...` und `von ... nach ...: neue Wohnadresse` werden erkannt.
- Die Wechselpatterns werden im Konflikt-Guard als ein Wohnadressziel behandelt; separate `Meldeadresse`, `Arbeitsadresse` und unsichere Fragen bleiben leer.
- Verifikation: `tests/test_weather_context.py` -> `204 passed`, acht gezielte Positive-/Negativ-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `9ae160c2 fix: parse additional street address moves`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-25

- `teebotus.service` aktiv/running, `MainPID 113726`, Start `2026-07-19 18:58:24 CEST`.
- Neuer Zyklus seit diesem Restart: `11/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Compound-Label nicht als Stadt lesen

- Das allgemeine Residence-Label-Pattern verlangt jetzt Wortgrenze nach `Wohnort`/`Wohnsitz`/ähnlichen Labels. `Wohnortwechsel` wird nicht mehr als Stadt `wechsel` extrahiert.
- Ein echtes `Wohnort: Hamburg` bleibt unverändert.
- Verifikation: `tests/test_weather_context.py` -> `205 passed`, Regression für `Wohnortwechsel` und `Wohnort: Hamburg`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `b092d613 fix: reject compound residence label matches`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-26

- `teebotus.service` aktiv/running, `MainPID 113726`, Start `2026-07-19 18:58:24 CEST`.
- Neuer Zyklus seit diesem Restart: `12/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Umzugsverben mit Stadt vor Straße

- `Ich bin aus/von ... nach ... umgezogen`, `Ich zog von ... nach ...`, `Von ... bin ich nach ... gezogen` und der abgesicherte `Umzug ...: neue Wohnadresse` werden erkannt.
- Freie Bewegungsformulierungen ohne Umzugsverb bleiben ungeklärt; zusätzliche `Meldeadresse` und Fahrten werden nicht als Wohnort übernommen.
- Verifikation: `tests/test_weather_context.py` -> `206 passed`, vier positive Move-Smokes plus Fahrt-/Melde-Negativfälle, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `1f6173bc fix: parse move verb street addresses`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-27

- `teebotus.service` aktiv/running, `MainPID 113726`, Start `2026-07-19 18:58:24 CEST`.
- Neuer Zyklus seit diesem Restart: `13/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Gegenwartsadresse mit Stadt vor Straße

- `Ich habe jetzt ... als Wohnadresse statt ...`, `Wohnanschrift hat sich geändert: neu, früher alt` und `Wohnadresse ist jetzt ... und nicht mehr ...` werden erkannt; Possessiv vor `Wohnadresse` ist optional, `Arbeitsadresse` bleibt ausgeschlossen.
- Separate `Meldeadresse` bleibt konfliktbehaftet und liefert leer.
- Verifikation: `tests/test_weather_context.py` -> `207 passed`, drei positive Gegenwarts-Smokes plus Arbeits-/Melde-Negativfälle, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `bef9da4f fix: parse current residence address phrasing`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-28

- `teebotus.service` aktiv/running, `MainPID 113726`, Start `2026-07-19 18:58:24 CEST`.
- Neuer Zyklus seit diesem Restart: `14/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Strukturierte Umzugsadressen

- Stadt-vor-Straße-Wechsel mit optionaler Postleitzahl (`10115 Berlin`), Klammerdetails (`Hinterhaus`, `2. OG links`) und bekannten Adressübergängen werden erkannt.
- Postal-City wird weiterhin durch `_clean_city` normalisiert; zusätzliche `Meldeadresse` bleibt konfliktbehaftet.
- Verifikation: `tests/test_weather_context.py` -> `208 passed`, Postleitzahl-/Klammer-/Melde-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `b48e7f75 fix: parse structured move addresses`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-29

- `teebotus.service` aktiv/running, `MainPID 113726`, Start `2026-07-19 18:58:24 CEST`.
- Neuer Zyklus seit diesem Restart: `15/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Gleiche Wohn- und Meldeadresse

- `Meldeadresse ist auch Berlin` wird im Konflikt-Guard als `Berlin`, nicht als `auch Berlin`, erfasst.
- `_clean_city` normalisiert führendes `auch`; zwei Adressen in derselben Stadt erzeugen keinen falschen Konflikt.
- Verifikation: `tests/test_weather_context.py` -> `209 passed`, zwei Same-City-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `32caf811 fix: normalize same-city registration context`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-30

- `teebotus.service` aktiv/running, `MainPID 113726`, Start `2026-07-19 18:58:24 CEST`.
- Neuer Zyklus seit diesem Restart: `16/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Pronomen bei Adresswechsel

- `Wohnadresse war Berlin, ... Jetzt ist sie/diese Hamburg, ...` wird als aktuelles Ziel `Hamburg` erkannt.
- Separate `Meldeadresse` blockiert weiterhin.
- Verifikation: `tests/test_weather_context.py` -> `210 passed`, zwei Pronomen-Smokes plus Melde-Negativfall, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `82bd35ee fix: parse pronoun residence address changes`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-31

- `teebotus.service` aktiv/running, `MainPID 113726`, Start `2026-07-19 18:58:24 CEST`.
- Neuer Zyklus seit diesem Restart: `17/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Erweiterte Pronomen-Übergänge

- Pronomen-Wechsel akzeptieren jetzt `lautet`, `Seitdem`, `bleibt aber`, `die ist jetzt` sowie vorangestelltes `Früher/Zuvor war ...`.
- Zeit-/Pronomenvarianten bleiben auf Wohnadresswechsel mit zwei vollständigen Straßenadressen begrenzt.
- Verifikation: `tests/test_weather_context.py` -> `210 passed`, sieben zusätzliche Pronomen-Smokes plus bestehender Melde-Negativfall, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `9a726bcd fix: expand pronoun residence transitions`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-32

- `teebotus.service` aktiv/running, `MainPID 113726`, Start `2026-07-19 18:58:24 CEST`.
- Neuer Zyklus seit diesem Restart: `18/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Stadt vor Wohnadresslabel

- `Berlin war meine alte Wohnadresse, Hamburg ist jetzt meine neue Wohnadresse` und die entsprechende `Wohnanschrift`-Variante werden erkannt.
- Arbeitsadressen und zusätzliche `Meldeadresse` bleiben ausgeschlossen bzw. konfliktbehaftet.
- Verifikation: `tests/test_weather_context.py` -> `211 passed`, zwei positive Label-Smokes plus Arbeits-/Melde-Negativfälle, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a9e9b2ec fix: parse city before residence label changes`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-33

- `teebotus.service` aktiv/running, `MainPID 113726`, Start `2026-07-19 18:58:24 CEST`.
- Neuer Zyklus seit diesem Restart: `19/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Straße vor Wohnadresslabel

- `Berlin, Musterstr. 5 war meine alte Wohnadresse; Hamburg, Hauptweg 7 ist jetzt meine neue` und `frühere Wohnadresse Berlin, Musterstr. 5 ist vorbei, jetzt Hamburg, Hauptweg 7` werden erkannt.
- Arbeitsadressen und zusätzliche `Meldeadresse` bleiben ausgeschlossen bzw. konfliktbehaftet.
- Verifikation: `tests/test_weather_context.py` -> `212 passed`, zwei positive Street-before-Label-Smokes plus Arbeits-/Melde-Negativfälle, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `4c52ae80 fix: parse street before residence label changes`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-34

- `teebotus.service` aktiv/running, `MainPID 450172`, Start `2026-07-19 20:13:41 CEST`.
- Zyklus abgeschlossen: `20/20` Code-Fixes. Kein Push. Neuer Zyklus startet ab nächstem Code-Fix mit `1/20`.

### Folgefix 2026-07-19: Informelle Straßen-vor-Label-Wechsel

- `Berlin, Musterstr. 5 war meine alte Wohnadresse, jetzt Hamburg, Hauptweg 7` und `ist nicht mehr meine Wohnadresse, sondern ...` werden erkannt.
- Arbeitsadressen sowie zusätzliche `Meldeadresse` bleiben ausgeschlossen bzw. konfliktbehaftet.
- Verifikation: `tests/test_weather_context.py` -> `213 passed`, zwei positive informelle Move-Smokes plus Arbeits-/Melde-Negativfälle, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `9cab7d3a fix: parse informal street first moves`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-35

- `teebotus.service` aktiv/running, `MainPID 450172`, Start `2026-07-19 20:13:41 CEST`.
- Neuer Zyklus seit diesem Restart: `1/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Doppelpunkt-Labels für alte/neue Adresse

- `Alte Wohnadresse: Berlin, ...; Neue Wohnadresse: Hamburg, ...` und `Meine alte Wohnadresse: ...; Meine neue: ...` werden erkannt.
- Der Multiplicity-Guard behandelt das explizite alte/neue Paar als Wechsel; Arbeitsadresse und zusätzliche `Meldeadresse` bleiben leer.
- Verifikation: `tests/test_weather_context.py` -> `214 passed`, zwei positive Colon-Label-Smokes plus Arbeits-/Melde-Negativfälle, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `170aec31 fix: preserve colon labelled address moves`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-36

- `teebotus.service` aktiv/running, `MainPID 450172`, Start `2026-07-19 20:13:41 CEST`.
- Neuer Zyklus seit diesem Restart: `2/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Inline-Zeitlabels bei Wohnadressen

- `Wohnadresse alt: ...; Wohnadresse neu: ...`, `Wohnadresse früher ..., heute ...` und `Wohnadresse ..., jetzt ...` werden erkannt.
- Der Multiplicity-Guard behandelt diese expliziten Zeitpaare als Wechsel; zusätzliche `Meldeadresse` bleibt konfliktbehaftet.
- Verifikation: `tests/test_weather_context.py` -> `215 passed`, drei positive Inline-Label-Smokes plus Melde-Negativfall, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `f815dbcc fix: parse inline labelled residence times`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-37

- `teebotus.service` aktiv/running, `MainPID 450172`, Start `2026-07-19 20:13:41 CEST`.
- Neuer Zyklus seit diesem Restart: `3/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Labelgebundene Von-nach-Änderungen

- `Wohnadresse von Berlin, ... zu/nach Hamburg, ... geändert/verlegt` wird erkannt.
- Arbeitsadresse und zusätzliche `Meldeadresse` bleiben ausgeschlossen bzw. konfliktbehaftet.
- Verifikation: `tests/test_weather_context.py` -> `216 passed`, zwei positive From-to-Smokes plus Arbeits-/Melde-Negativfälle, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `82316f36 fix: parse labelled from-to address moves`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-38

- `teebotus.service` aktiv/running, `MainPID 450172`, Start `2026-07-19 20:13:41 CEST`.
- Neuer Zyklus seit diesem Restart: `4/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Passive und nominale Wohnadresswechsel

- `Wohnadresse wurde von ... nach ... verlegt/geändert` und `Umzug der Wohnadresse von ... nach ... ist erfolgt` werden erkannt.
- Arbeitsadresse und zusätzliche `Meldeadresse` bleiben ausgeschlossen bzw. konfliktbehaftet.
- Verifikation: `tests/test_weather_context.py` -> `217 passed`, drei positive Passive-/Nominal-Smokes plus Arbeits-/Melde-Negativfälle, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `1472379d fix: parse passive residence address moves`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-39

- `teebotus.service` aktiv/running, `MainPID 450172`, Start `2026-07-19 20:13:41 CEST`.
- Neuer Zyklus seit diesem Restart: `5/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Einzeilige Label-Separatoren

- `Wohnadresse: Berlin, ... ->/nach Hamburg, ...` wird als Wechsel erkannt.
- Arbeitsadresse und zusätzliche `Meldeadresse` bleiben ausgeschlossen bzw. konfliktbehaftet.
- Verifikation: `tests/test_weather_context.py` -> `218 passed`, zwei positive Separator-Smokes plus Arbeits-/Melde-Negativfälle, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `36be3fd6 fix: parse colon separator address moves`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-40

- `teebotus.service` aktiv/running, `MainPID 450172`, Start `2026-07-19 20:13:41 CEST`.
- Neuer Zyklus seit diesem Restart: `6/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Alternativmarker bei Wohnorten

- `entweder ... oder ...` wird nicht mehr als Stadtfragment gespeichert; alternative Adressziele bleiben ungeklärt.
- Verifikation: `tests/test_weather_context.py` -> `219 passed`, zwei Alternative-/Frage-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c9596c56 fix: reject either-or residence targets`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-41

- `teebotus.service` aktiv/running, `MainPID 450172`, Start `2026-07-19 20:13:41 CEST`.
- Neuer Zyklus seit diesem Restart: `7/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Unabgeschlossene Straßenumzüge

- `Ich ziehe von ... nach ...` und `Ich ziehe gerade von ... nach ...` werden nicht mehr als aktueller Wohnort übernommen.
- Abgeschlossene Form `Ich bin von ... nach ... gezogen` bleibt gültig.
- Verifikation: `tests/test_weather_context.py` -> `220 passed`, zwei Future-Smokes plus abgeschlossener Move-Regression, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `28f1b380 fix: reject unfinished street moves`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-42

- `teebotus.service` aktiv/running, `MainPID 450172`, Start `2026-07-19 20:13:41 CEST`.
- Neuer Zyklus seit diesem Restart: `8/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Geplante Wohnadresswechsel

- `Ich plane/beabsichtige, meine Wohnadresse von ... nach ... zu verlegen` wird als Zukunft verworfen.
- Ein bestehender aktueller Wohnort vor einem späteren Plan bleibt erhalten.
- Verifikation: `tests/test_weather_context.py` -> `221 passed`, zwei Plan-Smokes plus Current-before-plan-Regression, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `8c13df14 fix: reject planned address moves`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-43

- `teebotus.service` aktiv/running, `MainPID 450172`, Start `2026-07-19 20:13:41 CEST`.
- Neuer Zyklus seit diesem Restart: `9/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Straßenfragment im Mehrziel-Guard

- Bei `Ich wohne in Berlin, Musterstr. 5 und besuche Hamburg, Hauptweg 7` wird `Musterstr` nicht mehr als zweite Stadt interpretiert.
- Besuchs-/Reisezielschutz bleibt aktiv.
- Verifikation: `tests/test_weather_context.py` -> `222 passed`, zwei Residence-before-Visit-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `935f4866 fix: ignore street fragments in residence ambiguity`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-44

- `teebotus.service` aktiv/running, `MainPID 450172`, Start `2026-07-19 20:13:41 CEST`.
- Neuer Zyklus seit diesem Restart: `10/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Zeitlich mehrere Wohnadressen

- `Ich wohne in Berlin, ... und lebe zeitweise/abwechselnd in Hamburg, ...` wird nicht auf den zweiten Ort reduziert, sondern bleibt ungeklärt.
- Verifikation: `tests/test_weather_context.py` -> `223 passed`, zwei temporale Mehrfach-Wohn-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `cfc4b3d9 fix: reject temporal multiple street residences`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-45

- `teebotus.service` aktiv/running, `MainPID 450172`, Start `2026-07-19 20:13:41 CEST`.
- Neuer Zyklus seit diesem Restart: `11/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Hauptwohnung gegenüber Zweitwohnung

- `Meine Hauptwohnung ist in Berlin, ...` wird als Hauptwohnsitz erkannt; `Zweitwohnung` wird nicht fälschlich als Wohnort übernommen.
- Bei Haupt- und Zweitwohnung gewinnt primäre `Berlin`-Adresse.
- Verifikation: `tests/test_weather_context.py` -> `224 passed`, drei Main-/Secondary-Home-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `3b4fa631 fix: recognize main home street addresses`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-46

- `teebotus.service` aktiv/running, `MainPID 450172`, Start `2026-07-19 20:13:41 CEST`.
- Neuer Zyklus seit diesem Restart: `12/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Hauptwohnung vor Zweitwohnung mit `und`

- `Hauptwohnung befindet sich in Berlin, ... und die Zweitwohnung in Hamburg, ...` akzeptiert Anschlusswörter nach der primären Straßenadresse.
- Primäre `Berlin`-Adresse bleibt erhalten.
- Verifikation: `tests/test_weather_context.py` -> `224 passed`, Main-before-Secondary-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `cfc84244 fix: preserve main home before secondary home`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-47

- `teebotus.service` aktiv/running, `MainPID 450172`, Start `2026-07-19 20:13:41 CEST`.
- Neuer Zyklus seit diesem Restart: `13/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Primäre Wohnung nach „Ich habe"

- `Ich habe eine/meine Wohnung in Berlin, Musterstr. 5` wird erkannt.
- `Zweitwohnung` und `Ferienwohnung` bleiben ausgeschlossen; bei primärer Wohnung plus Nebenwohnung gewinnt Berlin.
- Verifikation: `tests/test_weather_context.py` -> `225 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `93fc9482 fix: recognize primary owned homes`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-48

- `teebotus.service` aktiv/running, `MainPID 450172`, Start `2026-07-19 20:13:41 CEST`.
- Neuer Zyklus seit diesem Restart: `14/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Städtenamen mit `bin` am Anfang

- `_clean_city` verwirft `Binz` und `Bingen` nicht mehr als vermeintliche `bin...`-Verbfragmente.
- Verbphrase-Schutz bleibt für das eigenständige Wort `bin` aktiv.
- Verifikation: `tests/test_weather_context.py` -> `226 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `d8369462 fix: accept cities beginning with bin`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-49

- `teebotus.service` aktiv/running, `MainPID 450172`, Start `2026-07-19 20:13:41 CEST`.
- Neuer Zyklus seit diesem Restart: `15/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Parenthesized compound city `Frankfurt (Oder)`

- `Frankfurt (Oder)` wird nicht mehr als logisches `oder`/Mehrfachwohnort fehlklassifiziert.
- Bestehende Compound-Städte und echte alternative Wohnorte bleiben getrennt behandelt.
- Verifikation: `tests/test_weather_context.py` -> `226 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `1e77216e fix: preserve parenthesized compound cities`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-50

- `teebotus.service` aktiv/running, `MainPID 450172`, Start `2026-07-19 20:13:41 CEST`.
- Neuer Zyklus seit diesem Restart: `16/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Casefold-Normalisierung mit `ß`

- `Neustadt an der Weinstraße` wird auch bei komplett kleingeschriebener Eingabe auf kanonische Schreibweise normalisiert.
- Mapping-Schlüssel folgt jetzt dem verwendeten `.casefold()`-Verhalten.
- Verifikation: `tests/test_weather_context.py` -> `226 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `73c02a5f fix: normalize sharp-s compound city names`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-51

- `teebotus.service` aktiv/running, `MainPID 450172`, Start `2026-07-19 20:13:41 CEST`.
- Neuer Zyklus seit diesem Restart: `17/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Kollision langer Wohnort-Memory-IDs

- `_city_id_token` hängt bei abgeschnittenen Städtenamen Hash-Suffix an.
- Unterschiedliche lange Städte mit identischem 48-Zeichen-Präfix überschreiben sich nicht mehr; kurze bestehende IDs bleiben stabil.
- Verifikation: `tests/test_weather_context.py` -> `227 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `80689ded fix: prevent long city memory id collisions`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-52

- `teebotus.service` aktiv/running, `MainPID 450172`, Start `2026-07-19 20:13:41 CEST`.
- Neuer Zyklus seit diesem Restart: `18/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Aktivitätspräfixe in Ortsnamen

- Aktivitätsfilter erkennt konkrete Verbformen statt beliebiger Wortpräfixe.
- `Gehrden`, `Reiskirchen`, `Machern`, `Sehnde` und `Treffurt` werden nicht mehr als Arbeit-/Reisefragmente verworfen.
- Verifikation: `tests/test_weather_context.py` -> `228 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `078fe770 fix: avoid activity prefix city false negatives`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-53

- `teebotus.service` aktiv/running, `MainPID 450172`, Start `2026-07-19 20:13:41 CEST`.
- Neuer Zyklus seit diesem Restart: `19/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Ortsname `Fahren` gegen Fahrverb

- Der gültige Ortsname `Fahren` wird nicht mehr als Infinitivfragment `fahren` verworfen.
- Konkrete Fahrformen mit Flexionsendung bleiben im Aktivitätsfilter.
- Verifikation: `tests/test_weather_context.py` -> `228 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `f745a1ef fix: accept fahren residence town`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-54

- Vor Restart: `teebotus.service` aktiv/running, `MainPID 450172`, Start `2026-07-19 20:13:41 CEST`.
- Neuer Zyklus abgeschlossen: `20/20` Code-Fixes. Restart jetzt erforderlich; kein Push.

## Aktueller Ledger 2026-07-19-Post-Restart-4-55

- `teebotus.service` nach Zyklusrestart aktiv/running, `MainPID 747309`, Start `2026-07-19 21:20:05 CEST`.
- Neuer Zyklus seit diesem Restart: `0/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Wohnort neben besessenem Zweitobjekt

- `Ich wohne in Berlin und besitze ein Haus/eine Wohnung in Hamburg` behält Berlin als Wohnort.
- Besitzformeln werden nicht als zweites Wohnziel behandelt; echte zweite Wohnformeln bleiben mehrdeutig.
- Verifikation: `tests/test_weather_context.py` -> `229 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `52e559c1 fix: preserve residence beside owned property`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-56

- `teebotus.service` aktiv/running, `MainPID 747309`, Start `2026-07-19 21:20:05 CEST`.
- Neuer Zyklus seit diesem Restart: `1/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Wohnort neben Objektverwaltung

- `vermiete`, `verkaufe`, `verwalte`, `renoviere`, `saniere` und `nutze` werden in Anschluss an einen Wohnsatz nicht als zweites Wohnziel behandelt.
- `miete` bleibt bewusst mehrdeutig, weil es eine echte Wohnungsanmietung sein kann.
- Verifikation: `tests/test_weather_context.py` -> `230 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `0c50f48e fix: preserve residence beside property activity`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-57

- `teebotus.service` aktiv/running, `MainPID 747309`, Start `2026-07-19 21:20:05 CEST`.
- Neuer Zyklus seit diesem Restart: `2/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Wohnangaben anderer Personen

- `meine Freundin/meine Eltern wohnen in Hamburg` wird nicht als eigener Wohnort übernommen.
- Eigener Wohnort bleibt bei Komma- und `und`-Satzform in Berlin.
- Verifikation: `tests/test_weather_context.py` -> `231 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `edc89ca3 fix: ignore other people residence claims`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-58

- `teebotus.service` aktiv/running, `MainPID 747309`, Start `2026-07-19 21:20:05 CEST`.
- Neuer Zyklus seit diesem Restart: `3/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Fremde Wohnortlabels nach eigener Stadt

- `Hamburg ist der Wohnort meiner Freundin/Eltern` wird nicht als eigener Wohnort ausgewertet.
- Das gilt für Komma- und `und`-Verknüpfung; eigener Wohnort Berlin bleibt erhalten.
- Verifikation: `tests/test_weather_context.py` -> `231 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `8e65bb23 fix: ignore other person residence labels`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-59

- `teebotus.service` aktiv/running, `MainPID 747309`, Start `2026-07-19 21:20:05 CEST`.
- Neuer Zyklus seit diesem Restart: `4/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Wohnortlabels von Organisationen

- `Wohnort meiner Firma/meines Arbeitgebers` wird nicht als eigener User-Wohnort gewertet.
- Organisationen, Schulen und Betriebe folgen derselben Fremdträger-Regel wie Personen.
- Verifikation: `tests/test_weather_context.py` -> `231 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `0959c2b2 fix: ignore organization residence labels`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-60

- `teebotus.service` aktiv/running, `MainPID 747309`, Start `2026-07-19 21:20:05 CEST`.
- Neuer Zyklus seit diesem Restart: `5/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Grammatische Fremdlabel-Varianten

- Fremde Wohnorte mit `von meiner`, `der`, `dem`, `den` und ähnlichen Präfixen werden nicht als eigener Ort übernommen.
- Organisationen und Personen bleiben über Kasus-/Artikelvarianten geschützt.
- Verifikation: `tests/test_weather_context.py` -> `231 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `51565b43 fix: handle inflected foreign residence labels`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-61

- `teebotus.service` aktiv/running, `MainPID 747309`, Start `2026-07-19 21:20:05 CEST`.
- Neuer Zyklus seit diesem Restart: `6/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

## Vault-Migration 2026-07-19

- Kanonischer Default-Vault fuer alle Instanzen ist jetzt `/home/teladi/Dokumente/Obsidian_Vaults/Teladi_Programming`.
- `TeeBotus/artifact_outputs.py` fuehrt den Vault-Pfad zentral; Standardausgaben gehen nach `Teladi_Programming/incomming`.
- `TeeBotus/runtime/codex_command.py` nutzt den Bauplanpfad unter `Teladi_Programming/Projekte/TeeBotus/Bauplaene!`.
- `.env` wurde lokal auf den neuen `TEEBOTUS_OBSIDIAN_INCOMING_DIR` umgestellt; der alte `Teladi_Def_Obs_Vault` bleibt unangetastet und ist EOL.
- Der aktuelle externe Bauplanstand wurde nach `Teladi_Programming/Projekte/TeeBotus/Bauplaene!` migriert. Der alte Plan wird nicht weiter gepflegt.
- Verifikation: 150 fokussierte Tests gruen, `py_compile` gruen, `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-/Konfigurationscommit: `2a95628f config: switch default Obsidian vault to Teladi Programming`.
- `teebotus.service` bleibt bis zum planmaessigen `20/20`-Restart unveraendert laufend; neue Umgebung greift beim naechsten Restart.

## Aktueller Ledger 2026-07-19-Post-Restart-4-62

- `teebotus.service` aktiv/running, `MainPID 747309`, Start `2026-07-19 21:20:05 CEST`.
- Neuer Zyklus seit diesem Restart: `7/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Weitere Fremdpersonen bei Wohnortlabels

- `Frau`, `Mann`, `Ehepartner`, `Chef` und `Vorgesetzte` werden bei fremden Wohnortangaben wie Personen behandelt.
- Die gemeinsame Label-Liste verhindert sowohl falsche Ueberschreibung durch `Hamburg ist der Wohnort meiner Frau` als auch falsche Mehrdeutigkeit bei `Ich wohne in Berlin und meine Frau wohnt in Hamburg`.
- Verifikation: `tests/test_weather_context.py` -> `232 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `7a14b886 fix: ignore common foreign residence labels`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-63

- `teebotus.service` aktiv/running, `MainPID 747309`, Start `2026-07-19 21:20:05 CEST`.
- Neuer Zyklus seit diesem Restart: `8/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Hauptwohnung ohne Strassenadresse

- `Meine Hauptwohnung ist in Berlin, meine Zweitwohnung in Hamburg` liefert jetzt Berlin als Primaerwohnort.
- Das gilt auch fuer `befindet sich` und `und`-Verknuepfungen; eine explizite Zweitwohnung ueberschreibt den Hauptort nicht.
- Verifikation: `tests/test_weather_context.py` -> `232 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `aa10c31c fix: recognize primary home without street address`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-64

- `teebotus.service` aktiv/running, `MainPID 747309`, Start `2026-07-19 21:20:05 CEST`.
- Neuer Zyklus seit diesem Restart: `9/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Zeitliche Fremdorte nicht als Konflikt

- Historische Adressen und zukuenftige Wohnorte werden aus Konflikt-/Mehrfachwohnortmengen ausgeschlossen.
- `Ich wohne in Berlin, meine alte Adresse ist in Hamburg` und `Mein zukuenftiger Wohnort ist Hamburg` behalten Berlin als aktuellen Wohnort.
- Verifikation: `tests/test_weather_context.py` -> `232 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `992d8cbd fix: ignore temporal residence conflicts`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-65

- `teebotus.service` aktiv/running, `MainPID 747309`, Start `2026-07-19 21:20:05 CEST`.
- Neuer Zyklus seit diesem Restart: `10/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Weitere Fremdpersonen und Kasusformen

- Familien-, Partner-, Nachbarschafts-, Betreuungs- und medizinische Rollen werden in Fremdwohnortlabels erkannt.
- Kasus-/Pluralformen wie `meines Arztes`, `meiner Nachbarn` und `meiner Großeltern` ueberschreiben den eigenen Wohnort nicht mehr.
- Verifikation: `tests/test_weather_context.py` -> `232 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `53d80e86 fix: cover additional foreign residence labels`.

## Aktueller Ledger 2026-07-19-Post-Restart-5-00

- `teebotus.service` nach planmaessigem Restart aktiv/running, `MainPID 929669`, Start `2026-07-19 22:00:21 CEST`.
- Neuer Zyklus seit diesem Restart: `0/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.
- Der Prozess laedt jetzt die kanonische Vault-Konfiguration aus `Teladi_Programming`; der alte Vault bleibt EOL und unangetastet.

## Aktueller Ledger 2026-07-19-Post-Restart-5-01

- `teebotus.service` aktiv/running, `MainPID 929669`, Start `2026-07-19 22:00:21 CEST`.
- Neuer Zyklus seit diesem Restart: `1/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Weitere zusammengesetzte Stadtnamen

- `Weiden in der Oberpfalz` und `Weil am Rhein` bleiben vollstaendig erhalten.
- Das gilt fuer normale Wohnortsaetze und Wohnort plus Strassenadresse.
- Verifikation: `tests/test_weather_context.py` -> `232 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `0c6fc309 fix: preserve additional compound city names`.

## Aktueller Ledger 2026-07-19-Post-Restart-5-02

- `teebotus.service` aktiv/running, `MainPID 929669`, Start `2026-07-19 22:00:21 CEST`.
- Neuer Zyklus seit diesem Restart: `2/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Vollstaendige Compound-City-Matches priorisieren

- Generische `bei`-/`in`-Patterns schneiden bekannte zusammengesetzte Ortsnamen nicht mehr auf den letzten Teil herunter.
- `Neustadt bei Coburg` bleibt vollstaendig erhalten; der Schutz gilt fuer alle zentral registrierten Compound-City-Namen und Trailing-Punktuation.
- Verifikation: `tests/test_weather_context.py` -> `232 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `b489756f fix: prioritize full compound city matches`.

## Aktueller Ledger 2026-07-19-Post-Restart-5-03

- `teebotus.service` aktiv/running, `MainPID 929669`, Start `2026-07-19 22:00:21 CEST`.
- Neuer Zyklus seit diesem Restart: `3/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Inflektierte Organisations-/Institutionslabels

- `Unternehmen`, `Betriebe`, `Vereine`, Firmenplural sowie Praxis-, Klinik-, Hochschul- und Behördenformen werden als Fremdtraeger erkannt.
- Solche Orte ueberschreiben den eigenen Wohnort nicht mehr.
- Verifikation: `tests/test_weather_context.py` -> `232 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `1f1562b0 fix: cover inflected organization residence labels`.

## Aktueller Ledger 2026-07-19-Post-Restart-5-04

- `teebotus.service` aktiv/running, `MainPID 929669`, Start `2026-07-19 22:00:21 CEST`.
- Neuer Zyklus seit diesem Restart: `4/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Regionale Compound-City-Namen

- `Buchholz in der Nordheide`, `Freiburg im Breisgau`, `Freiberg am Neckar`, `Burg auf Fehmarn`, `Dillingen an der Donau` und `Neumarkt in der Oberpfalz` werden vollstaendig gespeichert.
- Plaintext- und Strassenadressformen nutzen denselben zentralen Compound-Schutz.
- Verifikation: `tests/test_weather_context.py` -> `232 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `9bfc037e fix: preserve regional compound city names`.

## Aktueller Ledger 2026-07-19-Post-Restart-5-05

- `teebotus.service` aktiv/running, `MainPID 929669`, Start `2026-07-19 22:00:21 CEST`.
- Neuer Zyklus seit diesem Restart: `5/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Slash-qualifizierte Stadtnamen

- `Mühlhausen/Thüringen`, `Schwedt/Oder` und `Wittstock/Dosse` werden als offizielle Compound-Cities erkannt.
- Der Slash loest dort keine falsche Mehrfachwohnortregel aus; Plaintext und Strassenadresse bleiben stabil.
- Verifikation: `tests/test_weather_context.py` -> `232 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `38c8955b fix: preserve slash-qualified city names`.

## Aktueller Ledger 2026-07-19-Post-Restart-5-06

- `teebotus.service` aktiv/running, `MainPID 929669`, Start `2026-07-19 22:00:21 CEST`.
- Neuer Zyklus seit diesem Restart: `6/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Region-zu-Stadt-Aufloesung

- `Bayern, in München`, `Nordrhein-Westfalen, in Köln` und `NRW, in Köln` liefern jetzt die Stadt.
- Bare `NRW` bleibt wie andere Regionen kein Wohnort; der Alias wird nicht als Stadt gespeichert.
- Verifikation: `tests/test_weather_context.py` -> `232 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `599f16ab fix: resolve region-prefixed residence cities`.
