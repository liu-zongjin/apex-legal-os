# 仅靠公开互联网（含维基文库）做类案检索的可行性与技术路线

> 调查日期：2026-11-02
> 目标：回答“AI 增强能否在完全不借助已接入 MCP 的情况下，仅用公开互联网（维基文库等）检索用户指令的类案”，并给出可落地的技术路径。
> 判断边界：**本文只做研究与实测，不改动任何产品代码**。网页可浏览不等于可批量调用；公开存档不等于权威发布；能搜到不等于能作为裁判依据。

## 一、结论摘要

分三层回答，避免把“能搜到”误当成“能替代”：

1. **能不能检索到类案：能，而且比预期更好。** 维基文库（zh.wikisource.org）已沉淀了带有结构化元数据（案号、法院、日期、文书类型）的裁判文书全文档层，支持全文检索、分类过滤和案号前缀浏览。本机实测：单次争点检索即可召回讨论同一争点的最高人民法院判决全文（5,000–28,000 字），且**案号写在页面标题里，可由程序确定性提取**，不依赖模型生成。
2. **能不能替代法随 MCP：不能等同。** 法随案例库的约 7,408 条是**精选权威层**（指导案例、公报案例、典型案例、法答网），带裁判要旨与权威层级；维基文库是**普通裁判全文的公开存档**，没有裁判要旨、没有权威分级、不承诺覆盖完整、页面可能被删除或改写。两者不是同一类资产。
3. **合理定位：新增“公开互联网案源”作为可选召回层 + 独立核验层，默认与 MCP 结果分级呈现，不混同、不冒充权威。** 若用户明确选择“不借助 MCP”，系统仍可给出“公开存档、待核验”的类案列表，但必须逐案标注来源类型与核验级别。

一句话判断：**技术可行，且比 ChatGPT 依赖的二手网页路径更可核验；但必须坚持“程序提案号 + 争点硬过滤 + 来源分级 + 原文快照”，否则会退化成更严重的编造风险。**

## 二、本机实测证据（2026-11-02）

### 2.1 维基文库的裁判文书规模与结构

| 观测项 | 实测结果 | 说明 |
| --- | --- | --- |
| `Category:中华人民共和国民事判决书` | 4,459,925 页 | categoryinfo 采样，量级为百万级 |
| `Category:中华人民共和国最高人民法院` | 2,819 页（含 8 个子分类） | 最高法层级可单独过滤 |
| 争点检索“建设工程价款 优先受偿权 债权转让 受让人” | 命中 2,629 条 | 全文检索（CirrusSearch）可用 |
| `incategory:"中华人民共和国最高人民法院" 建设工程价款 优先受偿权 债权转让` | 命中 72 条 | 分类过滤 + 争点词可组合 |
| 抽样正文长度 | 5,187 / 5,248 / 9,204 / 16,241 / 28,003 字 | 完整判决，含“本院认为”“判决如下” |
| 页面命名 | `(2022)京73民终3131号广州酷狗…二审民事判决书`、`中华人民共和国最高人民法院（2021）最高法知民终2480号民事判决书` | 两种命名并存，后者常为**消歧义页**，需跟链到实际文书页 |
| 页面结构 | `{{Header/裁判文书 |title|court|type|案号|year|month|day|docid}}` + 正文 | 元数据可确定性解析 |
| 分类体系 | `Category:2023年中华人民共和国民事判决书`、法院分类、`Category:中华人民共和国公有领域` | 可按年份/法院/案由收窄 |

### 2.2 检索能力的真实边界（重要）

- **案号精确检索会失败**：`"（2021）最高法民终958号"` 引号短语检索 **0 命中**；不加引号时被分词成“2021 年 / 958 号”，召回一堆无关文书。要点：**案号必须走 `intitle:` 或 `list=allpages` 前缀**，不能走通用全文检索。
- **长句检索噪声大**：把用户原问题整句送进去，返回的是主题相近、争点无关的判决（与 CASE_SEARCH_STUDY.md 记录的 MCP 问题同源）。必须做查询改写 + 争点硬过滤。
- **首次召回的“争点相关度”参差**：最高法 72 条命中里，前排混有“执行异议之诉”，需要二次重排才能把“债权转让后受让人能否主张优先受偿权”顶上来。
- **网络不稳定**：本机对 `zh.wikisource.org/w/api.php` 的请求多次出现 15–25 秒超时或连接重置（同一时段 `Special:Search` 页面可通）。生产实现必须有超时预算、重试与降级，不能假设单次必达。

