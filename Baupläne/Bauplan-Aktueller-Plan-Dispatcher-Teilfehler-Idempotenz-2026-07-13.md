# Bauplan: Aktueller Plan fuer Telegram-Dispatcher-Teilfehler und Idempotenz

**Stand:** 2026-07-13

**Status:** Aktiv

**Parent-Plan:**
`Baupläne/Bauplan-Aktueller-Plan-Logikpruefung-Telegram-Runtime-2026-07-13.md`

**Quellstand:** TeeBotus `1.9.498`, letzter lokaler Commit
`535c1e18 fix: defer Telegram attachment downloads`

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
- Die relevante Testsuite meldete zuletzt `602 passed, 17 subtests passed`.
- Seit dem letzten Live-Restart am 2026-07-13 um 18:17 CEST liegen 17 lokale
  Commits vor. Der naechste Restart ist erst am 20-Commit-Fenster faellig.
- Push ist nicht angefordert und bleibt aus.
- Die uncommitteten Benutzerdateien `.obsidian/`, `.stfolder/`,
  `Fusion_Packliste.txt`, `Unbenannt.base` und `Unbenannt.canvas` bleiben
  unangetastet.

## Arbeitspakete

### 1. Dispatcher-Vertrag pruefen

- [ ] `handle_update` und `_dispatch_modern_telegram_actions` gemeinsam lesen.
- [ ] Festhalten, wann ein Poll-Offset fortgeschrieben wird.
- [ ] Pruefen, ob ein Fehler nach bereits erfolgreicher Aktion den gesamten
  Update-Retry ausloest.
- [ ] `message_tracking` auf vorhandene Sent-Message-, Dedupe- und
  Restore-Mechanismen pruefen.
- [ ] Den Unterschied zwischen absichtlich erneut versendbaren Aktionen und
  nicht idempotenten Seiteneffekten dokumentieren.

### 2. Fehler reproduzieren und minimal beheben

- [ ] Einen lokalen Fake-API-Fall mit mindestens zwei Aktionen aufbauen:
  Aktion 1 erfolgreich, Aktion 2 fehlschlaegt, anschliessender Update-Retry.
- [ ] Beweisen, ob Aktion 1 doppelt gesendet wird oder bereits sicher
  unterdrueckt wird.
- [ ] Nur bei bestaetigtem Fehler die kleinste passende Korrektur einbauen.
- [ ] Identitaet des Updates, Aktionsreihenfolge, Retry-Verhalten und
  Fehlermeldung erhalten.
- [ ] Keine kostenpflichtigen Provider- oder LLM-Aufrufe verwenden.

### 3. Regression und Nachweis

- [ ] Fokussierte Dispatcher-/Telegram-Tests ergaenzen.
- [ ] Die relevante Suite vollstaendig ausfuehren.
- [ ] `git diff --check` ausfuehren.
- [ ] Testergebnis und allfaellige Restunsicherheit hier dokumentieren.
- [ ] Nach abgeschlossenem Fix lokal committen.
- [ ] Keinen Push ohne ausdrueckliche Anforderung ausfuehren.
- [ ] Keinen Restart vor dem 20-Commit-Fenster ausfuehren, sofern nicht
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

Noch offen. Nach Abschluss mindestens dokumentieren:

```text
.venv-py313/bin/pytest -q tests/test_bot.py tests/test_telegram_runner.py \
  tests/test_engine_identity_flows.py tests/test_adapters.py \
  tests/test_runtime_state.py
git diff --check
```

