import test from 'node:test';
import assert from 'node:assert/strict';
import {botBadge, botRows, clearSecrets, connectionBadge, deliveryRows, mailboxBadge, mailboxChanges, mailboxConnect, mailboxDraft, mailboxRows, needsReconnect, photoProblem, profileChanges, profileDraft, removalText, switchValue, webhookText, withSecrets} from '../src/services/channelSetup.js';

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

test('a bot badge shows off first, then the webhook state', () => {
  const bot = (health, enabled = true) => ({ enabled, health })
  assert.deepEqual(botBadge(bot({ webhook_status: 'registered' })), { label: 'Connected', theme: 'green' })
  assert.deepEqual(botBadge(bot({ webhook_status: 'not_registered' })), { label: 'Not receiving', theme: 'orange' })
  assert.deepEqual(botBadge(bot({ webhook_status: 'registered' }, false)), { label: 'Off', theme: 'gray' })
  assert.deepEqual(botBadge(bot({})), { label: 'Not checked yet', theme: 'gray' })
})

test('bot rows explain a missing HTTPS Hub and never show the token', () => {
  const rows = botRows({ username: 'acme_textiles_bot', webhook_status: 'not_registered', webhook_missing: 'The Hub has no public HTTPS URL.', token_saved: true })
  assert.deepEqual(rows.map(row => row.text), ['@acme_textiles_bot', 'The Hub has no public HTTPS URL.', 'Kept by Relay Hub'])
  assert.match(botRows({ webhook_status: 'not_registered' })[1].text, /repair/)
  assert.match(botRows({})[2].text, /Missing/)
})

test('mailbox badge and rows read the sign-in and sync state', () => {
  assert.deepEqual(mailboxBadge({ enabled: true, health: { connection_status: 'failed' } }), { label: 'Check failed', theme: 'red' })
  assert.deepEqual(mailboxBadge({ enabled: false, health: { connection_status: 'connected' } }), { label: 'Off', theme: 'gray' })
  const rows = mailboxRows({ smtp_status: 'connected', imap_status: 'not_configured', rejected: 2, sync: [{ last_sync: '2026-11-01 10:00' }] }, value => 'at ' + value)
  assert.deepEqual(rows.map(row => row.text), ['Signed in', 'Not set up', 'at 2026-11-01 10:00', '2'])
  assert.equal(mailboxRows({ sync: [{ error: 'Mailbox synchronization failed' }] })[2].text, 'Mailbox synchronization failed')
})

test('a mailbox change sends only changed fields and typed passwords', () => {
  const health = { server: { host: 'smtp.example.com', port: 587, imap_host: 'imap.example.com' } }
  const draft = mailboxDraft(health)
  assert.equal(draft.port, '587')
  assert.equal(draft.password, '')
  assert.deepEqual(mailboxChanges(health, draft), {})
  assert.deepEqual(mailboxChanges(health, { ...draft, imap_folder: ' Support ', host: 'smtp.example.com', password: 'local-only' }), { imap_folder: 'Support', password: 'local-only' })
})

test('a new mailbox leaves blank fields out and the form forgets its secrets', () => {
  assert.deepEqual(mailboxConnect({ from: ' sales@example.com ', host: 'smtp.example.com', port: '587', imap_host: '', password: ' pass word ' }),
    { from: 'sales@example.com', host: 'smtp.example.com', port: '587', password: ' pass word ' })
  const form = { from: 'sales@example.com', password: 'local-only', imap_password: 'local-only', bot_token: '111111:local' }
  clearSecrets(form)
  assert.deepEqual(form, { from: 'sales@example.com', password: '', imap_password: '', bot_token: '' })
})

test('tokens and passwords go in their own secrets field, apart from the other values', () => {
  assert.deepEqual(withSecrets('values', { label: 'Acme Textiles', bot_token: '111111:acme_bot_token_local_only_aaaa' }),
    { values: { label: 'Acme Textiles' }, secrets: { bot_token: '111111:acme_bot_token_local_only_aaaa' } });
  assert.deepEqual(withSecrets('settings', { host: 'smtp.example.com', password: 'smtp-local-only', imap_password: 'imap-local-only' }),
    { settings: { host: 'smtp.example.com' }, secrets: { password: 'smtp-local-only', imap_password: 'imap-local-only' } });
  assert.deepEqual(withSecrets('settings', { enabled: 0 }), { settings: { enabled: 0 }, secrets: {} });
});
