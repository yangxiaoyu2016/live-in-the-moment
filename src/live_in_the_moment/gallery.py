from __future__ import annotations

import csv
import hashlib
import html
import json
from collections import Counter, defaultdict
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps

from .media import cache_key_for_path, iter_month_image_cache, read_media
from .moments import Moment, load_moments


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def image_hashes_and_size(body: bytes) -> tuple[int, int, int, int, int]:
    with Image.open(BytesIO(body)) as image:
        image = ImageOps.exif_transpose(image)
        width, height = image.size
        gray = image.convert("L")

        d_img = gray.resize((9, 8), Image.Resampling.LANCZOS)
        d_pixels = list(d_img.getdata())
        dhash = 0
        for y in range(8):
            row = d_pixels[y * 9 : (y + 1) * 9]
            for x in range(8):
                dhash = (dhash << 1) | (1 if row[x] > row[x + 1] else 0)

        a_img = gray.resize((8, 8), Image.Resampling.LANCZOS)
        a_pixels = list(a_img.getdata())
        avg = sum(a_pixels) / len(a_pixels)
        ahash = 0
        for pixel in a_pixels:
            ahash = (ahash << 1) | (1 if pixel >= avg else 0)

        b_img = gray.resize((32, 32), Image.Resampling.LANCZOS)
        b_pixels = list(b_img.getdata())
        b_avg = sum(b_pixels) / len(b_pixels)
        block_hash = 0
        for pixel in b_pixels:
            block_hash = (block_hash << 1) | (1 if pixel >= b_avg else 0)

        return width, height, dhash, ahash, block_hash


def is_duplicate_image(
    keeper: dict,
    candidate: dict,
    dhash_threshold: int,
    ahash_threshold: int,
    crop_ahash_threshold: int,
    blockhash_threshold: int,
) -> bool:
    dhash_distance = hamming(keeper["dhash"], candidate["dhash"])
    ahash_distance = hamming(keeper["ahash"], candidate["ahash"])
    if dhash_distance <= dhash_threshold and ahash_distance <= ahash_threshold:
        return True
    block_distance = hamming(keeper["block_hash"], candidate["block_hash"])
    return ahash_distance <= crop_ahash_threshold and block_distance <= blockhash_threshold


def dedupe_records(
    records: list[dict],
    dhash_threshold: int = 10,
    ahash_threshold: int = 12,
    crop_ahash_threshold: int = 12,
    blockhash_threshold: int = 250,
) -> tuple[list[dict], int, int]:
    ordered = sorted(records, key=lambda item: (item["pixels"], item["size"]), reverse=True)
    used = [False] * len(ordered)
    kept: list[dict] = []
    groups = 0
    removed = 0
    for i, keeper in enumerate(ordered):
        if used[i]:
            continue
        used[i] = True
        duplicates: list[dict] = []
        for j in range(i + 1, len(ordered)):
            if used[j]:
                continue
            candidate = ordered[j]
            if is_duplicate_image(
                keeper,
                candidate,
                dhash_threshold,
                ahash_threshold,
                crop_ahash_threshold,
                blockhash_threshold,
            ):
                used[j] = True
                duplicates.append(candidate)
        if duplicates:
            groups += 1
            removed += len(duplicates)
        kept.append(
            {
                **keeper,
                "duplicate_group_size": len(duplicates) + 1,
                "removed_cache_keys": [item["cache_key"] for item in duplicates],
            }
        )
    return sorted(kept, key=lambda item: item["source_order"]), groups, removed


def collect_image_candidates(account_root: Path, months: set[str], aes_key: bytes, xor_key: int) -> tuple[dict[str, list[dict]], Counter]:
    by_month: dict[str, list[dict]] = defaultdict(list)
    stats = Counter()
    seen_content: set[str] = set()
    order = 0
    for month, path in iter_month_image_cache(account_root, months):
        media = read_media(path, aes_key=aes_key, xor_key=xor_key)
        if not media or media.ext == ".mp4":
            continue
        content_md5 = hashlib.md5(media.body).hexdigest()
        if content_md5 in seen_content:
            stats["exact_duplicates"] += 1
            continue
        seen_content.add(content_md5)
        try:
            width, height, dhash, ahash, block_hash = image_hashes_and_size(media.body)
        except Exception:
            stats["unreadable_images"] += 1
            continue
        by_month[month].append(
            {
                "month": month,
                "cache_key": cache_key_for_path(path),
                "body": media.body,
                "ext": media.ext,
                "content_md5": content_md5,
                "size": len(media.body),
                "width": width,
                "height": height,
                "pixels": width * height,
                "decoded": media.decoded,
                "dhash": dhash,
                "ahash": ahash,
                "block_hash": block_hash,
                "source_order": order,
            }
        )
        order += 1
        stats["decoded_candidates"] += 1
    return by_month, stats


def _render_posts(posts: list[Moment]) -> str:
    parts = []
    for post in posts:
        text = html.escape(post.content or "[No text]")
        parts.append(f"<li><time>{post.created:%Y-%m-%d %H:%M:%S}</time><p>{text}</p></li>")
    return "\n".join(parts)


