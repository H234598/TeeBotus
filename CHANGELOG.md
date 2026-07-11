# Changelog

## 1.9.14 - 2026-07-11

- Use the validated instance name consistently in account-memory health output.

## 1.9.13 - 2026-07-11

- Reject invalid instance and account identifiers before resolving status
  memory paths.

## 1.9.12 - 2026-07-11

- Do not mask unreadable JSON account memory with its raw file size in
  `/status`.

## 1.9.11 - 2026-07-11

- Keep account-memory health diagnostics alive when fallback status resolution
  fails.

## 1.9.10 - 2026-07-11

- Keep `/status` diagnostic when account-memory backend resolution fails.

## 1.9.9 - 2026-07-11

- Do not report legacy JSON sizes when the configured account-memory backend is
  unavailable or returned partial data.

## 1.9.8 - 2026-07-11

- Reject path-traversal instance names in account-memory health checks.

## 1.9.7 - 2026-07-11

- Fail closed when callback spool delivery responses lack a valid inner
  success object.

## 1.9.6 - 2026-07-11

- Persist generated callback event IDs inside spool payloads so retries retain
  delivery idempotency.

## 1.9.5 - 2026-07-11

- Keep callback spool files when the Dispatcher RPC succeeds transport-wise but
  reports an inner delivery failure.

## 1.9.4 - 2026-07-11

- Accept both `recipient_id` and legacy `account_id` fields when skipping
  already delivered bridge recipients.

## 1.9.3 - 2026-07-11

- Preserve already delivered History-Dispatcher recipients when a bridge claim
  has no remaining open recipient.

## 1.9.2 - 2026-07-11

- Preserve the documented `dispatch-limit 0` semantics across the
  History-Dispatcher bridge so all queued history entries can be queried and
  claimed.

## 1.9.1 - 2026-07-10

- Made scheduling, activity profiles, and notification wake windows use one
  deterministic configurable local timezone (`TEEBOTUS_TIMEZONE`).
- Hardened temporary-file cleanup against symlink replacement races and made
  the first memory-backend fallback warning visible on fresh runtimes.

## 1.9.0 - 2026-07-10

- Added the optional History-Dispatcher bridge and shadow migration path.
- Added the optional full Dispatcher section to the TeeBotus Cinnamon applet.
- Kept the legacy AccountStore readable while Dispatcher claims and receipts
  are exchanged over a bounded owner-only Unix socket.
- Hardened applet snapshot reads, action argv validation, subprocess timeouts,
  generation guards, and removal-time cancellation.
