<script setup>
import RemoteLinkField from "../fields/RemoteLinkField.vue";
import { ref, watch } from "vue";
import { Button, FormControl, ErrorMessage } from "@relay/ui";
import RelaySelect from "../RelaySelect.vue";
import { coreApi } from "../../services/coreApi";
import { useConversationPresence } from "../../composables/useConversationPresence";
import { useTask } from "../../composables/useTask";
const props = defineProps({
  contact: String,
  lastMessage: String,
  lastVisible: String,
  visibleMessages: Array,
});
const { busy, error, notice, run } = useTask(),
  state = ref({}),
  folder = ref(""),
  team = ref(""),
  agent = ref(""),
  teams = ref([]),
  agents = ref([]),
  expanded = ref(false);
const { people } = useConversationPresence(props, (value) => {
  state.value = value;
});
let generation = 0;
async function load(current = ++generation) {
  const result = await coreApi("inbox.read", { contact: props.contact });
  if (current !== generation) return;
  state.value = result;
  folder.value = result.folder || "";
  team.value = result.assignment?.team || "";
  agent.value = result.assignment?.assigned_to || "";
}
async function update(values) {
  const current = generation;
  const result = await coreApi(
    "inbox.update",
    { contact: props.contact, ...values },
    true,
  );
  if (current !== generation) return;
  state.value = result;
  notice.value = "Conversation preferences saved";
}
async function assign() {
  await coreApi(
    "teams.assign",
    { contact: props.contact, team: team.value, assigned_to: agent.value },
    true,
  );
  notice.value = "Assignment saved";
  await load();
}
watch(
  () => props.contact,
  () => {
    const current = ++generation;
    expanded.value = false;
    state.value = {};
    folder.value = "";
    team.value = "";
    agent.value = "";
    error.value = "";
    notice.value = "";
    if (props.contact)
      load(current).catch((err) => {
        if (generation === current) error.value = err.message;
      });
  },
  { immediate: true },
);
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
      /><span class="text-xs text-ink-gray-5"
        >{{ state.unread || 0 }}{{ state.unread_more ? "+" : "" }} unread</span
      ><Button
        label="Details" icon-left="sidebar" aria-label="Organize conversation"
        :disabled="busy"
        @click="
          expanded = !expanded;
          
        "
      />
    </div>
    <p v-if="people.length" class="text-xs text-ink-gray-5">
      Viewing:
      {{ people.map((person) => (person.full_name || person.name) + (person.typing ? ' is typing…' : '')).join(", ") }}
    </p>
    <ErrorMessage :message="error" />
    <p v-if="notice" role="status" class="text-xs">{{ notice }}</p>
    <div v-if="expanded" class="grid sm:grid-cols-2 gap-3 mt-3">
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
  </div>
</template>
