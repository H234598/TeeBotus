# Bauplan: Healthcheck-Applet und Statusaggregation

**Stand:** 2026-07-13  
**Status:** Aktiv, noch nicht abgeschlossen  
**Quellstand:** TeeBotus `1.9.461`, Codecommit `78e2806a`
**Geltungsbereich:** `TeeBotus/cinnamon_applet.py`, Cinnamon-Applet, Runtime-Healthpayload und `tests/test_cinnamon_applet.py`

## Auftrag

Die Healthcheck-Logik soll echte Betriebsprobleme, Warnungen und reine
Hinweise deterministisch und konsistent klassifizieren. Python-Payload,
JavaScript-Applet und Tests muessen dieselbe Statussemantik verwenden. Ein
staler oder widerspruechlicher Gesamtzaehler darf keinen vorhandenen
Einzelstatus verstecken.

## Leitplanken

- Sicherheit vor Bequemlichkeit: unbekannte oder widerspruechliche Zustande
  werden nicht als gesund behandelt.
- Keine kostenpflichtigen Provider- oder LLM-Aufrufe fuer Diagnose und Tests.
- Fallbacks duerfen einen fachlich abgedeckten Hinweis herabstufen, aber keinen
  echten, ungeklaerten Fehler verschlucken.
- Die Rohdiagnose bleibt fuer Detailansicht und Admin-Analyse erhalten.
- Healthcheck und Applet lesen nur; Reparatur, Linking, Reconciliation und
  Konfigurationsaenderungen bleiben explizite Aktionen.
- Secrets gehoeren weder in Payloads, Plantexte noch Applet-Ausgaben.
- Uncommittete Benutzerdateien bleiben unangetastet:
  `.obsidian/`, `.stfolder/`, `Fusion_Packliste.txt`, `Unbenannt.base` und
  `Unbenannt.canvas`.

## Ausgangslage

- Ausgangspunkt vor dem aktuellen Fix: `1.9.425`, `2332583e`.
- Aktueller gepruefter Quellstand: `1.9.445`, Commit `27338c58`.
- Der laufende Dienst kann wegen der geltenden 20-Commit-Restart-Regel auf
  einem aelteren Runtime-Stand bleiben; ein automatischer Bot-Restart ist kein
  Bestandteil dieses Bauplans.
- `classification_version=2` trennt actionable Probleme von informativen
  Hinweisen.
- Die Applet- und Python-Aggregation muss sowohl strukturierte Statuszaehler
  als auch deklarative Textfelder wie `problem_statuses` und
  `actionable_problem_statuses` beruecksichtigen.

## Bereits etablierte Statusregeln

1. Nicht-neutrale `error=`-Felder ohne explizites `status=` werden als
   `warning` erkannt; neutrale Fehlerwerte erzeugen keinen falschen Befund.
2. Codex-History-Metadaten mit `failed` oder nicht-terminalen Problemstatus
   bleiben actionable. Reine `queued`-/`skipped`-Hinweise werden nicht zu
   Defekten hochgestuft.
3. API-Budgetfehler werden nur bei einer passenden fehlerhaften Route als
   Duplikat unterdrueckt. Ein verwaister oder widerspruechlicher API-Befund
   bleibt sichtbar.
4. Ein unbekannter Entscheidungsroutenstatus ist ein echter Befund und wird
   nicht durch einen Fallback verdeckt.
5. Fallback-Sentinels wie `none`, `disabled`, `unknown`, `missing` und
   `unconfigured` gelten nicht als Fallback. Ein frueheres explizites
   Deaktivierungsfeld hat Vorrang vor spaeteren Modell- oder Profilfeldern.
6. Status- und Fallbackwerte werden auch mit einfachen, doppelten oder
   Backtick-Quotes normalisiert.
7. Die Gesamtzaehler werden bereits gegen strukturierte Detailzaehler
   abgesichert; ueberlappende Qdrant-Signale werden nicht doppelt gezaehlt.

## Aktueller Befund

Ein v2-Payload kann deklarativ einen schwerwiegenden Status melden, obwohl die
strukturierten Detailzaehler veraltet oder leer sind, zum Beispiel:

```text
actionable_problem_status_count=0
actionable_problem_statuses=broken:1
status_counts={}
actionable_status_counts={}
```

Vor der laufenden Korrektur konnte daraus `status=ok` beziehungsweise
`severe_status_count=0` entstehen. Der Status war damit im Payload vorhanden,
wurde aber bei der Python-Aggregation nicht als Fehlerzaehler verwendet.

## Befund 81: Deklarative v2-Severity wurde ignoriert

Die Python-Aggregation beruecksichtigte deklarative Textfelder bisher nicht
bei der Ermittlung von Gesamt-, actionable- und schweren Problemzaehlern. Ein
staler Detailindex konnte deshalb einen deklarativ gemeldeten `broken`-Status
auf `ok` oder `warning` herabsetzen.

### Umsetzung

- Neuer Parser fuer `status:count`-Listen mit Allowlist der bekannten
  Problemstatus.
- Gesamt-, actionable- und informative Zaehler nehmen jetzt jeweils das
  Maximum aus Integerfeld, strukturierten Zaehlern und deklarativer Statusliste.
- `severe_status_count` beruecksichtigt deklarative actionable Status pro
  Status und bleibt dadurch bei `broken:1` mindestens `1`.
- SemVer-Bump auf `1.9.426`.

### Nachweis

- Fokussierte Regression: `2 passed, 204 deselected in 1.29s`.
- Vollstaendige `tests/test_cinnamon_applet.py`: `206 passed in 42.84s`.
- `git diff --check`: erfolgreich.
- Lokaler Commit: `d76614b8` (`Honor declared health severity statuses`).

## Befund 82: Nicht klassifizierte v2-Problemstatus wurden als gesund behandelt

Auch nach Befund 81 konnte ein widerspruechlicher v2-Payload einen Fehler
enthalten, der weder in den actionable- noch in den informativen Zaehlern
auftauchte. Beispiel: `status_counts=broken:1`,
`problem_statuses=broken:1`, aber beide getrennten Klassifikationen waren leer.
`_health_summary()` vertraute dann auf `actionable_problem_status_count=0` und
lieferte trotz des vorhandenen schweren Problems `status=ok`.

