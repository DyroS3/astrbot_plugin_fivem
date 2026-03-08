import asyncio
import json
import math
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import aiohttp
from aiohttp import web

from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig
import astrbot.api.message_components as Comp


_HISTORY_FILE = Path(__file__).parent / "_history.json"
_HISTORY_RETENTION = 24 * 3600  # 保留 24 小时数据


@register("astrbot_plugin_fivem", "DingYu", "通过 QQ 查询和管理 FiveM 服务器", "1.16.0")
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
        self.default_platform_id = "" if push.get("default_platform_id") is None else str(push.get("default_platform_id")).strip()
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
        self._target_fail_counts: dict[str, int] = {}
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
            self._target_fail_counts.pop(saved, None)
            self._target_fail_counts.pop(self._resolve_target(saved), None)
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

    def _describe_loop_reasons(self) -> str:
        reasons = []
        if self.auto_push_enabled:
            reasons.append("定时状态推送")
        if self.alert_enabled:
            reasons.append("离线告警 / 趋势采集")
        if self.event_notify_enabled and (self.notify_player_events or self.notify_server_events) and not self.webhook_enabled:
            reasons.append("事件轮询")
        return " + ".join(reasons) if reasons else "无需后台轮询"

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
        try:
            if self._needs_loop():
                self._start_push_loop()
            if self.webhook_enabled:
                await self._start_webhook_server()
        except Exception as e:
            logger.error(f"FiveM 插件初始化失败: {e}")
            self._stop_push_loop()
            await self._stop_webhook_server()
            if self._session and not self._session.closed:
                await self._session.close()
            self._session = None
            raise

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

    def _ensure_session(self):
        """确保 aiohttp 会话可用"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )

    async def _request(self, path: str) -> dict | None:
        """向 FiveM 服务器状态 API 发起 GET 请求"""
        url = f"{self.server_url.rstrip('/')}{path}"
        self._ensure_session()
        try:
            async with self._session.get(url) as resp:
                if resp.status != 200:
                    logger.warning(f"FiveM API 返回 HTTP {resp.status}: {url}")
                    return None
                text = await resp.text()
                try:
                    data = json.loads(text) if text else None
                except json.JSONDecodeError as e:
                    logger.error(f"FiveM API 返回了无效 JSON ({url}): {e}")
                    return None
                if not isinstance(data, dict):
                    logger.warning(f"FiveM API 返回了非对象 JSON: {url}")
                    return None
                return data
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
        self._ensure_session()
        try:
            async with self._session.post(url, json=payload, headers=headers) as resp:
                text = await resp.text()
                data = None
                if text:
                    try:
                        data = json.loads(text)
                    except json.JSONDecodeError:
                        data = None
                if resp.status == 401:
                    return {"success": False, "message": "管理令牌验证失败，请检查 admin_token 与 FiveM 端 AdminToken 是否一致"}
                if resp.status >= 400:
                    message = ""
                    if isinstance(data, dict):
                        message = self._safe_text(data.get("message")).strip()
                    if not message:
                        message = text.strip()
                    if not message:
                        message = f"FiveM 管理接口返回 HTTP {resp.status}"
                    return {"success": False, "message": message}
                if isinstance(data, dict):
                    return data
                if text.strip():
                    return {"success": True, "message": text.strip()}
                return {"success": False, "message": "FiveM 管理接口返回了空响应"}
        except aiohttp.ClientError as e:
            logger.error(f"FiveM Admin API 请求失败: {e}")
            return None
        except Exception as e:
            logger.error(f"FiveM Admin API 未知错误: {e}")
            return None

    @staticmethod
    def _safe_text(value: object) -> str:
        return "" if value is None else str(value)

    @staticmethod
    def _safe_int(value: object, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _escape_md(value: object) -> str:
        text = "" if value is None else str(value)
        return text.replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ")

    @staticmethod
    def _apply_template(template: str, **values) -> str:
        result = "" if template is None else str(template)
        for key, value in values.items():
            result = result.replace(f"{{{key}}}", "" if value is None else str(value))
        return result

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

    def _format_status_md(self, data: dict) -> str:
        """将 /status API 响应格式化为 Markdown"""
        status = data.get("data") if isinstance(data, dict) else None
        if not isinstance(status, dict):
            return "# 🎮 FiveM 服务器状态\n\n⚠️ 服务器返回异常数据。"
        total = self._safe_int(status.get("totalPlayers", 0))
        max_players = self._safe_int(status.get("maxPlayers", 0))
        server_name = self._safe_text(status.get("serverName", ""))
        uptime = status.get("uptime")
        lines = ["# 🎮 FiveM 服务器状态\n"]
        if server_name:
            lines.append(f"**🏷️ {self._escape_md(server_name)}**\n")
        lines.append(f"- 👥 在线人数: **{total} / {max_players}**")
        if uptime is not None:
            lines.append(f"- ⏱️ 运行时长: {self._format_uptime(self._safe_int(uptime))}")
        jobs = status.get("jobs", [])
        if not isinstance(jobs, list):
            jobs = []
        if jobs:
            lines.append("\n## 📋 职业在线\n")
            lines.append("| 职业 | 在线 |")
            lines.append("|------|------|")
            for job in jobs:
                if not isinstance(job, dict):
                    continue
                name = self._escape_md(job.get("label", job.get("name", "未知")))
                online = self._safe_int(job.get("online", 0))
                lines.append(f"| {name} | {online} 人 |")
        return "\n".join(lines)

    def _format_status(self, data: dict) -> str:
        """将 /status API 响应格式化为可读文本"""
        status = data.get("data") if isinstance(data, dict) else None
        if not isinstance(status, dict):
            return "⚠️ FiveM 服务器返回异常数据。"
        total = self._safe_int(status.get("totalPlayers", 0))
        max_players = self._safe_int(status.get("maxPlayers", 0))
        server_name = self._safe_text(status.get("serverName", ""))
        uptime = status.get("uptime")

        lines = [
            f"🎮 FiveM 服务器状态",
        ]
        if server_name:
            lines.append(f"🏷️ {server_name}")
        lines.append(f"👥 在线人数: {total}/{max_players}")
        if uptime is not None:
            lines.append(f"⏱️ 运行时长: {self._format_uptime(self._safe_int(uptime))}")

        jobs = status.get("jobs", [])
        if not isinstance(jobs, list):
            jobs = []
        if jobs:
            lines.append("📋 职业在线:")
            for job in jobs:
                if not isinstance(job, dict):
                    continue
                name = self._safe_text(job.get("label", job.get("name", "未知")))
                online = self._safe_int(job.get("online", 0))
                lines.append(f"  • {name}: {online} 人")

        return "\n".join(lines)

    async def _render_image(self, event: AstrMessageEvent, md_text: str, fallback_text: str):
        """尝试用 text_to_image 渲染 Markdown 图片，失败则回退纯文本"""
        if self.render_image:
            try:
                url = await self.text_to_image(md_text)
                yield event.image_result(url)
                return
            except Exception as e:
                logger.warning(f"图片渲染失败，回退纯文本: {e}")
        yield event.plain_result(fallback_text)

    # ── 定时推送 ──

    def _start_push_loop(self):
        """启动定时推送循环"""
        if self._push_task is not None:
            if not self._push_task.done():
                return
            try:
                exc = self._push_task.exception()
            except asyncio.CancelledError:
                exc = None
            if exc is not None:
                logger.error(f"FiveM 定时推送任务已异常退出，正在重启: {exc}")
            self._push_task = None
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
        while True:
            try:
                await asyncio.sleep(self.auto_push_interval)

                data = await self._request("/status")
                ok = data is not None and data.get("success")
                status = data.get("data") if isinstance(data, dict) else None

                # ── 记录历史数据点（无论是否有推送目标都采集） ──
                if ok and isinstance(status, dict):
                    self._record_data_point(self._safe_int(status.get("totalPlayers", 0)))

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
                    await self._broadcast_image(self._format_status_md(data), self._format_status(data))

                # ── 玩家上下线事件通知 ──
                if self.event_notify_enabled and (self.notify_player_events or self.notify_server_events) and not self.webhook_enabled and ok:
                    await self._poll_events()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"FiveM 定时推送循环异常，下一轮将继续: {e}")

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
        if ts is None:
            return "--:--"
        try:
            return datetime.fromtimestamp(float(ts), tz=timezone(timedelta(hours=8))).strftime("%H:%M")
        except (TypeError, ValueError, OSError):
            return "--:--"

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

    def _build_server_notification(self, events: list[dict]) -> tuple[str | None, bool]:
        """构建服务器事件纯文本通知。返回 (文本, 是否@全体)"""
        lines: list[str] = []
        has_at_all = False

        for ev in events:
            etype = ev.get("type")
            if etype in ("connecting", "join", "leave"):
                continue
            t_str = self._get_event_time(ev)

            if etype == "announcement":
                author = self._safe_text(ev.get("author", "txAdmin"))
                message = self._safe_text(ev.get("message", ""))
                lines.append(f"  📢 管理员公告 ({author}): {message}")

            elif etype == "shutdown":
                author = self._safe_text(ev.get("author", "txAdmin"))
                delay = self._safe_int(ev.get("delay", 0))
                message = self._safe_text(ev.get("message", ""))
                delay_sec = round(delay / 1000) if delay else 0
                line = self._apply_template(self.shutdown_template, author=author, delay=delay_sec, message=message, time=t_str, at_all="{at_all}")
                if message and "{message}" not in self.shutdown_template:
                    line += f": {message}"
                lines.append(f"  {line}")
                if "{at_all}" in self.shutdown_template:
                    has_at_all = True

            elif etype == "restart":
                seconds = self._safe_int(ev.get("secondsRemaining", 0))
                minutes = math.ceil(seconds / 60) if seconds > 0 else 0
                line = self._apply_template(self.restart_template, minutes=minutes, seconds=seconds, time=t_str, at_all="{at_all}")
                lines.append(f"  {line}")
                if "{at_all}" in self.restart_template:
                    has_at_all = True

            elif etype == "server_start":
                sn = self._safe_text(ev.get("serverName", "FiveM Server"))
                players = self._safe_int(ev.get("totalPlayers", 0))
                max_p = self._safe_int(ev.get("maxPlayers", 0))
                line = self._apply_template(self.server_start_template, server_name=sn, time=t_str, players=players, max_players=max_p, at_all="{at_all}")
                lines.append(f"  {line}")
                if "{at_all}" in self.server_start_template:
                    has_at_all = True

            elif etype == "custom":
                ctitle = self._safe_text(ev.get("title", "自定义事件"))
                message = self._safe_text(ev.get("message", ""))
                line = f"  🔔 {ctitle}"
                if message:
                    line += f": {message}"
                lines.append(line)

        if not lines:
            return None, False

        text = f"🖥️ 服务器通知 ({len(lines)} 条):\n" + "\n".join(lines)
        return text, has_at_all

    async def _broadcast_notification(self, text: str, has_at_all: bool):
        """广播服务器事件纯文本通知，支持 @全体"""
        chain = self._render_template_chain(text) if has_at_all else MessageChain().message(text)
        await self._broadcast_chain(chain)

    async def _send_alert(self):
        """发送离线告警纯文本通知"""
        text = self._apply_template(self.alert_template, count=self._fail_count, at_all="{at_all}")
        has_at_all = "{at_all}" in self.alert_template
        await self._broadcast_notification(text, has_at_all)

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
        try:
            await asyncio.sleep(self.event_buffer_seconds)
            while self._event_buffer:
                events = self._event_buffer
                self._event_buffer = []
                try:
                    await self._send_events(events)
                except Exception as e:
                    logger.error(f"FiveM 事件批量发送失败，已跳过本批次: {e}")
        except asyncio.CancelledError:
            pass

    async def _send_events(self, events: list[dict]):
        """格式化事件并广播到所有推送目标"""
        events = [ev for ev in events if isinstance(ev, dict)]
        if not events:
            return
        if self.notify_server_events:
            text, has_at_all = self._build_server_notification(events)
            if text:
                await self._broadcast_notification(text, has_at_all)
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
        try:
            site = web.TCPSite(runner, '0.0.0.0', self.webhook_port)
            await site.start()
        except Exception:
            await runner.cleanup()
            raise
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

    def _select_target_platform_id(self) -> str | None:
        try:
            platforms = self.context.platform_manager.get_insts()
            if not platforms:
                return None
            if self.default_platform_id:
                for platform in platforms:
                    pid = platform.meta().id
                    if pid == self.default_platform_id:
                        return pid
                fallback_pid = platforms[0].meta().id
                logger.warning(
                    f"FiveM 插件：未找到配置的默认平台 {self.default_platform_id}，已回退到 {fallback_pid}"
                )
                return fallback_pid
            return platforms[0].meta().id
        except Exception as e:
            logger.warning(f"FiveM 插件：获取可用平台实例失败: {e}")
            return None

    def _resolve_target(self, target: str) -> str:
        """将纯群号解析为完整 UMO 格式，已是 UMO 则直接返回"""
        if ":" in target:
            return target
        if not target.strip().isdigit():
            return target
        try:
            pid = self._select_target_platform_id()
            if pid:
                return f"{pid}:GroupMessage:{target.strip()}"
        except Exception as e:
            logger.warning(f"FiveM 插件：无法为群号 {target} 构造 UMO: {e}")
        return target

    async def _broadcast_image(self, md_text: str, fallback_text: str):
        """尝试用 text_to_image 渲染 Markdown 图片并广播，失败则回退纯文本"""
        if self.render_image:
            try:
                url = await self.text_to_image(md_text)
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
                fail_count = self._target_fail_counts.pop(target, 0)
                if fail_count > 0:
                    self._target_fail_counts[umo] = fail_count
            try:
                await self.context.send_message(umo, chain)
                self._target_fail_counts.pop(umo, None)
            except Exception as e:
                fail_count = self._target_fail_counts.get(umo, 0) + 1
                self._target_fail_counts[umo] = fail_count
                logger.error(f"消息发送失败 ({umo}, 连续失败 {fail_count} 次): {e}")

        if need_save:
            self._push_targets = resolved_targets
            self._save_push_targets()
            logger.info(f"FiveM 插件：已将纯群号自动转换为 UMO 并回写配置")
        self._target_fail_counts = {
            target: count for target, count in self._target_fail_counts.items()
            if target in resolved_targets
        }

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
        async for result in self._render_image(event, self._format_status_md(data), self._format_status(data)):
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
        players = data.get("data")
        if not isinstance(players, list):
            yield event.plain_result("❌ 服务器返回异常数据。")
            return
        if not players:
            yield event.plain_result("当前没有玩家在线。")
            return
        fallback = [f"👥 在线玩家 ({len(players)} 人):"]
        md = [f"# 👥 在线玩家 ({len(players)} 人)\n", "| ID | 名称 | 职业 | 在线时长 |", "|----|------|------|----------|"]
        for p in players:
            if not isinstance(p, dict):
                continue
            pid = self._safe_text(p.get("id", "?"))
            name = self._safe_text(p.get("name", "未知"))
            job_label = self._safe_text(p.get("jobLabel", p.get("job", "")))
            online_sec = p.get("onlineSeconds")
            duration = self._format_uptime(self._safe_int(online_sec)) if online_sec is not None else None
            suffix = f" ({duration})" if duration else ""
            fallback.append(f"  [{pid}] {name} — {job_label}{suffix}")
            md.append(f"| {self._escape_md(pid)} | {self._escape_md(name)} | {self._escape_md(job_label)} | {self._escape_md(duration or '-')} |")
        async for result in self._render_image(event, "\n".join(md), "\n".join(fallback)):
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
        if not isinstance(jobs, list) or not jobs:
            return None, "❌ 当前没有已配置的职业。"

        normalized_jobs = []
        for job in jobs:
            if not isinstance(job, dict):
                continue
            name = self._safe_text(job.get("name", "")).strip()
            if not name:
                continue
            label = self._safe_text(job.get("label", name)).strip() or name
            normalized_jobs.append({"name": name, "label": label})

        if not normalized_jobs:
            return None, "❌ 当前没有可用的职业数据。"

        kw = keyword.lower()

        # 精确匹配（name 或 label）
        for j in normalized_jobs:
            if kw == j["name"].lower() or kw == j["label"].lower():
                return j["name"], None

        # 模糊匹配（label 或 name 包含关键词）
        matches = [
            j for j in normalized_jobs
            if kw in j["label"].lower() or kw in j["name"].lower()
        ]

        if len(matches) == 1:
            return matches[0]["name"], None

        if len(matches) > 1:
            options = "\n".join(f"  • {m['label']}（{m['name']}）" for m in matches)
            return None, f"⚠️ 匹配到多个职业，请更精确地输入:\n{options}"

        # 无匹配 → 列出所有可用职业
        all_jobs = "\n".join(f"  • {j['label']}（{j['name']}）" for j in normalized_jobs)
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
        job = data.get("data")
        if not isinstance(job, dict):
            yield event.plain_result("❌ 服务器返回异常数据。")
            return
        label = self._safe_text(job.get("label", job.get("name", job_keyword)))
        online = self._safe_int(job.get("online", 0))
        players = job.get("players", [])
        if not isinstance(players, list):
            players = []
        fallback = [f"👔 {label} ({online} 人在线):"]
        md = [f"# 👔 {self._escape_md(label)} ({online} 人在线)\n"]
        if players:
            md.extend(["| ID | 名称 |", "|----|------|"])
            for p in players:
                if not isinstance(p, dict):
                    continue
                pid = self._safe_text(p.get("id", "?"))
                name = self._safe_text(p.get("name", "未知"))
                fallback.append(f"  [{pid}] {name}")
                md.append(f"| {self._escape_md(pid)} | {self._escape_md(name)} |")
        else:
            fallback.append("  当前无人在线")
            md.append("当前无人在线")
        async for result in self._render_image(event, "\n".join(md), "\n".join(fallback)):
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
        players = data.get("data")
        if not isinstance(players, list):
            yield event.plain_result("❌ 服务器返回异常数据。")
            return
        for p in players:
            if not isinstance(p, dict):
                continue
            name = self._safe_text(p.get("name", ""))
            if kw in name.lower():
                results.append({
                    "id": self._safe_text(p.get("id", "?")),
                    "name": name,
                    "job_label": self._safe_text(p.get("jobLabel", p.get("job", ""))),
                })
        fallback = [f"🔍 搜索「{keyword}」 — 匹配 {len(results)} 人:"]
        md = [f"# 🔍 搜索「{self._escape_md(keyword)}」 — 匹配 {len(results)} 人\n"]
        if results:
            md.extend(["| ID | 名称 | 职业 |", "|----|------|------|"])
            for r in results:
                fallback.append(f"  [{r['id']}] {r['name']} — {r['job_label']}")
                md.append(f"| {self._escape_md(r['id'])} | {self._escape_md(r['name'])} | {self._escape_md(r['job_label'])} |")
        else:
            fallback.append("  未找到匹配的在线玩家。")
            md.append("未找到匹配的在线玩家。")
        async for result in self._render_image(event, "\n".join(md), "\n".join(fallback)):
            yield result

    @fivem.command("查找")
    async def search_player(self, event: AstrMessageEvent, keyword: str):
        """模糊搜索在线玩家（用法: /fivem 查找 玩家名）"""
        if cd := self._check_cooldown(event):
            yield event.plain_result(cd)
            return
        async for result in self._do_search_player(event, keyword):
            yield result

    def _build_trend_data(self, history: list[dict]) -> tuple[str, list[str]] | None:
        """将历史数据点构建为趋势 Markdown（含内嵌 SVG）和纯文本行，数据不足时返回 None"""
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

        fallback = [
            f"📊 最近 {len(points)} 个数据点趋势:",
            f"  📈 峰值: {max_count} 人 ({peak_point['label']})",
            f"  📉 均值: {avg_count} 人",
            f"  📌 当前: {counts[-1]} 人",
        ]

        # 构建 SVG 图表
        chart_w, chart_h = 1060, 360
        margin_l, margin_b = 60, 40
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

        total_w = chart_w + margin_l
        svg_parts = [
            f'<svg width="{total_w}" height="{chart_h}" viewBox="0 0 {total_w} {chart_h}" xmlns="http://www.w3.org/2000/svg" style="background:#f6f8fa;border-radius:12px;border:1px solid #d1d9e0;margin-top:16px;display:block">',
            f'  <text x="8" y="24" font-size="20" fill="#656d76" font-family="sans-serif">{y_max}</text>',
            f'  <text x="8" y="{chart_h - margin_b}" font-size="20" fill="#656d76" font-family="sans-serif">0</text>',
            f'  <line x1="{margin_l}" y1="0" x2="{margin_l}" y2="{chart_h - margin_b}" stroke="#d1d9e0" stroke-width="1"/>',
            f'  <line x1="{margin_l}" y1="{chart_h - margin_b}" x2="{total_w}" y2="{chart_h - margin_b}" stroke="#d1d9e0" stroke-width="1"/>',
            f'  <polyline points="{polyline}" fill="none" stroke="#1f883d" stroke-width="3" stroke-linejoin="round"/>',
        ]
        for sp in svg_points:
            svg_parts.append(f'  <circle cx="{sp["x"]}" cy="{sp["y"]}" r="4" fill="#1f883d"/>')
        for xl in x_labels:
            svg_parts.append(f'  <text x="{xl["x"]}" y="{chart_h - 8}" font-size="18" fill="#656d76" text-anchor="middle" font-family="sans-serif">{xl["text"]}</text>')
        svg_parts.append('</svg>')
        svg_str = "\n".join(svg_parts)

        md_text = (
            f"# 📊 在线人数趋势\n\n"
            f"- 📈 峰值: **{max_count} 人** ({peak_point['label']})\n"
            f"- 📉 均值: **{avg_count} 人**\n"
            f"- 📌 当前: **{counts[-1]} 人**\n\n"
            f"{svg_str}\n"
        )
        return md_text, fallback

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
        md_text, fallback = result
        async for r in self._render_image(event, md_text, "\n".join(fallback)):
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
        loop_expected = self._needs_loop()
        loop_running = self._push_task is not None and not self._push_task.done()
        webhook_ready = not self.webhook_enabled or self._webhook_runner is not None
        event_delivery = self._describe_event_delivery()
        loop_reasons = self._describe_loop_reasons()
        loop_status = "运行中" if loop_running else ("未启用" if not loop_expected else "未运行")
        failed_targets = sum(1 for count in self._target_fail_counts.values() if count > 0)

        # ── 纯文本回退 ──
        lines = [
            "🩺 FiveM 插件自检",
            f"🔗 API /health: {'正常' if health_ok else '失败'}",
            f"📊 API /status: {'正常' if status_ok else '失败'}",
            f"📡 事件通知: {event_delivery}",
            f"🗂️ 通知范围: {self._describe_event_scope()}",
            f"📬 订阅目标: {len(self._push_targets)} 个",
            f"🙋 当前会话: {'已订阅' if current_subscribed else '未订阅'}",
            f"🧭 后台用途: {loop_reasons}",
            f"⚙️ 后台任务: {loop_status}",
        ]
        if failed_targets:
            lines.append(f"🚫 发送失败目标: {failed_targets} 个")

        if self.webhook_enabled:
            lines.append(f"🌐 Webhook 监听: {'已启动' if webhook_ready else '未启动'}")

        # ── 检查项 ──
        checks = [
            ("🔗", "API /health", "正常" if health_ok else "失败", "✅" if health_ok else "❌"),
            ("📊", "API /status", "正常" if status_ok else "失败", "✅" if status_ok else "❌"),
            ("📡", "事件通知", event_delivery, "ℹ️" if not self.event_notify_enabled else "✅"),
            ("🗂️", "通知范围", self._describe_event_scope(), "ℹ️" if not self.event_notify_enabled else "✅"),
            ("📬", "订阅目标", f"{len(self._push_targets)} 个", "ℹ️" if not self._push_targets else "✅"),
            ("🙋", "当前会话", "已订阅" if current_subscribed else "未订阅", "✅" if current_subscribed else "ℹ️"),
            ("🧭", "后台用途", loop_reasons, "ℹ️" if not loop_expected else "✅"),
            ("⚙️", "后台任务", loop_status, "✅" if (not loop_expected or loop_running) else "⚠️"),
        ]
        if failed_targets:
            checks.append(("🚫", "发送失败目标", f"{failed_targets} 个", "⚠️"))
        if self.webhook_enabled:
            checks.append(("🌐", "Webhook", "已启动" if webhook_ready else "未启动", "✅" if webhook_ready else "❌"))

        issues = []
        tips = []
        if not health_ok:
            issues.append("FiveM /health 不可达，请检查 server_url、网络与 WhitelistIPs。")
        elif not status_ok:
            issues.append("FiveM /status 未返回 success，请检查资源端状态输出是否正常。")
        if self.event_notify_enabled and not (self.notify_player_events or self.notify_server_events):
            issues.append("事件通知总开关已开启，但玩家事件和服务器事件都已关闭。")
        if loop_expected and not loop_running:
            issues.append("后台任务未运行，请检查插件初始化日志与后台循环异常。")
        if self.webhook_enabled and not webhook_ready:
            issues.append("Webhook 已启用但监听服务未启动，请检查端口占用和插件初始化日志。")
        if failed_targets:
            issues.append("存在发送失败的推送目标，请检查目标平台可用性、群会话状态或订阅目标配置。")
        if not self._push_targets:
            tips.append("当前没有任何推送目标，如需接收推送可通过 /fivem 订阅 添加。")
        elif not current_subscribed:
            tips.append("当前会话未订阅推送，如需在本群接收通知，请执行 /fivem 订阅。")
        if not self.event_notify_enabled:
            tips.append("事件通知当前已关闭，如需接收玩家动态或服务器通知，请开启 event_notify_enabled。")

        if issues:
            lines.append("")
            lines.append("⚠️ 建议关注:")
            for issue in issues:
                lines.append(f"  • {issue}")
        else:
            lines.append("")
            lines.append("✅ 未发现明显运行故障。")

        if tips:
            lines.append("")
            lines.append("💡 配置提醒:")
            for tip in tips:
                lines.append(f"  • {tip}")

        md = ["# 🩺 FiveM 插件自检\n", "| 项目 | 状态 |", "|------|------|"]
        for icon, label, value, status_icon in checks:
            md.append(f"| {icon} {label} | {status_icon} {value} |")
        if issues:
            md.append("\n> **⚠️ 建议关注:**")
            for issue in issues:
                md.append(f"> - {issue}")
        else:
            md.append("\n✅ 未发现明显运行故障。")
        if tips:
            md.append("\n> **💡 配置提醒:**")
            for tip in tips:
                md.append(f"> - {tip}")
        async for result in self._render_image(event, "\n".join(md), "\n".join(lines)):
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
            f"🧭 后台用途: {self._describe_loop_reasons()}",
        ]
        for i, target in enumerate(sorted(self._push_targets), 1):
            display = self._format_target_display(target)
            fail_count = self._target_fail_counts.get(target, 0)
            fail_suffix = f"（连续失败 {fail_count} 次）" if fail_count > 0 else ""
            if display == target:
                lines.append(f"  {i}. {display}{fail_suffix}")
            else:
                lines.append(f"  {i}. {display} → {target}{fail_suffix}")
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

        md = [
            "# 📖 FiveM 指令帮助\n",
            "## 查询类命令\n",
            "| 命令 | 说明 |",
            "|------|------|",
            "| `/fivem 状态` | 查询在线人数与职业在线 |",
            "| `/fivem 玩家` | 查询在线玩家列表 |",
            "| `/fivem 职业 <名>` | 查询指定职业在线玩家 |",
            "| `/fivem 查找 <名>` | 模糊搜索在线玩家 |",
            "| `/fivem 趋势` | 24 小时在线人数趋势图 |",
            "| `/fivem 检测` | 服务器健康检测 |",
            "| `/fivem 帮助` | 显示本帮助 |",
            "\n## 管理员命令 🔒\n",
            "| 命令 | 说明 |",
            "|------|------|",
            "| `/fivem 自检` | 检查 API、Webhook 与订阅状态 |",
            "| `/fivem 订阅` | 订阅当前会话接收推送 |",
            "| `/fivem 退订` | 取消推送订阅 |",
            "| `/fivem 订阅列表` | 查看所有推送目标 |",
            "| `/fivem 公告 <内容>` | 发送公告到游戏内 |",
            "| `/fivem 广播 <内容>` | 发送聊天广播到游戏内 |",
            "| `/fivem 踢人 <目标>` | 远程踢出游戏内玩家 |",
        ]
        async for result in self._render_image(event, "\n".join(md), "\n".join(lines)):
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
            yield event.plain_result("📊 历史数据不足，至少需要 2 个数据点才能生成趋势图。")
            return
        md_text, fallback = result
        async for r in self._render_image(event, md_text, "\n".join(fallback)):
            yield r
