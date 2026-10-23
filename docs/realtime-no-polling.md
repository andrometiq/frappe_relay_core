# Realtime UI updates

The Core inbox uses Socket.IO over WebSocket. Message/status, private action,
read, presence and notification invalidations trigger bounded permission-checked
API reads. The events intentionally contain no customer message content or
record identity in shared rooms. These reads are event-driven, not scheduled
polls. Sending, searching, pagination and marking messages actually viewed are
explicit API operations.

Removed periodic inbox recovery, send reconciliation, presence reads,
notification reads, reply-window checks, summary fallback and report checks.
Socket.IO reconnects with backoff and rejoins subscribed rooms. Each mounted
view coalesces the reconnect into one refresh cycle. Hidden views retain pending
invalidations and catch up on becoming visible. Failures do not start retry
polls. The connection indicator reports interruptions instead of silently
switching to API polling. WhatsApp window expiry uses a local timer with the
server's remaining duration; the backend still checks every send.

Durable action snapshots read at most 50 local records, recheck source access,
and never dispatch or call Hub. Business history snapshots preserve the selected
record boundary. Denied snapshots clear affected visible state.

Validation: three Node tests cover batching, hidden/in-flight invalidations,
error behavior, the production client's real WebSocket transport, room rejoin
and one reconnect catch-up. Isolated Frappe integration checks cover after-commit
publication, rollback suppression, business snapshot isolation and the local
read-only action snapshot path. Production frontend build passes. A built-UI
browser fixture made zero API requests during 31 idle seconds with realtime
unavailable, with no JavaScript errors.

This is not live provider acceptance: the installed site's authenticated browser
verification remains blocked by its Frappe login metadata query. The browser
fixture uses synthetic records, while the transport test runs a local Socket.IO
server. Neither test is represented as a real WhatsApp delivery test.
