# Workspace layout

ARRAY, Run, Journals, Kept and Settings use the same presentation controller and CSS skeleton:

```text
Navigation Rail | Content | Functional Sidebar | Tool Rail
                 ↑ Directory / Index flyout overlays Content
```

Window Chrome and Status reserve space outside Workbench Content. Ordinary pages fill that container; they do not subtract Header/Footer heights. The same Browser pane mounts in Kept Content for Compact/Focus, or in Workbench Content for a temporary Run task Focus view. Queue and returning to Run hide its native View without closing the Page or Session.

## Ownership and sizes

`frontend/ui/workspace-layout-model.js` defines target validation and allocation. `workspace-layout.js` owns each mounted host's flyout, expanded view, geometry and resize interaction. Controllers retain selection, task state and drafts. Hosts never mount, move or close a Reader and never render a Journal editor during resize.

| Size | Source / rule |
| --- | --- |
| `railWidth` | Target 48 px, allowed 36–72 px; two rails allocated first |
| `flyoutPreferredWidth` | Target 280 px, allowed 220–480 px; effective width limited to the space between rails |
| `sidebarPreferredWidth` | Target 320 px, allowed 260–560 px |
| Minimum Content | ARRAY 360 px; Journals 320 px, including internal padding |
| Minimum Docked Sidebar | 260 px, including its border and padding |
| Docked threshold | Two rail widths + workspace Content minimum + Sidebar minimum |
| Effective Sidebar | Docked: lesser of target and remaining space after Content minimum; Overlay: lesser of target and space between rails |
| Content width | Space between rails minus the Sidebar only when docked |
| Compact Browser preferredWidth | 960 px, allowed 320–2400 px; pane width including optional Browser Services, constrained by Content |
| Compact Browser preferredHeight | 300 px, allowed 140–1200 px; webpage area below trusted controls, constrained by remaining height |

The host measures its actual root Bounds with ResizeObserver. Its measured sizes are outputs, never preferences. At 48 px rails ARRAY docks from 716 px and Journals from 676 px. Collapsing a Sidebar returns all space between rails to Content. Overlay leaves Content's width unchanged. Local form/card changes use container sizing; GRID always uses `auto-fill` with a 200 px card minimum constrained to its own container.

The Electron window minimum is 600 × 480 logical pixels. The real Chromium DOM fixture checks ARRAY, Journals, Directory, Chrome/Status and the empty Browser body's usable space at this size and default zoom. This does not establish native webpage usability at every zoom or display scale.

## Interaction and preferences

- Hover opens a flyout after 160 ms; leaving its trigger and content closes after 280 ms. Crossing into the content cancels dismissal. Focus and click open it; arrow keys enter and move list focus, Enter applies selection. HTML drag hover also opens a Directory so existing Journal assignment/reordering remains available. Escape closes and restores the trigger without reopening. The host saves each Directory scope and Candidates/Kept Index scroll before hiding or changing preview, then restores it after showing the list.
- Journals previews a `directoryScope` without changing the Controller's active scope/filter. Clicking a category activates it and restores its group. Choosing a group closes Details; **Edit** opens that group's existing editor. ARRAY/GRID changes only the list rendering, leaving the editor DOM intact.
- Tool icons open on click, toggle the current view closed, or switch an open view. Journal selection opens Details. ARRAY selection updates Info without changing expansion. Each workspace retains its host and expansion while away. Browser presentation retains the mounted business DOM.
- ARRAY Keep/Reject remain in Content. Kept Queue owns Service statistics, batch scope, Prepare/Import and results; Paper identities are expandable details. Inline workflow status, Continue/Cancel and task-page handoff remain available during Browser interaction. Kept Access and Workflow mount the same configuration fields and controller used by autosave.
- Layout targets use the independent localStorage key `allfold.workbench-layout`. Developer inputs preview live; SAVE stores all targets (including Compact Browser preferredWidth/Height), RESET restores that baseline, ORIGIN uses source defaults without replacing the baseline. Ordinary pointer/keyboard Sidebar resize persists only its new preferred width on completion. Shrinking and host Zoom never write effective dimensions back into preferences. Developer outputs report the measured webpage dimensions separately.
- Invalid values fall back independently to defaults. Only when the new key is absent may an in-range legacy `allfold.journal-layout.right` seed the Sidebar target. Legacy left/columns state is ignored; no old layout controller or manual GRID controls remain. Browser Services, Archive and other UI preferences keep their own keys.
- The developer/status strip stays one row and scrolls horizontally. Messages have bounded internal scrolling. Window-level overlays and dialogs retain viewport bounds.