### Umsetzung und Nachweis

- Strukturierte und deklarative Gesamtstatus werden pro Status gegen die
  actionable- und informative Klassifikation abgeglichen.
- Ein nicht abgedeckter Rest wird fail-closed als actionable gewertet; ein
  stale Gesamt-Integer allein wird weiterhin nicht automatisch hochgestuft.
- `broken:1` liefert jetzt `actionable_problem_count=1`,
  `runtime_problem_count=1`, `total_problem_count=1` und
  `severe_status_count=1`.
- Fokussierte Regression: `3 passed, 204 deselected in 1.13s`.
- Vollstaendige `tests/test_cinnamon_applet.py`: `207 passed in 39.57s`.
- `git diff --check`: erfolgreich.
- SemVer `1.9.427`, lokaler Commit `c2a87a32`
  (`Fail closed on unclassified health statuses`).

## Befund 83: Negative Qdrant-Laufzeitzaehler verfaelschten den Gesamtstatus

`qdrant_runtime_problem_count` wurde direkt mit `_safe_int()` gelesen, aber
nicht auf einen nichtnegativen Wert begrenzt. Ein negativer oder fehlerhaft
stale Payloadwert wie `-5` erzeugte dadurch selbst fuenf Runtime-Probleme,
einen negativen Qdrant-Zaehler und faelschlich `status=warning`.

### Umsetzung und Nachweis

- Der Qdrant-Laufzeitzaehler wird jetzt mit `max(0, ...)` normalisiert.
- Negative Werte koennen weder Runtime-, Qdrant- noch Gesamtzaehler erhoehen.
- Regression: `4 passed, 204 deselected in 1.41s`.
- Vollstaendige `tests/test_cinnamon_applet.py`: `208 passed in 45.89s`.
- `git diff --check`: erfolgreich.
- SemVer `1.9.428`, lokaler Commit `79e76b6b`
  (`Clamp qdrant health counters`).

## Befund 84: Gequotete Codex-History-Statuslisten wurden ignoriert

Die Metadatenpruefung fuer `codex_history` und `codex_history_repo` zerlegte
`problem_statuses="failed:1,skipped:2"` ohne die aeusseren Quotes zu entfernen.
Der erste Status wurde dadurch als `"failed` gelesen. Eine neutrale
Primaerzeile konnte einen echten History-Fehler verschweigen; ein quotierter
reiner `queued`/`skipped`-Zustand wurde ebenfalls nicht sicher als Hinweis
klassifiziert.

### Umsetzung und Nachweis

- Gemeinsamer Parser fuer gequotete und ungequotete `status:count`-Listen.
- Healthaggregation, Codex-History-Fehlererkennung und Skip-Unterdrueckung
  verwenden dieselbe Normalisierung.
- Quoted `failed` bleibt actionable; quoted `queued`/`skipped` bleibt
  informativ.
- Fokussierte Codex-/Quoted-Suite: `4 passed, 205 deselected in 1.27s`.
- Vollstaendige `tests/test_cinnamon_applet.py`: `209 passed in 37.78s`.
- `git diff --check`: erfolgreich.
- SemVer `1.9.429`, lokaler Commit `9bf13bf3`
  (`Normalize quoted history status lists`).

## Befund 85: Zaehler und Breakdown-Text konnten auseinanderlaufen

Die fail-closed Ergaenzung aus Befund 82 erhoehte bei einem unklassifizierten
`broken:1` zwar den actionable Zaehler, gab aber weiterhin den leeren
Rohwert `actionable_problem_statuses` aus. Das Applet zeigte damit eine Zahl
ohne die zugehoerige Ursache. Zusaetzlich verwendete die Aggregation fuer
unterschiedliche strukturierte und deklarative Statuslisten nur einen
Gesamt-`max()` und konnte dadurch verschiedene Statusarten unterzaehlen.

### Umsetzung und Nachweis

- Problem-, actionable- und informative Breakdowns werden pro Status mit
  sicheren Maximalwerten zusammengefuehrt.
- Die Healthpayload-Ausgabe wird aus diesen kanonischen Breakdowns erzeugt,
  statt stale Rohtext unveraendert weiterzureichen.
- Ein unklassifiziertes `broken:1` erscheint jetzt sowohl in
  `problem_statuses` als auch in `actionable_problem_statuses`.
- Fokussierte Health-Suite: `4 passed, 205 deselected in 0.21s`.
- Vollstaendige `tests/test_cinnamon_applet.py`: `209 passed in 36.13s`.
- `git diff --check`: erfolgreich.
- SemVer `1.9.430`, lokaler Commit `97a67599`
  (`Canonicalize health status breakdowns`).

## Befund 86: Schwere Sekundaerstatus wurden durch Fallbacks verdeckt

Die Fallback-Sperre pruefte bisher nur den primaeren `status` und
`route_status`. Ein gemischter Datensatz wie
`route_status=unavailable semantic=unknown effective_status=configured
fallback=local_ollama` wurde deshalb komplett als informativer Fallback
behandelt. Der globale Blocker `unknown` verschwand dadurch trotz der
korrekten Sekundaerstatus-Erkennung.

### Umsetzung und Nachweis

- Die Fallback-Sperre prueft jetzt jeden erkannten Problemstatus der Zeile,
  einschliesslich `semantic` und `models_feed`.
- Sobald ein globaler Blocker vorhanden ist, wird die Diagnosezeile
  konservativ actionable klassifiziert.
- Fokussierte Fallback-/Unknown-Suite: `8 passed, 202 deselected in 1.34s`.
- Vollstaendige `tests/test_cinnamon_applet.py`: `210 passed in 36.17s`.
- `git diff --check`: erfolgreich.
- SemVer `1.9.431`, lokaler Commit `fab67610`
  (`Expose blocked secondary health statuses`).

## Befund 87: Gequotete numerische History-Metadaten wurden nicht gelesen

