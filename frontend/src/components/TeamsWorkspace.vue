<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { Badge, Button, ErrorMessage, FeatherIcon, TextInput } from "@relay/ui";
import VirtualScroller from "primevue/virtualscroller";
import RelaySelect from "./RelaySelect.vue";
import { coreApi } from "../services/coreApi";
import { useRealtimeRefresh } from "../composables/useRealtimeRefresh";

const types = ref([]);
const doctype = ref("");
const groupingField = ref("");
const groups = ref([]);
const groupNext = ref(null);
const groupQuery = ref("");
const selected = ref(null);
const records = ref([]);
const recordNext = ref(null);
const recordQuery = ref("");
const owner = ref("");
const user = ref("");
const busy = ref(false);
const error = ref("");
let groupTimer;
let recordTimer;
let generation = 0;
let initialized = false;

const visibleUnread = computed(() => records.value.reduce((total, row) => total + Number(row.unread || 0), 0));

async function guarded(action) {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  try { await action(); } catch (exception) { error.value = exception.message; }
  finally { busy.value = false; }
}

async function loadGroups(append = false) {
  const ticket = append ? generation : ++generation;
  const result = await coreApi("business_groups.directory", {
    doctype: doctype.value,
    query: groupQuery.value,
    after: append ? groupNext.value : undefined,
  });
  if (ticket !== generation) return;
  groupingField.value = result.field || "";
  groups.value = append ? [...groups.value, ...(result.items || [])] : result.items || [];
  groupNext.value = result.next;
  if (!append && selected.value && !groups.value.some((row) => row.value === selected.value.value)) clearSelection();
}

async function loadRecords(append = false) {
  if (!selected.value) return;
  const result = await coreApi("business_groups.records", {
    doctype: doctype.value,
    group: selected.value.value,
    query: recordQuery.value,
    start: append ? recordNext.value || 0 : 0,
  });
  const known = new Set(records.value.map((row) => row.name));
  records.value = append ? [...records.value, ...result.items.filter((row) => !known.has(row.name))] : result.items || [];
  recordNext.value = result.next;
  owner.value = result.assigned_to || "";
  user.value = result.user || "";
}

function choose(group) {
  selected.value = group;
  recordQuery.value = "";
  records.value = [];
  recordNext.value = null;
  history.replaceState(null, "", `#/teams?business_doctype=${encodeURIComponent(doctype.value)}&group=${encodeURIComponent(group.value)}`);
  guarded(() => loadRecords());
}
function clearSelection() {
  selected.value = null;
  records.value = [];
  owner.value = "";
  history.replaceState(null, "", "#/teams");
}
async function claim(release = false) {
  await guarded(async () => {
    const result = await coreApi("business_groups.claim", { doctype: doctype.value, group: selected.value.value, release }, true);
    owner.value = result.assigned_to || "";
  });
}
function groupScrolled(event) {
  const node = event.currentTarget;
  if (groupNext.value && !busy.value && node.scrollHeight - node.scrollTop - node.clientHeight < 160) guarded(() => loadGroups(true));
}
function recordScrolled(event) {
  const node = event.currentTarget;
  if (recordNext.value !== null && !busy.value && node.scrollHeight - node.scrollTop - node.clientHeight < 160) guarded(() => loadRecords(true));
}
function openRecord(record) {
  location.hash = `#/messages?business_doctype=${encodeURIComponent(doctype.value)}&business_name=${encodeURIComponent(record.name)}`;
}
watch(groupQuery, () => { clearTimeout(groupTimer); groupTimer = setTimeout(() => guarded(() => loadGroups()), 300); });
watch(recordQuery, () => { clearTimeout(recordTimer); recordTimer = setTimeout(() => guarded(() => loadRecords()), 300); });
watch(doctype, () => {
  if (!initialized) return;
  guarded(async () => { clearSelection(); groupQuery.value = ""; await loadGroups(); });
});
useRealtimeRefresh(["Relay Message", "Relay Conversation Summary"], ["messages", "summaries"], () => {
  if (selected.value && !busy.value) return loadRecords();
});
onMounted(() => guarded(async () => {
  types.value = await coreApi("api.business_types");
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  doctype.value = types.value.includes(params.get("business_doctype")) ? params.get("business_doctype") : types.value[0] || "";
  if (doctype.value) {
    await loadGroups();
    const routed = params.get("group");
    const match = groups.value.find((row) => row.value === routed);
    if (match) choose(match);
  }
  initialized = true;
}));
onBeforeUnmount(() => { ++generation; clearTimeout(groupTimer); clearTimeout(recordTimer); });
</script>

