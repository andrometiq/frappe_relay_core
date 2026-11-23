// The site's WhatsApp numbers from api.capabilities whatsapp_numbers. Number tags, filters and pickers
// show only when a site has two or more numbers; a one-number site keeps the plain layout.

export function whatsappNumbers(capabilities) {
  return capabilities?.whatsapp_numbers || []
}

export function hasManyNumbers(capabilities) {
  return whatsappNumbers(capabilities).length > 1
}

// The short name of a number for tags, or '' when the channel is not one of the site's numbers.
export function numberName(capabilities, channel) {
  return whatsappNumbers(capabilities).find(row => row.name === channel)?.label || ''
}

// Thread tags by message name: a message names its number ("to Sales line", "via Sales line") when the
// number differs from the previous message in the same direction. A copy sent to several channels has no tag.
export function messageNumberTags(rows, capabilities) {
  const tags = {}, last = {}
  if (!hasManyNumbers(capabilities)) return tags
  for (const message of rows) {
    const name = message.sends ? '' : numberName(capabilities, message.channel)
    if (name && last[message.direction] !== message.channel) tags[message.name] = (message.direction === 'Outgoing' ? 'via ' : 'to ') + name
    last[message.direction] = message.channel
  }
  return tags
}

