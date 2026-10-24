<script setup>
import { recordTitle } from '../services/recordTitle'
import { linkedTitle } from '../services/linkedTitle'
import { useRealtimeRefresh } from "../composables/useRealtimeRefresh";
import { onMounted, ref, watch } from "vue";
import { Button, ErrorMessage, FormControl } from "@relay/ui";
import RelaySelect from "./RelaySelect.vue";
import { coreApi } from "../services/coreApi";
const businesses = ref([]), business = ref("");
const rows = ref([]),
  next = ref(null),
  busy = ref(false),
  error = ref(""),
  selected = ref(null),
  query = ref(""),
  contacts = ref([]),
  contact = ref(""),
  notice = ref("");
watch(contact, async value => {
  business.value = ""; businesses.value = [];
  if (!value) return;
  try { const rows = await coreApi("enrollment.businesses", {contact:value}); if (contact.value === value) businesses.value = rows; }
  catch(e) { error.value = e.message; }
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
async function load(after) {
  const result = await coreApi("enrollment.pending", { after });
  rows.value = result.items;
  next.value = result.next;
}
async function search() {
  const result = await coreApi("api.contacts", {
    query: query.value,
    limit: 30,
  });
  contacts.value = result.items;
  if(selected.value?.contact && !contacts.value.some(row=>row.name===selected.value.contact))
    contacts.value.unshift({name:selected.value.contact,display_name:selected.value.endpoint});
}
async function choose(row) {
  selected.value = row;
  contact.value = row.contact || "";
  query.value = "";
  await run(search);
}
async function bind() {
  await run(async () => {
    await coreApi(
      "enrollment.bind",
      {
        event: selected.value.event,
        provider_id: selected.value.provider_id,
        contact: contact.value,
        ...JSON.parse(business.value),
      },
      true,
    );
    notice.value =
      "Sender linked. Its stored messages are being added to the inbox.";
    selected.value = null;
    await load();
  });
}
onMounted(() => run(() => load()));
useRealtimeRefresh([],['incoming'],()=>{if(!busy.value&&!selected.value)return run(()=>load())});
</script>
<template>
  <section class="incoming-workspace">
    <header>
      <div>
        <h2>Unlinked/ambiguous</h2>
        <p>
          Link incoming messages to the right business contact so your team can
          handle them.
        </p>
      </div>
      <Button label="Refresh" :disabled="busy" @click="run(() => load())" />
    </header>
    <ErrorMessage :message="error" />
    <p v-if="notice" role="status">{{ notice }}</p>
    <p v-if="busy" role="status">Loading / linking senders…</p>
    <div class="incoming-grid">
      <div>
        <article v-for="(row, index) in rows" :key="row.event + ':' + index">
          <template v-if="row.configuration_required"
            ><h3>Channel setup required</h3>
            <p>An incoming event could not be matched to an enabled channel.</p>
            <a href="/desk/relay-channel">Open channel settings</a></template
          ><template v-else
            ><div class="incoming-title">
              <strong>{{ row.endpoint }}</strong
              ><span>{{ row.medium }}</span>
            </div>
            <p class="incoming-preview">{{ row.preview }}</p>
            <small>{{ row.received_at }}</small
            ><Button :label="row.ambiguous ? 'Choose business' : 'Link sender'" :disabled="busy" @click="choose(row)"
          /></template>
        </article>
        <p v-if="!rows.length && !busy" class="incoming-empty">
          No unlinked or ambiguous incoming messages.
        </p>
        <Button
          v-if="next"
          label="Next incoming events"
          :disabled="busy"
          @click="run(() => load(next))"
        />
      </div>
      <form v-if="selected" @submit.prevent="bind">
        <ErrorMessage :message="error" />
        <h3>Link {{ selected.endpoint }}</h3>
        <p>
          Choose the business contact that owns this
          {{ selected.medium }} conversation.
        </p>
        <div class="flex gap-2 items-end">
          <FormControl label="Search contacts" v-model="query" /><Button
            label="Search"
            :disabled="busy"
            @click="run(search)"
          />
        </div>
        <RelaySelect
          label="Business contact"
          v-model="contact"
          :options="
            contacts.map((row) => ({
              value: row.name,
              label: recordTitle(row, 'Contact'),
            }))
          "
        />
        <RelaySelect label="Business record" v-model="business" :options="businesses.map(row => ({value:JSON.stringify({business_doctype:row.doctype,business_name:row.name}),label:linkedTitle(row.doctype, row.name)}))" />
        <p class="text-xs text-ink-gray-5">
          Missing a contact? Create it and its business link in
          <a href="/desk/relay-contact" target="_blank" rel="noopener"
            >Frappe Desk</a
          >, then search again.
        </p>
        <Button
          label="Link sender and load history"
          type="submit"
          variant="solid"
          :disabled="busy || !contact || !business"
        /><Button label="Cancel" :disabled="busy" @click="selected = null" />
      </form>
    </div>
  </section>
</template>
<style scoped>
.incoming-workspace {
  padding: 24px;
  overflow: auto;
  height: 100%;
}
.incoming-workspace header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 24px;
}
.incoming-workspace h2 {
  font-size: 18px;
  font-weight: 600;
}
.incoming-workspace header p,
.incoming-workspace form > p {
  font-size: 13px;
  color: #7b8490;
  margin-top: 6px;
}
.incoming-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(280px, 360px);
  gap: 24px;
  max-width: 1100px;
}
.incoming-grid article,
.incoming-grid form {
  border: 1px solid #e5e7eb;
  border-radius: 9px;
  padding: 16px;
  margin-bottom: 12px;
}
.incoming-title {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
}
.incoming-title span,
.incoming-grid small {
  color: #7b8490;
  font-size: 11px;
}
.incoming-preview {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  margin: 12px 0;
  font-size: 14px;
}
.incoming-grid article button {
  display: block;
  margin-top: 12px;
}
.incoming-grid form {
  display: flex;
  flex-direction: column;
  gap: 14px;
  align-self: start;
}
.incoming-grid h3 {
  font-weight: 600;
}
.incoming-empty {
  color: #7b8490;
  padding: 30px;
  text-align: center;
}
@media (max-width: 700px) {
  .incoming-grid {
    grid-template-columns: 1fr;
  }
  .incoming-workspace {
    padding: 16px;
  }
}
</style>
