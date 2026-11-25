"""The version pip installed is the one in porometry/__init__.py (pyproject.toml reads it from there)."""

import json
from importlib import metadata
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest

import porometry

DIST = "capillary-flow-porometry-analyzer"
REPO = Path(__file__).resolve().parents[1]


def _installed_from() -> Path | None:
    """The folder pip installed this package from (editable or not), if pip recorded it."""
    try:
        raw = metadata.distribution(DIST).read_text("direct_url.json")
    except metadata.PackageNotFoundError:
        return None
    if not raw:
        return None
    url = urlparse(json.loads(raw).get("url", ""))
    if url.scheme != "file":
        return None
    path = unquote(url.path)
    if len(path) > 2 and path[0] == "/" and path[2] == ":":  # file:///C:/Users/... on Windows
        path = path[1:]
    return Path(path).resolve()


def test_installed_version_is_the_package_version():
    try:
        installed = metadata.version(DIST)
    except metadata.PackageNotFoundError:
        pytest.skip(f"{DIST} isn't installed (pip install -e .)")
    where = _installed_from()
    if where is not None and where != REPO:
        pytest.skip(f"installed from another copy ({where})")
    assert installed == porometry.__version__, (
        f"pip has {installed} but porometry/__init__.py says {porometry.__version__}: run pip install -e . again")
