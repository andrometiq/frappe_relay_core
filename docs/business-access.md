# Business type access

Relay Contact Type is the common configuration for every channel. Its Users table
contains each assigned User once. Managers edit assignments in Settings > Business
types and users. Only System Managers can create types or change their configuration;
security, Single and child DocTypes cannot be registered.

- Relay Communication User: enabled business types where the user is listed.
- Relay Communication Manager: every enabled type, user assignments and bulk campaigns.
- System Manager: every enabled type, bulk campaigns and setup.
- Unlinked contacts and chats: shared by Relay users for triage. A contact linked
  to any business record is not unlinked, even when its type is disabled, unassigned
  or absent from Relay configuration.

The rule lives in `relay_core/business_access.py`. Lists, counts, business threads,
contacts, contact links, tickets, imports/exports and sends use this scope. A shared
contact does not grant access to messages, notes or topics filed under an unassigned
business type.
Relay reads safe public title and grouping fields server-side after authorization;
Customer/Contact read permissions are not required. Frappe Desk permissions and
existing write services are unchanged. Document actions, reports and AI tools
still enforce their own permissions for business operations beyond conversation access.

Teams, group claims and team filters are hidden. Existing team data, DocTypes and
endpoints remain for compatibility; they do not grant business access. The legacy
Relay Communication Team User role alone grants no business scope. Assign one of
the roles above instead.

Deployment: migrate the target site to install Relay Contact Type User and the
Relay Contact Type.users field, then assign users before they resume work. No
migration or site activation was run as part of this change. Unit tests use local
in-memory records and mocked external delivery; installed-site verification must
follow migration.
