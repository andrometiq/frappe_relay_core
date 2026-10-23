<script setup>
import { randomUUID } from "../services/crypto.js";
import { ref, computed, onMounted } from "vue";
import { Button, FormControl, ErrorMessage, Badge } from "@relay/ui";
import DocumentForm from "./DocumentForm.vue";
import LegacyFlowImport from "./flows/LegacyFlowImport.vue";
import BusinessActionEditor from "./flows/BusinessActionEditor.vue";
import MetaFlowsWorkspace from "./MetaFlowsWorkspace.vue";
const mode = ref("conversation");
const aiOpen=ref(false), aiRequirement=ref(''), aiProvider=ref(''), aiPreview=ref(null);
async function generateDraft(){aiPreview.value=await coreApi('flows.authoring.draft',{requirement:aiRequirement.value,provider:aiProvider.value},true)}
function useAIDraft(){const result=aiPreview.value;fresh();draft.value.title=result.title;draft.value.command=result.command;nodes.value=result.nodes;aiPreview.value=null;aiOpen.value=false;notice.value='AI draft loaded. Review the steps and choose its channel, business type and execution user before saving.'}
const importOpen = ref(false),
  importWarnings = ref([]);
function imported(result) {
  fresh();
  nodes.value = result.nodes;
  draft.value.command = result.command;
  draft.value.template_button = result.template_button || "";
  draft.value.enabled = 0;
  importWarnings.value = result.warnings;
  importOpen.value = false;
}
import RelaySelect from "./RelaySelect.vue";
import { validateFields } from "./formValidation";
import { coreApi } from "../services/coreApi";
import { useTask } from "../composables/useTask";
const { busy, error, notice, run } = useTask(),
  rows = ref([]),
  next = ref(null),
  draft = ref(null),
  nodes = ref([]),
  fieldErrors = ref({}),
  runs = ref([]),
  runNext = ref(null),
  runDetails = ref({}),
  canConfigure = ref(false);
const reference = (name, label, kind) => ({
  name,
  label,
  kind,
  type: "RemoteLink",
  method: "automation.settings.references",
  required: true,
});
const baseFields = [
  {
    name: "title",
    label: "Flow title",
    type: "Data",
    required: true,
    maxLength: 140,
  },
  {
    name: "command",
    label: "Slash command",
    type: "Data",
    required: true,
    placeholder: "/support",
  },
  {
    name: "template_button",
    label: "Template button payload",
    type: "Data",
    maxLength: 140,
    placeholder: "Optional WhatsApp button payload",
  },
  reference("channel", "Channel", "channel"),
  reference("execution_user", "Execution user", "execution_user"),
  reference("business_doctype", "Business type", "business_doctype"),
  { name: "enabled", label: "Enabled", type: "Check" },
];
const fields = computed(() =>
  baseFields.map((field) => ({
    ...field,
    readOnly:
      !canConfigure.value ||
      (field.name === "enabled" && !draft.value?.published_version),
  })),
);
const actionCatalog = ref([]),
  actionValidity = ref({});