### 2.3 其他公开渠道的可达性

| 渠道 | 实测/既有结论 | 可用性 |
| --- | --- | --- |
| 中国裁判文书网 `wenshu.court.gov.cn` | 首页 200，但检索需登录、验证码、动态参数 | **不可程序化检索**，不绕过（与 CASE_SOURCE_EXPANSION_STUDY.md 结论一致） |
| 人民法院案例库 `rmfyalk.court.gov.cn` | 首页 200，检索需登录 | 同上 |
| 法院官网 / 中国法院网 / 最高法公报 | 可通过通用搜索命中 | 可作“官方原文核验层” |
| 维基文库 | API 公开、有结构化元数据 | **本方案的主召回层** |

## 三、为什么维基文库能支撑类案检索

维基文库的判决页不是“网页文章”，而是**带模板元数据的文书对象**：

1. **标题即索引**：`(年份)法院代字+案件类型+序号号 + 当事人 + 案由 + 审级 + 文书类型`。案号、法院、案由、审级都能从标题解析，不需要模型猜。
2. **Header 模板即字段**：`court / type / 案号 / year / month / day / docid`，可直接映射到现有 case dict 的 `court / case_number / judgment_date / authority_type`。
3. **分类即过滤器**：年份分类 + 法院分类 + 案件类型分类，支持“只要最高法”“只要近三年”“只要民事”这类硬约束，正好补上 MCP 语义检索不支持的结构化筛选。
4. **全文即证据**：含“本院认为”“判决如下”，可以按段抽取裁判理由，满足“命中原文依据”的展示要求。
5. **确定性案号**：案号来自标题与模板，不来自模型生成——这是该路线相对 ChatGPT 的最大可信度优势（CASE_SEARCH_STUDY.md 记录的对比系统缺陷正是“案号/案名错配”）。

**必须同时承认的短板**：无裁判要旨、无权威层级、无覆盖承诺；部分页面做了脱敏（`{{PRC-redact|1}}`、某公司），部分保留真实当事人姓名；页面可能被删除、合并或改写。

## 四、与 ChatGPT 路径的差异（为什么它能“找到恰当案例”）

ChatGPT 的“类案”多来自搜索引擎已索引的**二手材料**：法院新闻稿、公报摘要、律所公众号文章、法律数据库的公开页。它能给出“支持/反对”的漂亮结构，但案号、案名经常错配（CASE_SEARCH_STUDY.md 已逐条记录）。

维基文库路线给的是**判决全文 + 标题案号**，可回溯、可核对、可存证。两者是互补关系：

- 维基文库补“原文与案号”；
- 模型补“争点理解、正反组织、说理归纳”。

真正的风险不在“搜不到”，而在“把公开存档当成权威发布”。所以本方案的核心不是加一个搜索源，而是**加一套来源分级与核验门禁**。

## 五、技术实现路径

### 5.1 总体架构（复用现有流水线，只加一个召回适配器）

```
用户问题
  │
  ├─ build_case_query_plan()                    已有：去交付噪声、争点拆解、正/反/中立三路、法院/地域约束
  │
  ├─ 召回层（并发，可裁剪）
  │    ├─ aluris MCP（权威精选，已有）
  │    ├─ yuandian（可选，已有，默认关闭）
  │    └─ public_case_web（新增）
  │         ├─ Wikisource API：争点全文 / incategory 法院 / intitle 案号
  │         └─ 通用搜索兜底：site:court.gov.cn、site:chinacourt.org（复用 public_web_search）
  │
  ├─ 结构化解析（新增）：Header 模板 → case dict；消歧义页跟链
  ├─ 争点重排（已有）：evaluate_case_fit() + rank_cases()
  ├─ 来源核验（已有，需扩展分级）：verify_case_source()
  └─ 合并去重（按案号）→ 分级呈现：权威案例 / 公开存档案例
```

