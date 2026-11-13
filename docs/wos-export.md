# WoS Plain Text export

Discover uses the saved Web of Science Access Service and its Core Collection page from Login. The export content is a fixed business selection, not a user
field editor in Allfold:

| Group | Selected fields |
| --- | --- |
| Author, Title, Source | Author(s), Title, Source, ISSN, PubMed ID |
| Abstract, Keyword, Addresses | Abstract, Document Type, Keywords |
| Cited References and Use | None |
| Funding and Other | None |

The native operation reads each leaf checkbox's `checked` state and changes
only mismatches. It saves, reopens Edit, and checks all leaf choices before
returning to the export dialog. A displayed count of eight is insufficient.
Missing, duplicated, disabled or unverifiable controls fail explicitly; there
is no fallback to another content preset. Group checkboxes are not leaf fields.

The task rechecks the current content, record range, Core Collection route and
captured page/document before exporting. The per-batch limit comes from the
current ending-range control's accessible description. The input's `max`
attribute is not a substitute, and an unknown limit is an error. The download
still requires the native event on the bound page, its observed URL chain and
the server-issued staging path; cancellation and document replacement retain
their existing refusal behavior. Results capture a lightweight native Document
binding; polling uses the bounded access probe rather than HTML. Export shares
one absolute request deadline across dialogs, verification and download polling.
Cancellation/expiry cancels the original DownloadItem and awaits its actual
terminal before releasing ownership; cleanup remains scoped to the captured
Document. The eight fields and URL-chain attribution above are unchanged.

## Selector evidence

On 2026-11-07, a task-isolated, normally authenticated Core Collection journal
query reached 15 results. Live DOM inspection confirmed this path:

```text
#export-trigger-btn → #exportToFieldTaggedButton
app-export-out-details → wos-select button[role=combobox]
#option-customFieldSelection → button.custom-field-selection (Edit)
app-custom-field-selection-dialog → Save selections
```

The custom component used `display: contents`; visibility is checked through
its enclosing modal rather than requiring a box on that component. Checkbox
IDs were generated; leaf `aria-label` values were stable within the observed
session. The selected values were `authorTitleSource_AUTHORS`,
`authorTitleSource_TITLE`, `authorTitleSource_SOURCE`, `authorTitleSource_ISSN`,
`authorTitleSource_PMID`, `abstractKeywordAddress_ABSTRACT`,
`abstractKeywordAddress_DOCTYPE` and `abstractKeywordAddress_KEYWORDS`.
Twenty other leaf controls were checked as unselected. Clicking Edit selected
Custom and opened its editor; Save returned to Plain Text. The ending-range
description specified 1,000 records per export, with no `max` attribute.
This observation is not a universal batch-size guarantee.

Saving and reopening retained the exact eight fields, including after an
export. Reopening the main export dialog reset its preset and range, so each
batch must reestablish them. A two-record Plain Text export contained two
closed records and a terminal `EF`, with the selected fields and automatically
included identifiers/date tags. The original export remains private; tests
use synthetic controls and records. This DOM observation does not by itself
prove every later WoS session or product Run succeeds.

In Integrated Run, each fully verified export batch may submit its DOI facts to
the parent's operation-local Work queue. Submission does no inline HTTP or Paper
write and does not alter these eight export choices. Count, path or duplicate-UT
failure prevents that batch callback. Final native conflict quarantine still
applies to all roots, including batches already submitted for Work lookup.
