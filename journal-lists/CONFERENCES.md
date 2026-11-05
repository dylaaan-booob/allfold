# Conference Registry source

`conferences.json` is the reviewed, offline input for the `conferences` table in
`journal-registry.sqlite`. It contains the 22 DBLP Stream identities adopted in
Issue #32. Each row records its official DBLP series index URL, formal/display
name, abbreviation, historical aliases and a source-scope limitation. The series
indices were checked on 2026-11-05; this snapshot is not a promise that every
annual event or main-conference paper is indexed. In particular ECML-PKDD uses
the adopted `streams/conf/pkdd` identity, rather than adding related streams.

The stable Allfold IDs are recorded in this source and must survive name changes.
Their initial values are `conf_` plus UUIDv5(`NAMESPACE_URL`,
`https://allfold.app/conferences/` + Stream Key). IDs are not abbreviations, ISSNs,
or OpenAlex Source IDs. Registry entries are never automatically followed.

Reproduce the Conference table without acquiring the large journal source lists:

```sh
uv run --locked python tools/build_journal_registry.py --conferences-only
```

The command replaces only that table in the existing Registry; the normal full
Registry build also includes it. `tests/test_conferences.py` compares the rebuilt
rows against the shipped table. Runtime opens the shipped database read-only and
does not fetch RDF, SPARQL, the DBLP publication dump, or remote metadata for
source lookup. New entries or changed identities require a reviewed source edit
and rebuild.

The descriptive facts and stream identities come from the linked DBLP indices.
DBLP bibliographic metadata is available under [CC0](https://dblp.org/faq/1474679.html).
The source snapshot does not redistribute page markup or publication records.
A direct RDF request during implementation returned HTTP 202 with an access
verification page; it was not processed as metadata or bypassed. Offline Registry
validation does not establish live DBLP discovery availability.
