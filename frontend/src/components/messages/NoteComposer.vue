<script setup>
import { computed, ref, nextTick, onMounted, watch } from "vue";
import { Button } from "@relay/ui";
import RemoteLinkField from "../fields/RemoteLinkField.vue";
import { businessScope } from "../../services/businessScope.js";
import { coreApi } from "../../services/coreApi";
import { stableSubmission } from "../../services/submission";
import { useStoredDraft } from "../../composables/useStoredDraft";

/** Internal note mode of the chat composer. Notes go to the team only and never to the customer. */
const props = defineProps({
  contact: String,
  businessDoctype: String,
  businessName: String,
  messages: { type: Array, default: () => [] },
  replyTo: Object,
});
const emit = defineEmits(["added", "clear-messages", "clear-reply", "busy"]);
const body = ref(""), busy = ref(false), error = ref(""), optionsOpen = ref(false);
const assignedTo = ref(""), mentions = ref([]), input = ref(null);
watch(busy, value => emit("busy", value));
const colleagueField = computed(() => ({ method: "collaboration.colleagues", params: { contact: props.contact }, readOnly: busy.value }));
const optionCount = computed(() => mentions.value.length + (assignedTo.value ? 1 : 0));
useStoredDraft(() => props.contact ? JSON.stringify(["note", document.getElementById("app")?.dataset.user, props.contact]) : "",
  () => ({ body: body.value, mentions: mentions.value, assignedTo: assignedTo.value }), saved => {
    body.value = typeof saved === 'string' ? saved : saved.body || '';
    mentions.value = saved.mentions || []; assignedTo.value = saved.assignedTo || '';
  });
onMounted(() => nextTick(() => { resize(); input.value?.focus(); }));
watch(body, () => nextTick(resize));

function selectMentions(values) {
  if (values.length > 10) { error.value = "Choose at most 10 colleagues"; return; }
  mentions.value = values;
}
async function submit() {
  if (busy.value || !body.value.trim() || body.value.length > 4000) return;
  busy.value = true;
  error.value = "";
  try {
    const payload = {
      ...businessScope(props),
      contact: props.contact,
      body: body.value,
      messages: props.messages.map((m) => m.name),
      reply_to: props.replyTo?.name,
      assigned_to: assignedTo.value || null,
      mentions: mentions.value,
    };
    await stableSubmission("relay-comment", payload, (key) =>
      coreApi("collaboration.add", { ...payload, request_key: key }, true),
    );
    body.value = "";
    assignedTo.value = "";
    mentions.value = [];
    optionsOpen.value = false;
    emit("added");
    emit("clear-messages");
    emit("clear-reply");
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
function keydown(event) {
  if (event.key !== "Enter" || event.shiftKey || event.isComposing || event.keyCode === 229) return;
  event.preventDefault();
  if (!event.repeat) submit();
}
function resize() {
  const node = input.value;
  if (!node) return;
  node.style.height = "auto";
  node.style.height = Math.min(node.scrollHeight, 130) + "px";
}
</script>

<template>
  <div class="note-composer">
    <div v-if="replyTo || messages.length" class="note-context">
      <span>{{ replyTo ? "Reply to " + replyTo.author_name + "'s note" : messages.length === 1 ? "Note about 1 message" : "Note about " + messages.length + " messages" }}</span>
      <Button icon="x" variant="ghost" :aria-label="replyTo ? 'Cancel note reply' : 'Remove linked messages'" :title="replyTo ? 'Cancel note reply' : 'Remove linked messages'"
        :disabled="busy" @click="emit(replyTo ? 'clear-reply' : 'clear-messages')" />
    </div>
    <div v-if="optionsOpen" class="note-options">
      <RemoteLinkField :field="{ ...colleagueField, label: 'Assign a task to (optional)' }" v-model="assignedTo" />
      <RemoteLinkField :field="{ ...colleagueField, label: 'Mention colleagues (up to 10)' }" :model-value="mentions" multiple @update:model-value="selectMentions" />
    </div>
    <p v-if="optionCount" class="note-summary">{{ mentions.length ? 'Mentioning ' + mentions.join(', ') : '' }}{{ assignedTo ? ' · Assigned to ' + assignedTo : '' }} ({{ optionCount }})</p>
    <p v-if="error" role="alert" class="note-error">{{ error }}</p>
    <p v-if="busy" role="status">Adding note…</p>
    <div class="note-input">
      <Button icon="at-sign" variant="ghost" aria-label="Mention or assign a colleague" title="Mention or assign a colleague" :aria-expanded="optionsOpen" :disabled="busy" @click="optionsOpen = !optionsOpen" />
      <textarea ref="input" v-model="body" aria-label="Internal note" placeholder="Write an internal note…"
        rows="1" maxlength="4000" :readonly="busy" @keydown="keydown" @input="resize" />
      <Button class="note-add" icon-left="lock" label="Add note" variant="solid" :loading="busy" :disabled="!body.trim() || body.length > 4000"
        :title="body.trim() ? 'Add note · Enter' : 'Type a note first'" @click="submit" />
    </div>
  </div>
</template>

<style scoped>
.note-composer { display:flex; flex-direction:column; gap:8px; min-width:0; }
.note-context, .note-options { display:flex; align-items:center; gap:8px; padding:0 6px; font-size:12px; color:var(--relay-note-ink); }
.note-context span { flex:1; }
.note-options { flex-direction:column; align-items:stretch; }
.note-input { display:flex; align-items:flex-end; gap:8px; padding:6px; border:1px solid var(--relay-note-ink); border-radius:10px; background:var(--relay-layer); color:var(--relay-note-ink); }
.note-input textarea { flex:1; min-width:0; min-height:44px; max-height:130px; padding:10px 4px; border:0; border-radius:6px; background:none; color:var(--relay-ink); font:inherit; font-size:14px; line-height:24px; resize:none; }
.note-input textarea::placeholder { color:var(--relay-ink-3); opacity:1; }
.note-error { font-size:13px; color:var(--relay-red); }
.note-summary { font-size:12px; overflow-wrap:anywhere; }
.note-add.relay-button, .note-add.relay-button:hover:not(:disabled) { flex:none; background:var(--relay-note-ink); border-color:var(--relay-note-ink); color:var(--relay-note-on-solid); }
.note-add.relay-button:disabled { opacity:.55; }
@media (max-width:768px) {
  .note-input { padding:5px; }
  .note-input textarea { font-size:16px; }
  .note-add :deep(svg) { display:none; }
  .note-add.relay-button { padding:0 10px; font-size:12px; }
}
</style>
