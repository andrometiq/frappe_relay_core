const CONNECTION = 'The WhatsApp connection is unavailable. Check the channel settings and try again.';
const HUB_REJECTION = /^Hub rejected this operation: (.+)$/s;

// The Hub's redacted rejection reason, as one short line; nothing that looks like a trace, payload or path.
export function hubReason(text) {
  const detail = String(text || '').replace(/\s+/g, ' ').trim().replace(/\.$/, '');
  if (!detail || /traceback|exception|[{}<>]|\/(private|files|home|tmp)\//i.test(detail)) return '';
  return detail.length > 200 ? `${detail.slice(0, 199).trimEnd()}…` : `${detail}.`;
}

// Campaigns never render exception messages or provider responses, even if a server
// mistakenly puts one in _server_messages. Match known causes to our own copy.
export function campaignError(error) {
  if (error?.status === 401) return 'Your session has expired. Sign in again.';
  if (error?.status === 403) return 'Only a Relay Communication Manager or System Manager can manage campaigns.';
  const text = String(error?.message || error || '');
  // Size reasons are our own text and name the real limit.
  if (/^Header attachment (is empty|must be at most [0-9.]+ [KM]B)\.?$/.test(text)) return text.replace(/\.?$/, '.');
  const rejection = hubReason(text.match(HUB_REJECTION)?.[1]);
  if (rejection) return `WhatsApp did not accept this: ${rejection}`;
  const reasons = [
    [/^Hub returned an invalid response or is unavailable|^Hub HTTP request rejected \(5\d\d\)|^Configure relay_hub_url|timed out|^(Invalid MCP response envelope|Missing MCP result|Unexpected Hub response|Expected stateless JSON MCP response)$/i, CONNECTION],
    [/^Hub connection is not authorized/, 'The Hub connection is not authorized. Update the saved Hub API credential in Relay Settings.'],
    [/^Hub account belongs to another site/, 'The Hub account belongs to another site. Check the Hub settings in Relay Settings.'],
    [/^Hub could not complete this operation|^Hub operation was rejected|^Hub rejected (this|the MCP) operation|^Hub HTTP request rejected \(4\d\d\)/, 'WhatsApp Hub did not accept this action. Check the WhatsApp account setup and template, then try again.'],
    [/^Hub returned no media id/, 'The header file could not be uploaded to WhatsApp. Try again.'],
    [/^The header file could not be read/, 'The header file could not be read. Upload it again.'],
    [/^Configure an enabled WhatsApp channel/, 'Set up an enabled WhatsApp channel in Relay Settings first.'],
    [/^Choose (the WhatsApp (channel|number)|an enabled WhatsApp channel)/, 'Choose the WhatsApp number this campaign sends from.'],
    [/exactly one.*sheet/i, 'The ZIP must contain exactly one Excel or CSV sheet.'],
    [/200 MiB|expanded files/i, 'The ZIP and its expanded files must fit within 200 MiB.'],
    [/10000 entries/i, 'The ZIP must contain at most 10000 files and folders.'],
    [/unsafe path|symbolic link/i, 'The ZIP contains an unsafe path or link. Create a new ZIP with regular files.'],
    [/duplicate file names/i, 'Two ZIP files have the same name. Give each file a unique name.'],
    [/password.protected/i, 'Use a ZIP without password protection.'],
    [/ZIP may contain only/i, 'Include only the sheet and WhatsApp-supported images, videos or documents.'],
    [/ZIP/i, 'The ZIP could not be read. Create a new ZIP and try again.'],
    [/no recipient rows|unique column names/i, 'Add column names on the first row and at least one recipient below them.'],
    [/sheet could not be read/i, 'The sheet could not be read. Save a new Excel or CSV copy and upload it again.'],
    [/file type|file content/i, 'Use the correct header file type for every header file.'],
    [/already exists/i, 'A campaign with this title already exists. Choose another title.'],
    [/readable title/i, 'Use a title of 3–100 characters without slashes or special symbols.'],
    [/approved template|template not found/i, 'Choose a template approved for this WhatsApp number.'],
    [/start time|schedule.*ahead/i, 'Choose a start time at least one minute and no more than 90 days ahead.'],
    [/validate|valid row|import.*failed/i, 'Validate the recipients and fix any file errors before sending. At least one row must be ready.'],
    [/permission|not permitted|denied/i, 'You do not have access to this campaign or one of its files.'],
    [/connection lost|failed to fetch|network/i, 'Connection lost. Check your connection and try again.'],
  ];
  return reasons.find(([pattern]) => pattern.test(text))?.[1] || 'The action could not finish. Check the campaign details and try again.';
}
