# Relay acceptance checkpoint — 2026-09-24

This supplements the historical September 23 audit; it does not replace the original scope or certify completion. Actual data migration remains on hold.

## Installed realtime acceptance

A fresh authenticated browser context opened yrp.site:8002/relay#/messages without API interception. It displayed Live. Frappe published a payload-free relay_changed messages event after commit into the real Relay Message doctype room. The browser received one WebSocket event and made one inbox-directory refresh request 151 ms afterward. No business records or provider messages were created. This proves installed server→Redis→Socket.IO→browser→API invalidation; it does not prove every workspace subscription, provider callback latency, reconnect recovery or high-volume behavior.

## Current concrete gaps

- Campaigns now accept WhatsApp, Telegram and Email with provider-specific operation validation, and the audience UI supports multiple business records. Local campaign integration tests cover these paths; live multi-provider campaign acceptance remains outstanding. This supersedes the earlier WhatsApp-only finding.
- Populated native Daily summary Prepared Reports now have isolated integration evidence for PDF/Excel output, source references, cache reuse, edited-source invalidation and revoked-access rejection. These tests use a fixture model. Live installed worker execution with populated data and real inference remains outstanding.
- Email recipient selection, optimistic state, durable uncertain-attempt restoration and reviewed retry now have isolated database plus browser fixture evidence. Installed yrp.site has only Telegram enabled and no email messages; real mailbox end-to-end acceptance remains outstanding.
- Telegram outbound typing is implemented and loaded in local Hub/Core. Scoped routing, throttling and account authorization passed synthetic checks; display on a real Telegram client is not yet observed. No incoming customer typing capability is claimed.
- Native template authoring now has category and language controls (`whatsapp/TemplateEditor.vue`); the old minimal-form finding is historical. Full provider template lifecycle acceptance remains to be established.
- Canned text/location/contact replies and explicit Desk-configured business actions now exist, including Add internal note. Bounded paging, retry receipts and crash-after-side-effect protection have isolated database/browser evidence. Live business-action execution remains to be accepted.
- Complete per-tab realtime acceptance, provider-specific attachment coverage, both-theme review across all workflows and representative-load measurements remain open acceptance work.
- Migration capability must be verified separately from migrating real data. Do not import sales-prod messages while the user hold remains active.

The full requirement inventory remains the original audit, user instructions and communication-expansion specification. This checkpoint records evidence and confirmed next work; it is not a narrowed completion definition.

## Installed status pipeline and inspector checkpoint

The 41-check channel-status regression passed. The Hub now runs migration 0028
and its independent bounded status dispatcher; Core's matching HTTP receiver
and background projection are installed. A real signed HTTP request on yrp.site
created synthetic event RELAY-EVT-0000000006, which its actual worker projected.
No provider message was sent. This is not live provider acceptance.

Hub Events now defaults to an account/channel-scoped message inspector with
bounded server pagination and on-demand payload previews. System activity is a
separate tab. Database isolation/pagination tests and both-theme desktop/mobile
browser fixture checks passed; the local Hub release is deployed and ready.

A fresh authenticated installed Core browser displayed Live and the overlapping
reader avatars with Seen by 2 in the Telegram conversation. No API interception
was used for that check. Actual WhatsApp credentials remain user-managed, and
actual data migration remains on hold.
