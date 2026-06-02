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

from .db_decrypt import candidate_source_roots
from .one_click import one_click_export


class App:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("Live in the moment")
        self.root.geometry("900x640")
        self.events: queue.Queue[str] = queue.Queue()

        source_roots = candidate_source_roots()
        self.source_root = StringVar(value=str(source_roots[0]) if source_roots else str(Path.home() / "xwechat_files"))
        self.output_dir = StringVar(value=str(Path.home() / "Documents" / "live-in-the-moment-output"))
        self.start_date = StringVar()
        self.end_date = StringVar()
        self.include_images = BooleanVar(value=True)

        self._build()
        self._poll_events()

    def _build(self) -> None:
        frame = ttk.Frame(self.root, padding=16)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Live in the moment - 微信朋友圈一键导出", font=("Segoe UI", 16, "bold")).grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 12)
        )
        ttk.Label(
            frame,
            text="使用前请先登录 Windows 版微信，并保持微信运行。本工具仅用于导出你本人、本机、已授权的朋友圈数据。",
            foreground="#8a4b00",
            wraplength=840,
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(0, 14))

        self._path_row(frame, 2, "微信数据目录", self.source_root, self._choose_source_root, extra=True)
        self._path_row(frame, 3, "输出目录", self.output_dir, self._choose_output_dir)

        ttk.Label(frame, text="开始日期").grid(row=4, column=0, sticky="w", pady=6)
        ttk.Entry(frame, textvariable=self.start_date, width=18).grid(row=4, column=1, sticky="w", pady=6)
        ttk.Label(frame, text="结束日期  YYYY-MM-DD，可留空").grid(row=4, column=1, sticky="w", padx=(160, 0), pady=6)
        ttk.Entry(frame, textvariable=self.end_date, width=18).grid(row=4, column=1, sticky="w", padx=(360, 0), pady=6)

        ttk.Checkbutton(frame, text="同时导出本地可打开图片 HTML（会自动探测图片缓存 Key）", variable=self.include_images).grid(
            row=5, column=0, columnspan=4, sticky="w", pady=8
        )

        actions = ttk.Frame(frame)
        actions.grid(row=6, column=0, columnspan=4, sticky="ew", pady=14)
        ttk.Button(actions, text="一键导出所有朋友圈", command=self._one_click).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="打开输出目录", command=self._open_output).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="重新自动检测", command=self._auto_source_root).pack(side="left")

        self.log = ScrolledText(frame, height=22, wrap="word")
        self.log.grid(row=7, column=0, columnspan=4, sticky="nsew", pady=(10, 0))
        self._log("准备就绪。确认 Windows 版微信已登录后，点击“一键导出所有朋友圈”。")
        if self.source_root.get():
            self._log(f"微信数据目录：{self.source_root.get()}")

        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(7, weight=1)

    def _path_row(self, frame: ttk.Frame, row: int, label: str, variable: StringVar, command, extra: bool = False) -> None:
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=6)
        ttk.Entry(frame, textvariable=variable, width=72).grid(row=row, column=1, sticky="ew", pady=6)
        ttk.Button(frame, text="浏览", command=command).grid(row=row, column=2, padx=8, pady=6)
        if extra:
            ttk.Button(frame, text="自动检测", command=self._auto_source_root).grid(row=row, column=3, pady=6)

    def _choose_source_root(self) -> None:
        path = filedialog.askdirectory(title="选择 xwechat_files 微信数据目录")
        if path:
            self.source_root.set(path)

    def _choose_output_dir(self) -> None:
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.output_dir.set(path)

    def _auto_source_root(self) -> None:
        roots = candidate_source_roots()
        if not roots:
            messagebox.showinfo("未找到", "没有自动找到 xwechat_files。请手动选择微信数据目录。")
            return
        self.source_root.set(str(roots[0]))
        self._log(f"已自动选择微信数据目录：{roots[0]}")

    def _validate(self) -> tuple[Path | None, Path]:
        raw_source = self.source_root.get().strip()
        source_root = Path(raw_source) if raw_source else None
        output_dir = Path(self.output_dir.get().strip())
        if source_root and not source_root.exists():
            raise ValueError("微信数据目录不存在，请重新选择 xwechat_files 目录。")
        if not output_dir:
            raise ValueError("请先选择输出目录。")
        return source_root, output_dir

    def _one_click(self) -> None:
        if not messagebox.askyesno(
            "确认一键导出",
            "这一步会读取本机正在运行的 Weixin.exe 进程内存，用于解密你本机的朋友圈数据库和图片缓存。\n\n请确认你正在处理的是自己的电脑、自己的微信账号或已获授权的数据。",
        ):
            return

        def job() -> dict:
            source_root, output_dir = self._validate()
            return one_click_export(
                output_dir=output_dir,
                source_root=source_root,
                include_images=self.include_images.get(),
                start_date=self.start_date.get().strip(),
                end_date=self.end_date.get().strip(),
                logger=self._thread_log,
            )

        self._run("一键导出", job)

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
                self.events.put(f"[{name}] 失败：{exc}\n{traceback.format_exc()}")

        threading.Thread(target=worker, daemon=True).start()

    def _thread_log(self, message: str) -> None:
        self.events.put(str(message))

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

