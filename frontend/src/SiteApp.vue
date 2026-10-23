<script setup>
import { realtimeStatus, startRealtime } from "./services/realtime";
onMounted(startRealtime);
import {
  defineAsyncComponent,
  provide,
  ref,
  computed,
  watch,
  onMounted,
  onErrorCaptured,
} from "vue";
import { FeatherIcon, ErrorMessage } from "@relay/ui";
import { frappeRequest, coreApi } from "./services/coreApi";
import NotificationInbox from "./components/NotificationInbox.vue";
import { useViewRoute } from "./useViewRoute";
if (window.location.hash.split("?")[0] === "#/settings")
  window.location.replace("/desk/relay-settings");
const capabilities = ref({ manage: false, configure: false });
provide("relayCapabilities", capabilities);
onMounted(async () => {
  try {
    capabilities.value = await coreApi("api.capabilities");
  } catch {}
});
const views = {
  Messages: defineAsyncComponent(() => import('./components/ConnectedMessages.vue')),
  Flows: defineAsyncComponent(() => import('./components/WorkflowViewer.vue')),
  WhatsApp: defineAsyncComponent(() => import('./components/WhatsAppWorkspace.vue')),
  Teams: defineAsyncComponent(() => import('./components/TeamsWorkspace.vue')),
  Incoming: defineAsyncComponent(() => import('./components/IncomingWorkspace.vue')),
};
const navigation = [
  {name:'Messages',label:'Business inbox',icon:'inbox'},
  {name:'Teams',label:'Teams',icon:'users'},

  {name:'Flows',label:'Workflow viewer',icon:'git-branch'},
];
const tools = [{name:'Incoming',label:'Unlinked/ambiguous',icon:'inbox',manage:true},{name:'WhatsApp',label:'Templates',icon:'file-text',manage:true}];
const view = useViewRoute(Object.keys(views), "Messages"),
  mobile = ref(false),
  expanded = ref(tools.some((item) => item.name === view.value));
const current = computed(() =>
  [...navigation, ...tools].find((item) => item.name === view.value),
);
const user =
  window.frappe?.session?.user ||
  document.getElementById("app")?.dataset.user ||
  "Account";
const location = window.location;
const logoutError = ref(""),
  loadError = ref("");
onErrorCaptured((error) => {
  if (
    /dynamically imported module|Loading chunk|Importing a module script/.test(
      String(error),
    )
  ) {
    loadError.value = "A new Relay version is available. Refresh to load it.";
    return false;
  }
});
watch(view, () => {
  mobile.value = false;
  if (tools.some((item) => item.name === view.value)) expanded.value = true;
});
async function logout() {
  try {
    await frappeRequest("logout", {}, true);
    location.assign("/login?redirect-to=/relay");
  } catch (e) {
    logoutError.value = e.message;
  }
}
</script>
<template>
  <div
    class="app-shell relay-shell"
    @keydown.esc="mobile = false"
  >
    <button
      v-if="mobile"
      class="relay-nav-backdrop"
      aria-label="Close navigation"
      @click="mobile = false"
    />
    <aside class="app-nav" :class="{ 'mobile-nav-open': mobile }">
      <div class="relay-brand w-full" aria-label="Relay">
        <span class="relay-brand-mark"
          ><FeatherIcon name="message-circle" class="h-4 w-4" /></span
        ><span class="nav-label flex-1 text-left">Relay</span>
      </div>
      <div class="nav-label relay-nav-caption">Workspace</div>
      <nav aria-label="Workspace" class="relay-nav-section">
        <button
          v-for="item in navigation"
          :key="item.name"
          class="nav-item"
          :class="{ active: view === item.name }"
          :aria-label="item.label"
          :aria-current="view === item.name ? 'page' : undefined"
          :title="item.label"
          @click="view = item.name"
        >
          <FeatherIcon :name="item.icon" class="h-4 w-4" /><span
            class="nav-label"
            >{{ item.label }}</span
          >
        </button>
      </nav>
      <button
        class="relay-tools-toggle"
        :aria-expanded="expanded"
        aria-label="Workspace tools"
        @click="expanded = !expanded"
      >
        <FeatherIcon name="grid" class="h-4 w-4" /><span
          class="nav-label flex-1 text-left"
          >Tools</span
        ><FeatherIcon
          :name="expanded ? 'chevron-down' : 'chevron-right'"
          class="nav-label h-3 w-3"
        />
      </button>
      <nav v-if="expanded" aria-label="Tools" class="relay-nav-section">
        <button
          v-for="item in tools.filter(
            (item) => !item.manage || capabilities.manage,
          )"
          :key="item.name"
          class="nav-item"
          :class="{ active: view === item.name }"
          :aria-label="item.label"
          :aria-current="view === item.name ? 'page' : undefined"
          :title="item.label"
          @click="view = item.name"
        >
          <FeatherIcon :name="item.icon" class="h-4 w-4" /><span
            class="nav-label"
            >{{ item.label }}</span
          >
        </button>
      </nav>
      <div class="relay-nav-footer">
        <a
          href="/desk/relay-core"
          class="nav-item"
          aria-label="Frappe Desk"
          title="Frappe Desk"
          ><FeatherIcon name="grid" class="h-4 w-4" /><span class="nav-label"
            >Frappe Desk<FeatherIcon
              name="arrow-up-right"
              class="inline ml-2 h-3 w-3" /></span
        ></a>
        <div class="relay-account">
          <span class="relay-user-avatar" :title="user">{{
            user.slice(0, 1).toUpperCase()
          }}</span
          ><span class="nav-label relay-user-name" :title="user">{{
            user
          }}</span
          ><button
            class="nav-label relay-icon-button"
            aria-label="Sign out"
            title="Sign out"
            @click="logout"
          >
            <FeatherIcon name="log-out" class="h-4 w-4" />
          </button>
        </div>
      </div>
    </aside>
    <main class="workspace">
      <ErrorMessage :message="logoutError" />
      <div v-if="loadError" role="alert" class="p-3 text-sm">
        {{ loadError }}
        <button class="underline" @click="location.reload()">
          Refresh Relay
        </button>
      </div>
      <header class="page-header relay-mobile-page-header">
        <div class="flex items-center gap-3">
          <button
            class="relay-mobile-menu relay-icon-button"
            aria-label="Toggle navigation"
            :aria-expanded="mobile"
            @click="mobile = !mobile"
          >
            <FeatherIcon name="menu" class="h-4 w-4" /></button
          ><h1>Relay</h1>
        </div>
        <div class="flex items-center gap-2"><span v-if="realtimeStatus !== 'Live'" class="relay-connection-state compact" role="status">Reconnecting…</span><NotificationInbox /></div>
      </header>
      <KeepAlive
        ><component :is="views[view]"
      /></KeepAlive>
    </main>

  </div>
</template>
