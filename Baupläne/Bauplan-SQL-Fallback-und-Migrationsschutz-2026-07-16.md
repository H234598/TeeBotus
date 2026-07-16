# Bauplan: SQL-Fallback und Legacy-Migrationsschutz

**Stand:** 2026-07-16

**Status:** Aktiv; SQL-Fallback-Thema umgesetzt, uebergeordnete
Logikpruefung laeuft weiter.

## Auftrag

AccountStore-Lesepfade gegen Teilkorruption und stille Datenverluste pruefen.
SQL bleibt Primaerquelle. JSON/JSONL bleibt Rueckfallquelle, bis eine
Migration verifiziert ist. Tests bleiben providerfrei.

## Befund

- SQLite/PostgreSQL koennen gueltige Collection-Rows liefern und gleichzeitig
  `last_collection_read_error` oder `last_collection_skipped` setzen.
- Die alten Reader behandelten diesen Partial-Read wie Totalausfall und
  ersetzten gueltige SQL-Daten durch stale JSON/JSONL.
- Migrationspfade loeschten Legacy-Dateien nach einem Write auch dann, wenn
  ein stiller Readback-Verlust die neue SQL-Collection leer zurueckgab.

## Umgesetzte Regeln

1. JSON-Dokumente mit gueltigen SQL-Rows und Partial-Diagnose liefern diese
   Rows direkt. Kein destruktiver Compact-Write, kein Legacy-Merge, kein
   Legacy-Loeschen.
2. JSONL mit gueltigen SQL-Rows und Partial-Diagnose nutzt SQL plus Legacy nur
   im Speicher. Kein Write und kein Legacy-Loeschen.
3. Partial-Diagnose ohne gueltige Rows behaelt bisherigen Fallback: Legacy
   lesen, sonst Fehler sichtbar machen.
4. Saubere Migration liest Collection nach dem Write erneut. Legacy wird nur
   geloescht, wenn Readback exakt dem erwarteten Payload entspricht und keine
   Diagnose gesetzt ist.
5. `read_llm_state()` darf bei unbestaetigter `LLM_State.json`-Migration nicht
   nachtraeglich `LLM_State.json` oder `OpenAI_State.json` entfernen.

## Nachweis

- Commit: `aa6663d9 fix: preserve valid SQL state during partial reads`
- Regressionen fuer `llm_state`, `agent_state`, JSONL-Outbox, Instanz-State,
  stale Legacy-Daten und stillen Readback-Verlust.
- Fokustests: `29 passed`.
- AccountStore-Suite: `224 passed in 6.50s`.
- `python3 -m py_compile TeeBotus/runtime/accounts.py`: erfolgreich.
- Ruff fuer geaenderte Runtime-/Testdateien: erfolgreich.
- `git diff --check`: erfolgreich.

## Offene Abnahme

- Weitere mehrteilige Account-Metadatenwrites im uebergeordneten Audit pruefen.
- Diesen Bauplan erst nach Abschluss des uebergeordneten Audits nach
  `Pläne/` verschieben.
- Kein Push und kein Restart durch diesen Schritt; seit letztem Restart
  `3/20` Commits.