<template>
  <section class="team-workspace" :class="{ 'has-selection': selected }" aria-label="Business teams">
    <aside class="team-groups">
      <header><div><h2>Teams</h2><p v-if="groupingField">Grouped by {{ groupingField }}</p><p v-else>Business responsibility groups</p></div></header>
      <div class="team-filters">
        <RelaySelect v-if="types.length > 1" label="Business type" v-model="doctype" :options="types" :disabled="busy" />
        <TextInput v-model="groupQuery" type="search" placeholder="Search teams" aria-label="Search teams"><template #prefix><FeatherIcon name="search" class="h-4 w-4 text-ink-gray-5" /></template></TextInput>
      </div>
      <ErrorMessage :message="error" />
      <VirtualScroller :items="groups" :item-size="58" class="team-group-list" @scroll.passive="groupScrolled">
        <template #item="{ item }"><button type="button" :class="{ active: selected?.value === item.value }" @click="choose(item)"><span class="team-avatar">{{ (item.label || 'U').slice(0, 1).toUpperCase() }}</span><span><strong>{{ item.label }}</strong><small>{{ groupingField || "All accessible records" }}</small></span><FeatherIcon name="chevron-right" class="h-4 w-4" /></button></template>
      </VirtualScroller>
      <p v-if="busy" class="team-loading" role="status">Loading…</p>
    </aside>

    <main v-if="selected" class="team-records">
      <header class="team-heading"><Button class="mobile-only" icon="arrow-left" aria-label="Back to teams" @click="clearSelection" /><span class="team-avatar large">{{ selected.label.slice(0, 1).toUpperCase() }}</span><div><h2>{{ selected.label }}</h2><p>{{ records.length }} loaded · {{ visibleUnread }} unread in this view</p></div><Badge :label="owner ? `Handled by ${owner}` : 'Unclaimed'" :theme="owner ? 'blue' : 'gray'" /><Button v-if="!owner" label="Take team" variant="solid" :disabled="busy" @click="claim()" /><Button v-else-if="owner === user" label="Release" :disabled="busy" @click="claim(true)" /></header>
      <div class="team-record-search"><TextInput v-model="recordQuery" type="search" placeholder="Search records, contacts, or mobile numbers" aria-label="Search team business records"><template #prefix><FeatherIcon name="search" class="h-4 w-4 text-ink-gray-5" /></template></TextInput></div>
      <VirtualScroller :items="records" :item-size="76" class="team-record-list" @scroll.passive="recordScrolled">
        <template #item="{ item }"><button type="button" @click="openRecord(item)"><span class="team-avatar">{{ item.label.slice(0, 1).toUpperCase() }}</span><span class="team-record-copy"><span><strong>{{ item.label }}</strong><time v-if="item.last_activity">{{ item.last_activity }}</time></span><small>{{ item.summary || item.last_message || item.description || "No WhatsApp activity yet" }}</small></span><Badge v-if="item.unread" :label="String(item.unread)" theme="blue" /><FeatherIcon name="chevron-right" class="h-4 w-4 text-ink-gray-4" /></button></template>
      </VirtualScroller>
      <p v-if="!records.length && !busy" class="team-empty">No accessible business records match this team.</p>
    </main>
    <div v-else class="team-welcome"><span class="team-avatar large"><FeatherIcon name="users" class="h-5 w-5" /></span><h2>Choose a team</h2><p>Teams come directly from the configured grouping field. They do not create duplicate business records.</p></div>
  </section>
</template>