## Workspace ownership and retained boundaries

| Area | Container behavior / compatibility | Acceptance boundary |
| --- | --- | --- |
| Run | Overview and Provider Directory share a Rail/Flyout; provider configuration uses the Functional Sidebar. Host geometry and local container rules replace the previous directory/context window breakpoints. Existing fullscreen task surfaces remain. | Synthetic DOM checks cover normal and constrained layouts; real Provider and WoS results require separate service acceptance. |
| Kept | Service Directory is always a Flyout. Queue is the default; the same native Browser pane mounts in its main region. Access, Workflow, Service and Results use one Sidebar. Legacy Kept entry points navigate to the independent workspace. | Local synthetic task/page interaction is separate from real institution and Zotero acceptance. |
| Settings | Application/Appearance/Data/Developer use one bounded column; System diagnostics open through the Tool Rail. Container rules adapt fields without globally stacking workspace columns. | File, Reset and credential operations retain their own previews/confirmation. |
| Archive | No new rails or visual redesign. Canvas retains its existing window geometry, inspection transitions and shared Reader lifecycle. Disable preference and the Index flyout's ARCHIVE entry remain. | DOM tests check restoration mechanics; the full animated Archive experience is not reaccepted by Browser tests. |
| CSS/build | Window variables remain in shell rules; workspace dimensions stay local. `kept-app.css` remains generated film styling through the existing build. | Generated resources are rebuilt; vendor sources and animation assets remain unchanged. |

## Verification boundaries

`electron/tests/workspace-layout.test.cjs` covers allocation, validation, preferences and host interactions. `workspace-layout-dom.test.cjs` runs actual Electron/Chromium with a temporary profile and synthetic HTTP responses, checks real geometry and editor/Reader node identity, and dispatches hover, keyboard and resize events. It also checks Archive restoration and an empty synthetic Browser round trip. It performs no external calls or native saving. Build UI resources before running this test, as required by the normal source setup. Optional `ALLFOLD_LAYOUT_SCREENSHOTS=<directory>` saves local rendered fixtures; those outputs are not source artifacts.

Limited computer-use acceptance with synthetic data checked Index/Info, Journal selection across ARRAY/GRID, group filtering and Details collapse, Escape focus return, Service chooser cancellation, and empty synthetic Browser return. It did not establish native page Session behavior, pointer dragging, exact hover timing, touch or reliable independent scroll behavior.

The following real-UI checks are a reference for changes affecting those behaviors, not requirements for every PR. Existing Electron/Chromium fixtures already establish the synthetic results described above and below. Select additional real-UI checks only for affected behavior the fixtures cannot cover. Browser control, external accounts, real user-data edits, Zotero and PDF operations require separate task-specific authorization:

1. Real pointer hover across trigger/flyout boundaries, delayed dismissal, touch activation, Tab/Shift-Tab and Escape. Drag/keyboard-resize Sidebar at wide/narrow bounds; inspect clipping and focus with long Directory and Details content.
2. At 600 × 480 and larger sizes, check Reader, list, flyout, forms and workflow scroll regions; vary host zoom, display scale, low height, messages and developer controls. Verify preferred width after repeated narrow/wide changes and restart.
3. Real-data Group/Service/Label edits, destructive confirmations and Cover upload/crop/search. Isolated tests cover ordinary autosave, error/conflict recovery and assignment Undo; real covers and user data are outside those fixtures.
4. Native Browser pages and Session across Allfold return, tasks and dialog suspension; Run WoS and Kept Prepare/Import in both presentation modes, task-page association, polling, Continue/Cancel and uncertain save handling. Parent items and PDFs require separate authorized Zotero inspection.
5. Re-enable Archive and verify actual Canvas inspection/return, shared Reader, Archive layout/debug preferences, and recovery from both enabled and disabled states. The DOM test proves restoration mechanics, not the full animated Archive experience.

