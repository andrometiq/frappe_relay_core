<script setup>
import { computed, onMounted, reactive, ref, watch } from "vue";
import { Badge, Button, ErrorMessage, TextInput } from "@relay/ui";
import RelaySelect from "../RelaySelect.vue";
import { useCampaignAudience } from "../../composables/useCampaignAudience";
import { audienceSummary, cleanAudience, dropContact, missingValues, pickContact, valueOptions } from "../../services/campaignAudience";

const props = defineProps({ campaign: Object, uploadMedia: Function });
const emit = defineEmits(["imported"]);
const campaign = computed(() => props.campaign);
const { options, audience, mapping, preview, found, error, busy, counting, load, search, importContacts } = useCampaignAudience(campaign);
const query = ref(""), mediaFile = ref("");
const known = reactive({});

const tagOptions = computed(() => [{ value: "", label: "Any tag" }, ...(options.value?.tags || [])]);
const typeOptions = computed(() => [{ value: "", label: "Any record" }, ...(options.value?.types || []).map((row) => row.doctype)]);
const segments = computed(() => options.value?.types.find((row) => row.doctype === audience.value.doctype)?.segments || []);
const missing = computed(() => missingValues(props.campaign.fields, mapping.value));
const ready = computed(() => preview.value?.count > 0 && !missing.value.length);

const filtered = computed(() => Object.keys(cleanAudience(audience.value)).some((key) => key !== "include" && key !== "exclude"));
// Names of contacts seen in the list or the search, for the added and removed chips.
watch(() => [preview.value?.sample, found.value], (lists) => { for (const row of lists.flat()) if (row) known[row.contact] = row; });
const label = (contact) => known[contact] ? `${known[contact].name} · +${known[contact].number}` : contact;

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
    <div class="audience-filters">
      <RelaySelect v-model="audience.tag" label="Tag" :options="tagOptions" />
      <RelaySelect :model-value="audience.doctype" label="Linked to" :options="typeOptions" @update:model-value="chooseType" />
      <RelaySelect v-for="segment in segments" :key="segment.field" :model-value="audience.segments[segment.field] || ''"
        :label="segment.label" :options="[{ value: '', label: 'Any' }, ...segment.options]" @update:model-value="setSegment(segment.field, $event)" />
      <label class="audience-field"><span>Number contains</span><TextInput v-model="audience.number" inputmode="numeric" placeholder="9198" /></label>
      <label class="audience-field"><span>Last message from</span><TextInput v-model="audience.last_message_from" type="date" /></label>
      <label class="audience-field"><span>Last message to</span><TextInput v-model="audience.last_message_to" type="date" /></label>
    </div>
    <p class="audience-count" role="status">{{ counting && !preview ? "Counting…" : audienceSummary(preview) }}
      <small v-if="!filtered">No filter: every contact on this number.</small></p>

    <div v-if="preview?.sample.length" class="audience-rows" role="table" aria-label="Matched contacts">
      <div v-for="row in preview.sample" :key="row.contact + row.number" role="row">
        <span>{{ row.name }}</span><span>+{{ row.number }}</span>
        <Badge v-if="row.opted_out" label="Opted out" theme="orange" /><span v-else />
        <Button label="Remove" variant="ghost" @click="remove(row.contact)" />
      </div>
      <small v-if="preview.count > preview.sample.length">and {{ (preview.count - preview.sample.length).toLocaleString() }} more</small>
    </div>

    <div class="audience-manual">
      <label class="audience-field"><span>Add a contact</span>
        <TextInput v-model="query" placeholder="Name or number" @update:model-value="search" /></label>
      <div v-for="row in found" :key="'found' + row.contact + row.number" class="audience-found">
        <span>{{ row.name }} · +{{ row.number }}</span><Button label="Add" variant="subtle" @click="add(row.contact)" />
      </div>
      <div v-if="audience.include.length" class="audience-chips"><span>Added</span>
        <Button v-for="contact in audience.include" :key="'in' + contact" :label="label(contact)" icon-right="x" variant="subtle" @click="undo(contact, 'include')" /></div>
      <div v-if="audience.exclude.length" class="audience-chips"><span>Removed</span>
        <Button v-for="contact in audience.exclude" :key="'out' + contact" :label="label(contact)" icon-right="x" variant="subtle" @click="undo(contact, 'exclude')" /></div>
    </div>

    <div v-if="campaign.fields.length" class="audience-values">
      <strong>Message values</strong>
      <div v-for="field in campaign.fields" :key="field.key" class="audience-value">
        <RelaySelect :model-value="mapping.fields[field.key] || ''" :label="field.label" :options="valueOptions(field, options?.sources || [])"
          @update:model-value="setSource(field.key, $event)" />
        <div v-if="!mapping.fields[field.key]" class="audience-fixed">
          <input v-if="field.component === 'media'" type="file" :aria-label="`${field.label} file`" @change="chooseMedia" />
          <small v-if="field.component === 'media'">{{ mediaFile || "Upload one file for every contact, or paste an HTTPS link." }}</small>
          <TextInput v-model="mapping.fixed[field.key]" :placeholder="field.media ? 'https://…' : 'Same value for every contact'" :aria-label="`${field.label} fixed value`" />
        </div>
      </div>
    </div>
    <p v-if="missing.length" class="audience-issue">Still needed: {{ missing.join(", ") }}</p>
    <div><Button :label="preview?.count ? `Add ${preview.count.toLocaleString()} numbers` : 'Add numbers'" variant="solid" :loading="busy" :disabled="!ready" @click="submit" /></div>
  </div>
</template>

<style scoped>
.audience { display: grid; gap: 14px; margin-top: 12px; }
.audience-filters { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; align-items: end; }
.audience-field { display: grid; gap: 6px; font-size: 12px; color: var(--ink-gray-5); }
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
