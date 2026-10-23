# Communication reports

Open Reports, choose a business type and up to 20 records using the search-based selector, select the inclusive start/end dates and PDF or Excel, then choose Prepare report. Processing runs in Frappe's long queue. The page updates when the job finishes and offers Download report. Recent reports remain available after a reload.

Dates use the site's message timeline: provider send time where recorded, otherwise record creation time. Only messages accessible to the requesting user are included. The export contains full message text, direction, delivery state, message type, references and attachment names. A range exceeding 20,000 accessible messages fails explicitly; narrow the dates rather than accepting an incomplete export.

Include image previews is optional. PDF embeds previews beside messages; Excel adds an Images worksheet. Image aspect ratios are preserved. Up to 50 previews and 20 MiB of processed preview data are included. Each source is limited to 4 MiB and 10 million pixels. Images are decoded into a static JPEG preview, at most 900 × 900 pixels. Animated stickers unsupported by the image decoder are listed as unavailable. Audio, voice, video, documents and email attachments are inventoried rather than embedded as executable or playable files. Open the original conversation to access originals.

The worker reads images through the same permission-checked attachment service as the chat. Provider attachments can expire or be unavailable. The export labels unavailable/limited previews and retains message text. It never follows arbitrary URLs from message text or HTML. Preparing a report does not mark its messages as read or send messages to contacts.

PDF/XLSX artifacts are stored in a private directory outside direct file routes. Download rechecks access to the report's business scope and messages. Deleting the native Prepared Report removes its export files. Excel treats message content as literal text, including text beginning with formula characters.

Shared messages are included once and list all matching selected business records. Access is checked for every selected record.

Daily summary mode is implemented. Enable summaries on the channel’s Desk AI policy, then choose Daily summary in Reports. The background report groups accessible messages by conversation, channel and date; each chunk contains at most 200 messages and 36,000 bytes of text evidence. It reuses summaries only when the requester, policy version and source evidence match. Changed messages invalidate that reuse. A failed summary may retry once under the existing permission and budget checks. Missing policy, exhausted budget or incomplete summary fails the report explicitly. PDF and Excel include summary text and source-message references; downloads recheck access without running AI again. This summarizes stored message text, not the contents of attached images or documents.

Not yet implemented: embedded email image previews and resumable exports above the current row limit. Live installed-site worker/download acceptance has covered empty reports; populated image exports are verified with isolated database and attachment fixtures, not live provider media.
