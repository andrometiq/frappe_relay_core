<script setup>
import { useLoadMore } from '../../composables/useLoadMore'
import ChoiceField from '../fields/ChoiceField.vue'
import { linkedTitle } from '../../services/linkedTitle'
import { recordTitle } from '../../services/recordTitle'
import { ref, onMounted, onBeforeUnmount, watch } from "vue";
import { TextInput, ErrorMessage, FeatherIcon } from "@relay/ui";
import RemoteLinkField from "../fields/RemoteLinkField.vue";
import { coreApi } from "../../services/coreApi";
import { useRealtimeRefresh } from "../../composables/useRealtimeRefresh";
import VirtualScroller from "primevue/virtualscroller";

const props = defineProps({ selected: String, selectedDoctype: String, busy: Boolean });
const emit = defineEmits(["select"]);
const types = ref([]), doctype = ref(""), group = ref(""), groupField = ref(""),
  query = ref(""), records = ref([]), next = ref(null), owner = ref(""),
  user = ref(""), loading = ref(false), error = ref(""), filtersOpen = ref(false);
let timer, sequence = 0;

async function loadRecords(reset = true) {
  if (!doctype.value || (!reset && (loading.value || next.value === null))) return;
  const current = reset ? ++sequence : sequence;
  const start = reset ? 0 : next.value;
  if (reset) { records.value = []; next.value = null; owner.value = ""; }
  loading.value = true; error.value = "";
  try {
    const result = await coreApi("business_groups.records", {
      doctype: doctype.value, group: group.value, query: query.value, start,
    });
    if (current !== sequence) return;
    const known = new Set(records.value.map(record => record.name));
    records.value = reset ? result.items : [
      ...records.value,
      ...result.items.filter(record => !known.has(record.name)),
    ];
    next.value = result.next;
    owner.value = result.assigned_to;
    user.value = result.user;
  } catch (e) {
    if (current === sequence) error.value = e.message;
  } finally {
    if (current === sequence) loading.value = false;
  }
}

async function loadInitialGroup() {
  const current = ++sequence;
  records.value = []; next.value = null; group.value = ""; groupField.value = ""; query.value = "";
  if (!doctype.value) return;
  loading.value = true; error.value = "";
  try {
    const result = await coreApi("business_groups.directory", { doctype: doctype.value, query: "", include_all: 1 });
    if (current !== sequence) return;
    groupField.value = result.field;
    group.value = result.items[0]?.value || "";
  } catch (e) {
    if (current === sequence) error.value = e.message;
  } finally {
    if (current === sequence) loading.value = false;
  }
  if (current === sequence) await loadRecords(true);
}

function scrolled(event) {
  const node = event.currentTarget;
  if (node.scrollLeft) node.scrollLeft = 0;
}

function timeLabel(value) {
  if (!value) return "";
  const date = new Date(String(value).replace(" ", "T"));
  if (Number.isNaN(date.getTime())) return "";
  const today = new Date();
  if (date.toDateString() === today.toDateString())
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const age = today.getTime() - date.getTime();
  if (age >= 0 && age < 6 * 86400000)
    return date.toLocaleDateString([], { weekday: "short" });
  return date.toLocaleDateString([], { day: "2-digit", month: "2-digit", year: "2-digit" });
}

async function claim(release = false) {
  loading.value = true; error.value = "";
  try {
    const result = await coreApi("business_groups.claim", {
      doctype: doctype.value, group: group.value, release,
    }, true);
    owner.value = result.assigned_to;
  } catch (e) { error.value = e.message; }
  finally { loading.value = false; }
}

