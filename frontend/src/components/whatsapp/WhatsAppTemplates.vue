<script setup>
import { recordTitle } from '../../services/recordTitle'
import { computed, inject, onBeforeUnmount, ref, watch } from "vue";
import { Badge, Button, FeatherIcon, TextInput } from "@relay/ui";
import FrappeFormSection from "../frappe/FrappeFormSection.vue";
import FrappeFormView from "../frappe/FrappeFormView.vue";
import FrappeListView from "../frappe/FrappeListView.vue";
import FrappeReadField from "../frappe/FrappeReadField.vue";
import RelaySelect from "../RelaySelect.vue";
import { whatsappKey } from "../../composables/whatsapp/context";
import { languageLabel } from "../../services/templateLanguages";
import { sentenceCase } from "../../services/textCase";
import {
  filterTemplates,
  templateBody,
  templateButtons,
  templateFooter,
  templateHeader,
  templateStatusTheme,
  templateSyncLabel,
} from "../../services/templateList";
import TemplateEditor from "./TemplateEditor.vue";
import TemplatePreview from "./TemplatePreview.vue";
import { templateRendering, templateParameterDescriptors } from "../../services/templateParameters";
import { templateForm, templatePreview } from "../../services/templateAuthoring";
import { closeRoute, openRoute } from "../../useViewRoute";

const access = inject('relayCapabilities', ref({ manage: false }));
const workspace = inject(whatsappKey);
const {
  busy,
  templates,
  syncStatus,
  editingTemplate,
  template,
  creating,
  selectedTemplate,
  supported,
  refresh,
  deleteTemplate,
} = workspace;

const neverSynced = computed(() => !syncStatus.value?.synced_at && !syncStatus.value?.syncing);
const emptyDescription = computed(() => {
  if (templates.value.length) return 'Try another name, status, category or language.';
  if (neverSynced.value) return 'Templates have not been synced from Meta yet. Select Sync now to load them.';
  return 'No templates exist yet. Create an approved message to start conversations with your customers.';
});
const query = ref("");
const status = ref("ALL");
const category = ref("ALL");
const language = ref("ALL");
const confirmingDelete = ref(false);
const selectedPreview = computed(() => {
  try { return selectedTemplate.value ? templatePreview(templateForm(selectedTemplate.value)) : null; }
  catch { return null; } // Templates without a standard body keep the field view only.
});
const renderedBody = (row) => templateBody(row) ? templateRendering(row, templateParameterDescriptors(row), {}).body : "";
const shortBody = (row) => { const body = renderedBody(row).replace(/\s+/g, " "); return body.length > 80 ? body.slice(0, 79) + "…" : body; };
const statusHint = (status) => ({ PENDING: "Waiting for Meta to approve. This usually takes under a day.", REJECTED: "Meta did not approve this template.",
  APPROVED: "Approved by Meta. Ready to send.", PAUSED: "Meta paused this template because of low quality.", DISABLED: "Meta turned this template off." })[String(status || "").toUpperCase()] || "";
const rejection = (row) => row.rejected_reason || row.rejection_reason || "";
const columns = [
  { key: "name", label: "Template name", width: "minmax(210px,1.2fr)" },
  { key: "status", label: "Status", width: "130px" },
  { key: "category", label: "Category", width: "150px" },
  { key: "language", label: "Language", width: "190px" },
  { key: "message", label: "Message", width: "minmax(240px,1.5fr)" },
];
const filteredTemplates = computed(() =>
  filterTemplates(templates.value, {
    query: query.value,
    status: status.value,
    category: category.value,
    language: language.value,
  }),
);
const statuses = computed(() => [
  { value: "ALL", label: "All statuses" },
  ...[
    ...new Set(
      templates.value
        .map((row) => String(row.status || "").toUpperCase())
        .filter(Boolean),
    ),
  ]
    .sort()
    .map((value) => ({ value, label: sentenceCase(value) })),
]);

