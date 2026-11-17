# PDF source discovery — rules and fixed evidence

The current P1–P5 coordinator serves public Download. Workspace collection saves
reusable page/API clues; PDF-only refresh does not restart completed metadata
collection. Transfer, original DownloadItem responses, file publication and local
body operations are described in [body downloads](body-downloads.md).

This document owns source order, platform/input conditions and the R/API/S
catalogue. Fixed external observations retain their original dates and evidence
limits; they are not current Allfold live-test results. Task, page and transfer
policy belongs to the linked module guides, not the historical research process.

## Component entry points

| Entry | Responsibility |
| --- | --- |
| `document_metadata_branch()` / `collect_document_metadata()` | One captured collection branch reads independent Date/Abstract and PDF clues in one detached snapshot, emits one increment, and settles partial failure explicitly. |
| `read_document_pdf_clues(context, ...)` | PDF-only article/qualified-reader refresh; returns current candidates, operation-local navigation/access and separately persistable facts without emitting or restarting collection. |
| `iter_p1_candidates()` / `iter_p2_candidates()` | Pure Host/type/input-qualified lazy rules; no requests or completion claims. |
| `PdfDiscovery(...).run(consume)` | P1–P5 coordination with downstream `CandidateResult` feedback, source/fallback semantics and captured cancellation/authority. |
| `PdfHttpClient` / `PdfDiscoveryIO` | Independent paced HTTP, bounded current response/API parsing and optional fixed native reads; no temporary downloader. |
| `submit_pdf_discovery(host, paper, target=..., ...)` | Internal read-only task using captured Paper/Workspace/access qualification, existing reservation/scheduler and actual resource settlement. Completed collection remains unchanged. |

The core lives in `src/allfold/pdf_discovery.py`, rules in `pdf_rules.py`, adoption
metadata in `pdf_catalog.py`, response parsing in `pdf_responses.py`, and scoped
HTTP in `pdf_http.py`. `pdf_facts.py` owns the bounded version-1 persistable
contract. The read-only adapter is `application/pdf_discovery.py`; it remains
read-only. Public Download is composed by `application/body_downloads.py` using
the same coordinator inside its body reservation, without nested read-only
admission or a second source deque. Production Run registration belongs to the
separate `application/collection_planner.py` and Workspace registry.

The core accepts canonical `journal-article`, `conference-paper` or `unknown`
target types. Explicitly unsupported types return `not-applicable` without
consuming a candidate or querying, including when cached clues exist. The task
entry rejects those targets before reserving a Paper or creating clients. A
formal target Work's own repository/Preprint PDF locations remain eligible.

Only a downstream PDF-type result with normal transfer completion sets a
successful `pdf_source`. A PDF response without that consumer remains pending;
the discovery HTTP client does not read a possible PDF body to identify its type or claim transfer. MIME is only a discovery hint; byte identification belongs to the actual transfer owner. A local
failure ends the task. Current signed URLs/Referer stay operation-local; stored
facts contain stable fields or explicit refresh locators. Same-reader parsing
keeps its original discovery phase and ordinary redirects/retries are not
fallbacks. Current implementation limits and response handling are not additional
source-rule requirements. Lists are matched and deduplicated before byte capacity is applied; partial observations preserve qualified increments. OpenAlex uses all eligible distinct locations, best first. The parent deadline, memory capacity, exact response/edge loop guards and ordinary transient retry policy bound work; arbitrary operation/hop/transfer counts do not. See [body downloads](body-downloads.md).

Python discovery HTTP validates each actual request/redirect and checks resolved
addresses before dispatch. This is a DNS preflight, not transport-level address
pinning: OS/proxy resolution may occur again. Native fixed-reader navigation has
its own per-hop static public-URL gate and does not claim DNS resolution coverage.
Neither check expands Prepare/institution navigation or forwards credentials to
an arbitrary next hop. Real platform/account compatibility requires separately scoped acceptance.

## Fixed external evidence