const kinds = [
  { value: "input", label: "Collect input" },
  { value: "reply", label: "Send reply" },
  { value: "action", label: "Business action" },
  { value: "handoff", label: "Hand off to agent" },
  { value: "condition", label: "Branch on an answer" },
  { value: "wait", label: "Wait before continuing" },
  { value: "end", label: "Finish flow" },
];
async function load(after = null) {
  const result = await coreApi("flows.service.directory", { after });
  rows.value = result.items;
  next.value = result.next;
  canConfigure.value = result.can_configure;
  actionCatalog.value = await coreApi("flows.actions.catalog");
}
function fresh() {
  importWarnings.value = [];
  draft.value = {
    title: "",
    command: "",
    channel: "",
    execution_user: "",
    business_doctype: "",
    enabled: 0,
  };
  nodes.value = [];
  runs.value = [];
  runNext.value = null;
  error.value = "";
  notice.value = "";
  fieldErrors.value = {};
}
async function open(name) {
  draft.value = await coreApi("flows.service.read", { name });
  nodes.value = JSON.parse(draft.value.nodes);
  fieldErrors.value = {};
  await loadRuns();
}
function add() {
  if (nodes.value.length >= 30) return;
  nodes.value.push({
    id: "step_" + randomUUID().replaceAll("-", "").slice(0, 12),
    kind: "reply",
    text: "",
  });
}
function move(index, offset) {
  const target = index + offset;
  if (target < 0 || target >= nodes.value.length) return;
  [nodes.value[index], nodes.value[target]] = [
    nodes.value[target],
    nodes.value[index],
  ];
}
function changeKind(node) {
  for (const key of [
    "input_type",
    "variable",
    "choices",
    "category",
    "operator",
    "value",
    "then",
    "otherwise",
    "seconds",
    "minimum",
    "maximum",
    "integer_only",
    "optional",
    "title",
    "status",
    "action",
    "arguments",
    "next",
  ])
    delete node[key];
  if (node.kind === "input") {
    node.input_type = "text";
    node.variable = "input_" + nodes.value.indexOf(node);
  }
  if (node.kind === "action") {
    node.action = "";
    node.arguments = {};
  }
  if (node.kind === "topic") {
    node.title = "Conversation follow-up";
    node.status = "Open";
    node.category = "";
  }
  if (node.kind === "ticket") node.category = "Query";
  if (node.kind === "condition") {
    node.variable = "";
    node.operator = "eq";
    node.value = "";
    node.then = "";
    node.otherwise = "";
  }
  if (node.kind === "wait") node.seconds = 60;
  if (["condition", "wait", "end", "action"].includes(node.kind))
    node.text = "";
}
async function save() {
  fieldErrors.value = validateFields(baseFields, draft.value);
  if (!/^\/[a-z][a-z0-9_]{0,31}$/.test(draft.value.command || ""))
    fieldErrors.value.command =
      "Use a lowercase slash command such as /support.";
  if (Object.keys(fieldErrors.value).length) return;
  if (!nodes.value.length) throw Error("Add at least one flow step.");
  if (
    nodes.value.some(
      (node) =>
        !["condition", "wait", "end", "action"].includes(node.kind) &&
        !node.text.trim(),
    )
  )
    throw Error("Enter text for each flow step.");
  if (
    nodes.value.some(
      (node) => node.kind === "action" && !actionValidity.value[node.id],
    )
  )
    throw Error("Complete each business action field before saving.");
  const values = Object.fromEntries(
    baseFields.map((field) => [field.name, draft.value[field.name]]),
  );
  values.nodes = nodes.value;
  const result = await coreApi(
    "flows.service.save",
    { values, name: draft.value.name || null },
    true,
  );
  draft.value = result;
  notice.value = "Draft saved. Publish to use these steps for new runs.";
  await load();
}
async function publish() {
  draft.value = await coreApi(
    "flows.service.publish",
    { name: draft.value.name },
    true,
  );
  notice.value = "Saved version published. Enable the flow when ready.";
  await load();
}
async function loadRuns(after = null) {
  const result = await coreApi("flows.service.runs", {
    flow: draft.value.name,
    after,
  });
  runs.value = result.items;
  runNext.value = result.next;
}
async function showResponses(name) {
  runDetails.value[name] = await coreApi("flows.service.responses", { name });
}
async function cancel(name) {
  await coreApi("flows.service.cancel", { name }, true);
  await loadRuns();
  notice.value = "Flow run cancelled";
}
onMounted(() => run(() => load()));
</script>
<template>
  <div class="page-body overflow-auto space-y-5">
    <LegacyFlowImport
      v-if="importOpen"
      @close="importOpen = false"
      @import="imported"
    />
    <div class="flex gap-2">
      <Button
        label="Conversation flows"
        :variant="mode === 'conversation' ? 'subtle' : 'ghost'"
        @click="mode = 'conversation'"
      /><Button
        v-if="canConfigure"
        label="WhatsApp forms"
        :variant="mode === 'forms' ? 'subtle' : 'ghost'"
        @click="mode = 'forms'"
      />
    </div>
    <MetaFlowsWorkspace v-if="mode === 'forms'" />
    <section v-else class="space-y-5">
      <ul
        v-if="importWarnings.length"
        class="list-disc pl-5 text-sm text-ink-gray-5"
      >
        <li v-for="warning in importWarnings" :key="warning">{{ warning }}</li>
      </ul>
      <div class="flex flex-wrap items-center gap-3">
        <h2 class="text-xl font-semibold">Conversation flows</h2>
        <Button v-if="canConfigure" label="Draft with AI" :disabled="busy" @click="aiOpen=!aiOpen"/>
        <Button
          v-if="canConfigure"
          label="Import legacy flow"
          :disabled="busy"
          @click="importOpen = true"
        />
        <Button
          v-if="canConfigure"
          label="New flow"
          :disabled="busy"
          @click="fresh"
        /><Button
          label="First flows"
          :disabled="busy"
          @click="run(() => load())"
        />
      </div>
      <p class="text-sm text-ink-gray-5">
        Build a sequence triggered by a slash command. Inputs and actions stay
        within the contact's conversation and the execution user's business
        permissions.
      </p>
      <ErrorMessage :message="error" />
      <p v-if="notice" role="status">{{ notice }}</p>
      <div class="grid sm:grid-cols-2 xl:grid-cols-3 gap-3">
        <button
          v-for="row in rows"
          :key="row.name"
          class="workflow-card text-left"
          :disabled="busy"
          @click="run(() => open(row.name))"
        >
          <strong>{{ row.title }}</strong
          ><span class="text-sm"
            >{{ row.command }} ·
            {{ row.enabled ? "Enabled" : "Disabled" }}</span
          ><span class="text-xs">{{
            row.published_version ? "Published version available" : "Draft only"
          }}</span>
        </button>
      </div>
      <p v-if="!rows.length && !busy" class="text-sm">No flows configured.</p>
      <Button
        v-if="next"
        label="Next flows"
        :disabled="busy"
        @click="run(() => load(next))"
      />
      <section v-if="aiOpen" class="workflow-card space-y-3" aria-label="AI flow draft">
        <h3 class="font-medium">Describe your business workflow</h3>
        <FormControl type="textarea" label="What should this flow do?" v-model="aiRequirement" :rows="4"/>
        <DocumentForm :model-value="{provider:aiProvider}" @update:model-value="aiProvider=$event.provider" :fields="[{name:'provider',label:'AI provider',type:'RemoteLink',method:'automation.settings.references',kind:'provider',required:true}]"/>
        <p class="text-sm text-ink-gray-5">AI produces a draft only. Review it before saving or publishing. Provider configuration stays in Desk.</p>
        <Button label="Generate draft" :loading="busy" :disabled="!aiProvider||aiRequirement.trim().length<10" @click="run(generateDraft)"/>
        <template v-if="aiPreview"><h4>{{aiPreview.title}}</h4><ol class="space-y-2"><li v-for="node in aiPreview.nodes" :key="node.id">{{node.kind}} · {{node.text||node.action||node.id}}</li></ol><Button label="Use this draft" :disabled="busy" @click="useAIDraft"/></template>
      </section>
      <form v-if="draft" class="workflow-card" @submit.prevent="run(save)">
        <h3 class="font-semibold">
          {{ draft.name ? "Edit flow" : "New flow" }}
        </h3>
        <DocumentForm v-model="draft" :fields="fields" :errors="fieldErrors" />
        <p class="text-sm">
          Steps run from top to bottom unless a condition selects a later step.
          End each branch with Finish flow. Use
          <code v-pre>{{ input_name }}</code> in later steps to insert a
          collected value. Publishing makes a snapshot of the saved draft.
        </p>
        <div
          v-for="(node, index) in nodes"
          :key="node.id"
          class="flow-step space-y-3"
        >
          <div class="flex flex-wrap gap-2 items-center">
            <Badge :label="'Step ' + (index + 1)" /><Button
              label="Move step up"
              :disabled="busy || !canConfigure || index === 0"
              @click="move(index, -1)"
            /><Button
              label="Move step down"
              :disabled="busy || !canConfigure || index === nodes.length - 1"
              @click="move(index, 1)"
            /><Button
              label="Remove step"
              :disabled="busy || !canConfigure"
              @click="nodes.splice(index, 1)"
            />
          </div>
          <RelaySelect
            :label="'Step ' + (index + 1) + ' action'"
            v-model="node.kind"
            :options="kinds"
            :disabled="busy || !canConfigure"
            @update:model-value="changeKind(node)"
          />
          <RelaySelect
            v-if="!['condition', 'end', 'handoff'].includes(node.kind)"
            :model-value="node.next || ''"
            :label="'Step ' + (index + 1) + ' next step'"
            :options="[
              { value: '', label: 'Continue to following step' },
              ...nodes
                .slice(index + 1)
                .map((n) => ({ value: n.id, label: n.id })),
            ]"
            :disabled="busy || !canConfigure"
            @update:model-value="
              $event ? (node.next = $event) : delete node.next
            "
          />
          <BusinessActionEditor
            v-if="node.kind === 'action'"
            :node="node"
            :catalog="actionCatalog"
            :answers="
              nodes
                .slice(0, index)
                .filter((item) => item.kind === 'input')
                .map((item) => ({ value: item.variable, label: item.variable }))
            "
            :disabled="busy || !canConfigure"
            @validity="actionValidity[node.id] = $event"
          />
          <FormControl
            v-if="!['condition', 'wait', 'action'].includes(node.kind)"
            :label="'Step ' + (index + 1) + ' text'"
            type="textarea"
            v-model="node.text"
            :disabled="busy || !canConfigure"
          />
          <div
            v-if="node.kind === 'condition'"
            class="grid sm:grid-cols-2 gap-3"
          >
            <RelaySelect
              :label="'Step ' + (index + 1) + ' answer'"
              v-model="node.variable"
              :options="
                nodes
                  .slice(0, index)
                  .filter((item) => item.kind === 'input')
                  .map((item) => ({
                    value: item.variable,
                    label: item.variable,
                  }))
              "
              :disabled="busy || !canConfigure"
            />
            <RelaySelect
              :label="'Step ' + (index + 1) + ' comparison'"
              v-model="node.operator"
              :options="[
                { value: 'eq', label: 'Equals' },
                { value: 'ne', label: 'Does not equal' },
                { value: 'contains', label: 'Contains' },
                { value: 'gt', label: 'Greater than' },
                { value: 'gte', label: 'At least' },
                { value: 'lt', label: 'Less than' },
                { value: 'lte', label: 'At most' },
                { value: 'is_set', label: 'Has a value' },
              ]"
              :disabled="busy || !canConfigure"
            />
            <FormControl
              v-if="node.operator !== 'is_set'"
              :label="'Step ' + (index + 1) + ' comparison value'"
              v-model="node.value"
              :disabled="busy || !canConfigure"
            />
            <RelaySelect
              v-for="branch in ['then', 'otherwise']"
              :key="branch"
              :label="
                'Step ' +
                (index + 1) +
                (branch === 'then' ? ' if matched' : ' otherwise')
              "
              v-model="node[branch]"
              :options="
                nodes.slice(index + 1).map((item, offset) => ({
                  value: item.id,
                  label: 'Step ' + (index + offset + 2) + ' · ' + item.kind,
                }))
              "
              :disabled="busy || !canConfigure"
            />
          </div>
          <template v-if="node.kind === 'topic'">
            <FormControl
              v-model="node.title"
              :label="'Step ' + (index + 1) + ' topic title'"
              :maxlength="140"
            />
            <FormControl
              v-model="node.category"
              label="Topic category"
              :maxlength="140"
            />
            <FormControl
              v-model="node.status"
              type="select"
              label="Topic status"
              :options="['Open', 'Waiting', 'Resolved', 'Archived']"
            />
            <p class="text-xs text-ink-gray-5">
              Step text becomes the summary. Messages collected in this run are
              grouped together. Human edits are preserved.
            </p>
          </template>
          <FormControl
            v-if="node.kind === 'wait'"
            :label="'Step ' + (index + 1) + ' delay (seconds)'"
            type="number"
            :model-value="node.seconds"
            @update:model-value="node.seconds = Number($event)"
            :disabled="busy || !canConfigure"
          />
          <p v-if="node.kind === 'end'" class="text-sm text-ink-gray-5">
            This branch finishes here without sending another message.
          </p>
          <div v-if="node.kind === 'input'" class="grid sm:grid-cols-2 gap-3">
            <FormControl
              :label="'Step ' + (index + 1) + ' input name'"
              v-model="node.variable"
              :disabled="busy || !canConfigure"
            /><RelaySelect
              :label="'Step ' + (index + 1) + ' input type'"
              v-model="node.input_type"
              :options="[
                { value: 'text', label: 'Text' },
                { value: 'number', label: 'Number' },
                { value: 'email', label: 'Email address' },
                { value: 'date', label: 'Date' },
                { value: 'choice', label: 'Choose one' },
                { value: 'multi_choice', label: 'Choose several' },
              ]"
              :disabled="busy || !canConfigure"
            /><FormControl
              v-if="['choice', 'multi_choice'].includes(node.input_type)"
              :label="
                'Step ' + (index + 1) + ' choices (one per line; label | value)'
              "
              type="textarea"
              :model-value="
                (node.choices || [])
                  .map((c) =>
                    typeof c === 'string' ? c : c.label + ' | ' + c.value,
                  )
                  .join('\n')
              "
              :disabled="busy || !canConfigure"
              @update:model-value="
                node.choices = $event
                  .split('\n')
                  .map((value) => value.trim())
                  .filter(Boolean)
                  .map((value) =>
                    value.includes(' | ')
                      ? {
                          label: value.slice(0, value.indexOf(' | ')).trim(),
                          value: value.slice(value.indexOf(' | ') + 3).trim(),
                        }
                      : value,
                  )
              "
            />
          </div>
          <div v-if="node.kind === 'input'" class="grid sm:grid-cols-2 gap-3">
            <FormControl
              type="checkbox"
              :label="'Step ' + (index + 1) + ' optional answer'"
              v-model="node.optional"
              :disabled="busy || !canConfigure"
            />
            <template v-if="node.input_type === 'number'">
              <FormControl
                type="checkbox"
                :label="'Step ' + (index + 1) + ' whole numbers only'"
                v-model="node.integer_only"
                :disabled="busy || !canConfigure"
              />
              <FormControl
                v-for="bound in ['minimum', 'maximum']"
                :key="bound"
                type="number"
                :label="'Step ' + (index + 1) + ' ' + bound"
                :model-value="node[bound] ?? ''"
                @update:model-value="
                  node[bound] = $event === '' ? null : Number($event)
                "
                :disabled="busy || !canConfigure"
              />
            </template>
          </div>
          <RelaySelect
            v-if="node.kind === 'ticket'"
            :label="'Step ' + (index + 1) + ' ticket category'"
            v-model="node.category"
            :options="['Query', 'Payment evidence', 'Support', 'Other']"
            :disabled="busy || !canConfigure"
          />
          <div
            v-if="index < nodes.length - 1"
            class="text-center text-ink-gray-5"
            aria-hidden="true"
          >
            ↓
          </div>
        </div>
        <div class="flex flex-wrap gap-2">
          <Button
            v-if="canConfigure"
            label="Add step"
            :disabled="busy || nodes.length >= 30"
            @click="add"
          /><Button
            v-if="canConfigure"
            label="Save flow draft"
            type="submit"
            variant="solid"
            :disabled="busy"
          /><Button
            v-if="canConfigure && draft.name"
            label="Publish saved version"
            :disabled="busy"
            @click="run(publish)"
          /><Button
            label="Close flow editor"
            :disabled="busy"
            @click="draft = null"
          />
        </div>
      </form>
      <section v-if="draft?.name" class="workflow-card">
        <div class="flex flex-wrap gap-2 items-center">
          <h3 class="font-semibold">Flow runs</h3>
          <Button
            label="Refresh runs"
            :disabled="busy"
            @click="run(() => loadRuns())"
          /><Button
            v-if="runNext"
            label="Next runs"
            :disabled="busy"
            @click="run(() => loadRuns(runNext))"
          />
        </div>
        <p v-if="!runs.length" class="text-sm">No runs yet.</p>
        <div
          v-for="item in runs"
          :key="item.name"
          class="border rounded p-3 space-y-2"
        >
          <strong class="text-sm">{{ item.name }}</strong>
          <p class="text-sm">
            {{ item.status }} · Step {{ item.step + 1 }} ·
            {{ item.display_name || item.relay_contact }}
          </p>
          <p v-if="item.reason" class="text-sm">{{ item.reason }}</p>
          <Button
            label="View responses"
            :disabled="busy"
            @click="run(() => showResponses(item.name))"
          />
          <dl
            v-if="runDetails[item.name]"
            class="space-y-3 rounded border p-3 text-sm"
          >
            <p v-if="!runDetails[item.name].responses.length">
              No answers collected yet.
            </p>
            <div
              v-for="answer in runDetails[item.name].responses"
              :key="answer.field"
            >
              <dt class="font-medium break-words">{{ answer.question }}</dt>
              <dd class="whitespace-pre-wrap break-words">
                {{
                  typeof answer.answer === "object"
                    ? JSON.stringify(answer.answer)
                    : answer.answer
                }}
              </dd>
            </div>
          </dl>
          <Button
            v-if="['Running', 'Waiting'].includes(item.status)"
            label="Cancel run"
            :disabled="busy"
            @click="run(() => cancel(item.name))"
          />
        </div>
      </section>
    </section>
  </div>
</template>
<style scoped>
.flow-step {
  border: 1px solid #dce3ed;
  border-left: 3px solid #4377b9;
  border-radius: 8px;
  padding: 16px;
  min-width: 0;
}
</style>
