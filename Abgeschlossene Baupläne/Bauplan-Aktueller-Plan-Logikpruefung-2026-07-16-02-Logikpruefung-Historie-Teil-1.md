# Bauplan: Logikpruefung-Historie, Teil 1

**Kategorie:** fortlaufende historische Befunde und Regressionen

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

