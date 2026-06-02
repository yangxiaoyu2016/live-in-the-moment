from __future__ import annotations

import base64
import csv
import datetime as dt
import html
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

TAG_RE = re.compile(r"<(?P<tag>createTime|contentDesc|id|username|type)>(?P<val>.*?)</(?P=tag)>", re.DOTALL)
URL_RE = re.compile(r"<url[^>]*>(.*?)</url>", re.DOTALL)
THUMB_RE = re.compile(r"<thumb[^>]*>(.*?)</thumb>", re.DOTALL)
MD5_RE = re.compile(r'md5="([a-fA-F0-9]{32})"')
MEDIA_BLOCK_RE = re.compile(r"<media(?:\s[^>]*)?>(.*?)</media>", re.DOTALL)


def clean_text(value: str) -> str:
    return " ".join(html.unescape(value or "").replace("\r", " ").replace("\n", " ").split())


def to_iso(timestamp: int | None) -> str | None:
    if not timestamp:
        return None
    try:
        return dt.datetime.fromtimestamp(timestamp).isoformat(timespec="seconds")
    except Exception:
        return None


def normalize_db_field(value: Any) -> dict:
    if isinstance(value, bytes):
        try:
            text = value.decode("utf-8")
            if "<SnsDataItem>" in text:
                return {"type": "text", "value": text}
        except UnicodeDecodeError:
            pass
        return {"type": "blob_base64", "value": base64.b64encode(value).decode("ascii")}
    return {"type": "text", "value": value}


def export_raw_timeline(db_path: Path, output_dir: Path, logger=print) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        if "SnsTimeLine" not in tables:
            raise RuntimeError("解密后的数据库里没有 SnsTimeLine 表。")
        rows = conn.execute("SELECT tid, user_name, content, pack_info_buf FROM SnsTimeLine ORDER BY tid DESC").fetchall()

    raw_rows = []
    for tid, user_name, content, pack_info in rows:
        content_norm = normalize_db_field(content)
        pack_norm = normalize_db_field(pack_info)
        raw_rows.append(
            {
                "tid": tid,
                "user_name": user_name,
                "content_type": content_norm["type"],
                "content": content_norm["value"],
                "pack_info_type": pack_norm["type"],
                "pack_info_buf": pack_norm["value"],
            }
        )

    json_path = output_dir / "moments_raw.json"
    csv_path = output_dir / "moments_raw.csv"
    json_path.write_text(json.dumps(raw_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["tid", "user_name", "content_type", "content", "pack_info_type", "pack_info_buf"])
        writer.writeheader()
        writer.writerows(raw_rows)
    logger(f"[4/5] 已读取朋友圈原始记录：{len(raw_rows)} 条")
    return {"rows": len(raw_rows), "json": str(json_path), "csv": str(csv_path), "raw_rows": raw_rows}


def parse_xml_content(xml_text: str) -> dict:
    result = {
        "post_id": None,
        "username": None,
        "create_time": None,
        "create_time_iso": None,
        "content_desc": "",
        "content_object_type": None,
        "media_count": 0,
        "media_urls": [],
        "thumb_urls": [],
        "media_md5": [],
    }
    values: dict[str, list[str]] = {}
    for match in TAG_RE.finditer(xml_text):
        values.setdefault(match.group("tag"), []).append(match.group("val"))
    if values.get("id"):
        result["post_id"] = values["id"][0]
    if values.get("username"):
        result["username"] = values["username"][0]
    if values.get("createTime"):
        try:
            timestamp = int(values["createTime"][0])
            result["create_time"] = timestamp
            result["create_time_iso"] = to_iso(timestamp)
        except ValueError:
            pass
    if values.get("contentDesc"):
        result["content_desc"] = clean_text(values["contentDesc"][0])
    if values.get("type"):
        try:
            result["content_object_type"] = int(values["type"][0])
        except ValueError:
            result["content_object_type"] = values["type"][0]
    result["media_count"] = len(MEDIA_BLOCK_RE.findall(xml_text))
    result["media_urls"] = [clean_text(item) for item in URL_RE.findall(xml_text) if clean_text(item)]
    result["thumb_urls"] = [clean_text(item) for item in THUMB_RE.findall(xml_text) if clean_text(item)]
    result["media_md5"] = sorted(set(MD5_RE.findall(xml_text)))
    return result


def parse_date(value: str, end_of_day: bool) -> int | None:
    if not value:
        return None
    parsed = dt.datetime.strptime(value, "%Y-%m-%d")
    if end_of_day:
        parsed = parsed.replace(hour=23, minute=59, second=59)
    return int(parsed.timestamp())


def extract_moments(
    raw_rows: list[dict],
    output_dir: Path,
    owner_wxid: str = "",
    owner_only: bool = True,
    start_date: str = "",
    end_date: str = "",
    logger=print,
) -> dict:
    start_ts = parse_date(start_date, False) if start_date else None
    end_ts = parse_date(end_date, True) if end_date else None
    extracted = []
    skipped_non_owner = 0
    skipped_time_range = 0
    for item in raw_rows:
        parsed = {
            "tid": item.get("tid"),
            "user_name": item.get("user_name"),
            "source_content_type": item.get("content_type"),
            "pack_info_type": item.get("pack_info_type"),
        }
        content = item.get("content")
        if isinstance(content, str) and "<SnsDataItem>" in content:
            parsed.update(parse_xml_content(content))
            parsed["is_xml"] = True
        else:
            continue
        row_owner = parsed.get("username") or parsed.get("user_name")
        if owner_only and owner_wxid and row_owner != owner_wxid:
            skipped_non_owner += 1
            continue
        row_ts = parsed.get("create_time")
        if start_ts is not None and (row_ts is None or row_ts < start_ts):
            skipped_time_range += 1
            continue
        if end_ts is not None and (row_ts is None or row_ts > end_ts):
            skipped_time_range += 1
            continue
        extracted.append(parsed)

    # Some accounts expose a custom WeChat ID instead of the wxid-derived account folder.
    # Falling back prevents a one-click export from producing an empty result.
    if owner_only and owner_wxid and not extracted:
        logger("没有用账号目录 wxid 匹配到本人记录，已自动改为导出数据库中可解析的朋友圈记录。")
        return extract_moments(raw_rows, output_dir, owner_wxid="", owner_only=False, start_date=start_date, end_date=end_date, logger=logger)

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "moments_extracted.json"
    csv_path = output_dir / "moments_extracted_summary.csv"
    json_path.write_text(json.dumps(extracted, ensure_ascii=False, indent=2), encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["tid", "user_name", "username", "create_time", "create_time_iso", "content_object_type", "media_count", "media_md5_count", "content_desc"])
        for row in extracted:
            writer.writerow(
                [
                    row.get("tid"),
                    row.get("user_name"),
                    row.get("username"),
                    row.get("create_time"),
                    row.get("create_time_iso"),
                    row.get("content_object_type"),
                    row.get("media_count"),
                    len(row.get("media_md5", [])),
                    row.get("content_desc", ""),
                ]
            )
    logger(f"[5/5] 已生成朋友圈 JSON：{len(extracted)} 条")
    return {
        "rows": len(extracted),
        "json": str(json_path),
        "csv": str(csv_path),
        "skipped_non_owner": skipped_non_owner,
        "skipped_time_range": skipped_time_range,
    }
