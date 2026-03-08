import asyncio
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import aiohttp
from aiohttp import web

from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig
from astrbot.core.star.star_tools import StarTools
import astrbot.api.message_components as Comp

from .templates import (
    TMPL_STATUS, TMPL_PLAYERS, TMPL_JOB, TMPL_SELFCHECK, TMPL_HELP, TMPL_SEARCH, TMPL_TREND,
    CARD_VIEWPORT_WIDTH,
)

_HISTORY_FILE = Path(__file__).parent / "_history.json"
_HISTORY_RETENTION = 24 * 3600  # 保留 24 小时数据


@register("astrbot_plugin_fivem", "DingYu", "通过 QQ 查询和管理 FiveM 服务器", "1.14.2")
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
        self.notify_player_events = push.get("notify_player_events", True)
        self.notify_server_events = push.get("notify_server_events", True)
        self.alert_enabled = alert.get("alert_enabled", True)
        self.alert_threshold = max(alert.get("alert_threshold", 3), 1)
        self.admin_ids: list[str] = [str(aid) for aid in perm.get("admin_ids", [])]
        self.command_cooldown: int = max(perm.get("command_cooldown", 5), 0)

        display = config.get("display", {})
        self.render_image = display.get("render_image", True)
        self.server_start_template = display.get("server_start_template", "✅ 服务器已启动: {server_name}")
        self.shutdown_template = display.get("shutdown_template", "🔴 服务器即将关闭 ({author}, {delay}秒后)")
        self.restart_template = display.get("restart_template", "⏰ 计划重启: 剩余 {minutes} 分钟")
        self.alert_template = display.get("alert_template", "🚨 FiveM 服务器离线告警\n连续 {count} 次检测失败，服务器可能已离线！")

        self.webhook_enabled = push.get("webhook_enabled", False)
        self.webhook_port = push.get("webhook_port", 5765)
        self.webhook_token = push.get("webhook_token", "")
        self.event_buffer_seconds = max(push.get("event_buffer_seconds", 10), 0)
        self.admin_token: str = conn.get("admin_token", "")

        self._push_task: asyncio.Task | None = None
        self._push_targets: set[str] = set()
        self._fail_count = 0
        self._alerted = False
        self._session: aiohttp.ClientSession | None = None
        self._webhook_runner: web.AppRunner | None = None
        self._event_buffer: list[dict] = []
        self._flush_task: asyncio.Task | None = None
        self._cooldowns: dict[str, float] = {}
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

    # ── 历史数据持久化 ──

    @staticmethod
    def _load_history() -> list[dict]:
        """从 JSON 文件加载历史数据点"""
        try:
            if _HISTORY_FILE.exists():
                return json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"加载历史数据失败: {e}")
        return []

    @staticmethod
    def _save_history(history: list[dict]):
        """将历史数据点写入 JSON 文件"""
        try:
            _HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.warning(f"保存历史数据失败: {e}")

    def _record_data_point(self, count: int):
        """记录一个在线人数数据点，并裁剪超出保留期的旧数据"""
        now = int(time.time())
        history = self._load_history()
        history.append({"t": now, "c": count})
        cutoff = now - _HISTORY_RETENTION
        history = [p for p in history if p["t"] >= cutoff]
        self._save_history(history)

    def _targets_match(self, left: str, right: str) -> bool:
        return left == right or self._resolve_target(left) == self._resolve_target(right)

    def _has_push_target(self, target: str) -> bool:
        return any(self._targets_match(saved, target) for saved in self._push_targets)

    def _discard_push_target(self, target: str) -> bool:
        matched = [saved for saved in self._push_targets if self._targets_match(saved, target)]
        if not matched:
            return False
        for saved in matched:
            self._push_targets.discard(saved)
        return True

    def _format_target_display(self, target: str) -> str:
        parts = target.split(":", 2)
        if len(parts) == 3:
            platform, session_type, session_id = parts
            if session_type == "GroupMessage":
                return f"QQ群 {session_id} ({platform})"
            if session_type == "FriendMessage":
                return f"私聊 {session_id} ({platform})"
            return f"{session_type} {session_id} ({platform})"
        if target.strip().isdigit():
            return f"QQ群 {target.strip()}"
        return target

    def _describe_event_scope(self) -> str:
        scopes = []
        if self.notify_player_events:
            scopes.append("玩家动态")
        if self.notify_server_events:
            scopes.append("服务器通知")
        return " + ".join(scopes) if scopes else "全部关闭"

    def _describe_event_delivery(self) -> str:
        if not self.event_notify_enabled:
            return "已关闭"
        if self.webhook_enabled:
            return f"Webhook 实时推送 (端口 {self.webhook_port})"
        return f"轮询 /events ({self.auto_push_interval} 秒)"

    # ── 生命周期 ──

    def _needs_loop(self) -> bool:
        """是否需要启动定时循环"""
        return self.auto_push_enabled or self.alert_enabled or (
            self.event_notify_enabled and (self.notify_player_events or self.notify_server_events) and not self.webhook_enabled
        )

    async def initialize(self):
        """插件初始化，启动定时任务和 Webhook 服务"""
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.timeout)
        )
        if self._needs_loop():
            self._start_push_loop()
        if self.webhook_enabled:
            await self._start_webhook_server()

    async def terminate(self):
        """插件卸载，停止所有后台服务"""
        self._stop_push_loop()
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
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

    def _check_cooldown(self, event: AstrMessageEvent) -> str | None:
        """检查命令冷却，返回提示文本或 None（允许执行）。明确配置的管理员豁免。"""
        if self.command_cooldown <= 0:
            return None
        # 仅当 admin_ids 非空且用户在列表中时才豁免；admin_ids 为空时所有人都受冷却限制
        if self.admin_ids and str(event.get_sender_id()) in self.admin_ids:
            return None
        uid = str(event.get_sender_id())
        now = time.time()
        last = self._cooldowns.get(uid, 0)
        remaining = self.command_cooldown - (now - last)
        if remaining > 0:
            return f"⏳ 操作过于频繁，请 {remaining:.0f} 秒后再试。"
        self._cooldowns[uid] = now
        # 清理过期条目，防止字典无限增长
        cutoff = now - self.command_cooldown
        self._cooldowns = {k: v for k, v in self._cooldowns.items() if v >= cutoff}
        return None

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

    async def _post_admin(self, path: str, payload: dict) -> dict | None:
        """向 FiveM 服务器管理 API 发起 POST 请求"""
        if not self.admin_token:
            return {"success": False, "message": "未配置 admin_token，无法执行远程管理操作"}
        url = f"{self.server_url.rstrip('/')}{path}"
        headers = {"Authorization": f"Bearer {self.admin_token}"}
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )
        try:
            async with self._session.post(url, json=payload, headers=headers) as resp:
                data = await resp.json()
                if resp.status == 401:
                    return {"success": False, "message": "管理令牌验证失败，请检查 admin_token 与 FiveM 端 AdminToken 是否一致"}
                return data
        except aiohttp.ClientError as e:
            logger.error(f"FiveM Admin API 请求失败: {e}")
            return None
        except Exception as e:
            logger.error(f"FiveM Admin API 未知错误: {e}")
            return None

    # ── 状态文本格式化 ──

    @staticmethod
    def _format_uptime(seconds: int) -> str:
        """将秒数格式化为可读的运行时长"""
        if seconds < 60:
            return f"{seconds} 秒"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes} 分钟"
        hours = minutes // 60
        remaining_min = minutes % 60
        if hours < 24:
            return f"{hours} 小时 {remaining_min} 分钟"
        days = hours // 24
        remaining_hours = hours % 24
        return f"{days} 天 {remaining_hours} 小时"

    def _build_status_tmpl_data(self, data: dict) -> dict:
        """从 /status API 响应构建状态模板所需数据"""
        status = data["data"]
        total = status.get("totalPlayers", 0)
        max_p = status.get("maxPlayers", 0)
        uptime = status.get("uptime")
        return {
            "server_name": status.get("serverName", ""),
            "uptime": self._format_uptime(uptime) if uptime is not None else None,
            "total": total,
            "max_players": max_p,
            "ratio": round(total / max_p * 100) if max_p else 0,
            "jobs": status.get("jobs", []),
        }

    def _format_status(self, data: dict) -> str:
        """将 /status API 响应格式化为可读文本"""
        status = data["data"]
        total = status.get("totalPlayers", 0)
        max_players = status.get("maxPlayers", 0)
        server_name = status.get("serverName", "")
        uptime = status.get("uptime")

        lines = [
            f"🎮 FiveM 服务器状态",
        ]
        if server_name:
            lines.append(f"🏷️ {server_name}")
        lines.append(f"👥 在线人数: {total}/{max_players}")
        if uptime is not None:
            lines.append(f"⏱️ 运行时长: {self._format_uptime(uptime)}")

        jobs = status.get("jobs", [])
        if jobs:
            lines.append("📋 职业在线:")
            for job in jobs:
                name = job.get("label", job.get("name", "未知"))
                online = job.get("online", 0)
                lines.append(f"  • {name}: {online} 人")

        return "\n".join(lines)

    async def _render_image(self, event: AstrMessageEvent, template: str, data: dict, fallback_text: str):
        """尝试用 html_render 渲染图片卡片，失败则回退纯文本"""
        if self.render_image:
            try:
                url = await self.html_render(
                    template, data,
                    options={
                        "type": "png",
                        "viewport_width": CARD_VIEWPORT_WIDTH,
                    },
                )
                yield event.image_result(url)
                return
            except Exception as e:
                logger.warning(f"图片渲染失败，回退纯文本: {e}")
        yield event.plain_result(fallback_text)

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

                data = await self._request("/status")
                ok = data is not None and data.get("success")

                # ── 记录历史数据点（无论是否有推送目标都采集） ──
                if ok:
                    self._record_data_point(data["data"].get("totalPlayers", 0))

                if not self._push_targets:
                    continue

                # ── 离线告警逻辑 ──
                if self.alert_enabled:
                    if not ok:
                        self._fail_count += 1
                        if self._fail_count >= self.alert_threshold and not self._alerted:
                            self._alerted = True
                            await self._send_alert()
                        continue
                    else:
                        if self._alerted:
                            self._alerted = False
                        self._fail_count = 0

                # ── 定时推送 ──
                if self.auto_push_enabled and ok:
                    tmpl_data = self._build_status_tmpl_data(data)
                    await self._broadcast_image(TMPL_STATUS, tmpl_data, self._format_status(data))

                # ── 玩家上下线事件通知 ──
                if self.event_notify_enabled and (self.notify_player_events or self.notify_server_events) and not self.webhook_enabled and ok:
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

    @staticmethod
    def _render_template_chain(text: str) -> MessageChain:
        """将含 {at_all} 占位符的文本转换为 MessageChain；无 {at_all} 则为纯文本消息链"""
        chain = MessageChain()
        if "{at_all}" in text:
            parts = text.split("{at_all}")
            components = []
            for i, part in enumerate(parts):
                if part:
                    components.append(Comp.Plain(part))
                if i < len(parts) - 1:
                    components.append(Comp.At(qq="all"))
            chain.chain = components
        else:
            chain.message(text)
        return chain

    @staticmethod
    def _get_event_time(ev: dict) -> str:
        ts = ev.get("time")
        return datetime.fromtimestamp(ts, tz=timezone(timedelta(hours=8))).strftime("%H:%M") if ts else "--:--"

    @staticmethod
    def _format_player_lines(events: list[dict]) -> list[str]:
        """将玩家事件格式化为纯文本行"""
        lines = []
        for ev in events:
            etype = ev.get("type")
            if etype not in ("connecting", "join", "leave"):
                continue
            name = ev.get("name", "未知")
            pid = ev.get("id")
            id_tag = f"[{pid}] " if pid else ""
            job_label = ev.get("jobLabel", "")
            job_suffix = f" [{job_label}]" if job_label else ""
            if etype == "connecting":
                lines.append(f"  🟡 {name} 正在连接...")
            elif etype == "join":
                lines.append(f"  🟢 {id_tag}{name}{job_suffix} 加入了服务器")
            elif etype == "leave":
                reason = ev.get("reason", "")
                reason_suffix = f" ({reason})" if reason else ""
                lines.append(f"  🔴 {id_tag}{name}{job_suffix} 离开了服务器{reason_suffix}")
        return lines

    def _build_server_notification(self, events: list[dict]) -> tuple[str | None, str, bool]:
        """构建服务器事件通知文本。返回 (Markdown 图片文本, 纯文本 fallback, 是否@全体)"""
        md_lines: list[str] = []
        fallback_lines: list[str] = []
        has_at_all = False
        icon_map = {"ok": "✅", "info": "📢", "warn": "⏰", "err": "🔴"}
        severity = "ok"
        sev_order = {"ok": 0, "info": 1, "warn": 2, "err": 3}

        for ev in events:
            etype = ev.get("type")
            if etype in ("connecting", "join", "leave"):
                continue
            t_str = self._get_event_time(ev)

            if etype == "announcement":
                author = ev.get("author", "txAdmin")
                message = ev.get("message", "")
                md_lines.append(f"**📢 管理员公告 ({author})**")
                if message:
                    md_lines.append(f"- 内容: {message}")
                if ev.get("time"):
                    md_lines.append(f"- ⏰ {t_str}")
                md_lines.append("")
                fallback_lines.append(f"  📢 管理员公告 ({author}): {message}")
                if sev_order["info"] > sev_order[severity]:
                    severity = "info"

            elif etype == "shutdown":
                author = ev.get("author", "txAdmin")
                delay = ev.get("delay", 0)
                message = ev.get("message", "")
                delay_sec = round(delay / 1000) if delay else 0
                title = self.shutdown_template.format(author=author, delay=delay_sec, message=message, time=t_str, at_all="").strip()
                if "{at_all}" in self.shutdown_template:
                    has_at_all = True
                md_lines.append(f"**🔴 {title}**")
                if message and "{message}" not in self.shutdown_template:
                    md_lines.append(f"- 附加消息: {message}")
                if ev.get("time"):
                    md_lines.append(f"- ⏰ {t_str}")
                md_lines.append("")
                fb = self.shutdown_template.format(author=author, delay=delay_sec, message=message, time=t_str, at_all="{at_all}")
                if message and "{message}" not in self.shutdown_template:
                    fb += f": {message}"
                fallback_lines.append(f"  {fb}")
                severity = "err"

            elif etype == "restart":
                seconds = ev.get("secondsRemaining", 0)
                minutes = round(seconds / 60)
                title = self.restart_template.format(minutes=minutes, seconds=seconds, time=t_str, at_all="").strip()
                if "{at_all}" in self.restart_template:
                    has_at_all = True
                md_lines.append(f"**⏰ {title}**")
                if ev.get("time"):
                    md_lines.append(f"- ⏰ {t_str}")
                md_lines.append("")
                fb = self.restart_template.format(minutes=minutes, seconds=seconds, time=t_str, at_all="{at_all}")
                fallback_lines.append(f"  {fb}")
                if sev_order["warn"] > sev_order[severity]:
                    severity = "warn"

            elif etype == "server_start":
                sn = ev.get("serverName", "FiveM Server")
                players = ev.get("totalPlayers", 0)
                max_p = ev.get("maxPlayers", 0)
                title = self.server_start_template.format(server_name=sn, time=t_str, players=players, max_players=max_p, at_all="").strip()
                if "{at_all}" in self.server_start_template:
                    has_at_all = True
                md_lines.append(f"**✅ {title}**")
                if max_p:
                    md_lines.append(f"- 在线 / 最大: {players} / {max_p}")
                if ev.get("time"):
                    md_lines.append(f"- ⏰ {t_str}")
                md_lines.append("")
                fb = self.server_start_template.format(server_name=sn, time=t_str, players=players, max_players=max_p, at_all="{at_all}")
                fallback_lines.append(f"  {fb}")

            elif etype == "custom":
                ctitle = ev.get("title", "自定义事件")
                message = ev.get("message", "")
                md_lines.append(f"**🔔 {ctitle}**")
                if message:
                    md_lines.append(f"- 内容: {message}")
                if ev.get("time"):
                    md_lines.append(f"- ⏰ {t_str}")
                md_lines.append("")
                line = f"  🔔 {ctitle}"
                if message:
                    line += f": {message}"
                fallback_lines.append(line)
                if sev_order["info"] > sev_order[severity]:
                    severity = "info"

        if not md_lines:
            return None, "", False

        header = f"# {icon_map[severity]} 服务器通知 ({len(fallback_lines)} 条)\n\n---\n"
        md_text = header + "\n".join(md_lines)
        fallback = f"🖥️ 服务器通知 ({len(fallback_lines)} 条):\n" + "\n".join(fallback_lines)
        return md_text, fallback, has_at_all

    async def _broadcast_notification(self, md_text: str, fallback: str, has_at_all: bool):
        """将 Markdown 文本渲染为图片并广播；支持 @全体；渲染失败回退纯文本"""
        try:
            url = await self.text_to_image(md_text)
            chain = MessageChain()
            if has_at_all:
                chain.chain = [Comp.At(qq="all"), Comp.Plain("\n"), Comp.Image(file=url)]
            else:
                chain.chain = [Comp.Image(file=url)]
            await self._broadcast_chain(chain)
            return
        except Exception as e:
            logger.warning(f"通知图片渲染失败，回退纯文本: {e}")
        chain = self._render_template_chain(fallback)
        await self._broadcast_chain(chain)

    async def _send_alert(self):
        """发送离线告警通知（图片 + 可选 @全体）"""
        raw = self.alert_template.format(count=self._fail_count, at_all="").strip()
        has_at_all = "{at_all}" in self.alert_template
        now_str = datetime.now(tz=timezone(timedelta(hours=8))).strftime("%H:%M")
        md_text = f"# 🚨 离线告警\n\n---\n\n**{raw}**\n- 连续失败: {self._fail_count} 次\n- ⏰ {now_str}\n"
        fallback = self.alert_template.format(count=self._fail_count, at_all="{at_all}")
        await self._broadcast_notification(md_text, fallback, has_at_all)

    async def _process_and_broadcast_events(self, events: list[dict]):
        """将事件放入缓冲区，延迟合并后广播；buffer_seconds=0 时立即发送"""
        if self.event_buffer_seconds <= 0:
            await self._send_events(events)
            return
        self._event_buffer.extend(events)
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.create_task(self._flush_events())

    async def _flush_events(self):
        """等待缓冲窗口结束后，批量发送所有缓冲事件；若发送期间有新事件到达，循环处理"""
        await asyncio.sleep(self.event_buffer_seconds)
        while self._event_buffer:
            events = self._event_buffer
            self._event_buffer = []
            await self._send_events(events)

    async def _send_events(self, events: list[dict]):
        """格式化事件并广播到所有推送目标"""
        if self.notify_server_events:
            md_text, fallback, has_at_all = self._build_server_notification(events)
            if md_text:
                await self._broadcast_notification(md_text, fallback, has_at_all)
        if self.notify_player_events:
            lines = self._format_player_lines(events)
            if lines:
                text = f"📡 玩家动态 ({len(lines)} 条):\n" + "\n".join(lines)
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

        if not self.event_notify_enabled or not events or not self._push_targets or not (self.notify_player_events or self.notify_server_events):
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

    async def _broadcast_image(self, template: str, data: dict, fallback_text: str):
        """尝试渲染图片卡片并广播到所有推送目标，失败则回退纯文本"""
        if self.render_image:
            try:
                url = await self.html_render(
                    template, data,
                    options={"type": "png", "viewport_width": CARD_VIEWPORT_WIDTH},
                )
                chain = MessageChain().image(url)
                await self._broadcast_chain(chain)
                return
            except Exception as e:
                logger.warning(f"推送图片渲染失败，回退纯文本: {e}")
        await self._broadcast(fallback_text)

    async def _broadcast(self, text: str):
        """向所有绑定会话发送纯文本消息"""
        chain = MessageChain().message(text)
        await self._broadcast_chain(chain)

    async def _broadcast_chain(self, chain: MessageChain):
        """向所有绑定会话发送消息链，支持纯群号自动转换"""
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

    async def _do_server_status(self, event: AstrMessageEvent):
        """服务器状态查询核心逻辑（命令与 LLM 工具共用）"""
        data = await self._request("/status")
        if data is None:
            yield event.plain_result("❌ 无法连接到 FiveM 服务器，请稍后重试。")
            return
        if not data.get("success"):
            yield event.plain_result("❌ 服务器返回异常数据。")
            return
        tmpl_data = self._build_status_tmpl_data(data)
        async for result in self._render_image(event, TMPL_STATUS, tmpl_data, self._format_status(data)):
            yield result

    @fivem.command("状态")
    async def server_status(self, event: AstrMessageEvent):
        """查询服务器在线状态与职业人数"""
        if cd := self._check_cooldown(event):
            yield event.plain_result(cd)
            return
        async for result in self._do_server_status(event):
            yield result

    async def _do_player_list(self, event: AstrMessageEvent):
        """玩家列表核心逻辑（命令与 LLM 工具共用）"""
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
        tmpl_players = []
        for p in players:
            pid = p.get("id", "?")
            name = p.get("name", "未知")
            job_label = p.get("jobLabel", p.get("job", ""))
            online_sec = p.get("onlineSeconds")
            duration = self._format_uptime(online_sec) if online_sec is not None else None
            suffix = f" ({duration})" if duration else ""
            lines.append(f"  [{pid}] {name} — {job_label}{suffix}")
            tmpl_players.append({"id": pid, "name": name, "job_label": job_label, "duration": duration})
        async for result in self._render_image(
            event, TMPL_PLAYERS, {"players": tmpl_players}, "\n".join(lines)
        ):
            yield result

    @fivem.command("玩家")
    async def players_list(self, event: AstrMessageEvent):
        """查询在线玩家列表"""
        if cd := self._check_cooldown(event):
            yield event.plain_result(cd)
            return
        async for result in self._do_player_list(event):
            yield result

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

    async def _do_job_query(self, event: AstrMessageEvent, job_keyword: str):
        """职业查询核心逻辑（命令与 LLM 工具共用）"""
        resolved, err = await self._resolve_job_name(job_keyword)
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
        label = job.get("label", job.get("name", job_keyword))
        online = job.get("online", 0)
        players = job.get("players", [])
        lines = [f"👔 {label} ({online} 人在线):"]
        tmpl_players = []
        if players:
            for p in players:
                pid = p.get("id", "?")
                name = p.get("name", "未知")
                lines.append(f"  [{pid}] {name}")
                tmpl_players.append({"id": pid, "name": name})
        else:
            lines.append("  当前无人在线")
        tmpl_data = {"label": label, "online": online, "players": tmpl_players}
        async for result in self._render_image(event, TMPL_JOB, tmpl_data, "\n".join(lines)):
            yield result

    @fivem.command("职业")
    async def job_query(self, event: AstrMessageEvent, job_name: str):
        """查询指定职业的在线玩家"""
        if cd := self._check_cooldown(event):
            yield event.plain_result(cd)
            return
        async for result in self._do_job_query(event, job_name):
            yield result

    async def _do_search_player(self, event: AstrMessageEvent, keyword: str):
        """玩家搜索核心逻辑（命令与 LLM 工具共用）"""
        data = await self._request("/players")
        if data is None:
            yield event.plain_result("❌ 无法连接到 FiveM 服务器，请稍后重试。")
            return
        if not data.get("success"):
            yield event.plain_result("❌ 服务器返回异常数据。")
            return
        kw = keyword.lower()
        results = []
        for p in data["data"]:
            name = p.get("name", "")
            if kw in name.lower():
                results.append({
                    "id": p.get("id", "?"),
                    "name": name,
                    "job_label": p.get("jobLabel", p.get("job", "")),
                })
        lines = [f"🔍 搜索「{keyword}」 — 匹配 {len(results)} 人:"]
        if results:
            for r in results:
                lines.append(f"  [{r['id']}] {r['name']} — {r['job_label']}")
        else:
            lines.append("  未找到匹配的在线玩家。")
        tmpl_data = {"keyword": keyword, "results": results}
        async for result in self._render_image(event, TMPL_SEARCH, tmpl_data, "\n".join(lines)):
            yield result

    @fivem.command("查找")
    async def search_player(self, event: AstrMessageEvent, keyword: str):
        """模糊搜索在线玩家（用法: /fivem 查找 玩家名）"""
        if cd := self._check_cooldown(event):
            yield event.plain_result(cd)
            return
        async for result in self._do_search_player(event, keyword):
            yield result

    def _build_trend_data(self, history: list[dict]) -> tuple[dict, list[str]] | None:
        """将历史数据点构建为趋势模板数据和纯文本行，数据不足时返回 None"""
        if len(history) < 2:
            return None

        tz = timezone(timedelta(hours=8))
        points = []
        for p in history:
            dt = datetime.fromtimestamp(p["t"], tz=tz)
            points.append({"label": dt.strftime("%H:%M"), "count": p["c"], "ts": p["t"]})

        counts = [p["count"] for p in points]
        max_count = max(counts) if counts else 1
        avg_count = round(sum(counts) / len(counts), 1)
        peak_point = max(points, key=lambda p: p["count"])

        lines = [
            f"📊 最近 {len(points)} 个数据点趋势:",
            f"  📈 峰值: {max_count} 人 ({peak_point['label']})",
            f"  📉 均值: {avg_count} 人",
            f"  📌 当前: {counts[-1]} 人",
        ]

        chart_w, chart_h = 440, 180
        margin_l, margin_b = 40, 24
        y_max = max(max_count, 1)
        n = len(points)
        svg_points = []
        for i, p in enumerate(points):
            x = margin_l + (i / max(n - 1, 1)) * chart_w
            y = chart_h - (p["count"] / y_max) * (chart_h - margin_b)
            svg_points.append({"x": round(x, 1), "y": round(y, 1), "count": p["count"], "label": p["label"]})

        label_count = min(6, n)
        label_indices = [round(i * (n - 1) / max(label_count - 1, 1)) for i in range(label_count)]
        x_labels = [{"x": svg_points[i]["x"], "text": svg_points[i]["label"]} for i in label_indices]

        polyline = " ".join(f"{p['x']},{p['y']}" for p in svg_points)

        tmpl_data = {
            "polyline": polyline,
            "svg_points": svg_points,
            "x_labels": x_labels,
            "chart_w": chart_w + margin_l,
            "chart_h": chart_h,
            "y_max": y_max,
            "margin_l": margin_l,
            "margin_b": margin_b,
            "max_count": max_count,
            "avg_count": avg_count,
            "peak_label": peak_point["label"],
            "current": counts[-1],
            "total_points": len(points),
        }
        return tmpl_data, lines

    @fivem.command("趋势")
    async def trend(self, event: AstrMessageEvent):
        """查看最近 24 小时在线人数趋势图"""
        if cd := self._check_cooldown(event):
            yield event.plain_result(cd)
            return
        history = self._load_history()
        result = self._build_trend_data(history)
        if result is None:
            yield event.plain_result("📊 历史数据不足，至少需要 2 个数据点才能生成趋势图。\n提示：数据在定时推送轮询时自动采集。")
            return
        tmpl_data, lines = result
        async for r in self._render_image(event, TMPL_TREND, tmpl_data, "\n".join(lines)):
            yield r

    @fivem.command("检测")
    async def health_check(self, event: AstrMessageEvent):
        """服务器健康检测"""
        if cd := self._check_cooldown(event):
            yield event.plain_result(cd)
            return
        data = await self._request("/health")
        if data is None:
            yield event.plain_result("❌ FiveM 服务器不可达。")
            return

        if data.get("status") == "ok":
            yield event.plain_result("✅ FiveM 服务器运行正常。")
        else:
            yield event.plain_result(f"⚠️ FiveM 服务器状态异常: {data}")

    @fivem.command("自检")
    async def self_check(self, event: AstrMessageEvent):
        if not self._is_admin(event):
            yield event.plain_result("🚫 权限不足，仅管理员可执行此操作。")
            return

        health_data = await self._request("/health")
        status_data = await self._request("/status")
        health_ok = health_data is not None and health_data.get("status") == "ok"
        status_ok = status_data is not None and status_data.get("success")
        current_subscribed = self._has_push_target(event.unified_msg_origin)
        loop_running = self._push_task is not None and not self._push_task.done()
        webhook_ready = not self.webhook_enabled or self._webhook_runner is not None

        # ── 纯文本回退 ──
        lines = [
            "🩺 FiveM 插件自检",
            f"🔗 API /health: {'正常' if health_ok else '失败'}",
            f"📊 API /status: {'正常' if status_ok else '失败'}",
            f"📡 事件通知: {self._describe_event_delivery()}",
            f"🗂️ 通知范围: {self._describe_event_scope()}",
            f"📬 订阅目标: {len(self._push_targets)} 个",
            f"🙋 当前会话: {'已订阅' if current_subscribed else '未订阅'}",
            f"⚙️ 后台任务: {'运行中' if loop_running else '未运行'}",
        ]

        if self.webhook_enabled:
            lines.append(f"🌐 Webhook 监听: {'已启动' if webhook_ready else '未启动'}")

        # ── 图片渲染数据 ──
        checks = [
            {"icon": "🔗", "label": "API /health", "value": "正常" if health_ok else "失败", "status": "ok" if health_ok else "err"},
            {"icon": "📊", "label": "API /status", "value": "正常" if status_ok else "失败", "status": "ok" if status_ok else "err"},
            {"icon": "📡", "label": "事件通知", "value": self._describe_event_delivery(), "status": "ok" if self.event_notify_enabled else "warn"},
            {"icon": "🗂️", "label": "通知范围", "value": self._describe_event_scope(), "status": "ok"},
            {"icon": "📬", "label": "订阅目标", "value": f"{len(self._push_targets)} 个", "status": "ok" if self._push_targets else "warn"},
            {"icon": "🙋", "label": "当前会话", "value": "已订阅" if current_subscribed else "未订阅", "status": "ok" if current_subscribed else "warn"},
            {"icon": "⚙️", "label": "后台任务", "value": "运行中" if loop_running else "未运行", "status": "ok" if loop_running else "warn"},
        ]
        if self.webhook_enabled:
            checks.append({"icon": "🌐", "label": "Webhook", "value": "已启动" if webhook_ready else "未启动", "status": "ok" if webhook_ready else "err"})

        issues = []
        if not health_ok:
            issues.append("FiveM /health 不可达，请检查 server_url、网络与 WhitelistIPs。")
        elif not status_ok:
            issues.append("FiveM /status 未返回 success，请检查资源端状态输出是否正常。")
        if self.event_notify_enabled and not (self.notify_player_events or self.notify_server_events):
            issues.append("事件通知总开关已开启，但玩家事件和服务器事件都已关闭。")
        if self.webhook_enabled and not webhook_ready:
            issues.append("Webhook 已启用但监听服务未启动，请检查端口占用和插件初始化日志。")
        if not self._push_targets:
            issues.append("当前没有任何推送目标，可通过 /fivem 订阅 添加。")
        elif not current_subscribed:
            issues.append("当前会话未订阅推送，如需在本群接收通知，请执行 /fivem 订阅。")

        if issues:
            lines.append("")
            lines.append("⚠️ 建议关注:")
            for issue in issues:
                lines.append(f"  • {issue}")
        else:
            lines.append("")
            lines.append("✅ 未发现明显配置问题。")

        tmpl_data = {"checks": checks, "issues": issues}
        async for result in self._render_image(event, TMPL_SELFCHECK, tmpl_data, "\n".join(lines)):
            yield result

    @fivem.command("订阅")
    async def subscribe_push(self, event: AstrMessageEvent):
        """订阅当前会话接收推送/告警/事件通知（需管理员权限）"""
        if not self._is_admin(event):
            yield event.plain_result("🚫 权限不足，仅管理员可执行此操作。")
            return

        umo = event.unified_msg_origin
        if self._has_push_target(umo):
            yield event.plain_result("ℹ️ 当前会话已订阅推送。")
            return

        self._push_targets.add(umo)
        self._save_push_targets()

        if self._needs_loop():
            self._start_push_loop()

        yield event.plain_result(
            f"✅ 已订阅当前会话，将接收推送/告警/事件通知。\n当前订阅总数: {len(self._push_targets)}"
        )

    @fivem.command("退订")
    async def unsubscribe_push(self, event: AstrMessageEvent):
        """取消当前会话的推送订阅（需管理员权限）"""
        if not self._is_admin(event):
            yield event.plain_result("🚫 权限不足，仅管理员可执行此操作。")
            return

        umo = event.unified_msg_origin
        if not self._has_push_target(umo):
            yield event.plain_result("ℹ️ 当前会话未订阅推送。")
            return

        self._discard_push_target(umo)
        self._save_push_targets()

        yield event.plain_result(
            f"✅ 已取消当前会话的推送订阅。\n当前订阅总数: {len(self._push_targets)}"
        )

    @fivem.command("订阅列表")
    async def list_subscriptions(self, event: AstrMessageEvent):
        """查看当前所有推送订阅目标（需管理员权限）"""
        if not self._is_admin(event):
            yield event.plain_result("🚫 权限不足，仅管理员可执行此操作。")
            return

        if not self._push_targets:
            yield event.plain_result("ℹ️ 当前没有任何推送订阅。\n提示：可通过 /fivem 订阅 添加，或在 WebUI 配置 push_targets。")
            return

        lines = [
            f"📬 推送订阅列表 ({len(self._push_targets)} 个):",
            f"📡 事件通知: {self._describe_event_delivery()}",
            f"🗂️ 通知范围: {self._describe_event_scope()}",
        ]
        for i, target in enumerate(sorted(self._push_targets), 1):
            display = self._format_target_display(target)
            if display == target:
                lines.append(f"  {i}. {display}")
            else:
                lines.append(f"  {i}. {display} → {target}")
        yield event.plain_result("\n".join(lines))

    # ── 远程管理命令 ──

    @fivem.command("公告")
    async def admin_announce(self, event: AstrMessageEvent, content: str = ""):
        """从 QQ 发送公告到游戏内（需管理员权限）"""
        if not self._is_admin(event):
            yield event.plain_result("🚫 权限不足，仅管理员可执行此操作。")
            return
        if not content.strip():
            yield event.plain_result("用法: /fivem 公告 <内容>")
            return
        result = await self._post_admin("/admin/announce", {"message": content.strip(), "author": "QQ管理"})
        if result is None:
            yield event.plain_result("❌ 无法连接到 FiveM 服务器。")
            return
        if result.get("success"):
            yield event.plain_result(f"📢 公告已发送到游戏内:\n{content.strip()}")
        else:
            yield event.plain_result(f"❌ 公告发送失败: {result.get('message', '未知错误')}")

    @fivem.command("广播")
    async def admin_broadcast(self, event: AstrMessageEvent, content: str = ""):
        """从 QQ 发送聊天广播到游戏内（需管理员权限）"""
        if not self._is_admin(event):
            yield event.plain_result("🚫 权限不足，仅管理员可执行此操作。")
            return
        if not content.strip():
            yield event.plain_result("用法: /fivem 广播 <内容>")
            return
        result = await self._post_admin("/admin/broadcast", {"message": content.strip(), "author": "QQ管理"})
        if result is None:
            yield event.plain_result("❌ 无法连接到 FiveM 服务器。")
            return
        if result.get("success"):
            yield event.plain_result(f"📣 广播已发送到游戏内:\n{content.strip()}")
        else:
            yield event.plain_result(f"❌ 广播发送失败: {result.get('message', '未知错误')}")

    @fivem.command("踢人")
    async def admin_kick(self, event: AstrMessageEvent, target: str = "", reason: str = ""):
        """从 QQ 远程踢出游戏内玩家（需管理员权限）"""
        if not self._is_admin(event):
            yield event.plain_result("🚫 权限不足，仅管理员可执行此操作。")
            return
        if not target.strip():
            yield event.plain_result("用法: /fivem 踢人 <玩家ID或名称> [原因]")
            return
        payload = {"target": target.strip()}
        if reason.strip():
            payload["reason"] = reason.strip()
        result = await self._post_admin("/admin/kick", payload)
        if result is None:
            yield event.plain_result("❌ 无法连接到 FiveM 服务器。")
            return
        if result.get("success"):
            yield event.plain_result(f"✅ {result.get('message', '操作成功')}")
        else:
            yield event.plain_result(f"❌ {result.get('message', '操作失败')}")

    @fivem.command("帮助")
    async def show_help(self, event: AstrMessageEvent):
        """显示所有可用指令"""
        lines = [
            "📖 FiveM 服务器状态插件指令:",
            "",
            "查询类命令:",
            "  /fivem 状态         — 查询在线人数与职业在线",
            "  /fivem 玩家         — 查询在线玩家列表",
            "  /fivem 职业 <名>    — 查询指定职业在线玩家",
            "  /fivem 查找 <名>    — 模糊搜索在线玩家",
            "  /fivem 趋势         — 查看 24 小时在线人数趋势",
            "  /fivem 检测         — 服务器健康检测",
            "  /fivem 帮助         — 显示本帮助",
            "",
            "管理员命令:",
            "  /fivem 自检         — 检查 API、Webhook 与订阅状态 🔒",
            "  /fivem 订阅         — 订阅当前会话接收推送 🔒",
            "  /fivem 退订         — 取消推送订阅 🔒",
            "  /fivem 订阅列表     — 查看所有推送目标 🔒",
            "",
            "远程管理命令:",
            "  /fivem 公告 <内容>  — 发送公告到游戏内 🔒",
            "  /fivem 广播 <内容>  — 发送聊天广播到游戏内 🔒",
            "  /fivem 踢人 <目标>  — 远程踢出游戏内玩家 🔒",
            "",
            "🔒 = 需要管理员权限",
            "提示：推送目标也可在 WebUI 插件配置中直接管理，事件通知范围可分别控制玩家动态和服务器通知。",
        ]

        tmpl_data = {
            "query_cmds": [
                {"usage": "/fivem 状态", "desc": "查询在线人数与职业在线"},
                {"usage": "/fivem 玩家", "desc": "查询在线玩家列表"},
                {"usage": "/fivem 职业 <名>", "desc": "查询指定职业在线玩家"},
                {"usage": "/fivem 查找 <名>", "desc": "模糊搜索在线玩家"},
                {"usage": "/fivem 趋势", "desc": "24 小时在线人数趋势图"},
                {"usage": "/fivem 检测", "desc": "服务器健康检测"},
                {"usage": "/fivem 帮助", "desc": "显示本帮助"},
            ],
            "admin_cmds": [
                {"usage": "/fivem 自检", "desc": "检查 API、Webhook 与订阅状态"},
                {"usage": "/fivem 订阅", "desc": "订阅当前会话接收推送"},
                {"usage": "/fivem 退订", "desc": "取消推送订阅"},
                {"usage": "/fivem 订阅列表", "desc": "查看所有推送目标"},
                {"usage": "/fivem 公告 <内容>", "desc": "发送公告到游戏内"},
                {"usage": "/fivem 广播 <内容>", "desc": "发送聊天广播到游戏内"},
                {"usage": "/fivem 踢人 <目标>", "desc": "远程踢出游戏内玩家"},
            ],
        }
        async for result in self._render_image(event, TMPL_HELP, tmpl_data, "\n".join(lines)):
            yield result

    # ── AI 自然语言查询工具 ──

    @filter.llm_tool(name="fivem_server_status")
    async def tool_server_status(self, event: AstrMessageEvent):
        '''查询 FiveM 游戏服务器的在线状态，包括在线人数、各职业在线人数、服务器运行时长等信息。

        Args:
        '''
        async for result in self._do_server_status(event):
            yield result

    @filter.llm_tool(name="fivem_player_list")
    async def tool_player_list(self, event: AstrMessageEvent):
        '''查询 FiveM 游戏服务器当前所有在线玩家列表，包括玩家 ID、名称、职业和在线时长。

        Args:
        '''
        async for result in self._do_player_list(event):
            yield result

    @filter.llm_tool(name="fivem_job_query")
    async def tool_job_query(self, event: AstrMessageEvent, job_keyword: str):
        '''查询 FiveM 游戏服务器中指定职业的在线玩家列表。支持模糊匹配职业名称，如"警察"、"医生"、"出租车"等。

        Args:
            job_keyword(string): 要查询的职业名称或关键词，如 police、警察、ambulance、医疗 等
        '''
        async for result in self._do_job_query(event, job_keyword):
            yield result

    @filter.llm_tool(name="fivem_player_search")
    async def tool_player_search(self, event: AstrMessageEvent, player_name: str):
        '''在 FiveM 游戏服务器中搜索指定名称的在线玩家。支持模糊匹配玩家名称。

        Args:
            player_name(string): 要搜索的玩家名称或关键词
        '''
        async for result in self._do_search_player(event, player_name):
            yield result

    @filter.llm_tool(name="fivem_trend")
    async def tool_trend(self, event: AstrMessageEvent):
        '''查看 FiveM 游戏服务器过去 24 小时的在线人数趋势图，展示历史在线人数变化曲线。

        Args:
        '''
        history = self._load_history()
        result = self._build_trend_data(history)
        if result is None:
            yield event.plain_result("� 历史数据不足，至少需要 2 个数据点才能生成趋势图。")
            return
        tmpl_data, lines = result
        async for r in self._render_image(event, TMPL_TREND, tmpl_data, "\n".join(lines)):
            yield r
