# Bauplan: Aktueller Stand und Ledger

**Kategorie:** aktiver Arbeitsstand, Tests und Commits

- `teebotus.service` aktiv/running, `MainPID 2292239`, Start `2026-07-19 01:09:27 CEST`.
- Seit diesem Restart: `3/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Kontrast-Konnektoren

- `auch wenn`, `trotzdem` und Label-Kontraste zwischen Arbeitsort und Wohnort liefern Wohnstadt.
- Gleichartige Arbeitsortangaben ohne Wohnortlabel bleiben leer.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, vier Contrast-Connector-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `f4237586 fix: parse contrast residence connectors`.

## Aktueller Ledger 2026-07-19-Post-Restart

- `teebotus.service` aktiv/running, `MainPID 2292239`, Start `2026-07-19 01:09:27 CEST`.
- Seit diesem Restart: `4/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Unsichere Wohnort-Suffixe

- Nachgestellte Unsicherheit (`glaube ich`, `denke ich`, `vermute ich`, `nehme ich an`) blockiert Wohnortspeicherung.
- Sichere Zusätze bleiben gültig.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, fünf Uncertainty-Suffix-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `98b3ac88 fix: reject uncertain residence suffixes`.

## Aktueller Ledger 2026-07-19-Post-Restart

- `teebotus.service` aktiv/running, `MainPID 2292239`, Start `2026-07-19 01:09:27 CEST`.
- Seit diesem Restart: `5/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Länderzusätze in Klammern

- `Berlin (Deutschland)` wird auf Berlin normalisiert.
- Echte Kompositstadt `Halle (Saale)` bleibt unverändert.
- Länder/Regionen werden nicht als Städte erfunden.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, drei Parenthesized-Location-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `4f99b457 fix: normalize parenthesized country suffixes`.

## Aktueller Ledger 2026-07-19-Post-Restart

- `teebotus.service` aktiv/running, `MainPID 2292239`, Start `2026-07-19 01:09:27 CEST`.
- Seit diesem Restart: `6/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Postpositive Sicherheitsadverbien

- `Ich wohne in Berlin, wirklich/sicher/tatsächlich` wird nicht mehr als Mehrfachziel verworfen.
- Echte Zweitstadt `Ich wohne in Berlin, Hamburg` bleibt mehrdeutig und leer.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, vier Confidence-Suffix-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `ac41a20c fix: allow confidence residence suffixes`.

## Aktueller Ledger 2026-07-19-Post-Restart

- `teebotus.service` aktiv/running, `MainPID 2292239`, Start `2026-07-19 01:09:27 CEST`.
- Seit diesem Restart: `7/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Qualifizierte Meldeadressen

- `Meine offizielle/private Meldeadresse ist Berlin` wird als Berlin erkannt.
- `Meine geschäftliche Adresse ist Berlin` wird nicht mehr als Wohnort gespeichert.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, vier Address-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `bcb0ee81 fix: parse qualified registered addresses`.

## Aktueller Ledger 2026-07-19-Post-Restart

- `teebotus.service` aktiv/running, `MainPID 2292239`, Start `2026-07-19 01:09:27 CEST`.
- Seit diesem Restart: `8/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Registrierte Wohnadressen

- Qualifizierte Meldeanschriften mit Doppelpunkt und `eine offizielle Meldeadresse in ...` werden erkannt.
- `Ich bin in Berlin amtlich gemeldet` liefert nur Berlin, nicht `Berlin amtlich`.
- `Berlin ist meine gemeldete Adresse` wird erkannt; Geschäftsadressen bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, fünf Registered-Residence-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `171e1b76 fix: parse registered residence variants`.

## Aktueller Ledger 2026-07-19-Post-Restart

- `teebotus.service` aktiv/running, `MainPID 2292239`, Start `2026-07-19 01:09:27 CEST`.
- Seit diesem Restart: `9/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Qualifier registrierter Wohnsitz

- `amtlich gemeldet/registriert` behält nur Stadtnamen und verschluckt Qualifier nicht als Stadtteil.
- `aktuelle`, `amtliche`, `neue` und `gemeldete Meldeadresse` werden erkannt.
- Arbeits-/Geschäftsadressen bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, sechs Qualifier-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `dfbdf953 fix: cover qualified registered addresses`.

## Aktueller Ledger 2026-07-19-Post-Restart

- `teebotus.service` aktiv/running, `MainPID 2292239`, Start `2026-07-19 01:09:27 CEST`.
- Seit diesem Restart: `10/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Gemischte Wohnadress-Ziele

- Direkte Aussagen wie `Berlin ist meine Wohnadresse. Hamburg ist mein Wohnort.` werden als widersprüchlich verworfen.
- Arbeits-/Geschäftsadressen bleiben aus dem Wohnziel-Konflikt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, vier Direct-Conflict-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `69efcc20 fix: reject mixed residence address targets`.

## Aktueller Ledger 2026-07-19-Post-Restart

- `teebotus.service` aktiv/running, `MainPID 2292239`, Start `2026-07-19 01:09:27 CEST`.
- Seit diesem Restart: `11/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Unaufgelöste `sondern`-Wohnsätze

- Unvollständige Kontrastsätze wie `Ich wohne in Berlin, sondern in Hamburg` speichern keinen Wohnort.
- Valide Negationskorrekturen mit `nicht ..., sondern ...` bleiben unverändert.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, vier Separator-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `7535f23b fix: reject unresolved sondern residence clauses`.

## Aktueller Ledger 2026-07-19-Post-Restart

- `teebotus.service` aktiv/running, `MainPID 2292239`, Start `2026-07-19 01:09:27 CEST`.
- Seit diesem Restart: `12/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Unaufgelöste Kontrast-Orte

- `aber/doch/jedoch in <Stadt>` ohne Zeit-/Verbkontext wird nicht als Umzug fehlinterpretiert.
- Verkürzte Kontrastlabels wie `aber Hamburg mein Wohnort` werden bei mehreren Wohnzielen als Konflikt erkannt.
- Valide `aber jetzt in ...`-Umzüge und Arbeitsort-Kontraste bleiben erhalten.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, acht Contrast-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `2b2f7173 fix: guard unresolved residence contrasts`.

## Aktueller Ledger 2026-07-19-Post-Restart

- `teebotus.service` aktiv/running, `MainPID 2292239`, Start `2026-07-19 01:09:27 CEST`.
- Seit diesem Restart: `13/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Klauselgrenzen bei Arbeits-/Wohnorten

- `Berlin ist mein Arbeitsort, Hamburg mein Wohnort` liefert Hamburg statt leer.
- Nicht-residenter Präfix aus vorheriger Kommaklausel vergiftet Folge-Match nicht mehr.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, vier Work/Residence-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c29b7253 fix: isolate residence clause prefixes`.

## Aktueller Ledger 2026-07-19-Post-Restart

- `teebotus.service` aktiv/running, `MainPID 2292239`, Start `2026-07-19 01:09:27 CEST`.
- Seit diesem Restart: `14/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: PLZ in Meldeadressen

- `10115 Berlin` wird aus Meldeadresse und `in ... gemeldet/registriert` als Berlin extrahiert.
- PLZ landet nicht im gespeicherten Stadtwert.
- Arbeits-/Geschäftsadressen mit PLZ bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, sieben Postcode-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `4962d078 fix: parse postal registered addresses`.

## Aktueller Ledger 2026-07-19-Post-Restart

- `teebotus.service` aktiv/running, `MainPID 2292239`, Start `2026-07-19 01:09:27 CEST`.
- Seit diesem Restart: `15/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Zeitlicher Einschub vor Wohnsitz

- `Ich habe derzeit/aktuell meinen Wohnsitz in ...` wird erkannt.
- Gleichlautende Arbeitsort-Angaben bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, drei Time-Insertion-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `fa2c7d37 fix: parse timed residence declarations`.

## Aktueller Ledger 2026-07-19-Post-Restart

- `teebotus.service` aktiv/running, `MainPID 2292239`, Start `2026-07-19 01:09:27 CEST`.
- Seit diesem Restart: `16/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Zeitstellung bei Wohnsitz und Wohnung

- `Ich habe meinen Wohnsitz derzeit/seit 2020 in ...` wird erkannt.
- Aktuelle/neue `Wohnung` und `Unterkunft` mit Ortsangabe werden erkannt.
- Unklare Zweitwohnungsform `Ich habe derzeit eine Wohnung in ...` bleibt leer; historische und Arbeitsorte bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, acht Housing/Time-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `bae5820b fix: parse timed housing residence forms`.

## Aktueller Ledger 2026-07-19-Post-Restart

- `teebotus.service` aktiv/running, `MainPID 2292239`, Start `2026-07-19 01:09:27 CEST`.
- Seit diesem Restart: `17/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Nicht-residente Begleitkontexte

- `mit meiner Ausbildung` und `bei meiner Firma` werden nicht mehr als Wohnortkontext gespeichert.
- Familie, Eltern und Partner bleiben als Wohnkontext gültig.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, fünf Companion-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `1b4dbaf7 fix: reject nonresidential companion contexts`.

## Aktueller Ledger 2026-07-19-Post-Restart

- `teebotus.service` aktiv/running, `MainPID 2292239`, Start `2026-07-19 01:09:27 CEST`.
- Seit diesem Restart: `18/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Arbeitgeber als Begleitperson

- `bei meinem Chef/Arbeitgeber` wird nicht mehr als Wohnkontext missinterpretiert.
- Familiäre Begleiter und Gastfamilie bleiben gültige Wohnkontexte.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, vier Work-Companion-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `8b8e6d75 fix: reject employer companion contexts`.

## Aktueller Ledger 2026-07-19-Post-Restart

- `teebotus.service` aktiv/running, `MainPID 2292239`, Start `2026-07-19 01:09:27 CEST`.
- Seit diesem Restart: `19/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Qualifier im Possessiv-Wohnsitz

- `meinen aktuellen/gemeldeten Wohnsitz` und `meinen jetzigen Wohnort` werden erkannt.
- Historische Wohnsitze und Arbeitsorte bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, fünf Possessive-Qualifier-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `d8aa60f7 fix: parse qualified possessive residences`.
- Restart danach: `teebotus.service` `active/running`, `MainPID 3403613`, Start `2026-07-19 02:19:35 CEST`.

## Aktueller Ledger 2026-07-19-Post-Restart

- `teebotus.service` aktiv/running, `MainPID 3403613`, Start `2026-07-19 02:19:35 CEST`.
- Neuer Zyklus seit diesem Restart: `7/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Weitere Straßenarten

- `Damm`, `Kai`, `Deich`, `Höhe`, `Park` und `Gürtel` werden als Straßenarten erkannt.
- Straßenparser, Fallbacks, `_clean_city` und Ambiguitätsguard verwenden gemeinsamen `_STREET_TYPE`.
- Verifikation: `tests/test_weather_context.py` -> `175 passed`, sechs Additional-Street-Type-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c14d6455 fix: parse additional street types`.

### Folgefix 2026-07-19: Internationale PLZ-Präfixe

- `D-10115`, `DE-10115` und `D 10115` werden in Straßen- und Labeladressen erkannt.
- Direkte Wohnadresse mit abweichender Meldeadresse bleibt durch Konfliktguard leer.
- Verifikation: `tests/test_weather_context.py` -> `176 passed`, vier International-Postal-Prefix-Smokes plus Konflikt-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `ac20b363 fix: parse international postal prefixes`.

### Folgefix 2026-07-19: Zuhause-Satz ohne falschen Subjekt-Stadtwert

- `Ich wohne/lebe in Berlin zuhause/zu Hause/daheim` liefert Berlin statt fälschlich `Ich wohne`.
- Breites Daheim-Fallback wird für Subjekt+Wohnverb blockiert; direkter Wohnpfad bleibt zuständig.
- Verifikation: `tests/test_weather_context.py` -> `178 passed`, drei Home-Adverb-Smokes plus Subjekt-Negativsmoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `d84b1fc6 fix: reject residence subject as home city`.

### Folgefix 2026-07-19: Pluraler Zuhause-Status

- `Wir sind in Hamburg daheim/zuhause/zu Hause` liefert Hamburg statt `Wir sind`.
- Breites Daheim-Fallback blockiert jetzt auch `Ich/Wir bin/sind`; historische Negation bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `178 passed`, bestehende Home-Smokes plus Plural-Status-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `65472c67 fix: parse plural home status`.

### Folgefix 2026-07-19: Statussuffix nach Wohnverb

- `Ich wohne/lebe in Berlin wohnhaft/ansässig/gemeldet/registriert` liefert Berlin statt Statussuffix im Stadtwert.
- Historische Statussätze bleiben ausgeschlossen; Arbeitskontext bleibt zulässig.
- Verifikation: `tests/test_weather_context.py` -> `179 passed`, vier Residence-Verb-Status-Smokes plus Negativ-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `27bf9812 fix: stop residence city before status suffix`.

### Folgefix 2026-07-19: Komma vor Zuhause-Adverb

- `Ich wohne/bin in Berlin, zuhause/zu Hause/daheim` und Pluralvarianten liefern Berlin.
- Generisches Daheim-Fallback wird für direkte Wohnsätze und den eindeutigen Kommaabschluss nicht als falsche Subjekt-Stadt verwendet; Mehrfachorte bleiben leer.
- Verifikation: `tests/test_weather_context.py` -> `180 passed`, vier Comma-Home-Smokes plus zwei Ambiguitäts-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `3e29ca30 fix: parse comma home adverb sentences`.

### Folgefix 2026-07-19: Ortspräzisierung vor Straßenadresse

- `im nördlichen Berlin`, `im Norden Berlins` und `im Bezirk Kreuzberg in Berlin` mit Straßenadresse liefern übergeordneten Ort.
- Unbekannter Stadtteil ohne übergeordnete Stadt bleibt ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `181 passed`, vier Area-Qualifier-Before-Street-Smokes plus Negativ-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e7896830 fix: parse area qualifiers before streets`.

### Folgefix 2026-07-19: Verbfreie Wohnadress-Labels

- `Wohnadresse Berlin` wird erkannt; `Geburtsort` wird nicht als Wohnziel gewertet.
- Wohnadresse/Meldeadresse-Konflikte werden auch ohne Verb erkannt.
- Arbeitsadresse bleibt als nicht-residenter Kontext zulässig.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, fünf Address/Origin-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a6010b83 fix: track verbless residence address labels`.

### Folgefix 2026-07-19: Qualifizierte verbfreie Wohnlabels

- `aktuelle/offizielle/gemeldete Wohnadresse` und `offizieller/gemeldeter Wohnsitz` werden erkannt.
- Verb-Füller `war/liegt` werden nicht als Stadt übernommen.
- Wohnadresse/Meldeadresse-Konflikt bleibt leer.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, neun Qualified-Label-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `797aec0b fix: parse qualified verbless residence labels`.

### Folgefix 2026-07-19: Artikel bei verbfreien Wohnlabels

- `der/die/das/ein/eine` werden bei verbfreien Wohn-, Wohnadress- und Meldeadress-Labels erkannt.
- Widerspruechliche Artikel-Labels mit separater Meldeadresse liefern weiterhin keinen Wohnort.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, Artikel-/Konflikt-Smoke gruen, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `b857f7fa fix: handle article residence labels`.

### Folgefix 2026-07-19: Mehrfachziele bei verbfreien Labels

- `Wohnadresse Berlin und Hamburg` sowie Komma-Varianten liefern keinen erfundenen Einzelort.
- `Umgebung`, Arbeitsadresse und Geburtsstadt bleiben als nicht-residente Zusätze zulässig.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, sechs Multiplikitäts-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `ee52ad80 fix: reject multiple verbless residence targets`.

### Folgefix 2026-07-19: Präzisierung verbfreier Adresslabels

- `Wohnadresse/Meldeadresse Berlin, genauer gesagt Hamburg` liefert den präzisierten aktuellen Ort.
- Arbeitsadresse und Geburtsstadt nach Komma bleiben nicht-residente Zusätze.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, drei Adresspräzisierungs-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `9518c7eb fix: parse residence address clarifications`.

### Folgefix 2026-07-19: Separatorvarianten bei Adresspräzisierungen

