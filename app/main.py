"""FastAPI app: serves the single-page frontend and the /api/inspect endpoint.

Local-only tool: uploads are written to a per-request temp directory, hashed
and inspected, then deleted in a finally block. Nothing is persisted.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse

from . import extraction, logic
from .models import InspectResponse

# 2 GB default; override with the env var for bigger videos.
MAX_UPLOAD_BYTES = int(os.environ.get("METADATA_INSPECTOR_MAX_BYTES", 2 * 1024**3))

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

INSTALL_HINT = (
    "exiftool was not found on PATH. Install it first: "
    "macOS: brew install exiftool | Debian/Ubuntu: apt install libimage-exiftool-perl"
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Fail loudly at startup rather than on the first upload: exiftool is the
    # primary engine and the app is pointless without it.
    if not extraction.exiftool_path():
        raise RuntimeError(INSTALL_HINT)
    yield


app = FastAPI(title="metadata-inspector", lifespan=lifespan)


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


def _too_large_detail(size_hint: int | None) -> str:
    limit_gb = MAX_UPLOAD_BYTES / 1024**3
    seen = f" (got {size_hint} bytes)" if size_hint else ""
    return (
        f"File exceeds the {MAX_UPLOAD_BYTES} byte ({limit_gb:g} GB) upload limit{seen}. "
        "Raise it with the METADATA_INSPECTOR_MAX_BYTES environment variable."
    )


@app.post("/api/inspect", response_model=InspectResponse)
async def inspect(file: UploadFile) -> InspectResponse:
    filename = file.filename or "unknown"
    # Cheap early rejection when the client declared a size; the streaming
    # count below is the real enforcement since headers can lie.
    if file.size is not None and file.size > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=_too_large_detail(file.size))

    tmp_dir = tempfile.mkdtemp(prefix="metadata-inspector-")
    try:
        # Keep the original suffix so extension-keyed supplements fire, but a
        # fixed basename so the uploaded name cannot traverse paths.
        suffix = Path(filename).suffix
        if not suffix.replace(".", "").isalnum():
            suffix = ""
        tmp_path = Path(tmp_dir) / f"upload{suffix.lower()}"

        # Hash while streaming to disk to avoid a second full read of what may
        # be a multi-gigabyte video.
        md5 = hashlib.md5()
        sha256 = hashlib.sha256()
        size = 0
        with open(tmp_path, "wb") as out:
            while chunk := await file.read(1 << 20):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail=_too_large_detail(None))
                md5.update(chunk)
                sha256.update(chunk)
                out.write(chunk)

        errors: list[str] = []

        detected_ext = detected_mime = None
        candidates: list[str] = []
        try:
            detected_ext, detected_mime, candidates = extraction.detect_type(tmp_path)
        except Exception as exc:
            errors.append(f"type-detection: {type(exc).__name__}: {exc}")

        claimed_ext = Path(filename).suffix.lstrip(".").lower() or None
        mismatch = logic.is_type_mismatch(claimed_ext, candidates)

        raw = None
        flat: dict = {}
        try:
            raw, exiftool_error = extraction.run_exiftool(tmp_path)
            if exiftool_error:
                errors.append(f"exiftool: {exiftool_error}")
            if raw:
                flat = logic.flat_from_exiftool(raw)
        except Exception as exc:
            errors.append(f"exiftool: {type(exc).__name__}: {exc}")

        supplements, supplement_errors = extraction.run_supplements(
            tmp_path, claimed_ext, detected_ext)
        errors.extend(supplement_errors)

        merged = logic.merge_supplements(flat, supplements)
        return InspectResponse(
            file_info={
                "name": filename,
                "size": size,
                "md5": md5.hexdigest(),
                "sha256": sha256.hexdigest(),
                "detected_type": detected_mime or detected_ext,
                "detected_mime": detected_mime,
                "claimed_type": claimed_ext,
                "type_mismatch": mismatch,
            },
            groups=logic.build_groups(merged),
            flags=logic.detect_flags(merged, claimed_type=claimed_ext,
                                     detected_type=detected_mime or detected_ext,
                                     type_mismatch=mismatch),
            gps=logic.find_gps_decimal(merged),
            raw=raw,
            errors=errors,
        )
    finally:
        # The privacy contract of the tool: the upload never outlives the request.
        shutil.rmtree(tmp_dir, ignore_errors=True)
