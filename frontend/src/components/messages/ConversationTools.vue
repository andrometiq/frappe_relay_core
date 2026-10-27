<script setup>
import MoveToFolderDialog from "./MoveToFolderDialog.vue";
import { computed, inject, onBeforeUnmount, ref, watch } from "vue";
import { Button, Dropdown, ErrorMessage } from "@relay/ui";
import { coreApi } from "../../services/coreApi";
import { useConversationPresence } from "../../composables/useConversationPresence";
import { useTask } from "../../composables/useTask";
import { useRealtimeRefresh } from "../../composables/useRealtimeRefresh";
import { useChatFolders } from "../../composables/useChatFolders";
const props = defineProps({
  contact: String,
  lastMessage: String,
  lastVisible: String,
  visibleMessages: Array,
  actions: Array,
  menuIcon: { type: String, default: "more-horizontal" },
});
const { busy, error, run } = useTask(),
  state = ref({}),
  moving = ref(false);
const capabilities = inject("relayCapabilities", ref({}));
function receiveState(value) {
  state.value = value;
}
useConversationPresence(props, receiveState);
const { move } = useChatFolders();
const menu = computed(() => [
  { label: state.value.starred ? "Unstar conversation" : "Star conversation", icon: state.value.starred ? "star" : "bookmark", disabled: busy.value,
    onClick: () => run(() => update({ starred: state.value.starred ? 0 : 1 })) },
  { label: "Mark read", icon: "check", disabled: busy.value || !props.lastMessage, onClick: () => run(() => update({ last_read: props.lastMessage })) },
  ...(capabilities.value.folders ? [{ label: "Move to folder", icon: "folder-input", disabled: busy.value, onClick: () => { moving.value = true; } }] : []),
  ...(capabilities.value.folders && state.value.folder ? [{ label: "Remove from folder", icon: "folder-minus", disabled: busy.value, onClick: () => run(() => move(props.contact, "").then(receiveState)) }] : []),
  ...(props.actions || []),
]);
let generation = 0;
async function load(current = ++generation) {
  const result = await coreApi("inbox.read", { contact: props.contact });
  if (current === generation) receiveState(result);
}
async function update(values) {
  const current = generation;
  const result = await coreApi("inbox.update", { contact: props.contact, ...values }, true);
  if (current !== generation) return;
  receiveState(result);
}
watch(
  () => props.contact,
  () => {
    const current = ++generation;
    state.value = {};
    moving.value = false;
    error.value = "";
    if (props.contact)
      load(current).catch((err) => {
        if (generation === current) error.value = err.message;
      });
  },
  { immediate: true },
);
// A reconnect re-reads the star and folder; losing access clears them.
useRealtimeRefresh([], ['inbox'], async () => {
  if (!props.contact) return;
  const current = ++generation;
  try { await load(current); }
  catch (err) {
    if (current !== generation) return;
    error.value = err.message;
    if ([401,403].includes(err.status)) state.value = {};
  }
});
onBeforeUnmount(() => { ++generation; });
</script>
<template>
  <div class="conversation-tools">
    <div class="conversation-tool-buttons">
      <slot />
      <Dropdown :options="menu"><Button :icon="menuIcon" aria-label="Conversation actions" title="Conversation actions" /></Dropdown>
    </div>
    <MoveToFolderDialog v-if="capabilities.folders" v-model="moving" :contact="contact" :current="state.folder" @moved="receiveState" />
    <ErrorMessage :message="error" />
  </div>
</template>
