"""AVI and animated WebP cannot be synthesized without media tooling, so these
tests feed hand-written ExifTool JSON stubs through everything downstream of
the subprocess call: flatten, merge, group, flag.
"""

import json
from pathlib import Path

from app import logic

STUBS = Path(__file__).resolve().parent.parent / "fixtures" / "stubs"


def run_pipeline(stub_name):
    record = json.loads((STUBS / stub_name).read_text())[0]
    flat = logic.flat_from_exiftool(record)
    merged = logic.merge_supplements(flat, {})
    return merged, logic.build_groups(merged), logic.detect_flags(merged)


class TestAviStub:
    def test_riff_group_present_with_video_tags(self):
        _, groups, _ = run_pipeline("avi.exiftool.json")
        riff = next(g for g in groups if g["name"] == "RIFF")
        keys = {e["key"] for e in riff["entries"]}
        assert {"VideoCodec", "FrameRate", "ImageWidth"} <= keys

    def test_software_flag_from_riff(self):
        _, _, flags = run_pipeline("avi.exiftool.json")
        flag = next(f for f in flags if "Software or device" in f["label"])
        assert "RIFF:Software" in flag["fields"]

    def test_temp_copy_tags_removed(self):
        merged, _, _ = run_pipeline("avi.exiftool.json")
        assert "System:FileName" not in merged
        assert "System:FileSize" in merged


class TestWebpStub:
    def test_animation_tags_survive(self):
        merged, _, _ = run_pipeline("webp.exiftool.json")
        assert merged["RIFF:FrameCount"] == 84

    def test_person_and_anomaly_flags(self):
        _, _, flags = run_pipeline("webp.exiftool.json")
        labels = " | ".join(f["label"] for f in flags)
        # The stub has XMP-dc:Creator and a ModifyDate before its CreateDate.
        assert "Personal names" in labels
        assert "earlier than creation" in labels