Die Statusnormalisierung behandelte Quotes bei Statusnamen, aber nicht bei
numerischen Feldern. `failed="1"` wurde von `_safe_int()` als ungueltig zu
`0` und damit ein Datensatz `status=skipped failed="1"` als harmloser Skip
behandelt. Ein echter History-Fehler konnte dadurch aus der Healthklassifikation
verschwinden.

### Umsetzung und Nachweis

- `_safe_int()` entfernt jetzt passende einfache, doppelte und Backtick-Quotes
  von Stringzahlen.
- Quoted `failed`, `total` und vergleichbare Metadaten werden konsistent mit
  ungequoteten Werten verarbeitet.
- Fokussierte Zahlen-/Codex-Suite: `3 passed, 208 deselected in 1.02s`.
- Vollstaendige `tests/test_cinnamon_applet.py`: `211 passed in 45.66s`.
- `git diff --check`: erfolgreich.
- SemVer `1.9.432`, lokaler Commit `ca5a1bdd`
  (`Normalize quoted numeric health metadata`).

## Befund 88: Informations-Sonderregeln konnten Health-Blocker ueberstimmen

Die Klassifikation behandelte `fallback_defaults`, partielle Codex-Usage,
bekannte Identity-Warnings und bestimmte History-/API-Zustaende direkt als
informativ. Diese Sonderregeln hatten Vorrang, wenn dieselbe Zeile zusaetzlich
einen blockierenden Sekundaerstatus wie `semantic=unknown` trug. Dadurch wurde
ein unbekannter Zustand trotz globaler Blocker-Allowlist als Hinweis behandelt.

### Umsetzung und Nachweis

- Alle Informations-Sonderregeln laufen jetzt nur noch, wenn kein erkannter
  Problemstatus ein Fallback-Suppression-Blocker ist.
- Gemischte Zeilen werden konservativ actionable klassifiziert, sodass der
  schwere Teil nicht durch eine Hinweis-Sonderregel verschwindet.
- Fokussierte Fallback-/Sonderfall-Suite: `9 passed, 203 deselected in 1.25s`.
- Vollstaendige `tests/test_cinnamon_applet.py`: `212 passed in 37.68s`.
- `git diff --check`: erfolgreich.
- SemVer `1.9.433`, lokaler Commit `7770e52a`
  (`Let health blockers override informational rules`).

## Befund 89: Unbekannte History-Skip-Gruende wurden als Hinweis verborgen

Eine `codex_history_repo`-Zeile mit `problem_statuses=skipped:1` wurde auch
dann als rein informativ klassifiziert, wenn `skip_reasons=unknown:1` oder
malformierte Reason-Tokens vorlagen. Damit konnte ein fehlender oder kaputter
Dispatcher-Grund genauso aussehen wie der bekannte terminale Grund
`no_private_route`.

### Umsetzung und Nachweis

- Die Informationsregel erlaubt jetzt nur noch den belegten terminalen Grund
  `no_private_route`.
- Unbekannte, nicht erlaubte und syntaktisch ungueltige Skip-Grundlisten
  werden fail-closed als actionable `warning` behandelt.
- Regressionstest deckt `unknown`, `no_private_route` und malformed gemischt
  ab: `3 passed, 210 deselected in 1.04s`.
- Vollstaendige `tests/test_cinnamon_applet.py`: `213 passed in 42.72s`.
- `git diff --check`: erfolgreich.
- SemVer `1.9.434`, lokaler Commit `b910dbc5`
  (`Expose unknown history skip reasons`).

## Befund 90: Installierte Applet-Kopie war hinter dem Quellstand

Der echte Python-Statuspayload war konsistent, aber die laufende Cinnamon-Installation
verwendete eine aeltere `applet.js`. Die installierte Kopie enthielt weder die
aktuelle Fehlerflag-Klassifikation noch die robuste v2-Health-Zaehllogik. Damit
konnte das Applet einen korrekten Payload veraltet oder irrefuehrend anzeigen.

### Umsetzung und Nachweis

- `scripts/install_cinnamon_applet.py` erneut ausgefuehrt und die lokale Kopie
  unter `~/.local/share/cinnamon/applets/teebotus@H234598` aktualisiert.
- Repo- und Installationskopie stimmen jetzt bytegenau ueberein:
  SHA-256 `ad336e8570b8a4d6aa49a874dd01bb5f4e3de924780b2cfd5f5577c1a5ab5183`.
- Echter Python-Payload: `version=1.9.434`, `health=warning`,
  `actionable=missing_key:1,warning:2`, `total=3`.
- Derselbe Payload wird vom aktuellen JavaScript-Validator akzeptiert:
  `valid=true`.
- Cinnamon-Applet ueber `org.Cinnamon.ReloadXlet` neu geladen; kein Bot- oder
  Service-Restart ausgefuehrt.

## Befund 91: Explizite Fehler wurden von Fallback-Hinweisen verdeckt

Die Informations-Sonderregeln fuer bekannte Identity-Warnings, terminale
Codex-History-Skips, strukturierte Entscheidungs-Fallbacks und allgemein
abgedeckte Fallback-Routen prueften bisher nicht, ob dieselbe Diagnosezeile
zusaetzlich ein nicht-neutrales `error=` enthielt. Dadurch konnte zum Beispiel
`status=warning identity_warnings=1 error=doctor_failed` als reiner Hinweis
oder `route_status=unavailable fallback=local error=provider_failed` als
erfolgreich abgefangener Fallback erscheinen.

### Umsetzung und Nachweis

- `_line_health_statuses()` merkt sich pro Zeile, ob ein echtes `error=`
  vorhanden ist, ohne die bestehenden Rohstatuszaehler zu veraendern.
- Identity-, Codex-History-Repo-, strukturierte Entscheidungs- und generische
  Fallback-Sonderregeln stufen solche Zeilen jetzt actionable ein.
- Der absichtlich informative `gemini_free_tier_limits`-Defaultbefund und die
  deduplizierte API-Budget-Sonderregel bleiben unveraendert.
- Regression mit allen betroffenen Sonderfaellen: `5 passed, 209 deselected`.
- Vollstaendige `tests/test_cinnamon_applet.py`: `214 passed in 39.92s`.
- `git diff --check`: erfolgreich.
- SemVer `1.9.435`, lokaler Commit `97513246`
  (`Keep explicit health errors actionable`).
