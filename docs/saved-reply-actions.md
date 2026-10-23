# Saved reply actions

System Managers configure these in **Desk → Relay Canned Reply**. Choose a
Telegram or WhatsApp reply, use **Choose business action**, enter its JSON
arguments, and save/publish. Actions cannot be enabled on AI replies. Selecting a
reply still only fills the composer; the separate labeled action button executes
it explicitly for that conversation.

The included `relay.add_internal_note` action takes:

```json
{"note":"Customer requested a follow-up."}
```

It creates an internal note linked to the source message. It does not send the
note to the customer. The operator must have access to that conversation and its
linked business record. Action configuration stays in Desk.

## Installed-app actions

Register a mapping in an installed app's `hooks.py`:

```python
relay_saved_reply_actions = {
    'my_app.follow_up': {
        'label': 'Schedule follow-up',
        'method': 'my_app.relay_actions.follow_up',
        'replay_safe': True,
        'parameters': {
            'type': 'object',
            'properties': {'note': {'type': 'string', 'maxLength': 4000}},
            'required': ['note'],
        },
    },
}
```

The handler receives keyword arguments `action_input`, `relay_contact`,
`source_message`, and `idempotency_key`. It runs as the authenticated operator,
not an administrator or configured automation user. It must enforce permissions
for its own business writes and reuse the supplied key for external operations.
Arbitrary browser arguments and handler paths are not accepted.

Use the same key to recover after a lost response. Core stores a service-owned
Relay Saved Reply Action receipt and rejects reuse with changed inputs. A handler
must also protect the gap between its side effect and receipt creation. The
included note handler uses the internal-comment journal for that protection.
Results must be JSON-compatible and at most 20,000 characters. No custom Python
code is accepted through Desk.

## Verification

The isolated database suite verifies actor context, configured inputs, replay,
cross-channel and unpublished-reply rejection, changed-input rejection, and a
crash after the built-in note committed but before the receipt was saved (one
note after retry). A browser fixture verifies explicit execution, a lost-response
retry with the same key, success state, and normal reply selection. The installed
`yrp.site` schema and action catalog are verified. No live business record was
changed for this acceptance; installed end-to-end action execution remains to be
accepted with an agreed test conversation.
