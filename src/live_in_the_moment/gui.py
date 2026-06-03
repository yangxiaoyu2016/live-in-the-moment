from __future__ import annotations

import os
import queue
import threading
import traceback
import webbrowser
from pathlib import Path
from tkinter import StringVar, Tk, filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from . import __version__
from .db_decrypt import candidate_source_roots
from .one_click import one_click_export, validate_date_range
from .report import build_report_from_txt


def should_show_gui_log(message: str) -> bool:
    hidden_prefixes = ("[2/5]", "[3/5]")
    return not str(message).lstrip().startswith(hidden_prefixes)


class App:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title(f"Live in the Moment v{__version__}")
        self.root.geometry("940x700")
        self.events: queue.Queue[str] = queue.Queue()

        source_roots = candidate_source_roots()
        self.source_root = StringVar(value=str(source_roots[0]) if source_roots else str(Path.home() / "xwechat_files"))
        self.output_dir = StringVar(value=str(Path.home() / "Documents" / "live-in-the-moment-output"))
        self.report_txt = StringVar(value=str(self._default_report_txt()))
        self.start_date = StringVar()
        self.end_date = StringVar()

        self._build()
        self._poll_events()

    def _build(self) -> None:
        frame = ttk.Frame(self.root, padding=16)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame,
            text=f"Live in the Moment - 微信朋友圈一键导出 v{__version__} - made by Yang&Codex",
            font=("Segoe UI", 16, "bold"),
        ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 12))
        ttk.Label(
            frame,
            text=(
                "使用前请先登录 Windows 版微信，并保持微信正在运行。"
                "本工具只导出你本人、本机、已登录账号可读取的朋友圈数据。"
            ),
            foreground="#8a4b00",
            wraplength=840,
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(0, 14))

        self._path_row(frame, 2, "微信数据目录", self.source_root, self._choose_source_root, extra=True)
        self._path_row(frame, 3, "输出目录", self.output_dir, self._choose_output_dir)

        ttk.Label(frame, text="开始日期  YYYY-MM-DD，可留空").grid(row=4, column=0, sticky="w", pady=6)
        ttk.Entry(frame, textvariable=self.start_date, width=18).grid(row=4, column=1, sticky="w", pady=6)
        ttk.Label(frame, text="结束日期  YYYY-MM-DD，可留空").grid(row=4, column=1, sticky="w", padx=(160, 0), pady=6)
        ttk.Entry(frame, textvariable=self.end_date, width=18).grid(row=4, column=1, sticky="w", padx=(360, 0), pady=6)

        self._path_row(frame, 5, "朋友圈 TXT", self.report_txt, self._choose_report_txt)

        actions = ttk.Frame(frame)
        actions.grid(row=6, column=0, columnspan=4, sticky="ew", pady=14)
        ttk.Button(actions, text="一键导出所有朋友圈", command=self._one_click).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="生成 HTML 个人报告", command=self._generate_report).pack(side="left", padx=(0, 8))
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
            self.report_txt.set(str(self._default_report_txt()))

    def _choose_report_txt(self) -> None:
        path = filedialog.askopenfilename(
            title="选择 moments_text.txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if path:
            self.report_txt.set(path)

    def _auto_source_root(self) -> None:
        roots = candidate_source_roots()
        if not roots:
            messagebox.showinfo("未找到", "没有自动找到 xwechat_files。请手动选择微信数据目录。")
            return
        self.source_root.set(str(roots[0]))
        self._log(f"已自动选择微信数据目录：{roots[0]}")

    def _validate(self) -> tuple[Path | None, Path, str, str]:
        raw_source = self.source_root.get().strip()
        raw_output = self.output_dir.get().strip()
        source_root = Path(raw_source) if raw_source else None
        if source_root and not source_root.exists():
            raise ValueError("微信数据目录不存在，请重新选择 xwechat_files 目录。")
        if not raw_output:
            raise ValueError("请先选择输出目录。")
        start_date, end_date = validate_date_range(self.start_date.get(), self.end_date.get())
        return source_root, Path(raw_output), start_date, end_date

    def _one_click(self) -> None:
        try:
            source_root, output_dir, start_date, end_date = self._validate()
        except ValueError as exc:
            messagebox.showerror("格式不对", str(exc))
            return

        if not messagebox.askyesno(
            "确认一键导出",
            (
                "这一步会读取本机正在运行的 Weixin.exe 进程内存，"
                "用于解密你本人本机的朋友圈数据库。\n\n"
                "请确认你正在导出的账号是自己的微信账号，并且微信已登录。"
            ),
        ):
            return

        def job() -> dict:
            return one_click_export(
                output_dir=output_dir,
                source_root=source_root,
                include_images=False,
                start_date=start_date,
                end_date=end_date,
                logger=self._thread_log,
            )

        self._run("一键导出", job)

    def _default_report_txt(self) -> Path:
        return Path(self.output_dir.get().strip()) / "text" / "moments_text.txt"

    def _generate_report(self) -> None:
        raw_path = self.report_txt.get().strip()
        txt_path = Path(raw_path) if raw_path else self._default_report_txt()
        if not txt_path.exists():
            messagebox.showerror("未找到 TXT", f"没有找到朋友圈 TXT：\n{txt_path}")
            return

        def job() -> dict:
            result = build_report_from_txt(txt_path)
            report_path = Path(result["html"])
            self._thread_log(f"朋友圈个人报告保存在了：目录 {report_path.parent}，文件 {report_path.name}")
            webbrowser.open(report_path.as_uri())
            return result

        self._run("生成 HTML 个人报告", job)

    def _open_output(self) -> None:
        path = Path(self.output_dir.get().strip())
        path.mkdir(parents=True, exist_ok=True)
        webbrowser.open(path.as_uri())

    def _run(self, name: str, fn) -> None:
        self._log(f"\n[{name}] 开始...")

        def worker() -> None:
            try:
                fn()
                self.events.put(f"[{name}] 完成")
            except Exception as exc:
                self.events.put(f"[{name}] 失败：{exc}\n{traceback.format_exc()}")

        threading.Thread(target=worker, daemon=True).start()

    def _thread_log(self, message: str) -> None:
        if not should_show_gui_log(str(message)):
            return
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
