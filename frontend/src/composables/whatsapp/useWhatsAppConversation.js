import { nextTick, watch } from "vue";
export function useWhatsAppConversation({
  incomingScroll,
  olderCursor,
  hasOlder,
  incoming,
  conversationCursor,
  conversationBusy,
  tab,
  error,
  capabilities,
  recordType,
  record,
  contact,
  disposed,
  api,
}) {
  let conversationGeneration = 0;
  watch([contact, recordType, record], () => {
    incoming.value = [];
    conversationCursor.value = null;
    olderCursor.value = "";
    hasOlder.value = false;
    conversationGeneration++;
  });
  async function conversationUpdates() {
    if (
      disposed.value ||
      conversationBusy.value ||
      document.hidden ||
      tab.value !== "Messages" ||
      !contact.value ||
      !capabilities.value
    )
      return;
    const generation = conversationGeneration;
    conversationBusy.value = true;
    try {
      const r = await api("conversation", {
        contact: contact.value,
        business_doctype: recordType.value,
        business_name: record.value,
        after: conversationCursor.value,
      });
      if (generation !== conversationGeneration || disposed.value) return;
      const seen = new Set(incoming.value.map((m) => m.id));
      incoming.value = [
        ...incoming.value,
        ...(r.messages || []).filter((m) => !seen.has(m.id)),
      ].slice(-200);
      if (conversationCursor.value === null) {
        olderCursor.value = r.first || "";
        hasOlder.value = r.has_more;
        await nextTick();
        if (incomingScroll.value)
          incomingScroll.value.scrollTop = incomingScroll.value.scrollHeight;
      }
      conversationCursor.value = r.next;
    } catch (e) {
      error.value = e.message;
    } finally {
      conversationBusy.value = false;
    }
  }

  async function olderMessages() {
    if (conversationBusy.value || !olderCursor.value) return;
    conversationBusy.value = true;
    const generation = conversationGeneration;
    const element = incomingScroll.value,
      oldHeight = element?.scrollHeight || 0;
    try {
      const r = await api("conversation", {
        contact: contact.value,
        business_doctype: recordType.value,
        business_name: record.value,
        before: olderCursor.value,
      });
      if (generation !== conversationGeneration) return;
      const seen = new Set(incoming.value.map((m) => m.id));
      incoming.value = [
        ...(r.messages || []).filter((m) => !seen.has(m.id)),
        ...incoming.value,
      ].slice(0, 200);
      olderCursor.value = r.first || olderCursor.value;
      hasOlder.value = r.has_more;
      await nextTick();
      if (element) element.scrollTop += element.scrollHeight - oldHeight;
    } catch (e) {
      error.value = e.message;
    } finally {
      conversationBusy.value = false;
    }
  }
  return { conversationUpdates, olderMessages };
}