关键判断：**不改 `search_cases_structured` 的输入输出契约**，只在 `parsed` 列表里多一路来源。这样 `query_plan / cases / coverage / metrics / retrieval_runs` 全部沿用，前端案例卡片、核验状态、检索运行记录都不用重写。

### 5.2 新增模块 `backend/public_case_web.py`

```python
WIKISOURCE_API = "https://zh.wikisource.org/w/api.php"
WIKI_UA = "Stella-LegalKB/1.0 (local research; contact: <owner email>)"

def build_wikisource_queries(plan: dict) -> list[dict]:
    """把 query_plan 翻译成 MediaWiki 检索式：争点组合 / 案由+争点 / 案号前缀 / 当事人。"""

async def search_wikisource_cases(plan: dict, *, limit: int = 8) -> list[dict]:
    """list=search + incategory/intitle → 标题候选（不取正文）。"""

async def fetch_judgment_texts(titles: list[str], *, batch: int = 5) -> dict[str, str]:
    """prop=revisions&rvslots=main 批量取 wikitext，去 {{gap}}/{{PRC-redact|n}} 等模板。"""

def parse_judgment_page(title: str, wikitext: str) -> dict:
    """解析 Header/裁判文书 与正文，返回与现有 case dict 同构的字段。"""

async def search_public_cases(query: str, *, top_k: int = 6,
                              sources: tuple[str, ...] = ("wikisource", "web")) -> dict:
    """对外入口：返回 cases / errors / retrieval_runs，供 case_research 合并。"""
```

解析后的 case dict 沿用现有字段（`title / case_number / court / year / source / authority_type / factual_summary / holding / matched_excerpt / source_url / viewpoint / retrieved_by`），额外增加两个字段：

- `source_kind`: `wikisource` / `official_web` / `secondary_web`
- `authority_status`: 由核验阶段写入，新增 `public_archive`（**绝不写成 `official`**）

### 5.3 查询规划：复用 + 三类改写

| 查询类型 | 生成规则 | 用途 |
| --- | --- | --- |
| 争点组合 | `required_term_groups` 每组取一个词，AND 连接 | 主召回 |
| 案由+争点 | `core_issue` 中的案由词 + 关键争点词 | 提高案由一致性 |
| 案号 | 正则抽 `[（(]\d{4}[）)][^\s，。；]{2,35}?号` → `intitle:"…"` 或 `allpages&apprefix=` | 用户点名案件 |
| 当事人 | 用户给公司/人名 → `intitle:` | 查找特定主体案件 |
| 范围限定 | `incategory:"中华人民共和国最高人民法院"` 等 | 落实法院层级约束 |

**反面清单**（实测踩过）：不要把整句问题送检索；不要用带全角括号的短语做全文匹配；不要把年份、疑问词放进检索词。

### 5.4 MediaWiki API 使用规范

- 端点：`/w/api.php`，`format=json&formatversion=2`；
- 检索：`action=query&list=search&srsearch=…&srlimit=10&srprop=snippet|wordcount`；
- 正文：`action=query&prop=revisions&rvprop=content&rvslots=main&titles=A|B|C`（一次 ≤5 页）；
- 前缀：`action=query&list=allpages&apprefix=(2021)最高法民终&aplimit=20`；
- **必须带描述性 User-Agent 并留联系方式**（维基媒体政策要求；现有 `public_web_search` 用的是 httpx 默认 UA，直接复用会被拒绝或限流）；
- 串行 ≤1 请求/秒，带 `maxlag=5`，失败指数退避；单次检索 ≤4 个检索请求 + ≤3 个正文请求，全链路预算 25 秒；
- 禁止批量镜像/抓全站；如需大规模语料，走官方 dumps（P2 再议）。

### 5.5 争点重排：直接用现成评分器

`evaluate_case_fit(texts, fingerprint)` 接受任意文本列表，维基判决全文正好适合：

```python
fit = evaluate_case_fit(
    (case["title"], case["factual_summary"], case["matched_excerpt"], case["holding"]),
    plan["fact_fingerprint"],
)
```

只有 `issue_match in {"direct"}（strict 时）/ {"direct","related"}` 才进入最终卡片——沿用 `search_cases_structured` 现有的弱相关剔除逻辑，避免"主题相关、争点无关"的判决混进来。

