from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

import aiohttp

from astrbot.api import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.api.web import error_response, json_response, request

PLUGIN_NAME = "astrbot_plugin_uptime_kuma"
_COMMAND_NAMES = ("uptime", "健康", "ukp")
_STATUS_MAP: dict[object, tuple[str, str, str]] = {
    0: ("🔴", "异常", "down"),
    1: ("🟢", "在线", "up"),
    2: ("🟡", "等待", "pending"),
    3: ("🔵", "维护", "maintenance"),
}
_UNKNOWN_STATUS = ("❓", "未知", "unknown")
_INCIDENT_STYLE_MAP = {
    "info": "信息",
    "warning": "警告",
    "danger": "危险",
    "primary": "重要",
}
_PLUGIN_CONFIG: AstrBotConfig | None = None


def _clean_list(raw: object) -> list[str]:
    """Normalize a string list from plugin config.

    Args:
        raw: Raw config value, usually a list of strings.

    Returns:
        Non-empty, stripped, de-duplicated strings preserving order.
    """
    if isinstance(raw, str):
        values = [raw]
    elif isinstance(raw, list | tuple | set):
        values = list(raw)
    else:
        return []
    result: list[str] = []
    for item in values:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _is_allowed(event: AstrMessageEvent, config: AstrBotConfig) -> bool:
    """Check whether the event is allowed by the access lists.

    Args:
        event: Incoming message event.
        config: Plugin configuration.

    Returns:
        Whether the sender and group may use the plugin.
    """
    user_id = str(event.get_sender_id() or "").strip()
    group_id = str(event.get_group_id() or "").strip()
    user_whitelist = set(_clean_list(config.get("user_whitelist")))
    user_blacklist = set(_clean_list(config.get("user_blacklist")))
    group_whitelist = set(_clean_list(config.get("group_whitelist")))
    group_blacklist = set(_clean_list(config.get("group_blacklist")))
    mode = str(config.get("access_mode") or "whitelist").strip().lower()

    if user_id and user_id in user_blacklist:
        return False
    if user_id and user_id in user_whitelist:
        return True
    if group_id:
        if group_id in group_blacklist:
            return False
        if group_id in group_whitelist:
            return True
    return mode == "blacklist"


def _keyword_rule_in_scope(rule: dict, umo: str) -> bool:
    """Check whether a keyword rule applies to a chat stream.

    Args:
        rule: Keyword rule config entry.
        umo: Unified message origin of the current chat.

    Returns:
        Whether the rule is enabled for the chat stream.
    """
    mode = str(rule.get("scope_mode") or "all").strip().lower()
    sessions = set(_clean_list(rule.get("sessions")))
    if mode == "none":
        return False
    if mode == "include":
        return umo in sessions
    if mode == "exclude":
        return umo not in sessions
    return True


def _find_keyword_rule(config: AstrBotConfig, message: str, umo: str) -> dict | None:
    """Find the first keyword rule matching the message and chat stream.

    Args:
        config: Plugin configuration.
        message: Raw message text.
        umo: Unified message origin of the current chat.

    Returns:
        The matching rule, or None.
    """
    folded = (message or "").strip().casefold()
    if not folded:
        return None
    for rule in config.get("keyword_rules") or []:
        if not isinstance(rule, dict):
            continue
        keyword = str(rule.get("keyword") or "").strip().casefold()
        if keyword and keyword == folded and _keyword_rule_in_scope(rule, umo):
            return rule
    return None


def _format_epoch_ms(value: object) -> str:
    """Format a millisecond timestamp as local time.

    Args:
        value: Millisecond timestamp.

    Returns:
        Formatted local time, or an empty string when invalid.
    """
    try:
        return datetime.fromtimestamp(float(value) / 1000).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def _format_datetime_text(value: object) -> str:
    """Format an Uptime Kuma UTC datetime string in local time.

    Args:
        value: UTC datetime string such as ``2026-11-24 10:00:00``.

    Returns:
        Local formatted time, or the original text when parsing fails.
    """
    if not value:
        return ""
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
            return parsed.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return text


def _describe_error(slug: str, exc: BaseException) -> str:
    """Convert a fetch exception into a user-facing message.

    Args:
        slug: Status page slug.
        exc: Raised exception.

    Returns:
        Readable error description.
    """
    text = str(exc)
    if "HTTP 404" in text:
        return f"状态页不存在或未公开（{slug}）"
    if isinstance(exc, asyncio.TimeoutError | TimeoutError):
        return "请求超时"
    if isinstance(exc, aiohttp.ClientError):
        return f"网络错误：{text}"
    return f"查询失败：{text}"


