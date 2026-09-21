> Paths used in commands are relative to the parent skill directory. Read this reference only for the route selected in SKILL.md.

## 横纵研究模式

只有任务同时需要历史演进、当前横向结构和综合判断时才进入本模式。单个事实查证、搜索候选、已知链接读取或快速总结不得为了“显得深入”而扩展成横纵研究。

触发后完整读取 [references/hengzong-research.md](../references/hengzong-research.md)，并按下列顺序执行：

1. 建立研究 brief：固定 `subject`、`goal`、`object_type`、`subtype`、`as_of`、`start_date`、`geography`、`audience` 和 `languages`。这些 key 必须出现；未知值保持 `unknown`，不得猜测。`start_date`、`geography`、`audience`、`languages` 是 scope keys，任一为 `unknown` 都进入不可 retained 的 blocking scope gap，并阻止正式报告就绪。
2. 在联网前把 brief 经纯离线计划器转为纵向与横向 workstream：

   ```bash
   python3 ~/.agents/skills/yichen-web-research/scripts/plan_hengzong_research.py \
     --brief -
   ```

3. 只有 `coverage_dimensions.query_group_matrix.status=ready` 时，才把计划中各 workstream 的 `query_groups` 交给 `$yichen-unified-search`。其 `query_text` 必须是可直接提交搜索的自然语言短语，不得把 `facet:`、`axis:`、`search_language:`、`time_scope:` 或 `evidence_intent:` 这类内部元数据伪装成搜索操作符。每个 workstream 都按已知 `geography` 与 `languages` 分组；只有 subject 与 geography 都可靠本地化时，group 才能标为 `localization_status=native`，否则保留原文并显式输出 localization gap。`source_annotations` 显式记录来源覆盖的 `geographies`/`languages`，且每个 workstream 的每个已知地区、每种已知语言都至少需要一条 temporal-eligible verified source。多地区、多语言必须逐维度覆盖，不能把一个地区或一种语言的证据外推为全范围；未知维度保持 unknown，不虚构默认值。未覆盖维度必须成为 blocking gap，或在满足保留披露条件后成为 retained gap。纵向优先起源、阶段、转折与驱动力；横向按研究目标选择实体的竞品/替代/用户/生态，或行业 3–5 个高价值切面。复用现有分波、去重和缺口补搜思想，但不得把任一平台扩成无界搜索。
4. 搜索 envelope 仍只是候选交接包。只有真实打开原文并核对具体主张后，才把来源标为已核验；不得用搜索摘要、AI 摘要、排名或 `opened_original=true` 单独证明事实。
5. 原请求已经明确限定需读取的公开来源时，可按该范围核验；只有用户明确要求持久化原文或下载媒体，且归档范围已限定时，才进入 `$yichen-content-archive` 的独立范围与授权门。搜索完成本身绝不转移归档授权。
6. 写作前把 canonical plan、按 workstream 对应且绑定同一 `plan_id` 的候选 envelope、显式来源等级/角色、原子主张与 retained gaps 组成 bundle，运行纯离线证据整理器：

   ```bash
   python3 ~/.agents/skills/yichen-web-research/scripts/assemble_hengzong_evidence.py \
     --bundle -
   ```

7. 只有 `scope_complete`、逐 workstream 基础 claim、非空 timeline、非空 cross-sectional matrix、逐地区/语言 coverage、`contradiction`、横纵交汇与三情景等结构门全部满足时才写正式报告。任何 `supports`/`contradicts` evidence link 都必须有非空 `locator`、`event_date`、`scope`；`notes` 可选，但提供后必须原样保留。缺少任一必填 link 字段的输入是 `invalid_bundle`，不是可以 retained 的 blocking gap。独立来源按 `independence_group` 去重；缺少 `published_at` 的来源不具 temporal eligibility。`as_of`、`start_date`、`pre_scope_context` 与 `retrospective` 规则不得因证据不足而放宽。
8. 普通缺口输出 `blocking` 并继续定向补搜。只有同一真实缺口已经尝试至少 2 条 `search_attempts` 对象，每条都含 `query_or_path` 与 `route`，且各条 query/path 彼此不同、route 也彼此不同，同时 retained disclosure 含 `impact`、`disclosure`、`bounded_conclusion`，才可输出 `ready_with_disclosure`；这不能豁免 locator、日期、逐 workstream 基础 claim、timeline、cross-sectional matrix、横纵交汇或三情景等结构门。固定 1–3 万字不是完成标准。

`start_date` 之前的材料默认越界；只有准确标为 `pre_scope_context=true` 时才可作为透明前史保留，并且不能计入 claim、coverage、timeline、交汇、情景或机会地图的证据资格。

任何“决策原因”必须标为 `explicit`、`supported_inference` 或 `unknown`；任何交汇洞察必须能回溯为 `past_event -> present_effect -> implication`。三情景必须给出时间范围、可观察触发信号和反证条件，不编造概率。

行业研究的 `goal` 出现未来、机会、机遇、前景或对应英文意图时，计划和报告契约必须显式包含非空 `opportunity_map` 并通过结构 gate，不能只靠三情景代替；每项 `evidence_basis` 必须绑定 ready claim IDs，并同时覆盖纵向与横向基础 claim。`languages` 指定两种交付语言时，`report_contract` 必须把双语输出写成硬要求，而不只是用两种语言检索。

本模式基于、受启发并扩展 `KKKKhazix/khazix-skills` 的 `hv-analysis`，作者为数字生命卡兹克，固定参考上游提交 `7a5c4934be4106ac740ffdb95280bb81b3f4b83c`；公开发布版已保留完整 MIT 归属。
