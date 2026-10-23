<script setup>
import { useRealtimeRefresh } from "../composables/useRealtimeRefresh";
import { computed, onMounted, ref } from "vue";
import { Button, ErrorMessage } from "@relay/ui";
import { coreApi } from "../services/coreApi";
const result = ref(null),
  busy = ref(false),
  error = ref("");
const maximum = computed(() =>
  Math.max(
    1,
    ...(result.value?.daily || []).map((row) => row.incoming + row.outgoing),
  ),
);
async function load() {
  busy.value = true;
  error.value = "";
  try {
    result.value = await coreApi("overview.read");
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
onMounted(load);
const links = [
  ["unlinked", "Unlinked incoming events", "#/incoming"],
  ["failed_events", "Failed incoming events", "/desk/relay-hub-event"],
  ["uncertain", "Unconfirmed message actions", "#/delivery"],
  ["campaigns", "Active or paused campaigns", "#/campaigns"],
];
useRealtimeRefresh(['Relay Message', 'Relay Hub Event', 'Relay Campaign'],['messages', 'incoming', 'campaigns'],()=>{if(!busy.value)return load()});
</script>
<template>
  <section class="overview-workspace">
    <header>
      <div>
        <h2>Workspace overview</h2>
        <p>Recent communication and work that needs attention.</p>
      </div>
      <Button label="Refresh overview" :disabled="busy" @click="load" />
    </header>
    <ErrorMessage :message="error" /><template v-if="result"
      ><p class="overview-caption">
        Last 7 days · Up to {{ result.limit }} recent messages you can access.
        {{
          result.has_more
            ? "More history exists; these are recent activity counts."
            : ""
        }}
      </p>
      <div class="overview-cards">
        <article>
          <span>Incoming</span
          ><strong>{{ result.directions.Incoming || 0 }}</strong>
        </article>
        <article>
          <span>Outgoing</span
          ><strong>{{ result.directions.Outgoing || 0 }}</strong>
        </article>
        <article>
          <span>Conversations</span><strong>{{ result.conversations }}</strong>
        </article>
        <article>
          <span>Failed outgoing messages</span
          ><strong>{{ result.failed_outgoing }}</strong>
        </article>
      </div>
      <section class="overview-chart">
        <div class="overview-chart-title">
          <h3>Message activity</h3>
          <span
            ><i class="incoming-key" />Incoming
            <i class="outgoing-key" />Outgoing</span
          >
        </div>
        <div class="overview-bars">
          <div
            v-for="day in result.daily"
            :key="day.date"
            :aria-label="
              day.date +
              ': ' +
              day.incoming +
              ' incoming, ' +
              day.outgoing +
              ' outgoing'
            "
          >
            <small>{{ day.incoming + day.outgoing }}</small>
            <div class="overview-bar-track">
              <div
                class="overview-bar"
                :style="{
                  height: ((day.incoming + day.outgoing) / maximum) * 100 + '%',
                }"
              >
                <div class="outgoing-bar" :style="{ flex: day.outgoing }" />
                <div class="incoming-bar" :style="{ flex: day.incoming }" />
              </div>
            </div>
            <time>{{ day.date.slice(5) }}</time>
          </div>
        </div>
      </section>
      <section v-if="result.operations" class="overview-operations">
        <h3>Needs attention</h3>
        <div>
          <a v-for="[key, label, url] in links" :key="key" :href="url"
            ><span>{{ label }}</span
            ><strong
              >{{ result.operations[key].count
              }}{{ result.operations[key].more ? "+" : "" }}</strong
            ></a
          >
        </div>
      </section>
      <section v-if="result.recovery" class="workflow-card space-y-3" aria-label="Scheduled recovery">
        <h3 class="font-medium">Scheduled recovery</h3>
        <p class="text-xs text-ink-gray-5">{{ result.recovery.mode }}</p>
        <p role="status" class="text-sm">{{ result.recovery.inactive ? 'Automatic recovery is inactive' : 'Recovery scheduling is active; check recent activity below' }}</p>
        <p v-for="reason in result.recovery.reasons" :key="reason" class="text-sm">{{ reason }}</p>
        <div v-for="job in result.recovery.items" :key="job.label" class="flex flex-wrap justify-between gap-2 border-b py-2 text-sm">
          <span>{{ job.label }}</span><span>{{ job.state }} · {{ job.last_started || 'No recorded start' }}</span>
        </div>
        <p class="text-xs text-ink-gray-5">A recorded start does not prove success. Jobs overdue by more than five minutes need a scheduler or worker check in Frappe Desk.</p>
      </section>
      <p class="overview-caption">
        Updated {{ result.generated_at }}
      </p></template
    >
    <p v-else-if="busy" class="overview-caption" role="status">
      Loading recent activity…
    </p>
  </section>
</template>
<style scoped>
.overview-workspace {
  height: 100%;
  overflow: auto;
  padding: 28px;
  max-width: 1400px;
}
.overview-workspace > header {
  display: flex;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 22px;
}
.overview-workspace h2 {
  font-size: 20px;
  font-weight: 600;
}
.overview-workspace header p,
.overview-caption {
  font-size: 12px;
  color: #7b8490;
  margin-top: 7px;
  line-height: 1.5;
}
.overview-cards {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
  margin: 18px 0 28px;
}
.overview-cards article {
  padding: 20px;
  border: 1px solid #e5e7eb;
  border-radius: 9px;
}
.overview-cards span {
  display: block;
  font-size: 12px;
  color: #7b8490;
}
.overview-cards strong {
  display: block;
  font-size: 29px;
  font-weight: 550;
  margin-top: 12px;
}
.overview-chart {
  border: 1px solid #e5e7eb;
  padding: 22px;
  border-radius: 9px;
}
.overview-chart-title {
  display: flex;
  justify-content: space-between;
  gap: 16px;
}
.overview-workspace h3 {
  font-size: 14px;
  font-weight: 600;
}
.overview-chart-title span {
  font-size: 11px;
  color: #7b8490;
}
.overview-chart-title i {
  display: inline-block;
  width: 8px;
  height: 8px;
  margin: 0 5px 0 10px;
  border-radius: 2px;
}
.incoming-key,
.incoming-bar {
  background: #557eaa;
}
.outgoing-key,
.outgoing-bar {
  background: #b9cce0;
}
.overview-bars {
  display: flex;
  gap: 20px;
  margin-top: 24px;
}
.overview-bars > div {
  flex: 1;
  min-width: 0;
  text-align: center;
}
.overview-bars small,
.overview-bars time {
  font-size: 10px;
  color: #7b8490;
}
.overview-bar-track {
  height: 150px;
  display: flex;
  align-items: end;
  justify-content: center;
  margin: 9px 0;
  border-bottom: 1px solid #eee;
}
.overview-bar {
  display: flex;
  flex-direction: column;
  width: 40px;
  max-width: 80%;
  border-radius: 4px 4px 0 0;
  overflow: hidden;
}
.overview-operations {
  margin: 28px 0;
}
.overview-operations > div {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 14px;
}
.overview-operations a {
  display: flex;
  justify-content: space-between;
  gap: 15px;
  padding: 16px;
  border: 1px solid #e5e7eb;
  border-radius: 7px;
  font-size: 13px;
}
.overview-operations a:hover {
  background: #fafafa;
}
@media (max-width: 640px) {
  .overview-workspace {
    padding: 16px;
  }
  .overview-cards {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 10px;
  }
  .overview-cards article {
    padding: 14px;
  }
  .overview-operations > div {
    grid-template-columns: 1fr;
  }
  .overview-bars {
    gap: 8px;
  }
  .overview-chart {
    padding: 14px;
  }
}
</style>
