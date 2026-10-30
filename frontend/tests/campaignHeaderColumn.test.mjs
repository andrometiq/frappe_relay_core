import test from 'node:test';
import assert from 'node:assert/strict';
import { headerFilesNotice, missingMapping } from '../src/services/campaignProgress.js';

const fields = [{ key: 'header_media', label: 'Header image attachment', media: 'image' }];

test('a ZIP still needs the header column that names each row file', () => {
  const attachment = { mode: 'named', files: [{ filename: 'offer.png', file_url: '/private/files/offer.png' }] };
  assert.deepEqual(missingMapping(fields, { phone: 'Mobile', fields: {}, header_attachment: attachment }), ['Header image attachment']);
  assert.deepEqual(missingMapping(fields, { phone: 'Mobile', fields: { header_media: 'Header image' }, header_attachment: attachment }), []);
});

test('the notice counts ZIP files and rejected files, or asks for links without a ZIP', () => {
  assert.equal(headerFilesNotice(null, 'image'), 'No ZIP uploaded, so each row needs an https link to its image.');
  assert.equal(headerFilesNotice({ files: [{}], rejected: [] }, 'video'), '1 video file in the ZIP. Each row names one of them or gives an https link.');
  assert.equal(headerFilesNotice({ files: [{}, {}, {}], rejected: [{}] }, 'image'), '3 image files in the ZIP, 1 rejected. Each row names one of them or gives an https link.');
  assert.match(headerFilesNotice({ files: [], rejected: [{}] }, 'document'), /0 document files in the ZIP, 1 rejected/);
});
