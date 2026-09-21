# 已知链接与精确容器路由

只引用现有 Skill、后端和本 Skill 的固定安全适配器。调用前读取目标 Skill/参考文件或运行脚本 `--help`；本表只限制可用分支，不替代目标入口的安全规则。

| 平台 | 已知单项 `read` | 已知单项 `download/archive` | `known_collection` 精确枚举 | 明确禁止 |
|---|---|---|---|---|
| 普通网页 | Jina Reader `https://r.jina.ai/<URL>`；需图片/格式控制时用 Web Reader | 把同一已知 URL 的 Markdown、文本、HTML 或用户明确指定的原始 HTTP 响应写入新文件 | URL 文件逐行处理；不从网页继续提取站内链接 | 无界站点爬取、搜索结果页扩展、相似链接 |
| 公开 HTTPS 有界站点 | 不用于单页读取 | `firecrawl_site.py` 默认 Map；只有同参数、未过期、HMAC 与清单哈希均通过的 `--execute --preflight` 才用 Firecrawl v2 Crawl 归档 | 精确 `site-url` + `path-prefix` + `limit <= 100` + `max-depth <= 3`；Map 与 Crawl 返回都过滤同源/path，Crawl 仅归档签名清单 URL | HTTP/私网、子域/外域、无界 crawl、登录、目标 headers/actions、TLS 绕过、monitor、自动执行 Crawl |
| Twitter/X | `python3 ~/.agents/skills/yichen-content-archive/scripts/x_known_url.py "<URL>"`；固定匿名 FxTwitter → Jina。Post 保留正文/作者/指标，Quote 同时保留引用对象，Article 先精确定位父推文再还原 Markdown 正文 | `known_media_download.py <URL>`；只从匿名读取结果选择该帖 `video.twimg.com` 最高码率 MP4，排他创建新目录 | 只接受用户给出的 URL 文件逐行处理；不得枚举作者主页、线程回复、书签或推荐 | 关键词搜索；把 Article ID 搜索结果扩展成候选；未经当轮授权调用 OpenCLI/xreach |
| 小红书 | 本 Skill `xiaohongshu_fetch.py <URL> <dir> --skip-media` | 同一脚本去掉 `--skip-media`；只有当前目标获当轮授权后才可 `--use-cookie` | 只接受已经给出的 URL 文件，不枚举用户主页或收藏 | 搜索笔记、作者发现、从收藏页扩展 |
| 抖音 | 本 Skill `douyin_download.py <URL> --metadata-only` | 同一脚本去掉 `--metadata-only` 下载已知视频 | 只接受已经给出的 URL 文件，不枚举账号或收藏 | 搜索、推荐页采样、账号发现 |
| 微博 | `weibo_known_url.py info <URL>`；把 `/u/<uid>?layerid=<id>` 规范为精确详情 URL，固定匿名访客读取 | `weibo_known_url.py download <URL>`；固定单项、无 Cookie/用户配置、排他新 run 目录，使用 `weibo-known-url` 后端 | 暂不支持账号/合集枚举，只接受已经给出的单条 URL | 裸账号页、账号视频列表、搜索、热榜、评论、推荐、登录态、浏览器 Cookie、输出临时签名源 URL |
| 微信公众号 | 单个已知 URL 用 `$yichen-wechat-mp-batch-exporter` 的已知 URL 路径读取 | 已知 URL 文件用同一 Skill 的 `download_urls.py` | 账号名称、完整历史、刷新和最新 N 篇均不支持；请求用户提供已知 URL 文件或既有历史导出 | 本机 `search`/`login`/`download`、重新登录、代理历史回退、增强指标、评论；任何微信 UI 代操作 |
| YouTube | `python3 ~/.agents/skills/yichen-content-archive/scripts/youtube_known_url.py info <VIDEO_URL>` | 同一脚本的 `download`（视频或 `--audio-only`）与 `subtitles`（SRT + 保留时间戳 TXT） | `youtube_known_url.py playlist <PLAYLIST_URL> --limit N` 生成固定 `playlist.json` 与 `enumerated-urls.txt` | `search`、`channel`、相关推荐和从条目跨到其他播放列表；默认不得读取浏览器 Cookie |
| B站 | 用 `bili-cli` 的 `bili video <BV_OR_URL> --json` 读取 BV/完整 URL；AV 先规范成 `https://www.bilibili.com/video/av<ID>/` 再读取 | `yt-dlp` 只下载已知 BV/AV/完整 URL；使用 `--download-archive`、`--continue`、`--no-overwrites` | 对用户给出的播放列表/合集/分P容器 URL 用 `yt-dlp --flat-playlist --dump-single-json <URL>`；后端不支持时停止 | `bili search`、UP 主空间扩展、相关视频、私人收藏和稍后再看 |
| 小宇宙 | 已知 episode URL 用 `~/.agents/skills/yichen-content-archive/scripts/xiaoyuzhou_stepfun.py --inspect-only <URL>`，匿名优先 | 同一脚本 `--download-only`；只有用户明确要求转写并确认数量/额度时才去掉该参数 | 已知 episode URL 文件直接用 `--batch-file` 匿名处理；已知 podcast ID/URL 需当轮账号令牌授权后用本 Skill 的 `xiaoyuzhou_opencli.py episodes` 生成清单，再回到匿名 `--batch-file` | 全站关键词搜索、从单集找相似播客、未授权账号令牌、自动调用付费 ASR |
| 其他公开单项媒体 | 不提供通用读取 | `known_media_download.py <PUBLIC_HTTPS_URL>`；固定匿名、忽略全局配置、不读取浏览器 Cookie、`--no-playlist`、单项下载和新目录防覆盖 | 不支持容器枚举 | HTTP/私网、搜索伪协议、主页、频道、播放列表、登录态、跨来源扩展 |

