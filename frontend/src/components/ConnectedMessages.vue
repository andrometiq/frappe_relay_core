<script setup>
import { useLoadMore } from '../composables/useLoadMore'
import { defineAsyncComponent, inject, provide, computed, ref, watch, onBeforeUnmount, onMounted } from "vue";
import { Avatar, Button, Dropdown, ErrorMessage, FeatherIcon } from "@relay/ui";
import { recordTitle } from '../services/recordTitle';
import { linkedTitle } from '../services/linkedTitle';
import { phoneCaption } from '../services/phoneNumber';
import WorkspaceState from "./WorkspaceState.vue";
import InboxDirectory from "./messages/InboxDirectory.vue";
import ConversationTools from "./messages/ConversationTools.vue";
import ContactDetails from "./ContactDetails.vue";
import ChatPanel from "./messages/ChatPanel.vue";
import { channelOffText, plainChatError } from "../services/chatErrors";
import { objectValue } from './messageContent';
import MessageThread from "./messages/MessageThread.vue";
import SendChannel from "./messages/SendChannel.vue";
import MessageComposer from "./messages/MessageComposer.vue";
import { useMessages } from "../composables/useMessages";
import { useThreadNotes } from "../composables/useThreadNotes";
import { sendNumbersKey, useSendNumbers } from "../composables/useSendNumbers";
import { useConversationPresence } from "../composables/useConversationPresence";
import { useRealtimeRefresh } from "../composables/useRealtimeRefresh";
import { coreApi } from "../services/coreApi";
import { messagesKey } from "../composables/messagesContext";
import { useEnabledChannels } from "../composables/useEnabledChannels";
import { channelCan } from "../services/enabledChannels";
import { closeRoute, openRoute } from "../useViewRoute";
import { useMobileLayout } from "../composables/useMobileLayout";
import { contactInfoRoute, isContactInfoRoute } from "../services/mobileNav";
import { linkedLabel, recordIcon } from "../services/contactLinks";

// Panels and dialogs that open on demand load in their own chunks, so the inbox paints sooner.
const StartConversation = defineAsyncComponent(() => import('./messages/StartConversation.vue'))
const ConversationCases = defineAsyncComponent(() => import('./messages/ConversationCases.vue'))
const ConversationTopics = defineAsyncComponent(() => import('./messages/ConversationTopics.vue'))
const ConversationDeliveries = defineAsyncComponent(() => import('./messages/ConversationDeliveries.vue'))
const CreateTicketDialog = defineAsyncComponent(() => import('./messages/CreateTicketDialog.vue'))
const InternalNotes = defineAsyncComponent(() => import('./messages/InternalNotes.vue'))
const MessageSearch = defineAsyncComponent(() => import('./messages/MessageSearch.vue'))
const BusinessMessageSearch = defineAsyncComponent(() => import('./messages/BusinessMessageSearch.vue'))
const ConversationSummary = defineAsyncComponent(() => import('./messages/ConversationSummary.vue'))
const ContactInfoPage = defineAsyncComponent(() => import('./messages/ContactInfoPage.vue'))
const EmailComposer = defineAsyncComponent(() => import('./messages/EmailComposer.vue'))
const NoteComposer = defineAsyncComponent(() => import('./messages/NoteComposer.vue'))

const state = useMessages();
const channelEnabled = useEnabledChannels();
const capabilities = inject("relayCapabilities", ref({}));
const deliveriesOpen = ref(false), contactRecord = ref(null);
const casesOpen = ref(false), topicsOpen = ref(false);
const activeBusiness = computed(() => ({
  businessDoctype: businessType.value || source.value?.business_doctype || "",
  businessName: businessName.value || source.value?.business_name || "",
}));
// The composer is in "reply" or "note" mode; a note can link one message or answer another note.
const composeMode = ref('reply'), noteMessages = ref([]), noteReply = ref(null);
const noteContact = computed(() => noteMessages.value[0]?.relay_contact || conversationContact.value);
const ticketOpen = ref(false), ticketMessage = ref(null), ticketQuoted = ref(false);
// One side panel at a time: "notes", "search" or "contact".
const panel = ref('');
const notesOpen = computed(() => panel.value === 'notes' && !!conversationContact.value);
const searchOpen = computed(() => panel.value === 'search');
const noteBusiness = computed(() => noteMessages.value[0]?.business_name
  ? { businessDoctype: noteMessages.value[0].business_doctype, businessName: noteMessages.value[0].business_name }
  : activeBusiness.value);
