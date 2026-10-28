import { onMounted, ref, computed, watch } from "vue";
import { useRealtimeRefresh } from "./useRealtimeRefresh";
import { telegramSubmission } from "../services/telegramSubmission";
import { coreApi } from "../services/coreApi";
import { objectValue } from "../components/messageContent";
import { positiveInteger as positive } from "../components/formValidation";
export function useTelegramGroups() {
  const pendingSends = ref({});
  const pendingSend = computed(()=>pendingSends.value[selected.value] || []);
  const pendingCursor = ref(null), pendingPage = ref(null);
  let pendingSequence = 0;
  const knownTopics = ref([]), topicCursor = ref(null);
  const rows = ref([]),
    cursor = ref(null),
    configured = ref(false),
    selected = ref(""),
    tab = ref("Conversation");
  const busy = ref(false),
    error = ref(""),
    notice = ref(""),
    info = ref(null),
    members = ref([]),
    count = ref(null);
  const title = ref(""),
    description = ref(""),
    text = ref(""),
    topic = ref(""),
    topicName = ref(""),
    userId = ref(""),
    member = ref(null),
    invite = ref(""),
    inviteName = ref(""),
    approval = ref(true);
  watch(userId, value => {if (member.value && String(member.value.user?.id) !== value) member.value = null;});
  const group = computed(() =>
    rows.value.find((row) => row.name === selected.value),
  );
  const atBottom = ref(true), newMessages = ref(false);
  let historySequence = 0, refreshPending = false, statusRefreshPending = false;
  const history = ref([]),
    historyCursor = ref(null),
    hasMore = ref(false),
    reply = ref(null);
  const tabs = ["Conversation", "Details", "Members", "Invites", "Topics"];
  async function run(work) {
    if (busy.value) return;
    busy.value = true;
    error.value = "";
    notice.value = "";
    try {
      await work();
    } catch (e) {
      error.value = e.message;
    } finally {
      busy.value = false;
    }
  }
  async function directory(after) {
    const page = await coreApi("telegram.group_chats", {
      ...(after ? { after } : {}),
      limit: 30,
    });
    rows.value = after ? [...rows.value, ...page.items] : page.items;
    cursor.value = page.next;
    configured.value = page.configured;
    if (!after) { selected.value = ""; info.value = null; }
  }
  let groupSearchSequence = 0;
  async function searchGroups(query, signal, after) {
    const request = ++groupSearchSequence;
    const page = await coreApi('telegram.group_chats', {query, limit:30, after}, false, {signal});
    if (signal?.aborted || request !== groupSearchSequence) return [];
    const current = group.value;
    rows.value = after ? [...rows.value, ...page.items] : current && !page.items.some(row=>row.name===current.name) ? [...page.items,current] : page.items;
    cursor.value = page.next;
    return page.items.map(row=>({value:row.name,label:row.label,description:String(row.chat_id)}));
  }
  async function operation(operation, args = {}) {
    if (!group.value) throw Error("Select a group.");
    return (
      await coreApi(
        "telegram.groups",
        { operation, arguments: { chat_id: group.value.chat_id, ...args } },
        true,
      )
    ).result;
  }
  function choose(value) {
    if (busy.value) return;
    ++historySequence; atBottom.value = true; newMessages.value = false;
    history.value = [];
    reply.value = null;
    selected.value = value;
    info.value = null;
    members.value = [];
    member.value = null;
    invite.value = "";
    topic.value = "";
    knownTopics.value = [];topicCursor.value = null;
    text.value = "";
    title.value = "";
    description.value = "";
    count.value = null;
    if (value)
      run(async () => {
        info.value = await operation("info");
        title.value = info.value.title || "";
        description.value = info.value.description || "";
        await loadHistory();
        await restorePending();
      });
  }
  async function loadHistory(older = false) {
    if (!group.value) return;
    const identity = selected.value, sequence = ++historySequence;
    const page = await coreApi("api.messages", {
      contact: group.value.contact,
      channel: group.value.channel,
      sender_endpoint: String(group.value.chat_id),
      limit: 40,
      ...(older && historyCursor.value ? { before: historyCursor.value } : {}),
    });
    if (identity !== selected.value || sequence !== historySequence) return;
    history.value = older
      ? [...page.items, ...history.value].slice(0, 120)
      : page.items;
    historyCursor.value = page.first;
    hasMore.value = page.has_more;
  }
  async function refreshHistory() {
    if (!group.value) return;
    if (busy.value) { refreshPending = true; return; }
    refreshPending = false;
    if (!atBottom.value) { newMessages.value = true; return; }
    await loadHistory();
  }
  useRealtimeRefresh(['Relay Message'], ['messages','message_actions'], refreshHistory);
  watch(busy, value => {
    if (!value && refreshPending) refreshHistory().catch(()=>{});
    if (!value && statusRefreshPending) {statusRefreshPending=false;refreshPendingSends().catch(()=>{});}
  });
  async function latest() {
    await run(async()=>{await loadHistory();atBottom.value=true;newMessages.value=false;});
  }
  async function saveDetails() {
    await operation("title", { title: title.value });
    await operation("description", { description: description.value });
    notice.value = "Group details saved";
  }
  async function lookup() {
    member.value = await operation("member", {
      user_id: positive(userId.value, "user ID"),
    });
  }
  async function memberAction(action) {
    await operation(action, { user_id: positive(userId.value, "user ID") });
    notice.value = "Member action confirmed";
  }
  async function loadTopics(more = false) {
    const page = await coreApi("telegram_topics.directory", {channel:group.value.channel,chat_id:group.value.chat_id,...(more ? {after:topicCursor.value} : {})});
    knownTopics.value = more ? [...knownTopics.value, ...page.items] : page.items;topicCursor.value = page.next;
  }
  async function topicAction(action) {
    const args = { message_thread_id: positive(topic.value, "topic ID") };
    if (action === "topics.edit") args.name = topicName.value;
    await operation(action, args);
    notice.value = "Topic updated";
  }
  async function restorePending(older=false, refresh=false) {
    if(!selected.value)return;
    const identity=selected.value, sequence=++pendingSequence;
    const before=older?pendingCursor.value:refresh?pendingPage.value:null;
    const result=await coreApi('telegram_delivery.pending',{endpoint:identity,...(before?{before}:{})});
    if(identity!==selected.value || sequence!==pendingSequence)return;
    const existing = pendingSends.value[identity] || [];
    pendingSends.value[identity] = older ? [...existing, ...result.items]
      : refresh && before ? existing.map(row => result.items.find(fresh => fresh.action === row.action) || row) : result.items;
    pendingPage.value=before;
    pendingCursor.value=result.next;
  }
  async function checkGroupSend(item) {
    const identity=selected.value,pending=item || pendingSend.value[0];
    if(!pending)return;
    if(busy.value){statusRefreshPending=true;return;}
    await run(async()=>{
      const receipt=await coreApi('messaging.reconcile',{action:pending.action},true);
      pending.status=receipt.status;pending.error=receipt.error;
      if(receipt.status==='Submitted') {
        await telegramSubmission(pending.args,async()=>receipt);
        pendingSends.value[identity]=(pendingSends.value[identity]||[]).filter(row=>row.action!==pending.action);
        if(selected.value===identity){
          if(text.value===pending.args.text)text.value='';
          notice.value='Message sent';await loadHistory();
        }
      }
    });
  }
  async function retryGroupSend(pending) {
    if (pending.status !== 'Rejected') return;
    await run(async () => {
      const receipt = await coreApi('messaging.retry', {action: pending.action}, true);
      notice.value = receipt.status === 'Submitted' ? 'Retry sent' : receipt.error || 'Retry status: ' + receipt.status;
      await restorePending();
      if (receipt.status === 'Submitted') await loadHistory();
    });
  }
  async function refreshPendingSends() {
    if (busy.value) { statusRefreshPending = true; return; }
    await restorePending(false, true);
  }
  useRealtimeRefresh([], ['message_actions'], refreshPendingSends);
  async function send() {
    const sentReply = reply.value;
    const args = { chat_id: group.value.chat_id, text: text.value };
    if (reply.value)
      args.reply_to = positive(
        objectValue(reply.value.provider_context).message_id,
        "reply message ID",
      );
    if (topic.value) args.message_thread_id = positive(topic.value, "topic ID");
    await telegramSubmission(args,async key=>{
      const receipt=await coreApi("telegram.send",{...args,request_key:key},true);
      if(receipt.status!=='Submitted'){
        const list=pendingSends.value[selected.value]||[];
        pendingSends.value[selected.value]=[{action:receipt.action,status:receipt.status,error:receipt.error,args},...list.filter(row=>row.action!==receipt.action)];
        if(pendingSends.value[selected.value].length>50 || pendingPage.value)await restorePending();
      }
      if(receipt.status!=='Submitted')throw Error(receipt.error || (['Queued','Dispatching'].includes(receipt.status)
        ? 'Message queued. Its delivery is not yet confirmed; the draft is retained.'
        : 'Delivery is not confirmed. The draft and original request are retained.'));
      return receipt;
    });
    if (text.value === args.text) text.value = "";
    if (reply.value === sentReply) reply.value = null;
    notice.value = "Message sent";
    await loadHistory();
  }
  onMounted(() => run(() => directory()));

  return {
    pendingSend, pendingCursor, pendingPage, restorePending, checkGroupSend, retryGroupSend, atBottom, newMessages, latest, knownTopics, topicCursor, loadTopics,
    rows,
    cursor,
    configured,
    selected,
    tab,
    busy,
    error,
    notice,
    info,
    members,
    count,
    title,
    description,
    text,
    topic,
    topicName,
    userId,
    member,
    invite,
    inviteName,
    approval,
    group,
    history,
    historyCursor,
    hasMore,
    reply,
    tabs,
    run,
    directory,
    searchGroups,
    operation,
    choose,
    loadHistory,
    saveDetails,
    lookup,
    memberAction,
    topicAction,
    send,
  };
}
