# Bulk campaigns

Bulk campaigns are available to Relay Communication Manager and System Manager. Template, sheet, contact-audience and JSON campaigns share `bulk_campaigns.py`; files use `campaign_media.py` and phone numbers use `bulk_sheet.sheet_phone`.

## 1. Upload

Create a campaign for an approved template (or text/media inside the reply window). Download the Excel template and fill it in: mobile numbers belong in the first column, followed by template values. New valid mobile numbers are enrolled through the existing Relay contact flow.

Upload `.xlsx`, `.csv` or `.tsv`, or a ZIP containing exactly one such sheet and optional WhatsApp image, video or document files. The site's normal upload limit also applies. ZIPs are limited to 200 MiB both compressed and expanded, and 10000 entries including folders and hidden entries. Hidden files/folders and `__MACOSX` are ignored. Subfolders are flattened. Absolute paths, traversal, symbolic links, encrypted entries, unsupported files and duplicate flattened filenames are rejected. Nested ZIP archives are not accepted. An XLSX in the ZIP counts as a sheet, not as a header document.

ZIP media becomes the existing per-contact header attachment selection. Name each file with the recipient's mobile number, for example `12025550101.png`. National numbers use the campaign's country, derived from the sending company. There is no filename column. Alternatively, upload one static header file or select individual mobile-named files. Header files remain private, must contain 1 byte to 4 MiB, and must match the template's media kind and file signature. Images accept JPG/PNG, videos MP4, and documents the existing WhatsApp registry types.

## 2. Validate

Select **Validate** after choosing the value mapping. This queues the existing import job; it sends no messages and uploads nothing to Hub. Every row is checked for a valid mobile number, duplicates, required values, header presence/type/size, opted-out or revoked endpoints, and (for text/media messages) an open 24-hour reply window. The enabled sending channel is checked before validation and again before sending. Unmatched or invalid uploaded header files appear as file issues.

The result shows **N ready / N with errors**, the first 50 error rows and a downloadable Excel report containing all skipped/failed rows, their original row numbers, mobile numbers and friendly reasons. Unknown exceptions/provider responses are not displayed. Rows with errors are stored as Skipped; valid rows are Pending. Sending requires at least one valid row. A replacement upload invalidates earlier validation. Revalidating replaces unsent imported rows through the existing import flow.

## 3. Send

Select **Start sending** or schedule a start. Only validated Pending rows are admitted to Hub. Opt-outs, revoked endpoints, media availability and reply-window eligibility are checked again when sending. Skipped rows never enter the Hub batch. Progress uses the existing `relay_campaign_progress` Socket.IO event and a coalesced event-triggered read, with no polling.

Sending keeps the existing 45-second slices on the `long` queue. Each send job receives `max(600, 5 × current Pending/Queued messages)` seconds; imports keep their 1800-second timeout. Media preparation checks the deadline between files, and cancellation also checks it between chunks. A slice may finish its current bounded Hub operation and bulk admission after its deadline; Hub requests have 30-second network timeouts. The minimum 600 seconds gives room for those calls, lock acquisition and persistence. Remaining work moves to the next deduplicated slice; it does not require one worker to run the whole campaign. Hub backpressure, retry keys and scheduler recovery are unchanged.

Recipient records retain validation outcome/reason/time/user in their existing `arguments.validation`, followed by the existing Queued, Sent, Delivered, Read, Failed, Skipped or Cancelled status and reason fields. Campaign `arguments.phases` records creation, upload, validation, control, scheduled-start and completion transitions with timestamp/user. The campaign page displays this history. No new DocTypes or fields are required.

## Local verification

`tests/test_campaign_zip_validation.py` covers archive limits and unsafe paths, validation evidence, blocked sending, timeout calculation, permissions and Excel safety. Existing campaign tests exercise missing/wrong media, duplicates, opt-outs, send batching, retries and delivery outcomes.

`FRAPPE_STREAM_LOGGING=1 ../../env/bin/python -B tests/integration_campaign_sheet_site.py` runs against the local `relay-flows-test.localhost` fixture site. It uses representative rows, private file adapters rooted in this repository, a mocked Hub, and disabled external sending; no migration or web server is started. Clearly named local test campaigns/contacts remain for inspection. It exercises ZIP → validation → error download → send → sent/failed delivery projection and phase history, plus concurrent contact enrollment.

After the normal frontend build, `node frontend/tests/browser/campaignValidation.mjs` checks the built UI at desktop/phone sizes in light/dark themes using intercepted HTTP. It verifies validation gating, replacement uploads, error-report download and Socket.IO sent/failed/pending updates without polling without starting a server or sending messages. The script uses the repository-local Playwright harness under `.runtime/browser` and system Chrome; it complements the real local database/API/job integration test.
