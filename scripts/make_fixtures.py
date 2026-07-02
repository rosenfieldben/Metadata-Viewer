#!/usr/bin/env python3
"""Generate golden fixture files under fixtures/.

Everything here is synthesized deterministically so fixtures stay tiny and
never carry anyone's real metadata. AVI and WebP video cannot be synthesized
cleanly without media tooling, so those are covered by hand-written ExifTool
JSON stubs in fixtures/stubs/ and tested downstream of the subprocess call.

Run: python scripts/make_fixtures.py
"""

from __future__ import annotations

import base64
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

# A valid 1x1 gray PNG. Hardcoded because generating one would drag in an
# image library the app itself does not need.
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def make_png(path: Path) -> None:
    path.write_bytes(TINY_PNG)
    if not shutil.which("exiftool"):
        sys.exit("exiftool is required to inject EXIF into the PNG fixture")
    # Inject the exact fields the flag detector looks for: a person, GPS,
    # software, and a device. San Francisco coordinates, obviously fake person.
    subprocess.run(
        [
            "exiftool", "-overwrite_original", "-q",
            "-EXIF:Artist=Ada Example",
            "-EXIF:Software=fixturegen 1.0",
            "-EXIF:Make=ExampleCorp",
            "-EXIF:Model=Fixture Cam 3000",
            "-EXIF:CreateDate=2024:01:02 03:04:05",
            "-EXIF:ModifyDate=2024:02:03 04:05:06",
            "-GPSLatitude=37.7749", "-GPSLatitudeRef=N",
            "-GPSLongitude=122.4194", "-GPSLongitudeRef=W",
            str(path),
        ],
        check=True,
    )


def make_pdf(path: Path, encrypted: bool) -> None:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({
        "/Author": "Ada Example",
        "/Creator": "Fixture Word 16.0",
        "/Producer": "fixturegen via pypdf",
        "/Title": "Golden PDF fixture",
        "/CreationDate": "D:20240102030405Z",
        "/ModDate": "D:20240203040506Z",
    })
    if encrypted:
        # Empty user password, so readers open it without prompting but the
        # encryption flag still trips in the pypdf supplement.
        writer.encrypt(user_password="", owner_password="fixture-owner")
    with open(path, "wb") as fh:
        writer.write(fh)


def make_docx(path: Path) -> None:
    import docx

    document = docx.Document()
    document.add_paragraph("Golden docx fixture for metadata-inspector.")
    props = document.core_properties
    props.author = "Ada Example"
    props.last_modified_by = "Grace Reviewer"
    props.revision = 4
    document.save(str(path))

    # python-docx exposes no Company property (it lives in docProps/app.xml),
    # so rewrite that one zip member in place.
    rewritten = []
    with zipfile.ZipFile(path) as zf:
        for item in zf.infolist():
            data = zf.read(item.filename)
            if item.filename == "docProps/app.xml":
                text = data.decode("utf-8")
                if "<Company>" in text:
                    import re
                    text = re.sub(r"<Company>[^<]*</Company>",
                                  "<Company>ExampleCorp Ltd</Company>", text)
                else:
                    text = text.replace(
                        "</Properties>",
                        "<Company>ExampleCorp Ltd</Company></Properties>")
                data = text.encode("utf-8")
            rewritten.append((item, data))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for item, data in rewritten:
            zf.writestr(item, data)


def make_mismatch(path: Path) -> None:
    # A PNG wearing a .docx extension: exercises content-vs-extension detection.
    path.write_bytes(TINY_PNG)


def main() -> None:
    FIXTURES.mkdir(exist_ok=True)
    make_png(FIXTURES / "golden.png")
    make_pdf(FIXTURES / "golden.pdf", encrypted=False)
    make_pdf(FIXTURES / "golden-encrypted.pdf", encrypted=True)
    make_docx(FIXTURES / "golden.docx")
    make_mismatch(FIXTURES / "renamed-png.docx")
    for p in sorted(FIXTURES.iterdir()):
        if p.is_file():
            print(f"  {p.relative_to(FIXTURES.parent)} ({p.stat().st_size} bytes)")
    print("Fixtures ready. Drop them onto the app to eyeball the output.")


if __name__ == "__main__":
    main()
