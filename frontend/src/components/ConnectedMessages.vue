<script setup>
import { provide, computed, ref, watch, onBeforeUnmount, onMounted } from "vue";
import { Avatar, Button, Dropdown, ErrorMessage } from "@relay/ui";
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
import ContactDetails from "./ContactDetails.vue";
import { objectValue } from './messageContent';
import MessageThread from "./messages/MessageThread.vue";
import StartConversation from "./messages/StartConversation.vue";
import BusinessMessageSearch from "./messages/BusinessMessageSearch.vue";
import ConversationSummary from "./messages/ConversationSummary.vue";
import EmailComposer from "./messages/EmailComposer.vue";
import SendChannel from "./messages/SendChannel.vue";
import MessageComposer from "./messages/MessageComposer.vue";
import { useMessages } from "../composables/useMessages";
import { useConversationPresence } from "../composables/useConversationPresence";
import { coreApi } from "../services/coreApi";
import { messagesKey } from "../composables/messagesContext";
import { useEnabledChannels } from "../composables/useEnabledChannels";

const state = useMessages();
const channelEnabled = useEnabledChannels();
const deliveriesOpen = ref(false), contactRecord = ref(null);
const casesOpen = ref(false), topicsOpen = ref(false);
const activeBusiness = computed(() => ({
  businessDoctype: businessType.value || source.value?.business_doctype || "",
  businessName: businessName.value || source.value?.business_name || "",
}));
const notesOpen = ref(false), contextOpen = ref(false), noteMessages = ref([]), noteContact = ref('');
const noteBusiness = computed(() => noteMessages.value[0]?.business_name
  ? { businessDoctype: noteMessages.value[0].business_doctype, businessName: noteMessages.value[0].business_name }
  : activeBusiness.value);
const conversationContact = computed(() => source.value?.relay_contact || selected.value || '');
const frappeContact = computed(() => activeBusinessContact.value || source.value?.frappe_contact || contactRecord.value?.contact || '');

provide(messagesKey, state);
const {
  businessType, businessName, businessContext, openBusiness,
  newer, restored, loadNewer, selected, rows, more, source, emoji,
  busy, error, connectionError, notice, channel, history, reply,
  focusMessage, openQuote, send, run,
} = state;

const startOpen = ref(false), startContact = ref(""), startContactLabel = ref(""), summaryOpen = ref(false), searchOpen = ref(false);
const linkedContacts = ref([]), contactsBusy = ref(false), contactsError = ref("");
const activeBusinessContact = ref("");
let contactRequest = 0;

const active = computed(() => selected.value || businessName.value);
const title = computed(() => (businessContext.value?.title ? recordTitle(businessContext.value) : '') || (businessName.value ? linkedTitle(businessType.value, businessName.value) : recordTitle(contactRecord.value, 'Conversation')));
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
  window.history.pushState(null, "", "#/messages?" + params.toString());
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
  startContactLabel.value = linkedContacts.value.find(item => item.value === contact)?.label || "";
  startOpen.value = true;
}
async function started(result) {
  startOpen.value = false;
  if (!businessName.value && result?.contact && result.contact !== selected.value) {
    historyRoute(result.contact);
    await state.open(result.contact);
  } else {
    await run(() => history());
    if (businessName.value && result?.contact) chooseContact(result.contact);
  }
}
function historyRoute(contact) { window.history.pushState(null, '', '#/messages?contact=' + encodeURIComponent(contact)); }
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

