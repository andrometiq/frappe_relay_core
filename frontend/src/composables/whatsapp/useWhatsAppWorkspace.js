import { templateParameterDescriptors } from "../../services/templateParameters";
import {
  ref,
  computed,
  watch,
  onMounted,
  onBeforeUnmount,
  nextTick,
} from "vue";
import { coreApi } from "../../services/coreApi";
import { useWhatsAppCalls } from "./useWhatsAppCalls";
import { useWhatsAppConversation } from "./useWhatsAppConversation";
import { useWhatsAppDelivery } from "./useWhatsAppDelivery";
import { useWhatsAppTemplates } from "./useWhatsAppTemplates";
import { useWhatsAppGroups } from "./useWhatsAppGroups";
export function useWhatsAppWorkspace(props) {
  const editingTemplate = ref("");
  const incomingScroll = ref(null),
    olderCursor = ref(""),
    hasOlder = ref(false);
  const incoming = ref([]),
    conversationCursor = ref(null),
    conversationBusy = ref(false);

  const callPermission = ref(""),
    recording = ref(false),
    recordingURL = ref("");

  const groupInfo = ref(null),
    groupDescription = ref(""),
    inviteLink = ref(""),
    joinRequests = ref([]),
    templateCursor = ref(""),
    groupCursor = ref("");
  const mediaType = ref("text"),
    mediaURL = ref(""),
    mediaCaption = ref(""),
    mediaFilename = ref("");
  const deliveries = ref([]),
    deliveryCursor = ref(""),
    replyTo = ref(""),
    messageText = ref(""),
    bulkContacts = ref([]);
  const isRecipientTab = computed(() =>
    ["Templates", "Messages", "Calls"].includes(tab.value),
  );
  const tab = ref(props.initialTab),
    busy = ref(false),
    error = ref(""),
    notice = ref(""),
    capabilities = ref(null),
    templates = ref([]),
    groups = ref([]);
  const contactCursor = ref(null),
    moreContacts = ref(false);
  const recordType = ref("Customer"),
    record = ref(""),
    contacts = ref([]),
    contact = ref(""),
    group = ref(""),
    text = ref(""),
    subject = ref("");
  const name = ref(""),
    language = ref("en_US"),
    category = ref("UTILITY"),
    body = ref(""),
    template = ref(""),
    creating = ref(false),
    callId = ref(""),
    callState = ref("Idle");
  watch(group, () => {
    groupInfo.value = null;
    inviteLink.value = "";
    joinRequests.value = [];
  });
  const parameterValues = ref({});
  const parameterKeys = computed(() =>
    templateParameterDescriptors(selectedTemplate.value),
  );
  watch(template, () => (parameterValues.value = {}));
  const selectedTemplate = computed(() =>
    templates.value.find((t) => t.id === template.value),
  );
  const supported = computed(
    () =>
      !!capabilities.value &&
      (["Messages", "Deliveries"].includes(tab.value) ||
        !!capabilities.value?.[tab.value.toLowerCase()]),
  );

  const remoteAudio = ref(null);

  let disposed = ref(false),
    pollTimer;

  const api = (method, args = {}) => coreApi("whatsapp." + method, args, true);
  async function execute(operation, arguments_ = {}) {
    if (operation === "calls.recording_limits")
      return coreApi("call_records.recording_limits");
    if (operation === "calls.pending")
      return coreApi("call_records.pending_call");
    if (operation === "calls.connected")
      return coreApi(
        "call_records.connected",
        { provider_id: arguments_.id },
        true,
      );
    if (["events.list", "events.latest"].includes(operation))
      return coreApi("call_records.events", { after: arguments_.after });
    return api("execute", {
      operation,
      arguments: arguments_,
      contact: contact.value,
      business_doctype: recordType.value,
      business_name: record.value,
    });
  }
  async function run(fn) {
    if (busy.value) return;
    busy.value = true;
    error.value = "";
    notice.value = "";
    try {
      await fn();
    } catch (e) {
      error.value = e.message;
    } finally {
      busy.value = false;
    }
  }
  async function refresh() {
    await run(async () => {
      const connection = await coreApi("whatsapp.connection");
      if (!connection.configured) {
        capabilities.value = null;
        return;
      }
      capabilities.value = await execute("capabilities");
      if (
        capabilities.value.templates &&
        (!props.focused || tab.value === "Templates")
      ) {
        const r = await execute("templates.list");
        templates.value = r.data || [];
        templateCursor.value = r.paging?.cursors?.after || "";
      }
      if (
        capabilities.value.groups &&
        tab.value === "Groups"
      ) {
        const r = await execute("groups.list");
        groups.value = groupRows(r);
        groupCursor.value = r.paging?.cursors?.after || "";
      }
    });
  }
  async function loadContacts(next = false) {
    if (!next) contactCursor.value = null;
    contact.value = "";
    bulkContacts.value = [];
    contacts.value = [];
    await run(async () => {
      const r = await api("business_contacts", {
        doctype: recordType.value,
        name: record.value,
        after: contactCursor.value,
      });
      contacts.value = r.contacts;
      moreContacts.value = r.has_more;
      contactCursor.value = r.contacts.at(-1)?.name || null;
    });
  }

  const {
    muted,
    incomingContact,
    toggleMute,
    recordingBlob,
    recordingCallId,
    recordingSaved,
    makePeer,
    pollEvents,
    acceptCall,
    rejectCall,
    releaseMedia,
    startCall,
    endCall,
    stopRecording,
    startRecording,
  } = useWhatsAppCalls({
    incoming,
    callPermission,
    recording,
    recordingURL,
    tab,
    error,
    capabilities,
    contact,
    callId,
    callState,
    remoteAudio,
    disposed,
    execute,
    run,
  });
  const { conversationUpdates, olderMessages } = useWhatsAppConversation({
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
  });
  const { enqueue, loadDeliveries, cancelDelivery, sendMessage } =
    useWhatsAppDelivery({
      mediaType,
      mediaURL,
      mediaCaption,
      mediaFilename,
      deliveries,
      deliveryCursor,
      replyTo,
      messageText,
      notice,
      recordType,
      record,
      contact,
      text,
      body,
      api,
      run,
    });
  const { createTemplate, sendTemplate, nextTemplates } = useWhatsAppTemplates({
    editingTemplate,
    templateCursor,
    bulkContacts,
    notice,
    templates,
    contact,
    text,
    name,
    language,
    category,
    body,
    template,
    creating,
    parameterValues,
    parameterKeys,
    selectedTemplate,
    execute,
    run,
    enqueue,
  });
  const {
    joinCursor, joinApprovalMode, nextJoinRequests, newGroupSubject, newGroupDescription,
    groupRows,
    inspectGroup,
    manageGroup,
    nextGroups,
    createGroup,
    sendGroup,
  } = useWhatsAppGroups({
    groupInfo,
    groupDescription,
    inviteLink,
    joinRequests,
    groupCursor,
    notice,
    groups,
    group,
    text,
    subject,
    body,
    execute,
    run,
    enqueue,
  });
  watch([recordType, record], () => {
    contacts.value = [];
    contact.value = "";
    bulkContacts.value = [];
    moreContacts.value = false;
    contactCursor.value = null;
  });
  onMounted(() => {
    refresh();
    const poll = async () => {
      if (disposed.value) return;
      // Keep active call signaling alive, but stop background inbox polling.
      if (capabilities.value && (!document.hidden || callId.value)) {
        await Promise.all([pollEvents(), conversationUpdates()]);
      }
      if (!disposed.value) pollTimer = setTimeout(poll, 2000);
    };
    pollTimer = setTimeout(poll, 2000);
  });
  onBeforeUnmount(() => {
    disposed.value = true;
    clearTimeout(pollTimer);
    releaseMedia();
    if (recordingURL.value) URL.revokeObjectURL(recordingURL.value);
  });

  return {
    muted,
    incomingContact,
    toggleMute,
    recordingBlob,
    recordingCallId,
    recordingSaved,
    editingTemplate,
    incomingScroll,
    olderCursor,
    hasOlder,
    incoming,
    conversationCursor,
    conversationBusy,
    callPermission,
    recording,
    recordingURL,
    groupInfo,
    groupDescription,
    inviteLink,
    joinRequests,
    templateCursor,
    groupCursor,
    mediaType,
    mediaURL,
    mediaCaption,
    mediaFilename,
    deliveries,
    deliveryCursor,
    replyTo,
    messageText,
    bulkContacts,
    isRecipientTab,
    tab,
    busy,
    error,
    notice,
    capabilities,
    templates,
    groups,
    contactCursor,
    moreContacts,
    recordType,
    record,
    contacts,
    contact,
    group,
    text,
    subject,
    name,
    language,
    category,
    body,
    template,
    creating,
    callId,
    callState,
    parameterValues,
    parameterKeys,
    selectedTemplate,
    supported,
    conversationUpdates,
    olderMessages,
    remoteAudio,
    makePeer,
    pollEvents,
    acceptCall,
    rejectCall,
    api,
    execute,
    run,
    refresh,
    loadContacts,
    createTemplate,
    enqueue,
    loadDeliveries,
    cancelDelivery,
    sendMessage,
    sendTemplate,
    joinCursor, joinApprovalMode, nextJoinRequests, newGroupSubject, newGroupDescription,
    groupRows,
    inspectGroup,
    manageGroup,
    nextTemplates,
    nextGroups,
    createGroup,
    sendGroup,
    releaseMedia,
    startCall,
    endCall,
    stopRecording,
    startRecording,
  };
}
