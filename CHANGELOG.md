# 更新日志

## v1.5.0

### 新功能

- **Webhook 实时推送**：FiveM 端事件发生时主动 POST 到 AstrBot 插件，延迟 <1 秒，无需轮询
  - AstrBot 插件启动 HTTP 服务监听 Webhook（`webhook_enabled` / `webhook_port`）
  - FiveM Lua 端事件触发时自动 `PerformHttpRequest` 推送
  - 支持 Bearer Token 认证（`webhook_token` / `WebhookToken`）
  - Webhook 与轮询可共存，互不冲突

### 改进

- **纯群号自动转换**：`push_targets` 支持直接填写 QQ 群号，插件自动构造 UMO 并回写配置
- **事件格式化重构**：提取 `_format_event_lines` 和 `_process_and_broadcast_events` 公共方法，轮询与 Webhook 复用同一套格式化逻辑

### 修复

- **Webhook 默认端口**：从 6185 改为 5765，避免与 AstrBot Dashboard 端口冲突

## v1.4.0

### 改进

- **配置分组**：使用 `object` 嵌套将配置按模块分组（连接设置 / 推送设置 / 告警设置 / 权限设置），WebUI 体验更清晰
- **推送目标 WebUI 可配**：新增 `push_targets` 配置项（推送设置模块），可在 WebUI 直接管理推送目标
- **命令重命名**：`/fivem 绑定` → `/fivem 订阅`，`/fivem 解绑` → `/fivem 退订`，语义更清晰
- **新增 `/fivem 订阅列表`**：查看当前所有推送订阅目标
- **旧版迁移兼容**：自动将旧版扁平配置数据迁移到新的分组结构

## v1.3.0

### 新功能

- **txAdmin 事件集成**：自动推送管理员公告、服务器关闭、计划重启倒计时到 QQ 群
- **离线告警**：连续检测失败后自动告警，恢复后发送恢复通知
- **玩家上下线通知**：支持双事件系统（连接中 + 角色加载 + 断开连接）
- **定时推送**：定时推送服务器在线状态到绑定的 QQ 群
- **权限控制**：管理员 QQ 号白名单，限制管理指令权限
- **职业模糊匹配**：`/fivem 职业` 指令支持中文标签和模糊搜索

### 指令列表

- `/fivem 状态` — 查询在线人数与职业在线
- `/fivem 玩家` — 查询在线玩家列表
- `/fivem 职业 <关键词>` — 查询指定职业在线玩家
- `/fivem 检测` — 服务器健康检测
- `/fivem 绑定` — 绑定推送目标 🔒
- `/fivem 解绑` — 取消推送绑定 🔒
- `/fivem 帮助` — 显示帮助信息
