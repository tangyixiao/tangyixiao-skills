# 标准交接结构

两个 Skill 使用同一 `yichen-content-handoff/v1` 结构。交接是运行摘要，不是新的授权。`authorization_not_transferable` 表示授权不能扩展到其他动作、目标或平台，并非每次换技能都必须重新询问；同一当前任务中已经明确授权且范围未变的动作可继续，独立的私人读取、登录态、下载与费用门槛仍分别满足。

```json
{
  "handoff_version": "yichen-content-handoff/v1",
  "producer_skill": "yichen-content-archive",
  "operation": "content_archive",
  "scope": {
    "platforms": ["xiaohongshu"],
    "input_kind": "known_urls",
    "discovery_performed": false
  },
  "authorization": {
    "private_read_authorized_this_turn": null,
    "download_authorized_this_turn": true,
    "authorization_not_transferable": true
  },
  "artifacts": [
    {
      "kind": "archive_manifest",
      "path": "/absolute/path/archive-manifest.jsonl",
      "count": 3
    }
  ],
  "counts": {
    "input": 3,
    "success": 2,
    "failed": 1,
    "skipped": 0,
    "unsupported": 0
  },
  "failures": [
    {
      "item_ref": "input.txt:3",
      "stage": "download",
      "reason": "access_denied"
    }
  ],
  "next_step": {
    "action": "none",
    "requires_explicit_user_request": true
  }
}
```

## 约束

- `producer_skill` 只能是 `yichen-content-archive` 或 `yichen-bookmarks-export`。
- `operation` 只能是 `content_archive` 或 `bookmark_export`。
- 普通已知链接与精确平台容器的 `discovery_performed` 必须为 `false`。唯一例外是 `scope.input_kind=known_collection`、`scope.container_kind=bounded_site` 且实际通过本 Skill `firecrawl_site.py` 的签名 Map→显式 Crawl 闸门时写 `true`；该值只陈述发生过有界站内枚举，不授权继续扩展。
- `bounded_site` 交接必须同时记录 `site_url`、`path_prefix`、`limit`、`max_depth`，并以 `preflight`、`site_map`、`enumerated_url_list`、`archive_manifest`、`run_summary`、`failures` 和 `web_content` 七种 artifact kind 引用对应文件或目录。除目录外的 artifact 同时记录 SHA-256；前三种必须指向 Crawl 新 run 内的复制件。
- Crawl `run-summary.json` 必须用 `preflight_audit` 记录来源 preflight 的绝对路径和 SHA-256、已验证的 receipt、签名 Map/URL 清单哈希，以及 Crawl run 内三个复制件的绝对路径和 SHA-256。签名 preflight 复制件保留原 Map run 的已签名路径，不改写 receipt；自包含复核以 `signed_artifact_hashes` 对照复制件哈希。
- Crawl 的 transport/job failure 必须只持久化安全分类，不保存响应正文；签名 URL 未返回、Markdown 缺失或页面超限等逐 URL 拒绝原因，必须在 `archive-manifest.jsonl`、`run-summary.json.failures`、`failures.json` 和 `handoff.json.failures` 中保持一致。
- Map 与 Crawl 的 summary/preflight，以及 Crawl handoff，必须记录 `quota_exposure.map_requests=1`、`quota_exposure.crawl_page_cap=limit` 和 `quota_exposure.pricing_must_be_rechecked=true`。这只陈述本次调用和页面上限，不声明当前价格或余额。
- 收藏导出交接的 `download_authorized_this_turn` 必须为 `false`。
- `authorization_not_transferable` 必须为 `true`；任何后续私人读取、登录态使用或下载按目标 Skill 重新判断。
- `artifacts[].path` 使用绝对路径。私人 URL、敏感查询参数和凭证放在受控本地文件中，不内嵌到交接 JSON。
- `counts` 五项必须存在；没有失败时 `failures` 使用空数组。
- `next_step` 只描述可选动作，不触发另一个 Skill。
