# Shared Browser Session

The application keeps `session.fromPartition('allfold')`. One
`SharedSessionEvents` lifetime installs the native request/header/redirect/error,
completion and `will-download` listeners. BrowserRuntime and Browser identity
subscribe to that entry; WoS registers an attempt before its export action.
Finishing a task disposes its registrations, never the Session listeners.
Shutdown drains owned work, pages and native items before disposing the entry.

Request handlers run synchronously in registration order. Each sees the headers
already composed by the preceding handler and returns the next header state.
The entry strips private markers last and calls Electron's callback exactly once.
A throwing or asynchronous handler cancels that request rather than retaining
its callback. Session identity supplies the existing HTTPS UA/Client Hints and
synchronous frame preload. Chromium continues to own cookies and authentication.
The unused Translator/item-saver Cookie/CDP adapter and its token/merge tests are
removed; no Cookie export, manual login synchronization or cross-origin
Authorization forwarding replaces it.

BrowserRuntime records workflow/task/request/attempt and Page/native-frame facts
when a real native request begins; a known preload Document ID is included when
available. Absence remains absence. Host fetches use `sessionEvents.fetch` with
an explicit owner, attempt, parent deadline, signal and authority validator.
Covers is the current production host-fetch consumer and keeps
`credentials: 'omit'`. A random marker associates a fetch with Chromium's request
ID at `onBeforeSendHeaders`, then is removed before consumers or the network see
it. Redirects retain that native request association. Returned request facts
contain actual observed redirect/response URLs and status, never `Response.url`
or a private Electron Response field. Terminal native events remove request-ID
references; cancellation and failed dispatch remove unused marker registrations.
No URL, selected tab, Service label or request ordering supplies ownership.

One `BrowserCooldown` belongs to this Session lifetime. Main-frame responses and
explicitly associated requests observe actual response origins: 429 uses valid
Retry-After or the existing one-second default; 503 requires valid Retry-After.
Unowned subresources retain the existing exclusion. Active waits can only extend,
are bounded by 30 seconds and the parent deadline, and recheck cancellation and
authority after waiting. Independent origins remain independent. Chromium's
existing redirect/authentication chain proceeds without host action replay.

## Managed download contract

`registerDownload` captures owner/attempt, source WebContents, native frame,
Document, expiry, signal, synchronous authority validator and a previously
prepared staging path. Exactly one matching registration may receive an item.
The path is assigned synchronously inside `will-download`, before business
callbacks. The source frame and, when available, initiator origin must match the
captured source Document. URL chains remain business evidence, not a substitute
for native source ownership. WoS additionally keeps its exact results Document,
known overlay rebinding, eight-field/range checks, observed export links and
server-issued path validation.

A missing frame cannot be assigned to the current attempt. An event from an
explicit managed source can be rejected within that Page's scope; missing source
events and unrelated user pages remain unclaimed. A task Page with no registered
download rejects its own unexpected downloads. Multiple candidate registrations
or duplicate items fail the affected attempt and cancel its items, without
touching another Page's item.

Cancellation and timeout cancel an accepted item but retain its terminal promise
until real `done`. An `updated(interrupted)` observation cancels rather than
resumes the item; its eventual `done` state remains distinct from that observation.
WoS reports the interruption after that actual terminal. `waitForDownloads`
waits for all tracked items, or only one source WebContents, and is not shortened
by a task's aborted signal. Source pages remain retained through that wait.

Disposing a dispatched attempt that never received an item retains a source/frame
guard until the original deadline or at least 30 seconds after disposal, whichever
is later; physical source destruction removes it sooner. This bounds late-event
protection while refusing an indistinguishable newer attempt on that source.
Verified pre-click WoS DOM failures do not create this guard and may retry.
No cancelled response is replaced by a GET, HEAD or `downloadURL` call.

## Electron 45.0.0 capability evidence

`session-downloads.test.cjs` runs the shared production event/router implementation
with a temporary Electron profile, local HTTP server and temporary files through
the normal Electron test entry. It fixes the runtime assertion at 45.0.0.

| Controlled entry | Observed result |
| --- | --- |
| Main-frame form POST, attachment response | Original DownloadItem completed; exact original bytes; one POST with original body, no GET/HEAD |
| Main-frame inline PDF form POST | Scoped response-header override produced original DownloadItem; one POST, exact bytes |
| iframe inline form POST | Source WebContents and the originating child frame matched; original item completed once |
| Popup inline form POST | Popup WebContents/frame matched independently of its opener; original item completed once |
| Two source pages, identical URL | Two independent items/paths/terminal states; two original POSTs, no FIFO or URL assignment |
| No item by expiry, then a late native item | Bounded old-source guard cancelled it; a newer registration could not claim it |
| Multiple registrations on one source/frame | Item cancelled as ambiguous; neither callback received ownership |
| Source-less `Session.downloadURL` | Native source and frame were null; the router left the unrelated item alone. A fixture-only listener supplied its path |
| Slow POST, source destroyed before headers/handoff | One original request; no item within the bounded observation window |
| Slow attachment POST, source destroyed after handoff | Original item completed; no replacement request |
| Source destroyed after real completion | Completed item and file stayed valid |
| Explicit cancellation during slow transfer | Real `done(cancelled)`; no resume or replacement request |
| Transport disconnect during transfer | Native `updated(interrupted)`, then managed cancel and real `done(cancelled)`; no resume or replacement request |
| Parallel `session.fetch` POST through 307/429 | Distinct native request IDs and observed redirect/final-response facts; later-operation cooldown cancellation sent no request; an independent origin remained usable; server saw no private marker |

Main-frame, iframe and popup form cases supplied a non-null fourth frame argument
on this macOS fixture. Source-present/null-frame refusal is also exercised at the
native event boundary in `session-events.test.cjs`; no reliable real-site mapping
for that case is claimed. `Session.downloadURL` above only tests missing-source
isolation and does not establish original POST/inline preservation.

The measured early-close result covers the local attachment form entry only.
Production retains all managed sources until real item terminal; iframe/popup,
authentication redirects and real WoS early-close behavior are not inferred from
that sample. Inline override is opt-in to an exact registered source/frame and
the response's declared MIME type; unrelated pages' responses are unchanged.
These fixtures establish mechanisms, not PDF validation or a permanent-file/UI
product. Real CARSI/WoS/accounts and CAPTCHA remain separately authorized live
acceptance. WF09/WF10 own the later PDF transport and product behavior.

The interruption fixture also checks native stderr for Chromium assertion
failures. Electron 45's DownloadItem observer list rejects reentrant cancellation
inside `updated`; the router defers that cancel to the next event-loop turn and
continues retaining the item until real `done`.
