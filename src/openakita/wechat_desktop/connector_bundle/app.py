from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

import requests

from .config_service import clear_config, load_config, masked_token, save_config
from .connector_service import ConnectorService


class ConnectorApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("OpenAkita 微信 Connector")
        self.geometry("620x480")
        self.minsize(560, 430)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.service = ConnectorService(lambda value: self.after(0, self._set_status, value))
        self.oa_url = tk.StringVar()
        self.pair_code = tk.StringVar()
        self.node_name = tk.StringVar(value="Windows 微信节点")
        self.node_id = tk.StringVar(value="未配对")
        self.token_display = tk.StringVar(value="-")
        self.status = tk.StringVar(value="未配对")
        self.auto_start = tk.BooleanVar(value=False)
        self._build()
        self._load()

    def _build(self) -> None:
        root = ttk.Frame(self, padding=20)
        root.pack(fill="both", expand=True)
        ttk.Label(root, text="OpenAkita 微信 Connector", font=("Microsoft YaHei UI", 18, "bold")).pack(anchor="w")
        ttk.Label(root, text="连接 Windows 微信电脑版与 OpenAkita", foreground="#666").pack(anchor="w", pady=(3, 18))

        form = ttk.LabelFrame(root, text="配对设置", padding=14)
        form.pack(fill="x")
        for column in range(2):
            form.columnconfigure(column, weight=1)
        ttk.Label(form, text="OpenAkita 地址").grid(row=0, column=0, sticky="w")
        ttk.Label(form, text="8 位配对码").grid(row=0, column=1, sticky="w", padx=(12, 0))
        ttk.Entry(form, textvariable=self.oa_url).grid(row=1, column=0, sticky="ew", pady=(4, 10))
        ttk.Entry(form, textvariable=self.pair_code).grid(row=1, column=1, sticky="ew", padx=(12, 0), pady=(4, 10))
        ttk.Label(form, text="节点名称").grid(row=2, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.node_name).grid(row=3, column=0, sticky="ew", pady=(4, 0))
        ttk.Button(form, text="配对", command=self._pair).grid(row=3, column=1, sticky="e", padx=(12, 0))

        status = ttk.LabelFrame(root, text="运行状态", padding=14)
        status.pack(fill="x", pady=14)
        rows = [("状态", self.status), ("节点 ID", self.node_id), ("节点令牌", self.token_display)]
        for index, (label, value) in enumerate(rows):
            ttk.Label(status, text=label, width=12).grid(row=index, column=0, sticky="w", pady=3)
            ttk.Label(status, textvariable=value).grid(row=index, column=1, sticky="w", pady=3)

        actions = ttk.Frame(root)
        actions.pack(fill="x")
        ttk.Button(actions, text="启动", command=self._start).pack(side="left")
        ttk.Button(actions, text="停止", command=self.service.stop).pack(side="left", padx=8)
        ttk.Button(actions, text="重新连接", command=self.service.restart).pack(side="left")
        ttk.Button(actions, text="打开日志", command=self.service.open_log).pack(side="left", padx=8)
        ttk.Button(actions, text="清除配对", command=self._clear).pack(side="right")
        ttk.Checkbutton(root, text="启动应用后自动连接", variable=self.auto_start, command=self._save_preferences).pack(anchor="w", pady=(18, 0))

    def _load(self) -> None:
        config = load_config()
        self.oa_url.set(str(config.get("oa_url") or ""))
        self.node_name.set(str(config.get("node_name") or "Windows 微信节点"))
        self.auto_start.set(bool(config.get("auto_start")))
        if config.get("node_id"):
            self.node_id.set(str(config["node_id"]))
            self.token_display.set(masked_token(str(config.get("node_token") or "")))
            self.status.set("已配对")
            if self.auto_start.get():
                self.after(400, self._start)

    def _pair(self) -> None:
        url = self.oa_url.get().strip().rstrip("/")
        code = self.pair_code.get().strip()
        node_name = self.node_name.get().strip() or "Windows 微信节点"
        auto_start = self.auto_start.get()
        if not url.startswith(("http://", "https://")):
            messagebox.showerror("地址错误", "请输入完整的 http:// 或 https:// 地址")
            return
        if len(code) != 8 or not code.isdigit():
            messagebox.showerror("配对码错误", "请输入 8 位数字配对码")
            return
        self.status.set("正在配对")
        threading.Thread(
            target=self._pair_worker,
            args=(url, code, node_name, auto_start),
            daemon=True,
        ).start()

    def _pair_worker(self, url: str, code: str, node_name: str, auto_start: bool) -> None:
        try:
            response = requests.post(f"{url}/api/wechat-desktop/pair", json={"code": code}, timeout=30)
            data = response.json() if response.content else {}
            if not response.ok:
                detail = data.get("detail") if isinstance(data, dict) else None
                raise RuntimeError(str(detail or f"OpenAkita 返回 HTTP {response.status_code}"))
            config = {
                "oa_url": url,
                "node_id": data["node_id"],
                "node_token": data["node_token"],
                "node_name": node_name or data.get("node_name", "Windows 微信节点"),
                "auto_start": auto_start,
            }
            save_config(config)
            self.after(0, self._paired, config)
        except Exception as exc:
            message = str(exc)
            self.after(0, self._pair_failed, message)

    def _pair_failed(self, message: str) -> None:
        self.status.set("配对失败")
        messagebox.showerror("配对失败", message)

    def _paired(self, config: dict[str, Any]) -> None:
        self.node_id.set(str(config["node_id"]))
        self.token_display.set(masked_token(str(config["node_token"])))
        self.status.set("已配对")
        self.pair_code.set("")
        messagebox.showinfo("配对成功", "配置已保存，可以启动 Connector。")

    def _start(self) -> None:
        config = load_config()
        if not config.get("node_id"):
            messagebox.showwarning("尚未配对", "请先输入 OpenAkita 地址和配对码。")
            return
        try:
            self.service.start()
        except FileNotFoundError:
            messagebox.showerror("启动失败", "Connector Worker 文件不存在，请重新下载完整发布包。")

    def _set_status(self, value: str) -> None:
        self.status.set(value)

    def _save_preferences(self) -> None:
        config = load_config()
        config["auto_start"] = self.auto_start.get()
        save_config(config)

    def _clear(self) -> None:
        if not messagebox.askyesno("清除配对", "确定清除本机配对信息吗？"):
            return
        self.service.stop()
        clear_config()
        self.node_id.set("未配对")
        self.token_display.set("-")
        self.status.set("未配对")

    def _close(self) -> None:
        self.service.stop()
        self.destroy()


def main() -> None:
    ConnectorApp().mainloop()


if __name__ == "__main__":
    main()
