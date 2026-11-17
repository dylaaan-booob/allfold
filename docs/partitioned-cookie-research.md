# 分区 Cookie 与后台 PDF 请求上下文

核查日期：2026-11-17。范围：[Issue #140](https://github.com/dylaaan-booob/allfold/issues/140) / [PR #141](https://github.com/dylaaan-booob/allfold/pull/141)，Electron 45.0.0 / Chromium 156.0.8078.48。

可以把“后台请求缺少当前页面分区 Cookie”作为优先工作原因，推进通用适配。社区有直接同类报告，本机相同 Electron 版本也有隔离机制复现；F18 的真实 `cf_clearance` 分区元数据仍未知，最终归因须由修复后原样本、对照和此前未访问的同类样本的正常 Download 结果确认。无需先取得或公开真实 Cookie 值。[现场记录](pdf-pairing-acceptance.md)；合成结果见下表，原始材料保存在本机 Workspace 外的证据目录

## 第一方报告与版本边界

| 来源、日期、版本 | 能支持的结论与状态 |
| --- | --- |
| [Zotero #588](https://github.com/zotero/zotero-connectors/issues/588)，2025-10-27 | 维护者记录：页面 fetch 会发送分区 Cookie，Chrome 后台请求漏掉带 `partitionKey` 的 `cf_clearance`，导致 CF 失败；当前仍为 Open / Upstream。对应[Chrome 扩展讨论](https://groups.google.com/a/chromium.org/g/chromium-extensions/c/CF6M5i6VvWY/m/mr6dtPjPAgAJ)明确说 `credentials: 'include'` 也会漏发，改 `mode: 'cors'` 无效。它是机制先例，不能单独证明 Electron 45 的现场原因。 |
| [Zotero 1ce8822](https://github.com/zotero/zotero-connectors/commit/1ce8822adfe94a70c5b3405fd578c0363f438bf7)，2025-10-27 | 应用侧临时 workaround：取分区 `cf_clearance`，经 DNR 补充请求。它不是 Chromium/Electron 引擎修复，不能直接套用其“所有分区”策略。 |
| [APS 原始报告](https://forums.zotero.org/discussion/127657/aps-export-returns-403-and-sandbox-cookie-securityerror-issue-15992705)，2025-10-25；Edge 141.0.0.0 / macOS 15.7.1 | 原作者报告 RIS/PDF 403、元数据有而附件无，并伴随 sandbox Cookie 异常。团队于 10-27 建议升级 Connector 5.0.188；没有后续用户成功确认，不能把所有异常都归因于 CHIPS。 |
| [Chromium 458071621](https://issues.chromium.org/issues/458071621)，由 Zotero 维护者于 2025-11-06 链出 | 本次公开页面只能取得动态外壳，无法核实当前状态、修复提交或里程碑；不宣称它已修复或仍未修复，也不据此推定 Electron 45 已解决。 |

CHIPS 按顶层站点划分 Cookie；“共用 Session”并不等于“共用请求分区上下文”。Chrome 的扩展 Cookie API 从 119 起有 `partitionKey`，默认 API 操作只针对未分区 Cookie；这与 Electron `session.fromPartition()` 的 Session 名称不是同一概念。[CHIPS](https://privacysandbox.google.com/cookies/chips)、[Chrome Cookie API](https://developer.chrome.com/docs/extensions/reference/api/cookies)、[Electron 45 Session](https://github.com/electron/electron/blob/v45.0.0/docs/api/session.md#sessionfrompartitionpartition-options)

Electron [#44456](https://github.com/electron/electron/issues/44456) 是 2024-10-29 的 33.0.2/Linux 默认 Session 混用报告，2024-11-11 因缺少复现关闭，不是 45 的 CHIPS 修复证据。[45 的 credentials 文档](https://github.com/electron/electron/blob/v45.0.0/docs/api/client-request.md#new-clientrequestoptions)描述普通凭据选项，也不能证明指定 `include` 后会采用正确分区。

## Electron 45 的实际约束

45.0.0 的 `cookies.get({url})` 使用 `CookiePartitionKeyCollection::ContainsAll()`，但返回 JS Cookie 对象不含 `partitionKey`；把这些结果全部拼接会丢失分区边界。[固定版本源码](https://github.com/electron/electron/blob/v45.0.0/shell/browser/api/electron_api_cookies.cc#L51)

Chromium 156.0.8078.48 的 `Network.getCookies` 使用目标页面的 `NetworkIsolationKey`、`SiteForCookies` 选择分区；`Network.getAllCookies` 则枚举整个存储分区。前者可以支撑绑定当前授权页面的适配，无需自行推导顶层站点或增加 PSL 依赖。[固定版本源码](https://github.com/chromium/chromium/blob/156.0.8078.48/content/browser/devtools/protocol/network_handler.cc#L261)

本机已有独立临时 Session / localhost 探针显示：Browser 发送普通和 Partitioned Cookie；`Session.fetch` 即使 `credentials: 'include'`，带或不带正确 Referer 都仅发送普通 Cookie 并返回合成 403。探针 4 增加其他分区负对照后，目标 `Network.getCookies` 仍只返回当前页面分区；同时，直接在 fetch options 设置 Cookie header 仍仅发普通 Cookie，不能据 Zotero 的补充方案推定 Electron 同样有效。这些是合成机制证据，不是实站成绩。本机证据：`checks/session-partition-probe-3.log`、`-4.log`、`-5.log`，均在 Workspace 外，非仓库文件

探针5在已有 `onBeforeSendHeaders` 最后阶段补上当前页面分区后，合成请求变为200，普通Cookie仍保留。当前分区之外另有同名Cookie作负对照，目标页面查询没有选入它。新适配据此沿现有受控请求执行，未照搬Zotero的DNR或全文件缓冲。

| 同一个隔离Session / localhost | 实际发送 | 合成响应 |
| --- | --- | --- |
| 正常Browser导航 | 普通 + 当前分区Cookie | 200 |
| Session.fetch，credentials include | 仅普通Cookie | 403 |
| 同上，正确Referer | 仅普通Cookie | 403 |
| 同上，fetch options直接设Cookie | 仅普通Cookie | 403 |
| 同上，受控beforeSendHeaders补充 | 普通 + 当前分区Cookie | 200 |

这些合成响应只检验传输机制，不代表真实Cloudflare响应或某个平台成绩。[隔离原生回归](../electron/tests/request-cookies.fixture.cjs)、[受控请求回归](../electron/tests/session-events.test.cjs)

## 与 F18 的对应及工程判断

Source `3a551ea` 的 F18（`10.1137/25M1735329`）已单独确认合法权限。Zotero 保存出版社 28 页 PDF，12.713–13.051s；Allfold 在两条出版社入口遇到 access-challenge 后保存相关 arXiv 30 页，23.120–23.480s。随后同一 Electron Session 的正常 Browser ViewPDF → SaveAs 得到出版社 28 页 / 3,814,818 bytes，无可见挑战。它确定了页面与后台请求差异，未确定真实 Cookie 分区；不同版本也不能作传输速度比较。[现场记录](pdf-pairing-acceptance.md)、[正式结果](pdf-pairing-formal-results.json)

建议沿现有受控 Session 请求链，在已有 `onBeforeSendHeaders` 最后阶段验证补充机制：仅使用同 Session、当前授权文档的分区 Cookie，逐跳遵守 domain/path/secure/expiry 和既有跳转约束；保持普通 Cookie 行为，禁止跨产品、跨页面混分区或写回 Cookie jar。此方案由上述版本源码与探针支持，是否解决 F18 仍须正常产品复测。只读研究没有读取真实 Cookie、运行应用或复制 AGPL 源码。
