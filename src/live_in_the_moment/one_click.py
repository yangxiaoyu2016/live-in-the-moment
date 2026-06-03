from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from .db_decrypt import account_name_from_db_path, decrypt_logged_in_sns_db, guess_owner_wxid
from .extract import export_raw_timeline, extract_moments
from .gallery import build_gallery
from .moments import export_text
from .probe import probe_v2_key
from .report import build_report_from_txt


def find_v2_sample(account_root: Path) -> Path | None:
    cache_root = account_root / "cache"
    if not cache_root.exists():
        return None
    for path in cache_root.glob("????-??/Sns/Img/**/*"):
        if not path.is_file():
            continue
        try:
            with path.open("rb") as f:
                if f.read(6) in (b"\x07\x08V1\x08\x07", b"\x07\x08V2\x08\x07"):
                    return path
        except OSError:
            continue
    return None


def account_root_from_db(db_path: Path) -> Path:
    try:
        return db_path.parents[2]
    except IndexError:
        return db_path.parent


def _parse_filter_date(value: str, label: str) -> dt.datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return dt.datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"日期格式不对：{label}必须是 YYYY-MM-DD，例如 2026-06-02。") from exc


def validate_date_range(start_date: str = "", end_date: str = "") -> tuple[str, str]:
    start_date = (start_date or "").strip()
    end_date = (end_date or "").strip()
    start = _parse_filter_date(start_date, "开始日期")
    end = _parse_filter_date(end_date, "结束日期")
    if start and end and start > end:
        raise ValueError("日期范围不对：开始日期不能晚于结束日期。")
    return start_date, end_date


def one_click_export(
    output_dir: Path,
    source_root: Path | None = None,
    include_images: bool = True,
    start_date: str = "",
    end_date: str = "",
    pid: int = 0,
    logger=print,
) -> dict:
    start_date, end_date = validate_date_range(start_date, end_date)
    output_dir.mkdir(parents=True, exist_ok=True)
    decrypt_report = decrypt_logged_in_sns_db(output_dir, source_root=source_root, pid=pid, logger=logger)
    plain_db = Path(decrypt_report["plain_db"])
    db_path = Path(decrypt_report["db"])
    account = account_name_from_db_path(db_path)
    account_root = account_root_from_db(db_path)
    owner_wxid = guess_owner_wxid(account)

    raw = export_raw_timeline(plain_db, output_dir / "internal" / "raw", logger=logger)
    extracted = extract_moments(
        raw["raw_rows"],
        output_dir / "moments",
        owner_wxid=owner_wxid,
        owner_only=True,
        start_date=start_date,
        end_date=end_date,
        logger=logger,
    )
    text = export_text(Path(extracted["json"]), output_dir / "text", start_date=start_date, end_date=end_date)
    text_path = Path(text["text"])
    logger(f"朋友圈文字保存在了：目录 {text_path.parent}，文件 {text_path.name}")
    report = {}
    try:
        report = build_report_from_txt(text_path)
        report_path = Path(report["html"])
        logger(f"朋友圈个人报告保存在了：目录 {report_path.parent}，文件 {report_path.name}")
    except Exception as exc:
        logger(f"朋友圈个人报告生成失败：{exc}")

    gallery = {}
    image_key = ""
    if include_images:
        sample = find_v2_sample(account_root)
        if sample:
            logger("正在探测图片缓存 key...")
            probe = probe_v2_key(sample)
            for item in probe.get("results", []):
                image_key = item.get("key_ascii") or ""
                if image_key:
                    break
            if image_key:
                gallery = build_gallery(
                    input_path=Path(extracted["json"]),
                    account_root=account_root,
                    output_dir=output_dir / "gallery",
                    v2_aes_key=image_key,
                    start_date=start_date,
                    end_date=end_date,
                )
            else:
                logger("未能探测到图片缓存 key，已跳过图片导出。可以在微信里重新打开朋友圈图片后再重试。")
        else:
            logger("没有找到 V2 图片缓存样本，已跳过图片导出。")

    manifest = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "account": account,
        "account_root": str(account_root),
        "owner_wxid": owner_wxid,
        "output_dir": str(output_dir),
        "moments_json": extracted["json"],
        "moments_csv": extracted["csv"],
        "text": text,
        "text_dir": str(text_path.parent),
        "text_file": text_path.name,
        "report": report,
        "gallery": gallery,
        "images_enabled": include_images,
        "images_key_found": bool(image_key),
        "decrypt_report": str(output_dir / "internal" / "runtime_decrypt_report.json"),
    }
    manifest_path = output_dir / "export_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    logger(f"导出完成：{output_dir}")
    return manifest