function routeTemplate(id = "", edit = false) {
  if (!id) return closeRoute("#/whatsapp");
  const params = new URLSearchParams({ template: id });
  if (edit) params.set("edit", "1");
  openRoute(`#/whatsapp?${params}`, !!(template.value || creating.value));
}
function openTemplate(row, updateRoute = true) {
  if (updateRoute) routeTemplate(row.id);
  confirmingDelete.value = false;
  creating.value = false;
  editingTemplate.value = "";
  template.value = row.id;
}
function openList(updateRoute = true) {
  if (updateRoute) routeTemplate();
  confirmingDelete.value = false;
  creating.value = false;
  editingTemplate.value = "";
  template.value = "";
}
function createTemplate(updateRoute = true) {
  if (!access.value.manage) return;
  if (updateRoute) routeTemplate("new");
  confirmingDelete.value = false;
  template.value = "";
  editingTemplate.value = "";
  creating.value = true;
}
function editTemplate() {
  if (!access.value.manage) return;
  if (!selectedTemplate.value) return;
  routeTemplate(selectedTemplate.value.id, true);
  confirmingDelete.value = false;
  editingTemplate.value = selectedTemplate.value.id;
  creating.value = true;
}
async function saved() {
  const edited = editingTemplate.value;
  creating.value = false;
  editingTemplate.value = "";
  await refresh();
  if (edited && templates.value.some((row) => row.id === edited))
    openTemplate(templates.value.find((row) => row.id === edited));
  else openList();
}
async function removeTemplate() {
  if (!selectedTemplate.value) return;
  await deleteTemplate(selectedTemplate.value);
  confirmingDelete.value = false;
  openList();
}
function restoreRoute() {
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const id = params.get("template") || "";
  if (id === "new") { createTemplate(false); return; }
  const row = templates.value.find((item) => item.id === id);
  if (!row) {
    if (!id) openList(false);
    return;
  }
  openTemplate(row, false);
  if (params.get("edit") === "1") {
    editingTemplate.value = row.id;
    creating.value = true;
  }
}
const restoreHandler = () => restoreRoute();
watch([templates, busy], restoreRoute, { immediate: true });
window.addEventListener("popstate", restoreHandler);
onBeforeUnmount(() => window.removeEventListener("popstate", restoreHandler));
</script>