- Kein Push und kein Bot-/Service-Restart ausgefuehrt.

Der aktuelle Live-Payload bleibt damit transparent bei
`actionable=missing_key:1,warning:2`: Das sind derzeit der fehlende
`OPENAI_API_KEY`-Zugang fuer `hard_reasoning`, die nicht verknuepfte
Depressionsbot-Signal-Identitaet und der nicht abgearbeitete TBL-History-
Rueckstand. Diese drei Befunde werden nicht still als Fallback-Hinweise
versteckt und sind die naechsten separaten Reparaturthemen.

## Befund 92: Verifizierte Fallback-Fehler wurden als Handlungsprobleme gezaehlt

Die Korrektur aus Befund 91 war fuer echte, ungeklaerte Fehler notwendig, war
aber fuer bereits verifizierte Fallback-Routen zu streng. Eine Zeile wie
`status=missing_key effective_status=configured fallback=local error=missing`
oder `status=unavailable effective_status=configured fallback=local
error=HFPoolUnavailable` beschreibt einen ausgefallenen Primaerweg mit
funktionierendem Ersatz. Sie wurde trotzdem als Top-Level-Problem gezahlt,
weil allein das technische `error=` die Informationsregel blockierte.

### Umsetzung und Nachweis

- Ein Fallback gilt mit Fehler nur dann als informational, wenn
  `effective_status` gesund ist, eine echte Fallback-Referenz existiert und
  `status` oder `route_status` einen bekannten Problemstatus des
  Primaerweges benennt.
- `unknown`, `broken`, `config_conflict`, `failed`, `invalid` und
  `schema_mismatch` bleiben durch die Blocker-Allowlist actionable.
- Ein Fallback ohne gesunden `effective_status` bleibt actionable; die
  Existenz eines Fallback-Feldes allein beweist keine funktionierende
  Ersatzroute.
- Identity-, Codex-History- und sonstige explizite Sonderfehler bleiben
  handlungsrelevant, solange sie nicht durch genau diese verifizierte
  Routenabdeckung belegt sind.
- Regression fuer verifizierte, unverifizierte und blockierte Fallbacks:
  `2 passed, 213 deselected`.
- Vollstaendige `tests/test_cinnamon_applet.py`: `215 passed in 46.34s`.
- Lesende Live-Probe danach: `actionable=missing_key:1,warning:2`,
  `informational=23`, Qdrant `0` Probleme.
- SemVer `1.9.436`, lokaler Commit `8dc23e83`
  (`Classify verified fallback errors as informational`).
- Kein Push und kein Bot-/Service-Restart ausgefuehrt.

## Befund 93: Skips ohne Begruendung wurden als harmlose Hinweise behandelt

`_codex_history_skip_reasons_are_informational()` gab bei einer leeren
`skip_reasons`-Angabe bisher `True` zurueck. Damit konnte eine
`codex_history_repo`-Zeile mit `skipped>0` und unbekannter Ursache als
informativer Hinweis erscheinen. Das widersprach der fail-closed-Regel, nach
der nur der bekannte terminale Grund `no_private_route` informativ sein darf.

### Umsetzung und Nachweis

- Eine leere Skip-Grundliste bleibt nur bei einer reinen `queued`-Zeile ohne
  Skips informativ.
- `skipped>0` ohne Grund wird als actionable `warning` klassifiziert.
- `no_private_route` bleibt als bekannter terminaler Skip informativ.
- Bestehende Testfixtures wurden fuer begruendete Skips explizit mit
  `skip_reasons=no_private_route:N` versehen.
- Regression fuer fehlenden, reinen queued- und bekannten Skip-Grund:
  `4 passed, 212 deselected`.
- Vollstaendige `tests/test_cinnamon_applet.py`: `216 passed in 46.70s`.
- Live-Probe bleibt stabil bei `actionable=missing_key:1,warning:2` und
  Qdrant ohne Probleme.
- SemVer `1.9.437`, lokaler Commit `1f2eefdc`
  (`Expose history skips without reasons`).
- Kein Push und kein Bot-/Service-Restart ausgefuehrt.

## Befund 94: History-Detail zeigte nicht den schwersten Befund

Die Parseraggregation ersetzte eine bereits gefundene problematische
`codex_history=`-Zeile nur dann, wenn vorher noch kein Problem gesehen worden
war. Stand zuerst eine `warning`-Zeile und spaeter eine `broken`-Zeile im
Runtime-Output, blieb die Warnung im Detailtext des Applets stehen. Die
Gesamtzaehler konnten dabei bereits den schwereren Status enthalten; Anzeige
und Zaehler waren damit widerspruechlich.

### Umsetzung und Nachweis

- History-Detailzeilen erhalten jetzt eine deterministische Statusprioritaet.
- Ein spaeterer schwererer Status ersetzt den bisherigen Detailkandidaten;
  gleich schwere Kandidaten bleiben in stabiler Eingabereihenfolge.
- Die Rohzeilen, Gesamtzaehler und Actionable-/Info-Klassifikation bleiben
  getrennt erhalten.
- Regression fuer gesund -> Problem und warning -> broken:
  `6 passed, 211 deselected`.
- Vollstaendige `tests/test_cinnamon_applet.py`: `217 passed in 38.03s`.
- Live-Probe: `actionable=missing_key:1,warning:2`, Qdrant ohne Probleme;
  TBL-Detail zeigt weiterhin die aktuelle problematische Aggregatezeile.
- SemVer `1.9.438`, lokaler Commit `a6bdbaf8`
  (`Prefer severe history health details`).
- Kein Push und kein Bot-/Service-Restart ausgefuehrt.

## Umsetzung

### 1. Deklarative Statusfelder auswerten

Die Aggregation erhaelt einen gemeinsamen Parser fuer die Textform
`status:count`. Er akzeptiert nur bekannte Problemstatus und positive
Zaehler. Ungueltige Token werden ignoriert, ohne einen gesunden Zustand zu
erfinden.

