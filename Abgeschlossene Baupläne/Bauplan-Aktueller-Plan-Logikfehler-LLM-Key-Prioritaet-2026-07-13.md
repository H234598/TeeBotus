# Bauplan: Aktuelle Logikpruefung der LLM-Key-Prioritaet

**Stand:** 2026-07-13  
**Status:** Aktiv, noch nicht abgeschlossen  
**Quellstand:** TeeBotus `1.9.449`, Commit `25151c00`
**Geltungsbereich:** `TeeBotus/runtime/config.py`,
`TeeBotus/runtime/llm_factory.py`, `TeeBotus/llm/profiles.py`, die
Runtime-Runner und die zugehoerigen Regressionstests

## Auftrag

> Entwickle und finde Logikfehler. Bleibe moeglichst bei einer Datei bzw. einem
> Thema, um Token zu sparen.

Der aktuelle Schwerpunkt ist die durchgaengige, instanzbezogene Auswahl von
OpenAI-/LiteLLM-Schluesseln. Healthcheck, Profil-Builder und echter
Request-Pfad muessen fuer denselben Benutzer und dieselbe Botinstanz denselben
Schluesselvertrag verwenden. Ein gruener Healthcheck darf keinen Request mit
einem anderen oder leeren Schluessel vortaeuschen.

## Leitplanken

- Sicherheit vor Bequemlichkeit: Instanz- und Kanalgrenzen bleiben erhalten.
- Keine echten OpenAI-, Gemini-, HF- oder sonstigen kostenpflichtigen
  Provideraufrufe fuer Diagnose und Tests.
- Secrets duerfen weder in Logs, Testausgaben, Planschriften noch
  Healthpayloads erscheinen; Tests verwenden nur Platzhalterwerte.
- Nicht-OpenAI-Routen duerfen nicht durch die OpenAI-Sonderlogik veraendert
  werden.
- Rueckwaertskompatibilitaet der oeffentlich exportierten Builder bleibt
  erhalten.
- Uncommittete Benutzerdateien bleiben unangetastet:
  `.obsidian/`, `.stfolder/`, `Fusion_Packliste.txt`, `Unbenannt.base` und
  `Unbenannt.canvas`.
- Aenderungen werden lokal committed. Push erfolgt nur auf ausdrueckliche
  Anforderung; ein Bot-/Service-Restart erfolgt nur an der vereinbarten
  20-Commit-Grenze oder nach ausdruecklicher Freigabe.

## Bereits erledigte Befunde

### Befund 99: Healthcheck meldete LiteLLM-OpenAI-Instanzschluessel als fehlend

`provider=litellm` mit einem `openai/*`-Modell wird als OpenAI-Route erkannt.
Accountstatus, Routenstatus und API-Budgetstatus beruecksichtigen den
Instanz-Fallback. Das Applet stellt `key_scope=instance_fallback` ohne Secret
als instanzbezogenen Fallback dar.

### Befund 100: Diagnose und Runtime-Factory verwendeten unterschiedliche Keys

Die Runtime-Factory las nicht nur den globalen `OPENAI_API_KEY`, sondern loest
bei OpenAI-kompatiblen LiteLLM-Routen auch `OPENAI_API_KEY_<INSTANCE>` auf.
Damit entspricht der Client-Bau dem Healthcheck.

### Befund 101: Exportierter Profil-Builder blieb hinter der Runtime-Factory

`build_profiled_text_llm_client` akzeptiert optional `instance_name` und nutzt
die gemeinsame `resolve_profile_api_key`-Logik. Direkte Aufrufe bleiben ohne
Instanznamen rueckwaertskompatibel.

Nachweis fuer Befund 101:

- Router-/Package-Suite: `68 passed in 1.97s`
- direkter Profil-Builder-Test mit Instanz-Key: erfolgreich
- SemVer: `1.9.445`
- Commit: `27338c58`
- Plan-/Dokumentationsnachweis: `fb7b5776`

## Befund 102: Spezifischer Runtime-Key wurde durch Instanz-Fallback ersetzt

`resolve_openai_key()` kennt eine spezifischere Reihenfolge als der Profil-
und Route-Builder. Fuer eine Instanz kann zum Beispiel ein Kanal-/Slot-Key
vorhanden sein:

```text
OPENAI_API_KEY_DEMO_TELEGRAM_1 = slot-key
OPENAI_API_KEY_DEMO            = instance-key
```

Die Runtime-Konfiguration lieferte korrekt `slot-key`. Die Factory
ueberschrieb diesen bereits aufgeloesten `default_api_key` jedoch mit dem
weniger spezifischen Profil-Fallback `OPENAI_API_KEY_DEMO`. Das verletzte die
Kanal-/Slot-Isolation und konnte zu falschem Monitoring, unerwarteter
Keyrotation oder einem unpassenden Benutzerkontext fuehren.

### Umsetzung und Nachweis