class KeywordTriggerFilter(filter.CustomFilter):
    """Activate the keyword handler only for exact keyword messages."""

    def filter(self, event: AstrMessageEvent, cfg: AstrBotConfig) -> bool:
        config = _PLUGIN_CONFIG
        if config is None:
            return False
        rule = _find_keyword_rule(
            config, event.get_message_str(), event.unified_msg_origin
        )
        if rule is None:
            return False
        return _is_allowed(event, config)


@register(
    "astrbot_plugin_uptime_kuma",
    "CSSQY",
    "Uptime Kuma 状态查询插件",
    "1.0.0",
    "https://github.com/CSSQY/astrbot_plugin_uptime_kuma",
)
class UptimeKumaPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        global _PLUGIN_CONFIG
        _PLUGIN_CONFIG = config

        self._card_template = ""
        try:
            self._card_template = (
                Path(__file__).parent / "templates" / "status_card.html"
            ).read_text(encoding="utf-8")
        except OSError as exc:
            self.logger.warning(f"Failed to load status card template: {exc}")

        context.register_web_api(
            f"/{PLUGIN_NAME}/overview",
            self.page_overview,
            ["GET"],
            "Uptime Kuma status overview for the plugin view",
        )

    async def initialize(self) -> None:
        """Validate configuration and warn about duplicated keywords."""
        if not self._is_configured():
            self.logger.warning(
                "Uptime Kuma plugin is not configured. "
                "Set uptime_kuma_url and projects in the plugin config.",
            )
            return

        seen: set[str] = set()
        duplicates: set[str] = set()
        keyword_count = 0
        for rule in self.config.get("keyword_rules") or []:
            if not isinstance(rule, dict):
                continue
            keyword = str(rule.get("keyword") or "").strip().casefold()
            if not keyword:
                continue
            keyword_count += 1
            if str(rule.get("scope_mode") or "all").strip().lower() != "all":
                continue
            if keyword in seen:
                duplicates.add(keyword)
            seen.add(keyword)
        if duplicates:
            self.logger.warning(
                "Duplicated keyword rules ignored after the first one: "
                + ", ".join(sorted(duplicates)),
            )
        self.logger.info(
            "Uptime Kuma plugin ready: site=%s, projects=%d, keywords=%d",
            self._base_url(),
            len(self._projects()),
            keyword_count,
        )

    def _base_url(self) -> str:
        """Return the normalized Uptime Kuma base URL."""
        return str(self.config.get("uptime_kuma_url") or "").strip().rstrip("/")

    def _projects(self) -> list[str]:
        """Return the configured project slugs."""
        return _clean_list(self.config.get("projects"))

    def _is_configured(self) -> bool:
        """Return whether the base URL and project list are usable."""
        base_url = self._base_url()
        parsed = urlparse(base_url)
        return bool(
            base_url
            and parsed.scheme in ("http", "https")
            and parsed.netloc
            and self._projects()
        )

    def _config_error_message(self) -> str:
        """Return a configuration hint for chat replies."""
        base_url = self._base_url()
        if not base_url:
            return "❌ 插件尚未配置：请先在插件配置中填写 uptime_kuma_url。"
        parsed = urlparse(base_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return (
                "❌ uptime_kuma_url 无效，请填写完整地址，"
                "例如 https://status.example.com。"
            )
        return "❌ 插件尚未配置：请在 projects 中添加至少一个状态页 slug。"

    def _validate_slug(self, slug: str) -> str | None:
        """Return the configured canonical slug for a user-provided value."""
        raw = str(slug or "").strip()
        if not raw:
            return None
        for project in self._projects():
            if project.casefold() == raw.casefold():
                return project
        return None

    def _resolve_targets(self, raw_targets: object) -> tuple[list[str], list[str]]:
        """Validate and normalize a list of requested project slugs."""
        valid: list[str] = []
        invalid: list[str] = []
        for item in _clean_list(raw_targets):
            slug = self._validate_slug(item)
            if slug is None:
                invalid.append(item)
            elif slug not in valid:
                valid.append(slug)
        return valid, invalid

    def _resolve_default_targets(self, umo: str) -> list[str]:
        """Resolve targets for a chat stream, falling back to global defaults."""
        for entry in self.config.get("session_targets") or []:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("session") or "").strip() != umo:
                continue
            targets = _clean_list(entry.get("targets"))
            if targets:
                return targets
        return _clean_list(self.config.get("default_targets"))

    def _format_project_list(self) -> str:
        """Return the configured project list for chat replies."""
        projects = self._projects()
        if not projects:
            return "尚未配置可查询项目，请在插件配置的 projects 中添加状态页 slug。"
        return "可查询项目：\n" + "\n".join(f"- {item}" for item in projects)

    def _parse_command_args(
        self, event: AstrMessageEvent
    ) -> tuple[list[str], str | None, bool]:
        """Parse targets and output flags from a command message.

        Args:
            event: Incoming command event.

        Returns:
            A tuple of targets, output mode override, and whether ``list`` was
            requested.
        """
        raw = (event.get_message_str() or "").strip()
        rest = raw
        for name in sorted(_COMMAND_NAMES, key=len, reverse=True):
            lowered_raw = raw.casefold()
            lowered_name = name.casefold()
            if lowered_raw == lowered_name:
                rest = ""
                break
            if lowered_raw.startswith(lowered_name):
                suffix = raw[len(name) :]
                if suffix[:1].isspace() or suffix[:1] in ",，、":
                    rest = suffix.strip()
                    break

        if rest.casefold() in ("list", "列表", "ls"):
            return [], None, True

        targets: list[str] = []
        output_mode: str | None = None
        for token in re.split(r"[\s,，、]+", rest):
            if not token:
                continue
            lowered = token.casefold()
            if lowered in ("-i", "--image"):
                output_mode = "image"
            elif lowered in ("-t", "--text"):
                output_mode = "text"
            else:
                targets.append(token)
        return targets, output_mode, False

    async def _fetch_json(self, session: aiohttp.ClientSession, url: str) -> dict:
        """Fetch a JSON object from an Uptime Kuma API endpoint."""
        async with session.get(url) as response:
            if response.status != 200:
                raise RuntimeError(f"HTTP {response.status}")
            data = await response.json(content_type=None)
            if not isinstance(data, dict):
                raise RuntimeError("响应格式不是 JSON 对象")
            return data

    async def _fetch_project(self, session: aiohttp.ClientSession, slug: str) -> dict:
        """Fetch and normalize one project's status page data."""
        base_url = self._base_url()
        encoded_slug = quote(slug, safe="")
        project: dict = {
            "slug": slug,
            "title": slug,
            "error": "",
            "stats": [],
            "groups": [],
            "incidents": [],
            "maintenance": [],
        }

        main_data, heartbeat_data = await asyncio.gather(
            self._fetch_json(session, f"{base_url}/api/status-page/{encoded_slug}"),
            self._fetch_json(
                session,
                f"{base_url}/api/status-page/heartbeat/{encoded_slug}",
            ),
            return_exceptions=True,
        )
        if isinstance(main_data, BaseException):
            project["error"] = _describe_error(slug, main_data)
            return project
        if isinstance(heartbeat_data, BaseException):
            self.logger.warning(
                "Failed to fetch heartbeat for %s: %s", slug, heartbeat_data
            )
            heartbeat_data = {}

        page_config = main_data.get("config")
        if isinstance(page_config, dict):
            title = str(page_config.get("title") or "").strip()
            if title:
                project["title"] = title

        heartbeat_list = heartbeat_data.get("heartbeatList")
        if not isinstance(heartbeat_list, dict):
            heartbeat_list = {}

        show_ping = bool(self.config.get("show_ping", True))
        show_tags = bool(self.config.get("show_tags", True))
        counts: dict[object, int] = {0: 0, 1: 0, 2: 0, 3: 0, "unknown": 0}

        public_groups = main_data.get("publicGroupList")
        if not isinstance(public_groups, list):
            public_groups = []
        for group in public_groups:
            if not isinstance(group, dict):
                continue
            monitors: list[dict] = []
            raw_monitors = group.get("monitorList")
            if not isinstance(raw_monitors, list):
                raw_monitors = []
            for monitor in raw_monitors:
                if not isinstance(monitor, dict):
                    continue
                monitor_id = str(monitor.get("id") or "")
                beats = heartbeat_list.get(monitor_id) or []
                latest = beats[-1] if isinstance(beats, list) and beats else {}
                if not isinstance(latest, dict):
                    latest = {}
                status_code = latest.get("status")
                if isinstance(status_code, str) and status_code.strip().isdigit():
                    status_code = int(status_code.strip())
                if not isinstance(status_code, int | str):
                    status_code = None
                icon, label, status_class = _STATUS_MAP.get(
                    status_code, _UNKNOWN_STATUS
                )
                counts[status_code if status_code in counts else "unknown"] += 1

                tag = ""
                tags = monitor.get("tags")
                if show_tags and isinstance(tags, list) and tags:
                    first_tag = tags[0]
                    if isinstance(first_tag, dict):
                        tag = str(first_tag.get("name") or "").strip()
                    else:
                        tag = str(first_tag or "").strip()

                ping = ""
                ping_value = latest.get("ping")
                if show_ping and ping_value is not None:
                    ping = f"{ping_value} ms"

                monitors.append(
                    {
                        "name": str(monitor.get("name") or monitor_id),
                        "tag": tag,
                        "icon": icon,
                        "label": label,
                        "status_class": status_class,
                        "status_code": status_code,
                        "ping": ping,
                    }
                )
            if monitors:
                project["groups"].append(
                    {"name": str(group.get("name") or ""), "monitors": monitors}
                )

        stats: list[dict] = []
        for status_key in (1, 0, 2, 3, "unknown"):
            count = counts.get(status_key, 0)
            if not count:
                continue
            if status_key == "unknown":
                icon, label, status_class = _UNKNOWN_STATUS
            else:
                icon, label, status_class = _STATUS_MAP[status_key]
            stats.append(
                {
                    "icon": icon,
                    "label": label,
                    "count": count,
                    "status_class": status_class,
                }
            )
        project["stats"] = stats

        if self.config.get("show_incidents", True):
            raw_incidents = main_data.get("incidents")
            if not isinstance(raw_incidents, list):
                raw_incidents = main_data.get("incidentList")
            if not isinstance(raw_incidents, list):
                single = main_data.get("incident")
                raw_incidents = [single] if single else []
            incidents: list[dict] = []
            for incident in raw_incidents:
                if not isinstance(incident, dict):
                    continue
                style = str(incident.get("style") or "info").strip().lower()
                incidents.append(
                    {
                        "label": _INCIDENT_STYLE_MAP.get(
                            style, style.upper() or "信息"
                        ),
                        "status_class": (
                            style
                            if style in ("info", "warning", "danger", "primary")
                            else "info"
                        ),
                        "title": str(incident.get("title") or "无标题"),
                        "content": str(incident.get("content") or "").strip(),
                        "updated": _format_datetime_text(
                            incident.get("lastUpdatedDate")
                            or incident.get("createdDate")
                        ),
                    }
                )
            project["incidents"] = incidents

        if self.config.get("show_maintenance", True):
            maintenance_list = main_data.get("maintenanceList")
            if not isinstance(maintenance_list, list):
                maintenance_list = []
            maintenance_items: list[dict] = []
            for item in maintenance_list:
                if not isinstance(item, dict):
                    continue
                start = _format_epoch_ms(item.get("startDate"))
                end = _format_epoch_ms(item.get("endDate"))
                if start and end:
                    time_text = f"{start} ~ {end}"
                elif start:
                    time_text = f"开始于 {start}"
                elif end:
                    time_text = f"结束于 {end}"
                elif item.get("cron"):
                    time_text = f"cron: {item.get('cron')}"
                else:
                    time_text = ""
                maintenance_items.append(
                    {
                        "title": str(item.get("title") or "无标题"),
                        "description": str(item.get("description") or "").strip(),
                        "time": time_text,
                    }
                )
            project["maintenance"] = maintenance_items

        return project

    async def _collect_projects(self, slugs: list[str]) -> list[dict]:
        """Fetch all requested projects concurrently."""
        try:
            timeout_seconds = max(1, int(self.config.get("request_timeout") or 10))
        except (TypeError, ValueError):
            timeout_seconds = 10
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
            return await asyncio.gather(
                *(self._fetch_project(session, slug) for slug in slugs)
            )

    def _render_text(self, projects: list[dict]) -> str:
        """Render project data as plain text for chat replies."""
        if not projects:
            return "没有可展示的项目。"
        lines: list[str] = []
        for project in projects:
            if lines:
                lines.append("")
            if project.get("error"):
                lines.append(f"❌ {project['slug']}：{project['error']}")
                continue
            lines.append(f"📊 {project['title']}（{project['slug']}）")
            stats = project.get("stats") or []
            if stats:
                lines.append(
                    "统计："
                    + "  ".join(
                        f"{item['icon']} {item['label']} {item['count']}"
                        for item in stats
                    )
                )
            for group in project.get("groups") or []:
                lines.append(f"—— {group.get('name') or '监控项'} ——")
                for monitor in group.get("monitors") or []:
                    tag = f"[{monitor['tag']}] " if monitor.get("tag") else ""
                    ping = f" {monitor['ping']}" if monitor.get("ping") else ""
                    lines.append(
                        f"{tag}{monitor['name']} "
                        f"{monitor['icon']} {monitor['label']}{ping}"
                    )
            incidents = project.get("incidents") or []
            if incidents:
                lines.append("—— 置顶通知 ——")
                for incident in incidents:
                    lines.append(f"📣【{incident['label']}】{incident['title']}")
                    if incident.get("content"):
                        lines.append(incident["content"])
                    if incident.get("updated"):
                        lines.append(f"🕰 更新于 {incident['updated']}")
            maintenance_items = project.get("maintenance") or []
            if maintenance_items:
                lines.append("—— 维护公告 ——")
                for item in maintenance_items:
                    lines.append(f"🔧 {item['title']}")
                    if item.get("description"):
                        lines.append(item["description"])
                    if item.get("time"):
                        lines.append(f"🕐 {item['time']}")
        return "\n".join(lines)

    def _view_settings(self) -> dict:
        """Build the configuration summary shown by the plugin view."""
        session_targets = []
        for entry in self.config.get("session_targets") or []:
            if not isinstance(entry, dict):
                continue
            session_targets.append(
                {
                    "session": str(entry.get("session") or "").strip(),
                    "targets": _clean_list(entry.get("targets")),
                }
            )

        keyword_rules = []
        for rule in self.config.get("keyword_rules") or []:
            if not isinstance(rule, dict):
                continue
            keyword_rules.append(
                {
                    "keyword": str(rule.get("keyword") or "").strip(),
                    "targets": _clean_list(rule.get("targets")),
                    "output_mode": str(rule.get("output_mode") or "default"),
                    "scope_mode": str(rule.get("scope_mode") or "all"),
                    "scope_count": len(_clean_list(rule.get("sessions"))),
                }
            )

        return {
            "default_targets": _clean_list(self.config.get("default_targets")),
            "session_targets": session_targets,
            "keyword_rules": keyword_rules,
            "default_output_mode": str(
                self.config.get("default_output_mode") or "text"
            ),
            "access_mode": str(self.config.get("access_mode") or "whitelist"),
            "user_whitelist": len(_clean_list(self.config.get("user_whitelist"))),
            "user_blacklist": len(_clean_list(self.config.get("user_blacklist"))),
            "group_whitelist": len(_clean_list(self.config.get("group_whitelist"))),
            "group_blacklist": len(_clean_list(self.config.get("group_blacklist"))),
        }

    async def page_overview(self):
        """Return live status data for the plugin view."""
        available = self._projects()
        settings = self._view_settings()
        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if not self._is_configured():
            return json_response(
                {
                    "configured": False,
                    "message": "请先在插件配置中填写 uptime_kuma_url 与 projects",
                    "site": self._base_url(),
                    "generated_at": generated_at,
                    "available_projects": available,
                    "selected_projects": [],
                    "projects": [],
                    "summary": {
                        "projects": 0,
                        "monitors": 0,
                        "up": 0,
                        "down": 0,
                        "pending": 0,
                        "maintenance": 0,
                        "unknown": 0,
                    },
                    "settings": settings,
                }
            )

        raw_projects = str(request.query.get("projects", "") or "").strip()
        if raw_projects:
            selected, invalid = self._resolve_targets(
                re.split(r"[\s,，、]+", raw_projects)
            )
            if invalid:
                return error_response(
                    "未配置的项目：" + ", ".join(invalid), status_code=400
                )
        else:
            selected = available

        try:
            projects = await self._collect_projects(selected)
        except Exception as exc:
            self.logger.error(f"Failed to query Uptime Kuma for view: {exc}")
            return error_response(f"查询失败：{exc}", status_code=502)

        summary = {
            "projects": len(projects),
            "monitors": 0,
            "up": 0,
            "down": 0,
            "pending": 0,
            "maintenance": 0,
            "unknown": 0,
        }
        key_by_status = {1: "up", 0: "down", 2: "pending", 3: "maintenance"}
        for project in projects:
            for group in project.get("groups") or []:
                for monitor in group.get("monitors") or []:
                    summary["monitors"] += 1
                    key = key_by_status.get(monitor.get("status_code"), "unknown")
                    summary[key] += 1

        return json_response(
            {
                "configured": True,
                "message": "",
                "site": self._base_url(),
                "generated_at": generated_at,
                "available_projects": available,
                "selected_projects": selected,
                "projects": projects,
                "summary": summary,
                "settings": settings,
            }
        )

    async def _reply(
        self, event: AstrMessageEvent, projects: list[dict], output_mode: str
    ):
        """Send query results as an image when possible, otherwise as text."""
        if output_mode == "image" and self._card_template:
            try:
                rendered = await self.html_render(
                    self._card_template,
                    {
                        "site": self._base_url(),
                        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "projects": projects,
                    },
                    return_url=False,
                    options={
                        "type": "jpeg",
                        "quality": 85,
                        "full_page": True,
                    },
                    umo=event.unified_msg_origin,
                )
                if rendered:
                    yield event.image_result(rendered)
                    event.stop_event()
                    return
            except Exception as exc:
                self.logger.warning(f"Failed to render status image: {exc}")

        yield event.plain_result(self._render_text(projects)).use_t2i(False)
        event.stop_event()

    @filter.command("uptime", alias={"健康", "ukp"})
    async def uptime(self, event: AstrMessageEvent):
        """Query Uptime Kuma status pages for the current chat."""
        if not _is_allowed(event, self.config):
            denied_message = str(self.config.get("denied_message") or "").strip()
            if denied_message:
                yield event.plain_result(denied_message).use_t2i(False)
            event.stop_event()
            return

        if not self._is_configured():
            yield event.plain_result(self._config_error_message()).use_t2i(False)
            event.stop_event()
            return

        raw_targets, output_override, list_requested = self._parse_command_args(event)
        if list_requested:
            yield event.plain_result(self._format_project_list()).use_t2i(False)
            event.stop_event()
            return

        if raw_targets:
            targets, invalid = self._resolve_targets(raw_targets)
            if invalid:
                yield event.plain_result(
                    "未找到项目："
                    + ", ".join(invalid)
                    + "\n"
                    + self._format_project_list()
                ).use_t2i(False)
                event.stop_event()
                return
        else:
            targets, invalid = self._resolve_targets(
                self._resolve_default_targets(event.unified_msg_origin)
            )
            if invalid:
                yield event.plain_result(
                    "会话查询项包含未配置的项目："
                    + ", ".join(invalid)
                    + "\n"
                    + self._format_project_list()
                ).use_t2i(False)
                event.stop_event()
                return
            if not targets:
                yield event.plain_result(
                    "当前会话没有设置查询项，请先配置 session_targets 或 "
                    "default_targets，或使用 /uptime <项目> 查询。\n"
                    + self._format_project_list()
                ).use_t2i(False)
                event.stop_event()
                return

        try:
            projects = await self._collect_projects(targets)
        except Exception as exc:
            self.logger.error(f"Failed to query Uptime Kuma: {exc}")
            yield event.plain_result(f"❌ 查询失败：{exc}").use_t2i(False)
            event.stop_event()
            return

        output_mode = (
            output_override
            or str(self.config.get("default_output_mode") or "text").strip().lower()
        )
        async for result in self._reply(event, projects, output_mode):
            yield result

    @filter.custom_filter(KeywordTriggerFilter)
    async def keyword_query(self, event: AstrMessageEvent):
        """Query the target project bound to an exact keyword message."""
        rule = _find_keyword_rule(
            self.config, event.get_message_str(), event.unified_msg_origin
        )
        if rule is None:
            event.stop_event()
            return

        if not self._is_configured():
            yield event.plain_result(self._config_error_message()).use_t2i(False)
            event.stop_event()
            return

        targets, invalid = self._resolve_targets(rule.get("targets"))
        if invalid or not targets:
            message = "关键词规则未配置可查询项目。"
            if invalid:
                message = "关键词规则包含未配置的项目：" + ", ".join(invalid)
            yield event.plain_result(
                message + "\n" + self._format_project_list()
            ).use_t2i(False)
            event.stop_event()
            return

        rule_mode = str(rule.get("output_mode") or "default").strip().lower()
        if rule_mode not in ("text", "image"):
            rule_mode = None
        output_mode = (
            rule_mode
            or str(self.config.get("default_output_mode") or "text").strip().lower()
        )
        try:
            projects = await self._collect_projects(targets)
        except Exception as exc:
            self.logger.error(f"Failed to query Uptime Kuma: {exc}")
            yield event.plain_result(f"❌ 查询失败：{exc}").use_t2i(False)
            event.stop_event()
            return
        async for result in self._reply(event, projects, output_mode):
            yield result
