from __future__ import annotations

import ctypes
import json
import re
import sqlite3
import subprocess
from ctypes import wintypes
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
MEM_COMMIT = 0x1000
PAGE_GUARD = 0x100
PAGE_NOACCESS = 0x01

HEX96_RE = re.compile(rb"x'([0-9a-f]{96})'", re.IGNORECASE)
SNS_PATH_RE = re.compile(rb"[A-Za-z]:\\[^\x00\r\n]{0,320}?db_storage\\sns\\sns\.db", re.IGNORECASE)


class MemoryBasicInformation(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
    ]


def run_cmd(args: list[str]) -> str:
    cp = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="ignore", check=False)
    return cp.stdout


def find_main_weixin_pid() -> int:
    out = run_cmd(["wmic", "process", "where", "name='Weixin.exe'", "get", "ProcessId,CommandLine", "/format:list"])
    candidates: list[int] = []
    for block in [item.strip() for item in out.split("\n\n") if item.strip()]:
        pid = 0
        command = ""
        for line in block.splitlines():
            line = line.strip()
            if line.startswith("CommandLine="):
                command = line.split("=", 1)[1]
            elif line.startswith("ProcessId="):
                try:
                    pid = int(line.split("=", 1)[1])
                except ValueError:
                    pid = 0
        if pid and "--type=" not in command:
            candidates.append(pid)
    if not candidates:
        raise RuntimeError("没有找到主 Weixin.exe 进程。请先登录 Windows 版微信，并保持微信运行。")
    return candidates[0]


def walk_memory(pid: int, callback, limit_hits: int) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        raise RuntimeError(f"读取微信进程失败，pid={pid}, err={ctypes.get_last_error()}。请确认微信正在运行，必要时用同等权限运行本工具。")

    address = 0
    hits = 0
    mbi = MemoryBasicInformation()
    try:
        while kernel32.VirtualQueryEx(handle, ctypes.c_void_p(address), ctypes.byref(mbi), ctypes.sizeof(mbi)):
            if mbi.State == MEM_COMMIT and not (mbi.Protect & PAGE_GUARD) and not (mbi.Protect & PAGE_NOACCESS):
                offset = 0
                region_size = int(mbi.RegionSize)
                while offset < region_size:
                    size = min(2 * 1024 * 1024, region_size - offset)
                    buf = ctypes.create_string_buffer(size)
                    read = ctypes.c_size_t(0)
                    ok = kernel32.ReadProcessMemory(handle, ctypes.c_void_p(address + offset), buf, size, ctypes.byref(read))
                    offset += size
                    if not ok or not read.value:
                        continue
                    hits += callback(buf.raw[: read.value])
                    if hits >= limit_hits:
                        return
            address += int(mbi.RegionSize)
            if address > 0x7FFFFFFFFFFF:
                break
    finally:
        kernel32.CloseHandle(handle)


def read_process_for_hex96(pid: int, limit: int = 300) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def callback(data: bytes) -> int:
        local = 0
        for match in HEX96_RE.finditer(data):
            value = match.group(1).decode("ascii").lower()
            if value in seen:
                continue
            seen.add(value)
            found.append(value)
            local += 1
            if len(found) >= limit:
                break
        return local

    walk_memory(pid, callback, limit)
    return found


def read_process_for_sns_paths(pid: int, limit: int = 50) -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()

    def callback(data: bytes) -> int:
        local = 0
        for match in SNS_PATH_RE.finditer(data):
            raw = match.group(0).decode("ascii", errors="ignore")
            path = Path(raw)
            key = str(path).lower()
            if key in seen:
                continue
            seen.add(key)
            found.append(path)
            local += 1
            if len(found) >= limit:
                break
        return local

    walk_memory(pid, callback, limit)
    return found


def candidate_source_roots() -> list[Path]:
    roots = [
        Path.home() / "xwechat_files",
        Path.home() / "Documents" / "WeChat Files",
        Path("D:/Cache/xwechat_files"),
        Path("C:/Cache/xwechat_files"),
    ]
    return [root for root in roots if root.exists()]


def pick_latest_sns_db(source_root: Path | None = None) -> Path:
    roots = [source_root] if source_root else candidate_source_roots()
    candidates: list[Path] = []
    for root in roots:
        if not root or not root.exists():
            continue
        for db_path in root.glob("*/db_storage/sns/sns.db"):
            if db_path.exists():
                candidates.append(db_path)
    if not candidates:
        raise RuntimeError("没有找到 sns.db。请确认微信数据目录可访问，或手动选择 xwechat_files 目录。")
    candidates.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return candidates[0]


def auto_select_sns_db(pid: int, source_root: Path | None = None) -> tuple[Path, str]:
    memory_paths = [path for path in read_process_for_sns_paths(pid) if path.exists()]
    if source_root:
        root_text = str(source_root).lower()
        memory_paths = [path for path in memory_paths if str(path).lower().startswith(root_text)]
    if memory_paths:
        memory_paths.sort(key=lambda item: item.stat().st_mtime, reverse=True)
        return memory_paths[0], "memory"
    return pick_latest_sns_db(source_root), "latest-mtime"


