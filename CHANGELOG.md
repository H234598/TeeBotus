# Changelog

## 1.9.0 - 2026-07-10

- Added the optional History-Dispatcher bridge and shadow migration path.
- Added the optional full Dispatcher section to the TeeBotus Cinnamon applet.
- Kept the legacy AccountStore readable while Dispatcher claims and receipts
  are exchanged over a bounded owner-only Unix socket.
- Hardened applet snapshot reads, action argv validation, subprocess timeouts,
  generation guards, and removal-time cancellation.
