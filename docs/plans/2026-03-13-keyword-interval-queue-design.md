# Keyword Interval Queue Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add per-website-config keyword reply batching so each Discord server can independently limit how many keyword-triggered replies are sent during each rotation interval window.

**Architecture:** Extend `user_website_settings` with one numeric field for the maximum keyword replies allowed per interval window. In the bot, queue keyword-match reply jobs by `(user_id, website_id, guild_id)` and flush immediately up to the configured limit, then defer remaining jobs until the next rotation window. Keep image replies and Bark interaction notifications unchanged.

**Tech Stack:** Flask, SQLite, Next.js, React, Python asyncio, unittest

---

### Task 1: Persist per-website keyword interval limit

**Files:**
- Modify: `backend/database.py`
- Modify: `backend/app.py`
- Test: `backend/tests/test_keyword_reply_settings.py`

**Step 1: Write the failing test**
Create database tests that expect `get_user_website_settings()` to expose a default `keyword_reply_batch_size` and `update_user_website_rotation()` to persist it.

**Step 2: Run test to verify it fails**
Run: `python -m unittest backend.tests.test_keyword_reply_settings -v`
Expected: FAIL because the field is not returned or persisted.

**Step 3: Write minimal implementation**
Add the SQLite column migration, return the field from reads, and allow updates through the rotation settings API.

**Step 4: Run test to verify it passes**
Run: `python -m unittest backend.tests.test_keyword_reply_settings -v`
Expected: PASS.

### Task 2: Add queue limiter for keyword replies

**Files:**
- Create: `backend/tests/test_keyword_reply_queue.py`
- Modify: `backend/bot.py`

**Step 1: Write the failing test**
Create focused queue-behavior tests that prove a queue with `batch_size=2` and `interval=300` sends the first two immediately, keeps the third pending, and releases it after the interval boundary.

**Step 2: Run test to verify it fails**
Run: `python -m unittest backend.tests.test_keyword_reply_queue -v`
Expected: FAIL because queue helpers do not exist.

**Step 3: Write minimal implementation**
Add small queue helper functions/classes and wire keyword-search replies through them before `schedule_reply()`.

**Step 4: Run test to verify it passes**
Run: `python -m unittest backend.tests.test_keyword_reply_queue -v`
Expected: PASS.

### Task 3: Add UI control next to rotation settings

**Files:**
- Modify: `frontend/components/accounts-view.tsx`
- Modify: `frontend/app/api/websites/[id]/rotation/route.ts`

**Step 1: Write/update the UI state path**
Add local state/input wiring for the new numeric setting near the existing rotation interval control.

**Step 2: Write minimal implementation**
Send the numeric field through the same PUT route and keep local website state in sync after save.

**Step 3: Verify frontend build/lint path**
Run: `pnpm --dir frontend lint`
Expected: PASS.

### Task 4: End-to-end verification

**Files:**
- No new files

**Step 1: Run backend targeted tests**
Run: `python -m unittest backend.tests.test_keyword_reply_settings backend.tests.test_keyword_reply_queue -v`
Expected: PASS.

**Step 2: Run frontend lint**
Run: `pnpm --dir frontend lint`
Expected: PASS.
