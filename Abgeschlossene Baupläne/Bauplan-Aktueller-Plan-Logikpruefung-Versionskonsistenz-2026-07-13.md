# Bauplan: Aktueller Plan fuer Logikpruefung und Versionskonsistenz

**Stand:** 2026-07-13  
**Status:** Versionsaudit abgeschlossen; uebergeordneter Logikpruefungs-Goal aktiv
**Quellstand:** TeeBotus `1.9.498`; History-Dispatcher `0.2.14`  
**Arbeitsbereich:** `/home/teladi/TeeBotus` und `/home/teladi/History-Dispatcher`  
**Vorgaenger:** `Abgeschlossene Baupläne/Bauplan-Aktueller-Arbeitsstand-Healthcheck-TBL-Statussemantik-2026-07-13.md`

## Auftrag

> Entwickle und finde Logikfehler. Bleibe moeglichst bei einer Datei bzw. einem
> Thema, um Token zu sparen.

Der aktuelle Pruefauftrag ist die Konsistenz zwischen Quellversion,
Python-Paketmetadaten, CLI-Einstiegspunkten, laufendem Runtime-Marker,
Healthcheck und Cinnamon-Applet. Eine veraltete Paketmetadatenversion darf
weder bei Installation, Diagnose, Benchmarks noch in Statusausgaben eine
andere Version als der ausgefuehrte Quellstand melden.

## Aktueller Arbeitskontext

Die Healthcheck-/TBL-Reconciliation ist im laufenden Vorgaengerplan
dokumentiert. Dort sind insbesondere die Statussemantik
`accepted`/`delivered`/`acknowledged`, die fail-closed Bridge-Pruefungen, die
begrenzten Follow-Diagnosereports und die Queue-Klassifikation festgehalten.

Der letzte Live-Cutover lief mit TeeBotus `1.9.498`. Runtime-Marker und
Quellversion waren dabei passend. Die Health-Anzeige kann sich danach durch
neu eingehende Codex-History veraendern; eine aktuelle Warnung muss deshalb
immer gegen die aktuelle Queue und nicht gegen einen alten Snapshot geprueft
werden.

## Vorbefund

Die Quellversion wird dynamisch aus `TeeBotus.__version__` in `pyproject.toml`
bezogen. Die lokale Paketpruefung reproduzierte eine Abweichung zwischen:

- `TeeBotus.__version__` und dem Runtime-Marker `1.9.498`;
- der installierten Editable-Distribution im Python-3.13-Venv;
- `importlib.metadata.version("teebotus")`, `pip show teebotus` und den
  vorhandenen `.dist-info`-Dateien.

Konkret meldete ein frischer Prozess aus dem Venv den Quellimport als
`1.9.498`, aber ein veraltetes Repository-`teebotus.egg-info` als `1.9.1`.
Die installierte Editable-Distribution meldete parallel `1.8.0`. Damit konnte
derselbe Rechner je nach Abfrageweg drei verschiedene TeeBotus-Versionen
anzeigen.

## Durchgefuehrte Korrektur

- Die Editable-Distribution wurde mit
  `/home/teladi/TeeBotus/.venv-py313/bin/python -m pip install --no-deps
  --editable /home/teladi/TeeBotus` aus dem aktuellen Quellstand neu erzeugt.
- Das ignorierte Repository-`teebotus.egg-info` und die Venv-
  `teebotus-1.9.498.dist-info` melden jetzt denselben Stand wie
  `TeeBotus.__version__`.
- Es wurde kein SemVer-Bump vorgenommen: Die Korrektur betrifft Installation,
  Buildmetadaten und Regressionstest, nicht die Programmfunktion.
- Der Root-Service wurde fuer diese Metadatenkorrektur nicht neu gestartet.

## Arbeitspakete

### 1. Versionsquellen erfassen

- [x] `TeeBotus.__version__`, `pyproject.toml` und alle expliziten
  Versionskonstanten erfassen.
- [x] Alle installierten `teebotus`-Distributionen, `.dist-info`-Pfade und
  Editable-Finder pruefen; Mehrfachinstallationen sichtbar machen.
- [x] CLI-Skripte, Systemd-Units, Runtime-Marker, `/status`, Healthcheck und
  Applet auf ihre jeweilige Versionsquelle pruefen.
- [x] Abhaengigkeitsversionen nicht mit der TeeBotus-Programmversion
  verwechseln.

### 2. Widerspruch reproduzieren und Ursache bestimmen

- [x] `importlib.metadata`, `pip show` und den direkten Quellimport in
  getrennten frischen Prozessen vergleichen.
- [x] `sys.path`, Venv `lib`/`lib64` und eventuelle doppelte
  `.dist-info`-Verzeichnisse dokumentieren.
- [x] Pruefen, ob ein alter Editable-Install, ein stale Finder oder ein
  falscher CLI-Wrapper die Abweichung verursacht.

### 3. Korrektur fail-closed umsetzen

- [x] Die kleinste Korrektur waehlen, die die installierte Distribution wieder
  aus dem aktuellen Quellstand erzeugt.
