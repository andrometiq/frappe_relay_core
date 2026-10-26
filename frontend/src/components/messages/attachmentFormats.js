import { channelFeature } from '../../services/enabledChannels.js';

// Extension to media type, as the backend guesses it from the file name.
const mediaTypes = {
  '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp', '.mp4': 'video/mp4',
  '.mp3': 'audio/mpeg', '.m4a': 'audio/mp4', '.ogg': 'audio/ogg', '.oga': 'audio/ogg', '.opus': 'audio/ogg', '.aac': 'audio/aac',
  '.pdf': 'application/pdf', '.txt': 'text/plain', '.doc': 'application/msword', '.xls': 'application/vnd.ms-excel',
  '.ppt': 'application/vnd.ms-powerpoint',
  '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
};

// Picker hints are advisory; the backend still validates the file against the channel formats.
function allowedExtensions(capabilities, provider, kind) {
  const types = channelFeature(capabilities, provider, 'media.' + kind);
  if (!types) return undefined;
  if (types.includes('*/*')) return [];
  return Object.keys(mediaTypes).filter(extension => types.includes(mediaTypes[extension]));
}
export function attachmentAccept(capabilities, provider, kind) {
  return (allowedExtensions(capabilities, provider, kind) || []).join(',');
}
export function attachmentFormatError(capabilities, provider, kind, filename) {
  const allowed = allowedExtensions(capabilities, provider, kind);
  if (!allowed) return 'This attachment type is unavailable for this channel.';
  if (!allowed.length) return '';
  const extension = '.' + filename.toLowerCase().split('.').at(-1);
  return allowed.includes(extension) ? '' : `Choose ${allowed.join(', ')} for this attachment.`;
}
