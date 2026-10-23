<script setup>
import { provide, computed, ref, watch, onBeforeUnmount } from "vue";
import { Button, ErrorMessage, FeatherIcon } from "@relay/ui";
import BusinessDirectory from "./messages/BusinessDirectory.vue";
import MessageThread from "./messages/MessageThread.vue";
import StartConversation from "./messages/StartConversation.vue";
import BusinessMessageSearch from "./messages/BusinessMessageSearch.vue";
import ConversationSummary from "./messages/ConversationSummary.vue";
import MessageComposer from "./messages/MessageComposer.vue";
import { useMessages } from "../composables/useMessages";
import { useConversationPresence } from "../composables/useConversationPresence";
import { coreApi } from "../services/coreApi";
import { messagesKey } from "../composables/messagesContext";

const state = useMessages();
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
const title = computed(() => businessContext.value?.title || businessName.value || "Business inbox");
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
  return linked?.label || source.value.contact_label || "Contact";
});

async function loadBusinessContacts() {
  const request = ++contactRequest;
  linkedContacts.value = [];
  contactsError.value = "";
  if (!businessType.value || !businessName.value) return;
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
  activeBusinessContact.value = contact;
  const message = messagesByContact.value.get(contact);
  if (message) state.selectRecipient(message);
  if (updateRoute) contactRoute(contact);
}
function showAllContacts() {
  activeBusinessContact.value = "";
  contactRoute("");
}
function openStart(contact = "") {
  startContact.value = contact;
  startContactLabel.value = linkedContacts.value.find(item => item.value === contact)?.label || "";
  startOpen.value = true;
}
async function started(result) {
  startOpen.value = false;
  await history();
  if (result?.contact) chooseContact(result.contact);
}
function clearRecipient() {
  activeBusinessContact.value = "";
  source.value = null;
  state.quoting.value = false;
}

const lastVisible = ref(""), visibleMessages = ref([]);
const { people } = useConversationPresence({
  get contact() { return selected.value; },
  get businessDoctype() { return businessType.value; },
  get businessName() { return businessName.value; },
  get lastVisible() { return lastVisible.value; },
  get visibleMessages() { return visibleMessages.value; },
}, () => {});

watch([businessType, businessName], () => {
  summaryOpen.value = false;
  searchOpen.value = false;
  activeBusinessContact.value = "";
  lastVisible.value = "";
  visibleMessages.value = [];
  loadBusinessContacts();
}, { immediate: true });
onBeforeUnmount(() => { ++contactRequest; });
</script>

<template>
  <section class="connected-inbox" :class="{ 'has-conversation': active }" aria-label="Business inbox">
    <StartConversation v-if="startOpen" :key="businessName + ':' + startContact" :contact="startContact" :contact-label="startContactLabel"
      :contacts="linkedContacts"
      :business-doctype="businessType" :business-name="businessName" @close="startOpen = false" @sent="started" />

    <aside class="contact-directory">
      <BusinessDirectory :selected="businessName" :selected-doctype="businessType" :busy="busy" @select="openBusiness" />
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
          <Button icon="file-text" aria-label="Conversation summary" title="Conversation summary" @click="summaryOpen = !summaryOpen" />
          <Button icon="search" aria-label="Search conversation" title="Search conversation" @click="searchOpen = !searchOpen" />
        </div>
      </header>

      <nav v-if="businessName" class="business-contact-strip" aria-label="Business contacts">
        <button type="button" :aria-pressed="!activeBusinessContact" :class="{ active: !activeBusinessContact }" @click="showAllContacts">
          <span>All</span><small>{{ linkedContacts.length }}</small>
        </button>
        <button v-for="contact in linkedContacts" :key="contact.value" type="button"
          :aria-pressed="activeBusinessContact === contact.value" :class="{ active: activeBusinessContact === contact.value }"
          @click="chooseContact(contact.value)">
          <span class="contact-chip-avatar">{{ contact.label.slice(0, 1).toUpperCase() }}</span>
          <span class="contact-chip-copy"><strong>{{ contact.label }}</strong><small>{{ contact.description || "No WhatsApp number" }}</small></span>
        </button>
        <span v-if="contactsBusy" class="contact-strip-loading" role="status">Loading contacts</span>
      </nav>

      <BusinessMessageSearch v-if="searchOpen && businessName" :business-doctype="businessType" :business-name="businessName"
        @close="searchOpen = false" @open="searchOpen = false; focusMessage($event)" />
      <ErrorMessage class="px-4" :message="error || contactsError" />
      <p v-if="connectionError" role="status" class="relay-connection-state">{{ connectionError }}</p>
      <p v-if="notice" role="status" class="feedback-panel">{{ notice }}</p>

      <MessageThread :key="active + ':' + channel + ':' + activeBusinessContact" :position="state.viewPosition.value"
        :newer="newer" :anchor="restored" :rows="visibleRows" :more="more" :busy="busy" :emoji="emoji"
        :selected="active" :contact-name="activeContact?.label || title" :can-comment="!!selected"
        @position="state.rememberPosition" @newer="loadNewer" @visible="lastVisible = $event"
        @visible-messages="visibleMessages = $event" @older="run(() => history(true))" @reply="reply"
        @quote="openQuote" @reconcile="state.checkPending" @send="send" />

      <Button v-if="newer || state.newArrivals.value" class="jump-latest" icon-left="arrow-down"
        :label="state.newArrivals.value ? `${state.newArrivals.value} new messages` : 'Go to latest'"
        :disabled="busy" @click="state.latest" />

      <div v-if="businessName && source" class="business-recipient-bar">
        <span>To</span><strong>{{ recipientLabel }}</strong><button type="button" @click="clearRecipient">Change</button>
      </div>
      <MessageComposer v-if="source" @template="openStart(source?.frappe_contact || '')" />
      <div v-else-if="businessName" class="business-compose-start">
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
