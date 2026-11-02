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
