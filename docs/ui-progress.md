# Core UI — workspace views

Added Dashboard, searchable/category-filtered Contacts, personal folders, Important and Unread filtering, campaign draft forms and canned replies to the existing Inbox, Teams and Flow editor. Selecting an unread conversation clears its local badge. Canned replies can be inserted into a matching-channel reply composer. Campaign drafts validate channel-compatible contacts. Saved drafts survive view changes.

All Core data here remains sample/in-memory and resets on reload. No server permissions, durable user read-state or AI summarization is claimed. Exact reader avatars, viewport resume, multi-business-link expansion, full visual flow authoring, templates, channel settings, full Frappe layouts and child tables remain future work.

The initial `DocumentForm` contract handles Data, Select, Check, Link, MultiSelect and Small Text. Link choices are local options, not a server permission-filtered search. It currently matches the Hub copy; a shared package will follow when the contract stabilizes.

Browser checks: folder creation/membership, Important, dashboard counts, unread clearing, supplier filtering, canned reply required-field validation and retention across views, desktop and 390px layout. Screenshot data is synthetic.
