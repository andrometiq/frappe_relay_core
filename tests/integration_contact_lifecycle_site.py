"""Contact edits, links, deletes and merges keep endpoints and access in step on the local site."""
import json

import frappe
from channel_site_fixtures import init, user
from channel_identity_fixtures import scenario, configured, incoming, endpoint, fails, cleanup
from site_labels import phone
from relay_core import enrollment, whatsapp
from relay_core.business_access import candidates

init()
fixture = scenario()


def endpoints(contact=None):
    return {row.endpoint: row.verified for row in frappe.get_all('Relay Contact Endpoint',
            filters={'relay_contact': contact or fixture.contact.name}, fields=['endpoint', 'verified'])}


def decisions(event):
    return set(json.loads(event.routing_decisions).values())


def message(business, body):
    return frappe.get_doc({'doctype': 'Relay Message', 'relay_contact': fixture.contact.name,
        'channel': fixture.channels['WhatsApp'].name, 'direction': 'Outgoing', 'status': 'Sent',
        'content': body, 'sender_endpoint': first, 'business_doctype': business.doctype,
        'business_name': business.name}).insert(ignore_permissions=True)


def visible(actor, name):
    frappe.set_user(actor)
    try:
        return (bool(frappe.get_list('Relay Message', filters={'name': name}, pluck='name'))
                and frappe.get_doc('Relay Message', name).has_permission('read'))
    finally:
        frappe.set_user('Administrator')


