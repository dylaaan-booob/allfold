# Workspace layout

ARRAY, Workflows, Journals and Settings use the same presentation controller and CSS skeleton:

```text
Navigation Rail | Content | Functional Sidebar | Tool Rail
                 ↑ Directory / Index flyout overlays Content
```

Window Chrome and Status reserve space outside Workbench Content. Browser fills that container with a left navigation rail, grouped Tabs flyout and a native webpage beneath the address bar. Returning to the business workspace hides the native View while retaining the Page and Session.

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

The host measures its actual root Bounds with ResizeObserver. Its measured sizes are outputs, never preferences. At 48 px rails ARRAY docks from 716 px and Journals from 676 px. Collapsing a Sidebar returns all space between rails to Content. Overlay leaves Content's width unchanged. Local form/card changes use container sizing; GRID always uses `auto-fill` with a 200 px card minimum constrained to its own container.

The Electron window minimum is 600 × 480 logical pixels. The Chromium fixtures check ARRAY, Journals and native Browser at this size. Native Browser tests also exercise host zoom at 1.25 with synthetic pages.

## Interaction and preferences

- Hover opens a flyout after 160 ms; leaving its trigger and content closes after 280 ms. Crossing into the content cancels dismissal. Focus and click open it; arrow keys enter and move list focus, Enter applies selection. HTML drag hover also opens a Directory so existing Journal assignment/reordering remains available. Escape closes and restores the trigger without reopening. The host saves each Directory scope and Candidates/Kept Index scroll before hiding or changing preview, then restores it after showing the list.
- Journals previews a `directoryScope` without changing the Controller's active scope/filter. Clicking a category activates it and restores its group. Choosing a group closes Details; **Edit** opens that group's existing editor. ARRAY/GRID changes only the list rendering, leaving the editor DOM intact.
- Tool icons open on click, toggle the current view closed, or switch an open view. Journal selection opens Details. ARRAY selection updates Info without changing expansion. Each workspace retains its host and expansion while away. Browser presentation retains the mounted business DOM.
- ARRAY Keep/Reject remain in Content. Workflows contains Login, Discover and Import to Zotero. Task-page handoff opens the shared Browser while workflow status and controls stay in their original surface.
- Layout targets use the independent localStorage key `allfold.workbench-layout`. Developer inputs preview live; SAVE stores all targets, RESET restores that baseline, ORIGIN uses source defaults without replacing the baseline. Ordinary pointer/keyboard Sidebar resize persists only its new preferred width on completion. Shrinking and host Zoom never write effective dimensions back into preferences.
- Invalid values fall back independently to defaults. Only when the new key is absent may an in-range legacy `allfold.journal-layout.right` seed the Sidebar target. Legacy left/columns state is ignored; no old layout controller or manual GRID controls remain. Archive and other UI preferences keep their own keys.
- The developer/status strip stays one row and scrolls horizontally. Messages have bounded internal scrolling. Window-level overlays and dialogs retain viewport bounds.

## Workspace ownership and retained boundaries

| Area | Container behavior / compatibility | Acceptance boundary |
| --- | --- | --- |
| Discover | Overview and Provider Directory share a Rail/Flyout; provider configuration uses the Functional Sidebar. Host geometry and local container rules replace the previous directory/context window breakpoints. Existing fullscreen task surfaces remain. | Synthetic DOM checks cover normal and constrained layouts; real Provider and WoS results require separate service acceptance. |
| Import to Zotero | Service Directory uses the shared Flyout. Legacy Kept entry points navigate to this Workflows view. | Local synthetic task/page interaction is separate from real Zotero acceptance. |
| Browser | One grouped Tabs flyout opens from the left rail, with the webpage in Focus. Search and History temporarily suspend the native View. | Rendered fixtures use synthetic pages and check Page identity, overlays, input, focus and host zoom. |
| Settings | Application/Appearance/Data/Developer use one bounded column; System diagnostics open through the Tool Rail. Container rules adapt fields without globally stacking workspace columns. | File, Reset and credential operations retain their own previews/confirmation. |
| Archive | No new rails or visual redesign. Canvas retains its existing window geometry, inspection transitions and shared Reader lifecycle. Disable preference and the Index flyout's ARCHIVE entry remain. | DOM tests check restoration mechanics; the full animated Archive experience is not reaccepted by Browser tests. |
| CSS/build | Window variables remain in shell rules; workspace dimensions stay local. The build bundles the ARRAY and Import controller. | Generated resources are rebuilt; the Discover animation retains its existing assets. |