- Präzisierungen nach `:`, `=` oder Komma werden auch bei Leerzeichen vor dem Separator erkannt.
- Bestehende Leerzeichen- und Konfliktformen bleiben unverändert.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, zwei Separator-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `7e2ff63e fix: accept separator variants in address changes`.

### Folgefix 2026-07-19: Klammerzusätze bei verbfreien Wohnlabels

- `Halle (Saale)` bleibt als bekannte zusammengesetzte Stadt erhalten.
- Länderzusätze wie `Berlin (Deutschland)` werden zu `Berlin` normalisiert.
- Konflikt- und Präzisierungslogik berücksichtigt Klammerzusätze ebenfalls.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, vier Parenthesized-Label-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `2cb779b0 fix: preserve parenthesized residence cities`.

### Folgefix 2026-07-19: Registrierte Adress-Aliase im Konfliktguard

- `Meldeanschrift` und `Meldesitz` werden bei widersprüchlichen Wohnzielen wie `Meldeadresse` behandelt.
- Arbeitsadressen lösen weiterhin keinen Wohnortkonflikt aus.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, drei Registered-Label-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a8b6348a fix: detect registered address aliases`.

### Folgefix 2026-07-19: Artikel und Qualifier bei Verb-Adresskonflikten

- `Die Wohnadresse ist ...` und `Die aktuelle Wohnadresse ist ...` werden im Konfliktguard erfasst.
- Widersprüche zu `Meldeadresse`, `Meldeanschrift`, `Meldesitz` und Arbeitsadresse werden nicht als aktueller Wohnort ausgegeben.
- Gleiche Wohn-/Melde-Stadt bleibt gültig.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, sechs Verb-Adress-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c9fe1e75 fix: detect article address conflicts`.

### Folgefix 2026-07-19: First-Person-Adressartikel

- `Ich habe eine Wohnadresse/einen Wohnsitz in Berlin` sowie aktuelle/offizielle Varianten werden erkannt.
- Arbeitsadresse, historische Adresse und mehrere Wohnziele bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, acht First-Person-Address-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a5e8400a fix: parse first-person residence addresses`.

### Folgefix 2026-07-19: First-Person-Adresskonflikte

- First-Person-Wohnadresse/Wohnsitz wird gegen persönliche Meldeadresse, Meldeanschrift, Meldesitz und Arbeitsadresse geprüft.
- Unterschiedliche Städte liefern leer; gleiche Stadt und Geburtsstadt bleiben zulässig.
- Generische Arbeitsadresslabels außerhalb dieses First-Person-Kontexts bleiben unverändert.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, vier First-Person-Conflict-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a37a0952 fix: guard first-person address conflicts`.

### Folgefix 2026-07-19: Postleitzahlen vor Wohnorten

- `10115 Berlin` wird in First-Person-, verbfreien und `wohnhaft`-Formen erkannt.
- Gespeicherter Stadtwert bleibt `Berlin`, nicht die Postleitzahl.
- Konflikte und Mehrfachziele mit PLZ bleiben geschützt.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, sechs Postal-Residence-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c0f3c357 fix: parse postal residence locations`.

### Folgefix 2026-07-19: PLZ bei Wohnort-Präzisierungen

- `10115 Berlin, genauer gesagt 20095 Hamburg` wird auch in First-Person-Adresssätzen als Wechsel nach Hamburg erkannt.
- Klammerzusätze und `in/bei` bleiben kompatibel.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, zwei Postal-Change-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `67433899 fix: parse postal residence changes`.

### Folgefix 2026-07-19: PLZ-Mehrfachziele

- `10115 Berlin und 20095 Hamburg` wird bei verbfreien und First-Person-Labels als mehrdeutig verworfen.
- `Umgebung`, Region/Nähe sowie Arbeits- und Geburtsortzusätze bleiben zulässig.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, drei Postal-Multiplicity-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `3b7dbce0 fix: reject postal residence multiplicity`.

### Folgefix 2026-07-19: Aktuelle Qualifier bei Possessivlabels

- `tatsächlicher`, `dauerhafter`, `vorübergehender`, `momentaner` und weitere aktuelle Qualifier werden vor Wohnort/Wohnsitz/Wohnadresse erkannt.
- Historische und künftige Qualifier bleiben ausgeschlossen.
- Konfliktcollector verwendet dieselbe Qualifiergruppe.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, acht Current-Qualifier-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `79a0140d fix: parse current residence qualifiers`.

## Aktueller Ledger 2026-07-19-Post-Restart

- `teebotus.service` aktiv/running, `MainPID 3403613`, Start `2026-07-19 02:19:35 CEST`.
- Seit diesem Restart: `16/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Straßenadress-Labels

- `Die Wohnadresse: Musterstraße 5, Berlin` und `Meldeadresse: Hauptweg 7, 10115 Berlin` werden erkannt.
- Optionaler Straßen-/PLZ-Teil wird nicht als Stadt gespeichert.
- Konfliktverknüpfung bleibt als Folgefix separat.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, drei Street-Address-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `efd23d0a fix: parse labeled street residence addresses`.

### Folgefix 2026-07-19: Straßenadress-Konflikte

- `Wohnadresse: Musterstraße 5, Berlin; Meldeadresse Hamburg` wird als widersprüchlich verworfen.
- `Meldeanschrift` und PLZ bei Straßenadressen werden im Konfliktguard berücksichtigt.
- Gleiche Wohn-/Melde-Stadt bleibt gültig; Arbeitsadresse bleibt davon getrennt.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, vier Street-Address-Conflict-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `4f139661 fix: guard street residence address conflicts`.

### Folgefix 2026-07-19: Separatoren bei Straßenadress-Labels

- Straßenadress-Labels akzeptieren `:`, `=` und Komma als Separator.
- PLZ, Hausnummer und Stadt werden weiterhin getrennt verarbeitet.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, zwei Separator-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `cea41f95 fix: accept street address label separators`.

### Folgefix 2026-07-19: Zusammengesetzte Hausnummern

- Hausnummern mit Bereich, Schrägstrich oder Buchstabenabstand (`5-7`, `5/7`, `5 b`) werden erkannt.
- Direkte Erkennung und Straßenadress-Konfliktguard verwenden dieselbe Variantenlogik.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, vier Compound-House-Number-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `fd28e27c fix: parse compound street house numbers`.

### Folgefix 2026-07-19: Abgekürzte Straßennamen

- `Musterstr. 5, Berlin` und `Hauptstr. 7, Berlin` werden erkannt.
- `_clean_city` verwirft Straßenfragmente wie `Musterstr. 5` nicht mehr als scheinbare Stadt.
- Konflikte mit abweichender Meldeadresse bleiben geschützt.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, vier Street-Abbreviation-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `b9ee8504 fix: support abbreviated street names`.

## Aktueller Ledger 2026-07-19-Post-Restart-2

- `teebotus.service` aktiv/running, `MainPID 434057`, Start `2026-07-19 03:36:33 CEST`.
- Neuer Zyklus seit diesem Restart: `20/20` Code-Fixes. Restart jetzt fällig; kein Push.

### Folgefix 2026-07-19: Präpositionale Straßennamen

- `Unter den Linden 5`, `Am Markt 5` und `Zur Alten Post 5` werden im Adresslabel erkannt.
- Gemeinsame Straßenadress-Regex wird für direkte Erkennung und Konfliktguard verwendet.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, vier Prepositional-Street-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `86842852 fix: parse prepositional street addresses`.

### Folgefix 2026-07-19: Whitespace-getrennte Straßenadressen

- `Musterstraße 5 10115 Berlin` und `Am Markt 5 Berlin` werden ohne Komma erkannt.
- PLZ bleibt von Stadtwert getrennt; abweichende Meldeadresse löst weiterhin Konflikt aus.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, drei Whitespace-Address-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `4d920905 fix: parse whitespace separated street addresses`.

### Folgefix 2026-07-19: Gebäudedetails in Straßenadressen

- `Hinterhaus`, Etagen (`2. OG`) und Wohnungsangaben werden zwischen Hausnummer und Stadt übersprungen.
- Direkte Erkennung und Konfliktguard verwenden dieselbe Detailliste.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, vier Building-Detail-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a8e492ab fix: skip street address building details`.

### Folgefix 2026-07-19: Zusammengesetzte Gebäudedetails

- `2. OG links`, `Wohnung 3 links` und `Hinterhaus rechts` werden vollständig übersprungen.
- Stadtwert bleibt stabil; keine Adressfragmente als Wohnort.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, drei Compound-Building-Detail-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `3ce4c531 fix: parse compound building address details`.

### Folgefix 2026-07-19: Weitere Gebäudedetails

- `1. Etage`, `Souterrain`, `Aufgang A` und `Haus A` werden als Adressdetails übersprungen.
- Gemeinsame Regex schützt direkte Stadt-Erkennung und Konfliktguard.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, vier Additional-Building-Detail-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `fcc4f05d fix: parse additional building address details`.

### Folgefix 2026-07-19: Ketten von Gebäudedetails

- Mehrere Details wie `Hinterhaus, 2. OG` oder `Aufgang A, Wohnung 3` werden vor Stadt/PLZ übersprungen.
- Unterschiedliche Meldeadresse bleibt trotz Detailkette Konflikt.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, vier Chained-Building-Detail-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `2128cbf2 fix: parse chained building address details`.

### Folgefix 2026-07-19: Hausnummern mit Buchstabenbereichen

- `5a-5b` und `5a/5b` werden als Hausnummern erkannt.
- `_clean_city` verwirft solche Straßenfragmente weiterhin als keine Stadt.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, drei Lettered-House-Range-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `2dcc52cf fix: parse lettered house number ranges`.

### Folgefix 2026-07-19: Verbale Straßenadress-Labels

- `Wohnadresse ist ...`, `Wohnadresse lautet ...`, `Meldeadresse befindet sich in ...` und `Wohnsitz liegt in ...` werden erkannt.
- Präpositionale Straßenadressen werden im Ambiguitätsguard nicht mehr als zwei Wohnziele gewertet.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, sechs Verbal-Street-Label-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `71285c5d fix: parse verbal street residence labels`.

### Folgefix 2026-07-19: Wohnortwechsel mit Straßenadressen

- `nicht mehr in Musterstraße 5, Berlin, sondern in Hauptweg 7, Hamburg` liefert Hamburg.
- Altadresse bleibt historisch; nur neue Stadt wird als aktueller Wohnort verwendet.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, ein Street-Address-Change-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `26dbd66c fix: parse street address residence changes`.

### Folgefix 2026-07-19: Straßenadresswechsel mit `auf`

- `Wohnadresse wechselte von Musterstraße 5, Berlin auf Hauptweg 7, Hamburg` liefert Hamburg.
- Alte Adresse bleibt als Wechselquelle; neuer Ort gewinnt.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, ein Switched-Street-Address-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `8247b5f3 fix: parse switched street residence addresses`.

### Folgefix 2026-07-19: Umzug mit Straßenadressen

- `Ich bin von Musterstraße 5, Berlin nach Hauptweg 7, Hamburg gezogen` liefert Hamburg.
- Verb `gezogen` bleibt außerhalb des Stadtwerts.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, ein Moved-Street-Address-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `085bb7ff fix: parse moved street residence addresses`.

### Folgefix 2026-07-19: Vorher-/Nachher-Straßenadresslabel

- `Wohnadresse: vorher Musterstraße 5, Berlin, jetzt Hauptweg 7, Hamburg` liefert Hamburg.
- Historischer Altort wird nicht als aktueller Wohnort gespeichert.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, ein Before-After-Street-Label-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `1ec33109 fix: parse before after street residence labels`.

### Folgefix 2026-07-19: Alte/neue Wohnadresse

- `Meine alte Wohnadresse war ..., meine neue ist ...` liefert neue Stadt.
- Historische Adresse bleibt ausgeschlossen; neue Straßenadresse gewinnt.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, ein Old-New-Street-Label-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c5a543cd fix: parse old new street residence labels`.

### Folgefix 2026-07-19: Verlagerte Straßenadressen

- `Wohnadresse/Wohnort hat sich von ... nach ... geändert/verlagert` liefert neue Stadt.
- Altadresse bleibt Quelle des Wechsels und wird nicht als aktuell gewertet.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, zwei Relocated-Street-Residence-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `f065001d fix: parse relocated street residences`.

### Folgefix 2026-07-19: Passive Straßenadressänderung

- `Adresse wurde von ... auf ... geändert` liefert neue Stadt.
- Hausnummern, PLZ und Altadresse werden korrekt aus Wechselquelle getrennt.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, ein Passive-Street-Address-Change-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `3ddfee20 fix: parse passive street address changes`.

### Folgefix 2026-07-19: Aktuelle Adresse vor `statt`

- `Wohnadresse ist jetzt Hauptweg 7, Hamburg statt Musterstraße 5, Berlin` liefert Hamburg.
- Aktueller Ort wird vor historischem Vergleichswert priorisiert.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, ein Current-First-Street-Change-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `7845e28d fix: parse current first street address changes`.

### Folgefix 2026-07-19: First-Person-Straßenadresswechsel

- `Ich habe meine Wohnadresse von ... auf ... geändert` liefert neue Stadt.
- Wechselwort und Altadresse werden nicht in den aktuellen Stadtwert gezogen.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, ein First-Person-Street-Change-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `77cf4061 fix: parse first person street address changes`.

### Folgefix 2026-07-19: Künftige Straßenadressen

- `künftige`/`zukünftige Wohnadresse` wird trotz Straßen-/PLZ-Komma nicht als aktueller Wohnort gespeichert.
- Ein späterer aktueller Wohnort im selben Satz bleibt erkennbar.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, vier Future-Street-Context-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `55e8b3fa fix: reject future street residence labels`.

### Folgefix 2026-07-19: Unsichere Straßenadressen

- `mögliche` und `wahrscheinliche Wohnadresse` werden nicht als Fakt gespeichert.
- Sichere Straßenadresse bleibt gültig.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, drei Uncertain-Street-Label-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `3ac3ddaa fix: reject uncertain street residence labels`.

### Folgefix 2026-07-19: Punktlose Straßenabkürzungen

- `Musterstr 5` und `Hauptstr 7` werden wie `Musterstr. 5` erkannt.
- Konfliktguard und `_clean_city` behandeln beide Schreibweisen konsistent.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, drei Unpunctuated-Street-Abbreviation-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `47051e03 fix: accept unpunctuated street abbreviations`.

## Aktueller Ledger 2026-07-19-Post-Restart-3

- `teebotus.service` aktiv/running, `MainPID 3691691`, Start `2026-07-19 16:41:08 CEST`.
- Neuer Zyklus seit diesem Restart: `20/20` Code-Fixes. Restart jetzt fällig; kein Push.

### Folgefix 2026-07-19: Freie Straßenadress-Sätze

- `Wir wohnen in Unter den Linden 5, Berlin`, `Ich wohne in Am Markt 5, Berlin` und `in ... wohnhaft` werden erkannt.
- Stadtwert bleibt Berlin; Straßenfragmente wie `in` werden nicht gespeichert.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, drei Freeform-Street-Sentence-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `b2862bfe fix: parse freeform street residence sentences`.

### Folgefix 2026-07-19: Qualifizierte freie Straßenadress-Sätze

- `Ich lebe momentan in ...` und `Ich wohne aktuell bei ...` werden erkannt.
- Aktuelle Zeitqualifier werden unterstützt, Zukunftsqualifier bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, zwei Qualified-Freeform-Street-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `11885dba fix: parse qualified freeform street residences`.

### Folgefix 2026-07-19: Besitz- und Statusformulierungen

- `Ich habe meinen Wohnsitz/meine Bleibe in ...` und `Ich bin wohnhaft/ansässig in ...` werden erkannt.
- Straßen-, PLZ- und Präpositionsvarianten bleiben gemeinsam nutzbar.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, vier Possession-Status-Street-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `91887ad3 fix: parse possession and residence status sentences`.

### Folgefix 2026-07-19: Qualifier bei Besitz-/Statusformulierungen

