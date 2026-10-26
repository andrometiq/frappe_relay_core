<script setup>
import { computed, inject, onBeforeUnmount, onMounted, ref } from "vue";
import { Badge, Button, ErrorMessage, FormControl, TextInput } from "@relay/ui";
import FrappeFormSection from "./frappe/FrappeFormSection.vue";
import FrappeFormView from "./frappe/FrappeFormView.vue";
import FrappeListView from "./frappe/FrappeListView.vue";
import FrappeReadField from "./frappe/FrappeReadField.vue";
import RelaySelect from "./RelaySelect.vue";
import { useCampaigns } from "../composables/useCampaigns";
import { closeRoute, openRoute } from "../useViewRoute";
import { channelFeature } from "../services/enabledChannels";
import { COUNTERS, campaignActions, campaignMessage, messageLabel, messageTypes, missingMapping, percent, placeholders,
  statusTheme, windowNotice } from "../services/campaignProgress";

const capabilities = inject("relayCapabilities");
const workspace = useCampaigns();
const { busy, error, items, campaign, sheet, templates, filter, replyWindow } = workspace;
const creating = ref(false), title = ref(""), type = ref("template"), template = ref(""), text = ref(""), mapping = ref(null);
const mediaFile = ref("");
const columns = [
  { key: "title", label: "Campaign", width: "minmax(200px,1.4fr)" },
  { key: "status", label: "Status", width: "120px" },
  { key: "template_name", label: "Message", width: "minmax(140px,1fr)" },
  { key: "progress", label: "Sent / replied", width: "140px" },
];
const templateOptions = computed(() => templates.value.map((row) => ({ value: `${row.name}|${row.language}`, label: `${row.name} (${row.language})` })));
const columnOptions = (field) => [{ value: "", label: field.component === "media" ? "One file or link for every row" : "Fixed value" },
  ...(sheet.value?.columns || [])];
const missing = computed(() => sheet.value && mapping.value ? missingMapping(sheet.value.fields, mapping.value) : []);
const counts = computed(() => campaign.value?.counts || {});
const media = (kind) => channelFeature(capabilities.value, "WhatsApp", "media." + kind);
const types = computed(() => messageTypes(["photo", "video", "document"].filter(media)));
const columnsUsed = computed(() => placeholders(text.value));
const ready = computed(() => title.value.trim().length >= 3 && (type.value === "template" ? template.value : type.value !== "text" || text.value.trim()));
const labels = { start: "Start sending", pause: "Pause", resume: "Resume", cancel: "Cancel campaign" };

const listRoute = "#/whatsapp?tab=campaigns";
function routeCampaign(name) {
  openRoute(`${listRoute}&campaign=${encodeURIComponent(name)}`, !!(campaign.value || creating.value));
}
function openCampaign(name) { routeCampaign(name); workspace.open(name); }
function startCreate(updateRoute = true) {
  if (updateRoute) routeCampaign("new");
  creating.value = true; title.value = ""; type.value = "template"; template.value = ""; text.value = "";
  workspace.loadTemplates();
}
async function create() {
  const [template_name, language] = template.value.split("|");
  const values = type.value === "template" ? { template_name, language } : { message: campaignMessage(type.value, text.value) };
  if (await workspace.create({ title: title.value, ...values })) { routeCampaign(campaign.value.name); creating.value = false; }
}
async function chooseFile(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  await workspace.upload(file);
  if (sheet.value) mapping.value = { phone: sheet.value.mapping.phone, fields: { ...sheet.value.mapping.fields }, fixed: {} };
  mediaFile.value = "";
  event.target.value = "";
}
function setColumn(key, column) {
  const fields = { ...mapping.value.fields };
  if (column) fields[key] = column; else delete fields[key];
  mapping.value = { ...mapping.value, fields };
}
async function chooseMedia(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  const fileUrl = await workspace.uploadMedia(file);
  if (fileUrl) { mapping.value.fixed.media_url = fileUrl; mediaFile.value = file.name; }
  event.target.value = "";
}
function showList() { creating.value = false; campaign.value = null; sheet.value = null; workspace.refresh(); }
function back() { closeRoute(listRoute); showList(); }
async function readRoute() {
  if (location.hash.split("?")[0] !== "#/whatsapp") return;
  const name = new URLSearchParams(location.hash.split("?")[1] || "").get("campaign");
  if (!name) { if (campaign.value || creating.value) showList(); return; }
  if (name === "new") { if (!creating.value) startCreate(false); return; }
  if (name === campaign.value?.name) return;
  creating.value = false;
  await workspace.open(name);
  if (campaign.value?.name !== name) { campaign.value = null; closeRoute(listRoute); }
}
onMounted(() => { readRoute(); window.addEventListener("popstate", readRoute); });
onBeforeUnmount(() => window.removeEventListener("popstate", readRoute));
</script>

