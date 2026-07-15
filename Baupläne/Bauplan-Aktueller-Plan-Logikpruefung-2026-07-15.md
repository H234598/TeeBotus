# Bauplan: Aktuelle Logikpruefung und Healthcheck

**Stand:** 2026-07-16 00:06 CEST

**Status:** Aktiv

**Geltungsbereich:** TeeBotus-Runtime, Cinnamon-Applet, Health-Payload,
Telegram-Adapter und die dazugehoerigen Regressionstests.

## Auftrag

Logikfehler reproduzieren, Ursache im gemeinsamen Pfad beheben und mit einer
kleinen Regression absichern. Pro Arbeitsschritt bleibt der Fokus auf einer
Datei oder einem eng zusammenhaengenden Thema. Keine Provider- oder LLM-
Aufrufe fuer Diagnose und Tests.

## Leitplanken

- Healthcheck und Status-Applet bleiben read-only.
- `actionable` Probleme bleiben sichtbar und werden nicht durch Fallbacks
  verdeckt.
- Rein informative Fallbacks, fehlende optionale Keys und terminale History-
  Skips werden nicht als Top-Level-Defekt klassifiziert.
- Keine Secrets, Account-IDs oder privaten Nachrichteninhalte in Plan,
  Testausgabe oder Applet-Payload speichern.
- Uncommittete Benutzerdateien `.obsidian/`, `.stfolder/`,
  `Fusion_Packliste.txt`, `Unbenannt.base` und `Unbenannt.canvas` bleiben
  unangetastet.
- Kein Push ohne ausdrueckliche Freigabe. Restart erst an der vereinbarten
  20-Commit-Grenze oder nach ausdruecklicher Freigabe.

## Aktueller Befund

Read-only Live-Probe ueber `TeeBotus.cinnamon_applet status`:

- Programmversion `1.9.498`, Runtime-Marker `matched`.
- `teebotus.service`: `active/running`, Returncode `0`.
- Qdrant: `active/running`, beide benoetigten Collections `ready`.
- Health-Payload: `status=ok`, `command_ok=true`,
  `actionable_problem_count=0`, `total_problem_count=0`.
- Es gibt `20` informative Hinweise. Sie bestehen aus konservativen Gemini-
  Limitdefaults, optional fehlenden Provider-Keys, partiellen Codex-Usage-
  Daten, erklaerten lokalen Fallbacks und terminalen Codex-History-Skips.
  Diese Befunde sind aktuell kein Top-Level-Defekt.
- Aktuelle Applet-Validierung akzeptiert die Live-Payload. Der erzeugte
  Kurztext lautet sinngemaess `Health ok` mit separaten `Hinweise`.
- Falls die sichtbare Cinnamon-Anzeige weiterhin `Health defekt` zeigt, liegt
  die Abweichung ausserhalb des aktuellen Payloads: stale Applet-Prozess,
  nicht ausgefuehrter Refresh oder alte Anzeige. Das wird vor einem weiteren
  Quellpatch reproduziert.

## Bereits umgesetzt

### Healthcheck und Applet

- Health-Klassifikation V2 trennt actionable Probleme von informativen
  Hinweisen.
- Applet-Validator prueft Boolean-Konsistenz, Servicezustand, Qdrant-
  Collections, Runtime-Returncode und Health-Zaehler fail-closed.
- Applet zeigt konkrete actionable Details; verifizierte lokale Fallbacks
  werden nicht nochmals als Defekt angezeigt.
- Zentrale Dispatcher-Warnung wird getrennt von Runtime-Health behandelt.

### Telegram-Paritaet

- Lange Textantworten werden im gemeinsamen Adapterpfad Telegram-konform in
  UTF-16-beschraenkte Chunks geteilt.
- Reply-Parameter werden fuer Text, Attachment und Export erhalten.
- Action-Reihenfolge und Partial-Failure-Fortschritt bleiben retrybar.
- `SendEdit` reicht `text_mode` weiter.
- Voice- und Document-Captions reichen Caption sowie normalisierten
  Telegram-`parse_mode` weiter.

## Naechste Schritte

1. **Sichtbare Applet-Abweichung reproduzieren.** Live-Payload, installierte
   Applet-Datei, Refresh-Ergebnis und angezeigten Text gemeinsam erfassen.
   Erfolg: keine unbelegte Annahme ueber `Health defekt`.
2. **Nur echte actionable Befunde beheben.** Ursache in Runtime oder
   Applet-Validierung korrigieren; informative Statuszeilen nicht blind
   entfernen. Erfolg: `actionable_problem_count` und Anzeige stimmen ueberein.
3. **Contract-Tests erweitern.** Einen schreibfreien Test fuer den aktuellen
   Live-Payload-Vertrag sowie fuer den betroffenen Anzeigezustand ergaenzen.
   Erfolg: fokussierte Applet-Suite und relevante Runtime-Suite gruen.
