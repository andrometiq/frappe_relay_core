from relay_core import relay_chats


def execute():
    """Build the Relay Chat rows of existing messages. The rows are derived, so a second run rewrites the same values."""
    relay_chats.rebuild()
