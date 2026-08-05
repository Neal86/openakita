from __future__ import annotations

import os
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any

import psutil
import requests
import yaml

from app_paths import CONFIG_PATH, LOG_PATH

APP_TITLE = "OpenAkita 微信连接器"


def executable_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--connector"]
    return [sys.executable, str(Path(__file__).with_name("main.py")), "--connector"]


def detect_wechat_processes() -> list[str]:
    matches: list[str] = []
    for process in psutil.process_iter(["pid", "name"]):
        try:
            name = str(process.info.get("name") or "")
            if name.lower() in {"wechat.exe", "weixin.exe"}:
                matches.append(f"{name} (PID {process.info['pid']})")
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    return matches


class ConnectorApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("720x560")
        self.minsize(680, 520)
        self.protocol("WM_DELETE_WINDOW", self.close_app)
        self.process: subprocess.Popen[Any] | None = None
        self.oa_url = tk.StringVar()
        self.pair_code = tk.StringVar()
        self.wechat_status = tk.StringVar(value="正在检测微信…")
        self.connection_status = tk.StringVar(value="未启动")
        self.node_name = tk.StringVar(value="未配对")
        self._build_ui()
        self._load_config()
        self.refresh_wechat()
        self.after(1000, self._refresh_runtime_state)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=20)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text=APP_TITLE, font=("Microsoft YaHei UI", 18, "bold")).pack(anchor="w")
        ttk.Label(outer, text="连接已登录的 Windows 微信电脑版，并由 OpenAkita Agent 自动收发消息。", foreground="#555555").pack(anchor="w", pady=(4, 18))

        card = ttk.LabelFrame(outer, text="连接设置", padding=14)
        card.pack(fill="x")
        card.columnconfigure(1, weight=1)

        ttk.Label(card, text="OA 地址").grid(row=0, column=0, sticky="w", padx=(0, 12), pady=6)
        ttk.Entry(card, textvariable=self.oa_url).grid(row=0, column=1, sticky="ew", pady=6)
        ttk.Label(card, text="配对码").grid(row=1, column=0, sticky="w", padx=(0, 12), pady=6)
        ttk.Entry(card, textvariable=self.pair_code, show="•").grid(row=1, column=1, sticky="ew", pady=6)
        ttk.Button(card, text="完成配对", command=self.pair).grid(row=1, column=2, padx=(10, 0), pady=6)

        ttk.Separator(card).grid(row=2, column=0, columnspan=3, sticky="ew", pady=10)
        ttk.Label(card, text="微信状态").grid(row=3, column=0, sticky="w", padx=(0, 12), pady=6)
        ttk.Label(card, textvariable=self.wechat_status).grid(row=3, column=1, sticky="w", pady=6)
        ttk.Button(card, text="重新检测", command=self.refresh_wechat).grid(row=3, column=2, padx=(10, 0), pady=6)
        ttk.Label(card, text="节点名称").grid(row=4, column=0, sticky="w", padx=(0, 12), pady=6)
        ttk.Label(card, textvariable=self.node_name).grid(row=4, column=1, sticky="w", pady=6)
        ttk.Label(card, text="Agent 绑定").grid(row=5, column=0, sticky="w", padx=(0, 12), pady=6)
        ttk.Label(card, text="在 OpenAkita 设置中心选择微信账号并绑定 Agent").grid(row=5, column=1, columnspan=2, sticky="w", pady=6)

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=16)
        self.start_button = ttk.Button(actions, text="启动连接器", command=self.start_connector)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(actions, text="停止", command=self.stop_connector, state="disabled")
        self.stop_button.pack(side="left", padx=8)
        ttk.Label(actions, text="运行状态：").pack(side="left", padx=(18, 0))
        ttk.Label(actions, textvariable=self.connection_status).pack(side="left")

        log_card = ttk.LabelFrame(outer, text="运行日志", padding=8)
        log_card.pack(fill="both", expand=True)
        self.log_text = tk.Text(log_card, height=12, wrap="word", state="disabled", font=("Consolas", 9))
        scrollbar = ttk.Scrollbar(log_card, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def _load_config(self) -> None:
        if not CONFIG_PATH.exists():
            return
        try:
            data = yaml.safe_load(CONFIG_PATH.read_text("utf-8")) or {}
            self.oa_url.set(str(data.get("oa_url") or ""))
            self.node_name.set(str(data.get("node_name") or data.get("node_id") or "已配对"))
        except Exception as exc:
            self._append_log(f"读取配置失败：{exc}")

    def pair(self) -> None:
        oa_url = self.oa_url.get().strip().rstrip("/")
        code = self.pair_code.get().strip()
        if not oa_url.startswith(("http://", "https://")) or not code:
            messagebox.showerror(APP_TITLE, "请输入正确的 OA 地址和配对码。")
            return

        def work() -> None:
            try:
                response = requests.post(f"{oa_url}/api/wechat-desktop/pair", json={"code": code}, timeout=30)
                response.raise_for_status()
                data = response.json()
                config = {
                    "oa_url": oa_url,
                    "node_id": data["node_id"],
                    "node_token": data["node_token"],
                    "node_name": data.get("node_name", "Windows 微信节点"),
                }
                CONFIG_PATH.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), "utf-8")
                self.after(0, lambda: self._pair_succeeded(config["node_name"]))
            except Exception as exc:
                self.after(0, lambda: messagebox.showerror(APP_TITLE, f"配对失败：{exc}"))

        threading.Thread(target=work, daemon=True).start()

    def _pair_succeeded(self, node_name: str) -> None:
        self.node_name.set(node_name)
        self.pair_code.set("")
        self._append_log("配对成功，节点凭据已安全保存到当前 Windows 用户目录。")
        messagebox.showinfo(APP_TITLE, "配对成功。确认微信电脑版已登录后即可启动连接器。")

    def refresh_wechat(self) -> None:
        matches = detect_wechat_processes()
        self.wechat_status.set("；".join(matches) if matches else "未检测到已运行的微信电脑版")

    def start_connector(self) -> None:
        if self.process and self.process.poll() is None:
            return
        if not CONFIG_PATH.exists():
            messagebox.showerror(APP_TITLE, "请先完成配对。")
            return
        if not detect_wechat_processes():
            messagebox.showerror(APP_TITLE, "未检测到微信电脑版，请先登录微信。")
            return
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            self.process = subprocess.Popen(executable_command(), creationflags=creationflags)
            self.connection_status.set("启动中")
            self.start_button.configure(state="disabled")
            self.stop_button.configure(state="normal")
            self._append_log("连接器进程已启动。")
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"启动失败：{exc}")

    def stop_connector(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None
        self.connection_status.set("已停止")
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self._append_log("连接器已停止。")

    def _refresh_runtime_state(self) -> None:
        if self.process:
            code = self.process.poll()
            if code is None:
                self.connection_status.set("运行中")
            else:
                self.connection_status.set(f"已退出（代码 {code}）")
                self.process = None
                self.start_button.configure(state="normal")
                self.stop_button.configure(state="disabled")
        self._refresh_log()
        self.after(1000, self._refresh_runtime_state)

    def _refresh_log(self) -> None:
        if not LOG_PATH.exists():
            return
        try:
            content = LOG_PATH.read_text("utf-8", errors="replace")[-16000:]
            self.log_text.configure(state="normal")
            self.log_text.delete("1.0", "end")
            self.log_text.insert("end", content)
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        except OSError:
            pass

    def _append_log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def close_app(self) -> None:
        self.stop_connector()
        self.destroy()


def main() -> None:
    ConnectorApp().mainloop()
