import { sha256Hex, randomUUID } from '../../services/crypto.js';
import { nextTick, watch } from "vue";
export function useWhatsAppDelivery({
  mediaType,
  mediaURL,
  mediaCaption,
  mediaFilename,
  deliveries,
  deliveryCursor,
  replyTo,
  messageText,
  notice,
  recordType,
  record,
  contact,
  text,
  body,
  api,
  run,
}) {
  async function enqueue(operation, arguments_, recipients = [contact.value]) {
    const intents = recipients.map((recipient) => ({
      operation,
      arguments: arguments_,
      contact: recipient,
      business_doctype: recordType.value,
      business_name: record.value,
    }));
    const hash = sha256Hex(JSON.stringify(intents));
    const storageKey = "relay-submission-" + hash;
    let batchKey = sessionStorage.getItem(storageKey);
    if (!batchKey) {
      batchKey = randomUUID();
      sessionStorage.setItem(storageKey, batchKey);
    }
    const result = await api("enqueue", {
      messages: intents.map((item, i) => ({
        ...item,
        key: batchKey + "-" + i,
      })),
    });
    sessionStorage.removeItem(storageKey);
    notice.value = (result.deliveries?.length || 1) + " queued for delivery";
  }

  async function loadDeliveries(next = false) {
    await run(async () => {
      if (next && deliveries.value.length)
        deliveryCursor.value = deliveries.value.at(-1).id;
      deliveries.value =
        (await api("deliveries", { after: deliveryCursor.value })).deliveries ||
        [];
    });
  }

  async function cancelDelivery(id) {
    await run(async () => {
      await api("deliveries", { cancel_id: id });
      deliveries.value =
        (await api("deliveries", { after: deliveryCursor.value })).deliveries ||
        [];
    });
  }

  async function sendMessage() {
    await run(async () => {
      await enqueue(
        mediaType.value === "text" ? "messages.send" : "messages.media",
        mediaType.value === "text"
          ? { body: messageText.value, reply_to: replyTo.value }
          : {
              media_type: mediaType.value,
              media_url: mediaURL.value,
              caption: ["image", "video", "document"].includes(mediaType.value)
                ? mediaCaption.value
                : "",
              filename:
                mediaType.value === "document" ? mediaFilename.value : "",
              reply_to: replyTo.value,
            },
      );
      messageText.value = "";
      replyTo.value = "";
      mediaURL.value = "";
      mediaCaption.value = "";
      mediaFilename.value = "";
    });
  }
  return { enqueue, loadDeliveries, cancelDelivery, sendMessage };
}
