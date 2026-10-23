import test from "node:test";
import assert from "node:assert/strict";
import { ref } from "vue";
import { useWhatsAppCalls } from "../src/composables/whatsapp/useWhatsAppCalls.js";

test("incoming calls, microphone mute, remote audio and termination retain one call identity", async () => {
  const track = {
    enabled: true,
    stopped: false,
    stop() {
      this.stopped = true;
    },
  };
  const stream = { getTracks: () => [track], getAudioTracks: () => [track] };
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: { mediaDevices: { getUserMedia: async () => stream } },
  });
  let peer;
  globalThis.RTCPeerConnection = class {
    constructor() {
      peer = this;
    }
    addTrack() {}
    async setRemoteDescription(value) {
      this.remoteDescription = value;
    }
    async createAnswer() {
      return { type: "answer", sdp: "v=0\r\nanswer" };
    }
    async setLocalDescription(value) {
      this.localDescription = value;
    }
    close() {
      this.closed = true;
    }
  };
  const calls = [],
    audio = { srcObject: null, play: async () => {} };
  const state = {
    incoming: ref([]),
    callPermission: ref(""),
    recording: ref(false),
    recordingURL: ref(""),
    tab: ref("Calls"),
    error: ref(""),
    capabilities: ref({ calls: true }),
    contact: ref("contact-a"),
    callId: ref(""),
    callState: ref("Idle"),
    remoteAudio: ref(audio),
    disposed: ref(false),
  };
  let events = [
    {
      payload: {
        entry: [
          {
            changes: [
              {
                value: {
                  calls: [
                    {
                      id: "call-one",
                      contact: "relay-a",
                      event: "connect",
                      timestamp: String(Math.floor(Date.now() / 1000)),
                      session: { sdp_type: "offer", sdp: "v=0\r\noffer" },
                    },
                  ],
                },
              },
            ],
          },
        ],
      },
    },
  ];
  state.execute = async (op, args) => {
    calls.push({ op, args });
    return op.startsWith("events.") ? { events, next: "1" } : {};
  };
  state.run = async (fn) => {
    state.error.value = "";
    try {
      await fn();
    } catch (e) {
      state.error.value = e.message;
    }
  };
  const control = useWhatsAppCalls(state);
  await control.pollEvents();
  assert.equal(state.callId.value, "call-one");
  assert.equal(control.incomingContact.value, "relay-a");
  await control.acceptCall();
  assert.equal(state.callState.value, "Connecting");
  assert.equal(calls.at(-1).args.id, "call-one");
  peer.connectionState = "connected";
  peer.onconnectionstatechange();
  assert.equal(state.callState.value, "Connected");
  assert.equal(calls.at(-1).op, "calls.connected");
  control.toggleMute();
  assert.equal(track.enabled, false);
  control.toggleMute();
  assert.equal(track.enabled, true);
  const remote = {};
  peer.ontrack({ streams: [remote] });
  assert.equal(audio.srcObject, remote);
  events = [
    {
      payload: {
        entry: [
          {
            changes: [
              {
                value: {
                  calls: [
                    {
                      id: "call-one",
                      event: "terminate",
                      timestamp: String(Math.floor(Date.now() / 1000)),
                    },
                  ],
                },
              },
            ],
          },
        ],
      },
    },
  ];
  await control.pollEvents();
  assert.equal(state.callId.value, "");
  assert.equal(state.callState.value, "Ended");
  assert.equal(track.stopped, true);
  assert.equal(peer.closed, true);
});

test("an unconfirmed connect prevents another call in the active workspace", async () => {
  const track = { enabled: true, stop() {} };
  const stream = { getTracks: () => [track], getAudioTracks: () => [track] };
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: { mediaDevices: { getUserMedia: async () => stream } },
  });
  globalThis.RTCPeerConnection = class {
    constructor() {
      this.iceGatheringState = "complete";
    }
    addTrack() {}
    async createOffer() {
      return { type: "offer", sdp: "v=0" };
    }
    async setLocalDescription(value) {
      this.localDescription = value;
    }
    close() {}
  };
  let submissions = 0;
  const state = {
    incoming: ref([]),
    callPermission: ref(""),
    recording: ref(false),
    recordingURL: ref(""),
    tab: ref("Calls"),
    error: ref(""),
    capabilities: ref({ calls: true }),
    contact: ref("contact-a"),
    callId: ref(""),
    callState: ref("Idle"),
    remoteAudio: ref(null),
    disposed: ref(false),
  };
  state.execute = async (op) => {
    if (op === "calls.pending") return {};
    if (op === "calls.permission.get")
      return {
        actions: [{ action_name: "start_call", can_perform_action: true }],
      };
    submissions++;
    throw Error("Transport lost");
  };
  state.run = async (fn) => {
    state.error.value = "";
    try {
      await fn();
    } catch (e) {
      state.error.value = e.message;
    }
  };
  const control = useWhatsAppCalls(state);
  await control.startCall();
  assert.equal(state.callState.value, "Outcome unknown");
  await control.startCall();
  assert.equal(submissions, 1);
});

test("pending call recovery survives a new workspace without reconnecting media", async () => {
  const state = {
    incoming: ref([]),
    callPermission: ref(""),
    recording: ref(false),
    recordingURL: ref(""),
    tab: ref("Calls"),
    error: ref(""),
    capabilities: ref({ calls: true }),
    contact: ref("contact-a"),
    callId: ref(""),
    callState: ref("Idle"),
    remoteAudio: ref(null),
    disposed: ref(false),
  };
  const operations = [];
  state.execute = async (op, args) => {
    operations.push({ op, args });
    if (op === "calls.pending")
      return {
        calls: [{ id: "recovered-one" }],
        state: "Connecting",
        contact: "relay-a",
      };
    return {};
  };
  state.run = async (fn) => {
    try {
      await fn();
    } catch (e) {
      state.error.value = e.message;
    }
  };
  const control = useWhatsAppCalls(state);
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(state.callId.value, "recovered-one");
  assert.equal(state.callState.value, "Recovered call");
  assert.equal(control.incomingContact.value, "relay-a");
  await control.endCall();
  assert.equal(operations.at(-1).args.action, "terminate");
  assert.equal(operations.at(-1).args.id, "recovered-one");
  assert.equal(state.callState.value, "Ended");
});
