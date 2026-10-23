<script setup>
import { provide, computed, ref, watch, onBeforeUnmount, onMounted } from "vue";
import { Button, ErrorMessage, FeatherIcon } from "@relay/ui";
import InboxDirectory from "./messages/InboxDirectory.vue";
import ConversationTools from "./messages/ConversationTools.vue";
import ConversationDeliveries from "./messages/ConversationDeliveries.vue";
import MessageSearch from "./messages/MessageSearch.vue";
import InternalNotes from "./messages/InternalNotes.vue";
import ContactDetails from "./ContactDetails.vue";
import { objectValue } from './messageContent';
import MessageThread from "./messages/MessageThread.vue";
import StartConversation from "./messages/StartConversation.vue";
import BusinessMessageSearch from "./messages/BusinessMessageSearch.vue";
import ConversationSummary from "./messages/ConversationSummary.vue";
import MessageComposer from "./messages/MessageComposer.vue";
import { useMessages } from "../composables/useMessages";
import { useConversationPresence } from "../composables/useConversationPresence";
import { coreApi, frappeRequest } from "../services/coreApi";
import { messagesKey } from "../composables/messagesContext";

const state = useMessages();
const deliveriesOpen = ref(false), contactRecord = ref(null);
const notesOpen = ref(false), contextOpen = ref(false), noteMessages = ref([]), noteContact = ref('');
const conversationContact = computed(() => source.value?.relay_contact || selected.value || '');
const frappeContact = computed(() => activeBusinessContact.value || source.value?.frappe_contact || contactRecord.value?.contact || '');
const isWhatsApp = row => objectValue(row.provider_context).provider === 'WhatsApp' && !objectValue(row.provider_context).group_id;
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
const title = computed(() => businessContext.value?.title || businessName.value || contactRecord.value?.display_name || "Conversation");
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
  const all = state.displayRows.value.filter(isWhatsApp);
  if (!activeBusinessContact.value) return all;
  const target = messagesByContact.value.get(activeBusinessContact.value);
  if (!target) return [];
  return all.filter(row => row.frappe_contact === activeBusinessContact.value ||
    (row.channel === target.channel && row.sender_endpoint === target.sender_endpoint));
});
const recipientLabel = computed(() => {
  if (!source.value) return "";
  const linked = linkedContacts.value.find(item => item.value === source.value.frappe_contact);
  return linked?.label || source.value.contact_label || contactRecord.value?.display_name || "Contact";
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
  if (message && isWhatsApp(message)) state.selectRecipient(message);
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
function closeNotes() { notesOpen.value = false; noteMessages.value = []; noteContact.value = ''; }
function openNote(message) {
  noteContact.value = message ? message.relay_contact : conversationContact.value;
  noteMessages.value = message ? [message] : [];
  notesOpen.value = !!noteContact.value;
}
watch(source, value => {
  if (value && !isWhatsApp(value)) state.clearRecipient();
  else if (businessName.value && value?.frappe_contact && activeBusinessContact.value && activeBusinessContact.value !== value.frappe_contact) activeBusinessContact.value = value.frappe_contact;
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
  try { const record = await frappeRequest('frappe.client.get', { doctype: 'Relay Contact', name: contact }); if (selected.value === contact) contactRecord.value = record; }
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
        <Button class="mobile-only conversation-back" icon="arrow-left" aria-label="Back to businesses" title="Back to businesses" @click="state.clearSelection()" />
        <span class="conversation-avatar" aria-hidden="true">{{ title.slice(0, 1).toUpperCase() }}</span>
        <div class="conversation-title">
          <h2>{{ title }}</h2>
          <div class="conversation-meta">
            <span>{{ businessContext?.doctype_label || businessType }}</span>
            <span v-if="groupLabel">{{ groupLabel }}</span>
            <span v-if="contactCount">{{ contactCount }}</span>
            <span v-if="people.length">{{ people.length }} viewing</span>
          </div>
        </div>
        <div class="conversation-heading-actions">
          <Button v-if="conversationContact" icon="activity" aria-label="Delivery failures and retry" title="Delivery failures and retry" @click="deliveriesOpen = true" />
          <Button v-if="frappeContact" icon="info" aria-label="Business context" title="Business context" @click="contextOpen = !contextOpen" />
          <Button v-if="conversationContact" icon="message-square" aria-label="Internal notes" title="Internal notes" @click="openNote()" />
          <Button v-if="businessName" icon="file-text" aria-label="Conversation summary" title="Conversation summary" @click="summaryOpen = !summaryOpen" />
          <Button icon="search" aria-label="Search conversation" title="Search conversation" @click="searchOpen = !searchOpen" />
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
          <span class="contact-chip-copy"><strong>{{ contact.label }}</strong><small>{{ contact.description || "No WhatsApp number" }}</small></span>
        </button>
        <span v-if="contactsBusy" class="contact-strip-loading" role="status">Loading contacts</span>
      </nav>

      <ConversationTools v-if="conversationContact" :key="conversationContact" :contact="conversationContact" :last-message="contactRows.at(-1)?.name" :last-visible="contactVisibleMessages.at(-1)" :visible-messages="contactVisibleMessages" />
      <div v-if="contextOpen && frappeContact" class="v1-context"><ContactDetails :contact="frappeContact" /></div>
      <InternalNotes v-if="notesOpen && noteContact" :key="noteContact" :contact="noteContact" :messages="noteMessages" @close="closeNotes" @open="focusMessage" @clear-messages="noteMessages = []" />
      <ConversationDeliveries v-if="deliveriesOpen && conversationContact" :key="conversationContact" :contact="conversationContact" @close="deliveriesOpen = false" @open="focusMessage" />
      <MessageSearch v-if="searchOpen && selected && !businessName" :contact="selected" @close="searchOpen = false" @open="searchOpen = false; focusMessage($event)" />
      <BusinessMessageSearch v-if="searchOpen && businessName" :business-doctype="businessType" :business-name="businessName"
        @close="searchOpen = false" @open="searchOpen = false; focusMessage($event)" />
      <ErrorMessage class="px-4" :message="error || contactsError" />
      <p v-if="connectionError" role="status" class="relay-connection-state">{{ connectionError }}</p>
      <p v-if="notice" role="status" class="feedback-panel">{{ notice }}</p>

      <MessageThread :key="active + ':' + channel + ':' + activeBusinessContact" :position="state.viewPosition.value"
        :newer="newer" :anchor="restored" :rows="visibleRows" :more="more" :busy="busy" :emoji="emoji"
        :selected="active" :contact-name="activeContact?.label || title" :can-comment="true" @note="openNote"
        @position="state.rememberPosition" @newer="loadNewer" @visible="lastVisible = $event"
        @visible-messages="visibleMessages = $event" @older="run(() => history(true))" @reply="reply"
        @quote="openQuote" @reconcile="state.checkPending" @send="send" />

      <Button v-if="newer || state.newArrivals.value" class="jump-latest" icon-left="arrow-down"
        :label="state.newArrivals.value ? `${state.newArrivals.value} new messages` : 'Go to latest'"
        :disabled="busy" @click="state.latest" />

      <div v-if="source" class="business-recipient-bar">
        <span>To</span><strong>{{ recipientLabel }} · {{ source.sender_endpoint }}</strong><button type="button" :disabled="busy" @click="clearRecipient">Change</button>
      </div>
      <MessageComposer v-if="source" :key="source.channel + source.sender_endpoint" @template="openStart(source?.frappe_contact || '')" />
      <div v-else-if="active" class="business-compose-start">
        <Button icon-left="plus" :label="activeContact ? `Message ${activeContact.label}` : 'New message'"
          :disabled="busy || contactsBusy" @click="openStart(activeBusinessContact)" />
      </div>

      <ConversationSummary v-if="summaryOpen && businessName" :business-doctype="businessType" :business-name="businessName"
        @close="summaryOpen = false" @open="focusMessage" />
    </div>
    <div v-else class="connected-thread whatsapp-empty-pane" aria-label="No open conversation">
      <div class="whatsapp-empty-mark" aria-hidden="true"><FeatherIcon name="message-circle" :size="34" /></div>
      <h2>Relay for WhatsApp</h2>
      <p>Business conversations, linked contacts, and message history in one workspace.</p>
      <div class="whatsapp-empty-security"><FeatherIcon name="lock" :size="13" /> Connected to your Frappe business records</div>
    </div>
  </section>
</template>
