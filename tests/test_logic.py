"""Unit tests for the pure logic: flag detection, mismatch detection,
merge conflict handling, and CSV flattening.
"""

from app import logic


def flags_by_label(flags):
    return {f["label"]: f for f in flags}


def find_flag(flags, substring):
    matches = [f for f in flags if substring.lower() in f["label"].lower()]
    return matches[0] if matches else None


CLEAN = {
    "File:FileType": "PNG",
    "File:MIMEType": "image/png",
    "PNG:ImageWidth": 100,
    "PNG:ImageHeight": 50,
}


class TestFlagDetection:
    def test_clean_file_produces_no_flags(self):
        assert logic.detect_flags(CLEAN) == []

    def test_gps_flag(self):
        merged = dict(CLEAN, **{"GPS:GPSLatitude": "+37.774900",
                                "GPS:GPSLongitude": "-122.419400"})
        flag = find_flag(logic.detect_flags(merged), "GPS coordinates")
        assert flag and flag["severity"] == "warning"
        assert set(flag["fields"]) == {"GPS:GPSLatitude", "GPS:GPSLongitude"}

    def test_gps_flag_ignores_empty_values(self):
        merged = dict(CLEAN, **{"GPS:GPSLatitude": ""})
        assert find_flag(logic.detect_flags(merged), "GPS coordinates") is None

    def test_person_flag_from_author_and_xmp_creator(self):
        merged = dict(CLEAN, **{"IFD0:Artist": "Ada",
                                "XMP-dc:Creator": "Ada",
                                "pypdf:Creator": "Ada"})
        flag = find_flag(logic.detect_flags(merged), "Personal names")
        assert flag and flag["severity"] == "warning"
        assert set(flag["fields"]) == {"IFD0:Artist", "XMP-dc:Creator", "pypdf:Creator"}

    def test_pdf_creator_is_software_not_person(self):
        merged = dict(CLEAN, **{"PDF:Creator": "Microsoft Word"})
        flags = logic.detect_flags(merged)
        assert find_flag(flags, "Personal names") is None
        software = find_flag(flags, "Software or device")
        assert software and software["severity"] == "info"
        assert software["fields"] == ["PDF:Creator"]

    def test_company_flag(self):
        merged = dict(CLEAN, **{"FlashPix:Company": "ExampleCorp"})
        flag = find_flag(logic.detect_flags(merged), "Company or organization")
        assert flag and flag["severity"] == "warning"

    def test_date_anomaly_modified_before_created(self):
        merged = dict(CLEAN, **{"XMP-xmp:CreateDate": "2024:03:10 14:22:31",
                                "XMP-xmp:ModifyDate": "2024:03:09 08:00:00"})
        flag = find_flag(logic.detect_flags(merged), "earlier than creation")
        assert flag and flag["severity"] == "warning"
        assert set(flag["fields"]) == {"XMP-xmp:CreateDate", "XMP-xmp:ModifyDate"}

    def test_no_date_anomaly_when_order_is_normal(self):
        merged = dict(CLEAN, **{"XMP-xmp:CreateDate": "2024:03:09 08:00:00",
                                "XMP-xmp:ModifyDate": "2024:03:10 14:22:31"})
        assert find_flag(logic.detect_flags(merged), "earlier than creation") is None

    def test_no_date_anomaly_across_groups(self):
        # Create in one group, modify in another: sources are not comparable.
        merged = dict(CLEAN, **{"ExifIFD:CreateDate": "2024:03:10 14:22:31",
                                "XMP-xmp:ModifyDate": "2024:03:09 08:00:00"})
        assert find_flag(logic.detect_flags(merged), "earlier than creation") is None

    def test_software_and_device_flag(self):
        merged = dict(CLEAN, **{"IFD0:Software": "GIMP 2.10",
                                "IFD0:Make": "Canon", "IFD0:Model": "EOS R5"})
        flag = find_flag(logic.detect_flags(merged), "Software or device")
        assert flag and flag["severity"] == "info"
        assert set(flag["fields"]) == {"IFD0:Software", "IFD0:Make", "IFD0:Model"}

    def test_thumbnail_flag(self):
        merged = dict(CLEAN, **{"IFD1:ThumbnailImage": "(Binary data 4859 bytes)"})
        flag = find_flag(logic.detect_flags(merged), "thumbnail")
        assert flag and flag["severity"] == "info"

    def test_revision_flag_triggers_above_one(self):
        merged = dict(CLEAN, **{"XML:RevisionNumber": 4})
        flag = find_flag(logic.detect_flags(merged), "Revision history")
        assert flag and flag["severity"] == "warning"

    def test_revision_one_is_not_notable(self):
        merged = dict(CLEAN, **{"XML:RevisionNumber": "1"})
        assert find_flag(logic.detect_flags(merged), "Revision history") is None

    def test_track_changes_flag(self):
        merged = dict(CLEAN, **{"python-docx:TrackChanges": True})
        assert find_flag(logic.detect_flags(merged), "Revision history")

    def test_type_mismatch_flag(self):
        flags = logic.detect_flags(CLEAN, claimed_type="docx",
                                   detected_type="image/png", type_mismatch=True)
        flag = find_flag(flags, "does not match")
        assert flag and flag["severity"] == "warning"

    def test_warnings_sort_before_info(self):
        merged = dict(CLEAN, **{"IFD0:Software": "GIMP",
                                "GPS:GPSLatitude": "+1.0", "GPS:GPSLongitude": "+2.0"})
        severities = [f["severity"] for f in logic.detect_flags(merged)]
        assert severities == sorted(severities, key=lambda s: s != "warning")