- `fester/offizieller/aktueller/dauerhafter Wohnsitz` und `offiziell/dauerhaft wohnhaft/ansässig` mit Straßenadresse werden erkannt.
- Vorhandene Current-Qualifier-Gruppe wird wiederverwendet; generische Wohnort-Labels bleiben geschützt.
- Verifikation: `tests/test_weather_context.py` -> `158 passed`, sechs Qualified-Possession-Status-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `3a698f04 fix: parse qualified residence status sentences`.

### Folgefix 2026-07-19: Hauptwohnsitz und Lebensmittelpunkt mit Straßenadresse

- Besitzsätze mit `Hauptwohnsitz` oder `Lebensmittelpunkt` plus Straßenadresse liefern die Stadt.
- Vorhandene Qualifier und bestehende generische Wohnort-Guards bleiben unverändert.
- Verifikation: `tests/test_weather_context.py` -> `159 passed`, drei Primary-Residence-Street-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `21346a8d fix: parse primary residence street labels`.

### Folgefix 2026-07-19: `Nr.`-Hausnummern

- `Musterstraße Nr. 5`, `Musterstraße Nr 5` und alphanumerische `Nr. 7a` werden als Straßenadresse erkannt.
- `_clean_city` und Ambiguitätsguard behandeln `Nr`-Adressen konsistent; Straßenfragmente werden nicht als Stadt gespeichert.
- Verifikation: `tests/test_weather_context.py` -> `160 passed`, drei Numbered-Street-Address-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `5b5e888c fix: parse numbered street addresses`.

### Folgefix 2026-07-19: Ausgeschriebene Hausnummernmarker

- `Nummer`, `Hausnummer`, `Hausnr.`, `Haus-Nr.` und `Hs.-Nr.` vor Hausnummer werden erkannt.
- Gemeinsamer Marker-Baustein hält Straßenparser, Fallbacks, `_clean_city` und Ambiguitätsguard synchron.
- Verifikation: `tests/test_weather_context.py` -> `161 passed`, fünf Written-House-Number-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a0760401 fix: parse written street number labels`.

### Folgefix 2026-07-19: Stadt vor Straßenadresse ohne Komma

- `Ich wohne in Berlin in der Musterstraße 5` und `an der ...` werden erkannt.
- Straßenadress-Kern ist vom nachfolgenden Trenner getrennt; mehrteilige Städte wie Frankfurt am Main bleiben korrekt.
- Verifikation: `tests/test_weather_context.py` -> `162 passed`, drei City-Before-Street-Smokes, Compound-City-Smokes und `py_compile`/`git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `f2ff3d79 fix: parse city before street addresses`.

### Folgefix 2026-07-19: Beschriftete Stadt-vor-Straße-Sätze

- `Wohnadresse/Wohnsitz/Wohnung liegt in Stadt in/an der Straße` und `ich bin wohnhaft in Stadt in/an der Straße` werden erkannt.
- Arbeits- und Geburtsadressen bleiben ausgeschlossen; mehrteilige Städte bleiben korrekt.
- Verifikation: `tests/test_weather_context.py` -> `163 passed`, vier Labeled-City-Before-Street-Smokes plus Negativ-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `8fc5d4c1 fix: parse labeled city before street`.

### Folgefix 2026-07-19: Nachgestellte Wohnstatusform

- `Ich bin in Stadt in/an der Straße wohnhaft/ansässig/gemeldet/registriert` wird erkannt.
- Komma- und Präpositionsvarianten funktionieren; `geschäftlich` und historische Statuszusätze bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `164 passed`, vier Postposed-Residence-Status-Smokes plus Negativ-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `6f121412 fix: parse postposed residence status`.

### Folgefix 2026-07-19: Beschriftete Statusadresse

- `Wohnhaft:`, `ansässig in`, `gemeldet in`, `registriert:` und `Ich bin aktuell wohnhaft:` mit Straßenadresse werden erkannt.
- Geschäftliche, historische und künftige Statusangaben bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `165 passed`, sechs Labeled-Residence-Status-Smokes plus Negativ-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `da55d3d6 fix: parse labeled residence status`.

### Folgefix 2026-07-19: Status vor Stadt-vor-Straße

- `offiziell/aktuell wohnhaft in Stadt in/an der Straße` wird erkannt.
- Geschäftliche, historische und künftige Statuszusätze bleiben ausgeschlossen; mehrteilige Städte bleiben korrekt.
- Verifikation: `tests/test_weather_context.py` -> `166 passed`, vier Status-City-Before-Street-Smokes plus Negativ-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `43d0fe3a fix: parse status city before street`.

### Folgefix 2026-07-19: Konfliktguard für registrierte Stadt-vor-Straße

- `Meldeadresse/Meldeanschrift/Privatadresse ist in Stadt in/an der Straße` wird erkannt.
- Unterschiedliche Wohn- und Meldeadressen mit Straßenangaben bleiben mehrdeutig und liefern leer; Arbeitsadressen bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `167 passed`, drei Registered-City-Before-Street-Smokes plus drei Konflikt-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `07cc0b18 fix: guard registered city street conflicts`.

### Folgefix 2026-07-19: Ortsart vor Straßenadresse

- `in der Stadt/Gemeinde/Landeshauptstadt Stadt in/an der Straße` und `im Stadtgebiet von Stadt ...` werden erkannt.
- Arbeitskontexte bleiben ausgeschlossen; bestehende Stadt- und Straßenparser bleiben unverändert.
- Verifikation: `tests/test_weather_context.py` -> `168 passed`, vier Locality-Type-Before-Street-Smokes plus Negativ-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `45828e45 fix: parse locality type before street`.

### Folgefix 2026-07-19: Konfliktguard für Ortsart-Adressen

- Beschriftete `Wohn-/Meldeadresse` mit `in der Stadt/im Stadtgebiet` werden erkannt.
- Unterschiedliche Wohn- und Meldeadressen bleiben auch bei Ortsart und Straßenangabe mehrdeutig und liefern leer.
- Verifikation: `tests/test_weather_context.py` -> `169 passed`, Ortsart-Positivsmokes und getrennte Konflikt-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `8048f91b fix: guard locality residence conflicts`.

### Folgefix 2026-07-19: Bare Stadt-vor-Straße-Labels

- `Meldeadresse: in Berlin in der Straße`, `Wohnadresse: Hamburg an der Straße` und `Privatadresse = in Köln ...` werden erkannt.
- Unterschiedliche Wohn-/Meldeadressen bleiben leer; gleiche Stadt und Arbeitsadresse bleiben zulässig.
- Verifikation: `tests/test_weather_context.py` -> `170 passed`, drei Bare-City-Before-Street-Smokes plus drei Konflikt-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `51e582b1 fix: parse bare city street labels`.

### Folgefix 2026-07-19: Bare Ortsart-Labels

- `Meldeadresse: in der Stadt Berlin`, `Wohnadresse: im Stadtgebiet von Hamburg ...` und `Privatadresse = in der Gemeinde Köln` werden erkannt.
- Unterschiedliche Wohn-/Meldeadressen bleiben auch in Ortsartform leer; Arbeitsadressen bleiben zulässig.
- Verifikation: `tests/test_weather_context.py` -> `171 passed`, drei Bare-Locality-Type-Smokes plus Konflikt-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `8747060d fix: parse bare locality street labels`.

### Folgefix 2026-07-19: Status-Ortsart

- `Wohnhaft/ansässig in der Stadt`, `im Stadtgebiet von` und `in der Gemeinde` werden erkannt, auch mit Straßenadresse.
- Geschäftliche, historische und künftige Statuszusätze bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `172 passed`, vier Status-Locality-Type-Smokes plus Negativ-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `ac0de80b fix: parse status locality labels`.

### Folgefix 2026-07-19: Zusammengesetzte Städte vor Straßenadresse

- `Brandenburg an der Havel`, `Frankfurt an der Oder`, `Mülheim an der Ruhr` und `Neustadt an der Weinstraße` bleiben vollständig erhalten.
- Bekannte Compound-City-Namen werden vor generischer `an der`-Straßeninterpretation priorisiert.
- Verifikation: `tests/test_weather_context.py` -> `173 passed`, vier Compound-City-Before-Street-Smokes plus kompletter Compound-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `d6eb0f87 fix: preserve compound cities before streets`.

### Folgefix 2026-07-19: Compound-City in Labels und Status

- Compound-City-Priorität gilt jetzt auch für Wohn-/Meldeadressen und Statussätze vor Straßenadresse.
- Konfliktprüfung bleibt aktiv; unterschiedliche Wohn-/Meldeadressen liefern leer.
- Verifikation: `tests/test_weather_context.py` -> `174 passed`, vier Compound-Labeled-Status-Smokes plus drei Konflikt-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e0f1fedb fix: preserve compound cities in labels`.

## Aktueller Ledger 2026-07-19-Post-Restart-4

- `teebotus.service` aktiv/running, `MainPID 3949354`, Start `2026-07-19 17:38:55 CEST`.
- Neuer Zyklus seit diesem Restart: `0/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Beschriftete Gebietspräzisierung vor Straßenadresse

- Wohnort-, Wohnadress-, Status- und Meldeadress-Formen mit `im nördlichen Berlin`, `im Norden Berlins` sowie `im Bezirk/Stadtteil ... in Berlin` liefern den übergeordneten Ort.
- Genitiv-`s` wird nicht im Stadtnamen gespeichert; unterschiedliche Gebiet-Wohn- und Meldeadressen bleiben mehrdeutig und liefern leer.
- Verifikation: `tests/test_weather_context.py` -> `182 passed`, sechs Gebiet- und Konflikt-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `21b6447f fix: parse labeled area street residences`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-2

- `teebotus.service` aktiv/running, `MainPID 3949354`, Start `2026-07-19 17:38:55 CEST`.
- Neuer Zyklus seit diesem Restart: `8/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Attributive Gebietspräzisierung vor Straßenadresse

- `Berliner/Hamburger/Münchner` vor `Bezirk`, `Stadtteil`, `Innenstadt`, `Zentrum` und ähnlichen Ortsarten mit Straßenadresse werden erkannt.
- Genitive Formen wie `Innenstadt Berlins` werden normalisiert; Wohn-/Meldeadresskonflikte bleiben mehrdeutig und liefern leer.
- Verifikation: `tests/test_weather_context.py` -> `183 passed`, sieben attributive/genitive Gebiet- und Konflikt-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `3264fa36 fix: parse attributive area street residences`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-3

- `teebotus.service` aktiv/running, `MainPID 3949354`, Start `2026-07-19 17:38:55 CEST`.
- Neuer Zyklus seit diesem Restart: `9/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Straßenadressdetails nicht als Stadt

- `Hinterhaus`, `Vorderhaus`, Etagen-, Wohnungs- und einzelne `links/rechts`-Details werden aus späteren Fallback-Kandidaten ausgeschlossen.
- Stadt-vor-Straßenadresse mit solchen Details behält korrekte Stadt; bestehende Detail- und Konfliktformen bleiben unverändert.
- Verifikation: `tests/test_weather_context.py` -> `184 passed`, drei Street-Detail-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `54447028 fix: reject street details as cities`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-4

- `teebotus.service` aktiv/running, `MainPID 3949354`, Start `2026-07-19 17:38:55 CEST`.
- Neuer Zyklus seit diesem Restart: `10/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: PLZ vor Stadt bei Straßenadressen

- `10115 Berlin`, `20095 Hamburg` usw. funktionieren jetzt vor Straßenadresse in Direkt-, Wohnort-, Status- und Meldeadressformen.
- Unterschiedliche PLZ-Wohn- und Meldeadressen bleiben mehrdeutig und liefern leer.
- Verifikation: `tests/test_weather_context.py` -> `185 passed`, vier PLZ-Positivformen plus Konflikt-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `69e83dc2 fix: parse postal city street residences`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-5

- `teebotus.service` aktiv/running, `MainPID 3949354`, Start `2026-07-19 17:38:55 CEST`.
- Neuer Zyklus seit diesem Restart: `11/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: PLZ-Status mit Straßenadresse

- `Ich bin in 10115 Berlin ... wohnhaft`, `Wohnhaft: 10115 Berlin, ...` und Varianten mit Komma/Leerzeichen werden erkannt.
- PLZ-Status mit abweichender Meldeadresse bleibt mehrdeutig und liefert leer.
- Verifikation: `tests/test_weather_context.py` -> `186 passed`, vier Status-Positivformen plus Konflikt-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c29f1a6f fix: parse postal status street forms`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-6

- `teebotus.service` aktiv/running, `MainPID 3949354`, Start `2026-07-19 17:38:55 CEST`.
- Neuer Zyklus seit diesem Restart: `12/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Straßenart `Markt`

- `am Markt 5` wird wie andere Straßenarten erkannt; Stadt bleibt aus Stadt-vor-Straßen-, Label- und Bare-Adressformen erhalten.
- Gemeinsamer `_STREET_TYPE` hält Parser, `_clean_city` und Guards synchron.
- Verifikation: `tests/test_weather_context.py` -> `187 passed`, drei Marktadress-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e43d1413 fix: parse markt street addresses`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-7

- `teebotus.service` aktiv/running, `MainPID 3949354`, Start `2026-07-19 17:38:55 CEST`.
- Neuer Zyklus seit diesem Restart: `13/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Weitere häufige Straßenarten

- `Wall`, `Tor`, `Brücke/Bruecke`, `Bogen`, `Zeile`, `Stein`, `Winkel`, `Kamp`, `Koppel`, `Dorf`, `Feld` und `Wiesen` werden zentral erkannt.
- Bestehende Street-Type-Tests bleiben aktiv; doppelter Testname wurde bereinigt, damit keine Testgruppe überschrieben wird.
- Verifikation: `tests/test_weather_context.py` -> `188 passed`, dreizehn zusätzliche Street-Type-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `001ed14a fix: parse extended street types`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-8

- `teebotus.service` aktiv/running, `MainPID 3949354`, Start `2026-07-19 17:38:55 CEST`.
- Neuer Zyklus seit diesem Restart: `14/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Kommagetrennte Gebietsadressen

- `im Bezirk Kreuzberg, Berlin, Musterstraße 5` und entsprechende Stadtteil-, Label- und Bare-Formen werden erkannt.
- Ambiguitäts- und Multiplicity-Guards akzeptieren vollständige Einzeladressen, blockieren aber weiterhin getrennte Wohn-/Meldeorte.
- Verifikation: `tests/test_weather_context.py` -> `189 passed`, vier Komma-Area-Smokes plus Konfliktfälle, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `f091ad33 fix: parse comma separated area addresses`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-9

- `teebotus.service` aktiv/running, `MainPID 3949354`, Start `2026-07-19 17:38:55 CEST`.
- Neuer Zyklus seit diesem Restart: `15/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Länderpräfixe vor PLZ und Straßenadresse

- `Deutschland`, `Österreich` und `Schweiz` vor Stadt/Straße werden erkannt; vier- und fünfstellige Länder-PLZ funktionieren.
- Multiplicity-/Ambiguity-Guards behandeln vollständige Länderadressen als ein Ziel; separate Meldeadresse bleibt konfliktbehaftet.
- Verifikation: `tests/test_weather_context.py` -> `190 passed`, sechs DE/AT/CH-Smokes plus Konflikt-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `d09799d5 fix: parse country postal street addresses`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-10

- `teebotus.service` aktiv/running, `MainPID 3949354`, Start `2026-07-19 17:38:55 CEST`.
- Neuer Zyklus seit diesem Restart: `16/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Normalisierung geklammerter Stadtteile

- Bekannte Formen wie `Berlin (Kreuzberg)`, `Berlin (Mitte)`, `Hamburg (Altona)` und `Frankfurt am Main (Sachsenhausen)` liefern die übergeordnete Stadt.
- `Halle (Saale)` bleibt als echter zusammengesetzter Ortsname vollständig erhalten.
- Verifikation: `tests/test_weather_context.py` -> `190 passed`, vier Parenthesized-District-Smokes plus Halle-Regression, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `4e13ad1a fix: normalize parenthesized city districts`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-11

- `teebotus.service` aktiv/running, `MainPID 3949354`, Start `2026-07-19 17:38:55 CEST`.
- Neuer Zyklus seit diesem Restart: `17/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Klammerform bei Gebiets-Straßenadressen

