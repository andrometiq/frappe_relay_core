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
  assert.match(campaignError(Error('Hub returned private payload xyz')), /could not finish/);
});

test('header size reasons keep the real limit, other header file reasons get fixed copy', () => {
  assert.equal(campaignError(Error('Header attachment must be at most 10 MB')), 'Header attachment must be at most 10 MB.');
  assert.equal(campaignError(Error('Header attachment is empty')), 'Header attachment is empty.');
  assert.match(campaignError(Error('Header attachment must be at most 10 MB /private/files/x')), /could not finish/);
  assert.match(campaignError(Error('Wrong file type for image header')), /correct header file type/);
});

test('a Hub rejection keeps its real reason as one short clean line', () => {
  assert.equal(campaignError(Error('Hub rejected this operation: WhatsApp rejected this request (code 132001): Template name does not exist in the translation')),
    'WhatsApp did not accept this: WhatsApp rejected this request (code 132001): Template name does not exist in the translation.');
  assert.equal(campaignError(Error('Hub rejected this operation: Media upload failed · token [hidden]')), 'WhatsApp did not accept this: Media upload failed · token [hidden].');
  const long = campaignError(Error('Hub rejected this operation: ' + 'word '.repeat(100)));
  assert.ok(long.length < 260 && long.endsWith('…'));
});

test('a Hub rejection that carries a trace, payload or path shows fixed copy', () => {
  for (const detail of ['Traceback (most recent call last)', '{"error":"secret"}', 'see /private/files/a.png', '<html>502</html>']) {
    const text = campaignError(Error('Hub rejected this operation: ' + detail));
    assert.equal(text, 'WhatsApp Hub did not accept this action. Check the WhatsApp account setup and template, then try again.');
  }
});

test('only real connection failures show the connection line', () => {
  const connection = 'The WhatsApp connection is unavailable. Check the channel settings and try again.';
  for (const raw of ['Hub returned an invalid response or is unavailable', 'Hub HTTP request rejected (503)', 'The read operation timed out',
    'Configure relay_hub_url and relay_hub_token for this Frappe site']) {
    assert.equal(campaignError(Error(raw)), connection);
  }
  for (const raw of ['Hub could not complete this operation. Check account configuration.', 'Hub HTTP request rejected (400)',
    'Choose the WhatsApp number this campaign sends from', 'Configure an enabled WhatsApp channel', 'Hub returned no media id',
    'Hub connection is not authorized. Update the saved Hub API credential in Relay Settings.', 'The header file could not be read. Upload it again']) {
    assert.notEqual(campaignError(Error(raw)), connection, raw);
    assert.doesNotMatch(campaignError(Error(raw)), /could not finish/, raw);
  }
});
