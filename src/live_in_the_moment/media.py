from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

IMAGE_SIGNATURES = (
    (b"\xff\xd8\xff", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
)
V2_MAGIC = (b"\x07\x08V1\x08\x07", b"\x07\x08V2\x08\x07")


@dataclass(frozen=True)
class MediaBytes:
    body: bytes
    ext: str
    decoded: bool


def sniff_ext(head: bytes) -> str:
    for sig, ext in IMAGE_SIGNATURES:
        if head.startswith(sig):
            return ext
    if head.startswith(b"RIFF") and b"WEBP" in head[:16]:
        return ".webp"
    if len(head) > 12 and head[4:8] == b"ftyp":
        return ".mp4"
    return ""


def decode_v2_image_bytes(data: bytes, aes_key: bytes, xor_key: int = 5) -> bytes:
    if len(data) < 32 or data[:6] not in V2_MAGIC or len(aes_key) != 16:
        return b""
    encrypted_length = struct.unpack_from("<H", data, 6)[0]
    encrypted_length_rounded = encrypted_length // 16 * 16 + 16
    encrypted = data[15 : 15 + encrypted_length_rounded]
    rest = data[15 + encrypted_length_rounded :]
    if not encrypted or len(encrypted) % 16:
        return b""

    decryptor = Cipher(algorithms.AES(aes_key), modes.ECB()).decryptor()
    decrypted = decryptor.update(encrypted) + decryptor.finalize()
    pad = decrypted[-1] if decrypted else 0
    if 0 < pad <= 16:
        decrypted = decrypted[:-pad]

    if rest:
        split = max(0, len(rest) - 0x100000)
        rest = rest[:split] + bytes(byte ^ xor_key for byte in rest[split:])

    output = decrypted + rest
    return output if sniff_ext(output[:64]) else b""


def read_media(path: Path, aes_key: bytes = b"", xor_key: int = 5) -> MediaBytes | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    ext = sniff_ext(data[:64])
    if ext:
        return MediaBytes(data, ext, decoded=False)
    if aes_key and data[:6] in V2_MAGIC:
        decoded = decode_v2_image_bytes(data, aes_key, xor_key)
        ext = sniff_ext(decoded[:64])
        if decoded and ext:
            return MediaBytes(decoded, ext, decoded=True)
    return None


def cache_key_for_path(path: Path) -> str:
    candidates = [path.stem.lower(), path.name.lower()]
    if path.parent.name:
        candidates.append((path.parent.name + path.name).lower())
        candidates.append((path.parent.name + path.stem).lower())
    for candidate in candidates:
        if len(candidate) == 32 and all(ch in "0123456789abcdef" for ch in candidate):
            return candidate
    return hashlib.md5(str(path).encode("utf-8", errors="ignore")).hexdigest()


def iter_month_image_cache(account_root: Path, months: set[str] | None = None):
    cache_root = account_root / "cache"
    if not cache_root.exists():
        return
    for month_dir in sorted(cache_root.glob("????-??")):
        if months and month_dir.name not in months:
            continue
        sns_img = month_dir / "Sns" / "Img"
        if not sns_img.exists():
            continue
        for path in sns_img.rglob("*"):
            if path.is_file():
                yield month_dir.name, path

