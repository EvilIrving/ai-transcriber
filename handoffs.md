# Handoff — AI Transcribe refactor & feature work

Branch: `refactor/de-async-summarizer`
Date: 2026-06-09
Status: Item ① **done & verified (uncommitted)**. Items ②③④ **not started** — analysis + plans below.

---

## ✅ Item ① — Architecture decoupling (DONE, behavior-preserving)

### Backend: `main.py` 1268 → 43 lines
New layered layout (flat modules — app runs from inside `backend/` via `uvicorn main:app`, so **use flat imports, not package-relative**):

| Layer | File | Responsibility |
|---|---|---|
| App assembly | `backend/main.py` | FastAPI app, CORS, static mount, `include_router` only |
| HTTP | `backend/routers/core.py` | `/`, `/api/models` |
| HTTP | `backend/routers/transcribe.py` | process/upload, task-status, SSE stream, `/api/download/{file}`, delete, `tasks/active`, retry, `_enqueue_upload_job` |
| HTTP | `backend/routers/downloads.py` | download video/audio/subtitles + file serving |
| HTTP | `backend/routers/rss.py` | all `/api/rss/*` |
| Orchestration | `backend/pipeline.py` | `run_post_extract_pipeline`, `process_video_task`, `process_upload_task`, `run_download_*`, `run_rss_summarize_task`, `_llm_call`, `sanitize_title_for_filename`, `txt_to_raw_transcript_markdown` |
| Dependencies | `backend/services.py` | processor singletons (`video_processor`, `transcriber`, `summarizer`, `translator`, `rss_reader`) + `UPLOAD_*` config |
| State (unchanged) | `backend/task_store.py` | `tasks`, `active_tasks`, `sse_connections`, `processing_urls`, stage/progress, SSE broadcast — single source of truth |

**Verification done:** route table byte-identical to pre-refactor baseline (27 routes); all 8 modules compile + import; `TestClient` smoke test passes (`/api/tasks/active` 200, bad task-status 404, `/api/rss/feeds` 200).

Re-run regression check:
```bash
cd backend && ../venv/bin/python -c "import main; print(len(main.app.routes))"   # expect 27
```

### Frontend: extracted network layer
- New `static/js/api.js` → `window.VTApiClient`. **Only** place that knows server endpoints.
  - Methods: `processVideo, retry, taskStatus, deleteTask, fetchModels, downloadFormats, downloadVideo, downloadAudio, downloadSubtitles, rssParse(fd, signal), rssCreateTask`.
  - URL builders (for EventSource / `<a download>`): `streamUrl, mdFileUrl, videoFileUrl`.
  - Error contract: on HTTP error throws `Error` with `.detail` (server detail or undefined), `.message` (= detail || `HTTP <status>`), `.status`. Callers use `err.detail || this.t('fallback')` to preserve original localized messages.
- Wired in `static/app.js` ctor: `this.api = new window.VTApiClient(this.apiBase)`.
- Loaded first in `static/index.html` (before i18n.js): `<script src="/static/js/api.js?v=20260609-api-layer">`.
- All inline `fetch(` removed from `transcribe.js`, `ui.js`, `download.js`, `rss.js`. RSS 35s abort-timeout preserved (controller created in `_rssParseFeed`, signal passed to `api.rssParse`). Removed dead `_rssFetchWithTimeout`.

**Verification done:** zero raw `fetch(` / `apiBase}/` left in mixins; all JS passes `node --check`; client methods + URL builders confirmed.
**NOT done:** in-browser runtime test (no browser in session). Smoke-test on pickup: transcribe a URL, fetch models, download page, RSS parse/summarize.

---

## ⚠️ Item ② — Long-text optimization returns empty (NOT STARTED — root cause identified)

**Symptom:** long transcripts frequently yield an empty optimized transcript.

**Root cause:** in `backend/summarizer.py`, `_format_single_chunk()` (and the `summarize` paths) only fall back to basic formatting **on exception**, never on blank model output. When a chunk returns empty `message.content` — common with `finish_reason=length` truncation, content filters, or reasoning models where `max_tokens=4000` is consumed by reasoning tokens — `strip_llm_artifacts("")` yields `""`. Every chunk silently becomes `""`, the merge is `""`, and `pipeline.run_post_extract_pipeline` writes an empty transcript. (The pipeline's `try/except` around `optimize_task` doesn't catch this because no exception is raised.)

