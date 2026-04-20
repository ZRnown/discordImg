## 背景

用户要做三件事：

1. 清理会拖慢速度的冗余代码。
2. 在账号与规则的个人设置里新增一个开关。开启后，关键词命中并发送消息时，额外附带一张与客户来图最相似的商品图；关闭时保持原来的纯链接/纯文案流程。
3. 在以图搜图里新增“被略过的商品”历史。群里收到图片但最高相似度没有超过阈值时，记录这条消息和图片，方便回看。

## 现状

- 用户设置已经集中走 `user_settings` 表和 `/api/user/settings`。
- Discord 关键词与图片回复最终都走 `backend/bot.py` 的 `schedule_reply()` 发送链路。
- 以图搜图历史已有 `search_history` 表、接口和前端列表。
- 前端图搜上传链路已经改成直接传原始 `File`，这部分的 base64 重编码冗余会保留为已完成优化。

## 实现方案

### 1. 用户设置新增字段

在 `user_settings` 增加布尔字段：

- `keyword_reply_send_best_match_image`

同步更新：

- `backend/database.py`
- `backend/app.py`
- `frontend/components/accounts-view.tsx`

### 2. 关键词命中时附带最相似商品图

做法：

- 在图片识别流程里，把客户原图的临时文件路径和当前命中的商品信息放进 `match_context`。
- 在 `schedule_reply()` 的发图准备阶段统一处理“需要发送哪张图”。
- 当 `match_context.type == "image"` 且用户设置开启时：
  - 只对当前命中商品的候选图片做一次“哪张图最像查询图”的挑选；
  - 选中后只附带这一张；
  - 如果挑选失败，回退到原有图片发送逻辑，不让消息发送失败。

图片来源优先级：

1. 商品图集里命中的 `image_index`
2. 商品图集的已配置索引
3. 自定义上传图片 / 自定义 URL

优先先把“商品图集最相似图”做稳，避免对非本地图片做额外下载和重算。

### 3. 新增“被略过的商品”历史

新增表：

- `skipped_image_history`

记录字段至少包括：

- 查询图片路径
- 最高命中商品 ID
- 最高命中图片索引
- 最高相似度
- 用户阈值
- Discord 消息 ID / 频道 ID / 频道名 / 作者 ID / 作者名 / 文本内容
- 记录时间

触发条件：

- 群里图片识别完成，但没有任何结果超过当前用户阈值。

同步新增：

- `backend/database.py` CRUD
- `backend/app.py` 接口
- `frontend/app/api/skipped_image_history/**`
- `frontend/components/image-search-view.tsx` 新列表区块

### 4. 性能清理

本次只做安全且有直接收益的清理：

- 保留并补测试：图搜上传不再做 base64 编解码。
- 把发送图片时重复分支的图片收集逻辑提取成统一 helper，减少重复下载/判断路径。
- 如果模型预热有明显重复初始化入口，先做最小化收敛；如果会牵涉启动流程重构，就留在后续，不在这次冒险上线。

## 测试

后端：

- `backend/tests/test_keyword_reply_settings.py`
- 新增 `backend/tests/test_skipped_image_history.py`
- 新增或补充关键词图片回复相关测试

前端：

- 个人设置 UI 文本/字段存在性测试
- 以图搜图“被略过的商品”区块与接口路径测试
- 保留上传原始文件测试

## 验证与发布

1. 先跑本地测试。
2. 提交 git commit。
3. SSH 到 `38.247.142.131` 更新代码、安装依赖、构建前端、重启 PM2。
4. 服务器时区改成 `Asia/Shanghai` 并验证。
