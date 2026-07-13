# Bauplan: Healthcheck-Applet und Statusaggregation

**Stand:** 2026-07-13  
**Status:** Aktiv, noch nicht abgeschlossen  
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
- Aktueller gepruefter Quellstand: `1.9.426`, `d76614b8`.
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

1. `hard_reasoning` konfigurationsseitig bewusst klaeren: echter Key oder
   expliziter lokaler Fallback.
2. Die Signal-Identitaet des Depressionsbots ausschliesslich ueber den
   bestaetigten Linking-Flow verknuepfen und danach lesend pruefen.
3. TBL-History-Rueckstand mit Dry-Run, Dedupe-Key, Empfaengerresultaten und
   `no_private_route` getrennt analysieren. Kein stilles Loeschen oder Requeue.
4. Nach einer Applet-Aenderung Quellkopie und installierte Kopie vergleichen
   und nur das Applet reloaden, wenn sich dessen Code tatsaechlich geaendert
   hat.
5. Erst nach Tests, Live-Probe, Version-/Commit-Nachweis und geklaerten offenen
   Befunden den Plan abschliessen.

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