- Formen wie `im Bezirk Kreuzberg (Berlin), Musterstraße 5` werden intern in die bestehende Stadt-vor-Straße-Form normalisiert.
- Wohn-, Label-, Arbeitsadress- und Konfliktprüfungen bleiben auf demselben Parserpfad; historische und konkurrierende Adressen bleiben leer.
- Verifikation: `tests/test_weather_context.py` -> `191 passed`, vier Klammer-Gebiets-Smokes plus Konflikt-/Arbeits-/historischer Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `ec9d97b8 fix: normalize parenthesized area addresses`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-12

- `teebotus.service` aktiv/running, `MainPID 3949354`, Start `2026-07-19 17:38:55 CEST`.
- Neuer Zyklus seit diesem Restart: `18/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Geklammerte Straßenadressdetails

- Zusätze wie `(Hinterhaus)`, `(2. OG links)` und `(Wohnung B)` nach der Hausnummer werden vor der bestehenden Stadt-/Straßenanalyse als bekannte Adressdetails behandelt.
- Ortsklammern wie `Berlin (Kreuzberg)` bleiben davon getrennt; historische Wechsel, Arbeitsadressen und Wohn-/Meldekonflikte bleiben geschützt.
- Verifikation: `tests/test_weather_context.py` -> `192 passed`, vier Detail-Smokes plus Konflikt-, Arbeits- und historischer Wechsel-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `95771d14 fix: ignore parenthesized street details`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-13

- `teebotus.service` aktiv/running, `MainPID 3949354`, Start `2026-07-19 17:38:55 CEST`.
- Neuer Zyklus seit diesem Restart: `19/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Stadt-Kommaform und beschreibende Straßennamen

- `Ich wohne in Berlin, Musterstr. 5` wird als Stadt-vor-Straße-Adresse erkannt; der Ambiguitäts-Guard verwirft vollständige Einzeladressen nicht mehr.
- Straßennamen wie `Straße des 17. Juni` funktionieren direkt und nach Label; der Punkt in Datumsbestandteil wird nicht als Satzende fehlinterpretiert.
- Verifikation: `tests/test_weather_context.py` -> `193 passed`, direkte/Label-/Datumsstraßen-Smokes sowie Konflikt-, Arbeits- und historischer Wechsel-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `6dc25148 fix: parse comma city and descriptive streets`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-14

- `teebotus.service` wird nach diesem 20. Code-Fix neu gestartet; vorheriger Prozess: `MainPID 3949354`, Start `2026-07-19 17:38:55 CEST`.
- Neuer Zyklus seit diesem Restart: `0/20` Code-Fixes nach erfolgreicher Verifikation. Kein Push.

### Folgefix 2026-07-19: Zusammengesetzter Ortsname in Straßenadressen

- `Halle (Saale)` wird vor der Regex-Auswertung intern in eine parsebare Form überführt und durch `_KNOWN_COMPOUND_CITY_NAMES` wieder vollständig hergestellt.
- Straßen-, Label-, Melde-, Arbeits- und historische Wechselpfade behalten dadurch den vollständigen Ortsnamen; getrennte Ziele bleiben geschützt.
- Verifikation: `tests/test_weather_context.py` -> `194 passed`, vier Compound-Adress-Smokes plus Konflikt-/Arbeits-/historischer Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `54e929ee fix: preserve compound city names in addresses`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-15

- `teebotus.service` aktiv/running, `MainPID 113726`, Start `2026-07-19 18:58:24 CEST`.
- Neuer Zyklus seit diesem Restart: `1/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Labeladressen mit Stadt vor abgekürzter Straße

- `Wohnadresse`, `Wohnort` und `Meldeadresse` mit Formen wie `Berlin, Musterstr. 5` werden nicht mehr durch Multiplicity-/Ambiguitäts-Guards blockiert.
- Separate Meldeadressen bleiben Konfliktfälle; Arbeitsadressen und gleiche Wohn-/Melde-Stadt bleiben korrekt differenziert.
- Verifikation: `tests/test_weather_context.py` -> `195 passed`, drei Label-Smokes plus Konflikt-/Arbeits-/Unsicherheits-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `29831899 fix: accept labeled city street addresses`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-16

- `teebotus.service` aktiv/running, `MainPID 113726`, Start `2026-07-19 18:58:24 CEST`.
- Neuer Zyklus seit diesem Restart: `2/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Stadtteilklammern mit Straßenabkürzung

- Bekannte Formen wie `Berlin (Mitte)` und `Frankfurt am Main (Sachsenhausen)` werden vor der Auswertung auf die Oberstadt normalisiert, wenn danach eine Adresse folgt.
- `Halle (Saale)` bleibt als zusammengesetzter Ortsname separat erhalten; Wohn-/Melde- und Arbeitsadressschutz bleibt aktiv.
- Verifikation: `tests/test_weather_context.py` -> `196 passed`, 40 Stadtteil-/Straßenkombinationen plus Konflikt-/Arbeits-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `312dd42a fix: normalize district city address variants`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-17

- `teebotus.service` aktiv/running, `MainPID 113726`, Start `2026-07-19 18:58:24 CEST`.
- Neuer Zyklus seit diesem Restart: `3/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: PLZ- und Statusformen mit Straßenabkürzung

- `10115 Berlin, Musterstr. 5` und `Berlin, Musterstr. 5 wohnhaft` werden als vollständige Adressen akzeptiert.
- Ambiguitäts-Guard kennt direkte PLZ-/Statusadressen; getrennte Meldeadressen und unsichere Sätze bleiben geschützt.
- Verifikation: `tests/test_weather_context.py` -> `197 passed`, drei PLZ-/Status-Smokes plus Konflikt-/Unsicherheits-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `488a4938 fix: accept postal status address variants`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-18

- `teebotus.service` aktiv/running, `MainPID 113726`, Start `2026-07-19 18:58:24 CEST`.
- Neuer Zyklus seit diesem Restart: `4/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Genitiv-Gebietsadressen mit Komma

- Formen wie `im Bezirk Mitte Berlins, Musterstr. 5` werden als Berlin erkannt, statt Gebietsname und Stadt zu verkleben.
- Bekannter Bezirk `Kreuzberg` wird als Berlin normalisiert; nicht eindeutig bekannte Ortsteile bleiben ungeklärt.
- Verifikation: `tests/test_weather_context.py` -> `198 passed`, direkte/Label-/Genitiv-Smokes plus Konflikt- und unbekannter-Ortsteil-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `65c514cb fix: parse genitive area street addresses`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-19

- `teebotus.service` aktiv/running, `MainPID 113726`, Start `2026-07-19 18:58:24 CEST`.
- Neuer Zyklus seit diesem Restart: `5/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Gebiets-Suffix nach Straßenadresse

- `Berlin, Musterstr. 5 und Umgebung/Region/Nähe` bleibt als Berlin erkennbar.
- Der Multiplicity-Guard ignoriert den Punkt in `str.`, sodass `Umgebung von Hamburg` nicht fälschlich als Berlin durchrutscht.
- Verifikation: `tests/test_weather_context.py` -> `199 passed`, positive Suffix-Smokes und Mehrziel-Smokes mit `Musterstr.`/`Musterstraße`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `46bbb02c fix: handle area suffix after street address`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-20

- `teebotus.service` aktiv/running, `MainPID 113726`, Start `2026-07-19 18:58:24 CEST`.
- Neuer Zyklus seit diesem Restart: `6/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Stadtadjektiv plus Gebietsbegriff

- `Berliner/Hamburger Umgebung`, `Münchner Gegend`, `Kölner Nähe` und `Hamburger Region` werden mit anschließender Straße auf die bekannte Stadt normalisiert.
- Unbekannte Adjektive und Wohn-/Meldekonflikte bleiben ungeklärt bzw. leer.
- Verifikation: `tests/test_weather_context.py` -> `200 passed`, fünf positive Area-Smokes plus unbekannte-/Konflikt-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `dc6bf269 fix: normalize adjectival city area addresses`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-21

- `teebotus.service` aktiv/running, `MainPID 113726`, Start `2026-07-19 18:58:24 CEST`.
- Neuer Zyklus seit diesem Restart: `7/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Country-Statuslabels

- `Wohnhaft: Österreich, Wien, Musterstr. 5` und `Gemeldet: Schweiz, Zürich, Bahnhofstr. 3` nutzen jetzt denselben Country-Adresspfad wie Wohnadressen.
- Konflikt- und Arbeitsadressschutz wurde im lokalen Guard synchronisiert.
- Verifikation: `tests/test_weather_context.py` -> `201 passed`, Country-Status-Smokes plus Wohn-/Meldekonflikt und Arbeitsadresse, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `5cdc765d fix: parse country status labels`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-22

- `teebotus.service` aktiv/running, `MainPID 113726`, Start `2026-07-19 18:58:24 CEST`.
- Neuer Zyklus seit diesem Restart: `8/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Aktueller Status und Stadtwechsel mit Straßen

- `Ich bin jetzt in Berlin, Musterstr. 5 wohnhaft` wird erkannt.
- `Ich wohne nicht mehr in Berlin, Musterstr. 5, sondern in Hamburg, Hauptweg 7` liefert das neue Ziel.
- Der Konflikt-Guard übernimmt nur den neuen spezifischen Wechselmatch; historische Standardfälle bleiben unverändert und zusätzliche Meldeadressen blockieren.
- Verifikation: `tests/test_weather_context.py` -> `202 passed`, Current-/Change-Smokes plus Unsicherheit, Meldekonflikt und Regressionen, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `609343df fix: parse current and changed street residences`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-23

- `teebotus.service` aktiv/running, `MainPID 113726`, Start `2026-07-19 18:58:24 CEST`.
- Neuer Zyklus seit diesem Restart: `9/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Formulierte Stadtwechsel mit Stadt vor Straße

- `Wohnadresse wechselte/wurde ... von Berlin, Musterstr. 5 auf Hamburg, Hauptweg 7`, `hat sich ... nach ... verlagert` und `Ich bin ... von/nach ... gezogen` werden erkannt.
- Nur die drei neuen Stadt-vor-Straße-Change-Patterns werden im Konflikt-Guard wiederverwendet; alte/neue Adresse wird nicht fälschlich als parallele Wohnadresse behandelt. Eine zusätzliche `Meldeadresse` blockiert weiterhin.
- Verifikation: `tests/test_weather_context.py` -> `203 passed`, positive Move-Formen sowie Melde-/Arbeits-/Unsicherheits-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `5edf014c fix: parse formulated city street moves`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-24

- `teebotus.service` aktiv/running, `MainPID 113726`, Start `2026-07-19 18:58:24 CEST`.
- Neuer Zyklus seit diesem Restart: `10/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Weitere Stadt-vor-Straße-Wechsel

- `Wohnadresse ist jetzt ... statt ...`, `alte Wohnadresse war ..., neue ist ...`, `Wohnadresse: vorher ..., jetzt ...`, `Wohnadresse geändert: ... nach ...` und `von ... nach ...: neue Wohnadresse` werden erkannt.
- Die Wechselpatterns werden im Konflikt-Guard als ein Wohnadressziel behandelt; separate `Meldeadresse`, `Arbeitsadresse` und unsichere Fragen bleiben leer.
- Verifikation: `tests/test_weather_context.py` -> `204 passed`, acht gezielte Positive-/Negativ-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `9ae160c2 fix: parse additional street address moves`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-25

- `teebotus.service` aktiv/running, `MainPID 113726`, Start `2026-07-19 18:58:24 CEST`.
- Neuer Zyklus seit diesem Restart: `11/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Compound-Label nicht als Stadt lesen

- Das allgemeine Residence-Label-Pattern verlangt jetzt Wortgrenze nach `Wohnort`/`Wohnsitz`/ähnlichen Labels. `Wohnortwechsel` wird nicht mehr als Stadt `wechsel` extrahiert.
- Ein echtes `Wohnort: Hamburg` bleibt unverändert.
- Verifikation: `tests/test_weather_context.py` -> `205 passed`, Regression für `Wohnortwechsel` und `Wohnort: Hamburg`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `b092d613 fix: reject compound residence label matches`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-26

- `teebotus.service` aktiv/running, `MainPID 113726`, Start `2026-07-19 18:58:24 CEST`.
- Neuer Zyklus seit diesem Restart: `12/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Umzugsverben mit Stadt vor Straße

- `Ich bin aus/von ... nach ... umgezogen`, `Ich zog von ... nach ...`, `Von ... bin ich nach ... gezogen` und der abgesicherte `Umzug ...: neue Wohnadresse` werden erkannt.
- Freie Bewegungsformulierungen ohne Umzugsverb bleiben ungeklärt; zusätzliche `Meldeadresse` und Fahrten werden nicht als Wohnort übernommen.
- Verifikation: `tests/test_weather_context.py` -> `206 passed`, vier positive Move-Smokes plus Fahrt-/Melde-Negativfälle, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `1f6173bc fix: parse move verb street addresses`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-27

- `teebotus.service` aktiv/running, `MainPID 113726`, Start `2026-07-19 18:58:24 CEST`.
- Neuer Zyklus seit diesem Restart: `13/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Gegenwartsadresse mit Stadt vor Straße

- `Ich habe jetzt ... als Wohnadresse statt ...`, `Wohnanschrift hat sich geändert: neu, früher alt` und `Wohnadresse ist jetzt ... und nicht mehr ...` werden erkannt; Possessiv vor `Wohnadresse` ist optional, `Arbeitsadresse` bleibt ausgeschlossen.
- Separate `Meldeadresse` bleibt konfliktbehaftet und liefert leer.
- Verifikation: `tests/test_weather_context.py` -> `207 passed`, drei positive Gegenwarts-Smokes plus Arbeits-/Melde-Negativfälle, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `bef9da4f fix: parse current residence address phrasing`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-28

- `teebotus.service` aktiv/running, `MainPID 113726`, Start `2026-07-19 18:58:24 CEST`.
- Neuer Zyklus seit diesem Restart: `14/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Strukturierte Umzugsadressen

- Stadt-vor-Straße-Wechsel mit optionaler Postleitzahl (`10115 Berlin`), Klammerdetails (`Hinterhaus`, `2. OG links`) und bekannten Adressübergängen werden erkannt.
- Postal-City wird weiterhin durch `_clean_city` normalisiert; zusätzliche `Meldeadresse` bleibt konfliktbehaftet.
- Verifikation: `tests/test_weather_context.py` -> `208 passed`, Postleitzahl-/Klammer-/Melde-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `b48e7f75 fix: parse structured move addresses`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-29

- `teebotus.service` aktiv/running, `MainPID 113726`, Start `2026-07-19 18:58:24 CEST`.
- Neuer Zyklus seit diesem Restart: `15/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Gleiche Wohn- und Meldeadresse

- `Meldeadresse ist auch Berlin` wird im Konflikt-Guard als `Berlin`, nicht als `auch Berlin`, erfasst.
- `_clean_city` normalisiert führendes `auch`; zwei Adressen in derselben Stadt erzeugen keinen falschen Konflikt.
- Verifikation: `tests/test_weather_context.py` -> `209 passed`, zwei Same-City-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `32caf811 fix: normalize same-city registration context`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-30

- `teebotus.service` aktiv/running, `MainPID 113726`, Start `2026-07-19 18:58:24 CEST`.
- Neuer Zyklus seit diesem Restart: `16/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Pronomen bei Adresswechsel

- `Wohnadresse war Berlin, ... Jetzt ist sie/diese Hamburg, ...` wird als aktuelles Ziel `Hamburg` erkannt.
- Separate `Meldeadresse` blockiert weiterhin.
- Verifikation: `tests/test_weather_context.py` -> `210 passed`, zwei Pronomen-Smokes plus Melde-Negativfall, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `82bd35ee fix: parse pronoun residence address changes`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-31