### 5.6 来源核验与分级

现有 `verify_case_source()` 的逻辑（抓原文 → `authority_status` / `link_status` / `identifier_match` / `holding_match` → `verified/partial/unverified`）可直接复用，但需要扩展：

| 来源 | authority_status | 说明 |
| --- | --- | --- |
| 法院官网、公报、npc.gov.cn | `official` | 现有白名单 |
| 维基文库 | `public_archive`（新增） | 可核验页面存在 + 案号 + 争点原文，但**不是官方发布** |
| 律所/媒体/数据库摘要页 | `secondary` | 仅作线索，不作依据 |
| 抓取失败 | `missing` | 降级为“待核验” |

同时把 `metrics` 增加 `public_archive_rate`、`case_number_source`（`title` / `template` / `model`），后者应当**恒为 title/template**，模型生成案号一律拒绝。

### 5.7 合并、去重与排序

- 去重键：**案号优先**，无案号时用“法院+日期+标题前 20 字”；
- 同一案号同时出现在 MCP 与维基时，保留 MCP 的权威元数据，用维基页面补全文与原文链接；
- 排序沿用 `rank_cases`（争点 tier + 权威层级 + 分数），但**权威层级里 `public_archive` 不得排到 `official` 之前**；
- 输出时分组：`权威案例` / `公开存档案例（待核验）`，并给出一行覆盖提示（如“公开存档未覆盖 2019 年以前基层法院”）。

### 5.8 API 与前端改动点

| 位置 | 改动 | 说明 |
| --- | --- | --- |
| `POST /api/case-library/search` | payload 增加 `sources: ["aluris"\|"wikisource"\|"web"]`，默认 `["aluris"]` | 向后兼容 |
| `source_mode` | 新增 `public_web_cases`（或允许 `mcp:` 组合里带 `wikisource`） | 与现有 `aluris_only` 并列 |
| 前端来源选择器 | 增加“公开互联网（维基文库）”勾选项 + 来源徽标 | 复用现有案例卡片，不加新组件 |
| 案例卡片 | 显示“来源：维基文库（公开存档）· 核验：已比对案号与争点原文” | 与 official 视觉区分 |
| 检索运行记录 | `retrieval_runs` 增加 `source: "wikisource"` | 便于复盘 |

### 5.9 引用快照（必须做）

维基页面可能被删除或改写，链接会失效。建议新增本地表（仅存摘要与哈希，不存全文，避免版权与体积问题）：

```sql
CREATE TABLE IF NOT EXISTS public_case_cache (
  id INTEGER PRIMARY KEY,
  case_number TEXT,
  title TEXT,
  court TEXT,
  judgment_date TEXT,
  source_url TEXT UNIQUE,
  source_kind TEXT,          -- wikisource / official_web
  excerpt TEXT,              -- 命中的“本院认为”段落，≤2000 字
  content_hash TEXT,         -- 页面 wikitext 的 sha256 前 16 位
  fetched_at TEXT
);
```

作用：① 二次检索不重复抓取；② 页面消失时仍能证明“当时确实存在该文书、案号与争点原文”；③ 支撑导出时的时间戳与哈希。

## 六、分阶段实施与工作量

| 阶段 | 内容 | 预估 | 风险 |
| --- | --- | --- | --- |
| **P0** | `public_case_web.py`（维基检索 + 解析 + 骨架测试）；接入 `search_cases_structured(sources=…)`；`/api/case-library/search` 增加 `sources`；15–20 个单测（用固定 HTML/JSON 夹具，不联网） | 1.5–2 人日 | 低；不动 MCP 主路径 |
| **P1** | 通用搜索兜底（法院官网/公报）+ 引用快照表 + 前端来源徽标 + 导出标注 | +2 人日 | 中；涉及前端与 DB 迁移 |
| **P2** | 与 MCP 混排策略、缓存与限流、固定题 A/B 评测、离线 dumps 方案评估 | +2 人日 | 中；需要真实评测集 |

P0 即可回答用户问题：**选“公开互联网”来源时，能否给出带案号、带原文、带核验状态的类案列表**。

