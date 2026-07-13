# Bauplan: Aktueller Plan fuer Logikpruefung und Versionskonsistenz

**Stand:** 2026-07-13  
**Status:** Aktiv, noch nicht abgeschlossen  
**Quellstand:** TeeBotus `1.9.498`; History-Dispatcher `0.2.14`  
**Arbeitsbereich:** `/home/teladi/TeeBotus` und `/home/teladi/History-Dispatcher`  
**Vorgaenger:** `Baupläne/Bauplan-Aktueller-Arbeitsstand-Healthcheck-TBL-Statussemantik-2026-07-13.md`

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
bezogen. Eine erste lokale Paketpruefung zeigte jedoch eine moegliche
Abweichung zwischen:

- `TeeBotus.__version__` und dem Runtime-Marker `1.9.498`;
- der installierten Editable-Distribution im Python-3.13-Venv;
- `importlib.metadata.version("teebotus")`, `pip show teebotus` und den
  vorhandenen `.dist-info`-Dateien.

Dieser Befund wird vor einer Codeaenderung mit frischen Prozessen und allen
gefundenen Distributionpfaden reproduziert. Erst danach wird entschieden, ob
eine Neuinstallation der Editable-Distribution ausreicht oder ob ein
zusaetzlicher Schutztest bzw. Doctor-Befund erforderlich ist.

## Arbeitspakete

### 1. Versionsquellen erfassen

- [ ] `TeeBotus.__version__`, `pyproject.toml` und alle expliziten
  Versionskonstanten erfassen.
- [ ] Alle installierten `teebotus`-Distributionen, `.dist-info`-Pfade und
  Editable-Finder pruefen; Mehrfachinstallationen sichtbar machen.
- [ ] CLI-Skripte, Systemd-Units, Runtime-Marker, `/status`, Healthcheck und
  Applet auf ihre jeweilige Versionsquelle pruefen.
- [ ] Abhaengigkeitsversionen nicht mit der TeeBotus-Programmversion
  verwechseln.

### 2. Widerspruch reproduzieren und Ursache bestimmen

- [ ] `importlib.metadata`, `pip show` und den direkten Quellimport in
  getrennten frischen Prozessen vergleichen.
- [ ] `sys.path`, Venv `lib`/`lib64` und eventuelle doppelte
  `.dist-info`-Verzeichnisse dokumentieren.
- [ ] Pruefen, ob ein alter Editable-Install, ein stale Finder oder ein
  falscher CLI-Wrapper die Abweichung verursacht.

### 3. Korrektur fail-closed umsetzen

- [ ] Die kleinste Korrektur waehlen, die die installierte Distribution wieder
  aus dem aktuellen Quellstand erzeugt.
- [ ] Falls die Abweichung erneut entstehen kann, einen fokussierten
  Regressionstest fuer Quellversion gegen Paketmetadaten ergaenzen.
- [ ] Keine laufenden Dienste fuer eine reine Metadatenkorrektur unnoetig
  neustarten.
- [ ] Keine Provider-, LLM- oder kostenpflichtigen API-Aufrufe ausfuehren.

### 4. Regressionen und Live-Nachweis

- [ ] Metadaten-/SemVer-Tests ausfuehren.
- [ ] Die betroffenen Healthcheck-/Applet-Tests ausfuehren.
- [ ] `compileall`, JavaScript-Syntaxpruefung und `git diff --check`
  ausfuehren, soweit Dateien betroffen sind.
- [ ] Erneut pruefen, dass Quellversion, Paketmetadaten, CLI-Ausgabe und
  Runtime-Marker denselben Wert melden.
- [ ] Den aktuellen Healthcheck schreibfrei pruefen und neue Queue-Eintraege
  von echten Persistenz- oder Routingfehlern trennen.

### 5. Abschluss

- [ ] Testergebnisse und den reproduzierten Befund hier nachtragen.
- [ ] SemVer nur bei einer tatsaechlichen Programmcodeaenderung bumpen.
- [ ] Einen lokalen Commit erstellen.
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
