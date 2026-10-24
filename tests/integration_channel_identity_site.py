"""Cross-channel enrollment from signed callbacks on the approved local site."""
import frappe
from channel_site_fixtures import init, check_business_lifecycle
from channel_identity_fixtures import scenario, configured, incoming, email_raw, telegram_raw, fails
from relay_core import enrollment, api

init()
try:
    fixture = scenario()
    with configured(fixture):
        bindings = []
        for provider, sender in [('WhatsApp', '919555000123'), ('Telegram', '9555000123'),
                                  ('Email', 'LOCAL-C2-' + fixture.stamp + '@EXAMPLE.INVALID')]:
            body = 'Local order quantity 25'
            raw = email_raw('<identity-' + fixture.stamp + '@example.invalid>') if provider == 'Email' else (
                telegram_raw(int(sender), 101, body) if provider == 'Telegram' else None)
            event, identifier = incoming(fixture, provider, sender, body, raw=raw,
                                         identifier='101' if provider == 'Telegram' else None)
            assert event.projection_status == 'Uncategorized'
            result = enrollment.bind(event.name, identifier, fixture.contact.name,
                                     fixture.customer.doctype, fixture.customer.name)
            assert result['status'] == 'Projected'
            assert enrollment.bind(event.name, identifier, fixture.contact.name,
                                   fixture.customer.doctype, fixture.customer.name) == result
            rows = frappe.get_all('Relay Contact Endpoint', filters={'channel': fixture.channels[provider].name},
                                  fields=['name', 'endpoint', 'relay_contact'])
            assert len(rows) == 1 and rows[0].relay_contact == fixture.contact.name
            assert rows[0].endpoint == sender.lower()
            bindings.append(rows[0].name)
            fails(lambda: enrollment.bind(event.name, 'invented', fixture.contact.name,
                                           fixture.customer.doctype, fixture.customer.name))
        details = api.contact_details(fixture.person.name)
        assert {row.provider for row in details['endpoints']} == {'WhatsApp', 'Telegram', 'Email'}
        email_binding = frappe.get_doc('Relay Contact Endpoint', bindings[-1])
        duplicate = frappe.get_doc({'doctype': 'Relay Contact Endpoint', 'channel': email_binding.channel,
            'relay_contact': fixture.contact.name, 'endpoint': email_binding.endpoint.upper(), 'verified': 1})
        fails(lambda: duplicate.insert(), (frappe.UniqueValidationError, frappe.DuplicateEntryError))
        other_person = frappe.get_doc({'doctype': 'Contact', 'first_name': 'Local C2 other ' + fixture.stamp,
            'links': [{'link_doctype': fixture.customer.doctype, 'link_name': fixture.customer.name}]}).insert()
        other = frappe.get_doc({'doctype': 'Relay Contact', 'contact': other_person.name, 'display_name': 'Local C2 other'}).insert()
        frappe.db.commit()
        fails(lambda: enrollment.bind(event.name, identifier, other.name, fixture.customer.doctype, fixture.customer.name))
        email_binding.reload(); email_binding.relay_contact = other.name
        fails(email_binding.save)
        assert enrollment.revoke(bindings[-1])['verified'] is False
        frappe.db.commit()
        fails(lambda: enrollment.bind(event.name, identifier, fixture.contact.name,
                                       fixture.customer.doctype, fixture.customer.name))
        next_event, _ = incoming(fixture, 'Email', sender.lower(), 'Revoked quantity 50',
                                 raw=email_raw('<revoked-' + fixture.stamp + '@example.invalid>'))
        assert next_event.projection_status == 'Uncategorized'
        assert set(__import__('json').loads(next_event.routing_decisions).values()) == {'triage_unverified'}
        for provider, value, canonical in [('WhatsApp', '+91 (9555) 000124', '919555000124'),
                                            ('Telegram', '0009555000124', '9555000124')]:
            from channel_identity_fixtures import endpoint
            assert endpoint(fixture, provider, value).endpoint == canonical
        frappe.db.commit()
        # Simulate stored pre-normalization rows without rewriting their identity on revocation.
        import hashlib
        for provider, formatted in [('WhatsApp', '+91 (9555) 000125'),
                                    ('Email', 'LEGACY-' + fixture.stamp + '@EXAMPLE.INVALID')]:
            legacy = endpoint(fixture, provider, formatted)
            old_key = hashlib.sha256((legacy.channel + ':' + formatted).encode()).hexdigest()
            frappe.db.set_value('Relay Contact Endpoint', legacy.name, {'endpoint': formatted, 'endpoint_key': old_key})
            frappe.db.commit()
            assert enrollment.revoke(legacy.name)['verified'] is False
            legacy.reload()
            assert legacy.endpoint == formatted and legacy.endpoint_key == old_key
            # The revoked canonical alias cannot be re-enrolled under either contact.
            canonical = __import__('relay_core.identity', fromlist=['normalize']).normalize(provider, formatted)
            raw = email_raw('<legacy-alias-' + fixture.stamp + '@example.invalid>') if provider == 'Email' else None
            legacy_event, legacy_id = incoming(fixture, provider, canonical, 'Revoked alias quantity 50', raw=raw)
            for owner in (fixture.contact.name, other.name):
                fails(lambda: enrollment.bind(legacy_event.name, legacy_id, owner, 'Customer', fixture.customer.name))
                fails(lambda: endpoint(fixture, provider, canonical, owner),
                    (frappe.DuplicateEntryError, frappe.UniqueValidationError))
            assert frappe.db.count('Relay Contact Endpoint', {'channel': legacy.channel, 'relay_contact': other.name}) == 0
            legacy.verified = 1; legacy.save(); frappe.db.commit()
            assert legacy.endpoint == formatted and legacy.endpoint_key == old_key
            legacy.canonicalize(); frappe.db.commit(); legacy.reload()
            from relay_core.identity import normalize
            assert legacy.endpoint == normalize(provider, formatted)
            assert legacy.endpoint_key != old_key
        print('PASS legacy formatted endpoints revoke/reactivate unchanged; explicit canonicalization upgrades identities')
        check_business_lifecycle(fixture.customer)
        print('PASS one person across three channels; normalized conflicts, immutable ownership, revocation, callback replay and business lifecycle')
finally:
    frappe.destroy()
