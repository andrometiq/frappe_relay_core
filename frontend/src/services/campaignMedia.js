import { HEADER_MAX_BYTES } from './templateMedia.js';

export function attachmentMapping(mapping, attachment) {
  const fields = { ...mapping.fields }, fixed = { ...mapping.fixed };
  delete fields.header_media;
  delete fixed.header_media;
  return { ...mapping, fields, fixed, header_attachment: attachment };
}

export function attachmentSelectionError(files, mode) {
  if (!files.length || (mode === 'static' && files.length !== 1)) return 'Choose one file for everyone.';
  if (files.some(file => /\.zip$/i.test(file.name))) return 'Select individual files; ZIP archives are not supported.';
  if (files.some(file => !file.size || file.size > HEADER_MAX_BYTES)) return 'Each file must contain 1 byte to 4 MiB.';
  return '';
}