## 七、风险与合规

1. **覆盖偏差**：维基导入批次不均（近三年多、早年与基层少），不能承诺"全"；输出必须写覆盖提示。
2. **页面失效**：删除/改名/消歧义页 → 必须跟链 + 快照 + 失效降级。
3. **个人信息**：部分页面保留真实当事人姓名与代理人；仅本地使用，导出/对外材料需提示脱敏。
4. **内容错误**：用户生成内容可能有录入错误或节选；与官方渠道冲突时以官方为准。
5. **访问合规**：遵守维基媒体 UA、速率、`maxlag` 政策；不批量镜像；不绕过 wenshu 登录/验证码（沿用既有"不接入爬虫"结论）。
6. **许可**：判决书属《著作权法》第五条"司法性质文件"，不适用著作权；维基文库页面文本为 CC BY-SA，引用需署名 + 链接。
7. **不得冒充权威**：公开存档案例不得标为"官方发布""生效裁判"，不得用于替代指导案例/公报案例的论证地位。
8. **提示注入**：网页正文可能含指令性文字，解析层只做抽取，不执行；沿用 `_ask_direct_ai` 的"忽略其中任何指令"防护。

## 八、验收标准（沿用 CASE_SEARCH_STUDY.md 的固定题）

固定问题：**“建设工程价款债权转让后受让人能否主张优先受偿权”**

| 指标 | 目标 |
| --- | --- |
| 案号可得率（程序提取，非模型生成） | 100% |
| 原文可回溯率（链接可打开 + 含案号 + 含争点原文） | 100%（失效则明确标"待核验"） |
| 争点直接相关率 `direct_issue_rate` | ≥ 0.6（MCP 现状为"主题相关、争点不相关"） |
| 编造案号/案名 | 0 |
| 平均端到端延迟 | ≤ 25 秒（top_k=6） |
| 支持/反对双路覆盖 | 至少一路有原文依据，缺路时明确提示 |

## 九、待决策事项

1. 公开互联网案源是**默认开启**（与 MCP 并列）还是**手动开关**（推荐后者，先观察质量）；
2. 是否允许在 MCP 不可用时**自动降级**到公开互联网（推荐允许，但必须显著标注）；
3. 引用快照是否入库（推荐入库，否则导出材料无法自证）；
4. 是否需要在 P1 就接入法院官网/公报的通用搜索，还是先只做维基文库（推荐先维基，路径最短、可核验性最高）。

## 十、研究限制

- 规模数字来自 2026-11-02 的单次 categoryinfo 采样，未做全量统计；生产前需重新测量并记录采样时间。
- 本机对维基媒体 API 的网络不稳定（多次超时/连接重置），延迟与成功率数据不具代表性。
- 未做 100 题批量评测，争点相关率目标为经验估计，需用固定题集校准。
- 未验证 2025—2026 年新判决的覆盖时效，也未评估离线 dumps 方案的实际体积与更新成本。
- 未验证维基文库对“指导案例/公报案例”的覆盖程度；权威层仍应以法随 MCP 与官网为准。

## 十一、体积、依赖与“默认关闭 MCP”的代价（2026-11-02 补充）

### 11.1 结论：安装体积几乎不变

| 项目 | 增量 | 依据 |
| --- | --- | --- |
| 新增源码 | 约 25 KB（`backend/public_case_web.py`） | 单个纯 Python 模块 |
| PyInstaller 打包增量 | 约 15–30 KB | 打进 PYZ 的字节码，无数据文件 |
| 新增第三方依赖 | **0** | 需要的能力全部已在现有依赖里 |
| 新增二进制 / 驱动 / 附属进程 | **0** | 维基文库是 HTTPS + JSON API |
| 新增模型权重 / 向量库 / 浏览器内核 | **0** | 不做本地语义索引 |
| SQLite 增量 | 约 2 KB/案，1 万案 ≈ 20 MB | 只存命中段落 ≤2000 字 + 元数据，可设上限与过期清理 |
| 运行时内存峰值 | 数 MB（解析 5 页 wikitext） | 与现有 PDF/OCR 路径相比可忽略 |

