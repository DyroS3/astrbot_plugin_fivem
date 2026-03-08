# AstrBot FiveM 服务器状态插件

通过 QQ 查询和管理 FiveM 服务器，支持远程管理与 AI 自然语言查询。

本插件需要配合 FiveM 端 `fivem-server-status` 资源一起使用，兼容当前配套版本 `v1.14.1`。

## 架构与依赖关系

- FiveM 端负责提供 `/status`、`/players`、`/job/:name`、`/events`、`/health` 等查询 API，以及 `/admin/*` 管理 API
- AstrBot 端负责 QQ 指令、定时推送、离线告警、订阅管理、Webhook 接收、远程管理与 AI 工具注册
- 如启用 Webhook，FiveM 会主动向 AstrBot 发送事件通知；否则由 AstrBot 定时轮询 `/events`

## 安装

1. 先在 FiveM 服务端部署配套 `fivem-server-status` 资源，并确认 `/health` 与 `/status` 可访问
2. 将 `astrbot_plugin` 目录复制到 AstrBot 的 `data/plugins/astrbot_plugin_fivem` 目录下
3. 在 AstrBot WebUI 中重载插件并填写配置

## 配置

在 AstrBot WebUI 的插件管理中配置，按模块分组：

#### 连接设置
- **server_url** — FiveM 服务器状态 API 地址（如 `http://你的服务器IP:30120/fivem-server-status`）
- **timeout** — 请求超时秒数（默认 10）
- **admin_token** — 远程管理令牌（需与 FiveM 端 `config.lua` 的 `AdminToken` 一致；留空则禁用远程管理功能）

#### 推送设置
- **auto_push_enabled** — 是否启用定时状态推送（默认关闭）
- **auto_push_interval** — 定时状态推送 / 事件轮询间隔秒数（默认 300，最小 60）
- **event_notify_enabled** — 事件通知总开关：玩家动态 + txAdmin 事件（默认关闭）
- **notify_player_events** — 是否推送玩家动态（连接 / 加入 / 离开）
- **notify_server_events** — 是否推送服务器通知（txAdmin 公告 / 关服 / 重启 / 启动）
- **push_targets** — 推送目标列表（可直接填写 QQ 群号，插件会自动转换；也可通过 `/fivem 订阅` 命令自动添加）
- **webhook_enabled** — 是否启用 Webhook 实时推送（默认关闭；开启后事件通知改为实时推送，不再轮询）
- **webhook_port** — Webhook 监听端口（默认 5765）
- **webhook_token** — Webhook 认证 Token（可选，留空不验证）
- **event_buffer_seconds** — 事件聚合窗口秒数（默认 10；多人同时上下线时合并为一条消息，设 0 则立即发送）

#### 显示设置
- **render_image** — 查询类命令回复是否渲染为图片卡片（默认开启；需 AstrBot 内置 Playwright 可用，关闭后回退纯文本）
- **server_start_template** — 服务器启动通知模板（占位符: `{server_name}` `{time}` `{players}` `{max_players}` `{at_all}`）
- **shutdown_template** — 服务器关闭通知模板（占位符: `{author}` `{delay}` `{message}` `{time}` `{at_all}`）
- **restart_template** — 计划重启通知模板（占位符: `{minutes}` `{seconds}` `{time}` `{at_all}`）
- **alert_template** — 离线告警通知模板（占位符: `{count}` `{at_all}`）

> 💡 在任意模板中加入 `{at_all}` 占位符即可自动 @全体成员，不加则不 @。

#### 告警设置
- **alert_enabled** — 是否启用离线告警（默认开启）
- **alert_threshold** — 连续检测失败多少次后触发告警（默认 3）

#### 权限设置
- **admin_ids** — 管理员 QQ 号列表（留空则所有人可用管理指令）
- **command_cooldown** — 普通用户命令冷却秒数（默认 5，设 0 不限制；管理员豁免）

## 指令