4. **Plan fortschreiben.** Befund, Commit, Tests und offene Live-Abnahme hier
   dokumentieren. Plan erst nach reproduzierbarer Abnahme als abgeschlossen
   markieren.

## Letzter Nachweis

- Telegram-Media-Fix: Commit `0f2497fb`.
- Relevante Suite: `780 passed, 17 subtests passed in 12.91s`.
- Cinnamon-Applet-Suite: `238 passed in 29.18s`.
- `py_compile` und `git diff --check`: sauber.
- Tests liefen ohne Provider-/LLM-Aufruf.
- 2026-07-16: Ein Applet-Warning mit `TeeBotus_Logger queued=1` wurde
  reproduziert. Die Adminroute war `routable=1`; eine unmittelbare read-only
  Wiederholung zeigte lokale Queue `0` und zentrale Dispatcher-Queue `0`.
  Die Warnung war damit ein echter kurzlebiger Zustellzustand, kein stale
  Applet-Payload und kein Fehlklassifikationsbeleg. Die aktuelle Payload wurde
  durch den installierten JavaScript-Validator akzeptiert.
- 2026-07-16: Telegram-Kompatibilitaetsregression behoben: Der neue Caption-
  und `text_mode`-Pfad entfernte bei alten Adaptern nur `reply_parameters`.
  Adapter mit historischer Signatur ohne optionale Keywords konnten dadurch
  bei Voice-/Document-Actions mit `TypeError` abbrechen. Der gemeinsame
  Fallback entfernt jetzt nur die vom konkreten Adapter nicht unterstuetzten
  optionalen Keywords und laesst echte TypeErrors weiter hochlaufen.
- Regression fuer alte Voice-/Document-Signaturen ergaenzt. Relevante Suite:
  `781 passed, 17 subtests passed in 12.62s`; keine Provider-/LLM-Aufrufe.
- 2026-07-16: Der Kompatibilitaetsfallback wurde enger gefasst: Beliebige
  Texttreffer wie `caption must be a string` duerfen keinen Fehler mehr
  verschlucken. Fallback startet nur noch bei einer echten Python-Meldung
  `unexpected keyword argument '<name>'`.
- Adapter-Vollsuite danach: `150 passed in 1.90s`; `py_compile` und
  `git diff --check` sauber.
- 2026-07-16: Derselbe Fehler wurde im formatierten `SendText`-Fallback
  gefunden. Breite Textsuche konnte einen echten Fehler wie `text_mode must
  be html` verschlucken und stattdessen unformatiert senden. Gemeinsame
  Erkennung nutzt jetzt ausschliesslich echte `unexpected keyword argument`
  Meldungen.
- Regression fuer echten formatierten Text-`TypeError` ergaenzt.
  Adapter-Vollsuite danach: `151 passed in 0.97s`; `py_compile` und
  `git diff --check` sauber.
- 2026-07-16: Der verbleibende direkte/Legacy-Telegram-Textpfad hatte dieselbe
  breite `TypeError`-Suche. Ein echter Fehler wie `text_mode must be html`
  konnte dadurch verloren gehen. Der Pfad nutzt jetzt dieselbe exakte
  Erkennung fuer `unexpected keyword argument '<name>'` wie der gemeinsame
  Adapter; alte `send_message(chat_id, text)`-Signaturen bleiben kompatibel.
- Regression fuer beide Faelle ergaenzt: echte Textfehler werden propagiert,
  historische Signaturen erhalten Plaintext-Fallback. Relevante Suite danach:
  `785 passed, 17 subtests passed in 13.30s`; keine Provider-/LLM-Aufrufe.
- 2026-07-16: Auch der `SendEdit`-Pfad hatte noch einen breiten
  `text_mode`-Treffer. Ein echter Edit-Fehler konnte dadurch als zweiter,
  unformatierter Versuch ausgefuehrt werden. Fallback nutzt nun ebenfalls nur
  die exakte Meldung `unexpected keyword argument '<name>'`.
- Regression fuer echten Edit-`TypeError` und historische Edit-Signaturen
  ergaenzt. Adapter-Vollsuite danach: `153 passed in 1.52s`; keine
  Provider-/LLM-Aufrufe.

## Historische Plaene

- `Baupläne/Bauplan-Aktueller-Plan-Logikfehler-Healthcheck-Applet-Codex-History-2026-07-13.md`
- `Baupläne/Bauplan-Aktueller-Plan-Dispatcher-Teilfehler-Idempotenz-2026-07-13.md`
- `Baupläne/Bauplan-Fortsetzung-Healthcheck-TBL-Reconciliation-2026-07-13.md`
