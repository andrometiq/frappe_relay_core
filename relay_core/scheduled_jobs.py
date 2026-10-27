"""Scheduler entry points. Each job returns at once on a site that has no Relay Hub."""
from collections.abc import Callable

import frappe
from relay_core import ai_features


def is_hub_configured() -> bool:
    return bool(frappe.conf.get('relay_hub_url') or frappe.db.get_single_value('Relay Settings', 'hub_url'))


def when_hub_configured(method: str, ai: bool = False) -> Callable[[], None]:
    def job():
        if is_hub_configured() and (not ai or ai_features.is_enabled()):
            frappe.get_attr(method)()

    job.__doc__ = f'Run {method} when a Relay Hub is configured.'
    return job


recover_automation = when_hub_configured('relay_core.automation.service.recover')
recover_projection = when_hub_configured('relay_core.automation.projection.recover')
recover_ticket_notifications = when_hub_configured('relay_core.ticket_notifications.recover')
recover_flows = when_hub_configured('relay_core.flows.service.recover')
recover_messages = when_hub_configured('relay_core.messaging.recover')
recover_learning = when_hub_configured('relay_core.learning.service.recover', ai=True)
recover_summaries = when_hub_configured('relay_core.summaries.recover', ai=True)
recover_campaigns = when_hub_configured('relay_core.campaigns.recover')
recover_translations = when_hub_configured('relay_core.translations.recover', ai=True)
recover_voice_transcripts = when_hub_configured('relay_core.voice_transcripts.recover', ai=True)
recover_business_events = when_hub_configured('relay_core.business_events.recover')
sync_whatsapp_templates = when_hub_configured('relay_core.whatsapp_templates.sync')
refresh_whatsapp_billing = when_hub_configured('relay_core.billing.refresh_configured')
sync_channels = when_hub_configured('relay_core.channel_sync.sync')