- `_build_route_client()` und `_build_profile_client()` verwenden jetzt die
  Reihenfolge `override > resolved runtime key > profile fallback`.
- Der Fix gilt nur fuer OpenAI-kompatible Routen; Gemini-, lokale und andere
  Provider erben keinen OpenAI-Runtime-Key.
- Slot-vor-Instanz-Regression fuer Profil- und Purpose-Route: gruen.
- Router-/Package-Suite: `70 passed in 2.06s`.
- Mit Pyproject-Metadaten: `76 passed in 1.96s`.
- `py_compile` und `git diff --check`: erfolgreich.
- Read-only-Probe: `hard_reasoning ... status=configured
  key_scope=instance_fallback`; kein Provideraufruf.
- SemVer `1.9.446`, Commit `b877409f`.

## Befund 103: OpenAI-Fallback ignorierte den Instanz-Key

Der Primärpfad bewahrte den aufgeloesten Runtime-Key bereits korrekt. Ein
OpenAI-Fallback wurde jedoch separat nur mit `source[OPENAI_API_KEY]`
aufgebaut. Wenn nur `OPENAI_API_KEY_<INSTANCE>` gesetzt war, blieb der
Fallback-Client ohne Key, obwohl die Instanz korrekt konfiguriert war.

### Umsetzung und Nachweis

- Runtime-Factory und exportierter Profil-Builder loesen den Fallback-Key
  jetzt ueber denselben instanzbezogenen Resolver auf.
- Ein OpenAI-Fallback verwendet damit `OPENAI_API_KEY_<INSTANCE>` vor dem
  globalen Profil-Key; Gemini-, lokale und andere Fallbacks behalten ihre
  bisherige Env-Aufloesung.
- Runtime- und exportierter HF-Pool-Fallback-Test mit Instanz-Key: gruen.
- Router-, Package-, HF-Fallback-, Proactive- und Metadaten-Suite:
  `128 passed in 3.88s`.
- SemVer `1.9.447`, Commit `bdf427b4`.

## Befund 104: Unpraefixiertes OpenAI-Modell wurde nicht erkannt

Ein gueltiges LiteLLM-Fallback-Profil kann ein Modell wie `gpt-4.1-mini`
ohne `openai/`-Praefix fuehren. Das Routing behandelt `litellm` weiterhin als
remote, der Profil-Key-Resolver erkannte aber nur `openai` oder
`openai/...`. Ein vorhandener `OPENAI_API_KEY_<INSTANCE>` wurde dadurch fuer
dieses Profil nicht verwendet.

### Umsetzung und Nachweis

- Bei explizitem `OPENAI_API_KEY`-Env wird ein LiteLLM-Profil auch mit
  unpraefixiertem Modell als OpenAI-kompatibel behandelt.
- Andere LiteLLM-Modelle ohne dieses Env-Signal bleiben unveraendert.
- Unpraefixierter OpenAI-Fallback mit Instanz-Key: gruen.
- Router-, Package-, HF-Fallback-, Proactive- und Metadaten-Suite:
  `128 passed in 3.37s`.
- SemVer `1.9.448`, Commit `de5bc5a6`.

## Befund 105: Healthcheck erkannte unpraefixierte OpenAI-Routen nicht

Der Request-Resolver behandelte ein LiteLLM-Profil mit explizitem
`api_key_env=OPENAI_API_KEY` auch bei einem Modell ohne `openai/`-Praefix als
OpenAI-kompatibel. Der Healthcheck klassifizierte dagegen nur das Modell-
Praefix und konnte deshalb denselben vorhandenen Instanz-Key als fehlend
melden. Die Fallback-Statuszeile las den Key zudem nur global.

### Umsetzung und Nachweis

- Statusklassifikation verwendet jetzt ebenfalls das explizite
  `OPENAI_API_KEY`-Signal.
- `_runtime_status_llm_line()` und `_runtime_status_decision_line()` pruefen
  OpenAI-Fallbacks instanzbezogen vor dem globalen Env-Key.
- Der Fallback-Modellname bleibt im Statuspfad erhalten, damit die
  Keyklassifikation nicht vom Primärmodell abhaengt.
- Entrypoint-/Runtime-Status-Suite und LLM-Suite sind gruen; die LLM-Suite
  meldet `128 passed in 3.80s`.
- SemVer `1.9.449`, Commit `25151c00`.

## Befund 106: Structured-Decision-Status nutzte keine Instanzauflösung

`_runtime_status_structured_decision_line()` rief
`_runtime_route_status()` ohne `instance_names` auf. Bei einer Route mit
`api_key_env=OPENAI_API_KEY` blieb damit die instanzbezogene Aufloesung
unberuecksichtigt und der Status konnte trotz
`OPENAI_API_KEY_<INSTANCE>` falsch `missing_key` melden.

### Umsetzung und Nachweis

- Der aktuelle Instanzname wird an die gemeinsame Route-Key-Pruefung
  weitergereicht.
