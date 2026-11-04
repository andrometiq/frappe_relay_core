import test from 'node:test';
import assert from 'node:assert/strict';
import {connectionBadge, deliveryRows, needsReconnect, photoProblem, profileChanges, profileDraft, removalText, switchValue, webhookText} from '../src/services/channelSetup.js';

const account = (health = {}, enabled = true) => ({ enabled, health: { connection_status: 'connected', partner_status: 'active', ...health } });

test('the badge shows Meta removal first, then off, then the last check', () => {
  assert.deepEqual(connectionBadge(account()), { label: 'Connected', theme: 'green' });
  assert.deepEqual(connectionBadge(account({ partner_status: 'removed' })), { label: 'Removed by Meta', theme: 'red' });
  assert.deepEqual(connectionBadge(account({}, false)), { label: 'Off', theme: 'gray' });
  assert.deepEqual(connectionBadge(account({ connection_status: 'reconnect_required' })), { label: 'Connect again', theme: 'red' });
  assert.deepEqual(connectionBadge(account({ connection_status: 'surprise' })), { label: 'Not checked yet', theme: 'gray' });
  assert.deepEqual(connectionBadge(undefined), { label: 'Not checked yet', theme: 'gray' });
});

test('only a refused or removed number must be connected again', () => {
  assert.equal(needsReconnect(account()), false);
  assert.equal(needsReconnect(account({ connection_status: 'failed' })), false);
  assert.equal(needsReconnect(account({ connection_status: 'reconnect_required' })), true);
  assert.equal(needsReconnect(account({ partner_status: 'removed' })), true);
});

test('webhook and delivery rows read as plain text', () => {
  assert.match(webhookText({ webhook_subscribed: false }), /repair/);
  assert.equal(webhookText({}), 'Not checked yet.');
  const rows = deliveryRows({ delivery: { webhook_received_at: '2026-11-01 10:00', callback_pending: 3, callback_failed: 1 } }, value => 'at ' + value);
  assert.deepEqual(rows.map(row => row.text), ['at 2026-11-01 10:00', 'None yet', '3 (1 retrying)']);
  assert.equal(deliveryRows({}).at(-1).text, 'None');
});

test('switches read the Relay Channel for on/off and the Hub for the rest', () => {
  const row = account({ settings: { templates: true, sync_metadata: false } }, false);
  assert.equal(switchValue(row, 'enabled'), false);
  assert.equal(switchValue(row, 'templates'), true);
  assert.equal(switchValue(row, 'sync_metadata'), false);
});

test('only changed profile fields are sent, websites one per line', () => {
  const original = { about: 'Fabrics for every season', websites: ['https://example.com'], vertical: 'APPAREL' };
  const draft = profileDraft(original);
  assert.deepEqual(profileChanges(original, draft), {});
  draft.about = ' Fabrics for every season ';
  draft.email = 'hello@example.com';
  draft.websites = 'https://example.com\n\n https://shop.example.com ';
  assert.deepEqual(profileChanges(original, draft), { email: 'hello@example.com', websites: ['https://example.com', 'https://shop.example.com'] });
});

test('a profile photo is a JPEG or PNG up to 5 MB', () => {
  assert.equal(photoProblem({ type: 'image/png', size: 1000 }), '');
  assert.match(photoProblem({ type: 'image/gif', size: 1000 }), /JPEG or PNG/);
  assert.match(photoProblem({ type: 'image/jpeg', size: 6 * 1024 * 1024 }), /5 MB/);
  assert.equal(photoProblem(null), '');
});

test('removal text says whether the number can move', () => {
  assert.match(removalText({ removed: true, deregistered: true }), /can now move/);
  assert.match(removalText({ removed: true, deregistered: false }), /WhatsApp Manager/);
  assert.equal(removalText({}), '');
});
