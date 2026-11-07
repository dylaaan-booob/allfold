"""Local, revision-checked optional provider credentials beside a monitor config."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat

from allfold.persistence.safe_write import (
    ContentChangedError, atomic_create_text, read_text_exact, replace_regular_text_if_unchanged,
)


class OpenAlexCredentialError(ValueError):
    pass


def credential_path(config_path: Path, *, provider: str = "openalex") -> Path:
    if provider not in {"openalex", "pubmed"}:
        raise ValueError("Unknown credential Provider")
    return config_path.absolute().with_suffix(f".{provider}-secrets.json")


def validate_key(key: str | None, *, provider: str = "openalex") -> bool:
    return bool(provider in {"openalex", "pubmed"} and key and key.isascii()
                and all(33 <= ord(c) <= 126 for c in key))


def read_credential(config_path: Path, *, provider: str = "openalex") -> tuple[str | None, str]:
    """Return the secret and an opaque revision; missing is anonymous access."""
    path = credential_path(config_path, provider=provider)
    label = {"openalex":"OpenAlex", "pubmed":"PubMed"}.get(provider, provider)
    try:
        if any(part.is_symlink() for part in (path, *path.parents)):
            raise OpenAlexCredentialError(f"{label} credential path must not contain symlinks")
        try:
            info = path.lstat()
        except FileNotFoundError:
            return None, "missing"
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
            raise OpenAlexCredentialError(f"{label} credential file must be a regular file with permissions 0600")
        contents = read_text_exact(path)
        data = json.loads(contents)
        if not isinstance(data, dict) or set(data) != {"api_key"}:
            raise ValueError
        key = data["api_key"]
        if key is not None and (not isinstance(key, str) or not validate_key(key, provider=provider)):
            raise ValueError
        return key, hashlib.sha256(contents.encode()).hexdigest()
    except OpenAlexCredentialError:
        raise
    except (OSError, ValueError, UnicodeError):
        raise OpenAlexCredentialError(f"Unable to read valid {label} credentials; repair the local file explicitly") from None


def write_credential(config_path: Path, *, action: str, key: str | None, revision: str, provider: str = "openalex") -> None:
    label = {"openalex":"OpenAlex", "pubmed":"PubMed"}.get(provider, provider)
    if action not in {"replace", "clear"}:
        raise OpenAlexCredentialError(f"Choose replace or clear for the {label} API Key")
    if action == "replace" and (not validate_key(key, provider=provider)):
        raise OpenAlexCredentialError(f"{label} API Key has an invalid format")
    path = credential_path(config_path, provider=provider)
    _, actual = read_credential(config_path, provider=provider)
    if actual != revision:
        raise ContentChangedError(f"{label} credentials changed; reload Settings before saving")
    contents = json.dumps({"api_key": key if action == "replace" else None}) + "\n"
    if actual == "missing":
        atomic_create_text(path, contents)  # mkstemp creates the complete file with mode 0600.
    else:
        previous = read_text_exact(path)
        if hashlib.sha256(previous.encode()).hexdigest() != revision:
            raise ContentChangedError(f"{label} credentials changed before write")
        replace_regular_text_if_unchanged(path, contents, expected_contents=previous)