- Ein providerfreier Repro deckt den Unterschied zwischen fehlendem und
  vorhandenem Instanzkontext auf.
- Regression und vollstaendige Entrypoint-Suite sind gruen:
  `139 passed in 42.61s`.
- Syntax-/Whitespace-Pruefungen sind gruen.
- SemVer `1.9.450`, Commit `d29b8a4c`.

## Zielvertrag fuer die Key-Aufloesung

Fuer den echten Runtime-Pfad gilt diese Prioritaet:

1. expliziter `override_api_key` des Aufrufers,
2. bereits durch `resolve_openai_key()` aufgeloester `default_api_key`,
3. instanzbezogener Profil-Key `OPENAI_API_KEY_<INSTANCE>`,
4. globaler Profil-Key, zum Beispiel `OPENAI_API_KEY`.

Der direkte Profil-Builder ohne bereits aufgeloesten Runtime-Key verwendet
weiterhin:

1. `OPENAI_API_KEY_<INSTANCE>`,
2. den konfigurierten/globalen Profil-Key.

Damit wird ein spezifischerer Kanal-/Slot-Key nicht durch einen allgemeineren
Profil-Key ersetzt, ohne dass die bestehende API des Builders verbreitert
werden muss.

## Arbeitsplan

### 1. Vertragsabgleich (abgeschlossen)

- `resolve_openai_key()` und alle Runner-Aufrufer auf Kanal-/Slot-Kontext
  pruefen.
- `_build_route_client()` und `_build_profile_client()` auf die Reihenfolge
  `override > resolved default > profile fallback` abgleichen.
- Nur die beteiligten Factory-/Profil-Dateien aendern.

### 2. Fehler reproduzieren (abgeschlossen)

- Eine isolierte Konfiguration mit `slot-key` und `instance-key` verwenden.
- Nachweisen, dass die Konfiguration den Slot-Key liefert.
- Den resultierenden Client-Key ohne Provideraufruf pruefen.
- Keine Secretwerte ausgeben; nur stabile Testmarker verwenden.

### 3. Minimalen Fix umsetzen (abgeschlossen)

- Bereits aufgeloesten `default_api_key` vor dem Profil-Fallback bewahren.
- Explizite Overrides weiterhin an erster Stelle behandeln.
- Nicht-OpenAI-Provider unveraendert lassen.
- SemVer patch-bump nach erfolgreicher Korrektur.

### 4. Regressionen absichern (abgeschlossen)

- Test fuer Slot-vor-Instanz-Prioritaet im Runtime-Builder.
- Test fuer expliziten Override.
- Test fuer direkten Profil-Builder mit Instanz-vor-global.
- Test, dass Nicht-OpenAI-Routen keinen OpenAI-Key erben.
- Relevante Router-/Package-/Factory-Suiten ohne echte Provideraufrufe.

### 5. Laufzeit- und Plan-Nachweis (laufend fuer den uebergeordneten Plan)

- `py_compile` und `git diff --check` ausfuehren.
- Read-only-`--runtime-status` nach dem Quellfix auswerten (erledigt).
- Keine automatische Reparatur einer Signal-Identitaet aus dem Healthcheck
  ausloesen.
- Aktive Warnungen und verbleibende externe Handlungen getrennt dokumentieren.
- Diesen Plan und die verknuepften Healthcheck-Plaene mit Version, Commit,
  Testergebnis und Live-Befund aktualisieren (dieser Nachweis).

## Invarianten

- Ein Client darf nicht instanzuebergreifend auf einen fremden Key fallen.
- Ein Kanal-/Slot-Key ist spezifischer als ein reiner Instanz-Key.
- Ein expliziter Override darf durch keinen Profil-Fallback ersetzt werden.
- Healthcheck und Request-Pfad muessen denselben effektiven Key-Scope
  anzeigen, ohne den Key selbst preiszugeben.
- Ein fehlender oder widerspruechlicher Key bleibt diagnostizierbar und wird
  nicht als erfolgreich konfiguriert ausgegeben.
- Tests bleiben providerfrei und veraendern keine produktiven Secrets,
  Accounts, Memories oder Outboxen.

## Abschlusskriterien

Der Plan ist erst abgeschlossen, wenn:

- der Slot-vor-Instanz-Fall reproduziert und behoben ist,
- Override-, Runtime-, Profil- und Nicht-OpenAI-Regressionen gruen sind,
- die relevanten Tests sowie Syntax- und Diff-Pruefungen erfolgreich sind,
- eine lesende Runtime-Statusprobe ohne kostenpflichtigen Provideraufruf
  erfolgt ist,
- SemVer, Commit und Testergebnisse in diesem Plan stehen,
- keine unbeabsichtigten Benutzerdateien staged oder veraendert wurden.

Bis dahin bleibt dieser Bauplan unter `Abgeschlossene Baupläne/` aktiv.