- `teebotus.service` aktiv/running, `MainPID 113726`, Start `2026-07-19 18:58:24 CEST`.
- Neuer Zyklus seit diesem Restart: `17/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Erweiterte Pronomen-Übergänge

- Pronomen-Wechsel akzeptieren jetzt `lautet`, `Seitdem`, `bleibt aber`, `die ist jetzt` sowie vorangestelltes `Früher/Zuvor war ...`.
- Zeit-/Pronomenvarianten bleiben auf Wohnadresswechsel mit zwei vollständigen Straßenadressen begrenzt.
- Verifikation: `tests/test_weather_context.py` -> `210 passed`, sieben zusätzliche Pronomen-Smokes plus bestehender Melde-Negativfall, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `9a726bcd fix: expand pronoun residence transitions`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-32

- `teebotus.service` aktiv/running, `MainPID 113726`, Start `2026-07-19 18:58:24 CEST`.
- Neuer Zyklus seit diesem Restart: `18/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Stadt vor Wohnadresslabel

- `Berlin war meine alte Wohnadresse, Hamburg ist jetzt meine neue Wohnadresse` und die entsprechende `Wohnanschrift`-Variante werden erkannt.
- Arbeitsadressen und zusätzliche `Meldeadresse` bleiben ausgeschlossen bzw. konfliktbehaftet.
- Verifikation: `tests/test_weather_context.py` -> `211 passed`, zwei positive Label-Smokes plus Arbeits-/Melde-Negativfälle, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a9e9b2ec fix: parse city before residence label changes`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-33

- `teebotus.service` aktiv/running, `MainPID 113726`, Start `2026-07-19 18:58:24 CEST`.
- Neuer Zyklus seit diesem Restart: `19/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Straße vor Wohnadresslabel

- `Berlin, Musterstr. 5 war meine alte Wohnadresse; Hamburg, Hauptweg 7 ist jetzt meine neue` und `frühere Wohnadresse Berlin, Musterstr. 5 ist vorbei, jetzt Hamburg, Hauptweg 7` werden erkannt.
- Arbeitsadressen und zusätzliche `Meldeadresse` bleiben ausgeschlossen bzw. konfliktbehaftet.
- Verifikation: `tests/test_weather_context.py` -> `212 passed`, zwei positive Street-before-Label-Smokes plus Arbeits-/Melde-Negativfälle, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `4c52ae80 fix: parse street before residence label changes`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-34

- `teebotus.service` aktiv/running, `MainPID 450172`, Start `2026-07-19 20:13:41 CEST`.
- Zyklus abgeschlossen: `20/20` Code-Fixes. Kein Push. Neuer Zyklus startet ab nächstem Code-Fix mit `1/20`.

### Folgefix 2026-07-19: Informelle Straßen-vor-Label-Wechsel

- `Berlin, Musterstr. 5 war meine alte Wohnadresse, jetzt Hamburg, Hauptweg 7` und `ist nicht mehr meine Wohnadresse, sondern ...` werden erkannt.
- Arbeitsadressen sowie zusätzliche `Meldeadresse` bleiben ausgeschlossen bzw. konfliktbehaftet.
- Verifikation: `tests/test_weather_context.py` -> `213 passed`, zwei positive informelle Move-Smokes plus Arbeits-/Melde-Negativfälle, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `9cab7d3a fix: parse informal street first moves`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-35

- `teebotus.service` aktiv/running, `MainPID 450172`, Start `2026-07-19 20:13:41 CEST`.
- Neuer Zyklus seit diesem Restart: `1/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Doppelpunkt-Labels für alte/neue Adresse

- `Alte Wohnadresse: Berlin, ...; Neue Wohnadresse: Hamburg, ...` und `Meine alte Wohnadresse: ...; Meine neue: ...` werden erkannt.
- Der Multiplicity-Guard behandelt das explizite alte/neue Paar als Wechsel; Arbeitsadresse und zusätzliche `Meldeadresse` bleiben leer.
- Verifikation: `tests/test_weather_context.py` -> `214 passed`, zwei positive Colon-Label-Smokes plus Arbeits-/Melde-Negativfälle, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `170aec31 fix: preserve colon labelled address moves`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-36

- `teebotus.service` aktiv/running, `MainPID 450172`, Start `2026-07-19 20:13:41 CEST`.
- Neuer Zyklus seit diesem Restart: `2/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Inline-Zeitlabels bei Wohnadressen

- `Wohnadresse alt: ...; Wohnadresse neu: ...`, `Wohnadresse früher ..., heute ...` und `Wohnadresse ..., jetzt ...` werden erkannt.
- Der Multiplicity-Guard behandelt diese expliziten Zeitpaare als Wechsel; zusätzliche `Meldeadresse` bleibt konfliktbehaftet.
- Verifikation: `tests/test_weather_context.py` -> `215 passed`, drei positive Inline-Label-Smokes plus Melde-Negativfall, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `f815dbcc fix: parse inline labelled residence times`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-37

- `teebotus.service` aktiv/running, `MainPID 450172`, Start `2026-07-19 20:13:41 CEST`.
- Neuer Zyklus seit diesem Restart: `3/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Labelgebundene Von-nach-Änderungen

- `Wohnadresse von Berlin, ... zu/nach Hamburg, ... geändert/verlegt` wird erkannt.
- Arbeitsadresse und zusätzliche `Meldeadresse` bleiben ausgeschlossen bzw. konfliktbehaftet.
- Verifikation: `tests/test_weather_context.py` -> `216 passed`, zwei positive From-to-Smokes plus Arbeits-/Melde-Negativfälle, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `82316f36 fix: parse labelled from-to address moves`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-38

- `teebotus.service` aktiv/running, `MainPID 450172`, Start `2026-07-19 20:13:41 CEST`.
- Neuer Zyklus seit diesem Restart: `4/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Passive und nominale Wohnadresswechsel

- `Wohnadresse wurde von ... nach ... verlegt/geändert` und `Umzug der Wohnadresse von ... nach ... ist erfolgt` werden erkannt.
- Arbeitsadresse und zusätzliche `Meldeadresse` bleiben ausgeschlossen bzw. konfliktbehaftet.
- Verifikation: `tests/test_weather_context.py` -> `217 passed`, drei positive Passive-/Nominal-Smokes plus Arbeits-/Melde-Negativfälle, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `1472379d fix: parse passive residence address moves`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-39

- `teebotus.service` aktiv/running, `MainPID 450172`, Start `2026-07-19 20:13:41 CEST`.
- Neuer Zyklus seit diesem Restart: `5/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Einzeilige Label-Separatoren

- `Wohnadresse: Berlin, ... ->/nach Hamburg, ...` wird als Wechsel erkannt.
- Arbeitsadresse und zusätzliche `Meldeadresse` bleiben ausgeschlossen bzw. konfliktbehaftet.
- Verifikation: `tests/test_weather_context.py` -> `218 passed`, zwei positive Separator-Smokes plus Arbeits-/Melde-Negativfälle, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `36be3fd6 fix: parse colon separator address moves`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-40

- `teebotus.service` aktiv/running, `MainPID 450172`, Start `2026-07-19 20:13:41 CEST`.
- Neuer Zyklus seit diesem Restart: `6/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Alternativmarker bei Wohnorten

- `entweder ... oder ...` wird nicht mehr als Stadtfragment gespeichert; alternative Adressziele bleiben ungeklärt.
- Verifikation: `tests/test_weather_context.py` -> `219 passed`, zwei Alternative-/Frage-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c9596c56 fix: reject either-or residence targets`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-41

- `teebotus.service` aktiv/running, `MainPID 450172`, Start `2026-07-19 20:13:41 CEST`.
- Neuer Zyklus seit diesem Restart: `7/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Unabgeschlossene Straßenumzüge

- `Ich ziehe von ... nach ...` und `Ich ziehe gerade von ... nach ...` werden nicht mehr als aktueller Wohnort übernommen.
- Abgeschlossene Form `Ich bin von ... nach ... gezogen` bleibt gültig.
- Verifikation: `tests/test_weather_context.py` -> `220 passed`, zwei Future-Smokes plus abgeschlossener Move-Regression, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `28f1b380 fix: reject unfinished street moves`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-42

- `teebotus.service` aktiv/running, `MainPID 450172`, Start `2026-07-19 20:13:41 CEST`.
- Neuer Zyklus seit diesem Restart: `8/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Geplante Wohnadresswechsel

- `Ich plane/beabsichtige, meine Wohnadresse von ... nach ... zu verlegen` wird als Zukunft verworfen.
- Ein bestehender aktueller Wohnort vor einem späteren Plan bleibt erhalten.
- Verifikation: `tests/test_weather_context.py` -> `221 passed`, zwei Plan-Smokes plus Current-before-plan-Regression, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `8c13df14 fix: reject planned address moves`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-43

- `teebotus.service` aktiv/running, `MainPID 450172`, Start `2026-07-19 20:13:41 CEST`.
- Neuer Zyklus seit diesem Restart: `9/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Straßenfragment im Mehrziel-Guard

- Bei `Ich wohne in Berlin, Musterstr. 5 und besuche Hamburg, Hauptweg 7` wird `Musterstr` nicht mehr als zweite Stadt interpretiert.
- Besuchs-/Reisezielschutz bleibt aktiv.
- Verifikation: `tests/test_weather_context.py` -> `222 passed`, zwei Residence-before-Visit-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `935f4866 fix: ignore street fragments in residence ambiguity`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-44

- `teebotus.service` aktiv/running, `MainPID 450172`, Start `2026-07-19 20:13:41 CEST`.
- Neuer Zyklus seit diesem Restart: `10/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Zeitlich mehrere Wohnadressen

- `Ich wohne in Berlin, ... und lebe zeitweise/abwechselnd in Hamburg, ...` wird nicht auf den zweiten Ort reduziert, sondern bleibt ungeklärt.
- Verifikation: `tests/test_weather_context.py` -> `223 passed`, zwei temporale Mehrfach-Wohn-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `cfc4b3d9 fix: reject temporal multiple street residences`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-45

- `teebotus.service` aktiv/running, `MainPID 450172`, Start `2026-07-19 20:13:41 CEST`.
- Neuer Zyklus seit diesem Restart: `11/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Hauptwohnung gegenüber Zweitwohnung

- `Meine Hauptwohnung ist in Berlin, ...` wird als Hauptwohnsitz erkannt; `Zweitwohnung` wird nicht fälschlich als Wohnort übernommen.
- Bei Haupt- und Zweitwohnung gewinnt primäre `Berlin`-Adresse.
- Verifikation: `tests/test_weather_context.py` -> `224 passed`, drei Main-/Secondary-Home-Smokes, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `3b4fa631 fix: recognize main home street addresses`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-46

- `teebotus.service` aktiv/running, `MainPID 450172`, Start `2026-07-19 20:13:41 CEST`.
- Neuer Zyklus seit diesem Restart: `12/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Hauptwohnung vor Zweitwohnung mit `und`

- `Hauptwohnung befindet sich in Berlin, ... und die Zweitwohnung in Hamburg, ...` akzeptiert Anschlusswörter nach der primären Straßenadresse.
- Primäre `Berlin`-Adresse bleibt erhalten.
- Verifikation: `tests/test_weather_context.py` -> `224 passed`, Main-before-Secondary-Smoke, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `cfc84244 fix: preserve main home before secondary home`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-47

- `teebotus.service` aktiv/running, `MainPID 450172`, Start `2026-07-19 20:13:41 CEST`.
- Neuer Zyklus seit diesem Restart: `13/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Primäre Wohnung nach „Ich habe"

- `Ich habe eine/meine Wohnung in Berlin, Musterstr. 5` wird erkannt.
- `Zweitwohnung` und `Ferienwohnung` bleiben ausgeschlossen; bei primärer Wohnung plus Nebenwohnung gewinnt Berlin.
- Verifikation: `tests/test_weather_context.py` -> `225 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `93fc9482 fix: recognize primary owned homes`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-48

- `teebotus.service` aktiv/running, `MainPID 450172`, Start `2026-07-19 20:13:41 CEST`.
- Neuer Zyklus seit diesem Restart: `14/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Städtenamen mit `bin` am Anfang

- `_clean_city` verwirft `Binz` und `Bingen` nicht mehr als vermeintliche `bin...`-Verbfragmente.
- Verbphrase-Schutz bleibt für das eigenständige Wort `bin` aktiv.
- Verifikation: `tests/test_weather_context.py` -> `226 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `d8369462 fix: accept cities beginning with bin`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-49

- `teebotus.service` aktiv/running, `MainPID 450172`, Start `2026-07-19 20:13:41 CEST`.
- Neuer Zyklus seit diesem Restart: `15/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Parenthesized compound city `Frankfurt (Oder)`

- `Frankfurt (Oder)` wird nicht mehr als logisches `oder`/Mehrfachwohnort fehlklassifiziert.
- Bestehende Compound-Städte und echte alternative Wohnorte bleiben getrennt behandelt.
- Verifikation: `tests/test_weather_context.py` -> `226 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `1e77216e fix: preserve parenthesized compound cities`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-50

- `teebotus.service` aktiv/running, `MainPID 450172`, Start `2026-07-19 20:13:41 CEST`.
- Neuer Zyklus seit diesem Restart: `16/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Casefold-Normalisierung mit `ß`

- `Neustadt an der Weinstraße` wird auch bei komplett kleingeschriebener Eingabe auf kanonische Schreibweise normalisiert.
- Mapping-Schlüssel folgt jetzt dem verwendeten `.casefold()`-Verhalten.
- Verifikation: `tests/test_weather_context.py` -> `226 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `73c02a5f fix: normalize sharp-s compound city names`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-51

- `teebotus.service` aktiv/running, `MainPID 450172`, Start `2026-07-19 20:13:41 CEST`.
- Neuer Zyklus seit diesem Restart: `17/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Kollision langer Wohnort-Memory-IDs

- `_city_id_token` hängt bei abgeschnittenen Städtenamen Hash-Suffix an.
- Unterschiedliche lange Städte mit identischem 48-Zeichen-Präfix überschreiben sich nicht mehr; kurze bestehende IDs bleiben stabil.
- Verifikation: `tests/test_weather_context.py` -> `227 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `80689ded fix: prevent long city memory id collisions`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-52

- `teebotus.service` aktiv/running, `MainPID 450172`, Start `2026-07-19 20:13:41 CEST`.
- Neuer Zyklus seit diesem Restart: `18/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Aktivitätspräfixe in Ortsnamen

- Aktivitätsfilter erkennt konkrete Verbformen statt beliebiger Wortpräfixe.
- `Gehrden`, `Reiskirchen`, `Machern`, `Sehnde` und `Treffurt` werden nicht mehr als Arbeit-/Reisefragmente verworfen.
- Verifikation: `tests/test_weather_context.py` -> `228 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `078fe770 fix: avoid activity prefix city false negatives`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-53

- `teebotus.service` aktiv/running, `MainPID 450172`, Start `2026-07-19 20:13:41 CEST`.
- Neuer Zyklus seit diesem Restart: `19/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Ortsname `Fahren` gegen Fahrverb

- Der gültige Ortsname `Fahren` wird nicht mehr als Infinitivfragment `fahren` verworfen.
- Konkrete Fahrformen mit Flexionsendung bleiben im Aktivitätsfilter.
- Verifikation: `tests/test_weather_context.py` -> `228 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `f745a1ef fix: accept fahren residence town`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-54

- Vor Restart: `teebotus.service` aktiv/running, `MainPID 450172`, Start `2026-07-19 20:13:41 CEST`.
- Neuer Zyklus abgeschlossen: `20/20` Code-Fixes. Restart jetzt erforderlich; kein Push.

## Aktueller Ledger 2026-07-19-Post-Restart-4-55

- `teebotus.service` nach Zyklusrestart aktiv/running, `MainPID 747309`, Start `2026-07-19 21:20:05 CEST`.
- Neuer Zyklus seit diesem Restart: `0/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Wohnort neben besessenem Zweitobjekt

- `Ich wohne in Berlin und besitze ein Haus/eine Wohnung in Hamburg` behält Berlin als Wohnort.
- Besitzformeln werden nicht als zweites Wohnziel behandelt; echte zweite Wohnformeln bleiben mehrdeutig.
- Verifikation: `tests/test_weather_context.py` -> `229 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `52e559c1 fix: preserve residence beside owned property`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-56

- `teebotus.service` aktiv/running, `MainPID 747309`, Start `2026-07-19 21:20:05 CEST`.
- Neuer Zyklus seit diesem Restart: `1/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Wohnort neben Objektverwaltung