const frappeContact = computed(() => activeBusinessContact.value || source.value?.frappe_contact || contactRecord.value?.contact || '');

provide(messagesKey, state);
const numbers = useSendNumbers(state, capabilities);
provide(sendNumbersKey, numbers);
// On a site with several WhatsApp numbers the header names the number the customer wrote to.
const wroteTo = computed(() => numbers.active.value ? numbers.wroteTo.value : null);
const {
  businessType, businessName, businessContext, openBusiness,
  newer, restored, loadNewer, loadOlder, paging, pagingError, selected, rows, more, source, emoji,
  busy, error, connectionError, notice, channel, history, reply,
  focusMessage, openQuote, send, run,
} = state;
const conversationContact = computed(() => source.value?.relay_contact || selected.value || '');
const threadNotes = useThreadNotes(conversationContact), replyClosed = ref(false);

const startOpen = ref(false), startTemplate = ref(false), startBusiness = ref(false), startContact = ref(""), startChannel = ref(""), startContactLabel = ref(""), summaryOpen = ref(false);
const linkedContacts = ref([]), contactsBusy = ref(false), contactsError = ref("");
const activeBusinessContact = ref("");
let contactRequest = 0, pickSingleContact = false;

const active = computed(() => selected.value || businessName.value);
// A contact without a name is shown by its phone number.
function contactTitle(record) {
  const name = recordTitle(record?.primary || record, '');
  return phoneCaption(name) || name || phoneCaption(record?.display_name) || phoneCaption(record?.contact) || 'Conversation';
}
const title = computed(() => (businessContext.value?.title ? recordTitle(businessContext.value) : '') || (businessName.value ? linkedTitle(businessType.value, businessName.value) : contactTitle(contactRecord.value)));
const groupLabel = computed(() => businessContext.value?.grouping_value || "");
const contactCount = computed(() => {
  const count = businessContext.value?.contact_count;
  if (!Number.isFinite(count)) return "";
  return businessContext.value?.contact_count_limited ? "100+ contacts" : `${count} ${count === 1 ? "contact" : "contacts"}`;
});
const activeContact = computed(() => linkedContacts.value.find(item => item.value === activeBusinessContact.value) || null);
const messagesByContact = computed(() => {
  const result = new Map();
  for (const row of rows.value) if (row.frappe_contact) result.set(row.frappe_contact, row);
  return result;
});
const visibleRows = computed(() => {
  const all = state.displayRows.value;
  if (!activeBusinessContact.value) return all;
  const target = messagesByContact.value.get(activeBusinessContact.value);
  if (!target) return [];
  return all.filter(row => row.frappe_contact === activeBusinessContact.value ||
    (row.channel === target.channel && row.sender_endpoint === target.sender_endpoint));
});
const isMobile = useMobileLayout(), infoOpen = ref(false), linking = ref(false);
const primary = computed(() => businessName.value ? null : contactRecord.value?.primary);
const otherLinks = computed(() => businessName.value ? '' : linkedLabel(contactRecord.value));
const menuActions = computed(() => [
  ...(conversationContact.value ? [{label:'Internal notes',icon:'message-square',onClick:openNotes}, {label:'Topics',icon:'list',onClick:() => topicsOpen.value = true}] : []),
  {label:'Search conversation',icon:'search',onClick:() => togglePanel('search')},
  ...(isMobile.value && contactRows.value.length ? [{label:'Create ticket from this chat',icon:'ticket',onClick:() => openTicket()}] : []),
]);
function togglePanel(name) { panel.value = panel.value === name ? '' : name; }
const provider = computed(() => objectValue(source.value?.provider_context).provider || "");
const channelLine = computed(() => {
  if (!source.value) return "";
  const label = linkedTitle("Relay Channel", source.value.channel, "");
  return [provider.value, label].filter((value, index, list) => value && list.indexOf(value) === index).join(" · ");
});
// Line two of the header names the person: name, phone and email, each once.
const personName = computed(() => { const name = recordTitle(contactRecord.value, ''); return phoneCaption(name) ? '' : name; });
const phone = computed(() => provider.value === 'Email' ? '' : phoneCaption(source.value?.sender_endpoint) || phoneCaption(contactRecord.value?.display_name));
const email = computed(() => provider.value === 'Email' ? source.value?.sender_endpoint || '' : '');
const who = computed(() => [personName.value, phone.value, email.value].filter(value => value && value !== title.value));
const channelCaption = computed(() => wroteTo.value ? `Wrote to ${wroteTo.value.label}` : channelLine.value);
const whoLine = computed(() => [...who.value, channelCaption.value].filter(Boolean).join(' · '));
function readInfoRoute() { infoOpen.value = location.hash.split("?")[0] === "#/messages" && isContactInfoRoute(location.hash); }
function openInfo(link = false) { linking.value = link; openRoute(contactInfoRoute(location.hash)); infoOpen.value = true; }
const contextShown = computed(() => panel.value === 'contact');
function toggleContext() { linking.value = false; togglePanel('contact'); }
// "Link record" opens the link form itself, not the full contact details.
function openLinking() {
  if (isMobile.value) { openInfo(true); return; }
  const shown = contextShown.value && linking.value;
  linking.value = !shown; panel.value = shown ? '' : 'contact';
}
// Phones open the contact info page; wide screens open contact details under the heading.
function toggleInfo() { if (!isMobile.value) toggleContext(); else if (infoOpen.value) closeInfo(); else openInfo(); }
const unlinked = computed(() => !businessName.value && contactRecord.value && !Number(contactRecord.value.link_count));
function closeInfo() {
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  params.delete("info");
  closeRoute("#/messages?" + params);
  infoOpen.value = false;
}
function infoAction(open) { closeInfo(); open(); }
// After a link from "Link record" the header shows the record, so the form closes.
function linked() {
  loadProfile(selected.value);
  if (linking.value) { panel.value = ''; linking.value = false; }
}
const chooseRecipient = computed(() => !!businessName.value && linkedContacts.value.length > 1);
function replyTo(message) {
  reply(message);
  const bubble = document.querySelector(`[data-message="${CSS.escape(message.name)}"]`);
  bubble?.classList.add('reply-flash');
  setTimeout(() => bubble?.classList.remove('reply-flash'), 1400);
}
const recipientLabel = computed(() => {
  if (!source.value) return "";
  const linked = linkedContacts.value.find(item => item.value === source.value.frappe_contact);
  return recordTitle(linked?.label || source.value.contact_label || contactRecord.value?.display_name, "") || phone.value || "Contact";
});

