<script setup>
import { computed, ref, nextTick, onMounted } from "vue";
import { Button, FeatherIcon } from "@relay/ui";
import RemoteLinkField from "../fields/RemoteLinkField.vue";
import { businessScope } from "../../services/businessScope.js";
import { coreApi } from "../../services/coreApi";
import { stableSubmission } from "../../services/submission";
import { useStoredDraft } from "../../composables/useStoredDraft";
import { useMobileLayout } from "../../composables/useMobileLayout";

/** Internal note mode of the chat composer. Notes go to the team only and never to the customer. */
const props = defineProps({
  contact: String,
  businessDoctype: String,
  businessName: String,
  messages: { type: Array, default: () => [] },
  replyTo: Object,
});
const emit = defineEmits(["added", "clear-messages", "clear-reply"]);
const isMobile = useMobileLayout();
const body = ref(""), busy = ref(false), error = ref(""), optionsOpen = ref(false);
const assignedTo = ref(""), mentions = ref([]), input = ref(null);
const colleagueField = computed(() => ({ method: "collaboration.colleagues", params: { contact: props.contact }, readOnly: busy.value }));
const optionCount = computed(() => mentions.value.length + (assignedTo.value ? 1 : 0));
useStoredDraft(() => props.contact ? JSON.stringify(["note", document.getElementById("app")?.dataset.user, props.contact]) : "",
  () => body.value, saved => { body.value = typeof saved === "string" ? saved : ""; });
onMounted(() => nextTick(() => input.value?.focus()));

function selectMentions(values) {
  if (values.length > 10) { error.value = "Choose at most 10 colleagues"; return; }
  mentions.value = values;
}
async function submit() {
  if (busy.value || !body.value.trim()) return;
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
    <label class="note-input">
      <FeatherIcon name="lock" :size="15" />
      <textarea ref="input" v-model="body" aria-label="Internal note" placeholder="Note for your team. The customer will not see this."
        :rows="isMobile ? 2 : 1" maxlength="4000" :readonly="busy" @keydown="keydown" @input="resize" />
    </label>
    <p v-if="error" role="alert" class="note-error">{{ error }}</p>
    <div class="note-bar">
      <Button icon-left="at-sign" :label="isMobile ? '' : optionCount ? `Mention or assign (${optionCount})` : 'Mention or assign'"
        aria-label="Mention or assign a colleague" title="Mention or assign a colleague" :aria-pressed="optionsOpen" :disabled="busy" @click="optionsOpen = !optionsOpen" />
      <span class="note-hint">Only your team sees this</span>
      <Button class="note-add" icon-left="lock" label="Add note" variant="solid" :loading="busy" :disabled="!body.trim()"
        :title="body.trim() ? 'Add note · Enter' : 'Type a note first'" @click="submit" />
    </div>
  </div>
</template>

<style scoped>
.note-composer { grid-area:note; display:flex; flex-direction:column; gap:6px; padding:6px 8px 8px; }
.note-context, .note-options { display:flex; align-items:center; gap:8px; padding:0 6px; font-size:12px; color:var(--relay-amber); }
.note-context span { flex:1; }
.note-options { flex-direction:column; align-items:stretch; }
.note-input { display:flex; align-items:flex-start; gap:8px; padding:9px 12px; border:1px solid color-mix(in srgb, var(--relay-amber) 45%, transparent); border-radius:8px; background:var(--surface-white); color:var(--relay-amber); cursor:text; }
.note-input textarea { flex:1; min-width:0; min-height:22px; max-height:130px; padding:0; border:0; outline:0; background:none; color:var(--relay-ink, var(--ink-gray-8)); font:inherit; font-size:13.5px; line-height:1.45; resize:none; }
.note-input textarea::placeholder { color:var(--relay-amber); opacity:.75; }
.note-error { padding:0 6px; font-size:12px; color:var(--ink-red-3); }
.note-bar { display:flex; align-items:center; gap:8px; }
.note-hint { flex:1; text-align:right; font-size:11px; color:var(--relay-amber); }
.note-add.relay-button { background:var(--relay-amber); border-color:var(--relay-amber); color:var(--surface-white); }
.note-add.relay-button:disabled { opacity:.55; }
@media (max-width: 768px) {
  .note-composer { padding:0; }
  .note-input textarea { font-size:16px; }
}
</style>
