import { sizeError } from '../components/messages/attachmentFormats.js';

export function attachmentMapping(mapping, attachment) {
  const fields = { ...mapping.fields }, fixed = { ...mapping.fixed };
  delete fields.header_media;
  delete fixed.header_media;
  return { ...mapping, fields, fixed, header_attachment: attachment };
}

export function attachmentSelectionError(files, mode, limit) {
  if (!files.length || (mode === 'static' && files.length !== 1)) return 'Choose one file for everyone.';
  if (files.some(file => /\.zip$/i.test(file.name))) return 'Select individual files; ZIP archives are not supported.';
  return files.map(file => sizeError(file.size, limit, file.name)).find(Boolean) || '';
}
