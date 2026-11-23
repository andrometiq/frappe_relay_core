<script setup>
import { computed, inject, onBeforeUnmount, ref, watch } from "vue";
import { Badge, Button, FeatherIcon, TextInput } from "@relay/ui";
import PageSidebar from "../shell/PageSidebar.vue";
import SidePanel from "../shell/SidePanel.vue";
import { whatsappKey } from "../../composables/whatsapp/context";
import { languageLabel } from "../../services/templateLanguages";
import { sentenceCase } from "../../services/textCase";
import { qualityBadge } from "../../services/whatsappHealth";
import { whatsappNumbers } from "../../services/whatsappNumbers";
import { whatsappRoute, whatsappSections } from "../../services/navigation";
import {
  TEMPLATE_CATEGORIES,
  TEMPLATE_STATUS_GROUPS,
  filterTemplates,
  templateBody,
  templateButtons,
  templateCounts,
  templateFooter,
  templateHeader,
  templateStatusTheme,
  templateSyncLabel,
} from "../../services/templateList";
import TemplateEditor from "./TemplateEditor.vue";
import TemplatePreview from "./TemplatePreview.vue";
import { templateRendering, templateParameterDescriptors } from "../../services/templateParameters";
import { TEMPLATE_BUTTON_TYPES, templateForm, templatePreview } from "../../services/templateAuthoring";
import { closeRoute, openRoute } from "../../useViewRoute";

const access = inject("relayCapabilities", ref({ manage: false }));
const workspace = inject(whatsappKey);
const { busy, templates, syncStatus, editingTemplate, template, creating, selectedTemplate, supported, refresh, deleteTemplate } = workspace;

const neverSynced = computed(() => !syncStatus.value?.synced_at && !syncStatus.value?.syncing);
const query = ref("");
const group = ref("ALL");
const category = ref("ALL");
const language = ref("ALL");
const confirmingDelete = ref(false);
const counts = computed(() => templateCounts(templates.value));
const filtered = computed(() => filterTemplates(templates.value, { query: query.value, group: group.value, category: category.value, language: language.value }));
const languages = computed(() => [...new Set(templates.value.map((row) => row.language).filter(Boolean))].sort());
const hasFilters = computed(() => query.value || group.value !== "ALL" || category.value !== "ALL" || language.value !== "ALL");
const emptyDescription = computed(() => {
  if (templates.value.length) return "Try another name, status, category or language.";
  if (neverSynced.value) return "Templates have not been synced from Meta yet. Select Sync now to load them.";
  return "No templates exist yet. Create an approved message to start conversations with your customers.";
});

const sidebar = computed(() => [
  { key: "status", items: TEMPLATE_STATUS_GROUPS.filter((row) => row.key !== "PAUSED" || counts.value.PAUSED)
    .map((row) => ({ key: row.key, label: row.label, icon: row.icon, tone: row.tone, count: counts.value[row.key] })) },
  { key: "category", title: "Category", items: TEMPLATE_CATEGORIES.map((row) => ({ key: "category:" + row.key, label: row.label,
    dot: { blue: "#3e63dd", orange: "#f76b15", gray: "#8e4ec6" }[row.tone], count: counts.value.categories[row.key] || 0 })) },
  { key: "numbers", title: "Numbers", items: whatsappNumbers(access.value).map((row) => ({ key: "number:" + row.name, icon: "phone", tone: "whatsapp",
    label: [row.label, row.address].filter(Boolean).join(" · "), route: whatsappRoute("account") })) },
  { key: "more", title: "WhatsApp", items: [...whatsappSections(access.value).filter((row) => ["forms", "billing"].includes(row.name)),
    { name: "account", label: "Account", icon: "user" }].map((row) => ({ key: "tab:" + row.name, label: row.label, icon: row.icon, route: whatsappRoute(row.name) })) },
].filter((section) => section.items.length));
const activeKey = computed(() => (category.value !== "ALL" ? "category:" + category.value : group.value));
const heading = computed(() => {
  if (category.value !== "ALL") return sentenceCase(category.value) + " templates";
  return group.value === "ALL" ? "All templates" : TEMPLATE_STATUS_GROUPS.find((row) => row.key === group.value).label;
});
function pick(item) {
  if (item.route) { location.hash = item.route; return; }
  if (item.key.startsWith("category:")) { category.value = item.key.slice(9); group.value = "ALL"; }
  else { group.value = item.key; category.value = "ALL"; }
}
function clearFilters() { query.value = ""; group.value = "ALL"; category.value = "ALL"; language.value = "ALL"; }