| 固定依据 | 可借鉴机制与边界 |
| --- | --- |
| [JabRef DoiResolution](https://github.com/JabRef/jabref/blob/d79f1490aaafa9bc80da760d1baa6497cebf7c01/jablib/src/main/java/org/jabref/logic/importer/fetcher/DoiResolution.java) | 明确 Meta、正文入口歧义与原始 URL 大小写保护；不采用其额外 isPdf 网络探测或默认 Referer。 |
| [Parseland find_pdf.py](https://github.com/ourresearch/parseland/blob/442a300a247aee1f4b8b7e75aaa2b105aee52626/find_pdf.py) | 已观察的平台限定 URL 转换与正文入口筛除；本规格明确排除其中全局 epdf/ScienceDirect/Nature 重写、任意 JS 扫描、HEAD/GET/内容 Validation 和 Zyte 回退。 |
| [Paperlib webcontent-embed-entry-scraper.ts](https://github.com/Future-Scholars/paperlib-entry-scrape-extension/blob/f3ea1065fe6d9b82f081f170432b98a819171150/src/scrapers/webcontent-embed-entry-scraper.ts) | 学术 Meta 与 PDF 字段同页读取的实际实现；不引入 Cookie 转交、正文头尾检查或自动下载。项目代码许可未确认，不能据字体许可复制源码。 |
| [Electron 45 net-fetch.ts](https://github.com/electron/electron/blob/54f961b44b83e4ece81065ab60a182fd0c38c01e/lib/browser/api/net-fetch.ts#L83-L138) | 当前响应构造与请求头传递支持最终 URL/Referer 的具体接入约束；Allfold 行为仍需固定 Electron fixture。 |

## PDF 来源规则

以下记录来源选择、平台适用条件和证据。取得有效 PDF 指当前响应类型与正常传输完成，不指 PDF 文件结构或版本检查。规则预采集与实际下载尝试分离，P1–P5 规定 Download 的来源顺序。文件落位与数据库关联见 [body downloads](body-downloads.md)。

<a id="scope"></a>

### F1 目标与边界

#### F1.1 目标

根据目标论文的 DOI、已知 Platform、已有文章 URL 或内部标识符，优先构造 PDF 候选地址。下载操作按 P1–P5 使用适用来源；必要时才增加标识符查询或重新进入官方文章 HTML。Run 后采集已经得到的页面线索可以直接复用，不要求为了来源顺序丢弃它们。

PDF Source Discovery 不运行 Zotero Translator、Zotero Translate 或 Zotero Utilities。借鉴已有项目中的 Host 映射、URL 表达式、字段位置和访问条件，形成独立的确定性规则。

平台级适配和共享出版系统的规则复用已经有成熟实现支持，直接作为设计依据。后续核查集中于具体规则的适用条件和实现行为，不重新论证平台级提取是否可行。

#### F1.2 概念与输入

| 概念 | 本规格中的含义 |
|---|---|
| Paper | 已经确定的目标论文，不重新通过标题搜索选择另一篇文章 |
| Platform | 实际承载内容的平台及其 Host，是规则选择的主要依据 |
| Service | CARSI 等访问服务所提供的授权环境；不直接决定 PDF 路径 |
| 特殊标识符 | PII、`article_number`、`resourceId`、stable ID、AN 等平台字段 |
| PDF candidate（候选请求） | 指向 PDF 或明确下载入口的候选请求，不等于已经取得 PDF；与正文 Candidate 文献视图区分 |
| 中间页面 | 已知下载链中的 HTML 阅读器、下载中转页或提供下一跳的页面 |

发现过程可利用 DOI、Platform、内容类型、已有文章 URL、已有内部 ID、后台预采集结果，以及下载时按需取得的文章 Document。发现器本身不要求为了统一输入结构额外加载 HTML；此前 Run 的网页采集仍按整体工作流执行。

默认对象是论文正文 PDF。期刊与会议论文规则按内容类型分别匹配；图书、章节和补充材料不自动扩展为默认抓取范围。已有 URL 的 JMLR/PMLR 规则可以保留，不额外建立无 DOI 文献检索流程。

#### F1.3 明确的非目标

不进行 PDF 版本识别、版本评分、全文语义比对、PDF/OCR 元数据提取或跨版本替换；不增加 Unpaywall、Semantic Scholar 等新的外部全文回退服务；不建立 LLM 网页决策或新的登录/验证码处理系统。现有 Prepare 和 Cloudflare solver 由统一网页访问层接入，发现器不自行实现挑战处理。

当前 Workspace 已使用 SQLite 与独立正文文件。页面采集的固定快照接口和独立 Document 解析见 [Document access](browser-documents.md)；本目录不限定页面采集载体。

<a id="pipeline"></a>

### F2 确定的发现顺序

#### F2.1 五级来源顺序

| 阶段 | 行为 | 启动条件 |
|---|---|---|
| **P1：DOI 直接模板** | 以确认的 Platform、内容类型和 DOI 构造有限的 PDF 候选 | 对应模板已纳入采用目录，且适用条件满足 |
| **P2：内部 ID、已有 URL 与条件性查询** | 使用已有 PII、`arnumber`、stable URL、`resourceId` 或可转换的文章 URL；确有缺项时查询 Handle、Crossref 或已有凭证的官方接口 | 缺少 P1 规则，或 P1 未取得有效 PDF |
| **P3：官方文章 HTML Meta** | 从目标论文页面读取 `citation_pdf_url`、`fulltext_pdf_url` 等明确 PDF 元数据 | 前述适用路径没有成功 |
| **P4：DOM 与平台专用解析** | 读取正文下载链接、明确属性、下载表单 action、已知页面状态及阅读器入口 | Meta 没有产生可用结果，或其候选失败 |
| **P5：现有 OpenAlex 回退** | 沿用已确定的 OpenAlex PDF 候选机制 | 出版平台的适用路径已经结束且仍未取得有效 PDF |

阶段顺序来自已有讨论，并得到本次材料的支持。原项目的执行顺序与本规格的顺序分别记录：某个表达式只需要 DOI，不代表源项目已经在没有 HTML 的情况下调用它；本规格将具备所需输入的构造规则提前使用。[S096](#s096)、[S017](#s017)、[S018](#s018)

#### F2.2 按条件执行，不固定遍历所有来源

每条规则先检查输入、Host、内容类型和授权条件。条件不满足时跳过，不为凑齐流程而请求接口或打开页面。

- 已有 PII、`arnumber`、资源 ID 或完整文章 URL，直接使用，不再次查询相同信息。
- P1 下载完成时，本次 PDF 操作不再请求 Handle/Crossref、不额外加载文章 HTML，也不调用 OpenAlex；不否定此前 Run 已完成的网页/API 采集。
- P1 不适用时，直接进入第一个适用阶段；不对所有平台试探 `/doi/pdf/`。
- P2 的 Handle、Crossref 和官方 API 不是固定串联步骤。按缺少的信息选择相应来源，前一次结果足够时停止补查。
- P1 模板先行；已经具备资格的 P2、已有 P3 和稳定 P4 候选中，直达 PDF 先于 Reader、表单动作及可选的缺失输入 API 查询，同类候选保持来源次序。这是所有平台的共用优先级，不为找更多候选而提前请求新页面。partial 快照、可能补出的 P3 或无关刷新线索不强制先重开文章。已有候选失败、缺失或动态入口确需更新时，再按需执行 PDF-only 取页；当前 Document 与因此新获资格的模板也采用直达优先，不重发已试 P1/P2 URL 或重启缺失输入 API，不把动作/刷新定位信息当 GET。原 Paper、候选来源阶段、实际 Service、签名和访问上下文仍保留；P5 仍在后面。
- 规则在某个阶段取得新的 ID 或明确下载地址，可以就地完成其依赖链。无需为了阶段编号重新开始整个流程。

#### F2.3 中间页面随候选处理

中间页面解析不是所有论文必经的第六阶段。P1、P2、P3 或 P4 的候选返回已知结构的 HTML 时，可就地执行对应解析，取得下一跳后继续尝试。

普通 R024（包括带签名 GET）先走业务 Session；缺少 `md5` 不触发文章预读。HTML/JSON 先利用当前响应解析；必要 Reader 执行后，实际导航 URL 或访问进展可返回 Session，不要求最终正文仍满足起始 Reader 模板。普通 GET 的实际 HTTP 重定向可跨 origin，逐请求保留 URL/DNS、凭证作用域与实际 access 绑定；不局限于两组出版商 CDN 关系，也不计为换来源。原表单/一次性动作另保留原请求语义。

例如，ScienceDirect 的 `/pdfft` 返回可识别的 Meta Refresh 页面，可以直接跟进；IEEE 已有 `arnumber` 时先尝试 `getPDF.jsp`，失败后才考虑 `stamp.jsp`。只有当前路径无法继续时，才进入后续来源。[R024](#r024)、[R025](#r025)

#### F2.4 唯一成功停止条件

候选成功构造、HTTP 200、发现 `citation_pdf_url` 或取得一个阅读器 URL，都不是最终成功。**真实传输方用当前响应或已归属输出的五字节 `%PDF-` 前缀确认类型，且传输正常完成后，立即停止后续发现。** 不另设 PDF Validation；具体传输与终态见[body downloads](body-downloads.md)。

不因为取得的 PDF 可能来自其他出版版本而继续寻找；不添加版本字段、版本比较或升级流程。正文链接与补充材料链接仍根据页面上下文区分，这不涉及 PDF 内容或版本核验。

传输已经正常完成后，来源发现即停止。最终文件落位、Paper 关联或状态写入失败属于本地任务失败，结束本次 Download，不因本地失败再尝试其他 PDF 来源。用户看到的 completed 以[body downloads](body-downloads.md) 定义的整项下载终态为准。

<a id="rules"></a>

### F3 平台路由与轻量规则

#### F3.1 以内容 Platform 和 Host 选择规则

使用已有的 Platform 信息和确切内容 Host。共享 CMS 只决定可以复用哪些解析函数，不把其所有客户站点视为路径、授权和内容类型完全相同。

DOI 前缀只作辅助线索。既有目标 URL 或解析结果表明内容已经迁移时，以目标平台为准；不把某次论文跳转固化为整个 DOI 前缀的永久映射。已有明确 Platform 时，不要求每篇论文额外执行 DOI Resolution。[S097](#s097)、[S067](#s067)

需要补充目标 URL 时，可以使用 Handle 或有界的正常重定向。返回 URL 仍可能指向 LinkingHub 等中转站，应按已知 Host/路径识别，不把任意 URL 最后一段当作平台内部 ID。

#### F3.2 轻量规则需要保存的信息

规则目录不复制 Zotero 的 Item、Translator 注册、导入导出或 Sandbox 体系。每条规则只需明确以下语义；对应实现见上面的组件入口。

| 信息 | 用途 |
|---|---|
| 稳定规则编号 | 保留本材料的 `R001`–`R072`，关联来源和诊断 |
| Platform、Host 和内容类型 | 限定适用对象，防止跨平台替换 |
| 所需输入 | DOI、内部 ID、文章 URL、Document 或页面状态 |
| 规则种类 | DOI 构造、ID 解析、URL 转换、Meta、DOM、中间页解析 |
| 表达式或确定性提取位置 | 生成 URL 或读取下一步所需字段 |
| 条件性变体 | 说明变体的 Host、前置条件及尝试顺序 |
| 请求上下文 | 必要的 Referer、既有授权上下文及接口凭证条件 |
| 采用状态和来源 | 区分默认、条件性、扩展/待核和历史记录；保留固定源码链接 |

#### F3.3 规则采用状态

**默认规则**指已纳入能力范围、在自身条件满足时执行，不表示适用于该平台所有内容。

**条件性规则**指证据或输入限制更窄的候选，例如 SPIE 的内容类型分支、Springer 的有限变体、ClinicalKey 的独立会话。限制必须与规则同时保存。

**扩展/待核材料**不进入默认链，例如 T&F eBooks、尚未明确边界的 MDPI CDN 推导。**历史规则**也不进入默认链，失败后不得将历史库整体作为追加候选池。

附录 A 给出全部 72 条记录的采用处置。该目录保留研究分类，不把已有文章 URL 转换静默提升为通用 DOI-only 模板。

<a id="doi-templates"></a>

### F4 DOI 直接模板

#### F4.1 纳入的主要模板

`{doi}` 表示完整 DOI。路径和参数编码由对应规则明确规定；下表保留材料中的路径、大小写和参数，不统一追加 `download=true`。

| 规则 | Platform / Host | PDF 候选 | 适用限制 |
|---|---|---|---|
| [R001](#r001) | Springer Link · `link.springer.com` | `/content/pdf/{encodeURIComponent(doi)}.pdf` | 只用于确认的 Springer Link，不以出版社集团名替代实际 Host |
| [R002](#r002) | Wiley · `onlinelibrary.wiley.com` | `/doi/pdfdirect/{doi}?download=true` | 网页候选，不要求为此配置 Wiley TDM token |
| [R003](#r003) | T&F/Routledge 期刊 · `www.tandfonline.com` | `/doi/pdf/{doi}` | 与 eBooks/章节机制分开 |
| [R004](#r004) | NEJM · `www.nejm.org` | `/doi/pdf/{doi}` | 使用 NEJM 自身 Host 和访问上下文 |
| [R005](#r005) | SAGE · `journals.sagepub.com` | `/doi/pdf/{doi}` | 不因共享 Atypon 而追加其他 Host 的参数 |
| [R006](#r006) | Annual Reviews · `www.annualreviews.org` | `/doi/pdf/{doi}` | 保留现有源码表达式，不因网站迁移公告直接删除 |
| [R007](#r007) | Frontiers · `www.frontiersin.org` | `/articles/{doi}/pdf` | 不需要先取得 numeric article ID |
| [R008](#r008) | ACM · `dl.acm.org` | `/doi/pdf/{doi}?download=true` | 原实现有页面下载入口判断；本规格仅提前使用构造表达式，失败后回退 |
| [R009](#r009) | Project Euclid · `projecteuclid.org` | `/journalArticle/Download?urlId={encoded_doi}` | 期刊论文；证据为官方链接实例与日志解析器；安全检查 HTML 不算 PDF |
| [R010](#r010) | AIAA · `arc.aiaa.org` | `/doi/pdf/{doi}` | 内容 Host 确认后使用 |
| [R011](#r011) | AJR · `www.ajronline.org` | `/doi/pdf/{doi}?download=true` | 保留 Host 限制 |
| [R012](#r012) | SPIE 期刊 · `www.spiedigitallibrary.org` | `/journalArticle/Download?urlId={encoded_doi}` | 条件性纳入，必须确认期刊文章类型 |
| [R013](#r013) | SPIE 会议论文 · 同上 | `/Proceedings/Download?urlId={encoded_doi}` | 条件性纳入，保留大写 `P`；不发送期刊论文到此入口 |
| [R014](#r014) | Science/AAAS · `www.science.org` | `/doi/pdf/{doi}` | 不能推广为所有 Atypon Host 的默认表达式 |
| [R015](#r015) | PNAS · `www.pnas.org` | `/doi/pdf/{doi}` | 历史 HighWire 路径另按已有 URL 处理 |
| [R016](#r016) | RSNA · `pubs.rsna.org` | `/doi/pdf/{doi}?download=true` | Host 绑定 |
| [R017](#r017) | World Scientific · `www.worldscientific.com` | `/doi/pdf/{doi}?download=true` | Host 绑定 |
| [R018](#r018) | PLOS ONE · `journals.plos.org` | `/plosone/article/file?id={encoded_doi}&type=printable` | 其他 PLOS 期刊需要有依据的 journal slug；`manuscript` 是 XML |

上述规则均生成候选，不预先承诺获得 PDF。Euclid、SPIE 的实例证据与完整下载器实现分别保留；不把研究时遇到的挑战 HTML 或超时改写为实站成功。

#### F4.2 有限变体

Springer [R019](#r019) 的 `{doi}_reference.pdf` 只保留为材料记录的特定在版场景候选：确认 Springer Host、常规路径未成功且具备该场景依据时，才允许追加。它不是所有 Springer 论文、所有 `/articles/*.pdf` 或其他平台的通用重写。

Wiley、Atypon、EMBO 的 `/pdf/`、`/epdf/`、`/pdfdirect/`、`/pdfplus/` 变体按各条规则运行。未列入的变体不自动排列组合，也不将整段 URL 中的 `epdf` 全局替换。[S003](#s003)、[S026](#s026)

#### F4.3 从默认 DOI 模板中移出的早期判断

| 平台 | 收敛后的处理 |
|---|---|
| Nature | 不使用全站 DOI suffix 直接拼 article ID，也不统一删除点号。现代页面使用 Meta/DOM；已知旧文章 URL 时使用受限路径转换。材料同时给出保留点号和删除点号的反例。[R028](#r028)、[R037](#r037) |
| MDPI | 不按固定两位卷号拆分 DOI。默认使用 Meta；CDN 推导只保留为扩展材料，须先具备可靠的 volume、article number、slug 和文件命名条件。[R027](#r027)、[R042](#r042) |
| ACS | 默认采用当前 Silverchair 页面入口；旧 `/doi/pdf/{doi}` 留在历史候选中，不默认执行。依据是材料记录的 2026-07-24 迁移及新页面源码。[R044](#r044)、[R072](#r072) |
| RSC | 不把旧 `articlepdf` 路径提升为当前全站模板。迁移后字段尚未由材料确认，使用当前页面实际提供的明确 Meta/下载入口；旧规则待核。[R040](#r040) |
| Cambridge Core | 没有纳入通用 DOI suffix → PDF 模板。旧 `content/view/{suffix}` 保留历史记录；当前以 Meta/DOM 为依据。[R051](#r051)、[R071](#r071) |

<a id="identifiers"></a>

### F5 特殊标识符与已有 URL

#### F5.1 P2 的统一原则

按以下次序利用信息：已有标识符或明确 PDF URL；已有文章 URL 的平台转换；确实缺少字段时的条件性查询。引用或元数据响应已经给出明确 PDF 地址时，可以直接保留，不强制先转换成内部 ID。

Handle、Crossref 和官方 API 的响应按用途解释。登记 URL 不等于 PDF URL，`alternative-id` 不等于 PII，`fulltext` 不等于 PDF，`relation` 中的另一篇作品也不等于当前目标。

#### F5.2 DOI Handle 与 Crossref

**DOI Handle：** `https://doi.org/api/handles/{doi}?type=URL`。从 `values` 中选择 `type=URL` 的记录，读取 `data.value`；所得登记目标可用于识别 Host、PII、`arnumber` 或已知文章路径，必要时继续正常重定向。[API01](#api01)

**Crossref：** `https://api.crossref.org/works/{doi}`。使用目标记录的 `alternative-id`、资源 URL 和 `link[]`。PDF 候选需依据 `content-type` 及必要的 `intended-application` 条件判断；XML/JATS 地址不能作为 PDF 返回。已有的响应可直接利用，不要求重新发起一次查询。[API02](#api02)

只检查已知字段，不扫描 `relation` 或参考文献列表寻找任意替代 PDF。资料中的 PII/ID 查询覆盖不完整时，继续 HTML 回退，不猜测内部编号。

#### F5.3 Elsevier / ScienceDirect

**输入：** DOI、已有 PII，或明确包含 PII 的平台 URL。[R024](#r024)

优先利用已有 PII；其次使用已取得的 Crossref `alternative-id` 或 Handle/重定向目标中的 `/pii/`。需要补查时，按缺项使用对应来源。Crossref 替代 ID 必须经过平台形状检查，不取任意第一项。

材料中的常见规范化 PII 检查为：

```text
[SB][0-9]{7}[0-9X][0-9]{7}[0-9X]
```

这是一条已有实现支持的格式边界。未匹配的旧值或其他格式不得强行截断、拼接；该解析路径返回无合格 ID，继续其他路径。[S002](#s002)

有合格 PII 后生成：

```text
https://www.sciencedirect.com/science/article/pii/{PII}/pdfft
```

已有可信文章 URL 时保留其实际 origin（协议及端口）和必要 Referer，不把文章查询参数当作 PDF 签名生成。已取得的正文 URL 原样使用。`?download=true` 作为该平台已有依据的变体处理。如果已取得的 Elsevier API 响应包含 `coredata.link` 中的 `rel=scidir-pdf`，直接使用该候选，不再要求 DOI → PII → URL。[S109](#s109)

Cell Press 的 [R023](#r023) 使用 `https://www.cell.com/action/showPdf?pii={pii}`，输入可来自 `fulltext`、`pdfExtended` 或 `showPdf` URL。保留其有标点 PII/端点条件，不把 ScienceDirect 的规范化与 Host 直接套到 Cell。

#### F5.4 IEEE Xplore

**标识符：** `article_number` / `arnumber`。[R025](#r025)

已有 `/document/{id}`、明确查询参数或可信元数据字段时直接使用。缺失时可以从 DOI 登记目标补充；已有 IEEE API key 时，可按 DOI 查询 Metadata API，使用返回的 `article_number` 或 `pdf_url`。字段缺失时继续回退，不从 DOI 末尾数字猜测编号。[API03](#api03)、[API04](#api04)

已知编号后先尝试：

```text
https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber={article_number}&ref=
```

失败时才进入 `stamp/stamp.jsp` 的已知阅读器路径。官方名为 `fulltext` 的接口不作为 PDF 二进制保证。[API05](#api05)

#### F5.5 Oxford Academic / OUP

已有可靠 `resourceId` 时，可请求：

```text
https://academic.oup.com/Citation/Download?resourceId={resourceId}&resourceType=3&citationFormat=2
```

解析 BibTeX 的 `eprint`，将明确 PDF URL 作为候选。没有 `eprint` 或结果只是文章页面时，继续 Meta/DOM，不将文章 URL 标记为 PDF。[R020](#r020)

PaperMemory 原实现直接取 URL 末段，并未校验其是否是资源 ID。本规格只在规范文章路径、已有字段或页面引用链接能明确支持 `resourceId` 时使用；不直接采用任意 URL 的最后一段。该端点行为限定于 OUP，不能据此推广到所有 Silverchair Host。

#### F5.6 JSTOR

使用实际 `/stable/` URL 中的标识符构造 `/stable/pdfplus/{stable_id}.pdf`；Zotero 的 `acceptTC=true` 作为其有来源的变体记录，不解释为自动同意条款或绕过确认页。[R022](#r022)、[S094](#s094)

stable ID 可以包含 DOI 样式字符串和斜杠，不限定全数字。JSTOR TDM 的 UUID `item_id` 不能代入 stable PDF 路径；TDM 返回 OCR 数据的流程也不加入 PDF 来源链。[S088](#s088)

#### F5.7 已有文章 URL 的转换

| 规则 | 所需信息 | 采用的转换边界 |
|---|---|---|
| [R028](#r028) Nature / Palgrave 旧路径 | 完整旧文章 URL | 仅对已匹配的 `/full/`、`/abs/` 结构转 `/pdf/` 并修改扩展名 |
| [R029](#r029) IOPscience | 已有文章 URL，或已确认的现代 `/article/{doi}` 结构 | 清理规则指定的页面后缀后加 `/pdf`；保留完整 DOI 的多级斜杠 |
| [R030](#r030) APS 网页 | 已有 URL，或 journal slug + DOI | `/{journal_slug}/abstract/{doi}` 转 `/{journal_slug}/pdf/{doi}`；不猜 slug |
| [R031](#r031) ASCO/JCO | `ascopubs.org` 上匹配的已有链接 | `/doi/full/` 转 `/doi/pdfdirect/` |
| [R032](#r032) AHA | `ahajournals.org` 上匹配的已有链接 | `/doi/reader/` 转 `/doi/pdf/`；不由 DOI 前缀判断其当前托管平台 |
| [R033](#r033) Healio | `journals.healio.com` 上匹配的已有链接 | `/doi/epdf/` 转 `/doi/pdf/` |
| [R034](#r034) Chicago Journals | `journals.uchicago.edu` 上匹配的已有链接 | `/doi/full/` 转 `/doi/pdf/` |
| [R035](#r035) JMLR | volume + 文章 key，来自已有文章 URL | `/papers/v{volume}/{key}.html` 转 `/papers/volume{volume}/{key}/{key}.pdf` |
| [R036](#r036) PMLR | volume + 文章 key，来自已有文章 URL | `/v{volume}/{key}.html` 转 `/v{volume}/{key}/{key}.pdf` |

这些规则保留 P2 的输入资格。特别是 Parseland 的转换代码来自已发现的 HTML 候选，不能据其表达式将所有同族 Host 升格为无条件 DOI 模板。

<a id="html-discovery"></a>

### F6 HTML Meta 与 DOM 发现

#### F6.1 P3：标准化 PDF 元数据

只处理目标文章页面中明确表示 PDF 的字段，顺序固定为 `citation_pdf_url`，随后 `fulltext_pdf_url`。此顺序是本规格的选择，不沿用 findpapers 中按 DOM 出现顺序返回第一项的实现细节。[S095](#s095)、[S096](#s096)

同字段出现多个值时，保留顺序、去除空值和重复候选；只纳入目标主文章的值，不扫描引文、推荐论文或搜索结果卡片。相对地址以实际响应后的页面 URL 为基础解析。字段存在不等于下载完成，仍由下载层使用当前响应类型和传输终态报告结果。

Meta 值指向 HTML 下载器时进入适用的中间页规则。不能因为 URL 不以 `.pdf` 结尾而丢弃，也不能因包含 `.pdf` 就把实际 HTML 响应当作 PDF。

#### F6.2 P4：明确 DOM 入口与平台选择器

先使用匹配 Platform 的确定性选择器，再使用明确表示正文 PDF 的通用链接。已知选择器减少歧义，不要求平台必须有独立解析框架。

| 平台或机制 | 已有依据的入口 | 规则 |
|---|---|---|
| Silverchair 共用 | `a.article-pdfLink[href]` | [R044](#r044)–[R050](#r050)，保留各 Host 差异 |
| JAMA | `a#pdf-link[data-article-url]` | [R046](#r046) |
| ACS | 当前 Silverchair PDF 链接；引用链接提供 `resourceId/resourceType` | [R044](#r044)，不自动推广 OUP 的 BibTeX `eprint` 行为 |
| Cambridge Core | 期刊 Meta；材料中图书/章节另有 `.actions a[target='_blank'][href*='.pdf']` | [R051](#r051)，期刊与图书分支不混用 |
| Nature | Meta；`a[data-track-action='download pdf']` | [R037](#r037) |
| Atypon | 已识别实际期刊 Host 与 DOI 复用通用直达入口；已有专用 P1 模板优先，DOM/Reader 保留为回退 | [R039](#r039)、[R061](#r061) |
| De Gruyter Brill | `a.downloadPdf[href]` | [R054](#r054)，与 `brill.com` 规则分开 |
| Emerald | `a.intent_pdf_link[href]` 或已在 `full/pdf?` 的当前 URL | [R055](#r055) |
| eLife | `.article-download-list a[href]` 中明确 PDF 入口 | [R057](#r057)，不猜文件版本后缀 |
| Microbiology Society | `.download-pdf form.ft-download-content__form--pdf[action]` | [R059](#r059)，只提取有依据的 action，不据表单形态推定必须 POST |
| BioMed Central、MDPI、PLOS、Brill、Thieme、HighWire、Copernicus | 学术 PDF Meta，必要时采用对应站点明确下载入口 | 各自的 [附录 A](#rule-catalog) 规则，不按出版社名称硬套另一平台路径 |

通用链接识别结合文字、`title`、明确的类型属性及文章区域上下文。补充材料、Supporting Information、Supplementary、整期文件及其他论文链接不得因包含 `pdf` 而作为当前正文首选。存在多个无法消除歧义的文件入口时，不随机选择；使用更具体的平台规则或结束该路径。[S106](#s106)、[S017](#s017)

#### F6.3 明确页面状态与引用响应

允许读取已知结构中的数据，例如 ScienceDirect 的 `article.pdfDownload.urlMetadata`、LWW 的 `pdfDownloadDetails.pdfUrl`。只读取字段，不执行从网页取出的 JavaScript，也不遍历任意 JSON 中所有名为 `url` 的值。

引用导出响应只承担已有证据支持的任务，例如 OUP 的 BibTeX `eprint`。不因为某接口返回 RIS/BibTeX，就假定其中一定存在 PDF 地址。

#### F6.4 与 Date + Abstract 的边界

由 Run 注册、Workspace 持有的 Paper 网页采集一次捕获已渲染 HTML、实际 URL 和必要运行态值，在同一独立 Document 上完成 Date/Abstract 与 PDF 线索解析。PDF-only 刷新与 Reader 续读各自读取新快照，不重新采集字段；局部解析失败保留其他有效输出，后续活页面变化不撤销已捕获结果。候选自身的正文/补充资料/推荐条目与 URL 安全规则继续适用，PDF 信息采集不自动触发下载。

小型结果保存后释放工作页面。之后下载重新开页，仅执行 PDF 必需的读取/动作，不再次运行已完成的 Date/Abstract。独立提取函数的结果由外层任务包装，不能合并成负责网络、采集、下载和持久化的巨型模块。

<a id="intermediates"></a>

### F7 受控中间页面与特殊平台

#### F7.1 先判断响应，再决定是否解析

| 返回结果 | 发现层行为 |
|---|---|
| 实际前缀辨识为 PDF 且传输完成 | 成功并停止所有后续来源，不做全文或结构检查 |
| 正常 HTTP 重定向 | 沿既有请求过程处理；不人为插入 DOM 解析步骤 |
| 匹配已知阅读器或下载中转结构的 HTML | 调用对应的确定性解析规则，保留访问上下文 |
| 文章 HTML | 按 P3/P4 读取；不将其报告为 PDF |
| 登录、访问拒绝、安全检查或验证码页面 | 记录当前来源状态并继续其他合法来源；不得把安全 iframe 当 PDF；页面 Solver/人工验证保持独立 |
| XML、JATS、JSON 元数据或引文文本 | 只有规则明确支持其中 PDF 字段时继续；本身不作为 PDF |
| 未识别内容、空结果或失败 | 结束当前路径，继续下一条适用来源 |

候选失败与整个任务取消不同。来源访问拒绝、Reader 不可用、无 PDF 或解析失败都只结束当前路径，待其真实资源结束后继续后续合法候选。取消、任务失效、父期限到达或实际本地 I/O 失败后，不继续发起新请求。已确认的合法线索不因响应尾部或无关字段超限而丢弃；部分观察明确记录，不宣称完整读取。

磁盘、权限、文件落位或结果关联等本地失败终止整个下载任务，不属于可改用下一网络来源解决的候选失败。

#### F7.2 共用解析范围

可以共用 HTTP 重定向、明确的 Meta Refresh、指定 redirect anchor、`frame`、`iframe`、`embed`、`object` 的地址读取。共用的是处理能力，不是对所有网页执行无差别扫描。[S033](#s033)、[S050](#s050)

每个中间页面规则必须限定 Host/页面形态和可读字段。相对下一跳使用当前实际响应 URL，而非最初文章 URL。每次下一跳经过同样的 URL 资格检查。

解析链保留去重和环路识别，并响应实际任务取消。跳数、请求数和等待常量不作为通用来源规则；相应实现调整另行处理。

#### F7.3 特殊机制的采用范围

| 平台 | 采用的处理路径 | 保留的条件 |
|---|---|---|
| **ScienceDirect** | PII → `/pdfft`；必要时读取 `meta refresh`、`#redirect-message a`、`.PdfEmbed > object` 或明确 JSON 下载字段 | `md5/pid` 等值来自页面，不自行生成；已有下一跳时不返回文章页重走。[R024](#r024) |
| **IEEE** | 已知编号先请求 `getPDF.jsp`；失败后解析 `stamp.jsp` 的 frame/iframe/meta refresh | 区分阅读器与二进制候选；保持目标 `arnumber`。[R025](#r025) |
| **Optica / OSA** | `citation_pdf_url` 或 `#link-pdf` → 中间页 `frame:not(:first-of-type)[src]`，或已知 `gotourl` 参数 | `frame` 规则不能退化为任意第一个 iframe；`gotourl` 为平台字段。[R053](#r053) |
| **Silverchair / OUP** | 明确的 article-pdf 入口 → 正常 HTTP 重定向 → CDN | 不生成或修改签名；是否需要导航、Cookie 或 Referer 按 Host 和现有上下文处理。[R020](#r020)、[R044](#r044)–[R050](#r050) |
| **LWW / Ovid** | 文章页 AN + journal slug → `downloadpdf.aspx` → `pdfDownloadDetails.pdfUrl` → PDF | 读取真实 AN 和签名 URL；保留发现时的 viewer Referer。该 Referer 条件来自参考项目的机构环境，不宣称全站通用。[R060](#r060) |
| **Ovid OCE** | LWW viewer 无可用签名地址时，使用材料中的 OCE 路径 | 仅在确有该平台访问上下文、ID 和对应规则时运行，不把 LWW、OCE 权限视为相同。[S002](#s002) |
| **ClinicalKey** | PII → watermarked PDF 路径；必要时要求该平台正常初始化后的会话 | 不把 ScienceDirect 授权当作 ClinicalKey 授权，不固化参考项目的中文 locale、机构选择器或代理 Host。[R026](#r026) |
| **Wiley / Atypon** | 使用 Host 限定的 PDF 路径变体，或页面已经明确给出的阅读器入口 | EMBO 旧 Host 特例保留历史状态，不能推广为所有 `epdf` 的全局替换。[R002](#r002)、[R039](#r039)、[R063](#r063) |
| **Project Euclid / SPIE** | 先尝试内容类型对应的 DOI 查询式入口；若返回已知中间响应再解析 | 本材料中的安全检查 HTML 和超时不构成阅读器规则；不跟随其中任意 iframe。[R009](#r009)、[R012](#r012)、[R013](#r013) |
| **JSTOR** | stable ID 候选，普通重定向；未知确认页作为当前路径未完成 | 不以 `acceptTC=true` 宣称条款步骤已被消除，不新增自动确认行为。[R022](#r022) |

Nature、MDPI 和 Springer 的条件性变体见 F4。T&F eBooks 的 `product._id`、`_token` 与 `webpdf/chapterpdf.location` 是扩展参考，不进入本版期刊论文默认链。[R021](#r021)

#### F7.4 动态签名和请求上下文

发现签名 URL 时，保留路径、参数和其产生页面的上下文。不能删除看似无关的查询参数、统一小写路径、重新排序签名参数或用另一个页面替换已知必要的 Referer。

临时签名地址只作为本次候选，不作为永久 URL 模板。平台所需 Cookie、授权 Header 和 token 只在其既有授权范围内使用；不把平台凭证转发给任意下一跳，不把敏感参数写入公开诊断材料。

正常跨域跳转到 PDF CDN是已有案例的一部分，不要求所有候选都与文章页同源；跨域目标仍必须来自明确的候选链并通过 URL 安全条件。[S002](#s002)、[S029](#s029)

<a id="official-apis"></a>

### F8 官方接口的使用边界

#### F8.1 默认和可选来源

| 接口 | 本规格中的位置 | 条件 |
|---|---|---|
| [API01](#api01) DOI Handle | P2 的条件性目标 URL 查询 | 只有缺少有效目标或内部 ID 时使用 |
| [API02](#api02) Crossref REST | P2 的条件性 ID/PDF 字段来源 | 优先利用已有响应；按字段筛选，不固定对每篇请求 |
| [API03](#api03)、[API04](#api04) IEEE Metadata | P2 可选查询 | 已有适用 API key；缺少 key 时跳过，不阻塞网页路径 |
| [API06](#api06) Elsevier Article Retrieval | P2 可选直接来源或链接来源 | 已有相应 API 凭证及内容/格式访问条件；与网页 Session 分开 |
| [API07](#api07) Wiley TDM | P2 可选 DOI PDF 来源 | 已有独立 token 和相应访问条件；不为普通网页模板强制增加 token |
| [API08](#api08) APS Harvest | P2 可选 DOI PDF 来源 | OA 的无认证路径或已经具备相应授权；请求 `Accept: application/pdf` |
| [API09](#api09) Springer Metadata | 可选元数据候选来源 | 已有 API key，响应明确含 PDF URL；本材料官方文档证据主要来自搜索索引，保留该限制 |
| [API12](#api12) PLOS PDF | 已纳入 P1 对应模板 | `type=printable` 与正确期刊 slug |

这些可选接口在对应平台的普通直接模板之后、HTML 之前按条件使用。不为本模块强制新增一组 API 账号、密钥管理或协议申请流程。缺凭证是规则不适用，不应成为整个 PDF 获取失败的唯一原因。

#### F8.2 不作为 PDF 来源的服务

IEEE 的 `fulltext` 接口、Springer 的 JATS/XML 全文服务及 JSTOR OCR 数据集不能仅凭名称视作 PDF 二进制来源。Cambridge、IOP、RSC 的现有官方材料也没有提供本规格可以默认调用的通用、免额外条件的 DOI → PDF API。[API05](#api05)、[API10](#api10)、[API11](#api11)、[API13](#api13)–[API16](#api16)

API 的 HTTP 状态、限流和访问要求以相应官方证据为依据，不将客户端里的某个错误分类或等待常量提升为服务器保证。材料已经记录 Wiley 官方文档与其客户端在限流常量、404 分类上的差异。[API07](#api07)

<a id="candidates"></a>

### F9 URL 处理、候选与回退结果

#### F9.1 URL 处理约定

1. **身份比较与请求表达式分开。** DOI 比较需要的规范化不应用到整个 PDF URL。保留 Host 之外路径、文件名、大小写及查询值。
2. **按端点编码。** DOI 放入查询参数时编码整个参数值；路径模板按对应证据决定如何编码。保留 DOI suffix 中可能存在的多级斜杠，不只取最后一段，不重复编码已处理的值。
3. **保留实际响应地址。** 相对 Meta、anchor、frame 等地址按承载它的实际页面 URL 解析；不能一直使用最初的 DOI resolver 地址作基准。
4. **有限去重。** 同一候选不因 Meta、DOM 和模板重复发现而再次触发完整尝试。已观测的响应/导航关系及实际 Cookie 变化可以允许同 URL 的合法继续；重复相同响应/边和不可重放 POST 仍拒绝。去重不删除有效签名参数，不把不同 token 的地址强行合并；下载方内部重试与来源发现去重分开。
5. **限制可请求地址。** 只向符合既有 URL 安全边界的 HTTP(S) 目标发起请求；拒绝脚本、文件、本地或内部网络等不合格目标，重定向后的地址也要检查。当前材料未建立 `blob:` 或 `data:` 提取机制，不将其直接加入网络候选。

以上为发现层的共同约束，不规定网络库、代理实现或浏览器进程结构。[S068](#s068)、[S070](#s070)、[S095](#s095)、[S106](#s106)、[S108](#s108)

#### F9.2 最小候选语义

候选在逻辑上保留：URL、来源阶段、规则编号、目标 Platform，以及该请求确有必要的页面/访问上下文。URL 尚需解析为阅读器下一跳时，不能把这种状态抹成已取得直接 PDF。

这些信息用于维持请求正确性与来源记录，不要求新建数据库表或复杂候选评分对象。公开诊断仅保留可安全显示的规则与来源信息。

#### F9.3 与下载结果的衔接

发现层逐个提供候选，并根据结果决定继续、解析中间页或停止。下载层按当前响应类型和传输正常终态确认完成时，不再发起后续查询。

对于同一个响应，不为确定类型再进行一轮独立的 HEAD/GET。复用已经得到的响应分类；流式 Session 下载与原 DownloadItem 接管见[body downloads](body-downloads.md)。

身份以既有目标论文关系、可靠内部 ID、目标页面和正文入口为依据。不新增下载后解析 PDF 标题/DOI、页数、文本量或版本的校验。

任务最终的本地文件关联与 completed 条件见[body downloads](body-downloads.md)；发现器不接管数据库或文件落位写入。

#### F9.4 回退的最小可观察结果

保留两个结果语义：

| 结果 | 定义 |
|---|---|
| 最终 PDF 来源 | 成功候选的发现方式；没有取得有效 PDF 时为空或 `none` |
| 是否发生回退 | 已实际执行的路径或候选没有成功后，是否继续尝试了另一条适用路径或候选 |

字段名可沿用 `pdf_source` 和 `fallback_used`；成功结果随 Paper 主 PDF 关联记录，失败尝试的必要信息保留在任务诊断中，不要求新建独立候选数据库或评分系统。来源至少能区分 DOI 模板、标识符/已有 URL、HTML Meta、DOM/平台解析、OpenAlex。中间页解析保留原发现路径作为来源，不需要新的版本或可信度分数。

**不算回退：** 因输入或凭证不足而跳过不适用规则；从 DOI 查询取得 PII 后首次请求 PDF；正常 HTTP 重定向；同一路径读取已知中间页；下载方对同一候选的受控重试。

**算回退：** 已发生物理候选尝试且失败后，再实际尝试另一合格候选，包括来自 DOM 或 OpenAlex 的候选。只读取元数据、执行资格检查或得到空 OpenAlex 列表不虚构物理回退。同一规则明确列出的第二个 URL 在首个失败后被尝试，也属于候选回退。

例如，无 DOI 模板但已有 `arnumber`，直接取得 PDF 时不记为回退；Wiley 模板失败后 Meta 成功时记录 Meta 来源及回退；仅能适用 OpenAlex 时，最终来源已经清楚表示使用了该服务，不为被跳过的规则伪造失败记录。

规则号、失败原因和已尝试路径可以放在诊断中，用于解释结果；不要求新增复杂的统计或评分系统。

<a id="acceptance"></a>

### F10 来源规则示例

这些例子说明上述来源规则，不是历史阶段的执行指令或已通过的真实站点验收。

| 编号 | 条件 | 预期行为 |
|---|---|---|
| T01 | 已知平台的 P1 候选正常完成 PDF 下载 | 本次 PDF 操作不请求后续 Handle/Crossref、不额外加载 HTML、不调用 OpenAlex；允许此前 Run 预采集存在 |
| T02 | 某阶段条件不满足 | 直接跳过；不伪造该阶段已发送请求或失败 |
| T03 | 已有 PII、`arnumber`、stable URL 或可用 PDF URL | 不再次查询同一信息；使用适用规则 |
| T04 | 明确 URL/解析结果表明 DOI 已迁入另一个平台 | 按实际内容 Host 使用规则；不据单篇迁移永久改写整个 DOI 前缀 |
| T05 | Crossref `alternative-id` 第一项不是合格 PII | 不把第一项直接拼入 ScienceDirect URL；使用形状合格项或回退 |
| T06 | IEEE 缺 `article_number`，DOI 尾部恰为数字 | 不把尾部数字默认当 `arnumber`；查询或转网页路径 |
| T07 | OUP 引用响应缺 `eprint`，仅有文章 URL | 结果仍按文章页面处理，不报告 PDF 成功 |
| T08 | JSTOR stable ID 为 DOI-like 字符串 | 保留其完整路径；TDM UUID 不进入 stable PDF 模板 |
| T09 | Nature DOI suffix 与文章 ID 有不同点号规则 | 不启用全站 suffix 拼接或统一删点算法 |
| T10 | MDPI 示例 `10.3390/admsci3030032` | 不使用固定两位卷号算法将卷 3 解析为卷 30；默认转 Meta |
| T11 | ACS 新 Silverchair 页面或仅有旧 ACS DOI 模板 | 采用新页面规则；历史模板不会在默认失败链中自动追加 |
| T12 | SPIE 内容类型已知/未知 | 分别使用期刊、会议路径；未知时不对两种端点盲试 |
| T13 | Meta 为相对链接，实际页面已经重定向 | 按实际页面 URL 解析；保留最终地址的大小写与必要参数 |
| T14 | PLOS 返回 `type=manuscript`，或接口返回 JATS/XML | 不作为 PDF；`type=printable` 使用对应期刊条件 |
| T15 | 已知中间页提供明确的下一跳 | 就地解析并继续；不强制重新访问原文章页 |
| T16 | 挑战 HTML 内出现 iframe 或不明 JS URL | 不当作 PDF Reader 盲目跟随；统一网页访问流程识别支持的 Cloudflare 或人工状态，不执行任意提取脚本 |
| T17 | LWW viewer 提供签名地址和对应 Referer | 保留必要上下文及签名参数；不改写为永久模板 |
| T18 | 同一 URL 被多个来源发现，或出现中间页环路 | 不因重复发现再次完整尝试；识别并结束环路 |
| T19 | 发现明显补充材料、整期文件或其他论文入口 | 不作为目标论文正文候选；不通过下载后 NLP 弥补无依据选择 |
| T20 | 缺少某官方 API 的额外凭证 | 跳过该接口，继续其他适用路径；不影响普通网页模板 |
| T21 | 任意来源已确认有效 PDF | 不再比较出版版本，不再调用后续来源 |
| T22 | 任务取消或总预算结束 | 不发起新的候选、标识符查询或 OpenAlex 请求 |
| T23 | 多次内部重定向/同候选重试，但首条发现路径成功 | 回退标志为否；改用另一失败后的候选或来源时为是 |
| T24 | 只发现候选，尚未收到有效 PDF 确认 | 只报告发现/待处理状态，不记录成功 PDF 来源 |

真实机构权限、动态会话初始化及站点响应差异属于环境验收。登录、页面动作与 solver 使用 [Document access](browser-documents.md) 中的共享访问能力，不由规则各自实现一套流程。

<a id="exclusions"></a>

### F11 已排除规则与后续边界

#### F11.1 不采用的规则

本版不整体导入 `pubpatterns`，也不原样复用以下过宽处理：[S060](#s060)–[S066](#s066)、[S138](#s138)、[S017](#s017)

- Nature 全站 DOI suffix 拼 article ID，或全局删除点号。
- MDPI 按固定两位卷号拆分全部 DOI。
- 任何 Host 的 `/epdf/` 全局改 `/pdf/`，或所有 `/articles/*.pdf` 改 `_reference.pdf`。
- ScienceDirect 全部 `/article/pii/` 改 `/article/am/pii/`。
- F1000 固定文章 URL、Pensoft RIO 将 XML 字段当 PDF，以及未经当前材料支持的历史 Cambridge/Thieme/SPIE/PeerJ 等默认捷径。
- 从 DOI 尾部猜 IEEE `arnumber`、从任意 URL 末段猜 OUP `resourceId`，或将 Crossref 任意替代 ID 当 PII。
- 因某个项目含有特定文件就宣称主路径已经启用。材料已指出 JabRef 的 JSTOR Fetcher 当前未注册，不能作为该项目现行默认行为的证据。[S031](#s031)、[S112](#s112)

#### F11.2 共享平台与迁移

Atypon 共享有条件的路径选择；Silverchair 共享 PDF DOM 读取并保留 JAMA、ACS 等差异；HighWire 主要共享 Meta 与页面标志。共享 CMS 不赋予统一的 Host、API key、Cookie 或 URL 参数。

按材料记录，ACS 的迁移证据支持调整默认规则；RSC 仍保留迁移后字段未核实的限制；Annual Reviews 的迁移不导致现有 `/doi/pdf/` 表达式自动失效。历史记录保留供追溯，不作默认候选。[S067](#s067)、[S141](#s141)、[S142](#s142)

#### F11.3 许可证与证据

独立运行时不等于自动消除复制源码的许可义务。规则实现优先借鉴公开接口、URL 表达式及观察到的约束。直接复制函数时，再依据具体文件核对许可证；本文保留附件中的 MIT、AGPL 和未确认许可状态，不将其改写为统一许可证结论。

研究报告中的源码、测试期望和官方文档支持具体机制，不作为下载成功率或长期稳定性的量化证明。Parseland-eval 的对比数字不作为 Allfold 的成功率依据。[S130](#s130)

#### F11.4 与完整工作流的衔接

当前采集由 [Workspace runtime](collection-runtime.md) 管理；传输、原响应接管、文件与终态由 [body downloads](body-downloads.md) 说明。来源目录不另行规定任务阶段或文件提交工作流。

## PDF 规则、接口与来源总目录

附录 A–D 保留 R/API/S 来源编号、规则采用状态、固定版本与许可。默认、条件性、扩展与历史记录分别标注；引用源项目的行为不自动成为 Allfold 的运行时要求。

特别是，源项目可能使用 Zotero、同步 HTTP、PDF 内容校验或自己的存储结构。这里保留它们作为规则证据；Allfold 的任务、页面与文件边界由上述所属模块文档说明。

<a id="rule-catalog"></a>

## 附录 A：72 条规则的采用目录

编号、分类、表达式、输入条件、访问条件和来源编号与研究工作簿对应；“本规格采用”记录 Allfold 的规则处置。本文的来源优先级和排除条件与参考源码的原始调用顺序分别表述。

| 原材料分类 | 记录数 | 本规格解释 |
|---|---:|---|
| DOI 构造 | 19 | 匹配条件后直接生成候选；其中含有限场景和实例证据候选 |
| 额外标识符 | 8 | 需要明确 ID；部分属于条件性会话或扩展参考 |
| 文章 URL 转换 | 9 | 需要已有完整 URL 或经确认的结构，不自动视为 DOI-only |
| HTML Meta / DOM | 25 | 需要当前文章页面；按字段和 Host 条件执行 |
| 历史候选 | 11 | 保留追溯，不进入默认链 |

附录中的“源码验证”沿用原研究结论，指规则或相关调用确实存在；不表示本次测试执行或跨机构下载验证。材料中的历史 URL、扩展接口与模板占位符均为资料，不应作为可直接批量调用的清单。


### A.1 DOI 构造


<a id="r001"></a>

#### R001 · Springer Link

**本规格采用：** 纳入 P1；按本条 Host、内容类型及输入条件执行。

**Host：** `link.springer.com`  
**表达式或提取位置：** `https://link.springer.com/content/pdf/{encodeURIComponent(doi)}.pdf`

**所需输入与解析：** DOI；已有 DOI；源码从文章/章节/图书 URL 提取；HTML条件：构造URL不需要文章HTML；可能仍需处理响应中的中间页。

**已列变体：** `/content/pdf/… .pdf`

**中间页或响应：** 构造函数无中间页解析。

**访问条件：** PDF 请求依目标站点授权；所读构造函数未规定额外请求头。

**源实现范围：** PDF URL 构造仅依赖 DOI，但完整 translator 仍从已有 Document 开始并获取引用；不能称其完整流程 DOI-only。DOI 在代码中整体 URI 编码。

**研究证据及模块：** 源码验证；固定 commit 3fb4e794446763ac2053250112890631c428159f；未运行实站下载；函数/模块：scrape。**来源：** [S001](#s001)。


<a id="r002"></a>

#### R002 · Wiley Online Library

**本规格采用：** 纳入 P1；按本条 Host、内容类型及输入条件执行。

**Host：** `onlinelibrary.wiley.com`  
**表达式或提取位置：** `https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}?download=true`

**所需输入与解析：** 完整 DOI + 已确认 Platform；直接模板；已读取meta时也可按Wiley规则将/pdf/改/pdfdirect/；HTML条件：构造URL不需要文章HTML；可能仍需处理响应中的中间页。

**已列变体：** `/doi/pdf/{doi}；/doi/epdf/{doi} 属不同响应类型`

**中间页或响应：** 直达响应可能仍为访问控制或阅读器HTML。

**访问条件：** OA或现有机构Session；不需要Wiley TDM token来构造网页地址。

**源实现范围：** drpwchen ROUTES已有tpl调度。Zotero仅在已取得meta URL上替换，不添加download=true。

**研究证据及模块：** 源码验证；本轮未做授权下载；函数/模块：ROUTES; _proxy_pdf; scrapeEM。**来源：** [S002](#s002)、[S003](#s003)。


<a id="r003"></a>

#### R003 · Taylor & Francis Journals / Routledge journals

**本规格采用：** 纳入 P1；按本条 Host、内容类型及输入条件执行。

**Host：** `www.tandfonline.com`  
**表达式或提取位置：** `https://www.tandfonline.com/doi/pdf/{doi}`

**所需输入与解析：** DOI + 已知 Host；从 /doi/.../10... 文章 URL 取 DOI；HTML条件：构造URL不需要文章HTML；可能仍需处理响应中的中间页。

**已列变体：** `/doi/pdf/；EPUB 入口另输出 /doi/epub/?download=true`

**中间页或响应：** 源码不解析中间页。

**访问条件：** PDF 请求依目标站点授权；所读构造函数未规定额外请求头。

**源实现范围：** PDF 表达式只需 DOI + Host；完整 translator 仍先用 Document/引用导出。此处 PDF 没有追加 download=true，不能误引为源码原式。

**研究证据及模块：** 源码验证；固定 commit 3fb4e794446763ac2053250112890631c428159f；未运行实站下载；函数/模块：scrape。**来源：** [S004](#s004)。


<a id="r004"></a>

#### R004 · NEJM

**本规格采用：** 纳入 P1；按本条 Host、内容类型及输入条件执行。

**Host：** `www.nejm.org`  
**表达式或提取位置：** `https://www.nejm.org/doi/pdf/{doi}`

**所需输入与解析：** DOI + 已知 Host；与 T&F 共享 translator，Host 来自当前文章 URL；HTML条件：构造URL不需要文章HTML；可能仍需处理响应中的中间页。

**已列变体：** `/doi/pdf/{doi}`

**中间页或响应：** 源码不解析中间页。

**访问条件：** PDF 请求依目标站点授权；所读构造函数未规定额外请求头。

**源实现范围：** 同一函数的 Host 参数使 PDF 模板可共用；不证明两平台会话或授权相同。

**研究证据及模块：** 源码验证；固定 commit 3fb4e794446763ac2053250112890631c428159f；未运行实站下载；函数/模块：scrape。**来源：** [S004](#s004)。


<a id="r005"></a>

#### R005 · SAGE Journals

**本规格采用：** 纳入 P1；按本条 Host、内容类型及输入条件执行。

**Host：** `journals.sagepub.com`  
**表达式或提取位置：** `https://journals.sagepub.com/doi/pdf/{doi}`

**所需输入与解析：** DOI；meta dc.Identifier 或文章 URL；HTML条件：构造URL不需要文章HTML；可能仍需处理响应中的中间页。

**已列变体：** `/doi/pdf/{doi}`

**中间页或响应：** 未定义。

**访问条件：** PDF 请求依目标站点授权；所读构造函数未规定额外请求头。

**源实现范围：** 139–143 将 pdfurl 附件接入；完整 translator 使用已有 Document 并 POST citation。源码注释说明 SAGE 虽用 Atypon，但 translator 与通用 Atypon 差异较大。

**研究证据及模块：** 源码验证；固定 commit 3fb4e794446763ac2053250112890631c428159f；未运行实站下载；函数/模块：scrape。**来源：** [S005](#s005)。


<a id="r006"></a>

#### R006 · Annual Reviews

**本规格采用：** 纳入 P1；按本条 Host、内容类型及输入条件执行。

**Host：** `www.annualreviews.org`  
**表达式或提取位置：** `https://www.annualreviews.org/doi/pdf/{doi}`

**所需输入与解析：** DOI；从 /content/journals/{doi} 或列表入口提取；HTML条件：构造URL不需要文章HTML；可能仍需处理响应中的中间页。

**已列变体：** `引用端点 /content/journals/{doi}/cite/bibtex`

**中间页或响应：** 未定义。

**访问条件：** PDF 请求依目标站点授权；所读构造函数未规定额外请求头。

**源实现范围：** 新内容入口已是 /content/journals/，但源码 PDF 候选仍用 /doi/pdf/。这体现入口形态与 PDF URL 可以不同。

**研究证据及模块：** 源码验证；固定 commit 3fb4e794446763ac2053250112890631c428159f；未运行实站下载；函数/模块：addByBibTex。**来源：** [S006](#s006)。


<a id="r007"></a>

#### R007 · Frontiers

**本规格采用：** 纳入 P1；按本条 Host、内容类型及输入条件执行。

**Host：** `www.frontiersin.org`  
**表达式或提取位置：** `https://www.frontiersin.org/articles/{doi}/pdf`

**所需输入与解析：** DOI；已知 DOI；numeric articleID 可通过 /articles/{id} 重定向获取 DOI；HTML条件：构造URL不需要文章HTML；可能仍需处理响应中的中间页。

**已列变体：** `/articles/{doi}/full; /articles/{doi}/bibTex; /articles/{doi}/pdf`

**中间页或响应：** 普通 redirect 可能出现。

**访问条件：** PDF 请求依目标站点授权；所读构造函数未规定额外请求头。

**源实现范围：** ARTICLE_BASEURL 在 44；doWeb 129–130 允许 DOI 列表项传 null Document，走 BibTeX。只有需要补充文件时才可能为了 articleID 请求 HTML。

**研究证据及模块：** 源码验证；固定 commit 3fb4e794446763ac2053250112890631c428159f；未运行实站下载；函数/模块：doWeb; scrape; translateBibTeX; finalizeItem。**来源：** [S007](#s007)。


<a id="r008"></a>

#### R008 · ACM Digital Library

**本规格采用：** 纳入 P1；按本条 Host、内容类型及输入条件执行。

**Host：** `dl.acm.org`  
**表达式或提取位置：** `https://dl.acm.org/doi/pdf/{doi}?download=true`

**所需输入与解析：** DOI；文章 pathname 中 DOI；HTML条件：构造URL不需要文章HTML；可能仍需处理响应中的中间页。

**已列变体：** `/doi/pdf/{doi}；download=true`

**中间页或响应：** 未定义。

**访问条件：** PDF 请求依目标站点授权；所读构造函数未规定额外请求头。

**源实现范围：** 源码仅在 pathname 包含 pdf 或页面有 #downloadPdfUrl 时添加候选；构造式 DOI-only，原流程有 Document 门控。

**研究证据及模块：** 源码验证；固定 commit 3fb4e794446763ac2053250112890631c428159f；未运行实站下载；函数/模块：scrape。**来源：** [S008](#s008)。


<a id="r009"></a>

#### R009 · Project Euclid

**本规格采用：** 条件性纳入 P1：已确认 Project Euclid 及期刊文章时生成候选；保留官方实例/日志解析器证据等级。

**Host：** `projecteuclid.org`  
**表达式或提取位置：** `https://projecteuclid.org/journalArticle/Download?urlId={URL-encoded DOI}`

**所需输入与解析：** 完整DOI；部分旧内容urlId是平台handle；已知平台时直接以DOI作为查询参数urlId；整个DOI query编码。无DOI旧内容需保留handle。；HTML条件：构造URL不需要文章HTML；可能仍需处理响应中的中间页。

**已列变体：** `urlid / urlId；/accountAjax/Download?downloadType=journal%20article&urlid={...}&isResultClick=True；旧pdf_1/handle路径为历史`

**中间页或响应：** 端点应指向PDF，但本轮web open观察到Incapsula安全检查HTML iframe；不能将任意iframe视作PDF。

**访问条件：** OA或机构Session；可能正常浏览器安全检查；本轮未做授权下载。

**源实现范围：** 2025年AAP、AOAS、BA以及Acta的官方PDF链接使用DOI查询式。ezPAARSE为访问日志解析器，支持端点和参数结构的判断。旧Zotero规则提供HTML meta回退。

**研究证据及模块：** 官方当前PDF搜索索引 + ezPAARSE解析器/fixtures源码；本轮请求遇安全检查；函数/模块：analyseEC (PDF endpoint recognition)。**来源：** [S009](#s009)、[S010](#s010)、[S011](#s011)、[S012](#s012)、[S013](#s013)、[S014](#s014)、[S015](#s015)。


<a id="r010"></a>

#### R010 · AIAA ARC

**本规格采用：** 纳入 P1；按本条 Host、内容类型及输入条件执行。

**Host：** `arc.aiaa.org`  
**表达式或提取位置：** `https://arc.aiaa.org/doi/pdf/{doi}`

**所需输入与解析：** DOI；已知 DOI；源码从文章/列表引用机制取得；HTML条件：构造URL不需要文章HTML；可能仍需处理响应中的中间页。

**已列变体：** `/doi/abs/{doi}`

**中间页或响应：** 未指定。

**访问条件：** PDF 请求依目标站点授权；所读构造函数未规定额外请求头。

**源实现范围：** finalizeItem 无须 doc 也能构造附件，Host 来自站点；源码亦含无 doc 批量项分支。

**研究证据及模块：** 源码验证；固定 commit 3fb4e794446763ac2053250112890631c428159f；未运行实站下载；函数/模块：finalizeItem; scrape。**来源：** [S016](#s016)。


<a id="r011"></a>

#### R011 · AJR

**本规格采用：** 纳入 P1；按本条 Host、内容类型及输入条件执行。

**Host：** `www.ajronline.org`  
**表达式或提取位置：** `https://www.ajronline.org/doi/pdf/{doi}?download=true`

**所需输入与解析：** 完整 DOI；直接模板；另有parseland epdf→pdf独立佐证；HTML条件：构造URL不需要文章HTML；可能仍需处理响应中的中间页。

**已列变体：** `/doi/epdf/{doi}`

**中间页或响应：** 依响应。

**访问条件：** 机构Session或OA。

**源实现范围：** drpwchen提供已接入调度的DOI模板；parseland另在已发现的HTML候选上执行epdf→pdf。两种源码流程分别保留，不将后者写为DOI-first调度。

**研究证据及模块：** 源码验证；本轮未做授权下载；函数/模块：ROUTES。**来源：** [S002](#s002)、[S017](#s017)、[S018](#s018)。


<a id="r012"></a>

#### R012 · SPIE Digital Library（期刊）

**本规格采用：** 条件性纳入 P1：确认 SPIE 期刊文章类型后使用；内容类型未知时不与会议入口一起盲试。

**Host：** `www.spiedigitallibrary.org`  
**表达式或提取位置：** `https://www.spiedigitallibrary.org/journalArticle/Download?urlId={URL-encoded DOI}`

**所需输入与解析：** 完整DOI + 内容类型为journal article；DOI query编码直接构造；当前作者公布的2026论文PDF链接使用urlId；HTML条件：构造URL不需要文章HTML；可能仍需处理响应中的中间页。

**已列变体：** `旧参数 fullDOI；journalIssue/Download有既有链接但不优先概括成统一入口；文章完整路径.full→.pdf是另一路`

**中间页或响应：** citation_pdf_url有返回HTML interstitial的社区源码记录；直接Download接口候选仍须下载器验证。

**访问条件：** OA或机构授权Session；不能把proceedings适配器注释中的Referer要求自动推广到全部期刊。

**源实现范围：** 与proceedings端点分开。该DOI规则有新实例，强于2020 pubpatterns的journalIssue候选，但本轮未获即时PDF成功响应；保留DOM/meta回退。

**研究证据及模块：** 2026论文作者元数据链接 + ezPAARSE旧fullDOI端点源码/fixtures；本轮官方端点open超时；函数/模块：analyseEC / author publication url_pdf。**来源：** [S019](#s019)、[S020](#s020)、[S021](#s021)、[S022](#s022)。


<a id="r013"></a>

#### R013 · SPIE Digital Library（会议论文）

**本规格采用：** 条件性纳入 P1：确认 SPIE 会议论文类型后使用；不用于期刊文章。

**Host：** `www.spiedigitallibrary.org`  
**表达式或提取位置：** `https://www.spiedigitallibrary.org/Proceedings/Download?urlId={URL-encoded DOI}`

**所需输入与解析：** 完整DOI + 内容类型为proceedings article；以query component编码完整DOI；HTML条件：构造URL不需要文章HTML；可能仍需处理响应中的中间页。

**已列变体：** `旧日志有小写/proceedings/Download配合fullDOI；大小写与参数组合按具体证据保留`

**中间页或响应：** 实际下载器称citation_pdf_url可能是HTML interstitial，改用Download端点。

**访问条件：** 机构Session；Referer为此项目2026-06-29 CDP观察及适配器注释，未独立复测；视频only内容没有PDF。

**源实现范围：** IvanZhuyf3实现仍先开HTML取citation_doi，且把所有SPIE都发Proceedings；Allfold素材应保留journal/proceedings分类，不照搬这一范围过宽选择。许可证未核，不建议直接复制。

**研究证据及模块：** 真实下载器源码与注册主路径 + ezPAARSE日志解析fixtures；函数/模块：SPIEAdapter.find_download_url。**来源：** [S023](#s023)、[S024](#s024)、[S021](#s021)、[S022](#s022)。


<a id="r014"></a>

#### R014 · Science / AAAS

**本规格采用：** 纳入 P1；按本条 Host、内容类型及输入条件执行。

**Host：** `www.science.org`  
**表达式或提取位置：** `https://www.science.org/doi/pdf/{doi}`

**所需输入与解析：** 完整 DOI + 已确认 Host；直接模板；HTML条件：构造URL不需要文章HTML；可能仍需处理响应中的中间页。

**已列变体：** `Atypon页面可能给epdf等入口`

**中间页或响应：** 依响应处理PDF/普通redirect/HTML。

**访问条件：** OA或机构Session。

**源实现范围：** Agents365为机构模式的后段候选；此代码顺序不作为Allfold DOI-first调度证据。

**研究证据及模块：** 源码验证；本轮未做授权下载；函数/模块：_PUBLISHER_DIRECT_TEMPLATES; _try_publisher_direct。**来源：** [S025](#s025)、[S026](#s026)。


<a id="r015"></a>

#### R015 · PNAS

**本规格采用：** 纳入 P1；按本条 Host、内容类型及输入条件执行。

**Host：** `www.pnas.org`  
**表达式或提取位置：** `https://www.pnas.org/doi/pdf/{doi}`

**所需输入与解析：** 完整 DOI + 已确认 Host；直接模板；HTML条件：构造URL不需要文章HTML；可能仍需处理响应中的中间页。

**已列变体：** `历史HighWire /content/...full.pdf需按旧文章URL处理`

**中间页或响应：** 依响应。

**访问条件：** OA或机构Session。

**源实现范围：** 旧HighWire规则与当前doi路径分开，不按DOI前缀猜历史页面。

**研究证据及模块：** 源码验证；本轮未做授权下载；函数/模块：_PUBLISHER_DIRECT_TEMPLATES。**来源：** [S025](#s025)、[S026](#s026)。


<a id="r016"></a>

#### R016 · RSNA / Radiology

**本规格采用：** 纳入 P1；按本条 Host、内容类型及输入条件执行。

**Host：** `pubs.rsna.org`  
**表达式或提取位置：** `https://pubs.rsna.org/doi/pdf/{doi}?download=true`

**所需输入与解析：** 完整 DOI；直接模板；HTML条件：构造URL不需要文章HTML；可能仍需处理响应中的中间页。

**已列变体：** `/doi/epdf/入口可在该Host按已验证转换处理`

**中间页或响应：** 依响应。

**访问条件：** 机构Session或OA。

**源实现范围：** drpwchen已接入tpl调度；不向所有Atypon站点扩展同一query。

**研究证据及模块：** 源码验证；本轮未做授权下载；函数/模块：ROUTES; _proxy_pdf。**来源：** [S002](#s002)。


<a id="r017"></a>

#### R017 · World Scientific

**本规格采用：** 纳入 P1；按本条 Host、内容类型及输入条件执行。

**Host：** `www.worldscientific.com`  
**表达式或提取位置：** `https://www.worldscientific.com/doi/pdf/{doi}?download=true`

**所需输入与解析：** 完整 DOI；直接模板；HTML条件：构造URL不需要文章HTML；可能仍需处理响应中的中间页。

**已列变体：** `Atypon DOM可提供具体变体`

**中间页或响应：** 依响应。

**访问条件：** 机构Session或OA。

**源实现范围：** 与实际平台Host绑定；无需从DOI再查publisher名称。

**研究证据及模块：** 源码验证；本轮未做授权下载；函数/模块：ROUTES。**来源：** [S002](#s002)、[S026](#s026)。


<a id="r018"></a>

#### R018 · PLOS ONE（官方直接入口）

**本规格采用：** 纳入 P1；按本条 Host、内容类型及输入条件执行。

**Host：** `journals.plos.org`  
**表达式或提取位置：** `https://journals.plos.org/plosone/article/file?id={doi}&type=printable`

**所需输入与解析：** 完整 DOI；期刊slug=plosone；官方PDF示例；其他PLOS期刊保留实际journal slug；HTML条件：构造URL不需要文章HTML；可能仍需处理响应中的中间页。

**已列变体：** `type=manuscript返回XML，非PDF`

**中间页或响应：** 普通HTTP响应/重定向。

**访问条件：** OA；无需独立API key。

**源实现范围：** 此官方示例支持PLOS ONE。其他期刊可按已验证slug映射扩展；不把type=print当作这里的官方值。

**研究证据及模块：** 官方文档；未进行实际下载；函数/模块：官方Article PDF。**来源：** [S027](#s027)。


<a id="r019"></a>

#### R019 · Springer / BMC（在版候选变体）

**本规格采用：** 条件性变体：只限材料支持的 Springer 在版场景，在常规候选失败后使用；不默认覆盖整个平台。

**Host：** `link.springer.com`  
**表达式或提取位置：** `https://link.springer.com/content/pdf/{doi}_reference.pdf`

**所需输入与解析：** 完整 DOI + 已确认Springer平台；普通/content/pdf/{doi}.pdf失败后，该项目尝试alt_paths；HTML条件：构造URL不需要文章HTML；可能仍需处理响应中的中间页。

**已列变体：** `/content/pdf/{doi}.pdf；官方Metadata示例另有/openurl/pdf?id=doi:{doi}`

**中间页或响应：** 响应可能为正常PDF或访问挑战HTML。

**访问条件：** OA或机构Session。

**源实现范围：** 仅作为drpwchen记录的in-press场景变体；不能对所有/articles/*.pdf全局替换_reference，也不增加PDF版本比较。

**研究证据及模块：** 源码验证；本轮未做授权下载；函数/模块：ROUTES.alt_paths; _proxy_pdf。**来源：** [S002](#s002)。


### A.2 额外标识符


<a id="r020"></a>

#### R020 · Oxford Academic

**本规格采用：** 纳入 P2：只使用有依据的 resourceId 和文章资源类型；引用结果无 eprint 时转文章页面回退。

**Host：** `academic.oup.com`  
**表达式或提取位置：** `https://academic.oup.com/Citation/Download?resourceId={resourceId}&resourceType=3&citationFormat=2 → BibTeX eprint`

**所需输入与解析：** 规范文章URL的末段resourceId；应核对实际资源ID；PaperMemory直接取文章URL最后一段作为resourceId，未验证末段格式；Citation返回BibTeX后读取eprint；HTML条件：已有所需ID时可构造或查询；ID来源见解析规则。

**已列变体：** `DOM a.article-pdfLink href；citation_pdf_url`

**中间页或响应：** Citation导出文本；最终PDF正常HTTP重定向。

**访问条件：** 沿用机构Session；源码未证明Referer header通用必需。

**源实现范围：** PaperMemory 的 eprint 缺失时回退到文章URL；该回退不是已获得PDF。需要先有数字ID且仅resourceType=3文章。并非DOI-only。 Silverchair 页面中的 a.article-pdfLink 保留为HTML回退。

**研究证据及模块：** 源码验证（未进行本轮实站下载）；函数/模块：OupSource.parse / Silverchair.scrape。**来源：** [S028](#s028)、[S029](#s029)。


<a id="r021"></a>

#### R021 · Taylor & Francis eBooks / 章节

**本规格采用：** 扩展参考：图书/章节及其 token 接口不纳入本版期刊论文默认链。

**Host：** `www.taylorfrancis.com；api.taylorfrancis.com`  
**表达式或提取位置：** `https://api.taylorfrancis.com/v4/content/{apiId}?apiVersion=4.0.1&filenamePrefix={ISBN}&render=false → JSON location`

**所需输入与解析：** product._id；页面 #product-detail-page-state JSON；HTML条件：已有所需ID时可构造或查询；ID来源见解析规则。

**已列变体：** `响应 type=webpdf 或 chapterpdf`

**中间页或响应：** 页面客户端初始化 + JSON 内容接口。

**访问条件：** 需要已有 _token cookie；API 请求 Authorization: idtoken {token}。

**源实现范围：** 范围为图书/章节，与 tandfonline journals 分开。无 token 时完成元数据但不附 PDF；不能仅 DOI 直达。

**研究证据及模块：** 源码验证；固定 commit 3fb4e794446763ac2053250112890631c428159f；未运行实站下载；函数/模块：scrape。**来源：** [S030](#s030)。


<a id="r022"></a>

#### R022 · JSTOR

**本规格采用：** 纳入 P2；已有所需 ID 优先，缺失时只执行有依据的解析路径。

**Host：** `www.jstor.org`  
**表达式或提取位置：** `https://www.jstor.org/stable/pdfplus/{stable_id}.pdf`

**所需输入与解析：** JSTOR stable_id；Parseland从/stable/{stable_id} URL转换；未新增DOI到stable ID resolver；HTML条件：已有所需ID时可构造或查询；ID来源见解析规则。

**中间页或响应：** 依实际响应可能确认页；Parseland未实现专门确认交互。

**访问条件：** 机构Session或OA；不能由URL构造推断授权。

**源实现范围：** JabRef JstorFetcher在getFullTextFetchers中被注释，不能作为当前主路径佐证。

**研究证据及模块：** 源码验证（未进行本轮实站下载）；函数/模块：transform_pdf_url。**来源：** [S017](#s017)、[S031](#s031)。


<a id="r023"></a>

#### R023 · Cell Press

**本规格采用：** 纳入 P2；已有所需 ID 优先，缺失时只执行有依据的解析路径。

**Host：** `www.cell.com`  
**表达式或提取位置：** `https://www.cell.com/action/showPdf?pii={pii}`

**所需输入与解析：** 有标点的PII或文章URL最后一段；PaperMemory.findCellPii从fulltext、pdfExtended、showPdf URL取PII；HTML条件：已有所需ID时可构造或查询；ID来源见解析规则。

**已列变体：** `/{journal}/pdfExtended/{pii}；/action/showPdf?pii={pii}`

**中间页或响应：** showPdf端点实际返回类型由平台决定。

**访问条件：** 机构Session或OA。

**源实现范围：** PaperMemory parse仍访问HTML取citation_doi；规则本身可在已有PII时构造，不证明通用DOI-only。

**研究证据及模块：** 源码验证（未进行本轮实站下载）；函数/模块：findCellPii / CellSource.parse。**来源：** [S032](#s032)。


<a id="r024"></a>

#### R024 · ScienceDirect

**本规格采用：** 纳入 P2；已有所需 ID 优先，缺失时只执行有依据的解析路径。

**Host：** `www.sciencedirect.com`  
**表达式或提取位置：** `https://www.sciencedirect.com/science/article/pii/{PII}/pdfft`

**所需输入与解析：** PII；Crossref alternative-id经PII格式校验；或DOI登记/redirect目标的/pii/；已有API响应也可直接给scidir-pdf；HTML条件：已有所需ID时可构造或查询；ID来源见解析规则。

**已列变体：** `/pdfft?download=true；页面JSON article.pdfDownload.urlMetadata`

**中间页或响应：** meta refresh；#redirect-message a；.PdfEmbed>object；明确JSON字段。

**访问条件：** 相应ScienceDirect授权Session；官方API是独立权限渠道。

**源实现范围：** 无需把HTML中间页放成每篇必经阶段。PII通常应使用规范化串；B类/旧PII及非标准值需校验；不能取alternative-id任意第一项。

**研究证据及模块：** 源码验证；本轮未做授权下载；函数/模块：getPDFLink; parseIntermediatePDFPage; _crossref_pii。**来源：** [S002](#s002)、[S033](#s033)、[S025](#s025)。


<a id="r025"></a>

#### R025 · IEEE Xplore

**本规格采用：** 纳入 P2；已有所需 ID 优先，缺失时只执行有依据的解析路径。

**Host：** `ieeexplore.ieee.org`  
**表达式或提取位置：** `https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber={article_number}&ref=`

**所需输入与解析：** article_number / arnumber；官方DOI metadata API返回article_number或pdf_url；已知/document/{id}、DOI登记目标或文章URL也可提供；HTML条件：已有所需ID时可构造或查询；ID来源见解析规则。

**已列变体：** `/stamp/stamp.jsp?tp=&arnumber={id} 为阅读器入口`

**中间页或响应：** 阅读器内iframe/frame或meta refresh。

**访问条件：** 网页PDF使用机构Session/OA；metadata API另需API key。

**源实现范围：** Zotero实际先解析stamp.jsp，未找到URL才使用getPDF.jsp。先尝试该已知ID端点是可复用选择；无通用DOI尾部=arnumber保证。

**研究证据及模块：** 源码验证；本轮未做授权下载；函数/模块：scrape。**来源：** [S034](#s034)、[S035](#s035)、[S036](#s036)。


<a id="r026"></a>

#### R026 · ClinicalKey

**本规格采用：** 条件性专用规则：具备 ClinicalKey 自身的标识符、访问权限与就绪会话时使用；本文不设计初始化流程。

**Host：** `www.clinicalkey.com`  
**表达式或提取位置：** `https://www.clinicalkey.com/service/content/pdf/watermarked/1-s2.0-{PII}.pdf?locale=zh_CN&searchIndex=`

**所需输入与解析：** PII + ClinicalKey Session；Crossref alternative-id或DOI跳转PII；正常访问 /content/playBy/doi/?v={doi} 建立平台状态；HTML条件：已有所需ID时可构造或查询；ID来源见解析规则。

**已列变体：** `locale等参数按站点页面实际值保留`

**中间页或响应：** SPA初始化及机构选择；不只是普通HTTP重定向。

**访问条件：** ClinicalKey自己的会话和该平台内容权限。

**源实现范围：** 源码路径来自特定机构代理环境，locale=zh_CN、代理Host及登录实现不可泛化。拥有ScienceDirect权限不能推定ClinicalKey权限。

**研究证据及模块：** 源码验证；本轮未做授权下载；函数/模块：_crossref_pii; _ck_pdf。**来源：** [S002](#s002)。


<a id="r027"></a>

#### R027 · MDPI CDN（有条件候选）

**本规格采用：** 扩展待核：CDN 推导不默认启用；具备可靠元数据、slug 和明确文件命名边界后，才可形成限定子规则。固定两位卷号算法不采用。

**Host：** `pub.mdpi-res.com; mdpi-res.com`  
**表达式或提取位置：** `https://pub.mdpi-res.com/{slug}/{slug}-{volume}-{article5}/article_deploy/{slug}-{volume}-{article5}.pdf`

**所需输入与解析：** journal slug + volume + article number；由已知出版元数据结合DOI后缀；drpwchen查询Crossref volume/container-title；Agents365使用固定2位卷号和short→slug映射；HTML条件：已有所需ID时可构造或查询；ID来源见解析规则。

**已列变体：** `https://mdpi-res.com/d_attachment/{slug}/{slug}-{volume}-{article5}/article_deploy/{slug}-{volume}-{article5}.pdf`

**中间页或响应：** CDN候选直接请求；失败回到meta。

**访问条件：** OA；是否被接入层拦截取决实际响应。

**源实现范围：** 固定2位volume算法对10.3390/admsci3030032（实际卷3、期3、页32–52）会误读卷30。两项目均是有限候选推导，不能当MDPI全平台规则。

**研究证据及模块：** 源码验证；本轮未做授权下载；函数/模块：_mdpi_pdf_candidates; _mdpi_cdn_urls。**来源：** [S025](#s025)、[S037](#s037)、[S038](#s038)。


### A.3 已有文章 URL 转换


<a id="r028"></a>

#### R028 · Nature / Palgrave 历史期刊站

**本规格采用：** 纳入 P2 的已有 URL 转换：仅匹配材料支持的旧路径，不提升为 Nature/Palgrave 全站 DOI 模板。

**Host：** `www.nature.com; historical Palgrave hosts`  
**表达式或提取位置：** `文章 URL 的 /full/ 或 /abs/ 换成 /pdf/，扩展名换 .pdf`

**所需输入与解析：** 完整旧文章 URL；保留原 journal/volume/issue/文章路径；HTML条件：已有完整文章URL时不需要重新读取HTML。

**已列变体：** `旧 /journal/.../full/{id}.html → /journal/.../pdf/{id}.pdf`

**中间页或响应：** 无需另解析（旧 URL 结构匹配时）。

**访问条件：** PDF 请求依目标站点授权；所读构造函数未规定额外请求头。

**源实现范围：** 只对匹配旧结构的 URL；不能移植成全部 10.1038 或 10.1057 DOI 的直接模板。

**研究证据及模块：** 源码验证；固定 commit 3fb4e794446763ac2053250112890631c428159f；未运行实站下载；函数/模块：getPdfUrl。**来源：** [S039](#s039)。


<a id="r029"></a>

#### R029 · IOPscience

**本规格采用：** 纳入 P2：使用已知文章 URL 或已确认的现代 DOI-based 结构；保留完整多级 DOI 路径。

**Host：** `iopscience.iop.org`  
**表达式或提取位置：** `https://iopscience.iop.org/article/{doi}/pdf（DOI-based article 路径）；一般规则为文章 URL 去 /meta 和 query/hash 后 + /pdf`

**所需输入与解析：** 文章 URL；现代路径可由完整 DOI 构造；已有文章 URL 或 DOI-based canonical form；HTML条件：已有完整文章URL时不需要重新读取HTML。

**已列变体：** `旧 ISSN/volume/issue/article 路径同样可加 /pdf`

**中间页或响应：** 未定义。

**访问条件：** PDF 请求依目标站点授权；所读构造函数未规定额外请求头。

**源实现范围：** 源码使用 url.replace 后 +/pdf；DOI模板是对已确认 /article/{doi} 结构的代入。DOI suffix 可能包含多级斜杠，不可只取最后段。

**研究证据及模块：** 源码验证；固定 commit 3fb4e794446763ac2053250112890631c428159f；未运行实站下载；函数/模块：scrape。**来源：** [S040](#s040)。


<a id="r030"></a>

#### R030 · APS Journals / Physical Review

**本规格采用：** 纳入 P2：需要已有文章 URL 或可靠 journal slug；不从任意 DOI 猜 slug。

**Host：** `journals.aps.org`  
**表达式或提取位置：** `https://journals.aps.org/{journal_slug}/pdf/{doi}`

**所需输入与解析：** 完整文章 URL 或 journal_slug + DOI；/abstract/{doi} 路径替换为 /pdf/{doi}；HTML条件：已有完整文章URL时不需要重新读取HTML。

**已列变体：** `/{journal_slug}/abstract/{doi} → /{journal_slug}/pdf/{doi}`

**中间页或响应：** 未定义。

**访问条件：** PDF 请求依目标站点授权；所读构造函数未规定额外请求头。

**源实现范围：** Zotero 这里没有 DOI→journal_slug 表；不能仅由这一源码声称 DOI-only。其他项目/官方 link.aps.org/pdf/{doi} 可另行核查。 /export/{doi}?type=ris&download=true属于引文导出，不是PDF变体。

**研究证据及模块：** 源码验证；固定 commit 3fb4e794446763ac2053250112890631c428159f；未运行实站下载；函数/模块：scrape。**来源：** [S041](#s041)。


<a id="r031"></a>

#### R031 · ASCO / JCO

**本规格采用：** 纳入 P2 的 Host 限定 URL 转换，不据此新建所有 DOI 的无条件模板。

**Host：** `ascopubs.org`  
**表达式或提取位置：** `https://ascopubs.org/doi/pdfdirect/{doi}`

**所需输入与解析：** DOI + 已确认的内容Host；从既有PDF/文章链接/doi/full/{doi}变换为/doi/pdfdirect/{doi}；HTML条件：已有完整文章URL时不需要重新读取HTML。

**中间页或响应：** 目标可能PDF或访问控制HTML，依下载验证。

**访问条件：** OA或机构Session。

**源实现范围：** parseland实际只在HTML发现候选之后执行变换；抽出为DOI模板是基于源码的可迁移推断，不是源项目DOI-first执行证明。

**研究证据及模块：** 源码验证（未进行本轮实站下载）；函数/模块：transform_pdf_url / parse_oa。**来源：** [S017](#s017)、[S018](#s018)。


<a id="r032"></a>

#### R032 · AHA Journals

**本规格采用：** 纳入 P2 的 Host 限定 URL 转换，不以 DOI 前缀强行指定 AHA 或 LWW 平台。

**Host：** `ahajournals.org`  
**表达式或提取位置：** `https://ahajournals.org/doi/pdf/{doi}`

**所需输入与解析：** DOI + 已确认的内容Host；从既有PDF/文章链接/doi/reader/{doi}变换为/doi/pdf/{doi}；HTML条件：已有完整文章URL时不需要重新读取HTML。

**中间页或响应：** 目标可能PDF或访问控制HTML，依下载验证。

**访问条件：** OA或机构Session。

**源实现范围：** parseland实际只在HTML发现候选之后执行变换；抽出为DOI模板是基于源码的可迁移推断，不是源项目DOI-first执行证明。

**研究证据及模块：** 源码验证（未进行本轮实站下载）；函数/模块：transform_pdf_url / parse_oa。**来源：** [S017](#s017)、[S018](#s018)。


<a id="r033"></a>

#### R033 · Healio

**本规格采用：** 纳入 P2 的 Host 限定 URL 转换，不全局替换 epdf。

**Host：** `journals.healio.com`  
**表达式或提取位置：** `https://journals.healio.com/doi/pdf/{doi}`

**所需输入与解析：** DOI + 已确认的内容Host；从既有PDF/文章链接/doi/epdf/{doi}变换为/doi/pdf/{doi}；HTML条件：已有完整文章URL时不需要重新读取HTML。

**中间页或响应：** 目标可能PDF或访问控制HTML，依下载验证。

**访问条件：** OA或机构Session。

**源实现范围：** parseland实际只在HTML发现候选之后执行变换；抽出为DOI模板是基于源码的可迁移推断，不是源项目DOI-first执行证明。

**研究证据及模块：** 源码验证（未进行本轮实站下载）；函数/模块：transform_pdf_url / parse_oa。**来源：** [S017](#s017)、[S018](#s018)。


<a id="r034"></a>

#### R034 · Chicago Journals

**本规格采用：** 纳入 P2 的 Host 限定 URL 转换，不提升为共享 CMS 的通用 DOI 模板。

**Host：** `journals.uchicago.edu`  
**表达式或提取位置：** `https://journals.uchicago.edu/doi/pdf/{doi}`

**所需输入与解析：** DOI + 已确认的内容Host；从既有PDF/文章链接/doi/full/{doi}变换为/doi/pdf/{doi}；HTML条件：已有完整文章URL时不需要重新读取HTML。

**中间页或响应：** 目标可能PDF或访问控制HTML，依下载验证。

**访问条件：** OA或机构Session。

**源实现范围：** parseland实际只在HTML发现候选之后执行变换；抽出为DOI模板是基于源码的可迁移推断，不是源项目DOI-first执行证明。

**研究证据及模块：** 源码验证（未进行本轮实站下载）；函数/模块：transform_pdf_url / parse_oa。**来源：** [S017](#s017)、[S018](#s018)。


<a id="r035"></a>

#### R035 · JMLR

**本规格采用：** 已有 URL 时纳入 P2；不增加 JMLR 论文检索或 DOI 补查任务。

**Host：** `jmlr.org`  
**表达式或提取位置：** `https://jmlr.org/papers/volume{volume}/{jid}/{jid}.pdf`

**所需输入与解析：** 文章路径volume与jid；将/papers/v{volume}/{jid}.html转为/papers/volume{volume}/{jid}/{jid}.pdf；HTML条件：已有完整文章URL时不需要重新读取HTML。

**中间页或响应：** 无专门HTML中间页机制。

**访问条件：** OA。

**源实现范围：** PaperMemory同步用{articleStem}.bib获取元数据，PDF路径可由已知URL产生。DOI不普遍存在，独立的URL规则。

**研究证据及模块：** 源码验证（未进行本轮实站下载）；函数/模块：JmlrSource.parse。**来源：** [S042](#s042)。


<a id="r036"></a>

#### R036 · PMLR

**本规格采用：** 已有 URL 时纳入 P2；不增加 PMLR 论文检索或 DOI 补查任务。

**Host：** `proceedings.mlr.press`  
**表达式或提取位置：** `https://proceedings.mlr.press/v{volume}/{key}/{key}.pdf`

**所需输入与解析：** v{volume}和文章key；由/v{volume}/{key}.html去.html后拼/{key}.pdf；HTML条件：已有完整文章URL时不需要重新读取HTML。

**中间页或响应：** 不需要额外页面来计算URL；源项目仍读取HTML补元数据。

**访问条件：** OA。

**源实现范围：** URL结构规则，不是DOI-only；与统计/ML论文相关。

**研究证据及模块：** 源码验证（未进行本轮实站下载）；函数/模块：PMLRSource.parse。**来源：** [S043](#s043)。


### A.4 HTML Meta / DOM


<a id="r037"></a>

#### R037 · Nature Portfolio（现代文章）

**本规格采用：** 纳入 P3/P4；排除全站 DOI suffix 拼接与统一删点算法。

**Host：** `www.nature.com`  
**表达式或提取位置：** `citation_pdf_url；否则 a[data-track-action='download pdf']`

**所需输入与解析：** 文章 URL 或 Document；先 Embedded Metadata；缺 PDF 才 getPdfUrl；HTML条件：需要文章HTML、DOM或页面状态。

**已列变体：** `/articles/{article_id}.pdf；article_id 不总等于 DOI suffix`

**中间页或响应：** 由页面给出链接。

**访问条件：** PDF 请求依目标站点授权；所读构造函数未规定额外请求头。

**源实现范围：** 直接 DOI suffix 模板并非该源码实现。反例 DOI onc.2011.282→onc2011282、sdata.2016.18→sdata201618；nsmb.1371/nprot.2006.52 又保留点号，不能全局删点。scrape 接入在 687–705。

**研究证据及模块：** 源码验证；固定 commit 3fb4e794446763ac2053250112890631c428159f；未运行实站下载；函数/模块：getPdfUrl; scrape。**来源：** [S039](#s039)。


<a id="r038"></a>

#### R038 · BioMed Central

**本规格采用：** 纳入 P3/P4；只读取目标论文页面及本条明确字段。

**Host：** `*.biomedcentral.com`  
**表达式或提取位置：** `citation_pdf_url`

**所需输入与解析：** Document；HTML meta；HTML条件：需要文章HTML、DOM或页面状态。

**已列变体：** `随 meta 指定`

**中间页或响应：** 源码不解析中间页。

**访问条件：** PDF 请求依目标站点授权；所读构造函数未规定额外请求头。

**源实现范围：** 源码未提供独立 DOI 模板；出版商族同属 Springer Nature 不等于使用相同 Host/模板。

**研究证据及模块：** 源码验证；固定 commit 3fb4e794446763ac2053250112890631c428159f；未运行实站下载；函数/模块：scrape。**来源：** [S044](#s044)。


<a id="r039"></a>

#### R039 · Atypon 共用解析器

**本规格采用：** 复用已有 Atypon Host 识别。实际 Host、期刊类型与 DOI 确认后，已有专用 P1 模板优先；没有专用模板时，共享 `/doi/pdf/{doi}` 直达入口。P3/P4、Reader 和 P5 保留为后续来源。

**Host：** `pdf_rules.ATYPON_HOSTS` 中已有实际期刊 Host，不按 publisher 名称推断。
**表达式或提取位置：** 通用 P1 为 `/doi/pdf/{doi}`；当前 DOM 中的 `/doi/pdf/`、`/doi/epdf/`、`/doi/pdfplus/` 仍供 P3/P4 使用。

**所需输入与解析：** P1 需要已确认 Host、期刊文章类型和 DOI；书籍、章节、会议及未知 Host 不获得这个共享模板。P3/P4 仍只读取目标论文页面。专用模板的 URL、查询参数和 DOI 请求拼写保持原规则。

**已列变体：** `/doi/pdf/{doi}; /doi/epdf/{doi}; /doi/pdfplus/{doi}`

**中间页或响应：** 仅 EMBO host 特判 pdfdirect。

**访问条件：** PDF 请求依目标站点授权；所读构造函数未规定额外请求头。

**源实现范围：** 源 `buildPdfUrl` 根据 DOM 选择路径。本机版本及现场出版版 PDF 入口对照用于扩展共用直达资格；不轮询三个变体，不复制 Translator 实现。共用优先级还适用于其他平台已有的直达候选与 Reader；不会为了排序提前打开新页面。

**研究证据及模块：** 历史源码固定 commit `3fb4e794446763ac2053250112890631c428159f`，本机 Atypon Journals 更新日期 `2022-10-25 02:51:38`；具体实站覆盖及未验证 Host 见 [配对验收报告](pdf-pairing-acceptance.md)。**来源：** [S026](#s026)。


<a id="r040"></a>

#### R040 · RSC Publishing

**本规格采用：** 过渡限制：使用当前文章实际给出的明确 Meta/下载入口；不将尚未确认的迁移后结构或旧路径推导为新规则。

**Host：** `pubs.rsc.org`  
**表达式或提取位置：** `citation_pdf_url（Embedded Metadata）`

**所需输入与解析：** Document；HTML meta；HTML条件：需要文章HTML、DOM或页面状态。

**已列变体：** `主文 PDF 与 .list__item-link 中 Supplementary information 分开`

**中间页或响应：** 未定义。

**访问条件：** PDF 请求依目标站点授权；所读构造函数未规定额外请求头。

**源实现范围：** Zotero 本文件未直接构造 articlepdf/{year}/{journal}/{code}；不要把 supplementary PDF 误当主文规则。 官方公告列出2026-06-30迁移计划；本轮未独立确认完成后的PDF字段。

**研究证据及模块：** 源码验证；固定 commit 3fb4e794446763ac2053250112890631c428159f；未运行实站下载；函数/模块：scrape。**来源：** [S045](#s045)。


<a id="r041"></a>

#### R041 · PLOS Journals

**本规格采用：** 纳入 P3/P4；只读取目标论文页面及本条明确字段。

**Host：** `journals.plos.org`  
**表达式或提取位置：** `citation_pdf_url（Embedded Metadata）`

**所需输入与解析：** Document；HTML meta；HTML条件：需要文章HTML、DOM或页面状态。

**已列变体：** `PLOS journal slug 由当前页面给出`

**中间页或响应：** 未定义。

**访问条件：** PDF 请求依目标站点授权；所读构造函数未规定额外请求头。

**源实现范围：** 源码没有 DOI suffix→journal slug 的直接映射；如果其他项目提供 article/file?id={doi}&type=print，需引用那一项目而非此文件。

**研究证据及模块：** 源码验证；固定 commit 3fb4e794446763ac2053250112890631c428159f；未运行实站下载；函数/模块：scrape。**来源：** [S046](#s046)。


<a id="r042"></a>

#### R042 · MDPI

**本规格采用：** 纳入 P3/P4；只读取目标论文页面及本条明确字段。

**Host：** `www.mdpi.com`  
**表达式或提取位置：** `citation_pdf_url（Embedded Metadata）`

**所需输入与解析：** Document；HTML meta；HTML条件：需要文章HTML、DOM或页面状态。

**已列变体：** `由页面指定主站或 CDN URL`

**中间页或响应：** 未定义。

**访问条件：** PDF 请求依目标站点授权；所读构造函数未规定额外请求头。

**源实现范围：** Zotero 没有 DOI 后缀拆 volume/issue/article 的规则，也不硬编码 pub.mdpi-res.com；更适合把其他项目 CDN 推导标为有条件启发式。 测试反例：10.3390/admsci3030032 对应卷3期3、/2076-3387/3/3/32，固定两位卷数解析会误判；见L122–150。

**研究证据及模块：** 源码验证；固定 commit 3fb4e794446763ac2053250112890631c428159f；未运行实站下载；函数/模块：scrape。**来源：** [S038](#s038)。


<a id="r043"></a>

#### R043 · Copernicus

**本规格采用：** 纳入 P3/P4；只读取目标论文页面及本条明确字段。

**Host：** `{journal}.copernicus.org`  
**表达式或提取位置：** `citation_pdf_url（Embedded Metadata）`

**所需输入与解析：** Document；HTML meta；HTML条件：需要文章HTML、DOM或页面状态。

**已列变体：** `源码能把现成 .pdf URL 改 .html 读取 metadata`

**中间页或响应：** 未定义。

**访问条件：** PDF 请求依目标站点授权；所读构造函数未规定额外请求头。

**源实现范围：** 测试展示 10.5194/{journal}-{vol}-{page}-{year} 对应 articles/{vol}/{page}/{year} 路径，但 translator 未将 DOI 拆成 PDF 模板；新 discussion/preprint DOI 不能沿用旧格式而不确认。

**研究证据及模块：** 源码验证；固定 commit 3fb4e794446763ac2053250112890631c428159f；未运行实站下载；函数/模块：doWeb; scrape。**来源：** [S047](#s047)。


<a id="r044"></a>

#### R044 · ACS 当前 Silverchair 页面

**本规格采用：** 纳入 P3/P4 的当前 ACS 规则；旧 DOI 模板另列 R072，不默认回试。

**Host：** `pubs.acs.org`  
**表达式或提取位置：** `a.article-pdfLink[href]`

**所需输入与解析：** Document；resourceId/resourceType；特殊从 a[href*='/Citation/Download'] query 获取引文 ID；HTML条件：需要文章HTML、DOM或页面状态。

**已列变体：** `新 /{journal}/article/...；旧 /doi/... 入口测试仍存在`

**中间页或响应：** 本 translator 未指定。

**访问条件：** PDF 请求依目标站点授权；所读构造函数未规定额外请求头。

**源实现范围：** lastUpdated 2026-08-10；测试 937+ 含旧 /doi 入口，1146/1192 为新 jacsat/article 路径。旧 /doi/pdf/{doi} 是否保留服务器兼容由其他证据核查。

**研究证据及模块：** 源码验证；固定 commit 3fb4e794446763ac2053250112890631c428159f；未运行实站下载；函数/模块：citationLinkParam; scrape。**来源：** [S029](#s029)。


<a id="r045"></a>

#### R045 · AIP 当前平台

**本规格采用：** 纳入 P3/P4；只读取目标论文页面及本条明确字段。

**Host：** `pubs.aip.org`  
**表达式或提取位置：** `a.article-pdfLink[href]`

**所需输入与解析：** Document；Silverchair DOM；HTML条件：需要文章HTML、DOM或页面状态。

**已列变体：** `新 /{publisher}/{journal}/article/...`

**中间页或响应：** 本 translator 未指定。

**访问条件：** PDF 请求依目标站点授权；所读构造函数未规定额外请求头。

**源实现范围：** 源码测试含 pubs.aip.org/avs/aqs/article/...；scitation.aip.org 的 AIP.js 属另一旧站规则。

**研究证据及模块：** 源码验证；固定 commit 3fb4e794446763ac2053250112890631c428159f；未运行实站下载；函数/模块：scrape。**来源：** [S029](#s029)。


<a id="r046"></a>

#### R046 · JAMA Network

**本规格采用：** 纳入 P3/P4；只读取目标论文页面及本条明确字段。

**Host：** `jamanetwork.com`  
**表达式或提取位置：** `a#pdf-link[data-article-url]；先尝试 a.article-pdfLink[href]`

**所需输入与解析：** Document；article numeric ID；Silverchair DOM/属性；HTML条件：需要文章HTML、DOM或页面状态。

**已列变体：** `/journals/{journal}/fullarticle/{article_id} 入口`

**中间页或响应：** 本 translator 未指定。

**访问条件：** PDF 请求依目标站点授权；所读构造函数未规定额外请求头。

**源实现范围：** 针对所有 JAMA 的特殊属性分支为源码注释明确；仅 DOI 不能在这段实现中计算 article ID/最终 PDF。 Zotero Silverchair显式注释 all JAMA journals；不是DOI后缀推导。

**研究证据及模块：** 源码验证；固定 commit 3fb4e794446763ac2053250112890631c428159f；未运行实站下载；函数/模块：scrape。**来源：** [S029](#s029)。


<a id="r047"></a>

#### R047 · Rockefeller University Press

**本规格采用：** 纳入 P3/P4；只读取目标论文页面及本条明确字段。

**Host：** `rupress.org`  
**表达式或提取位置：** `a.article-pdfLink[href]`

**所需输入与解析：** Document；Silverchair DOM；HTML条件：需要文章HTML、DOM或页面状态。

**已列变体：** `article/article-abstract 入口`

**中间页或响应：** 未指定。

**访问条件：** PDF 请求依目标站点授权；所读构造函数未规定额外请求头。

**源实现范围：** 固定 SHA 测试包含 JCB 页面；共享机制保留 Host，不能当统一 DOI 模板。

**研究证据及模块：** 源码验证；固定 commit 3fb4e794446763ac2053250112890631c428159f；未运行实站下载；函数/模块：scrape。**来源：** [S029](#s029)。


<a id="r048"></a>

#### R048 · ASH / Blood

**本规格采用：** 纳入 P3/P4；只读取目标论文页面及本条明确字段。

**Host：** `ashpublications.org`  
**表达式或提取位置：** `a.article-pdfLink[href]`

**所需输入与解析：** Document；Silverchair DOM；HTML条件：需要文章HTML、DOM或页面状态。

**已列变体：** `article/article-abstract 入口`

**中间页或响应：** 未指定。

**访问条件：** PDF 请求依目标站点授权；所读构造函数未规定额外请求头。

**源实现范围：** 固定 SHA 测试包含 Blood 页面。

**研究证据及模块：** 源码验证；固定 commit 3fb4e794446763ac2053250112890631c428159f；未运行实站下载；函数/模块：scrape。**来源：** [S029](#s029)。


<a id="r049"></a>

#### R049 · ARVO Journals

**本规格采用：** 保留共享选择器能力，仅在当前页面确有合格正文入口时返回候选；材料测试没有 PDF 期望，不计作已确认下载覆盖。

**Host：** `*.arvojournals.org`  
**表达式或提取位置：** `a.article-pdfLink[href]`

**所需输入与解析：** Document；Silverchair DOM；HTML条件：需要文章HTML、DOM或页面状态。

**已列变体：** `article.aspx?articleid=...`

**中间页或响应：** 未指定。

**访问条件：** PDF 请求依目标站点授权；所读构造函数未规定额外请求头。

**源实现范围：** 测试样本仅期望 Snapshot，无 PDF；说明检测/元数据支持不等同该测试 PDF 获取成功。

**研究证据及模块：** 源码验证；固定 commit 3fb4e794446763ac2053250112890631c428159f；未运行实站下载；函数/模块：scrape。**来源：** [S029](#s029)。


<a id="r050"></a>

#### R050 · GeoScienceWorld

**本规格采用：** 保留共享选择器能力及内容类型限制；章节案例不扩展默认论文范围，不计作已确认 PDF 下载覆盖。

**Host：** `pubs.geoscienceworld.org`  
**表达式或提取位置：** `a.article-pdfLink[href]`

**所需输入与解析：** Document；Silverchair DOM；HTML条件：需要文章HTML、DOM或页面状态。

**已列变体：** `article / chapter / chapter-abstract`

**中间页或响应：** 未指定。

**访问条件：** PDF 请求依目标站点授权；所读构造函数未规定额外请求头。

**源实现范围：** 测试有书籍章节，非 DOI-only；该测试不期望 PDF，不能据此声称可下载覆盖。

**研究证据及模块：** 源码验证；固定 commit 3fb4e794446763ac2053250112890631c428159f；未运行实站下载；函数/模块：scrape。**来源：** [S029](#s029)。


<a id="r051"></a>

#### R051 · Cambridge Core

**本规格采用：** 期刊纳入 P3/P4；书籍/章节分支仅作扩展参考，历史 DOI shortcut 不默认采用。

**Host：** `www.cambridge.org`  
**表达式或提取位置：** `期刊：citation_pdf_url；图书/章节：meta name contains citation_pdf_url 或 .actions a[target='_blank'][href*='.pdf']`

**所需输入与解析：** Document；图书引用另需 productID；meta/DOM；productID 来自 URL 最后段；HTML条件：需要文章HTML、DOM或页面状态。

**已列变体：** `core/services/aop-easybib/export 用于 RIS，不是 PDF`

**中间页或响应：** 本 translator 未指定。

**访问条件：** PDF 请求依目标站点授权；所读构造函数未规定额外请求头。

**源实现范围：** 图书引用 ID 与 PDF URL 各自独立。期刊主路径委托 Embedded Metadata；未发现通用 DOI→PDF 模板。 历史pubpatterns仅用DOI尾缀插入content/view的写法未获当前实现交叉确认，单列历史，不升级。

**研究证据及模块：** 源码验证；固定 commit 3fb4e794446763ac2053250112890631c428159f；未运行实站下载；函数/模块：scrape。**来源：** [S048](#s048)。


<a id="r052"></a>

#### R052 · HighWire 2.0 / BMJ 系

**本规格采用：** 纳入 P3/P4；只读取目标论文页面及本条明确字段。

**Host：** `各 journal Host，如 bmj.com 及其子域`  
**表达式或提取位置：** `citation_pdf_url（Embedded Metadata）`

**所需输入与解析：** Document；HTML meta；HTML条件：需要文章HTML、DOM或页面状态。

**已列变体：** `/content/...；.full.pdf+html 阅读器`

**中间页或响应：** 若用户已在 .full.pdf+html，回到文章页面读取元数据。

**访问条件：** PDF 请求依目标站点授权；所读构造函数未规定额外请求头。

**源实现范围：** 这不是用 DOI 推导 volume/issue/page；共享点是 metadata/页面标志。阅读器分支 435–437。 不把某一期刊的/content/journal/*.full.pdf路径推广到所有HighWire站点。

**研究证据及模块：** 源码验证；固定 commit 3fb4e794446763ac2053250112890631c428159f；未运行实站下载；函数/模块：addEmbMeta; doWeb。**来源：** [S049](#s049)。


<a id="r053"></a>

#### R053 · Optica / OSA

**本规格采用：** 纳入 P3/P4；只读取目标论文页面及本条明确字段。

**Host：** `opg.optica.org；旧 osapublishing.org`  
**表达式或提取位置：** `citation_pdf_url 或 #link-pdf → 中间页 frame src / gotourl → PDF`

**所需输入与解析：** Document；中间页 URL；frame:not(:first-of-type)[src] 或中间页 query gotourl；HTML条件：需要文章HTML、DOM或页面状态。

**已列变体：** `直接 PDF 时保留原 pdfPageURL`

**中间页或响应：** frame 型中间页，区别于普通 iframe/embed。

**访问条件：** PDF 请求依目标站点授权；所读构造函数未规定额外请求头。

**源实现范围：** 源码先 requestDocument 判断是否 HTML。解析不到时仍保留 pdfPageURL 以报告附件失败；这不是验证码解决方案。

**研究证据及模块：** 源码验证；固定 commit 3fb4e794446763ac2053250112890631c428159f；未运行实站下载；函数/模块：scrape。**来源：** [S050](#s050)。


<a id="r054"></a>

#### R054 · De Gruyter Brill

**本规格采用：** 纳入 P3/P4；只读取目标论文页面及本条明确字段。

**Host：** `www.degruyterbrill.com`  
**表达式或提取位置：** `a.downloadPdf[href]`

**所需输入与解析：** Document；DOM；HTML条件：需要文章HTML、DOM或页面状态。

**已列变体：** `按平台给出的 document/download 路径`

**中间页或响应：** 未指定。

**访问条件：** PDF 请求依目标站点授权；所读构造函数未规定额外请求头。

**源实现范围：** 源码清空 EM 附件后以该 DOM 链接重新设置；旧 degruyter.com DOI模板不能无条件覆盖新 Host。

**研究证据及模块：** 源码验证；固定 commit 3fb4e794446763ac2053250112890631c428159f；未运行实站下载；函数/模块：scrape。**来源：** [S051](#s051)。


<a id="r055"></a>

#### R055 · Emerald Insight

**本规格采用：** 纳入 P3/P4；只读取目标论文页面及本条明确字段。

**Host：** `www.emerald.com`  
**表达式或提取位置：** `a.intent_pdf_link[href]；已在 full/pdf? 页面时沿用当前 URL`

**所需输入与解析：** Document；DOM；HTML条件：需要文章HTML、DOM或页面状态。

**已列变体：** `full/pdf?`

**中间页或响应：** 未指定。

**访问条件：** PDF 请求依目标站点授权；所读构造函数未规定额外请求头。

**源实现范围：** XSRF cookie/token 在本源码用于 RIS citation 请求，不能误写为 PDF 请求必须具备该 header。 历史/doi/pdfplus/{doi}不可当作当前唯一规则；源码当前明确使用页面入口。

**研究证据及模块：** 源码验证；固定 commit 3fb4e794446763ac2053250112890631c428159f；未运行实站下载；函数/模块：scrape。**来源：** [S052](#s052)。


<a id="r056"></a>

#### R056 · Brill

**本规格采用：** 纳入 P3/P4；只读取目标论文页面及本条明确字段。

**Host：** `brill.com；referenceworks.brill.com`  
**表达式或提取位置：** `citation_pdf_url（Embedded Metadata）`

**所需输入与解析：** Document；HTML meta；HTML条件：需要文章HTML、DOM或页面状态。

**已列变体：** `按页面实际路径`

**中间页或响应：** 未指定。

**访问条件：** PDF 请求依目标站点授权；所读构造函数未规定额外请求头。

**源实现范围：** 不是 De Gruyter Brill 同一规则。特定 bibliography 分支另处理引用。

**研究证据及模块：** 源码验证；固定 commit 3fb4e794446763ac2053250112890631c428159f；未运行实站下载；函数/模块：scrape。**来源：** [S053](#s053)。


<a id="r057"></a>

#### R057 · eLife

**本规格采用：** 纳入 P3/P4；只读取目标论文页面及本条明确字段。

**Host：** `elifesciences.org`  
**表达式或提取位置：** `.article-download-list a[href]`

**所需输入与解析：** Document；DOM；引用用当前 URL 去 vN 后 + .ris；HTML条件：需要文章HTML、DOM或页面状态。

**已列变体：** `版本可能体现在服务器返回 URL`

**中间页或响应：** 未指定。

**访问条件：** PDF 请求依目标站点授权；所读构造函数未规定额外请求头。

**源实现范围：** 源码不直接用 DOI suffix 拼 elife-{id}-vN.pdf；版本和文件名由页面链接提供。

**研究证据及模块：** 源码验证；固定 commit 3fb4e794446763ac2053250112890631c428159f；未运行实站下载；函数/模块：scrape。**来源：** [S054](#s054)。


<a id="r058"></a>

#### R058 · Thieme Connect

**本规格采用：** 纳入 P3/P4；只读取目标论文页面及本条明确字段。

**Host：** `www.thieme-connect.com`  
**表达式或提取位置：** `citation_pdf_url（Embedded Metadata）`

**所需输入与解析：** Document；HTML meta；HTML条件：需要文章HTML、DOM或页面状态。

**已列变体：** `/products/... 页面`

**中间页或响应：** 未指定。

**访问条件：** PDF 请求依目标站点授权；所读构造函数未规定额外请求头。

**源实现范围：** 通过 Embedded Metadata 主路径读 citation_pdf_url；源码未提供独立 DOI 模板。

**研究证据及模块：** 源码验证；固定 commit 3fb4e794446763ac2053250112890631c428159f；未运行实站下载；函数/模块：scrape。**来源：** [S055](#s055)。


<a id="r059"></a>

#### R059 · Microbiology Society Journals

**本规格采用：** 纳入 P4，读取明确 PDF 表单 action；不自行增加源码未提供依据的 POST 提交行为。

**Host：** `*.microbiologyresearch.org`  
**表达式或提取位置：** `.download-pdf form.ft-download-content__form--pdf[action]`

**所需输入与解析：** Document；读取下载表单 action；HTML条件：需要文章HTML、DOM或页面状态。

**已列变体：** `HTML 表单 action，非普通 anchor`

**中间页或响应：** 源码直接将 action 当 PDF 候选。

**访问条件：** PDF 请求依目标站点授权；所读构造函数未规定额外请求头。

**源实现范围：** 新增可复用 DOM 形态：form[action]。源码没有复制表单提交方法/参数，不应无据推广为需要 POST。

**研究证据及模块：** 源码验证；固定 commit 3fb4e794446763ac2053250112890631c428159f；未运行实站下载；函数/模块：scrape。**来源：** [S056](#s056)。


<a id="r060"></a>

#### R060 · LWW / Ovid Journals

**本规格采用：** 条件性专用规则：已有合法 LWW/Ovid 页面和上下文时解析；OCE 回退须单独满足该平台条件。

**Host：** `journals.lww.com; pdfs.journals.lww.com`  
**表达式或提取位置：** `/{journal}/_layouts/15/oaks.journals/downloadpdf.aspx?trckng_src_pg=ArticleViewer&an={AN} → pdfDownloadDetails.pdfUrl`

**所需输入与解析：** AN + journal slug + 动态签名URL；文章页PDFDownloadInit/页面文本提取AN；viewer中读取pdfUrl；HTML条件：需要文章HTML、DOM或页面状态。

**已列变体：** `Ovid OCE作为另一内容平台的条件性回退`

**中间页或响应：** 下载viewer HTML→动态签名PDF；需要保留请求上下文。

**访问条件：** 在该项目代理环境中，最终请求Referer为downloadpdf.aspx。

**源实现范围：** AN形如8位-9位-5位；签名地址不能从DOI自行计算，也不宜作为永久模板。Referer必需是该项目记录的条件，未证明所有LWW访问环境一致。

**研究证据及模块：** 源码验证；本轮未做授权下载；函数/模块：_lww_ovid_pdf; _ovid_oce_pdf。**来源：** [S002](#s002)。


<a id="r061"></a>

#### R061 · SIAM Journals（Atypon 规则线索）

**本规格采用：** 本条保留 P3/P4 DOM 线索；直达入口使用共用 [R039](#r039)，不增加 SIAM 专用性能分支。所有候选适用共用直达优先级，失败后仍可进入 Reader 与 P5。

**Host：** `epubs.siam.org`  
**表达式或提取位置：** 已确认 DOM 中的 `/doi/pdf/{doi}`、`/doi/epdf/{doi}`、`/doi/pdfplus/{doi}`。

**所需输入与解析：** 本条读取文章 DOI URL + 目标论文 DOM；已识别 Host 的期刊 DOI 直达资格由 R039 共用规则处理。

**已列变体：** ePDF 可能返回 HTML，与直接 PDF 是不同入口。

**中间页或响应：** 依响应。

**访问条件：** 机构Session或OA。

**源实现范围：** 本机 Atypon Journals `2022-10-25 02:51:38` 的 `buildPdfUrl` 按 DOM 线索选择路径。真实 Connector 已从当前 SIAM `/doi/pdf/` 保存出版版；Allfold 将该证据用于共用入口选择，保留原 Session、Service 与保存终点，未复制 Translator 源码。

**研究证据及模块：** 本轮具体样本、修复前后版本及现场结果见 [配对验收报告](pdf-pairing-acceptance.md)。历史源码依据仍为 `buildPdfUrl`。**来源：** [S026](#s026)。


### A.5 历史候选：默认不启用


<a id="r062"></a>

#### R062 · Hindawi 旧平台

**本规格采用：** 历史材料；不进入默认发现链，也不作为默认失败后的追加候选池。

**Host：** `www.hindawi.com`  
**表达式或提取位置：** `citation_pdf_url（Embedded Metadata）`

**所需输入与解析：** Document；HTML meta；HTML条件：取决于历史规则；未确认为当前通用途径。

**已列变体：** `旧 journals/{slug}/{year}/{id} 页面`

**中间页或响应：** 未定义。

**访问条件：** PDF 请求依目标站点授权；所读构造函数未规定额外请求头。

**源实现范围：** 该文件 lastUpdated 2021，旧 Hindawi host 的元数据方法；未提供通用 DOI→PDF 模板。迁移后 Wiley 路径应另由实际平台规则处理。

**研究证据及模块：** 源码验证；固定 commit 3fb4e794446763ac2053250112890631c428159f；未运行实站下载；函数/模块：scrape。**来源：** [S057](#s057)。


<a id="r063"></a>

#### R063 · EMBO Press 旧 Atypon 路径

**本规格采用：** 历史材料；不进入默认发现链，也不作为默认失败后的追加候选池。

**Host：** `www.embopress.org`  
**表达式或提取位置：** `匹配 /pdf/ 或 /epdf/ 改 /pdfdirect/，追加 download=true`

**所需输入与解析：** 文章 DOI URL + DOM；Atypon buildPdfUrl 中 host 精确特判；HTML条件：取决于历史规则；未确认为当前通用途径。

**已列变体：** `/doi/pdfdirect/{doi}?download=true`

**中间页或响应：** 避免嵌入式阅读器。

**访问条件：** PDF 请求依目标站点授权；所读构造函数未规定额外请求头。

**源实现范围：** 该特判只匹配 www.embopress.org。不要推广到所有 epdf，也不要假定出版社迁移后仍使用旧 Host。

**研究证据及模块：** 源码验证；固定 commit 3fb4e794446763ac2053250112890631c428159f；未运行实站下载；函数/模块：buildPdfUrl。**来源：** [S026](#s026)。


<a id="r064"></a>

#### R064 · Cell Press 旧期刊下载桥接

**本规格采用：** 历史材料；不进入默认发现链，也不作为默认失败后的追加候选池。

**Host：** `*.cell.com`  
**表达式或提取位置：** `Embedded Metadata PDF → HTML 中 redirectToScienceURL 的 input value，或追加 intermediate=true`

**所需输入与解析：** Document；EM PDF URL；按两种 onload 标志区分中间页；HTML条件：取决于历史规则；未确认为当前通用途径。

**已列变体：** `ScienceDirect 转接；trackPDFDownload 页面`

**中间页或响应：** HTML/JavaScript 模板识别。

**访问条件：** PDF 请求依目标站点授权；所读构造函数未规定额外请求头。

**源实现范围：** 源码机制确实接入附件路径；文件历史较旧，特征存在性须按当前页面验证。不可把任意 JS 赋值都当可执行跳转。

**研究证据及模块：** 源码验证；固定 commit 3fb4e794446763ac2053250112890631c428159f；未运行实站下载；函数/模块：scrape。**来源：** [S058](#s058)。


<a id="r065"></a>

#### R065 · BioOne 旧 Atypon 页面

**本规格采用：** 历史材料；不进入默认发现链，也不作为默认失败后的追加候选池。

**Host：** `www.bioone.org`  
**表达式或提取位置：** `/action/showCitFormats?doi={doi} → /doi/pdf/{doi}`

**所需输入与解析：** 引用导出页面 URL；URL 路径转换；HTML条件：取决于历史规则；未确认为当前通用途径。

**已列变体：** `旧 DOI 路径`

**中间页或响应：** 未指定。

**访问条件：** PDF 请求依目标站点授权；所读构造函数未规定额外请求头。

**源实现范围：** 老 translator 目标仅 www.bioone.org/s；不能据此保证当前 BioOne Complete 新站路径可直接使用。

**研究证据及模块：** 源码验证；固定 commit 3fb4e794446763ac2053250112890631c428159f；未运行实站下载；函数/模块：scrape。**来源：** [S059](#s059)。


<a id="r066"></a>

#### R066 · SPIE Digital Library（历史规则）

**本规格采用：** 历史材料；不进入默认发现链，也不作为默认失败后的追加候选池。

**Host：** `www.spiedigitallibrary.org`  
**表达式或提取位置：** `https://www.spiedigitallibrary.org/journalIssue/Download?fullDOI={doi}`

**所需输入与解析：** 完整DOI；pubpatterns src/spie.json；HTML条件：取决于历史规则；未确认为当前通用途径。

**中间页或响应：** 未知；历史规则标记cookies=true。

**访问条件：** 历史数据标记cookies=true；是否必需及当前条件未独立验证。

**源实现范围：** 2020规则，fulltext ftd_doi示例包括SPIE会议论文与期刊；本轮没有2026端点有效性证据。

**研究证据及模块：** 源码验证（未进行本轮实站下载）；函数/模块：pub_spie = pub_factory1。**来源：** [S060](#s060)。


<a id="r067"></a>

#### R067 · Pensoft（历史规则）

**本规格采用：** 历史材料；不进入默认发现链，也不作为默认失败后的追加候选池。

**Host：** `{journal}.pensoft.net`  
**表达式或提取位置：** `https://{journal}.pensoft.net/article/{trailing_integer}/download/pdf/`

**所需输入与解析：** DOI末尾数字 + 期刊Host；pubpatterns journals按ISSN匹配Host，DOI regex [0-9]+$；HTML条件：取决于历史规则；未确认为当前通用途径。

**中间页或响应：** 无专用。

**访问条件：** OA。

**源实现范围：** 历史库的RIO条目pdf字段错误指向/download/xml/，应排除；不能将所有Pensoft Host由DOI前缀直接推导。

**研究证据及模块：** 源码验证（未进行本轮实站下载）；函数/模块：pub_pensoft。**来源：** [S061](#s061)、[S062](#s062)。


<a id="r068"></a>

#### R068 · PeerJ（历史规则）

**本规格采用：** 历史材料；不进入默认发现链，也不作为默认失败后的追加候选池。

**Host：** `peerj.com`  
**表达式或提取位置：** `https://peerj.com/articles/{id}.pdf；CS: https://peerj.com/articles/cs-{id}.pdf`

**所需输入与解析：** DOI尾部数字 + journal类型；pubpatterns按ISSN区分PeerJ/Computer Science/Preprints；HTML条件：取决于历史规则；未确认为当前通用途径。

**已列变体：** `/preprints/{id}.pdf`

**访问条件：** OA。

**源实现范围：** 2020规则；不合并普通PeerJ、CS及旧preprints。

**研究证据及模块：** 源码验证（未进行本轮实站下载）；函数/模块：pub_peerj = pub_factory2。**来源：** [S063](#s063)。


<a id="r069"></a>

#### R069 · Thieme

**本规格采用：** 历史材料；不进入默认发现链，也不作为默认失败后的追加候选池。

**Host：** `www.thieme-connect.com`  
**表达式或提取位置：** `https://www.thieme-connect.com/products/ejournals/pdf/{doi}.pdf`

**所需输入与解析：** 完整DOI；pubpatterns 2020按期刊ISSN列出的模板；Zotero当前Thieme仍走Embedded Metadata；HTML条件：取决于历史规则；未确认为当前通用途径。

**中间页或响应：** 未知；缺少该直达模板2026实站佐证。

**访问条件：** OA或机构Session。

**源实现范围：** 将直达模板标历史候选；当前稳妥证据为citation_pdf_url回退。

**研究证据及模块：** 源码验证（未进行本轮实站下载）；函数/模块：Thieme.scrape / pubpatterns。**来源：** [S064](#s064)、[S055](#s055)。


<a id="r070"></a>

#### R070 · Trans Tech / Scientific.Net（历史规则）

**本规格采用：** 历史材料；不进入默认发现链，也不作为默认失败后的追加候选池。

**Host：** `www.scientific.net`  
**表达式或提取位置：** `http://{DOI中从www.scientific.net开始的后缀}.pdf`

**所需输入与解析：** 形如10.4028/www.scientific.net/MSF.702-703.774的DOI；pubpatterns regex www.scientific.net.+；HTML条件：取决于历史规则；未确认为当前通用途径。

**中间页或响应：** 未知。

**访问条件：** 不能依历史JSON open_access=true断言全部免费。

**源实现范围：** 仅匹配包含域名的历史DOI结构；不得对任意10.4028 DOI套用。

**研究证据及模块：** 源码验证（未进行本轮实站下载）；函数/模块：pub_transtech = pub_factory1。**来源：** [S065](#s065)。


<a id="r071"></a>

#### R071 · Cambridge Core（旧直达候选）

**本规格采用：** 历史材料；不进入默认发现链，也不作为默认失败后的追加候选池。

**Host：** `www.cambridge.org`  
**表达式或提取位置：** `https://www.cambridge.org/core/services/aop-cambridge-core/content/view/{DOI最后一段}`

**所需输入与解析：** DOI末尾[A-Za-z0-9\-.]+；pubpatterns src/cambridge.json；HTML条件：取决于历史规则；未确认为当前通用途径。

**中间页或响应：** 未知；该路径本身不保证PDF。

**访问条件：** 历史cookies=true。

**源实现范围：** Zotero当前Core实现未采用此模板；不得升级为2026通用DOI直达规则。

**研究证据及模块：** 源码验证（未进行本轮实站下载）；函数/模块：pubpatterns。**来源：** [S066](#s066)、[S048](#s048)。


<a id="r072"></a>

#### R072 · ACS（旧 DOI 模板候选）

**本规格采用：** 历史材料；不进入默认发现链，也不作为默认失败后的追加候选池。

**Host：** `pubs.acs.org`  
**表达式或提取位置：** `https://pubs.acs.org/doi/pdf/{doi}`

**所需输入与解析：** 完整 DOI；Agents365 / JabRef中的已有模板；当前ACS另有Silverchair路径；HTML条件：取决于历史规则；未确认为当前通用途径。

**已列变体：** `当前 a.article-pdfLink；新文章路径/{journal}/article/...`

**中间页或响应：** 可能兼容redirect，当前兼容范围未确认。

**访问条件：** 机构Session或OA。

**源实现范围：** ACS官方确认2026-07-24迁移到Silverchair。旧模板的代码存在不证明迁移后普遍有效。

**研究证据及模块：** 源码验证；本轮未做授权下载；函数/模块：_PUBLISHER_DIRECT_TEMPLATES; Silverchair.scrape。**来源：** [S025](#s025)、[S067](#s067)、[S029](#s029)。


---

<a id="api-catalog"></a>

## 附录 B：17 条接口或服务记录

本节保留研究材料中的端点、返回格式、凭证要求和证据等级；“采用处置”表示其在本规格中的角色。服务名称含 fulltext、Open Access 或 TDM，不代表返回 PDF。


<a id="api01"></a>

### API01 · DOI Proxy

**采用处置：** 默认可用的条件性查询能力；不要求每篇调用。

**端点或字段：** `https://doi.org/api/handles/{doi}?type=URL`

**输入 / HTML 条件：** DOI；不需要文章HTML。

**授权与输出：** 无API key参数；JSON中的 values[type=URL].data.value。

**限制与原研究核查范围：** 官方文档确认。只给注册目标URL，可能仍需HTTP跳转；适合条件性ID解析。 Wiley官方SDK使用Handle API核查DOI；将登记URL解释为PII等平台ID仍需独立的识别规则。；未测试实际授权下载。

**证据：** 官方文档已读。**来源：** [S068](#s068)、[S069](#s069)、[S070](#s070)、[S071](#s071)、[S072](#s072)、[S073](#s073)。


<a id="api02"></a>

### API02 · Crossref REST

**采用处置：** 默认可用的条件性查询能力；优先复用已有目标记录。

**端点或字段：** `https://api.crossref.org/works/{doi} → alternative-id、link[]、普通资源URL`

**输入 / HTML 条件：** DOI；不需要。

**授权与输出：** 元数据服务；全文链接权限由承载站控制。

**限制与原研究核查范围：** link按 content-type/intended-application区分，不把TDM XML当PDF。；未测试实际授权下载。

**证据：** 官方文档已读。**来源：** [S074](#s074)、[S075](#s075)、[S076](#s076)。


<a id="api03"></a>

### API03 · IEEE Xplore Metadata

**采用处置：** 已有凭证时可选；缺凭证跳过。

**端点或字段：** `https://ieeexploreapi.ieee.org/api/v1/search/articles?doi={doi}&apikey={key}`

**输入 / HTML 条件：** DOI；不需要。

**授权与输出：** API key；JSON/XML；article_number、pdf_url（仅有值的字段返回）。

**限制与原研究核查范围：** 官方参数/输出表。；未测试实际授权下载。

**证据：** 官方文档已读。**来源：** [S035](#s035)、[S036](#s036)、[S077](#s077)、[S078](#s078)。


<a id="api04"></a>

### API04 · IEEE DOI Metadata

**采用处置：** 已有凭证时可选；本规格不要求新增批量请求调度。

**端点或字段：** `/api/v1/articles/doi/{DOI_Values}`

**输入 / HTML 条件：** DOI列表，最多25；不需要。

**授权与输出：** API key；JSON/XML。

**限制与原研究核查范围：** 官方交互API文档明确列出；未实际发key请求。；未测试实际授权下载。

**证据：** 官方文档已读。**来源：** [S077](#s077)。


<a id="api05"></a>

### API05 · IEEE Open Access fulltext

**采用处置：** 仅作格式边界参考；不把 fulltext 接口直接当原始 PDF。

**端点或字段：** `/api/v1/search/document/{article_number}/fulltext`

**输入 / HTML 条件：** article_number；不需要。

**授权与输出：** API key；文档列JSON/XML。

**限制与原研究核查范围：** 不能因为叫fulltext就当成原始PDF下载端点；PDF来源采用 metadata pdf_url 或已核查网页路由。；未测试实际授权下载。

**证据：** 官方文档已读。**来源：** [S036](#s036)、[S077](#s077)、[S078](#s078)。


<a id="api06"></a>

### API06 · Elsevier Article Retrieval

**采用处置：** 已有合格凭证和内容权限时可选；不替代网页 Session 的权限定义。

**端点或字段：** `https://api.elsevier.com/content/article/doi/{doi} 或 .../pii/{pii}，Accept PDF`

**输入 / HTML 条件：** DOI或PII；亦支持 EID/Scopus ID/PubMed ID；不需要。

**授权与输出：** X-ELS-APIKey；可选Insttoken/Authtoken/OAuth；内容及格式权限；PDF/XML/JSON/plain等。

**限制与原研究核查范围：** 当前WADL明确PDF并说明303/307重定向；API key单独不足。；未测试实际授权下载。

**证据：** 官方文档已读。**来源：** [S079](#s079)、[S080](#s080)、[S081](#s081)。


<a id="api07"></a>

### API07 · Wiley TDM

**采用处置：** 已有独立 token 和权限时可选；普通 Wiley 网页候选不依赖此 token。

**端点或字段：** `https://api.wiley.com/onlinelibrary/tdm/v1/articles/{encoded_doi}`

**输入 / HTML 条件：** DOI；不需要。

**授权与输出：** Wiley-TDM-Client-Token；须另取得token与相关订阅权限；提供PDF。

**限制与原研究核查范围：** 初始响应重定向到二进制服务器，跟随redirect； SDK中的5秒间隔与官方页面60次/10分钟限制不同；404分类也不同，接口语义以官方文档为依据。；未测试实际授权下载。

**证据：** 官方文档与源码。**来源：** [S082](#s082)、[S070](#s070)、[S071](#s071)、[S072](#s072)、[S073](#s073)。


<a id="api08"></a>

### API08 · APS Harvest

**采用处置：** P2 可选来源；按官方 OA 无认证路径或既有授权条件使用 PDF 响应类型。

**端点或字段：** `https://harvest.aps.org/v2/journals/articles/{doi} + Accept: application/pdf`

**输入 / HTML 条件：** DOI；不需要。

**授权与输出：** OA可无认证；其他访问依API key/IP/CHORUS entitlement；支持PDF/XML/JSON/ZIP。

**限制与原研究核查范围：** 官方有OA PDF curl示例。另 /accepted_fulltext 要 X-API-Key，无须纳入默认规则。；未测试实际授权下载。

**证据：** 官方文档已读。**来源：** [S083](#s083)。


<a id="api09"></a>

### API09 · Springer Nature Metadata

**采用处置：** 可选候选来源，保留官方正文未完整读取的证据限制；不作为必需接口。

**端点或字段：** `/meta/v2/json?q=doi:{doi}&api_key=... 返回url数组`

**输入 / HTML 条件：** DOI；不需要。

**授权与输出：** API key；元数据JSON。

**限制与原研究核查范围：** 官方示例含 http://link.springer.com/openurl/pdf?id=doi:{doi}。这是公开网页候选URL，不是API直接交付PDF。；官方文档仅在搜索索引中可读，open仅返回页面壳；没有进行端点实测。

**证据：** 官方搜索索引摘录，正文页面未读全。**来源：** [S084](#s084)。


<a id="api10"></a>

### API10 · Springer Nature Open Access

**采用处置：** 不纳入直接 PDF 来源；JSON/JATS 的格式与 PDF 分开。

**端点或字段：** `/openaccess/json、/openaccess/jats`

**输入 / HTML 条件：** DOI等query；不需要。

**授权与输出：** API key；JSON元数据、JATS全文（如有）。

**限制与原研究核查范围：** 不应把JATS接口当PDF二进制。；官方文档仅在搜索索引中可读，open仅返回页面壳；没有进行端点实测。

**证据：** 官方搜索索引摘录，正文页面未读全。**来源：** [S085](#s085)。


<a id="api11"></a>

### API11 · Springer Nature Full Text TDM

**采用处置：** 不纳入本版 PDF 默认来源；保留协议和 XML/JATS 输出边界。

**端点或字段：** `https://api.springernature.com/xmldata/jats?q=...`

**输入 / HTML 条件：** query含DOI等；不需要。

**授权与输出：** special agreement；API key/metric；XML/JATS。

**限制与原研究核查范围：** 2026-08-07前要求从spdi.public.springernature.app迁到api.springernature.com。不是普遍PDF捷径。；官方文档仅在搜索索引中可读，open仅返回页面壳；没有进行端点实测。

**证据：** 官方搜索索引摘录，正文页面未读全。**来源：** [S086](#s086)。


<a id="api12"></a>

### API12 · PLOS individual PDF

**采用处置：** 纳入 P1 的 PLOS ONE 规则；其他期刊需要明确 slug。

**端点或字段：** `https://journals.plos.org/plosone/article/file?id={doi}&type=printable（PLOS ONE官方例）`

**输入 / HTML 条件：** DOI + 期刊slug；不需要。

**授权与输出：** 网页PDF；无需独立API key。

**限制与原研究核查范围：** 官方明确 printable 是PDF，manuscript 是XML。其他期刊slug映射须由源码或页面核实。；未测试实际授权下载。

**证据：** 官方文档已读。**来源：** [S027](#s027)。


<a id="api13"></a>

### API13 · Cambridge Core

**采用处置：** 平台指南参考；不据此新增未经确认的内容 API。

**端点或字段：** `未公布公共内容API`

**输入 / HTML 条件：** DOI/文章URL；普通网页路线。

**授权与输出：** 官方建议从站点获取；大规模TDM联系出版方。

**限制与原研究核查范围：** 不以缺API推断不存在任意历史DOI shortcut；旧shortcut保留为历史证据待核。；未测试实际授权下载。

**证据：** 官方文档已读。**来源：** [S087](#s087)。


<a id="api14"></a>

### API14 · JSTOR text analysis

**采用处置：** 不纳入 PDF 来源；OCR/UUID 与网页 PDF/stable ID 分开。

**端点或字段：** `下载元数据 → item_id列表申请 → OCR全文JSON`

**输入 / HTML 条件：** UUID item_id；非单篇PDF路线。

**授权与输出：** JSTOR账户/条款/数据集申请。

**限制与原研究核查范围：** 非PDF API；stable URL与item_id分开。；未测试实际授权下载。

**证据：** 官方文档已读。**来源：** [S088](#s088)、[S089](#s089)、[S090](#s090)。


<a id="api15"></a>

### API15 · IOP TDM

**采用处置：** 服务指南参考；不新增 SFTP/协议交付流程。

**端点或字段：** `当前官方指向联系后SFTP或双方约定交付`

**输入 / HTML 条件：** DOI列表/期刊日期范围；非普通网页路线。

**授权与输出：** 审批/协议；XML或PDF。

**限制与原研究核查范围：** 不形成可直接调用的DOI PDF API。；未测试实际授权下载。

**证据：** 官方搜索结果。**来源：** [S091](#s091)。


<a id="api16"></a>

### API16 · RSC TDM

**采用处置：** 服务指南参考；不添加未确认的通用 API。

**端点或字段：** `当前官方页指向联系/许可`

**输入 / HTML 条件：** 项目范围；未找到公开通用API。

**授权与输出：** 依项目与许可。

**限制与原研究核查范围：** 不添加未经证实的API端点。；未测试实际授权下载。

**证据：** 官方搜索结果。**来源：** [S092](#s092)。


<a id="api17"></a>

### API17 · OUP

**采用处置：** 保留 OUP API 边界；实际采用 resourceId 引用导出或 Meta/DOM。

**端点或字段：** `未找到公开通用 DOI→PDF API`

**输入 / HTML 条件：** DOI/文章URL；已知resourceId时可用OUP引用导出取eprint；否则使用页面Meta/DOM。

**授权与输出：** 内容访问Session；TDM另联系。

**限制与原研究核查范围：** 只能说未确认；官方真实 article-pdf URL含卷期页码和文件数字ID，不能只保留DOI suffix生成。；只确认具体article-pdf实例；未找到通用公开DOI到PDF API不等于证明其不存在。

**证据：** 官方URL实例；通用接口未确认。**来源：** [S093](#s093)。


---

<a id="repositories"></a>

## 附录 C：仓库版本与许可证

下表保留附件核查的固定 SHA 和许可状态。固定版本用于追溯该次阅读，不代表所有项目都具有相同维护状态。具体函数、文件与行号见规则记录和附录 D；不因许可证未确认而复制整库。

| 仓库 | 固定版本 | 材料记录的许可证 | 取材范围或限制 |
|---|---|---|---|

| [JabRef/jabref](<https://github.com/JabRef/jabref/tree/d79f1490aaafa9bc80da760d1baa6497cebf7c01>) | `d79f1490aaafa9bc80da760d1baa6497cebf7c01` | MIT | 具体文件与机制见附录 D。 |

| [jonatasgrosman/findpapers](<https://github.com/jonatasgrosman/findpapers/tree/3b42b66befa0a64416258e7481201a0253f09e73>) | `3b42b66befa0a64416258e7481201a0253f09e73` | MIT | 具体文件与机制见附录 D。 |

| [Future-Scholars/paperlib-entry-scrape-extension](<https://github.com/Future-Scholars/paperlib-entry-scrape-extension/tree/f3ea1065fe6d9b82f081f170432b98a819171150>) | `f3ea1065fe6d9b82f081f170432b98a819171150` | 本仓库根目录及package.json未找到项目代码许可证；字体许可证不能代表项目许可 | 具体文件与机制见附录 D。 |

| [vict0rsch/PaperMemory](<https://github.com/vict0rsch/PaperMemory/tree/d6bbea7375cfe64b99d3cf9a62d70244d09a7693>) | `d6bbea7375cfe64b99d3cf9a62d70244d09a7693` | MIT（LICENSE版权占位符未填） | 具体文件与机制见附录 D。 |

| [ourresearch/parseland](<https://github.com/ourresearch/parseland/tree/442a300a247aee1f4b8b7e75aaa2b105aee52626>) | `442a300a247aee1f4b8b7e75aaa2b105aee52626` | MIT | 具体文件与机制见附录 D。 |

| [ourresearch/parseland-eval](<https://github.com/ourresearch/parseland-eval/tree/56d7d1940312114210f537bf2f8d5e733ac8f2de>) | `56d7d1940312114210f537bf2f8d5e733ac8f2de` | 未核 | 评价实验不是parseland生产确定性PDF resolver；95/100%数字不能转述为PDF下载成功率 |

| [ropensci-archive/fulltext](<https://github.com/ropensci-archive/fulltext/tree/706a3a9d1c87a267fd7f2867544dd4cd945d6199>) | `706a3a9d1c87a267fd7f2867544dd4cd945d6199` | MIT + file LICENSE（DESCRIPTION已读） | 归档；外部pubpatterns JSON载入并按Crossref member/ISSN分发 |

| [sckott/pubpatterns](<https://github.com/sckott/pubpatterns/tree/2a342529dad052caa41776adbd45f3bda60a8b70>) | `2a342529dad052caa41776adbd45f3bda60a8b70` | 根目录未找到LICENSE；不建议复制整库 | 历史规则材料，非2026有效性证据 |

| [zotero/translators](<https://github.com/zotero/translators/tree/3fb4e794446763ac2053250112890631c428159f>) | `3fb4e794446763ac2053250112890631c428159f` | AGPL-3.0-or-later见各文件头 | 采用文件头声明为AGPL-3.0-or-later的已读文件；旧AIP.js与HighWire.js未核许可证头，仅列历史线索。 |

| [ezpaarse-project/ezpaarse-platforms](<https://github.com/ezpaarse-project/ezpaarse-platforms/tree/631980a51504b25d89881bdc5fb81591daa25015>) | `631980a51504b25d89881bdc5fb81591daa25015` | 未核（根LICENSE请求404） | 电子资源访问日志解析器，不是PDF下载器；可以证实端点识别和参数结构 |

| [IvanZhuyf3/literature-skill](<https://github.com/IvanZhuyf3/literature-skill/tree/7cf79678988527535686c852318a03508f28bb49>) | `7cf79678988527535686c852318a03508f28bb49` | 未核 | SPIEAdapter已注册；find_download_url构造proceedings DOI端点，注释给2026-06-29 CDP经验；本轮未独立复测Referer |

| [drpwchen/paper-fetch](<https://github.com/drpwchen/paper-fetch/tree/0ff462c0e81b2e90ae5ae9b378c59a54aba83659>) | `0ff462c0e81b2e90ae5ae9b378c59a54aba83659` | MIT | 访问记录常来自特定机构代理；源码核实不等于跨机构成功率 |

| [Agents365-ai/365-skills](<https://github.com/Agents365-ai/365-skills/tree/0a1679d1c9188656b104eddea9ae8d677920f13c>) | `0a1679d1c9188656b104eddea9ae8d677920f13c` | paper-fetch子插件 MIT | 只借鉴publisher-direct相关段落；不纳入非授权来源、LLM操作或版本功能 |

| [WileyLabs/tdm-client](<https://github.com/WileyLabs/tdm-client/tree/f318ce9c29de6db4139e424349dc90584fb1f06e>) | `f318ce9c29de6db4139e424349dc90584fb1f06e` | MIT | 官方客户端；header/编码/redirect可借鉴，源码错误标签和限流常量不等于服务器保证 |

| [nanoy42/nanoy.fr](<https://github.com/nanoy42/nanoy.fr/tree/6ba7d2efcdf44f24d34bdc74e5104bfe9554d36c>) | `6ba7d2efcdf44f24d34bdc74e5104bfe9554d36c` | 未核；仅引用论文PDF链接实例 | 作者论文元数据，不是下载器实现 |


Zotero 相关已读文件主要声明 AGPL-3.0-or-later；其他仓库按表中实际记录处理。运行时独立、借鉴机制和复制具体源码是不同事项；未来复制实现时须逐文件核对适用许可。


---

<a id="sources"></a>

## 附录 D：142 项来源索引

来源编号沿用研究材料。下面的读取范围、证据层次和许可状态均来自原汇编；本文件没有将搜索摘要升级为完整文档核查，也没有重新执行仓库测试。一个来源可以关联多条规则，不据此将其他文件中的函数归入当前文件。

链接优先固定 commit，并保留原材料已经提供的定位；这里的链接不是对当前远端可访问性的新增保证。


<a id="s001"></a>

### S001 · zotero/translators · Springer Link.js

固定版本源码；commit `3fb4e794446763ac2053250112890631c428159f`；许可：AGPL-3.0-or-later见各文件头；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L237-L280）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/Springer%20Link.js#L237-L280>)


<a id="s002"></a>

### S002 · drpwchen/paper-fetch · library_session.py

固定版本源码；commit `0ff462c0e81b2e90ae5ae9b378c59a54aba83659`；许可：MIT；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L237-L255）](<https://github.com/drpwchen/paper-fetch/blob/0ff462c0e81b2e90ae5ae9b378c59a54aba83659/library_session.py#L237-L255>) · [源码 2（L260-L270）](<https://github.com/drpwchen/paper-fetch/blob/0ff462c0e81b2e90ae5ae9b378c59a54aba83659/library_session.py#L260-L270>) · [源码 3（L240-L254）](<https://github.com/drpwchen/paper-fetch/blob/0ff462c0e81b2e90ae5ae9b378c59a54aba83659/library_session.py#L240-L254>) · [源码 4（L1479-L1549）](<https://github.com/drpwchen/paper-fetch/blob/0ff462c0e81b2e90ae5ae9b378c59a54aba83659/library_session.py#L1479-L1549>) · [源码 5（L2201-L2225）](<https://github.com/drpwchen/paper-fetch/blob/0ff462c0e81b2e90ae5ae9b378c59a54aba83659/library_session.py#L2201-L2225>) · [源码 6（L2201-L2275）](<https://github.com/drpwchen/paper-fetch/blob/0ff462c0e81b2e90ae5ae9b378c59a54aba83659/library_session.py#L2201-L2275>) · [源码 7（L2036-L2200）](<https://github.com/drpwchen/paper-fetch/blob/0ff462c0e81b2e90ae5ae9b378c59a54aba83659/library_session.py#L2036-L2200>) · [源码 8（L1661-L1845）](<https://github.com/drpwchen/paper-fetch/blob/0ff462c0e81b2e90ae5ae9b378c59a54aba83659/library_session.py#L1661-L1845>) · [源码 9（L277-L310）](<https://github.com/drpwchen/paper-fetch/blob/0ff462c0e81b2e90ae5ae9b378c59a54aba83659/library_session.py#L277-L310>) · [源码 10（L1683-L1845）](<https://github.com/drpwchen/paper-fetch/blob/0ff462c0e81b2e90ae5ae9b378c59a54aba83659/library_session.py#L1683-L1845>) · [源码 11（L2228-L2378）](<https://github.com/drpwchen/paper-fetch/blob/0ff462c0e81b2e90ae5ae9b378c59a54aba83659/library_session.py#L2228-L2378>)


<a id="s003"></a>

### S003 · zotero/translators · Wiley Online Library.js

固定版本源码；commit `3fb4e794446763ac2053250112890631c428159f`；许可：AGPL-3.0-or-later见各文件头；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L183-L193）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/Wiley%20Online%20Library.js#L183-L193>) · [源码 2（L345-L354）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/Wiley%20Online%20Library.js#L345-L354>)


<a id="s004"></a>

### S004 · zotero/translators · Taylor and Francis+NEJM.js

固定版本源码；commit `3fb4e794446763ac2053250112890631c428159f`；许可：AGPL-3.0-or-later见各文件头；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L192-L208）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/Taylor%20and%20Francis%2BNEJM.js#L192-L208>)


<a id="s005"></a>

### S005 · zotero/translators · SAGE Journals.js

固定版本源码；commit `3fb4e794446763ac2053250112890631c428159f`；许可：AGPL-3.0-or-later见各文件头；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L81-L93）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/SAGE%20Journals.js#L81-L93>)


<a id="s006"></a>

### S006 · zotero/translators · Annual Reviews.js

固定版本源码；commit `3fb4e794446763ac2053250112890631c428159f`；许可：AGPL-3.0-or-later见各文件头；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L35-L86）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/Annual%20Reviews.js#L35-L86>)


<a id="s007"></a>

### S007 · zotero/translators · Frontiers.js

固定版本源码；commit `3fb4e794446763ac2053250112890631c428159f`；许可：AGPL-3.0-or-later见各文件头；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L193-L222）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/Frontiers.js#L193-L222>)


<a id="s008"></a>

### S008 · zotero/translators · ACM Digital Library.js

固定版本源码；commit `3fb4e794446763ac2053250112890631c428159f`；许可：AGPL-3.0-or-later见各文件头；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L135-L202）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/ACM%20Digital%20Library.js#L135-L202>)


<a id="s009"></a>

### S009 · projecteuclid.org/journalArticle/Download

网页/官方资料；许可：不适用；原研究范围：见关联记录；不含实际授权下载验证。

[资料](<https://projecteuclid.org/journalArticle/Download?urlId=10.1214%2F25-AAP2226>)


<a id="s010"></a>

### S010 · projecteuclid.org/journalArticle/Download

网页/官方资料；许可：不适用；原研究范围：见关联记录；不含实际授权下载验证。

[资料](<https://projecteuclid.org/journalArticle/Download?urlId=10.1214%2F24-AOAS1990>)


<a id="s011"></a>

### S011 · projecteuclid.org/journalArticle/Download

网页/官方资料；许可：不适用；原研究范围：见关联记录；不含实际授权下载验证。

[资料](<https://projecteuclid.org/journalArticle/Download?urlId=10.1214%2F24-BA1503>)


<a id="s012"></a>

### S012 · projecteuclid.org/journalArticle/Download

网页/官方资料；许可：不适用；原研究范围：见关联记录；不含实际授权下载验证。

[资料](<https://projecteuclid.org/journalArticle/Download?urlId=10.4310%2FACTA.2025.v234.n1.a1>)


<a id="s013"></a>

### S013 · ezpaarse-project/ezpaarse-platforms · pe/parser.js

固定版本源码；commit `631980a51504b25d89881bdc5fb81591daa25015`；许可：未核（根LICENSE请求404）；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L72-L86）](<https://github.com/ezpaarse-project/ezpaarse-platforms/blob/631980a51504b25d89881bdc5fb81591daa25015/pe/parser.js#L72-L86>)


<a id="s014"></a>

### S014 · ezpaarse-project/ezpaarse-platforms · pe/test/pe.2021-06-06.csv

固定版本源码；commit `631980a51504b25d89881bdc5fb81591daa25015`；许可：未核（根LICENSE请求404）；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L1-L15）](<https://github.com/ezpaarse-project/ezpaarse-platforms/blob/631980a51504b25d89881bdc5fb81591daa25015/pe/test/pe.2021-06-06.csv#L1-L15>)


<a id="s015"></a>

### S015 · zotero/translators · Euclid.js

固定版本源码；commit `3fb4e794446763ac2053250112890631c428159f`；许可：AGPL-3.0-or-later见各文件头；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L49-L93）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/Euclid.js#L49-L93>)


<a id="s016"></a>

### S016 · zotero/translators · American Institute of Aeronautics and Astronautics.js

固定版本源码；commit `3fb4e794446763ac2053250112890631c428159f`；许可：AGPL-3.0-or-later见各文件头；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L80-L111）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/American%20Institute%20of%20Aeronautics%20and%20Astronautics.js#L80-L111>)


<a id="s017"></a>

### S017 · ourresearch/parseland · find_pdf.py

固定版本源码；commit `442a300a247aee1f4b8b7e75aaa2b105aee52626`；许可：MIT；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L369-L370）](<https://github.com/ourresearch/parseland/blob/442a300a247aee1f4b8b7e75aaa2b105aee52626/find_pdf.py#L369-L370>) · [源码 2（L411-L415）](<https://github.com/ourresearch/parseland/blob/442a300a247aee1f4b8b7e75aaa2b105aee52626/find_pdf.py#L411-L415>) · [源码 3（L353-L354）](<https://github.com/ourresearch/parseland/blob/442a300a247aee1f4b8b7e75aaa2b105aee52626/find_pdf.py#L353-L354>) · [源码 4（L357-L358）](<https://github.com/ourresearch/parseland/blob/442a300a247aee1f4b8b7e75aaa2b105aee52626/find_pdf.py#L357-L358>) · [源码 5（L386-L387）](<https://github.com/ourresearch/parseland/blob/442a300a247aee1f4b8b7e75aaa2b105aee52626/find_pdf.py#L386-L387>) · [源码 6（L348-L350）](<https://github.com/ourresearch/parseland/blob/442a300a247aee1f4b8b7e75aaa2b105aee52626/find_pdf.py#L348-L350>)


<a id="s018"></a>

### S018 · ourresearch/parseland · views.py

固定版本源码；commit `442a300a247aee1f4b8b7e75aaa2b105aee52626`；许可：MIT；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L138-L169）](<https://github.com/ourresearch/parseland/blob/442a300a247aee1f4b8b7e75aaa2b105aee52626/views.py#L138-L169>)


<a id="s019"></a>

### S019 · www.spiedigitallibrary.org/journalArticle/Download

网页/官方资料；许可：不适用；原研究范围：见关联记录；不含实际授权下载验证。

[资料](<https://www.spiedigitallibrary.org/journalArticle/Download?urlId=10.1117%2F1.AP.8.1.016009>)


<a id="s020"></a>

### S020 · nanoy42/nanoy.fr · content/publication/chip-flm/index.md

固定版本源码；commit `6ba7d2efcdf44f24d34bdc74e5104bfe9554d36c`；许可：未核；仅引用论文PDF链接实例；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/nanoy42/nanoy.fr/blob/6ba7d2efcdf44f24d34bdc74e5104bfe9554d36c/content/publication/chip-flm/index.md>)


<a id="s021"></a>

### S021 · ezpaarse-project/ezpaarse-platforms · sdl/parser.js

固定版本源码；commit `631980a51504b25d89881bdc5fb81591daa25015`；许可：未核（根LICENSE请求404）；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L22-L31）](<https://github.com/ezpaarse-project/ezpaarse-platforms/blob/631980a51504b25d89881bdc5fb81591daa25015/sdl/parser.js#L22-L31>)


<a id="s022"></a>

### S022 · ezpaarse-project/ezpaarse-platforms · sdl/test/sdl.2019-09-09.csv

固定版本源码；commit `631980a51504b25d89881bdc5fb81591daa25015`；许可：未核（根LICENSE请求404）；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/ezpaarse-project/ezpaarse-platforms/blob/631980a51504b25d89881bdc5fb81591daa25015/sdl/test/sdl.2019-09-09.csv>)


<a id="s023"></a>

### S023 · IvanZhuyf3/literature-skill · publisher/spie.py

固定版本源码；commit `7cf79678988527535686c852318a03508f28bb49`；许可：未核；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L68-L99）](<https://github.com/IvanZhuyf3/literature-skill/blob/7cf79678988527535686c852318a03508f28bb49/publisher/spie.py#L68-L99>)


<a id="s024"></a>

### S024 · IvanZhuyf3/literature-skill · lit/download/engine.py

固定版本源码；commit `7cf79678988527535686c852318a03508f28bb49`；许可：未核；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L55-L116）](<https://github.com/IvanZhuyf3/literature-skill/blob/7cf79678988527535686c852318a03508f28bb49/lit/download/engine.py#L55-L116>)


<a id="s025"></a>

### S025 · Agents365-ai/365-skills · plugins/paper-fetch/skills/paper-fetch/scripts/fetch.py

固定版本源码；commit `0a1679d1c9188656b104eddea9ae8d677920f13c`；许可：paper-fetch子插件 MIT；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L956-L974）](<https://github.com/Agents365-ai/365-skills/blob/0a1679d1c9188656b104eddea9ae8d677920f13c/plugins/paper-fetch/skills/paper-fetch/scripts/fetch.py#L956-L974>) · [源码 2（L1042-L1064）](<https://github.com/Agents365-ai/365-skills/blob/0a1679d1c9188656b104eddea9ae8d677920f13c/plugins/paper-fetch/skills/paper-fetch/scripts/fetch.py#L1042-L1064>) · [源码 3（L978-L1039）](<https://github.com/Agents365-ai/365-skills/blob/0a1679d1c9188656b104eddea9ae8d677920f13c/plugins/paper-fetch/skills/paper-fetch/scripts/fetch.py#L978-L1039>)


<a id="s026"></a>

### S026 · zotero/translators · Atypon Journals.js

固定版本源码；commit `3fb4e794446763ac2053250112890631c428159f`；许可：AGPL-3.0-or-later见各文件头；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L188-L210）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/Atypon%20Journals.js#L188-L210>) · [源码 2（L191-L208）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/Atypon%20Journals.js#L191-L208>)


<a id="s027"></a>

### S027 · PLOS Text and Data Mining

网页/官方资料；许可：不适用；原研究范围：官方文档已读。

[资料](<https://api.plos.org/text-and-data-mining.html>)


<a id="s028"></a>

### S028 · vict0rsch/PaperMemory · src/shared/js/utils/sources/oup.js

固定版本源码；commit `d6bbea7375cfe64b99d3cf9a62d70244d09a7693`；许可：MIT（LICENSE版权占位符未填）；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L22-L37）](<https://github.com/vict0rsch/PaperMemory/blob/d6bbea7375cfe64b99d3cf9a62d70244d09a7693/src/shared/js/utils/sources/oup.js#L22-L37>)


<a id="s029"></a>

### S029 · zotero/translators · Silverchair.js

固定版本源码；commit `3fb4e794446763ac2053250112890631c428159f`；许可：AGPL-3.0-or-later见各文件头；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L144-L199）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/Silverchair.js#L144-L199>) · [源码 2（L144-L200）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/Silverchair.js#L144-L200>) · [源码 3（L93-L115）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/Silverchair.js#L93-L115>) · [源码 4（L93-L165）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/Silverchair.js#L93-L165>)


<a id="s030"></a>

### S030 · zotero/translators · Taylor & Francis eBooks.js

固定版本源码；commit `3fb4e794446763ac2053250112890631c428159f`；许可：AGPL-3.0-or-later见各文件头；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L139-L181）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/Taylor%20%26%20Francis%20eBooks.js#L139-L181>)


<a id="s031"></a>

### S031 · JabRef/jabref · jablib/src/main/java/org/jabref/logic/importer/WebFetchers.java

固定版本源码；commit `d79f1490aaafa9bc80da760d1baa6497cebf7c01`；许可：MIT；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L275-L304）](<https://github.com/JabRef/jabref/blob/d79f1490aaafa9bc80da760d1baa6497cebf7c01/jablib/src/main/java/org/jabref/logic/importer/WebFetchers.java#L275-L304>)


<a id="s032"></a>

### S032 · vict0rsch/PaperMemory · src/shared/js/utils/sources/cell.js

固定版本源码；commit `d6bbea7375cfe64b99d3cf9a62d70244d09a7693`；许可：MIT（LICENSE版权占位符未填）；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L6-L75）](<https://github.com/vict0rsch/PaperMemory/blob/d6bbea7375cfe64b99d3cf9a62d70244d09a7693/src/shared/js/utils/sources/cell.js#L6-L75>)


<a id="s033"></a>

### S033 · zotero/translators · ScienceDirect.js

固定版本源码；commit `3fb4e794446763ac2053250112890631c428159f`；许可：AGPL-3.0-or-later见各文件头；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L69-L200）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/ScienceDirect.js#L69-L200>) · [源码 2（L176-L200）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/ScienceDirect.js#L176-L200>)


<a id="s034"></a>

### S034 · zotero/translators · IEEE Xplore.js

固定版本源码；commit `3fb4e794446763ac2053250112890631c428159f`；许可：AGPL-3.0-or-later见各文件头；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L166-L184）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/IEEE%20Xplore.js#L166-L184>)


<a id="s035"></a>

### S035 · IEEE Search Parameters

网页/官方资料；许可：不适用；原研究范围：官方文档已读。

[资料](<https://developer.ieee.org/docs/read/Metadata_API_details>)


<a id="s036"></a>

### S036 · IEEE Data Fields Returned

网页/官方资料；许可：不适用；原研究范围：官方文档已读。

[资料](<https://developer.ieee.org/docs/read/Metadata_API_responses>)


<a id="s037"></a>

### S037 · drpwchen/paper-fetch · paper_fetch.py

固定版本源码；commit `0ff462c0e81b2e90ae5ae9b378c59a54aba83659`；许可：MIT；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L519-L566）](<https://github.com/drpwchen/paper-fetch/blob/0ff462c0e81b2e90ae5ae9b378c59a54aba83659/paper_fetch.py#L519-L566>) · [源码 2（L487-L516）](<https://github.com/drpwchen/paper-fetch/blob/0ff462c0e81b2e90ae5ae9b378c59a54aba83659/paper_fetch.py#L487-L516>)


<a id="s038"></a>

### S038 · zotero/translators · MDPI Journals.js

固定版本源码；commit `3fb4e794446763ac2053250112890631c428159f`；许可：AGPL-3.0-or-later见各文件头；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L122-L150）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/MDPI%20Journals.js#L122-L150>) · [源码 2（L79-L104）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/MDPI%20Journals.js#L79-L104>)


<a id="s039"></a>

### S039 · zotero/translators · Nature Publishing Group.js

固定版本源码；commit `3fb4e794446763ac2053250112890631c428159f`；许可：AGPL-3.0-or-later见各文件头；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L268-L275）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/Nature%20Publishing%20Group.js#L268-L275>) · [源码 2（L687-L705）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/Nature%20Publishing%20Group.js#L687-L705>) · [源码 3（L1143-L1210）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/Nature%20Publishing%20Group.js#L1143-L1210>)


<a id="s040"></a>

### S040 · zotero/translators · Institute of Physics.js

固定版本源码；commit `3fb4e794446763ac2053250112890631c428159f`；许可：AGPL-3.0-or-later见各文件头；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L72-L97）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/Institute%20of%20Physics.js#L72-L97>)


<a id="s041"></a>

### S041 · zotero/translators · APS.js

固定版本源码；commit `3fb4e794446763ac2053250112890631c428159f`；许可：AGPL-3.0-or-later见各文件头；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L104-L145）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/APS.js#L104-L145>)


<a id="s042"></a>

### S042 · vict0rsch/PaperMemory · src/shared/js/utils/sources/jmlr.js

固定版本源码；commit `d6bbea7375cfe64b99d3cf9a62d70244d09a7693`；许可：MIT（LICENSE版权占位符未填）；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L21-L38）](<https://github.com/vict0rsch/PaperMemory/blob/d6bbea7375cfe64b99d3cf9a62d70244d09a7693/src/shared/js/utils/sources/jmlr.js#L21-L38>)


<a id="s043"></a>

### S043 · vict0rsch/PaperMemory · src/shared/js/utils/sources/pmlr.js

固定版本源码；commit `d6bbea7375cfe64b99d3cf9a62d70244d09a7693`；许可：MIT（LICENSE版权占位符未填）；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L41-L49）](<https://github.com/vict0rsch/PaperMemory/blob/d6bbea7375cfe64b99d3cf9a62d70244d09a7693/src/shared/js/utils/sources/pmlr.js#L41-L49>)


<a id="s044"></a>

### S044 · zotero/translators · BioMed Central.js

固定版本源码；commit `3fb4e794446763ac2053250112890631c428159f`；许可：AGPL-3.0-or-later见各文件头；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L85-L119）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/BioMed%20Central.js#L85-L119>)


<a id="s045"></a>

### S045 · zotero/translators · RSC Publishing.js

固定版本源码；commit `3fb4e794446763ac2053250112890631c428159f`；许可：AGPL-3.0-or-later见各文件头；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L65-L98）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/RSC%20Publishing.js#L65-L98>)


<a id="s046"></a>

### S046 · zotero/translators · PLoS Journals.js

固定版本源码；commit `3fb4e794446763ac2053250112890631c428159f`；许可：AGPL-3.0-or-later见各文件头；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L84-L98）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/PLoS%20Journals.js#L84-L98>)


<a id="s047"></a>

### S047 · zotero/translators · Copernicus.js

固定版本源码；commit `3fb4e794446763ac2053250112890631c428159f`；许可：AGPL-3.0-or-later见各文件头；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L65-L104）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/Copernicus.js#L65-L104>)


<a id="s048"></a>

### S048 · zotero/translators · Cambridge Core.js

固定版本源码；commit `3fb4e794446763ac2053250112890631c428159f`；许可：AGPL-3.0-or-later见各文件头；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L99-L179）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/Cambridge%20Core.js#L99-L179>) · [源码 2（L99-L175）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/Cambridge%20Core.js#L99-L175>)


<a id="s049"></a>

### S049 · zotero/translators · HighWire 2.0.js

固定版本源码；commit `3fb4e794446763ac2053250112890631c428159f`；许可：AGPL-3.0-or-later见各文件头；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L286-L382）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/HighWire%202.0.js#L286-L382>) · [源码 2（L286-L440）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/HighWire%202.0.js#L286-L440>)


<a id="s050"></a>

### S050 · zotero/translators · Optical Society of America.js

固定版本源码；commit `3fb4e794446763ac2053250112890631c428159f`；许可：AGPL-3.0-or-later见各文件头；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L93-L149）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/Optical%20Society%20of%20America.js#L93-L149>)


<a id="s051"></a>

### S051 · zotero/translators · De Gruyter Brill.js

固定版本源码；commit `3fb4e794446763ac2053250112890631c428159f`；许可：AGPL-3.0-or-later见各文件头；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L95-L128）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/De%20Gruyter%20Brill.js#L95-L128>)


<a id="s052"></a>

### S052 · zotero/translators · Emerald Insight.js

固定版本源码；commit `3fb4e794446763ac2053250112890631c428159f`；许可：AGPL-3.0-or-later见各文件头；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L93-L145）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/Emerald%20Insight.js#L93-L145>) · [源码 2（L93-L144）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/Emerald%20Insight.js#L93-L144>)


<a id="s053"></a>

### S053 · zotero/translators · Brill.js

固定版本源码；commit `3fb4e794446763ac2053250112890631c428159f`；许可：AGPL-3.0-or-later见各文件头；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L90-L172）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/Brill.js#L90-L172>)


<a id="s054"></a>

### S054 · zotero/translators · eLife.js

固定版本源码；commit `3fb4e794446763ac2053250112890631c428159f`；许可：AGPL-3.0-or-later见各文件头；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L81-L100）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/eLife.js#L81-L100>)


<a id="s055"></a>

### S055 · zotero/translators · Thieme.js

固定版本源码；commit `3fb4e794446763ac2053250112890631c428159f`；许可：AGPL-3.0-or-later见各文件头；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L94-L135）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/Thieme.js#L94-L135>) · [源码 2（L94-L123）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/Thieme.js#L94-L123>)


<a id="s056"></a>

### S056 · zotero/translators · Microbiology Society Journals.js

固定版本源码；commit `3fb4e794446763ac2053250112890631c428159f`；许可：AGPL-3.0-or-later见各文件头；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L82-L115）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/Microbiology%20Society%20Journals.js#L82-L115>)


<a id="s057"></a>

### S057 · zotero/translators · Hindawi Publishers.js

固定版本源码；commit `3fb4e794446763ac2053250112890631c428159f`；许可：AGPL-3.0-or-later见各文件头；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L73-L99）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/Hindawi%20Publishers.js#L73-L99>)


<a id="s058"></a>

### S058 · zotero/translators · Cell Press.js

固定版本源码；commit `3fb4e794446763ac2053250112890631c428159f`；许可：AGPL-3.0-or-later见各文件头；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L90-L125）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/Cell%20Press.js#L90-L125>)


<a id="s059"></a>

### S059 · zotero/translators · BioOne.js

固定版本源码；commit `3fb4e794446763ac2053250112890631c428159f`；许可：AGPL-3.0-or-later见各文件头；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L85-L108）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/BioOne.js#L85-L108>)


<a id="s060"></a>

### S060 · sckott/pubpatterns · src/spie.json

固定版本源码；commit `2a342529dad052caa41776adbd45f3bda60a8b70`；许可：根目录未找到LICENSE；不建议复制整库；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/sckott/pubpatterns/blob/2a342529dad052caa41776adbd45f3bda60a8b70/src/spie.json>)


<a id="s061"></a>

### S061 · sckott/pubpatterns · src/pensoft.json

固定版本源码；commit `2a342529dad052caa41776adbd45f3bda60a8b70`；许可：根目录未找到LICENSE；不建议复制整库；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/sckott/pubpatterns/blob/2a342529dad052caa41776adbd45f3bda60a8b70/src/pensoft.json>)


<a id="s062"></a>

### S062 · ropensci-archive/fulltext · R/ftdoi_publisher_plugins.R

固定版本源码；commit `706a3a9d1c87a267fd7f2867544dd4cd945d6199`；许可：MIT + file LICENSE（DESCRIPTION已读）；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L1-L8）](<https://github.com/ropensci-archive/fulltext/blob/706a3a9d1c87a267fd7f2867544dd4cd945d6199/R/ftdoi_publisher_plugins.R#L1-L8>)


<a id="s063"></a>

### S063 · sckott/pubpatterns · src/peerj.json

固定版本源码；commit `2a342529dad052caa41776adbd45f3bda60a8b70`；许可：根目录未找到LICENSE；不建议复制整库；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/sckott/pubpatterns/blob/2a342529dad052caa41776adbd45f3bda60a8b70/src/peerj.json>)


<a id="s064"></a>

### S064 · sckott/pubpatterns · src/thieme.json

固定版本源码；commit `2a342529dad052caa41776adbd45f3bda60a8b70`；许可：根目录未找到LICENSE；不建议复制整库；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/sckott/pubpatterns/blob/2a342529dad052caa41776adbd45f3bda60a8b70/src/thieme.json>)


<a id="s065"></a>

### S065 · sckott/pubpatterns · src/transtech.json

固定版本源码；commit `2a342529dad052caa41776adbd45f3bda60a8b70`；许可：根目录未找到LICENSE；不建议复制整库；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/sckott/pubpatterns/blob/2a342529dad052caa41776adbd45f3bda60a8b70/src/transtech.json>)


<a id="s066"></a>

### S066 · sckott/pubpatterns · src/cambridge.json

固定版本源码；commit `2a342529dad052caa41776adbd45f3bda60a8b70`；许可：根目录未找到LICENSE；不建议复制整库；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/sckott/pubpatterns/blob/2a342529dad052caa41776adbd45f3bda60a8b70/src/cambridge.json>)


<a id="s067"></a>

### S067 · pubs.acs.org/page/platform-transition-plans

网页/官方资料；许可：不适用；原研究范围：见关联记录；不含实际授权下载验证。

[资料](<https://pubs.acs.org/page/platform-transition-plans>)


<a id="s068"></a>

### S068 · DOI Resolution Documentation

网页/官方资料；许可：不适用；原研究范围：官方文档已读。

[资料](<https://www.doi.org/the-identifier/resources/factsheets/doi-resolution-documentation>)


<a id="s069"></a>

### S069 · DOI Resolution Documentation

网页/官方资料；许可：不适用；原研究范围：官方文档已读。

[资料](<https://doi.org/help.html>)


<a id="s070"></a>

### S070 · WileyLabs/tdm-client · src/wiley_tdm/tdm_client.py

固定版本源码；commit `f318ce9c29de6db4139e424349dc90584fb1f06e`；许可：MIT；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L316-L383）](<https://github.com/WileyLabs/tdm-client/blob/f318ce9c29de6db4139e424349dc90584fb1f06e/src/wiley_tdm/tdm_client.py#L316-L383>) · [源码 2（L316-L350）](<https://github.com/WileyLabs/tdm-client/blob/f318ce9c29de6db4139e424349dc90584fb1f06e/src/wiley_tdm/tdm_client.py#L316-L350>)


<a id="s071"></a>

### S071 · WileyLabs/tdm-client · src/wiley_tdm/doi_utils.py

固定版本源码；commit `f318ce9c29de6db4139e424349dc90584fb1f06e`；许可：MIT；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/WileyLabs/tdm-client/blob/f318ce9c29de6db4139e424349dc90584fb1f06e/src/wiley_tdm/doi_utils.py>)


<a id="s072"></a>

### S072 · WileyLabs/tdm-client · tests/test_tdm_client.py

固定版本源码；commit `f318ce9c29de6db4139e424349dc90584fb1f06e`；许可：MIT；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/WileyLabs/tdm-client/blob/f318ce9c29de6db4139e424349dc90584fb1f06e/tests/test_tdm_client.py>)


<a id="s073"></a>

### S073 · WileyLabs/tdm-client · LICENSE

固定版本源码；commit `f318ce9c29de6db4139e424349dc90584fb1f06e`；许可：MIT；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/WileyLabs/tdm-client/blob/f318ce9c29de6db4139e424349dc90584fb1f06e/LICENSE>)


<a id="s074"></a>

### S074 · Crossref Accessing full texts

网页/官方资料；许可：不适用；原研究范围：官方文档已读。

[资料](<https://www.crossref.org/documentation/retrieve-metadata/text-and-data-mining/>)


<a id="s075"></a>

### S075 · Crossref REST API filters

网页/官方资料；许可：不适用；原研究范围：官方文档已读。

[资料](<https://www.crossref.org/documentation/retrieve-metadata/rest-api/rest-api-filters/>)


<a id="s076"></a>

### S076 · Crossref Article numbers or IDs

网页/官方资料；许可：不适用；原研究范围：官方文档已读。

[资料](<https://www.crossref.org/documentation/schema-library/markup-guide-metadata-segments/article-ids/>)


<a id="s077"></a>

### S077 · IEEE Interactive Documentation

网页/官方资料；许可：不适用；原研究范围：官方文档已读。

[资料](<https://developer.ieee.org/io-docs>)


<a id="s078"></a>

### S078 · IEEE API Query Basics

网页/官方资料；许可：不适用；原研究范围：官方文档已读。

[资料](<https://developer.ieee.org/docs/read/Searching_the_IEEE_Xplore_Metadata_API>)


<a id="s079"></a>

### S079 · Elsevier Article Retrieval API

网页/官方资料；许可：不适用；原研究范围：官方文档已读。

[资料](<https://dev.elsevier.com/documentation/FullTextRetrievalAPI.wadl>)


<a id="s080"></a>

### S080 · Elsevier Text Mining technical guide

网页/官方资料；许可：不适用；原研究范围：官方文档已读。

[资料](<https://dev.elsevier.com/tecdoc_text_mining.html>)


<a id="s081"></a>

### S081 · Elsevier API format overview

网页/官方资料；许可：不适用；原研究范围：官方搜索结果。

[资料](<https://dev.elsevier.com/sd_api_spec.html>)


<a id="s082"></a>

### S082 · Wiley Text and Data Mining

网页/官方资料；许可：不适用；原研究范围：官方文档已读。

[资料](<https://onlinelibrary.wiley.com/library-info/resources/text-and-datamining>)


<a id="s083"></a>

### S083 · APS Harvest API

网页/官方资料；许可：不适用；原研究范围：官方文档已读。

[资料](<https://harvest.aps.org/docs/harvest-api>)


<a id="s084"></a>

### S084 · Springer Making First API Call

网页/官方资料；许可：不适用；原研究范围：官方搜索索引摘录，正文页面未读全。

[资料](<https://dev.springernature.com/docs/quick-start/making-first-api-call/>)


<a id="s085"></a>

### S085 · Springer Open Access API

网页/官方资料；许可：不适用；原研究范围：官方搜索索引摘录，正文页面未读全。

[资料](<https://dev.springernature.com/docs/api-endpoints/open-access/>)


<a id="s086"></a>

### S086 · Springer Full Text API

网页/官方资料；许可：不适用；原研究范围：官方搜索索引摘录，正文页面未读全。

[资料](<https://dev.springernature.com/docs/api-endpoints/fulltext-api/>)


<a id="s087"></a>

### S087 · Cambridge Text and data mining

网页/官方资料；许可：不适用；原研究范围：官方文档已读。

[资料](<https://www.cambridge.org/core/services/open-research/text-and-data-mining>)


<a id="s088"></a>

### S088 · JSTOR Working with Bibliographic Metadata

网页/官方资料；许可：不适用；原研究范围：官方文档已读。

[资料](<https://support.jstor.org/hc/en-us/articles/32485272590487-JSTOR-Text-Analysis-Support-Working-with-JSTOR-Bibliographic-Metadata>)


<a id="s089"></a>

### S089 · JSTOR stable URL guidance

网页/官方资料；许可：不适用；原研究范围：官方搜索结果。

[资料](<https://support.jstor.org/hc/en-us/articles/115004872507-Citation-Management-Permanently-Linking-to-Content-on-JSTOR>)


<a id="s090"></a>

### S090 · JSTOR Troubleshooting PDF Errors

网页/官方资料；许可：不适用；原研究范围：官方搜索结果。

[资料](<https://support.jstor.org/hc/en-us/articles/115004798167-Troubleshooting-PDF-Errors>)


<a id="s091"></a>

### S091 · IOP Text and Data Mining policy

网页/官方资料；许可：不适用；原研究范围：官方搜索结果。

[资料](<https://ioppublishing.org/legal/textanddataminingpolicy/>)


<a id="s092"></a>

### S092 · RSC AI and TDM applications

网页/官方资料；许可：不适用；原研究范围：官方搜索结果。

[资料](<https://www.rsc.org/publishing/product-information/product-catalogue/text-and-data-mining>)


<a id="s093"></a>

### S093 · OUP official article-PDF example

网页/官方资料；许可：不适用；原研究范围：official_url_example。

[资料](<https://academic.oup.com/library/article-pdf/24/2/235/51334421/fpad019.pdf>)


<a id="s094"></a>

### S094 · zotero/translators · JSTOR.js

固定版本源码；commit `3fb4e794446763ac2053250112890631c428159f`；许可：AGPL-3.0-or-later见各文件头；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L195-L220）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/JSTOR.js#L195-L220>)


<a id="s095"></a>

### S095 · zotero/translators · Embedded Metadata.js

固定版本源码；commit `3fb4e794446763ac2053250112890631c428159f`；许可：AGPL-3.0-or-later见各文件头；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1（L527-L545）](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/Embedded%20Metadata.js#L527-L545>)


<a id="s096"></a>

### S096 · jonatasgrosman/findpapers · findpapers/runners/download_runner.py

固定版本源码；commit `3b42b66befa0a64416258e7481201a0253f09e73`；许可：MIT；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/jonatasgrosman/findpapers/blob/3b42b66befa0a64416258e7481201a0253f09e73/findpapers/runners/download_runner.py>)


<a id="s097"></a>

### S097 · drpwchen/paper-fetch · tests/test_landing_routes.py

固定版本源码；commit `0ff462c0e81b2e90ae5ae9b378c59a54aba83659`；许可：MIT；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/drpwchen/paper-fetch/blob/0ff462c0e81b2e90ae5ae9b378c59a54aba83659/tests/test_landing_routes.py>)


<a id="s098"></a>

### S098 · Cambridge official PDF example

网页/官方资料；许可：不适用；原研究范围：official_url_example。

[资料](<https://www.cambridge.org/core/services/aop-cambridge-core/content/view/66E9D20EBB3B08E35C48F2F35DF4780B/S1537592724002755a.pdf/methodologies_of_informed_intuition_the_role_of_informed_intuition_and_intuitive_openness.pdf>)


<a id="s099"></a>

### S099 · zotero/translators · APS-Physics.js

固定版本源码；commit `3fb4e794446763ac2053250112890631c428159f`；许可：AGPL-3.0-or-later见各文件头；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/APS-Physics.js>)


<a id="s100"></a>

### S100 · zotero/translators · AIP.js

固定版本源码；commit `3fb4e794446763ac2053250112890631c428159f`；许可：AGPL-3.0-or-later见各文件头；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/AIP.js>)


<a id="s101"></a>

### S101 · zotero/translators · HighWire.js

固定版本源码；commit `3fb4e794446763ac2053250112890631c428159f`；许可：AGPL-3.0-or-later见各文件头；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/HighWire.js>)


<a id="s102"></a>

### S102 · zotero/translators · IEEE Computer Society.js

固定版本源码；commit `3fb4e794446763ac2053250112890631c428159f`；许可：AGPL-3.0-or-later见各文件头；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/IEEE%20Computer%20Society.js>)


<a id="s103"></a>

### S103 · zotero/translators · Elsevier Health Journals.js

固定版本源码；commit `3fb4e794446763ac2053250112890631c428159f`；许可：AGPL-3.0-or-later见各文件头；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/Elsevier%20Health%20Journals.js>)


<a id="s104"></a>

### S104 · zotero/translators · Oxford University Press.js

固定版本源码；commit `3fb4e794446763ac2053250112890631c428159f`；许可：AGPL-3.0-or-later见各文件头；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/zotero/translators/blob/3fb4e794446763ac2053250112890631c428159f/Oxford%20University%20Press.js>)


<a id="s105"></a>

### S105 · JabRef/jabref · jablib/src/main/java/org/jabref/logic/importer/FulltextFetcher.java

固定版本源码；commit `d79f1490aaafa9bc80da760d1baa6497cebf7c01`；许可：MIT；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/JabRef/jabref/blob/d79f1490aaafa9bc80da760d1baa6497cebf7c01/jablib/src/main/java/org/jabref/logic/importer/FulltextFetcher.java>)


<a id="s106"></a>

### S106 · JabRef/jabref · jablib/src/main/java/org/jabref/logic/importer/fetcher/DoiResolution.java

固定版本源码；commit `d79f1490aaafa9bc80da760d1baa6497cebf7c01`；许可：MIT；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/JabRef/jabref/blob/d79f1490aaafa9bc80da760d1baa6497cebf7c01/jablib/src/main/java/org/jabref/logic/importer/fetcher/DoiResolution.java>)


<a id="s107"></a>

### S107 · JabRef/jabref · jablib/src/main/java/org/jabref/logic/importer/fetcher/ACS.java

固定版本源码；commit `d79f1490aaafa9bc80da760d1baa6497cebf7c01`；许可：MIT；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/JabRef/jabref/blob/d79f1490aaafa9bc80da760d1baa6497cebf7c01/jablib/src/main/java/org/jabref/logic/importer/fetcher/ACS.java>)


<a id="s108"></a>

### S108 · JabRef/jabref · jablib/src/main/java/org/jabref/logic/importer/fetcher/ApsFetcher.java

固定版本源码；commit `d79f1490aaafa9bc80da760d1baa6497cebf7c01`；许可：MIT；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/JabRef/jabref/blob/d79f1490aaafa9bc80da760d1baa6497cebf7c01/jablib/src/main/java/org/jabref/logic/importer/fetcher/ApsFetcher.java>)


<a id="s109"></a>

### S109 · JabRef/jabref · jablib/src/main/java/org/jabref/logic/importer/fetcher/ScienceDirect.java

固定版本源码；commit `d79f1490aaafa9bc80da760d1baa6497cebf7c01`；许可：MIT；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/JabRef/jabref/blob/d79f1490aaafa9bc80da760d1baa6497cebf7c01/jablib/src/main/java/org/jabref/logic/importer/fetcher/ScienceDirect.java>)


<a id="s110"></a>

### S110 · JabRef/jabref · jablib/src/main/java/org/jabref/logic/importer/fetcher/SpringerNatureFullTextFetcher.java

固定版本源码；commit `d79f1490aaafa9bc80da760d1baa6497cebf7c01`；许可：MIT；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/JabRef/jabref/blob/d79f1490aaafa9bc80da760d1baa6497cebf7c01/jablib/src/main/java/org/jabref/logic/importer/fetcher/SpringerNatureFullTextFetcher.java>)


<a id="s111"></a>

### S111 · JabRef/jabref · jablib/src/main/java/org/jabref/logic/importer/fetcher/WileyFetcher.java

固定版本源码；commit `d79f1490aaafa9bc80da760d1baa6497cebf7c01`；许可：MIT；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/JabRef/jabref/blob/d79f1490aaafa9bc80da760d1baa6497cebf7c01/jablib/src/main/java/org/jabref/logic/importer/fetcher/WileyFetcher.java>)


<a id="s112"></a>

### S112 · JabRef/jabref · jablib/src/main/java/org/jabref/logic/importer/fetcher/JstorFetcher.java

固定版本源码；commit `d79f1490aaafa9bc80da760d1baa6497cebf7c01`；许可：MIT；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/JabRef/jabref/blob/d79f1490aaafa9bc80da760d1baa6497cebf7c01/jablib/src/main/java/org/jabref/logic/importer/fetcher/JstorFetcher.java>)


<a id="s113"></a>

### S113 · Future-Scholars/paperlib-entry-scrape-extension · src/scrapers/webcontent-embed-entry-scraper.ts

固定版本源码；commit `f3ea1065fe6d9b82f081f170432b98a819171150`；许可：本仓库根目录及package.json未找到项目代码许可证；字体许可证不能代表项目许可；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/Future-Scholars/paperlib-entry-scrape-extension/blob/f3ea1065fe6d9b82f081f170432b98a819171150/src/scrapers/webcontent-embed-entry-scraper.ts>)


<a id="s114"></a>

### S114 · Future-Scholars/paperlib-entry-scrape-extension · src/scrapers/webcontent-pdfurl-entry-scraper.ts

固定版本源码；commit `f3ea1065fe6d9b82f081f170432b98a819171150`；许可：本仓库根目录及package.json未找到项目代码许可证；字体许可证不能代表项目许可；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/Future-Scholars/paperlib-entry-scrape-extension/blob/f3ea1065fe6d9b82f081f170432b98a819171150/src/scrapers/webcontent-pdfurl-entry-scraper.ts>)


<a id="s115"></a>

### S115 · Future-Scholars/paperlib-entry-scrape-extension · src/services/entry-scrape-service.ts

固定版本源码；commit `f3ea1065fe6d9b82f081f170432b98a819171150`；许可：本仓库根目录及package.json未找到项目代码许可证；字体许可证不能代表项目许可；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/Future-Scholars/paperlib-entry-scrape-extension/blob/f3ea1065fe6d9b82f081f170432b98a819171150/src/services/entry-scrape-service.ts>)


<a id="s116"></a>

### S116 · vict0rsch/PaperMemory · src/shared/js/utils/sources/index.js

固定版本源码；commit `d6bbea7375cfe64b99d3cf9a62d70244d09a7693`；许可：MIT（LICENSE版权占位符未填）；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/vict0rsch/PaperMemory/blob/d6bbea7375cfe64b99d3cf9a62d70244d09a7693/src/shared/js/utils/sources/index.js>)


<a id="s117"></a>

### S117 · vict0rsch/PaperMemory · src/shared/js/utils/sources/pmc.js

固定版本源码；commit `d6bbea7375cfe64b99d3cf9a62d70244d09a7693`；许可：MIT（LICENSE版权占位符未填）；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/vict0rsch/PaperMemory/blob/d6bbea7375cfe64b99d3cf9a62d70244d09a7693/src/shared/js/utils/sources/pmc.js>)


<a id="s118"></a>

### S118 · vict0rsch/PaperMemory · src/shared/js/utils/sources/pnas.js

固定版本源码；commit `d6bbea7375cfe64b99d3cf9a62d70244d09a7693`；许可：MIT（LICENSE版权占位符未填）；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/vict0rsch/PaperMemory/blob/d6bbea7375cfe64b99d3cf9a62d70244d09a7693/src/shared/js/utils/sources/pnas.js>)


<a id="s119"></a>

### S119 · vict0rsch/PaperMemory · src/shared/js/utils/parsers.js

固定版本源码；commit `d6bbea7375cfe64b99d3cf9a62d70244d09a7693`；许可：MIT（LICENSE版权占位符未填）；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/vict0rsch/PaperMemory/blob/d6bbea7375cfe64b99d3cf9a62d70244d09a7693/src/shared/js/utils/parsers.js>)


<a id="s120"></a>

### S120 · vict0rsch/PaperMemory · src/shared/js/utils/paper.js

固定版本源码；commit `d6bbea7375cfe64b99d3cf9a62d70244d09a7693`；许可：MIT（LICENSE版权占位符未填）；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/vict0rsch/PaperMemory/blob/d6bbea7375cfe64b99d3cf9a62d70244d09a7693/src/shared/js/utils/paper.js>)


<a id="s121"></a>

### S121 · ourresearch/parseland · find_shared.py

固定版本源码；commit `442a300a247aee1f4b8b7e75aaa2b105aee52626`；许可：MIT；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/ourresearch/parseland/blob/442a300a247aee1f4b8b7e75aaa2b105aee52626/find_shared.py>)


<a id="s122"></a>

### S122 · ourresearch/parseland · publisher/controller.py

固定版本源码；commit `442a300a247aee1f4b8b7e75aaa2b105aee52626`；许可：MIT；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/ourresearch/parseland/blob/442a300a247aee1f4b8b7e75aaa2b105aee52626/publisher/controller.py>)


<a id="s123"></a>

### S123 · ourresearch/parseland · publisher/parsers/cup.py

固定版本源码；commit `442a300a247aee1f4b8b7e75aaa2b105aee52626`；许可：MIT；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/ourresearch/parseland/blob/442a300a247aee1f4b8b7e75aaa2b105aee52626/publisher/parsers/cup.py>)


<a id="s124"></a>

### S124 · ourresearch/parseland · publisher/parsers/oxford.py

固定版本源码；commit `442a300a247aee1f4b8b7e75aaa2b105aee52626`；许可：MIT；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/ourresearch/parseland/blob/442a300a247aee1f4b8b7e75aaa2b105aee52626/publisher/parsers/oxford.py>)


<a id="s125"></a>

### S125 · ourresearch/parseland · publisher/parsers/ama.py

固定版本源码；commit `442a300a247aee1f4b8b7e75aaa2b105aee52626`；许可：MIT；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/ourresearch/parseland/blob/442a300a247aee1f4b8b7e75aaa2b105aee52626/publisher/parsers/ama.py>)


<a id="s126"></a>

### S126 · ourresearch/parseland · publisher/parsers/bmj.py

固定版本源码；commit `442a300a247aee1f4b8b7e75aaa2b105aee52626`；许可：MIT；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/ourresearch/parseland/blob/442a300a247aee1f4b8b7e75aaa2b105aee52626/publisher/parsers/bmj.py>)


<a id="s127"></a>

### S127 · ourresearch/parseland · publisher/parsers/spie.py

固定版本源码；commit `442a300a247aee1f4b8b7e75aaa2b105aee52626`；许可：MIT；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/ourresearch/parseland/blob/442a300a247aee1f4b8b7e75aaa2b105aee52626/publisher/parsers/spie.py>)


<a id="s128"></a>

### S128 · ourresearch/parseland · publisher/parsers/emerald.py

固定版本源码；commit `442a300a247aee1f4b8b7e75aaa2b105aee52626`；许可：MIT；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/ourresearch/parseland/blob/442a300a247aee1f4b8b7e75aaa2b105aee52626/publisher/parsers/emerald.py>)


<a id="s129"></a>

### S129 · ourresearch/parseland · publisher/parsers/thieme.py

固定版本源码；commit `442a300a247aee1f4b8b7e75aaa2b105aee52626`；许可：MIT；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/ourresearch/parseland/blob/442a300a247aee1f4b8b7e75aaa2b105aee52626/publisher/parsers/thieme.py>)


<a id="s130"></a>

### S130 · ourresearch/parseland-eval · RESULTS.md

固定版本源码；commit `56d7d1940312114210f537bf2f8d5e733ac8f2de`；许可：未核；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/ourresearch/parseland-eval/blob/56d7d1940312114210f537bf2f8d5e733ac8f2de/RESULTS.md>)


<a id="s131"></a>

### S131 · ropensci-archive/fulltext · R/ftd_doi.R

固定版本源码；commit `706a3a9d1c87a267fd7f2867544dd4cd945d6199`；许可：MIT + file LICENSE（DESCRIPTION已读）；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/ropensci-archive/fulltext/blob/706a3a9d1c87a267fd7f2867544dd4cd945d6199/R/ftd_doi.R>)


<a id="s132"></a>

### S132 · ropensci-archive/fulltext · R/ftdoi_patterns.R

固定版本源码；commit `706a3a9d1c87a267fd7f2867544dd4cd945d6199`；许可：MIT + file LICENSE（DESCRIPTION已读）；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/ropensci-archive/fulltext/blob/706a3a9d1c87a267fd7f2867544dd4cd945d6199/R/ftdoi_patterns.R>)


<a id="s133"></a>

### S133 · ropensci-archive/fulltext · R/ftdoi_publisher_plugin_helpers.R

固定版本源码；commit `706a3a9d1c87a267fd7f2867544dd4cd945d6199`；许可：MIT + file LICENSE（DESCRIPTION已读）；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/ropensci-archive/fulltext/blob/706a3a9d1c87a267fd7f2867544dd4cd945d6199/R/ftdoi_publisher_plugin_helpers.R>)


<a id="s134"></a>

### S134 · sckott/pubpatterns · src/oxford.json

固定版本源码；commit `2a342529dad052caa41776adbd45f3bda60a8b70`；许可：根目录未找到LICENSE；不建议复制整库；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/sckott/pubpatterns/blob/2a342529dad052caa41776adbd45f3bda60a8b70/src/oxford.json>)


<a id="s135"></a>

### S135 · sckott/pubpatterns · src/jama.json

固定版本源码；commit `2a342529dad052caa41776adbd45f3bda60a8b70`；许可：根目录未找到LICENSE；不建议复制整库；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/sckott/pubpatterns/blob/2a342529dad052caa41776adbd45f3bda60a8b70/src/jama.json>)


<a id="s136"></a>

### S136 · sckott/pubpatterns · src/emerald.json

固定版本源码；commit `2a342529dad052caa41776adbd45f3bda60a8b70`；许可：根目录未找到LICENSE；不建议复制整库；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/sckott/pubpatterns/blob/2a342529dad052caa41776adbd45f3bda60a8b70/src/emerald.json>)


<a id="s137"></a>

### S137 · sckott/pubpatterns · src/microbiology.json

固定版本源码；commit `2a342529dad052caa41776adbd45f3bda60a8b70`；许可：根目录未找到LICENSE；不建议复制整库；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/sckott/pubpatterns/blob/2a342529dad052caa41776adbd45f3bda60a8b70/src/microbiology.json>)


<a id="s138"></a>

### S138 · sckott/pubpatterns · src/f1000.json

固定版本源码；commit `2a342529dad052caa41776adbd45f3bda60a8b70`；许可：根目录未找到LICENSE；不建议复制整库；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/sckott/pubpatterns/blob/2a342529dad052caa41776adbd45f3bda60a8b70/src/f1000.json>)


<a id="s139"></a>

### S139 · drpwchen/paper-fetch · LICENSE

固定版本源码；commit `0ff462c0e81b2e90ae5ae9b378c59a54aba83659`；许可：MIT；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/drpwchen/paper-fetch/blob/0ff462c0e81b2e90ae5ae9b378c59a54aba83659/LICENSE>)


<a id="s140"></a>

### S140 · Agents365-ai/365-skills · plugins/paper-fetch/LICENSE

固定版本源码；commit `0a1679d1c9188656b104eddea9ae8d677920f13c`；许可：paper-fetch子插件 MIT；原研究范围：已读相关实现、注册路径或测试期望；未运行测试。

[源码 1](<https://github.com/Agents365-ai/365-skills/blob/0a1679d1c9188656b104eddea9ae8d677920f13c/plugins/paper-fetch/LICENSE>)


<a id="s141"></a>

### S141 · pubs.rsc.org/en/search/advancedsearch

网页/官方资料；许可：不适用；原研究范围：见关联记录；不含实际授权下载验证。

[资料](<https://pubs.rsc.org/en/search/advancedsearch>)


<a id="s142"></a>

### S142 · www.annualreviews.org/page/librarians/MigrationFAQ_LRC

网页/官方资料；许可：不适用；原研究范围：见关联记录；不含实际授权下载验证。

[资料](<https://www.annualreviews.org/page/librarians/MigrationFAQ_LRC>)