Die folgenden Maximalwerte werden danach zusammengefuehrt:

- Gesamtprobleme: deklarierter Integer, strukturierte Statuszaehler und
  `problem_statuses`.
- Actionable Probleme: deklarierter Integer, strukturierte actionable
  Statuszaehler und `actionable_problem_statuses`.
- Informative Probleme: deklarierter Integer, strukturierte informative
  Statuszaehler und `informational_problem_statuses`.
- Schwere Probleme: pro Status der groessere Wert aus strukturiertem und
  deklarativem actionable Zaehler.

### 2. Regressionstest

Ein Test muss den oben genannten widerspruechlichen v2-Payload reproduzieren
und mindestens folgende Ergebnisse erzwingen:

- `status == "broken"`
- `actionable_problem_count == 1`
- `runtime_problem_count == 1`
- `total_problem_count == 1`
- `severe_status_count == 1`

Ergaenzend bleiben die bisherigen Tests fuer stale Gesamtzaehler, quoted
Statuswerte, Fallback-Sentinels, API-Budgetduplikate, Codex-History und
Qdrant-Doppelzaehlung gruen.

### 3. Erledigte Verifikation

- SemVer auf `1.9.426` erhoeht.
- `git diff --check` erfolgreich ausgefuehrt.
- Fokussierter und vollstaendiger Testlauf erfolgreich ausgefuehrt.
- Code, Test und Version lokal als `d76614b8` committed.
- Dieser Plan wird nach der Aktualisierung separat committed.
- Kein `git push`, solange dies nicht ausdruecklich angefordert wird.
- Kein Bot-/Service-Restart ausserhalb der vereinbarten 20-Commit-Grenze.

## Weiterfuehrende Arbeit nach diesem Fix

1. Die Signal-Identitaet des Depressionsbots ausschliesslich ueber den
   bestaetigten Linking-Flow verknuepfen und danach lesend pruefen.
2. TBL-History-Rueckstand mit Dry-Run, Dedupe-Key, Empfaengerresultaten und
   `no_private_route` getrennt analysieren. Kein stilles Loeschen oder Requeue.
3. Nach einer Applet-Aenderung Quellkopie und installierte Kopie vergleichen
   und nur das Applet reloaden, wenn sich dessen Code tatsaechlich geaendert
   hat.
4. Erst nach Tests, Live-Probe, Version-/Commit-Nachweis und geklaerten offenen
   Befunden den Plan abschliessen.

## Befund 95: Gequotete Status- und Zahlenwerte waren im Applet nicht parity

Python entfernt aeussere Quotes vor der Healthklassifikation, das Applet-
JavaScript tat dies bei `route_status`, Problemflags und numerischen
Stale-/Zaehlerfeldern nicht. Ein gequoteter `unknown`-Status konnte deshalb in
der Detailansicht normal erscheinen, obwohl Python denselben Befund als
actionable meldete.

### Umsetzung und Nachweis

- Gemeinsamer `_stripOuterStatusQuotes`-Helper im Applet fuer Statusflags,
  Problemstatus und strikte Integerwerte.
- Regression fuer `route_status="unknown"`, `stale_hours="24"`,
  `"12"` und `"warning"`.
- Vollstaendige Applet-Suite: `218 passed in 44.40s`.
- Installierte Applet-Kopie byte-identisch zur Quelle.
- SemVer `1.9.439`, Commit `bfd641a8` (`Normalize quoted applet health values`).

### Live-Ergebnis

Die aktuelle Live-Probe hat zwei actionable Befunde: `hard_reasoning` ohne
generischen Key und die fehlende Signal-Identitaetsverknuepfung bei
Depressionsbot. Der lokale TBL-History-Rueckstand bleibt sichtbar, ist bei
expliziter `queued`/`skipped`- und `no_private_route`-Begruendung aber nur noch
informational. Qdrant ist gesund; der zentrale Dispatcher meldet Queue `0`.

## Befund 96: Erklaertes History-Aggregat nicht doppelt als actionable zaehlen

Die Healthparser-Details behandelten `queued` und `no_private_route` bereits
als informativ. Die aggregierte TBL-Zeile tat das nicht. Das wurde mit einer
fail-closed Aggregatregel korrigiert: Erst ein explizites
`problem_statuses=queued:...,skipped:...` zusammen mit ausschliesslich
`skip_reasons=no_private_route:...` darf informational werden. Unvollstaendige
oder unbekannte Metadaten bleiben actionable.

Nachweis: `8 passed, 212 deselected` fokussiert und `220 passed in 36.27s`
vollstaendig; SemVer `1.9.440`, Commit `13eed576`. Der laufende Dienst ist noch der alte Prozess,
daher steht der Live-Nachweis nach dem naechsten erlaubten Reload noch aus.

## Befund 97: v2-Health ohne Klassifikationsfelder muss fail-closed bleiben

Das Applet vertraute bei `classification_version=2` auf den deklarierten
Gesamtzähler. Bei `total_problem_count=0` und fehlenden Action-/Infofeldern
konnten gleichzeitig vorhandene Rohwerte aus `runtime.status_counts` verloren
gehen. Der neue Fallback verwendet diese Rohwerte nur dann, wenn die v2-
Klassifikation wirklich fehlt; explizite Informationsfelder behalten Vorrang.

Nachweis: `4 passed, 217 deselected`, danach `221 passed in 33.45s`; SemVer
`1.9.441`, Commit `ccb511cc`; installierte Applet-Kopie byte-identisch.

## Befund 98: Quoted Breakdown-Werte muessen wie Python normalisiert werden

Bei gequoteten `problem_statuses`-Strings konnte das Applet die erste und
letzte Statuskennung mit Quote anreichern. Der neue Pfad strippt aeussere
Quotes und normalisiert Statusnamen vor Darstellung, Count und v2-Fallback.

Nachweis: `5 passed, 217 deselected` fokussiert und `222 passed in 33.33s`
vollstaendig; SemVer `1.9.442`, Commit `3896e7c3`; Applet-Kopie
byte-identisch installiert.

## Befund 99: LiteLLM-OpenAI-Instanzschluessel wurden als fehlend gemeldet