## Task Browser synthetic acceptance

Three real Electron fixtures use temporary profiles and loopback HTTP pages. All reject
non-fixture HTTP(S) requests; none starts Python, accesses an account/institution,
uses a real CAPTCHA provider or saves to Zotero.

- `browser-presentation-dom.fixture.cjs` exercises production Runtime, Presentation,
  trusted IPC/preload and Layout Host inside a small synthetic shell. It checks the
  320 × 140 viewport, multiple Compact heights, preferences, host reload, webpage
  dialogs and trusted Popover occlusion.
- `browser-workspaces-dom.fixture.cjs` loads the shipped **built index and controllers**
  with synthetic API responses. It checks actual Kept Queue / Compact / Focus / Restore,
  Flyout, Overlay Sidebar, History Dialog, restored inline/fullscreen Kept, cancellation
  and acknowledgement, and restored fullscreen Run WoS with exact task-page handoff.
  Its test runs with both macOS scrolling-only and always-visible scrollbars through
  process-local Cocoa arguments; it does not change the system preference.
- `enrich-workspace-dom.fixture.cjs` independently loads the built UI with the target
  Paper present in every initial Workspace response. It waits for that Paper and
  usable Reader controls before starting Enrich, then checks background layout,
  task-bound Browser entry/return, real verification input, retained Page/Session/Cookie,
  focus and cancel controls, one start/zero cancels and completion refresh. It runs
  both scrollbar modes without depending on the preceding Kept/Run scenarios.

The shipped Kept/Run and Enrich fixtures report candidate IDs, target-Paper presence,
Workspace readiness/busy state, dialogs/focus/navigation, in-flight fixture Workspace
responses, recent request routes and native presentation state on failure. A renderer
inspection failure is recorded without replacing the original test error.

Run after the normal UI build:

```sh
node --test --test-concurrency=1 electron/tests/browser-presentation-dom.test.cjs electron/tests/browser-workspaces-dom.test.cjs electron/tests/enrich-workspace-dom.test.cjs
ALLFOLD_BROWSER_SCREENSHOTS=/tmp/allfold-browser-acceptance node --test electron/tests/browser-presentation-dom.test.cjs
ALLFOLD_BROWSER_WORKSPACES_SCREENSHOTS=/tmp/allfold-browser-workspaces node --test electron/tests/browser-workspaces-dom.test.cjs
ALLFOLD_ENRICH_WORKSPACE_SCREENSHOTS=/tmp/allfold-enrich-workspace node --test electron/tests/enrich-workspace-dom.test.cjs
```

The optional directories contain paired trusted-host and native-page PNGs and
`measurements.json` for Browser geometry; the shipped Kept/Run and independent Enrich
fixtures separate `WhenScrolling` and `Always` screenshot directories.
Electron host `capturePage()` excludes child Views; `-page.png`
records the actual webpage viewport separately. The fixtures briefly show their own
Window because macOS supplies no usable native child-View compositor surface for real
input/capture in a never-shown Window. Outputs remain local, outside source artifacts.

Executed on macOS / Electron 45 on 2026-11-04. The shipped UI measurements below use
Window dimensions including its 32 px native title bar; the 600 × 480 Window therefore
has 600 × 448 content bounds. DIP rounding can clip one fractional CSS pixel.