**Fix plan:**
1. In `_format_single_chunk`: after `strip_llm_artifacts`, if result is blank → fall back to `_apply_basic_formatting(chunk_text)` (treat blank == failure). Optionally inspect `response.choices[0].finish_reason`.
2. In `summarize` / `_summarize_with_chunks` / `_integrate_chunk_summaries`: same blank-guard.
3. In `pipeline.run_post_extract_pipeline`: after `script = await optimize_task`, guard `if not (script or "").strip(): script = raw_script`.
4. Consider raising/​separating `max_tokens` for the optimize step and verifying with the actual configured model.

**Verify:** feed a long (>4000-char) transcript via a `.txt` upload and confirm non-empty optimized output; simulate a blank-content response to confirm fallback.

---

## ☐ Item ③ — Batch deletion for history (NOT STARTED)

History is **client-side IndexedDB**, all in `static/js/history.js` (store `ai_transcriber_history`). Today only single delete (`_historyDelete(id)`).

**Plan (self-contained, low risk, frontend-only):**
1. Add multi-select UI to history cards in `_historyRender` (checkbox per `.history-item`, a "select mode" toggle or persistent checkboxes + a "Delete selected" bar).
2. Track selected ids in instance state (e.g. `this._historySelected = new Set()`).
3. Add `_historyDeleteMany(ids)` — one `readwrite` tx deleting all ids, then update `this.historyItems` + re-render.
4. Add i18n keys in `static/js/i18n.js` (e.g. `select_all`, `delete_selected`, `confirm_delete_selected`).

No backend change needed.

---

## ☐ Item ④ — Lighter retry: summary-only regenerate IN PLACE (NOT STARTED)

**Decision (confirmed with user):** regenerate the summary **in place** — same task/transcript, overwrite only the summary. No transcription, no transcript re-optimization.

**Current behavior:** `POST /api/retry/{task_id}` (`routers/transcribe.py`) creates a NEW task id and re-runs the full `run_post_extract_pipeline` (re-optimizes transcript + re-summarizes).

**Plan:**
1. `pipeline.py`: add `regenerate_summary(task_id, request_summarizer, summary_language, use_two_step)` that:
   - reads existing optimized transcript (prefer `tasks[task_id]["script_path"]`, fallback `raw_script_file`),
   - runs **only** `summary_two_step` / `summarize` (no `optimize_transcript`),
   - overwrites `summary`, `summary_path`, `summary_prompt_file` on the **same** task id, broadcasts update. Use the `retry` stage set in `task_store.STAGE_WEIGHTS` (or a lighter summary-only stage list).
2. `routers/transcribe.py`: either change `/api/retry/{task_id}` to call the in-place path, or add `POST /api/regenerate-summary/{task_id}`. (If keeping `/retry` for full re-run, add a new endpoint + new `api.js` method `regenerateSummary`.)
3. `static/js/api.js`: add method; `static/js/transcribe.js` `_retryTranscription` (or a dedicated summary-retry button) calls it. Note the retry buttons today: `retryScriptBtn`, `retrySummaryBtn`, `retryTranslationBtn` all call `_retryTranscription`. The summary button should trigger the lighter path.
4. Update `_historySaveSummary` flow if the regenerated summary should replace the history entry.

**Verify:** retry a completed task; confirm no transcription/optimization stages run, transcript unchanged, only summary updated in place.

---

## Conventions / gotchas
- Backend runs from `backend/` cwd (`start.py` does `os.chdir`). Keep flat imports.
- `temp/tasks.json` persists task state; processing tasks are marked errored on restart (`task_store.py` startup).
- Frontend mixins are `Object.assign`'d in `app.js`; new method bundles must be loaded before `app.js` and attached to `window.VT*Methods` or the new class instance field.
- Nothing committed yet on this branch beyond prior commits — review `git diff` before committing ①.