watch(query, () => {
  clearTimeout(timer); ++sequence; next.value = null; records.value = [];
  timer = setTimeout(() => loadRecords(true), 300);
});
watch(() => props.selectedDoctype, async value => {
  if (value && types.value.includes(value) && value !== doctype.value) {
    doctype.value = value;
    await loadInitialGroup();
  }
});
onMounted(async () => {
  try {
    types.value = await coreApi("api.business_types");
    doctype.value = types.value.includes(props.selectedDoctype) ? props.selectedDoctype : types.value[0] || "";
    if (doctype.value) await loadInitialGroup();
  } catch (e) { error.value = e.message; }
});
useRealtimeRefresh(["Relay Message", "Contact", "Relay Conversation Summary"], ["messages", "incoming", "contacts", "reports"], () => loadRecords(true));
onBeforeUnmount(() => { clearTimeout(timer); ++sequence; });
const moreSentinel = useLoadMore({ loading, hasMore: () => next.value !== null, error, load: () => loadRecords(false) })
</script>

<template>
  <div class="directory-heading">
    <div class="directory-identity"><span class="directory-self-avatar" aria-hidden="true"><FeatherIcon name="message-circle" class="h-4 w-4" /></span><h2>Chats</h2></div>
    <button type="button" class="directory-heading-action" aria-label="Filter business chats" title="Filter business chats"
      :aria-expanded="filtersOpen" @click="filtersOpen = !filtersOpen"><FeatherIcon name="filter" class="h-4 w-4" /></button>
  </div>
  <ErrorMessage class="px-4" :message="error" />
  <div class="business-directory-controls">
    <div class="business-search-row"><TextInput type="search" v-model="query" placeholder="Search or start a business chat"
      aria-label="Search businesses" :disabled="!doctype"><template #prefix><FeatherIcon name="search" class="h-4 w-4 text-ink-gray-5" /></template></TextInput></div>
    <div v-if="filtersOpen" class="business-directory-filters">
      <ChoiceField v-if="types.length > 1" :field="{ label: 'Business type', options: types, readOnly: busy || loading }" v-model="doctype" @update:model-value="loadInitialGroup" />
      <RemoteLinkField v-if="groupField" :key="doctype + ':' + groupField" v-model="group"
        :field="{ label: 'Business team', method: 'business_groups.directory', params: { doctype, include_all: 1 }, placeholder: 'Search teams…', readOnly: busy || loading }"
        @update:model-value="loadRecords(true)" />
      <div v-if="groupField && records.length" class="business-group-owner">
        <span>{{ owner ? 'Handled by ' + linkedTitle('User', owner, 'Team member') : "Unclaimed group" }}</span>
        <button v-if="!owner" :disabled="loading" @click="claim()">Take group</button>
        <button v-else-if="owner === user" :disabled="loading" @click="claim(true)">Release</button>
      </div>
    </div>
  </div>
  <VirtualScroller :items="records" :item-size="72" class="directory-rows" aria-label="Businesses"
    :pt="{ content: { class: 'directory-virtual-content' } }" @scroll.passive="scrolled">
    <template #item="{ item: record }">
      <button :key="record.name" class="directory-contact relative" :class="{ selected: selected === record.name }"
        @click="emit('select', doctype, record)">
        <span class="business-avatar" aria-hidden="true">{{ recordTitle(record, 'Business').slice(0, 1).toUpperCase() }}</span>
        <span class="directory-contact-copy">
          <span class="directory-contact-top"><strong>{{ recordTitle(record, 'Business') }}</strong><time v-if="record.last_activity">{{ timeLabel(record.last_activity) }}</time></span>
          <span class="directory-contact-bottom"><small>{{ record.last_message || record.summary || record.description || "No WhatsApp messages yet" }}</small><span v-if="record.unread" class="directory-unread">{{ record.unread > 99 ? "99+" : record.unread }}</span></span>
        </span>
      <span v-if="record === records.at(-1) && next !== null" ref="moreSentinel" class="absolute bottom-0 left-0 w-full h-px" aria-hidden="true" /></button>
    </template>
  </VirtualScroller>
  <div class="directory-loading-slot">
    <div v-if="loading" role="status" aria-label="Loading businesses" class="directory-skeletons">
      <span v-for="index in 3" :key="index" class="directory-skeleton" />
    </div>
    <p v-else-if="!records.length" class="p-4 text-sm text-ink-gray-5">
      {{ types.length ? "No businesses match this view." : "No business type is configured." }}
    </p>
  </div>
</template>
