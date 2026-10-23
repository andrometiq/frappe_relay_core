# Email recipient selection

The inbox email composer uses API-backed multi-selects for To, CC and BCC. Searches debounce for 300 ms, cancel superseded requests and return at most 30 verified addresses for the current contact and email channel. An exact verified address can resolve another readable business contact for forwarding or copying. Recipient verification is repeated when sending. Draft recipient selections survive channel tab switches. Both themes use the shared Frappe choice field.

## Verification (2026-09-24)

- Isolated Frappe integration: verified address filtering, literal wildcard handling, 30-result bound, search beyond the initial results, email reply attachments, threading, forwarding and revoked-recipient protection passed. Provider calls were mocked.
- Browser acceptance: To/CC search reaches the API, selections survive channel switches; existing Enter sending, drafts, attachment cancellation, bounded bidirectional history, dark theme and mobile overflow checks passed. Core API responses were fixtures.
- A report permission hook regression denied ordinary files because this Frappe version treats a None controller result as denial. Unrelated files/reports and authorized report checks now return True, allowing Frappe's remaining permission checks to run. Email attachment and prepared report regression checks passed.
- Local yrp.site build and web/worker reload completed. Authenticated report API returned HTTP 200; recipient API rejected an invalid source with HTTP 417. No real provider email was sent, and real mailbox end-to-end acceptance remains outstanding.

## Email send feedback

Email sends now show an immediate Sending bubble. Acknowledged sends are replaced by their persisted message when history loads; an unconfirmed response preserves the draft and displays Check status. That action reads Core's stored receipt and never invokes the provider. It cannot discover a provider acceptance that failed before Core saved its receipt; such sends remain unconfirmed. Email sends anchored to a conversation now create a durable Relay Message Action before provider I/O. The inbox restores unresolved actions after a full reload through its bounded pending-message API. Request replay reads the existing outcome and never sends again. Changed content with the same request key is rejected. Core automatic replies now use the same durable path.

Drafts are shared reactively per email conversation. Responses clear only the matching unchanged draft, including when its composer was destroyed by switching channels. A response does not clear another channel's draft.

Verification: browser fixtures passed delayed sending, channel switching, draft preservation, failed-response preservation and checking status without a second send. The isolated email integration test verified a persisted receipt lookup and unknown request lookup without provider calls. These are synthetic acceptance checks, not real mailbox delivery evidence.

Durable recovery checks passed in the isolated Frappe site: timeout persistence, pending inbox restoration, receipt recovery after an incomplete action update, no provider calls during replay/reconciliation, immutable payload identity and automatic-reply deduplication. Four email permission/validation unit tests passed. The browser fixture passed a full reload followed by pending email status checking without an additional send. Real provider acceptance remains outstanding.

Confirmed rejection remains Failed. New email attempts retain their original request fields for an explicit reviewed retry through Message activity. Only the original sender can retry a rejected attempt; the retry has a stable child identity and rechecks recipients, attachments and source access. Older email attempts without saved request fields do not offer retry. Uncertain sends cannot use this action. Non-conversation legacy email callers still use the existing Hub path.

Reviewed retry verification: isolated integration rejected an unverified recipient before any provider call, added its verified binding, retried once successfully, replayed that retry without another send, and denied retrying an uncertain action. Browser fixtures passed the review/retry workflow and displayed “Sent”. The activity dialog now uses Sending, Sent, Unconfirmed and Failed labels.

Installed-site inspection on 2026-09-24 found Telegram as the only enabled channel and zero email messages. Email provider end-to-end verification therefore remains outstanding; no mailbox configuration was invented or changed by these tests.
