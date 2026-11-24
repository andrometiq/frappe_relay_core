import hashlib
import frappe
from frappe.model.document import Document
from relay_core.permissions import require_access


class RelayContactEndpoint(Document):
    def validate(self):
        # Contact sync follows a permitted Contact write.
        if getattr(frappe.flags, "relay_endpoint_enrollment", False):
            require_access(manage=True)
        elif not getattr(frappe.flags, "relay_contact_sync", False):
            require_access(configure=True)
        previous = self.get_doc_before_save()
        from relay_core.identity import canonical_endpoint, normalize
        provider = frappe.db.get_value('Relay Channel', self.channel, 'channel')
        self.canonical_endpoint = canonical_endpoint(provider, self.endpoint)
        if previous:
            canonicalizing = self.flags.get('canonicalize_identity')
            expected = normalize(provider, previous.endpoint) if canonicalizing else previous.endpoint
            if (self.channel != previous.channel or self.relay_contact != previous.relay_contact
                    or self.endpoint != expected):
                frappe.throw('Endpoint ownership is immutable; revoke the existing binding before enrolling another identity')
            if not canonicalizing:
                if self.verified and not previous.verified:
                    from relay_core.identity import bindings
                    if any(row.name != self.name for row in bindings(self.channel, provider, self.endpoint)):
                        frappe.throw('Conflicting legacy bindings require administrator review')
                self.endpoint_key = previous.endpoint_key
                return
        self.endpoint = normalize(provider, self.endpoint)
        from relay_core.identity import bindings
        if any(row.name != self.name for row in bindings(self.channel, provider, self.endpoint)):
            frappe.throw('This identity already has a binding, including legacy or revoked aliases', frappe.DuplicateEntryError)
        self.endpoint_key = hashlib.sha256((self.channel + ':' + self.endpoint).encode()).hexdigest()

    @frappe.whitelist()
    def canonicalize(self):
        """Explicit administrator upgrade of a legacy identity; uniqueness still applies."""
        require_access(configure=True)
        from relay_core.identity import normalize
        self.endpoint = normalize(frappe.db.get_value('Relay Channel', self.channel, 'channel'), self.endpoint)
        self.flags.canonicalize_identity = True
        try:
            self.save()
        finally:
            self.flags.canonicalize_identity = False


def on_doctype_update():
    install_indexes()


def install_indexes():
    """Runs on DocType update and after every migrate, because migrate skips an unchanged DocType."""
    # Channel filters on the inbox and its counts read contacts per channel from this index.
    frappe.db.add_index('Relay Contact Endpoint', ['channel', 'relay_contact'], 'relay_channel_contacts')
    # A chat's own endpoints (inbox_records.chat_endpoints, endpoint_labels) are read by contact alone.
    frappe.db.add_index('Relay Contact Endpoint', ['relay_contact'], 'relay_endpoint_contact')
    # identity.bindings finds an identity and its legacy aliases on one channel by equality.
    frappe.db.add_index('Relay Contact Endpoint', ['channel', 'canonical_endpoint'], 'relay_endpoint_canonical')
