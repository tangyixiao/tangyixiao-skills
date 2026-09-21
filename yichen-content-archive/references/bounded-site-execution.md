# 有界站点执行

仅在用户明确要求有界公开站点 Map 或归档时读取，执行前同时遵守 SKILL.md 的范围、授权、费用与防覆盖规则。

有界站点是唯一允许 `discovery_performed: true` 的容器路线，并固定分两次执行：

```bash
# 默认只 Map，不 Crawl
python3 ~/.agents/skills/yichen-content-archive/scripts/firecrawl_site.py \
  --site-url "https://example.com/docs" --path-prefix "/docs" \
  --limit 50 --max-depth 2

# 只有用户明确要求执行，且复用完全相同的四个范围参数
python3 ~/.agents/skills/yichen-content-archive/scripts/firecrawl_site.py \
  --site-url "https://example.com/docs" --path-prefix "/docs" \
  --limit 50 --max-depth 2 --execute --preflight "/absolute/preflight.json"
```

执行器只接受公开 HTTPS。域名固定使用 `idna` 3.x 的 UTS46 non-transitional + STD3 规范化；依赖不可用时只允许 ASCII 域名继续，绝不回退到 Python 内置 IDNA2003。规范化前拒绝 percent-encoded 主机，规范化后继续拒绝特殊用途 DNS、私网/本地地址和 WHATWG legacy IPv4 表示。`path-prefix` 必须显式非空（只有显式 `/` 才代表整站），路径按有限轮次严格解码到稳定，并拒绝 malformed percent escape、任意层级编码的 slash/backslash 和 dot segment。禁止子域、外域、登录态、目标站 headers、actions、TLS 跳过和 monitor。Firecrawl API 请求固定 v2 且拒绝所有重定向，避免 Bearer Key 被带到其他 origin。Crawl 固定 `allowSubdomains=false`、`allowExternalLinks=false`、`ignoreRobotsTxt=false`、`crawlEntireDomain=false`，并固定 `scrapeOptions.storeInCache=false`、`proxy=basic`、`skipTlsVerification=false`。不得传 `zeroDataRetention=true`；`storeInCache=false` 不能表述为绝对零留存。Firecrawl Key 只从 `FIRECRAWL_API_KEY` 或 `~/.config/agent-secrets/firecrawl-api-key` 读取，不回显、不进入普通日志。Map/Crawl 审计同时记录 `map_requests=1`、`crawl_page_cap=limit` 和 `pricing_must_be_rechecked=true`；这是额度暴露上限，不是固定价格承诺。
