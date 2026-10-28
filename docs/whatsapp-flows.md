# WhatsApp flows

A flow guides a customer through questions, answers and business actions in a private WhatsApp chat. Managers build flows in Relay under **Flows**. A System Manager turns the feature on in **Settings & Setup** with **Enable flows**. The switch is off by default. While it is off, the Flows page is hidden, the API refuses flow calls and no inbound message starts or continues a flow.

## Start a flow

A flow starts when the customer sends one of these:

| Trigger | Match |
|---|---|
| Slash command, such as `/help` | The first word of the message |
| Keywords, one per line | The whole message, without case and extra spaces |
| Template button payload | The payload of a template button reply |

`exit`, `cancel` or `stop` (with or without `/`) closes an open flow. A flow that waits more than 7 days for a reply stops waiting. A new trigger restarts the flow.

## Steps

| Step | What it does |
|---|---|
| Ask a question | Sends a question and waits. Answer types: text (shortest and longest length), number, email, date, one choice, several choices, any message (text, media, location or contact). A wrong answer gets the step's own message, or the reason and the question again |
| Send a message | Sends text. `{{answer}}` inserts an answer and `{{result.field}}` inserts a field of a business action result |
| Branch on an answer | Compares an answer or a result field (is, is not, contains, more, less, has a value) and goes to one of two steps |
| Run a business action | Calls an action that an app registers in the `relay_flow_actions` hook, with JSON arguments. `{"var": "name"}` passes an answer. The result can be saved under a name |
| Wait | Continues after 1 second to 24 hours |
| Raise a ticket, Save a topic | Creates a Relay ticket or a conversation topic |
| Hand over to a person | Stops the flow and gives the chat to staff |
| End the flow | Sends an optional final message |

Each step goes to the following step, or to the step named in **Then go to**. A loop is allowed only when it stops at a question. **Repeat limit** stops a step after a number of visits (default 20). Choices are sent as a numbered list; the customer replies with the number or the label.

## Versions

**Save draft** validates and keeps the steps. **Publish** freezes them as a Relay Flow Version. A run keeps the version it started on. **Enable** needs a published version and registered business actions.

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

1. The inbound drain claims the WhatsApp message and writes one Relay Flow Event.
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