def write_gallery_outputs(output_dir: Path, posts_by_month: dict[str, list[Moment]], images_by_month: dict[str, list[dict]], manifest: list[dict]) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    html_path = output_dir / "openable_moments_gallery.html"
    md_path = output_dir / "openable_moments_gallery.md"
    csv_path = output_dir / "openable_media_manifest.csv"
    json_path = output_dir / "openable_media_manifest.json"

    months = sorted(set(posts_by_month) | set(images_by_month))
    html_parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<title>Live in the moment export</title>",
        "<style>body{font-family:system-ui,sans-serif;max-width:1120px;margin:32px auto;padding:0 16px;line-height:1.5}.month{border-top:1px solid #ddd;margin-top:32px;padding-top:24px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px}.grid img{width:100%;height:180px;object-fit:cover;border-radius:6px}.muted{color:#666}time{font-weight:600}</style>",
        "</head><body><h1>Live in the moment export</h1>",
    ]
    md_parts = ["# Live in the moment export\n"]
    for month in months:
        posts = posts_by_month.get(month, [])
        images = images_by_month.get(month, [])
        html_parts.append(f"<section class='month' id='m-{month}'><h2>{month}</h2>")
        html_parts.append(f"<p class='muted'>{len(posts)} posts, {len(images)} images</p><ol>")
        html_parts.append(_render_posts(posts))
        html_parts.append("</ol><div class='grid'>")
        md_parts.append(f"\n## {month}\n")
        for post in posts:
            md_parts.append(f"- {post.created:%Y-%m-%d %H:%M:%S} {post.content or '[No text]'}")
        for image in images:
            rel = image["rel_path"]
            alt = f"{month} {image['cache_key']}"
            html_parts.append(f"<a href='{html.escape(rel)}'><img src='{html.escape(rel)}' alt='{html.escape(alt)}'></a>")
            md_parts.append(f"![{alt}]({rel})")
        html_parts.append("</div></section>")
    html_parts.append("</body></html>")
    html_path.write_text("\n".join(html_parts), encoding="utf-8")
    md_path.write_text("\n".join(md_parts) + "\n", encoding="utf-8")

    json_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        fieldnames = ["month", "rel_path", "cache_key", "content_md5", "size", "width", "height", "decoded", "duplicate_group_size", "removed_cache_keys"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in manifest:
            writer.writerow({key: row.get(key, "") for key in fieldnames})
    return {"html": str(html_path), "markdown": str(md_path), "manifest_csv": str(csv_path), "manifest_json": str(json_path)}


def build_gallery(
    input_path: Path,
    account_root: Path,
    output_dir: Path,
    v2_aes_key: str,
    v2_xor_key: int = 5,
    start_date: str = "",
    end_date: str = "",
) -> dict:
    if len(v2_aes_key.encode("ascii", errors="ignore")) != 16:
        raise ValueError("--v2-aes-key must be exactly 16 ASCII bytes")
    moments = load_moments(input_path, start_date=start_date, end_date=end_date)
    posts_by_month: dict[str, list[Moment]] = defaultdict(list)
    for moment in moments:
        posts_by_month[moment.month].append(moment)
    months = set(posts_by_month)
    output_media_root = output_dir / "media_by_month"
    output_media_root.mkdir(parents=True, exist_ok=True)

    candidates, stats = collect_image_candidates(account_root, months, v2_aes_key.encode("ascii"), v2_xor_key)
    images_by_month: dict[str, list[dict]] = defaultdict(list)
    manifest: list[dict] = []
    for month in sorted(candidates):
        kept, groups, removed = dedupe_records(candidates[month])
        stats["duplicate_groups"] += groups
        stats["removed_duplicates"] += removed
        month_dir = output_media_root / month
        month_dir.mkdir(parents=True, exist_ok=True)
        for index, image in enumerate(kept, start=1):
            filename = f"{index:04d}_{image['cache_key']}{image['ext']}"
            path = month_dir / filename
            path.write_bytes(image["body"])
            rel_path = path.relative_to(output_dir).as_posix()
            public_row = {
                "month": month,
                "rel_path": rel_path,
                "cache_key": image["cache_key"],
                "content_md5": image["content_md5"],
                "size": image["size"],
                "width": image["width"],
                "height": image["height"],
                "pixels": image["pixels"],
                "decoded": image["decoded"],
                "duplicate_group_size": image["duplicate_group_size"],
                "removed_cache_keys": image["removed_cache_keys"],
            }
            images_by_month[month].append(public_row)
            manifest.append(public_row)
            stats["decoded_images"] += 1

    outputs = write_gallery_outputs(output_dir, posts_by_month, images_by_month, manifest)
    return {
        "posts": len(moments),
        "posts_with_text": sum(1 for item in moments if item.content),
        "posts_with_media_refs": sum(1 for item in moments if item.media_urls or item.thumb_urls or item.media_md5),
        "months": len(months),
        **dict(stats),
        "output_dir": str(output_dir),
        **outputs,
    }