Die Runtime verwendete fuer `hard_reasoning` `provider=litellm` mit
`openai/gpt-5.5`. Obwohl `OPENAI_API_KEY_<INSTANCE>` gesetzt war, prueften
Account- und Routenstatus nur den generischen `OPENAI_API_KEY`-Namen.

### Umsetzung und Nachweis

- LiteLLM-OpenAI-Routen verwenden jetzt die instanzbezogene
  OpenAI-Keyaufloesung.
- Accountstatus, Route und API-Budgetstatus sind damit konsistent.
- `key_scope=instance_fallback` ist nicht geheim und im Applet als
  `instanzbezogener Fallback` sichtbar.
- `359 passed in 86.82s` in der vollstaendigen Kompatibilitaets- und
  Applet-Suite.
- Applet-Installation und Quellvergleich: byte-identisch.
- Live-Probe: actionable nur noch `warning:1` fuer die nicht verknuepfte
  Depressionsbot-Signal-Identitaet.
- SemVer `1.9.443`, Commit `2fd7bf6d`.

## Befund 100: Diagnose und Request-Pfad verwendeten unterschiedliche Keys

Der Healthcheck erkannte den instanzbezogenen OpenAI-Key bereits, die
Runtime-Factory verwendete beim Bau des LiteLLM-Clients jedoch weiterhin nur
den globalen Variablennamen. Das konnte eine gruene Diagnose mit einem leeren
echten Request-Key erzeugen.

### Umsetzung und Nachweis

- Profil- und Purpose-Routen loesen den instanzbezogenen OpenAI-Key jetzt vor
  dem globalen Key auf.
- Nicht-OpenAI-Routen erhalten diese Sonderbehandlung nicht.
- Router: `60 passed in 1.95s`.
- Factory-/Fallback-/Proactive-Tests: `50 passed in 1.86s`.
- Direkter Client-Probe erfolgreich; kein Provideraufruf.
- SemVer `1.9.444`, Commit `50278e3d`.

## Befund 101: Exportierter Profil-Builder blieb hinter dem Runtime-Builder

Der oeffentlich exportierte `build_profiled_text_llm_client` hatte keinen
Instanzkontext und las fuer OpenAI-Profile nur den globalen Key. Dadurch
blieb dieser Pfad hinter der Runtime-Factory zurueck.

### Umsetzung und Nachweis

- Gemeinsame `resolve_profile_api_key`-Logik fuer beide Builder.
- Optionales `instance_name` ergaenzt, ohne bestehende Aufrufer zu brechen.
- `68 passed in 1.97s` in Router- und Package-Suite.
- Direkter Profil-Builder-Test mit Instanz-vor-Global-Prioritaet gruen.
- SemVer `1.9.445`, Commit `27338c58`.

## Befund 102: Healthcheck- und Request-Key konnten auseinanderlaufen

Die Runtime-Konfiguration konnte einen kanal-/slot-spezifischen Key bereits
korrekt bestimmen. Die Factory ersetzte ihn anschliessend mit dem weniger
spezifischen Instanz-Key aus dem Profil. Der Healthcheck konnte dadurch
`configured` melden, obwohl der Request-Pfad einen anderen Key verwendete.

### Umsetzung und Nachweis

- Beide Runtime-Factory-Pfade bewahren jetzt den bereits aufgeloesten
  `default_api_key` vor dem Profil-Fallback.
- Explizite Overrides bleiben vorrangig; Nicht-OpenAI-Routen bleiben getrennt.
- Vier fokussierte Key-Prioritaetsregressionen und die Router-/Package-Suite
  sind gruen; Gesamt mit Metadaten: `76 passed in 1.96s`.
- Read-only-Runtime-Probe bestaetigt `hard_reasoning ... configured` und
  `key_scope=instance_fallback` ohne Provideraufruf.
- SemVer `1.9.446`, Commit `b877409f`.

## Befund 103: Fallback-Key war nicht instanzbezogen

Der Healthcheck konnte die Primaerroute mit einem Instanz-Key als konfiguriert
anzeigen, waehrend ein OpenAI-Fallback nur den globalen Keynamen las. Dadurch
war der Request-Fallback in derselben Instanz ohne Key.

### Umsetzung und Nachweis

- Runtime- und exportierter Profil-Builder verwenden fuer OpenAI-Fallbacks
  nun denselben Instanz-vor-Global-Resolver.
- Lokale HF-Pool-Fallback-Regressionen fuer beide Builder sind gruen.
- Router-, Package-, HF-Fallback-, Proactive- und Metadaten-Suite:
  `128 passed in 3.88s`.
- SemVer `1.9.447`, Commit `bdf427b4`.

## Befund 104: Modellpraefix und OpenAI-Key-Scope waren uneinheitlich

Das Routing akzeptierte ein unpraefixiertes LiteLLM-Modell als remote, waehrend
die Key-Aufloesung nur `openai/...` als OpenAI-Signal verwendete. Dadurch
konnten Status-/Requestpfad bei einem OpenAI-Fallback auseinanderlaufen.

### Umsetzung und Nachweis

- `api_key_env=OPENAI_API_KEY` ist nun ein zusaetzliches, explizites
  OpenAI-Signal fuer die Resolverlogik.
- Die Instanz-vor-Global-Prioritaet bleibt dabei erhalten.
- Unpraefixierter OpenAI-Fallback und die betroffene Suite sind gruen:
  `128 passed in 3.37s`.
- SemVer `1.9.448`, Commit `de5bc5a6`.

## Befund 105: Statusaggregation war nicht keyvertragsgleich zur Factory

Die Factory erkannte OpenAI-Kompatibilitaet bei explizitem
`OPENAI_API_KEY`-Env auch ohne `openai/`-Modellpraefix. Der Statuspfad tat das
nicht und meldete fuer einen vorhandenen Instanz-Key einen falschen Fehler.
OpenAI-Fallbacks wurden im Status ebenfalls nur gegen den globalen Key
geprueft.

### Umsetzung und Nachweis

- Statusklassifikation und Darstellung teilen jetzt das OpenAI-Env-Signal mit
  dem Resolver.