async function loadBusinessContacts() {
  const request = ++contactRequest;
  linkedContacts.value = [];
  contactsError.value = "";
  if (!businessType.value || !businessName.value) { contactsBusy.value = false; return; }
  contactsBusy.value = true;
  try {
    const result = await coreApi("business_inbox.contacts", { doctype: businessType.value, name: businessName.value });
    if (request !== contactRequest) return;
    linkedContacts.value = result.items || [];
    const routed = new URLSearchParams(location.hash.split("?")[1] || "").get("contact") || "";
    if (routed && linkedContacts.value.some(item => item.value === routed)) chooseContact(routed, false);
  } catch (e) {
    if (request === contactRequest) contactsError.value = e.message;
  } finally {
    if (request === contactRequest) contactsBusy.value = false;
  }
}

function contactRoute(contact) {
  const params = new URLSearchParams({ business_doctype: businessType.value, business_name: businessName.value });
  if (contact) params.set("contact", contact);
  openRoute("#/messages?" + params.toString(), true);
}
function chooseContact(contact, updateRoute = true) {
  if (busy.value) return;
  state.clearRecipient();
  closeNotes();
  activeBusinessContact.value = contact;
  const message = messagesByContact.value.get(contact);
  if (message) state.selectRecipient(message);
  if (updateRoute) contactRoute(contact);
}
function showAllContacts() {
  if (busy.value) return;
  pickSingleContact = false;
  state.clearRecipient();
  closeNotes();
  activeBusinessContact.value = "";
  contactRoute("");
}
// The inbox "+" starts empty; chat buttons start with the chat's contact and, in a business chat, its record.
function openStart({ contact = "", template = false, business = false } = {}) {
  startTemplate.value = template;
  startBusiness.value = business;
  startContact.value = contact;
  startChannel.value = numbers.active.value && contact && contact === numbers.contact.value ? numbers.current.value : "";
  startContactLabel.value = business ? linkedContacts.value.find(item => item.value === contact)?.label || ""
    : contact ? recordTitle(contactRecord.value, "") || title.value : "";
  startOpen.value = true;
}
function startInChat(template = false) {
  if (!businessName.value) return openStart({ contact: selected.value, template });
  openStart({ contact: (template ? source.value?.frappe_contact : activeBusinessContact.value) || "", template, business: true });
}
async function started(result) {
  startOpen.value = false;
  if (!startBusiness.value && result?.contact && result.contact !== selected.value) {
    await openContact(result.contact);
  } else {
    await run(() => history());
    if (businessName.value && result?.contact) chooseContact(result.contact);
  }
}
function openContact(contact) {
  if (busy.value) return;
  openRoute('#/messages?contact=' + encodeURIComponent(contact), !!active.value);
  return state.open(contact);
}
function openTicket(message) {
  ticketQuoted.value = !!message;
  ticketMessage.value = message || contactRows.value.at(-1) || null;
  ticketOpen.value = !!ticketMessage.value;
}
function closeTicket() { ticketOpen.value = false; ticketMessage.value = null; ticketQuoted.value = false; }
function closeNotes() { casesOpen.value = false; topicsOpen.value = false; if (panel.value === 'notes') panel.value = ''; setComposeMode('reply'); }
function openNotes() { if (conversationContact.value) panel.value = 'notes'; }
function setComposeMode(mode) {
  composeMode.value = mode;
  if (mode === 'reply') { noteMessages.value = []; noteReply.value = null; }
}
function startNote(message = null, reply = null) {
  setComposeMode('note');
  noteMessages.value = message ? [message] : [];
  noteReply.value = reply;
  // The phone notes panel covers the chat, so it closes to show the note composer.
  if (isMobile.value && panel.value === 'notes') panel.value = '';
}
const toast = ref(null);
let toastTimer;
function showToast(text, href = '') {
  clearTimeout(toastTimer);
  toast.value = { text, href };
  toastTimer = setTimeout(() => { toast.value = null; }, href ? 5000 : 2500);
}
onBeforeUnmount(() => clearTimeout(toastTimer));
// A switched-off channel cannot send, so the composer shows a banner in place of replies; notes still work.
const channels = ref(null);
coreApi('api.channel_options').then(result => { channels.value = result.items; }, () => {});
const channelOff = computed(() => !!source.value && !!channels.value && !channels.value.some(row => row.name === source.value.channel && row.enabled));
const replyOff = computed(() => channelOff.value && !numbers.active.value ? channelOffText(provider.value) : '');
watch(source, value => {
  if (businessName.value && value?.frappe_contact && activeBusinessContact.value && activeBusinessContact.value !== value.frappe_contact) activeBusinessContact.value = value.frappe_contact;
});
function clearRecipient() {
  activeBusinessContact.value = "";
  state.clearRecipient();
}

