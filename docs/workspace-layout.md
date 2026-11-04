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

Manual acceptance still required:

1. Real pointer hover across trigger/flyout boundaries, delayed dismissal, touch activation, Tab/Shift-Tab and Escape. Drag/keyboard-resize Sidebar at wide/narrow bounds; inspect clipping and focus with long Directory and Details content.
2. At 600 × 480 and larger sizes, check Reader, list, flyout, forms and workflow scroll regions; vary host zoom, display scale, low height, messages and developer controls. Verify preferred width after repeated narrow/wide changes and restart.
3. Real-data Group/Service/Label edits, destructive confirmations and Cover upload/crop/search. Isolated tests cover ordinary autosave, error/conflict recovery and assignment Undo; real covers and user data are outside those fixtures.
4. Native Browser pages and Session across Allfold return, tasks and dialog suspension; Run WoS and Kept Prepare/Import in both presentation modes, task-page association, polling, Continue/Cancel and uncertain save handling. Parent items and PDFs require separate authorized Zotero inspection.
5. Re-enable Archive and verify actual Canvas inspection/return, shared Reader, Archive layout/debug preferences, and recovery from both enabled and disabled states. The DOM test proves restoration mechanics, not the full animated Archive experience.

## Task Browser synthetic acceptance

`electron/tests/browser-presentation-dom.fixture.cjs` runs the production BrowserRuntime,
BrowserPresentation, trusted IPC/preload, Workbench and Layout Host against a local HTTP
challenge page in a disposable Electron profile. It briefly shows its own Window because
macOS does not provide a compositor surface for real child-View input/capture in a never-shown
Window. Both Sessions reject non-fixture HTTP(S) requests. It uses no Python process,
real account, institution, CAPTCHA provider or Zotero.

Run the fixture through:

```sh
node --test electron/tests/browser-presentation-dom.test.cjs
ALLFOLD_BROWSER_SCREENSHOTS=/tmp/allfold-browser-acceptance node --test electron/tests/browser-presentation-dom.test.cjs
```

The optional directory contains paired trusted-host and native-page PNGs plus
`measurements.json`. Electron's host `capturePage()` excludes child Views; the `-page.png`
image records the actual webpage viewport separately. These local outputs are not source
artifacts. The fixture uses a small synthetic business shell with production presentation
modules; its geometry does not certify every real Kept status/error message or third-party
page layout.

Executed on macOS / Electron 45 on 2026-11-04 (Window dimensions include native Chrome;
this environment gave a 32 px title bar):

| Window / host Zoom | Presentation | Native webpage viewport (DIP) |
| --- | --- | --- |
| 1200 × 800 / 1 | Default Compact, 960 × 300 pane target, Services expanded | 666 × 300 |
| 1200 × 800 / 1 | Compact height targets 140 / 240 / 300 / 420 | 666 × each target height |
| 1200 × 800 / 1 | Narrow, flat Compact | 320 × 140 |
| 600 × 480 / 1 | Compact target 640 × 240; Focus; Restore | 504 × 225 (container limited) |
| 600 × 480 / 1 | Run task Focus | 600 × 255 |
| 600 × 480 / 1.25 | Compact and Focus | 480 × 147 (container and Zoom limited) |

The 300 px default lets the complete synthetic challenge fit at wide bounds; 140 px
remains usable through scrolling and keyboard focus but is deliberately a lower bound,
not a claim that a real challenge fits without Focus. Focus uses additional main-area
space when available; at the minimum Window the container can constrain both modes to
the same height. Browser Services yields below a 320 px webpage plus 180 px panel and
is omitted from Run task Focus. The address bar stays one row while maintenance is
closed, preserving height at non-default Zoom.

Actual Chromium `sendInputEvent` mouse/key/wheel interactions checked the checkbox,
Tab, Shift+Tab, Space, code entry, Enter submission, a local webpage dialog/Escape,
native scrolling, the final control, Page switching, Compact/Focus/Restore/Queue,
Flyout, Overlay Sidebar, trusted Dialog, fullscreen task-surface suspension and Run
return focus. Assertions also check selected Page ID, Session object and Cookie,
page-load token, focused webpage element, preserved input, exact Run task association,
unchanged task ownership, native removal during trusted overlays, resize/Zoom clipping,
SAVE/RESET/ORIGIN, malformed storage fallback and host-reload preference restoration.

Real hCaptcha/MFA, institutional authentication, account popups and actual Zotero/PDF
results remain separate, explicitly authorized acceptance. The local component is a
synthetic challenge and does not establish real CAPTCHA compatibility.