依赖核对：`httpx` 已用于 `public_web_search.py`；`jieba` 已在 `法律操作系统.spec` 中 `collect_all`（其词典约 5 MB 早已计入现有体积）；解析只需标准库 `re` / `json` / `urllib.parse`；快照只需标准库 `sqlite3`。因此 **`requirements-private.txt` 与打包 spec 都不需要改**，`backend/` 整目录以 datas 打包，新模块自动进入产物。

唯一会显著增大体积的是 **P2 的离线镜像**（维基文库民事判决 dump，按 446 万页 × 5–15 KB 估算为数十 GB 级，未实测）：明确**不做**，大批量语料一律不落地。

### 11.2 “默认不用 MCP”才是真正的改动点

把案例检索默认来源改为公开互联网，不是体积问题，而是四处行为变更：

1. **错误路径**：`/api/case-library/search` 现在在无 MCP 结果且 `errors` 非空时 `raise AlurisMCPError` → 502。公开模式必须走正常返回，只在“公开源也不可达”时降级提示，不能返回空列表假装查到。
2. **设置项与迁移**：新增“案例检索默认来源：公开互联网 / 法随 MCP / 两者”（默认公开互联网），只对**未设置过**的安装生效；已显式选择 `aluris_only` 的用户不被改写。
3. **隐私披露**：公开检索会把**用户问题的关键词**发往 Bing 与维基媒体服务器。首次启用需一次明确说明；提供“仅维基文库、不走 Bing”的收窄选项，以及“不联网”的纯本地模式。
4. **质量提示**：公开存档没有裁判要旨与权威层级，界面须常驻一行“公开存档、待核验”的说明，避免用户误当权威引用。

成本侧：维基媒体 API 与 Bing RSS 均免费、无需 Key；该路线把 MCP 的调用成本降为零，代价是召回质量与稳定性下降（实测有 15–25 秒超时）。因此“默认关 MCP”应同时保留一键切回 MCP 的入口，而不是隐藏它。

### 11.3 建议

先做 P0（适配器 + 解析 + 单测 + `sources` 参数），再决定默认值。P0 的安装体积增量可以按 **< 0.1 MB、零新增依赖** 对外承诺。

## 十二、其他公开免费案源盘点（2026-11-02，本机实测可达性）

判断口径四项：**免费**、**海量**、**持续更新**、**可程序化接入（无需登录/验证码/签名）**。同时满足四项的大陆源极少。

### 12.1 零门槛或低门槛

| 源 | 规模 | 更新 | 可接入性（实测） | 结论 |
| --- | --- | --- | --- | --- |
| 维基文库 | 民事判决约 446 万页 | 社区机器人从裁判文书网搬运，有滞后 | MediaWiki API，公开可用 | **主召回层** |
| 最高法/最高检官网（典型案例、指导性案例） | 数百至数千篇 | 随批次发布，持续 | 普通 HTML，可解析 | 权威补强 |
| 最高人民法院公报 | 1985 年起 | 月刊 | `gongbao.court.gov.cn` 当前 **502（奇安信 WAF）** | 需监控，暂不可用 |
| 12309 中国检察网·法律文书公开 | 刑事起诉书/不起诉决定书等 | 持续 | 存在公开 CMS 接口 `/cmsApi/open-api/manuscript/page`（页面内固定 Interface Key），实测可取 JSON；但文书频道 `channelCodeRegexp` 报“服务器异常”，需再验证 | 刑事补充，待验证 |
| 地方政府公共数据开放平台（杭州/四川/宜宾等） | 单市数千至数万条 | 不定期 | 数据集接口，需逐平台核许可 | 小众补充 |
| 台湾司法院裁判书查询系统 + 官方 OpenData API | 千万级 | 每日 | 有正式开放 API；**本机网络不可达（000）** | 架构范本，大陆不可用 |

### 12.2 登录墙 / 强反爬（不建议接入）

| 源 | 障碍（实测） |
| --- | --- |
| 中国裁判文书网 `wenshu.court.gov.cn` | 首页 200；检索接口 `rest.q4w` 无签名直接返回 `{"code":9}`，需 AES 签名 + Cookie + 验证码 |
| 人民法院案例库 `rmfyalk.court.gov.cn` | 首页 200，页面含登录入口，前端由“法信”驱动，需实名登录 |
| 中国审判流程信息公开网 `splcgk.court.gov.cn` | 仅返回 197 字节跳转页，需案号 + 当事人 |
| 破产重整案件信息网 `pccz.court.gov.cn` | 302 跳登录 |