const lastVisible = ref(""), visibleMessages = ref([]);
const contactRows = computed(() => visibleRows.value.filter(row => row.relay_contact === conversationContact.value && !row._pending));
const { people } = useConversationPresence({
  get contact() { return selected.value; },
  get businessDoctype() { return businessType.value; },
  get businessName() { return businessName.value; },
  get lastVisible() { return lastVisible.value; },
  get visibleMessages() { return visibleMessages.value; },
}, () => {});

// The chat title and record bar show the primary record, so a link change in contact details reloads the profile.
async function loadProfile(contact) {
  try { const record = await coreApi('api.contact_profile', { contact }); if (selected.value === contact) contactRecord.value = record; }
  catch (e) { if (selected.value === contact) contactsError.value = e.message; }
}
watch(selected, contact => {
  contactRecord.value = null; closeNotes(); closeTicket(); deliveriesOpen.value = false; panel.value = ''; linking.value = false;
  lastVisible.value = ''; visibleMessages.value = [];
  if (contact) loadProfile(contact);
}, { immediate: true });
watch([businessType, businessName], () => {
  closeNotes(); closeTicket(); panel.value = ''; linking.value = false;
  summaryOpen.value = false;
  activeBusinessContact.value = "";
  pickSingleContact = true;
  lastVisible.value = "";
  visibleMessages.value = [];
  loadBusinessContacts();
}, { immediate: true });
// A record with one contact opens on that contact's chat, so the composer shows without a click.
watch([linkedContacts, messagesByContact, busy], () => {
  const only = linkedContacts.value.length === 1 ? linkedContacts.value[0].value : "";
  if (!pickSingleContact || busy.value || !businessName.value || !messagesByContact.value.has(only)) return;
  pickSingleContact = false;
  if (!source.value && [only, ""].includes(activeBusinessContact.value)) chooseContact(only);
}, { flush: 'post' });
function readContactRoute() {
  if (location.hash.split('?')[0] !== '#/messages' || busy.value) return;
  const params = new URLSearchParams(location.hash.split('?')[1] || '');
  if (!businessName.value) {
    if (params.get('contact') === selected.value && params.get('notes') === '1' && !error.value) {
      openNotes();
      params.delete('notes');
      window.history.replaceState(null, '', '#/messages?' + params.toString());
    }
    return;
  }
  if (params.get('business_name') !== businessName.value || params.get('business_doctype') !== businessType.value) return;
  const contact = params.get('contact') || '';
  if (contact !== activeBusinessContact.value) chooseContact(contact, false);
}
watch([busy, selected], readContactRoute, { flush: 'post' });
onMounted(() => { readContactRoute(); readInfoRoute(); window.addEventListener('hashchange', readContactRoute); window.addEventListener('popstate', readContactRoute); window.addEventListener('hashchange', readInfoRoute); window.addEventListener('popstate', readInfoRoute); });
onBeforeUnmount(() => { ++contactRequest; window.removeEventListener('hashchange', readContactRoute); window.removeEventListener('popstate', readContactRoute); window.removeEventListener('hashchange', readInfoRoute); window.removeEventListener('popstate', readInfoRoute); });
// A chat that failed to open tries again when the connection or the tab comes back.
const loadFailed = state.loadFailed;
const loadFailedReason = computed(() => loadFailed.value?.status >= 500 ? "The server could not load this chat. Try again." : loadFailed.value?.message);
function retryChat() {
  contactsError.value = "";
  if (selected.value && !contactRecord.value) loadProfile(selected.value);
  return state.retryOpen();
}
useRealtimeRefresh([], [], ({ kinds }) => {
  if (loadFailed.value && !busy.value && (kinds.has('reconnect') || kinds.has('visible'))) return retryChat();
});
const moreSentinel = useLoadMore({ loading: busy, hasMore: () => state.pendingCursor.value, error: () => state.error.value, load: () => state.loadPending() })
</script>