watch(selected, async contact => {
  contactRecord.value = null; closeNotes(); deliveriesOpen.value = false;
  lastVisible.value = ''; visibleMessages.value = [];
  if (!contact) return;
  try { const record = await coreApi('api.contact_profile', { contact }); if (selected.value === contact) contactRecord.value = record; }
  catch (e) { if (selected.value === contact) contactsError.value = e.message; }
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
onMounted(() => { readContactRoute(); window.addEventListener('hashchange', readContactRoute); window.addEventListener('popstate', readContactRoute); });
onBeforeUnmount(() => { ++contactRequest; window.removeEventListener('hashchange', readContactRoute); window.removeEventListener('popstate', readContactRoute); });
</script>

<template>
  <section class="connected-inbox" :class="{ 'has-conversation': active }" aria-label="Business inbox">
    <StartConversation v-if="startOpen" :key="businessName + ':' + startContact" :contact="startContact" :contact-label="startContactLabel"
      :contacts="linkedContacts"
      :business-doctype="businessType" :business-name="businessName" @close="startOpen = false" @sent="started" />

    <aside class="contact-directory">
      <InboxDirectory :selected="selected" :business-name="businessName" :business-type="businessType" :busy="busy"
        @business="openBusiness" @select="contact => { state.open(contact); historyRoute(contact) }" />
    </aside>

    <div v-if="active" class="connected-thread">
      <header class="conversation-heading">
        <Button class="mobile-only conversation-back" icon="arrow-left" aria-label="Back to conversations" title="Back to conversations" @click="state.clearSelection()" />
        <Avatar :label="title" aria-hidden="true" />
        <div class="conversation-title">
          <h2>{{ title }}</h2>
          <div class="conversation-meta">
            <span v-if="businessContext?.doctype_label || businessType">{{ businessContext?.doctype_label || businessType }}</span>
            <span v-if="groupLabel">{{ groupLabel }}</span>
            <span v-if="contactCount">{{ contactCount }}</span>
            <span v-if="people.length">{{ people.length }} viewing</span>
          </div>
        </div>
        <div class="conversation-heading-actions">
          <ConversationTools v-if="conversationContact" :key="conversationContact" :contact="conversationContact" :last-message="contactRows.at(-1)?.name" :last-visible="contactVisibleMessages.at(-1)" :visible-messages="contactVisibleMessages" />
          <Dropdown :options="[
            ...(conversationContact ? [{label:'Delivery failures and retry',icon:'activity',onClick:() => deliveriesOpen = true}, {label:'Internal notes',disabled:busy,icon:'message-square',onClick:() => openNote()}, {label:'Cases',disabled:busy,icon:'briefcase',onClick:() => casesOpen = true}, {label:'Topics',disabled:busy,icon:'list',onClick:() => topicsOpen = true}] : []),
            ...(frappeContact ? [{label:'Business context',icon:'info',onClick:() => contextOpen = !contextOpen}] : []),
            ...(businessName ? [{label:'Conversation summary',icon:'file-text',onClick:() => summaryOpen = !summaryOpen}] : []),
            {label:'Search conversation',icon:'search',onClick:() => searchOpen = !searchOpen}
          ]"><Button icon="more-horizontal" aria-label="Conversation actions" title="Conversation actions" /></Dropdown>
        </div>
      </header>

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

      <div v-if="contextOpen && frappeContact" class="v1-context"><ContactDetails :contact="frappeContact" /></div>
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

      <MessageThread :key="active + ':' + channel + ':' + activeBusinessContact" :position="state.viewPosition.value"
        :newer="newer" :anchor="restored" :unread="state.firstUnread.value" :rows="visibleRows" :more="more" :busy="busy" :emoji="emoji"
        :selected="active" :contact-name="activeContact?.label || title" :can-comment="true" @note="openNote"
        @position="state.rememberPosition" @newer="loadNewer" @visible="lastVisible = $event"
        @visible-messages="visibleMessages = $event" @older="run(() => history(true))" @reply="reply"
        @quote="openQuote" @reconcile="state.checkPending" @send="send" />

      <Button v-if="state.pendingCursor.value" label="More queued attempts" :disabled="busy" @click="state.loadPending" />
      <Button v-if="newer || state.newArrivals.value" class="jump-latest" icon-left="arrow-down"
        :label="state.newArrivals.value ? `${state.newArrivals.value} new messages` : 'Go to latest'"
        :disabled="busy" @click="state.latest" />

      <EmailComposer v-if="source && objectValue(source.provider_context).provider === 'Email' && channelEnabled('Email')" :key="source.name">
        <template #channel><SendChannel /></template>
        <template #recipient><div class="business-recipient-bar"><span>To</span><strong>{{ recipientLabel }}</strong><button type="button" :disabled="busy" @click="clearRecipient">Change</button></div></template>
      </EmailComposer>
      <MessageComposer v-else-if="source && channelEnabled(objectValue(source.provider_context).provider)" :key="source.channel + source.sender_endpoint" @template="openStart(source?.frappe_contact || '')">
        <template #channel><SendChannel /></template>
        <template #recipient><div class="business-recipient-bar"><span>To</span><strong>{{ recipientLabel }}</strong><button type="button" :disabled="busy" @click="clearRecipient">Change</button></div></template>
      </MessageComposer>
      <div v-else-if="active" class="business-compose-start">
        <Button variant="solid" icon-left="plus" :label="activeContact ? `Message ${activeContact.label}` : 'New message'"
          :disabled="busy || contactsBusy" @click="openStart(activeBusinessContact)" />
      </div>

      <ConversationSummary v-if="summaryOpen && businessName" :business-doctype="businessType" :business-name="businessName"
        @close="summaryOpen = false" @open="focusMessage" />
    </div>
    <div v-else class="connected-thread whatsapp-empty-pane" aria-label="No open conversation">
      <WorkspaceState title="Choose a conversation" description="Select a customer on the left to view messages and reply." icon="message-circle" />
    </div>
  </section>
</template>

<style scoped>
.conversation-compose-context { display:flex; align-items:center; gap:8px; padding:6px 16px; border-top:1px solid var(--outline-gray-2); }
.conversation-compose-context > :first-child { flex-shrink:0; }
.conversation-compose-context .business-recipient-bar { flex:1; flex-wrap:nowrap; min-width:0; padding:0; border:0; }
.business-recipient-bar strong { flex:1; }
.business-recipient-bar button { flex-shrink:0; min-height:36px; }
</style>
