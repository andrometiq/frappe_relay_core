// Built UI checks with intercepted HTTP only. No server or provider is started.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { chromium } from '../../../.runtime/browser/node_modules/playwright/index.mjs';
const root = new URL('../../../', import.meta.url);
const html = await readFile(new URL('relay_core/public/relay/site.html', root), 'utf8');
const capabilities = { manage: true, enabled_channels: ['WhatsApp'], channels: { WhatsApp: { templates: true, bulk_campaigns: true, media: { photo: ['image/png'] } } } };
const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || '/usr/bin/google-chrome', headless: true, args: ['--no-sandbox'] });
const outcomes = [];
try {
  for (const width of [1440, 375]) for (const theme of ['light', 'dark']) {
    const context = await browser.newContext({ viewport: { width, height: 900 }, colorScheme: theme });
    const page = await context.newPage(), errors = [], writes = [];
    let socket, reads = 0;
    await page.routeWebSocket(/\/socket.io\//, ws => {
      socket = ws;
      ws.send('0' + JSON.stringify({ sid: 'local-campaign', upgrades: [], pingInterval: 25000, pingTimeout: 20000 }));
      ws.onMessage(message => {
        if (String(message).startsWith('40/relay-flows-test.localhost')) ws.send('40/relay-flows-test.localhost,' + JSON.stringify({ sid: 'local-campaign' }));
        if (message === '2') ws.send('3');
      });
    });
    const progress = () => socket.send('42/relay-flows-test.localhost,' + JSON.stringify(['relay_campaign_progress', { name: campaign.name, status: campaign.status, counts: campaign.counts }]));
    page.on('pageerror', error => errors.push(error.message));
    let campaign = { name: 'Local ZIP', title: 'Local ZIP', status: 'Draft', source_file: '/private/files/people.csv',
      template_name: 'local_offer', language: 'en', time_zone: 'Asia/Kolkata', reply_window_hours: 72,
      fields: [{ key: 'body:1', label: 'Body value 1', component: 'body' }], validated: false,
      counts: { total: 0, skipped: 0 }, recipients: [], error_rows: [], issues: [], phases: [] };
    await page.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.pathname === '/relay') {
        return route.fulfill({ contentType: 'text/html', body: html.replace('id="app"', `id="app" data-site="relay-flows-test.localhost" data-user="local-manager@example.invalid" data-capabilities='${JSON.stringify(capabilities)}'`) });
      }
      if (url.pathname.startsWith('/assets/relay_core/relay/')) {
        const file = url.pathname.replace('/assets/relay_core/relay/', '');
        assert.ok(!file.includes('..'));
        return route.fulfill({ body: await readFile(new URL('relay_core/public/relay/' + file, root)), contentType: file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'application/octet-stream' });
      }
      let result = {};
      const method = url.pathname.split('/api/method/')[1];
      if (route.request().method() === 'POST') writes.push(method);
      if (method === 'relay_core.bulk_campaigns.read') { reads++; result = campaign; }
      else if (method === 'relay_core.campaigns.directory') result = { items: [campaign] };
      else if (method === 'upload_file') result = { file_url: '/private/files/people.zip' };
      else if (method === 'relay_core.bulk_campaigns.inspect') result = { columns: ['Mobile', 'Name'], fields: campaign.fields, mapping: { phone: 'Mobile', fields: { 'body:1': 'Name' } } };
      else if (method === 'relay_core.bulk_campaigns.import_rows') {
        campaign = { ...campaign, validated: true, counts: { total: 2, skipped: 2 }, error_rows: [
          { sheet_row: 4, destination: 'bad', reason: 'Invalid phone number' },
          { sheet_row: 5, destination: '12025550102', reason: 'Missing Body value 1' }],
          phases: [{ phase: 'Validated', at: '2026-10-30 12:00:00', user: 'local-manager@example.invalid' }] };
        result = { ...campaign, status: 'Importing', validated: false };
        setTimeout(progress, 100);
      } else if (method === 'relay_core.bulk_campaigns.control') {
        campaign = { ...campaign, status: 'Running', counts: { ...campaign.counts, queued: 2, sent: 0, failed: 0 } };
        result = campaign;
      } else if (method === 'relay_core.bulk_campaigns.sample_sheet' || method === 'relay_core.bulk_campaigns.error_report') {
        return route.fulfill({ contentType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', body: Buffer.from('local download fixture') });
      } else if (method?.includes('notifications') || method?.includes('directory')) result = { items: [] };
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ message: result }) });
    });
    await page.goto('http://relay-flows-test.localhost:8001/relay#/whatsapp?tab=campaigns&campaign=Local%20ZIP');
    const send = page.getByRole('button', { name: /^Start sending to/ });
    await page.getByText('Live', { exact: true }).waitFor({ state: 'attached' });
    await send.waitFor(); assert.equal(await send.isDisabled(), true);
    await page.getByLabel('Recipients sheet').setInputFiles({ name: 'people.zip', mimeType: 'application/zip', buffer: Buffer.from('ZIP handled by the backend integration fixture') });
    await page.getByRole('button', { name: 'Validate', exact: true }).click();
    await page.getByText('2 ready / 2 with errors', { exact: true }).waitFor();
    assert.equal(await send.isEnabled(), true);
    assert.equal(await page.getByRole('table', { name: 'Rows with errors' }).locator('tbody tr').count(), 2);
    const download = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Download error report (.xlsx)' }).click();
    assert.equal((await download).suggestedFilename(), 'campaign-errors.xlsx');
    assert.equal(writes.includes('relay_core.bulk_campaigns.control'), false);
    const overflow = await page.locator('.campaign-workspace').evaluate(el => el.scrollWidth > el.clientWidth + 1);
    assert.equal(overflow, false, `Campaign overflow at ${width}/${theme}`);
    await page.screenshot({ path: new URL(`.runtime/campaign-${width}-${theme}.png`, root).pathname, fullPage: true });
    await page.getByLabel('Recipients sheet').setInputFiles({ name: 'replacement.csv', mimeType: 'text/csv', buffer: Buffer.from('Mobile,Name\n12025550101,Asha') });
    await page.getByRole('button', { name: 'Validate', exact: true }).waitFor();
    assert.equal(await send.isDisabled(), true, 'Replacement upload invalidates send');
    await page.getByRole('button', { name: 'Validate', exact: true }).click();
    await page.getByText('2 ready / 2 with errors', { exact: true }).waitFor();
    await send.click();
    await page.getByRole('button', { name: 'Start sending', exact: true }).click();
    await page.getByText('Progress', { exact: true }).waitFor();
    campaign = { ...campaign, status: 'Completed', counts: { ...campaign.counts, queued: 0, sent: 1, failed: 1 } };
    progress();
    await page.waitForFunction(() => [...document.querySelectorAll('.campaign-counters > div')].some(el => el.querySelector('span')?.textContent === 'Sent' && el.querySelector('strong')?.textContent === '1'));
    for (const [label, value] of [['Sent', '1'], ['Failed', '1'], ['Pending', '0']]) {
      const counter = page.locator('.campaign-counters > div').filter({ has: page.getByText(label, { exact: true }) });
      assert.equal(await counter.locator('strong').innerText(), value);
    }
    await page.waitForTimeout(800); // Allow the one event-triggered coalesced read to finish.
    const settled = reads;
    await page.waitForTimeout(1000);
    assert.equal(reads, settled, 'Progress must not poll');
    assert.deepEqual(errors, []);
    outcomes.push(`${width}px ${theme}: passed`);
    await context.close();
  }
  console.log(JSON.stringify(outcomes));
} finally { await browser.close(); }