class TestTypeMismatch:
    def test_matching_extension(self):
        assert not logic.is_type_mismatch("png", ["png"])

    def test_alias_is_not_a_mismatch(self):
        assert not logic.is_type_mismatch("jpeg", ["jpg"])

    def test_real_mismatch(self):
        assert logic.is_type_mismatch("docx", ["png"])

    def test_unknown_detection_is_not_a_mismatch(self):
        assert not logic.is_type_mismatch("xyz", [])
        assert not logic.is_type_mismatch(None, ["png"])

    def test_zip_container_is_compatible_with_ooxml(self):
        assert not logic.is_type_mismatch("docx", ["zip"])
        assert not logic.is_type_mismatch("epub", ["zip"])

    def test_ole_container_is_compatible_with_legacy_office(self):
        assert not logic.is_type_mismatch("doc", ["msi"])

    def test_dotted_and_mixed_case_extensions(self):
        assert not logic.is_type_mismatch("PNG", [".png"])


class TestMerge:
    def test_supplement_lands_under_source_group(self):
        merged = logic.merge_supplements(
            {"PDF:Author": "Ada"}, {"pypdf": {"PageCount": 3}})
        assert merged["pypdf:PageCount"] == 3
        assert merged["PDF:Author"] == "Ada"

    def test_identical_duplicate_is_dropped(self):
        merged = logic.merge_supplements(
            {"PDF:Author": "Ada"}, {"pypdf": {"Author": "Ada"}})
        assert "pypdf:Author" not in merged

    def test_duplicate_comparison_ignores_python_stringification(self):
        merged = logic.merge_supplements(
            {"XML:RevisionNumber": "4"}, {"python-docx": {"RevisionNumber": 4}})
        assert "python-docx:RevisionNumber" not in merged

    def test_conflicting_value_keeps_both_with_source_marked(self):
        merged = logic.merge_supplements(
            {"PDF:Author": "Ada"}, {"pypdf": {"Author": "Grace"}})
        assert merged["PDF:Author"] == "Ada"
        assert merged["pypdf:Author"] == "Grace"

    def test_exiftool_values_never_overwritten(self):
        flat = {"PDF:PageCount": 2}
        merged = logic.merge_supplements(flat, {"pypdf": {"PageCount": 3}})
        assert merged["PDF:PageCount"] == 2
        assert merged["pypdf:PageCount"] == 3

    def test_empty_supplement_values_skipped(self):
        merged = logic.merge_supplements({}, {"pypdf": {"Author": "", "X": None}})
        assert merged == {}


class TestGroupsAndCsv:
    def test_build_groups_orders_file_first_composite_last(self):
        merged = {
            "Composite:ImageSize": "1x1",
            "IFD0:Make": "Canon",
            "File:FileType": "PNG",
            "System:FileSize": "1 kB",
        }
        names = [g["name"] for g in logic.build_groups(merged)]
        assert names[0] == "System" and names[1] == "File"
        assert names[-1] == "Composite"

    def test_flatten_csv_rows_stringifies_non_strings(self):
        groups = [{"name": "RIFF", "entries": [
            {"key": "FrameRate", "value": 29.97},
            {"key": "Codec", "value": "xvid"},
            {"key": "Streams", "value": [1, 2]},
        ]}]
        rows = logic.flatten_csv_rows(groups)
        assert rows == [("RIFF", "FrameRate", "29.97"),
                        ("RIFF", "Codec", "xvid"),
                        ("RIFF", "Streams", "[1, 2]")]

    def test_rows_to_csv_escapes_quotes_and_commas(self):
        csv_text = logic.rows_to_csv([("G", "Key", 'va"l,ue')])
        assert csv_text.splitlines()[0] == "group,key,value"
        assert '"va""l,ue"' in csv_text

    def test_flat_from_exiftool_drops_temp_copy_tags(self):
        flat = logic.flat_from_exiftool({
            "SourceFile": "/tmp/x/upload.png",
            "System:FileName": "upload.png",
            "System:FileModifyDate": "2026:07:01 10:00:00",
            "System:FileSize": "1 kB",
            "File:FileType": "PNG",
        })
        assert "System:FileName" not in flat
        assert "System:FileModifyDate" not in flat
        assert flat["System:FileSize"] == "1 kB"
        assert "SourceFile" not in flat


class TestGps:
    def test_composite_signed_values_win_over_raw_gps(self):
        merged = {
            "GPS:GPSLatitude": "37.7749",
            "GPS:GPSLongitude": "122.4194",
            "GPS:GPSLongitudeRef": "West",
            "Composite:GPSLatitude": "+37.774900",
            "Composite:GPSLongitude": "-122.419400",
        }
        assert logic.find_gps_decimal(merged) == (37.7749, -122.4194)

    def test_hemisphere_letters_negate(self):
        merged = {"RIFF:GPSLatitude": '12.5 S', "RIFF:GPSLongitude": '45.25 W'}
        assert logic.find_gps_decimal(merged) == (-12.5, -45.25)

    def test_missing_coordinate_returns_none(self):
        assert logic.find_gps_decimal({"GPS:GPSLatitude": "+1.0"}) is None


class TestDateParsing:
    def test_exiftool_format(self):
        dt = logic.parse_metadata_date("2024:01:02 03:04:05")
        assert (dt.year, dt.month, dt.second) == (2024, 1, 5)

    def test_timezone_and_z(self):
        aware = logic.parse_metadata_date("2024:01:02 03:04:05+05:30")
        zulu = logic.parse_metadata_date("2024:01:02 03:04:05Z")
        assert aware.tzinfo and zulu.tzinfo

    def test_garbage_returns_none(self):
        assert logic.parse_metadata_date("0000:00:00 00:00:00") is None
        assert logic.parse_metadata_date("not a date") is None
        assert logic.parse_metadata_date(12345) is None