| 指令 | 说明 |
|---|---|
| `/fivem 状态` | 查询在线人数、职业在线、服务器名称与运行时长 |
| `/fivem 玩家` | 查询在线玩家列表（含在线时长） |
| `/fivem 职业 <关键词>` | 查询指定职业的在线玩家（支持中文/模糊匹配） |
| `/fivem 查找 <名>` | 模糊搜索在线玩家 |
| `/fivem 趋势` | 24 小时在线人数趋势图 |
| `/fivem 检测` | 服务器健康检测 |
| `/fivem 自检` | 检查 API、Webhook、订阅与通知配置 🔒 |
| `/fivem 订阅` | 订阅当前会话接收推送/告警/事件通知 🔒 |
| `/fivem 退订` | 取消当前会话的推送订阅 🔒 |
| `/fivem 订阅列表` | 查看所有推送目标 🔒 |
| `/fivem 公告 <内容>` | 发送全服公告到游戏内 🔒 |
| `/fivem 广播 <内容>` | 发送聊天广播到游戏内 🔒 |
| `/fivem 踢人 <目标> [原因]` | 远程踢出游戏内玩家 🔒 |
| `/fivem 帮助` | 显示所有可用指令 |

> 🔒 = 需要管理员权限（`admin_ids` 配置）
> 远程管理命令还需配置 `admin_token`

## 输出示例

### /fivem 状态
```
🎮 FiveM 服务器状态
🏷️ My RP Server
👥 在线人数: 32/64
⏱️ 运行时长: 2 天 5 小时
📋 职业在线:
  • 执法队: 5 人
  • 急救组: 2 人
```

### /fivem 玩家
```
👥 在线玩家 (3 人):
  [1] Player1 — 执法队 (2 小时 30 分钟)
  [2] Player2 — 急救组 (45 分钟)
  [3] Player3 — 执法队 (10 分钟)
```

### /fivem 职业 执法队
```
👔 执法队 (2 人在线):
  [1] Player1
  [3] Player3
```

> 也可以输入 `/fivem 职业 执法`、`/fivem 职业 police` 等，支持模糊匹配。

### 玩家动态通知（自动推送）
```
📡 玩家动态 (3 条):
  🟡 NewPlayer 正在连接...
  🟢 [5] NewPlayer [执法队] 加入了服务器
  🔴 [2] Player2 [急救组] 离开了服务器 (Quit)
```

### txAdmin 服务器通知（自动推送）
```
🖥️ 服务器通知 (2 条):
  📢 管理员公告 (Admin): 服务器将于 22:00 维护
  ⏰ 计划重启: 剩余 5 分钟
```

> 支持的 txAdmin 事件：管理员公告、服务器关闭、计划重启倒计时。

### 服务器启动通知（自动推送）
```
🖥️ 服务器通知 (1 条):
  ✅ 服务器已启动: My RP Server
```

> 服务器重启或资源加载完成后自动推送，无需等待离线告警阈值。

## 自定义事件钩子

其他 FiveM 资源可通过 `exports` 向 QQ 群推送自定义通知：

```lua
-- 在你的 FiveM 资源中调用
exports['fivem-server-status']:pushEvent({
    type = 'custom',     -- 可选，不填默认 'custom'
    title = '银行抢劫',   -- 通知标题
    message = '抢劫已开始' -- 通知内容（可选）
})
```

群内显示效果：`🔔 银行抢劫: 抢劫已开始`

> 自定义事件归类为服务器通知，受 `notify_server_events` 开关控制。需同时开启 `event_notify_enabled` 和 `notify_server_events` 才能接收。

## Webhook 实时推送

默认的事件通知采用轮询模式（按 `auto_push_interval` 间隔拉取）。开启 Webhook 后，FiveM 端事件发生时会主动 POST 到 AstrBot 插件，延迟 <1 秒；此时插件不再轮询 `/events`，以避免重复推送。

如果你希望减少群消息噪声，可以只开启以下其中一类：

- `notify_player_events`：只推送玩家动态
- `notify_server_events`：只推送服务器通知

### 配置步骤

