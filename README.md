# astrbot_plugin_uptime_kuma

AstrBot 的 Uptime Kuma 状态查询插件。触发指令或关键词时抓取指定状态页，返回监控项在线情况、置顶通知与维护公告，并支持图片/文本回复、按聊天流设置查询项和黑白名单。

## 功能

- 查询 Uptime Kuma 状态页：监控项状态、Ping、标签、状态统计
- 输出置顶事件（incidents）与维护公告（maintenance）
- 图片或文本回复，图片渲染失败自动回退文本
- 支持多个关键词，每个关键词绑定查询目标（整条消息仅包含关键词时触发）
- 按聊天流（UMO）设置查询项，另有全局默认查询项
- 用户/群聊黑白名单，默认白名单模式
- WebUI 插件可视化“状态面板”，实时查看全部项目状态

## 安装

1. 将本目录放入 AstrBot 的 `data/plugins/`。
2. 在 AstrBot WebUI 的插件页启用插件。
3. 打开插件配置，填写 Uptime Kuma 地址与项目 slug。

## 配置

在 WebUI 插件配置页填写：

| 配置项 | 说明 |
| --- | --- |
| `uptime_kuma_url` | Uptime Kuma 站点根地址，如 `https://status.example.com`，末尾不要加 `/`，不要填 `/status/xxx` |
| `projects` | 可查询项目（状态页 slug）列表，对应 `/status/<slug>` 中的 slug |
| `default_targets` | 全局默认查询项；会话未单独配置时使用 |
| `session_targets` | 按聊天流设置的查询项：选择会话 + 填写该项目下的 slug 列表 |
| `keyword_rules` | 关键词规则：关键词 + 目标项目 + 输出方式（跟随全局/文本/图片） |
| `default_output_mode` | 默认输出方式：文本或图片 |
| `show_ping` | 是否显示 Ping |
| `show_tags` | 是否显示监控项标签 |
| `show_incidents` | 是否输出置顶通知 |
| `show_maintenance` | 是否输出维护公告 |
| `request_timeout` | 单次请求超时（秒），默认 10 |
| `access_mode` | `whitelist`（默认，仅白名单可用）或 `blacklist`（除黑名单外可用） |
| `user_whitelist` / `user_blacklist` | 用户白/黑名单 |
| `group_whitelist` / `group_blacklist` | 群聊白/黑名单 |
| `denied_message` | 指令被拒绝时的提示；留空则静默，关键词触发始终静默 |

## 指令

```
/uptime                    查询当前会话的查询项（无则使用全局默认）
/uptime <项目> [更多项目]   查询指定项目
/uptime list               列出可查询项目
/uptime <项目> -i          本次以图片回复
/uptime <项目> -t          本次以文本回复
```

指令别名：`/健康`、`/ukp`。

项目名大小写不敏感；多个项目可用空格、逗号或顿号分隔。

## 关键词触发

在 `keyword_rules` 中添加规则，例如：

- 关键词 `服务器状态`，目标 `aaa`
- 关键词 `ping`，目标 `bbb`

配置后发送 `/服务器状态`（`/` 为 AstrBot 的唤醒前缀）或群聊中 `@机器人 服务器状态`，会返回 aaa 项目状态。关键词后附带其他内容不会触发，需要使用 `/uptime <项目>`。

## 按聊天流设置查询项

在 `session_targets` 中添加条目：

1. 在“聊天流”选择器中选择会话；
2. 填写该会话要查询的项目 slug 列表。

查询优先级：指令参数 > 关键词规则 > 会话查询项 > 全局默认查询项。

## 黑白名单

判定顺序：

1. 用户黑名单 → 拒绝
2. 用户白名单 → 允许
3. 群聊黑名单 → 拒绝（白名单用户已在第 2 步放行）
4. 群聊白名单 → 允许（黑名单用户已在第 1 步拒绝）
5. 白名单模式 → 拒绝；黑名单模式 → 允许

说明：

- 私聊忽略群聊名单。
- 同一用户同时在用户白名单与黑名单时，**黑名单优先**。
- 默认白名单模式下若白名单为空，则所有人不可用。

## 图片 / 文本

- 默认输出方式由 `default_output_mode` 决定。
- 指令可用 `-i` / `--image`、`-t` / `--text` 临时覆盖。
- 关键词规则可单独指定输出方式。
- 图片通过 AstrBot 文转图服务渲染；失败时自动回退文本。

## 可视化状态面板

在 AstrBot WebUI 的插件详情页打开“状态面板”，可查看：

- 全部项目的实时状态、监控项、Ping 与标签
- 置顶通知与维护公告
- 默认查询项、会话查询项、关键词规则与黑白名单数量

面板支持手动刷新、30 秒/60 秒/5 分钟自动刷新、按项目筛选，并适配亮/暗主题。配置修改仍在插件配置页完成。

## 平台适配

已适配 `aiocqhttp`、`qq_official`、`qq_official_webhook`：

- 文本使用纯文本消息，图片使用本地渲染结果，由各适配器转换为平台所需格式。
- `qq_official` / `qq_official_webhook` 的用户 ID 为 openid、群 ID 为 group_openid，黑白名单请填写事件中的实际 ID。

## 获取项目 slug

打开 Uptime Kuma 状态页，地址形如 `https://status.example.com/status/<slug>`，其中 `<slug>` 即项目名。将 slug 填入 `projects`。
