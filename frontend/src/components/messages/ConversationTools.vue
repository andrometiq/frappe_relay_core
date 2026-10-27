<script setup>
import RemoteLinkField from "../fields/RemoteLinkField.vue";
import MoveToFolderDialog from "./MoveToFolderDialog.vue";
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { Button, Dialog, Dropdown, ErrorMessage } from "@relay/ui";
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
  organizeRequest: Number,
  menuIcon: { type: String, default: "more-horizontal" },
});
const { busy, error, notice, run } = useTask(),
  state = ref({}),
  moving = ref(false),
  team = ref(""),
  agent = ref(""),
  expanded = ref(false);
const assignment = ref({team:'', assigned_to:''}), assignmentChanged = ref(false);
const assignmentDirty = computed(() => team.value !== assignment.value.team || agent.value !== assignment.value.assigned_to);
function receiveState(value) {
  state.value = value;
}
const { people } = useConversationPresence(props, receiveState);
const { move } = useChatFolders();
const menu = computed(() => [
  { label: state.value.starred ? "Unstar conversation" : "Star conversation", icon: state.value.starred ? "star" : "bookmark", disabled: busy.value,
    onClick: () => run(() => update({ starred: state.value.starred ? 0 : 1 })) },
  { label: "Mark read", icon: "check", disabled: busy.value || !props.lastMessage, onClick: () => run(() => update({ last_read: props.lastMessage })) },
  { label: "Move to folder", icon: "folder-input", disabled: busy.value, onClick: () => { moving.value = true; } },
  ...(state.value.folder ? [{ label: "Remove from folder", icon: "folder-minus", disabled: busy.value, onClick: () => run(() => move(props.contact, "").then(receiveState)) }] : []),
  ...(props.actions || []),
]);
watch(() => props.organizeRequest, () => { expanded.value = true; });
let generation = 0, contactGeneration = 0;
async function load(current = ++generation) {
  const result = await coreApi("inbox.read", { contact: props.contact });
  if (current !== generation) return;
  receiveState(result);
  const next = {team:result.assignment?.team || "", assigned_to:result.assignment?.assigned_to || ""};
  if (assignmentDirty.value) {
    assignmentChanged.value = next.team !== assignment.value.team || next.assigned_to !== assignment.value.assigned_to;
  } else {
    assignment.value = next;
    team.value = next.team;
    agent.value = next.assigned_to;
    assignmentChanged.value = false;
  }
}
async function update(values) {
  const current = generation;
  const result = await coreApi(
    "inbox.update",
    { contact: props.contact, ...values },
    true,
  );
  if (current !== generation) return;
  receiveState(result);
  notice.value = "Conversation preferences saved";
}
async function assign() {
  const current = contactGeneration, contact = props.contact;
  await coreApi(
    "teams.assign",
    { contact, team: team.value, assigned_to: agent.value },
    true,
  );
  if (current !== contactGeneration) return;
  assignment.value = {team:team.value, assigned_to:agent.value};
  assignmentChanged.value = false;
  notice.value = "Assignment saved";
  await load();
}
watch(
  () => props.contact,
  () => {
    const current = ++generation;
    ++contactGeneration;
    expanded.value = false;
    state.value = {};
    moving.value = false;
    team.value = "";
    agent.value = "";
    assignment.value = {team:'', assigned_to:''};
    assignmentChanged.value = false;
    error.value = "";
    notice.value = "";
    if (props.contact)
      load(current).catch((err) => {
        if (generation === current) error.value = err.message;
      });
  },
  { immediate: true },
);
useRealtimeRefresh(['Relay Conversation Assignment'], ['inbox'], async () => {
  if (!props.contact) return;
  const current = ++generation;
  try { await load(current); }
  catch (err) {
    if (current !== generation) return;
    error.value = err.message;
    if ([401,403].includes(err.status)) {
      state.value = {}; team.value = ''; agent.value = '';
      assignment.value = {team:'', assigned_to:''}; assignmentChanged.value = false;
    }
  }
});
onBeforeUnmount(() => { ++generation; ++contactGeneration; });
</script>
<template>
  <div class="conversation-tools">
    <div class="conversation-tool-buttons">
      <Button class="conversation-assign" icon="user" label="Assign" title="Assign and organize" :disabled="busy" @click="expanded = true" />
      <slot />
      <Dropdown :options="menu"><Button :icon="menuIcon" aria-label="Conversation actions" title="Conversation actions" /></Dropdown>
    </div>
    <Dialog v-model="expanded" :options="{title:'Organize conversation'}">
    <p v-if="people.length" class="text-xs text-ink-gray-5">
      Viewing:
      {{ people.map((person) => (person.full_name || person.name) + (person.typing ? ' is typing…' : '')).join(", ") }}
    </p>
    <ErrorMessage :message="error" />
    <p v-if="notice" role="status" class="text-xs">{{ notice }}</p>
    <p v-if="assignmentChanged" role="status" class="text-xs">Assignment changed elsewhere. Your edits are preserved; saving will replace the current assignment.</p>
    <div class="grid sm:grid-cols-2 gap-3 mt-3">
      <template v-if="state.can_assign"
        ><RemoteLinkField v-model="team" :field="{label:'Assign team',method:'teams.directory',readOnly:busy}" /><RemoteLinkField v-model="agent" :field="{label:'Assign agent',method:'teams.agents',readOnly:busy}" /><Button
          label="Save assignment"
          :disabled="busy"
          @click="run(assign)"
      /></template>
    </div>
    </Dialog>
    <MoveToFolderDialog v-model="moving" :contact="contact" :current="state.folder" @moved="receiveState" />
    <ErrorMessage v-if="!expanded" :message="error" />
  </div>
</template>
