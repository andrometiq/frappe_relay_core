<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { Badge, Button, ErrorMessage, FeatherIcon, TextInput } from "@relay/ui";
import { coreApi } from "../services/coreApi";
import { useRealtimeRefresh } from "../composables/useRealtimeRefresh";

const rows = ref([]), next = ref(null), query = ref(""), loading = ref(false),
  error = ref(""), selected = ref(""), flow = ref(null), runs = ref([]), runNext = ref(null);
let timer, sequence = 0, listController;

const nodes = computed(() => {
  const value = flow.value?.published_nodes || flow.value?.nodes;
  if (!value) return [];
  try { return typeof value === "string" ? JSON.parse(value) : value; }
  catch { return []; }
});
const statusTheme = value => ({ Completed: "green", Running: "blue", Waiting: "blue", Handoff: "gray", Cancelled: "red" })[value] || "gray";
const kindLabel = kind => ({ input:"Collect input", reply:"Reply", action:"Business action", handoff:"Hand off", condition:"Condition", wait:"Wait", end:"Finish", ticket:"Ticket", topic:"Topic" })[kind] || kind;
const kindIcon = kind => ({ input:"message-square", reply:"reply", action:"zap", handoff:"user-check", condition:"git-branch", wait:"clock", end:"check", ticket:"file-text", topic:"message-circle" })[kind] || "circle";
const formatDate = value => value ? new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium", timeStyle: "short",
}).format(new Date(String(value).replace(" ", "T"))) : "";

function nodeDetail(node) {
  if (node.kind === "action") return node.action;
  if (node.kind === "condition") return `${node.variable} ${node.operator} ${node.value ?? ""}`.trim();
  if (node.kind === "wait") return `${node.seconds} seconds`;
  if (node.kind === "input") return `${node.input_type || "text"} → ${node.variable}`;
  if (node.kind === "topic") return node.title;
  return "";
}

async function load(reset = true) {
  if (!reset && (loading.value || !next.value)) return;
  if (reset) listController?.abort();
  const controller = new AbortController();
  listController = controller;
  const current = reset ? ++sequence : sequence;
  const after = reset ? null : next.value;
  if (reset) { rows.value = []; next.value = null; }
  loading.value = true; error.value = "";
  try {
    const result = await coreApi("flows.service.directory", { query: query.value, after }, false, { signal: controller.signal });
    if (current !== sequence) return;
    const known = new Set(rows.value.map(row => row.name));
    rows.value = reset ? result.items : [...rows.value, ...result.items.filter(row => !known.has(row.name))];
    next.value = result.next;
  } catch (e) { if (e.name !== "AbortError" && current === sequence) error.value = e.message; }
  finally { if (current === sequence) loading.value = false; }
}

async function loadRuns(reset = true) {
  if (!selected.value || (!reset && !runNext.value)) return;
  const name = selected.value;
  const result = await coreApi("flows.service.runs", { flow: name, after: reset ? null : runNext.value });
  if (name !== selected.value) return;
  runs.value = reset ? result.items : [...runs.value, ...result.items];
  runNext.value = result.next;
}

function route(name) {
  const params = new URLSearchParams();
  if (name) params.set("flow", name);
  window.history.pushState(null, "", "#/flows" + (params.size ? "?" + params : ""));
}

async function open(name, updateRoute = true) {
  selected.value = name; flow.value = null; runs.value = []; runNext.value = null; error.value = "";
  if (updateRoute) route(name);
  try {
    const [definition] = await Promise.all([coreApi("flows.service.read", { name }), loadRuns(true)]);
    if (selected.value === name) flow.value = definition;
  } catch (e) { if (selected.value === name) error.value = e.message; }
}

function close() { selected.value = ""; flow.value = null; runs.value = []; route(""); }
function scrolled(event) {
  const target = event.currentTarget;
  if (target.scrollHeight - target.scrollTop - target.clientHeight < 140) load(false);
}
function restoreRoute() {
  const name = new URLSearchParams(location.hash.split("?")[1] || "").get("flow") || "";
  if (name && name !== selected.value) open(name, false);
  else if (!name && selected.value) { selected.value = ""; flow.value = null; runs.value = []; }
}

watch(query, () => { clearTimeout(timer); timer = setTimeout(() => load(true), 300); });
useRealtimeRefresh(["Relay Flow", "Relay Flow Run"], ["flows"], async () => {
  await load(true);
  if (selected.value) await open(selected.value, false);
});
onMounted(async () => { await load(true); restoreRoute(); window.addEventListener("popstate", restoreRoute); });
onBeforeUnmount(() => { clearTimeout(timer); ++sequence; listController?.abort(); window.removeEventListener("popstate", restoreRoute); });
</script>