## 路由纪律

- 短链接的单次规范化或跟随重定向属于已知链接解析，不得借机抓取推荐列表。
- 小红书与抖音都只调用本 Skill 内置执行器；旧 `xiaohongshu-fetch`、`douyin-fetcher` 入口已经退役，不得回退调用。
- 微博只调用本 Skill 的 `weibo_known_url.py`。桌面 overlay URL 必须先抽取十进制 `layerid` 并规范为单条详情 URL；不得把原始 `/u/` URL 直接交给 `yt-dlp`，因为它可能被识别为账号视频列表。执行器固定 `--ignore-config`、禁用 Cookie 输入、`--no-playlist` 和 `--no-overwrites`；`yt-dlp` 在进程内生成的匿名访客状态不等于用户登录态，且不得持久化或回显。
- `known_collection` 必须先写固定清单，并记录容器引用、用户指定上限、实际条数和是否截断。清单条目不能继续扩展子来源。
- URL 文件属于用户已提供的精确清单，不运行链接发现器或站内爬虫。
- Firecrawl 有界站点是 URL 文件规则之外的显式例外：Map 只生成两小时签名预检，Crawl 必须再次显式执行并保持四个范围参数完全一致。`path-prefix` 不得为空，只有显式 `/` 才允许整站；多层路径编码严格解码到稳定后再检查 dot segment 与编码 separator。公开主机用 `idna` 3.x UTS46 non-transitional + STD3 规范化，再经过特殊用途 DNS 和 WHATWG legacy IPv4 闸门；依赖缺失时保守拒绝非 ASCII，percent-encoded 主机在规范化前直接拒绝。Firecrawl Bearer 请求禁止重定向。固定 v2、`storeInCache=false`、`proxy=basic`、`skipTlsVerification=false`；这不等于绝对零留存，也不得伪称 `zeroDataRetention` 已启用。Map 为空、全部过滤或预检 artifact 超限时只写失败审计，不签发可执行 preflight；Map 统计分别记录 returned/accepted/filtered/rejected、`cap_reached` 和 `completeness: unknown`。每个 run 记录 `map_requests=1`、`crawl_page_cap=limit` 与 `pricing_must_be_rechecked=true`，实际计费仍须按当时官方价格和账单复核。
- X 的 `/i/article/<ARTICLE_ID>` 不直接交给 Jina；先用 FxTwitter `/2/search` 对该 ID 做最多 10 条的一次查询，只接受 `article.id` 精确相等的父推文，再请求 `/2/status/<PARENT_ID>`。该查询只用于对象解析，输出中不得保留或归档其他结果。
- X Article 通常以 `x.com/<handle>/status/<STATUS_ID>` 分享；请求该 status 后只要返回内嵌 `article` 对象，就直接判定为 Article，不再做 Article ID 搜索。若正文块不完整，匿名 Jina 和授权后的 OpenCLI 都使用该父 Status URL。
- X 匿名链成功即停止。匿名失败或 Article 正文缺失时，先说明具体缺口；取得当前链接的当轮授权后，Post/Quote 才可运行 `opencli twitter thread "<STATUS_URL>" --limit 1 -f json`，Article 才可运行 `opencli twitter article "<PARENT_STATUS_URL>" -f md`，仍失败再运行 `xreach --cookie-source chrome --json tweet "<STATUS_URL>"`。不得读取 Feed、评论线程、书签、通知或私信。
- 微信公众号账号搜索、完整历史、刷新和最新 N 篇自 2026-07-30 起不再可枚举。`wechat_mp_local.py` 的 `login`、`search`、`download` 仅保留失败闭合的兼容命令；`status` 只检查固定 `127.0.0.1:18901/` 根可达性，不能证明任何导出能力。所有已知 URL 统一交给 `$yichen-wechat-mp-batch-exporter`；不得请求重新登录、进入代理回退或操控微信客户端。
- YouTube 只能使用本 Skill 的 `youtube_known_url.py` 处理已知视频 URL 或精确播放列表。不得调用 `$yichen-unified-search`、`search`、`channel` 或相关推荐；默认匿名，只有当前目标经当轮授权后才可显式传 `--allow-browser-cookies`。
- B站公开内容匿名优先。高画质、高码率、4K/HDR/杜比、会员/已购/地区年龄限制、私人数据或明确要求登录的字幕，必须说明具体目标和原因，取得当轮 Cookie 授权；普通 412 不自动升级为登录态。
- 小宇宙 episode 页面、音频和已给出的 episode URL 清单匿名优先。只有已知 podcast 结构化列表、平台已有转写或匿名失败时，才按目标取得当轮账号令牌授权；批量 StepFun 前先确认节目数量和额度。
- 小宇宙 StepFun 默认固定目录冲突时写入新的 `-run-N` 目录；只有显式 `--resume` 且 metadata、大小和 SHA-256 一致时复用。OpenCLI 的 `--overwrite` 是兼容性破坏模式，Agent 禁止自动使用；缺少与 `--output-dir` 完全一致的 `--confirm-overwrite-exact-dir` 时必须失败。
- 平台 Skill 要求登录态、Cookie、代理、证书或其他人工门时，以它的更严格规则为准。
- 容器类型不受现有后端支持时只生成失败项：`stage=enumeration`、`reason=unsupported_container`；不得降级成搜索。
- 不支持专用路由的平台若输入是用户明确给出的单条公开 HTTPS 媒体 URL，且动作是视频或音频下载，固定进入 `known_media_download.py`；其他动作仍生成失败项：`stage=route`、`reason=unsupported_platform`。不得借此放开登录态、账号枚举、播放列表或跨来源扩展。
