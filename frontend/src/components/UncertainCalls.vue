<script setup>
import { ref, watch } from "vue";
import { Button, FormControl, ErrorMessage } from "@relay/ui";
import RelaySelect from "./RelaySelect.vue";
import { coreApi } from "../services/coreApi";
const props = defineProps({ contact: String });
const rows = ref([]), before = ref(null), canResolve = ref(false), busy = ref(false), error = ref(""), selected = ref(null), outcome = ref("Not started"), evidence = ref(""), providerId = ref("");
let generation = 0;
async function load(older = false) {
  const current = ++generation;
  busy.value = true; error.value = "";
  try {
    const result = await coreApi("call_records.uncertain_attempts", {contact: props.contact, ...(older ? {before: before.value} : {})});
    if (current !== generation) return;
    rows.value = older ? [...rows.value, ...result.items].slice(-150) : result.items;
    before.value = result.before; canResolve.value = result.can_resolve;
  } catch (e) { if (current === generation) error.value = e.message; }
  finally { if (current === generation) busy.value = false; }
}
function review(row) { selected.value = row; outcome.value = "Not started"; evidence.value = ""; providerId.value = ""; error.value = ""; }
async function save() {
  if (busy.value) return;
  busy.value = true; error.value = "";
  try {
    await coreApi("call_records.resolve_attempt", {name:selected.value.name, outcome:outcome.value, evidence:evidence.value, provider_id:outcome.value === "Existing call" ? providerId.value : undefined}, true);
    selected.value = null; await load();
  } catch (e) { error.value = e.message; }
  finally { busy.value = false; }
}
watch(() => props.contact, () => {selected.value = null; load();}, {immediate:true});
</script>
<template>
  <section class="workflow-card space-y-3" aria-label="Unconfirmed calls">
    <div class="flex flex-wrap justify-between gap-2"><h2 class="font-semibold">Unconfirmed calls</h2><Button label="Refresh unconfirmed calls" :loading="busy" @click="load()" /></div>
    <ErrorMessage :message="error" />
    <p v-if="!rows.length && !busy" class="text-sm text-ink-gray-5">No unconfirmed attempts on this page.</p>
    <p v-if="rows.length" class="text-sm">The connection was lost before the call outcome was confirmed. Verify the provider’s call records before resolving an attempt.</p>
    <article v-for="row in rows" :key="row.name" class="border-b py-3 space-y-2 text-sm">
      <a class="underline" :href="'#/messages?contact='+encodeURIComponent(row.relay_contact)">{{ row.relay_contact }}</a>
      <p>{{ row.started_at }} · {{ row.requested_by }}</p>
      <Button v-if="canResolve" label="Review call outcome" :disabled="busy" @click="review(row)" />
      <p v-else>A communication manager can record the verified outcome.</p>
      <form v-if="selected?.name === row.name" class="space-y-3" @submit.prevent="save">
        <RelaySelect v-model="outcome" label="Verified outcome" :options="['Not started','Existing call']" :disabled="busy" />
        <FormControl v-if="outcome === 'Existing call'" v-model="providerId" label="Provider call ID" :disabled="busy" required />
        <p v-if="outcome === 'Existing call'">The outgoing call must already be present in this conversation’s call history.</p>
        <FormControl v-model="evidence" label="Verification evidence" type="textarea" :maxlength="2000" :disabled="busy" required />
        <p>Recording this outcome does not start or end a call.</p>
        <div class="flex gap-2"><Button type="submit" label="Record verified outcome" variant="solid" :loading="busy" :disabled="evidence.trim().length < 10 || (outcome === 'Existing call' && !providerId.trim())" /><Button label="Cancel review" :disabled="busy" @click="selected = null" /></div>
      </form>
    </article>
    <Button v-if="before" label="Earlier unconfirmed calls" :disabled="busy" @click="load(true)" />
  </section>
</template>
