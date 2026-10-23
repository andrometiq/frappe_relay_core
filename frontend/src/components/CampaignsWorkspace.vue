<script setup>
import { useRealtimeRefresh } from "../composables/useRealtimeRefresh";
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { Badge, Button, ErrorMessage, FeatherIcon, FormControl, TextInput } from "@relay/ui";
import BusinessRecordPicker from "./BusinessRecordPicker.vue";
import CampaignCsvImport from "./CampaignCsvImport.vue";
import FrappeFormSection from "./frappe/FrappeFormSection.vue";
import FrappeFormView from "./frappe/FrappeFormView.vue";
import FrappeListView from "./frappe/FrappeListView.vue";
import FrappeReadField from "./frappe/FrappeReadField.vue";
import RelaySelect from "./RelaySelect.vue";
import { coreApi } from "../services/coreApi";
import { stableSubmission } from "../services/submission";
import {
  buildTemplateComponents,
  templateParameterDescriptors,
  templatePreview,
} from "../services/templateParameters";

const list = ref([]);
const next = ref(null);
const selected = ref(null);
const creating = ref(false);
const busy = ref(false);
const loadingMore = ref(false);
const csvImporting = ref(false);
const error = ref("");
const channels = ref([]);
const listQuery = ref("");
const listStatus = ref("");
const activeTab = ref("Details");

const title = ref("");
const channel = ref("");
const businessType = ref("");
const businessName = ref("");
const operation = ref("templates.send");
const body = ref("");
const templates = ref([]);
const templateId = ref("");
const parameters = ref({});

const contacts = ref([]);
const chosen = ref([]);
const contactCursor = ref(null);
const moreContacts = ref(false);
const ledgerStatus = ref("");
const detailCursor = ref(null);

let listTimer;
let ledgerTimer;
let restoreHandler;
let listGeneration = 0;

const columns = [
  { key: "title", label: "Campaign", width: "minmax(240px,1.5fr)" },
  { key: "status", label: "Status", width: "130px" },
  { key: "creation", label: "Created", width: "190px" },
  { key: "name", label: "ID", width: "190px" },
];
const statuses = [
  { value: "", label: "All statuses" },
  "Draft", "Running", "Paused", "Cancelling", "Completed", "Cancelled",
];
const recipientStatuses = [
  { value: "", label: "All statuses" },
  "Pending", "Dispatching", "Queued", "Submitted", "Rejected", "Uncertain", "Cancelled",
];
const template = computed(() => templates.value.find((row) => row.id === templateId.value));
const variables = computed(() => templateParameterDescriptors(template.value));
const templateBody = computed(() => templatePreview(template.value, variables.value, parameters.value));
const selectedCount = computed(() => Object.values(selected.value?.counts || {}).reduce((sum, value) => sum + Number(value || 0), 0));
const documentTabs = computed(() => selected.value?.status === "Draft" ? ["Details", "Audience", "Recipients"] : ["Details", "Recipients"]);

const statusTheme = (value) => ({
  Draft: "gray", Running: "blue", Paused: "orange", Cancelling: "orange",
  Completed: "green", Cancelled: "red", Submitted: "green", Rejected: "red",
  Uncertain: "orange", Queued: "blue", Dispatching: "blue", Pending: "gray",
})[value] || "gray";
const formatDate = (value) => value ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(String(value).replace(" ", "T"))) : "—";

async function run(action) {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  try { await action(); }
  catch (exception) { error.value = exception.message; }
  finally { busy.value = false; }
}

async function load(after = null) {
  const generation = after ? listGeneration : ++listGeneration;
  if (after) loadingMore.value = true;
  try {
    const result = await coreApi("campaigns.directory", {
      after: after || undefined,
      query: listQuery.value || undefined,
      status: listStatus.value || undefined,
    });
    if (generation !== listGeneration) return;
    const known = new Set(list.value.map((row) => row.name));
    list.value = after ? [...list.value, ...result.items.filter((row) => !known.has(row.name))] : result.items;
    next.value = result.next;
  } finally { loadingMore.value = false; }
}

function route(name = "") {
  history.pushState(null, "", `#/campaigns${name ? `?campaign=${encodeURIComponent(name)}` : ""}`);
}

