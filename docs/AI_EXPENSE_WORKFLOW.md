# AI expense workflow (Quick add)

Type a sentence such as "Yesterday I paid 1200 for petrol" or "Kal 350 rupaye chai aur snacks pe kharch kiye". The app extracts the details, asks only for what is missing, shows a draft, and saves only after you confirm.

## Division of labour
| Step | Done by |
|---|---|
| Pull *phrases* out of the sentence (amount text, date text, type, category hint, merchant, account hint) | AI, as schema-validated JSON |
| Turn the amount phrase into a number (`2.5k`, `1 lakh`, `Rs 1,25,000`) | Code (`expense_intent.parse_spoken_amount`) |
| Turn the date phrase into a date in the user's timezone | Code (`resolve_date_phrase`) |
| Match a category / account to the user's own | Code (suggestions are labelled "Suggested") |
| Validate and save | The normal transaction service, after confirmation |

The model never produces a final amount or date, never writes to the database, and its output is rejected unless it matches the schema. Unknown keys are ignored, and the user's text is passed as delimited data.

## State machine
`needs_clarification` → `ready_for_review` → `saved`, with `cancelled` and `expired` as exits. Required fields are amount, type and date, asked one question at a time in that order. Category, account, merchant and description are never asked for.

- Answers to the question just asked (an amount, a date, "expense"/"income") are parsed locally, so they cost no AI quota.
- Anything else (for example "No, it was 650 not 500") is sent to the model with the current draft, and only what it states or corrects is merged. Other fields, such as the date, are kept.
- A correction that can't be applied (ambiguous or future date, unreadable amount) is asked about; the old value stays until answered, and the draft cannot be saved while a question is open.
- Drafts expire after 60 minutes of inactivity. The original sentence is **not** stored, only the resolved fields.

## Date and amount rules
`kal` means yesterday (spending is recorded after the fact); `parso` means two days ago. `N days/weeks ago` is exact. `last <weekday>` is strictly before today; a bare weekday on that same weekday is ambiguous. A bare day number (`5th`) is its most recent occurrence on or before today, or ambiguous if that month has no such day. `2 October` without a year is this year, or last year if that would be in the future. Numeric dates follow the user's `date_format`. Months, weeks and anything unclear are asked about. Future dates are refused. Amounts with more than two decimals, zero, negatives or unrecognised words are rejected, never rounded.

## Saving
`POST .../confirm` creates the transaction through the same validation as manual entry, with source `ai` and the draft id as its idempotency key. Double clicks, retries and refreshes return the original transaction (`idempotent_replay: true`). If saving fails validation, the draft stays reviewable.

## Provider, limits and failure behaviour (`app/integrations/ai/`)
- `AIProvider` has `generate_text`, `generate_structured` and `check_health`. Gemini is one adapter over direct REST (no SDK); a new provider needs an adapter and configuration only.
- The model comes from `AI_TEXT_MODEL`, with `AI_FALLBACK_MODEL` tried when the first is quota-limited or failing (free-tier quota is per model).
- 429 skips straight to the fallback; 5xx and timeouts retry with exponential backoff and jitter up to two retries; 400/401/403 are never retried. An overall deadline (twice the per-request timeout) bounds a request.
- Guards before any request: `AI_REQUESTS_PER_MINUTE`, `AI_DAILY_REQUEST_BUDGET` and a limit of two concurrent requests. Usage is visible at `GET /api/v1/ai/status`.
- The API key is sent only in a header. Prompts, responses and keys are never logged or placed in error messages.
- If AI is unconfigured, unavailable or out of quota, users get a clear message and manual entry, existing records and reports keep working.

## Checking quota and models
Free-tier limits and model availability change. Check them in Google AI Studio (rate limits page) and https://ai.google.dev/gemini-api/docs/pricing, and confirm a model with `GET .../v1beta/models`. Verify structured output on a model before adopting it.

## Voice entry
Press the microphone, speak, press **Stop and use**. The recording becomes text in the message box; you check and fix it, then press Send. From there it is exactly the text workflow above, and the saved transaction is marked `voice`.

1. **Consent.** The first time, a dialog explains that the audio goes to Google for transcription and that this app doesn't keep it. Consent is remembered in the browser (`localStorage["voiceConsent"]`).
2. **Capture.** `MediaRecorder` records; the page stops automatically at 60 seconds. The browser decodes the recording and re-encodes it as 16 kHz mono WAV, so the format is always known and the real duration is exact.
3. **Upload.** `POST /api/v1/ai/transcriptions` (multipart `audio`, optional `duration_ms`). The server checks the file's real signature (not its name or claimed type), size (10 MB), allowed formats (wav, webm, ogg, mp3, m4a) and, for WAV, the duration from the header. Audio is held in memory only: never written to disk, never logged.
4. **Transcribe.** Done by a separate adapter that uses `TRANSCRIPTION_MODEL` with the same `AI_API_KEY`. It shares the text provider's retry, fallback and quota guards. Digits are requested for amounts; Hindi is written in Roman letters (Hinglish).
5. **Review.** The transcript is returned to the browser, not interpreted or stored. Silence returns `no_speech`. Noise can still be read as words, which is one reason you always see and edit the text before sending.

Cost in quota: one request to transcribe plus one to extract. The microphone needs a secure context (`localhost` or HTTPS) and `Permissions-Policy: microphone=(self)`, which the app sets. Switch it on by setting `TRANSCRIPTION_MODEL` to a model that accepts audio (verify with a test file before choosing one); it needs `AI_API_KEY`.

## Not yet implemented
Multiple transactions in one sentence, live streaming transcription, AI-written insights.
