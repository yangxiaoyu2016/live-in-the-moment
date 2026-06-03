from __future__ import annotations

import json
import struct
import tempfile
import unittest
from datetime import datetime
from io import BytesIO
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from PIL import Image

from live_in_the_moment.gallery import dedupe_records, image_hashes_and_size
from live_in_the_moment.gui import should_show_gui_log
from live_in_the_moment.extract import extract_moments, parse_xml_content
from live_in_the_moment.media import decode_v2_image_bytes, sniff_ext
from live_in_the_moment.moments import export_text, load_moments
from live_in_the_moment.one_click import validate_date_range
from live_in_the_moment.report import TextMoment, build_report_from_txt, build_yearly_summaries, parse_moments_txt


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


def parse_moments_txt_line(timestamp: str, content: str) -> TextMoment:
    return TextMoment(created=datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S"), content=content)


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

    def test_validate_date_range(self):
        self.assertEqual(validate_date_range(" 2025-01-01 ", "2026-06-02"), ("2025-01-01", "2026-06-02"))
        with self.assertRaisesRegex(ValueError, "日期格式不对"):
            validate_date_range("2025/01/01", "")
        with self.assertRaisesRegex(ValueError, "开始日期不能晚于结束日期"):
            validate_date_range("2026-01-01", "2025-01-01")

    def test_gui_hides_database_progress_logs(self):
        self.assertTrue(should_show_gui_log("[1/5] 已找到微信进程：1234"))
        self.assertFalse(should_show_gui_log("[2/5] 已找到朋友圈数据库：hidden"))
        self.assertFalse(should_show_gui_log("  [3/5] 朋友圈数据库解密完成"))
        self.assertTrue(should_show_gui_log("[4/5] 已读取朋友圈原始记录：10 条"))
        self.assertTrue(should_show_gui_log("[5/5] 已生成朋友圈 JSON：10 条"))

    def test_parse_moments_txt(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "moments_text.txt"
            src.write_text(
                "\n".join(
                    [
                        "2025-01-01 09:00:00",
                        "First line",
                        "Second line with <script>alert(1)</script> & text",
                        "",
                        "2025-02-01 10:30:00",
                        "[No text]",
                        "",
                        "2025-03-03 11:00:00",
                        "Last entry without trailing newline",
                    ]
                ),
                encoding="utf-8",
            )
            records = parse_moments_txt(src)
            self.assertEqual(len(records), 3)
            self.assertEqual(records[0].content, "First line\nSecond line with <script>alert(1)</script> & text")
            self.assertEqual(records[1].content, "")
            self.assertEqual(records[2].content, "Last entry without trailing newline")

    def test_build_report_from_txt_escapes_user_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "moments_text.txt"
            out = Path(tmp) / "custom_report.html"
            src.write_text(
                "2025-01-01 09:00:00\n<script>alert(1)</script> & <b>bold</b>\n",
                encoding="utf-8",
            )
            result = build_report_from_txt(src, out)
            html = out.read_text(encoding="utf-8")
            self.assertEqual(result["moments"], 1)
            self.assertEqual(result["html"], str(out))
            self.assertEqual(result["analysis_prompts"], ["yearly_summary"])
            self.assertIn("微信朋友圈个人报告", html)
            self.assertIn("年度总结", html)
            self.assertNotIn("查看内置 Prompt", html)
            self.assertNotIn("请根据下面的朋友圈内容", html)
            self.assertIn("month-2025-01", html)
            self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt; &amp; &lt;b&gt;bold&lt;/b&gt;", html)
            self.assertNotIn("<script>alert(1)</script>", html)
            self.assertIn("applySearch", html)

    def test_build_yearly_summaries_uses_only_observed_text(self):
        records = [
            parse_moments_txt_line("2024-01-01 09:00:00", "工作 项目 加班，但是和朋友吃饭很开心。"),
            parse_moments_txt_line("2025-01-01 09:00:00", "旅行 到达 东京，拍照记录。"),
        ]
        summaries = build_yearly_summaries(records)
        self.assertEqual([item["year"] for item in summaries], ["2024", "2025"])
        self.assertIn("工作/事业", summaries[0]["main_themes"])
        self.assertIn("朋友关系", summaries[0]["relationships"])
        self.assertIn("偏积极", summaries[0]["emotion"])
        self.assertIn("旅行/城市", summaries[1]["main_themes"])
        self.assertIn("变化为", summaries[1]["life_change"])
        self.assertTrue(any("工作 项目 加班" in item for item in summaries[0]["representative_expressions"]))

    def test_build_yearly_summaries_marks_unknown_fields(self):
        records = [parse_moments_txt_line("2025-01-01 09:00:00", "。")]
        summary = build_yearly_summaries(records)[0]
        self.assertEqual(summary["main_themes"], "无法判断")
        self.assertEqual(summary["emotion"], "无法判断")
        self.assertEqual(summary["life_focus"], "无法判断")
        self.assertEqual(summary["relationships"], "无法判断")

    def test_parse_moments_txt_rejects_empty_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "moments_text.txt"
            src.write_text("No timestamps here\njust text\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "No valid Moments timestamps"):
                parse_moments_txt(src)

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
