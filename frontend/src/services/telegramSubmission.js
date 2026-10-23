import { stableSubmission } from './submission.js'

// Restored actions include zero-valued optional references. Keep their identity
// identical to the original composer payload, including its property order.
export function telegramSubmissionPayload(intent) {
  const payload = { chat_id: intent.chat_id, text: intent.text }
  if (intent.reply_to) payload.reply_to = intent.reply_to
  if (intent.message_thread_id) payload.message_thread_id = intent.message_thread_id
  return payload
}

export function telegramSubmission(intent, submit) {
  return stableSubmission('relay-telegram', telegramSubmissionPayload(intent), submit)
}
