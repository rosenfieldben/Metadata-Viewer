# metadata-inspector

A local-only web app for inspecting file metadata. Drag any file onto the page
(documents, images, video, audio, archives) and see everything extractable:
ExifTool output grouped by tag family, content-based type detection, hashes,
and notable-finding flags (GPS, author names, tracked changes, and so on).

Files never leave your machine: uploads go to a per-request temp directory,
are inspected, and are deleted before the response returns. Nothing is
persisted, there is no history and no database.

## Requirements

- Python 3.11+
- ExifTool on PATH (primary extraction engine, checked at startup)
  - macOS: `brew install exiftool`
  - Debian/Ubuntu: `apt install libimage-exiftool-perl`

## Run

The easy way (macOS and Linux): double-click `start.command` in Finder, or
run it from a shell. It creates the virtual environment on first run,
installs dependencies, starts the server, and opens your browser. Press
Ctrl+C in the window it opens to stop.

The manual way:

```sh
python3 -m venv .venv && source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 and drop files anywhere in the window.

The max upload size defaults to 2 GB; override with the
`METADATA_INSPECTOR_MAX_BYTES` environment variable. `start.command` also
respects a `PORT` environment variable if 8000 is taken.

## Sharing it with others

The tool is local by design, so "sharing" means giving someone their own
copy, not access to yours:

- **Share the repository.** They clone it and double-click `start.command`.
  Requirements on their machine: Python 3.11+ and ExifTool.
- **Docker, zero setup beyond Docker itself.** The image bundles Python,
  ExifTool, and all libraries:

  ```sh
  docker build -t metadata-inspector .
  docker run --rm -p 8000:8000 metadata-inspector
  ```

  You can also `docker save`/`docker load` the built image to hand it to
  someone as a single file.
- **Not recommended: serving your instance over the network.** Binding to
  `0.0.0.0` would let others on your network use your running copy, but
  their files would then be uploaded to your machine, which breaks the
  files-never-leave-your-machine promise and there is no authentication.

## Test fixtures

Golden fixtures are generated, not committed (only the ExifTool JSON stubs
under `fixtures/stubs/` are in git):

```sh
python scripts/make_fixtures.py
```

This produces, under `fixtures/`:

- `golden.png`: 1x1 PNG with injected EXIF author, software, device, and GPS
- `golden.pdf` and `golden-encrypted.pdf`: minimal pypdf PDFs with author,
  creator, and creation/modification dates (one encrypted with an empty
  user password)
- `golden.docx`: minimal Word document with author, last-modified-by,
  revision 4, and a Company field patched into `docProps/app.xml`
- `renamed-png.docx`: a PNG wearing a `.docx` extension, to trip the type
  mismatch warning

Drop any of these onto the running app to eyeball the output.

## Tests

```sh
python -m pytest tests/
```

The suite covers the pure logic (flag detection, type mismatch, merge
conflict handling, CSV flattening), the pipeline downstream of ExifTool via
the AVI and WebP JSON stubs, and a full-response integration pass through the
FastAPI test client. The integration tests generate the golden fixtures on
first run, so they need ExifTool available.

## How extraction works

1. File basics: original name, size, MD5 and SHA-256 (hashed while streaming
   the upload to disk).
2. Content-based type detection via puremagic; the claimed extension and the
   detected type are both reported, with a mismatch warning when they
   disagree (container formats like zip/OOXML and OLE are treated as
   compatible with the formats built on them).
3. ExifTool with `-j -G1 -a -u -ee` (plus `-c "%+.6f"` so GPS values arrive
   as signed decimals ready for the OpenStreetMap link).
4. Format-specific supplements merged in without overwriting ExifTool values:
   pypdf (encryption, page count, page sizes), python-docx plus raw
   `docProps/app.xml` and `word/settings.xml` reads (revision, company,
   track-changes state, unaccepted revisions in the body), openpyxl (workbook
   properties). Supplements live under source-named groups (`pypdf`,
   `python-docx`, `openpyxl`); a value identical to an ExifTool value is
   dropped as noise, a differing value is kept alongside so you see both.

Failures degrade per stage: a file ExifTool cannot parse still returns
basics, detection, and any supplements that succeeded, with the failures
listed in the response's `errors` array.

## Known-shallow formats

- AVI and animated WebP: ExifTool reads RIFF headers well, but codec-level
  and stream-level details are shallower than a dedicated media tool
  (ffprobe) would give. These formats are covered in tests by stubbed
  ExifTool JSON, since they cannot be synthesized without media tooling.
- Encrypted PDFs with a non-empty user password: only the encryption flag
  and whatever ExifTool can read from the unencrypted header.
- Legacy binary Office (.doc, .xls, .ppt): ExifTool output only, there is no
  supplement pass for OLE containers.
- Proprietary raw camera formats vary by ExifTool version.

## Layout

- `app/logic.py`: pure functions, no I/O (flags, merge, grouping, CSV)
- `app/extraction.py`: subprocess and filesystem stages
- `app/main.py`: FastAPI app and the `/api/inspect` endpoint
- `app/models.py`: pydantic models, response boundary only
- `static/index.html`: the entire frontend, no build step
- `scripts/make_fixtures.py`: golden fixture generator
- `fixtures/stubs/`: hand-written ExifTool JSON for formats we cannot generate
