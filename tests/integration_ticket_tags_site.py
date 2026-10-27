"""Create tickets from a chat, tag users, notify assignees and deny users outside the conversation."""
from site_labels import run_label
import frappe
from relay_core import tickets, ticket_tags, teams
from channel_site_fixtures import init, business as fixture_business, user as fixture_user
init()
run = run_label().lower()
author = fixture_user(f'relay-tag-author-{run}@example.invalid')
helper = fixture_user(f'relay-tag-helper-{run}@example.invalid')
outsider = fixture_user(f'relay-tag-outsider-{run}@example.invalid')
manager = fixture_user(f'relay-tag-manager-{run}@example.invalid', manager=True)
business = fixture_business('Ticket tags ' + run)
person = frappe.get_doc({'doctype': 'Contact', 'first_name': 'Ticket tags ' + run,
    'links': [{'link_doctype': business.doctype, 'link_name': business.name}]}).insert()
contact = frappe.get_doc({'doctype': 'Relay Contact', 'contact': person.name, 'display_name': 'Ticket tags ' + run}).insert()
channel = frappe.get_doc({'doctype': 'Relay Channel', 'channel': 'Email', 'account': 'tags-' + run, 'enabled': 1}).insert()
message = frappe.get_doc({'doctype': 'Relay Message', 'relay_contact': contact.name, 'channel': channel.name,
    'direction': 'Incoming', 'content': 'Parcel arrived damaged', 'status': 'Sent',
    'business_doctype': business.doctype, 'business_name': business.name}).insert()
team = teams.save('Ticket tags ' + run, [author, helper]); teams.assign(contact.name, team['name'])
frappe.db.commit()


def denied(fn):
    try:
        fn()
    except (frappe.PermissionError, frappe.ValidationError):
        frappe.db.rollback()
    else:
        raise AssertionError('Unauthorized operation accepted')


def logs(user, kind):
    return frappe.get_all('Notification Log', filters={'for_user': user, 'type': kind,
        'document_type': 'Relay Ticket', 'document_name': ticket}, fields=['link', 'subject'])


def notices(user):
    return [entry for entry in frappe.publish_realtime.call_args_list
            if entry.args[0] == 'relay_ticket_notice' and entry.kwargs.get('user') == user]


def listed(mine):
    return {row['name'] for row in tickets.directory(mine=mine)['items']}


frappe.set_user(author)
denied(lambda: tickets.create('Damaged parcel', [message.name], tagged=[outsider]))
denied(lambda: tickets.create('Damaged parcel', [message.name], assigned_to=outsider))
denied(lambda: tickets.create('Damaged parcel', [message.name], priority='Critical'))
print('PASS create denies outsiders as tagged users or assignee and rejects unknown priority')

frappe.publish_realtime.reset_mock()
ticket = tickets.create('Damaged parcel', [message.name], brief='Customer sent photos', priority='High',
                        assigned_to=helper)['name']
frappe.db.commit()
created = tickets.read(ticket)
assert created['priority'] == 'High' and created['assigned_to'] == helper
assert (created['business_doctype'], created['business_name']) == (business.doctype, business.name)
assert logs(helper, 'Assignment') and logs(helper, 'Assignment')[0].link == '/relay#/tickets?ticket=' + ticket
assert notices(helper) and notices(helper)[0].args[1]['ticket'] == ticket
assert not logs(author, 'Assignment'), 'The actor must not notify themselves'
print('PASS chat ticket keeps business link, assignee gets Notification Log and live notice')

frappe.set_user(helper)
assert ticket in listed('assigned') and ticket not in listed('tagged')
frappe.set_user(outsider)
denied(lambda: tickets.read(ticket))
denied(lambda: ticket_tags.comments(ticket))
denied(lambda: ticket_tags.add_comment(ticket, 'Let me in'))
assert ticket not in listed('')
print('PASS assigned-to-me filter and outsider is denied read and comment')

frappe.set_user(author)
denied(lambda: ticket_tags.add_comment(ticket, '@Outsider please check', [outsider]))
denied(lambda: ticket_tags.set_tagged(ticket, [outsider]))
frappe.set_user(manager)
ticket_tags.set_tagged(ticket, [])
frappe.db.commit()
frappe.set_user(author)
frappe.publish_realtime.reset_mock()
ticket_tags.add_comment(ticket, '@Helper please call the customer', [helper])
frappe.db.commit()
assert [row['user'] for row in tickets.read(ticket)['tagged']] == [helper]
assert logs(helper, 'Mention') and notices(helper)
assert ticket_tags.comments(ticket)[-1]['body'] == '@Helper please call the customer'
frappe.set_user(helper)
assert ticket in listed('tagged')
print('PASS mention in a comment tags the user, notifies them and shows under tagged me')

frappe.set_user(author)
denied(lambda: tickets.assign(ticket, author))
frappe.set_user(manager)
tickets.assign(ticket, author)
frappe.db.commit()
assert logs(author, 'Assignment'), 'A reassignment must notify the new assignee'
print('PASS only a manager reassigns and the new assignee is notified')
