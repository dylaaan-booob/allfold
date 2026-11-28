"""Construct the selected catalog entry using the current institution's public values."""

from base64 import b64encode
import re
from urllib.parse import quote, unquote, urlsplit

from allfold.application.carsi_catalog import get_carsi_catalog
from allfold.url_safety import normalize_public_http_url

_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
_PORTAL = "https://ds.carsi.edu.cn"


def _encode(value: str) -> str:
    return quote(value, safe='')


def _statista_target(entity_id: str) -> str:
    value = b64encode(entity_id.encode('utf-8')).decode('ascii')
    return _encode("https://shibboleth.statista.com/index.php?idp=" + _encode(value))


def wayfless_url(template, institution):
    if not template or institution is None:
        return None
    needed = set(_PLACEHOLDER.findall(template))
    values = {}
    for name in needed:
        if name == 'statista_auth_target':
            if not institution.idp_entity_id:
                return None
            values[name] = _statista_target(institution.idp_entity_id)
        elif name in {'idp_entity_id', 'product_tenant_id', 'gale_location_id', 'institution_resource_url'}:
            if not (value := getattr(institution, name)):
                return None
            values[name] = _encode(_encode(value)) if name == 'product_tenant_id' else _encode(value)
        else:
            raise ValueError('Unknown CARSI entry placeholder')
    return normalize_public_http_url(_PLACEHOLDER.sub(lambda match: values[match[1]], template))


def school_identity(institution):
    return (institution.name, institution.idp_entity_id) if institution else (None, None)


def _entry_hosts(template, access_url, institution_url):
    # The official product URL and the selected template's literal destinations
    # are evidence for the landing. The runtime Entity ID is deliberately absent.
    values = list(filter(None, (access_url, institution_url)))
    if template:
        values.extend(re.findall(r"https?://[a-zA-Z0-9.-]+", unquote(unquote(template))))
    return sorted({host for value in values if (host := urlsplit(value).hostname)})


def service_entry(service, institution):
    if service.access_method == 'manual':
        return None
    resource = get_carsi_catalog().get(service.name)
    if resource and resource.unavailable_reason:
        return {'unavailable_reason': resource.unavailable_reason}
    template = resource.wayfless_url_template if resource else None
    access_url = resource.access_url if resource else service.access_url
    landing_url = '//' + resource.url.strip() if resource and not access_url else access_url
    name, entity_id = school_identity(institution)
    entry = wayfless_url(template, institution)
    portal = (_PORTAL + '/Shibboleth.sso/Login?entityID=' + _encode(entity_id)
              + '&target=' + _encode(_PORTAL + '/wxds')) if institution and institution.use_shibboleth and entity_id else None
    return dict(wayfless_url=entry, portal_login_url=portal, institution_name=name, idp_entity_id=entity_id,
                resource_name=service.name, access_url=access_url,
                landing_hosts=_entry_hosts(template, landing_url,
                    institution.institution_resource_url if entry and '{institution_resource_url}' in template else None))
