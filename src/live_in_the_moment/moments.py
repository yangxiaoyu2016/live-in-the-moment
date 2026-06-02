from __future__ import annotations

import csv
import html
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class Moment:
    created: datetime
    content: str
    post_id: str = ""
    tid: str = ""
    media_urls: tuple[str, ...] = ()
    thumb_urls: tuple[str, ...] = ()
    media_md5: tuple[str, ...] = ()

    @property
    def month(self) -> str:
        return self.created.strftime("%Y-%m")


def clean_text(value: str) -> str:
    return " ".join(html.unescape(value or "").replace("\r", " ").replace("\n", " ").split())


def parse_created(row: dict) -> datetime | None:
    raw_ts = row.get("create_time")
    if isinstance(raw_ts, (int, float)) and raw_ts > 0:
        return datetime.fromtimestamp(raw_ts)
    if isinstance(raw_ts, str) and raw_ts.isdigit():
        return datetime.fromtimestamp(int(raw_ts))
    for key in ("create_time_iso", "time", "created_at"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            try:
                return datetime.fromisoformat(value.strip())
            except ValueError:
                try:
                    return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    pass
    return None


def load_moments(input_path: Path, start_date: str = "", end_date: str = "") -> list[Moment]:
    rows = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("Input JSON must be a list of extracted Moments rows")
    start = datetime.strptime(start_date, "%Y-%m-%d") if start_date else None
    end = datetime.strptime(end_date + " 23:59:59", "%Y-%m-%d %H:%M:%S") if end_date else None
    moments: list[Moment] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        created = parse_created(row)
        if created is None:
            continue
        if start and created < start:
            continue
        if end and created > end:
            continue
        moments.append(
            Moment(
                created=created,
                content=clean_text(str(row.get("content_desc") or "")),
                post_id=str(row.get("post_id") or ""),
                tid=str(row.get("tid") or ""),
                media_urls=tuple(str(x) for x in (row.get("media_urls") or []) if isinstance(x, str)),
                thumb_urls=tuple(str(x) for x in (row.get("thumb_urls") or []) if isinstance(x, str)),
                media_md5=tuple(str(x) for x in (row.get("media_md5") or []) if isinstance(x, str)),
            )
        )
    return sorted(moments, key=lambda item: item.created)


def export_text(input_path: Path, output_dir: Path, start_date: str = "", end_date: str = "") -> dict:
    moments = load_moments(input_path, start_date=start_date, end_date=end_date)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "moments_text.json"
    csv_path = output_dir / "moments_text.csv"
    md_path = output_dir / "moments_text.md"
    txt_path = output_dir / "moments_text.txt"

    records = [
        {
            "time": item.created.strftime("%Y-%m-%d %H:%M:%S"),
            "content": item.content,
            "post_id": item.post_id,
            "tid": item.tid,
        }
        for item in moments
    ]
    json_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["time", "content", "post_id", "tid"])
        writer.writeheader()
        writer.writerows(records)
    md_path.write_text(
        "# WeChat Moments Text Export\n\n"
        + "\n\n".join(f"## {row['time']}\n\n{row['content'] or '[No text]'}" for row in records)
        + "\n",
        encoding="utf-8",
    )
    txt_path.write_text(
        "\n\n".join(f"{row['time']}\n{row['content'] or '[No text]'}" for row in records) + "\n",
        encoding="utf-8",
    )
    return {
        "moments": len(moments),
        "output_dir": str(output_dir),
        "json": str(json_path),
        "csv": str(csv_path),
        "markdown": str(md_path),
        "text": str(txt_path),
    }

