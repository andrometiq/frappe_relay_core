<script setup>
import { useRealtimeRefresh } from "../composables/useRealtimeRefresh";
import RemoteLinkField from "./fields/RemoteLinkField.vue";
import { ref, onMounted } from "vue";
import CasesWorkspace from "./CasesWorkspace.vue";
const mode = ref("tickets");
import TicketNotifications from "./TicketNotifications.vue";
import { Button, FormControl, ErrorMessage, Badge } from "@relay/ui";
import RelayTable from "./RelayTable.vue";
import RelaySelect from "./RelaySelect.vue";
import { coreApi } from "../services/coreApi";
import { useTask } from "../composables/useTask";
const { busy, error, notice, run } = useTask(),
  query = ref(""),
  revision = ref(0),
  ticket = ref(null),
  status = ref("Open"),
  agent = ref(""),
  agents = ref([]);
const columns = [
  { key: "name", label: "Ticket", minWidth: 190 },
  { key: "subject", label: "Subject", minWidth: 220 },
  { key: "category", label: "Category" },
  { key: "status", label: "Status" },
];
const source = ({ cursor, query, signal }) =>
  coreApi("tickets.directory", { query, ...cursor }, false, { signal });
async function open(name) {
  ticket.value = await coreApi("tickets.read", { name });
  status.value = ticket.value.status;
  agent.value = ticket.value.assigned_to || "";

}
async function save() {
  await coreApi(
    "tickets.update_status",
    { name: ticket.value.name, status: status.value },
    true,
  );
  notice.value = "Ticket updated";
  await open(ticket.value.name);
  revision.value++;
}
async function assign() {
  await coreApi(
    "tickets.assign",
    { name: ticket.value.name, user: agent.value },
    true,
  );
  await open(ticket.value.name);
  revision.value++;
  notice.value = "Ticket assignment saved";
}
onMounted(() => {
  const name = new URLSearchParams(location.hash.split("?")[1] || "").get(
    "ticket",
  );
  if (name) run(() => open(name));
});
useRealtimeRefresh(['Relay Ticket'],['tickets'],()=>{revision.value++});
</script>
<template>
  <section class="page-body space-y-5">
    <div class="flex gap-2">
      <Button
        label="Tickets"
        :variant="mode === 'tickets' ? 'solid' : 'subtle'"
        @click="mode = 'tickets'"
      /><Button
        label="Cases"
        :variant="mode === 'cases' ? 'solid' : 'subtle'"
        @click="mode = 'cases'"
      />
    </div>
    <CasesWorkspace v-if="mode === 'cases'" />
    <template v-else>
      <div class="flex items-center justify-between gap-3">
        <div>
          <h2 class="text-xl font-semibold">Tickets</h2>
          <p class="text-sm text-ink-gray-5 mt-2">
            Track requests and return to the messages that need attention.
          </p>
        </div>
        <Button label="Refresh tickets" :disabled="busy" @click="revision++" />
      </div>
      <ErrorMessage :message="error" />
      <p v-if="notice" role="status">{{ notice }}</p>
      <div v-if="ticket" class="workflow-card max-w-3xl">
        <div class="flex justify-between gap-3">
          <h3 class="font-semibold">{{ ticket.subject }}</h3>
          <Button label="Close ticket details" @click="ticket = null" />
        </div>
        <Badge :label="ticket.category" />
        <p class="text-sm whitespace-pre-wrap">{{ ticket.brief }}</p>
        <div class="flex items-end gap-3">
          <RelaySelect
            label="Ticket status"
            v-model="status"
            :options="['Open', 'In progress', 'Resolved', 'Closed']"
          /><Button label="Update status" :disabled="busy" @click="run(save)" />
        </div>
        <div v-if="ticket.can_assign" class="flex flex-wrap items-end gap-3">
          <RemoteLinkField v-model="agent" :field="{label:'Ticket assignee',method:'teams.agents',readOnly:busy}" /><Button
            label="Assign ticket"
            :disabled="busy"
            @click="run(assign)"
          />
        </div>
        <p v-else class="text-sm">
          Assigned to: {{ ticket.assigned_to || "Unassigned" }}
        </p>
        <div class="space-y-2">
          <h4 class="text-sm font-medium">Linked messages</h4>
          <a
            v-for="message in ticket.messages"
            :key="message.message"
            :href="'#/messages?message=' + encodeURIComponent(message.message)"
            class="block rounded border p-3 text-sm text-blue-700"
            >{{ message.message }} · {{ message.channel }}</a
          >
        </div>
        <TicketNotifications :key="ticket.name" :ticket="ticket.name" />
      </div>
      <FormControl
        v-model="query"
        type="search"
        placeholder="Search tickets"
        aria-label="Search tickets"
      /><RelayTable
        :columns="columns"
        :fetch-page="source"
        :query="query"
        :revision="revision"
        label="Tickets"
        ><template #name="{ item }"
          ><button
            class="text-blue-700"
            :disabled="busy"
            @click="run(() => open(item.name))"
          >
            {{ item.name }}
          </button></template
        ><template #status="{ item }"><Badge :label="item.status" /></template
      ></RelayTable>
    </template>
  </section>
</template>
