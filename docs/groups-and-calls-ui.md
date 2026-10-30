# Groups and Calls workspace

Open the installed `/relay` workspace. Groups and Calls are direct sidebar
entries; no separate Core login is introduced.

## Groups

Choose WhatsApp or Telegram in the channel tabs.

WhatsApp exposes the existing Hub-backed group list, creation, details,
invitations, member removal, paged join-request review and text sending. Creation
supports description and joining approval mode. More group actions exposes JPEG
photo upload, invite creation, queued pin/unpin by message ID, and deletion after
typing the group ID. The account must have Meta group capability. The group composer supports text, image/video/audio/document uploads up to the Relay file limit (10 MB),
media URLs/IDs, captions, filenames, quoted-message IDs and approved templates
with parameter fields. Sends use the durable queue and preserve failed drafts.
Account-wide group operations are manager-only; assigned agents use the
permission-scoped inbox for verified group conversations.

Telegram lists verified group endpoints for the current site's configured
account, in pages of 30. Private chats and unverified endpoints are excluded.
Contact labels require access to the linked business record. Managers can:

- Read bounded group history and send text or a quoted reply to its original topic.
- Change title and description.
- Read administrators/member count, look up a member, approve/reject a join request,
  and ban/unban a selected member.
- Create, edit or revoke an invite link, with optional join approval.
- Create, rename, close and reopen forum topics.

The Bot API does not provide arbitrary enumeration of every chat member or every
forum topic. This UI offers supported administrator lookup, member-ID lookup and
a paged directory of observed topic names, with topic-ID fallback for unseen
topics. Authenticated forum events and successful Relay topic actions update the
directory; closed/hidden states are retained and deleted topics are excluded.
A newly created topic is selected automatically. Group setup
still requires an incoming group to be linked and verified in Core.

History filters by Contact, Relay Channel and group endpoint together. Two groups
under the same Contact cannot be mixed by this view. It loads 40 messages at a time
and retains at most 120 while paging older history. Group history refresh is manual.

## Calls

The Calls entry currently uses WhatsApp voice calling, per the initial channel
scope. It exposes recipient selection, permission request/check, start, incoming
answer/decline, end, and the existing browser recording controls. The business
record picker queries configured DocTypes with Frappe permissions and returns at
most 30 records. It then lists the record's Contacts.

Switching workspaces preserves the mounted call state. Durable call attempts and
exact webhook correlation prevent duplicate starts after a lost acknowledgement.
After reload, known calls can be recovered for termination; this does not restore
a lost browser audio session. Managers can resolve unconfirmed attempts using
recorded verification evidence, without sending another provider request.
Recordings can be archived as private server files with conversation permissions;
live audio/recording interoperability remains unverified.

Telegram bots cannot use the user-only
[`phone.requestCall`](https://core.telegram.org/method/phone.requestCall) API.
There is no Telegram-call or Google Meet adapter in this release.

## Validation — 23 September 2026

- Core unit contracts: 65 passed; 2 optional live-Hub tests skipped.
- Frontend data tests: 16 passed; installed frontend production build passed.
- Real Frappe/PostgreSQL group scenarios: 22 passed, including separate groups and
  topics, verified bindings, authorization, cursor paging and group-history isolation.
- Browser fixture: Telegram messaging, topic create/close, invite creation,
  administrator/member count, join approval, WhatsApp group settings, call
  permission/connect/navigation/terminate and widths 320/390/768/1440 passed.
- Actual installed review: new sidebar entries load without JavaScript errors;
  unconfigured Telegram and disabled WhatsApp calls are shown honestly.

The browser fixture intercepts provider operations and stubs microphone/WebRTC;
backend group scenarios use loopback transports. These results do not prove live
provider calls, audio quality, recording capture or provider eligibility.
