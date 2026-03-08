import asyncio

import aiohttp
from aiohttp import web

from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig
from astrbot.core.star.star_tools import StarTools


@register("astrbot_plugin_fivem", "DingYu", "通过 QQ 查询 FiveM 服务器在线状态", "1.5.0")
class FiveMStatusPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

        # ── 读取分组配置 ──
        conn = config.get("connection", {})
        push = config.get("push", {})
        alert = config.get("alert", {})
        perm = config.get("permission", {})

        self.server_url = conn.get("server_url", "http://127.0.0.1:30120/fivem-server-status")
        self.timeout = conn.get("timeout", 10)
        self.auto_push_enabled = push.get("auto_push_enabled", False)
        self.auto_push_interval = max(push.get("auto_push_interval", 300), 60)
        self.event_notify_enabled = push.get("event_notify_enabled", False)
        self.alert_enabled = alert.get("alert_enabled", True)
        self.alert_threshold = max(alert.get("alert_threshold", 3), 1)
        self.admin_ids: list[str] = [str(aid) for aid in perm.get("admin_ids", [])]

        self.webhook_enabled = push.get("webhook_enabled", False)
        self.webhook_port = push.get("webhook_port", 5765)
        self.webhook_token = push.get("webhook_token", "")

        self._push_task: asyncio.Task | None = None
        self._push_targets: set[str] = set()
        self._fail_count = 0
        self._alerted = False
        self._session: aiohttp.ClientSession | None = None
        self._webhook_runner: web.AppRunner | None = None
        self._load_push_targets()

    # ── 推送目标持久化 ──

    def _load_push_targets(self):
        """从配置中读取推送目标，兼容旧版扁平字段迁移"""
        targets = set()
        push = self.config.get("push", {})
        if isinstance(push, dict):
            saved = push.get("push_targets", [])
            if isinstance(saved, list):
                targets.update(saved)
        # 兼容旧版扁平字段，迁移后清除
        for old_key in ("_push_targets", "push_targets"):
            old = self.config.get(old_key, [])
            if isinstance(old, list) and old:
                targets.update(old)
                self.config[old_key] = []
                logger.info(f"FiveM 插件：已从旧版 {old_key} 迁移 {len(old)} 个推送目标")
        if targets:
            self._ensure_push_dict()
            self.config["push"]["push_targets"] = list(targets)
            self.config.save_config()
        self._push_targets = targets

    def _ensure_push_dict(self):
        """确保 config['push'] 是 dict"""
        if not isinstance(self.config.get("push"), dict):
            self.config["push"] = {}

    def _save_push_targets(self):
        """将推送目标持久化到配置"""
        self._ensure_push_dict()
        self.config["push"]["push_targets"] = list(self._push_targets)
        self.config.save_config()

    # ── 生命周期 ──

    def _needs_loop(self) -> bool:
        """是否需要启动定时循环"""
        return self.auto_push_enabled or self.alert_enabled or self.event_notify_enabled

    async def initialize(self):
        """插件初始化，启动定时任务和 Webhook 服务"""
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.timeout)
        )
        if self._push_targets and self._needs_loop():
            self._start_push_loop()
        if self.webhook_enabled:
            await self._start_webhook_server()

    async def terminate(self):
        """插件卸载，停止所有后台服务"""
        self._stop_push_loop()
        await self._stop_webhook_server()
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    # ── 权限校验 ──

    def _is_admin(self, event: AstrMessageEvent) -> bool:
        """检查发送者是否为管理员，admin_ids 为空时允许所有人"""
        if not self.admin_ids:
            return True
        return str(event.get_sender_id()) in self.admin_ids

    # ── HTTP 请求 ──

    async def _request(self, path: str) -> dict | None:
        """向 FiveM 服务器状态 API 发起 GET 请求"""
        url = f"{self.server_url.rstrip('/')}{path}"
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )
        try:
            async with self._session.get(url) as resp:
                if resp.status != 200:
                    logger.warning(f"FiveM API 返回 HTTP {resp.status}: {url}")
                    return None
                return await resp.json()
        except aiohttp.ClientError as e:
            logger.error(f"FiveM API 请求失败: {e}")
            return None
        except Exception as e:
            logger.error(f"FiveM API 未知错误: {e}")
            return None

    # ── 状态文本格式化 ──

    def _format_status(self, data: dict) -> str:
        """将 /status API 响应格式化为可读文本"""
        status = data["data"]
        total = status.get("totalPlayers", 0)
        max_players = status.get("maxPlayers", 0)

        lines = [
            f"🎮 FiveM 服务器状态",
            f"👥 在线人数: {total}/{max_players}",
        ]

        jobs = status.get("jobs", [])
        if jobs:
            lines.append("📋 职业在线:")
            for job in jobs:
                name = job.get("label", job.get("name", "未知"))
                online = job.get("online", 0)
                lines.append(f"  • {name}: {online} 人")

        return "\n".join(lines)

    # ── 定时推送 ──

    def _start_push_loop(self):
        """启动定时推送循环"""
        if self._push_task is not None:
            return
        self._push_task = asyncio.create_task(self._push_loop())
        logger.info(f"FiveM 定时推送已启动，间隔 {self.auto_push_interval} 秒")

    def _stop_push_loop(self):
        """停止定时推送循环"""
        if self._push_task is not None:
            self._push_task.cancel()
            self._push_task = None
            logger.info("FiveM 定时推送已停止")

    async def _push_loop(self):
        """定时推送 + 离线告警主循环"""
        try:
            while True:
                await asyncio.sleep(self.auto_push_interval)
                if not self._push_targets:
                    continue

                data = await self._request("/status")
                ok = data is not None and data.get("success")

                # ── 离线告警逻辑 ──
                if self.alert_enabled:
                    if not ok:
                        self._fail_count += 1
                        if self._fail_count >= self.alert_threshold and not self._alerted:
                            self._alerted = True
                            await self._broadcast(
                                f"🚨 FiveM 服务器离线告警\n"
                                f"连续 {self._fail_count} 次检测失败，服务器可能已离线！"
                            )
                        continue
                    else:
                        if self._alerted:
                            self._alerted = False
                            await self._broadcast("✅ FiveM 服务器已恢复在线。")
                        self._fail_count = 0

                # ── 定时推送 ──
                if self.auto_push_enabled and ok:
                    text = self._format_status(data)
                    await self._broadcast(text)

                # ── 玩家上下线事件通知 ──
                if self.event_notify_enabled and ok:
                    await self._poll_events()
        except asyncio.CancelledError:
            pass

    async def _poll_events(self):
        """轮询 /events 端点，有新事件时推送通知"""
        data = await self._request("/events")
        if data is None or not data.get("success"):
            return

        events = data.get("data", [])
        if events:
            await self._process_and_broadcast_events(events)

    def _format_event_lines(self, events: list[dict]) -> tuple[list[str], list[str]]:
        """将事件列表格式化为 (player_lines, server_lines)"""
        player_lines = []
        server_lines = []
        for ev in events:
            etype = ev.get("type")

            # ── 玩家事件 ──
            if etype in ("connecting", "join", "leave"):
                name = ev.get("name", "未知")
                pid = ev.get("id", "?")
                job_label = ev.get("jobLabel", "")
                job_suffix = f" [{job_label}]" if job_label else ""
                if etype == "connecting":
                    player_lines.append(f"  🟡 [{pid}] {name} 正在连接...")
                elif etype == "join":
                    player_lines.append(f"  🟢 [{pid}] {name}{job_suffix} 加入了服务器")
                elif etype == "leave":
                    reason = ev.get("reason", "")
                    reason_suffix = f" ({reason})" if reason else ""
                    player_lines.append(f"  🔴 [{pid}] {name}{job_suffix} 离开了服务器{reason_suffix}")

            # ── txAdmin 服务器事件 ──
            elif etype == "announcement":
                author = ev.get("author", "txAdmin")
                message = ev.get("message", "")
                server_lines.append(f"  📢 管理员公告 ({author}): {message}")
            elif etype == "shutdown":
                author = ev.get("author", "txAdmin")
                delay = ev.get("delay", 0)
                message = ev.get("message", "")
                delay_sec = round(delay / 1000) if delay else 0
                msg = f"  🔴 服务器即将关闭 ({author}, {delay_sec}秒后)"
                if message:
                    msg += f": {message}"
                server_lines.append(msg)
            elif etype == "restart":
                seconds = ev.get("secondsRemaining", 0)
                minutes = round(seconds / 60)
                server_lines.append(f"  ⏰ 计划重启: 剩余 {minutes} 分钟")

        return player_lines, server_lines

    async def _process_and_broadcast_events(self, events: list[dict]):
        """格式化事件并广播到所有推送目标"""
        player_lines, server_lines = self._format_event_lines(events)
        if server_lines:
            text = f"🖥️ 服务器通知 ({len(server_lines)} 条):\n" + "\n".join(server_lines)
            await self._broadcast(text)
        if player_lines:
            text = f"📡 玩家动态 ({len(player_lines)} 条):\n" + "\n".join(player_lines)
            await self._broadcast(text)

    # ── Webhook 服务 ──

    async def _start_webhook_server(self):
        """启动 Webhook HTTP 服务器，接收 FiveM 实时事件推送"""
        app = web.Application()
        app.router.add_post('/webhook/fivem', self._handle_webhook)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', self.webhook_port)
        await site.start()
        self._webhook_runner = runner
        logger.info(f"FiveM Webhook 服务已启动，监听 0.0.0.0:{self.webhook_port}")

    async def _stop_webhook_server(self):
        """停止 Webhook HTTP 服务器"""
        if self._webhook_runner:
            await self._webhook_runner.cleanup()
            self._webhook_runner = None
            logger.info("FiveM Webhook 服务已停止")

    async def _handle_webhook(self, request: web.Request) -> web.Response:
        """处理来自 FiveM 的 Webhook POST 请求"""
        if self.webhook_token:
            token = request.headers.get('Authorization', '').removeprefix('Bearer ')
            if token != self.webhook_token:
                return web.json_response({"error": "unauthorized"}, status=401)

        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json"}, status=400)

        events = data if isinstance(data, list) else [data]

        if not events or not self._push_targets:
            return web.json_response({"ok": True, "pushed": 0})

        await self._process_and_broadcast_events(events)
        return web.json_response({"ok": True, "pushed": len(events)})

    def _resolve_target(self, target: str) -> str:
        """将纯群号解析为完整 UMO 格式，已是 UMO 则直接返回"""
        if ":" in target:
            return target
        if not target.strip().isdigit():
            return target
        try:
            platforms = self.context.platform_manager.get_insts()
            if platforms:
                pid = platforms[0].meta().id
                return f"{pid}:GroupMessage:{target.strip()}"
        except Exception as e:
            logger.warning(f"FiveM 插件：无法为群号 {target} 构造 UMO: {e}")
        return target

    async def _broadcast(self, text: str):
        """向所有绑定会话发送消息，支持纯群号自动转换"""
        chain = MessageChain().message(text)
        resolved_targets: set[str] = set()
        need_save = False

        for target in list(self._push_targets):
            umo = self._resolve_target(target)
            resolved_targets.add(umo)
            if umo != target:
                need_save = True
            try:
                await self.context.send_message(umo, chain)
            except Exception as e:
                logger.error(f"消息发送失败 ({umo}): {e}")

        if need_save:
            self._push_targets = resolved_targets
            self._save_push_targets()
            logger.info(f"FiveM 插件：已将纯群号自动转换为 UMO 并回写配置")

    # ── 指令组 /fivem ──

    @filter.command_group("fivem")
    def fivem(self):
        pass

    @fivem.command("状态")
    async def server_status(self, event: AstrMessageEvent):
        """查询服务器在线状态与职业人数"""
        data = await self._request("/status")
        if data is None:
            yield event.plain_result("❌ 无法连接到 FiveM 服务器，请稍后重试。")
            return

        if not data.get("success"):
            yield event.plain_result("❌ 服务器返回异常数据。")
            return

        yield event.plain_result(self._format_status(data))

    @fivem.command("玩家")
    async def players_list(self, event: AstrMessageEvent):
        """查询在线玩家列表"""
        data = await self._request("/players")
        if data is None:
            yield event.plain_result("❌ 无法连接到 FiveM 服务器，请稍后重试。")
            return

        if not data.get("success"):
            yield event.plain_result("❌ 服务器返回异常数据。")
            return

        players = data["data"]
        if not players:
            yield event.plain_result("当前没有玩家在线。")
            return

        lines = [f"👥 在线玩家 ({len(players)} 人):"]
        for p in players:
            pid = p.get("id", "?")
            name = p.get("name", "未知")
            job_label = p.get("jobLabel", p.get("job", ""))
            lines.append(f"  [{pid}] {name} — {job_label}")

        yield event.plain_result("\n".join(lines))

    async def _resolve_job_name(self, keyword: str) -> tuple[str | None, str | None]:
        """将用户输入的关键词模糊匹配到实际 job name。

        匹配规则：精确匹配 name/label > label 包含关键词 > name 包含关键词。
        返回 (job_name, error_message)，成功时 error_message 为 None。
        """
        status_data = await self._request("/status")
        if status_data is None or not status_data.get("success"):
            return None, "❌ 无法连接到 FiveM 服务器，请稍后重试。"

        jobs = status_data.get("data", {}).get("jobs", [])
        if not jobs:
            return None, "❌ 当前没有已配置的职业。"

        kw = keyword.lower()

        # 精确匹配（name 或 label）
        for j in jobs:
            if kw == j["name"].lower() or kw == j["label"].lower():
                return j["name"], None

        # 模糊匹配（label 或 name 包含关键词）
        matches = [
            j for j in jobs
            if kw in j["label"].lower() or kw in j["name"].lower()
        ]

        if len(matches) == 1:
            return matches[0]["name"], None

        if len(matches) > 1:
            options = "\n".join(f"  • {m['label']}（{m['name']}）" for m in matches)
            return None, f"⚠️ 匹配到多个职业，请更精确地输入:\n{options}"

        # 无匹配 → 列出所有可用职业
        all_jobs = "\n".join(f"  • {j['label']}（{j['name']}）" for j in jobs)
        return None, f"❌ 未找到匹配「{keyword}」的职业。可用职业:\n{all_jobs}"

    @fivem.command("职业")
    async def job_query(self, event: AstrMessageEvent, job_name: str):
        """查询指定职业的在线玩家（用法: /fivem 职业 执法队）"""
        resolved, err = await self._resolve_job_name(job_name)
        if err:
            yield event.plain_result(err)
            return

        data = await self._request(f"/job/{resolved}")
        if data is None:
            yield event.plain_result("❌ 无法连接到 FiveM 服务器，请稍后重试。")
            return

        if not data.get("success"):
            yield event.plain_result("❌ 服务器返回异常数据。")
            return

        job = data["data"]
        label = job.get("label", job.get("name", job_name))
        online = job.get("online", 0)
        players = job.get("players", [])

        lines = [f"👔 {label} ({online} 人在线):"]
        if players:
            for p in players:
                pid = p.get("id", "?")
                name = p.get("name", "未知")
                lines.append(f"  [{pid}] {name}")
        else:
            lines.append("  当前无人在线")

        yield event.plain_result("\n".join(lines))

    @fivem.command("检测")
    async def health_check(self, event: AstrMessageEvent):
        """服务器健康检测"""
        data = await self._request("/health")
        if data is None:
            yield event.plain_result("❌ FiveM 服务器不可达。")
            return

        if data.get("status") == "ok":
            yield event.plain_result("✅ FiveM 服务器运行正常。")
        else:
            yield event.plain_result(f"⚠️ FiveM 服务器状态异常: {data}")

    @fivem.command("订阅")
    async def subscribe_push(self, event: AstrMessageEvent):
        """订阅当前会话接收推送/告警/事件通知（需管理员权限）"""
        if not self._is_admin(event):
            yield event.plain_result("🚫 权限不足，仅管理员可执行此操作。")
            return

        umo = event.unified_msg_origin
        if umo in self._push_targets:
            yield event.plain_result("ℹ️ 当前会话已订阅推送。")
            return

        self._push_targets.add(umo)
        self._save_push_targets()

        if self._needs_loop():
            self._start_push_loop()

        yield event.plain_result("✅ 已订阅当前会话，将接收推送/告警/事件通知。")

    @fivem.command("退订")
    async def unsubscribe_push(self, event: AstrMessageEvent):
        """取消当前会话的推送订阅（需管理员权限）"""
        if not self._is_admin(event):
            yield event.plain_result("🚫 权限不足，仅管理员可执行此操作。")
            return

        umo = event.unified_msg_origin
        if umo not in self._push_targets:
            yield event.plain_result("ℹ️ 当前会话未订阅推送。")
            return

        self._push_targets.discard(umo)
        self._save_push_targets()

        if not self._push_targets:
            self._stop_push_loop()

        yield event.plain_result("✅ 已取消当前会话的推送订阅。")

    @fivem.command("订阅列表")
    async def list_subscriptions(self, event: AstrMessageEvent):
        """查看当前所有推送订阅目标（需管理员权限）"""
        if not self._is_admin(event):
            yield event.plain_result("🚫 权限不足，仅管理员可执行此操作。")
            return

        if not self._push_targets:
            yield event.plain_result("ℹ️ 当前没有任何推送订阅。\n提示：可通过 /fivem 订阅 添加，或在 WebUI 配置 push_targets。")
            return

        lines = [f"📬 推送订阅列表 ({len(self._push_targets)} 个):"]
        for i, target in enumerate(sorted(self._push_targets), 1):
            lines.append(f"  {i}. {target}")
        yield event.plain_result("\n".join(lines))

    @fivem.command("帮助")
    async def show_help(self, event: AstrMessageEvent):
        """显示所有可用指令"""
        lines = [
            "📖 FiveM 服务器状态插件指令:",
            "  /fivem 状态         — 查询在线人数与职业在线",
            "  /fivem 玩家         — 查询在线玩家列表",
            "  /fivem 职业 <名>    — 查询指定职业在线玩家",
            "  /fivem 检测         — 服务器健康检测",
            "  /fivem 订阅         — 订阅当前会话接收推送 🔒",
            "  /fivem 退订         — 取消推送订阅 🔒",
            "  /fivem 订阅列表     — 查看所有推送目标 🔒",
            "  /fivem 帮助         — 显示本帮助",
            "",
            "🔒 = 需要管理员权限",
            "提示：推送目标也可在 WebUI 插件配置中直接管理。",
        ]
        yield event.plain_result("\n".join(lines))
