# First executable specification

This is an isolated Python reference model for Core read-state semantics and the requested agent/manager visibility rules. It is not the Go Hub, an installed Frappe module or a production authorization implementation. It performs no database, provider or network operations.

Run: `python3 -B -m unittest discover -s specifications -v` from the repository root.

Eight tests pass: open badge versus exact reads, arrivals after the open snapshot, independent users, strict assignments, site-scoped managers, stale tabs, backward resume anchors, background/future-message and revoked-access rejection. Production must add transactional persistence, actual message membership validation, permission integration and realtime tests.
