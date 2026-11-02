# Research scope and Services

Each configuration keeps its own followed Journals, order, Groups, Labels, Access Services and default Service assignments in SQLite. Sharing a Markdown file adds a research scope to the receiving configuration; it does not replace that configuration or change another configuration.

## Identify and import Journals

Choose **Import Research Scope**, select a UTF-8 Markdown file, review its Preview, then explicitly confirm the rows to add. Names are looked up in the local Registry first, with OpenAlex as a fallback. ISSN/eISSN values are checksum-validated and take precedence over names. Source records that share identifiers can contribute evidence to the same candidate. If identity remains ambiguous, choose a candidate; a row without a valid identifier stays in Preview rather than becoming a saved Journal.

Existing Journals are skipped by default, including their Group, Labels and default Service. New registry entries and Journals retain their source order after existing entries. Preview identifies duplicates, identity conflicts, verified Services, Services requiring attention, pending Resolver queries and Unresolved rows. Resolve unsaved Settings before confirmation; stale revisions require a fresh Preview.

## Choose a Service

CARSI Service names must match the official Catalog's `production` exactly. A shared file's `svc_...` identifiers are local to its author and are never treated as portable identities. Import reuses the receiving configuration's matching Service or creates a new local identity. An explicit Journal → CARSI choice, such as INFORMS Journal on Computing → EBSCO, does not require GOKB to prove that access relationship.

Manual Services use a user-supplied public HTTP(S) URL and do not enter automatic CARSI authentication. Missing or invalid URLs require attention; Allfold does not invent an institutional login URL. A Journal may remain Unresolved.

For Journals without a supplied valid Service, the Import Preview offers optional GOKB resolution. It follows all Current TIPP pages and retains the associated Journal UUIDs, Platforms, Packages and candidate products. Multiple GOKB identities or CARSI products remain visible for a Journal-level choice. A unique reliable candidate may fill an empty default. Neither refresh nor an imported choice overwrites an existing default, and a Journal-level choice never becomes an application-wide Platform rule.

GOKB and the CARSI Catalog use shared local caches; explicit refresh replaces a snapshot only after successful validation. Failed refresh retains the last valid data and reports failure separately from a confirmed empty GOKB result. Ordinary Run uses saved Journal identifiers without contacting GOKB. Candidate evidence does not establish institutional entitlement, a successful login or PDF availability.

## Export, backup and migration

**Export User Data** generates Markdown from the current configuration's saved SQLite scope. It includes all Journals, order, Groups, Labels, Services and assignments, including independent Services such as Web of Science. It excludes credentials, institution passwords, API keys, sessions, Workspace papers, Zotero data, Registry and external caches.

For backup at the same configuration paths, preserve the private `.allfold/` directory along with YAML and other user data. For transfer to another location or configuration, export and import Markdown. Renaming a configuration changes its canonical scope identity.

On first migration, Allfold validates the old managed Markdown sections before creating the scope, records the source and digest, and keeps the original file unchanged. Damaged, incomplete or conflicting source data is not silently repaired or used to overwrite valid SQLite state. Conferences are not imported into the new model; their original Markdown remains available in the legacy file. After migration, editing that file does not update saved Journal state.

## Markdown formats

For a name-only list, use bullets. A heading is optional:

```markdown
# Research Scope

- Biometrics
- Annals of Applied Statistics
```

For identifiers, assignments or a supplied Service, use a table. Column order is flexible; optional columns may be omitted. Recognized Journal columns are `Journal` (also `Name` or `Title`), `ISSN`, `eISSN`, `Group`, `Label` (also `Labels`), `Service`, `Access URL` and `Access Method`. Separate multiple Labels with `;`. Names and cells must not contain literal pipes or newlines.

```markdown
## Journals

| Journal | ISSN | Group | Labels | Service | Access Method | Access URL |
| --- | --- | --- | --- | --- | --- | --- |
| Biometrics | 0006-341X | Statistics | Methods; Follow | EBSCO | carsi | |
| Annals of Applied Statistics | 1932-6157 | Statistics | Follow | Project Euclid | manual | https://projecteuclid.org/ |
```

A supplied CARSI production must match the official Catalog exactly. An existing CARSI Service for that production is reused with its local ID and settings preserved. A new Service uses the official URL; an imported CARSI URL is never trusted. `manual` requires the supplied public HTTP(S) URL, and a same-name local Manual Service with different settings remains a conflict. A blank Service means Unresolved unless the user opts into GOKB and a unique reliable candidate is found. Choosing Unresolved explicitly in Preview keeps it unresolved. A valid supplied Service skips GOKB even when the query option is enabled. Service choices are configuration-local preferences, not proof of access or entitlement.

To share independent Services or preserve empty Group/Label entries and their order, add the following tables. Journal `Service` cells refer to these definitions by name:

```markdown
## Groups

| Group |
| --- |
| Statistics |
| Later |

## Custom Labels

| Label |
| --- |
| Methods |
| Follow |
| Unused |

## Access Services

| Service | Access URL | Access Method |
| --- | --- | --- |
| EBSCO | | carsi |
| Web of Science | | carsi |
| Project Euclid | https://projecteuclid.org/ | manual |
```

Export User Data writes this portable named format, preserving Journal, registry and Service order and assignments. The previous six-column `Journal / ISSN / eISSN / Access Service ID / Group / Labels` table is also accepted with its accompanying `Service ID / Service / Access URL / Access Method` definitions. Those foreign IDs are references within the imported file only; Allfold verifies definitions and creates or reuses local Service identities. Missing, invalid or conflicting Service definitions remain visible for correction while valid Journals can still be added without a Service.

Preview offers per-row Skip, identity candidates with source evidence, editable names/ISSNs and CARSI/Manual/Unresolved corrections. Choose **Update Preview** after edits; Confirm uses only that verified Preview. Imported identifiers that overlap multiple saved Journals are conflicts requiring correction. A single existing identity is skipped before lookup, preserving its saved fields. Preview tokens are temporary and are invalidated by changed source, choices or Settings revisions; they do not survive application restart.

Identity selections bind the complete ISSN/eISSN pair, including when candidates share one identifier. The Preview form's `import_choices` JSON maps row indices to corrections; its `candidate` value is an object such as `{"issn":"0006-341X","eissn":"1541-0420"}`, with `null` for a missing identifier. This is a temporary selection, not a new Journal ID. Explicit CARSI/Manual corrections remain selected across subsequent **Update Preview** operations.