- `vermiete`, `verkaufe`, `verwalte`, `renoviere`, `saniere` und `nutze` werden in Anschluss an einen Wohnsatz nicht als zweites Wohnziel behandelt.
- `miete` bleibt bewusst mehrdeutig, weil es eine echte Wohnungsanmietung sein kann.
- Verifikation: `tests/test_weather_context.py` -> `230 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `0c50f48e fix: preserve residence beside property activity`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-57

- `teebotus.service` aktiv/running, `MainPID 747309`, Start `2026-07-19 21:20:05 CEST`.
- Neuer Zyklus seit diesem Restart: `2/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Wohnangaben anderer Personen

- `meine Freundin/meine Eltern wohnen in Hamburg` wird nicht als eigener Wohnort übernommen.
- Eigener Wohnort bleibt bei Komma- und `und`-Satzform in Berlin.
- Verifikation: `tests/test_weather_context.py` -> `231 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `edc89ca3 fix: ignore other people residence claims`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-58

- `teebotus.service` aktiv/running, `MainPID 747309`, Start `2026-07-19 21:20:05 CEST`.
- Neuer Zyklus seit diesem Restart: `3/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Fremde Wohnortlabels nach eigener Stadt

- `Hamburg ist der Wohnort meiner Freundin/Eltern` wird nicht als eigener Wohnort ausgewertet.
- Das gilt für Komma- und `und`-Verknüpfung; eigener Wohnort Berlin bleibt erhalten.
- Verifikation: `tests/test_weather_context.py` -> `231 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `8e65bb23 fix: ignore other person residence labels`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-59

- `teebotus.service` aktiv/running, `MainPID 747309`, Start `2026-07-19 21:20:05 CEST`.
- Neuer Zyklus seit diesem Restart: `4/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Wohnortlabels von Organisationen

- `Wohnort meiner Firma/meines Arbeitgebers` wird nicht als eigener User-Wohnort gewertet.
- Organisationen, Schulen und Betriebe folgen derselben Fremdträger-Regel wie Personen.
- Verifikation: `tests/test_weather_context.py` -> `231 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `0959c2b2 fix: ignore organization residence labels`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-60

- `teebotus.service` aktiv/running, `MainPID 747309`, Start `2026-07-19 21:20:05 CEST`.
- Neuer Zyklus seit diesem Restart: `5/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Grammatische Fremdlabel-Varianten

- Fremde Wohnorte mit `von meiner`, `der`, `dem`, `den` und ähnlichen Präfixen werden nicht als eigener Ort übernommen.
- Organisationen und Personen bleiben über Kasus-/Artikelvarianten geschützt.
- Verifikation: `tests/test_weather_context.py` -> `231 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `51565b43 fix: handle inflected foreign residence labels`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-61

- `teebotus.service` aktiv/running, `MainPID 747309`, Start `2026-07-19 21:20:05 CEST`.
- Neuer Zyklus seit diesem Restart: `6/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

## Vault-Migration 2026-07-19

- Kanonischer Default-Vault fuer alle Instanzen ist jetzt `/home/teladi/Dokumente/Obsidian_Vaults/Teladi_Programming`.
- `TeeBotus/artifact_outputs.py` fuehrt den Vault-Pfad zentral; Standardausgaben gehen nach `Teladi_Programming/incomming`.
- `TeeBotus/runtime/codex_command.py` nutzt den Bauplanpfad unter `Teladi_Programming/Projekte/TeeBotus/Bauplaene!`.
- `.env` wurde lokal auf den neuen `TEEBOTUS_OBSIDIAN_INCOMING_DIR` umgestellt; der alte `Teladi_Def_Obs_Vault` bleibt unangetastet und ist EOL.
- Der aktuelle externe Bauplanstand wurde nach `Teladi_Programming/Projekte/TeeBotus/Bauplaene!` migriert. Der alte Plan wird nicht weiter gepflegt.
- Verifikation: 150 fokussierte Tests gruen, `py_compile` gruen, `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-/Konfigurationscommit: `2a95628f config: switch default Obsidian vault to Teladi Programming`.
- `teebotus.service` bleibt bis zum planmaessigen `20/20`-Restart unveraendert laufend; neue Umgebung greift beim naechsten Restart.

## Aktueller Ledger 2026-07-19-Post-Restart-4-62

- `teebotus.service` aktiv/running, `MainPID 747309`, Start `2026-07-19 21:20:05 CEST`.
- Neuer Zyklus seit diesem Restart: `7/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Weitere Fremdpersonen bei Wohnortlabels

- `Frau`, `Mann`, `Ehepartner`, `Chef` und `Vorgesetzte` werden bei fremden Wohnortangaben wie Personen behandelt.
- Die gemeinsame Label-Liste verhindert sowohl falsche Ueberschreibung durch `Hamburg ist der Wohnort meiner Frau` als auch falsche Mehrdeutigkeit bei `Ich wohne in Berlin und meine Frau wohnt in Hamburg`.
- Verifikation: `tests/test_weather_context.py` -> `232 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `7a14b886 fix: ignore common foreign residence labels`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-63

- `teebotus.service` aktiv/running, `MainPID 747309`, Start `2026-07-19 21:20:05 CEST`.
- Neuer Zyklus seit diesem Restart: `8/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Hauptwohnung ohne Strassenadresse

- `Meine Hauptwohnung ist in Berlin, meine Zweitwohnung in Hamburg` liefert jetzt Berlin als Primaerwohnort.
- Das gilt auch fuer `befindet sich` und `und`-Verknuepfungen; eine explizite Zweitwohnung ueberschreibt den Hauptort nicht.
- Verifikation: `tests/test_weather_context.py` -> `232 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `aa10c31c fix: recognize primary home without street address`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-64

- `teebotus.service` aktiv/running, `MainPID 747309`, Start `2026-07-19 21:20:05 CEST`.
- Neuer Zyklus seit diesem Restart: `9/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Zeitliche Fremdorte nicht als Konflikt

- Historische Adressen und zukuenftige Wohnorte werden aus Konflikt-/Mehrfachwohnortmengen ausgeschlossen.
- `Ich wohne in Berlin, meine alte Adresse ist in Hamburg` und `Mein zukuenftiger Wohnort ist Hamburg` behalten Berlin als aktuellen Wohnort.
- Verifikation: `tests/test_weather_context.py` -> `232 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `992d8cbd fix: ignore temporal residence conflicts`.

## Aktueller Ledger 2026-07-19-Post-Restart-4-65

- `teebotus.service` aktiv/running, `MainPID 747309`, Start `2026-07-19 21:20:05 CEST`.
- Neuer Zyklus seit diesem Restart: `10/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Weitere Fremdpersonen und Kasusformen

- Familien-, Partner-, Nachbarschafts-, Betreuungs- und medizinische Rollen werden in Fremdwohnortlabels erkannt.
- Kasus-/Pluralformen wie `meines Arztes`, `meiner Nachbarn` und `meiner Großeltern` ueberschreiben den eigenen Wohnort nicht mehr.
- Verifikation: `tests/test_weather_context.py` -> `232 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `53d80e86 fix: cover additional foreign residence labels`.

## Aktueller Ledger 2026-07-19-Post-Restart-5-00

- `teebotus.service` nach planmaessigem Restart aktiv/running, `MainPID 929669`, Start `2026-07-19 22:00:21 CEST`.
- Neuer Zyklus seit diesem Restart: `0/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.
- Der Prozess laedt jetzt die kanonische Vault-Konfiguration aus `Teladi_Programming`; der alte Vault bleibt EOL und unangetastet.

## Aktueller Ledger 2026-07-19-Post-Restart-5-01

- `teebotus.service` aktiv/running, `MainPID 929669`, Start `2026-07-19 22:00:21 CEST`.
- Neuer Zyklus seit diesem Restart: `1/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Weitere zusammengesetzte Stadtnamen

- `Weiden in der Oberpfalz` und `Weil am Rhein` bleiben vollstaendig erhalten.
- Das gilt fuer normale Wohnortsaetze und Wohnort plus Strassenadresse.
- Verifikation: `tests/test_weather_context.py` -> `232 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `0c6fc309 fix: preserve additional compound city names`.

## Aktueller Ledger 2026-07-19-Post-Restart-5-02

- `teebotus.service` aktiv/running, `MainPID 929669`, Start `2026-07-19 22:00:21 CEST`.
- Neuer Zyklus seit diesem Restart: `2/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Vollstaendige Compound-City-Matches priorisieren

- Generische `bei`-/`in`-Patterns schneiden bekannte zusammengesetzte Ortsnamen nicht mehr auf den letzten Teil herunter.
- `Neustadt bei Coburg` bleibt vollstaendig erhalten; der Schutz gilt fuer alle zentral registrierten Compound-City-Namen und Trailing-Punktuation.
- Verifikation: `tests/test_weather_context.py` -> `232 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `b489756f fix: prioritize full compound city matches`.

## Aktueller Ledger 2026-07-19-Post-Restart-5-03

- `teebotus.service` aktiv/running, `MainPID 929669`, Start `2026-07-19 22:00:21 CEST`.
- Neuer Zyklus seit diesem Restart: `3/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Inflektierte Organisations-/Institutionslabels

- `Unternehmen`, `Betriebe`, `Vereine`, Firmenplural sowie Praxis-, Klinik-, Hochschul- und Behördenformen werden als Fremdtraeger erkannt.
- Solche Orte ueberschreiben den eigenen Wohnort nicht mehr.
- Verifikation: `tests/test_weather_context.py` -> `232 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `1f1562b0 fix: cover inflected organization residence labels`.

## Aktueller Ledger 2026-07-19-Post-Restart-5-04

- `teebotus.service` aktiv/running, `MainPID 929669`, Start `2026-07-19 22:00:21 CEST`.
- Neuer Zyklus seit diesem Restart: `4/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Regionale Compound-City-Namen

- `Buchholz in der Nordheide`, `Freiburg im Breisgau`, `Freiberg am Neckar`, `Burg auf Fehmarn`, `Dillingen an der Donau` und `Neumarkt in der Oberpfalz` werden vollstaendig gespeichert.
- Plaintext- und Strassenadressformen nutzen denselben zentralen Compound-Schutz.
- Verifikation: `tests/test_weather_context.py` -> `232 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `9bfc037e fix: preserve regional compound city names`.

## Aktueller Ledger 2026-07-19-Post-Restart-5-05

- `teebotus.service` aktiv/running, `MainPID 929669`, Start `2026-07-19 22:00:21 CEST`.
- Neuer Zyklus seit diesem Restart: `5/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Slash-qualifizierte Stadtnamen

- `Mühlhausen/Thüringen`, `Schwedt/Oder` und `Wittstock/Dosse` werden als offizielle Compound-Cities erkannt.
- Der Slash loest dort keine falsche Mehrfachwohnortregel aus; Plaintext und Strassenadresse bleiben stabil.
- Verifikation: `tests/test_weather_context.py` -> `232 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `38c8955b fix: preserve slash-qualified city names`.

## Aktueller Ledger 2026-07-19-Post-Restart-5-06

- `teebotus.service` aktiv/running, `MainPID 929669`, Start `2026-07-19 22:00:21 CEST`.
- Neuer Zyklus seit diesem Restart: `6/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Region-zu-Stadt-Aufloesung

- `Bayern, in München`, `Nordrhein-Westfalen, in Köln` und `NRW, in Köln` liefern jetzt die Stadt.
- Bare `NRW` bleibt wie andere Regionen kein Wohnort; der Alias wird nicht als Stadt gespeichert.
- Verifikation: `tests/test_weather_context.py` -> `232 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `599f16ab fix: resolve region-prefixed residence cities`.

## Aktueller Ledger 2026-07-19-Post-Restart-5-07

- `teebotus.service` aktiv/running, `MainPID 929669`, Start `2026-07-19 22:00:21 CEST`.
- Neuer Zyklus seit diesem Restart: `7/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Kopula-Suffixe in Negationssaetzen

- `Berlin ist nicht mein Wohnort, aber Hamburg ist es/bleibt es` liefert jetzt nur Hamburg.
- Generische Treffer schleppen `ist es` oder `bleibt es` nicht mehr in den gespeicherten Stadtnamen.
- Verifikation: `tests/test_weather_context.py` -> `232 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `36750a8a fix: trim copula residence suffixes`.

## Aktueller Ledger 2026-07-19-Post-Restart-5-08

- `teebotus.service` aktiv/running, `MainPID 929669`, Start `2026-07-19 22:00:21 CEST`.
- Neuer Zyklus seit diesem Restart: `8/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Beruflich/dienstlich qualifizierte Wohnorte

- `Ich lebe in Berlin, wohne aber beruflich in Hamburg.` liefert jetzt Hamburg statt des frueheren allgemeinen Berlin-Treffers.
- `Ich wohne dienstlich in Hamburg.` wird erkannt; `arbeite ... in Hamburg` und `beruflich ... ansaessig` bleiben ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `232 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `b59d495b fix: recognize qualified residence statements`.

## Aktueller Ledger 2026-07-19-Post-Restart-5-10

- `teebotus.service` aktiv/running, `MainPID 929669`, Start `2026-07-19 22:00:21 CEST`.
- Neuer Zyklus seit diesem Restart: `10/20` Code-Fixes. Kein Push. Restart erst bei `20/20` Commits.

### Folgefix 2026-07-19: Fragevorspann vor Wohnortantwort

- `Weißt du, wo ich wohne? In Köln.` liefert jetzt Köln statt des Fragevorspanns `Weißt du`.
- Normale Relativform `Köln, wo ich wohne.` bleibt erkennbar.
- Verifikation: `tests/test_weather_context.py` -> `232 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `bc2412ea fix: ignore question prefixes as cities`.

## Aktueller Ledger 2026-07-19-Post-Restart-5-11

- `teebotus.service` aktiv/running, `MainPID 929669`, Start `2026-07-19 22:00:21 CEST`.
- Neuer Zyklus seit diesem Restart: `11/20` Code-Fixes. Dieser Plan-Commit erreicht den 20-Commit-Restartpunkt; danach Service-Restart.

### Folgefix 2026-07-19: Kurzform `genauer:`

- `Ich lebe in Köln, genauer: Bonn.` liefert jetzt Bonn wie die bereits unterstuetzte Form `genauer gesagt:`.
- Verifikation: `tests/test_weather_context.py` -> `232 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `0111779d fix: parse shorthand residence clarifications`.

## Aktueller Ledger 2026-07-19-Post-Restart-5-09

- `teebotus.service` aktiv/running, `MainPID 929669`, Start `2026-07-19 22:00:21 CEST`.
- Neuer Zyklus seit diesem Restart: `9/20` Code-Fixes. Kein Push. Restart erst bei `20/20`.

### Folgefix 2026-07-19: Verneinte Mehrfachwohnorte

- `Ich wohne weder in Hamburg noch in Berlin.` liefert jetzt keinen Wohnort statt des falschen Stadtnamens `weder`.
- Eindeutige Einzelangabe `Ich wohne in Köln.` bleibt unveraendert.
- Verifikation: `tests/test_weather_context.py` -> `232 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `93e11163 fix: reject neither residence claims`.

## Aktueller Ledger 2026-07-19-Post-Restart-6-00

- `systemctl --user restart teebotus.service` erfolgreich.
- Service aktiv/running, `MainPID 1147780`, Start `2026-07-19 22:49:53 CEST`.
- Kanonischer Incoming-Vault im Prozess: `Teladi_Programming/incomming`.
- Neuer Zyklus seit diesem Restart: `0/20` Code-Fixes. Kein Push.
- Plan-Katalog und Teilung: `935919c5 docs: catalog and split active build plans`.

## Aktueller Ledger 2026-07-19-Post-Restart-6-01

- `teebotus.service` aktiv/running, `MainPID 1147780`, Start `2026-07-19 22:49:53 CEST`.
- Neuer Zyklus seit diesem Restart: `1/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Hauptwohnung ohne Strassenadresse

