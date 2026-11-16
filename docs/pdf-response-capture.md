# Capturing a browser PDF response with misleading MIME

A protocol relay can inspect a small prefix before returning the response stream
to Chromium. The isolated probe below demonstrates one physical HTTP request,
but does not preserve the required original-request correlation. Real HTML must
continue as a Document; only proven PDF bytes may become managed download output.
A header hook alone cannot make that distinction. None of the mechanisms examined
here completes the remaining ScienceDirect implementation.

The repository pins Electron 45.0.0. Its upstream tag selects Chromium
156.0.8078.48; API/source observations below use those tags, rather than assuming
old reports describe the installed runtime. See [Electron DEPS](https://github.com/electron/electron/blob/v45.0.0/DEPS#L3-L5).
The existing ownership, output and completion contract remains in
[body downloads](body-downloads.md).

## Similar reports and actual guidance

| Report | What it establishes; proposed or confirmed treatment |
| --- | --- |
| [AtoM #1868](https://github.com/artefactual/atom/issues/1868), 2024 | A user reports PDF responses labeled `text/html`, including Safari adding `.html`. The proposed fix is the server's MIME response. No Electron capture solution or maintainer-confirmed fix is recorded. |
| [Kimi #2143](https://github.com/MoonshotAI/kimi-cli/issues/2143), 2026 | A Windows Desktop user reports `Content-Disposition: attachment` downloading the PDF.js wrapper `viewer.html`. They propose removing attachment for that HTML route. This is a report in the CLI tracker, not a confirmed Electron 45 fix; it illustrates why attaching every HTML response destroys Reader execution. |
| [Electron #12599](https://github.com/electron/electron/issues/12599), 1.8.4 | A form's original POST returns PDF, then a GET returns HTML; the reported `will-download` exposes only the GET. The maintainer requested a newer-version reproduction. This supports preserving the original response, not recreating it with GET. |
| [Electron #24334](https://github.com/electron/electron/issues/24334), 9.0.5; [Electron community report](https://www.reddit.com/r/electronjs/comments/ls3d7n/download_pdf_inside_electron_app/) | Users report inline PDF viewing without `will-download`, even with `plugins: false`. Community suggestions include changing server MIME or downloading separately. These are related dispatch symptoms, not evidence that another request or disabling plugins solves the present case. |
| [Electron #48347](https://github.com/electron/electron/issues/48347), 38 | The PDF viewer's Download button stopped starting downloads; [PR #48372](https://github.com/electron/electron/pull/48372) fixed a missing `SaveRequestType` enum. Viewer defects can be version-specific. That fix does not identify a `text/html` body as PDF. |

There is affirmative maintainer guidance for protocol forwarding. In August 2026,
MarshallOfSound closed [Electron #15434](https://github.com/electron/electron/issues/15434)
by recommending `protocol.handle` plus
`net.fetch(req, { bypassCustomProtocolHandlers: true })`, available since Electron
25. The [45.0.0 Session API](https://github.com/electron/electron/blob/v45.0.0/docs/api/session.md#sesfetchinput-init)
documents this forwarding option and says `webRequest` still runs. Using the
business Session's `fetch` is necessary here; the default Session is not the
business Session.

## Candidate: prefix inspection before Chromium receives the body

Intercept the admitted browser navigation before its upstream request is sent,
forward that request once through the same business Session, then read only the
five-byte PDF discriminator. A pull-based stream can put that prefix back before
the unread remainder. Return actual HTML with its original status/headers/body so
its own navigation still executes; for proven PDF, return the same bytes with a
qualified attachment response, retaining the existing native item/output path.
The streaming mechanism follows the forwarding API and
[Electron's stream response implementation](https://github.com/electron/electron/blob/v45.0.0/lib/browser/api/protocol.ts#L154-L215),
with the limited local observation recorded below. Interception must replace the first dispatch;
fetching after the browser has already received its response would be a second
request.

Two constraints determine whether this fits Allfold:

- **Exact authority:** `protocol.handle` constructs a `Request` from URL, method,
  headers, referrer and upload body, with `initiatorOrigin`; it does not expose the
  original native frame or request ID. A URL/PII match alone cannot authorize a
  file. Any one-use private correlation must originate in the already admitted
  native request and disappear before outbound HTTP. The
  [v45 request routing](https://github.com/electron/electron/blob/v45.0.0/shell/browser/net/proxying_url_loader_factory.cc#L164-L186)
  can start its target before `onBeforeSendHeaders` when the network header client
  is used, so a marker added there cannot be assumed to reach the protocol handler.
- **Shared Session behavior:** the handler is registered for the Session's entire
  scheme. Other requests need correct forwarding too. [Electron #39709](https://github.com/electron/electron/issues/39709)
  records lost progress and request/redirect behavior under scheme interception.
  It is not permission to route all shared browsing through a new downloader.
  [PR #49671](https://github.com/electron/electron/pull/49671) proposed native
  fall-through on `null`, but is closed; the
  [v45 handler](https://github.com/electron/electron/blob/v45.0.0/lib/browser/api/protocol.ts#L110-L123)
  rejects missing responses. Forwarding is not transparent native fall-through.

One focused association experiment is to attach `Fetch` Request-stage interception
to the already owned Page: its `requestPaused` has `frameId`/`networkId`, and
[`continueRequest` can add headers](https://github.com/chromium/chromium/blob/156.0.8078.48/third_party/blink/public/devtools_protocol/domains/Fetch.pdl#L118-L142)
without changing URL, method or body. A Main-issued one-use token there could
reach the protocol handler before upstream dispatch, then be removed before
HTTP. The local control experiment below did not deliver this interception on
the protocol-handled path. It also does not resolve scheme-wide forwarding.
The deprecated protocol callbacks do not restore native
IDs either: the [native request converter](https://github.com/electron/electron/blob/v45.0.0/shell/common/gin_converters/net_converter.cc#L692-L706)
also omits frame/request identity.

The first fixture should therefore prove exact frame/request association and one
physical HTTP request before product integration. It must also preserve method,
body, Referer, cookies, redirect qualification, an HTML Reader's script navigation,
the original DownloadItem/output association, cancellation and actual resource
settlement. A slow response and slow sink must show finite prefix buffering and
existing backpressure, with unrelated same-URL frames unable to claim output.
Failure of these conditions rejects this relay implementation; it does not prove
that all response-capture mechanisms are impossible.

## Other mechanisms and their limits

### Native viewer Save Original

The built-in viewer has two distinct save paths. With the default-disabled
[`PdfGetSaveDataInBlocks` feature](https://github.com/chromium/chromium/blob/156.0.8078.48/pdf/pdf_features.cc#L39-L40)
off, [`SaveRequestType.ORIGINAL`](https://github.com/chromium/chromium/blob/156.0.8078.48/pdf/pdf_view_web_plugin.cc#L2083-L2105)
calls `SaveToFile`, which sends
[`PDFHost::SavePdf`](https://github.com/chromium/chromium/blob/156.0.8078.48/pdf/pdf_view_web_plugin.cc#L2437-L2444).
The [browser helper](https://github.com/chromium/chromium/blob/156.0.8078.48/components/pdf/browser/pdf_document_helper.cc#L536-L551)
finds the PDF's embedder RenderFrameHost and calls `WebContents::SaveFrame` for
its committed URL. It does not pass the viewer's already consumed body stream to
the download manager.

[`SaveFrameWithHeaders`](https://github.com/chromium/chromium/blob/156.0.8078.48/content/browser/web_contents/web_contents_impl.cc#L7415-L7527)
builds new download parameters from that frame, uses `prefer_cache(true)` and
starts `DownloadManager::DownloadUrl`. Its
[`GetLoadFlags`](https://github.com/chromium/chromium/blob/156.0.8078.48/components/download/internal/common/download_utils.cc#L504-L540)
uses the HTTP cache without revalidation for GET; a cache miss may reach the
network. A saved POST transaction uses cache-only flags rather than reposting.
Thus a cache hit with one counted HTTP request does not establish reuse of the
original response. A `no-store` response and physical request count distinguish
the cases.

The new download retains the embedder frame. Its initiator is taken from the
original FrameNavigationEntry and can be absent; it must not be invented from the
URL. Electron's
[`will-download` bridge](https://github.com/electron/electron/blob/v45.0.0/shell/browser/api/electron_api_session.cc#L610-L631)
passes the DownloadItem's actual WebContents and RenderFrameHost. An attributed
frame therefore does not prove that the item reused the original HTTP request.

The feature-enabled viewer path instead obtains plugin bytes in blocks and
writes through FileWriter or File System Access APIs; it is a different output
path, not the original managed DownloadItem contract. See
[`saveInBlocks_`](https://github.com/chromium/chromium/blob/156.0.8078.48/chrome/browser/resources/pdf/pdf_viewer.ts#L1820-L1914).
Electron's public [`webContents.savePage`](https://github.com/electron/electron/blob/v45.0.0/docs/api/web-contents.md#contentssavepagefullpath-savetype)
offers HTMLOnly/HTMLComplete/MHTML rather than a public `saveFrame` operation;
its [SavePackage items are excluded](https://github.com/electron/electron/blob/v45.0.0/shell/browser/api/electron_api_session.cc#L610-L613)
from `will-download`. Neither API contract promises original-PDF-stream adoption.

### Response interception APIs

| Mechanism | Applicability to this boundary |
| --- | --- |
| Header removal, unknown MIME, `application/octet-stream` | Chromium's [matching-version sniffer](https://github.com/chromium/chromium/blob/156.0.8078.48/net/base/mime_sniffer.cc#L659-L808) excludes `text/html`/XHTML from normal sniffable types, honors `nosniff`, and deliberately avoids ordinary magic-number detection for octet-stream. Unknown MIME can allow HTML/PDF sniffing, but inferred PDF can still enter the viewer rather than create an item. Headers alone expose no byte discriminator. |
| `Fetch.takeResponseBodyAsStream` + sequential `IO.read` | [Fetch](https://github.com/chromium/chromium/blob/156.0.8078.48/third_party/blink/public/devtools_protocol/domains/Fetch.pdl#L184-L234) provides request/frame IDs and a stream; [the pipe reader](https://github.com/chromium/chromium/blob/156.0.8078.48/content/browser/devtools/devtools_stream_pipe.cc#L59-L121) reads on demand. But taking the body consumes Chromium's original response path: [continuation explicitly refuses it](https://github.com/chromium/chromium/blob/156.0.8078.48/content/browser/devtools/devtools_url_loader_interceptor.cc#L1292-L1452). `fulfillRequest` accepts a whole binary body, not a stream handle. Useful for an entry already known not to require HTML continuation; insufficient by itself for ambiguous Reader HTML. |
| `Network.streamResourceContent` | Can observe an in-flight response without replaying HTTP or stopping the page. In [the current implementation](https://github.com/chromium/chromium/blob/156.0.8078.48/third_party/blink/renderer/core/inspector/inspector_network_agent.cc#L1698-L1752), it copies buffered bytes and pushes subsequent chunks as `dataReceived`; inspector buffering remains active. There is no sink acknowledgement/pull control in this path. It is not an established replacement for the existing backpressured writer. |
| `Network.getResponseBody` / `Fetch.getResponseBody` | Return the complete body. [chrome-remote-interface #260](https://github.com/cyrus-and/chrome-remote-interface/issues/260) advises waiting for `loadingFinished` and tracking the original ID, with later reports of missing bodies. That timing advice does not provide a bounded stream or remove full-body caching. |
| Electron `webRequest` response filters | [#36261](https://github.com/electron/electron/issues/36261) clarifies that a purported Chromium implementation was a fork demo, not an upstream API, and rejects whole-body buffering for large responses. [#8374](https://github.com/electron/electron/issues/8374) was closed as unplanned in 2025. The [v45 API](https://github.com/electron/electron/blob/v45.0.0/docs/api/web-request.md) exposes headers/events, not a response-body filter. Firefox extension filters or a custom Electron build cannot be assumed available. |

Repeated GET/HEAD, `downloadURL` after the original response, injected service
workers, whole-PDF buffering, and global PDF-viewer/security switches do not meet
the present original-response and shared-browser constraints. Server-side MIME
correction is appropriate when the server is owned, but does not solve capture
from an external publisher. No publisher/account access or live acceptance is
established by these upstream reports and source observations.

## Zotero Connector save ownership

This source comparison pins Connector
[`02271dc76769a2e723107cbd5ca7263c0d93ba94`](https://github.com/zotero/zotero-connectors/tree/02271dc76769a2e723107cbd5ca7263c0d93ba94)
and Desktop
[`992853536935dce3249a4ecf61d0d129883f85c4`](https://github.com/zotero/zotero/tree/992853536935dce3249a4ecf61d0d129883f85c4).
They are research revisions, not new Allfold dependencies. The inspected paths
do not establish a solution for PDF bytes labelled `text/html` with no native
DownloadItem.

| Save path | Owner and actual bytes |
| --- | --- |
| Translator items | Connector first calls Desktop `saveItems` with item metadata and linked attachments, then saves binary attachments separately. The top-level item can already exist when an attachment fails. See [itemSaver](https://github.com/zotero/zotero-connectors/blob/02271dc76769a2e723107cbd5ca7263c0d93ba94/src/common/itemSaver.js#L176-L197). |
| PDF/EPUB attachment | The browser background performs a new `GET`, obtains a complete `ArrayBuffer`, and POSTs it to Desktop `saveAttachment`; standalone saving uses the same acquisition method. This is a new fetch operation, possibly cache-served, rather than adoption of the navigation response. See [background saver](https://github.com/zotero/zotero-connectors/blob/02271dc76769a2e723107cbd5ca7263c0d93ba94/src/common/itemSaver_background.js#L82-L134), [GET](https://github.com/zotero/zotero-connectors/blob/02271dc76769a2e723107cbd5ca7263c0d93ba94/src/common/itemSaver_background.js#L204-L239) and [full-body read](https://github.com/zotero/zotero-connectors/blob/02271dc76769a2e723107cbd5ca7263c0d93ba94/src/common/http.js#L367-L410). |
| HTML webpage/snapshot | The browser Document executes normally. `document.contentType` selects the webpage path; `saveSnapshot` creates metadata, then SingleFile serializes the current page. Its resource fetches can issue further GETs. This is a rendered HTML snapshot, not PDF-response capture. See [pageSaving](https://github.com/zotero/zotero-connectors/blob/02271dc76769a2e723107cbd5ca7263c0d93ba94/src/common/inject/pageSaving.js#L310-L428) and [SingleFile adapter](https://github.com/zotero/zotero-connectors/blob/02271dc76769a2e723107cbd5ca7263c0d93ba94/src/common/singlefile.js#L33-L103). |
| Desktop receives browser bytes | Desktop `saveAttachment` passes its local POST input stream to `importFromNetworkStream`, attached to the session's parent item. That input is the Connector upload, not the publisher navigation channel. `saveSingleFile` instead imports supplied snapshot content. See [Desktop endpoints](https://github.com/zotero/zotero/blob/992853536935dce3249a4ecf61d0d129883f85c4/chrome/content/zotero/xpcom/server/server_connector.js#L486-L589). |

Connector validates expected attachment MIME against the response header. A
declared PDF returned as `text/html` fails even if its bytes begin `%PDF-`;
`application/octet-stream` is an explicit exception. Missing declared MIME is
filled from the header or, if absent, the URL. There is no byte discriminator in
this validator. See [validation](https://github.com/zotero/zotero-connectors/blob/02271dc76769a2e723107cbd5ca7263c0d93ba94/src/common/itemSaver_background.js#L275-L300)
and [header parsing](https://github.com/zotero/zotero-connectors/blob/02271dc76769a2e723107cbd5ca7263c0d93ba94/src/common/utilities.js#L134-L148).

Connector's access recovery is also a URL-acquisition path. Its qualified
ScienceDirect/NCBI branch lets a hidden iframe or popup execute challenge HTML.
`BrowserAttachmentMonitor` detects only PDF/EPUB MIME or attachment disposition,
returns the response URL, and redirects recognized attachment navigations to an
extension placeholder. The saver then performs another GET. A PDF labelled HTML
without attachment disposition fails that detector. See [bypass selection and
execution](https://github.com/zotero/zotero-connectors/blob/02271dc76769a2e723107cbd5ca7263c0d93ba94/src/common/botBypass.js#L26-L158),
[header detection and redirect](https://github.com/zotero/zotero-connectors/blob/02271dc76769a2e723107cbd5ca7263c0d93ba94/src/browserExt/browserAttachmentMonitor/browserAttachmentMonitor.js#L134-L231)
and [subsequent acquisition](https://github.com/zotero/zotero-connectors/blob/02271dc76769a2e723107cbd5ca7263c0d93ba94/src/common/itemSaver_background.js#L242-L271).
The general [WebRequest interceptor](https://github.com/zotero/zotero-connectors/blob/02271dc76769a2e723107cbd5ca7263c0d93ba94/src/browserExt/webRequestIntercept.js#L34-L86)
observes request/response headers and frame metadata, with no body filter.
An optional [Desktop OA resolver fallback](https://github.com/zotero/zotero-connectors/blob/02271dc76769a2e723107cbd5ca7263c0d93ba94/src/common/itemSaver.js#L263-L302)
is another acquisition source, not reuse of the failed response.

Desktop has a separate file downloader: `HTTP.download` fetches a new response
and streams it to disk; `downloadFile` can then sniff a 1,000-byte file sample and
fall back to `BrowserRequest.downloadPDF` for supported failures. See
[HTTP downloader](https://github.com/zotero/zotero/blob/992853536935dce3249a4ecf61d0d129883f85c4/chrome/content/zotero/xpcom/http.js#L637-L783)
and [file validation/fallback](https://github.com/zotero/zotero/blob/992853536935dce3249a4ecf61d0d129883f85c4/chrome/content/zotero/xpcom/attachments.js#L1176-L1240).
That fallback really can consume its hidden browser's response: a Firefox
`nsITraceableChannel` listener captures a registered MIME type and checks the
channel's `nsILoadContext.topFrameElement` against the owned browser. However,
registration is for `application/pdf`, selection uses HTTP Content-Type, and the
listener buffers the entire body into `StorageStream`, then `ArrayBuffer` and
`Blob` before writing. See [registration](https://github.com/zotero/zotero/blob/992853536935dce3249a4ecf61d0d129883f85c4/chrome/content/zotero/xpcom/browserRequest.js#L455-L461),
[browser ownership/save](https://github.com/zotero/zotero/blob/992853536935dce3249a4ecf61d0d129883f85c4/chrome/content/zotero/xpcom/browserRequest.js#L525-L583),
[MIME dispatch](https://github.com/zotero/zotero/blob/992853536935dce3249a4ecf61d0d129883f85c4/chrome/content/zotero/xpcom/mimeTypeHandler.js#L155-L187)
and [body buffering](https://github.com/zotero/zotero/blob/992853536935dce3249a4ecf61d0d129883f85c4/chrome/content/zotero/xpcom/mimeTypeHandler.js#L228-L280).
This Firefox privileged implementation supplies neither an Electron 45 response
filter nor a proof that ambiguous HTML can continue while only proven PDF bytes
enter the original managed output path.

The applicable design lesson is to preserve browser execution and exact resource
ownership separately from attachment validation. Zotero's inspected saving paths
do not remove Allfold's remaining requirement to prove original-response capture,
finite buffering/backpressure and original DownloadItem association together.
No Zotero account, browser, publisher or installed-app acceptance was performed.

## Isolated observations

These are synthetic local Electron 45 / Node probes, not publisher or Zotero
application acceptance. They tested the candidate mechanisms before integration:

- Protocol relay: one HTTP GET, a replayed `%PDF-` prefix and one completed real
  DownloadItem produced the exact supplied bytes. The outer navigation had its
  own request ID and frame; the Session fetch had a different ID and no frame.
  The handler ran before the inner `beforeSendHeaders`, so that hook could not
  identify the outer request to the handler.
- CDP token control: Request-stage `Fetch.requestPaused` fired on normal browser
  HTTP, but did not fire when `protocol.handle` handled that navigation. The
  proposed token injection therefore supplied no correlation on this path.
- Native viewer: a minimal real PDF served as HTML became a PDF Viewer after
  scoped `unknown/unknown` MIME replacement. Its existing Save button created an
  item in the original embedder frame, but a `Cache-Control: no-store` response
  caused **two physical GETs**. The saved bytes matched; original-response reuse
  did not. This method was rejected, without changing product headers or actions.
- Connector validator: the pinned unmodified `itemSaver_background.js` was loaded
  in a Node VM with stub headers and a `%PDF-` payload. Expected PDF with PDF or
  octet-stream MIME was accepted; HTML MIME was rejected. This exercises the
  validator, not the installed Connector, network access or a Zotero library.

The production regression remains in the existing native fixture: a committed
ScienceDirect Reader followed by a CDN HTTP redirect completes once; unchanged
navigation/Cookie cycles still stop. Restoring the old continuation-context check
in an in-memory test reproduced `download_not_attributable`; the corrected
`body-native.test.cjs` passes all six tests, including the public SQLite fixture.
