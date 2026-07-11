# Changelog

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