async function open(name, after = null, append = false, updateRoute = true) {
  detailCursor.value = after || null;
  const result = await coreApi("campaigns.read", { name, after: after || undefined, status: ledgerStatus.value || undefined });
  selected.value = append && selected.value?.name === name
    ? { ...result, recipients: [...selected.value.recipients, ...result.recipients.filter((row) => !selected.value.recipients.some((current) => current.name === row.name))] }
    : result;
  creating.value = false;
  if (!append) {
    activeTab.value = "Details";
    if (updateRoute) route(name);
  }
}

function openList(updateRoute = true) {
  selected.value = null;
  creating.value = false;
  contacts.value = [];
  chosen.value = [];
  ledgerStatus.value = "";
  if (updateRoute) route();
}

function newCampaign(updateRoute = true) {
  selected.value = null;
  creating.value = true;
  title.value = "";
  businessName.value = "";
  operation.value = "templates.send";
  body.value = "";
  templateId.value = "";
  parameters.value = {};
  error.value = "";
  if (updateRoute) route("new");
}

async function restoreRoute() {
  const name = new URLSearchParams(location.hash.split("?")[1] || "").get("campaign") || "";
  if (name === "new") { newCampaign(false); return; }
  if (name && selected.value?.name !== name) await run(() => open(name, null, false, false));
  else if (!name && (selected.value || creating.value)) openList(false);
}

async function searchContacts(after = null) {
  if (!selected.value) return;
  const result = await coreApi("whatsapp.business_contacts", {
    doctype: selected.value.business_doctype,
    name: selected.value.business_name,
    after: after || undefined,
  });
  contacts.value = after
    ? [...contacts.value, ...result.contacts.filter((row) => !contacts.value.some((current) => current.name === row.name))]
    : result.contacts;
  moreContacts.value = result.has_more;
  contactCursor.value = result.contacts.at(-1)?.name;
  if (!after) chosen.value = [];
}

function loadMoreCampaigns() {
  if (next.value && !busy.value && !loadingMore.value) run(() => load(next.value));
}
function contactScrolled(event) {
  const node = event.currentTarget;
  if (moreContacts.value && !busy.value && node.scrollHeight - node.scrollTop - node.clientHeight < 100)
    run(() => searchContacts(contactCursor.value));
}
function ledgerScrolled(event) {
  const node = event.currentTarget;
  if (selected.value?.next && !busy.value && node.scrollHeight - node.scrollTop - node.clientHeight < 100)
    run(() => open(selected.value.name, selected.value.next, true, false));
}
function changeTab(tab) {
  activeTab.value = tab;
  if (tab === "Audience" && selected.value?.status === "Draft" && !contacts.value.length)
    run(() => searchContacts());
}

async function create() {
  await run(async () => {
    let args;
    if (operation.value === "messages.send") args = { body: body.value };
    else {
      if (!template.value) throw Error("Select an approved template");
      args = { name: template.value.name, language: template.value.language, components: buildTemplateComponents(variables.value, parameters.value) };
    }
    const payload = {
      title: title.value, channel: channel.value, business_doctype: businessType.value,
      business_name: businessName.value, operation: operation.value, arguments: args,
    };
    const result = await stableSubmission("relay-campaign", payload, (key) => coreApi("campaigns.create", { ...payload, request_key: key }, true));
    await open(result.name);
    await Promise.all([searchContacts(), load()]);
  });
}

async function add() {
  await run(async () => {
    selected.value = await coreApi("campaigns.add_recipients", { name: selected.value.name, contacts: chosen.value }, true);
    chosen.value = [];
  });
}

async function control(action) {
  if (csvImporting.value) { error.value = "Finish importing recipients before changing delivery"; return; }
  await run(async () => {
    selected.value = await coreApi("campaigns.control", { name: selected.value.name, action }, true);
    await load();
  });
}

async function approvedTemplates() {
  await run(async () => {
    const result = await coreApi("whatsapp.execute", { operation: "templates.list" }, true);
    templates.value = (result.data || []).filter((row) => row.status === "APPROVED");
    templateId.value = "";
    parameters.value = {};
  });
}

async function refreshDelivery() {
  await run(async () => { selected.value = await coreApi("campaigns.refresh", { name: selected.value.name }, true); });
}

watch([listQuery, listStatus], () => {
  clearTimeout(listTimer);
  listTimer = setTimeout(() => run(() => load()), 300);
});
watch(ledgerStatus, () => {
  clearTimeout(ledgerTimer);
  ledgerTimer = setTimeout(() => { if (selected.value) run(() => open(selected.value.name, null, false, false)); }, 250);
});