## Verification boundaries

`electron/tests/workspace-layout.test.cjs` covers allocation, validation, preferences and host interactions. `workspace-layout-dom.test.cjs` runs actual Electron/Chromium with a temporary profile and synthetic HTTP responses, checks real geometry and editor/Reader node identity, and dispatches hover, keyboard and resize events. It also checks Archive restoration and an empty synthetic Browser round trip. It performs no external calls or native saving. Build UI resources before running this test, as required by the normal source setup. Optional `ALLFOLD_LAYOUT_SCREENSHOTS=<directory>` saves local rendered fixtures; those outputs are not source artifacts.

Limited computer-use acceptance with synthetic data checked Index/Info, Journal selection across ARRAY/GRID, group filtering and Details collapse, Escape focus return, Service chooser cancellation, and empty synthetic Browser return. It did not establish native page Session behavior, pointer dragging, exact hover timing, touch or reliable independent scroll behavior.

The following real-UI checks are a reference for changes affecting those behaviors, not requirements for every PR. Existing Electron/Chromium fixtures already establish the synthetic results described above and below. Select additional real-UI checks only for affected behavior the fixtures cannot cover. Browser control, external accounts, real user-data edits, Zotero and PDF operations require separate task-specific authorization:

1. Real pointer hover across trigger/flyout boundaries, delayed dismissal, touch activation, Tab/Shift-Tab and Escape. Drag/keyboard-resize Sidebar at wide/narrow bounds; inspect clipping and focus with long Directory and Details content.
2. At 600 × 480 and larger sizes, check Reader, list, flyout, forms and workflow scroll regions; vary host zoom, display scale, low height, messages and developer controls. Verify preferred width after repeated narrow/wide changes and restart.
3. Real-data Group/Service/Label edits, destructive confirmations and Cover upload/crop/search. Isolated tests cover ordinary autosave, error/conflict recovery and assignment Undo; real covers and user data are outside those fixtures.
4. Native Browser pages and Session across Allfold return, tasks and dialog suspension; Login, Discover and Import handoff, task-page association, polling, Continue/Cancel and uncertain save handling. Parent items and PDFs require separate authorized Zotero inspection.
5. Re-enable Archive and verify actual Canvas inspection/return, shared Reader, Archive layout/debug preferences, and recovery from both enabled and disabled states. The DOM test proves restoration mechanics, not the full animated Archive experience.

## Task Browser synthetic acceptance

The Electron fixtures use temporary profiles and loopback HTTP pages. They reject
non-fixture HTTP(S) requests.

- `browser-presentation-dom.fixture.cjs` exercises the production Runtime,
  Presentation, preload and layout controller in a synthetic shell. It checks
  viewport bounds during loading, long messages, zoom, host reload, dialog
  suspension and background updates while a tab button has focus.
- `browser-workspaces-dom.fixture.cjs` loads the built UI with synthetic APIs.
  It checks the four navigation entries, keyboard Quick Open for local records
  and commands, CARSI/Service/Other groups, collapse and focus, Search/History
  suspension, and Discover task-page handoff.
- `enrich-workspace-dom.fixture.cjs` loads the built UI with a synthetic Paper.
  It checks Enrich Browser handoff, verification input, focus and cancel controls,
  and the refreshed Paper after completion.

The shipped Workflows and Enrich fixtures run in both scrolling-only and
always-visible scrollbar modes using process-local macOS arguments. They report
renderer and native presentation state on failure. Run after the UI build:

```sh
node --test --test-concurrency=1 electron/tests/browser-presentation-dom.test.cjs electron/tests/browser-workspaces-dom.test.cjs electron/tests/enrich-workspace-dom.test.cjs
```

Optional `ALLFOLD_BROWSER_SCREENSHOTS`, `ALLFOLD_BROWSER_WORKSPACES_SCREENSHOTS`
and `ALLFOLD_ENRICH_WORKSPACE_SCREENSHOTS` directories receive local screenshots
and measurements. Host `capturePage()` excludes child Views. The corresponding
`-page.png` records the webpage viewport separately.

The fixtures use real Chromium input for checkbox, keyboard, scroll and submit
interactions and retain the Page ID, Session, cookie, load token and task identity
across presentation changes. Host reload clears presentation at navigation start
and when the replacement document commits. Real institution login, hCaptcha/MFA,
Zotero writes and PDFs require separate acceptance.

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