- `Ich habe eine Hauptwohnung in Berlin und eine Zweitwohnung in Hamburg.` liefert jetzt Berlin.
- Eine reine Zweitwohnung bleibt ausgeschlossen; Strassenadress-Varianten bleiben unveraendert.
- Verifikation: `tests/test_weather_context.py` -> `232 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `259c0fff fix: recognize primary home without street address`.

## Aktueller Ledger 2026-07-19-Post-Restart-6-02

- `teebotus.service` aktiv/running, `MainPID 1147780`, Start `2026-07-19 22:49:53 CEST`.
- Neuer Zyklus seit diesem Restart: `2/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: City-only-Adresswechsel

- `Meine fruehere Adresse war Koeln, meine aktuelle ist Bonn.` liefert jetzt Bonn.
- Eine einzelne alte Adresse bleibt ausgeschlossen; der Fix braucht keinen Strassenadress-Parser.
- Verifikation: `tests/test_weather_context.py` -> `232 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e6f2e37c fix: parse city-only address changes`.

## Aktueller Ledger 2026-07-19-Post-Restart-6-03

- `teebotus.service` aktiv/running, `MainPID 1147780`, Start `2026-07-19 22:49:53 CEST`.
- Neuer Zyklus seit diesem Restart: `3/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Wohnortlabel-Grammatik

- `Meine Wohnadresse ist jetzt Köln.` und `Seit 2020 bin ich in Köln gemeldet.` werden erkannt.
- `Köln lautet mein Wohnort.` liefert nur Köln statt `Köln lautet`.
- Verifikation: `tests/test_weather_context.py` -> `232 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `d072b166 fix: cover residence label grammar variants`.

## Aktueller Ledger 2026-07-19-Post-Restart-6-04

- `teebotus.service` aktiv/running, `MainPID 1147780`, Start `2026-07-19 22:49:53 CEST`.
- Neuer Zyklus seit diesem Restart: `4/20` Code-Fixes. Kein Push.

### Folgefix 2026-07-19: Laenderlabel mit Stadtpraezisierung

- `Wohnort: Deutschland, Köln`, `Wohnort: Deutschland, in Köln` und `Wohnort: Deutschland, genauer Köln` liefern jetzt Köln.
- Bestehende Strassenadressform `Wohnhaft: Österreich, Wien, Musterstr. 5.` bleibt Wien.
- Verifikation: `tests/test_weather_context.py` -> `232 passed`, `py_compile` und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `a4e85011 fix: parse labeled country residence cities`.

## Aktueller Ledger 2026-07-19-Post-Restart-7-00

- `systemctl --user restart teebotus.service` erfolgreich.
- Service aktiv/running, `MainPID 1405994`, Start `2026-07-19 23:53:28 CEST`.
- Historische und abgeschlossene Baupläne liegen jetzt unter `../Abgeschlossene Baupläne/`; aktive Pläne bleiben in `../Baupläne/`.
- Neuer Zyklus seit diesem Restart: `0/20` Code-Fixes. Kein Push.

### Folgefix-Batch 2026-07-19: Residence-Kontext und Archivregel

- Residence-Parser erkennt primäre Wohnortangaben, registrierte Wohnsitze, nahe Stadtangaben, Stadtteile und temporäre/zeitliche Ausschlüsse robuster.
- Mehrdeutige Großraum-, Raum-, Gebiet-, Umland- und Außenbereichsangaben mit mehreren Städten werden verworfen; Arbeits-/Besuchs-/Wochenendkontext bleibt getrennt.
- `... und Umgebung` bleibt als gültiger Einzel-Ortszusatz erhalten; `... und Umgebung von <zweiter Ort>` bleibt mehrdeutig.
- Verifikation nach jedem Fix: `tests/test_weather_context.py` -> `234 passed`, `py_compile`, Smoke-Checks und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commits: `6ffb5a6e`, `4cd20aa9`, `f35c40e6`, `d9334ad8`, `7bc32fbc`, `cea65151`, `752acd48`, `b28fd58d`, `f14de223`, `7f0c030f`, `3eceb6c8`, `96f18a74`, `f0f4ce64`.
- Archiv-/README-Commits: `c4a57c1e`, `9afa480a`, `4e2397d7`.

## Aktueller Ledger 2026-07-19-Post-Restart-7-09

- `teebotus.service` aktiv/running, `MainPID 1405994`, Start `2026-07-19 23:53:28 CEST`.
- Neuer Zyklus seit diesem Restart: `9/20` Code-Fixes. Kein Push.

### Folgefix-Batch 2026-07-19: Routine- und Besuchskontext

- Routine-Qualifier `normalerweise`, `gewöhnlich`, `in der Regel`, `regulär` und `üblicherweise` werden als Hauptwohnort-Kontext erkannt.
- Mehrere Städte nach Routine-Qualifiern bleiben mehrdeutig; `... und Umgebung` bleibt zulässiger Einzel-Ortszusatz.
- Ferien-, Reise-, Dienstreise-, Wochenend-, Wochentag- und Besuchsorte überschreiben Wohnort nicht; mit `sonst/ansonsten` wird Normalort übernommen.
- Verifikation nach jedem Fix: `tests/test_weather_context.py` -> `235 passed`, `py_compile`, Smoke-Checks und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commits: `f3cd90ab`, `7430434e`, `330fb932`, `d7ea3aae`, `7d5a4ae7`, `ca6aa9a8`, `a473b054`, `71c69f17`, `ed4c482d`.

## Aktueller Ledger 2026-07-20-Post-Restart-8-00

- `systemctl --user restart teebotus.service` erfolgreich.
- Service aktiv/running, `MainPID 1697303`, Start `2026-07-20 01:04:25 CEST`.
- Neuer Zyklus seit diesem Restart: `0/20` Code-Fixes. Kein Push.
- Aktive Planstruktur bleibt unter `../Baupläne/`; historische und abgeschlossene
  Planaufnahmen bleiben unter `../Abgeschlossene Baupläne/`.

### Folgefix-Batch 2026-07-20: Sekundaer- und parenthetische Wohnsitzlabels

- Sekundaerwohnsitz ohne Hauptwohnsitz wird auch bei `Zweitwohnsitz`,
  `Nebenwohnsitz`, `Ferienwohnsitz`, `als ... gemeldet` und Klammerlabels
  verworfen.
- Bare Hauptwohnsitzlabels und Umkehrformen wie `Berlin (Hauptwohnsitz)`
  werden erkannt; Hauptwohnsitz plus Arbeitsort bleibt gueltig.
- Zwei echte parenthetische Wohnsitzstaedte bleiben mehrdeutig; sekundäre,
  historische und Arbeitsort-Zusätze werden nicht als zweiter Hauptwohnsitz
  bewertet.
- Verifikation: `tests/test_weather_context.py` -> `237 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commits: `a2a27015`, `38990e3a`, `e5c24156`, `6dc74c0a`, `af416079`,
  `c9f2be3f`, `d8a8140b`, `a3d8cbde`, `40db7503`, `5b1657ca`.

## Aktueller Ledger 2026-07-20-Post-Restart-8-01

- `teebotus.service` aktiv/running, `MainPID 1697303`, Start `2026-07-20 01:04:25 CEST`.
- Historische und abgeschlossene Baupläne bleiben unter `../Abgeschlossene Baupläne/`;
  aktive Pläne bleiben unter `../Baupläne/`.
- Neuer Zyklus seit diesem Restart: `6/20` Code-Fixes. Kein Push.

### Folgefix-Batch 2026-07-20: Inverse Adress- und Wohnungsformen

- Inverse Haupt-/Wohnadressen werden auch nach Komma und `und` als Konflikt erkannt;
  Arbeitsadresse bleibt davon getrennt.
- Inverse `Meldeadresse` wird gegen Wohnort geprüft; gleicher Ort bleibt gültig.
- Zwei unterschiedliche inverse Wohnlabels (`Wohnung`, `Zuhause`) werden als
  mehrdeutiger Mehrfachwohnsitz verworfen; alte Wohnung und Fremdpersonen bleiben
  ausgeschlossen.
- Verifikation: `tests/test_weather_context.py` -> `237 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commits: `15780d8b`, `fe41f666`, `2d460dc1`, `f4a7f4d8`, `17c6f332`, `8f7f0b9e`.

## Aktueller Ledger 2026-07-20-Post-Restart-8-02

- `teebotus.service` aktiv/running, `MainPID 1697303`, Start `2026-07-20 01:04:25 CEST`.
- Neuer Zyklus seit diesem Restart: `10/20` Code-Fixes. Kein Push.

### Folgefix-Batch 2026-07-20: Inverse Zeit- und Jahresendqualifier

- Inverse `ist mein Wohnort`-Formen mit `seit gestern`, `ab sofort` und
  `bis zum Jahresende` werden erkannt.
- Zukuenftige und historische Suffixe (`ab morgen`, `gewesen`) werden nicht
  als aktueller Wohnort gespeichert.
- Gleiche Zeitfilter gelten fuer `Wohnadresse`, `Hauptadresse` und
  `Meldeadresse`; direkte `bis zum Jahresende`-Formen funktionieren vor und
  nach der Stadt.
- Verifikation: `tests/test_weather_context.py` -> `237 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commits: `641fb901`, `2e90b7b1`, `f00a8c76`, `4a69137a`.

## Aktueller Ledger 2026-07-20-Post-Restart-8-03

- `teebotus.service` aktiv/running, `MainPID 1697303`, Start `2026-07-20 01:04:25 CEST`.
- Neuer Zyklus vor dem planmaessigen Restart: `20/20` Code-Fixes. Kein Push.

### Folgefix-Batch 2026-07-20: Kurzzeit-, Registrierungs- und Routineformen

- `bis morgen`, `bis Ende der Woche`, Kalenderzeiträume und inverse Routineformen
  werden konsistent erkannt.
- `wohnhaft/gemeldet/ansässig` mit aktuellem `bis`-Suffix bleibt gültig;
  `ab morgen` und historische Formen werden verworfen.
- Vollsuite fing eine Regression bei `Bei Berlin und Hamburg bin ich gemeldet`
  ab; die Inversionsregex akzeptiert jetzt keine Präfix- oder Mehrfachstadt mehr.
- Verifikation: `tests/test_weather_context.py` -> `237 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commits: `b8f36692`, `082b3d7c`, `9d760ace`, `fe93357c`, `8459102a`.

### Folgefix-Batch 2026-07-20: Klauselgrenzen und aktuelle Wohnorte

- Fremdpersonen-, historische, zukuenftige und unsichere Wohnortklauseln vor
  einem aktuellen Eigen-Wohnort ueberschreiben diesen nicht.
- Kontrastformen nach Komma (`aber`, `doch`, `sondern`) werden als eigene
  aktuelle Klausel erkannt; alte Klauseln nach aktuellem Wohnort bleiben ohne
  Einfluss.
- Verifikation: `tests/test_weather_context.py` -> `237 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commits: `4cf5651c`, `3add3997`, `edba51af`, `bcd33669`.
- Danach planmaessiger User-Service-Restart: `MainPID 2038659`, Start
  `2026-07-20 02:24:52 CEST`, aktiv/running.
- Neuer Zyklus seit diesem Restart: `11/20` Commits. Kein Push.

## Aktueller Ledger 2026-07-20-Post-Restart-8-04

- `teebotus.service` aktiv/running, `MainPID 2038659`, Start `2026-07-20 02:24:52 CEST`.
- Historische Splitteile liegen jetzt unter `../Abgeschlossene Baupläne/`;
  aktive Katalog-, Ledger- und SQL-Pläne bleiben unter `../Baupläne/`.
- Archivschritt zählt als Commit 12/20. Kein Push. Restart erst bei 20/20.

### Folgefix 2026-07-20: Companion-Aufenthalte nach aktueller Wohnstadt

- `Ich wohne in Berlin und lebe zeitweise bei meiner Frau in Hamburg` sowie
  Komma-/Aktuellvarianten behalten Berlin als Wohnstadt.
- Gültige direkte Formen wie `Ich wohne bei meinen Eltern in Berlin` bleiben
  erhalten; Companion-Erkennung greift nur nach einer echten Klauselgrenze.
- Verifikation: `tests/test_weather_context.py` -> `237 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `87260e24`.

## Aktueller Ledger 2026-07-20-Post-Restart-8-05

- `teebotus.service` aktiv/running, `MainPID 2038659`, Start `2026-07-20 02:24:52 CEST`.
- Institutionelle Companion-Aufenthalte werden nicht als Wohnstadt gespeichert;
  Familien- und Partnerformen bleiben gültig.
- Nach Codefix und diesem Ledger-Commit: `14/20` Commits seit Restart. Kein
  Push. Restart erst bei 20/20.

### Folgefix 2026-07-20: Institutionelle Companion-Kontexte

- `Schule`, `Universität`, `Hochschule`, `Klinik`, `Praxis` und weitere
  institutionelle Begleiter werden in `bei/mit ... in Stadt` als
  Nicht-Wohnkontext verworfen.
- Personen- und Familienbegleiter bleiben normale Wohnortangaben.
- Verifikation: `tests/test_weather_context.py` -> `238 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `feeb44b8`.

## Aktueller Ledger 2026-07-20-Post-Restart-8-06

- `teebotus.service` aktiv/running, `MainPID 2038659`, Start `2026-07-20 02:24:52 CEST`.
- Fremdpersonen-Wohnlabels werden auch bei possessiven `hat ... Wohnsitz/
  Wohnadresse ... in/bei`-Formen am tatsächlichen City-Start gefiltert.
- Nach Codefix und diesem Ledger-Commit: `16/20` Commits seit Restart. Kein
  Push. Restart erst bei 20/20.

### Folgefix 2026-07-20: Possessive Fremdpersonen-Wohnlabels

- `Ich wohne in Berlin und meine Frau hat ihren Wohnsitz in Hamburg` sowie
  `... ihre Wohnadresse bei Hamburg` behalten Berlin als eigene Wohnstadt.
- Der Offset-Check nutzt Pattern- und tatsächlichen City-Start; dadurch werden
  Präpositionsvarianten nicht mehr als eigener Wohnort gewertet.
- Verifikation: `tests/test_weather_context.py` -> `238 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `e12a06c9`.

## Aktueller Ledger 2026-07-20-Post-Restart-8-07

- `teebotus.service` aktiv/running, `MainPID 2038659`, Start `2026-07-20 02:24:52 CEST`.
- Fremdpersonen-Ortsangaben in Subjektform werden vor allgemeiner
  Mehrdeutigkeitsprüfung erkannt.
- Nach Codefix und diesem Ledger-Commit: `18/20` Commits seit Restart. Kein
  Push. Restart erst bei 20/20.

### Folgefix 2026-07-20: Fremdperson-Ortsangaben in Subjektform

- `Meine Frau ist in Hamburg gemeldet`, `ist zuhause` und `hat ihr Zuhause`
  werden nicht als eigener Wohnort neben Berlin bewertet.
- Filter prüft sowohl Pattern- als auch tatsächlichen City-Start; Präpositionen
  und possessive Wohnlabels bleiben konsistent.
- Verifikation: `tests/test_weather_context.py` -> `238 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `6ec29491`.

## Aktueller Ledger 2026-07-20-Post-Restart-8-08

- `teebotus.service` bleibt bis zum planmaessigen Restart aktiv/running.
- Inverse Fremdpersonen-Wohnlabels (`Wohnsitz meiner Frau liegt in ...`) werden
  vor der Mehrdeutigkeitsprüfung erkannt.
- Dieser Ledger-Commit ist `20/20` seit dem letzten Restart. Kein Push.
- User-Service-Restart folgt jetzt nach der 20-Commit-Regel.

### Folgefix 2026-07-20: Inverse Fremdpersonen-Wohnlabels

- `Ich wohne in Berlin und der Wohnsitz meiner Frau liegt in Hamburg` bleibt
  bei Berlin; die inverse Stadt wird nicht als eigener Wohnort bewertet.
- Der Filter erkennt Personenlabel nach `Wohnsitz`, `Wohnadresse`, `Wohnort`
  und verwandten Labels, inklusive `ist/liegt/befindet sich`.
- Verifikation: `tests/test_weather_context.py` -> `238 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `62b47989`.