### 12.3 已失效或不可达（本机 DNS/HTTP 实测）

`openlaw.cn`（302 跳转）、`basscase.com`（无 DNS）、`chinacourt.org`（无 DNS）、`ipr.court.gov.cn`（无 DNS）、`ccmt.court.gov.cn`（无 DNS）、`legalminer.com`（不可达）、`caseshare.cn`（无 DNS）。

### 12.4 收费或静态

北大法宝、法信、威科先行、无讼、聚法、Alpha 等均为付费；CAIL2018、LeCaRDv2 为静态学术集，不更新，只宜做评测基线。

### 12.5 结构性判断

大陆法院系统没有类似台湾“司法院 OpenData”那样的官方开放接口，裁判文书网与案例库都在登录墙后。因此“免费 + 海量 + 持续更新 + 可接入”在现阶段几乎只能靠**社区搬运的镜像**（维基文库）与**官网栏目**（公报、典型案例）组合，而不是靠一个官方 API。

### 12.6 附带发现：公报校验链路已受影响

现有 `aluris_mcp._search_gongbao_exact_case()` 依赖 `gongbao.court.gov.cn/QueryArticle.html`，本次实测连续两次返回 **502**（域名已指向奇安信 WAF）。这意味着“法随 MCP + 公报精确校验”里的公报兜底可能已在静默失效，建议加可达性探测与降级提示，不要假装校验成功。

## 十三、实施状态（2026-11-02）

已按第五、六节落地 P0，并顺带完成用户要求的“案例检索默认来源”设置（m00360）。

### 13.1 新增与改动

| 文件 | 改动 |
| --- | --- |
| `backend/public_case_web.py`（新增） | 维基文库适配器：`build_wikisource_queries` / `search_public_cases` / `parse_judgment_page`；MediaWiki 串行限速、`maxlag=5`、429 按 `Retry-After` 退避、IPv6 回退 |
| `backend/case_research.py` | `search_cases_structured(..., sources=("aluris",))`；`CASE_SOURCE_MCP/PUBLIC/ALL`；公开存档核验状态 `archived` / `public_archive`；`coverage.sources_used`、`metrics.public_archive_rate` |
| `backend/main.py` | `CaseLibrarySearchPayload.sources`；`/api/preferences/case-search-source`（mcp/public_web/both）；新 source_mode `public_web_cases`；公开模式专用上下文标题与提示词 |
| `frontend/index.html` | 来源菜单新增「仅用公开互联网案例」与「案例检索默认来源」三项 |
| `frontend/app.js` | `public_web_cases` 的模式/文案/白名单；`loadCaseSearchSourceDefault` / `setCaseSearchSourceDefault` |
| `tests/test_public_case_web.py`（新增） | 7 个用例；与 `tests/test_case_research.py` 合计 18 passed |

### 13.2 行为

- 选「仅用公开互联网案例」或把默认来源设为“公开互联网”后，案例检索只调用维基文库，不触碰案例 MCP；MCP 不可用不会 502，只会记 `errors`。
- 公开存档案例统一标注“公开存档已核验”，`authority_status=public_archive`，排序上排在官方来源之后。
- 网络失败（超时、429、页面缺失）降级为空结果 + `errors`，不影响「两者都用」模式下的 MCP 结果。

### 13.3 本机实测限制

