import test from 'node:test';
import assert from 'node:assert/strict';
import { campaignError } from '../src/services/campaignErrors.js';

test('raw responses, tracebacks and private details never reach campaign errors', () => {
  for (const raw of ['Traceback: secret=/private/files/user.csv', '<html>500 Internal Server Error</html>', '{"exc":"secret"}', 'Unrecognised SQL exception']) {
    const text = campaignError(Error(raw));
    assert.equal(text, 'The action could not finish. Check the campaign details and try again.');
  }
  assert.equal(campaignError({ status: 403, message: 'secret' }), 'Only a Relay Communication Manager or System Manager can manage campaigns.');
});

test('known ZIP and validation errors provide useful fixed copy without echoing payloads', () => {
  assert.match(campaignError(Error('ZIP must contain exactly one .xlsx, .csv or .tsv sheet')), /exactly one/);
  assert.match(campaignError(Error('ZIP contains an unsafe path or symbolic link /private/secret')), /unsafe path/);
  assert.ok(!campaignError(Error('ZIP contains an unsafe path /private/secret')).includes('secret'));
  assert.match(campaignError(Error('Validate recipients before sending')), /At least one row/);
  assert.match(campaignError(Error('Hub returned private payload xyz')), /connection is unavailable/);
});

test('header size reasons keep the real limit, other header file reasons get fixed copy', () => {
  assert.equal(campaignError(Error('Header attachment must be at most 10 MB')), 'Header attachment must be at most 10 MB.');
  assert.equal(campaignError(Error('Header attachment is empty')), 'Header attachment is empty.');
  assert.match(campaignError(Error('Header attachment must be at most 10 MB /private/files/x')), /could not finish/);
  assert.match(campaignError(Error('Wrong file type for image header')), /correct header file type/);
});
