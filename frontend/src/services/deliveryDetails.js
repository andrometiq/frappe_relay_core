// Hub deliveries may contain only a queue ID and provider receipt, without a recipient.
export function deliveryDetails(row) {
  const timestamp = ['sent_at', 'updated_at', 'created_at', 'next_attempt'].find(key => row[key])
  return {
    recipient: row.recipient || '',
    message: row.message_id || row.result?.messages?.[0]?.id || '',
    time: timestamp ? row[timestamp] : '',
    timeLabel: { sent_at: 'Sent', updated_at: 'Updated', created_at: 'Created', next_attempt: 'Scheduled attempt' }[timestamp] || '',
  }
}
