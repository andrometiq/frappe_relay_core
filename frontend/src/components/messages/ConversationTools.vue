<script setup>
import RemoteLinkField from "../fields/RemoteLinkField.vue";
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { Button, Dialog, FormControl, ErrorMessage } from "@relay/ui";
import { coreApi } from "../../services/coreApi";
import { useConversationPresence } from "../../composables/useConversationPresence";
import { useTask } from "../../composables/useTask";
import { useRealtimeRefresh } from "../../composables/useRealtimeRefresh";
const props = defineProps({
  contact: String,
  lastMessage: String,
  lastVisible: String,
  visibleMessages: Array,
});
const { busy, error, notice, run } = useTask(),
  state = ref({}),
  folder = ref(""),
  savedFolder = ref(""),
  team = ref(""),
  agent = ref(""),
  expanded = ref(false);
const assignment = ref({team:'', assigned_to:''}), assignmentChanged = ref(false);
const assignmentDirty = computed(() => team.value !== assignment.value.team || agent.value !== assignment.value.assigned_to);
function receiveState(value) {
  if (folder.value === savedFolder.value) folder.value = value.folder || "";
  savedFolder.value = value.folder || "";
  state.value = value;
}
const { people } = useConversationPresence(props, receiveState);
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
    folder.value = "";
    savedFolder.value = "";
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
    <div class="flex flex-wrap items-center gap-2">
      <Button
        :aria-label="state.starred ? 'Unstar conversation' : 'Star conversation'"
        :title="state.starred ? 'Unstar conversation' : 'Star conversation'"
        :icon="state.starred ? 'star' : 'bookmark'"
        :disabled="busy"
        @click="run(() => update({ starred: state.starred ? 0 : 1 }))"
      /><Button
        icon="check" aria-label="Mark read" title="Mark read"
        :disabled="busy || !lastMessage"
        @click="run(() => update({ last_read: lastMessage }))"
      /><span class="conversation-unread text-xs text-ink-gray-5"
        >{{ state.unread || 0 }}{{ state.unread_more ? "+" : "" }} unread</span
      ><Button
        icon="sidebar" aria-label="Organize conversation" title="Organize conversation"
        :disabled="busy"
        @click="
          expanded = !expanded;
          
        "
      />
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
      <div class="flex items-end gap-2">
        <FormControl
          label="Folder"
          v-model="folder"
          placeholder="e.g. Follow up"
        /><Button
          label="Save folder"
          :disabled="busy"
          @click="run(() => update({ folder }))"
        />
      </div>
      <template v-if="state.can_assign"
        ><RemoteLinkField v-model="team" :field="{label:'Assign team',method:'teams.directory',readOnly:busy}" /><RemoteLinkField v-model="agent" :field="{label:'Assign agent',method:'teams.agents',readOnly:busy}" /><Button
          label="Save assignment"
          :disabled="busy"
          @click="run(assign)"
      /></template>
    </div>
    </Dialog>
    <ErrorMessage v-if="!expanded" :message="error" />
  </div>
</template>
