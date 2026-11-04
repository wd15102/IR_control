#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
电脑红外遥控器 - 控制机顶盒等红外设备
硬件: IR03T 红外学习模块 + USB转TTL (CH340)
"""

import json
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("错误: 请先安装 pyserial 库")
    print("  pip install pyserial")
    sys.exit(1)

# ==================== IR03T 协议 ====================
FRAME_HEAD = 0xFA
FRAME_SECOND = 0xFD
CMD_LEARN = 0x01
CMD_SEND = 0x02
FRAME_TAIL = 0xDF

RESP_LEARN_START = "A1"
RESP_LEARN_DONE = "A2"
RESP_SEND_DONE = "F1"

CONFIG_FILE = "config.json"
DEFAULT_BAUDRATE = 9600


def build_frame(cmd, data):
    return bytes([FRAME_HEAD, FRAME_SECOND, cmd, data, FRAME_TAIL])


def check_resp(data, expected):
    if not data:
        return False
    if expected.encode("ascii") in data:
        return True
    try:
        if bytes([int(expected, 16)]) in data:
            return True
    except ValueError:
        pass
    return False


def list_serial_ports():
    return [p.device for p in serial.tools.list_ports.comports()]


class IRRemoteApp:
    def __init__(self, root):
        self.root = root
        self.root.title("电脑红外遥控器 - IR03T")
        self.root.geometry("780x620")
        self.root.minsize(660, 500)

        self.serial = None
        self.config = self.load_config()
        self.active_remote = None

        self.build_ui()
        self.refresh_ports()
        self.refresh_remote_list()

    # -------------------- UI --------------------
    def build_ui(self):
        top = ttk.LabelFrame(self.root, text="串口设置")
        top.pack(fill="x", padx=10, pady=5)

        ttk.Label(top, text="串口:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(top, textvariable=self.port_var, width=12, state="readonly")
        self.port_combo.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(top, text="波特率:").grid(row=0, column=2, padx=5, pady=5)
        self.baud_var = tk.StringVar(value=str(DEFAULT_BAUDRATE))
        ttk.Combobox(top, textvariable=self.baud_var, width=10, state="readonly",
                     values=["9600", "19200", "38400", "57600", "115200"]).grid(row=0, column=3, padx=5, pady=5)

        ttk.Button(top, text="刷新串口", command=self.refresh_ports).grid(row=0, column=4, padx=5, pady=5)
        self.connect_btn = ttk.Button(top, text="连接", command=self.toggle_connect, width=10)
        self.connect_btn.grid(row=0, column=5, padx=5, pady=5)

        mid = ttk.Frame(self.root)
        mid.pack(fill="both", expand=True, padx=10, pady=5)

        sel = ttk.Frame(mid)
        sel.pack(fill="x", pady=2)
        ttk.Label(sel, text="遥控器:").pack(side="left", padx=5)
        self.remote_var = tk.StringVar()
        self.remote_combo = ttk.Combobox(sel, textvariable=self.remote_var, width=24, state="readonly")
        self.remote_combo.pack(side="left", padx=5)
        self.remote_combo.bind("<<ComboboxSelected>>", self.on_remote_change)
        ttk.Button(sel, text="新建", command=self.new_remote, width=8).pack(side="left", padx=2)
        ttk.Button(sel, text="保存", command=self.save_config, width=8).pack(side="left", padx=2)
        ttk.Button(sel, text="删除", command=self.delete_remote, width=8).pack(side="left", padx=2)

        panel = ttk.LabelFrame(mid, text="按键面板")
        panel.pack(fill="both", expand=True, pady=2)
        self.panel_canvas = tk.Canvas(panel, highlightthickness=0)
        self.panel_canvas.pack(fill="both", expand=True)
        self.panel_inner = ttk.Frame(self.panel_canvas)
        self.panel_canvas.create_window((0, 0), window=self.panel_inner, anchor="nw")
        self.panel_inner.bind("<Configure>", lambda e: self.panel_canvas.configure(scrollregion=self.panel_canvas.bbox("all")))

        bottom = ttk.Frame(self.root)
        bottom.pack(fill="x", padx=10, pady=5)

        btn_frame = ttk.Frame(bottom)
        btn_frame.pack(side="left")
        ttk.Button(btn_frame, text="学习按键", command=self.learn_single).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="连续学习", command=self.learn_loop).pack(side="left", padx=2)

        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(bottom, textvariable=self.status_var, relief="sunken", anchor="w").pack(
            side="right", fill="x", expand=True, padx=5)

    # -------------------- 串口 --------------------
    def refresh_ports(self):
        ports = list_serial_ports()
        self.port_combo["values"] = ports
        if ports:
            if self.port_var.get() not in ports:
                self.port_var.set(ports[0])
        else:
            self.port_var.set("")

    def toggle_connect(self):
        if self.serial and self.serial.is_open:
            self.disconnect()
        else:
            self.connect()

    def connect(self):
        port = self.port_var.get()
        if not port:
            messagebox.showwarning("提示", "请先选择串口")
            return
        try:
            self.serial = serial.Serial(port, int(self.baud_var.get()), timeout=0.2)
            time.sleep(0.1)
            self.status_var.set("已连接 " + port + " @ " + self.baud_var.get())
            self.connect_btn.config(text="断开")
        except Exception as e:
            messagebox.showerror("连接失败", "无法打开串口 " + port + "\n\n" + str(e))
            self.serial = None

    def disconnect(self):
        if self.serial:
            try:
                self.serial.close()
            except Exception:
                pass
            self.serial = None
        self.status_var.set("已断开")
        self.connect_btn.config(text="连接")

    def send_frame(self, frame, timeout=0.5):
        if not self.serial or not self.serial.is_open:
            return b""
        try:
            self.serial.reset_input_buffer()
            self.serial.write(frame)
            self.serial.flush()
            start = time.time()
            while time.time() - start < timeout:
                if self.serial.in_waiting:
                    return self.serial.read(self.serial.in_waiting)
                time.sleep(0.01)
        except Exception as e:
            self.status_var.set("发送失败: " + str(e))
        return b""

    # -------------------- 红外操作 --------------------
    def send_ir(self, channel):
        if not self._check_serial():
            return
        resp = self.send_frame(build_frame(CMD_SEND, channel))
        if check_resp(resp, RESP_SEND_DONE):
            self.status_var.set("已发射: 通道 " + format(channel, "02X"))
        elif resp:
            self.status_var.set("发射反馈: " + repr(resp))
        else:
            self.status_var.set("已发射: 通道 " + format(channel, "02X") + " (无反馈)")

    def learn_ir(self, channel):
        if not self._check_serial():
            return False, "未连接串口"
        resp = self.send_frame(build_frame(CMD_LEARN, channel), timeout=0.5)
        if not check_resp(resp, RESP_LEARN_START):
            return False, "未进入学习状态 (反馈: " + repr(resp) + ")"
        start = time.time()
        while time.time() - start < 15:
            if self.serial and self.serial.in_waiting:
                data = self.serial.read(self.serial.in_waiting)
                if check_resp(data, RESP_LEARN_DONE):
                    return True, "学习成功"
            time.sleep(0.03)
        return False, "学习超时 (15秒内未检测到遥控信号)"

    def _check_serial(self):
        if not self.serial or not self.serial.is_open:
            messagebox.showwarning("提示", "请先连接串口")
            return False
        return True

    # -------------------- 配置 --------------------
    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print("加载配置失败: " + str(e))
        return {"remotes": {}, "active": None}

    def save_config(self):
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            self.status_var.set("配置已保存")
            return True
        except Exception as e:
            messagebox.showerror("保存失败", str(e))
            return False

    def refresh_remote_list(self):
        remotes = list(self.config.get("remotes", {}).keys())
        self.remote_combo["values"] = remotes
        if remotes:
            active = self.config.get("active") or remotes[0]
            if active not in remotes:
                active = remotes[0]
            self.remote_var.set(active)
            self.active_remote = active
        else:
            self.remote_var.set("")
            self.active_remote = None
        self.render_buttons()

    def on_remote_change(self, event=None):
        self.active_remote = self.remote_var.get()
        self.config["active"] = self.active_remote
        self.render_buttons()

    def new_remote(self):
        name = simpledialog.askstring("新建遥控器", "请输入遥控器名称 (如: 芒果TV 机顶盒):")
        if not name:
            return
        if name in self.config.get("remotes", {}):
            messagebox.showwarning("提示", "该名称已存在")
            return
        self.config.setdefault("remotes", {})[name] = {"baudrate": DEFAULT_BAUDRATE, "buttons": {}}
        self.refresh_remote_list()
        self.remote_var.set(name)
        self.active_remote = name
        self.render_buttons()
        self.save_config()

    def delete_remote(self):
        name = self.active_remote
        if not name:
            return
        if messagebox.askyesno("确认删除", "确定删除遥控器 " + name + " ?\n此操作不可恢复。"):
            self.config["remotes"].pop(name, None)
            self.refresh_remote_list()
            self.save_config()

    def render_buttons(self):
        for w in self.panel_inner.winfo_children():
            w.destroy()
        if not self.active_remote:
            ttk.Label(self.panel_inner, text="请选择或新建一个遥控器").pack(pady=30)
            return
        remote = self.config["remotes"].get(self.active_remote, {})
        buttons = remote.get("buttons", {})
        if not buttons:
            ttk.Label(self.panel_inner, text="暂无按键\n点击 学习按键 添加").pack(pady=30)
            return
        cols = 4
        for i, (name, ch) in enumerate(sorted(buttons.items(), key=lambda x: x[1])):
            row, col = divmod(i, cols)
            btn = ttk.Button(self.panel_inner, text=name + "\n[" + format(ch, "02X") + "]", width=14,
                             command=lambda c=ch: self.send_ir(c))
            btn.grid(row=row, column=col, padx=4, pady=4, sticky="nsew")
        for c in range(cols):
            self.panel_inner.columnconfigure(c, weight=1)

    # -------------------- 学习模式 --------------------
    def _next_free_channel(self):
        used = set(self.config["remotes"][self.active_remote].get("buttons", {}).values())
        for i in range(256):
            if i not in used:
                return i
        return None

    def learn_single(self):
        if not self._check_serial():
            return
        if not self.active_remote:
            messagebox.showwarning("提示", "请先选择或新建遥控器")
            return
        free = self._next_free_channel()
        if free is None:
            messagebox.showwarning("提示", "通道已用完 (0~255)")
            return
        name = simpledialog.askstring("学习按键", "请输入按键名称 (如: POWER, 音量+):")
        if not name:
            return
        if name in self.config["remotes"][self.active_remote]["buttons"]:
            messagebox.showwarning("提示", "按键 " + name + " 已存在")
            return
        ch_str = simpledialog.askstring("通道号", "请输入通道号 (0~255)\n推荐自动分配: " + format(free, "02X"),
                                        initialvalue=format(free, "02X"))
        if not ch_str:
            return
        try:
            channel = int(ch_str.strip(), 16)
            if not (0 <= channel <= 255):
                raise ValueError
        except ValueError:
            messagebox.showerror("错误", "通道号无效, 请输入 0~FF 的十六进制数")
            return
        threading.Thread(target=self._learn_worker, args=(name, channel), daemon=True).start()

    def _learn_worker(self, name, channel):
        self.root.after(0, lambda: self.status_var.set(
            "正在学习 " + name + " -> 通道 " + format(channel, "02X") + ", 请对准原遥控器按键..."))
        ok, msg = self.learn_ir(channel)
        self.root.after(0, lambda: self._learn_done(name, channel, ok, msg))

    def _learn_done(self, name, channel, ok, msg):
        if ok:
            self.config["remotes"][self.active_remote]["buttons"][name] = channel
            self.save_config()
            self.render_buttons()
            self.status_var.set("学习成功: " + name + " -> 通道 " + format(channel, "02X"))
        else:
            self.status_var.set("学习失败: " + msg)
            messagebox.showerror("学习失败", msg)

    def learn_loop(self):
        if not self._check_serial():
            return
        if not self.active_remote:
            messagebox.showwarning("提示", "请先选择或新建遥控器")
            return
        win = tk.Toplevel(self.root)
        win.title("连续学习模式")
        win.geometry("420x320")
        win.transient(self.root)

        ttk.Label(win, text="输入按键名称, 点击 学习 按钮", anchor="w").pack(fill="x", padx=10, pady=5)
        entry = ttk.Entry(win)
        entry.pack(fill="x", padx=10, pady=5)
        entry.focus()

        log = tk.Text(win, height=10, state="disabled")
        log.pack(fill="both", expand=True, padx=10, pady=5)

        def log_msg(msg):
            log.config(state="normal")
            log.insert("end", msg + "\n")
            log.see("end")
            log.config(state="disabled")

        def do_learn():
            name = entry.get().strip()
            if not name:
                return
            if name in self.config["remotes"][self.active_remote]["buttons"]:
                log_msg("警告: 按键 " + name + " 已存在, 跳过")
                return
            free = self._next_free_channel()
            if free is None:
                log_msg("警告: 通道已用完")
                return
            log_msg("正在学习 " + name + " -> 通道 " + format(free, "02X") + ", 请按原遥控器...")
            threading.Thread(target=self._loop_worker, args=(name, free, log_msg), daemon=True).start()

        def do_finish():
            self.save_config()
            win.destroy()

        btn_frame = ttk.Frame(win)
        btn_frame.pack(fill="x", padx=10, pady=5)
        ttk.Button(btn_frame, text="学习", command=do_learn).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="完成", command=do_finish).pack(side="right", padx=2)
        entry.bind("<Return>", lambda e: do_learn())

    def _loop_worker(self, name, channel, log_msg):
        ok, msg = self.learn_ir(channel)
        self.root.after(0, lambda: self._loop_done(name, channel, ok, msg, log_msg))

    def _loop_done(self, name, channel, ok, msg, log_msg):
        if ok:
            self.config["remotes"][self.active_remote]["buttons"][name] = channel
            log_msg("成功: " + name + " -> 通道 " + format(channel, "02X"))
            self.render_buttons()
        else:
            log_msg("失败: " + name + " - " + msg)


def main():
    root = tk.Tk()
    try:
        style = ttk.Style()
        available = style.theme_names()
        for t in ("vista", "clam", "alt", "default"):
            if t in available:
                style.theme_use(t)
                break
    except Exception:
        pass
    app = IRRemoteApp(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (app.disconnect(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