- 本机 IPv4 到维基媒体不可达（`curl -4` 20s 超时），只有 IPv6 通；适配器默认走系统路由，连接超时后自动切 `local_address="::"` 并固化，IPv4-only 网络不受影响。
- 短时间大量请求会触发 Varnish 429（`retry-after: 100`）。2026-11-02 凌晨在本机观察到：`prop=revisions` 取正文多能成功（真实判决页可解析出案号、法院、日期与裁判理由），但 `list=search` 对“建设工程价款 优先受偿权 债权转让”这类高命中中文查询连续 429，而“刑法”“China”等短查询可通过——判断为共享运营商 IPv6 出口触发了 Wikimedia 的搜索池/机器人限流，不是适配器缺陷。适配器对 429 只做一次短退避（≤5 秒）后快速失败，并把“限流/稍后重试/改用 MCP”写进检索结果，避免整轮问答被拖住。
- 端到端验证：`POST /api/case-library/search`（偏好=public_web）返回 200、`source=维基文库（公开存档）`、`coverage.sources_used=["wikisource"]`；单篇真实判决 `(2022)京0491民初26309号` 解析出法院“北京互联网法院”、日期 2023-02-02、`其他法院案例` 与裁判理由摘录。

### 13.4 限流兜底（2026-11-02 二次修复）

用户实测反复出现“维基文库限流（HTTP 429）”，定位到三个并列原因，均已修复：

1. **一次 429 就整轮失败**：`_MAX_RETRIES=1`、退避上限 5 秒，检索请求被限流后直接放弃。现改为按 `Retry-After` 退避最多 15 秒重试一次；`Search is currently too busy`（CirrusSearch 以 HTTP 200 + error 返回的过载）也按可重试处理。
2. **没有备用通道**：`list=search` 被限流时整条链路就断了。现增加两条 MediaWiki 备用路径——REST 检索 `/w/rest.php/v1/search/page`（主检索失败时接管）与 REST 单页 `/w/rest.php/v1/page/{title}`（正文抓取失败时逐条接管）；`prop=revisions` 批量失败后同样回落到单页接口。
3. **没有缓存，重复提问每次都要重新撞限流**：新增三级 SQLite 缓存（与主库同目录 `legal_kb_public_case_cache.db`）——最终结果（7 天）、命中标题（1 天）、判决正文（30 天）。命中缓存时 `retrieval_runs[].cache="fresh"`，完全不走网络；全部失败时若仍有 30 天内的旧结果，标记 `cache="stale"` 并注明抓取时间，而不是直接报“未取得案例”。

另外把 IPv6 偏好改为进程级一次性探测（1.5 秒 TCP 连 `zh.wikisource.org:443` 的 AAAA 地址），避免首个请求先白等 6 秒 IPv4 超时；检索式按词袋去重，两条同义查询只发一次；单次检索最多取 2 篇正文，整体预算 32 秒。

实测（2026-11-02 凌晨，本机共享出口仍处限流窗口）：冷启动一次检索 5～22 秒，成功时返回 3 篇带案号/法院/裁判理由的公开存档案例；同一问题第二次 0 秒命中缓存。

### 13.5 正文接口限流与「摘要成卡」降级（2026-11-02 凌晨追加）

**现象**：用户重启后仍反复看到「维基文库限流（HTTP 429）」。复测发现限流并不均匀：`action=query&list=search` 基本可用，**正文接口**（`/w/rest.php/v1/page/…` 与 `prop=revisions`）在同一出口连续取数后会被单独限流，`retry-after` 可达 100 秒级。

**处置**（`backend/public_case_web.py`）：

- 正文抓取改为**一次批量** `prop=revisions&titles=A|B|C`（原来逐页 REST，一次检索会发 3—4 次请求），失败再补 1 页，整体预算 12 秒；
- 抓不到正文时**先按检索摘要成卡**（`parse_search_hit`）：案号从标题正则提取，法院从标题推断，争点命中句取摘要；卡片带 `body_fetched=False`，前端与 Markdown 标注「公开存档摘要（未取正文）」；
- 检索式再降一级：主查询 → 截短两词 → REST 检索 → 原式 REST 检索，四步都失败才报限流；
- `backend/case_research.py`：严格争点筛选全空且来源含维基文库时，回退最多 2 条 `related` 候选，并在结果首部写明「未检得完全命中全部争点要素…不足以单独作为裁判依据」。

**实测**：摘要路径 4.3 秒返回 2 篇（含案号缺失、法院「结果未提供」的诚实标注）；正文可用时冷启动 20 秒左右返回 3 篇并落缓存，同一问题二次 0 秒。

**已知代价**：摘要模式下案号/法院可能缺失，裁判理由为空；这类卡片只能用于「找线索」，不能直接引用，用户需点开维基文库原文核对。
