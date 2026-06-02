from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .gallery import build_gallery
from .moments import export_text
from .one_click import one_click_export
from .probe import probe_v2_key


def _print_result(result: dict) -> None:
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(prog="limm", description="Archive your own WeChat Moments.")
    sub = parser.add_subparsers(dest="command", required=True)

    text = sub.add_parser("export-text", help="Export Moments date and text from moments_extracted.json")
    text.add_argument("--input", required=True, type=Path)
    text.add_argument("--output-dir", required=True, type=Path)
    text.add_argument("--start-date", default="", help="Inclusive YYYY-MM-DD")
    text.add_argument("--end-date", default="", help="Inclusive YYYY-MM-DD")

    gallery = sub.add_parser("build-gallery", help="Build a local HTML gallery from Moments and WeChat image cache")
    gallery.add_argument("--input", required=True, type=Path)
    gallery.add_argument("--account-root", required=True, type=Path)
    gallery.add_argument("--output-dir", required=True, type=Path)
    gallery.add_argument("--v2-aes-key", required=True, help="16 ASCII bytes, for example: 0123456789abcdef")
    gallery.add_argument("--v2-xor-key", type=int, default=5)
    gallery.add_argument("--start-date", default="", help="Inclusive YYYY-MM-DD")
    gallery.add_argument("--end-date", default="", help="Inclusive YYYY-MM-DD")

    probe = sub.add_parser("probe-v2-key", help="Probe a running Weixin.exe process for the V2 image cache AES key")
    probe.add_argument("--sample", required=True, type=Path, help="One encrypted WeChat V1/V2 image cache file")
    probe.add_argument("--pid", type=int, default=0, help="Weixin.exe PID. Omit to auto-detect.")
    probe.add_argument("--max-mb", type=int, default=0, help="Maximum MB to read per process; 0 means no explicit limit.")

    one_click = sub.add_parser("one-click", help="Export all Moments from the currently logged-in Windows WeChat")
    one_click.add_argument("--source-root", type=Path, default=None, help="Optional xwechat_files root. Omit to auto-detect.")
    one_click.add_argument("--output-dir", required=True, type=Path)
    one_click.add_argument("--no-images", action="store_true", help="Skip image gallery generation")
    one_click.add_argument("--start-date", default="", help="Inclusive YYYY-MM-DD")
    one_click.add_argument("--end-date", default="", help="Inclusive YYYY-MM-DD")
    one_click.add_argument("--pid", type=int, default=0, help="Main Weixin.exe PID. Omit to auto-detect.")

    args = parser.parse_args(argv)
    if args.command == "export-text":
        _print_result(export_text(args.input, args.output_dir, start_date=args.start_date, end_date=args.end_date))
        return 0
    if args.command == "build-gallery":
        _print_result(
            build_gallery(
                input_path=args.input,
                account_root=args.account_root,
                output_dir=args.output_dir,
                v2_aes_key=args.v2_aes_key,
                v2_xor_key=args.v2_xor_key,
                start_date=args.start_date,
                end_date=args.end_date,
            )
        )
        return 0
    if args.command == "probe-v2-key":
        _print_result(probe_v2_key(args.sample, pid=args.pid, max_mb=args.max_mb))
        return 0
    if args.command == "one-click":
        _print_result(
            one_click_export(
                output_dir=args.output_dir,
                source_root=args.source_root,
                include_images=not args.no_images,
                start_date=args.start_date,
                end_date=args.end_date,
                pid=args.pid,
            )
        )
        return 0
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
