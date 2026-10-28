<script setup>
import { useLoadMore } from '../composables/useLoadMore'
import { inject, provide, computed, ref, watch, onBeforeUnmount, onMounted } from "vue";
import { Avatar, avatarInitials, avatarTone, Button, Dropdown, ErrorMessage, FeatherIcon } from "@relay/ui";
import { recordTitle } from '../services/recordTitle';
import { linkedTitle } from '../services/linkedTitle';
import WorkspaceState from "./WorkspaceState.vue";
import InboxDirectory from "./messages/InboxDirectory.vue";
import ConversationTools from "./messages/ConversationTools.vue";
import ConversationDeliveries from "./messages/ConversationDeliveries.vue";
import MessageSearch from "./messages/MessageSearch.vue";
import ConversationCases from "./messages/ConversationCases.vue";
import ConversationTopics from "./messages/ConversationTopics.vue";
import InternalNotes from "./messages/InternalNotes.vue";
import CreateTicketDialog from "./messages/CreateTicketDialog.vue";
import ContactDetails from "./ContactDetails.vue";
import ContactInfoPage from "./messages/ContactInfoPage.vue";
import { objectValue } from './messageContent';
import MessageThread from "./messages/MessageThread.vue";
import StartConversation from "./messages/StartConversation.vue";
import BusinessMessageSearch from "./messages/BusinessMessageSearch.vue";
import ConversationSummary from "./messages/ConversationSummary.vue";
import EmailComposer from "./messages/EmailComposer.vue";
import SendChannel from "./messages/SendChannel.vue";
import MessageComposer from "./messages/MessageComposer.vue";
import { useMessages } from "../composables/useMessages";
import { sendNumbersKey, useSendNumbers } from "../composables/useSendNumbers";
import { useConversationPresence } from "../composables/useConversationPresence";
import { coreApi } from "../services/coreApi";
import { messagesKey } from "../composables/messagesContext";
import { useEnabledChannels } from "../composables/useEnabledChannels";
import { channelCan } from "../services/enabledChannels";
import { closeRoute, openRoute } from "../useViewRoute";
import { useMobileLayout } from "../composables/useMobileLayout";
import { contactInfoRoute, isContactInfoRoute } from "../services/mobileNav";
import { linkedLabel, recordIcon } from "../services/contactLinks";

const state = useMessages();
const channelEnabled = useEnabledChannels();
const capabilities = inject("relayCapabilities", ref({}));
const deliveriesOpen = ref(false), contactRecord = ref(null);
const casesOpen = ref(false), topicsOpen = ref(false);
const activeBusiness = computed(() => ({
  businessDoctype: businessType.value || source.value?.business_doctype || "",
  businessName: businessName.value || source.value?.business_name || "",
}));
const notesOpen = ref(false), contextOpen = ref(false), noteMessages = ref([]), noteContact = ref('');
const ticketOpen = ref(false), ticketMessage = ref(null), ticketQuoted = ref(false), ticketCreated = ref(null);
const noteBusiness = computed(() => noteMessages.value[0]?.business_name
  ? { businessDoctype: noteMessages.value[0].business_doctype, businessName: noteMessages.value[0].business_name }
  : activeBusiness.value);
const conversationContact = computed(() => source.value?.relay_contact || selected.value || '');
const frappeContact = computed(() => activeBusinessContact.value || source.value?.frappe_contact || contactRecord.value?.contact || '');

provide(messagesKey, state);
const numbers = useSendNumbers(state, capabilities);
provide(sendNumbersKey, numbers);
// On a site with several WhatsApp numbers the header names the number the customer wrote to.
const wroteTo = computed(() => numbers.active.value ? numbers.wroteTo.value : null);
const {
  businessType, businessName, businessContext, openBusiness,
  newer, restored, loadNewer, selected, rows, more, source, emoji,
  busy, error, connectionError, notice, channel, history, reply,
  focusMessage, openQuote, send, run,
} = state;

const startOpen = ref(false), startContact = ref(""), startChannel = ref(""), startContactLabel = ref(""), summaryOpen = ref(false), searchOpen = ref(false);
const linkedContacts = ref([]), contactsBusy = ref(false), contactsError = ref("");
const activeBusinessContact = ref("");
let contactRequest = 0;