<template>
  <TemplateEditor
    v-if="creating && access.manage"
    :key="editingTemplate || 'new'"
    :enabled="supported"
    :template="editingTemplate ? selectedTemplate : null"
    @cancel="openList"
    @saved="saved"
  />

  <FrappeFormView
    v-else-if="selectedTemplate"
    :title="selectedTemplate.name"
    :breadcrumbs="['Templates', selectedTemplate.name]"
    :status="selectedTemplate.status || 'Unknown'"
    :status-theme="templateStatusTheme(selectedTemplate.status)"
    @back="openList"
  >
    <template #actions>
      <Button v-if="access.manage" variant="outline" icon-left="edit-3" label="Edit" :disabled="!supported" @click="editTemplate" />
      <Button v-if="access.manage && !confirmingDelete" variant="outline" theme="red" icon-left="trash" label="Delete" :disabled="!supported" @click="confirmingDelete = true" />
    </template>

    <FrappeFormSection>
      <div class="frappe-field-grid">
        <FrappeReadField label="Status" :value="[selectedTemplate.status ? sentenceCase(selectedTemplate.status) : 'Unknown', statusHint(selectedTemplate.status)].filter(Boolean).join(' · ')" />
        <FrappeReadField v-if="['REJECTED', 'PAUSED', 'DISABLED'].includes(selectedTemplate.status)" label="Reason from Meta" :value="rejection(selectedTemplate) || 'Meta has not provided a reason. Review the template in WhatsApp Manager.'" wide />
        <FrappeReadField label="Category" :value="sentenceCase(selectedTemplate.category)" />
        <FrappeReadField label="Language" :value="languageLabel(selectedTemplate.language)" />
        <FrappeReadField label="Variables look like" :value="String(selectedTemplate.parameter_format || '').toUpperCase() === 'NAMED' ? '{{customer_name}}' : '{{1}}'" />
      </div>
    </FrappeFormSection>
    <FrappeFormSection title="Message content">
      <div class="frappe-field-grid">
        <FrappeReadField label="Header" :value="templateHeader(selectedTemplate) || 'No header'" />
        <FrappeReadField label="Footer" :value="templateFooter(selectedTemplate) || 'No footer'" />
        <FrappeReadField label="Message body" :value="renderedBody(selectedTemplate) || 'No message body'" wide multiline />
      </div>
    </FrappeFormSection>
    <FrappeFormSection v-if="templateButtons(selectedTemplate).length" title="Buttons" collapsible>
      <div class="template-button-list">
        <div v-for="(button, index) in templateButtons(selectedTemplate)" :key="index">
          <span>{{ button.type?.replaceAll('_', ' ') }}</span><strong>{{ button.text || "Untitled button" }}</strong>
        </div>
      </div>
    </FrappeFormSection>

    <FrappeFormSection title="More details" collapsible collapsed>
      <div class="frappe-field-grid"><FrappeReadField label="Meta template ID" :value="selectedTemplate.id" /></div>
    </FrappeFormSection>

    <template #sidebar>
      <TemplatePreview v-if="selectedPreview" :preview="selectedPreview" />
      <section v-if="confirmingDelete" class="template-danger-zone" role="alert">
        <h3>Delete template?</h3>
        <p>This removes <strong>{{ selectedTemplate.name }}</strong> from Meta.</p>
        <div class="flex gap-2">
          <Button label="Delete" variant="solid" theme="red" :loading="busy" @click="removeTemplate" />
          <Button variant="outline" label="Cancel" @click="confirmingDelete = false" />
        </div>
      </section>
    </template>
  </FrappeFormView>

  <FrappeListView
    v-else
    title="Message templates"
    :description="neverSynced ? 'Not synced yet. Select Sync now to load your templates from Meta.' : templateSyncLabel(syncStatus)"
    label="Message templates"
    :columns="columns"
    :items="filteredTemplates"
    :busy="busy"
    empty-title="No templates found"
    :empty-description="emptyDescription"
    @open="openTemplate"
  >
    <template #actions>
      <Button variant="outline" v-if="neverSynced" label="Sync now" icon-left="refresh-cw" :loading="busy" @click="refresh" />
      <Button v-else variant="outline" icon-left="refresh-cw" label="Sync with Meta" :loading="busy" @click="refresh" />
      <Button v-if="access.manage" label="New template" icon-left="plus" variant="solid" :disabled="!supported" @click="createTemplate" />
    </template>
    <template #filters>
      <TextInput v-model="query" type="search" placeholder="Search templates" aria-label="Search templates"><template #prefix><FeatherIcon name="search" /></template></TextInput>
      <RelaySelect v-model="status" label="Status" hide-label :options="statuses" />
      <RelaySelect v-model="category" label="Category" hide-label :options="[{ value: 'ALL', label: 'All categories' }, ...['UTILITY', 'MARKETING', 'AUTHENTICATION'].map(value => ({ value, label: sentenceCase(value) }))]" />
      <RelaySelect v-model="language" label="Language" hide-label :options="[{ value: 'ALL', label: 'All languages' }, ...[...new Set(templates.map(row => row.language).filter(Boolean))].map(value => ({ value, label: languageLabel(value) }))]" />
    </template>
    <template #cell-name="{ item }"><strong>{{ recordTitle(item, 'Template') }}</strong></template>
    <template #cell-status="{ item }"><Badge :label="item.status ? sentenceCase(item.status) : 'Unknown'" :theme="templateStatusTheme(item.status)" :title="statusHint(item.status)" /></template>
    <template #cell-category="{ item }">{{ item.category ? sentenceCase(item.category) : "—" }}</template>
    <template #cell-language="{ item }">{{ languageLabel(item.language) }}</template>
    <template #cell-message="{ item }"><span><span v-if="item.status === 'REJECTED'" class="template-row-reason">Rejected{{ rejection(item) ? ': ' + rejection(item) : '' }}</span>{{ shortBody(item) || "No message body" }}</span></template>
    <template #empty-action><Button variant="outline" v-if="query || status !== 'ALL' || category !== 'ALL' || language !== 'ALL'" label="Clear filters" @click="query = ''; status = 'ALL'; category = 'ALL'; language = 'ALL'" /><Button v-else-if="neverSynced" label="Sync now" variant="solid" :loading="busy" @click="refresh" /><Button v-else-if="access.manage" label="Create template" variant="solid" :disabled="!supported" @click="createTemplate" /><Button variant="outline" v-else label="Refresh templates" @click="refresh" /></template>
    <template #footer><span>{{ filteredTemplates.length }} of {{ templates.length }} templates</span></template>
  </FrappeListView>
</template>