## Aktueller Ledger 2026-07-20-Post-Restart-8-09

- `systemctl --user restart teebotus.service` erfolgreich.
- Service aktiv/running, `MainPID 2292168`, Start `2026-07-20 03:25:05 CEST`.
- Neuer Zyklus: `1/20` Commit seit diesem Restart. Kein Push.

## Aktueller Ledger 2026-07-20-Post-Restart-8-10

- `teebotus.service` aktiv/running, `MainPID 2292168`, Start `2026-07-20 03:25:05 CEST`.
- Kopulalose inverse Fremdpersonen-Wohnlabels bleiben aus eigener Wohnstadt
  ausgeschlossen.
- Neuer Zyklus: `3/20` Commits seit diesem Restart. Kein Push. Restart erst
  bei 20/20.

### Folgefix 2026-07-20: Kopulalose inverse Fremdpersonen-Wohnlabels

- `Der Wohnort meiner Frau ist Hamburg`, `Wohnadresse ... lautet Hamburg`
  und `Wohnung meines Mannes bleibt Hamburg` werden nicht als eigener
  Wohnort neben Berlin bewertet.
- City-Start-Filter und Ambiguitätsausnahme verwenden dasselbe Personenlabel.
- Verifikation: `tests/test_weather_context.py` -> `238 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c9dfa08a`.

## Aktueller Ledger 2026-07-20-Post-Restart-8-11

- `teebotus.service` aktiv/running, `MainPID 2292168`, Start `2026-07-20 03:25:05 CEST`.
- Fremdperson-Zuweisungen mit `hat/nennt/bezeichnet ... als/ihren Wohnort`
  werden über die tatsächliche City-Spanne gefiltert.
- Neuer Zyklus: `5/20` Commits seit diesem Restart. Kein Push. Restart erst
  bei 20/20.

### Folgefix 2026-07-20: Fremdperson-Zuweisungen

- `Meine Frau hat Hamburg als Wohnort` und `nennt Hamburg ihren Wohnort`
  erzeugen neben Berlin keinen falschen Mehrfachwohnsitz.
- Eigene Formen bleiben unverändert, weil Filter Personenlabel und Verbkontext
  gemeinsam verlangen.
- Verifikation: `tests/test_weather_context.py` -> `238 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `f55c6ea7`.

## Aktueller Ledger 2026-07-20-Post-Restart-8-12

- `teebotus.service` aktiv/running, `MainPID 2292168`, Start `2026-07-20 03:25:05 CEST`.
- Fremdpersonen-Wohnformen mit wechselnden Referenzen, possessiven Labels,
  inversen Labels und Zuweisungsverben werden aus der eigenen Wohnortwahl
  herausgehalten.
- Neuer Zyklus: `6/20` Commits seit diesem Restart. Kein Push. Restart erst
  bei 20/20.

### Folgefix 2026-07-20: Breite Fremdpersonen-Referenzen

- Erkannt: `führt/sieht ... als Wohnort`, `ihr Wohnsitz`, `ihre Wohnung`,
  `die Wohnadresse der Frau`, `in Hamburg wohnt die Frau` und verwandte Formen.
- Generische Wohnortmuster übernehmen bei Fremdpersonenklauseln nur die
  vorherige eigene Stadt; `mein/unser Wohnort` bleibt eigener Kontext.
- Adress-/Wohnort-Konfliktprüfung nutzt dieselben Fremdpersonenfilter.
- Verifikation: `tests/test_weather_context.py` -> `238 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `952dab8d`.

## Aktueller Ledger 2026-07-20-Post-Restart-8-13

- `teebotus.service` aktiv/running, `MainPID 2292168`, Start `2026-07-20 03:25:05 CEST`.
- Weitere Fremdpersonenformen mit `sowie`, `dessen` und `von Frau ...` sind
  vor der eigenen Wohnortentscheidung abgefangen.
- Eigene Haushaltsform `unsere Wohnung` bleibt absichtlich mehrdeutig.
- Neuer Zyklus: `8/20` Commits seit diesem Restart. Kein Push. Restart erst
  bei 20/20.

### Folgefix 2026-07-20: Weitere Fremdpersonen-Referenzen

- Erkannt: `sowie die Wohnung meiner Frau`, `dessen Wohnort`, `Wohnadresse
  von Frau Müller` und `Hamburg ist der Wohnort von Frau Müller`.
- Referenzmarker unterscheiden possessive Fremdpersonenbezüge von neutralen
  Artikeln in eigenen Labels wie `die Meldeanschrift`.
- Verifikation: `tests/test_weather_context.py` -> `238 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `8eaa5a7d`.

## Aktueller Ledger 2026-07-20-Post-Restart-8-14

- `teebotus.service` aktiv/running, `MainPID 2292168`, Start `2026-07-20 03:25:05 CEST`.
- Invertierte Eigenangaben wie `während ich in Berlin wohne` werden erkannt;
  reine Fremdpersonen-Sätze bleiben ohne eigenen Wohnort.
- Negierte Inversionen wie `In Berlin wohne ich nicht` bleiben ausgeschlossen.
- Neuer Zyklus: `10/20` Commits seit diesem Restart. Kein Push. Restart erst
  bei 20/20.

### Folgefix 2026-07-20: Invertierte Wohnortklauseln

- Neues Muster für `in/bei Stadt wohne/lebe ich/wir` mit Satz- oder
  Konnektorabschluss.
- Verhindert positive Treffer bei Negation und unbestimmten Nachsätzen.
- Verifikation: `tests/test_weather_context.py` -> `238 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `f1c64444`.

## Aktueller Ledger 2026-07-20-Post-Restart-8-15

- `teebotus.service` aktiv/running, `MainPID 2292168`, Start `2026-07-20 03:25:05 CEST`.
- Pronominale und elliptische Fremdpersonenlabels werden vor generischen
  Wohnortmustern herausgefiltert.
- Neuer Zyklus: `12/20` Commits seit diesem Restart. Kein Push. Restart erst
  bei 20/20.

### Folgefix 2026-07-20: Pronominale Fremdpersonen-Wohnlabels

- Erkannt: `der Wohnort ihrer Frau`, `der Wohnort von ihr` und
  `Hamburg gehört/gilt ... als Wohnort`.
- Filter wird auch bei Kandidaten angewandt, deren Regex-Stadtgruppe bereits
  mit Personen-/Verbtext beginnt.
- Verifikation: `tests/test_weather_context.py` -> `238 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `c7720dbb`.

## Aktueller Ledger 2026-07-20-Post-Restart-8-16

- `teebotus.service` aktiv/running, `MainPID 2292168`, Start `2026-07-20 03:25:05 CEST`.
- Label- und Satzformen fremder Wohnorte werden jetzt auch bei Komma,
  Semikolon, `während` und invertierten Klauseln sauber getrennt.
- Kandidatenfilter verhindert, dass generische Muster komplette Fremdsätze
  wie `Hamburg ist ihr Wohnort` als eigene Stadt übernehmen.
- Parser-Sweep mit 280 Kombinationen aus fünf eigenen Formen, acht
  Fremdformen und sieben Konnektoren: `280/280` korrekt.
- Neuer Zyklus: `15/20` Commits seit diesem Restart. Kein Push. Restart erst
  bei `20/20`.

### Folgefix 2026-07-20: Labelierte Fremdpersonen-Klauseln

- Wortgrenze verhindert Stadtcaptures mitten in `Berlin` (`Be`).
- Adress-/Wohnort-Konfliktprüfung verwirft Fremdpersonen-Kandidaten vor dem
  Mehrfachwohnsitz-Check.
- Regressionen für `die Wohnadresse von Frau Müller`, `ihr Wohnsitz`,
  `Hamburg gehört als Wohnort` und `während` ergänzt.
- Verifikation: `tests/test_weather_context.py` -> `238 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `d85a2fb5`.

## Aktueller Ledger 2026-07-20-Post-Restart-8-17

- `teebotus.service` aktiv/running, `MainPID 2292168`, Start `2026-07-20 03:25:05 CEST`.
- Fremde Wohnortlabels vor oder nach eigener Wohnortangabe werden über
  Satzgrenzen und Konnektoren getrennt; Organisationsbesitz wie
  `Wohnort meines Arbeitgebers` bleibt Fremdkontext.
- Ambiguitätsprüfung zählt pronominale Fremdlabels wie `ihr Wohnsitz` nicht
  mehr als eigene Zielstadt.
- Erweiterter Sweep mit 143 Kombinationen aus elf Fremdformen, sieben
  Konnektoren und beiden Satzrichtungen: `143/143` korrekt.
- Neuer Zyklus: `17/20` Commits seit diesem Restart. Kein Push. Restart erst
  bei `20/20`.

### Folgefix 2026-07-20: Fremdlabels über Satzgrenzen

- Prefix-Split berücksichtigt `.`, `!`, `?`, Zeilenumbruch und `während`.
- Generische Ambiguitätsmuster prüfen den direkt vorangestellten
  Fremdpronomenkontext.
- Regressionen für `ihr Wohnsitz ... und Ich wohne`, Arbeitgeberlabel mit
  `sowie` und Fremdsatz vor eigener Wohnangabe ergänzt.
- Verifikation: `tests/test_weather_context.py` -> `238 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `9e0dc0e4`.

## Aktueller Ledger 2026-07-20-Post-Restart-8-20

- Vor Restart: `teebotus.service` aktiv/running, `MainPID 2292168`, Start
  `2026-07-20 03:25:05 CEST`.
- Organisationsbezüge wie Arbeitgeber, Firma, Unternehmen, Verein, Schule,
  Praxis und Klinik werden bei fremden Wohnortlabels berücksichtigt.
- Sweep mit 196 Kombinationen aus 14 Organisations-/Pronominalformen, sieben
  Konnektoren und beiden Satzrichtungen: `196/196` korrekt.
- Zyklus erreicht: `20/20` Commits seit letztem Restart. Kein Push.

### Folgefix 2026-07-20: Organisations-Wohnortbezüge

- `Wohnort meines Arbeitgebers ist Hamburg` wird nicht als eigene Stadt
  übernommen.
- `Hamburg gehört als Wohnort meiner Firma` wird als Fremdbezug verworfen.
- Kandidaten- und Suffixfilter verwenden dafür das vorhandene
  `_OTHER_RESIDENCE_OWNER_LABEL`.
- Verifikation: `tests/test_weather_context.py` -> `238 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `f6418555`.

## Service-Restart 2026-07-20

- Restart nach abgeschlossenem Zyklus `20/20` ausgeführt.
- `teebotus.service` ist `active/running`, neuer `MainPID 2585598`.
- Neuer Zyklus: `1/20` Commits seit diesem Restart. Kein Push.

## Aktueller Ledger 2026-07-20-Post-Restart-8-03

- `teebotus.service` aktiv/running, `MainPID 2585598`.
- Benannte Fremdpersonen, Organisationen und pronominale Ortslabels werden
  auch bei `liegt`, `lautet`, `Zuhause`, `Meldeadresse` und Satzwechseln
  erkannt.
- Registeradress-Konfliktprüfung filtert rohe Fremdtextfragmente vor dem
  Vergleich; echte eigene Registrierungsadressen bleiben wirksam.
- Varianten-Sweep mit 238 Kombinationen: `238/238` korrekt.
- Neuer Zyklus: `3/20` Commits seit diesem Restart. Kein Push. Restart erst
  bei `20/20`.

### Folgefix 2026-07-20: Fremde Adressfragmente

- Unmittelbare Pronomen vor Ortslabels (`ihr Zuhause`) blockieren keine
  eigene Wohnstadt mehr.
- Prefixfilter deckt benannte Personen und Organisationsbesitzer nach `von`
  ab.
- `registered_address_cities` entfernt nur Kandidaten, die als Fremdbezug
  klassifiziert sind.
- Verifikation: `tests/test_weather_context.py` -> `238 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `ef269e20`.

## Aktueller Ledger 2026-07-20-Post-Restart-8-04

- `teebotus.service` aktiv/running, `MainPID 2585598`.
- Besitzkonstruktionen mit `hat ihre/seine Meldeadresse` und
  `Firma ist in ... ansässig` werden als Fremdbezug getrennt.
- Registeradress-Konfliktprüfung entfernt die daraus extrahierten fremden
  Städte zentral, ohne echte eigene Adresskonflikte zu ignorieren.
- Besitz-/Adress-Sweep mit 80 Varianten: `80/80` korrekt; fünf
  Konfliktinvarianten zusätzlich geprüft.
- Neuer Zyklus: `5/20` Commits seit diesem Restart. Kein Push. Restart erst
  bei `20/20`.

### Folgefix 2026-07-20: Besitzkonstruktionen

- Fremdmarker erkennt Besitzer mit `hat ... Wohn-/Meldeadresse` sowie
  `ist in/bei`.
- Prefixfilter schützt City-Kandidaten bei Personen- und Organisationsbesitz.
- Registersammler entfernt fremde Cities vor disjunktem Adressvergleich.
- Verifikation: `tests/test_weather_context.py` -> `238 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `516cc9ee`.

## Aktueller Ledger 2026-07-20-Post-Restart-8-06

- `teebotus.service` aktiv/running, `MainPID 2585598`.
- Fremdstatusformen `wohnhaft`, `ansässig`, `gemeldet`, `registriert` und
  `zuhause` werden nach Besitzerlabeln korrekt erkannt.
- Besitzform `hat Stadt als Adresse` wird nicht als eigene Wohnstadt
  übernommen.
- Kontroll-Sweep mit 80 Kombinationen: `80/80` korrekt.
- Neuer Zyklus: `7/20` Commits seit diesem Restart. Kein Push. Restart erst
  bei `20/20`.

### Folgefix 2026-07-20: Fremder Aufenthaltsstatus

- Fremdmarker deckt Organisationen und Personen mit Status-/Adressverb an
  verschiedenen Wortstellungen ab.
- Prefixfilter hält generische City-Regexe bei diesen Formen auf eigener
  Stadt fest.
- Regressionen für `wohnhaft`, `gemeldet` und `hat ... als Adresse` ergänzt.
- Verifikation: `tests/test_weather_context.py` -> `238 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `660b46a9`.

## Folgefix 2026-07-20: Wohnort-Memory und Wetter-State atomarer halten

- City-Wechsel räumte Wohnort-Memory bisher vor dem separaten Agent-State-Write
  um. Bei einem fehlgeschlagenen State-Write konnten Memory und Wetter-State
  unterschiedliche Städte enthalten.
- `_append_city_memory()` liefert bei einer echten Mutation Snapshot von
  Entries und Index zurück.
- Der nachfolgende Wetter-State-Write stellt diesen Snapshot bei Fehler wieder
  her; Rollbackfehler werden sichtbar gemeldet.
- Regressionstest deckt neuen Wohnort plus fehlgeschlagenen State-Write ab.
- Verifikation: `tests/test_weather_context.py` -> `239 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `0a58c842`.

### Folgefix 2026-07-20: Wetter-State-Rollback nach Teil-Write

- Ein fehlgeschlagener `write_agent_state()` kann den State bereits persistiert
  haben. Vorher wurde dann nur das Wohnort-Memory zurückgesetzt.
- Der Wetterpfad nimmt jetzt vor jeder Mutation Snapshot des Agent-States und
  stellt bei Write-Fehlern State sowie betroffene Memory-Entries und Index
  gemeinsam wieder her.
- Fehler beim Memory-Rollback werden nicht mehr als normales `memory_error`
  verschluckt; sie bleiben als Inkonsistenzfehler sichtbar.
- Regressionen decken Pre-Write-Fehler, Teil-Write-Fehler und fehlgeschlagenes
  Index-Rollback ab.
- Verifikation: `tests/test_weather_context.py` -> `241 passed`, `py_compile`
  und `git diff --check` gruen. Kein Provider/API-Aufruf.
- Code-Commit: `8daab7b5`.
- Neuer Zyklus: `10/20` Commits seit diesem Restart. Kein Push. Restart erst
  bei `20/20`.
