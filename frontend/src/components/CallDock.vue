<script setup>
import { inject } from "vue";
import { Button, Badge, ErrorMessage } from "@relay/ui";
import { callingKey } from "../composables/whatsapp/context";
const {
  callId,
  callState,
  pollEvents,
  busy,
  error,
  remoteAudio,
  muted,
  toggleMute,
  acceptCall,
  rejectCall,
  endCall,
  incomingContact,
  recording,
  stopRecording,
} = inject(callingKey);
</script>
<template>
  <div class="relay-call-host contents">
    <audio ref="remoteAudio" autoplay class="hidden" />
    <section
      v-if="callId || callState === 'Outcome unknown'"
      class="fixed bottom-4 right-4 z-40 max-w-[calc(100vw-2rem)] w-96 rounded-xl border bg-surface-white shadow-lg p-4 space-y-3"
      aria-label="Active WhatsApp call"
    >
      <div class="flex justify-between items-center gap-2">
        <strong class="text-sm">WhatsApp call</strong
        ><Badge :label="callState" />
      </div>
      <a
        v-if="incomingContact"
        :href="'#/messages?contact=' + encodeURIComponent(incomingContact)"
        class="text-sm underline"
        >Open conversation</a
      ><ErrorMessage :message="error" />
      <p v-if="callState === 'Recovered call'" class="text-xs text-ink-gray-5">
        A previous call is still active. End it before starting another;
        microphone audio cannot resume after a reload.
      </p>
      <Button
        v-if="callState === 'Outcome unknown'"
        label="Check call status"
        :disabled="busy"
        @click="pollEvents"
      />
      <div class="flex flex-wrap gap-2">
        <template v-if="callState === 'Incoming call'"
          ><Button
            label="Answer call"
            variant="solid"
            :disabled="busy"
            @click="acceptCall" /><Button
            label="Decline call"
            :disabled="busy"
            @click="rejectCall" /></template
        ><template v-else
          ><Button
            :label="muted ? 'Unmute' : 'Mute'"
            :icon-left="muted ? 'mic-off' : 'mic'"
            :disabled="busy || callState !== 'Connected'"
            @click="toggleMute" /><Button
            label="End call"
            icon-left="phone-off"
            :disabled="busy || !callId"
            @click="endCall" /></template
        ><Button
          v-if="recording"
          label="Stop recording"
          @click="stopRecording"
        />
      </div>
      <a href="#/calls" class="text-xs underline">Open call workspace</a>
    </section>
  </div>
</template>