<template>
  <section class="connected-inbox" :class="{ 'has-conversation': active }" aria-label="Business inbox">
    <StartConversation v-if="startOpen" :key="businessName + ':' + startContact + startTemplate + startBusiness" :template="startTemplate" :contact="startContact" :contact-label="startContactLabel" :channel="startChannel"
      :contacts="startBusiness ? linkedContacts : []"
      :business-doctype="startBusiness ? businessType : ''" :business-name="startBusiness ? businessName : ''" @close="startOpen = false" @sent="started" />

    <aside class="contact-directory">
      <InboxDirectory :selected="selected" :business-name="businessName" :business-type="businessType" :busy="busy"
        @business="openBusiness" @select="openContact" @start="openStart()" />
    </aside>

    <Teleport v-if="isMobile && !active" to="#relay-header-actions" defer>
      <Button variant="solid" icon="plus" class="relay-header-new" aria-label="New conversation" title="New conversation" @click="openStart()" />
    </Teleport>

    <Transition name="relay-page" :css="isMobile">
    <div v-if="active" class="connected-thread">
      <header class="conversation-heading">
        <Button class="mobile-only conversation-back" icon="chevron-left" aria-label="Back to conversations" title="Back to conversations" @click="state.clearSelection()" />
        <Avatar :label="title" aria-hidden="true" />
        <div class="conversation-title">
          <h2><button v-if="frappeContact || conversationContact" type="button" class="conversation-title-button" aria-label="Open contact info" @click="toggleInfo">{{ title }}</button><template v-else>{{ title }}</template></h2>
          <p v-if="isMobile && whoLine" class="conversation-channel-line" :title="whoLine">{{ whoLine }}</p>
          <div class="conversation-meta">
            <span v-if="!isMobile && whoLine" class="conversation-channel conversation-who" :title="whoLine">{{ whoLine }}</span>
            <span v-if="businessContext?.doctype_label || businessType"><FeatherIcon name="file-text" :size="13" />{{ businessContext?.doctype_label || businessType }}</span>
            <span v-if="groupLabel">{{ groupLabel }}</span>
            <span v-if="contactCount">{{ contactCount }}</span>
            <template v-if="!isMobile">
              <span v-if="primary" class="conversation-record"><FeatherIcon :name="recordIcon(primary.doctype).icon" :size="13" />{{ primary.title }}<small>· {{ primary.doctype }}</small></span>
              <button v-if="otherLinks" type="button" class="conversation-linked" :aria-expanded="contextShown" @click="toggleContext">{{ otherLinks }}</button>
              <button v-if="unlinked && capabilities.manage" type="button" class="conversation-linked" :aria-expanded="contextShown && linking" @click="openLinking">Not linked · Link</button>
            </template>
          </div>
        </div>
        <div class="conversation-heading-actions">
          <span v-if="people.length" class="conversation-viewers" role="group" aria-label="Also viewing this chat"><Avatar v-for="person in people.slice(0, 3)" :key="person.name" class="viewer-avatar" size="sm" :label="person.full_name || person.name" :title="'Also viewing: ' + (person.full_name || person.name) + (person.typing ? ' (typing)' : '')" /><span v-if="people.length > 3" class="viewer-more" :title="'Also viewing: ' + people.slice(3).map(person => person.full_name || person.name).join(', ')">+{{ people.length - 3 }}</span></span>
          <ConversationTools v-if="conversationContact" :key="conversationContact" :actions="menuActions" :menu-icon="isMobile ? 'more-vertical' : 'more-horizontal'">
            <Button class="conversation-ticket" icon="ticket" label="Create ticket from this chat" :title="contactRows.length ? 'Create a ticket linked to the last message' : 'No messages in this chat yet'" :disabled="busy || !contactRows.length" @click="openTicket()" />
            <Button icon="info" aria-label="Contact info" title="Contact info" :aria-pressed="isMobile ? infoOpen : contextShown" @click="toggleInfo" />
          </ConversationTools>
          <Dropdown v-else :options="menuActions"><Button :icon="isMobile ? 'more-vertical' : 'more-horizontal'" aria-label="Conversation actions" title="Conversation actions" /></Dropdown>
        </div>
      </header>

      <div v-if="isMobile && (primary || otherLinks || unlinked)" class="mobile-record-bar">
        <span v-if="primary" class="mobile-record-chip"><FeatherIcon :name="recordIcon(primary.doctype).icon" :size="14" />{{ primary.title }}<small>· {{ primary.doctype }}</small></span>
        <button v-if="otherLinks" type="button" class="mobile-linked-chip" @click="openInfo()">{{ otherLinks }}</button>
        <button v-if="unlinked && capabilities.manage" type="button" class="mobile-linked-chip" @click="openLinking">Not linked · Link</button>
      </div>

      <nav v-if="businessName" class="business-contact-strip" aria-label="Business contacts">
        <button type="button" :aria-pressed="!activeBusinessContact" :class="{ active: !activeBusinessContact }" :disabled="busy" @click="showAllContacts">
          <span>All</span><small>{{ linkedContacts.length }}</small>
        </button>
        <button v-for="contact in linkedContacts" :key="contact.value" type="button"
          :aria-pressed="activeBusinessContact === contact.value" :class="{ active: activeBusinessContact === contact.value }"
          :disabled="busy" @click="chooseContact(contact.value)">
          <span class="contact-chip-avatar">{{ contact.label.slice(0, 1).toUpperCase() }}</span>
          <span class="contact-chip-copy"><strong>{{ recordTitle(contact, 'Contact') }}</strong><small>{{ contact.description || "Review channel identities" }}</small></span>
        </button>
        <span v-if="contactsBusy" class="contact-strip-loading" role="status">Loading contacts</span>
      </nav>

      <ConversationCases v-if="casesOpen && conversationContact" :key="conversationContact" :contact="conversationContact" v-bind="activeBusiness" @close="casesOpen = false" />
      <ConversationTopics v-if="topicsOpen && conversationContact" :key="conversationContact" :contact="conversationContact" v-bind="activeBusiness" :messages="contactRows" @close="topicsOpen = false" @open="focusMessage" />
      <ConversationDeliveries v-if="deliveriesOpen && conversationContact" :key="conversationContact" :contact="conversationContact" @close="deliveriesOpen = false" @open="focusMessage" />
      <ErrorMessage class="px-4" :message="plainChatError(loadFailed ? '' : error) || contactsError" />
      <p v-if="connectionError" role="status" class="relay-connection-state">{{ connectionError }}</p>
      <p v-if="notice" role="status" class="feedback-panel">{{ notice }}</p>
      <CreateTicketDialog v-if="ticketMessage" :key="ticketMessage.name" v-model="ticketOpen" :contact="ticketMessage.relay_contact || conversationContact" :message="ticketMessage" :quoted="ticketQuoted" :contact-name="title" @created="showToast('Ticket created', $event.href)" />

      <div class="conversation-body">
      <WorkspaceState v-if="loadFailed && !visibleRows.length" class="conversation-load-failed" title="Could not load messages" :description="loadFailedReason" icon="alert-circle">
        <Button label="Retry" variant="solid" icon-left="refresh-cw" :loading="busy" @click="retryChat" />
      </WorkspaceState>
      <MessageThread v-else :key="active + ':' + channel + ':' + activeBusinessContact" :position="state.viewPosition.value"
        :newer="newer" :anchor="restored" :unread="state.firstUnread.value" :rows="visibleRows" :more="more" :busy="busy" :paging="paging" :paging-error="pagingError" :error="state.error.value" :emoji="emoji"
        :selected="active" :contact-name="activeContact?.label || title" :can-comment="true" :notes="threadNotes.items.value" :reply-closed="replyClosed" @note="startNote" @ticket="openTicket"
        @position="state.rememberPosition" @newer="loadNewer" @visible="lastVisible = $event"
        @visible-messages="visibleMessages = $event" @older="loadOlder" @retry-page="pagingError = ''" @reply="replyTo"
        @quote="openQuote" @reconcile="state.checkPending" @retry="state.retryPending" @discard="state.deletePending" @send="send" @toast="showToast" />
      <InternalNotes v-if="notesOpen" :key="conversationContact" :contact="conversationContact" @close="panel = ''" @open="focusMessage" @reply="startNote(null, $event)" @add="startNote()" />
      <MessageSearch v-if="searchOpen && selected && !businessName" :contact="selected" @close="panel = ''" @open="panel = ''; focusMessage($event)" />
      <BusinessMessageSearch v-if="searchOpen && businessName" :business-doctype="businessType" :business-name="businessName"
        @close="panel = ''" @open="panel = ''; focusMessage($event)" />
      <ChatPanel v-if="contextShown && !isMobile" :title="linking ? 'Link record' : 'Contact info'" @close="panel = ''">
        <div v-if="!linking" class="contact-panel-summary">
          <Avatar :label="title" size="lg" aria-hidden="true" />
          <strong>{{ personName || title }}</strong>
          <span v-for="line in [phone, email, channelCaption].filter(Boolean)" :key="line">{{ line }}</span>
        </div>
        <ContactDetails v-if="frappeContact" :key="frappeContact + linking" compact :contact="frappeContact" :link="linking" @changed="linked" @close="panel = ''" />
        <p v-else class="contact-panel-empty">This chat has no linked Contact yet.</p>
      </ChatPanel>
      <p v-if="toast" class="chat-toast" role="status">{{ toast.text }}<template v-if="toast.href"> · <a :href="toast.href">Open</a></template></p>
      </div>

      <div v-if="state.pendingCursor.value" ref="moreSentinel" class="h-px" aria-hidden="true" />
      <Button v-if="newer || state.newArrivals.value" class="jump-latest" icon-left="arrow-down"
        :label="state.newArrivals.value ? `${state.newArrivals.value} new messages` : 'Go to latest'"
        :disabled="busy" @click="state.latest" />

      <EmailComposer v-if="!replyOff && source && channelCan(capabilities, provider, 'email_threading')" :key="source.name" :mode="composeMode" @mode="setComposeMode">
        <template #channel><SendChannel /></template>
        <template #note><NoteComposer :key="noteContact" :contact="noteContact" v-bind="noteBusiness" :messages="noteMessages" :reply-to="noteReply"
          @added="showToast('Note added'); threadNotes.load()" @clear-messages="noteMessages = []" @clear-reply="noteReply = null" /></template>
        <template v-if="chooseRecipient" #recipient><div class="business-recipient-bar"><span>To</span><strong>{{ recipientLabel }}</strong><button type="button" :disabled="busy" @click="clearRecipient">Change</button></div></template>
      </EmailComposer>
      <MessageComposer v-else-if="source && (replyOff || channelEnabled(provider))" :key="source.channel + source.sender_endpoint" :off-text="replyOff" :recipient="chooseRecipient ? recipientLabel : ''" :contact-name="activeContact?.label || title" :mode="composeMode" @mode="setComposeMode" @template="startInChat(true)" @closed="replyClosed = $event">
        <template #channel><SendChannel /></template>
        <template #note><NoteComposer :key="noteContact" :contact="noteContact" v-bind="noteBusiness" :messages="noteMessages" :reply-to="noteReply"
          @added="showToast('Note added'); threadNotes.load()" @clear-messages="noteMessages = []" @clear-reply="noteReply = null" /></template>
        <template v-if="chooseRecipient" #recipient><div class="business-recipient-bar"><span>To</span><strong>{{ recipientLabel }}</strong><button type="button" :disabled="busy" @click="clearRecipient">Change</button></div></template>
      </MessageComposer>
      <div v-else-if="active && !loadFailed" class="business-compose-start">
        <Button variant="solid" icon-left="plus" :label="activeContact ? `Message ${activeContact.label}` : 'New message'"
          :disabled="busy || contactsBusy" @click="startInChat()" />
      </div>

      <ConversationSummary v-if="summaryOpen && businessName && capabilities.ai" :business-doctype="businessType" :business-name="businessName"
        @close="summaryOpen = false" @open="focusMessage" />
    </div>
    <div v-else class="connected-thread whatsapp-empty-pane" aria-label="No open conversation">
      <WorkspaceState title="Choose a conversation" description="Select a customer on the left to view messages and reply." icon="message-circle" />
    </div>
    </Transition>

    <Transition name="relay-page">
      <ContactInfoPage v-if="isMobile && infoOpen && active" :title="title" :contact="frappeContact" :primary="contactRecord?.primary" :channel="channelLine" :link="linking"
        :can-organize="!!conversationContact" @close="closeInfo" @cases="infoAction(() => casesOpen = true)" @notes="infoAction(openNotes)" @changed="loadProfile(selected)" />
    </Transition>
  </section>
