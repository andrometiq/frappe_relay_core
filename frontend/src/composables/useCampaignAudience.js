import { computed, onBeforeUnmount, ref, watch } from "vue";
import { attachmentMapping } from '../services/campaignMedia';
import { coreApi } from "../services/coreApi";
import { cleanAudience, emptyAudience, hasAudienceChoice } from "../services/campaignAudience";

const WAIT_MS = 300;

// Contact filters of a Draft campaign with a live count; the last request wins.
// Nothing is counted until a filter, an added contact or `everyone` picks people.
export function useCampaignAudience(campaign, everyone) {
  const options = ref(null), audience = ref(emptyAudience()), mapping = ref({ fields: {}, fixed: {} });
  const chosen = computed(() => hasAudienceChoice(audience.value, everyone.value));
  const preview = ref(null), found = ref([]), error = ref(""), busy = ref(false), counting = ref(false);
  let countTimer = null, searchTimer = null, asked = 0;

  async function load() {
    error.value = "";
    try {
      options.value = await coreApi("campaign_audience.options", { name: campaign.value.name });
      const saved = campaign.value.audience;
      audience.value = { ...emptyAudience(), ...(saved || {}), segments: { ...(saved?.segments || {}) } };
      const own = saved && campaign.value.mapping;
      mapping.value = own ? { ...own, fields: { ...own.fields }, fixed: { ...own.fixed } } : options.value.mapping;
      if (campaign.value.fields.some(field => field.key === 'header_media'))
        mapping.value = attachmentMapping(mapping.value, own?.header_attachment || { mode: 'static', files: [] });
    } catch (e) { error.value = e.message; }
  }

  async function count() {
    const ticket = ++asked;
    if (!chosen.value) { preview.value = null; counting.value = false; return; }
    counting.value = true;
    try {
      const result = await coreApi("campaign_audience.preview", { name: campaign.value.name, audience: cleanAudience(audience.value) }, true);
      if (ticket === asked) { preview.value = result; error.value = ""; }
    } catch (e) {
      if (ticket === asked) error.value = e.message;
    } finally {
      if (ticket === asked) counting.value = false;
    }
  }

  function search(query) {
    clearTimeout(searchTimer);
    if (String(query || "").trim().length < 2) { found.value = []; return; }
    searchTimer = setTimeout(async () => {
      try { found.value = await coreApi("campaign_audience.search", { name: campaign.value.name, query }); } catch (e) { error.value = e.message; }
    }, WAIT_MS);
  }

  async function importContacts() {
    busy.value = true; error.value = "";
    try {
      return await coreApi("campaign_audience.import_contacts", { name: campaign.value.name, audience: cleanAudience(audience.value), mapping: mapping.value }, true);
    } catch (e) { error.value = e.message; } finally { busy.value = false; }
  }

  watch([audience, chosen], () => { clearTimeout(countTimer); countTimer = setTimeout(count, WAIT_MS); }, { deep: true });
  onBeforeUnmount(() => { clearTimeout(countTimer); clearTimeout(searchTimer); });
  return { options, audience, chosen, mapping, preview, found, error, busy, counting, load, search, importContacts };
}