- Fallback-Status prueft `OPENAI_API_KEY_<INSTANCE>` vor `OPENAI_API_KEY`.
- Drei neue providerfreie Statusregressionen und die relevante Gesamtsuite
  sind gruen; LLM-Suite: `128 passed in 3.80s`.
- SemVer `1.9.449`, Commit `25151c00`.

## Befund 106: Structured-Decision-Status verlor den Instanz-Key-Kontext

Die `structured_decision`-Statuszeile pruefte die Route ohne den Namen der
aktuellen Instanz. Dadurch wurde ein vorhandener
`OPENAI_API_KEY_<INSTANCE>`-Fallback nicht beruecksichtigt, obwohl die
allgemeine LLM-Statuszeile denselben Key korrekt fand.

### Umsetzung und Nachweis

- Der Structured-Decision-Status verwendet jetzt dieselbe
  instanzbezogene Route-Key-Pruefung wie der restliche Statuspfad.
- Providerfreier Repro und Regression fuer `OPENAI_API_KEY_DEMO` sind gruen.
- Entrypoint-Suite: `139 passed in 42.61s`; `git diff --check` und
  `compileall` gruen.
- SemVer `1.9.450`, Commit `d29b8a4c`.

## Befund 107: `route_error` wurde vom Applet-Healthparser ignoriert

Die Parserlogik behandelte nur `error=...` als Fehlertext. Die
per-Account-Structured-Decision meldet die Ursache aber als
`route_error=...`. Damit konnte `route_status=unavailable` trotz fehlendem
Nachweis eines funktionierenden Fallbacks in den informationalen Bereich
fallen.

### Umsetzung und Nachweis

- `_line_has_error()` wertet jetzt beide Fehlerfelder aus.
- Regression fuer `route_error` ohne `effective_status` ist gruen.
- Applet-Suite: `224 passed in 36.13s`.
- Live-Parser: `unavailable:5` actionable fuer die fuenf betroffenen Slots;
  vorhandene `effective_status=configured`-Fallbacks bleiben informational.
- SemVer `1.9.451`, Commit `7eb2efa3`.

## Befund 108: Fallback-Effektivitaet fehlte in per-Account-Zeilen

`structured_decision` zeigte bei einem deaktivierten HF-Pool zwar den lokalen
Fallbacknamen, aber keinen Status des Fallbackprofils. Die Appletlogik konnte
deshalb nicht zwischen einem belegten und einem nur behaupteten Fallback
unterscheiden.

### Umsetzung und Nachweis

- Neue providerfreie Fallback-Statusauflösung in `bot.py` verwendet Profil,
  Modell, Base-URL und Instanz-Key-Scope.
- `effective_status=configured` wird pro Account ausgegeben, wenn der lokale
  Fallback konfiguriert ist; kaputte oder fehlende Fallbacks bleiben sichtbar.
- Entrypoint-Suite: `140 passed in 44.13s`; Applet-Suite: `225 passed in
  36.26s`; Live-Probe ohne Provideraufruf gruen.
- SemVer `1.9.452`, Commit `34729c1b`.

## Befund 109: Fallback-/Offload-Fehler wurden nicht als Fehler erkannt

Die Statusausgabe kann neben `error` auch `fallback_error` und
`offload_error` enthalten. Beide Felder wurden vom Parser nicht als
Fehlerindikator ausgewertet, wodurch die Fallback-Sonderlogik einen defekten
effektiven Pfad verschleiern konnte.

### Umsetzung und Nachweis

- Beide Felder sind jetzt Freitext-Statusfelder mit korrekten Grenzen.
- `_line_has_error()` wertet sie gemeinsam mit `error` und `route_error` aus.
- Regression fuer `effective_status=broken fallback_error=...` ist gruen;
  vollstaendige Applet-Suite: `226 passed in 35.69s`.
- SemVer `1.9.453`, Commit `417ef2ad`.

## Befund 110: Python und JS ignorierten `effective_status`

Die Statusaggregation kann eine effektive Route als `degraded` oder `broken`
melden. Dieses Feld fehlte jedoch in `SECONDARY_PROBLEM_STATUS_FIELDS`; die
Python- und JS-Parser konnten eine solche Verschlechterung nicht als Problem
zaehlen.

### Umsetzung und Nachweis

- `effective_status` ist in beiden Parsern als sekundares Problemfeld
  registriert.
- Regression deckt `status=configured effective_status=degraded` ab.
- Python-/JS-Konstanten sind synchron; Applet-Suite: `227 passed in 34.09s`.
- `node --check files/teebotus@H234598/applet.js` erfolgreich.
- SemVer `1.9.454`, Commit `a11e716a`.

## Befund 111: Status-/Preflight-Secretprovider nutzte keine Runtime-Retries

Die Applet-Statusausgabe kann mehrere Account- und History-Pruefungen in einem
Lauf ausfuehren. Die gemeinsame Providerinstanz wurde aber ohne die globale
Runtime-Retry-Policy angelegt; Secret-Service-Transienten wurden dadurch nicht
abgefangen.

### Umsetzung und Nachweis

- `bot.py` bezieht den gemeinsamen read-only Provider jetzt aus
  `runtime_secret_provider()`.
- Der Providercache bleibt pro Statuslauf geteilt; Erstellung neuer Secrets
  bleibt deaktiviert.
- Entrypoint-Suite: `141 passed in 42.41s`; Live-History danach `status=ok`.
- SemVer `1.9.455`, Commit `bc3941c7`.

## Befund 112: Status-Provider hatten eine andere Secret-Service-Policy

Mehrere Python-Statushelfer erzeugten den read-only Secret-Service-Provider
direkt ohne Runtime-Retries. Damit konnte der Python-Healthpayload bei einem
transienten Lookupfehler `unknown` oder einen Storefehler melden, waehrend der
Runtimepfad denselben Secretzugriff noch erfolgreich wiederholen konnte. Das
fuehrte zu einem moeglichen falschen oder flackernden Healthcheck im Applet.

### Umsetzung und Nachweis

