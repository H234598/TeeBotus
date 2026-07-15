# Bauplan: Aktueller Plan fuer Telegram-Dispatcher-Teilfehler und Idempotenz

**Stand:** 2026-07-13

**Status:** Abgeschlossen fuer Dispatcher-Teilfehler, Journal und Offset-Commit

**Parent-Plan:**
`Baupläne/Bauplan-Aktueller-Plan-Logikpruefung-Telegram-Runtime-2026-07-13.md`

**Quellstand:** TeeBotus `1.9.498`, Dispatcher-Journal-Fix dieses Abschnitts

## Auftrag

Den aktuellen Logikpruefungs-Plan im Telegram-Runtime-Thema fortsetzen. Der
moderne Action-Dispatcher muss bei Teilfehlern, Telegram-Retries und erneut
zugestellten Updates idempotent und nachvollziehbar bleiben. Bereits
erfolgreich ausgefuehrte Aktionen duerfen durch einen Poller-Retry nicht
versehentlich doppelt gesendet werden. Fehler muessen sichtbar bleiben und
duerfen nicht durch ein vorschnelles Fortschreiben des Poll-Offsets
verschluckt werden.

Der uebergeordnete Arbeitsauftrag lautet:

> Entwickle und finde Logikfehler. Bleibe moeglichst bei einer Datei bzw. einem
> Thema, um Token zu sparen.

## Aktueller Arbeitsstand

- Der moderne Telegram-Pfad erkennt Replys auf eigene Botnachrichten vor der
  Accountaufloesung.
- Eine voruebergehend fehlende `getMe`-Identitaet wird vor dem Polling einmal
  erneut aufgeloest; bei weiterem Fehlen bleibt die Gruppenadressierung
  fail-closed.
- Telegram-Anhaenge werden erst nach Reply-, Adressierungs- und Status-Gate
  heruntergeladen. Unadressierte Gruppenanhaenge loesen keinen Download aus.
- Die relevante Testsuite meldet jetzt `604 passed, 17 subtests passed`.
- Vor dem aktuellen Timeout-Fix lagen seit dem letzten Live-Restart am
  2026-07-13 um 18:17 CEST 19 lokale Commits vor.
  Der Restart erfolgte danach am 20-Commit-Fenster. Der naechste Restart ist
  erst am naechsten 20-Commit-Fenster faellig.
- Push ist nicht angefordert und bleibt aus.
- Die uncommitteten Benutzerdateien `.obsidian/`, `.stfolder/`,
  `Fusion_Packliste.txt`, `Unbenannt.base` und `Unbenannt.canvas` bleiben
  unangetastet.

## Arbeitspakete

### 1. Dispatcher-Vertrag pruefen

- [x] `handle_update` und `_dispatch_modern_telegram_actions` gemeinsam lesen.
- [x] Festhalten, wann ein Poll-Offset fortgeschrieben wird: erst nach
  erfolgreichem `handle_update`; ein Dispatchfehler fuehrt zum Retry desselben
  Updates.
- [x] Pruefen, ob ein Fehler nach bereits erfolgreicher Aktion den gesamten
  Update-Retry ausloest.
- [x] `message_tracking` auf vorhandene Sent-Message-, Dedupe- und
  Restore-Mechanismen pruefen.
- [x] Den Unterschied zwischen absichtlich erneut versendbaren Aktionen und
  nicht idempotenten Seiteneffekten dokumentieren.

### 2. Fehler reproduzieren und minimal beheben

- [x] Einen lokalen Fake-API-Fall mit mindestens zwei Aktionen aufbauen:
  Aktion 1 erfolgreich, Aktion 2 fehlschlaegt, anschliessender Update-Retry.
- [x] Beweisen: Vor dem Fix wurde Aktion 1 bei der Wiederholung doppelt
  gesendet, weil Message-Tracking erst nach der vollstaendigen Aktionsliste
  schrieb.
- [x] Die kleinste passende Korrektur einbauen: Aktionen werden einzeln
  versendet, der Fortschritt wird pro Update im laufenden Runtime-Prozess
  gehalten, und das Engine-Ergebnis wird bei diesem Retry wiederverwendet.
- [x] Identitaet des Updates, Aktionsreihenfolge, Retry-Verhalten und
  Fehlermeldung erhalten.
- [x] Keine kostenpflichtigen Provider- oder LLM-Aufrufe verwenden.

- [x] Den Dispatch-Fortschritt ueber einen Prozessneustart hinweg persistent
  machen: Der moderne Telegram-Pfad schreibt vor dem Versand einen
  verschluesselten, explizit allowlisteten Action-Plan und markiert jede
  bestaetigte Aktion einzeln. Ein neuer Runtime-Kontext laedt diesen Plan und
  setzt nur offene Aktionen fort. Klartext-Message- und Dateiinhalte liegen
  nicht im Journal.
- [x] Journalfehler fail-closed behandeln: Wenn der Plan nicht sicher
  geschrieben werden kann, bleibt das Update unbestaetigt und es wird kein
  in-memory-only Retry weitergefuehrt.
- [x] Offset-Commit-Reihenfolge absichern: Das Dispatch-Journal bleibt nach
  erfolgreichem Versand erhalten, bis der Telegram-Offset atomar geschrieben
  wurde. Ein fehlgeschlagener Offset-Write oder eine fehlgeschlagene
  Journal-Finalisierung laesst das Update retrybar und verhindert dadurch eine
  erneute Seiteneffekt-Ausfuehrung.
