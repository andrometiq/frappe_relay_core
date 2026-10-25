import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import { coreApi } from "../services/coreApi";
import { onRealtime, subscribeRoom } from "../services/realtime";
import { useRealtimeRefresh } from "./useRealtimeRefresh";
import { applyProgress, approvedTemplates, mergeCampaign } from "../services/campaignProgress";
import { realtimeRefreshQueue } from "../services/realtimeRefreshQueue";

async function uploadPrivate(file) {
  const form = new FormData();
  form.append("file", file, file.name);
  form.append("is_private", "1");
  const response = await fetch("/api/method/upload_file", { method: "POST", credentials: "same-origin", body: form,
    headers: { "X-Frappe-CSRF-Token": window.frappe?.csrf_token || window.csrf_token || "" } });
  const body = await response.json().catch(() => null);
  if (!response.ok || !body?.message?.file_url) throw Error("The file could not be uploaded. Use a .xlsx or .csv file.");
  return body.message.file_url;
}

export function useCampaigns() {
  const busy = ref(false), error = ref(""), items = ref([]), next = ref(null), campaign = ref(null), sheet = ref(null), templates = ref([]);
  const filter = ref("");
  async function run(fn) {
    busy.value = true; error.value = "";
    try { return await fn(); } catch (e) { error.value = e.message; } finally { busy.value = false; }
  }
  const refresh = () => run(async () => {
    const page = await coreApi("campaigns.directory");
    items.value = page.items; next.value = page.next;
  });
  const open = (name) => run(async () => { campaign.value = await coreApi("bulk_campaigns.read", { name }); sheet.value = null; filter.value = ""; });
  const loadTemplates = () => run(async () => {
    templates.value = await approvedTemplates((after) =>
      coreApi("whatsapp.execute", { operation: "templates.list", arguments: after ? { after } : {} }, true));
  });
  const create = (values) => run(async () => { campaign.value = await coreApi("bulk_campaigns.create", values, true); return campaign.value; });
  const upload = (file) => run(async () => {
    const file_url = await uploadPrivate(file);
    sheet.value = await coreApi("bulk_campaigns.inspect", { name: campaign.value.name, file_url }, true);
  });
  const importRows = (mapping) => run(async () => { campaign.value = await coreApi("bulk_campaigns.import_rows", { name: campaign.value.name, mapping }, true); sheet.value = null; });
  const control = (action) => run(async () => { campaign.value = await coreApi("bulk_campaigns.control", { name: campaign.value.name, action }, true); });
  const page = (status, after) => run(async () => {
    filter.value = status || "";
    const result = await coreApi("bulk_campaigns.read", { name: campaign.value.name, status: status || undefined, after: after || undefined });
    campaign.value = { ...campaign.value, recipients: after ? [...campaign.value.recipients, ...result.recipients] : result.recipients, next: result.next };
  });

  let leave = null;
  watch(() => campaign.value?.name, (name) => { leave?.(); leave = name ? subscribeRoom("Relay Campaign", name) : null; });
  // Counters apply at once; the error, issues and rows follow in one coalesced re-read.
  const reread = realtimeRefreshQueue(async () => {
    const name = campaign.value?.name;
    if (!name) return;
    const fresh = await coreApi("bulk_campaigns.read", { name, status: filter.value || undefined });
    campaign.value = mergeCampaign(campaign.value, fresh);
  }, () => document.visibilityState === "visible", 500);
  const off = onRealtime((event) => {
    if (event.kind === "campaign_progress" && event.name === campaign.value?.name) {
      campaign.value = applyProgress(campaign.value, event);
      reread.schedule("progress");
    } else if (event.kind === "reconnect" && campaign.value) open(campaign.value.name);
  });
  useRealtimeRefresh(["Relay Campaign"], ["campaigns"], refresh);
  onMounted(refresh);
  onBeforeUnmount(() => { off(); leave?.(); reread.dispose(); });
  return { busy, error, items, next, campaign, sheet, templates, filter, refresh, open, loadTemplates, create, upload, importRows, control, page };
}
