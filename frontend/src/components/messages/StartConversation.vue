<script setup>
import { ref, computed, inject, watch, onMounted, onBeforeUnmount } from "vue";
import { Button, FormControl, ErrorMessage, Dialog, TextInput, FeatherIcon } from "@relay/ui";
import ChoiceField from "../fields/ChoiceField.vue";
import RelaySelect from "../RelaySelect.vue";
import TemplateMediaField from "./TemplateMediaField.vue";
import { coreApi } from "../../services/coreApi";
import { useStoredDraft } from '../../composables/useStoredDraft';
import { useEnabledChannels } from "../../composables/useEnabledChannels";
import { channelCan } from "../../services/enabledChannels";
import { sha256Hex, randomUUID } from "../../services/crypto";
import { readableName } from "../../services/recordTitle";
import {
  templateParameterDescriptors,
  buildTemplateComponents,
  templateRendering,
} from "../../services/templateParameters";
// `channel` is the WhatsApp number staff picked in "Send via"; the message and its templates go through that number.
// A business record lists one endpoint per number, so the picked number is preselected there and staff may change it.
// `template` opens straight on an approved template for this chat, as when its reply window is closed.
const props = defineProps({ contact: String, contactLabel:String, contacts:Array, businessDoctype:String, businessName:String, channel:String, template:Boolean });
const emit = defineEmits(["close", "sent"]);
const channelEnabled = useEnabledChannels();
const capabilities = inject("relayCapabilities", ref({}));
const sendChannel = computed(() => props.businessName ? destination.value?.channel || "" : props.channel);
// A header file is uploaded through the number that sends the template.
const mediaChannel = computed(() => sendChannel.value || destination.value?.channel || "");
const numberLabel = computed(() => {
  const row = (capabilities.value.whatsapp_numbers || []).find(item => item.name === sendChannel.value);
  return row ? [row.label, row.address].filter(Boolean).join(' · ') : '';
});
const can = feature => channelCan(capabilities.value, destination.value?.provider, feature);
const shown = ref(true),
  contact = ref(props.contact || ""),
  endpoint = ref(""),
  endpoints = ref([]),
  busy = ref(false),
  error = ref(""),
  notice = ref(""),
  body = ref(""),
  subject = ref(""),
  kind = ref(props.channel || props.template ? "template" : "text");
const contactQuery = ref(""), contactOptions = ref([]), contactsBusy = ref(false), contactsError = ref("");
// A contact with several records and no primary picks the record the new chat belongs to.
const records = ref([]), record = ref("");
const chosenRecord = computed(() => records.value.find(row => row.value === record.value));
const businessDoctype = computed(() => props.businessDoctype || chosenRecord.value?.doctype);
const businessName = computed(() => props.businessName || chosenRecord.value?.name);
const templates = ref([]),
  templateId = ref(""),
  parameters = ref({}),
  cursor = ref(""),
  pending = ref(null),
  renewRequestKey = ref(false);
const destination = computed(() =>
  endpoints.value.find((row) => row.value === endpoint.value),
);
const template = computed(() =>
  templates.value.find((row) => row.id === templateId.value),
);
const descriptors = computed(() =>
  templateParameterDescriptors(template.value),
);
const rendering = computed(() => template.value ? templateRendering(template.value, descriptors.value, parameters.value) : null);
const templatesBusy = ref(false), templatesError = ref("");
let templatesGeneration = 0;
let generation = 0;
let contactGeneration = 0, contactTimer, contactController;

// A phone number as a name looks like a generated key to recordTitle, which would caption it "Record".
const contactCaption = (value, fallback) => /^\d{7,}$/.test(String(value || "").trim()) ? "+" + String(value).trim() : readableName(value, fallback);
async function searchDirectory(query, signal) {
  const result = await coreApi("inbox.directory", { query }, false, { signal });
  return (result.items || []).map(row => ({ value: row.name, label: contactCaption(row.display_name, "Contact") }));
}
const contactField = computed(() => ({ label: "Contact", placeholder: "Search by name or number…", search: searchDirectory, readOnly: busy.value || !!pending.value,
  initialOptions: contact.value ? [{ value: contact.value, label: props.contactLabel || contactCaption(contact.value, "Contact") }] : [] }));

