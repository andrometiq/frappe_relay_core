import { resetRecipient } from '../services/recipientContext.js';
import { useRealtimeRefresh } from "./useRealtimeRefresh";
import { sha256Hex, randomUUID } from '../services/crypto.js';
import { computed, inject, onMounted, onBeforeUnmount, ref, watch } from "vue";
import { composerKinds, defaultSendSource } from "../services/enabledChannels.js";
import { coordinates } from "../components/formValidation";
import { coreApi } from "../services/coreApi";
import { messageData, objectValue } from "../components/messageContent";
import { closeRoute, openRoute } from "../useViewRoute.js";

export function useMessages() {
  const capabilities = inject('relayCapabilities', ref({}));
  const contacts = ref([]),
    query = ref(""),
    selected = ref(""),
    rows = ref([]),
    before = ref(null),
    more = ref(false);
  const ingestionCursor = ref('RELAY-MSG-0000000000');
  const attachment = ref(null);
  const pendingMessages=ref([]), pendingCursor=ref(null);
  const rowTime=row=>Date.parse(String(row.sent_at||row.creation||'').replace(' ','T'));
  // A pending or failed send sits at its own time among the loaded messages; one without a time goes last.
  const displayRows=computed(()=>{
    const merged=[...rows.value];
    for(const row of pendingMessages.value.filter(row=>row.scope===(selected.value||businessType.value+':'+businessName.value) && (!channel.value||row.channel===channel.value))){
      const time=rowTime(row), index=Number.isNaN(time)?-1:merged.findIndex(item=>rowTime(item)>time);
      if(index<0)merged.push(row);else merged.splice(index,0,row);
    }
    return merged;
  });
  function beginEmail(message, values, key) {
    const name='pending:email:'+key;
    let pending=pendingMessages.value.find(row=>row.name===name);
    if(!pending) {
      pendingMessages.value.push({name,scope:selected.value||businessType.value+':'+businessName.value,
        channel:message.channel,provider_context:message.provider_context,direction:'Outgoing',
        content:values.body,creation:new Date().toISOString(),_pending:true,
        emailRequest:key,emailSource:message.name});
      pending=pendingMessages.value.at(-1);
    }
    pending.status='Sending';
    return pending;
  }
  async function finishEmail(pending,result) {
    if(!result?.message){pending.status='Unconfirmed';return;}
    pending.status='Sent';
    if(pending.scope===(selected.value||businessType.value+':'+businessName.value))await refreshNew();
    // Retain the acknowledged bubble until its persisted message appears in history.
    pending.persistedMessage=result.message;
    if(rows.value.some(row=>row.name===result.message))pendingMessages.value=pendingMessages.value.filter(row=>row!==pending);
  }
  watch(rows,()=>{pendingMessages.value=pendingMessages.value.filter(pending=>!pending.persistedMessage||!rows.value.some(row=>row.name===pending.persistedMessage));});
  async function checkPending(message) {
    if(message.emailRequest && !message.action) {
      await run(async()=>{
        const result=await coreApi('email.send_status',{message:message.emailSource,request_key:message.emailRequest});
        if(result.message)await finishEmail(message,result);
        else notice.value='Email delivery is still unconfirmed. Checking status does not send again.';
      });
      return;
    }
    if(!message.action)return;
    await run(async()=>{
      const result=await coreApi('messaging.reconcile',{action:message.action},true);
      retireAction(result);
      if(result.status==='Submitted') {
        pendingMessages.value=pendingMessages.value.filter(row=>row.action!==message.action);
        await history();
      } else {
        message.error=result.error||null;
        if(result.error)notice.value=result.error;
        message.status=({Dispatching:'Sending',Rejected:'Failed',Uncertain:'Unconfirmed'})[result.status]||result.status;
        if(result.status==='Uncertain')notice.value='Delivery is still unconfirmed. This message has not been sent again.';
      }
    });
  }
  let pendingSequence = 0;
  async function restorePending(older=false) {
    const sequence = ++pendingSequence;
    const scope=selected.value || (businessName.value ? businessType.value+':'+businessName.value : '');
    if(!scope)return;
    const values=businessName.value ? {business_doctype:businessType.value,business_name:businessName.value} : {contact:selected.value};
    const result=await coreApi('messaging.pending_messages',{...values,...(older&&pendingCursor.value?{before:pendingCursor.value}:{})});
    if((selected.value || businessType.value+':'+businessName.value)!==scope || sequence!==pendingSequence)return;
    const items=result.items||[];
    pendingCursor.value=result.next||null;
    // Keep unresolved local HTTP attempts. Never turn recovery into another send.
    pendingMessages.value=[...pendingMessages.value.filter(row=>row.scope!==scope || (!row.action&&!items.some(item=>item.emailRequest&&item.emailRequest===row.emailRequest)) || (older&&row.action&&!items.some(item=>item.action===row.action))),
      ...items].sort((a,b)=>String(a.creation).localeCompare(String(b.creation)));
  }
  function retireAction(state) {
    if (!['Submitted','Rejected'].includes(state.status)) return;
    const index='relay-typed-result-'+state.action;
    const storage=sessionStorage.getItem(index);
    if(storage)sessionStorage.removeItem(storage);
    sessionStorage.removeItem(index);
  }
  async function retireCompletedActions() {
    const names=Object.keys(sessionStorage).filter(key=>key.startsWith('relay-typed-result-')).map(key=>key.slice('relay-typed-result-'.length));
    for(let i=0;i<names.length;i+=50){
      const result=await coreApi('messaging.action_snapshots',{names:JSON.stringify(names.slice(i,i+50))});
      result.items.forEach(retireAction);
    }
  }
  async function refreshPendingStatuses() {
    const generation=requestSequence, identity=conversationIdentity();
    await retireCompletedActions();
    if(generation!==requestSequence || identity!==conversationIdentity())return;
    const scope=selected.value||businessType.value+':'+businessName.value;
    const items=pendingMessages.value.filter(row=>row.scope===scope&&row.action).slice(0,50);
    if(!items.length)return;
    const result=await coreApi('messaging.action_snapshots',{names:JSON.stringify(items.map(row=>row.action))});
    if(generation!==requestSequence || identity!==conversationIdentity())return;
    const readableActions=new Set(result.items.map(item=>item.action));
    pendingMessages.value=pendingMessages.value.filter(row=>!items.includes(row)||readableActions.has(row.action));
    for(const state of result.items){
      const row=items.find(item=>item.action===state.action);if(!row)continue;
      row.status=({Submitted:'Sent',Dispatching:'Sending',Rejected:'Failed',Uncertain:'Unconfirmed'})[state.status]||state.status;
      row.error=state.error;row.persistedMessage=state.message;
    }
  }
  async function refreshMetadata() {
    const contact=selected.value;if(!contact)return;
    try {const result=await coreApi('api.conversation_channels',{contact});if(selected.value===contact)channels.value=result.items;}catch(e){if([401,403].includes(e.status)){channels.value=[];rows.value=[];clearRecipient();windows.clear();}}
  }
  const businessType = ref(""),
    businessName = ref(""),
    businessContext = ref(null);
  const conversationIdentity = () => businessName.value
    ? JSON.stringify(['business',businessType.value,businessName.value])
    : selected.value ? JSON.stringify(['contact',selected.value]) : '';
  function historyRequest(values = {}) {
    return businessName.value
      ? coreApi("business_inbox.messages", {
          doctype: businessType.value,
          name: businessName.value,
          ...values,
        })
      : coreApi("api.messages", { contact: selected.value, ...values });
  }
  const quoting = ref(false);
  // A source staff chose sends from its own channel; any other source lets the server pick the reply channel.
  const pinnedSource = ref(null);
  const source = ref(null),
    kind = ref("text"),
    body = ref(""),
    emoji = ref("👍"),
    latitude = ref(""),
    longitude = ref("");
  const contactName = ref(""),
    phone = ref(""),
    alsoVia = ref([]),
    // The WhatsApp number staff picked in "Send via"; empty lets the server reply from the newest incoming number.
    viaNumber = ref(""),
    busy = ref(false),
    error = ref(""),
    notice = ref("");
  // Sends in flight and their request keys. New incoming rows can refresh during a send.
  const sending = ref(0), sendingKeys = new Set();
  const newer = ref(false),
    last = ref(null),
    restored = ref(""),
    firstUnread = ref("");
  const windows = new Map(), preferredChannels = new Map();
  let restoredRefreshPending = false;
  const viewPosition = ref(null), newArrivals = ref(0), UNREAD_OFFSET = 56, SNAPSHOT_ROWS = 300;
  let bufferedArrivals = new Map();
  function clearArrivals() { bufferedArrivals.clear(); newArrivals.value=0; }
  const windowKey = () => businessName.value
    ? JSON.stringify(['business', businessType.value, businessName.value, channel.value])
    : selected.value ? JSON.stringify(['contact', selected.value, channel.value]) : '';
  const draftFields = {body,kind,emoji,latitude,longitude,contactName,phone,attachment,quoting,source,alsoVia,viaNumber};
  function clearRecipient() {
    resetRecipient(draftFields);
    error.value = ""; notice.value = "";
  }
  function saveWindow() {
    flushPosition();
    const conversation=selected.value || businessType.value+':'+businessName.value;
    preferredChannels.delete(conversation);preferredChannels.set(conversation,channel.value);
    while(preferredChannels.size>30)preferredChannels.delete(preferredChannels.keys().next().value);
    const key = windowKey();
    if (!businessName.value || !key || !rows.value.length) return;
    windows.delete(key);
    windows.set(key, {rows: rows.value, before: before.value, last: last.value, ingestionCursor:ingestionCursor.value, more:more.value, newer:newer.value, position:viewPosition.value, arrivals:[...bufferedArrivals.values()]});
    while(windows.size>20) windows.delete(windows.keys().next().value);
  }
  function restoreWindow() {
    const saved=windows.get(windowKey());
    if (!saved) { viewPosition.value=null; return false; }
    ingestionCursor.value=saved.ingestionCursor||'RELAY-MSG-0000000000';rows.value=saved.rows;before.value=saved.before;last.value=saved.last;more.value=saved.more;newer.value=saved.newer;
    bufferedArrivals=new Map((saved.arrivals||[]).map(row=>[row.name,row]));newArrivals.value=bufferedArrivals.size;
    viewPosition.value=saved.position;restored.value=saved.position?.atBottom?'':saved.position?.name||'';
    if(!businessName.value && !source.value)source.value=defaultSendSource(rows.value,capabilities.value);
    restoredRefreshPending = true;
    return true;
  }
  let positionTimer, pendingPosition;
  function flushPosition() {
    clearTimeout(positionTimer);
    if(!pendingPosition)return;
    const values=pendingPosition;pendingPosition=null;
    const method=values.business?'business_inbox.save_view':'inbox.save_view';
    if(values.business)delete values.business;
    coreApi(method,values,true,{keepalive:true}).catch(()=>{});
  }
  function rememberPosition(value) {
    viewPosition.value=value;
    if(value.atBottom && !newer.value) showArrivals();
    if(businessName.value)pendingPosition={business:true,doctype:businessType.value,name:businessName.value,
      message:value.name,offset:value.offset,at_bottom:value.atBottom?1:0};
    else if(selected.value)pendingPosition={contact:selected.value,channel:channel.value,message:value.name,offset:value.offset,at_bottom:value.atBottom?1:0};
    else return;
    clearTimeout(positionTimer);positionTimer=setTimeout(flushPosition,800);
  }
  // An opening conversation may pass its view state request, started together with its other reads.
  async function restoreSavedView(usePreferred=false,savedRequest=null) {
    if(!selected.value&&!businessName.value)return;
    const generation=++requestSequence;
    const identity=conversationIdentity();
    const saved=await (savedRequest||(businessName.value
      ? coreApi('business_inbox.view_state',{doctype:businessType.value,name:businessName.value})
      : coreApi('inbox.view_state',{contact:selected.value,...(usePreferred?{}:{channel:channel.value})})));
    if(generation!==requestSequence||identity!==conversationIdentity())return;
    if(!businessName.value&&usePreferred && saved.channel && channels.value.some(row=>row.value===saved.channel)){channel.value=saved.channel;clearRecipient();}
    // A contact conversation opens at its first unread message, otherwise at the newest one.
    const target=businessName.value ? !saved.atBottom && saved.name : saved.first_unread;
    if(!target){await history();return;}
    const [checkpoint,page]=await Promise.all([historyRequest({limit:1,...(channel.value?{channel:channel.value}:{})}),
      businessName.value
        ? coreApi('business_inbox.message_context',{doctype:businessType.value,name:businessName.value,message:target})
        : coreApi('api.message_context',{message:target,...(channel.value?{channel:channel.value}:{})})]);
    if(generation!==requestSequence||identity!==conversationIdentity())return;
    ingestionCursor.value=checkpoint.ingestion_cursor||'RELAY-MSG-0000000000';
    rows.value=page.items;before.value=page.first;last.value=page.last;more.value=page.has_more;newer.value=page.has_newer;
    viewPosition.value=businessName.value ? saved : {name:target,offset:UNREAD_OFFSET,atBottom:false};
    restored.value=target;firstUnread.value=businessName.value ? '' : target;
    if(!source.value)source.value=defaultSendSource(rows.value,capabilities.value);
    updateChannels();
  }
  function appendRows(items) {
    const combined = [...new Map([...rows.value, ...items].map(row=>[row.name,row])).values()]
      .sort((a,b)=>String(a.sent_at||a.creation).localeCompare(String(b.sent_at||b.creation))||a.name.localeCompare(b.name));
    rows.value = combined;
    before.value = rows.value[0]?.name;
    last.value = rows.value.at(-1)?.name || last.value;
    updateChannels();
  }
  function showArrivals() {
    if (!bufferedArrivals.size) return;
    appendRows([...bufferedArrivals.values()]);
    clearArrivals();
  }
  async function latest() {
    await run(async()=>{
      restored.value=''; viewPosition.value=null;
      // Every row up to the newest is loaded: show the buffered arrivals and scroll, without loading again.
      if(!newer.value) showArrivals();
      else {
        // Newer pages stop at once: a page landing after the latest page would add rows out of order.
        newer.value=false;
        const arrivals=[...bufferedArrivals.values()], identity=conversationIdentity();
        const loading=history(), generation=requestSequence;
        await loading;
        if(arrivals.length && generation===requestSequence && identity===conversationIdentity())appendRows(arrivals);
      }
    });
  }
  let requestSequence = 0;
  const connectionError = ref('');
  let refreshing = false, snapshotting = false, sweepQueued = false;
  const changedQueued = new Set();
  function refreshError(err) {
    connectionError.value = err.message || 'Live updates unavailable.';
    if([401,403].includes(err.status)){rows.value=[];pendingMessages.value=[];clearArrivals();clearRecipient();windows.clear();}
  }
  async function refreshNew() {
    if (refreshing || busy.value || !(selected.value || businessName.value) || document.visibilityState !== 'visible') return;
    const generation = requestSequence, identity = conversationIdentity();
    refreshing = true;
    restoredRefreshPending = false;
    try {
      if(!last.value){await history();return;}
      let hasMore = true;
      while (hasMore) {
        const batch = await historyRequest({since:ingestionCursor.value,limit:50,...(channel.value?{channel:channel.value}:{})});
        if (generation !== requestSequence || identity !== conversationIdentity()) return;
        if (batch.items.length) {
          const known = new Set(rows.value.map(row=>row.name));
          // A row this read just brought is current, so a change event naming it needs no second read.
          for (const row of batch.items) { changedQueued.delete(row.name); if (!known.has(row.name)) bufferedArrivals.set(row.name,row); }
          newArrivals.value=bufferedArrivals.size;
          if(!newer.value && (!viewPosition.value || viewPosition.value.atBottom)) showArrivals();
        }
        ingestionCursor.value = batch.ingestion_cursor || ingestionCursor.value;
        hasMore = batch.has_more && batch.items.length > 0;
      }
      connectionError.value = '';
    } catch (err) {
      if (generation === requestSequence && identity === conversationIdentity()) refreshError(err);
    } finally {
      refreshing = false;
      if (restoredRefreshPending) await refreshVisible();
    }
  }
  // A reconnect or a return to the tab re-reads the newest loaded rows once. A live event re-reads only the loaded
  // messages it names; its new messages come from the ingestion cursor instead.
  async function drainSnapshots() {
    if (snapshotting) return;
    if (busy.value || sending.value) { actionRefreshPending=true; return; }
    if (!conversationIdentity() || document.visibilityState !== 'visible') return;
    const generation = requestSequence, identity = conversationIdentity();
    const current = () => generation === requestSequence && identity === conversationIdentity();
    const candidates = [...(sweepQueued ? [...rows.value.slice(-SNAPSHOT_ROWS), ...bufferedArrivals.values()] : []),
      ...[...rows.value, ...bufferedArrivals.values()].filter(row=>changedQueued.has(row.name))];
    const allNames = [...new Set(candidates.filter(row=>!row._pending).map(row=>row.name))];
    sweepQueued=false; changedQueued.clear();
    if (!allNames.length) return;
    snapshotting=true;
    try {
      const snapshots = [];
      for(let offset=0;offset<allNames.length;offset+=150){
        if(!current())return;
        const requests=[];
        for(let start=offset;start<Math.min(offset+150,allNames.length);start+=50){
          const names=JSON.stringify(allNames.slice(start,start+50));
          requests.push(businessName.value ? historyRequest({names,limit:50})
            : coreApi('api.message_snapshots',{contact:selected.value,names}));
        }
        // Wait for the entire wave even on failure, keeping the global limit at three.
        const results=await Promise.allSettled(requests);
        if(!current())return;
        const failed=results.find(result=>result.status==='rejected');
        if(failed)throw failed.reason;
        for(const result of results)snapshots.push(...result.value.items);
      }
      if(!current())return;
      const updated = new Map(snapshots.map(row=>[row.name,row]));
      const checked = new Set(allNames);
      if(source.value && checked.has(source.value.name) && !updated.has(source.value.name))source.value=null;
      // Merge into current rows: a new arrival during this sweep must survive it.
      const merge = items => items.filter(row=>!checked.has(row.name)||updated.has(row.name))
        .map(row=>updated.has(row.name) && JSON.stringify(updated.get(row.name))!==JSON.stringify(row)?updated.get(row.name):row);
      rows.value=merge(rows.value);
      bufferedArrivals=new Map(merge([...bufferedArrivals.values()]).map(row=>[row.name,row]));
      newArrivals.value=bufferedArrivals.size;
    } catch(err) {
      if(current())refreshError(err);
    } finally {
      snapshotting=false;
      if(sweepQueued || changedQueued.size) void drainSnapshots();
    }
  }
  async function refreshLive() {
    await refreshNew();
    void drainSnapshots();
  }
  async function refreshVisible() {
    sweepQueued=true;
    await refreshLive();
  }
  async function refreshDetails(kinds) {
    if(busy.value || sending.value){actionRefreshPending=true;return;}
    const generation=requestSequence, identity=conversationIdentity();
    const current=()=>generation===requestSequence && identity===conversationIdentity();
    if(kinds.has('reconnect') || kinds.has('visible') || kinds.has('message_actions')) {
      windows.clear();
      try { await restorePending(); } catch(e) { if(current() && [401,403].includes(e.status))refreshError(e); }
      if(!current())return;
      await refreshPendingStatuses().catch(()=>{});
    }
    if(current() && (kinds.has('reconnect') || kinds.has('visible') || kinds.has('contacts'))) await refreshMetadata();
  }
  useRealtimeRefresh(['Relay Message','Relay Contact'],['messages','contacts','message_actions','permissions'],async({kinds,messages})=>{
    if(document.visibilityState !== 'visible')return;
    if(kinds.has('reconnect'))pagingError.value='';
    if(kinds.has('permissions')){++requestSequence;windows.clear();rows.value=[];last.value=null;pendingMessages.value=[];clearArrivals();clearRecipient();}
    // Queued before a busy return, so the refresh after the action still re-reads them.
    if(kinds.has('reconnect') || kinds.has('visible'))sweepQueued=true;
    for(const name of messages||[])changedQueued.add(name);
    if(busy.value){actionRefreshPending=true;return;}
    if(kinds.has('reconnect') || kinds.has('visible') || kinds.has('messages') || kinds.has('permissions') || kinds.has('message_actions')) await refreshLive();
    // Recovery and metadata must not hold up the queue's next incoming message.
    void refreshDetails(kinds).catch(()=>{});
  },40);
  let actionRefreshPending = false;
  async function refreshActionState() {
    if (busy.value || sending.value) { actionRefreshPending = true; return; }
    actionRefreshPending = false;
    await refreshLive();
    await refreshDetails(new Set(['visible']));
  }
  watch(() => busy.value || sending.value > 0, value => {
    if (!value && actionRefreshPending) refreshActionState().catch(()=>{});
  });
  onBeforeUnmount(() => { flushPosition(); ++requestSequence; });
  const sourceContext = computed(() =>
    objectValue(source.value?.provider_context),
  );
  const kinds = computed(() => composerKinds(capabilities.value, sourceContext.value));

  const call = (method, values, write) =>
    coreApi(method.replace("relay_core.", ""), values, write);
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
      if (restoredRefreshPending) await refreshVisible();
    }
  }
  const previousContacts = ref(null),
    nextContacts = ref(null),
    channel = ref(""),
    channels = ref([]),
    starred = ref(false),
    directoryMode = ref('all'),
    folder = ref(""),
    team = ref("");
  let directorySequence=0, searchTimer;
  watch(query,()=>{++directorySequence;clearTimeout(searchTimer);searchTimer=setTimeout(()=>findContacts(),300)});
  onBeforeUnmount(()=>{clearTimeout(searchTimer);++directorySequence});
  async function findContacts(cursor = {}) {
    const generation=++directorySequence;
    try {
      const page = await call("relay_core.inbox.directory", {
        query: query.value, starred:starred.value?1:0,folder:folder.value,team:team.value,mode:directoryMode.value,...cursor,
      });
      if(generation!==directorySequence)return;
      contacts.value=page.items;previousContacts.value=page.previous;nextContacts.value=page.next;
    }catch(e){if(generation===directorySequence)error.value=e.message;}
  }

  function filterChannel(value) {
    if(busy.value || channel.value===value) return;
    clearRecipient();saveWindow();clearArrivals();++requestSequence;
    channel.value=value;rows.value=[];source.value=null;quoting.value=false;
    restored.value='';firstUnread.value='';newArrivals.value=0;before.value=null;last.value=null;newer.value=false;more.value=false;
    clearRecipient();
    return restoreWindow() ? refreshVisible() : run(restoreSavedView);
  }

  // Sending picks a channel without filtering the timeline; the newest loaded message of that person on it becomes the source.
  function sendVia(value) {
    if (busy.value) return;
    const contact = source.value?.relay_contact;
    const row = rows.value.findLast(item => item.channel === value && (!contact || item.relay_contact === contact));
    if (!row) return filterChannel(value);
    selectRecipient(row);
    quoting.value = false;
  }
  // A WhatsApp number from "Send via" on a site with several numbers; the draft stays as typed.
  function pickNumber(value) {
    if (busy.value) return;
    quoting.value = false;
    viaNumber.value = value;
  }
  // More channels for one composed message; the picker offers them only when several channels are enabled.
  function toggleAlsoVia(value) {
    alsoVia.value = alsoVia.value.includes(value) ? alsoVia.value.filter(item => item !== value) : [...alsoVia.value, value];
  }

  async function history(older = false) {
    const generation = ++requestSequence,
      identity = conversationIdentity();
    const page = await historyRequest({
      limit: 50,
      ...(channel.value ? { channel: channel.value } : {}),
      ...(older && before.value ? { before: before.value } : {}),
    });
    if (generation !== requestSequence || identity !== conversationIdentity()) return;
    // An older page only adds rows above: loaded rows stay, so nothing below needs loading again.
    const seen = new Set((older ? rows.value : []).map((row) => row.name));
    rows.value = older ? [...page.items.filter((row) => !seen.has(row.name)), ...rows.value] : page.items;
    if(!older){clearArrivals();ingestionCursor.value=page.ingestion_cursor||'RELAY-MSG-0000000000';}
    before.value = page.first;
    if (!older) { last.value = page.last; newer.value = false; }
    more.value = page.has_more;
    updateChannels();
    if (!older && !source.value && !businessName.value) source.value = defaultSendSource(rows.value, capabilities.value);
  }
  function updateChannels() {
    if(channel.value)return;
    const choices=new Map(channels.value.map(row=>[row.value,row]));
    for(const row of rows.value)if(!choices.has(row.channel))choices.set(row.channel,{value:row.channel,label:objectValue(row.provider_context).provider||row.channel});
    channels.value=[...choices.values()];
  }

  function open(contact) {
    if (busy.value || !contact) return;
    clearRecipient();saveWindow();clearArrivals();
    ++requestSequence;
    businessName.value = "";
    businessType.value = "";
    businessContext.value = null;
    restored.value = "";firstUnread.value = "";
    viewPosition.value=null;newArrivals.value=0;
    newer.value = false;
    last.value = null;
    ingestionCursor.value = 'RELAY-MSG-0000000000';
    attachment.value = null;
    selected.value = contact;
    source.value = null;
    quoting.value = false;
    rows.value = [];
    before.value = null;
    more.value = false;
    body.value = "";
    channel.value = preferredChannels.get(contact)||"";
    channels.value = [];
    clearRecipient();
    return run(loading(async () => {
      const saved=coreApi('inbox.view_state',{contact});
      saved.catch(()=>{});
      const [metadata]=await Promise.all([coreApi('api.conversation_channels',{contact}),restorePending()]);
      channels.value=metadata.items;
      await restoreSavedView(true,saved);
    }));
  }
  // A conversation that failed to open stays open with a retry; only a missing or forbidden one leaves.
  const loadFailed = ref(null);
  function loading(work) {
    loadFailed.value = null;
    return async () => {
      try { await work(); }
      catch (e) { loadFailed.value = { status: e.status || 0, message: e.message }; throw e; }
    };
  }
  function retryOpen() {
    if (selected.value) return open(selected.value);
    if (businessName.value) return openBusiness(businessType.value, businessName.value, false);
  }
  function businessRoute(doctype, name, replace = false) {
    const params = new URLSearchParams({ business_doctype: doctype, business_name: name });
    openRoute("#/messages?" + params.toString(), replace);
  }
  function clearSelection(updateRoute = true) {
    clearRecipient();saveWindow();clearArrivals();++requestSequence;loadFailed.value=null;
    selected.value="";businessName.value="";businessType.value="";businessContext.value=null;
    rows.value=[];source.value=null;quoting.value=false;
    if(updateRoute && location.hash.split('?')[0]==='#/messages')closeRoute("#/messages");
  }
  function openBusiness(doctype, record, updateRoute = true) {
    const name=typeof record==='string'?record:record?.name;
    if (busy.value || !doctype || !name) return;
    const switching=!!(selected.value||businessName.value);
    clearRecipient();saveWindow();clearArrivals();
    ++requestSequence;
    selected.value = "";
    businessType.value = doctype;
    businessName.value = name;
    businessContext.value = typeof record==='object' ? {
      name, title:record.label||name, doctype, doctype_label:doctype,
    } : null;
    rows.value = [];
    source.value = null;
    quoting.value = false;
    attachment.value = null;
    body.value = "";
    before.value = null;
    last.value = null;
    ingestionCursor.value = 'RELAY-MSG-0000000000';
    newer.value = false;
    restored.value = "";firstUnread.value = "";
    more.value = false;
    channel.value = "";
    channels.value = [];
    clearRecipient();
    if(updateRoute)businessRoute(doctype,name,switching);
    return run(loading(async()=>{
      businessContext.value=await coreApi('business_inbox.context',{doctype,name});
      if(!restoreWindow())await restoreSavedView();
      await restorePending();
    }));
  }
  // Paging has its own flag: it must not disable the chat or wait for a send.
  // A failed page shows its own retry and does not block the chat.
  const paging = ref(false), pagingError = ref("");
  async function page(work) {
    if (paging.value) return;
    paging.value = true;
    pagingError.value = "";
    try { await work(); } catch (e) { pagingError.value = e.message || "Could not load messages"; } finally { paging.value = false; }
  }
  const loadOlder = () => page(() => history(true));
  async function loadNewer() {
    await page(async () => {
      const generation = requestSequence, identity = conversationIdentity();
      const page = await historyRequest({
        after: last.value,
        limit: 50,
        ...(channel.value ? { channel: channel.value } : {}),
      });
      // A page for a chat the user has left must not land in the open chat.
      if (generation !== requestSequence || identity !== conversationIdentity()) return;
      const seen = new Set(rows.value.map((row) => row.name));
      rows.value = [...rows.value, ...page.items.filter((row) => !seen.has(row.name))];
      last.value = page.last || last.value;
      newer.value = page.has_more;
      for(const row of rows.value)bufferedArrivals.delete(row.name);
      newArrivals.value=bufferedArrivals.size;
      if(!newer.value && viewPosition.value?.atBottom)showArrivals();
    });
  }
  function reply(message) {
    if(businessName.value && (source.value?.channel!==message.channel || source.value?.sender_endpoint!==message.sender_endpoint)) {
      clearRecipient();
    }
    source.value = message;
    quoting.value = true;
  }
  function selectRecipient(message) {
    clearRecipient();
    source.value = message || null;
    pinnedSource.value = source.value;
  }
  async function focusMessage(message) {
    await run(async () => {
      const business={doctype:businessType.value,name:businessName.value};
      const page = business.name
        ? await coreApi('business_inbox.message_context',{...business,message})
        : await coreApi('api.message_context', { message });
      if(business.name){
        ++requestSequence;
        rows.value=page.items;before.value=page.first;last.value=page.last;
        more.value=page.has_more;newer.value=page.has_newer;restored.value=message;
        const recipient=page.items.find(row=>row.name===message);
        if(recipient && (source.value?.channel!==recipient.channel || source.value?.sender_endpoint!==recipient.sender_endpoint)) clearRecipient();
        source.value=recipient||source.value;
        updateChannels();return;
      }
      const changed = selected.value !== page.contact || !!businessName.value;
      if (changed) {clearRecipient();clearArrivals();}
      ++requestSequence;
      businessName.value = '';
      selected.value = page.contact;
      channel.value = '';
      rows.value = page.items;
      before.value = page.first;
      last.value = page.last;
      more.value = page.has_more;
      newer.value = page.has_newer;
      restored.value = message;
      if (!quoting.value) source.value = page.items.find(row => row.name === message);
      updateChannels();
      // A chat opened at a message starts its live updates from now, not from the first message ever.
      if (changed) {
        const identity = conversationIdentity(), checkpoint = await historyRequest({ limit: 1 });
        if (identity !== conversationIdentity()) return;
        ingestionCursor.value = checkpoint.ingestion_cursor || 'RELAY-MSG-0000000000';
      }
    });
  }
  async function openQuote(message) {
    let target;
    await run(async () => {
      const result = await coreApi('api.quoted_message', { message: message.name });
      target = result.message;
      if (!target) notice.value = 'The original message is not available in Relay history.';
    });
    if (target) await focusMessage(target);
  }
  async function send(
    message = source.value,
    action = kind.value,
    data = null,
  ) {
    if (!message) return;
    const submitted = {scope:windowKey(), body:body.value, kind:kind.value, attachment:attachment.value,
      quoting:quoting.value, source:source.value};
    if (!data) {
      if (["photo", "video", "audio", "voice", "document"].includes(action)) {
        if (!attachment.value) {
          error.value = "Choose an attachment first.";
          return;
        }
        data = {
          attachment: attachment.value.name,
          caption:
            sourceContext.value.provider === "WhatsApp" &&
            ["audio", "voice"].includes(action)
              ? ""
              : body.value,
        };
      }
      if (action === "text") data = { text: body.value };
      if (action === "text" && !data.text.trim()) return;
      if (action === "sticker") {
        const media = messageData(message).media || {};
        data = { file_id: media.file_id || media.id || "" };
        if (!data.file_id) {
          error.value = "Select an existing sticker to resend.";
          return;
        }
      }
      if (action === "location") {
        try {
          data = coordinates(latitude.value, longitude.value);
        } catch (e) {
          error.value = e.message;
          return;
        }
      }
      if (action === "contact")
        data = {
          contacts: [
            {
              name: {
                formatted_name: contactName.value,
                first_name: contactName.value,
              },
              phones: [{ phone: phone.value }],
            },
          ],
        };
    }
    error.value = "";
    notice.value = "";
    const quote = action === "reaction" || quoting.value;
    // A picked number sends from its newest loaded message of this person, else the server finds that message.
    // Media stays on the message it was uploaded to; the server moves the attachment to the picked number.
    const media = ["photo", "video", "audio", "voice", "document"].includes(action);
    const picked = !quote && !media && viaNumber.value ? rows.value.findLast(row => row.channel === viaNumber.value && row.relay_contact === message.relay_contact && !row._pending) : null;
    if (picked) message = picked;
    const via = quote || picked ? "" : viaNumber.value || (message === pinnedSource.value ? "" : "auto");
    const extraChannels = ["text", "location", "contact"].includes(action) ? alsoVia.value : [];
    const intent = JSON.stringify({
      quote,
      ...(via && via !== "auto" ? { via } : {}),
      message: message.name,
      kind: action,
      data,
      ...(extraChannels.length ? { channels: extraChannels } : {}),
    });
    const storage = "relay-typed-action-" + sha256Hex(intent);
    let key = sessionStorage.getItem(storage);
    if (!key) {
      key = randomUUID();
      sessionStorage.setItem(storage, key);
    }
    // A second Send of the same content while it is still on its way is the same send.
    if (sendingKeys.has(key)) return;
    sendingKeys.add(key);
    const request = { message: message.name, kind: action, data, request_key: key, quote: quote ? 1 : 0,
      ...(extraChannels.length ? { channels: extraChannels } : {}), ...(via ? { via } : {}) };
    let pending;
    if(action!=='reaction') {
      pending=pendingMessages.value.find(row=>row.name==='pending:'+key);
      if(!pending) {pending={name:'pending:'+key,contact:selected.value,scope:selected.value||businessType.value+':'+businessName.value,channel:message.channel,provider_context:message.provider_context,
        direction:'Outgoing',status:'Sending',content:data.text||data.caption||attachment.value?.filename||action,
        creation:new Date().toISOString(),_pending:true,storage};pendingMessages.value.push(pending);pending=pendingMessages.value.at(-1);}
      else pending.status='Sending';
      pending.request=request;
      quoting.value = false;
      body.value = "";
      attachment.value = null;
      kind.value = "text";
      // A send from an older message jumps to the newest one, where the sent bubble appears.
      restored.value = ""; viewPosition.value = null;
      if (!newer.value) showArrivals();
    }
    await queueSend(() => deliver(request, storage, pending, submitted))
      .finally(() => sendingKeys.delete(key));
  }
  // Sends go out one at a time in the order they were made; the composer does not wait for them.
  let sendQueue = Promise.resolve();
  function queueSend(work) {
    sending.value++;
    const next = sendQueue.then(work).catch(e => { error.value = e.message; }).finally(() => { sending.value--; });
    sendQueue = next;
    return next;
  }
  // Puts the unsent draft back unless the user started a new one.
  function restoreDraft(submitted) {
    if (windowKey() !== submitted.scope || body.value || attachment.value) return;
    body.value = submitted.body;
    kind.value = submitted.kind;
    attachment.value = submitted.attachment;
    if (source.value === submitted.source) quoting.value = submitted.quoting;
  }
  async function deliver(request, storage, pending, submitted) {
    let result;
    try { result = await call("relay_core.messaging.send", request, true); }
    catch(err) {if(pending){pending.status='Unconfirmed';restoreDraft(submitted);}throw err;}
    sessionStorage.setItem('relay-typed-result-'+result.action,storage);
    retireAction(result);
    if(pending) {pending.error=result.error||null;pending.action=result.action;pending.status=({Submitted:'Sent',Dispatching:'Sending',Rejected:'Failed',Uncertain:'Unconfirmed'})[result.status]||result.status;}
    notice.value = result.error || (
      result.status === "Submitted"
        ? ""
        : result.status === "Queued" ? "" : result.status === "Rejected" ? "Message was not sent. Use Retry or Delete on the message." : "Delivery not confirmed. Review the action before retrying.");
    if(result.status==='Submitted')sessionStorage.removeItem(storage);
    restored.value = "";
    await history();
    if(result.status==='Submitted')pendingMessages.value=pendingMessages.value.filter(row=>row!==pending);
    // Unfinished copies on other channels join the same bubble as failed or pending marks.
    if((result.sends||[]).slice(1).some(copy=>!['Submitted','Queued'].includes(copy.status))) {
      notice.value=notice.value||"Some channels did not get this message. Review Message activity for retry options.";
      await restorePending();
    }
  }
  // A message that was not sent: Retry resends it with its own request key, Delete hides it for good.
  function retryPending(message) {
    if (message.action) return queueSend(async () => {
      const result = await coreApi('messaging.retry', { action: message.action }, true);
      retireAction(result);
      pendingMessages.value = pendingMessages.value.filter(row => row !== message);
      await history();
      await restorePending();
    });
    if (!message.request || sendingKeys.has(message.request.request_key)) return;
    message.status = 'Sending';
    sendingKeys.add(message.request.request_key);
    return queueSend(() => deliver(message.request, message.storage, message, { scope: null }))
      .finally(() => sendingKeys.delete(message.request.request_key));
  }
  async function deletePending(message) {
    if (message.action) {
      try { await coreApi('messaging.dismiss', { action: message.action }, true); }
      catch (e) { error.value = e.message; return; }
    } else if (message.storage) sessionStorage.removeItem(message.storage);
    pendingMessages.value = pendingMessages.value.filter(row => row !== message);
  }
  async function uploadAttachment(file) {
    attachment.value = null;
    if (!file) return;
    await run(async () => {
      const content = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result.split(",")[1]);
        reader.onerror = () => reject(Error("Could not read the attachment"));
        reader.readAsDataURL(file);
      });
      attachment.value = await coreApi(
        "attachments.upload",
        {
          message: source.value.name,
          filename: file.name,
          content_base64: content,
        },
        true,
      );
    });
  }
  async function openFromLink() {
    if(location.hash.split('?')[0]!=='#/messages')return;
    const params=new URLSearchParams(location.hash.split('?')[1]||'');
    const businessDoctype=params.get('business_doctype'),business=params.get('business_name');
    if(businessDoctype&&business){
      if(businessDoctype!==businessType.value||business!==businessName.value)
        await openBusiness(businessDoctype,business,false);
      return;
    }
    const anchor=params.get('message'),contact=params.get('contact');
    if(businessName.value||(!anchor&&!contact&&selected.value))clearSelection(false);
    if(anchor && anchor!==restored.value)await focusMessage(anchor);
    else if(contact && contact!==selected.value){
      await open(contact);
      // A missing or forbidden conversation link falls back to the list.
      if([403,404].includes(loadFailed.value?.status)&&selected.value===contact){clearSelection(false);window.history.replaceState(null,"","#/messages");}
    }
  }
  onMounted(async()=>{window.addEventListener('hashchange',openFromLink);window.addEventListener('popstate',openFromLink);await openFromLink()});
  onBeforeUnmount(()=>{window.removeEventListener('hashchange',openFromLink);window.removeEventListener('popstate',openFromLink)});


  return {
    beginEmail, finishEmail, checkPending, pendingCursor, loadPending:()=>run(()=>restorePending(true)), displayRows, viewPosition, rememberPosition, newArrivals, latest,
    clearSelection, clearRecipient, loadFailed, retryOpen,
    businessType,
    businessName,
    businessContext,
    openBusiness,
    attachment,
    uploadAttachment,
    newer,
    last,
    restored,
    firstUnread,
    loadNewer,
    loadOlder,
    paging,
    pagingError,
    contacts,
    starred,
    directoryMode,
    team,
    folder,
    query,
    selected,
    rows,
    before,
    more,
    source,
    quoting,
    cancelReply: () => { quoting.value = false; },
    kind,
    body,
    emoji,
    latitude,
    longitude,
    contactName,
    phone,
    busy,
    error,
    connectionError,
    notice,
    sourceContext,
    kinds,
    previousContacts,
    nextContacts,
    channel,
    channels,
    findContacts,
    filterChannel,
    sendVia,
    viaNumber,
    pinnedSource,
    pickNumber,
    alsoVia,
    toggleAlsoVia,
    history,
    open,
    reply,
    selectRecipient,
    focusMessage,
    openQuote,
    send,
    sending,
    retryPending,
    deletePending,
    run,
  };
}
