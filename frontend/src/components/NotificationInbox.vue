<script setup>
import { useRealtimeRefresh } from "../composables/useRealtimeRefresh";
import { ref, onMounted, onBeforeUnmount } from "vue";
import { Button, ErrorMessage } from "@relay/ui";
import { coreApi } from "../services/coreApi";
const open = ref(false),
  rows = ref([]),
  next = ref(null),
  busy = ref(false),
  error = ref("");
let disposed = false;
async function load(before) {
  if (busy.value) return;
  busy.value = true;
  try {
    const data = await coreApi("collaboration.notifications", { before });
    if (disposed) return;
    rows.value = before
      ? [...rows.value, ...data.items].slice(-120)
      : data.items;
    next.value = data.next;
    error.value = "";
  } catch (e) {
    if (!disposed) error.value = e.message;
  } finally {
    busy.value = false;
  }
}
async function visit(row) {
  try {
    await coreApi("collaboration.mark_notification", { name: row.name }, true);
    row.is_read = 1;
    open.value = false;
    window.location.hash =
      "/messages?contact=" + encodeURIComponent(row.relay_contact) + "&notes=1";
    window.dispatchEvent(
      new CustomEvent("relay-open-notes", { detail: row.relay_contact }),
    );
  } catch (e) {
    error.value = e.message;
  }
}
onMounted(() => load());
onBeforeUnmount(() => { disposed = true; });
useRealtimeRefresh(['Relay Notification'],['notifications'],()=>load());
</script>
<template>
  <div class="notification-inbox" @keydown.esc="open = false">
    <button
      class="notification-toggle"
      aria-label="Notifications"
      :aria-expanded="open"
      @click="
        open = !open;
        if (open) load();
      "
    >
      <svg
        width="17"
        height="17"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="1.5"
      >
        <path
          d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"
        /></svg
      ><span v-if="rows.some((row) => !row.is_read)" class="notification-dot" />
    </button>
    <aside v-if="open" aria-label="Notifications" class="notification-panel">
      <header>
        <h2>Notifications</h2>
        <Button icon="x" label="Close notifications" @click="open = false" />
      </header>
      <ErrorMessage :message="error" />
      <div class="notification-rows">
        <button
          v-for="row in rows"
          :key="row.name"
          :class="{ unread: !row.is_read }"
          @click="visit(row)"
        >
          <small>{{ row.kind }} · {{ row.contact_name }}</small>
          <p>{{ row.body }}</p>
          <time>{{ row.creation }}</time>
        </button>
        <p v-if="!rows.length && !busy" class="notification-empty">
          You’re up to date.
        </p>
        <Button
          v-if="next"
          label="Earlier notifications"
          :disabled="busy"
          @click="load(next)"
        />
      </div>
    </aside>
  </div>
</template>
<style scoped>
.notification-inbox {
  position: relative;
  margin-left: auto;
}
.notification-toggle {
  position: relative;
  display: grid;
  place-items: center;
  padding: 8px;
  border-radius: 6px;
  color: #666;
}
.notification-toggle:hover {
  background: #f3f3f3;
}
.notification-dot {
  position: absolute;
  right: 5px;
  top: 5px;
  width: 6px;
  height: 6px;
  background: #3971d9;
  border-radius: 50%;
}
.notification-panel {
  position: absolute;
  right: 0;
  top: 40px;
  width: 340px;
  max-width: calc(100vw - 32px);
  max-height: 70vh;
  z-index: 60;
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 9px;
  box-shadow: 0 10px 35px #0002;
  display: flex;
  flex-direction: column;
}
.notification-panel header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px;
  border-bottom: 1px solid #eee;
}
.notification-panel h2 {
  font-size: 14px;
  font-weight: 600;
}
.notification-rows {
  overflow: auto;
  min-height: 0;
  padding: 8px;
}
.notification-rows > button:not(.btn) {
  display: block;
  width: 100%;
  padding: 12px;
  text-align: left;
  border-bottom: 1px solid #eee;
  border-radius: 5px;
}
.notification-rows button.unread {
  background: #f3f7ff;
}
.notification-rows small,
.notification-rows time {
  font-size: 10px;
  color: #7b8490;
}
.notification-rows p {
  font-size: 12px;
  line-height: 1.5;
  overflow-wrap: anywhere;
  margin: 4px 0;
}
.notification-rows .notification-empty {
  padding: 20px;
  color: #888;
}
</style>