1. AstrBot WebUI → 推送设置 → 开启 **event_notify_enabled** 与 **webhook_enabled**，设置端口和 Token
2. FiveM `config.lua` → 填写 `WebhookURL` 和 `WebhookToken`：
   ```lua
   WebhookURL = 'http://AstrBot所在IP:5765/webhook/fivem',
   WebhookToken = '你设置的Token',
   ```
3. 重启 FiveM 资源即可

> `event_notify_enabled` 是事件通知总开关；`webhook_enabled` 是事件通知的实时传输模式。开启 Webhook 后，插件不会再轮询事件队列。

## 快速验证

建议首次部署后按以下顺序验证：

1. 直接访问 FiveM `/health`，确认返回 `{"status":"ok"}`
2. 直接访问 FiveM `/status`，确认返回带 `success = true` 的 JSON
3. 在 QQ 中执行 `/fivem 状态`
4. 管理员在目标群执行 `/fivem 自检`
5. 在目标群执行 `/fivem 订阅`
6. 触发玩家上下线或 txAdmin 事件，确认群内收到推送

## 常见排障

### `/fivem 状态` 提示无法连接到 FiveM 服务器

优先检查：

- `connection.server_url` 是否填写正确
- AstrBot 所在机器是否能访问 FiveM HTTP 端口
- FiveM 资源是否已成功加载
- FiveM `/health` 与 `/status` 是否可直接访问

### 访问 FiveM `/status` 返回 403

通常说明 `WhitelistIPs` 未包含当前来源 IP。需要检查：

- AstrBot 所在机器的出口 IP
- 是否经过反向代理
- 代理是否正确传递 `X-Forwarded-For` 或 `X-Real-IP`

### 开启 Webhook 后没有收到事件推送

优先检查：

- `event_notify_enabled` 是否开启
- `webhook_enabled` 是否开启
- FiveM `WebhookURL` 是否能访问到 AstrBot
- `webhook_token` 与 `WebhookToken` 是否一致
- Webhook 监听端口是否已放行

### 已订阅但没有收到消息

优先检查：

- 当前会话是否真的执行成功 `/fivem 订阅`
- `push_targets` 是否已保存
- 管理员权限是否限制了订阅操作
- 当前是否实际触发了推送条件（定时推送 / 告警 / 事件通知）

## 远程管理（双向通道）

从 QQ 直接操作游戏服务器，无需登录游戏或 txAdmin 面板：

### 配置步骤

1. FiveM `config.lua` → 设置 `AdminToken`（自定义一个安全令牌）：
   ```lua
   AdminToken = '你的安全令牌',
   ```
2. AstrBot WebUI → 连接设置 → 填写相同的 **admin_token**
3. 重启 FiveM 资源即可

### 使用示例
```
/fivem 公告 服务器将于 22:00 维护
/fivem 广播 欢迎新玩家
/fivem 踢人 3 违反规则
/fivem 踢人 张三 AFK过久
```

> 踢人命令支持玩家 ID 或名称模糊匹配。

## AI 自然语言查询

插件注册了 6 个 LLM 工具，用户可用自然语言提问，AstrBot 的 LLM 会自动调用对应工具：

| 自然语言示例 | 自动调用的工具 |
|---|---|
| "服务器现在多少人？" | `fivem_server_status` |
| "在线玩家有哪些？" | `fivem_player_list` |
| "现在警察几个人在线？" | `fivem_job_query` |
| "张三在不在线？" | `fivem_player_search` |
| "今天在线趋势怎么样？" | `fivem_trend` |

> 需要 AstrBot 已配置 LLM 供应商（如 OpenAI / 通义千问 / DeepSeek 等），且用户消息经过 LLM 处理管道。

## 依赖

- FiveM 服务端需部署 `fivem-server-status` 资源并开放 HTTP API
- AstrBot 所在服务器需能访问 FiveM 服务器的 HTTP 端口
- 使用 Webhook 时，FiveM 服务器需能访问 AstrBot 的 Webhook 端口
- 使用 AI 自然语言查询时，需配置 LLM 供应商
