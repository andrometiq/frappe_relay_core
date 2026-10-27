# OpenAI and configured fallback

Relay AI Provider now accepts OpenAI with a user-configured model identifier and an encrypted API key. The fixed-host adapter uses `POST https://api.openai.com/v1/responses`, requests JSON text with a 1500 output-token cap, and sets `store: false`. It scans assistant message output rather than assuming the first output item is text, and rejects incomplete or refused responses. All decisions still pass Relay's existing allowed-action validator.

Automation policies, automatic translation and learned procedures use the policy AI Model from frappe_tools. Relay AI Provider is used only for voice transcription. Each AI attempt counts against the daily policy budget. Scope and policy version are rechecked before any action.

Configure providers in installed Settings or Frappe Desk. Blank key edits preserve the encrypted key; changing the provider requires a new key. API read responses never include keys. Live provider credentials and model availability remain user-configured; local acceptance uses synthetic transports only.

Contract checked against official [Responses reference](https://developers.openai.com/api/reference/cli/resources/responses/methods/create) and [text generation guide](https://developers.openai.com/api/docs/guides/text), 2026-09-23. This integration uses the OpenAI API; it does not reuse a Codex application login.
