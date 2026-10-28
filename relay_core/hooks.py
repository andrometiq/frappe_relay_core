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
doc_events = {"Relay Message": {"after_insert": ["relay_core.opt_out.on_message", "relay_core.inbox.message_created", "relay_core.relay_chats.on_message", "relay_core.translations.on_message", "relay_core.voice_transcripts.on_message", "relay_core.flows.service.on_message", "relay_core.automation.service.on_message", "relay_core.email_preferences.on_message"]}, "Relay Hub Event": {"after_insert": "relay_core.automation.projection.on_event"}, "Relay Ticket": {"on_update": "relay_core.ticket_notifications.on_update"}}
# Every job returns at once while no Relay Hub is configured.
scheduler_events = {
    "cron": {
        "* * * * *": [f"relay_core.scheduled_jobs.{job}" for job in (
            "recover_automation", "recover_projection", "recover_ticket_notifications", "recover_flows",
            "recover_messages", "recover_learning", "recover_summaries", "recover_campaigns",
            "recover_translations", "recover_voice_transcripts", "recover_business_events")],
        "*/10 * * * *": ["relay_core.scheduled_jobs.sync_whatsapp_templates"],
    },
    "daily": ["relay_core.scheduled_jobs.refresh_whatsapp_billing", "relay_core.scheduled_jobs.sync_channels"],
}

permission_query_conditions = {'Relay Contact':'relay_core.permissions.contact_query', 'Relay Message':'relay_core.permissions.message_query', 'Relay Ticket':'relay_core.tickets.query_condition'}
has_permission = {'Relay Contact':'relay_core.permissions.contact_permission', 'Relay Message':'relay_core.permissions.message_permission', 'Relay Ticket':'relay_core.tickets.permission'}
has_permission['Relay Message Action'] = 'relay_core.business_access.action_permission'
permission_query_conditions['Relay Message Action'] = 'relay_core.business_access.action_query'

app_home = "/relay"
add_to_apps_screen = [{"name":"relay_core","title":"Relay Core",
    "logo":"/assets/relay_core/images/relay.svg","route":"/relay",
    "has_permission":"relay_core.permissions.has_app_permission"}]

# Registered adapters are explicit; case definitions remain Desk configuration.
from relay_core.flows.retailer import ACTION as _retailer_action
relay_flow_actions = {'retailer.create_follow_up': _retailer_action}
from relay_core.ai.actions import CREATE_DRAFT as _draft_action, REPLY as _reply_action
relay_flow_actions.update({'create_draft': _draft_action, 'reply': _reply_action})

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
doc_events['Contact'] = {event: 'relay_core.contact_lifecycle.' + event
                         for event in ('on_update', 'on_trash', 'before_rename', 'after_rename')}

from relay_core.business_references import RELAY_DOCTYPES as _relay_doctypes
ignore_links_on_delete = list(_relay_doctypes)

required_apps = ["frappe_tools"]
doc_events['*'] = {event: 'relay_core.business_events.on_event' for event in ('after_insert', 'on_submit', 'on_cancel')}

has_permission['Relay Channel Preference'] = 'relay_core.channel_preferences.permission'
permission_query_conditions['Relay Channel Preference'] = 'relay_core.channel_preferences.query'
has_permission['Relay Chat Folder'] = 'relay_core.chat_folders.permission'
permission_query_conditions['Relay Chat Folder'] = 'relay_core.chat_folders.query'
has_permission['Relay Chat'] = 'relay_core.relay_chats.permission'
permission_query_conditions['Relay Chat'] = 'relay_core.relay_chats.query'

# Configured Relay Document Actions add a "Send on WhatsApp" button to their desk forms.
boot_session = ["relay_core.document_actions.boot_session", "relay_core.whatsapp_redirects.boot_session"]
app_include_js = ["/assets/relay_core/js/document_actions.js", "/assets/relay_core/js/whatsapp_redirects.js"]

# Old /whatsapp links open /relay once WhatsApp Core is switched off or removed.
page_renderer = ["relay_core.whatsapp_redirects.WhatsAppRedirectPage"]
