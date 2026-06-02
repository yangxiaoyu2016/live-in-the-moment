from __future__ import annotations

import ctypes
import hashlib
import json
import re
import struct
import subprocess
from collections import Counter
from ctypes import wintypes
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
MEM_COMMIT = 0x1000
PAGE_GUARD = 0x100
PAGE_NOACCESS = 0x01
V2_MAGIC = (b"\x07\x08V1\x08\x07", b"\x07\x08V2\x08\x07")
IMAGE_SIGS = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"GIF87a", b"GIF89a", b"RIFF")


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


def weixin_pids() -> list[int]:
    cp = subprocess.run(
        ["wmic", "process", "where", "name='Weixin.exe'", "get", "ProcessId,CommandLine", "/format:list"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        check=False,
    )
    pids: list[int] = []
    for block in [item.strip() for item in cp.stdout.split("\n\n") if item.strip()]:
        pid = 0
        command = ""
        for line in block.splitlines():
            if line.startswith("CommandLine="):
                command = line.split("=", 1)[1]
            elif line.startswith("ProcessId="):
                try:
                    pid = int(line.split("=", 1)[1])
                except ValueError:
                    pid = 0
        if pid and "--type=" not in command:
            pids.insert(0, pid)
        elif pid:
            pids.append(pid)
    return pids


def parse_v2_sample(path: Path) -> bytes:
    data = path.read_bytes()
    if len(data) < 32 or data[:6] not in V2_MAGIC:
        raise ValueError(f"not a WeChat V1/V2 image cache sample: {path}")
    encrypted_length = struct.unpack_from("<H", data, 6)[0]
    encrypted_length_rounded = encrypted_length // 16 * 16 + 16
    return data[15 : 15 + encrypted_length_rounded]


def try_key(key: bytes, encrypted: bytes) -> bytes | None:
    if len(key) != 16 or len(encrypted) % 16:
        return None
    try:
        decryptor = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
        head = decryptor.update(encrypted[: min(len(encrypted), 4096)]) + decryptor.finalize()
    except Exception:
        return None
    pad = head[-1] if head else 0
    if 0 < pad <= 16:
        head = head[:-pad]
    return head if any(head.startswith(sig) for sig in IMAGE_SIGS) else None


def candidate_keys_from_chunk(data: bytes) -> set[bytes]:
    keys: set[bytes] = set()
    for match in re.finditer(rb"(?<![0-9A-Fa-f])[0-9A-Fa-f]{16}(?![0-9A-Fa-f])", data):
        keys.add(match.group(0))
    for match in re.finditer(rb"(?<![0-9A-Fa-f])[0-9A-Fa-f]{32}(?![0-9A-Fa-f])", data):
        raw = match.group(0)
        keys.add(raw[:16])
        try:
            keys.add(bytes.fromhex(raw.decode("ascii")))
        except ValueError:
            pass
    for marker in (b"cfcd208495d565ef", b"43e7d25eb1b9bb64", b"\x07\x08V1\x08\x07", b"\x07\x08V2\x08\x07"):
        index = data.find(marker)
        while index >= 0:
            area = data[max(0, index - 2048) : min(len(data), index + 2048)]
            for offset in range(0, max(0, len(area) - 15)):
                window = area[offset : offset + 16]
                if 8 <= sum(32 <= byte < 127 for byte in window) <= 16:
                    keys.add(window)
            index = data.find(marker, index + 1)
    return keys


def readable_regions(pid: int):
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        raise RuntimeError(f"OpenProcess failed, pid={pid}, err={ctypes.get_last_error()}")
    address = 0
    mbi = MemoryBasicInformation()
    try:
        while kernel32.VirtualQueryEx(handle, ctypes.c_void_p(address), ctypes.byref(mbi), ctypes.sizeof(mbi)):
            if mbi.State == MEM_COMMIT and not (mbi.Protect & PAGE_GUARD) and not (mbi.Protect & PAGE_NOACCESS):
                yield kernel32, handle, address, int(mbi.RegionSize)
            address += int(mbi.RegionSize)
            if address > 0x7FFFFFFFFFFF:
                break
    finally:
        kernel32.CloseHandle(handle)


def probe_process(pid: int, encrypted: bytes, max_mb: int = 0) -> dict:
    seen: set[bytes] = set()
    stats = Counter()
    total_read = 0
    for kernel32, handle, address, region_size in readable_regions(pid):
        offset = 0
        while offset < region_size:
            size = min(2 * 1024 * 1024, region_size - offset)
            buf = ctypes.create_string_buffer(size)
            read = ctypes.c_size_t(0)
            ok = kernel32.ReadProcessMemory(handle, ctypes.c_void_p(address + offset), buf, size, ctypes.byref(read))
            offset += size
            if not ok or not read.value:
                continue
            chunk = buf.raw[: read.value]
            total_read += len(chunk)
            stats["chunks"] += 1
            for key in candidate_keys_from_chunk(chunk):
                if key in seen:
                    continue
                seen.add(key)
                hit = try_key(key, encrypted)
                if hit is not None:
                    return {
                        "pid": pid,
                        "key_ascii": key.decode("ascii", errors="replace"),
                        "key_hex": key.hex(),
                        "tested_candidates": len(seen),
                        "read_mb": round(total_read / 1024 / 1024, 2),
                    }
            if max_mb and total_read >= max_mb * 1024 * 1024:
                return {"pid": pid, "key_ascii": "", "key_hex": "", "tested_candidates": len(seen), "read_mb": round(total_read / 1024 / 1024, 2), "limited": True}
    return {"pid": pid, "key_ascii": "", "key_hex": "", "tested_candidates": len(seen), "read_mb": round(total_read / 1024 / 1024, 2)}


def probe_v2_key(sample: Path, pid: int = 0, max_mb: int = 0) -> dict:
    encrypted = parse_v2_sample(sample)
    pids = [pid] if pid else weixin_pids()
    results = []
    for candidate_pid in pids:
        result = probe_process(candidate_pid, encrypted, max_mb=max_mb)
        results.append(result)
        if result.get("key_ascii"):
            break
    return {"pids": pids, "sample_encrypted_head_md5": hashlib.md5(encrypted[:16]).hexdigest(), "results": results}


def dumps_probe_result(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2)
