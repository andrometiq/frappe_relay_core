"""Executable specification only: no Frappe/database/provider integration."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Conversation:
    site: str
    assigned_user: str | None
    inbound_sequences: tuple[int, ...]
    committed_sequence: int


@dataclass(frozen=True)
class Actor:
    site: str
    user: str
    manager: bool = False


def authorize(actor: Actor, conversation: Conversation) -> None:
    if actor.site != conversation.site or not (
        actor.manager or actor.user == conversation.assigned_user
    ):
        raise PermissionError("Conversation is not assigned to this user")


@dataclass
class ReadState:
    # Caller must obtain this row from authenticated actor + conversation key.
    badge_through: int = 0
    viewport_anchor: int | None = None
    viewport_session: int = 0
    viewport_version: int = 0
    viewed: set[int] = field(default_factory=set)

    def open(self, actor: Actor, conversation: Conversation) -> dict:
        authorize(actor, conversation)
        previous = self.viewport_anchor
        self.viewport_session += 1
        self.viewport_version = 0
        self.badge_through = max(self.badge_through, conversation.committed_sequence)
        return {
            "snapshot_seq": conversation.committed_sequence,
            "previous_anchor": previous,
            "session": self.viewport_session,
            "version": self.viewport_version,
        }

    def view(self, actor: Actor, conversation: Conversation, *, session: int,
             version: int, visible: set[int], anchor: int, foreground: bool) -> int:
        authorize(actor, conversation)
        if session != self.viewport_session or version != self.viewport_version:
            raise ValueError("Stale viewport update")
        if not foreground:
            raise ValueError("Background tabs cannot record views")
        if len(visible) > 100 or not visible or anchor not in visible:
            raise ValueError("Expected a bounded visible page containing the anchor")
        # This model uses contiguous ingestion sequences; production must validate
        # actual message IDs against the authorized conversation, including tombstones.
        if any(type(n) is not int or n < 1 or n > conversation.committed_sequence for n in visible):
            raise ValueError("Message is outside the committed conversation")
        self.viewed.update(visible)
        self.viewport_anchor = anchor  # Backward scrolling is deliberately permitted.
        self.viewport_version += 1
        return self.viewport_version

    def unread(self, actor: Actor, conversation: Conversation) -> int:
        authorize(actor, conversation)
        return sum(n > self.badge_through and n not in self.viewed
                   for n in conversation.inbound_sequences)
