# Global Filter Blocked Users And OCR Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 补齐全局 `website_block_user_trigger` 和全局 `ocr_contains`，让全局拉黑触发可记录并展示对应用户，全局 OCR 只拦截图片回复不拉黑用户。

**Architecture:** 后端新增全局拉黑用户表与接口，机器人把全局拉黑触发从普通消息过滤链中独立出来，保证它先于全局文本过滤执行；图片回复链把全局 OCR 规则并入现有 OCR 判定，只在存在 OCR 规则且相似度达阈值时执行 OCR。前端在全局消息过滤卡片下展示仅属于 `website_block_user_trigger` 的对应用户列表，并沿用网站级紧凑样式。

**Tech Stack:** Flask, SQLite, discord.py-self runtime, Next.js 16, React 19, node:test, unittest

---

### Task 1: 补失败测试

**Files:**
- Modify: `backend/tests/test_message_filter_helpers.py`
- Modify: `backend/tests/test_keyword_reply_queue.py`
- Modify: `frontend/filter-options.node-test.ts`

**Step 1: Write the failing test**

- 给 `should_run_ocr_for_image_reply` 增加全局 OCR 规则测试。
- 给 `on_message` 增加全局拉黑触发优先于全局 `contains http` 的测试，以及命中过一次后后续消息直接跳过的测试。
- 给前端全局消息过滤增加 `ocr_contains` / `website_block_user_trigger` 输入归一化和“对应用户”紧凑展示断言。

**Step 2: Run test to verify it fails**

Run: `python3 -m unittest backend.tests.test_message_filter_helpers backend.tests.test_keyword_reply_queue`

Run: `node --test frontend/filter-options.node-test.ts frontend/website-filters.node-test.ts`

Expected: 新增测试失败，说明缺口还在。

### Task 2: 数据库与接口

**Files:**
- Modify: `backend/database.py`
- Modify: `backend/app.py`
- Create: `frontend/app/api/message-filters/[id]/blocked-users/route.ts`
- Create: `frontend/app/api/message-filters/[id]/blocked-users/[discordUserId]/route.ts`

**Step 1: Write the failing test**

- 复用 Task 1 中对接口和拉黑记录的行为测试，不额外加独立集成测试。

**Step 2: Run test to verify it fails**

Run: `python3 -m unittest backend.tests.test_keyword_reply_queue`

Expected: 全局拉黑记录相关断言失败。

**Step 3: Write minimal implementation**

- 新增 `message_filter_blocked_users` 表。
- 增加全局拉黑用户的增删查方法。
- 增加 Flask API 和 Next 代理路由。

**Step 4: Run test to verify it passes**

Run: `python3 -m unittest backend.tests.test_keyword_reply_queue`

Expected: 全局拉黑记录相关测试通过。

### Task 3: 机器人执行链

**Files:**
- Modify: `backend/message_filter_utils.py`
- Modify: `backend/bot.py`

**Step 1: Write the failing test**

- 复用 Task 1 里 OCR 和全局拉黑顺序测试。

**Step 2: Run test to verify it fails**

Run: `python3 -m unittest backend.tests.test_message_filter_helpers backend.tests.test_keyword_reply_queue`

Expected: 全局 OCR / 全局拉黑顺序测试失败。

**Step 3: Write minimal implementation**

- 扩展 `should_run_ocr_for_image_reply` 支持全局过滤。
- 把全局 `website_block_user_trigger` 从 `_should_filter_message` 外独立处理。
- 在 `handle_image`、`_build_keyword_reply_job`、`schedule_reply` 中接入全局 `ocr_contains`。

**Step 4: Run test to verify it passes**

Run: `python3 -m unittest backend.tests.test_message_filter_helpers backend.tests.test_keyword_reply_queue`

Expected: 相关测试通过。

### Task 4: 前端全局消息过滤卡片

**Files:**
- Modify: `frontend/components/accounts-view.tsx`
- Modify: `frontend/filter-options.node-test.ts`

**Step 1: Write the failing test**

- 断言全局 `website_block_user_trigger` 卡片下存在“对应用户”紧凑网格。
- 断言 `ocr_contains` / `website_block_user_trigger` 进入全局多值规则归一化逻辑。

**Step 2: Run test to verify it fails**

Run: `node --test frontend/filter-options.node-test.ts frontend/website-filters.node-test.ts`

Expected: 新增断言失败。

**Step 3: Write minimal implementation**

- 添加全局 blocked users 状态、请求、删除逻辑。
- 在全局规则卡片下只对 `website_block_user_trigger` 展示用户列表。
- 补全新增和编辑表单的多值规则校验。

**Step 4: Run test to verify it passes**

Run: `node --test frontend/filter-options.node-test.ts frontend/website-filters.node-test.ts`

Expected: 测试通过。

### Task 5: 完整验证

**Files:**
- Modify: `backend/tests/test_message_filter_helpers.py`
- Modify: `backend/tests/test_keyword_reply_queue.py`
- Modify: `frontend/filter-options.node-test.ts`
- Modify: `frontend/website-filters.node-test.ts`

**Step 1: Run backend verification**

Run: `python3 -m unittest backend.tests.test_message_filter_helpers backend.tests.test_keyword_reply_queue.OnMessageKeywordImagePriorityTestCase backend.tests.test_keyword_reply_queue.KeywordSearchMatchingTestCase`

Expected: PASS

**Step 2: Run frontend verification**

Run: `node --test frontend/website-filters.node-test.ts frontend/filter-options.node-test.ts`

Expected: PASS

**Step 3: Run build**

Run: `cd frontend && pnpm build`

Expected: exit 0
