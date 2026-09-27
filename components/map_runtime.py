"""Public map resources; never cache private store/token or edited catalog values."""

import os
import sqlite3
import tempfile
from pathlib import Path

import streamlit as st

from core.map_catalog import build_map_catalog
from core.map_query import MapQueryService
from core.pilot import load_pilot
from data_factory.map_index import build_map_index
from data_factory.sqlite_index import build_runtime_index


@st.cache_resource
def pilot_index(version):
    directory = tempfile.TemporaryDirectory(prefix="animeway-pilot-map-")
    catalog = load_pilot()
    payload = {
        "stats": {"schema_version": "3"},
        "items": [
            {
                "anime_id": int(work["id"]),
                "meta": {"id": int(work["id"]), "titles": {"cn": work["cn"], "jp": work["jp"]}},
                "spots": [],
            }
            for work in catalog["anime"]
        ],
    }
    path = str(Path(directory.name) / "pilot.sqlite3")
    build_runtime_index(payload, path)
    build_map_index(path, build_map_catalog(payload, catalog))
    return directory, path


def map_resource(store, catalog):
    provider = (lambda: store.catalog(load_pilot())) if store else load_pilot
    root = os.getenv("ANIMEWAY_SNAPSHOT_DIR") or "knowledge_base/releases"
    if (Path(root) / "current.json").exists() or os.getenv("ANIMEWAY_SNAPSHOT_DIR"):
        try:
            service = MapQueryService.from_snapshot(root, provider)
            return (
                service,
                service.snapshot["version"],
                "all",
                bool(service.snapshot["fallback_reasons"]),
            )
        except (OSError, ValueError, sqlite3.Error, TypeError, KeyError):
            # Explicitly labeled curated fallback; no mixed JSON/SQLite version.
            _, path = pilot_index(catalog.get("version"))
            return (
                MapQueryService(path, provider),
                "pilot:" + str(catalog.get("version")),
                "pilot",
                True,
            )
    _, path = pilot_index(catalog.get("version"))
    return MapQueryService(path, provider), "pilot:" + str(catalog.get("version")), "pilot", False
