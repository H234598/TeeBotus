# Bauplan: Aktuelle Logikpruefung und Memory-Konsistenz

**Rolle:** Katalog und Einstiegspunkt

**Status:** Aktiv

**Stand:** 2026-07-19

## Zweck

Dieser Katalog ersetzt den unhandlichen Monolithen. Der vollstaendige
Planinhalt bleibt in den verlinkten Teilen erhalten. Kein Teil darf mehr als
5000 Zeilen enthalten; Zielgrenze fuer neue Teile ist 4800 Zeilen.

## Teile

| Teil | Kategorie | Inhalt | Zeilen beim Split |
| --- | --- | --- | ---: |
| [Bauplan-Aktueller-Plan-Logikpruefung-2026-07-16-01-Grundlagen-und-Fruehe-Funde](<../Abgeschlossene Baupläne/Bauplan-Aktueller-Plan-Logikpruefung-2026-07-16-01-Grundlagen-und-Fruehe-Funde.md>) | Historie/Grundlagen | Auftrag, Leitplanken, Akzeptanzkriterien, fruehe Befunde und Fixes | 4800 |
| [Bauplan-Aktueller-Plan-Logikpruefung-2026-07-16-02-Logikpruefung-Historie-Teil-1](<../Abgeschlossene Baupläne/Bauplan-Aktueller-Plan-Logikpruefung-2026-07-16-02-Logikpruefung-Historie-Teil-1.md>) | Historie 1 | fortlaufende Logikpruefung und Regressionen | 4804 |
| [Bauplan-Aktueller-Plan-Logikpruefung-2026-07-16-03-Logikpruefung-Historie-Teil-2](<../Abgeschlossene Baupläne/Bauplan-Aktueller-Plan-Logikpruefung-2026-07-16-03-Logikpruefung-Historie-Teil-2.md>) | Historie 2 | fortlaufende Logikpruefung und Regressionen | 4804 |
| [[Bauplan-Aktueller-Plan-Logikpruefung-2026-07-16-04-Aktueller-Stand-und-Ledger]] | Aktiv | juengster Stand, Ledger, aktuelle Tests und Commits | 1632 |

Split erfolgte verlustfrei an Originalzeilen 1-4800, 4801-9600,
9601-14400 und 14401-16020. Die Quellkopie liegt unter
`Teladi_Programming/Projekte/TeeBotus/Archiv/`.

Die ersten drei Teile sind abgeschlossene Historie und liegen deshalb unter
`../Abgeschlossene Baupläne/`. Nur Katalog und aktueller Ledger bleiben in der
aktiven Ablage.

## Themenkatalog

- **AccountStore und Memory:** Entries, Indizes, Access-Recency, Rollback,
  Secret-/Legacy-Pfade, Identity-Link und Konsolidierung.
- **Working Memory:** JSONL-Index, Reparatur, atomare Writes und stale Daten.
- **Proactive Agent und Zeit:** Erinnerungen, Due-at, Zeitzonen, Schlaf-/Wake-
  Fenster und Scheduler-Verhalten.
- **Wetter und Wohnort:** Wohnortextraktion, Mehrfachangaben, Ortsnamen,
  Zeitbezug und Wetterkontext.
- **Telegram und Runtime:** Replys, Attachments, Polling, Status, Healthcheck
  und Applet-Vertrag.
- **LLM und Adapter:** Profile, Aliasnormalisierung, Gemini/OpenAI/HF,
  Providervertraege und providerfreie Tests.
- **Codex-History und Exporte:** Outbox, Dispatch, Summarys, Obsidian und
  Mermaid-Ausgaben.

## Aktueller Arbeitsstand

- Nach planmaessigem Service-Restart: `MainPID 1147780`, Start
  `2026-07-19 22:49:53 CEST`.
- Neuer Fixzyklus seit diesem Restart: `4/20` Code-Fixes. Kein Push.
- Letzter Code-Commit im Parserlauf:
  `0111779d fix: parse shorthand residence clarifications`.
- Aktive Tests bleiben providerfrei. Kein Push ohne ausdrueckliche Freigabe.

## Pflege-Regeln

- Neue Befunde werden in den aktuellsten Aktiv-/Ledger-Teil geschrieben.
- Bei 4500 Zeilen wird ein neuer Teil angelegt; harte Obergrenze bleibt 5000.
- Dieser Katalog wird bei neuen Teilen um eine Tabellenzeile ergaenzt.
- Repo-Plan und kanonischer Obsidian-Plan werden inhaltlich synchron gehalten.
- Kanonischer Default-Vault fuer alle Instanzen ist
  `/home/teladi/Dokumente/Obsidian_Vaults/Teladi_Programming`.
- Der alte `Teladi_Def_Obs_Vault` bleibt EOL und wird nicht weiter beschrieben.

## Archiv

Die vorherige Monolith-Quellkopie liegt ausserhalb des aktiven Planordners:
`/home/teladi/Dokumente/Obsidian_Vaults/Teladi_Programming/Projekte/TeeBotus/Archiv/`.