useRealtimeRefresh(["Relay Campaign", "Relay Campaign Recipient"], ["campaigns"], async () => {
  if (busy.value || csvImporting.value || creating.value) return;
  await load();
  if (selected.value) await open(selected.value.name, null, false, false);
});

onMounted(async () => {
  await run(async () => {
    await load();
    channels.value = await coreApi("campaigns.channels");
    channel.value = channels.value[0]?.name || "";
  });
  await restoreRoute();
  restoreHandler = () => restoreRoute();
  window.addEventListener("popstate", restoreHandler);
});
onBeforeUnmount(() => {
  clearTimeout(listTimer);
  clearTimeout(ledgerTimer);
  ++listGeneration;
  if (restoreHandler) window.removeEventListener("popstate", restoreHandler);
});
</script>

<template>
  <section class="campaign-workspace">
    <ErrorMessage class="campaign-global-error" :message="error" />

    <FrappeFormView v-if="creating" title="New campaign" :breadcrumbs="['Bulk messaging', 'New campaign']" :tabs="['Setup']" active-tab="Setup" @back="openList">
      <template #actions>
        <Button label="Cancel" @click="openList" />
        <Button label="Save draft" variant="solid" :loading="busy" :disabled="busy || !title.trim() || !channel || !businessName" @click="create" />
      </template>
      <FrappeFormSection title="Campaign setup" description="Choose the business record and WhatsApp content for this audience.">
        <div class="frappe-field-grid campaign-form-grid">
          <FormControl label="Campaign title" v-model="title" required />
          <div class="campaign-channel">
            <span class="team-avatar"><FeatherIcon name="message-circle" class="h-4 w-4" /></span>
            <span><strong>WhatsApp</strong><small>{{ channels[0]?.account || "No enabled account" }}</small></span>
          </div>
          <div class="campaign-business-picker frappe-grid-wide">
            <BusinessRecordPicker v-model:doctype="businessType" v-model:record="businessName" :disabled="busy || csvImporting" />
          </div>
          <RelaySelect label="Content" v-model="operation" :options="[
            { value: 'templates.send', label: 'Approved template' },
            { value: 'messages.send', label: 'Text in an open service window' },
          ]" />
          <FormControl v-if="operation !== 'templates.send'" label="Message" type="textarea" rows="5" v-model="body" class="frappe-grid-wide" />
          <template v-else>
            <div class="campaign-template-picker frappe-grid-wide">
              <Button label="Load approved templates" :disabled="busy || !channel" @click="approvedTemplates" />
              <RelaySelect label="Template" v-model="templateId" :options="templates.map((row) => ({ value: row.id, label: `${row.name} · ${row.language}` }))" />
            </div>
            <FormControl v-for="field in variables" :key="field.key" :label="field.label + (field.kind === 'media' ? ' (public URL or media ID)' : '')" v-model="parameters[field.key]" />
          </template>
        </div>
      </FrappeFormSection>
      <template #sidebar>
        <section class="campaign-side-card">
          <h3>Message preview</h3>
          <div class="template-phone-preview"><div class="template-preview-bubble"><p>{{ templateBody || body || "Your WhatsApp message appears here." }}</p><time>12:00</time></div></div>
        </section>
        <section v-if="!channels.length" class="campaign-side-note">
          <strong>WhatsApp is not connected</strong><p>Enable the account in Relay Channel before saving a campaign.</p><a href="/desk/relay-channel">Open Relay Channel</a>
        </section>
      </template>
    </FrappeFormView>

    <FrappeFormView v-else-if="selected" :title="selected.title" :breadcrumbs="['Bulk messaging', selected.title]" :status="selected.status" :status-theme="statusTheme(selected.status)" :tabs="documentTabs" :active-tab="activeTab" @update:active-tab="changeTab" @back="openList">
      <template #actions>
        <Button v-if="selected.status === 'Draft'" label="Start" variant="solid" :disabled="busy || !selectedCount" @click="control('start')" />
        <Button v-if="selected.status === 'Running'" label="Pause" :disabled="busy || csvImporting" @click="control('pause')" />
        <Button v-if="selected.status === 'Paused'" label="Resume" variant="solid" :disabled="busy || csvImporting" @click="control('resume')" />
        <Button icon="refresh-cw" variant="ghost" aria-label="Refresh delivery states" :disabled="busy || csvImporting" @click="refreshDelivery" />
        <Button v-if="!['Completed', 'Cancelled'].includes(selected.status)" label="Cancel" theme="red" :disabled="busy || csvImporting" @click="control('cancel')" />
      </template>

      <template v-if="activeTab === 'Details'">
        <FrappeFormSection>
          <div class="frappe-field-grid">
            <FrappeReadField label="Campaign ID" :value="selected.name" />
            <FrappeReadField label="Status" :value="selected.status" />
            <FrappeReadField label="Business type" :value="selected.business_doctype" />
            <FrappeReadField label="Business record" :value="selected.business_name" />
            <FrappeReadField label="Channel" value="WhatsApp" />
            <FrappeReadField label="Content type" :value="selected.operation === 'templates.send' ? 'Approved template' : 'Service-window message'" />
          </div>
        </FrappeFormSection>
        <FrappeFormSection title="Message content">
          <div class="frappe-field-grid">
            <FrappeReadField v-if="selected.arguments.name" label="Template" :value="selected.arguments.name" />
            <FrappeReadField v-if="selected.arguments.language" label="Language" :value="selected.arguments.language" />
            <FrappeReadField label="Message" :value="selected.arguments.body || selected.arguments.name" wide multiline />
          </div>
        </FrappeFormSection>
      </template>

      <FrappeFormSection v-else-if="activeTab === 'Audience'" title="Campaign audience" description="Only contacts linked to this business record can be added.">
        <CampaignCsvImport :key="selected.name" :campaign="selected" :contacts="contacts" @busy="csvImporting = $event" @imported="run(() => open(selected.name, null, false, false))" />
        <div class="campaign-contact-toolbar">
          <div><strong>Linked contacts</strong><small>{{ contacts.length }} loaded</small></div>
          <Button :label="`Add selected (${chosen.length})`" variant="solid" :disabled="busy || !chosen.length" @click="add" />
        </div>
        <div class="campaign-contact-list" @scroll.passive="contactScrolled">
          <label v-for="person in contacts" :key="person.name"><input type="checkbox" :value="person.name" v-model="chosen" /><span><strong>{{ person.full_name || person.name }}</strong><small>{{ person.mobile_no || "No WhatsApp number" }}</small></span></label>
          <p v-if="!contacts.length && !busy" class="campaign-inline-empty">No linked WhatsApp contacts are available.</p>
        </div>
      </FrappeFormSection>

      <FrappeFormSection v-else title="Recipient ledger" description="Delivery state changes arrive through Relay realtime events.">
        <div class="campaign-ledger-heading"><RelaySelect label="Status" v-model="ledgerStatus" :options="recipientStatuses" /></div>
        <div class="campaign-ledger" @scroll.passive="ledgerScrolled">
          <article v-for="row in selected.recipients" :key="row.name"><div><strong>{{ row.contact }}</strong><small>{{ row.reason || row.provider_id || "Awaiting delivery" }}</small></div><Badge :label="row.delivery_status || row.status" :theme="statusTheme(row.delivery_status || row.status)" /></article>
          <p v-if="!selected.recipients.length" class="campaign-inline-empty">No recipients match this status.</p>
        </div>
      </FrappeFormSection>

      <template #sidebar>
        <section class="campaign-side-card"><h3>Delivery summary</h3><dl class="campaign-counts"><div v-for="(count, status) in selected.counts" :key="status"><dt>{{ status }}</dt><dd>{{ count }}</dd></div><div><dt>Total</dt><dd>{{ selectedCount }}</dd></div></dl></section>
        <section class="campaign-side-note"><strong>Delivery control</strong><p>Pausing stops new admissions. Messages already submitted to Meta cannot be recalled.</p></section>
        <ErrorMessage :message="selected.last_error" />
      </template>
    </FrappeFormView>

    <FrappeListView v-else title="Bulk messaging" description="Create WhatsApp campaigns for contacts linked to a business record." label="WhatsApp campaigns" :columns="columns" :items="list" :busy="busy" :loading-more="loadingMore" empty-title="No campaigns found" empty-description="Create a campaign or change the search filters." @open="(row) => run(() => open(row.name))" @near-end="loadMoreCampaigns">
      <template #actions><Button label="New campaign" icon-left="plus" variant="solid" :disabled="busy || csvImporting" @click="newCampaign" /></template>
      <template #filters>
        <TextInput v-model="listQuery" type="search" placeholder="Search campaigns" aria-label="Search campaigns"><template #prefix><FeatherIcon name="search" /></template></TextInput>
        <RelaySelect v-model="listStatus" label="Status" :options="statuses" />
      </template>
      <template #cell-title="{ item }"><strong>{{ item.title }}</strong><small>{{ item.name }}</small></template>
      <template #cell-status="{ item }"><Badge :label="item.status" :theme="statusTheme(item.status)" /></template>
      <template #cell-creation="{ item }">{{ formatDate(item.creation) }}</template>
      <template #footer><span>{{ list.length }} campaigns loaded</span><span v-if="next">More campaigns load as you scroll</span></template>
    </FrappeListView>
  </section>
