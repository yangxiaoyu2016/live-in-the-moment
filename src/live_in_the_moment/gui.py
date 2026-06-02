from __future__ import annotations

import json
import os
import queue
import threading
import traceback
import webbrowser
from pathlib import Path
from tkinter import BooleanVar, StringVar, Tk, filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from .gallery import build_gallery
from .media import V2_MAGIC
from .moments import export_text
from .probe import probe_v2_key


def candidate_account_roots() -> list[Path]:
    roots = [
        Path.home() / "xwechat_files",
        Path("D:/Cache/xwechat_files"),
        Path("C:/Cache/xwechat_files"),
    ]
    found: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for child in sorted(root.iterdir()):
            if child.is_dir() and (child / "cache").exists():
                found.append(child)
    return found


def find_v2_sample(account_root: Path) -> Path | None:
    img_root = account_root / "cache"
    if not img_root.exists():
        return None
    for path in img_root.glob("????-??/Sns/Img/**/*"):
        if not path.is_file():
            continue
        try:
            with path.open("rb") as f:
                head = f.read(6)
        except OSError:
            continue
        if head in V2_MAGIC:
            return path
    return None


class App:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("Live in the moment")
        self.root.geometry("880x680")
        self.events: queue.Queue[str] = queue.Queue()

        self.input_json = StringVar()
        self.account_root = StringVar()
        self.output_dir = StringVar(value=str(Path.home() / "Documents" / "live-in-the-moment-output"))
        self.v2_key = StringVar()
        self.start_date = StringVar()
        self.end_date = StringVar()
        self.include_images = BooleanVar(value=True)

        self._build()
        self._poll_events()

    def _build(self) -> None:
        frame = ttk.Frame(self.root, padding=16)
        frame.pack(fill="both", expand=True)

        title = ttk.Label(frame, text="Live in the moment - 微信朋友圈导出工具", font=("Segoe UI", 16, "bold"))
        title.grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 12))

        warning = (
            "仅用于导出你本人、本机、已授权的微信数据。不要把真实导出结果、图片、wxid 或密钥上传到公开仓库。"
        )
        ttk.Label(frame, text=warning, foreground="#8a4b00", wraplength=820).grid(row=1, column=0, columnspan=4, sticky="w", pady=(0, 14))

        self._path_row(frame, 2, "朋友圈 JSON", self.input_json, self._choose_json)
        self._path_row(frame, 3, "微信账号缓存目录", self.account_root, self._choose_account_root)
        self._path_row(frame, 4, "输出目录", self.output_dir, self._choose_output_dir)

        ttk.Label(frame, text="V2 图片 key").grid(row=5, column=0, sticky="w", pady=6)
        ttk.Entry(frame, textvariable=self.v2_key, show="*", width=70).grid(row=5, column=1, sticky="ew", pady=6)
        ttk.Button(frame, text="探测图片 Key", command=self._probe_key).grid(row=5, column=2, padx=8, pady=6)
        ttk.Button(frame, text="显示/隐藏", command=self._toggle_key_visibility).grid(row=5, column=3, pady=6)
        self.key_entry = frame.grid_slaves(row=5, column=1)[0]

        ttk.Label(frame, text="开始日期").grid(row=6, column=0, sticky="w", pady=6)
        ttk.Entry(frame, textvariable=self.start_date, width=18).grid(row=6, column=1, sticky="w", pady=6)
        ttk.Label(frame, text="结束日期  YYYY-MM-DD，可留空").grid(row=6, column=1, sticky="w", padx=(160, 0), pady=6)
        ttk.Entry(frame, textvariable=self.end_date, width=18).grid(row=6, column=1, sticky="w", padx=(360, 0), pady=6)

        actions = ttk.Frame(frame)
        actions.grid(row=7, column=0, columnspan=4, sticky="ew", pady=14)
        ttk.Button(actions, text="只导出文字", command=self._export_text).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="生成图文 HTML", command=self._build_gallery).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="打开输出目录", command=self._open_output).pack(side="left")

        self.log = ScrolledText(frame, height=22, wrap="word")
        self.log.grid(row=8, column=0, columnspan=4, sticky="nsew", pady=(10, 0))
        self._log("准备就绪。先选择朋友圈 JSON；如果要图片，再选择微信账号缓存目录并探测/填写 V2 图片 key。")

        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(8, weight=1)

        roots = candidate_account_roots()
        if roots:
            self.account_root.set(str(roots[0]))
            self._log(f"已自动发现微信账号缓存目录：{roots[0]}")

    def _path_row(self, frame: ttk.Frame, row: int, label: str, variable: StringVar, command) -> None:
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=6)
        ttk.Entry(frame, textvariable=variable, width=70).grid(row=row, column=1, sticky="ew", pady=6)
        ttk.Button(frame, text="浏览", command=command).grid(row=row, column=2, padx=8, pady=6)
        if label == "微信账号缓存目录":
            ttk.Button(frame, text="自动查找", command=self._auto_account_root).grid(row=row, column=3, pady=6)

    def _choose_json(self) -> None:
        path = filedialog.askopenfilename(title="选择 moments_extracted.json", filetypes=[("JSON", "*.json"), ("All files", "*.*")])
        if path:
            self.input_json.set(path)

    def _choose_account_root(self) -> None:
        path = filedialog.askdirectory(title="选择 xwechat_files 下的 wxid 账号目录")
        if path:
            self.account_root.set(path)

    def _choose_output_dir(self) -> None:
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.output_dir.set(path)

    def _auto_account_root(self) -> None:
        roots = candidate_account_roots()
        if not roots:
            messagebox.showinfo("未找到", "没有自动找到微信账号缓存目录，请手动选择 xwechat_files 下的账号目录。")
            return
        self.account_root.set(str(roots[0]))
        self._log(f"已选择：{roots[0]}")

    def _toggle_key_visibility(self) -> None:
        current = str(self.key_entry.cget("show"))
        self.key_entry.configure(show="" if current else "*")

    def _validate_common(self) -> tuple[Path, Path]:
        input_path = Path(self.input_json.get().strip())
        output_dir = Path(self.output_dir.get().strip())
        if not input_path.exists():
            raise ValueError("请先选择有效的 moments_extracted.json")
        if not output_dir:
            raise ValueError("请先选择输出目录")
        return input_path, output_dir

    def _export_text(self) -> None:
        def job() -> dict:
            input_path, output_dir = self._validate_common()
            return export_text(input_path, output_dir, self.start_date.get().strip(), self.end_date.get().strip())

        self._run("导出文字", job)

    def _build_gallery(self) -> None:
        def job() -> dict:
            input_path, output_dir = self._validate_common()
            account_root = Path(self.account_root.get().strip())
            key = self.v2_key.get().strip()
            if not account_root.exists():
                raise ValueError("请先选择有效的微信账号缓存目录")
            if len(key.encode("ascii", errors="ignore")) != 16:
                raise ValueError("请填写 16 位 ASCII V2 图片 key，或先点击“探测图片 Key”")
            return build_gallery(
                input_path=input_path,
                account_root=account_root,
                output_dir=output_dir,
                v2_aes_key=key,
                start_date=self.start_date.get().strip(),
                end_date=self.end_date.get().strip(),
            )

        self._run("生成图文 HTML", job)

    def _probe_key(self) -> None:
        if not messagebox.askyesno(
            "确认探测图片 Key",
            "这一步会读取本机正在运行的 Weixin.exe 进程内存，用于寻找图片缓存 key。\n\n请确认这台电脑和微信账号都是你本人或已获授权的数据。",
        ):
            return

        def job() -> dict:
            account_root = Path(self.account_root.get().strip())
            if not account_root.exists():
                raise ValueError("请先选择有效的微信账号缓存目录")
            sample = find_v2_sample(account_root)
            if sample is None:
                raise ValueError("没有在该账号缓存目录下找到 V2 图片缓存样本")
            result = probe_v2_key(sample)
            for item in result.get("results", []):
                key = item.get("key_ascii") or ""
                if key:
                    self.v2_key.set(key)
                    break
            return result

        self._run("探测图片 Key", job)

    def _open_output(self) -> None:
        path = Path(self.output_dir.get().strip())
        path.mkdir(parents=True, exist_ok=True)
        webbrowser.open(path.as_uri())

    def _run(self, name: str, fn) -> None:
        self._log(f"\n[{name}] 开始...")

        def worker() -> None:
            try:
                result = fn()
                self.events.put(f"[{name}] 完成\n{json.dumps(result, ensure_ascii=False, indent=2)}")
            except Exception as exc:
                detail = traceback.format_exc()
                self.events.put(f"[{name}] 失败：{exc}\n{detail}")

        threading.Thread(target=worker, daemon=True).start()

    def _poll_events(self) -> None:
        while True:
            try:
                message = self.events.get_nowait()
            except queue.Empty:
                break
            self._log(message)
        self.root.after(200, self._poll_events)

    def _log(self, message: str) -> None:
        self.log.insert("end", message + "\n")
        self.log.see("end")


def main() -> int:
    os.environ.setdefault("PYTHONUTF8", "1")
    root = Tk()
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

