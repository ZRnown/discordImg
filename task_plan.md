# Task Plan: 修复上传图片不显示问题

## Goal
解决用户上传本地图片后，重新打开编辑框时看不到已上传图片的问题。

## Current Status
**Phase:** 1 (调查中)

## Problem Summary
- ✅ 图片文件成功保存到 `data/custom_reply_images/304/`
- ✅ 数据库更新成功，包含 `uploaded_reply_images` 字段
- ❌ `get_full_product_data()` 返回的 `uploadedImages` 是空数组 `[]`

## Key Evidence
```
INFO - 保存了 2 张新的自定义回复图片到 data/custom_reply_images/304
INFO - 数据库更新完成，updates: dict_keys(['uploaded_reply_images', ...])
INFO - 返回给前端的uploadedImages: []
```

## Phases

### Phase 1: 调查 `_get_product_info_by_id` 函数 [in_progress]
**Goal:** 确认该函数是否返回 `uploaded_reply_images` 字段

**Actions:**
- [ ] 查找 `_get_product_info_by_id` 函数定义
- [ ] 检查 SQL 查询是否包含 `uploaded_reply_images` 列
- [ ] 添加调试日志查看返回的原始数据

**Expected Outcome:** 找到函数不返回该字段的原因

### Phase 2: 修复数据读取问题 [pending]
**Goal:** 确保 `_get_product_info_by_id` 正确返回 `uploaded_reply_images`

**Actions:**
- [ ] 修改 SQL 查询添加缺失的列
- [ ] 测试修复后的数据返回

### Phase 3: 验证完整流程 [pending]
**Goal:** 端到端测试上传图片功能

**Actions:**
- [ ] 上传新图片
- [ ] 保存并关闭编辑框
- [ ] 重新打开编辑框验证图片显示
- [ ] 测试机器人回复是否发送图片

## Errors Encountered
| Error | Phase | Resolution |
|-------|-------|------------|
| `uploadedImages` 返回空数组 | 1 | 调查中 |

## Files Modified
- `backend/app.py` - 添加调试日志
- `backend/database.py` - 添加 `uploadedImages` 解析逻辑

## Next Steps
1. 查找 `_get_product_info_by_id` 函数
2. 检查其 SQL 查询
3. 确认是否包含 `uploaded_reply_images` 字段
