# GOKB resource discovery contract

Allfold queries public `https://gokb.org/gokb/api/find` on demand. It does not
download the full catalog or add GOKB to Run. Fixtures model the official server
at commit `ed459e44eaef207cc79502fc15855b32ecf980f9`:

- [ApiController.find](https://github.com/openlibraryenvironment/gokb/blob/ed459e44eaef207cc79502fc15855b32ecf980f9/server/grails-app/controllers/org/gokb/ApiController.groovy#L344-L363)
  sets `skipDomainMapping=true` unless `mapRecords` is requested. Allfold uses
  this default flattened Elasticsearch record representation.
- [ESSearchService request mapping and identifier handling](https://github.com/openlibraryenvironment/gokb/blob/ed459e44eaef207cc79502fc15855b32ecf980f9/server/grails-app/services/com/k_int/ESSearchService.groovy#L487-L569)
  accepts a bare `identifier` value across namespaces. Allfold queries each local
  ISSN/eISSN, validates matching ISSN namespace evidence and retains every UUID.
- [Linked-field filtering](https://github.com/openlibraryenvironment/gokb/blob/ed459e44eaef207cc79502fc15855b32ecf980f9/server/grails-app/services/com/k_int/ESSearchService.groovy#L854-L888)
  maps `linkedTitle` to `tippTitle` and supports its `Uuid` field.
- [ESSearchService.find](https://github.com/openlibraryenvironment/gokb/blob/ed459e44eaef207cc79502fc15855b32ecf980f9/server/grails-app/services/com/k_int/ESSearchService.groovy#L1080-L1227)
  returns `result: "OK"`, `count`, `max`, `offset`, `records`. The result window
  is limited to `max + offset <= 10000`. The total field is `count`, not `total`.
- [TIPP ES fields](https://github.com/openlibraryenvironment/gokb/blob/ed459e44eaef207cc79502fc15855b32ecf980f9/server/grails-app/domain/org/gokb/cred/TitleInstancePackagePlatform.groovy#L94-L107)
  retain `tippTitleUuid`, `hostPlatformUuid/Name`, `tippPackageUuid/Name`.
  [Platform](https://github.com/openlibraryenvironment/gokb/blob/ed459e44eaef207cc79502fc15855b32ecf980f9/server/grails-app/domain/org/gokb/cred/Platform.groovy#L9)
  supplies `primaryUrl` through a separate UUID query.

| Step | Request parameters |
| --- | --- |
| Journal | `componentType=JournalInstance`, `identifier=<ISSN or eISSN>` |
| TIPP for each Journal UUID | `componentType=TitleInstancePackagePlatform`, `linkedTitle=<UUID>`, `status=Current` |
| Platform for each associated UUID | `componentType=Platform`, `uuid=<UUID>` |
| Every page | `max=100`, `offset=<consumed count>`, `sort=uuid`, `order=asc` |

Allfold validates response status, record type/UUID, requested page bounds,
fixed total, page length, uniqueness and link identities. A count above the
supported window, missing/duplicate UUID, changed total, truncated page or
non-Current TIPP rejects the entire refresh. Only complete validated snapshots,
including confirmed zero-result queries, replace prior cache entries.
Timeouts and query/schema failures return prior data with `stale` status or
`unavailable` without prior data. Neither outcome changes user choices.

The CARSI catalog comes from [official SPlist.html](https://www.carsi.edu.cn/SPlist.html).
Its nonempty inline JSON records are stored as `production`, `searchStr`, `url`,
`sptype` (string `1` or `2`). Renames/removals/conflicts are warnings, not a
request to rewrite saved Services. Outer URL whitespace may be trimmed for a
validated access link; scheme-less catalog references remain evidence only.

`tests/test_resource_resolver.py` uses synthetic isolated HTTP and SQLite
fixtures. These checks establish source behavior, not real-site, institution
authentication, entitlement, UI or Zotero acceptance.
