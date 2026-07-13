# Bauplan: Aktueller Plan fuer Bridge-Reconciliation und Health-Status

**Stand:** 2026-07-13
**Status:** Aktiv, noch nicht abgeschlossen
**Uebernommen aus:** Bauplaene/Aktueller-Plan-Logikpruefung-Codex-History.md
**Geltungsbereich:** Codex-History, SQL-Outbox, History-Dispatcher, Bridge-Modus, /status, Healthcheck und TeeBotus-Cinnamon-Applet

## Zweck dieses Plans

Dieser Bauplan ist eine neue, aktuelle Arbeitskopie des laufenden
Logikpruefungsplans. Die bereits dokumentierten Befunde bleiben in den
bestehenden Planaufnahmen erhalten. Dieser Plan fuehrt die noch offene Arbeit
ab dem aktuellen Produktionsbefund weiter.

## Ziel

Die Codex-History- und Health-Logik soll fachlich konsistent, idempotent,
fail-closed und nachvollziehbar sein. Lokale und zentrale Outbox duerfen nicht
auseinanderlaufen, ohne dass der Zustand sichtbar wird. Ein terminaler Erfolg
darf nicht erneut versendet werden; echte Fehler und nicht zustellbare Skips
muessen in SQL, /status, Healthcheck und Applet dieselbe Bedeutung haben.

## Sicherheits- und Arbeitsregeln

1. Keine automatische Loeschung, kein stilles Requeue und keine Secret-Ausgabe.
2. Lokale Outbox-Zeilen bleiben erhalten, bis ein zentraler Status sie bestaetigt.
3. Mirror und Reconciliation muessen ueber ID oder deterministischen Dedupe-Key
   idempotent sein.
4. Dry-Run bleibt strikt nicht mutierend und muss geplante Nachfuehrungen
   sichtbar ausweisen.
5. Produktionsdaten werden erst nach isolierten Tests und einer lesenden Probe
   veraendert.
6. Kein kostenpflichtiger LLM- oder Provider-Call fuer diese Logiktests.
7. SemVer verwenden; lokal committen, aber nur auf ausdrueckliche Anweisung
   pushen. Bot-/Service-Restart bleibt an die vereinbarte Commit-Grenze
   gebunden, sofern kein expliziter Neustart verlangt wird.

## Aktueller Stand

- TeeBotus-Quellstand: 1.9.411.
- Laufender TeeBotus-Dienst: vor dem naechsten zulaessigen Restart noch
  1.9.404; der laufende History-Dispatcher: 0.2.9.
- Die Health-Klassifikation nutzt classification_version=2 und trennt
  handlungsrelevante Probleme von Informationen.
- Dispatcher- und Applet-Statuspruefungen validieren verschachtelte Antworten,
  Snapshot-Typen, Zeitstempel, Statuswerte und konkurrierende Refreshes.
- Terminale skipped-Ergebnisse werden nicht mehr als endlos retrybare Fehler
  behandelt.
- Die bestehende Statuslogik beruecksichtigt Bridge-Delegation, malformed rows,
  created_at fuer die Latest-Auswahl und Dispatcher-Warnungen.

## Offener Befund: lokale TBL-Queue und zentrale Bridge

Die aktuelle lesende Probe fuer TeeBotus_Logger zeigt einen echten
Reconciliation-Rueckstand:

- lokale TeeBotus-Outbox: zuletzt 44 queued-History-Zeilen
- zentraler History-Dispatcher: queued=0
- Bridge-Dry-Run: statuses: none
- zentrale Dispatcher-Queue kann diese alten lokalen Zeilen daher nicht
  claimen
- Collector-Scans erkennen die Sessiondaten zwar als bereits verarbeitet, sie
  reaktivieren die lokalen alten Queue-Zeilen aber nicht