</template>

<style scoped>
.conversation-body { position:relative; display:flex; flex:1; min-height:0; }
.conversation-body > :deep(.message-thread), .conversation-body > .conversation-load-failed { flex:1; min-width:0; }
.chat-toast { position:absolute; left:50%; bottom:16px; z-index:8; transform:translateX(-50%); padding:8px 14px; border-radius:999px; background:var(--ink-gray-9, #1f2328); color:var(--surface-white, #fff); font-size:13px; white-space:nowrap; box-shadow:0 4px 16px #0003; animation:relay-fade-up 160ms ease-out; }
.chat-toast a { color:inherit; font-weight:600; text-decoration:underline; }
.contact-panel-summary { display:flex; flex-direction:column; align-items:center; gap:2px; padding:16px; text-align:center; overflow-wrap:anywhere; }
.contact-panel-summary strong { margin-top:6px; font-size:15px; }
.contact-panel-summary span { color:var(--ink-gray-5); font-size:12px; }
.contact-panel-empty { padding:0 16px 16px; color:var(--ink-gray-5); font-size:13px; text-align:center; }
.contact-panel-summary + .contact-details { padding:0 16px 16px; }
.conversation-load-failed { flex:1; }
.conversation-compose-context { display:flex; align-items:center; gap:8px; padding:6px 16px; border-top:1px solid var(--outline-gray-2); }
.conversation-compose-context > :first-child { flex-shrink:0; }
.conversation-compose-context .business-recipient-bar { flex:1; flex-wrap:nowrap; min-width:0; padding:0; border:0; }
.business-recipient-bar strong { flex:1; }
.business-recipient-bar button { flex-shrink:0; min-height:36px; }
</style>
