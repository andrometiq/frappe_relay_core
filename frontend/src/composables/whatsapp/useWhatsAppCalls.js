import { nextTick, watch, ref } from "vue";
import { randomUUID } from "../../services/crypto.js";
export function useWhatsAppCalls({
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
}) {
  const openedAt = Date.now() / 1000;
  const muted = ref(false),
    incomingContact = ref(""),
    recordingBlob = ref(null),
    recordingCallId = ref(""),
    recordingSaved = ref("");
  function toggleMute() {
    if (!stream) return;
    muted.value = !muted.value;
    stream.getAudioTracks().forEach((track) => (track.enabled = !muted.value));
  }
  let peer,
    stream,
    pendingOffer,
    recorder,
    recordingContext,
    recordingDestination,
    recordingChunks = [],
    eventCursor = "",
    polling = false;
  async function recoverCall() {
    const result = await execute("calls.pending", {});
    if (result.contact) incomingContact.value = result.contact;
    if (result.outcome_unknown) {
      callState.value = "Outcome unknown";
      return;
    }
    const id = result.calls?.[0]?.id;
    if (id && !callId.value) {
      callId.value = id;
      callState.value = "Recovered call";
    }
    if (!id && callState.value === "Outcome unknown") callState.value = "Idle";
  }
  watch(
    () => capabilities.value?.calls,
    (enabled) => {
      if (enabled)
        recoverCall().catch(() => {
          error.value =
            "Could not check pending calls. Refresh before calling.";
          callState.value = "Outcome unknown";
        });
    },
    { immediate: true },
  );
  function makePeer() {
    peer = new RTCPeerConnection();
    peer.onconnectionstatechange = () => {
      if (peer?.connectionState === "connected") {
        callState.value = "Connected";
        if (callId.value)
          execute("calls.connected", { id: callId.value }).catch(() => {});
      } else if (peer?.connectionState === "failed")
        callState.value = "Connection failed";
      else if (peer?.connectionState === "disconnected")
        callState.value = "Disconnected";
    };
    peer.ontrack = (e) => {
      if (remoteAudio.value) {
        remoteAudio.value.srcObject =
          e.streams[0] || new MediaStream([e.track]);
        remoteAudio.value.play().catch(() => {});
      }
    };
    stream.getTracks().forEach((t) => peer.addTrack(t, stream));
  }

  async function pollEvents() {
    if (
      disposed.value ||
      polling ||
      !capabilities.value?.calls ||
      (tab.value !== "Calls" && !callId.value)
    )
      return;
    polling = true;
    try {
      const r = await execute(
        eventCursor ? "events.list" : "events.latest",
        eventCursor ? { after: eventCursor } : {},
      );
      for (const event of r.events || []) {
        for (const entry of event.payload?.entry || []) {
          for (const change of entry.changes || []) {
            for (const call of change.value?.calls || []) {
              if (call.timestamp && Number(call.timestamp) < openedAt - 30)
                continue;
              if (call.event === "terminate" && call.id === callId.value) {
                releaseMedia();
                callId.value = "";
                callState.value = "Ended";
              } else if (call.session?.sdp_type === "offer" && !callId.value) {
                incomingContact.value = call.contact || "";
                pendingOffer = call.session.sdp;
                callId.value = call.id;
                callState.value = "Incoming call";
              } else if (
                call.id === callId.value &&
                call.session?.sdp_type === "answer" &&
                peer?.signalingState === "have-local-offer"
              ) {
                await peer.setRemoteDescription({
                  type: "answer",
                  sdp: call.session.sdp,
                });
                callState.value = "Connecting";
              }
            }
          }
        }
      }
      eventCursor = r.next || eventCursor;
      if (callState.value === "Outcome unknown") await recoverCall();
    } catch (e) {
      error.value =
        "Call updates unavailable; reconnect before starting another call";
    } finally {
      polling = false;
    }
  }

  async function acceptCall() {
    await run(async () => {
      if (!pendingOffer) throw new Error("No incoming offer");
      if (!navigator.mediaDevices?.getUserMedia)
        throw new Error(
          "Calling requires HTTPS or localhost and microphone access",
        );
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      makePeer();
      await peer.setRemoteDescription({ type: "offer", sdp: pendingOffer });
      await peer.setLocalDescription(await peer.createAnswer());
      await execute("calls.action", {
        action: "accept",
        id: callId.value,
        sdp_type: "answer",
        sdp: peer.localDescription.sdp,
      });
      callState.value = "Connecting";
    });
    if (error.value) releaseMedia();
  }

  async function rejectCall() {
    await run(async () => {
      await execute("calls.action", { action: "reject", id: callId.value });
      releaseMedia();
      callId.value = "";
      callState.value = "Rejected";
    });
  }

  function releaseMedia() {
    stopRecording();
    peer?.close();
    stream?.getTracks().forEach((t) => t.stop());
    peer = null;
    stream = null;
    pendingOffer = null;
    muted.value = false;
  }

  async function startCall() {
    await run(async () => {
      if (callId.value || callState.value === "Outcome unknown")
        throw new Error("Resolve the current call before starting another");
      if (!contact.value) throw new Error("Select a contact");
      const permission = await execute("calls.permission.get");
      callPermission.value = permission.permission?.status || "Unknown";
      if (
        !permission.actions?.some(
          (a) => a.action_name === "start_call" && a.can_perform_action,
        )
      )
        throw new Error("Call permission is not available for this contact");
      if (!navigator.mediaDevices?.getUserMedia)
        throw new Error(
          "Calling requires HTTPS or localhost and microphone access",
        );
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      makePeer();
      await peer.setLocalDescription(await peer.createOffer());
      await new Promise((resolve) => {
        if (peer.iceGatheringState === "complete") return resolve();
        const timer = setTimeout(resolve, 3000);
        peer.addEventListener("icegatheringstatechange", () => {
          if (peer?.iceGatheringState === "complete") {
            clearTimeout(timer);
            resolve();
          }
        });
      });
      let result;
      try {
        result = await execute("calls.action", {
          action: "connect",
          request_key: randomUUID(),
          sdp_type: "offer",
          sdp: peer.localDescription.sdp,
        });
      } catch (e) {
        callState.value = "Outcome unknown";
        throw new Error(
          "Call submission could not be confirmed. Check call history before starting another call.",
        );
      }
      if (result.rejected) {
        callState.value = "Rejected";
        throw new Error(
          "Call was rejected before connection. Check calling permission before trying again.",
        );
      }
      callId.value = result.calls?.[0]?.id || result.id || "";
      if (!callId.value) {
        callState.value = "Outcome unknown";
        throw new Error("Call outcome is unknown; reconcile before retrying");
      }
      callState.value = "Awaiting answer";
      if (result.session?.sdp) {
        await peer.setRemoteDescription({
          type: "answer",
          sdp: result.session.sdp,
        });
        callState.value = "Connecting";
      }
    });
    if (error.value) releaseMedia();
  }

  async function endCall() {
    await run(async () => {
      await execute("calls.action", { action: "terminate", id: callId.value });
      releaseMedia();
      callState.value = "Ended";
      callId.value = "";
    });
  }

  function stopRecording() {
    if (recorder?.state === "recording") recorder.stop();
  }

  async function startRecording() {
    await run(async () => {
      if (
        callState.value !== "Connected" ||
        !stream ||
        !remoteAudio.value?.srcObject
      )
        throw new Error("Recording needs a connected call");
      if (!window.MediaRecorder || !window.AudioContext)
        throw new Error("Recording is unavailable in this browser");
      const limits = await execute("calls.recording_limits");
      const maximum = Math.min(32 * 1024 * 1024, Number(limits.max_bytes));
      if (!Number.isFinite(maximum) || maximum < 16)
        throw new Error("Recording upload limit is unavailable");
      if (recordingURL.value) URL.revokeObjectURL(recordingURL.value);
      recordingURL.value = "";
      recordingChunks = [];
      recordingBlob.value = null;
      recordingSaved.value = "";
      recordingCallId.value = callId.value;
      recordingContext = new AudioContext();
      recordingDestination = recordingContext.createMediaStreamDestination();
      recordingContext
        .createMediaStreamSource(stream)
        .connect(recordingDestination);
      recordingContext
        .createMediaStreamSource(remoteAudio.value.srcObject)
        .connect(recordingDestination);
      recorder = new MediaRecorder(recordingDestination.stream);
      let size = 0;
      recorder.ondataavailable = (e) => {
        if (size + e.data.size <= maximum) {
          size += e.data.size;
          recordingChunks.push(e.data);
        }
        if (
          size >= Math.max(16, maximum - 65536) ||
          size + e.data.size > maximum
        )
          stopRecording();
      };
      recorder.onstop = () => {
        if (!disposed.value) {
          recordingBlob.value = new Blob(recordingChunks, {
            type: recorder.mimeType,
          });
          recordingURL.value = URL.createObjectURL(recordingBlob.value);
        }
        recordingChunks = [];
        recordingContext.close();
        recordingDestination.stream.getTracks().forEach((t) => t.stop());
        recording.value = false;
      };
      recorder.start(1000);
      recording.value = true;
    });
  }
  return {
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
  };
}
