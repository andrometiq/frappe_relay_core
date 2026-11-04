"""Knowledge source ingest into Relay AI Knowledge Chunk rows."""


def on_event_change(doc, method=None) -> None:
    """Relay AI Event hook: refresh the event's knowledge source. Built with the knowledge base chunk."""


def sync_due() -> None:
    """Daily job: re-sync auto-sync sources. Built with the knowledge base chunk."""
