# Discord Window Manager Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Tauri desktop shell that opens and manages multiple Discord browser windows from one control dashboard.

**Architecture:** Keep one Tauri main window as the control surface, and spawn one native Discord `WebviewWindow` per session. The frontend owns session metadata, settings, and layout previews; the Rust layer owns actual native window creation, sizing, positioning, focusing, and closing with per-window data directories for login-state isolation.

**Tech Stack:** Next.js App Router frontend, Tailwind UI, Tauri 2 Rust commands, Node built-in test runner for pure layout logic.

---

### Task 1: Write and verify the layout-state tests

**Files:**
- Create: `frontend/tests/discord-window-layout.test.ts`
- Create: `frontend/lib/discord-window-layout.ts`

**Step 1: Write the failing test**

Write tests for:
- layered placement fills stack depth before moving to the next grid slot
- placement wraps to the next row after `columns * layers`
- settings sanitization clamps invalid values into safe ranges

**Step 2: Run test to verify it fails**

Run: `node --test --experimental-strip-types frontend/tests/discord-window-layout.test.ts`

Expected: FAIL because `frontend/lib/discord-window-layout.ts` does not exist yet.

**Step 3: Write minimal implementation**

Implement:
- `DEFAULT_WINDOW_MANAGER_SETTINGS`
- `sanitizeWindowManagerSettings`
- `getWindowPlacement`
- `buildWindowPlacements`

**Step 4: Run test to verify it passes**

Run: `node --test --experimental-strip-types frontend/tests/discord-window-layout.test.ts`

Expected: PASS

### Task 2: Add Tauri commands for Discord child windows

**Files:**
- Modify: `src-tauri/src/lib.rs`

**Step 1: Write the failing frontend integration against the missing commands**

Use the new page and helper module to call:
- `create_discord_window`
- `update_discord_window`
- `focus_discord_window`
- `close_discord_window`

**Step 2: Run Rust check to surface missing command wiring**

Run: `cargo check --manifest-path src-tauri/Cargo.toml`

Expected: FAIL until command structs and handlers are added.

**Step 3: Write minimal Rust implementation**

Implement:
- payload structs with `camelCase` serde mapping
- per-window data-directory creation under app data
- `WebviewWindowBuilder` with external Discord URL, title, position, size
- update/focus/close command handlers
- command registration in `invoke_handler`

**Step 4: Run Rust check to verify it passes**

Run: `cargo check --manifest-path src-tauri/Cargo.toml`

Expected: PASS

### Task 3: Build the main dashboard UI

**Files:**
- Modify: `frontend/app/page.tsx`
- Modify: `frontend/app/layout.tsx`
- Modify: `frontend/app/globals.css`
- Create: `frontend/lib/tauri-discord-windows.ts`
- Modify: `frontend/package.json`

**Step 1: Replace the old homepage entry with the window dashboard**

Build:
- header with active window stats
- add-window button
- settings panel for columns, stack layers, width/height, offsets, spacing
- live stack preview
- session cards with open/focus/close actions

**Step 2: Keep the page usable outside Tauri**

Show a visible desktop-runtime warning when the page is opened in a plain browser and keep preview/layout state functional.

**Step 3: Add minimal Tauri frontend bridge**

Implement a small wrapper around `@tauri-apps/api/core` that no-ops cleanly when Tauri is unavailable.

**Step 4: Run frontend build**

Run: `pnpm --dir frontend build`

Expected: PASS

### Task 4: Final verification

**Files:**
- None

**Step 1: Re-run the focused layout test**

Run: `node --test --experimental-strip-types frontend/tests/discord-window-layout.test.ts`

Expected: PASS

**Step 2: Re-run frontend build**

Run: `pnpm --dir frontend build`

Expected: PASS

**Step 3: Re-run Rust check**

Run: `cargo check --manifest-path src-tauri/Cargo.toml`

Expected: PASS
