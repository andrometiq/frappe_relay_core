<script setup>
import ChoiceField from '../fields/ChoiceField.vue'
import { readableName, recordTitle } from '../../services/recordTitle'
import { computed, onMounted, reactive, ref, watch } from "vue";
import { Badge, Button, ErrorMessage, FormControl, TextInput } from "@relay/ui";
import RelaySelect from "../RelaySelect.vue";
import { useCampaignAudience } from "../../composables/useCampaignAudience";
import { audienceSummary, dropContact, emptyAudience, hasAudienceChoice, missingValues, pickContact, valueOptions } from "../../services/campaignAudience";

const props = defineProps({ campaign: Object, uploadMedia: Function });
const emit = defineEmits(["imported"]);
const campaign = computed(() => props.campaign);
// A saved audience without filters or added contacts was "everyone on this number".
const everyone = ref(Boolean(props.campaign.audience) && !hasAudienceChoice(props.campaign.audience, false));
const { options, audience, chosen, mapping, preview, found, error, busy, counting, load, search, importContacts } = useCampaignAudience(campaign, everyone);
// Everyone means no filters; contacts removed by hand stay removed.
watch(everyone, (value) => { if (value) audience.value = { ...emptyAudience(), exclude: audience.value.exclude }; });
const query = ref(""), mediaFile = ref("");
const known = reactive({});

const tagOptions = computed(() => [{ value: "", label: "Any tag" }, ...(options.value?.tags || [])]);
const typeOptions = computed(() => [{ value: "", label: "Any record" }, ...(options.value?.types || []).map((row) => row.doctype)]);
const segments = computed(() => options.value?.types.find((row) => row.doctype === audience.value.doctype)?.segments || []);
const missing = computed(() => missingValues(props.campaign.fields, mapping.value));
const ready = computed(() => preview.value?.count > 0 && !missing.value.length);

// Names of contacts seen in the list or the search, for the added and removed chips.
watch(() => [preview.value?.sample, found.value], (lists) => { for (const row of lists.flat()) if (row) known[row.contact] = row; });
const label = (contact) => known[contact] ? `${known[contact].name} · +${known[contact].number}` : recordTitle(contact, 'Contact');

function chooseType(value) { audience.value = { ...audience.value, doctype: value, segments: {} }; }
function setSegment(field, value) { audience.value = { ...audience.value, segments: { ...audience.value.segments, [field]: value } }; }
function setSource(key, source) {
  const fields = { ...mapping.value.fields };
  if (source) fields[key] = source; else delete fields[key];
  mapping.value = { ...mapping.value, fields };
}
function add(contact) { audience.value = pickContact(audience.value, contact, "include"); query.value = ""; search(""); }
function remove(contact) { audience.value = pickContact(audience.value, contact, "exclude"); }
function undo(contact, list) { audience.value = dropContact(audience.value, contact, list); }
async function chooseMedia(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  const fileUrl = await props.uploadMedia(file);
  if (fileUrl) { mapping.value.fixed.media_url = fileUrl; mediaFile.value = file.name; }
  event.target.value = "";
}
async function submit() {
  const fresh = await importContacts();
  if (fresh) emit("imported", fresh);
}
onMounted(load);
</script>

