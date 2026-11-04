# Workspace layout

ARRAY and Journals use the same presentation controller and CSS skeleton:

```text
Navigation Rail | Content | Functional Sidebar | Tool Rail
                 ↑ Directory / Index flyout overlays Content
```

Window Chrome and Status reserve space outside Workbench Content. Ordinary pages fill that container; they do not subtract Header/Footer heights. Browser remains a separate full view with its existing native presentation and independent Services panel.

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

The Electron window minimum is 600 × 480 logical pixels. The real Chromium DOM fixture checks ARRAY, Journals, Directory, Chrome/Status and the empty Browser body's usable space at this size and default zoom. This does not establish native webpage usability at every zoom or display scale.

## Interaction and preferences

- Hover opens a flyout after 160 ms; leaving its trigger and content closes after 280 ms. Crossing into the content cancels dismissal. Focus and click open it; arrow keys enter the list. Escape closes and restores the trigger without reopening. Each list scrolls independently.
- Journals previews a `directoryScope` without changing the Controller's active scope/filter. Clicking a category activates it and restores its group. Choosing a group closes Details; **Edit** opens that group's existing editor. ARRAY/GRID changes only the list rendering, leaving the editor DOM intact.
- Tool icons open on click, toggle the current view closed, or switch an open view. Journal selection opens Details. ARRAY selection updates Info without changing expansion. Each workspace retains its host and expansion while away. Browser hides Allfold without replacing its DOM.
- ARRAY Keep/Reject and Kept's direct Import actions live in Content. Inline workflow status, Continue/Cancel and task-page handoff also live in Content, with a bounded scroll region for long messages. Import records and Paper metadata remain in Info.
- Layout targets use the independent localStorage key `allfold.workbench-layout`. Developer inputs preview live; SAVE stores all targets, RESET restores that baseline, ORIGIN uses source defaults without replacing the baseline. Ordinary pointer/keyboard Sidebar resize persists only its new preferred width on completion. Shrinking never writes preferences.
- Invalid values fall back independently to defaults. Only when the new key is absent may an in-range legacy `allfold.journal-layout.right` seed the Sidebar target. Legacy left/columns state is ignored; no old layout controller or manual GRID controls remain. Browser Services, Archive and other UI preferences keep their own keys.
- The developer/status strip stays one row and scrolls horizontally. Messages have bounded internal scrolling. Window-level overlays and dialogs retain viewport bounds.

## Run, Settings and Archive source audit

| Area | Current dependency / compatibility | Follow-up |
| --- | --- | --- |
| Run | `settings.css` retains its 1000 px Context-to-bottom and 600 px directory/body stacking rules, scoped to `#s-run`. Private `--run-index-width`, `--run-context-width`, `--run-gap` replace shared ARRAY/Journals geometry. `run.css` and the Kept film remain window-level task surfaces. | Convert Run's database/context sizing to its container when its Content layout is redesigned; verify long task results and low-height inline controls. |
| Settings | System Sidebar keeps its own `--settings-system-width`; 1000 px stacking and 700 px form changes remain. File menu, institution search and dialogs intentionally use viewport bounds. | Replace window breakpoints with Settings container queries; refine independently scrolling main/System panes at low heights. |
| Archive | No new rails are added. Canvas still intentionally spans `100vw`; `app.js` measures its canvas/root and uses Archive-specific pane/Reader/control geometry. Inspection and shared Reader move only during existing business entry/exit. Archive debug height is capped by its parent. Disable preference and the Index flyout's restored ARCHIVE entry remain. | Convert Canvas/camera to a local container only as a separate Archive redesign, together with inspection transitions and widget placement. Accept actual camera/Reader geometry and resize behavior with Archive re-enabled. |
| CSS/build | Window variables remain in shell rules; new host variables are local. Old ARRAY/Journals stacking, Context widths, column overrides and resize/debug selectors are deleted. `kept-app.css` is generated film styling through the existing UI build, not an editable layout source. | Keep future Content rules local; avoid reintroducing global workspace column widths. |

## Verification boundaries

`electron/tests/workspace-layout.test.cjs` covers allocation, validation, preferences and host interactions. `workspace-layout-dom.test.cjs` runs actual Electron/Chromium with a temporary profile and synthetic HTTP responses, checks real geometry and editor/Reader node identity, and dispatches hover, keyboard and resize events. It also checks Archive restoration and an empty synthetic Browser round trip. It performs no external calls or native saving. Build UI resources before running this test, as required by the normal source setup. Optional `ALLFOLD_LAYOUT_SCREENSHOTS=<directory>` saves local rendered fixtures; those outputs are not source artifacts.

Limited computer-use acceptance with synthetic data checked Index/Info, Journal selection across ARRAY/GRID, group filtering and Details collapse, Escape focus return, Service chooser cancellation, and empty synthetic Browser return. It did not establish native page Session behavior, pointer dragging, exact hover timing, touch or reliable independent scroll behavior.

Manual acceptance still required:

1. Real pointer hover across trigger/flyout boundaries, delayed dismissal, touch activation, Tab/Shift-Tab and Escape. Drag/keyboard-resize Sidebar at wide/narrow bounds; inspect clipping and focus with long Directory and Details content.
2. At 600 × 480 and larger sizes, check Reader, list, flyout, forms and workflow scroll regions; vary host zoom, display scale, low height, messages and developer controls. Verify preferred width after repeated narrow/wide changes and restart.
3. Edit Group/Service/Label, assign/reorder/delete, Save/error/Undo, and Cover upload/crop/search. Resize and open Browser while a form is focused; verify raw draft, dirty state and both list/editor scroll positions.
4. Native Browser pages and Session across Allfold return, tasks and dialog suspension; Run WoS and Kept Prepare/Import in both presentation modes, task-page association, polling, Continue/Cancel and uncertain save handling. Parent items and PDFs require separate authorized Zotero inspection.
5. Re-enable Archive and verify actual Canvas inspection/return, shared Reader, Archive layout/debug preferences, and recovery from both enabled and disabled states. The DOM test proves restoration mechanics, not the full animated Archive experience.