try:
    with configured(fixture):
        first, second, third = (phone(fixture.stamp + suffix) for suffix in (' first', ' second', ' third'))
        mail = 'sim-lifecycle-' + fixture.stamp.lower() + '@example.invalid'
        person = fixture.person
        # Email first: essdee_yrp_partner ties a Contact email to one mobile on this site.
        person.append('email_ids', {'email_id': mail.upper(), 'is_primary': 1}); person.save(); frappe.db.commit()
        endpoint(fixture, 'Email', mail); frappe.db.commit()
        person.reload(); person.email_ids[0].email_id = 'sim-new-' + mail; person.save(); frappe.db.commit()
        assert endpoints() == {mail: 0, 'sim-new-' + mail: 1}
        person.reload(); person.email_ids = []; person.email_id = None; person.save(); frappe.db.commit()
        assert endpoints() == {mail: 0, 'sim-new-' + mail: 0}

        person.reload(); person.append('phone_nos', {'phone': '+' + first[:2] + ' ' + first[2:], 'is_primary_mobile_no': 1})
        person.save(); frappe.db.commit()
        endpoint(fixture, 'WhatsApp', first); frappe.db.commit()
        mails = {mail: 0, 'sim-new-' + mail: 0}
        assert endpoints() == {first: 1, **mails}

        # Format-only edits (leading 0, spaces) keep the same identity.
        person.reload(); person.phone_nos[0].phone = '0' + first[2:7] + ' ' + first[7:]; person.save(); frappe.db.commit()
        assert endpoints() == {first: 1, **mails}
        assert whatsapp.prepare('messages.send', {'body': 'Hello'}, person.name, 'Customer', fixture.customer.name)['to'] == first

        # Outbound needs a link; inbound routing asks between the linked businesses.
        fails(lambda: whatsapp.prepare('messages.send', {'body': 'Hello'}, person.name, 'Customer', 'Sim Unlinked Customer'))
        event, _ = incoming(fixture, 'WhatsApp', first, 'Quantity 25 please')
        assert decisions(event) == {'triage_prompt_pending'}
        old_message = message(fixture.customer, 'Order note quantity 25'); frappe.db.commit()

        # A manager's number change disables the old endpoint and verifies the new one.
        person.reload(); person.phone_nos[0].phone = '+' + second; person.save(); frappe.db.commit()
        assert endpoints() == {first: 0, second: 1, **mails}
        old_event, _ = incoming(fixture, 'WhatsApp', first, 'Old number quantity 25')
        assert decisions(old_event) == {'triage_unverified'}
        new_event, _ = incoming(fixture, 'WhatsApp', second, 'New number quantity 25')
        assert decisions(new_event) == {'triage_prompt_pending'}
        assert frappe.db.get_value('Relay Message', old_message.name, 'relay_contact') == fixture.contact.name
        assert visible(fixture.actor, old_message.name)

        # A plain Contact editor only stops the removed number.
        editor = user('relay-lifecycle-editor-' + fixture.stamp + '@example.invalid')
        frappe.set_user(editor)
        person = frappe.get_doc('Contact', person.name)
        person.phone_nos[0].phone = '+' + third; person.save(); frappe.db.commit()
        frappe.set_user('Administrator')
        assert endpoints() == {first: 0, second: 0, **mails}

        # A shared number stays with its existing binding.
        def reverify(value):
            name = frappe.db.get_value('Relay Contact Endpoint', {'relay_contact': fixture.contact.name, 'endpoint': value})
            frappe.db.set_value('Relay Contact Endpoint', name, 'verified', 1); frappe.db.commit()
            return name
        reverify(second)
        person.reload(); person.phone_nos[0].phone = '+' + second; person.save(); frappe.db.commit()
        other_person = frappe.get_doc({'doctype': 'Contact', 'first_name': 'Sim Lifecycle Other ' + fixture.stamp,
            'phone_nos': [{'phone': '+' + third, 'is_primary_mobile_no': 1}],
            'links': [{'link_doctype': 'Customer', 'link_name': fixture.customer.name}]}).insert()
        other = frappe.get_doc({'doctype': 'Relay Contact', 'contact': other_person.name,
                                'display_name': 'Sim Lifecycle Other'}).insert()
        endpoint(fixture, 'WhatsApp', third, other.name); frappe.db.commit()
        person.reload(); person.phone_nos[0].phone = '+' + third; person.save(); frappe.db.commit()
        assert endpoints(other.name) == {third: 1}
        assert endpoints() == {first: 0, second: 0, **mails}

        # Removing a business link ends access to that business's history at once.
        assert visible(fixture.actor, old_message.name)
        person.reload(); person.links = [row for row in person.links if row.link_doctype != 'Customer']
        person.save(); frappe.db.commit()
        assert ('Customer', fixture.customer.name) not in candidates(fixture.contact.name)
        assert not visible(fixture.actor, old_message.name)
        fails(lambda: whatsapp.prepare('messages.send', {'body': 'Hello'}, person.name, 'Customer', fixture.customer.name))
        person.reload(); person.append('links', {'link_doctype': 'Customer', 'link_name': fixture.customer.name})
        person.save(); frappe.db.commit()
        assert visible(fixture.actor, old_message.name)

        # The reading user's own business permission decides access.
        supplier_message = message(fixture.supplier, 'Supplier note quantity 25'); frappe.db.commit()
        assert not visible(fixture.actor, supplier_message.name)

        # Revocation stops routing.
        assert enrollment.revoke(reverify(second))['verified'] is False; frappe.db.commit()
        revoked_event, _ = incoming(fixture, 'WhatsApp', second, 'Revoked quantity 25')
        assert decisions(revoked_event) == {'triage_unverified'}

        # Delete is blocked while Relay history exists; a merge moves it to the target Contact.
        fails(lambda: frappe.delete_doc('Contact', person.name), frappe.LinkExistsError)
        fails(lambda: frappe.rename_doc('Contact', other_person.name, person.name, merge=True))
        target = frappe.get_doc({'doctype': 'Contact', 'first_name': 'Sim Lifecycle Target ' + fixture.stamp,
            'links': [{'link_doctype': 'Customer', 'link_name': fixture.customer.name}]}).insert()
        frappe.db.commit()
        frappe.rename_doc('Contact', other_person.name, target.name, merge=True); frappe.db.commit()
        assert frappe.db.get_value('Relay Contact', other.name, 'contact') == target.name
        assert not frappe.db.exists('Contact', other_person.name)
        assert candidates(other.name) == [('Customer', fixture.customer.name)]
        renamed = frappe.rename_doc('Contact', target.name, 'Sim Lifecycle Renamed ' + fixture.stamp)
        frappe.db.commit()
        assert frappe.db.get_value('Relay Contact', other.name, 'contact') == renamed
    print('contact lifecycle site checks passed')
finally:
    cleanup(fixture)