<template>
  <div class="audience">
    <ErrorMessage v-if="error" :message="error" />
    <FormControl v-model="everyone" type="checkbox" label="Everyone with a WhatsApp number here" />
    <p v-if="!everyone" class="audience-hint">Or narrow it down with filters, or add people by name below.</p>
    <div v-if="!everyone" class="audience-filters">
      <ChoiceField v-model="audience.tag" :field="{ label: 'Tag', placeholder: 'Any tag', options: tagOptions, readOnly: false }" />
      <ChoiceField :model-value="audience.doctype" :field="{ label: 'Linked to', placeholder: 'Any record type', options: typeOptions, readOnly: false }" @update:model-value="chooseType" />
      <RelaySelect v-for="segment in segments" :key="segment.field" :model-value="audience.segments[segment.field] || ''"
        :label="segment.label" :options="[{ value: '', label: 'Any' }, ...segment.options]" @update:model-value="setSegment(segment.field, $event)" />
      <label class="audience-field"><span>Number contains</span><TextInput v-model="audience.number" inputmode="numeric" placeholder="9198" /></label>
      <label class="audience-field"><span>Last message on or after</span><TextInput v-model="audience.last_message_from" type="date" /></label>
      <label class="audience-field"><span>Last message on or before</span><TextInput v-model="audience.last_message_to" type="date" /></label>
    </div>
    <p class="audience-count" role="status">{{ !chosen ? "No people chosen yet." : counting && !preview ? "Counting…" : audienceSummary(preview) }}</p>

    <div v-if="preview?.sample.length" class="audience-rows" role="table" aria-label="Matched contacts">
      <div v-for="row in preview.sample" :key="row.contact + row.number" role="row">
        <span>{{ readableName(row.name, 'Contact') }}</span><span>+{{ row.number }}</span>
        <Badge v-if="row.opted_out" label="Opted out" theme="orange" /><span v-else />
        <Button label="Remove" variant="outline" size="xs" @click="remove(row.contact)" />
      </div>
      <small v-if="preview.count > preview.sample.length">and {{ (preview.count - preview.sample.length).toLocaleString() }} more</small>
    </div>

    <div v-if="!everyone" class="audience-manual">
      <label class="audience-field"><span>Add a contact</span>
        <TextInput v-model="query" placeholder="Name or number" @update:model-value="search" /></label>
      <div v-for="row in found" :key="'found' + row.contact + row.number" class="audience-found">
        <span>{{ row.name }} · +{{ row.number }}</span><Button label="Add" variant="outline" @click="add(row.contact)" />
      </div>
      <div v-if="audience.include.length" class="audience-chips"><span>Added</span>
        <Button v-for="contact in audience.include" :key="'in' + contact" :label="label(contact)" icon-right="x" variant="subtle" @click="undo(contact, 'include')" /></div>
      <div v-if="audience.exclude.length" class="audience-chips"><span>Removed</span>
        <Button v-for="contact in audience.exclude" :key="'out' + contact" :label="label(contact)" icon-right="x" variant="subtle" @click="undo(contact, 'exclude')" /></div>
    </div>

    <div v-if="campaign.fields.length" class="audience-values">
      <strong>Message values</strong>
      <div v-for="field in campaign.fields" :key="field.key" class="audience-value">
        <ChoiceField :model-value="mapping.fields[field.key] || ''" :field="{ label: field.label, options: valueOptions(field, options?.sources || []) }"
          @update:model-value="setSource(field.key, $event)" />
        <div v-if="!mapping.fields[field.key]" class="audience-fixed">
          <input v-if="field.component === 'media'" type="file" :aria-label="`${field.label} file`" @change="chooseMedia" />
          <small v-if="field.component === 'media'">{{ mediaFile || "Upload one file for every contact, or paste an HTTPS link." }}</small>
          <TextInput v-model="mapping.fixed[field.key]" :placeholder="field.media ? 'https://…' : 'Same value for every contact'" :aria-label="`${field.label} fixed value`" />
        </div>
      </div>
    </div>
    <p v-if="missing.length" class="audience-issue">Still needed: {{ missing.join(", ") }}</p>
    <div><Button :label="preview?.count ? `Use these ${preview.count.toLocaleString()} people` : 'Use these people'" variant="solid" :loading="busy" :disabled="!chosen || !ready" @click="submit" /></div>
  </div>
</template>

<style scoped>
.audience { display: grid; gap: 14px; margin-top: 12px; }
.audience-filters { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; align-items: end; }
.audience-field { display: grid; gap: 6px; font-size: 12px; color: var(--ink-gray-5); }
.audience-hint { font-size: 12.5px; color: var(--ink-gray-5); }
.audience-count { font-size: 14px; color: var(--ink-gray-8); display: grid; gap: 2px; }
.audience-count small, .audience-rows small, .audience-fixed small { font-size: 12px; color: var(--ink-gray-5); }
.audience-rows > div { display: grid; grid-template-columns: minmax(0, 1fr) 140px 90px auto; gap: 8px; align-items: center; padding: 4px 0; border-bottom: 1px solid var(--outline-gray-1); font-size: 13px; color: var(--ink-gray-8); }
.audience-manual, .audience-values { display: grid; gap: 8px; }
.audience-found { display: flex; justify-content: space-between; align-items: center; font-size: 13px; color: var(--ink-gray-8); }
.audience-chips { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; font-size: 12px; color: var(--ink-gray-5); }
.audience-value { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 8px; align-items: end; }
.audience-fixed { display: grid; gap: 6px; }
.audience-issue { color: var(--ink-red-4); font-size: 13px; }
@media (max-width: 768px) {
  .audience-filters, .audience-value { grid-template-columns: 1fr; }
  .audience-rows > div { grid-template-columns: minmax(0, 1fr) auto; }
}
</style>
