# Supplier ledger skill

The disabled **Supplier ledger** sample is installed once using its stable
`sample_key`, alongside the business-event samples. Installation never replaces
edited instructions or configuration. Set the supplier types in the instruction
text, choose a WhatsApp channel, AI Model, run-as user and handoff owner, then test
in Shadow mode before enabling Automatic replies. Disabled drafts may omit those
operational settings; activation validates them.

The single `supplier_ledger` tool reads GL Entry using `get_list`. Its Dynamic
Link scope fixes both `party` and `party_type` to the verified conversation's
supplier. Model filters can only narrow the scope. Reads are
restricted to non-cancelled GL entries (`is_cancelled = 0`) before pagination.
The exposed fields are posting_date, voucher_type, voucher_no, debit, credit and
remarks. Reads continue
to enforce query, document and field permissions under the conversation user.

The assistant is instructed to offer a date range and ask for confirmation
before reading. The sample instructions and provider still determine this
conversation behavior; it is not a general-purpose consent state machine.
Decimal totals for the returned rows are calculated in code. When a GL read
succeeds, Core renders the ledger reply itself rather than forwarding model
arithmetic. It fetches one extra row to detect truncation, excludes that row from
totals, and explains partial totals. These figures are never described as an
opening/closing balance. Long details are bounded to the message budget with an
explicit omission note. Delivery rechecks the scoped read fingerprint.

Tickets now show their creation age and use the shared heading, loading, badge,
avatar and empty-state components. Skills and event rules use cards with enabled
filters; event previews fetch the actual Hub template wording and substitute
labelled source-field placeholders as the mapping changes. Previews send nothing.

Validation preparation: Relay AI Skill was reloaded on yrp.site without migration,
and one disabled Shadow sample was installed (RELAY-AIS-0000000001).
Connected AI/event acceptance and site UI behavior remain pending the required
web/worker restart; no restart was performed by the agent. See Hub's
`docs/simulation-validation.md` for steps 13–14 and fixture boundaries.