| Shipped UI Window / host Zoom | Presentation | Native webpage viewport (DIP) |
| --- | --- | --- |
| 1200 × 800 / 1 | Compact, 960 × 300 target; Browser Services expanded | 666 × 299 |
| 1200 × 800 / 1 | Focus | 1092 × 518 |
| 1200 × 800 / 1 | Focus with TOOLS expanded | 1092 × 482 |
| 600 × 480 / 1 | Compact | 492 × 174 |
| 600 × 480 / 1 | Focus | 492 × 210 |
| 600 × 480 / 1.25 | Compact | 464 × 109 |
| 600 × 480 / 1.25 | Focus | 464 × 151 |
| 600 × 480 / 1.25 | Focus with active inline task controls and two scope/count rows | 464 × 109 |
| 1200 × 800 / 1 | Run fullscreen task handoff | 1200 × 568 |

The 300 px default fits the complete synthetic challenge at wide bounds. The separate
320 × 140 flat test and constrained shipped views remain operable through actual
mouse input and keyboard scrolling; they do not imply that a real challenge fits without
Focus. Focus uses the available main area, temporarily omits Browser Services, and
starts with its address/maintenance tools collapsed behind TOOLS. Compact and Focus
retain independent tool expansion choices; returning to Compact restores the Services
preference. Empty status text and empty workflow hosts consume no extra viewport.
Preferred dimensions never receive effective measurements after resize or Zoom.

With always-visible scrollbars, the shipped 600 × 480 window measures 492 × 148
in Compact and 492 × 184 in Focus at Zoom 1. At Zoom 1.25 it measures 464 × 109
in Compact, 464 × 125 in idle Focus and 464 × 109 in active inline Focus. The
tabbar uses one horizontal scrolling region. In a constrained Browser container,
the trusted controls can scroll independently and the webpage retains up to an
88 CSS-pixel minimum strip, limited by the container itself. TOOLS remains an
explicit, operable control; the narrower viewport still needs webpage scrolling.

Actual Chromium `sendInputEvent` mouse/key/wheel interactions check checkbox activation,
Tab, Shift+Tab, Space, code entry, Enter submission, native scrolling and the final
control. The shipped 600 × 480 / Zoom 1.25 Compact, Focus and active-inline cases all
complete the synthetic challenge successfully. The populated active batch shows planned
3, processed 2, confirmed parents 1 and pending 1; its narrow counter row can receive
keyboard focus and scroll horizontally. Queue's real task-page entry and statistics
retain nonzero scrollable height at constrained sizes.

Assertions retain the physical Page ID, Session object, Cookie, page-load token,
webpage form/focused element, workflow/task association and legal cancellation identity.
Trusted Flyout / Sidebar / Dialog / Popover coverage removes the native View while the
Page stays alive. Fullscreen task surfaces remain open while hidden for handoff and
restore their controls/focus on return. A host reload clears Presentation at navigation
start and again when the replacement main document commits. The latter discards any
last layout sent by the outgoing renderer while the response was pending. A real
reload/resize regression checks that the new host initially hides the old native View
before presenting the same Page and Session; a same-document navigation retains the
existing View. SAVE / RESET / ORIGIN, malformed storage fallback
and saved-preference restoration are also checked.

Real hCaptcha/MFA, institutional authentication, account popups and actual Zotero/PDF
results remain separate, explicitly authorized acceptance. These local synthetic pages
do not establish real CAPTCHA compatibility or every external site's usable minimum size.

## Source categories and Paper dates

Journals manages followed journals. Paper Reader shows the bibliographic source
name and four dates at their available precision. ARRAY **Info** keeps the
bibliographic date and chronological evidence, including original source labels,
record IDs, preprint version details and source links. Its bioRxiv/medRxiv lookup
targets the selected Paper and reports the outcome in place. DOI-free Papers
remain reviewable and locally editable. Unavailable external actions explain
their DOI requirements. Webpage Enrich remains independent.
Run result fixtures also render Integrated retrieval/status counts and per-source
failures, unsupported old Integrated snapshots, and WoS Journal Coverage, export
batches and date/diagnostic explanations at constrained bounds. They use synthetic
API results and cannot establish real-service retrieval. Rare date/version cases
and Translator Accepted/event-only responses use synthetic automatic tests;
real samples are optional supplementary evidence.
See [change-scoped Provider acceptance](providers.md#old-data-and-manual-acceptance).
