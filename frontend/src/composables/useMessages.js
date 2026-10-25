import { resetRecipient } from '../services/recipientContext.js';
import { useRealtimeRefresh } from "./useRealtimeRefresh";
import { sha256Hex, randomUUID } from '../services/crypto.js';
import { computed, onMounted, onBeforeUnmount, ref, watch } from "vue";
import { coordinates } from "../components/formValidation";
import { coreApi } from "../services/coreApi";
import { messageData, objectValue } from "../components/messageContent";

export function useMessages() {
  const contacts = ref([]),
    query = ref(""),
    selected = ref(""),
    rows = ref([]),
    before = ref(null),
    more = ref(false);
  const ingestionCursor = ref('RELAY-MSG-0000000000');
  const attachment = ref(null);
  const pendingMessages=ref([]), pendingCursor=ref(null);
  const displayRows=computed(()=>[...rows.value,...pendingMessages.value.filter(row=>row.scope===(selected.value||businessType.value+':'+businessName.value) && (!channel.value||row.channel===channel.value))]);
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
    if(pending.scope===(selected.value||businessType.value+':'+businessName.value))await refreshVisible();
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
    await retireCompletedActions();
    const scope=selected.value||businessType.value+':'+businessName.value;
    const items=pendingMessages.value.filter(row=>row.scope===scope&&row.action).slice(0,50);
    if(!items.length)return;
    const result=await coreApi('messaging.action_snapshots',{names:JSON.stringify(items.map(row=>row.action))});
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
  const source = ref(null),
    kind = ref("text"),
    body = ref(""),
    emoji = ref("👍"),
    latitude = ref(""),
    longitude = ref("");
  const contactName = ref(""),
    phone = ref(""),
    busy = ref(false),
    error = ref(""),
    notice = ref("");
  const newer = ref(false),
    last = ref(null),
    restored = ref(""),
    firstUnread = ref("");
  const windows = new Map(), preferredChannels = new Map();
  let restoredRefreshPending = false;
  const viewPosition = ref(null), newArrivals = ref(0), UNREAD_OFFSET = 56;
  const windowKey = () => businessName.value
    ? JSON.stringify(['business', businessType.value, businessName.value, channel.value])
    : selected.value ? JSON.stringify(['contact', selected.value, channel.value]) : '';
  const draftFields = {body,kind,emoji,latitude,longitude,contactName,phone,attachment,quoting,source};
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
    windows.set(key, {rows: rows.value, before: before.value, last: last.value, ingestionCursor:ingestionCursor.value, more:more.value, newer:newer.value, position:viewPosition.value});
    while(windows.size>20) windows.delete(windows.keys().next().value);
  }
  function restoreWindow() {
    const saved=windows.get(windowKey());
    if (!saved) { viewPosition.value=null; return false; }
    ingestionCursor.value=saved.ingestionCursor||'RELAY-MSG-0000000000';rows.value=saved.rows;before.value=saved.before;last.value=saved.last;more.value=saved.more;newer.value=saved.newer;
    viewPosition.value=saved.position;restored.value=saved.position?.atBottom?'':saved.position?.name||'';
    if(!businessName.value && !source.value)source.value=rows.value.at(-1)||null;
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
    if(businessName.value)pendingPosition={business:true,doctype:businessType.value,name:businessName.value,
      message:value.name,offset:value.offset,at_bottom:value.atBottom?1:0};
    else if(selected.value)pendingPosition={contact:selected.value,channel:channel.value,message:value.name,offset:value.offset,at_bottom:value.atBottom?1:0};
    else return;
    clearTimeout(positionTimer);positionTimer=setTimeout(flushPosition,800);
  }
  async function restoreSavedView(usePreferred=false) {
    if(!selected.value&&!businessName.value)return;
    const generation=++requestSequence;
    const identity=conversationIdentity();
    const saved=businessName.value
      ? await coreApi('business_inbox.view_state',{doctype:businessType.value,name:businessName.value})
      : await coreApi('inbox.view_state',{contact:selected.value,...(usePreferred?{}:{channel:channel.value})});
    if(generation!==requestSequence||identity!==conversationIdentity())return;
    if(!businessName.value&&usePreferred && saved.channel && channels.value.some(row=>row.value===saved.channel)){channel.value=saved.channel;clearRecipient();}
    // A contact conversation opens at its first unread message, otherwise at the newest one.
    const target=businessName.value ? !saved.atBottom && saved.name : saved.first_unread;
    if(!target){await history();return;}
    const checkpoint=await historyRequest({limit:1,...(channel.value?{channel:channel.value}:{})});
    if(generation!==requestSequence||identity!==conversationIdentity())return;
    ingestionCursor.value=checkpoint.ingestion_cursor||'RELAY-MSG-0000000000';
    const page=businessName.value
      ? await coreApi('business_inbox.message_context',{doctype:businessType.value,name:businessName.value,message:target})
      : await coreApi('api.message_context',{message:target,...(channel.value?{channel:channel.value}:{})});
    if(generation!==requestSequence||identity!==conversationIdentity())return;
    rows.value=page.items;before.value=page.first;last.value=page.last;more.value=page.has_more;newer.value=page.has_newer;
    viewPosition.value=businessName.value ? saved : {name:target,offset:UNREAD_OFFSET,atBottom:false};
    restored.value=target;firstUnread.value=businessName.value ? '' : target;
    if(!source.value)source.value=rows.value.at(-1)||null;
    updateChannels();
  }
  async function latest() {
    await run(async()=>{restored.value=''; viewPosition.value=null; newArrivals.value=0; await history();});
  }
  let requestSequence = 0;
  const connectionError = ref('');
  let refreshing = false;
  async function refreshVisible() {
    if (refreshing || busy.value || !(selected.value || businessName.value) || document.visibilityState !== 'visible') return;
    const generation = requestSequence, identity = conversationIdentity();
    refreshing = true;
    restoredRefreshPending = false;
    try {
      if(!last.value){await history();return;}
      const page = {items:[]};
      let cursor = ingestionCursor.value, hasMore = true;
      while (hasMore) {
        const batch = await historyRequest({since:cursor,limit:50,...(channel.value?{channel:channel.value}:{})});
        if (generation !== requestSequence || identity !== conversationIdentity()) return;
        page.items.push(...batch.items);
        cursor = batch.ingestion_cursor || cursor;
        hasMore = batch.has_more && batch.items.length > 0;
      }
      if (generation !== requestSequence || identity !== conversationIdentity()) return;
      if (rows.value.length) {
        const names = JSON.stringify(rows.value.filter(row=>!row._pending).map(row=>row.name));
        const snapshots = {items:[]};
        const allNames = JSON.parse(names);
        for(let offset=0;offset<allNames.length;offset+=50){
          const batchNames=JSON.stringify(allNames.slice(offset,offset+50));
          const batch=businessName.value ? await historyRequest({names:batchNames,limit:50})
            : await coreApi('api.message_snapshots',{contact:selected.value,names:batchNames});
          snapshots.items.push(...batch.items);
        }
        if (generation !== requestSequence || identity !== conversationIdentity()) return;
        const updated = new Map(snapshots.items.map(row=>[row.name,row]));
        const checked = new Set(JSON.parse(names));
        if(source.value && checked.has(source.value.name) && !updated.has(source.value.name))source.value=null;
        rows.value = rows.value.filter(row=>!checked.has(row.name)||updated.has(row.name)).map(row=>updated.get(row.name)||row);
      }
      connectionError.value = '';
      if (page.items.length) {
        if(viewPosition.value && !viewPosition.value.atBottom) { newArrivals.value=page.items.length; return; }
        const known = new Set(rows.value.map(row => row.name));
        const combined = [...rows.value, ...page.items.filter(row => !known.has(row.name))].sort((a,b)=>String(a.sent_at||a.creation).localeCompare(String(b.sent_at||b.creation))||a.name.localeCompare(b.name));
        rows.value = combined.slice(-150);
        if (combined.length > 150) more.value = true;
        before.value = rows.value[0]?.name;
        last.value = rows.value.at(-1)?.name || last.value;
        updateChannels();
      }
      ingestionCursor.value = cursor;
    } catch (err) {
      if (generation === requestSequence) {
        connectionError.value = err.message || 'Live updates unavailable.';
        if([401,403].includes(err.status)){rows.value=[];pendingMessages.value=[];clearRecipient();windows.clear();}
      }
    } finally {
      refreshing = false;
      if (restoredRefreshPending) await refreshVisible();
    }
  }
  useRealtimeRefresh(['Relay Message','Relay Contact'],['messages','contacts','message_actions','permissions'],async({kinds})=>{
    if(kinds.has('permissions')){++requestSequence;windows.clear();rows.value=[];last.value=null;pendingMessages.value=[];clearRecipient();}
    if(busy.value){actionRefreshPending=true;return;}
    if(kinds.has('reconnect') || kinds.has('visible') || kinds.has('message_actions')) {
      windows.clear();
      try { await restorePending(); } catch(e) { if([401,403].includes(e.status)){pendingMessages.value=[];rows.value=[];clearRecipient();} }
    }
    if(kinds.has('reconnect') || kinds.has('visible') || kinds.has('message_actions')) await refreshPendingStatuses().catch(()=>{});
    if(kinds.has('reconnect') || kinds.has('visible') || kinds.has('messages') || kinds.has('permissions') || kinds.has('message_actions')) await refreshVisible();
    if(kinds.has('reconnect') || kinds.has('visible') || kinds.has('contacts')) await refreshMetadata();
  });
  let actionRefreshPending = false;
  async function refreshActionState() {
    if (busy.value) { actionRefreshPending = true; return; }
    actionRefreshPending = false;
    await restorePending();
    await refreshPendingStatuses();
    await refreshVisible();
    await refreshMetadata();
  }
  watch(busy, value => {
    if (!value && actionRefreshPending) refreshActionState().catch(()=>{});
  });
  onBeforeUnmount(() => { flushPosition(); ++requestSequence; });
  const sourceContext = computed(() =>
    objectValue(source.value?.provider_context),
  );
  const whatsappGroup = computed(
    () =>
      sourceContext.value.provider === "WhatsApp" &&
      sourceContext.value.group_id,
  );
  const kinds = computed(() =>
    whatsappGroup.value
      ? ["text", "sticker", "photo", "video", "audio", "document"]
      : [
          "text",
          "sticker",
          "location",
          "contact",
          ...(sourceContext.value.provider === "Telegram"
            ? ["photo", "video", "audio", "voice", "document"]
            : sourceContext.value.provider === "WhatsApp"
              ? ["photo", "video", "audio", "document"]
              : []),
        ],
  );

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
    clearRecipient();saveWindow();++requestSequence;
    channel.value=value;rows.value=[];source.value=null;quoting.value=false;
    restored.value='';firstUnread.value='';newArrivals.value=0;before.value=null;last.value=null;newer.value=false;more.value=false;
    clearRecipient();
    return restoreWindow() ? refreshVisible() : run(restoreSavedView);
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
    const seen = new Set((older ? rows.value : []).map((row) => row.name));
    rows.value = older
      ? [
          ...page.items.filter((row) => !seen.has(row.name)),
          ...rows.value,
        ].slice(0, 150)
      : page.items;
    if(!older)ingestionCursor.value=page.ingestion_cursor||'RELAY-MSG-0000000000';
    before.value = page.first;
    last.value = older ? rows.value.at(-1)?.name : page.last;
    newer.value = older && (rows.value.length >= 150 || newer.value);
    more.value = page.has_more;
    updateChannels();
    if (!older && !source.value && !businessName.value) source.value = rows.value.at(-1) || null;
  }
  function updateChannels() {
    if(channel.value)return;
    const choices=new Map(channels.value.map(row=>[row.value,row]));
    for(const row of rows.value)if(!choices.has(row.channel))choices.set(row.channel,{value:row.channel,label:objectValue(row.provider_context).provider||row.channel});
    channels.value=[...choices.values()];
  }

  function open(contact) {
    if (busy.value || !contact) return;
    clearRecipient();saveWindow();
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
    return run(async () => {
      const metadata=await coreApi('api.conversation_channels',{contact});
      channels.value=metadata.items;
      await restorePending();
      await restoreSavedView(true);
    });
  }
  function businessRoute(doctype, name, replace = false) {
    const params = new URLSearchParams({ business_doctype: doctype, business_name: name });
    const route = "#/messages?" + params.toString();
    if (location.hash === route) return;
    window.history[replace ? "replaceState" : "pushState"](null, "", route);
  }
  function clearSelection(updateRoute = true) {
    clearRecipient();saveWindow();++requestSequence;
    selected.value="";businessName.value="";businessType.value="";businessContext.value=null;
    rows.value=[];source.value=null;quoting.value=false;
    if(updateRoute && location.hash.split('?')[0]==='#/messages')window.history.pushState(null,"","#/messages");
  }
  function openBusiness(doctype, record, updateRoute = true) {
    const name=typeof record==='string'?record:record?.name;
    if (busy.value || !doctype || !name) return;
    clearRecipient();saveWindow();
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
    if(updateRoute)businessRoute(doctype,name);
    return run(async()=>{
      businessContext.value=await coreApi('business_inbox.context',{doctype,name});
      if(!restoreWindow())await restoreSavedView();
      await restorePending();
    });
  }
  async function loadNewer() {
    await run(async () => {
      const page = await historyRequest({
        after: last.value,
        limit: 50,
        ...(channel.value ? { channel: channel.value } : {}),
      });
      const seen = new Set(rows.value.map((row) => row.name));
      rows.value = [
        ...rows.value,
        ...page.items.filter((row) => !seen.has(row.name)),
      ].slice(-150);
      last.value = page.last || last.value;
      newer.value = page.has_more;
      before.value = rows.value[0]?.name;
      more.value = true;
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
      if (changed) clearRecipient();
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
    const submitted = {scope:windowKey(), body:body.value, attachment:attachment.value,
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
    await run(async () => {
      const quote = action === "reaction" || quoting.value;
      const intent = JSON.stringify({
        quote,
        message: message.name,
        kind: action,
        data,
      });
      const digest = sha256Hex(intent);
      const storage = "relay-typed-action-" + digest;
      let key = sessionStorage.getItem(storage);
      if (!key) {
        key = randomUUID();
        sessionStorage.setItem(storage, key);
      }
      let pending;
      if(action!=='reaction') {
        pending=pendingMessages.value.find(row=>row.name==='pending:'+key);
        if(!pending) {pending={name:'pending:'+key,contact:selected.value,scope:selected.value||businessType.value+':'+businessName.value,channel:message.channel,provider_context:message.provider_context,
          direction:'Outgoing',status:'Sending',content:data.text||data.caption||attachment.value?.filename||action,
          creation:new Date().toISOString(),_pending:true};pendingMessages.value.push(pending);pending=pendingMessages.value.at(-1);}
        else pending.status='Sending';
      }
      let result;
      try { result = await call(
        "relay_core.messaging.send",
        { message: message.name, kind: action, data, request_key: key, quote: quote ? 1 : 0 },
        true,
      ); } catch(err) {if(pending)pending.status='Unconfirmed';throw err;}
      sessionStorage.setItem('relay-typed-result-'+result.action,storage);
      retireAction(result);
      if(pending) {pending.error=result.error||null;pending.action=result.action;pending.status=({Submitted:'Sent',Dispatching:'Sending',Rejected:'Failed',Uncertain:'Unconfirmed'})[result.status]||result.status;}
      notice.value = result.error || (
        result.status === "Submitted"
          ? ""
          : result.status === "Queued" ? "" : result.status === "Rejected" ? "Message was not sent. Review Message activity for retry options." : "Delivery not confirmed. Review the action before retrying.");
      if (['Submitted','Queued'].includes(result.status)) {
        if(result.status==='Submitted')sessionStorage.removeItem(storage);
        if (action !== 'reaction' && windowKey() === submitted.scope) {
          if (quoting.value === submitted.quoting && source.value === submitted.source) quoting.value = false;
          if (body.value === submitted.body) body.value = "";
          if (attachment.value === submitted.attachment) attachment.value = null;
        }
      }
      restored.value = "";
      await history();
      if(result.status==='Submitted')pendingMessages.value=pendingMessages.value.filter(row=>row!==pending);
    });
  }
  async function uploadAttachment(file) {
    attachment.value = null;
    if (!file) return;
    if (file.size < 1 || file.size > 4 * 1024 * 1024) {
      error.value = "Choose a file up to 4 MiB.";
      return;
    }
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
    if(businessName.value)clearSelection(false);
    const anchor=params.get('message'),contact=params.get('contact');
    if(anchor && anchor!==restored.value)await focusMessage(anchor);
    else if(contact && contact!==selected.value)open(contact);
  }
  onMounted(async()=>{window.addEventListener('hashchange',openFromLink);window.addEventListener('popstate',openFromLink);await openFromLink()});
  onBeforeUnmount(()=>{window.removeEventListener('hashchange',openFromLink);window.removeEventListener('popstate',openFromLink)});


  return {
    beginEmail, finishEmail, checkPending, pendingCursor, loadPending:()=>run(()=>restorePending(true)), displayRows, viewPosition, rememberPosition, newArrivals, latest,
    clearSelection, clearRecipient,
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
    whatsappGroup,
    kinds,
    previousContacts,
    nextContacts,
    channel,
    channels,
    findContacts,
    filterChannel,
    history,
    open,
    reply,
    selectRecipient,
    focusMessage,
    openQuote,
    send,
    run,
  };
}
