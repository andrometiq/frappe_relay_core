<script setup>
import { dateTime } from './relativeTime';
import ChoiceField from './fields/ChoiceField.vue'
import { useLoadMore } from '../composables/useLoadMore'
import { computed, inject, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { Badge, Button, Dialog, ErrorMessage, FeatherIcon, FormControl, TextInput, toast } from "@relay/ui";
import FrappeFormSection from "./frappe/FrappeFormSection.vue";
import FrappeFormView from "./frappe/FrappeFormView.vue";
import FrappeListView from "./frappe/FrappeListView.vue";
import FrappeReadField from "./frappe/FrappeReadField.vue";
import RelaySelect from "./RelaySelect.vue";
import CampaignValidation from './campaigns/CampaignValidation.vue';
import { campaignError } from '../services/campaignErrors.js';
import { useCampaigns } from "../composables/useCampaigns";
import { coreApi } from "../services/coreApi";
import { closeRoute, openRoute } from "../useViewRoute";
import { channelFeature } from "../services/enabledChannels";
import { attachmentMaxBytes, sizeLabel } from "./messages/attachmentFormats";
import { hasManyNumbers, numberName, whatsappNumbers } from "../services/whatsappNumbers";
import { campaignActions, campaignMessage, headerFilesNotice, messageLabel, messageTypes, missingMapping, percent, placeholders,
  shownCounters, statusTheme, windowNotice, invalidNumberLabel } from "../services/campaignProgress";
import { inputTime, recipientLabel, scheduleNotice, siteTime } from "../services/campaignAudience";

const capabilities = inject("relayCapabilities");
const headerLimit = computed(() => {
  const largest = capabilities.value?.max_file_bytes, image = attachmentMaxBytes(capabilities.value, 'WhatsApp', 'photo');
  return largest && (image < largest ? `${sizeLabel(largest)}, and each image at most ${sizeLabel(image)}` : sizeLabel(largest));
});
const workspace = useCampaigns();
const { busy, error, items, campaign, sheet, templates, filter, replyWindow } = workspace;
const creating = ref(false), title = ref(""), type = ref("template"), template = ref(""), text = ref(""), mapping = ref(null);
// A site with two or more WhatsApp numbers names the number each campaign sends from.
const manyNumbers = computed(() => hasManyNumbers(capabilities.value));
const number = ref("");
const numberOptions = computed(() => whatsappNumbers(capabilities.value).map((row) => ({ value: row.name, label: [row.label, row.address].filter(Boolean).join(" · ") })));
const mediaFile = ref("");
const columns = [
  { key: "title", label: "Campaign", width: "minmax(200px,1.4fr)" },
  { key: "status", label: "Status", width: "120px" },
  { key: "template_name", label: "Message", width: "minmax(140px,1fr)" },
  { key: "progress", label: "Sent / replied", width: "140px" },
];
const templateOptions = computed(() => templates.value.map((row) => ({ value: `${row.name}|${row.language}`, label: `${row.name} (${row.language})` })));
const columnOptions = (field) => [{ value: "", label: field.key === "header_media" ? "Choose a column" : field.component === "media" ? "One file or link for every row" : "Fixed value" },
  ...(sheet.value?.columns || [])];
const headerField = computed(() => sheet.value?.fields.find((field) => field.key === "header_media"));
const missing = computed(() => sheet.value && mapping.value ? missingMapping(sheet.value.fields, mapping.value) : []);
const counts = computed(() => campaign.value?.counts || {});
const media = (kind) => channelFeature(capabilities.value, "WhatsApp", "media." + kind);
const types = computed(() => messageTypes(["photo", "video", "document"].filter(media)));
const columnsUsed = computed(() => placeholders(text.value));
const ready = computed(() => title.value.trim().length >= 3 && (!manyNumbers.value || number.value) && (type.value === "template" ? template.value : type.value !== "text" || text.value.trim()));
const noApprovedTemplates = computed(() => type.value === "template" && !busy.value && !templates.value.length && (!manyNumbers.value || number.value));
const createMissing = computed(() => [
  title.value.trim().length < 3 && "add a title of at least 3 characters",
  manyNumbers.value && !number.value && "choose a WhatsApp number",
  type.value === "template" && !template.value && (noApprovedTemplates.value ? "choose an approved template (none yet)" : "choose an approved template"),
  type.value === "text" && !text.value.trim() && "add the message text",
].filter(Boolean));
const missingList = new Intl.ListFormat("en", { type: "conjunction" });
const labels = { start: "Send now", unschedule: "Unschedule", pause: "Pause", resume: "Resume", cancel: "Cancel campaign" };
const actionLabel = (action) => action === "cancel" && campaign.value.status === "Draft" ? "Discard draft" : labels[action];
// A Draft starts from "Start sending" under When to send, so the header keeps only the other actions.
const headerActions = computed(() => campaignActions(campaign.value?.status).filter((action) => !(action === "start" && campaign.value.status === "Draft")));
// Draft recipients come from contacts or from a sheet; nothing is picked until the user chooses one.
const sendMode = ref("now"), startAt = ref("");
const fileHint = "Accepted: .xlsx, .csv, .tsv, or a ZIP with exactly one sheet and the header files (200 MiB / 10000 entries maximum). Put mobile numbers in the first column, with column names in the first row. New numbers become Relay contacts.";
const canSend = computed(() => campaign.value?.validated && !sheet.value && counts.value.total > 0);
const messageName = computed(() => campaign.value?.template_name ? `the template "${campaign.value.template_name}"` : "this message");
// Starting, retrying or cancelling asks once; the dialog names the people and the message.
const confirming = ref("");
const canRetry = computed(() => campaign.value?.status === "Completed" && counts.value.failed > 0);
const confirmDialog = computed(() => {
  const draft = campaign.value?.status === "Draft";
  return {
    start: { title: "Start sending?", label: "Start sending", theme: "blue", done: "Sending started",
      text: `Send ${messageName.value} to ${(counts.value.total || 0).toLocaleString()} people now? You can pause sending, but sent messages cannot be taken back.` },
    retry: { title: "Retry failed messages?", label: "Retry failed", theme: "blue", done: "Retrying failed messages",
      text: `Send ${messageName.value} again to the ${(counts.value.failed || 0).toLocaleString()} people whose message failed? Each failed row is sent once more.` },
    cancel: { title: draft ? "Discard draft?" : "Cancel campaign?", label: draft ? "Discard draft" : "Cancel campaign", theme: "red", done: "Campaign cancelled",
      text: draft ? "Discard this draft? Nothing is sent. It stays in the list as Cancelled." : "Stop this campaign? Messages not sent yet are not sent." },
  }[confirming.value];
});
async function confirmAction() {
  const action = confirming.value, done = confirmDialog.value.done;
  confirming.value = "";
  if (action === "retry") await retryFailed(); else await workspace.control(action);
  if (!error.value) toast(done);
}
async function retryFailed() {
  busy.value = true; error.value = "";
  try { campaign.value = await coreApi("bulk_campaigns.retry_failed", { name: campaign.value.name }, true); }
  catch (e) { error.value = campaignError(e); }
  finally { busy.value = false; }
}
function request(action) { if (["start", "cancel"].includes(action)) confirming.value = action; else workspace.control(action); }
async function validateSheet() {
  await workspace.importRows(mapping.value);
}
async function schedule() {
  await workspace.control("schedule", { scheduled_at: siteTime(startAt.value) });
  if (!error.value) toast("Campaign scheduled");
}
watch(() => campaign.value?.name, () => {
  sendMode.value = "now"; startAt.value = inputTime(campaign.value?.scheduled_at);
});

const listRoute = "#/whatsapp?tab=campaigns";
function routeCampaign(name) {
  openRoute(`${listRoute}&campaign=${encodeURIComponent(name)}`, !!(campaign.value || creating.value));
}
function openCampaign(name) { routeCampaign(name); workspace.open(name); }
function startCreate(updateRoute = true) {
  if (updateRoute) routeCampaign("new");
  creating.value = true; title.value = ""; type.value = "template"; template.value = ""; text.value = "";
  number.value = "";
  if (!manyNumbers.value) workspace.loadTemplates();
}
function chooseNumber(value) {
  number.value = value; template.value = "";
  workspace.loadTemplates(value);
}
async function create() {
  const [template_name, language] = template.value.split("|");
  const values = type.value === "template" ? { template_name, language } : { message: campaignMessage(type.value, text.value) };
  if (await workspace.create({ title: title.value, ...values, ...(number.value ? { channel: number.value } : {}) })) { routeCampaign(campaign.value.name); creating.value = false; }
}
async function chooseFile(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  await workspace.upload(file);
  if (sheet.value) mapping.value = { ...sheet.value.mapping, fields: { ...sheet.value.mapping.fields }, fixed: {} };
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
const moreSentinel = useLoadMore({ loading: busy, hasMore: () => campaign.value?.next, error: error, load: () => workspace.page(filter.value, campaign.value.next) })
const campaignSentinel = useLoadMore({ loading: busy, hasMore: () => workspace.next?.value, error, load: () => workspace.refresh(workspace.next.value) })
</script>

<template>
  <div class="campaign-workspace">
    <div v-if="error" class="v1-template-feedback"><ErrorMessage :message="error" /></div>
    <Dialog :model-value="Boolean(confirming)" :options="{ title: confirmDialog?.title, size: 'sm' }" @update:model-value="value => { if (!value) confirming = '' }">
      <p class="campaign-confirm">{{ confirmDialog?.text }}</p>
      <template #actions>
        <Button variant="outline" label="Keep editing" autofocus @click="confirming = ''" />
        <Button variant="solid" :theme="confirmDialog?.theme" :label="confirmDialog?.label" :loading="busy" @click="confirmAction" />
      </template>
    </Dialog>


    <FrappeFormView v-if="creating" title="New campaign" :breadcrumbs="['Campaigns', 'New']" @back="back">
      <FrappeFormSection description="Send one WhatsApp message to every mobile number in a sheet.">
        <div class="frappe-field-grid">
          <label class="campaign-field"><span>Title</span><TextInput v-model="title" maxlength="100" placeholder="Winter launch Oct 2026" /><small class="campaign-hint">3 to 100 characters. Do not use / \ % # ? &lt; &gt;</small></label>
          <ChoiceField v-if="manyNumbers" :model-value="number" :field="{ label: 'WhatsApp number', options: numberOptions }" @update:model-value="chooseNumber" />
          <RelaySelect v-model="type" label="Message type" :options="types" />
          <ChoiceField v-if="type === 'template'" v-model="template" :field="{ label: 'Approved template', options: templateOptions, readOnly: manyNumbers && !number }" />
        </div>
        <div v-if="noApprovedTemplates" class="campaign-note campaign-empty" role="status">
          <FeatherIcon name="file-text" :size="20" />
          <div><strong>No approved template yet</strong><p>A campaign needs a template that Meta has approved. Create one in Templates; approval usually takes under a day.</p></div>
          <a class="relay-button relay-button--outline" href="#/whatsapp">Go to Templates</a>
        </div>
        <div v-if="type !== 'template'" class="campaign-actions">
          <FormControl v-model="text" type="textarea" :rows="4" :label="type === 'text' ? 'Message' : 'Caption (optional)'"
            :placeholder="'Hi {{Name}}, your order is ready'" />
          <p class="campaign-hint">Write <code v-text="'{{column}}'" /> to fill a value from the sheet column with that name.
            <template v-if="columnsUsed.length">Columns used: {{ columnsUsed.join(", ") }}.</template></p>
          <p class="campaign-note">Text and media reach only people who wrote to you in the last 24 hours. Use an approved template to reach everyone.</p>
        </div>
        <div class="campaign-actions">
          <Button label="Create campaign" variant="solid" :loading="busy" :disabled="!ready" @click="create" />
          <p v-if="createMissing.length" class="campaign-hint" role="status">To create the campaign, {{ missingList.format(createMissing) }}.</p>
          <p v-else class="campaign-hint">Next you upload the sheet of people who get it.</p>
        </div>
      </FrappeFormSection>
    </FrappeFormView>

    <FrappeFormView v-else-if="campaign" :title="campaign.title" :breadcrumbs="['Campaigns', campaign.title]"
      :status="campaign.status" :status-theme="statusTheme(campaign.status)" @back="back">
      <template #actions>
        <Button v-for="action in headerActions" :key="action"
          :label="actionLabel(action)" :variant="action === 'start' || action === 'resume' ? 'solid' : 'outline'" :theme="action === 'cancel' ? 'red' : 'gray'"
          :loading="busy" :disabled="action === 'start' && !canSend" @click="request(action)" />
        <Button v-if="canRetry" :label="`Retry failed (${counts.failed.toLocaleString()})`" variant="solid" icon-left="refresh-cw" :loading="busy" @click="confirming = 'retry'" />
      </template>
      <FrappeFormSection :title="campaign.status === 'Draft' ? 'Summary' : 'Progress'">
        <div class="campaign-counters">
          <div v-for="[key, label] in shownCounters(campaign.status, counts)" :key="key"><span>{{ label }}</span><strong>{{ (counts[key] || 0).toLocaleString() }}</strong>
            <small v-if="key !== 'total' && key !== 'skipped' && counts.total">{{ percent(counts[key], counts.total) }}%</small></div>
        </div>
        <p v-if="campaign.contact_counts" class="campaign-hint" role="status">
          Sheet rows: {{ campaign.contact_counts.created }} created · {{ campaign.contact_counts.existing }} existing · {{ invalidNumberLabel(campaign) }}.
        </p>
        <p v-if="campaign.last_error" class="campaign-issue" role="alert">{{ campaignError(campaign.last_error) }}</p>
        <p v-if="replyWindow" :class="replyWindow.open ? 'campaign-note' : 'campaign-issue'" role="status">{{ windowNotice(replyWindow) }}</p>
        <p v-if="scheduleNotice(campaign)" class="campaign-hint" role="status">{{ scheduleNotice(campaign) }}</p>
      </FrappeFormSection>
      <FrappeFormSection v-if="campaign.status === 'Draft'" title="1. Upload recipients"
        description="Upload a sheet. Uploading again replaces the people not messaged yet.">
        <label class="campaign-drop" :class="{ 'is-busy': busy }">
          <FeatherIcon name="upload" :size="20" /><strong>Choose a sheet or ZIP</strong><small v-text="fileHint" />
          <input type="file" accept=".xlsx,.csv,.tsv,.zip" aria-label="Recipients sheet" :disabled="busy" @change="chooseFile" />
        </label>
        <Button class="campaign-sample" label="Download Excel template" variant="outline" :disabled="busy" @click="workspace.download('sample_sheet')" />
        <p class="campaign-hint">For a template with a header image, video or document, fill its header column on each row with a file name from the ZIP or an https link. Rows can reuse a file name. Subfolders are flattened; hidden files are ignored.<template v-if="headerLimit"> Each header file must be at most {{ headerLimit }}.</template></p>
        <div v-if="sheet && mapping" class="campaign-mapping">
          <p class="campaign-hint">Mobile numbers: {{ mapping.phone }} (first column)</p>
          <div v-if="headerField" class="campaign-map-row">
            <RelaySelect :model-value="mapping.fields.header_media || ''" :label="`Header ${headerField.media} column`" :options="columnOptions(headerField)" @update:model-value="setColumn('header_media', $event)" />
            <p class="campaign-hint" role="status">{{ headerFilesNotice(mapping.header_attachment, headerField.media) }}</p>
          </div>
          <div v-for="field in sheet.fields.filter(field => field.key !== 'header_media')" :key="field.key" class="campaign-map-row">
            <RelaySelect :model-value="mapping.fields[field.key] || ''" :label="field.label" :options="columnOptions(field)" @update:model-value="setColumn(field.key, $event)" />
            <div v-if="!mapping.fields[field.key] && field.component === 'media'" class="campaign-media">
              <input type="file" :accept="(media(campaign.message.kind) || []).join(',')" :aria-label="`${field.label} file`" :disabled="busy" @change="chooseMedia" />
              <small>{{ mediaFile || "Upload one file for every row, or paste an HTTPS link." }}</small>
              <TextInput v-model="mapping.fixed[field.key]" placeholder="https://…" :aria-label="`${field.label} fixed value`" />
            </div>
            <TextInput v-else-if="!mapping.fields[field.key]" v-model="mapping.fixed[field.key]" :placeholder="field.media ? 'https://…' : 'Same value for every row'" :aria-label="`${field.label} fixed value`" />
          </div>
          <p v-if="missing.length" class="campaign-issue">Still needed: {{ missing.join(", ") }}</p>
          <Button label="Validate" variant="solid" :loading="busy" :disabled="missing.length > 0" @click="validateSheet" />
        </div>
      </FrappeFormSection>
      <FrappeFormSection title="2. Validate">
        <CampaignValidation :campaign="campaign" :busy="busy" @download="workspace.download('error_report')" />
      </FrappeFormSection>
      <FrappeFormSection v-if="campaign.status === 'Draft'" title="3. Send">
        <div class="campaign-modes" role="radiogroup" aria-label="When to send">
          <label><input v-model="sendMode" type="radio" value="now" /> Send now</label>
          <label><input v-model="sendMode" type="radio" value="later" /> Schedule at</label>
        </div>
        <div v-if="sendMode === 'later'" class="campaign-schedule">
          <label class="campaign-field"><span>Start time ({{ campaign.time_zone }})</span><TextInput v-model="startAt" type="datetime-local" /></label>
          <Button label="Schedule" variant="solid" :loading="busy" :disabled="!startAt || !canSend" @click="schedule" />
        </div>
        <div v-else class="campaign-schedule"><Button :label="`Start sending to ${(counts.total || 0).toLocaleString()} people`" variant="solid" :loading="busy" :disabled="!canSend" @click="request('start')" /></div>
      </FrappeFormSection>
      <FrappeFormSection v-if="campaign.issues?.length" title="Rows not sent">
        <div class="campaign-issues"><div v-for="row in campaign.issues" :key="row.reason"><span>{{ row.reason }}</span><strong>{{ row.count }}</strong></div></div>
      </FrappeFormSection>
      <FrappeFormSection title="Recipients" collapsible>
        <RelaySelect v-model="filter" label="Show" :options="[{ value: '', label: 'All rows' }, 'Pending', 'Skipped', 'Sent', 'Delivered', 'Read', 'Failed']" @update:model-value="workspace.page($event)" />
        <div class="campaign-rows" role="table" aria-label="Campaign recipients">
          <div v-for="row in campaign.recipients" :key="row.sheet_row" role="row">
            <span>Row {{ row.sheet_row }}</span><span>{{ /^\d+$/.test(row.destination) ? '+' : '' }}{{ row.destination }}</span><Badge :label="recipientLabel(row)" />
            <small v-if="row.reason && recipientLabel(row) === row.status">{{ row.reason }}</small>
          </div>
        </div>
        <div v-if="campaign.next" ref="moreSentinel" class="h-px" aria-hidden="true" />
      </FrappeFormSection>
      <FrappeFormSection v-if="campaign.phases?.length" title="Campaign log" collapsible>
        <ol class="campaign-log"><li v-for="(entry, index) in campaign.phases" :key="index"><strong>{{ entry.phase }}</strong> · {{ dateTime(entry.at) }} · {{ entry.user }}</li></ol>
      </FrappeFormSection>
      <template #sidebar>
        <div class="frappe-field-grid">
          <FrappeReadField v-if="campaign.template_name" label="Template" :value="`${campaign.template_name} (${campaign.language})`" wide />
          <FrappeReadField v-else label="Message" :value="campaign.message?.body || campaign.message?.caption || messageLabel(campaign)" wide />
          <FrappeReadField v-if="manyNumbers && campaign.channel" label="WhatsApp number" :value="numberName(capabilities, campaign.channel) || campaign.channel" wide />
          <FrappeReadField label="Reply window" :value="`${campaign.reply_window_hours} hours`" wide />
          <FrappeReadField v-if="campaign.scheduled_at" label="Scheduled for" :value="`${dateTime(campaign.scheduled_at)} (${campaign.time_zone})`" wide />
          <FrappeReadField label="Started" :value="dateTime(campaign.started_at)" wide />
        </div>
      </template>
    </FrappeFormView>

    <FrappeListView v-else title="Campaigns" description="Send a WhatsApp template, text or media to many numbers and track replies."
      label="Campaigns" :columns="columns" :items="items" :busy="busy" empty-title="No campaigns yet"
      empty-description="Create a campaign, pick contacts or upload a sheet, then send now or schedule it." @open="openCampaign($event.name)">
      <template #actions><Button label="New campaign" icon-left="plus" variant="solid" @click="startCreate" /></template>
      <template #cell-title="{ item }"><strong>{{ item.title }}</strong></template>
      <template #cell-status="{ item }"><Badge :label="item.status" :theme="statusTheme(item.status)" /></template>
      <template #cell-template_name="{ item }">{{ messageLabel(item) }}</template>
      <template #cell-progress="{ item }">{{ item.sent_count || 0 }} / {{ item.replied_count || 0 }}</template>
      <template #footer><div v-if="workspace.next?.value" ref="campaignSentinel" class="h-px" aria-hidden="true" /></template>
    </FrappeListView>
  </div>
</template>

<style scoped>
.campaign-log { display: grid; gap: 8px; font-size: 13px; color: var(--ink-gray-8); overflow-wrap: anywhere; }
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
.campaign-note { margin-top: 10px; padding: 10px 12px; border: 1px solid var(--outline-gray-2); border-radius: 8px; background: var(--surface-gray-1); color: var(--ink-gray-7); font-size: 13px; }
.campaign-empty { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; }
.campaign-empty > div { flex: 1 1 240px; }
.campaign-empty p { margin-top: 2px; color: var(--ink-gray-6); }
.campaign-empty .relay-button { text-decoration: none; }
.campaign-drop { position: relative; display: grid; justify-items: center; gap: 4px; margin-top: 12px; padding: 20px; border: 1.5px dashed var(--outline-gray-3); border-radius: 10px; text-align: center; color: var(--ink-gray-7); cursor: pointer; }
.campaign-drop:hover, .campaign-drop:focus-within { border-color: var(--relay-accent, #0f6cbd); background: var(--surface-gray-1); }
.campaign-drop.is-busy { opacity: .6; cursor: progress; }
.campaign-drop small { color: var(--ink-gray-5); font-size: 12px; }
.campaign-drop input { position: absolute; width: 1px; height: 1px; opacity: 0; }
.campaign-sample { display: inline-flex; align-items: center; gap: 4px; margin-top: 8px; font-size: 13px; }
.campaign-confirm { font-size: 14px; line-height: 1.5; color: var(--ink-gray-8); }
.campaign-hint { margin-top: 10px; color: var(--ink-gray-5); font-size: 13px; }
.campaign-media { display: grid; gap: 6px; }
.campaign-modes { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; font-size: 13px; color: var(--ink-gray-8); }
.campaign-schedule { display: flex; flex-wrap: wrap; gap: 12px; align-items: end; margin-top: 12px; }
.campaign-media small { color: var(--ink-gray-5); font-size: 12px; }
.campaign-rows { display: grid; margin: 12px 0; }
.campaign-rows > div { display: grid; grid-template-columns: 80px minmax(0, 1fr) auto; gap: 4px 10px; padding: 8px 0; border-bottom: 1px solid var(--outline-gray-1); font-size: 13px; color: var(--ink-gray-8); }
.campaign-rows small { grid-column: 1 / -1; color: var(--ink-gray-5); overflow-wrap: anywhere; }
@media (max-width: 768px) {
  .campaign-counters { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .campaign-map-row { grid-template-columns: 1fr; }
}
</style>
