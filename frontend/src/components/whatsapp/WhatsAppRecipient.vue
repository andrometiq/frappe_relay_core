<script setup>
import { inject } from "vue";
import { Button, FormControl, Badge } from "@relay/ui";
import RelaySelect from "../RelaySelect.vue";
import BusinessRecordPicker from "../BusinessRecordPicker.vue";
import WhatsAppMessages from "./WhatsAppMessages.vue";
import WhatsAppCalls from "./WhatsAppCalls.vue";
import { whatsappKey } from "../../composables/whatsapp/context";
const {
  bulkContacts,
  tab,
  busy,
  moreContacts,
  recordType,
  record,
  contacts,
  contact,
  text,
  name,
  template,
  selectedTemplate,
  supported,
  loadContacts,
  sendTemplate,
} = inject(whatsappKey);
</script>
<template>
  <section class="workflow-card">
    <BusinessRecordPicker
      v-model:doctype="recordType"
      v-model:record="record"
      :disabled="busy"
    />
    <Button
      label="Find contacts"
      :disabled="busy || !supported || !record"
      @click="loadContacts(false)"
    /><Button
      v-if="moreContacts"
      label="Next contacts"
      :disabled="busy"
      @click="loadContacts(true)"
    /><RelaySelect
      label="Recipient contact"
      v-model="contact"
      :options="
        contacts.map((c) => ({
          label:
            (c.full_name || c.name) + (c.mobile_no ? ' · ' + c.mobile_no : ''),
          value: c.name,
        }))
      "
    />
    <WhatsAppMessages v-if="tab === 'Messages'" />
    <div v-if="tab === 'Templates' && contacts.length > 1" class="space-y-2">
      <span class="text-sm text-ink-gray-5">Bulk recipients</span
      ><label
        v-for="c in contacts"
        :key="c.name"
        class="flex items-center gap-2 text-sm"
        ><input type="checkbox" :value="c.name" v-model="bulkContacts" />{{
          c.full_name || c.name
        }}</label
      >
    </div>
    <Button
      v-if="tab === 'Templates'"
      label="Send template"
      :disabled="
        busy ||
        !supported ||
        (!contact && !bulkContacts.length) ||
        selectedTemplate?.status !== 'APPROVED'
      "
      @click="sendTemplate"
    />
    <WhatsAppCalls v-if="tab === 'Calls'" />
  </section>
</template>
