// Match the formats currently accepted by the Core and Hub upload adapters.
// Picker hints are advisory; provider adapters still validate the actual bytes.
const formats = {
  Telegram: {
    photo: '.jpg,.jpeg,.png,.webp', video: '.mp4', audio: '.mp3,.m4a',
    voice: '.ogg,.oga,.opus', document: '',
  },
  WhatsApp: {
    photo: '.jpg,.jpeg,.png', video: '.mp4', audio: '.mp3,.m4a,.ogg,.aac',
    document: '.pdf,.txt,.doc,.docx,.xls,.xlsx,.ppt,.pptx',
  },
};
export function attachmentAccept(provider, kind) {
  return formats[provider]?.[kind] ?? '';
}
export function attachmentFormatError(provider, kind, filename) {
  const allowed = formats[provider]?.[kind];
  if (allowed === undefined) return 'This attachment type is unavailable for this channel.';
  if (!allowed) return '';
  const extension = '.' + filename.toLowerCase().split('.').at(-1);
  return allowed.split(',').includes(extension) ? '' : `Choose ${allowed.replaceAll(',', ', ')} for this attachment.`;
}
