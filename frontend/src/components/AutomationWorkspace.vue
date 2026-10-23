<script setup>
import { ref } from "vue";
import { coreApi } from "../services/coreApi";
import { Button, FormControl } from "@relay/ui";
import RelayTable from "./RelayTable.vue";
const query = ref(""),
  revision = ref(0),
  transcript = ref("");
const columns = [
  {key:"report",label:"Report",minWidth:140},
  { key: "name", label: "Run", minWidth: 190 },
  { key: "status", label: "Decision" },
  { key: "delivery", label: "Reply status" },
  { key: "message", label: "Message", minWidth: 190 },
  { key: "ticket", label: "Ticket", minWidth: 190 },
  { key: "reason", label: "Details", minWidth: 220 },
  { key: "transcript", label: "Voice transcript", minWidth: 160 },
];
async function source({ cursor, query, signal }) {
  const page = await coreApi(
    "automation.service.runs",
    { query, ...cursor },
    false,
    { signal },
  );
  if (!Array.isArray(page?.items))
    throw new Error("Unable to load automation runs.");
  return page;
}
</script>
<template>
  <section class="page-body">
    <div class="flex flex-wrap items-center gap-3 mb-5">
      <FormControl
        v-model="query"
        type="search"
        placeholder="Search automation"
        aria-label="Search automation"
      /><Button label="Refresh" icon-left="refresh-cw" @click="revision++" /><a
        class="text-sm text-ink-gray-6"
        href="/desk/relay-automation-policy"
        >Policies</a
      ><a class="text-sm text-ink-gray-6" href="/desk/relay-canned-reply"
        >Canned replies</a
      >
    </div>
    <RelayTable
      :fetch-page="source"
      :query="query"
      :revision="revision"
      :columns="columns"
      label="Automation runs"
      ><template #status="{ item }"
        ><span
          class="rounded px-2 py-1 text-xs"
          :class="
            item.status === 'Handoff'
              ? 'bg-amber-50 text-amber-800'
              : item.status === 'Completed'
                ? 'bg-green-50 text-green-800'
                : 'bg-gray-100 text-gray-700'
          "
          >{{ item.status }}</span
        ></template
      ><template #ticket="{ item }"
        ><a
          v-if="item.ticket"
          :href="'#/tickets?ticket=' + encodeURIComponent(item.ticket)"
          class="text-blue-700"
          >{{ item.ticket }}</a
        ><span v-else>—</span></template
      ><template #message="{ item }"
        ><a
          :href="'#/messages?message=' + encodeURIComponent(item.message)"
          class="text-blue-700"
          >{{ item.message }}</a
        ></template
      >
      <template #report="{item}"><a v-if="item.has_report" :href="'/api/method/relay_core.reports.from_run?run='+encodeURIComponent(item.name)" target="_blank" rel="noopener" class="text-blue-700">Download PDF</a><span v-else>—</span></template>
      <template #transcript="{ item }"
        ><Button
          v-if="item.transcript"
          label="Read transcript"
          @click="transcript = item.transcript"
        /><span v-else>—</span></template
      >
    </RelayTable>
    <section v-if="transcript" class="workflow-card mt-4">
      <h3 class="font-semibold">Voice transcript</h3>
      <p class="whitespace-pre-wrap text-sm">{{ transcript }}</p>
      <Button label="Close transcript" @click="transcript = ''" />
    </section>
  </section>
</template>