<template>
  <section class="workflow-viewer" :class="{ 'has-selection': selected }" aria-label="Workflow viewer">
    <aside class="workflow-directory" @scroll.passive="scrolled">
      <header><div><h2>AI workflows</h2><p>Read-only definitions</p></div><FeatherIcon name="sparkles" :size="18" /></header>
      <div class="workflow-search"><TextInput v-model="query" type="search" placeholder="Search workflows" aria-label="Search workflows"><template #prefix><FeatherIcon name="search" :size="15" /></template></TextInput></div>
      <ErrorMessage class="mx-3 mb-2" :message="error && !flow ? error : ''" />
      <div class="workflow-list">
        <button v-for="item in rows" :key="item.name" type="button" :class="{ selected: selected === item.name }" @click="open(item.name)">
          <span class="workflow-list-icon"><FeatherIcon name="git-branch" :size="16" /></span>
          <span class="workflow-list-copy"><strong>{{ item.title }}</strong><small>{{ item.command }}</small></span>
          <span class="workflow-state-dot" :class="{ enabled: item.enabled }" :title="item.enabled ? 'Enabled' : 'Disabled'" />
        </button>
        <p v-if="!loading && !rows.length && !error" class="workflow-list-empty">{{ query ? 'No workflows match this search.' : 'No workflows yet.' }}</p>
        <div v-if="loading" class="workflow-viewer-loading" role="status">Loading workflows…</div>
      </div>
    </aside>

    <main v-if="flow" class="workflow-detail">
      <header class="workflow-detail-heading">
        <Button class="mobile-only" icon="arrow-left" aria-label="Back to workflows" @click="close" />
        <div><div class="workflow-title-row"><h2>{{ flow.title }}</h2><Badge :label="flow.enabled ? 'Enabled' : 'Disabled'" :theme="flow.enabled ? 'green' : 'gray'" /></div><p>{{ flow.command }}</p></div>
        <div class="workflow-heading-meta"><span>{{ flow.business_doctype }}</span><span>{{ flow.channel }}</span><span>Runs as {{ flow.execution_user }}</span></div>
      </header>
      <ErrorMessage class="m-4 mb-0" :message="error" />
      <div class="workflow-detail-scroll">
        <section class="workflow-definition" aria-labelledby="workflow-sequence-title">
          <div class="workflow-section-heading"><div><h3 id="workflow-sequence-title">Flow sequence</h3><p>{{ nodes.length }} steps · published snapshot {{ flow.published_version || 'not published' }}</p></div></div>
          <ol class="workflow-steps">
            <li v-for="(node, index) in nodes" :key="node.id">
              <span class="workflow-step-index">{{ index + 1 }}</span>
              <article><div class="workflow-step-kind"><FeatherIcon :name="kindIcon(node.kind)" :size="15" /><strong>{{ kindLabel(node.kind) }}</strong><code>{{ node.id }}</code></div><p v-if="node.text">{{ node.text }}</p><small v-if="nodeDetail(node)">{{ nodeDetail(node) }}</small><div v-if="node.kind === 'condition'" class="workflow-branches"><span>Then → {{ node.then }}</span><span>Otherwise → {{ node.otherwise }}</span></div></article>
            </li>
          </ol>
        </section>

        <section class="workflow-runs" aria-labelledby="workflow-runs-title">
          <div class="workflow-section-heading"><div><h3 id="workflow-runs-title">Recent runs</h3><p>Permission-checked execution history</p></div></div>
          <div v-if="runs.length" class="workflow-run-list">
            <article v-for="item in runs" :key="item.name"><div><strong>{{ item.display_name || item.relay_contact }}</strong><small>{{ item.business_name || item.business_doctype }} · step {{ item.step }}</small></div><div><Badge :label="item.status" :theme="statusTheme(item.status)" /><time :datetime="item.creation">{{ formatDate(item.creation) }}</time></div><p v-if="item.reason">{{ item.reason }}</p></article>
          </div>
          <p v-else class="workflow-list-empty">No accessible runs yet.</p>
          <Button v-if="runNext" label="Load more runs" variant="subtle" @click="loadRuns(false)" />
        </section>
      </div>
    </main>

    <main v-else class="workflow-viewer-empty">
      <span><FeatherIcon name="git-branch" :size="32" /></span><h2>Workflow viewer</h2><p>Review AI-generated WhatsApp flows and their execution history.</p>
    </main>
  </section>
</template>
