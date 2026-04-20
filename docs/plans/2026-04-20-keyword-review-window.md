# Keyword Review Window Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为网站的关键词回复增加人工审核窗口，支持按频道单独开关、批量审核、审核后按既有回复规则发送内容或链接。

**Architecture:** 在频道绑定表里增加审核开关，把“是否进入人工审核”绑定到实际监听入口。机器人在关键词命中后先落库到审核队列，前端从独立审核页拉取待审消息，审批后再由后端调度机器人发送，沿用现有回复内容生成和延迟逻辑。

**Tech Stack:** Flask + SQLite + discord.py-self + Next.js 16 + React 19 + shadcn/ui

---

### Task 1: 数据模型和后端审核队列

**Files:**
- Modify: `backend/database.py`
- Modify: `backend/app.py`
- Modify: `backend/bot.py`

**Step 1: Add failing coverage for the queue contract**

```python
def test_review_item_round_trip():
    ...
```

**Step 2: Add channel-level review toggle and review queue storage**
- `website_channel_bindings` 增加 `keyword_review_enabled`
- 新增 `keyword_reply_review_items` 表，保存消息、账号、位置、时间、回复内容和序列化负载

**Step 3: Expose APIs**
- `GET /api/websites` 返回频道审核开关
- `PUT /api/websites/<id>/channels/<channelId>/review-window` 更新开关
- `GET /api/keyword-review-items`
- `POST /api/keyword-review-items/bulk-action`

**Step 4: Verify**
- 启动后端，确认迁移可重复执行
- 确认新增接口返回预期字段

### Task 2: 机器人关键词回复拦截与审批发送

**Files:**
- Modify: `backend/bot.py`

**Step 1: Write the failing behavior check**
- 关键词命中且审核开关开启时，不直接发送
- 需要把待审记录写入数据库

**Step 2: Add queueing path**
- 在关键词发送出口拦截
- 记录账号、内容、发送者、位置、时间和完整 payload

**Step 3: Add approval dispatch path**
- 审核通过后从队列读取 payload
- 调度机器人按现有回复规则发送
- 审核拒绝只更新状态，不发消息

**Step 4: Verify**
- 手工触发关键词消息，确认只入队不发送
- 审核通过后确认消息能发出

### Task 3: 前端网站配置和审核窗口

**Files:**
- Modify: `frontend/components/accounts-view.tsx`
- Add: `frontend/components/review-window-view.tsx`
- Modify: `frontend/components/app-sidebar.tsx`
- Modify: `frontend/components/app-page-client.tsx`
- Add: `frontend/app/api/keyword-review-items/route.ts`
- Add: `frontend/app/api/keyword-review-items/[id]/bulk-action/route.ts`
- Add: `frontend/app/api/websites/[id]/channels/[channelId]/review-window/route.ts`

**Step 1: Add a failing UI smoke test or node test**
- 覆盖审核窗口开关字段和批量操作入口

**Step 2: Add the channel switch**
- 在网站配置下展示“关键词人工审核”开关
- 默认关闭，支持单频道单独开启/关闭

**Step 3: Add the review page**
- 列表展示账号、内容、发送者、位置、时间
- 支持全选、批量通过、批量拒绝

**Step 4: Verify**
- 页面能加载待审数据
- 批量操作后列表刷新

### Task 4: 测试与部署

**Files:**
- Add or modify tests under `backend/tests/` and `frontend/*.node-test.ts`

**Step 1: Cover the database helpers**
- 审核队列入库/查询/状态更新
- 频道审核开关更新

**Step 2: Cover the frontend helpers**
- 审核状态映射和批量选择逻辑

**Step 3: Run verification**
- `pytest`
- `pnpm lint`
- `pnpm test` for node tests if available in the repo shell

**Step 4: Deploy**
- 在代码通过验证后把变更发布到远程服务器

