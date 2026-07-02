"""Pure metadata logic with no I/O, so every function here is directly unit testable.

The working representation throughout is a flat dict of "Group:Tag" -> value,
matching ExifTool's -G1 output. Groups are only split back out at the response
boundary by build_groups.
"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, timedelta, timezone

# These -G1 tags describe the temporary server-side copy, not the uploaded file:
# the temp path would leak, and the filesystem timestamps are all "upload time",
# which reads as if the file itself was just created. Content-derived File:*
# tags (FileType, MIMEType) are kept.
TEMP_COPY_TAGS = {
    "System:FileName",
    "System:Directory",
    "System:FilePermissions",
    "System:FileModifyDate",
    "System:FileAccessDate",
    "System:FileInodeChangeDate",
    "System:FileCreateDate",
}

# Extension aliases so a .jpeg claimed name does not "mismatch" a jpg detection.
EXT_ALIASES = {
    "jpeg": "jpg",
    "jpe": "jpg",
    "tif": "tiff",
    "htm": "html",
    "mpeg": "mpg",
    "midi": "mid",
    "aif": "aiff",
    "yml": "yaml",
}

# OOXML and ODF documents are genuinely zip archives, and legacy Office formats
# share the OLE/CFB container. Content sniffers often report only the container,
# so container-compatible pairs are not mismatches.
ZIP_CONTAINER_EXTS = {
    "zip", "docx", "xlsx", "pptx", "odt", "ods", "odp", "epub", "jar", "apk",
}
OLE_CONTAINER_EXTS = {"doc", "xls", "ppt", "msi", "msg"}


def normalize_ext(ext: str) -> str:
    ext = ext.lower().lstrip(".")
    return EXT_ALIASES.get(ext, ext)


def is_type_mismatch(claimed_ext: str | None, detected_exts: list[str]) -> bool:
    """True when the filename extension disagrees with content detection.

    Errs toward no-flag: if either side is unknown there is nothing to compare,
    and container-level detections (zip, OLE) are compatible with the formats
    built on them.
    """
    if not claimed_ext or not detected_exts:
        return False
    claimed = normalize_ext(claimed_ext)
    detected = {normalize_ext(e) for e in detected_exts if e}
    if not detected or claimed in detected:
        return False
    if claimed in ZIP_CONTAINER_EXTS and detected & ZIP_CONTAINER_EXTS:
        return False
    if claimed in OLE_CONTAINER_EXTS and detected & OLE_CONTAINER_EXTS:
        return False
    return True


def flat_from_exiftool(record: dict) -> dict:
    """Flatten one ExifTool -j -G1 record, dropping temp-copy artifacts."""
    flat = {}
    for key, value in record.items():
        if key == "SourceFile" or key in TEMP_COPY_TAGS:
            continue
        # -G1 prefixes every tag with its group; the fallback is a safety net
        # for any ungrouped key so downstream split(":") never fails.
        flat[key if ":" in key else f"Other:{key}"] = value
    return flat


def _values_equal(a, b) -> bool:
    if a == b:
        return True
    # ExifTool stringifies numbers and booleans differently than Python
    # libraries do; compare the trimmed string forms before calling it a
    # conflict so "3" and 3 do not both appear.
    return str(a).strip() == str(b).strip()


def merge_supplements(flat: dict, supplements: dict[str, dict]) -> dict:
    """Merge library-sourced tags without ever overwriting ExifTool values.

    Each supplement lives under its own source-named group (pypdf, python-docx,
    openpyxl), which both marks provenance and guarantees no key collision. A
    supplement value identical to any ExifTool value for the same tag name is
    dropped as noise; a differing value is kept alongside, per spec.
    """
    merged = dict(flat)
    existing_by_tag: dict[str, list] = {}
    for full, value in flat.items():
        tag = full.split(":", 1)[1]
        existing_by_tag.setdefault(tag.lower(), []).append(value)

    for group, tags in supplements.items():
        for tag, value in tags.items():
            if value is None or value == "" or value == []:
                continue
            if any(_values_equal(value, v) for v in existing_by_tag.get(tag.lower(), [])):
                continue
            merged[f"{group}:{tag}"] = value
    return merged


# Display order: file-level facts first, ExifTool's derived groups last, and
# everything in between in the order ExifTool emitted it (which follows the
# physical layout of the file and is meaningful to power users).
FIRST_GROUPS = ["System", "File"]
LAST_GROUPS = ["Composite", "ExifTool"]


def build_groups(merged: dict) -> list[dict]:
    order: list[str] = []
    grouped: dict[str, list] = {}
    for full, value in merged.items():
        group, tag = full.split(":", 1)
        if group not in grouped:
            grouped[group] = []
            order.append(group)
        grouped[group].append({"key": tag, "value": value})

    def rank(group: str):
        if group in FIRST_GROUPS:
            return (0, FIRST_GROUPS.index(group))
        if group in LAST_GROUPS:
            return (2, LAST_GROUPS.index(group))
        return (1, order.index(group))

    return [{"name": g, "entries": grouped[g]} for g in sorted(order, key=rank)]


# Accepts ExifTool's "2024:01:02 03:04:05" (optionally .frac and +05:00 or Z)
# and ISO-ish variants from Python libraries.
_DATE_RE = re.compile(
    r"^(\d{4})[:-](\d{2})[:-](\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:\.\d+)?\s*(Z|[+-]\d{2}:?\d{2})?"
)


def parse_metadata_date(value) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    y, mo, d, h, mi, s = (int(x) for x in m.groups()[:6])
    try:
        dt = datetime(y, mo, d, h, mi, s)
    except ValueError:
        return None
    tz = m.group(7)
    if tz:
        if tz == "Z":
            offset = timedelta(0)
        else:
            sign = 1 if tz[0] == "+" else -1
            offset = sign * timedelta(hours=int(tz[1:3]), minutes=int(tz[-2:]))
        dt = dt.replace(tzinfo=timezone(offset))
    return dt


GPS_TAGS = {"gpslatitude", "gpslongitude", "gpsposition"}

# Person-name tags. "Creator" is only a person in Dublin Core (XMP-dc) and in
# the Office library supplements; in PDF, "Creator" is the authoring
# application and is classified as software below.
PERSON_TAGS = {"author", "artist", "lastmodifiedby", "last-modified-by", "by-line", "lastsavedby", "creator_person"}
PERSON_CREATOR_GROUP_PREFIXES = ("xmp", "pypdf", "python-docx", "openpyxl", "ooxml")

COMPANY_TAGS = {"company", "organization", "organisation", "manager"}

SOFTWARE_TAGS = {
    "software", "creatortool", "producer", "application", "appversion",
    "encoder", "writername", "encodedby", "encodingtool",
}
DEVICE_TAGS = {"make", "model", "cameramodelname", "devicemanufacturer", "devicemodelname"}

THUMBNAIL_TAGS = {"thumbnailimage", "thumbnailoffset", "thumbnaillength", "previewimage", "coverart"}

REVISION_TAGS = {"revisionnumber", "revision", "totaledittime", "trackchanges", "trackedrevisionsinbody"}

CREATE_DATE_TAGS = {"createdate", "creationdate", "datecreated", "created", "datetimeoriginal"}
MODIFY_DATE_TAGS = {"modifydate", "modificationdate", "datemodified", "modified", "lastmodified", "metadatadate"}


def _present(value) -> bool:
    return value not in (None, "", [], {})


def _tag_of(full_key: str) -> str:
    return full_key.split(":", 1)[1].lower().replace(" ", "")


def _collect(merged: dict, tags: set[str]) -> list[str]:
    return [k for k, v in merged.items() if _tag_of(k) in tags and _present(v)]


def _date_anomalies(merged: dict) -> list[str]:
    """Fields where a modification date precedes the creation date in the same
    metadata group. Compared per group because mixing sources (say filesystem
    vs XMP) produces false positives, and naive vs aware datetimes are only
    compared when both carry the same timezone awareness for the same reason.
    """
    by_group: dict[str, dict[str, list]] = {}
    for full, value in merged.items():
        group = full.split(":", 1)[0]
        tag = _tag_of(full)
        if tag in CREATE_DATE_TAGS:
            by_group.setdefault(group, {}).setdefault("create", []).append((full, value))
        elif tag in MODIFY_DATE_TAGS:
            by_group.setdefault(group, {}).setdefault("modify", []).append((full, value))

    fields = []
    for group, pair in by_group.items():
        for c_key, c_val in pair.get("create", []):
            created = parse_metadata_date(c_val)
            if not created:
                continue
            for m_key, m_val in pair.get("modify", []):
                modified = parse_metadata_date(m_val)
                if not modified or (created.tzinfo is None) != (modified.tzinfo is None):
                    continue
                if modified < created:
                    fields.extend([c_key, m_key])
    return fields


def detect_flags(merged: dict, claimed_type: str | None = None,
                 detected_type: str | None = None,
                 type_mismatch: bool = False) -> list[dict]:
    """Scan the merged metadata dict for notable findings.

    Pure function per spec: takes data, returns a list of
    {severity, label, fields} dicts, ordered warnings before info.
    """
    flags = []

    def add(severity: str, label: str, fields: list[str]):
        flags.append({"severity": severity, "label": label, "fields": fields})

    if type_mismatch:
        add("warning",
            f"File content ({detected_type or 'unknown'}) does not match its"
            f" extension (.{claimed_type})",
            ["claimed_type", "detected_type"])

    gps = _collect(merged, GPS_TAGS)
    if gps:
        add("warning", "GPS coordinates are embedded in this file", gps)

    person = _collect(merged, PERSON_TAGS)
    for key, value in merged.items():
        if _tag_of(key) == "creator" and _present(value):
            group = key.split(":", 1)[0].lower()
            if group.startswith(PERSON_CREATOR_GROUP_PREFIXES):
                person.append(key)
    if person:
        add("warning", "Personal names present (author, creator, or last modified by)", person)

    company = _collect(merged, COMPANY_TAGS)
    if company:
        add("warning", "Company or organization identifiers present", company)

    anomaly = _date_anomalies(merged)
    if anomaly:
        add("warning", "Modification date is earlier than creation date", anomaly)

    revisions = _collect(merged, REVISION_TAGS)
    # Revision 1 with no edit time is what a freshly saved document looks like;
    # only histories beyond that are notable.
    notable_revisions = []
    for key in revisions:
        tag = _tag_of(key)
        value = merged[key]
        if tag in ("revisionnumber", "revision"):
            try:
                if int(str(value)) <= 1:
                    continue
            except (TypeError, ValueError):
                pass
        if tag == "totaledittime" and str(value) in ("0", "0:00", "0 minutes"):
            continue
        notable_revisions.append(key)
    if notable_revisions:
        add("warning", "Revision history or tracked changes indicators present", notable_revisions)

    software = _collect(merged, SOFTWARE_TAGS)
    # PDF:Creator is the authoring application, unlike Dublin Core Creator.
    for key, value in merged.items():
        if _tag_of(key) == "creator" and _present(value):
            group = key.split(":", 1)[0].lower()
            if not group.startswith(PERSON_CREATOR_GROUP_PREFIXES):
                software.append(key)
    device = _collect(merged, DEVICE_TAGS)
    if software or device:
        add("info", "Software or device identifiers present", software + device)

    thumbs = _collect(merged, THUMBNAIL_TAGS)
    if thumbs:
        add("info", "Embedded thumbnail or preview image present", thumbs)

    flags.sort(key=lambda f: 0 if f["severity"] == "warning" else 1)
    return flags


def find_gps_decimal(merged: dict) -> tuple[float, float] | None:
    """Pull decimal lat/lon for the OpenStreetMap link. ExifTool is invoked
    with -c "%+.6f" so coordinate values arrive as signed decimal strings.
    """
    lat = lon = None
    # The Composite group is processed last so it wins: raw GPS:GPSLatitude is
    # unsigned with the hemisphere in a separate Ref tag, while Composite
    # values are already signed.
    keys = sorted(merged, key=lambda k: k.startswith("Composite:"))
    for key in keys:
        value = merged[key]
        tag = _tag_of(key)
        if tag not in ("gpslatitude", "gpslongitude"):
            continue
        m = re.search(r"[+-]?\d+(?:\.\d+)?", str(value))
        if not m:
            continue
        number = float(m.group(0))
        text = str(value)
        # Honor a hemisphere letter when a non-signed format slips through
        # (raw GPS group values, stub fixtures).
        if ("S" in text and tag == "gpslatitude") or ("W" in text and tag == "gpslongitude"):
            number = -abs(number)
        if tag == "gpslatitude":
            lat = number
        else:
            lon = number
    if lat is None or lon is None:
        return None
    return (lat, lon)


def flatten_csv_rows(groups: list[dict]) -> list[tuple[str, str, str]]:
    """Flatten the grouped view to (group, key, value) rows. Non-string values
    are JSON-encoded so lists and nested objects survive a round trip.
    """
    rows = []
    for group in groups:
        for entry in group["entries"]:
            value = entry["value"]
            rows.append((
                group["name"],
                entry["key"],
                value if isinstance(value, str) else json.dumps(value),
            ))
    return rows


def rows_to_csv(rows: list[tuple[str, str, str]]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(("group", "key", "value"))
    writer.writerows(rows)
    return buf.getvalue()