<template>
  <div class="campaign-workspace">
    <div v-if="error" class="v1-template-feedback"><ErrorMessage :message="error" /></div>

    <FrappeFormView v-if="creating" title="New campaign" :breadcrumbs="['Campaigns', 'New']" @back="back">
      <FrappeFormSection description="Send one WhatsApp message to every mobile number in a sheet.">
        <div class="frappe-field-grid">
          <label class="campaign-field"><span>Title</span><TextInput v-model="title" placeholder="Winter launch Oct 2026" /></label>
          <RelaySelect v-model="type" label="Message type" :options="types" />
          <RelaySelect v-if="type === 'template'" v-model="template" label="Approved template" :options="templateOptions" />
        </div>
        <div v-if="type !== 'template'" class="campaign-actions">
          <FormControl v-model="text" type="textarea" :rows="4" :label="type === 'text' ? 'Message' : 'Caption (optional)'"
            :placeholder="'Hi {{Name}}, your order is ready'" />
          <p class="campaign-hint">Write <code v-text="'{{column}}'" /> to fill a value from the sheet column with that name.
            <template v-if="columnsUsed.length">Columns used: {{ columnsUsed.join(", ") }}.</template></p>
          <p class="campaign-issue">WhatsApp delivers text and media only to numbers that messaged you in the last 24 hours. Use a template to reach everyone.</p>
        </div>
        <div class="campaign-actions"><Button label="Create campaign" variant="solid" :loading="busy" :disabled="!ready" @click="create" /></div>
      </FrappeFormSection>
    </FrappeFormView>

    <FrappeFormView v-else-if="campaign" :title="campaign.title" :breadcrumbs="['Campaigns', campaign.title]"
      :status="campaign.status" :status-theme="statusTheme(campaign.status)" @back="back">
      <template #actions>
        <Button v-for="action in campaignActions(campaign.status)" :key="action" :label="labels[action]"
          :variant="action === 'start' || action === 'resume' ? 'solid' : 'subtle'" :theme="action === 'cancel' ? 'red' : 'gray'"
          :loading="busy" :disabled="action === 'start' && !(counts.total > 0)" @click="workspace.control(action)" />
      </template>
      <FrappeFormSection title="Progress">
        <div class="campaign-counters">
          <div v-for="[key, label] in COUNTERS" :key="key"><span>{{ label }}</span><strong>{{ (counts[key] || 0).toLocaleString() }}</strong>
            <small v-if="key !== 'total' && key !== 'skipped' && counts.total">{{ percent(counts[key], counts.total) }}%</small></div>
        </div>
        <p v-if="campaign.last_error" class="campaign-issue" role="alert">{{ campaign.last_error }}</p>
        <p v-if="replyWindow" :class="replyWindow.closed ? 'campaign-issue' : 'campaign-hint'" role="status">{{ windowNotice(replyWindow) }}</p>
      </FrappeFormSection>
      <FrappeFormSection v-if="campaign.status === 'Draft'" title="Recipients file"
        :description="campaign.message ? 'Columns: mobile number, one column per {{column}} in the message, and the media link if each row sends its own file.' : 'Columns: mobile number, then the template values in order, and the image link if the template has one.'">
        <input type="file" accept=".xlsx,.csv" aria-label="Recipients file" :disabled="busy" @change="chooseFile" />
        <div v-if="sheet && mapping" class="campaign-mapping">
          <RelaySelect v-model="mapping.phone" label="Phone number column" :options="sheet.columns" />
          <div v-for="field in sheet.fields" :key="field.key" class="campaign-map-row">
            <RelaySelect :model-value="mapping.fields[field.key] || ''" :label="field.label" :options="columnOptions(field)" @update:model-value="setColumn(field.key, $event)" />
            <div v-if="!mapping.fields[field.key] && field.component === 'media'" class="campaign-media">
              <input type="file" :accept="(media(campaign.message.kind) || []).join(',')" :aria-label="`${field.label} file`" :disabled="busy" @change="chooseMedia" />
              <small>{{ mediaFile || "Upload one file for every row, or paste an HTTPS link." }}</small>
              <TextInput v-model="mapping.fixed[field.key]" placeholder="https://…" :aria-label="`${field.label} fixed value`" />
            </div>
            <TextInput v-else-if="!mapping.fields[field.key]" v-model="mapping.fixed[field.key]" :placeholder="field.media ? 'https://…' : 'Same value for every row'" :aria-label="`${field.label} fixed value`" />
          </div>
          <p v-if="missing.length" class="campaign-issue">Still needed: {{ missing.join(", ") }}</p>
          <Button label="Check and import rows" variant="solid" :loading="busy" :disabled="missing.length > 0" @click="workspace.importRows(mapping)" />
        </div>
      </FrappeFormSection>
      <FrappeFormSection v-if="campaign.issues?.length" title="Rows not sent">
        <div class="campaign-issues"><div v-for="row in campaign.issues" :key="row.reason"><span>{{ row.reason }}</span><strong>{{ row.count }}</strong></div></div>
      </FrappeFormSection>
      <FrappeFormSection title="Recipients" collapsible>
        <RelaySelect v-model="filter" label="Show" :options="[{ value: '', label: 'All rows' }, 'Pending', 'Skipped', 'Sent', 'Delivered', 'Read', 'Failed']" @update:model-value="workspace.page($event)" />
        <div class="campaign-rows" role="table" aria-label="Campaign recipients">
          <div v-for="row in campaign.recipients" :key="row.sheet_row" role="row">
            <span>Row {{ row.sheet_row }}</span><span>+{{ row.destination }}</span><Badge :label="row.replied_at ? 'Replied' : row.status" />
            <small v-if="row.reason">{{ row.reason }}</small>
          </div>
        </div>
        <Button v-if="campaign.next" label="Load more rows" :loading="busy" @click="workspace.page(filter, campaign.next)" />
      </FrappeFormSection>
      <template #sidebar>
        <div class="frappe-field-grid">
          <FrappeReadField v-if="campaign.template_name" label="Template" :value="`${campaign.template_name} (${campaign.language})`" wide />
          <FrappeReadField v-else label="Message" :value="campaign.message?.body || campaign.message?.caption || messageLabel(campaign)" wide />
          <FrappeReadField label="Reply window" :value="`${campaign.reply_window_hours} hours`" wide />
          <FrappeReadField label="Started" :value="campaign.started_at" wide />
        </div>
      </template>
    </FrappeFormView>

    <FrappeListView v-else title="Campaigns" description="Send a WhatsApp template, text or media to many numbers and track replies."
      label="Campaigns" :columns="columns" :items="items" :busy="busy" empty-title="No campaigns yet"
      empty-description="Create a campaign, upload a sheet of numbers and start sending." @open="openCampaign($event.name)">
      <template #actions><Button label="New campaign" icon-left="plus" variant="solid" @click="startCreate" /></template>
      <template #cell-title="{ item }"><strong>{{ item.title }}</strong></template>
      <template #cell-status="{ item }"><Badge :label="item.status" :theme="statusTheme(item.status)" /></template>
      <template #cell-template_name="{ item }">{{ messageLabel(item) }}</template>
      <template #cell-progress="{ item }">{{ item.sent_count || 0 }} / {{ item.replied_count || 0 }}</template>
    </FrappeListView>
  </div>