Ursache: Neue Eintraege werden beim Schreiben gespiegelt, aber der Bridge-
Dispatchpfad liest bei query/claim nur die zentrale Queue. Eine lokale
Queue, die vor dem Mirror, nach einem Ausfall oder durch einen alten Pfad
entstanden ist, wird weder nachgefuehrt noch als separat geplante Aktion im
Dry-Run ausgegeben. Dadurch bleibt die Warnung dauerhaft sichtbar und eine
Zustellung ist ohne manuelle Migration nicht moeglich.

## Arbeitsplan

### 1. Reconciliation fachlich festlegen

- Dispatchbare lokale Zeilen mit derselben Auswahl- und Sortierlogik wie im
  bestehenden Bridge-Worker bestimmen.
- queued, stale dispatching und andere retrybare Zustaende sauber von
  terminalen delivered, acknowledged, skipped und compacted trennen.
- ID zuerst, deterministischer Codex-Dedupe-Key als zweiter Abgleich verwenden.
- Ein bereits zentral vorhandener Eintrag darf durch die Nachfuehrung nicht
  dupliziert werden.
- Ein echter Mirror-Fehler darf nicht als erfolgreiche Zustellung erscheinen.

### 2. Bridge-Reconciliation umsetzen

- Schwerpunktdatei: TeeBotus/admin/codex_history.py.
- Den vorhandenen Mirror-Append so erweitern, dass der Aufrufer Erfolg oder
  kontrollierten Fehlschlag erkennen kann; bestehende Aufrufer bleiben
  kompatibel.
- Im echten Bridge-Dispatch vor dispatch.claim lokale dispatchbare Zeilen
  best-effort per history.append nachfuehren.
- Dedupe-Key, lokale ID, Payload-Metadaten, Summary-Prefix und Empfaengerdaten
  unveraendert beziehungsweise angereichert uebergeben.
- Terminale zentrale Dedupe-Antworten direkt in die lokale Outbox
  synchronisieren; keinen kuenstlichen Versandversuch zaehlen.
- Lokale Zeilen bei Mirror-Fehlern nicht loeschen und nicht als delivered
  markieren.
- limit=0 als unbegrenzte, aber weiterhin validierte Auswahl behandeln;
  positive Limits auf Reconciliation und Dispatch gemeinsam anwenden.

### 3. Dry-Run sichtbar und nicht mutierend machen

- Der Dry-Run darf niemals history.append, dispatch.claim oder lokale
  Statusupdates ausfuehren.
- Lokale Eintraege, die zentral fehlen, als geplante would_mirror-Aktionen
  ausweisen.
- Bereits zentrale Eintraege nicht doppelt als Nachfuehrung ausgeben.
- Fehlende oder malformed Payloads kontrolliert als Fehler ausweisen.

### 4. Regressionstests

- Lokale queued Zeile ohne zentrale Entsprechung wird im echten Bridge-Lauf
  gespiegelt und danach claimbar.
- Derselbe Dedupe-Key erzeugt keinen zweiten zentralen Eintrag.
- Unterschiedliche lokale und zentrale IDs werden korrekt reconciled.
- Terminaler zentraler Status synchronisiert lokal, ohne erneuten Versand.
- Mirror-Fehler lassen die lokale Zeile queued und melden einen Fehler.
- Dry-Run zeigt would_mirror, schreibt aber weder lokal noch zentral.
- Positive Limits und limit=0 werden korrekt behandelt.
- Malformed Append-/Query-/Claim-Antworten bleiben fail-closed.
- Bestehende Status-, Bridge- und Dispatcher-Suiten bleiben gruen.

### 5. Lesende und anschliessend kontrollierte Live-Probe

- Vorher lokale und zentrale Zaehler, Dedupe-Keys und Statuswerte erfassen.
- Zuerst Bridge-Dry-Run ohne Mutation ausfuehren.
- Nach erfolgreicher Implementierung nur mit expliziter Freigabe eine reale
  Nachfuehrung ausfuehren.
- Danach lokale und zentrale Statuswerte, Empfaengerresultate und Warnungen
  erneut vergleichen.
- Keine Summary-Zeile, kein Artefakt und kein Secret in diesem Plan speichern.