const selectedPreview = computed(() => {
  try { return selectedTemplate.value ? templatePreview(templateForm(selectedTemplate.value)) : null; }
  catch { return null; } // Templates without a standard body keep the field view only.
});
const renderedBody = (row) => (templateBody(row) ? templateRendering(row, templateParameterDescriptors(row), {}).body : "");
const shortBody = (row) => { const body = renderedBody(row).replace(/\s+/g, " "); return body.length > 80 ? body.slice(0, 79) + "…" : body; };
// Body text with its variables marked, as in the WhatsApp Manager editor.
const bodyParts = (row) => templateBody(row).split(/(\{\{[^{}]+\}\})/).filter(Boolean).map((text) => ({ text, variable: /^\{\{.+\}\}$/.test(text) }));
const statusHint = (status) => ({ PENDING: "Waiting for Meta to approve. This usually takes under a day.", REJECTED: "Meta did not approve this template.",
  APPROVED: "Ready to send.", PAUSED: "Meta flagged low quality.", DISABLED: "Meta turned this template off." })[String(status || "").toUpperCase()] || "";
const qualityHint = (score) => ({ GREEN: "Customers respond well.", YELLOW: "Customers are reporting or blocking it. Review the content.",
  RED: "Meta may pause it soon. Change the content or stop sending it." })[score] || "Meta has not rated it yet. New and rarely sent templates stay unknown.";
