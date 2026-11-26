# Image and voice automation

Enable AI features in Relay Settings first. Received voice messages use the Relay Settings **Voice transcription model** and keep text/status on the message. When that field is empty, the legacy **Voice transcription provider** (OpenAI speech-to-text) is used. The skill reply path uses an existing transcript in its original language; if none is available it hands off with a clear explanation. It does not transcribe again or guess from audio. Image observations require a vision-capable AI Model. Legacy policy media flags still apply to the older multimodal context helper. See [AI skills and business events](ai-skills-and-business-events.md) for language and script checks.

The voice transcription model is a frappe_tools AI Model that reads audio, for example an OpenRouter model for `google/gemini-2.5-flash`. Relay sends the audio as an OpenRouter `input_audio` part with the format from the file type (`ogg`, `mp3`, `m4a`, `wav` or `webm`). The model must write each word in the language and script that was spoken (Tamil in Tamil script, Hindi in Devanagari, English in English), must not translate, and returns `[no speech]` for silence. Instructions spoken in the audio are ignored. The provider guard of Relay AI applies: the model's account auth type must be in Relay Settings `allowed_ai_auth_types`, so an OpenRouter API key needs `API Key` there. OpenAI Codex, Anthropic and Genie accounts cannot read audio, and the voice note transcript is Failed with that reason. Each call has a 60-second limit and is logged in Document AI Call Log without the audio data.

Inputs are taken only from the authenticated source message through the same private attachment boundary used by the inbox. No model-authored URL, filename or recipient is accepted. Source business access, assignment, channel/account, verified endpoint, policy version and human takeover state remain checked before inference and before effects.

Images are limited to one JPEG, PNG or WebP, 4 MiB and 12 million pixels; corrupt/type-mismatched images fail closed. Voice is limited to 4 MiB and five minutes. Install `ffprobe` on Core workers for bounded audio validation. The probe uses private temporary files, explicit media demuxers, no network protocols and a five-second timeout. Transcription requests have a 25-second timeout and a 64 KiB response cap. The transcript is kept on the automation run and can be reviewed in the installed Automation view. Only users who can read the underlying conversation can read the transcript.

Each transcription and each reasoning/fallback attempt consumes the same policy daily attempt limit. A cached transcript is reused after worker recovery. Transcripts and image text are untrusted model input; the validated action schema still restricts outputs to configured tickets, approved replies and handoff. No raw model-authored tool call is executed.

The existing text adapters keep their protocols. Image requests use OpenAI Responses `input_image`, Anthropic base64 image blocks, Gemini inline media, and OpenRouter image URLs containing inline base64 data. GLM vision uses its documented native chat-completions endpoint rather than the text adapter's Anthropic-compatible endpoint. Model-specific availability remains an external provider acceptance check; local tests never claim that a user's subscription grants access to a model.

Protocol references checked 2026-09-23:

- [OpenAI image inputs](https://developers.openai.com/api/docs/guides/images-vision)
- [OpenAI file transcription](https://developers.openai.com/api/docs/guides/speech-to-text)
- [Claude vision](https://platform.claude.com/docs/en/build-with-claude/vision)
- [Gemini inline media schema](https://ai.google.dev/api/generate-content)
- [OpenRouter image understanding](https://openrouter.ai/docs/guides/overview/multimodal/image-understanding)
- [OpenRouter audio input](https://openrouter.ai/docs/features/multimodal/audio)
- [GLM vision endpoint](https://docs.z.ai/guides/vlm/glm-4.6v)

Local evidence: `tests/test_multimodal.py` covers request contracts, corrupt images, duration limits and error redaction. `tests/integration_multimodal_site.py` covers scoped image/voice inference, transcript persistence, replay, disabled modality, revoked endpoints and shared daily budgets. Provider calls are mocked; live AI acceptance has not been performed.