### 6. Status- und Applet-Abgleich

- /status soll lokale und zentrale Queue nicht widerspruechlich darstellen.
- Ein lokaler Rueckstand bleibt Warnung, bis die Reconciliation ihn bestaetigt
  oder ein begruendeter terminaler Status vorliegt.
- Applet-Header und Detailansicht muessen Dispatcherfehler, alte Snapshots,
  malformed Daten und Reconciliation-Rueckstaende identisch klassifizieren.
- Quell-Applet installieren, byteweise mit der installierten Kopie vergleichen
  und nur bei Applet-Aenderungen reloaden.

## Invarianten

- Kein terminaler Erfolg wird erneut versendet.
- Kein lokaler queued Eintrag verschwindet ohne zentralen oder explizit
  protokollierten terminalen Status.
- Dedupe-Key und ID-Zuordnung bleiben stabil und nachvollziehbar.
- Unbekannte Status- oder Antwortformen werden nicht als Erfolg behandelt.
- no_private_route bleibt ein begruendeter Skip und kein Endlos-Retry.
- Health-Problemzaehler duerfen echte Warnungen nicht durch queued=0 oder
  Fallback-Informationen verdecken.

## Abschlusskriterien

Der Plan ist erst abgeschlossen, wenn:

- die Reconciliation implementiert und durch isolierte SQL-/Bridge-Tests
  belegt ist
- der Dry-Run die lokale Nachfuehrung sichtbar und nicht mutierend ausweist
- ein realer kontrollierter Nachweis lokale und zentrale Statuswerte abgleicht
- keine Duplikate oder Statusdowngrades entstehen
- /status, Healthcheck und Applet dieselbe Ursache anzeigen
- Tests, Version, Commit-ID und Live-Nachweis hier eingetragen sind
- erst danach eine fertige Planfassung nach Plaene und Regeln/ archiviert wird

## Umsetzungsnachweis dieses Plans

- Der Bridge-Dispatchpfad spiegelt lokale dispatchbare Zeilen vor
  `dispatch.claim` idempotent per `history.append`.
- Terminale Dedupe-Antworten werden ohne neuen Versandversuch in die lokale
  Outbox synchronisiert.
- Der Dry-Run fragt bei lokalem Rueckstand den Dispatcher-Bestand lesend ab
  und meldet `would_mirror` oder `would_sync`; er ruft keinen Append-, Claim-
  oder lokalen Schreibpfad auf.
- Mirror-Fehler werden als `history_dispatcher_mirror_failed` ausgegeben; die
  lokale Zeile bleibt `queued`.
- `tests/test_codex_history.py`: `128 passed`; Bridge-Teilmenge: `24 passed`.
- SemVer: `1.9.411`.
- Die schreibfreie Live-Probe meldete bei 44 lokalen queued-Zeilen
  `would_mirror=40` und `would_sync=4`.
- Ein echter Produktions-Reconciliation-Lauf ist noch nicht ausgefuehrt;
  lokale TBL-Daten bleiben bis zu einer kontrollierten Freigabe unangetastet.

## Befund 66: Status-Reason nach gemischter Zustellung

Bei `accepted + skipped(no_private_route)` war der Gesamtstatus korrekt
`delivered`, aber die alte Reason-Reihenfolge uebernahm trotzdem den Skip-Grund
als Item-`last_reason`. Die Reason-Aggregation folgt jetzt zuerst dem
Gesamtstatus: erfolgreiche Zustaende verwenden nur Erfolgsgruende, reine Skips
behalten ihren Skip-Grund.

Der direkte Regressionstest bestaetigt, dass ein alter Fehlergrund bei
`accepted + skipped` entfernt wird. SemVer ist jetzt `1.9.411`.

## Aktueller naechster Schritt

Als naechstes bleibt nur eine kontrollierte echte Reconciliation-Probe mit
expliziter Freigabe offen. Bis dahin bleibt der aktuelle TBL-Bestand
unangetastet.