def account_name_from_db_path(db_path: Path) -> str:
    try:
        return db_path.parents[2].name
    except IndexError:
        return "unknown-account"


def guess_owner_wxid(account: str) -> str:
    match = re.match(r"^(wxid_[A-Za-z0-9]+)_[0-9a-fA-F]{4}$", account)
    if match:
        return match.group(1)
    return account


def aes_cbc_decrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    return decryptor.update(data) + decryptor.finalize()


def parse_page_size(first: int, second: int) -> int:
    value = (first << 8) | second
    return 65536 if value == 1 else value


def looks_like_sqlite_header_part(block: bytes) -> tuple[bool, int]:
    if len(block) != 16:
        return False, 0
    page_size = parse_page_size(block[0], block[1])
    page_ok = 512 <= page_size <= 65536 and (page_size & (page_size - 1)) == 0
    header_ok = block[2] in (1, 2) and block[3] in (1, 2) and block[5] == 64 and block[6] == 32 and block[7] == 32
    return page_ok and header_ok, page_size


def pick_key_for_db(hex96_list: list[str], db_path: Path) -> dict:
    page0 = db_path.read_bytes()[:4096]
    if len(page0) < 4096:
        raise RuntimeError("sns.db 太小，无法识别为有效数据库。")
    salt_hex = page0[:16].hex()
    matched = [item for item in hex96_list if item.endswith(salt_hex)]
    candidates = []
    for item in matched:
        key = bytes.fromhex(item[:64])
        for reserve in (80, 48, 64, 96):
            iv = page0[4096 - reserve : 4096 - reserve + 16]
            try:
                plain_block = aes_cbc_decrypt(key, iv, page0[16:32])
            except Exception:
                continue
            ok, page_size = looks_like_sqlite_header_part(plain_block)
            if ok:
                candidates.append(
                    {
                        "key_hex": item[:64],
                        "reserve": reserve,
                        "page_size": page_size,
                        "matched_salt": salt_hex,
                    }
                )
    if not candidates:
        raise RuntimeError("没有在微信进程中匹配到当前 sns.db 的数据库 key。请保持微信登录后重试。")
    return {"salt_hex": salt_hex, "matched_count": len(matched), "selected": candidates[0], "candidates": candidates}


def decrypt_db(src_db: Path, dst_db: Path, key_hex: str, reserve: int, page_size: int) -> dict:
    src = src_db.read_bytes()
    if len(src) % page_size != 0:
        raise RuntimeError(f"数据库大小不是 page_size 的整数倍：size={len(src)}, page_size={page_size}")
    key = bytes.fromhex(key_hex)
    out = bytearray(len(src))
    total_pages = len(src) // page_size
    for page_index in range(total_pages):
        start = page_index * page_size
        page = src[start : start + page_size]
        iv = page[page_size - reserve : page_size - reserve + 16]
        if page_index == 0:
            encrypted = page[16 : page_size - reserve]
            decrypted = aes_cbc_decrypt(key, iv, encrypted)
            out_page = bytearray(page_size)
            out_page[:16] = b"SQLite format 3\x00"
            out_page[16 : 16 + len(decrypted)] = decrypted
        else:
            encrypted = page[: page_size - reserve]
            decrypted = aes_cbc_decrypt(key, iv, encrypted)
            out_page = bytearray(page_size)
            out_page[: len(decrypted)] = decrypted
        out[start : start + page_size] = out_page
    dst_db.parent.mkdir(parents=True, exist_ok=True)
    dst_db.write_bytes(out)
    with sqlite3.connect(dst_db) as conn:
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        timeline_rows = None
        if "SnsTimeLine" in tables:
            timeline_rows = conn.execute("SELECT COUNT(1) FROM SnsTimeLine").fetchone()[0]
    return {"out_db": str(dst_db), "table_count": len(tables), "sns_timeline_rows": timeline_rows}


def decrypt_logged_in_sns_db(output_dir: Path, source_root: Path | None = None, pid: int = 0, logger=print) -> dict:
    use_pid = pid or find_main_weixin_pid()
    logger(f"[1/5] 已找到微信进程：{use_pid}")
    db_path, detect_source = auto_select_sns_db(use_pid, source_root)
    account = account_name_from_db_path(db_path)
    logger(f"[2/5] 已找到朋友圈数据库：{db_path}")
    hex96_list = read_process_for_hex96(use_pid)
    key_pick = pick_key_for_db(hex96_list, db_path)
    selected = key_pick["selected"]
    plain_db = output_dir / "internal" / "sns_plain.db"
    decrypt_result = decrypt_db(db_path, plain_db, selected["key_hex"], selected["reserve"], selected["page_size"])
    report = {
        "pid": use_pid,
        "account": account,
        "owner_wxid": guess_owner_wxid(account),
        "db": str(db_path),
        "detect_source": detect_source,
        "runtime_hex96_count": len(hex96_list),
        "key_pick": key_pick,
        "decrypt_result": decrypt_result,
        "plain_db": str(plain_db),
    }
    report_path = output_dir / "internal" / "runtime_decrypt_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    logger("[3/5] 朋友圈数据库解密完成")
    return report

