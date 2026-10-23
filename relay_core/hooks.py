app_name = "relay_core"
app_title = "Relay Core"
app_publisher = "Andrometiq"
app_description = "Multi-channel business communication"
app_email = "support@andrometiq.com"
app_license = "MIT"
before_install = "relay_core.permissions.install_roles"
after_migrate = "relay_core.permissions.after_migrate"
after_install = "relay_core.permissions.after_migrate"
on_login = "relay_core.login.use_site_scoped_boot_cache"

# Off until explicitly configured on an isolated/validated site.
doc_events = {"Relay Message": {"after_insert": ["relay_core.inbox.message_created", "relay_core.translations.on_message", "relay_core.flows.service.on_message", "relay_core.automation.service.on_message", "relay_core.email_preferences.on_message"]}, "Relay Hub Event": {"after_insert": "relay_core.automation.projection.on_event"}, "Relay Ticket": {"on_update": "relay_core.ticket_notifications.on_update"}}
scheduler_events = {"cron": {"* * * * *": ["relay_core.automation.service.recover", "relay_core.automation.projection.recover", "relay_core.ticket_notifications.recover", "relay_core.flows.service.recover", "relay_core.messaging.recover", "relay_core.learning.service.recover", "relay_core.summaries.recover", "relay_core.campaigns.recover", "relay_core.translations.recover"]}}

permission_query_conditions = {'Relay Contact':'relay_core.permissions.contact_query', 'Relay Message':'relay_core.permissions.message_query', 'Relay Ticket':'relay_core.tickets.query_condition'}
has_permission = {'Relay Contact':'relay_core.permissions.contact_permission', 'Relay Message':'relay_core.permissions.message_permission', 'Relay Ticket':'relay_core.tickets.permission'}
for _doctype in ('Relay Automation Run', 'Relay Business Event Delivery'):
    has_permission[_doctype] = 'relay_core.permissions.internal_record_permission'
    permission_query_conditions[_doctype] = 'relay_core.permissions.internal_record_query'

app_home = "/relay"
add_to_apps_screen = [{"name":"relay_core","title":"Relay Core",
    "logo":"/assets/relay_core/images/relay.svg","route":"/relay",
    "has_permission":"relay_core.permissions.has_app_permission"}]

# Registered adapters are explicit; case definitions remain Desk configuration.
from relay_core.flows.retailer import ACTION as _retailer_action
relay_flow_actions = {'retailer.create_follow_up': _retailer_action}

# Realtime invalidations contain no record payload; browser reads recheck permissions.
from relay_core.realtime import RESOURCES as _realtime_resources
for _doctype in _realtime_resources:
    _events = doc_events.setdefault(_doctype, {})
    for _event in ('on_update', 'on_trash'):
        _existing = _events.get(_event, [])
        if isinstance(_existing, str): _existing = [_existing]
        _events[_event] = [*_existing, 'relay_core.realtime.changed']

doc_events.setdefault('Prepared Report', {})['on_update'] = 'relay_core.prepared_reports.notify'
doc_events.setdefault('Prepared Report', {})['on_trash'] = 'relay_core.prepared_reports.cleanup'
has_permission['Prepared Report'] = 'relay_core.prepared_reports.permission'
has_permission['File'] = 'relay_core.prepared_reports.file_permission'

from relay_core.saved_reply_actions import NOTE_ACTION as _saved_note_action
relay_saved_reply_actions = {'relay.add_internal_note': _saved_note_action}

doc_events["Relay Message"]["before_insert"] = "relay_core.business_access.associate"

from relay_core.business_references import RELAY_DOCTYPES as _relay_doctypes
ignore_links_on_delete = list(_relay_doctypes)
doc_events['*'] = {event: 'relay_core.business_references.allow_cancel'
                   for event in ('before_cancel', 'on_cancel')}

required_apps = ["frappe_tools"]
after_migrate = [after_migrate, 'relay_core.business_events.install_samples']
after_install = [after_install, 'relay_core.business_events.install_samples']
for _event in ('after_insert', 'on_submit', 'on_cancel'):
    _handlers = doc_events['*'].get(_event, [])
    if isinstance(_handlers, str): _handlers = [_handlers]
    doc_events['*'][_event] = [*_handlers, 'relay_core.business_events.on_event']
scheduler_events['cron']['* * * * *'].append('relay_core.business_events.recover')

after_migrate.append('relay_core.ai.samples.install_samples')
after_install.append('relay_core.ai.samples.install_samples')
