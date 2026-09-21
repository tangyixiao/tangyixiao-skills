# 横纵研究协议

横纵研究把“沿时间解释如何走到今天”和“在同一时间切面解释当前结构”组合成一套可核验的研究流程。它是 `yichen-web-research` 的研究规划与证据综合协议，不是新的搜索后端，也不改变各子 Skill 的授权边界。

本协议基于、受启发并扩展 `KKKKhazix/khazix-skills` 的 `hv-analysis`，作者为数字生命卡兹克，固定参考上游提交 `7a5c4934be4106ac740ffdb95280bb81b3f4b83c`。公开发布版在仓库根目录保留 `THIRD_PARTY_NOTICES.md` 与完整 MIT 许可文本。

## 目录

1. [何时触发](#1-何时触发)
2. [研究 brief](#2-研究-brief开始前必须齐全)
3. [规划与证据脚本](#3-规划脚本的读取与运行时机)
4. [纵向与横向 workstream](#4-纵向与横向-workstream)
5. [来源等级与逐主张核验](#5-来源等级与逐主张核验)
6. [日期与决策逻辑](#6-日期与决策逻辑)
7. [用户口碑采样](#7-用户口碑的采样边界)
8. [Claim-source ledger](#8-claim-source-ledger)
9. [横纵交汇与三情景](#9-横纵交汇与三情景)
10. [停止闸门](#10-coveragegapcontradiction-停止闸门)
11. [子 Skill 交接](#11-与子-skill-的交接)

## 1. 何时触发

满足下列任一条件时，进入横纵研究模式：

- 用户明确要求“横纵分析”“深度研究”“发展史 + 现状对比”或同义任务。
- 问题同时要求历史演进、当前竞争或结构，以及机会、风险或未来判断。
- 对象是公司、产品、人物、协议、项目、机构、行业、赛道或知识领域，且单次事实查询不足以回答研究目标。
- 最终结论需要把过去事件与当前格局建立因果联系，而不只是汇总资料。

以下情况不触发：

- 单个事实、当前状态、价格、日期或定义的查证。
- 单平台或多平台的单阶段关键词搜索、候选发现或轻量核验。
- 已知链接、已确认候选或明确有限容器的读取与归档。
- 单篇文档总结、已有音视频转写、私人收藏链接导出。
- 用户只要快速答案，且没有要求历史、横向结构或情景推演。

不触发时直接路由到对应子 Skill。不要为了显得“深入”而强行扩展研究范围。

## 2. 研究 brief：开始前必须齐全

开始检索前，必须把输入规范化为研究 brief。以下字段不可省略；无法确认时写 `unknown` 并登记为 gap，不得静默猜测：

| 字段 | 要求 |
|---|---|
| `subject` | 研究对象的规范名称，并列出必要别名、旧名或容易混淆的同名对象。 |
| `goal` | 研究要回答的问题、支持的判断或决策；不能只写“全面了解”。 |
| `object_type` | `entity` 或 `industry`。`entity` 是边界明确的对象；`industry` 是市场、赛道、生态或知识领域。 |
| `subtype` | 实体可为 `company`、`product`、`person`、`protocol`、`project`、`institution` 等；行业可为 `market`、`sector`、`category`、`ecosystem`、`policy_domain` 等。 |
| `as_of` | 当前截面的截止日期，使用 `YYYY-MM-DD`；所有“当前”“最新”判断均以此为界。 |
| `start_date` | 纵向研究起点，使用 `YYYY-MM-DD`；若起点未知写 `unknown`，并从可核验的最早节点开始。 |
| `geography` | 国家、地区或全球范围；一个值可用字符串，多个值用字符串数组。每个已知值都必须独立进入查询覆盖。 |
| `audience` | 报告读者及其知识水平、决策场景。 |
| `languages` | 检索与交付语言；一个值可用字符串，多个值用字符串数组。指定两种语言时，同时形成双语报告契约。 |

建议同时记录研究问题、排除项、优先级、来源限制、时间或费用预算、期望交付形式。`object_type`、`subtype`、`as_of` 或范围发生实质变化时，旧计划失效，必须重新规划。

## 3. 规划脚本的读取与运行时机

### `plan_hengzong_research.py`

- 在 brief 完整之后、任何网络检索之前读取其契约并运行。
- 用它把 brief 转为纵向 workstream、横向切面、`query_groups`、优先级和覆盖目标；计划本身不是证据。
- `plan_id` 必须绑定 planner 输出的 canonical plan；执行器不得接受只复制 ID、但正文已经漂移的计划。
- 当对象类型、截止日期、时间范围、地域或研究目标变化时重新运行。
- 当证据缺口证明原切面选择错误时，可以修订计划，但要保留变更原因，不能为了迁就现有材料而偷偷改问题。

### `assemble_hengzong_evidence.py`

- 在候选已完成原文核验、证据已进入 claim-source ledger 之后，正式写作之前读取其契约并运行。
- 用它组装已验证的来源、时间线视图、横向主张视图、矛盾项、覆盖缺口、横纵交汇链、三情景与停止闸门。
- 新增关键证据、解决矛盾或调整高优先级主张后重新运行。
- 它只整理已提供的结构化证据，不负责联网搜索、下载、自动归档，也不能把候选摘要升级为已核验事实。
- 输入 plan、bundle 与每个 envelope 的研究上下文必须绑定同一 canonical `plan_id`；不匹配时 fail closed。

## 4. 纵向与横向 workstream

### 4.1 实体：纵向

按研究目标选择并排序，不要求机械覆盖全部：

1. 前史与起源：需求、技术、制度和人物背景。
2. 成立、首次发布或首次提出的可核验节点。
3. 产品、技术、商业模式或组织的版本演进。
4. 融资、收入、用户、合作、并购等规模节点。
5. 团队、治理、战略和市场定位变化。
6. 监管、诉讼、危机、失败与重大争议。
7. 关键转折点、当时约束及其后续路径依赖。

纵向部分按事件日期重建因果，不写成把新闻发布时间依次排列的流水账。

### 4.2 实体：横向

以 `as_of` 为同一截面，优先考虑：

- 直接竞品、间接替代、上一代方案和“不采取行动”的替代成本。
- 技术路线、产品形态、目标用户与核心使用场景。
- 商业模式、定价、渠道、规模和单位经济性。
- 团队、治理、资本、生态合作与关键依赖。
- 用户实际使用方式、口碑主题及其与官方定位的偏差。
- 监管位置、声誉、执行风险、优势和脆弱点。

没有直接竞品时，不硬凑名单；改为解释品类边界、替代方案、进入壁垒及最可能出现竞争的方向。竞品很多时，按代表性而非知名度选取少量可比对象，并说明纳入与排除理由。

### 4.3 行业：纵向

1. 萌芽条件与最早可核验形态。
2. 阶段划分及每次阶段转换的判据。
3. 政策与监管周期。
4. 技术范式、成本曲线和基础设施变化。
5. 供需结构、用户认知和渠道变化。
6. 资本周期、竞争集中度与商业模式演变。
7. 危机、丑闻、标杆兴衰及跨界玩家进入。
8. 驱动力从早期到当前的替换、增强或衰减。

阶段不能只靠事后命名；每个阶段都要有起止依据、关键事件和可观察的转折条件。

### 4.4 行业：横向

候选切面包括：

- 市场定义、边界、规模、增速与细分赛道。
- 产业链、价值分配、议价权、瓶颈和脆弱环节。
- 玩家格局、集中度、竞争焦点与新进入者。
- 商业模式、盈利逻辑、成本结构与天花板。
- 用户分层、需求、采购或决策链路及满足程度。
- 技术路线、基础设施、效率与替代方案。
- 区域差异、先发市场和本地化约束。
- 监管、牌照、准入、政策方向及执法差异。
- 资本热度、融资结构与估值口径。

### 4.5 横向切面的选择标准

通常选 3–5 个高价值切面；对象较窄时可以更少。每个入选切面必须同时满足：

1. **目标相关**：能改变 `goal` 对应的判断或决策。
2. **可比**：不同对象、区域或方案能在同一口径下比较。
3. **可证**：存在可追溯来源、指标或可复核观察。
4. **重要**：对竞争位置、供需结构、机会或风险有实质影响。
5. **非重复**：不与其他切面换词重复，能提供独立解释力。
6. **截面一致**：尽量使用接近 `as_of` 的数据；口径或年份不同必须显式标注。

不要按模板追求面面俱到。切面无法取得可比证据时，应替换或降级为 gap，而不是用印象填满。

### 4.6 `query_groups` 的地区与语言覆盖

每个 workstream 都必须有自己的 `query_groups`；每组从父 workstream 继承 `workstream_id`，并明确记录 group ID、地域、语言、问题或查询意图。查询组是执行分波与检查覆盖的单位，不是把若干关键词混在一起的备忘录。

- `query_text` 必须是对应地区和语言下可直接提交搜索的自然短语，并吸收该 facet 的具体问题与来源路径。不得把 `facet:`、`axis:`、`search_language:`、`time_scope:` 或 `evidence_intent:` 这类内部字段当成通用搜索操作符。
- 中英双语 subject 应选择对应语言片段，常见中英地理名应双向本地化。只有 subject 与 geography 都已可靠本地化，group 才可标为 `localization_status=native`；无法可靠本地化时必须保留原文，并以 `subject_localization_status`、`geography_localization_status` 和 localization gap 明示，不得伪称原生查询。
- `geography` 有多个已知值时，每个地区至少出现在一个定向查询组；不能用“全球”或一个先发市场代替其他已知地区。
- `languages` 有多个已知值时，每种语言至少出现在一个原生语言查询组；翻译后的同一条查询不等于取得该语言生态的证据。
- 地域与语言都为多值时，planner 为每个已知“地区 × 语言”组合建立有界查询组，确保两个维度逐项覆盖；每个 workstream 最多 64 组，超过上限必须先缩小 brief，不能转为无界笛卡尔积。
- 每轮 envelope 的 `research_context` 必须带回并精确匹配 `plan_id` 与 `workstream_id`；若该轮来自 planner 的某个查询组，同时带回其 `query_group_id`，且该 ID 必须属于对应 workstream。
- `source_annotations` 必须显式写来源实际覆盖的 `geographies` 与 `languages`。每个 workstream 的每个已知地区、每种已知语言都至少需要一条 temporal-eligible verified source；整理器输出逐维度 `counts` 与 `missing`。
- 未覆盖的已知地区或语言不能静默忽略：未完成定向补搜时是 blocking gap；满足 retained disclosure 条件后才可保留为 report-visible gap，并限制结论外推范围。
- `start_date`、`geography`、`audience` 或 `languages` 任一为 `unknown` 时，不创建虚构范围；`coverage_dimensions.gaps` 必须逐项记录，`query_group_matrix.status` 必须为 `blocked_by_scope_gap`，并形成不可 retained 的 blocking scope gap。

## 5. 来源等级与逐主张核验

来源按其与原始事实的距离分级，而不是按品牌知名度分级：

| 等级 | 典型来源 | 用途与边界 |
|---|---|---|
| `L0` | 法律法规、监管文件、法院文书、公司申报、审计报告、官方统计或原始数据集 | 关键法律状态、财务数字、主体和事件的优先证据；仍需核对适用范围与口径。 |
| `L1` | 当事方公告、产品文档、技术论文、公开演讲、访谈、定价页、版本记录 | 证明当事方做了什么或明确说了什么；不能单独证明自我评价、市场效果或因果。 |
| `L2` | 有方法说明的学术研究、专业数据库、行业报告、可靠媒体的独立报道 | 交叉核验、行业估算和第三方观察；要追溯其引用的原始数据。 |
| `L3` | 论坛、社交媒体、应用商店评论、社区帖子、聚合页、转载和搜索摘要 | 发现线索、用户体验与口碑主题；不能自动升级为产品事实或总体结论。 |

核验单位是“主张”，不是“段落有一个链接”：

- 每个重要主张都要落入 ledger，并绑定支持、反驳或仅提供背景的具体来源。
- 决定性事实优先使用 `L0`/`L1`，并尽量加入一个独立来源；高风险或有争议主张需要至少两个相互独立的来源。
- 数字必须保留统计期、单位、币种、地域、样本和定义；不同口径不得直接并列计算。
- 来源引用另一来源时，尽可能回到原始材料；无法回溯时标记 `secondary_only`。
- Workstream coverage 中的 `independent_sources` 只在 `source_role=independent` 的第三方来源中按不同 `independence_group` 计数。`supported_inference` 的“两条独立证据线”则要求至少两个不同 `independence_group` 的 temporal-eligible supporting sources，不要求两条都标成 `source_role=independent`；例如不同主体的两份一手记录可以构成两条证据线。
- 两种口径都不能按 URL、标题或媒体品牌数量计数。整理器会先按规范来源身份生成默认 group；已知是转载、同一新闻稿或复用同一底层数据集时，annotation 必须把它们归入同一 group，使其只能算一条证据线。
- 搜索摘要、AI 摘要和候选卡片只用于发现，不得作为最终证据。
- “没有发生”“没有竞品”“没有公开信息”等否定主张必须记录检索范围，不能把未找到当成已证明不存在。
- 官方来源与独立来源冲突时不默认偏信任一方；记录口径差异和未解决部分。

## 6. 日期与决策逻辑

每条事件证据至少区分：

- `event_date`：事情实际发生或开始生效的日期。
- `published_at`：来源公开发布或更新的日期。
- `as_of`：报告允许使用的当前截面，必须等于 canonical plan 中的截止日期。
- `start_date`：纵向主研究窗口的起点。
- `retrospective`：来源晚于 `as_of` 但回顾更早事件时显式为 `true`。
- `pre_scope_context`：claim、evidence link 或 source annotation 的事件早于已知 `start_date` 时显式为 `true`。
- `in_scope`：Assembler 根据事件是否处于时间窗内输出，不由作者自行扩大。

时间线按 `event_date` 排序，来源新鲜度按 `published_at` 判断。claim 的 `as_of` 必须与 plan 一致，claim 与 evidence link 的 `event_date` 不得晚于 `as_of`。`source_annotations.published_at` 缺失时，来源 `temporal_eligible=false`；晚于 `as_of` 的来源只有在 `retrospective=true` 时可透明保留，仍不得计入 as-of coverage 或 material claim。已知 `start_date` 时，早于起点的 claim、evidence link 或 source annotation 默认无资格；只有准确设置 `pre_scope_context=true` 才可透明保留，且不得计入基础 claim、coverage、timeline、cross-sectional matrix、交汇、情景或 opportunity map。回顾文章不得把发布日期冒充事件日期；只有年月或日期存在争议时，保留粒度或候选区间，不补造具体日。

涉及“为什么做这个决定”时，只允许三种状态：

- `explicit`：决策者或可归责的一手文件明确说明原因，可准确定位原文。
- `supported_inference`：多个事实支持的分析推断；必须列出证据链、假设和合理的替代解释，不得写成当事人原话。
- `unknown`：证据不足、相互冲突，或只能猜测；直接说明未知及其对结论的影响。

## 7. 用户口碑的采样边界

用户口碑回答的是“被采样用户如何描述体验”，不是总体市场真相。采样前固定平台、时间窗、语言、地域、查询词、纳入规则和目标样本量，并遵守以下边界：

- 只读取获准范围内的公开内容或当轮明确授权的私人范围；社交平台全程只读，绝不操控微信。
- 以帖子、评论或评测的唯一标识去重，尽量识别转载、营销、返利、机器人和同一作者重复发言。
- 同时收集正面、负面和中性使用场景；不能只搜索预设结论的关键词。
- 报告样本数、独立作者数、平台分布、时间分布和明显缺失，不用样本占比冒充总体发生率。
- 将功能事实、个人体验、传闻和情绪分开编码；`L3` 中出现的产品事实需回到更高等级来源核验。
- 只总结反复出现且有代表性原例的主题；低频但严重的问题单独标记，不用“用户普遍认为”等超出样本的话术。

## 8. claim-source ledger

Ledger 使用规范化的三组记录，支持一个主张对应多个来源，也支持一个来源同时支持与反驳不同主张。

### `claims`

| 字段 | 含义 |
|---|---|
| `claim_id` | 稳定唯一 ID。 |
| `statement` | 单一、可判断真假的原子主张。 |
| `claim_type` | `fact`、`decision_logic`、`cross_insight` 或 `scenario`。 |
| `basis` | `explicit`、`supported_inference`、`unknown` 或 `not_applicable`。 |
| `workstream_ids` | 主张所属的一个或多个计划 workstream；交汇与情景必须同时引用纵向和横向。 |
| `event_date`、`as_of` | 事件日期与判断所处的当前截面，不能用发布日期替代事件日期。 |
| `pre_scope_context`、`in_scope` | 前史声明与整理器输出的窗口状态。 |
| `evidence` | `source_id`、`relation` 与可复核 `locator` 的数组。 |
| `cross_link` | 仅交汇主张使用，必须含 `past_event`、`present_effect`、`implication`。 |
| `scenario` | 仅情景主张使用，必须含标签、时间范围、起点、因果路径、触发信号、反证条件和影响。 |
| `contradiction_resolution` | 冲突已分析时记录 `resolved` 或 `retained_uncertainty` 及说明；不得静默丢弃反证。 |

Claim 运行时状态固定为 `ready`、`ready_with_uncertainty`、`retained_with_disclosure`、`insufficient`、`unknown` 或 `contested`。`contested` 表示存在尚未处理的已核验反证；不要使用未定义的 `contradicted` 状态。Claim 状态与报告级 `ready`/`ready_with_disclosure`/`blocking` 分层，不能混用。

### `sources`

| 字段 | 含义 |
|---|---|
| `source_id` | 稳定唯一 ID。 |
| `title`、`publisher`、`url` | 来源身份与规范链接。 |
| `source_tier` | `L0`–`L3`；无法可靠分级时为 `unknown`。 |
| `source_role` | `primary`、`authoritative`、`independent`、`community`、`aggregator` 或 `unknown`。 |
| `publisher_kind` | 法规发布者、公司、数据库、媒体、社区等来源身份。 |
| `published_at`、`retrieved_at` | 发布或更新时间，以及本次取得时间。 |
| `independence_group` | 识别转载、同一数据源或同一当事方，避免把重复来源当成交叉验证。 |
| `geographies`、`languages` | 该来源实际可支持的地域与语言覆盖；必须来自 annotation，不能从域名或标题猜测。 |
| `retrospective`、`pre_scope_context`、`temporal_eligible` | 回顾性、前史声明与截止日资格。 |

### `evidence_links`

| 字段 | 含义 |
|---|---|
| `claim_id`、`source_id` | 连接主张与来源。 |
| `relation` | `supports`、`contradicts` 或 `context_only`；只有前两者参与支持/冲突闸门。 |
| `locator` | 页码、章节、表格、段落或时间戳；只保存必要短摘录。 |
| `event_date` | 该证据所指事件的发生或生效日期。 |
| `scope` | 地域、对象、统计期、样本、单位和定义。 |
| `notes` | 可选的口径限制、推断步骤、冲突说明或待核验项。 |
| `pre_scope_context`、`in_scope` | 前史声明和整理器输出的窗口状态。 |

每条 `supports` 或 `contradicts` evidence link 都必须有非空 `source_id`、`relation`、`locator`、`event_date`、`scope`；`notes` 可选且一旦提供必须原样保留。整理器不得只留下来源 ID，`context_only` 不计入支持强度。缺字段、日期越界或前史状态错误会使 CLI 返回 `invalid_bundle`，不是可以 retained 的证据 gap。

若执行器采用单表，也必须保留上述多对多关系和日期、口径、独立性信息，不能把多条来源压成一个无法追溯的“参考资料”字段。

## 9. 横纵交汇与三情景

横纵交汇不是前两部分的摘要。每条核心洞察必须写成并在 ledger 中可追溯的链：

```text
past_event -> present_effect -> implication
```

- `past_event` 必须来自已核验的纵向节点。
- `present_effect` 必须在 `as_of` 截面的横向证据中可观察。
- `implication` 可以是判断，但要说明适用条件、受益或受损对象及不确定性。

最终至少构造三个互相可区分的情景：`most_likely`（最可能）、`danger`（最危险）、`optimistic`（最乐观）。每个情景都必须包含：

| 字段 | 要求 |
|---|---|
| `horizon` | 明确推演截止日期或时间跨度。 |
| `starting_conditions` | 与当前证据一致的起点。 |
| `causal_path` | 从关键变量到结果的因果链。 |
| `triggers` | 可观察、可跟踪的先行触发信号。 |
| `invalidators` | 一旦出现就足以否定或重写该情景的事实。 |
| `implications` | 对研究目标、对象和关键相关方的影响。 |

情景不是预测承诺。没有模型或可解释基准时，不编造概率；新事实触发 `invalidators` 后，应重做推演。

行业 brief 的 `goal` 含未来、机会、机遇、前景或对应英文意图时，`report_contract` 必须显式要求非空 `opportunity_map`，整理器必须把它作为结构 gate。每项至少包含唯一 `opportunity_id`，以及 `opportunity`、`historical_driver`、`current_condition`、`evidence_basis`、`beneficiaries`、`constraints`、`leading_indicators`、`invalidators`；`evidence_basis` 必须绑定 ready claim IDs，并至少覆盖一个纵向基础 claim 和一个横向基础 claim。不能把最乐观情景改名后当机会地图。

`languages` 指定两种交付语言时，`report_contract.language_requirements.delivery_languages` 必须同时列出两种语言，并把双语交付设为硬要求；两种语言对关键主张、数字、限定语和引用保持等义。双语检索不能自动替代双语交付；反之亦然。

## 10. coverage、gap、contradiction 停止闸门

每轮检索后都检查三类状态：

### Coverage

- 每个 workstream 至少有一条 `ready` 的基础 claim（`fact` 或 `decision_logic`）；达到来源数量但没有可用主张仍不算覆盖。
- 每个 `critical` 研究问题都有已核验主张，或被明确标为未知。
- 每个入选 workstream 和横向切面都有与其重要性相称的来源覆盖。
- 所有核心结论、交汇链和情景起点都能回指 ledger。
- 当前截面不使用 `as_of` 之后的信息，易变信息有接近截止日的来源。
- `views.timeline` 至少有一个窗口内、带 `event_date` 的 ready 纵向基础 claim；`views.cross_sectional` 至少有一个 ready 横向基础 claim，足以形成非空 cross-sectional matrix。

### Gap

- 每个缺口记录缺什么、为什么重要、已尝试的查询或来源、下一步和剩余影响。
- gap 未经定向补搜不得进入成稿；要保留为 disclosure，必须有至少 2 条结构化 `search_attempts`。每条包含非空 `query_or_path` 与 `route`，且各条 query/path 彼此不同、route 也彼此不同；不能把同一查询换写法或沿同一路由重复调用凑数。
- 补搜后仍不可得时，保留 `unknown`，降低结论强度；不得用低等级材料填空。
- `retained_gaps` 只能匹配整理器实际发现的 `coverage:{workstream_id}` 或 `claim:{claim_id}`；每项必须包含 `gap_key`、上述至少两条结构化 `search_attempts`、`impact`、`disclosure`、`bounded_conclusion`。

### Contradiction

- 冲突来源分别入账，不把数字取平均或悄悄选一个。
- 先检查时间、定义、地域、样本、主体和来源独立性是否不同。
- 无法解决的重大冲突保持 `contested`，在正文显式展示其对结论的影响。

停止结论只有三种：

- `blocking`：关键主张无证据、已知地区/语言未覆盖、重大缺口未完成至少两条且彼此不同的 query/path 与 route 补搜，或重要冲突尚未分析。
- `ready_with_disclosure`：所有不可豁免的结构门已经通过，剩余真实缺口同时具备至少两条且彼此不同的 query/path 与 route、`impact`、`disclosure` 与 `bounded_conclusion`。
- `ready`：关键结论均可追溯，重大缺口和冲突已解决或对结论无实质影响。

Retained disclosure 只改变“已尽合理检索但仍不可得”的 gap 状态，不得豁免：有效 bundle、canonical plan 绑定、逐 workstream 基础 claim、非空 timeline、非空 cross-sectional matrix、横纵交汇、三情景，以及适用时的 `opportunity_map` 和双语 report contract。任一结构门失败仍为 `blocking`；缺少 link 必填字段则在更早阶段直接 `invalid_bundle`。

固定 1–3 万字不是完成标准。完成度由问题覆盖、证据质量、矛盾处理和结论可追溯性决定；长篇文字不能弥补证据缺口，简单对象也不应为了字数重复扩写。

## 11. 与子 Skill 的交接

```text
完整 brief
  -> plan_hengzong_research.py
  -> 每个 workstream 的 query_groups 与覆盖目标
  -> yichen-unified-search
  -> 标准候选清单与轻量核验
  -> 是否由用户明确要求归档且范围已经限定？
       ├─ 否：直接进入获准的原文核验与 claim-source ledger
       └─ 是：yichen-content-archive（仅限该明确范围）
              -> claim-source ledger
  -> assemble_hengzong_evidence.py
  -> 时间线、横向矩阵、交汇链、情景与停止判断
```

- `yichen-unified-search` 负责多查询发现、去重、候选级核验与缺口补搜；候选不等于最终证据。
- `yichen-content-archive` 只接收用户明确要求归档的已知链接、已确认候选，或原请求已经明确限定的公开容器；“候选已确认可用”本身不等于“要求归档”。
- 搜索完成后不得自动归档、下载或读取私人范围。只有用户当轮请求已明确要求并限定归档范围，或用户随后明确要求归档具体候选，才可越过搜索到归档的安全门。
- 横纵研究计划、候选清单和 assembler 输出都不能转移授权；账号、登录态、私人收藏、付费 API 和媒体下载继续遵守各子 Skill 的独立规则。
- 归档不是完成研究的必选步骤。若可通过已核验原文和可追溯定位完成 ledger，应避免不必要的持久化。
