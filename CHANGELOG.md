# 更新日志

## v1.13.0

### 新功能

- **服务器通知模板全面自定义**：四种服务器事件通知均支持 WebUI 自定义模板 + 占位符
  - `display.server_start_template` — 占位符: `{server_name}` `{time}` `{players}` `{max_players}` `{at_all}`
  - `display.shutdown_template` — 占位符: `{author}` `{delay}` `{message}` `{time}` `{at_all}`
  - `display.restart_template` — 占位符: `{minutes}` `{seconds}` `{time}` `{at_all}`
  - `display.alert_template` — 占位符: `{count}` `{at_all}`
- **@全体成员占位符**：在任意通知模板中加入 `{at_all}` 即可自动 @全体成员，不加则不 @，完全由模板文本控制
- **Lua 端 server_start 事件数据扩展**：新增 `maxPlayers` 和 `totalPlayers` 字段

## v1.12.0

### 新功能

- **服务器启动通知**：FiveM 资源加载完成后自动推送 `server_start` 事件到 QQ 群，服务器重启后第一时间收到通知
  - Lua 端 `CreateThread` 延迟 5 秒确保网络就绪后推送，同时支持 Webhook 实时推送和轮询两种通道
  - 无论 `alert_enabled` 是否开启、重启快慢，均能触发通知

### 改进

- **去除重复恢复通知**：移除离线告警恢复时的 "✅ FiveM 服务器已恢复在线。" 广播，由 Lua 端 `server_start` 事件统一承担恢复通知职责，避免重启后收到两条重复消息

## v1.11.0

### 新功能

- **远程管理（双向通道）**：从 QQ 直接操作游戏服务器，无需登录游戏或 txAdmin
  - `/fivem 公告 <内容>` — 发送全服通知公告到游戏内 🔒
  - `/fivem 广播 <内容>` — 发送聊天广播到游戏内 🔒
  - `/fivem 踢人 <ID或名称> [原因]` — 远程踢出指定玩家 🔒
  - Lua 端新增 `POST /admin/announce`、`/admin/broadcast`、`/admin/kick` 三个管理 API
  - 安全性：IP 白名单 + `AdminToken` 令牌双重认证
- **AI 自然语言查询**：利用 AstrBot LLM 框架，用户可用自然语言提问而无需记忆命令
  - 注册 6 个 LLM 工具：服务器状态、玩家列表、职业查询、玩家搜索、趋势图、健康检测
  - 示例："现在警察几个人在线？"、"帮我看看服务器状态"、"张三在不在线？"
  - 需要 AstrBot 已配置 LLM 供应商（如 OpenAI / 通义千问等）

### 改进

- **趋势图逻辑抽取**：提取 `_build_trend_data()` 公共方法，命令与 LLM 工具复用同一套趋势数据构建逻辑
- **配置新增** `connection.admin_token`：远程管理令牌，需与 FiveM 端 `AdminToken` 一致
- **帮助信息更新**：新增「远程管理命令」分组展示

## v1.10.0

### 新功能

- **自定义事件钩子**：Lua 端通过 `exports('pushEvent', ...)` 导出事件推送接口，其他 FiveM 资源可调用 `exports['fivem-server-status']:pushEvent({ type = 'custom', title = '...', message = '...' })` 向 QQ 群推送自定义通知
- **命令冷却 / 频率限制**：新增 `command_cooldown` 配置项（默认 5 秒），防止普通用户刷屏；管理员不受限制

### 改进

- **状态模板数据构建抽取**：提取 `_build_status_tmpl_data()` 消除 `_push_loop` 与 `server_status` 命令中的重复代码
- **趋势数据采集独立于订阅**：定时循环启动不再依赖 `_push_targets`，即使无订阅者也会采集历史数据

## v1.9.1

### 改进

- **在线时长改用 ESX 内置 API**：移除自定义 `_JoinTime` 表，改用 `xPlayer.getPlayTime()` 获取当前会话在线秒数，更准确且无需手动维护
- **修复 playerConnecting 事件 ID 为 65536 的问题**：`playerConnecting` 阶段 `source` 始终为 65536，现已移除该 ID 字段，连接事件仅显示玩家名称
- **事件格式化统一**：`join`/`leave` 事件改用可选 `id_tag`，ID 缺失时优雅降级

