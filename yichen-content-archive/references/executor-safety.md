# 执行器安全与防覆盖

选择目标执行器后、首次调用前，只读取该脚本的同名小节。通用授权和输入限制仍以 SKILL.md 为准；这些小节保留各平台的非显然执行约束。

只使用本 Skill `scripts/` 下的安全执行器，不直接调用旧同名脚本：

## xiaohongshu_fetch.py

只接受小红书已知 HTTPS 链接，默认匿名抓取并优先解析 `window.__INITIAL_STATE__`，失败时回退网页 meta；输出目录存在时自动创建 `-run-N` 新目录。只有当前目标获当轮登录态授权后才可显式传 `--use-cookie`。

## douyin_download.py

只接受抖音已知 HTTPS 链接，使用 Playwright 获取目标视频详情；`--metadata-only` 不下载视频。视频或相邻 metadata 已存在时自动创建 `-run-N` 新文件名。

## weibo_known_url.py

只接受微博公开单条 URL；把 `/u/<uid>?layerid=<id>` 规范为 `https://m.weibo.cn/detail/<id>` 后再调用 `yt-dlp`。固定忽略用户配置、禁用 Cookie 输入、禁止播放列表和覆盖，下载只选择同时含音视频的单文件 MP4；输出排他新 run 目录，不持久化临时签名媒体 URL。

## x_known_url.py

只接受 `x.com`/`twitter.com` 的 status 或 `/i/article/` URL；status 返回内嵌 `article` 对象时自动判定为 Article，只有直接输入 `/i/article/<ID>` 时才在 FxTwitter 搜索结果中精确匹配 `article.id` 定位父推文。这属于解析已知对象，不得扩展其他候选。默认不使用任何登录态；匿名不完整时仅输出授权回退计划。

## known_media_download.py

只接受用户明确给出的单条公开 HTTPS URL。X 只从 `x_known_url.py` 的匿名结果中选择 `video.twimg.com` 最高码率 MP4；其他平台固定使用忽略全局配置、不读取浏览器 Cookie、`--no-playlist`、4 GiB 上限的 `yt-dlp` 单项兜底。输出目录冲突时创建 `-run-N`，媒体和元数据均不覆盖；不得传搜索伪协议、主页、频道、播放列表或登录态参数。

## youtube_known_url.py

只接受明确 YouTube 视频 URL 或含有效 `list=` ID 的播放列表容器。`info` 只读元数据；`download` 支持视频或 `--audio-only`；`subtitles` 始终生成 SRT 与保留时间戳的 TXT；`playlist --limit N` 只枚举该播放列表。所有写入使用新目录和 `--no-overwrites`，默认匿名；只有当前目标已获当轮授权后才可显式传 `--allow-browser-cookies`。

## xiaoyuzhou_stepfun.py

默认 episode 目录已存在时自动创建 `-run-N` 新目录；`--resume` 只复用 `source.json`、文件大小和 SHA-256 全部一致的产物，绝不重写 `source.json`。用户显式指定的单集输出目录已存在时默认拒绝。

## xiaoyuzhou_opencli.py

默认排他创建输出目录与清单文件。Agent 禁止自动使用兼容 `--overwrite`；只有用户当轮明确点名覆盖同一绝对目录，并同时提供独立的 `--confirm-overwrite-exact-dir <绝对路径>` 高摩擦确认后，包装器才接受。

## wechat_mp_local.py

仅保留 CLI 名称的安全兼容 stub。`login`、`search`、`download` 在任何客户端、文件或浏览器动作前统一以非零 JSON 失败；`status` 只诊断固定 localhost 根是否可达，并明确不证明登录、搜索、历史枚举或正文下载能力。所有已知 URL 必须转给 `$wechat-mp-batch-exporter`。

## firecrawl_site.py

每次 Map 或 Crawl 都排他创建新 run；Map 请求失败、返回为空/全被过滤或预检 artifact 超限时，也保留不含响应体或 Key 的安全审计，但不得签发 `preflight_ready`。Map 审计分别记录 returned、accepted、filtered、rejected、`cap_reached`，并固定 `completeness: unknown`，不得把过滤数量误报为截断。preflight 由 Firecrawl Key 派生密钥做 HMAC-SHA256，绑定范围参数、两小时有效期、Map 清单和文件 SHA-256；Crawl run 复制 preflight、site map 与 URL 清单，并在 summary/handoff 记录来源 preflight 哈希和复制件哈希。Crawl 返回仍需通过公开 HTTPS、同源、路径前缀和签名清单四项过滤；transport/job failure、未返回页面和正文拒绝原因必须在 manifest、summary、failures 与 handoff 中使用同一安全分类。不得把普通 `--site-url` 调用升级成 Crawl。

不得通过换用旧脚本、直接调用底层 OpenCLI 或自行写文件绕过这些闸门。
