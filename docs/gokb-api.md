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
non-Current TIPP rejects the query. Timeouts and invalid responses report
`unavailable` with an error. A confirmed empty Journal query reports `no_results`.
A complete query can report a unique, ambiguous or unresolved CARSI match.

Matching uses the bundled, read-only CARSI catalog. Its base product metadata
comes from the official directory. Outer URL whitespace may be trimmed for a
validated access link. Scheme-less references remain catalog evidence.
**Discover GOKB** selects a unique reliable match in the CARSI picker, and
**Save CARSI** validates and saves that selection through the normal Service
route. Research Scope can query during Preview and saves the verified proposal
on Confirm. [Official CARSI directory](https://www.carsi.edu.cn/SPlist.html)

`tests/test_resource_resolver.py` uses synthetic isolated HTTP and SQLite
fixtures. These checks establish source behavior, not real-site, institution
authentication, entitlement, UI or Zotero acceptance.