- `TeeBotus/core/status.py` nutzt jetzt eine gemeinsame
  `_status_secret_provider()`-Factory mit der Runtime-Konfiguration fuer
  Retries, Delay und Timeout.
- Der Appletvertrag bleibt unveraendert: keine Secrets werden ausgegeben und
  keine fehlenden Secrets angelegt.
- Providerfreier Regressionstest bestaetigt `create_if_missing=False` und die
  env-gesteuerten Werte.
- Entrypoint-Suite: `142 passed`.
- Vollstaendige Status-/Version-Suite: `215 passed`.
- Live-Appletstatus: `status=warning`, actionable `warning:1`,
  informational `23`; der einzige actionable Befund ist die fehlende
  Signal-Identitaet fuer den Depressionsbot.
- Die lokale Installation wurde mit `scripts/install_cinnamon_applet.py`
  aktualisiert; Quell- und Installationskopie sind byte-identisch.
- `node --check files/teebotus@H234598/applet.js`: erfolgreich.
- SemVer `1.9.456`, Codecommit `893899eb`.

## Befund 113: Unbekannte Breakdown-Status wurden im Applet mitgezaehlt

`_problemBreakdownCount()` und `_problemBreakdownText()` im Applet prueften
bisher nur die Zahl, nicht die Status-Allowlist. Dadurch konnte ein unbekannter
Status wie `bogus:999` den Healthheader als grosser Fehler erscheinen lassen,
waehrend Python denselben Status ignorierte.

### Umsetzung und Nachweis

- Beide JS-Helfer filtern jetzt gegen `PROBLEM_STATUSES`.
- Python und JS verwenden damit dieselbe Statussemantik fuer Breakdown-Text
  und Zaehler.
- Fokussierte Regression: `2 passed`.
- Vollstaendige Applet-Suite: `228 passed`.
- `node --check files/teebotus@H234598/applet.js`: erfolgreich.
- SemVer `1.9.457`, Codecommit `f8e3881e`.

## Befund 114: Teilklassifikation machte informative Warnungen actionable

Die JS-Seite behandelte bereits jedes v2-Klassifikationsfeld als Nachweis.
Python verwendete dagegen nur den actionable Zaehler und setzte bei dessen
Fehlen den gesamten Rohproblemzaehler als actionable an. Dadurch konnten
partielle, rein informative Payloads im Header falsch als Warnung erscheinen.

### Umsetzung und Nachweis

- Python und JS erkennen v2 jetzt ueber dieselben vier Klassifikationsfelder.
- Fehlt bei vorhandenem v2-Nachweis der actionable-Zaehler, wird nur die
  explizite actionable-Liste verwendet.
- Fokussierte Regression: `5 passed`.
- Vollstaendige Applet-Suite: `229 passed`.
- SemVer `1.9.458`, Codecommit `4285217b`.

## Befund 115: Admin-Healthcheck-Fallback umging Secret-Service-Retries

Die Applet-Statuskette kann Admin-Gruppen separat auswerten. Deren
`_default_account_store()` verwendete bisher keine Runtime-Retry-Policy,
obwohl der gemeinsame Botpfad bereits eine besass. Dadurch blieb ein
transienter Secret-Service-Fehler als moeglicher falscher Healthbefund.

### Umsetzung und Nachweis

- Der Admin-Healthcheck nutzt jetzt die zentrale read-only
  `runtime_secret_provider()`-Factory.
- Der Manifest-Guard und die Fail-Closed-Eigenschaften bleiben unveraendert.
- Admin-Account-Suite: `27 passed`; Entrypoint-Suite: `142 passed`.
- SemVer `1.9.459`, Codecommit `26688145`.

## Befund 116: Codex-History-Statuspfade nutzten eigene Secret-Defaults

Mehrere Standalone-Historypfade verwendeten den einfachen read-only Provider
statt der Runtime-Factory. Damit fehlten Retry-Policy und Manifest-Guard,
obwohl der normale Appletstatus bereits zentral versorgt wurde.

### Umsetzung und Nachweis

- Report, Watch, Index und Dispatch verwenden bei fehlendem explizitem
  Provider jetzt `runtime_secret_provider()`.
- Codex-History-Suite: `130 passed`; zusammen mit Runtime-Admin `157 passed`.
- SemVer `1.9.460`, Codecommit `65126428`.

## Befund 117: Recovery-Provider konnte bei Secret-Service-Transienten scheitern

Der Recoverypfad braucht bewusst einen toleranten Provider ohne Manifest-Guard,
damit kaputte oder alte Verschluesselungen diagnostizierbar bleiben. Dieser
Provider lief jedoch ohne Timeout und Wiederholungen.

### Umsetzung und Nachweis

- Normale Admin-Reports nutzen die zentrale Runtime-Policy.
- Der Recovery-Provider nutzt nun dieselben Retry-/Delay-/Timeoutwerte, ohne
  seine diagnostische read-only Semantik zu verlieren.
- Admin-/Recovery-Suite: `63 passed`.
- Entrypoint-/Status-Suite: `357 passed`.
- SemVer `1.9.461`, Codecommit `78e2806a`.

## Invarianten

- Ein echter Fehler wird nicht durch einen Fallback, einen leeren Queue-Zustand
  oder einen stale Gesamtzaehler unsichtbar.
- Ein unbekannter Status wird nicht als Erfolg klassifiziert.
- Terminale Zustellungen und begruendete Skips werden nicht endlos erneut
  versendet.
- Healthcheck und Applet zaehlen denselben Zustand nicht mehrfach, verlieren
  aber keine deklarativ gemeldete Statusart.
- Diagnose bleibt lesend und veraendert keine Memories, Outboxen oder Secrets.

## Abschlusskriterien

Der Bauplan bleibt aktiv, bis:

- der deklarative `broken:1`-Regressionsfall gruen getestet ist (erledigt),
- die vollstaendige Applet-Suite ohne Provideraufrufe gruen ist (erledigt),
- Version und Commit im Plan dokumentiert sind (erledigt),
- der aktuelle Live-/Installationsstand nachvollziehbar abgeglichen wurde,
- die offenen Healthbefunde entschieden und mit Nachweis dokumentiert sind.