function initialContacts() {
  const rows = Array.isArray(props.contacts) ? props.contacts : [];
  if (rows.length || !props.contact) return rows;
  return [{ value: props.contact, label: props.contactLabel || readableName(props.contact, "Contact"), description: "", has_phone: true }];
}
function resetContacts() {
  contactOptions.value = initialContacts();
  contactsError.value = "";
}
async function searchContacts() {
  contactController?.abort();
  if (!props.businessName || !contactQuery.value.trim()) { resetContacts(); return; }
  const current = ++contactGeneration;
  contactController = new AbortController();
  contactsBusy.value = true; contactsError.value = "";
  try {
    const result = await coreApi("business_inbox.contacts", {
      doctype: props.businessDoctype, name: props.businessName, query: contactQuery.value,
    }, false, { signal: contactController.signal });
    if (current === contactGeneration) contactOptions.value = result.items || [];
  } catch (e) {
    if (current === contactGeneration && e.name !== "AbortError") contactsError.value = e.message;
  } finally {
    if (current === contactGeneration) contactsBusy.value = false;
  }
}
function chooseContact(row) {
  if (busy.value || pending.value) return;
  contact.value = row.value;
}
watch(() => props.contacts, resetContacts, { immediate: true, deep: true });
watch(contactQuery, () => {
  clearTimeout(contactTimer); ++contactGeneration; contactController?.abort(); contactsBusy.value = false;
  if (!contactQuery.value.trim()) resetContacts();
  else contactTimer = setTimeout(searchContacts, 300);
});
watch(shown, (value) => {
  if (!value) emit("close");
});
async function run(fn) {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    await fn();
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
async function destinations() {
  const current = ++generation;
  endpoint.value = "";
  endpoints.value = [];
  try {
    const result = await coreApi(
      props.businessName ? "conversation_start.business_options" : "conversation_start.options",
      { contact: contact.value,
        business_doctype:businessDoctype.value,business_name:businessName.value,
        ...(props.businessName && props.channel ? { channel: props.channel } : {}) },
      !!props.businessName,
    );
    if (current !== generation) return;
    endpoints.value = result.filter(row => channelEnabled(row.provider) && (!props.channel || row.provider === 'WhatsApp')).map(row => ({...row, value: props.businessName ? row.endpoint : row.value, channel: props.businessName ? row.value : row.channel}));
    endpoint.value = (endpoints.value.find(row => props.businessName && row.channel === props.channel) || endpoints.value[0])?.value || "";
    if (!endpoints.value.length && !props.businessName && !record.value) await loadRecords(current);
  } catch (e) {
    if (current === generation) error.value = e.message;
  }
}
async function loadRecords(current) {
  const rows = await coreApi("conversation_start.records", { contact: contact.value });
  if (current !== generation) return;
  records.value = rows.map(row => ({ value: row.doctype + "\n" + row.name, label: row.title + " · " + row.doctype, doctype: row.doctype, name: row.name }));
}
watch(record, () => { if (record.value && contact.value) destinations(); });
watch(contact, () => {
  records.value = [];
  record.value = '';
  endpoint.value = '';
  pending.value = null;
  renewRequestKey.value = false;
  body.value = "";
  subject.value = "";
  if (contact.value) destinations();
}, {flush:'sync'});
watch(templateId, () => (parameters.value = {}), {flush:'sync'});

watch(sendChannel, (_now, before) => { if (before) { templateId.value = ''; parameters.value = {}; } }, {flush: 'sync'});
watch(mediaChannel, (_now, before) => { if (before) for (const field of descriptors.value) if (field.kind === 'media') delete parameters.value[field.key]; });
const clearDraft = useStoredDraft(
  () => endpoint.value ? JSON.stringify(['start', document.getElementById('app')?.dataset.user, props.businessDoctype, props.businessName, contact.value, endpoint.value]) : '',
  () => ({body:body.value,subject:subject.value,kind:kind.value,templateId:templateId.value,parameters:parameters.value,pending:pending.value,renewRequestKey:renewRequestKey.value}),
  saved => { body.value=saved.body || ''; subject.value=saved.subject || ''; kind.value=props.template ? 'template' : saved.kind || 'text'; templateId.value=saved.templateId || ''; parameters.value=saved.parameters || {}; pending.value=saved.pending || null; renewRequestKey.value=!!saved.renewRequestKey; },
  () => ({body:'',subject:'',kind:props.template ? 'template' : can('email_threading') ? 'email' : can('reply_window_hours') && !destination.value.window.open ? 'template' : 'text',templateId:'',parameters:{},pending:null}));
let templateRequest;
function loadTemplates(next = false) {
  if (templatesBusy.value) return templateRequest;
  templateRequest = fetchTemplates(next);
  return templateRequest;
}
async function fetchTemplates(next) {
  const current = ++templatesGeneration, channel = sendChannel.value;
  templatesBusy.value = true; templatesError.value = "";
  try {
    const result = await coreApi("whatsapp.execute", {
      operation: "templates.list", arguments: next && cursor.value ? {after: cursor.value} : {},
      ...(channel ? {channel} : {}),
    }, true);
    if (current !== templatesGeneration) return;
    templates.value = [...(next ? templates.value : []), ...(result.data || []).filter(row => row.status === "APPROVED")];
    cursor.value = result.paging?.has_more ? result.paging?.cursors?.after || "" : "";
    if (!templateId.value) templateId.value = templates.value[0]?.id || "";
  } catch (e) { if (current === templatesGeneration) templatesError.value = e.message; }
  finally { if (current === templatesGeneration) templatesBusy.value = false; }
}
watch(() => kind.value === 'template' && destination.value?.provider === 'WhatsApp' ? sendChannel.value || 'default' : '', scope => {
  ++templatesGeneration; templatesBusy.value = false; templatesError.value = "";
  templates.value = []; cursor.value = "";
  if (scope) loadTemplates();
}, {immediate: true, flush: 'sync'});
onBeforeUnmount(() => { ++templatesGeneration; });

function sendPayload() {
  const data = kind.value === "email" ? {subject:subject.value, body:body.value}
    : kind.value === "text" ? {text:body.value}
    : {name:template.value?.name, language:template.value?.language,
        components:buildTemplateComponents(descriptors.value, parameters.value)};
  return {
    contact:contact.value,
    business_doctype:businessDoctype.value, business_name:businessName.value,
    endpoint:endpoint.value, kind:kind.value, data,
    ...(props.channel && !props.businessName ? { channel: props.channel } : {}),
  };
}
function editRejected() {
  if (busy.value || pending.value?.status !== "Rejected") return;
  if (pending.value.storage) sessionStorage.removeItem(pending.value.storage);
  // Old drafts have no storage key and their template metadata may not be loaded.
  renewRequestKey.value = true;
  pending.value = null;
  notice.value = "";
}
async function send() {
  if (pending.value?.status === "Rejected") return;
  await run(async () => {
    let result, storage = pending.value?.storage;
    if (pending.value) {
      result = await coreApi(
        "messaging.reconcile",
        { action: pending.value.action },
        true,
      );
    } else {
      if (kind.value === "template" && !template.value) throw Error("Choose an approved template");
      const payload = sendPayload();
      const data = payload.data;
      storage = "relay-start-" + sha256Hex(JSON.stringify(payload));
      if (renewRequestKey.value) sessionStorage.removeItem(storage);
      let key = sessionStorage.getItem(storage);
      if (!key) {
        key = randomUUID();
        sessionStorage.setItem(storage, key);
      }
      renewRequestKey.value = false;
      result = await coreApi(
        props.businessName ? "conversation_start.send_business" : "conversation_start.send",
        props.businessName
          ? { contact:contact.value, channel:destination.value.channel, endpoint:endpoint.value, kind:kind.value, data,
              business_doctype:props.businessDoctype,business_name:props.businessName,request_key:key }
          : { ...payload, request_key: key },
        true,
      );
    }
    if (["Submitted", "Queued"].includes(result.status)) {
      if (storage) sessionStorage.removeItem(storage);
      clearDraft();
      notice.value = result.status === "Queued" ? "Queued for sending" : destination.value?.provider === "Email" ? "SMTP accepted" : destination.value?.provider === "Telegram" ? "Bot accepted" : "Sent";
      emit("sent", { contact: contact.value,
      business_doctype:businessDoctype.value,business_name:businessName.value, message: result.message, status: result.status });
      shown.value = false;
    } else {
      pending.value = {...result, storage};
      notice.value = result.error || (
        result.status === "Rejected"
          ? "Delivery was rejected. Review the channel and message before preparing another send."
          : "The send outcome is unknown. Check delivery or open the conversation to follow this attempt.");
    }
  });
}
onMounted(async () => {
  if (contact.value) await destinations();
});
onBeforeUnmount(() => { clearTimeout(contactTimer); ++contactGeneration; contactController?.abort(); });
</script>
<template>
  <Dialog v-model="shown" :options="{ title: props.template ? 'Send approved template' : 'New conversation', size: 'lg' }"
    ><template #body-content
      ><div class="space-y-4">
        <div v-if="props.businessName" class="start-contact-picker">
          <label>Business contact</label>
          <TextInput v-model="contactQuery" type="search" placeholder="Search linked contacts…"
            aria-label="Search linked contacts" :disabled="busy || !!pending">
            <template #prefix><FeatherIcon name="search" class="h-4 w-4 text-ink-gray-5" /></template>
          </TextInput>
          <div class="start-contact-results" role="listbox" aria-label="Linked business contacts">
            <button v-for="row in contactOptions" :key="row.value" type="button" role="option"
              :aria-selected="contact === row.value" :disabled="busy || !!pending"
              :class="{ selected: contact === row.value }" @click="chooseContact(row)">
              <span class="contact-chip-avatar" aria-hidden="true">{{ row.label.slice(0, 1).toUpperCase() }}</span>
              <span class="start-contact-copy"><strong>{{ row.label }}</strong>
                <small>{{ row.description || "Review verified channels" }}</small></span>
              <FeatherIcon v-if="contact === row.value" name="check" class="h-4 w-4" />
            </button>
            <p v-if="contactsBusy" role="status">Searching contacts…</p>
            <p v-else-if="contactsError" role="alert">{{ contactsError }}</p>
            <p v-else-if="!contactOptions.length">No linked contacts match this search.</p>
          </div>
        </div>
        <ChoiceField v-else v-model="contact" :field="contactField" />
        <ChoiceField v-if="records.length" v-model="record" :field="{ label: 'Business record', options: records, readOnly: busy || !!pending }" />
        <ChoiceField v-if="endpoints.length" v-model="endpoint" :field="{ label: 'Send through', options: endpoints, readOnly: busy || !!pending }" />
        <p v-else-if="contact && records.length && !record" class="text-sm text-ink-gray-5">This contact has several records. Choose the one this chat is for.</p>
        <p v-else-if="contact" class="text-sm text-ink-gray-5">
          {{ props.businessName
            ? "This contact has no number we can send to. Add a mobile number to the contact."
            : "This contact has no WhatsApp number we can send to. Add a mobile number to the contact." }}
        </p>
        <template v-if="destination">
          <p v-if="channel && numberLabel" class="text-sm">Sends an approved template through {{ numberLabel }}.</p>
          <p v-else-if="can('reply_window_hours')" class="text-sm">
            {{
              destination.window.open
                ? "The reply window is open. You can send a message or an approved template."
                : "The reply window is closed. Choose an approved template."
            }}
          </p>
          <RelaySelect
            v-if="can('templates')"
            label="Message type"
            v-model="kind"
            :disabled="busy || !!pending"
            :options="[
              ...(destination.window.open && !channel
                ? [{ value: 'text', label: 'Message' }]
                : []),
              { value: 'template', label: 'Approved template' },
            ]"
          />
          <FormControl v-if="kind === 'email'" v-model="subject" label="Subject" :disabled="busy || !!pending" maxlength="998" />
          <p v-if="destination.provider === 'Telegram'" class="text-xs">Private Telegram chat · {{ [...body].length }} / 4096 characters</p>
          <FormControl
            v-if="kind !== 'template'"
            label="Message"
            type="textarea"
            v-model="body"
            :disabled="busy || !!pending"
          />
          <template v-else
            >
            <p v-if="templatesBusy" role="status">Loading approved templates…</p>
            <ErrorMessage :message="templatesError" />
            <Button v-if="templatesError" label="Retry templates" @click="loadTemplates()" />
            <ChoiceField v-model="templateId" :field="{ label: 'Template', options: templates.map(row => ({ value: row.id, label: row.name + ' · ' + row.language })), readOnly: busy || !!pending, loading: templatesBusy, error: templatesError, hasMore: !!cursor, loadMore: () => loadTemplates(true) }"
              /><template v-for="field in descriptors" :key="field.key">
              <TemplateMediaField v-if="field.kind === 'media'" v-model="parameters[field.key]" :field="field"
                :channel="mediaChannel" :disabled="busy || !!pending" />
              <FormControl v-else :label="field.label" v-model="parameters[field.key]" :disabled="busy || !!pending" />
            </template>
            <div v-if="rendering" class="flex flex-col gap-1 whitespace-pre-wrap rounded-lg bg-surface-gray-2 p-3 text-sm" aria-label="Template preview">
              <strong v-if="rendering.header">{{ rendering.header }}</strong>
              <img v-if="rendering.media === 'image' && rendering.mediaUrl" :key="rendering.mediaUrl" :src="rendering.mediaUrl" alt="Image header" class="max-h-40 w-full rounded object-cover" referrerpolicy="no-referrer" @error="$event.target.remove()" />
              <em v-else-if="rendering.media" class="capitalize">{{ rendering.media }} header</em>
              <p>{{ rendering.body }}</p>
              <small v-if="rendering.footer" class="text-ink-gray-5">{{ rendering.footer }}</small>
              <span v-for="(button, index) in rendering.buttons" :key="index" class="rounded border border-outline-gray-2 px-2 py-1 text-center">{{ button.text }}</span>
            </div></template>
        </template>
        <ErrorMessage :message="error" />
        <p v-if="notice" role="status" class="text-sm">{{ notice }}</p>
        <Button v-if="pending?.status === 'Rejected'" label="Edit message" :disabled="busy" @click="editRejected" />
        <Button
          v-else
          :label="pending ? 'Check delivery' : 'Send message'"
          variant="solid"
          :loading="busy"
          :disabled="
            !destination ||
            (!pending && (kind !== 'template' ? (!body.trim() || (kind === 'email' && !subject.trim()) || (destination.provider === 'Telegram' && [...body].length > 4096)) : !template))
          "
          @click="send"
        />
        <Button v-if="pending" label="Open conversation" @click="emit('sent',{contact:contact,message:pending.message,status:pending.status});shown=false" />
</div></template
  ></Dialog>
</template>