- [x] Den Timeout-Pfad absichern: Ein laufender Versand wird durch einen
  In-Flight-Lock nicht parallel erneut gestartet. Der Timeout bleibt ein
  Retry-Fehler und sendet keine konkurrierende Fallback-Antwort; das Update
  wird erst nach einem belastbaren Dispatch-Ergebnis bestaetigt.

### 3. Regression und Nachweis

- [x] Fokussierte Dispatcher-/Telegram-Tests ergaenzen.
- [x] Die relevante Suite vollstaendig ausfuehren.
- [x] `git diff --check` ausfuehren.
- [x] Testergebnis und allfaellige Restunsicherheit hier dokumentieren.
- [x] Nach abgeschlossenem Fix lokal committen.
- [x] Keinen Push ohne ausdrueckliche Anforderung ausfuehren.
- [x] Keinen Restart vor dem 20-Commit-Fenster ausfuehren, sofern nicht
  ausdruecklich angefordert.

## Leitplanken

- Sicherheit und Zustellintegritaet vor Bequemlichkeit.
- Poll-Offsets nur nach einem belastbaren Dispatcher-Ergebnis bestaetigen.
- Teilfehler nicht als vollstaendigen Erfolg melden.
- Keine History-, Outbox- oder Dispatchdaten loeschen.
- Bestehende Benutzer- und Projektdateien ausserhalb dieses Themas nicht
  umstrukturieren.
- Tests muessen lokal und ohne externe LLM-Kosten laufen.

## Abnahmekriterien

Der Plan ist abgeschlossen, wenn:

1. der Teilfehlerfall mit einem lokalen Test reproduziert oder belastbar als
   bereits idempotent nachgewiesen wurde;
2. ein bestaetigter Fehler korrigiert und durch eine Regression abgesichert ist;
3. der Poll-Offset-Vertrag und das Retry-Verhalten dokumentiert sind;
4. die relevante Testsuite ohne Fehler laeuft;
5. der Testnachweis und der lokale Commit in diesem Plan eingetragen sind.

## Testnachweis

Der Teilfehler-Regressionstest ist gruen:

```text
.venv-py313/bin/pytest -q tests/test_bot.py -k 'modern_dispatch_retry_skips_completed_actions_and_reuses_engine_result'
1 passed, 188 deselected
```

Der Timeout-Regressionstest ist ebenfalls gruen:

```text
.venv-py313/bin/pytest -q tests/test_bot.py -k 'modern_dispatch_retry or modern_dispatch_timeout'
2 passed, 188 deselected in 1.61s
```

Der Prozessneustart-Nachweis ist gruen:

```text
.venv-py313/bin/pytest -q tests/test_bot.py -k 'modern_dispatch_retry or modern_dispatch_timeout'
3 passed, 188 deselected in 1.83s

.venv-py313/bin/pytest -q tests/test_bot.py -k 'run_polling or modern_dispatch_retry or modern_dispatch_timeout'
10 passed, 182 deselected in 3.22s
```

Die relevante Suite ist gruen:

```text
.venv-py313/bin/pytest -q tests/test_bot.py tests/test_telegram_runner.py \
  tests/test_engine_identity_flows.py tests/test_adapters.py \
  tests/test_runtime_state.py
606 passed, 17 subtests passed in 11.52s

git diff --check
```

## Nachtrag 2026-07-15

- Der verschluesselte Dispatch-Plan wurde mit `StaticSecretProvider` in einem
  neuen Runtime-Kontext wieder eingelesen. Aktion 1 blieb abgeschlossen,
  Aktion 2 wurde genau einmal nachgesendet; das Engine-Ergebnis wurde nicht
  erneut erzeugt. Der Test prueft ausserdem, dass `second` nicht im Journal-
  Dateibyte vorkommt.
- Die Zustellgarantie bleibt bewusst **at-least-once**: Ein Prozessabsturz
  exakt zwischen Telegram-Erfolg und dem lokalen Fortschritts-Write kann eine
  einzelne Aktion erneut senden. Telegram bietet dafuer keinen atomaren
  Commit mit unserem Journal. Das Journal reduziert das Fenster auf diese
  unvermeidbare Remote-Grenze.
- Die relevante Suite und Syntaxpruefung liefen ohne Provider-/LLM-Aufruf.
- Lokaler Commit fuer diesen Folgefix ist gesetzt; Push bleibt aus.
- Der Offset-Commit-Test reproduziert einen fehlgeschlagenen ersten Write:
  Telegram liefert Update `7` erneut, aber die Aktion `once` wird nur einmal
  gesendet. Erst nach erfolgreichem Offset-Write wird das verschluesselte
  Journal final geloescht. Damit ist die lokale Reihenfolge
  `dispatch -> offset durable -> journal complete` belastbar.
- 2026-07-15: Logikfehler im modernen Telegram-Pfad behoben: Lange
  `SendText`-Antworten wurden dort als eine ungeteilte API-Aktion gesendet,
  obwohl der Legacy-Pfad bereits Telegram-Chunks verwendete. Antworten ueber
  Telegrams Nachrichtenlimit konnten dadurch abgelehnt werden. Chunks werden
  jetzt vor Retry-Journal und Action-Indizes erzeugt; jeder Chunk ist damit
  einzeln retrybar und trackbar. Buttons bleiben am letzten Chunk, lange
  formatierte Varianten fallen auf Plaintext-Chunks zurueck.
- Regressionstest fuer Chunk-Grenze, Button-Platzierung und Action-Expansion
  ergaenzt. Relevante Suite: `607 passed, 17 subtests passed in 13.03s`;
  keine Provider-/LLM-Aufrufe. `py_compile` und `git diff --check` sauber.
