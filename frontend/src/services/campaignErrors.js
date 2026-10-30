// Campaigns never render exception messages or provider responses, even if a server
// mistakenly puts one in _server_messages. Match known causes to our own copy.
export function campaignError(error) {
  if (error?.status === 401) return 'Your session has expired. Sign in again.';
  if (error?.status === 403) return 'Only a Relay Communication Manager or System Manager can manage campaigns.';
  const text = String(error?.message || error || '');
  // Size reasons are our own text and name the real limit.
  if (/^Header attachment (is empty|must be at most [0-9.]+ [KM]B)\.?$/.test(text)) return text.replace(/\.?$/, '.');
  const reasons = [
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
    [/Hub|channel|WhatsApp number/i, 'The WhatsApp connection is unavailable. Check the channel settings and try again.'],
  ];
  return reasons.find(([pattern]) => pattern.test(text))?.[1] || 'The action could not finish. Check the campaign details and try again.';
}
