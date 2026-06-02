from __future__ import annotations

import json
import struct
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from PIL import Image

from live_in_the_moment.gallery import dedupe_records, image_hashes_and_size
from live_in_the_moment.extract import extract_moments, parse_xml_content
from live_in_the_moment.media import decode_v2_image_bytes, sniff_ext
from live_in_the_moment.moments import export_text, load_moments


def png_bytes(size=(32, 32), color=(200, 40, 40)) -> bytes:
    out = BytesIO()
    Image.new("RGB", size, color).save(out, format="PNG")
    return out.getvalue()


def make_v2_cache(body: bytes, key: bytes) -> bytes:
    pad = 16 - (len(body) % 16)
    padded = body + bytes([pad]) * pad
    encrypted = Cipher(algorithms.AES(key), modes.ECB()).encryptor().update(padded)
    header = b"\x07\x08V2\x08\x07" + struct.pack("<H", len(body)) + b"\x00" * 7
    return header + encrypted


class CoreTests(unittest.TestCase):
    def test_decode_v2_image_bytes(self):
        key = b"0123456789abcdef"
        body = png_bytes()
        encoded = make_v2_cache(body, key)
        decoded = decode_v2_image_bytes(encoded, key)
        self.assertEqual(sniff_ext(decoded[:64]), ".png")

    def test_export_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "moments.json"
            src.write_text(
                json.dumps(
                    [
                        {"create_time": 1735689600, "content_desc": " hello &amp; bye "},
                        {"create_time": 1738368000, "content_desc": ""},
                    ]
                ),
                encoding="utf-8",
            )
            out = root / "out"
            result = export_text(src, out)
            self.assertEqual(result["moments"], 2)
            self.assertIn("hello & bye", (out / "moments_text.txt").read_text(encoding="utf-8"))

    def test_load_moments_date_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "moments.json"
            src.write_text(
                json.dumps(
                    [
                        {"create_time_iso": "2025-01-01T00:00:00", "content_desc": "one"},
                        {"create_time_iso": "2025-03-01T00:00:00", "content_desc": "two"},
                    ]
                ),
                encoding="utf-8",
            )
            rows = load_moments(src, start_date="2025-02-01")
            self.assertEqual([row.content for row in rows], ["two"])

    def test_dedupe_prefers_larger_image(self):
        small = png_bytes((32, 32), (30, 120, 200))
        large = png_bytes((96, 96), (30, 120, 200))
        sw, sh, sd, sa, sb = image_hashes_and_size(small)
        lw, lh, ld, la, lb = image_hashes_and_size(large)
        records = [
            {"cache_key": "small", "body": small, "ext": ".png", "size": len(small), "width": sw, "height": sh, "pixels": sw * sh, "dhash": sd, "ahash": sa, "block_hash": sb, "source_order": 0},
            {"cache_key": "large", "body": large, "ext": ".png", "size": len(large), "width": lw, "height": lh, "pixels": lw * lh, "dhash": ld, "ahash": la, "block_hash": lb, "source_order": 1},
        ]
        kept, groups, removed = dedupe_records(records)
        self.assertEqual(groups, 1)
        self.assertEqual(removed, 1)
        self.assertEqual(kept[0]["cache_key"], "large")

    def test_parse_xml_content(self):
        xml = """
        <SnsDataItem><TimelineObject>
          <id>fake-post</id><username>wxid_example</username><createTime>1735689600</createTime>
          <contentDesc>Hello &amp; welcome</contentDesc>
          <ContentObject><type>2</type><mediaList><media md5="00000000000000000000000000000001">
            <url>https://example.invalid/full</url><thumb>https://example.invalid/thumb</thumb>
          </media></mediaList></ContentObject>
        </TimelineObject></SnsDataItem>
        """
        parsed = parse_xml_content(xml)
        self.assertEqual(parsed["post_id"], "fake-post")
        self.assertEqual(parsed["username"], "wxid_example")
        self.assertEqual(parsed["content_desc"], "Hello & welcome")
        self.assertEqual(parsed["media_count"], 1)
        self.assertEqual(parsed["media_md5"], ["00000000000000000000000000000001"])

    def test_extract_falls_back_when_owner_id_does_not_match(self):
        xml = "<SnsDataItem><TimelineObject><id>p1</id><username>custom_user</username><createTime>1735689600</createTime><contentDesc>Fallback works</contentDesc><ContentObject><type>1</type></ContentObject></TimelineObject></SnsDataItem>"
        with tempfile.TemporaryDirectory() as tmp:
            result = extract_moments(
                [{"tid": 1, "user_name": "custom_user", "content_type": "text", "content": xml, "pack_info_type": "text", "pack_info_buf": ""}],
                Path(tmp),
                owner_wxid="wxid_folder_guess",
                owner_only=True,
                logger=lambda _message: None,
            )
            self.assertEqual(result["rows"], 1)
            exported = json.loads((Path(tmp) / "moments_extracted.json").read_text(encoding="utf-8"))
            self.assertEqual(exported[0]["content_desc"], "Fallback works")


if __name__ == "__main__":
    unittest.main()
