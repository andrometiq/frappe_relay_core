# Message translation and voice transcripts

A System Manager configures **Relay Automation Policy** in Frappe Desk for the intended channel and business DocType. Choose an enabled provider, a dedicated execution user with access to that business, and a daily attempt limit. Enable **Automatically translate incoming messages to English** to queue new incoming text messages independently of automated replies. Existing historical messages are not silently backfilled. The site's existing AI automation switch must also be enabled.

For voice/audio, enable **Allow Voice Transcription** and choose a transcription provider. Reply inference and translation reuse the same source-version transcript. The original audio and original-language transcript remain available. The English translation is stored separately. Disabling a policy prevents pending jobs from invoking the provider.

Operators with current conversation access use **View in English** / **View original**. This only reads a stored result. **View transcript** reads the voice transcript. Provider/model/time information is available in details; unknown historical provenance is not guessed. Permission revocation or a source edit prevents access to stale derived text.

Each translation segment is at most 2,000 source characters, with at most 12,000 source characters per message. Every provider call, including a fallback and voice transcription, consumes the shared daily attempt budget. Results exceeding configured bounds or invalid JSON fail rather than silently replacing or truncating the original message. Translation accuracy requires review with the chosen live model and languages.

`Relay Message Translation` in Desk records job state and failures. Pending and expired Processing jobs are recovered by the Relay recovery job. Completed work is replay-safe; failed jobs require review and are not automatically retried indefinitely. A System Manager can use **Retry translation** on a failed job after correcting configuration or budget. The retry rechecks the current source/policy and records the request; changed source or policy creates a new versioned job. Historical messages are not automatically backfilled.

Only fixture AI responses have been used in the implementation acceptance checks. Live provider quality, latency and cost acceptance remain outstanding. Installation did not enable AI policies or import legacy messages.