- [x] Falls die Abweichung erneut entstehen kann, einen fokussierten
  Regressionstest fuer Quellversion gegen Paketmetadaten ergaenzen.
- [x] Keine laufenden Dienste fuer eine reine Metadatenkorrektur unnoetig
  neustarten.
- [x] Keine Provider-, LLM- oder kostenpflichtigen API-Aufrufe ausfuehren.

### 4. Regressionen und Live-Nachweis

- [x] Metadaten-/SemVer-Tests ausfuehren.
- [x] Die betroffenen Healthcheck-/Applet-Tests ausfuehren.
- [x] `compileall`, JavaScript-Syntaxpruefung und `git diff --check`
  ausfuehren, soweit Dateien betroffen sind.
- [x] Erneut pruefen, dass Quellversion und Paketmetadaten denselben Wert
  melden.
- [x] CLI-Ausgabe und Runtime-Marker denselben Programmstand melden.
- [x] Den aktuellen Healthcheck schreibfrei pruefen und neue Queue-Eintraege
  von echten Persistenz- oder Routingfehlern trennen.

### 5. Abschluss

- [x] Testergebnisse und den reproduzierten Befund hier nachtragen.
- [ ] SemVer nur bei einer tatsaechlichen Programmcodeaenderung bumpen.
- [x] Einen lokalen Commit erstellen.
- [ ] Push nur nach ausdruecklicher Anweisung ausfuehren.
- [ ] Restart nur im vereinbarten 20-Commit-Fenster oder nach ausdruecklicher
  Freigabe ausfuehren.

## Sicherheits- und Datenregeln

- Secrets, Account-IDs und private Nachrichteninhalte gehoeren nicht in
  diesen Plan oder Diagnoseausgaben.
- Healthchecks, Statusproben und Dry-Runs bleiben schreibfrei.
- Summarys, Outbox-Zeilen und Dispatch-Resultate werden nicht geloescht.
- Die uncommitteten Benutzerdateien `.obsidian/`, `.stfolder/`,
  `Fusion_Packliste.txt`, `Unbenannt.base` und `Unbenannt.canvas` bleiben
  unangetastet.
- Sicherheit bleibt wichtiger als Performance; unbekannte oder
  widerspruechliche Versionszustaende werden sichtbar gemacht und nicht
  stillschweigend normalisiert.

## Abnahmekriterien

Der Plan ist abgeschlossen, wenn:

1. alle TeeBotus-Versionsquellen und ihre Verantwortlichkeiten dokumentiert
   sind;
2. eine Abweichung zwischen Quellversion und installierter Distribution
   reproduzierbar ausgeschlossen oder technisch behoben ist;
3. ein Regressionstest eine erneute stale-Editable-Version erkennt;
4. Healthcheck, Applet, CLI und Runtime-Marker denselben Programmstand
   anzeigen;
5. die fokussierten Tests und der lokale Nachweis hier mit Datum und Ergebnis
   dokumentiert sind;
6. ein lokaler Commit den abgeschlossenen Planstand festhaelt.

## Nachweisprotokoll

- 2026-07-13: Neuer Bauplan aus dem aktuellen Healthcheck-/TBL-Arbeitsstand
  angelegt. Der Vorgaenger bleibt als Historie erhalten.
- 2026-07-13: Der laufende Quellstand wurde als TeeBotus `1.9.498` und
  History-Dispatcher `0.2.14` festgehalten. Die Versionsmetadatenpruefung ist
  als naechster abgegrenzter Arbeitsschritt offen.
- 2026-07-13: Versionsdrift reproduziert: Quellimport `1.9.498`, Root-
  `teebotus.egg-info` `1.9.1` und Venv-Editable-Distribution `1.8.0`.
- 2026-07-13: Editable-Distribution ohne Abhaengigkeitsinstallation auf
  `1.9.498` regeneriert. Danach meldeten Quellimport,
  `importlib.metadata`, `pip show` und beide sichtbaren `lib`/`lib64`-
  Distributionspfade `1.9.498`.
- 2026-07-13: Regressionen bestanden: `tests/test_pyproject_metadata.py`
  `7 passed`; `tests/test_cinnamon_applet.py` und
  `tests/test_version_notifications.py` `450 passed`; `compileall` und
  `git diff --check` erfolgreich.
- 2026-07-13: `python -m TeeBotus --version` meldete `TeeBotus 1.9.498`;
  der laufende systemd-Runtime-Marker meldete `status=matched`, PID
  `3595281`, Invocation `ca82eb1d...`.
- 2026-07-13: Schreibfreie Applet-Healthprobe bestand mit
  `health.status=ok`, `actionable_problem_count=0`,
  `informational_problem_count=20` und `qdrant_problem_count=0`. Die
  vorhandenen TBL-`no_private_route`-Skips blieben als Hinweise sichtbar und
  wurden nicht mutiert.
- 2026-07-13: Test, Korrektur und Planstand lokal als `6d51712d`
  (`fix: keep installed version metadata in sync`) committed. Kein Push und
  kein Restart wurden ausgeloest.
