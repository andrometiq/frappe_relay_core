import test from 'node:test';
import assert from 'node:assert/strict';
import { attachmentMapping, attachmentSelectionError } from '../src/services/campaignMedia.js';
import { missingMapping } from '../src/services/campaignProgress.js';

test('switching to attachments removes both legacy URL sources without losing message values', () => {
  const mapping = { phone: 'Mobile', fields: { header_media: 'URL', 'body:1': 'Name' }, fixed: { header_media: 'https://example.com/a.jpg' } };
  const attachment = { mode: 'dynamic', files: [{ filename: '919876543210.jpg', file_url: '/private/files/a.jpg' }] };
  assert.deepEqual(attachmentMapping(mapping, attachment), {
    phone: 'Mobile', fields: { 'body:1': 'Name' }, fixed: {}, header_attachment: attachment,
  });
  assert.equal(mapping.fields.header_media, 'URL');
});

test('media mapping needs an uploaded file, and clearing files blocks import', () => {
  const fields = [{ key: 'header_media', label: 'Header attachment' }];
  assert.deepEqual(missingMapping(fields, { phone: 'Mobile', header_attachment: { mode: 'static', files: [] } }), ['Header attachment']);
  assert.deepEqual(missingMapping(fields, { phone: 'Mobile', header_attachment: { mode: 'dynamic', files: [{ file_url: '/private/files/a.jpg' }] } }), []);
});

test('multi-select supports bounded individual files and rejects ZIPs including traversal names', () => {
  const image = { name: '919876543210.jpg', size: 1024 };
  assert.equal(attachmentSelectionError([image], 'static'), '');
  assert.equal(attachmentSelectionError([image, image], 'dynamic'), '');
  assert.match(attachmentSelectionError([image, image], 'static'), /one file/);
  for (const name of ['contacts.zip', '../contacts.zip', 'CONTACTS.ZIP'])
    assert.match(attachmentSelectionError([{ name, size: 1024 }], 'dynamic'), /ZIP/);
  for (const size of [0, 4 * 1024 * 1024 + 1])
    assert.match(attachmentSelectionError([{ ...image, size }], 'static'), /4 MiB/);
});
