<script setup>
import { ref, computed, inject, watch, onMounted, onBeforeUnmount } from "vue";
import { Button, FormControl, ErrorMessage, Dialog, TextInput, FeatherIcon } from "@relay/ui";
import RemoteLinkField from "../fields/RemoteLinkField.vue";
import RelaySelect from "../RelaySelect.vue";
import { coreApi } from "../../services/coreApi";
import { useStoredDraft } from '../../composables/useStoredDraft';
import { useEnabledChannels } from "../../composables/useEnabledChannels";
import { channelCan } from "../../services/enabledChannels";
import { sha256Hex, randomUUID } from "../../services/crypto";
import {
  templateParameterDescriptors,
  buildTemplateComponents,
} from "../../services/templateParameters";
const props = defineProps({ contact: String, contactLabel:String, contacts:Array, businessDoctype:String, businessName:String });
const emit = defineEmits(["close", "sent"]);
const channelEnabled = useEnabledChannels();
const capabilities = inject("relayCapabilities", ref({}));
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
  kind = ref("text");
const contactQuery = ref(""), contactOptions = ref([]), contactsBusy = ref(false), contactsError = ref("");
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
let generation = 0;
let contactGeneration = 0, contactTimer, contactController;

function initialContacts() {
  const rows = Array.isArray(props.contacts) ? props.contacts : [];
  if (rows.length || !props.contact) return rows;
  return [{ value: props.contact, label: props.contactLabel || props.contact, description: "", has_phone: true }];
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
        business_doctype:props.businessDoctype,business_name:props.businessName },
    );
    if (current !== generation) return;
    endpoints.value = result.filter(row => channelEnabled(row.provider)).map(row => ({...row, value: props.businessName ? row.endpoint : row.value, channel: props.businessName ? row.value : undefined}));
    endpoint.value = endpoints.value[0]?.value || "";
  } catch (e) {
    if (current === generation) error.value = e.message;
  }
}
watch(contact, () => {
  endpoint.value = '';
  pending.value = null;
  renewRequestKey.value = false;
  body.value = "";
  subject.value = "";
  if (contact.value) destinations();
}, {flush:'sync'});
watch(templateId, () => (parameters.value = {}), {flush:'sync'});
const clearDraft = useStoredDraft(
  () => endpoint.value ? JSON.stringify(['start', document.getElementById('app')?.dataset.user, props.businessDoctype, props.businessName, contact.value, endpoint.value]) : '',
  () => ({body:body.value,subject:subject.value,kind:kind.value,templateId:templateId.value,parameters:parameters.value,pending:pending.value,renewRequestKey:renewRequestKey.value}),
  saved => { body.value=saved.body || ''; subject.value=saved.subject || ''; kind.value=saved.kind || 'text'; templateId.value=saved.templateId || ''; parameters.value=saved.parameters || {}; pending.value=saved.pending || null; renewRequestKey.value=!!saved.renewRequestKey; },
  () => ({body:'',subject:'',kind:can('email_threading') ? 'email' : can('reply_window_hours') && !destination.value.window.open ? 'template' : 'text',templateId:'',parameters:{},pending:null}));
async function loadTemplates(next = false) {
  await run(async () => {
    const result = await coreApi(
      "whatsapp.execute",
      {
        operation: "templates.list",
        arguments: { ...(next && cursor.value ? { after: cursor.value } : {}) },
      },
      true,
    );
    templates.value = (result.data || []).filter(
      (row) => row.status === "APPROVED",
    );
    cursor.value = result.paging?.has_more
      ? result.paging?.cursors?.after || ""
      : "";
    templateId.value = templates.value[0]?.id || "";
  });
}
function sendPayload() {
  const data = kind.value === "email" ? {subject:subject.value, body:body.value}
    : kind.value === "text" ? {text:body.value}
    : {name:template.value?.name, language:template.value?.language,
        components:buildTemplateComponents(descriptors.value, parameters.value)};
  return {
    contact:contact.value,
    business_doctype:props.businessDoctype, business_name:props.businessName,
    endpoint:endpoint.value, kind:kind.value, data,
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
      business_doctype:props.businessDoctype,business_name:props.businessName, message: result.message, status: result.status });
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
  <Dialog v-model="shown" :options="{ title: 'New conversation', size: 'lg' }"
    ><template #body-content
      ><div class="space-y-4">
        <div v-if="businessName" class="start-contact-picker">
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
        <RemoteLinkField v-else v-model="contact" :field="{label:'Contact',method:'inbox.directory',params:{},placeholder:'Search contacts…',inlineResults:true,initialOptions:contact?[{value:contact,label:contactLabel||contact}]:[],readOnly:busy||!!pending}" />
        <RelaySelect
          v-if="endpoints.length"
          label="Send through"
          v-model="endpoint"
          :disabled="busy || !!pending"
          :options="endpoints"
        />
        <p v-else-if="contact" class="text-sm text-ink-gray-5">
          {{ businessName
            ? "No verified channel is available for this contact. Enroll an authenticated identity in Contacts & links."
            : "No eligible channel identity is available. Review the contact’s binding in Desk, or choose its business record from Business context when it has multiple links." }}
        </p>
        <template v-if="destination">
          <p v-if="can('reply_window_hours')" class="text-sm">
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
              ...(destination.window.open
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
            ><Button
              label="Load approved templates"
              @click="loadTemplates(false)"
              :disabled="busy || !!pending" /><Button
              v-if="cursor"
              label="Next templates"
              @click="loadTemplates(true)"
              :disabled="busy || !!pending" /><RelaySelect
              label="Template"
              v-model="templateId"
              :options="
                templates.map((row) => ({
                  value: row.id,
                  label: row.name + ' · ' + row.language,
                }))
              "
              :disabled="busy || !!pending" /><FormControl
              v-for="field in descriptors"
              :key="field.key"
              :label="field.label"
              v-model="parameters[field.key]"
              :disabled="busy || !!pending"
          /></template>
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
        <Button
          label="Close"
          :disabled="busy"
          @click="shown = false"
        /></div></template
  ></Dialog>
</template>