</template>

<style scoped>
.campaign-field { display: grid; gap: 6px; font-size: 13px; color: var(--ink-gray-6); }
.campaign-actions, .campaign-mapping { display: grid; gap: 12px; margin-top: 16px; }
.campaign-map-row { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 8px; align-items: end; }
.campaign-counters { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.campaign-counters > div, .campaign-issues > div { display: flex; flex-direction: column; gap: 2px; padding: 10px; border: 1px solid var(--outline-gray-2); border-radius: 8px; }
.campaign-counters span, .campaign-counters small { font-size: 12px; color: var(--ink-gray-5); }
.campaign-counters strong { font-size: 18px; color: var(--ink-gray-9); }
.campaign-issues { display: grid; gap: 8px; }
.campaign-issues > div { flex-direction: row; justify-content: space-between; }
.campaign-issue { margin-top: 10px; color: var(--ink-red-4); font-size: 13px; }
.campaign-hint { margin-top: 10px; color: var(--ink-gray-5); font-size: 13px; }
.campaign-media { display: grid; gap: 6px; }
.campaign-media small { color: var(--ink-gray-5); font-size: 12px; }
.campaign-rows { display: grid; margin: 12px 0; }
.campaign-rows > div { display: grid; grid-template-columns: 80px minmax(0, 1fr) auto; gap: 4px 10px; padding: 8px 0; border-bottom: 1px solid var(--outline-gray-1); font-size: 13px; color: var(--ink-gray-8); }
.campaign-rows small { grid-column: 1 / -1; color: var(--ink-gray-5); overflow-wrap: anywhere; }
@media (max-width: 768px) {
  .campaign-counters { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .campaign-map-row { grid-template-columns: 1fr; }
}
</style>