const active = computed(() => selected.value || businessName.value);
const title = computed(() => (businessContext.value?.title ? recordTitle(businessContext.value) : '') || (businessName.value ? linkedTitle(businessType.value, businessName.value) : recordTitle(contactRecord.value?.primary || contactRecord.value, 'Conversation')));
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
const isMobile = useMobileLayout(), infoOpen = ref(false);
const primary = computed(() => businessName.value ? null : contactRecord.value?.primary);
const otherLinks = computed(() => businessName.value ? '' : linkedLabel(contactRecord.value));
const menuActions = computed(() => [
  ...(conversationContact.value ? [{label:'Delivery failures and retry',icon:'activity',onClick:() => deliveriesOpen.value = true}, {label:'Internal notes',disabled:busy.value,icon:'message-square',onClick:() => openNote()}, {label:'Cases',disabled:busy.value,icon:'briefcase',onClick:() => casesOpen.value = true}, {label:'Topics',disabled:busy.value,icon:'list',onClick:() => topicsOpen.value = true}] : []),
  ...(frappeContact.value ? [{label:'Business context',icon:'info',onClick:() => contextOpen.value = !contextOpen.value}] : []),
  ...(businessName.value && capabilities.value?.ai ? [{label:'Conversation summary',icon:'file-text',onClick:() => summaryOpen.value = !summaryOpen.value}] : []),
  {label:'Search conversation',icon:'search',onClick:() => searchOpen.value = !searchOpen.value},
]);
const channelLine = computed(() => {
  if (!source.value) return "";
  const provider = objectValue(source.value.provider_context).provider || "";
  const label = linkedTitle("Relay Channel", source.value.channel, "");
  return [provider, label].filter((value, index, list) => value && list.indexOf(value) === index).join(" · ");
});
function readInfoRoute() { infoOpen.value = location.hash.split("?")[0] === "#/messages" && isContactInfoRoute(location.hash); }
function openInfo() { openRoute(contactInfoRoute(location.hash)); infoOpen.value = true; }
function closeInfo() {
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  params.delete("info");
  closeRoute("#/messages?" + params);
  infoOpen.value = false;
}
function infoAction(open) { closeInfo(); open(); }
const recipientLabel = computed(() => {
  if (!source.value) return "";
  const linked = linkedContacts.value.find(item => item.value === source.value.frappe_contact);
  return recordTitle(linked?.label || source.value.contact_label || contactRecord.value?.display_name, "Contact");
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
  state.clearRecipient();
  closeNotes();
  activeBusinessContact.value = "";
  contactRoute("");
}
function openStart(contact = "") {
  startContact.value = businessName.value ? contact : selected.value;
  startChannel.value = numbers.active.value && startContact.value === numbers.contact.value ? numbers.current.value : "";
  startContactLabel.value = businessName.value ? linkedContacts.value.find(item => item.value === contact)?.label || ""
    : startContact.value ? recordTitle(contactRecord.value, "") || recordTitle(contactRecord.value?.primary, "") : "";
  startOpen.value = true;
}
async function started(result) {
  startOpen.value = false;
  if (!businessName.value && result?.contact && result.contact !== selected.value) {
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
  ticketCreated.value = null;
  ticketOpen.value = !!ticketMessage.value;
}
function closeNotes() { casesOpen.value = false; topicsOpen.value = false; notesOpen.value = false; noteMessages.value = []; noteContact.value = ''; }
function openNote(message) {
  noteContact.value = message ? message.relay_contact : conversationContact.value;
  noteMessages.value = message ? [message] : [];
  notesOpen.value = !!noteContact.value;
}
watch(source, value => {
  if (businessName.value && value?.frappe_contact && activeBusinessContact.value && activeBusinessContact.value !== value.frappe_contact) activeBusinessContact.value = value.frappe_contact;
});
function clearRecipient() {
  activeBusinessContact.value = "";
  state.clearRecipient();
}

const lastVisible = ref(""), visibleMessages = ref([]);
const contactRows = computed(() => visibleRows.value.filter(row => row.relay_contact === conversationContact.value && !row._pending));
const contactVisibleMessages = computed(() => {
  const visible = new Set(visibleMessages.value);
  return contactRows.value.filter(row => visible.has(row.name)).map(row => row.name);
});
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
  contactRecord.value = null; closeNotes(); deliveriesOpen.value = false;
  lastVisible.value = ''; visibleMessages.value = [];
  if (contact) loadProfile(contact);
}, { immediate: true });
watch([businessType, businessName], () => {
  closeNotes(); contextOpen.value = false;
  summaryOpen.value = false;
  searchOpen.value = false;
  activeBusinessContact.value = "";
  lastVisible.value = "";
  visibleMessages.value = [];
  loadBusinessContacts();
}, { immediate: true });
function readContactRoute() {
  if (location.hash.split('?')[0] !== '#/messages' || busy.value) return;
  const params = new URLSearchParams(location.hash.split('?')[1] || '');
  if (!businessName.value) {
    if (params.get('contact') === selected.value && params.get('notes') === '1' && !error.value) {
      openNote();
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
const moreSentinel = useLoadMore({ loading: busy, hasMore: () => state.pendingCursor.value, error: () => state.error.value, load: () => state.loadPending() })
</script>

<template>
  <section class="connected-inbox" :class="{ 'has-conversation': active }" aria-label="Business inbox">
    <StartConversation v-if="startOpen" :key="businessName + ':' + startContact" :contact="startContact" :contact-label="startContactLabel" :channel="startChannel"
      :contacts="linkedContacts"
      :business-doctype="businessType" :business-name="businessName" @close="startOpen = false" @sent="started" />

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
          <h2><button v-if="isMobile && (frappeContact || conversationContact)" type="button" class="conversation-title-button" aria-label="Open contact info" @click="openInfo">{{ title }}</button><template v-else>{{ title }}</template></h2>
          <p v-if="isMobile && wroteTo" class="conversation-channel-line"><span class="number-tag">{{ wroteTo.label }}</span>{{ wroteTo.address }}</p>
          <p v-else-if="isMobile && channelLine" class="conversation-channel-line">{{ channelLine }}</p>
          <div class="conversation-meta">
            <span v-if="businessContext?.doctype_label || businessType"><FeatherIcon name="file-text" :size="13" />{{ businessContext?.doctype_label || businessType }}</span>
            <span v-if="groupLabel">{{ groupLabel }}</span>
            <span v-if="contactCount">{{ contactCount }}</span>
            <template v-if="!isMobile">
              <span v-if="primary" class="conversation-record"><FeatherIcon :name="recordIcon(primary.doctype).icon" :size="13" />{{ primary.title }}<small>· {{ primary.doctype }}</small></span>
              <button v-if="otherLinks" type="button" class="conversation-linked" :aria-expanded="contextOpen" @click="contextOpen = !contextOpen">{{ otherLinks }}</button>
            </template>
            <span v-if="!isMobile && wroteTo" class="conversation-number"><FeatherIcon name="message-circle" :size="13" />Wrote to {{ wroteTo.label }}<small v-if="wroteTo.address">· {{ wroteTo.address }}</small></span>
            <span v-else-if="!isMobile && channelLine" class="conversation-channel">· {{ channelLine }}</span>
          </div>
        </div>
        <div class="conversation-heading-actions">
          <span v-if="people.length" class="conversation-viewers"><span class="viewer-stack" aria-hidden="true"><span v-for="person in people.slice(0, 3)" :key="person.name" :class="avatarTone(person.full_name || person.name)">{{ avatarInitials(person.full_name || person.name) }}</span></span>{{ people.length }} viewing</span>
          <ConversationTools v-if="conversationContact" :key="conversationContact" :contact="conversationContact" :last-message="contactRows.at(-1)?.name" :last-visible="contactVisibleMessages.at(-1)" :visible-messages="contactVisibleMessages" :actions="menuActions" :menu-icon="isMobile ? 'more-vertical' : 'more-horizontal'">
            <Button class="conversation-ticket" icon="bookmark" label="Ticket" title="Create ticket" :disabled="busy || !contactRows.length" @click="openTicket()" />
          </ConversationTools>
          <Dropdown v-else :options="menuActions"><Button :icon="isMobile ? 'more-vertical' : 'more-horizontal'" aria-label="Conversation actions" title="Conversation actions" /></Dropdown>
        </div>
      </header>

      <div v-if="isMobile && (primary || otherLinks)" class="mobile-record-bar">
        <span v-if="primary" class="mobile-record-chip"><FeatherIcon :name="recordIcon(primary.doctype).icon" :size="14" />{{ primary.title }}<small>· {{ primary.doctype }}</small></span>
        <button v-if="otherLinks" type="button" class="mobile-linked-chip" @click="openInfo">{{ otherLinks }}</button>
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

      <div v-if="contextOpen && frappeContact" class="v1-context"><ContactDetails :contact="frappeContact" @changed="loadProfile(selected)" /></div>
      <ConversationCases v-if="casesOpen && conversationContact" :key="conversationContact" :contact="conversationContact" v-bind="activeBusiness" @close="casesOpen = false" />
      <ConversationTopics v-if="topicsOpen && conversationContact" :key="conversationContact" :contact="conversationContact" v-bind="activeBusiness" :messages="contactRows" @close="topicsOpen = false" @open="focusMessage" />
      <InternalNotes v-bind="noteBusiness" v-if="notesOpen && noteContact" :key="noteContact" :contact="noteContact" :messages="noteMessages" @close="closeNotes" @open="focusMessage" @clear-messages="noteMessages = []" />
      <ConversationDeliveries v-if="deliveriesOpen && conversationContact" :key="conversationContact" :contact="conversationContact" @close="deliveriesOpen = false" @open="focusMessage" />
      <MessageSearch v-if="searchOpen && selected && !businessName" :contact="selected" @close="searchOpen = false" @open="searchOpen = false; focusMessage($event)" />
      <BusinessMessageSearch v-if="searchOpen && businessName" :business-doctype="businessType" :business-name="businessName"
        @close="searchOpen = false" @open="searchOpen = false; focusMessage($event)" />
      <ErrorMessage class="px-4" :message="error || contactsError" />
      <p v-if="connectionError" role="status" class="relay-connection-state">{{ connectionError }}</p>
      <p v-if="notice" role="status" class="feedback-panel">{{ notice }}</p>
      <p v-if="ticketCreated" role="status" class="feedback-panel">Ticket created. <a class="v1-link" :href="ticketCreated.href">Open ticket</a></p>
      <CreateTicketDialog v-if="ticketMessage" v-model="ticketOpen" :contact="ticketMessage.relay_contact || conversationContact" :message="ticketMessage" :quoted="ticketQuoted" :contact-name="title" @created="ticketCreated = $event" />

      <MessageThread :key="active + ':' + channel + ':' + activeBusinessContact" :position="state.viewPosition.value"
        :newer="newer" :anchor="restored" :unread="state.firstUnread.value" :rows="visibleRows" :more="more" :busy="busy" :error="state.error.value" :emoji="emoji"
        :selected="active" :contact-name="activeContact?.label || title" :can-comment="true" @note="openNote" @ticket="openTicket"
        @position="state.rememberPosition" @newer="loadNewer" @visible="lastVisible = $event"
        @visible-messages="visibleMessages = $event" @older="run(() => history(true))" @reply="reply"
        @quote="openQuote" @reconcile="state.checkPending" @send="send" />

      <div v-if="state.pendingCursor.value" ref="moreSentinel" class="h-px" aria-hidden="true" />
      <Button v-if="newer || state.newArrivals.value" class="jump-latest" icon-left="arrow-down"
        :label="state.newArrivals.value ? `${state.newArrivals.value} new messages` : 'Go to latest'"
        :disabled="busy" @click="state.latest" />

      <EmailComposer v-if="source && channelCan(capabilities, objectValue(source.provider_context).provider, 'email_threading')" :key="source.name">
        <template #channel><SendChannel /></template>
        <template #recipient><div class="business-recipient-bar"><span>To</span><strong>{{ recipientLabel }}</strong><button type="button" :disabled="busy" @click="clearRecipient">Change</button></div></template>
      </EmailComposer>
      <MessageComposer v-else-if="source && channelEnabled(objectValue(source.provider_context).provider)" :key="source.channel + source.sender_endpoint" :recipient="recipientLabel" @note="openNote()" @template="openStart(source?.frappe_contact || '')">
        <template #channel><SendChannel /></template>
        <template #recipient><div class="business-recipient-bar"><span>To</span><strong>{{ recipientLabel }}</strong><button type="button" :disabled="busy" @click="clearRecipient">Change</button></div></template>
      </MessageComposer>
      <div v-else-if="active" class="business-compose-start">
        <Button variant="solid" icon-left="plus" :label="activeContact ? `Message ${activeContact.label}` : 'New message'"
          :disabled="busy || contactsBusy" @click="openStart(activeBusinessContact)" />
      </div>

      <ConversationSummary v-if="summaryOpen && businessName && capabilities.ai" :business-doctype="businessType" :business-name="businessName"
        @close="summaryOpen = false" @open="focusMessage" />
    </div>
    <div v-else class="connected-thread whatsapp-empty-pane" aria-label="No open conversation">
      <WorkspaceState title="Choose a conversation" description="Select a customer on the left to view messages and reply." icon="message-circle" />
    </div>
    </Transition>

    <Transition name="relay-page">
      <ContactInfoPage v-if="isMobile && infoOpen && active" :title="title" :contact="frappeContact" :primary="contactRecord?.primary" :channel="channelLine"
        :can-organize="!!conversationContact && !busy" @close="closeInfo" @cases="infoAction(() => casesOpen = true)" @notes="infoAction(() => openNote())" @changed="loadProfile(selected)" />
    </Transition>
  </section>
</template>

<style scoped>
.conversation-compose-context { display:flex; align-items:center; gap:8px; padding:6px 16px; border-top:1px solid var(--outline-gray-2); }
.conversation-compose-context > :first-child { flex-shrink:0; }
.conversation-compose-context .business-recipient-bar { flex:1; flex-wrap:nowrap; min-width:0; padding:0; border:0; }
.business-recipient-bar strong { flex:1; }
.business-recipient-bar button { flex-shrink:0; min-height:36px; }
</style>
