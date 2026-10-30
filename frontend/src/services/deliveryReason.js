import { deliveryError } from './serverError.js'

// Plain reasons for the WhatsApp delivery error codes staff meet most.
const REASONS = {
  131026: 'WhatsApp could not deliver this message. The number may not use WhatsApp, or the app needs an update.',
  131047: 'The 24-hour reply window is closed. Send a template message instead.',
  131049: 'WhatsApp held this message back to limit marketing messages. Try again later.',
  131050: 'The customer stopped marketing messages from this business.',
  131051: 'WhatsApp does not support this message type.',
  131053: 'WhatsApp could not upload the attachment. Check the file and try again.',
}

// A short reason for a failed outgoing message, from the stored provider error when there is one.
export function deliveryReason(error) {
  const code = Number(String(error || '').match(/\(code (\d+)\)/)?.[1])
  return REASONS[code] || deliveryError(error) || 'This message was not delivered.'
}