const rejection = (row) => row.rejected_reason || row.rejection_reason || "";
const categoryTheme = (value) => TEMPLATE_CATEGORIES.find((row) => row.key === String(value || "").toUpperCase())?.tone || "gray";
const buttonType = (button) => TEMPLATE_BUTTON_TYPES.find((option) => option.value === button.type)?.label || sentenceCase(String(button.type || "Button").replaceAll("_", " "));
const buttonText = (button) => button.text || (button.type === "COPY_CODE" ? "Copy offer code" : "Untitled button");
const buttonTarget = (button) => button.url || button.phone_number || "";

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
  if (!access.value.manage || !selectedTemplate.value) return;
  routeTemplate(selectedTemplate.value.id, true);
  confirmingDelete.value = false;
  editingTemplate.value = selectedTemplate.value.id;
  creating.value = true;
}
// Cancel returns to the template that was being edited, or to the list after a new one.
function cancelEdit() {
  const edited = editingTemplate.value && templates.value.find((row) => row.id === editingTemplate.value);
  if (edited) openTemplate(edited);
  else openList();
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
  <div class="relay-page template-page" :class="{ 'has-panel': selectedTemplate || (creating && access.manage) }">
    <PageSidebar title="Templates" :subtitle="neverSynced ? 'Not synced with Meta yet' : templateSyncLabel(syncStatus)" label="Template views" :sections="sidebar" :active="activeKey" @select="pick">
      <template #actions><Button v-if="access.manage" variant="ghost" icon="plus" aria-label="Create template" title="Create template" :disabled="!supported" @click="createTemplate" /></template>
    </PageSidebar>
    <main class="page-main" aria-label="Message templates">
      <header class="page-head">
        <h2>{{ heading }}</h2><small>{{ filtered.length }}</small>
        <div class="page-head-actions">
          <Button variant="outline" icon-left="refresh-cw" :label="neverSynced ? 'Sync now' : 'Sync with Meta'" :loading="busy" @click="refresh" />
          <Button v-if="access.manage" label="Create template" icon-left="plus" variant="solid" :disabled="!supported" @click="createTemplate" />
        </div>
      </header>
      <div class="page-bar">
        <TextInput v-model="query" class="page-search" type="search" placeholder="Filter by name or text" aria-label="Search templates"><template #prefix><FeatherIcon name="search" /></template></TextInput>
        <select v-model="language" class="page-select" aria-label="Language">
          <option value="ALL">All languages</option>
          <option v-for="code in languages" :key="code" :value="code">{{ languageLabel(code) }}</option>
        </select>
      </div>
      <table v-if="filtered.length" class="page-table template-table">
        <thead><tr><th>Name</th><th class="col-wide-optional">Category</th><th class="col-optional">Language</th><th>Status</th><th class="col-optional">Quality</th></tr></thead>
        <tbody>
          <tr v-for="row in filtered" :key="row.id" :class="{ selected: row.id === template }" tabindex="0" :aria-selected="row.id === template"
            @click="openTemplate(row)" @keydown.enter.prevent="openTemplate(row)">
            <td class="cell-main"><b class="cell-title page-mono">{{ row.name }}</b><small><template v-if="row.status === 'REJECTED'">Rejected{{ rejection(row) ? ': ' + rejection(row) : '' }} · </template>{{ shortBody(row) || "No message body" }}</small></td>
            <td data-label="Category" class="col-wide-optional"><Badge :label="row.category ? sentenceCase(row.category) : 'No category'" :theme="categoryTheme(row.category)" /></td>
            <td data-label="Language" class="col-optional">{{ languageLabel(row.language) }}</td>
            <td data-label="Status"><Badge :label="row.status ? sentenceCase(row.status) : 'Unknown'" :theme="templateStatusTheme(row.status)" :title="statusHint(row.status)" /></td>
            <td data-label="Quality" class="col-optional"><Badge v-bind="qualityBadge(row.quality_score?.score)" :title="qualityHint(row.quality_score?.score)" /></td>
          </tr>
        </tbody>
      </table>
      <div v-else-if="!busy" class="page-empty">
        <strong>No templates found</strong><p>{{ emptyDescription }}</p>
        <Button v-if="hasFilters" variant="outline" label="Clear filters" @click="clearFilters" />
        <Button v-else-if="neverSynced" label="Sync now" variant="solid" :loading="busy" @click="refresh" />
        <Button v-else-if="access.manage" label="Create template" variant="solid" :disabled="!supported" @click="createTemplate" />
      </div>
      <p v-else class="page-note" role="status">Loading templates…</p>
      <p v-if="filtered.length" class="page-note">{{ filtered.length }} of {{ templates.length }} templates</p>
    </main>

    <TemplateEditor v-if="creating && access.manage" :key="editingTemplate || 'new'" :enabled="supported"
      :template="editingTemplate ? selectedTemplate : null" @cancel="cancelEdit" @saved="saved" />

    <SidePanel v-else-if="selectedTemplate" :title="selectedTemplate.name" label="Template details" class="template-view" @close="openList">
      <template #title><h2 class="page-mono" :title="selectedTemplate.name">{{ selectedTemplate.name }}</h2></template>
      <template #actions>
        <Button v-if="access.manage" variant="outline" icon-left="edit-3" label="Edit" :disabled="!supported" @click="editTemplate" />
      </template>
      <div class="panel-field">
        <h3>Status</h3>
        <p class="template-status-line"><Badge :label="selectedTemplate.status ? sentenceCase(selectedTemplate.status) : 'Unknown'" :theme="templateStatusTheme(selectedTemplate.status)" /><span>{{ statusHint(selectedTemplate.status) }}</span></p>
        <p v-if="['REJECTED', 'PAUSED', 'DISABLED'].includes(selectedTemplate.status)" class="panel-box template-reason">{{ rejection(selectedTemplate) || "Meta has not provided a reason. Review the template in WhatsApp Manager." }}</p>
      </div>
      <div class="panel-field">
        <h3>Quality</h3>
        <p class="template-status-line"><Badge v-bind="qualityBadge(selectedTemplate.quality_score?.score)" /><span>{{ qualityHint(selectedTemplate.quality_score?.score) }}</span></p>
      </div>
      <div class="panel-field">
        <h3>Category</h3>
        <div class="segmented" role="group" aria-label="Category">
          <span v-for="row in TEMPLATE_CATEGORIES" :key="row.key" :class="{ on: String(selectedTemplate.category).toUpperCase() === row.key }">{{ row.label }}</span>
        </div>
      </div>
      <div class="panel-field"><h3>Language</h3><p>{{ languageLabel(selectedTemplate.language) }}</p></div>
      <div v-if="templateHeader(selectedTemplate)" class="panel-field"><h3>Header</h3><p class="panel-box">{{ templateHeader(selectedTemplate) }}</p></div>
      <div class="panel-field">
        <h3>Message body</h3>
        <p class="panel-box template-body"><template v-for="(part, index) in bodyParts(selectedTemplate)" :key="index"><span v-if="part.variable" class="template-variable">{{ part.text }}</span><template v-else>{{ part.text }}</template></template><template v-if="!templateBody(selectedTemplate)">No message body</template></p>
      </div>
      <div v-if="templateFooter(selectedTemplate)" class="panel-field"><h3>Footer</h3><p class="panel-box">{{ templateFooter(selectedTemplate) }}</p></div>
      <div v-if="templateButtons(selectedTemplate).length" class="panel-field">
        <h3>Buttons</h3>
        <p v-for="(button, index) in templateButtons(selectedTemplate)" :key="index" class="panel-box template-button-row">
          <span class="panel-hint">{{ buttonType(button) }}</span><strong>{{ buttonText(button) }}</strong><span v-if="buttonTarget(button)" class="panel-hint">{{ buttonTarget(button) }}</span>
        </p>
      </div>
      <TemplatePreview v-if="selectedPreview" :preview="selectedPreview" />
      <details class="template-more">
        <summary>More details</summary>
        <p><span class="panel-hint">Variables look like</span> <span class="page-mono" v-text="String(selectedTemplate.parameter_format || '').toUpperCase() === 'NAMED' ? '{{customer_name}}' : '{{1}}'" /></p>
        <p><span class="panel-hint">Meta template ID</span> <span class="page-mono">{{ selectedTemplate.id }}</span></p>
      </details>
      <section v-if="confirmingDelete" class="template-danger-zone" role="alert">
        <h3>Delete template?</h3>
        <p>This removes <strong>{{ selectedTemplate.name }}</strong> from Meta.</p>
        <div class="flex gap-2">
          <Button label="Delete" variant="solid" theme="red" :loading="busy" @click="removeTemplate" />
          <Button variant="outline" label="Cancel" @click="confirmingDelete = false" />
        </div>
      </section>
      <template v-if="access.manage && !confirmingDelete" #footer>
        <Button variant="outline" theme="red" icon-left="trash" label="Delete template" :disabled="!supported" @click="confirmingDelete = true" />
      </template>
    </SidePanel>
  </div>
</template>

<style scoped>
.template-status-line { display:flex; flex-wrap:wrap; align-items:center; gap:8px; font-size:13px; color:var(--relay-ink-2); }
.template-reason { color:var(--relay-red); }
.template-variable { padding:0 4px; border-radius:4px; background:var(--relay-accent-soft); color:var(--relay-accent-text); font-weight:500; }
.template-button-row { display:flex; flex-wrap:wrap; align-items:baseline; gap:4px 10px; white-space:normal; }
.template-more summary { cursor:pointer; color:var(--relay-ink-3); font-size:12.5px; }
.template-more p { margin-top:6px; font-size:13px; overflow-wrap:anywhere; }
</style>
