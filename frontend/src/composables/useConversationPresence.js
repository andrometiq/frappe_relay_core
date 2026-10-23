import { useRealtimeRefresh } from "./useRealtimeRefresh";
import { watch as watchRoom } from "vue";
import { subscribeRoom, watchDocumentViewers } from "../services/realtime";
import { ref, watch, onMounted, onBeforeUnmount } from "vue";
import { coreApi } from "../services/coreApi";

// Visible-message changes mark reads. Socket events refresh presence without
// writing another heartbeat, avoiding a feedback loop between viewers.
export function useConversationPresence(props, onState) {
  const people = ref([]);
  const marked = new Set();
  let activeViewers=[], typingExpiry;
  let lastHeartbeat = 0;
  let timer,
    reading = false,
    generation = 0,
    confirmed = "";
  async function heartbeat() {
    const business=props.businessDoctype&&props.businessName;
    if (reading || document.visibilityState !== "visible" || !document.hasFocus() || (!props.contact&&!business))
      return;
    const contact = props.contact,
      businessDoctype=props.businessDoctype,
      businessName=props.businessName,
      version = generation,
      visible = props.lastVisible;
    reading = true;
    try {
      const visibleNames = (props.visibleMessages || [])
        .filter((name) => !marked.has(name))
        .slice(0, 50);
      if (visibleNames.length) {
        if(business)await coreApi("business_inbox.mark_visible",{
          doctype:businessDoctype,name:businessName,messages:JSON.stringify(visibleNames),
          ...(visible?{last_read:visible}:{})},true);
        else await coreApi("message_reads.mark",{contact,messages:JSON.stringify(visibleNames)},true);
        if (version !== generation) return;
        visibleNames.forEach((name) => marked.add(name));
        if (marked.size > 500) {
          const recent = [...marked].slice(-150);
          marked.clear();
          recent.forEach((name) => marked.add(name));
        }
      }
      if (!business && (
        visibleNames.length ||
        (visible && visible > confirmed) ||
        Date.now() - lastHeartbeat > 30000
      )) {
        const state = await coreApi(
          "inbox.update",
          {
            contact,
            ...(visible && visible > confirmed ? { last_read: visible } : {}),
          },
          true,
        );
        if (version !== generation) return;
        confirmed = state.last_read || confirmed;
        onState(state);
        lastHeartbeat = Date.now();
      }
      await refreshPresence();
    } catch {
      /* Foreground controls surface actionable API errors. */
    } finally {
      reading = false;
    }
  }
  watch(
    () => [props.contact,props.businessDoctype,props.businessName],
    () => {
      generation++;
      lastHeartbeat = 0;
      confirmed = "";
      marked.clear();
      people.value = [];
      clearTimeout(timer); timer=setTimeout(heartbeat,0);
    },
  );
  watch(
    () => [props.lastVisible, props.visibleMessages],
    () => {
      clearTimeout(timer);
      timer = setTimeout(heartbeat, 1200);
    },
  );
  async function refreshPresence() {
    const contact=props.contact,businessDoctype=props.businessDoctype,businessName=props.businessName,version=generation;
    if((!contact&&!(businessDoctype&&businessName)) || document.visibilityState!=='visible')return;
    try {
      const result=businessDoctype&&businessName
        ? await coreApi('business_inbox.presence',{doctype:businessDoctype,name:businessName})
        : await coreApi('inbox.presence',{contact});
      if(version===generation){
        const profiles=new Map((result.users||[]).map(user=>[user.name,user]));
        people.value=activeViewers.map(name=>profiles.get(name)||{name,full_name:name,typing:false});
        clearTimeout(typingExpiry);typingExpiry=setTimeout(()=>{people.value=people.value.map(user=>({...user,typing:false}));},8000);
      }
    } catch { /* Existing view errors handle access failures. */ }
  }
  function focus(){ heartbeat(); }
  onMounted(() => { heartbeat(); window.addEventListener('focus',focus); });
  onBeforeUnmount(() => {
    generation++; clearTimeout(timer); clearTimeout(typingExpiry); window.removeEventListener('focus',focus);
  });
  let leaveRoom, leaveViewers;
  watchRoom(()=>[props.contact,props.businessDoctype,props.businessName],value=>{
    leaveRoom?.();leaveViewers?.();activeViewers=[];people.value=[];
    const [contact,businessDoctype,businessName]=value;
    const doctype=businessName?businessDoctype:'Relay Contact',name=businessName||contact;
    leaveRoom=name?subscribeRoom(doctype,name):null;
    leaveViewers=name?watchDocumentViewers(doctype,name,users=>{
      const self=document.getElementById('app')?.dataset.user;
      activeViewers=users.filter(user=>user!==self);
      people.value=activeViewers.map(name=>people.value.find(user=>user.name===name)||{name,full_name:name,typing:false});
    }):null;
  },{immediate:true});
  useRealtimeRefresh([],['presence'],refreshPresence);
  onBeforeUnmount(()=>{leaveRoom?.();leaveViewers?.();});
  return { people };
}