## v1.9.0

### 新功能

- **在线时长统计**：玩家列表新增「时长」列，显示每位玩家已在线多久（Lua 端记录加入时间戳）
- **定时推送图片化**：定时状态推送复用 `TMPL_STATUS` 渲染图片卡片，与查询指令视觉保持一致
- **在线趋势图** `/fivem 趋势`：基于历史数据（24 小时自动采集）生成 SVG 折线图，展示当前/峰值/均值统计

### 改进

- 广播方法重构：拆分 `_broadcast` / `_broadcast_chain` / `_broadcast_image`，支持文本与图片两种广播模式

## v1.8.1

### 修复

- **uptime 计算修正**：Lua 端 `os.clock()` 返回 CPU 时间而非挂钟时间，改为 `os.time() - _StartTime` 确保 uptime 准确
- **事件缓冲区滞留修复**：`_flush_events` 在 `_send_events` 网络 IO 期间到达的新事件可能被滞留，改为 `while` 循环处理
- **代码清理**：移除未使用的 `import time`

## v1.8.0

### 新功能

- **玩家搜索** `/fivem 查找 <名>`：模糊匹配在线玩家名称，快速查找特定玩家是否在线
- **事件聚合降噪**：多人同时上下线时，等待缓冲窗口（默认 10 秒）后合并为一条消息发送，减少群内刷屏；新增 `event_buffer_seconds` 配置项
- **服务器信息增强**：状态卡片展示服务器名称（`sv_hostname`）和运行时长（`uptime`），一目了然

## v1.7.2

### 优化

- **模板视觉重设计**：全新绿色渐变 header 横幅 + GitHub Dark 配色方案，提升视觉层次
- **字号全面加大**：标题 26px、正文 18px、数值 30px，QQ 群内阅读更清晰
- **图片高度自适应**：内容自动决定图片大小，无多余空白

## v1.7.1

### 修复

- **图片卡片渲染布局修复**：添加 viewport meta 和 `viewport_width` 选项，解决 Playwright 默认 1280px 视口导致卡片缩小的问题
- **卡片填满视口**：移除 body 外边距和 card 圆角/边框，内容区与图片大小完全一致，无多余空白

## v1.7.0

### 新功能

- **图片卡片渲染**：查询类命令（状态/玩家/职业/自检/帮助）的回复渲染为精美深色风格图片卡片，提升 QQ 群内展示效果
  - 使用 AstrBot 内置 `html_render`（HTML + Jinja2）实现，无额外依赖
  - 新增 `display.render_image` 配置项，可在 WebUI 关闭图片渲染回退纯文本
  - 渲染失败时自动降级为纯文本，保证可用性
- **新增模板文件** `templates.py`：包含 5 套 HTML 卡片模板（状态/玩家/职业/自检/帮助）

## v1.6.0

### 新功能

- **新增 `/fivem 自检`**：管理员可快速检查 FiveM API、Webhook、订阅状态、后台任务与关键配置是否正常

### 改进

- **事件通知粒度控制**：新增 `notify_player_events` 与 `notify_server_events`，可分别控制玩家动态与服务器通知
- **订阅列表可读性优化**：订阅目标优先显示为友好的 QQ 群 / 私聊格式，并保留原始 UMO 便于排障
- **管理员帮助信息优化**：帮助命令按查询类与管理员类分组展示，降低上手成本
- **订阅反馈增强**：订阅 / 退订后会显示当前订阅总数，便于管理员确认配置状态

## v1.5.0

### 新功能

- **Webhook 实时推送**：FiveM 端事件发生时主动 POST 到 AstrBot 插件，延迟 <1 秒，无需轮询
  - AstrBot 插件启动 HTTP 服务监听 Webhook（`webhook_enabled` / `webhook_port`）
  - FiveM Lua 端事件触发时自动 `PerformHttpRequest` 推送
  - 支持 Bearer Token 认证（`webhook_token` / `WebhookToken`）
  - 启用 Webhook 后，事件通知不再轮询 `/events`；定时状态推送与离线告警仍可继续工作

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
