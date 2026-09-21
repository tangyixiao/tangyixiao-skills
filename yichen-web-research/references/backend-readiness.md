# 后端能力与离线体检

仅在规划多后端、跨平台、登录态或对应专用后端时读取相关段落。此文不扩大 SKILL.md 和子 Skill 的授权范围。

## 后端定位

- AnySearch：公共网页、批量搜索、垂直搜索和搜索候选的轻量原文核验。
- Firecrawl：只作显式的有界站点 Map、当前 AnySearch 候选的单页 Scrape 回退，以及用户明确要求的有界公开站点归档；不进入默认搜索链。
- 知乎兼容搜索：只作显式 `zhihu` 平台后端，由 `$yichen-unified-search` 的白名单适配器调用已配置 CLI 进行站内搜索或显式热榜发现；不替换 AnySearch 的普通网页搜索。`global_search`、知乎直答（`zhida`/`answer`）与 `me` 账号命令不进入总路由。
- 平台原生 CLI/API：GitHub、YouTube、B站等结构化公共搜索。
- OpenCLI：仅作为部分平台的只读适配器，不是本体系的强制依赖或总入口。
- 本地平台 Skill：已知链接解析、媒体下载、公众号正文和批量归档。
- 浏览器或账号登录态：小红书、抖音的有界公开只读搜索，以及微博匿名访问门失败后的一次有界只读回退，可按子 Skill 的固定限速规则自动复用现有会话，无需逐次授权；其他登录态读取按具体目标取得当轮授权。

不得因为某个后端已安装或浏览器已登录，就绕过子 Skill 的范围、限速和高风险授权门。

## 多后端体检

跨平台或登录态任务开始前运行：

```bash
python3 ~/.agents/skills/yichen-web-research/scripts/doctor_yichen.py
```

OpenCLI 相关任务再运行：

```bash
opencli doctor
```

体检只证明后端和安全契约可识别。它不授权任何写操作或私人数据读取；有界公开只读会话复用是否允许，以当前子 Skill 的固定范围和限速规则为准。

知乎通道缺少已配置的兼容 CLI 或 Keychain 认证时只报告 `warn`，不把整个研究家族误判为结构损坏；统一搜索侧 `zhihu_adapter.py` 缺失才属于结构错误。该通道固定 `default_backend=false`、`network_probe_performed=false`、`public_commands_only=true`、`personal_commands_exposed=false`。

## 专用后端凭证与命令边界

- Firecrawl API Key 只从 `FIRECRAWL_API_KEY` 或本机私有文件 `~/.config/agent-secrets/firecrawl-api-key` 读取；doctor 只报告是否存在，不读取、不打印，也不发起计费探针。
- 知乎兼容 CLI 只允许经统一搜索适配器暴露公开 `search`/`hot` 能力；不得暴露 `global_search`、`zhida`/`answer` 或任何 `me` 私人命令。doctor 只运行离线 `version`、`capabilities`、`auth status` 元数据检查，子进程移除 `ZHIHU_ACCESS_SECRET`，只报告 Keychain 是否配置，不透传 stdout、stderr、Secret，也不发送搜索或热榜请求。

公开版不独立认证第三方 CLI 的官方来源。X 登录态后备须取得当轮明确授权并传 `allow_authenticated_fallback=true`，保持公共插件的授权检查。
