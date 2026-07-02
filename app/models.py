"""Pydantic models for the response boundary only. Everything upstream of the
endpoint passes plain dicts, per the project's code style constraints.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class FileInfo(BaseModel):
    name: str
    size: int
    md5: str
    sha256: str
    detected_type: str | None
    detected_mime: str | None
    claimed_type: str | None
    type_mismatch: bool


class MetadataEntry(BaseModel):
    key: str
    value: Any


class MetadataGroup(BaseModel):
    name: str
    entries: list[MetadataEntry]


class Flag(BaseModel):
    severity: Literal["info", "warning"]
    label: str
    fields: list[str]


class InspectResponse(BaseModel):
    file_info: FileInfo
    groups: list[MetadataGroup]
    flags: list[Flag]
    # gps is duplicated out of the groups as ready-to-use decimals so the
    # frontend can build a map link without re-parsing coordinate strings.
    gps: tuple[float, float] | None
    raw: dict[str, Any] | None
    errors: list[str]
