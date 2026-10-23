# Troubleshooting

| Symptom | Check |
| --- | --- |
| Core requests return login or permission errors | Use the Frappe site's session/API user; verify Relay role and document permissions |
| MCP rejects a browser request | Use Frappe REST methods from the browser; MCP requires API-token authentication without an Origin header |
| Hub connection is rejected | Check full MCP URL, account grant, operation scope, and site/account mapping |
| HTTP development URL is refused | Core's Hub client only allows plaintext HTTP for explicit loopback IPs |
| Incoming event remains uncategorized | Check Relay Channel account and verified Relay Contact Endpoint; do not guess an identity from a matching number |
| Reaction/edit remains uncategorized | The original target message or verified endpoint may not exist yet; inspect the event before reprocessing |
| Sticker is unavailable | Check source-message permissions, inbound account ownership, 2 MiB limit, and supported WebP/WebM/TGS format |
| Animated sticker offers fallback | The browser may lack decompression support, or animation complexity/format may exceed the renderer's bounds |
| Location/contact/reaction cannot be sent to a WhatsApp group | Those group message types are outside Meta's documented supported set |
| Action is Uncertain or stays Dispatching | Inspect Relay Message Action and provider evidence; do not create a new key to blindly resend |
| Messages/Automation view is unavailable in local preview | The standalone preview has no authenticated same-origin Frappe backend |
| AI does not reply | Check the site switch, enabled channel/provider/policy, verified endpoint, execution-user permissions, and Shadow mode |

Inspect a record by its Relay name and correlate its provider/message/action IDs.
Keep secrets and contact content out of issue reports. Include the operation,
sanitized status, timestamp, and failing test or reproduction steps instead.

For an uncertain submission, reconcile with Hub/provider evidence before making
another send attempt. Reusing a request key reports the stored intent status;
it is not a promise of automatic delivery reconciliation.
