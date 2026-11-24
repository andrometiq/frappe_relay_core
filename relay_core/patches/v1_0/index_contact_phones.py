def execute():
    """identity.contacts_by_phone reads candidates from the phone index, so it starts with every Contact's phones."""
    from relay_core.relay_core.doctype.relay_phone_index.relay_phone_index import rebuild
    rebuild()
