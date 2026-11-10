# Zotero 10 Local API protocol notes

Research checked on 2026-11-05 for the migration from Allfold baseline
`e2b97b8d4be48d8b027e0eedd4b6f5a2782aa244`. This is protocol/source evidence,
not real Zotero, Group Library, browser, or account acceptance.

## Supported release and transport

Support starts at **10.0.6**: 10.0.5 fixed client-supplied object keys
([22a26bb](https://github.com/zotero/zotero/commit/22a26bb)); 10.0.6 fixed form
encoding of spaces in filenames
([9cbba8c](https://github.com/zotero/zotero/commit/9cbba8c)). The
[release history](https://www.zotero.org/support/changelog#changes_in_1006_october_7_2026)
records both boundaries. The 10.0.6 tag resolves to
`536244c2771f590abab9c09a3c27e615e0b318ff`; its `server_localAPI.js` is identical
to that file at the requested newer reference
[`c2b239d`](https://github.com/zotero/zotero/blob/c2b239dd879feff328e0a11924ef35d000d00fbd/chrome/content/zotero/xpcom/server/server_localAPI.js).
This equality establishes the audited protocol, not equivalence of those entire releases.

Use a controlled origin such as `http://127.0.0.1:23119`, prefix `/api/`, and
reject redirects. `GET /api/` returns `X-Zotero-Version`, `Zotero-API-Version: 3`
and `Zotero-Server-ID`. A disabled Local API returns `403`. Reads require no key.
The database-specific Server ID survives restarts/upgrades; send the captured ID
on reads and all writes. Mismatch returns `412`; a write without it returns
`428`. Versions belong to that database, not the Web API or another instance.
([Local API documentation](https://www.zotero.org/support/dev/web_api/v3/local_api))

Electron requests should also carry `Zotero-Allowed-Request: 1`: Zotero blocks
browser-like `Mozilla/` user agents or requests with `Origin` without this header
(or its Connector alternative). The server accepts Host names only `localhost`,
`127.0.0.1`, or `[::1]`, optionally with a port; POST bodies require Content-Length.
These server restrictions do not replace Allfold's URL validation.
([10.0.6 HTTP server](https://github.com/zotero/zotero/blob/536244c2771f590abab9c09a3c27e615e0b318ff/chrome/content/zotero/xpcom/server/server.js#L277-L425))

## Authorization and targets

```http
POST /api/local/authorize
Content-Type: application/json
Zotero-Server-ID: <captured ID>
Zotero-Allowed-Request: 1

{"appName":"Allfold"}
```

Approval is `200 {"key":"<32-character key>","remember":true|false}`.
**Always Allow** makes the key reusable; **Allow** consumes it on the first write
that validates the key, before the library permission and business operation
checks. Thus an eventual failed write can consume it too. Denial is
`403 {"denied":true}`. Missing/invalid/consumed credentials return `401`.
At most five authorization dialogs per minute are allowed (`429`, `Retry-After`).
Send `Zotero-API-Key` only to controlled local write endpoints; persist reusable
keys in protected storage associated with Server ID, never URL query parameters.
([10.0.6 authorization and key consumption](https://github.com/zotero/zotero/blob/536244c2771f590abab9c09a3c27e615e0b318ff/chrome/content/zotero/xpcom/server/server_localAPI.js#L164-L219),
[authorization endpoint](https://github.com/zotero/zotero/blob/536244c2771f590abab9c09a3c27e615e0b318ff/chrome/content/zotero/xpcom/server/server_localAPI.js#L808-L868))

Allfold waits for the authorization decision without adding an expiry; quitting
or disconnecting cancels that pending authorization request. Ordinary local save
requests retain the previous Connector transport's 60-second timeout and are
awaited after dispatch. Local API lists use the server's complete-result default,
without an added entry-count or JSON-size cutoff.

| Read endpoint under `/api` | Meaning |
| --- | --- |
| `/users/0/groups` | All locally available groups; each has numeric `id` and `data.name` |
| `/groups/<groupID>` | One group's identifying metadata |
| `/users/0/collections` | Personal library's entire collection hierarchy |
| `/groups/<groupID>/collections` | Group library's entire collection hierarchy |
| `<prefix>/collections/top` | Only top-level collections |
| `<prefix>/collections/<key>/collections` | Immediate child collections |
| `<prefix>/collections/<key>` | Exact collection existence/details |

Here `<prefix>` is `/users/0` or `/groups/<groupID>`. User `0` works without an
online user ID; the actual logged-in numeric user ID is also accepted; any other
user returns `400`. Group IDs are online group IDs, **not** Zotero's internal
numeric Library IDs. Collections expose `data.key`, `data.name` and
`data.parentCollection` (key or `false`); preserve keys when building the tree.
([10.0.6 target routes](https://github.com/zotero/zotero/blob/536244c2771f590abab9c09a3c27e615e0b318ff/chrome/content/zotero/xpcom/server/server_localAPI.js#L285-L304),
[collection/group implementation](https://github.com/zotero/zotero/blob/536244c2771f590abab9c09a3c27e615e0b318ff/chrome/content/zotero/xpcom/server/server_localAPI.js#L974-L1046),
[collection JSON](https://github.com/zotero/zotero/blob/536244c2771f590abab9c09a3c27e615e0b318ff/chrome/content/zotero/xpcom/data/collection.js))

Group JSON deliberately omits member roles, `editable`, and `filesEditable`;
it is identification metadata, not a permission grant. No Local API permission
discovery endpoint was found. Show permissions as unknown until the real check:
ordinary writes reject non-editable libraries with `403`; file authorization
and registration additionally check `filesEditable`. Item permission never
proves attachment permission.
([group serialization](https://github.com/zotero/zotero/blob/536244c2771f590abab9c09a3c27e615e0b318ff/chrome/content/zotero/xpcom/data/group.js#L242-L280),
[write check](https://github.com/zotero/zotero/blob/536244c2771f590abab9c09a3c27e615e0b318ff/chrome/content/zotero/xpcom/server/server_localAPI.js#L311-L322),
[file check](https://github.com/zotero/zotero/blob/536244c2771f590abab9c09a3c27e615e0b318ff/chrome/content/zotero/xpcom/server/server_localAPI.js#L2355-L2383))

## Bounded Import

Import fixes the Paper plan, Service scope, authorization and Local API target at
start. Unprepared Services require explicit skips. Papers without a matching
Service retain their DOI path. The application admits Paper requests with
per-Service and total bounds while the native host bounds translation, PDF
retrieval and writes separately.

Independent Papers can issue Local API POSTs concurrently with distinct object
keys. Before each POST, the writer checks request and document ownership and
whether an earlier write became uncertain. Issued requests settle and retain all
known keys. The guarded Workspace commit records each confirmed parent
independently of attachment registration. Batch history marks uncertainty for
manual inspection.

## Parent creation and precise identity

Generate a fresh eight-character key from
`23456789ABCDEFGHIJKLMNPQRSTUVWXYZ` before dispatch. Create with
`POST /api<target-prefix>/items`, JSON array, API key, Server ID, and
`Zotero-API-Version: 3`:

```json
[{"key":"ABCD2345","version":0,"itemType":"journalArticle","title":"Example",
  "DOI":"10.5555/example","creators":[],"tags":[],"relations":{},
  "collections":["BCDE3456"]}]
```

Omit the collection key when targeting the library root. `version:0` is the
create precondition for a provided key; an existing positive local version
fails rather than silently updating it. A keyed object without `version` or a
request version precondition fails with code `428`. HTTP `200` wraps per-object
results; an example successful response is:

```json
{"successful":{"0":{"key":"ABCD2345","version":7,"data":{"key":"ABCD2345","version":7,"itemType":"journalArticle"}}},
 "success":{"0":"ABCD2345"},"unchanged":{},"failed":{}}
```

The full object also contains library/links/meta and item data. Failure instead
appears in `failed["0"] = {key,code,message}` even with HTTP `200`. Require the
matching `successful["0"].key`, not merely `success`, `unchanged`, status 200, or
a DOI search. `Zotero-Write-Token` is an optional duplicate-rejection token,
not permission to replay an uncertain write.
([official key generator](https://github.com/zotero/utilities/blob/5b93ec8b4e7ce6124cde1b8ff89ca65b2919d114/utilities.js#L1723-L1740),
[keyed creation regression tests](https://github.com/zotero/zotero/blob/536244c2771f590abab9c09a3c27e615e0b318ff/test/tests/server_localAPITest.js#L914-L1000),
[write response contract](https://www.zotero.org/support/dev/web_api/v3/write_requests#creating_an_item))

## PDF attachment: create → authorize → upload → register

1. Create a child in the same `/items` endpoint and check the exact successful
   key: `key`, `version:0`, `itemType:"attachment"`, `parentItem:<parentKey>`,
   `linkMode:"imported_url"`, `contentType:"application/pdf"`, `title`, `url`,
   `filename`, `tags:[]`, `relations:{}`. Do not claim a file from this shell.
2. Authorize with `POST <prefix>/items/<attachmentKey>/file`,
   `Content-Type: application/x-www-form-urlencoded`, API key, Server ID,
   `If-None-Match: *`. Body:
   `md5=<32 lowercase hex>&filename=<encoded bare filename>&filesize=<byte count>&mtime=<epoch milliseconds>`.
   Optional parameters are `contentType`, `charset`, and `params=1`.
3. Default `200` returns `{url,uploadKey,contentType,prefix:"",suffix:""}`.
   POST `prefix + bytes + suffix` to **that exact returned URL**, Content-Type as
   returned; expect `201`. With `params=1`, the response instead contains
   `params:{key:<md5>}`: multipart fields first, then a `file` part. The upload
   receiver requires neither API key nor Server ID; retain the local allowed
   request header and keep the upload key secret.
4. Register via `POST` to the original attachment `/file`, API key, Server ID,
   same `If-None-Match: *`, form body `upload=<uploadKey>`. Only `204` completes
   registration. In 10.0.6 its version header is **Last-Modified-Version**, even
   though the generic Web upload documentation says Zotero-Library-Version.

The authorization alternative `{exists:1}` is already terminal association
success. For replacement files the documented precondition is `If-Match:
<previous md5>` at authorization and registration; this task creates new files.
([official file upload protocol](https://www.zotero.org/support/dev/web_api/v3/file_upload),
[10.0.6 complete binary/multipart tests](https://github.com/zotero/zotero/blob/536244c2771f590abab9c09a3c27e615e0b318ff/test/tests/server_localAPITest.js#L1971-L2200))

All local upload URLs have the form
`http://<request Host>/api/local/uploads/<32-character uploadKey>`; no S3,
publisher, or alternate upload host is involved. Validate origin, port, path,
upload key, credentials, and redirects before sending bytes. The receiver stages
bytes and checks MD5; registration moves the file and updates metadata. Pending
upload keys are memory-only with a one-hour expiry. A reported filesize is
required and bounded, but the receiver verifies MD5 rather than comparing the
received length; Allfold must calculate both from its actual download.
([release upload implementation](https://github.com/zotero/zotero/blob/536244c2771f590abab9c09a3c27e615e0b318ff/chrome/content/zotero/xpcom/server/server_localAPI.js#L1279-L1366),
[authorization/registration details](https://github.com/zotero/zotero/blob/536244c2771f590abab9c09a3c27e615e0b318ff/chrome/content/zotero/xpcom/server/server_localAPI.js#L2391-L2599))

After any ambiguous dispatched write, retain the known keys, stop new writes,
and reconcile by reads; authorization renewal must not replay creation/upload.
Partial objects remain in Zotero. Handle `401/403/412/428/429` by stage and
preserve parent confirmation separately from the PDF result. Generic Web API
quota/rate errors are not evidence that the local receiver implements those
same limits.

Each Import create and upload POST rechecks its task/document immediately before
transport dispatch, including after asynchronous key reads and between upload
stages. Cancellation waits for an issued request to settle and prevents the next
POST. Only a failure before parent dispatch is `no_effect`; a dispatched rejection
retains the exact key and remains uncertain pending read-only reconciliation.

## Last Import: object queries, no file inspection

Read only `GET <prefix>/items/<knownKey>` and
`GET <prefix>/items/<knownKey>/children`, with pinned Server ID. Match exact
attachment key, `parentItem`, `itemType`, PDF `contentType`, and imported
`linkMode`; combine this with this run's confirmed upload registration.
An attachment shell is insufficient. Read failures and unresolved writes are
unknown, not No. Never request `/file`, `/file/view`, `/file/view/url`, follow
file links, inspect the filesystem, or compare downloaded bytes again.

Zotero itself serializes `md5`, `mtime`, file sizes and an enclosure link while
building ordinary item JSON; its 10.0.6 implementation can internally stat/hash
the stored file. There is no exposed query switch to avoid that serialization.
Ignore these storage fields/links and do not expose or use them as extra
verification. This distinction is necessary for the required object-only checks.
([item/children endpoints](https://github.com/zotero/zotero/blob/536244c2771f590abab9c09a3c27e615e0b318ff/chrome/content/zotero/xpcom/server/server_localAPI.js#L1207-L1276),
[actual JSON serialization](https://github.com/zotero/zotero/blob/536244c2771f590abab9c09a3c27e615e0b318ff/chrome/content/zotero/xpcom/data/item.js#L6154-L6236))

## Existing ItemSaver behavior to preserve or declare

The baseline [Allfold host](https://github.com/dylaaan-booob/allfold/blob/e2b97b8d4be48d8b027e0eedd4b6f5a2782aa244/electron/src/zotero/item-saver.cjs)
passes the full Translator item to official ItemSaver, uses the Browser Session
for downloads, permits one parent dispatch, disables cloud fallback, and leaves
PDF persistence unverified. Its preference shim enables associated files and
disables automatic snapshots. The pinned
[official Connector ItemSaver](https://github.com/zotero/zotero-connectors/blob/e942336f9a3671944c34abf5d35864d73265d5c1/src/common/itemSaver.js#L109-L280)
therefore retains URL links (`snapshot:false`), drops URL-less attachments and
HTML snapshots, downloads non-HTML binaries including EPUB, and uses PDF/EPUB
as primary attachment types. On an actual PDF page it substitutes that page
as the PDF source. OA resolution currently uses a Connector save session.

Compatibility checks must cover these differences:

- **Metadata:** retain schema-valid fields rather than a small article-field
  projection, creator modes, tags, accessDate, parent notes and note tags, and
  proxy-normalized bibliographic URLs. Desktop's importer strips translator
  `id`, `itemID`, `path`, `dateAdded`, `dateModified`, `version` and container
  fields; it resolves `CURRENT_TIMESTAMP` and saves notes as children.
  ([Desktop importer](https://github.com/zotero/zotero/blob/536244c2771f590abab9c09a3c27e615e0b318ff/chrome/content/zotero/xpcom/translation/translate_item.js#L230-L267),
  [field removal](https://github.com/zotero/zotero/blob/536244c2771f590abab9c09a3c27e615e0b318ff/chrome/content/zotero/xpcom/translation/translate_item.js#L530-L550))
- **Normalization helper:** retained `Utilities.Item.itemToAPIJSON` converts
  creators, tags, base fields and notes to API JSON. It does not convert
  attachments, drops note tags, and is not a complete replacement for Desktop
  import semantics. Reuse with explicit adaptation, not silent data loss.
  ([pinned helper](https://github.com/zotero/utilities/blob/5b93ec8b4e7ce6124cde1b8ff89ca65b2919d114/utilities_item.js#L781-L920))
- **Tags:** Connector Desktop saving forces automatic tags and respects
  Zotero's `automaticTags` preference. Local API writes bypass that importer;
  neither group metadata nor `/users/0/settings` exposes this preference.
  A changed policy is an explicit gap requiring tests/documentation.
  ([save session](https://github.com/zotero/zotero/blob/536244c2771f590abab9c09a3c27e615e0b318ff/chrome/content/zotero/xpcom/server/saveSession.js#L75-L111),
  [tag cleaning](https://github.com/zotero/zotero/blob/536244c2771f590abab9c09a3c27e615e0b318ff/chrome/content/zotero/xpcom/translation/translate_item.js#L1018-L1075))
- **Links/non-PDF files:** link attachments require separate `linked_url`
  child objects; non-PDF binaries already work through the old transport and
  must be retained or declared as a scoped regression. The old binary transport
  sends only URL, content type, parent identity and title, so binary note/tag
  preservation is not an existing guarantee. Rich link fields do pass through
  Desktop's importer. HTML snapshot support need not be added.
  ([binary metadata](https://github.com/zotero/zotero-connectors/blob/e942336f9a3671944c34abf5d35864d73265d5c1/src/common/itemSaver_background.js#L82-L110),
  [linked attachment metadata](https://github.com/zotero/zotero/blob/536244c2771f590abab9c09a3c27e615e0b318ff/chrome/content/zotero/xpcom/translation/translate_item.js#L605-L640))

## Allfold migration compatibility

The host importer uses the retained official API-JSON conversion inside the
translation sandbox, with explicit preservation of note tags, links and non-PDF
binary attachments. HTML snapshots remain disabled. Translator tags are retained
as automatic tags; the Local API does not expose Zotero's `automaticTags`
preference, so Allfold cannot mirror that Desktop setting.

PDF downloads use the originating Document and the Browser Session after the
parent is confirmed. A normalized PDF candidate URL gets at most three GETs,
including the initial request. This limit also applies when both Browser
helpers capture the same URL. All attachment reads share a 240-second window
beginning with the first download or OpenAlex lookup, limited by any earlier
caller deadline. The window also covers the OpenAlex lookup and up to four
unique OpenAlex candidates. A challenged candidate can use one hidden helper
(up to five seconds) and one visible helper (up to 60 seconds). Both helpers
begin at the original challenge URL.

Each GET has up to 60 seconds for redirects and body reading, limited by the
remaining attachment budget. Temporary connection errors, timeouts and HTTP
408, 429, 500, 502, 503 or 504 can retry. Backoff starts at 500 ms and doubles
on the second wait, with up to 249 ms of added jitter. The Browser Session's
origin-scoped gate honors `Retry-After` for 429 and 503 before new dispatches,
including validated redirect targets. The operation stops waiting if the gate
extends beyond its wait budget, while the shared gate remains in effect.
Backoff and cooldown before dispatch leave the download permit available to
other requests. Issued requests hold their permit through settlement.

URL, DNS and redirect checks apply on every attempt. Requests preserve the
existing Session Cookie and referrer policy. Empty, partial and oversized
responses fail verification. When an identity-encoded length is supplied it
must match the received bytes. PDF verification requires an accepted MIME
type, a PDF header and an end-of-file marker. Content validation failures skip
GET retry. An explicit challenge or content mismatch on the locked BotBypass
domains (`sciencedirect.com`, `pdf.sciencedirectassets.com` and
`ncbi.nlm.nih.gov`, including attributed proxy-normalized URLs) can enter the
bounded helper flow. HTTP 404 skips the helpers. The old ItemSaver-specific
Amazon CAPTCHA adapter was removed with its writer VM and remains unverified.

Cancellation and original Document and Import authority checks guard download
dispatch and subsequent writes. DNS checks precede the final download authority
check. Attachment writes recheck Import authority after acquiring the write
permit and reading credentials, before each new POST. A confirmed parent and its known keys survive
an attachment failure. Download recovery never replays child creation, upload
or registration. Diagnostics record fixed failure evidence and attempt counts
without URLs, headers, Zotero keys or response data.

Real 10.0.6+ authorization, group permission changes, parent/PDF creation,
OpenAlex fallback and native UI acceptance remain separately authorized manual
checks. This investigation made no such accesses or writes.
