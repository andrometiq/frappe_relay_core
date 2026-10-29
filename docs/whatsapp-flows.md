# Channel automation and flows

Current access: [business type assignments](business-access.md). Team controls and group claims are hidden; team-related descriptions below refer to retained legacy implementation.


A flow guides a customer through questions, answers and business actions on WhatsApp, Telegram or Email. Relay Communication Managers can save, publish and enable flows under **Automation → Flows**. A System Manager turns the feature on in **Settings & Setup** with **Enable flows**. The switch is off by default. While it is off, the Flows page is hidden, the API refuses flow calls and no inbound message starts or continues a flow.

## Channel automation

**Automation → Channel automation** configures ordered steps on an existing Relay Channel. Managers can edit only automation settings through this API; transport configuration remains restricted. Save uses a revision check, and the screen refreshes through Socket.IO without polling.

Identity, consent keywords, duplicate admission, staff ownership and explicit requests for a person are checked before the configured pipeline. A waiting flow retains follow-up replies. A channel with no rows keeps legacy admission: its mandatory episode ticket, pending AI-search continuation, flow and automatic skill matching. AI still requires both site and Settings switches; flows require Enable flows.

Configured rows are **Flow**, **AI skill**, **Assign**, **Ticket**, and **Out of hours reply**. Unmatched/disabled rows continue. Stop ends the pipeline when that row handles the message. Continue permits later rows; once a flow, skill or reply claims the response, remaining response handlers are skipped. Assignment and ticket enrichment can continue. Rows are snapshotted into the existing Automation Run for recovery; disabling channel automation fences queued work and automatic email fallback.

The mandatory episode ticket remains the ownership record. Ticket **Always** enriches/reuses it, **Create if not resolved** does so only while it is open, and **Never** skips this optional enrichment. These rules never remove admission tickets or create competing active episodes.

Out of hours replies use an IANA timezone, opening/closing times and working days. The opening boundary is inclusive and closing is exclusive. Overnight hours belong to the opening day; daylight saving follows the timezone. Delivery uses the existing Message Action journal, including uncertain-send recovery.

**Test with a message** uses saved settings and shows the decision trace without sending, assigning or writing tickets. A selected contact supplies its latest readable conversation/business context. Without a contact the trace is conditional; identity, ownership and deduplication cannot be verified. No AI inference is run in preview.

The API methods are `relay_core.automation.channel.read`, `save` and `dry_run(channel, text, contact=None)`.

## Start a flow

A flow starts when the customer sends one of these:

| Trigger | Match |
|---|---|
| Slash command, such as `/help` | The first word of the message |
| Keywords, one per line | The whole message, without case and extra spaces |
| Template button payload | The payload of a template button reply |

`exit`, `/exit`, `cancel`, `/cancel` or `/stop` closes an open flow. **STOP remains a consent opt-out**, even during an active flow: the opt-out hook updates consent and admission returns without a flow-exit response. Configured opt-in/out keywords always take precedence. A waiting flow owns subsequent replies, including text that would otherwise trigger another flow. A flow left unanswered for 7 days stops waiting.

## Steps

| Step | What it does |
|---|---|
| Ask a question | Sends a question and waits. Answer types: text (shortest and longest length), number, email, date, one choice, several choices, any message (text, media, location or contact). A wrong answer gets the step's own message, or the reason and the question again |
| Send a message | Sends text. `{{answer}}` inserts an answer and `{{result.field}}` inserts a field of a business action result |
| Branch on an answer | Compares an answer or a result field (is, is not, contains, more, less, has a value) and goes to one of two steps |
| Run AI skill | Hands this message to a selected, compatible Relay AI Skill through the existing AI runner. Waits for completion, delivery or approval; then continues or ends. A search announcement requiring customer confirmation ends the flow so the next reply can confirm it |
| Assign | Assigns the conversation to a team and/or user through Relay Conversation Assignment; assignment alone does not take human ownership |
| Run a business action (Advanced) | Calls an action that an app registers in the `relay_flow_actions` hook, with JSON arguments. `{"var": "name"}` passes an answer. The result can be saved under a name |
| Wait (Advanced) | Continues after 1 second to 24 hours |
| Raise a ticket, Save a topic | Updates the admission ticket’s subject/brief, or saves a conversation topic |
| Hand over to a person | Sends its Message, holds the admission ticket for staff and stops the flow |
| End the flow | Sends an optional final message |

Each step goes to the following step, or to the step named in **Then go to**. A loop is allowed only when it stops at a question. **Repeat limit** stops a step after a number of visits (default 20). Single choices use up to 3 WhatsApp reply buttons or a list of up to 10 options when the Hub advertises `messages.interactive` in its capability operations. The installed Hub does not currently advertise that operation. Otherwise choices use numbered text; the customer can reply with a number, label or stable value. Long labels, optional choices and multiple-choice questions also use numbered text. Delivery format is pinned per prompt visit so retries cannot change its idempotency payload.

## Versions

**Save draft** validates and keeps the steps. **Publish** freezes them as a Relay Flow Version. A run keeps the version it started on; publishing a later version does not cancel it. Disabling the flow still stops active runs. The editor compares channel, execution user, business type and trigger settings as well as nodes when showing unpublished changes. Trigger routing remains on the saved flow record; execution settings and nodes use the published version. **Enable** needs a published version and registered business actions.

Publication validates channel compatibility: template-button triggers require WhatsApp, Email content questions must accept text, selected AI skills must match the channel/business type, and action registrations may restrict `channels` (WhatsApp, Telegram, Email).

## Business actions

An app adds actions in `hooks.py`:

```python
relay_flow_actions = {
    "support.create_ticket": {
        "label": "Create ticket",
        "method": "my_app.support.create_ticket",
        "replay_safe": True,
        "parameters": {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]},
    }
}
```

The method gets `action_input`, `idempotency_key`, `relay_contact`, `business_doctype`, `business_name` and `flow_run` as keyword arguments. It must give the same result for the same `idempotency_key` and must not commit. It runs as the flow's run-as user.

## How a step runs

1. The inbound drain admits the incoming message and writes one Relay Flow Event.
2. One background job processes the event. It finds the open run of the chat through the (conversation_key, status) index and runs at most 5 steps.
3. When the job ends, it queues the next pending event of the same chat. There is no polling.

Measured with 1,000 open runs on a laptop, without the Hub send: start step p50 90 ms (p95 138 ms), reply step p50 137 ms (p95 172 ms), open run lookup 0.6 ms. Run `tests/perf_flow_site.py` on a test site to measure again.

## Import WhatsApp Core flows

```bash
bench --site <site> relay-import-whatsapp-flows --source-db <whatsapp core db> \
  --source-site-label operations --execution-user <manager user> --dry-run
```

The command copies each flow and all its versions, sets the published version and keeps the flow disabled. A second run adds only missing versions and never changes an imported flow. It lists business actions that are not registered yet; register them, review the steps and then enable the flow. `--channel` and `--business-doctype` are needed when the site has more than one WhatsApp channel or contact type.

## Old links

When WhatsApp Core is switched off or removed, `/whatsapp` and `/whatsapp_core` redirect to `/relay`. `#/flows/<flow>` opens the imported flow and `#/inbox/<conversation>` opens the imported chat.
