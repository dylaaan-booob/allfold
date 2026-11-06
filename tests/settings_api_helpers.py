"""Isolated Registry data and Settings FormData from the UI Next JSON projection."""
from contextlib import closing
import sqlite3


def registry(root, rows=None):
    path = root / "journal-lists" / "journal-registry.sqlite"
    path.parent.mkdir(exist_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS journals (title TEXT, issn TEXT, eissn TEXT, publisher TEXT, source TEXT, status TEXT)")
        with connection:
            connection.execute("DELETE FROM journals")
            connection.executemany("INSERT INTO journals VALUES (?, ?, ?, ?, ?, ?)", rows or [
                ("Biometrics", "0006-341X", None, "Wiley", "SCIE", None),
                ("Annals", "0090-5364", None, "IMS", "SCIE", None),
                ("Annals of Applied Statistics", "1932-6157", None, "IMS", "SCIE", None),
                ("Canonical Source", "1541-0420", None, "Wiley", "Scopus", "Active"),
            ])
    return path


def form(state):
    import json
    v = state["values"]
    data = {key: v[key] for key in (
        "name", "keyword_expression", "openalex_key_revision", "crossref_mailto", "from_month", "to_month", "output_dir", "log_level",
        "monitor_revision_exists", "monitor_revision_digest", "journal_revision_exists",
        "journal_revision_digest", "transition_delay_seconds", "display_name",
        "institution_name", "institution_idp_entity_id",
    )}
    data.update({f"provider_alias_{key}": value for key, value in v["provider_aliases"].items()})
    data["conferences"] = json.dumps(v.get("conferences", []))
    data.update(csrf_token=state["csrf_token"], settings_group=v["groups"], settings_custom_label=v["custom_labels"], provider_order=v["provider_order"], enabled_providers=v["enabled_providers"], completion_providers=v["completion_providers"])
    data["auto_import_after_preparation"] = "1" if v["auto_import_after_preparation"] else ""
    data["institution_use_shibboleth"] = "1" if v["institution_use_shibboleth"] else ""
    for source, mapping in (
        ("journals", {"journal_name": "name", "journal_issn": "issn", "journal_eissn": "eissn", "journal_group": "group", "journal_labels": "labels",
                      "journal_access_service_id": "access_service_id"}),
        ("access_services", {"service_id": "id", "service_name": "name",
                             "service_access_url": "access_url", "service_access_method": "access_method"}),
    ):
        for target, field in mapping.items():
            data[target] = [row[field] for row in v[source]]
    return data
