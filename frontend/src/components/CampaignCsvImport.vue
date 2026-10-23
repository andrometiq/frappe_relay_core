<script setup>
import { ref } from "vue";
import { Button, ErrorMessage } from "@relay/ui";
import { coreApi } from "../services/coreApi";
import { recipientsFromCsv, csvTemplate } from "../services/campaignCsv";
const props = defineProps({ campaign: Object, contacts: Array });
const emit = defineEmits(["imported", "busy"]);
const rows = ref([]),
  error = ref(""),
  busy = ref(false),
  progress = ref(0),
  filename = ref("");
function download() {
  const url = URL.createObjectURL(
    new Blob([csvTemplate(props.campaign, props.contacts || [])], {
      type: "text/csv;charset=utf-8",
    }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = "relay-campaign-recipients.csv";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
async function selected(event) {
  rows.value = [];
  progress.value = 0;
  error.value = "";
  const file = event.target.files?.[0];
  if (!file) return;
  try {
    if (file.size > 512 * 1024) throw Error("Choose a CSV up to 512 KiB");
    rows.value = recipientsFromCsv(props.campaign, await file.text());
    filename.value = file.name;
  } catch (e) {
    error.value = e.message;
  }
}
async function add() {
  busy.value = true;
  emit("busy", true);
  error.value = "";
  try {
    while (progress.value < rows.value.length) {
      await coreApi(
        "campaigns.add_recipients",
        {
          name: props.campaign.name,
          contacts: rows.value.slice(progress.value, progress.value + 50),
        },
        true,
      );
      progress.value = Math.min(rows.value.length, progress.value + 50);
    }
    emit("imported");
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
    emit("busy", false);
  }
}
</script>
<template>
  <section
    class="border rounded-lg p-3 space-y-3"
    aria-label="CSV audience import"
  >
    <h4 class="font-medium">Import an audience</h4>
    <p class="text-sm text-ink-gray-5">
      Use existing Contact references linked to this campaign’s business record.
      Optional message columns personalize each recipient. Importing updates the
      draft; it does not start delivery.
    </p>
    <Button
      label="Download CSV template"
      :disabled="busy"
      @click="download"
    /><label class="block text-sm"
      >CSV file<input
        type="file"
        accept=".csv,text/csv"
        class="block mt-2 max-w-full"
        :disabled="busy"
        @change="selected" /></label
    ><ErrorMessage :message="error" /><template v-if="rows.length"
      ><p class="text-sm">
        {{ filename }} · {{ rows.length }} recipients · {{ progress }} added
      </p>
      <div class="max-h-48 overflow-auto text-sm border rounded p-2">
        <p
          v-for="row in rows.slice(0, 20)"
          :key="row.contact"
          class="py-1 break-words"
        >
          {{ row.contact }} ·
          {{
            row.arguments.body ||
            row.arguments.components
              .flatMap((c) =>
                (c.parameters || []).map(
                  (p) => p.text || p[p.type]?.link || p[p.type]?.id || "",
                ),
              )
              .join(" · ")
          }}
        </p>
        <p v-if="rows.length > 20">Showing the first 20 recipients.</p>
      </div>
      <Button
        :label="
          progress === rows.length
            ? 'Imported'
            : progress
              ? 'Continue importing'
              : 'Add CSV recipients to draft'
        "
        :loading="busy"
        :disabled="progress === rows.length"
        @click="add"
    /></template>
  </section>
</template>