</template>

<style scoped>
.campaign-workspace{position:relative;display:flex;height:100%;min-height:0;flex:1;flex-direction:column;background:var(--surface-white)}
.campaign-global-error{position:absolute;top:8px;left:50%;z-index:30;width:min(540px,calc(100% - 24px));transform:translateX(-50%)}
.campaign-form-grid{align-items:start}.campaign-business-picker :deep(.space-y-3){display:grid;grid-template-columns:1fr 1fr;gap:18px 30px}.campaign-business-picker :deep(.space-y-3>* ){margin:0}
.campaign-channel{display:flex;min-height:55px;align-items:center;gap:10px;border-radius:7px;background:var(--surface-gray-2);padding:8px 10px}.campaign-channel strong,.campaign-channel small{display:block}.campaign-channel strong{font-size:13px}.campaign-channel small{margin-top:2px;color:var(--ink-gray-5);font-size:10px}
.campaign-template-picker{display:grid;grid-template-columns:auto minmax(220px,1fr);align-items:end;gap:12px}.campaign-template-picker>.space-y-1\.5{margin:0}
.campaign-side-card>h3,.campaign-side-note>strong{display:block;margin-bottom:10px;color:var(--ink-gray-8);font-size:13px;font-weight:600}.campaign-side-note{margin-top:14px;border-radius:7px;background:var(--surface-gray-2);padding:12px}.campaign-side-note p{color:var(--ink-gray-6);font-size:11px;line-height:1.55}.campaign-side-note a{display:inline-block;margin-top:8px;color:var(--ink-blue-2);font-size:11px}
.campaign-counts{display:grid;gap:2px}.campaign-counts>div{display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--outline-gray-2);padding:8px 1px;color:var(--ink-gray-6);font-size:11px}.campaign-counts>div:last-child{border-bottom:0;color:var(--ink-gray-9);font-weight:600}.campaign-counts dd{color:var(--ink-gray-9);font-size:13px;font-weight:600}
.campaign-contact-toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:18px 0 8px}.campaign-contact-toolbar strong,.campaign-contact-toolbar small{display:block}.campaign-contact-toolbar strong{font-size:13px}.campaign-contact-toolbar small{margin-top:2px;color:var(--ink-gray-5);font-size:10px}
.campaign-contact-list,.campaign-ledger{max-height:420px;overflow:auto;border:1px solid var(--outline-gray-2);border-radius:7px}.campaign-contact-list label{display:flex;align-items:center;gap:11px;min-height:52px;border-bottom:1px solid var(--outline-gray-2);padding:8px 12px;font-size:12px}.campaign-contact-list label:last-of-type{border-bottom:0}.campaign-contact-list label:hover{background:var(--surface-gray-1)}.campaign-contact-list input{accent-color:var(--ink-blue-2)}.campaign-contact-list strong,.campaign-contact-list small{display:block}.campaign-contact-list small{margin-top:3px;color:var(--ink-gray-5);font-size:10px}
.campaign-ledger-heading{display:flex;justify-content:flex-end;margin-bottom:10px}.campaign-ledger-heading>.space-y-1\.5{width:210px}.campaign-ledger article{display:flex;min-height:56px;align-items:center;justify-content:space-between;gap:12px;border-bottom:1px solid var(--outline-gray-2);padding:9px 12px}.campaign-ledger article:last-of-type{border-bottom:0}.campaign-ledger strong,.campaign-ledger small{display:block}.campaign-ledger strong{font-size:12px}.campaign-ledger small{margin-top:3px;color:var(--ink-gray-5);font-size:10px}.campaign-inline-empty{padding:28px;color:var(--ink-gray-5);font-size:12px;text-align:center}
@media(max-width:650px){.campaign-business-picker :deep(.space-y-3){grid-template-columns:1fr;gap:14px}.campaign-template-picker{grid-template-columns:1fr}.campaign-contact-toolbar{align-items:flex-start;flex-direction:column}.campaign-ledger-heading>.space-y-1\.5{width:100%}}
</style>
