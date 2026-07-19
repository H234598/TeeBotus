# Bauplan: Logikpruefung-Historie, Teil 2

**Kategorie:** fortlaufende historische Befunde und Regressionen

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

