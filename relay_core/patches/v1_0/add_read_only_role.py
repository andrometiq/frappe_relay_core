from relay_core.permissions import install_roles


def execute():
    """Create the read-only role without desk access before the DocType sync, which would create it with desk access."""
    install_roles()
