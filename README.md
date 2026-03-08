# AstrBot FiveM 服务器状态插件

通过 QQ 查询 FiveM 服务器在线状态、职业人数等信息。

## 安装

将 `astrbot_plugin` 目录复制到 AstrBot 的 `data/plugins/astrbot_plugin_fivem` 目录下，然后在 WebUI 中重载插件。

## 配置

在 AstrBot WebUI 的插件管理中配置，按模块分组：

#### 连接设置
- **server_url** — FiveM 服务器状态 API 地址（如 `http://你的服务器IP:30120/fivem-server-status`）
- **timeout** — 请求超时秒数（默认 10）

#### 推送设置
- **auto_push_enabled** — 是否启用定时状态推送（默认关闭）
- **auto_push_interval** — 推送/轮询间隔秒数（默认 300，最小 60）
- **event_notify_enabled** — 是否启用事件通知：玩家动态 + txAdmin 事件（默认关闭）
- **push_targets** — 推送目标列表（可直接填写 QQ 群号，插件会自动转换；也可通过 `/fivem 订阅` 命令自动添加）
- **webhook_enabled** — 是否启用 Webhook 实时推送（默认关闭）
- **webhook_port** — Webhook 监听端口（默认 5765）
- **webhook_token** — Webhook 认证 Token（可选，留空不验证）

#### 告警设置
- **alert_enabled** — 是否启用离线告警（默认开启）
- **alert_threshold** — 连续检测失败多少次后触发告警（默认 3）

#### 权限设置
- **admin_ids** — 管理员 QQ 号列表（留空则所有人可用管理指令）

## 指令

| 指令 | 说明 |
|---|---|
| `/fivem 状态` | 查询在线人数与职业在线情况 |
| `/fivem 玩家` | 查询在线玩家列表 |
| `/fivem 职业 <关键词>` | 查询指定职业的在线玩家（支持中文/模糊匹配） |
| `/fivem 检测` | 服务器健康检测 |
| `/fivem 订阅` | 订阅当前会话接收推送/告警/事件通知 🔒 |
| `/fivem 退订` | 取消当前会话的推送订阅 🔒 |
| `/fivem 订阅列表` | 查看所有推送目标 🔒 |
| `/fivem 帮助` | 显示所有可用指令 |

> 🔒 = 需要管理员权限（`admin_ids` 配置）

## 输出示例

### /fivem 状态
```
🎮 FiveM 服务器状态
👥 在线人数: 32/64
📋 职业在线:
  • 执法队: 5 人
  • 急救组: 2 人
```

### /fivem 玩家
```
👥 在线玩家 (3 人):
  [1] Player1 — 执法队
  [2] Player2 — 急救组
  [3] Player3 — 执法队
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
  🟡 [5] NewPlayer 正在连接...
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

## Webhook 实时推送

默认的事件通知采用轮询模式（按 `auto_push_interval` 间隔拉取）。开启 Webhook 后，FiveM 端事件发生时会主动 POST 到 AstrBot 插件，延迟 <1 秒。

### 配置步骤

1. AstrBot WebUI → 推送设置 → 开启 **webhook_enabled**，设置端口和 Token
2. FiveM `config.lua` → 填写 `WebhookURL` 和 `WebhookToken`：
   ```lua
   WebhookURL = 'http://AstrBot所在IP:5765/webhook/fivem',
   WebhookToken = '你设置的Token',
   ```
3. 重启 FiveM 资源即可

> Webhook 与轮询可共存：Webhook 负责实时推送，轮询作为备用保障。也可单独使用 Webhook，关闭 `event_notify_enabled` 以避免重复推送。

## 依赖

- FiveM 服务端需部署 `fivem-server-status` 资源并开放 HTTP API
- AstrBot 所在服务器需能访问 FiveM 服务器的 HTTP 端口
- 使用 Webhook 时，FiveM 服务器需能访问 AstrBot 的 Webhook 端口
