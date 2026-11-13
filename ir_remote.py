#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
电脑红外遥控器 - 控制机顶盒等红外设备
硬件: IR03T 红外学习模块 + USB转TTL (CH340)
界面: 深色霓虹科技风 (tkinter)
"""

import json
import math
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("错误: 请先安装 pyserial 库")
    print("  pip install pyserial")
    sys.exit(1)

# ==================== 协议常量 ====================
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
APP_VERSION = "2.0"
AUTHOR = "吴东"

# ==================== 遥控器空间布局 ====================
# 中国移动 CM311-5-CH 真实按键位置（5 列网格）
REMOTE_COLS = 5
REMOTE_LAYOUT_ROWS = 9

REMOTE_LAYOUT = [
    # (布局键, 别名, row, col)
    ("电源", ["电源", "power"], 0, 0),
    ("TV", ["tv"], 0, 4),
    ("静音", ["静音", "mute"], 1, 0),
    ("菜单", ["菜单", "menu", "三横线"], 1, 2),
    ("设置", ["设置", "setting", "settings", "齿轮"], 1, 4),
    ("上", ["上", "up"], 2, 2),
    ("左", ["左", "left"], 3, 0),
    ("OK", ["ok", "确定", "确认"], 3, 2),
    ("右", ["右", "right"], 3, 4),
    ("下", ["下", "down"], 4, 2),
    ("主页", ["主页", "home", "首页"], 5, 0),
    ("M", ["m"], 5, 2),
    ("返回", ["返回", "back", "退回"], 5, 4),
    ("音量+", ["音量+", "音量＋", "vol+", "音量加"], 6, 0),
    ("频道+", ["频道+", "频道＋", "ch+", "频道加", "台+"], 6, 4),
    ("麦克风", ["麦克风", "mic", "语音"], 7, 2),
    ("音量-", ["音量-", "音量－", "vol-", "音量减"], 8, 0),
    ("频道-", ["频道-", "频道－", "ch-", "频道减", "台-"], 8, 4),
]

REMOTE_POS = {key: (row, col) for key, _a, row, col in REMOTE_LAYOUT}
REMOTE_ALIASES = {}
for _key, _aliases, _r, _c in REMOTE_LAYOUT:
    for _a in _aliases:
        REMOTE_ALIASES[_a] = _key


def match_layout_key(name):
    """按按键名称匹配遥控器布局位置，返回布局键或 None"""
    n = name.strip().lower()
    if n in REMOTE_ALIASES:
        return REMOTE_ALIASES[n]
    for alias, key in REMOTE_ALIASES.items():
        if len(alias) >= 2 and (alias in n or n in alias):
            return key
    return None


def layout_positions(buttons):
    """按真实遥控器位置计算每个按键的 (row, col)"""
    used_pos = set()
    placed = {}
    deferred = []
    for name in buttons:
        key = match_layout_key(name)
        pos = REMOTE_POS[key] if key is not None else None
        if pos is not None and pos not in used_pos:
            placed[name] = pos
            used_pos.add(pos)
        else:
            deferred.append(name)
    extra_row, extra_col = REMOTE_LAYOUT_ROWS, 0
    for name in deferred:
        placed[name] = (extra_row, extra_col)
        extra_col += 1
        if extra_col >= REMOTE_COLS:
            extra_col = 0
            extra_row += 1
    return placed

# ==================== 主题 ====================
class Theme:
    BG = "#070B14"
    BG_PANEL = "#0C1220"
    BG_CARD = "#111A2E"
    BG_INPUT = "#080D18"
    BORDER = "#1C2942"
    BORDER_HI = "#2B3D5F"

    CYAN = "#00E5FF"
    CYAN_DARK = "#0E7490"
    PURPLE = "#8B5CF6"
    GREEN = "#22E58A"
    AMBER = "#FFB020"
    RED = "#FF4D6D"

    TEXT = "#E8F0FB"
    TEXT_DIM = "#8296B8"
    TEXT_FAINT = "#4A5B78"

    FONT_CN = "Microsoft YaHei UI"
    FONT_MONO = "Consolas"
    FONT_TECH = "Bahnschrift"


def blend(c1, c2, a):
    """把 c1 以权重 a 混合到 c2 上 (a=1 时完全为 c1)"""
    r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
    r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
    return "#%02X%02X%02X" % (round(r1 * a + r2 * (1 - a)),
                             round(g1 * a + g2 * (1 - a)),
                             round(b1 * a + b2 * (1 - a)))


def chamfer_pts(x1, y1, x2, y2, c):
    """切角八边形点集 (科技感斜切角)"""
    return [x1 + c, y1, x2 - c, y1, x2, y1 + c, x2, y2 - c,
            x2 - c, y2, x1 + c, y2, x1, y2 - c, x1, y1 + c]


def center_window(win, master):
    win.update_idletasks()
    w, h = win.winfo_width(), win.winfo_height()
    x = master.winfo_rootx() + max(0, (master.winfo_width() - w) // 2)
    y = master.winfo_rooty() + max(0, (master.winfo_height() - h) // 2)
    win.geometry("+%d+%d" % (x, y))


# ==================== 自定义组件 ====================
class NeonButton(tk.Canvas):
    """切角霓虹按钮"""

    def __init__(self, master, text, command=None, color=Theme.CYAN,
                 width=132, height=40, subtext=None, font_size=11, expand=False,
                 icon=False, icon_command=None):
        super().__init__(master, width=(1 if expand else width), height=height,
                         bg=Theme.BG_PANEL, highlightthickness=0, cursor="hand2")
        self._bw, self._bh = (1 if expand else width), height
        self.text = text
        self.subtext = subtext
        self.command = command
        self.color = color
        self.state = "normal"
        self.icon = icon
        self.icon_command = icon_command
        self._icon_box = None
        self.font = (Theme.FONT_CN, font_size, "bold")
        self.subfont = (Theme.FONT_MONO, max(7, font_size - 3))
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        if expand:
            self.bind("<Configure>", self._on_resize)
        self.draw()

    def _on_resize(self, event):
        if event.width > 1 and event.height > 1:
            if event.width != self._bw or event.height != self._bh:
                self._bw, self._bh = event.width, event.height
                self.draw()

    def set_text(self, text):
        self.text = text
        self.draw()

    def set_color(self, color):
        self.color = color
        self.draw()

    def _on_enter(self, event):
        self.state = "hover"
        self.draw()

    def _on_leave(self, event):
        self.state = "normal"
        self.draw()

    def _on_press(self, event):
        self.state = "active"
        self.draw()

    def _on_release(self, event):
        self.state = "hover"
        self.draw()
        if self.icon_command and self._icon_box:
            x1, y1, x2, y2 = self._icon_box
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                self.icon_command(event)
                return
        if self.command:
            self.command()

    def draw(self):
        self.delete("all")
        w, h = self._bw, self._bh
        if w < 12 or h < 12:
            return
        if self.state == "hover":
            glow_a, fill_a, border_a = 0.30, 0.18, 1.0
            text_color = "#FFFFFF"
        elif self.state == "active":
            glow_a, fill_a, border_a = 0.50, 0.32, 1.0
            text_color = "#FFFFFF"
        else:
            glow_a, fill_a, border_a = 0.10, 0.08, 0.80
            text_color = self.color
        cut = min(8, h // 3)
        # 外层光晕
        self.create_polygon(chamfer_pts(1, 1, w - 2, h - 2, cut), fill="",
                            outline=blend(self.color, Theme.BG_PANEL, glow_a), width=5)
        # 中层边框
        self.create_polygon(chamfer_pts(2, 2, w - 3, h - 3, cut), fill="",
                            outline=blend(self.color, "#FFFFFF", border_a * 0.85), width=1)
        # 内层填充
        self.create_polygon(chamfer_pts(3, 3, w - 4, h - 4, cut),
                            fill=blend(self.color, Theme.BG_CARD, fill_a), outline="")
        # 文字
        cx, cy = w / 2, h / 2
        if self.subtext:
            if h >= 50:
                self.create_text(cx, cy - 6, text=self.text, fill=text_color, font=self.font)
                self.create_text(cx, cy + 12, text=self.subtext, fill=Theme.TEXT_DIM,
                                 font=self.subfont)
            else:
                self.create_text(cx, cy - 5, text=self.text, fill=text_color, font=self.font)
                self.create_text(cx, cy + 10, text=self.subtext, fill=Theme.TEXT_DIM,
                                 font=self.subfont)
        else:
            self.create_text(cx, cy + 0.5, text=self.text, fill=text_color, font=self.font)
        if self.icon:
            self._draw_icon(text_color)

    def _draw_icon(self, color):
        """右上角铅笔图标"""
        w, h = self._bw, self._bh
        size = max(6, min(10, h * 0.26))
        cx, cy = w - size - 6, size + 5
        dx, dy = -0.7071, 0.7071
        px, py = 0.7071, 0.7071
        L, W = size, size * 0.40
        bx, by = cx - dx * L / 2, cy - dy * L / 2
        tx, ty = cx + dx * L / 2, cy + dy * L / 2
        self.create_polygon(
            bx + px * W / 2, by + py * W / 2,
            bx - px * W / 2, by - py * W / 2,
            tx - px * W / 2, ty - py * W / 2,
            tx + px * W / 2, ty + py * W / 2,
            fill=color, outline="")
        self.create_polygon(
            tx - px * W / 2, ty - py * W / 2,
            tx + px * W / 2, ty + py * W / 2,
            cx + dx * L * 0.80, cy + dy * L * 0.80,
            fill=color, outline="")
        self._icon_box = (cx - size * 1.15, cy - size * 1.15,
                          cx + size * 1.15, cy + size * 1.15)


class LedIndicator(tk.Canvas):
    """状态指示灯 (带脉冲动画)"""

    def __init__(self, master, size=12, color=Theme.GREEN):
        super().__init__(master, width=size, height=size, bg=Theme.BG_PANEL,
                         highlightthickness=0)
        self.size = size
        self.color = color
        self.state = "off"
        self._pulse = False
        self._phase = 0
        self.draw()

    def set_state(self, state, color=None):
        self.state = state
        if color:
            self.color = color
        self.draw()

    def start_pulse(self):
        if not self._pulse:
            self._pulse = True
            self._phase = 0
            self._animate()

    def stop_pulse(self):
        self._pulse = False
        self.draw()

    def _animate(self):
        if not self._pulse:
            return
        self._phase = (self._phase + 1) % 24
        pulse = 0.5 + 0.5 * math.sin(self._phase / 24 * 2 * math.pi)
        self.draw(pulse=pulse)
        self.after(50, self._animate)

    def draw(self, pulse=1.0):
        self.delete("all")
        s = self.size
        if s < 4:
            return
        c = s / 2
        if self.state == "off":
            self.create_oval(1, 1, s - 2, s - 2,
                             fill=blend(Theme.TEXT_FAINT, Theme.BG_PANEL, 0.35),
                             outline=Theme.BORDER, width=1)
            return
        glow_r = (s / 2) * (0.9 + 0.35 * pulse)
        self.create_oval(c - glow_r, c - glow_r, c + glow_r, c + glow_r,
                         fill=blend(self.color, Theme.BG_PANEL, 0.20 * pulse), outline="")
        self.create_oval(1.5, 1.5, s - 2.5, s - 2.5, fill=self.color,
                         outline=blend(self.color, "#FFFFFF", 0.6), width=1)
        self.create_oval(c - s * 0.18, c - s * 0.22, c + s * 0.05, c + s * 0.02,
                         fill=blend("#FFFFFF", self.color, 0.55), outline="")


class Panel(tk.Frame):
    """带标题的面板容器"""

    def __init__(self, master, title="", accent=Theme.CYAN):
        super().__init__(master, bg=Theme.BG_PANEL, highlightthickness=1,
                         highlightbackground=Theme.BORDER)
        if title:
            bar = tk.Frame(self, bg=Theme.BG_PANEL)
            bar.pack(fill="x", padx=12, pady=(9, 2))
            cv = tk.Canvas(bar, width=14, height=14, bg=Theme.BG_PANEL,
                           highlightthickness=0)
            cv.pack(side="left", padx=(0, 8))
            cv.create_polygon([7, 0, 14, 7, 7, 14, 0, 7], fill=accent, outline="")
            cv.create_polygon([7, 4, 10, 7, 7, 10, 4, 7],
                              fill=Theme.BG_PANEL, outline="")
            tk.Label(bar, text=title, bg=Theme.BG_PANEL, fg=Theme.TEXT,
                     font=(Theme.FONT_CN, 10, "bold")).pack(side="left")
            line = tk.Canvas(bar, height=1, bg=Theme.BG_PANEL,
                             highlightthickness=0)
            line.pack(side="left", fill="x", expand=True, padx=(10, 0))

            def draw_line(e, cv=line, ac=accent):
                cv.delete("all")
                cv.create_line(0, 0, e.width, 0,
                               fill=blend(ac, Theme.BG_PANEL, 0.30), width=1)
            line.bind("<Configure>", draw_line)


class TerminalLog(tk.Frame):
    """终端风格日志"""

    LEVELS = {
        "sys": (Theme.CYAN, "SYS"),
        "info": (Theme.TEXT_DIM, "INF"),
        "ok": (Theme.GREEN, "OK "),
        "warn": (Theme.AMBER, "WRN"),
        "err": (Theme.RED, "ERR"),
        "cmd": (Theme.PURPLE, "CMD"),
    }

    def __init__(self, master, height=10):
        super().__init__(master, bg=Theme.BG_INPUT)
        self.text = tk.Text(self, height=height, bg=Theme.BG_INPUT, fg=Theme.TEXT_DIM,
                            font=(Theme.FONT_MONO, 9), relief="flat",
                            highlightthickness=1, highlightbackground=Theme.BORDER,
                            highlightcolor=blend(Theme.CYAN, Theme.BG_INPUT, 0.4),
                            insertbackground=Theme.CYAN, state="disabled",
                            wrap="word", padx=8, pady=6)
        sb = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        sb.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        self.text.configure(yscrollcommand=sb.set)
        self.text.tag_config("ts", foreground=Theme.TEXT_FAINT)
        self.text.tag_config("tag", foreground=Theme.TEXT_FAINT)
        for k, (color, _) in self.LEVELS.items():
            self.text.tag_config(k, foreground=color)

    def log(self, msg, level="info"):
        color, tag = self.LEVELS.get(level, self.LEVELS["info"])
        ts = time.strftime("%H:%M:%S")
        self.text.config(state="normal")
        self.text.insert("end", ts + " ", "ts")
        self.text.insert("end", "[" + tag + "] ", "tag")
        self.text.insert("end", msg + "\n", level)
        self.text.see("end")
        self.text.config(state="disabled")


class NeonDialog(tk.Toplevel):
    """霓虹风格输入对话框"""

    def __init__(self, master, title, prompt, default=""):
        super().__init__(master)
        self.title(title)
        self.configure(bg=Theme.BG_PANEL, highlightthickness=1,
                       highlightbackground=Theme.BORDER)
        self.transient(master)
        self.grab_set()
        self.result = None
        tk.Label(self, text=prompt, bg=Theme.BG_PANEL, fg=Theme.TEXT,
                 font=(Theme.FONT_CN, 10), wraplength=320,
                 justify="left").pack(anchor="w", padx=16, pady=(14, 6))
        self.entry = tk.Entry(self, bg=Theme.BG_INPUT, fg=Theme.TEXT,
                              font=(Theme.FONT_CN, 11), relief="flat",
                              insertbackground=Theme.CYAN, highlightthickness=1,
                              highlightbackground=Theme.BORDER)
        self.entry.pack(fill="x", padx=16, ipady=5)
        if default:
            self.entry.insert(0, default)
        self.entry.focus_set()
        row = tk.Frame(self, bg=Theme.BG_PANEL)
        row.pack(fill="x", padx=16, pady=12)
        NeonButton(row, "确 定", self._ok, Theme.CYAN, width=90,
                   height=32).pack(side="right")
        NeonButton(row, "取 消", self._cancel, Theme.PURPLE, width=90,
                   height=32).pack(side="right", padx=(0, 8))
        self.entry.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self._cancel())
        center_window(self, master)
        self.wait_window(self)

    def _ok(self):
        self.result = self.entry.get().strip()
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


class NeonConfirm(tk.Toplevel):
    """霓虹风格确认对话框"""

    def __init__(self, master, title, message):
        super().__init__(master)
        self.title(title)
        self.configure(bg=Theme.BG_PANEL, highlightthickness=1,
                       highlightbackground=Theme.BORDER)
        self.transient(master)
        self.grab_set()
        self.result = False
        tk.Label(self, text=message, bg=Theme.BG_PANEL, fg=Theme.TEXT,
                 font=(Theme.FONT_CN, 10), wraplength=320,
                 justify="left").pack(anchor="w", padx=16, pady=(16, 8))
        row = tk.Frame(self, bg=Theme.BG_PANEL)
        row.pack(fill="x", padx=16, pady=(0, 14))
        NeonButton(row, "确 定", self._ok, Theme.RED, width=90,
                   height=32).pack(side="right")
        NeonButton(row, "取 消", self._cancel, Theme.PURPLE, width=90,
                   height=32).pack(side="right", padx=(0, 8))
        self.bind("<Escape>", lambda e: self._cancel())
        center_window(self, master)
        self.wait_window(self)

    def _ok(self):
        self.result = True
        self.destroy()

    def _cancel(self):
        self.result = False
        self.destroy()


# ==================== 遥控器窗口 ====================
class RemoteWindow(tk.Toplevel):
    """独立遥控器窗口（窄长，按真实遥控器位置布局）"""

    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.title("遥控器")
        self.configure(bg=Theme.BG, highlightthickness=1,
                       highlightbackground=Theme.BORDER_HI)
        self.geometry("400x640")
        self.resizable(False, False)
        self._build()

    def _build(self):
        bar = tk.Frame(self, bg=Theme.BG)
        bar.pack(fill="x", padx=12, pady=(10, 2))
        self.title_var = tk.StringVar(value="遥控器")
        tk.Label(bar, textvariable=self.title_var, bg=Theme.BG, fg=Theme.TEXT,
                 font=(Theme.FONT_CN, 13, "bold")).pack(side="left")
        NeonButton(bar, "关闭", self.destroy, Theme.RED, width=62, height=28,
                   font_size=9).pack(side="right")

        body = tk.Frame(self, bg=Theme.BG_PANEL, highlightthickness=1,
                        highlightbackground=Theme.BORDER_HI)
        body.pack(fill="both", expand=True, padx=12, pady=(8, 12))
        self.grid = tk.Frame(body, bg=Theme.BG_PANEL)
        self.grid.pack(fill="both", expand=True, padx=10, pady=10)
        for c in range(REMOTE_COLS):
            self.grid.columnconfigure(c, weight=1)

    def refresh(self):
        for w in self.grid.winfo_children():
            w.destroy()
        app = self.app
        name = app.active_remote
        self.title_var.set("遥控器 · " + (name or "未选择"))
        if not name:
            tk.Label(self.grid, text="请先在主界面选择遥控器", bg=Theme.BG_PANEL,
                     fg=Theme.TEXT_FAINT, font=(Theme.FONT_CN, 11)).grid(
                         row=0, column=0, columnspan=REMOTE_COLS, pady=40)
            return
        buttons = app.config.get("remotes", {}).get(name, {}).get("buttons", {})
        if not buttons:
            tk.Label(self.grid, text="暂无按键\n点击「学习按键」添加", bg=Theme.BG_PANEL,
                     fg=Theme.TEXT_FAINT, font=(Theme.FONT_CN, 11)).grid(
                         row=0, column=0, columnspan=REMOTE_COLS, pady=40)
            return
        placed = layout_positions(buttons)
        for nm, ch in sorted(buttons.items(), key=lambda x: x[1]):
            r, c = placed[nm]
            btn = NeonButton(self.grid, nm, lambda c=ch, n=nm: app.send_ir(c, n),
                             Theme.CYAN, width=64, height=44,
                             subtext="CH " + format(ch, "02X"),
                             font_size=9, expand=True)
            btn.grid(row=r, column=c, padx=3, pady=3, sticky="nsew")


# ==================== 主应用 ====================
class IRRemoteApp:
    def __init__(self, root):
        self.root = root
        self.root.title("电脑红外遥控器 - IR03T")
        self.root.configure(bg=Theme.BG)
        self.root.geometry("1000x880")
        self.root.minsize(880, 750)
        self.root.grid_rowconfigure(2, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        self.serial = None
        self.config = self.load_config()
        self.active_remote = None
        self._learn_busy = False
        self._loop_count = 0
        self.remote_win = None

        self._build_header()
        self._build_body()
        self._build_footer()

        self.refresh_ports()
        self.refresh_remote_list()
        self.log("IR03T 红外控制终端 v2.0 已就绪", "sys")
        self.log("协议: FA FD <CMD> <DATA> DF  |  学习 0x01 / 发射 0x02", "info")

    # -------------------- UI 构建 --------------------
    def _build_header(self):
        bar = tk.Frame(self.root, bg=Theme.BG)
        bar.grid(row=0, column=0, sticky="ew")
        left = tk.Frame(bar, bg=Theme.BG)
        left.pack(side="left", padx=16, pady=10)
        cv = tk.Canvas(left, width=44, height=44, bg=Theme.BG, highlightthickness=0)
        cv.pack(side="left")
        cx, cy, r = 22, 22, 19
        pts = []
        for i in range(6):
            ang = math.pi / 6 + i * math.pi / 3
            pts += [cx + r * math.cos(ang), cy + r * math.sin(ang)]
        cv.create_polygon(pts, fill=blend(Theme.CYAN, Theme.BG, 0.15),
                          outline=Theme.CYAN, width=2)
        cv.create_line(cx - 9, cy + 5, cx - 9, cy - 5, cx - 3, cy - 5,
                       cx + 3, cy + 5, cx + 9, cy + 5,
                       fill=Theme.CYAN, width=2)
        txt = tk.Frame(left, bg=Theme.BG)
        txt.pack(side="left", padx=10)
        tk.Label(txt, text="电脑红外遥控器", bg=Theme.BG, fg=Theme.TEXT,
                 font=(Theme.FONT_CN, 17, "bold")).pack(anchor="w")
        tk.Label(txt, text="IR03T · USB INFRARED CONTROL SYSTEM",
                 bg=Theme.BG, fg=Theme.TEXT_DIM,
                 font=(Theme.FONT_TECH, 9)).pack(anchor="w")
        tk.Label(txt, text="By " + AUTHOR + "  ·  v" + APP_VERSION,
                 bg=Theme.BG, fg=Theme.CYAN,
                 font=(Theme.FONT_CN, 9)).pack(anchor="w")
        right = tk.Frame(bar, bg=Theme.BG)
        right.pack(side="right", padx=16)
        self.hdr_led = LedIndicator(right, size=14)
        self.hdr_led.pack(side="left", padx=(0, 8), pady=16)
        self.hdr_status = tk.StringVar(value="离线")
        tk.Label(right, textvariable=self.hdr_status, bg=Theme.BG,
                 fg=Theme.RED, font=(Theme.FONT_CN, 11, "bold")).pack(
                     side="left", pady=16)
        line = tk.Canvas(self.root, height=2, bg=Theme.BG, highlightthickness=0)
        line.grid(row=1, column=0, sticky="ew")
        line.bind("<Configure>", lambda e: (
            line.delete("all"),
            line.create_line(0, 1, e.width, 1,
                             fill=blend(Theme.CYAN, Theme.BG, 0.35), width=1)))

    def _build_body(self):
        body = tk.Frame(self.root, bg=Theme.BG)
        body.grid(row=2, column=0, sticky="nsew", padx=12, pady=(8, 0))
        left = tk.Frame(body, bg=Theme.BG, width=320)
        left.pack_propagate(False)
        left.pack(side="left", fill="y")
        self._build_device_panel(left)
        self._build_info_panel(left)
        right = tk.Frame(body, bg=Theme.BG)
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))
        self._build_remote_panel(right)

    def _build_device_panel(self, parent):
        p = Panel(parent, "设备控制 · DEVICE", Theme.CYAN)
        p.pack(fill="x")

        row = tk.Frame(p, bg=Theme.BG_PANEL)
        row.pack(fill="x", padx=12, pady=6)
        tk.Label(row, text="串口", bg=Theme.BG_PANEL, fg=Theme.TEXT_DIM,
                 font=(Theme.FONT_CN, 10), width=5, anchor="w").pack(side="left")
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(row, textvariable=self.port_var,
                                       state="readonly", font=(Theme.FONT_MONO, 10),
                                       width=14)
        self.port_combo.pack(side="left", fill="x", expand=True)

        row2 = tk.Frame(p, bg=Theme.BG_PANEL)
        row2.pack(fill="x", padx=12, pady=4)
        tk.Label(row2, text="波特率", bg=Theme.BG_PANEL, fg=Theme.TEXT_DIM,
                 font=(Theme.FONT_CN, 10), width=5, anchor="w").pack(side="left")
        self.baud_var = tk.StringVar(value=str(DEFAULT_BAUDRATE))
        self.baud_combo = ttk.Combobox(row2, textvariable=self.baud_var,
                                       state="readonly", font=(Theme.FONT_MONO, 10),
                                       width=14,
                                       values=["9600", "19200", "38400", "57600", "115200"])
        self.baud_combo.pack(side="left", fill="x", expand=True)

        btn_row = tk.Frame(p, bg=Theme.BG_PANEL)
        btn_row.pack(fill="x", padx=12, pady=8)
        self.refresh_btn = NeonButton(btn_row, "刷 新", self.refresh_ports,
                                      Theme.PURPLE, width=88, height=34)
        self.refresh_btn.pack(side="left", padx=(0, 6))
        self.connect_btn = NeonButton(btn_row, "连 接", self.toggle_connect,
                                      Theme.CYAN, width=150, height=34)
        self.connect_btn.pack(side="left", fill="x", expand=True)

        st = tk.Frame(p, bg=Theme.BG_PANEL)
        st.pack(fill="x", padx=12, pady=(0, 10))
        self.dev_led = LedIndicator(st, size=12)
        self.dev_led.pack(side="left")
        self.dev_status = tk.StringVar(value="未连接")
        tk.Label(st, textvariable=self.dev_status, bg=Theme.BG_PANEL,
                 fg=Theme.TEXT_DIM, font=(Theme.FONT_CN, 10)).pack(
                     side="left", padx=8)

    def _build_info_panel(self, parent):
        p = Panel(parent, "状态信息 · STATUS", Theme.PURPLE)
        p.pack(fill="x", pady=(10, 0))
        self.info_labels = {}
        items = [("遥控器", "0"), ("按键总数", "0"), ("通道占用", "0/256"),
                 ("协议版本", "v1.0")]
        inner = tk.Frame(p, bg=Theme.BG_PANEL)
        inner.pack(fill="x")
        inner.columnconfigure(0, weight=1)
        inner.columnconfigure(1, weight=1)
        for i, (k, v) in enumerate(items):
            r, c = divmod(i, 2)
            cell = tk.Frame(inner, bg=Theme.BG_PANEL)
            cell.grid(row=r, column=c, sticky="w", padx=(12, 4), pady=4)
            tk.Label(cell, text=k, bg=Theme.BG_PANEL, fg=Theme.TEXT_DIM,
                     font=(Theme.FONT_CN, 9), width=6, anchor="w").pack(side="left")
            lbl = tk.Label(cell, text=v, bg=Theme.BG_PANEL, fg=Theme.TEXT,
                           font=(Theme.FONT_MONO, 9), anchor="w")
            lbl.pack(side="left", padx=(4, 0))
            self.info_labels[k] = lbl
        self.update_info()

    def _build_remote_panel(self, parent):
        p = Panel(parent, "遥控器 · REMOTE", Theme.CYAN)
        p.pack(fill="both", expand=True)

        row = tk.Frame(p, bg=Theme.BG_PANEL)
        row.pack(fill="x", padx=12, pady=(4, 8))
        tk.Label(row, text="配置", bg=Theme.BG_PANEL, fg=Theme.TEXT_DIM,
                 font=(Theme.FONT_CN, 10), width=4, anchor="w").pack(side="left")
        self.remote_var = tk.StringVar()
        self.remote_combo = ttk.Combobox(row, textvariable=self.remote_var,
                                         state="readonly",
                                         font=(Theme.FONT_CN, 10))
        self.remote_combo.pack(side="left", fill="x", expand=True, padx=(8, 8))
        self.remote_combo.bind("<<ComboboxSelected>>", self.on_remote_change)
        mini = tk.Frame(row, bg=Theme.BG_PANEL)
        mini.pack(side="left")
        NeonButton(mini, "新建", self.new_remote, Theme.GREEN, width=52,
                   height=30, font_size=9).pack(side="left", padx=(0, 4))
        NeonButton(mini, "保存", self.save_config, Theme.CYAN, width=52,
                   height=30, font_size=9).pack(side="left", padx=(0, 4))
        NeonButton(mini, "删除", self.delete_remote, Theme.RED, width=52,
                   height=30, font_size=9).pack(side="left")
        NeonButton(row, "加载遥控器", self.load_remote_window, Theme.PURPLE,
                   width=104, height=30, font_size=9).pack(side="left", padx=(8, 0))

        grid_wrap = tk.Frame(p, bg=Theme.BG_PANEL)
        grid_wrap.pack(fill="both", expand=True, padx=12, pady=4)
        self.panel_canvas = tk.Canvas(grid_wrap, bg=Theme.BG_INPUT,
                                      highlightthickness=1,
                                      highlightbackground=Theme.BORDER,
                                      height=1)
        sb = ttk.Scrollbar(grid_wrap, orient="vertical",
                           command=self.panel_canvas.yview)
        sb.pack(side="right", fill="y")
        self.panel_canvas.pack(side="left", fill="both", expand=True)
        self.panel_canvas.configure(yscrollcommand=sb.set)
        self.panel_inner = tk.Frame(self.panel_canvas, bg=Theme.BG_INPUT)
        self._grid_win = self.panel_canvas.create_window((0, 0),
                                                         window=self.panel_inner,
                                                         anchor="nw")
        self.panel_canvas.bind("<Configure>", lambda e: self.panel_canvas.itemconfig(
            self._grid_win, width=e.width))
        self.panel_inner.bind("<Configure>", lambda e: self.panel_canvas.configure(
            scrollregion=self.panel_canvas.bbox("all")))
        self.panel_canvas.bind("<Enter>", lambda e: self.panel_canvas.bind_all(
            "<MouseWheel>", self._on_wheel))
        self.panel_canvas.bind("<Leave>", lambda e: self.panel_canvas.unbind_all(
            "<MouseWheel"))

        learn_row = tk.Frame(p, bg=Theme.BG_PANEL)
        learn_row.pack(fill="x", padx=12, pady=(4, 10))
        self.btn_learn = NeonButton(learn_row, "学习按键", self.learn_single,
                                    Theme.AMBER, width=150, height=36)
        self.btn_learn.pack(side="left", padx=(0, 8))
        self.btn_loop = NeonButton(learn_row, "连续学习", self.learn_loop,
                                   Theme.PURPLE, width=150, height=36)
        self.btn_loop.pack(side="left")
        tk.Label(learn_row, text="点右上角图标：删除 / 重新学习", bg=Theme.BG_PANEL,
                 fg=Theme.TEXT_FAINT, font=(Theme.FONT_CN, 9)).pack(side="right")

    def _build_footer(self):
        p = Panel(self.root, "系统日志 · TERMINAL", Theme.GREEN)
        p.grid(row=3, column=0, sticky="ew", padx=12, pady=(8, 4))
        self.log_view = TerminalLog(p, height=9)
        self.log_view.pack(fill="x", padx=12, pady=(0, 10))
        bar = tk.Frame(self.root, bg=Theme.BG_PANEL)
        bar.grid(row=4, column=0, sticky="ew")
        self.status_var = tk.StringVar(value="就绪")
        tk.Label(bar, textvariable=self.status_var, bg=Theme.BG_PANEL,
                 fg=Theme.TEXT_DIM, font=(Theme.FONT_CN, 9), anchor="w").pack(
                     side="left", padx=12, pady=5)
        tk.Label(bar, text="By " + AUTHOR + "  ·  v" + APP_VERSION,
                 bg=Theme.BG_PANEL, fg=Theme.TEXT_FAINT,
                 font=(Theme.FONT_CN, 9)).pack(side="right", padx=12, pady=5)

    def _on_wheel(self, event):
        self.panel_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # -------------------- 日志 / 状态 --------------------
    def log(self, msg, level="info"):
        if hasattr(self, "log_view"):
            self.log_view.log(msg, level)

    def set_status(self, text):
        self.status_var.set(text)

    def update_info(self):
        if not hasattr(self, "info_labels"):
            return
        remotes = self.config.get("remotes", {})
        total = sum(len(r.get("buttons", {})) for r in remotes.values())
        cur = self.config.get("remotes", {}).get(self.active_remote, {})
        used = len(cur.get("buttons", {}))
        self.info_labels["遥控器"].config(text=str(len(remotes)))
        self.info_labels["按键总数"].config(text=str(total))
        self.info_labels["通道占用"].config(text=str(used) + "/256")

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
            self.dev_led.set_state("on", Theme.GREEN)
            self.dev_led.start_pulse()
            self.hdr_led.set_state("on", Theme.GREEN)
            self.hdr_led.start_pulse()
            self.hdr_status.set("在线 · " + port)
            self.connect_btn.set_text("断 开")
            self.connect_btn.set_color(Theme.AMBER)
            self.set_status("已连接 " + port + " @ " + self.baud_var.get())
            self.log("串口已连接: " + port + " @ " + self.baud_var.get() + " bps", "ok")
        except Exception as e:
            self.log("串口连接失败: " + str(e), "err")
            messagebox.showerror("连接失败", "无法打开串口 " + port + "\n\n" + str(e))
            self.serial = None

    def disconnect(self):
        if self.serial:
            try:
                self.serial.close()
            except Exception:
                pass
            self.serial = None
        self.dev_led.set_state("off")
        self.dev_led.stop_pulse()
        self.hdr_led.set_state("off")
        self.hdr_led.stop_pulse()
        self.hdr_status.set("离线")
        self.connect_btn.set_text("连 接")
        self.connect_btn.set_color(Theme.CYAN)
        self.set_status("已断开")
        self.log("串口已断开", "warn")

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
            self.set_status("发送失败: " + str(e))
            self.log("发送失败: " + str(e), "err")
        return b""

    def on_close(self):
        self.disconnect()
        self.root.destroy()

    # -------------------- 红外操作 --------------------
    def send_ir(self, channel, name=None):
        if not self._check_serial():
            return
        label = ("[" + name + "]") if name else ("通道 " + format(channel, "02X"))
        self.log("发送 " + label + " 按键", "cmd")
        resp = self.send_frame(build_frame(CMD_SEND, channel))
        if check_resp(resp, RESP_SEND_DONE):
            self.set_status("已发送: " + label)
            self.log("发送完成, 模块反馈 " + RESP_SEND_DONE, "ok")
        elif resp:
            self.set_status("发送反馈: " + repr(resp))
            self.log("模块反馈异常: " + repr(resp), "warn")
        else:
            self.set_status("已发送: " + label + " (无反馈)")
            self.log("发送完成, 模块无反馈", "ok")

    def learn_ir(self, channel):
        if not self.serial or not self.serial.is_open:
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
                with open(CONFIG_FILE, "r", encoding="utf-8-sig") as f:
                    return json.load(f)
            except Exception as e:
                print("加载配置失败: " + str(e))
        return {"remotes": {}, "active": None}

    def save_config(self):
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            self.set_status("配置已保存")
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
        dlg = NeonDialog(self.root, "新建遥控器",
                         "请输入遥控器名称（如: 芒果TV 机顶盒）:")
        name = dlg.result
        if not name:
            return
        if name in self.config.get("remotes", {}):
            messagebox.showwarning("提示", "该名称已存在")
            return
        self.config.setdefault("remotes", {})[name] = {
            "baudrate": DEFAULT_BAUDRATE, "buttons": {}}
        self.refresh_remote_list()
        self.remote_var.set(name)
        self.active_remote = name
        self.render_buttons()
        self.save_config()
        self.log("新建遥控器: " + name, "ok")

    def delete_remote(self):
        name = self.active_remote
        if not name:
            return
        if NeonConfirm(self.root, "确认删除",
                       "确定删除遥控器「" + name + "」？\n此操作不可恢复。").result:
            self.config["remotes"].pop(name, None)
            self.refresh_remote_list()
            self.save_config()
            self.log("已删除遥控器: " + name, "warn")

    def load_remote_window(self):
        win = self.remote_win
        if win is None or not win.winfo_exists():
            win = RemoteWindow(self.root, self)
            self.remote_win = win
            sw = self.root.winfo_screenwidth()
            x = self.root.winfo_rootx() + self.root.winfo_width() + 8
            if x + 400 > sw:
                x = max(0, self.root.winfo_rootx() - 408)
            win.geometry("+%d+%d" % (x, max(0, self.root.winfo_rooty())))

            def _gone(e, w=win):
                if e.widget is w:
                    self.remote_win = None
            win.bind("<Destroy>", _gone)
        win.refresh()
        win.lift()
        self.log("已打开遥控器窗口", "sys")

    def sync_remote_window(self):
        win = self.remote_win
        if win is not None and win.winfo_exists():
            try:
                win.refresh()
            except Exception:
                pass

    def render_buttons(self):
        for w in self.panel_inner.winfo_children():
            w.destroy()
        if not self.active_remote:
            self._empty_hint("请选择或新建一个遥控器")
            self.update_info()
            return
        remote = self.config["remotes"].get(self.active_remote, {})
        buttons = remote.get("buttons", {})
        if not buttons:
            self._empty_hint("暂无按键\n点击「学习按键」添加")
            self.update_info()
            return
        cols = 4
        for i, (name, ch) in enumerate(sorted(buttons.items(), key=lambda x: x[1])):
            r, c = divmod(i, cols)
            btn = NeonButton(self.panel_inner, name,
                             lambda c=ch, n=name: self.send_ir(c, n), Theme.CYAN,
                             width=150, height=54,
                             subtext="CH " + format(ch, "02X"),
                             font_size=10, expand=True, icon=True,
                             icon_command=lambda e, n=name, c=ch: self.show_edit_popup(e, n, c))
            btn.grid(row=r, column=c, padx=4, pady=4, sticky="nsew")
        for c in range(cols):
            self.panel_inner.columnconfigure(c, weight=1)
        self.update_info()
        self.sync_remote_window()

    def _empty_hint(self, text):
        f = tk.Frame(self.panel_inner, bg=Theme.BG_INPUT)
        f.pack(expand=True)
        tk.Label(f, text=text, bg=Theme.BG_INPUT, fg=Theme.TEXT_FAINT,
                 font=(Theme.FONT_CN, 12)).pack(pady=50)

    # -------------------- 按键编辑（右上角图标） --------------------
    def show_edit_popup(self, event, name, channel):
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        outer = tk.Frame(win, bg=Theme.CYAN)
        outer.pack(fill="both", expand=True)
        inner = tk.Frame(outer, bg=Theme.BG_PANEL)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        NeonButton(inner, "重新学习",
                   lambda: self._popup_run(win, name, channel, "learn"),
                   Theme.CYAN, width=108, height=30, font_size=10).pack(padx=8, pady=(8, 4))
        NeonButton(inner, "删除按键",
                   lambda: self._popup_run(win, name, channel, "delete"),
                   Theme.RED, width=108, height=30, font_size=10).pack(padx=8, pady=(4, 8))
        win.update_idletasks()
        pw, ph = 130, 94
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = min(max(0, event.x_root - 8), max(0, sw - pw))
        y = min(max(0, event.y_root - 6), max(0, sh - ph))
        win.geometry("+%d+%d" % (x, y))
        self._popup = win
        self._popup_bind = self.root.bind("<Button-1>", self._popup_click, add="+")
        win.bind("<Escape>", lambda e: self._close_popup())
        win.focus_set()

    def _popup_run(self, win, name, channel, action):
        self._close_popup()
        if action == "learn":
            self.relearn_button(name, channel)
        else:
            self.delete_button(name, channel)

    def _close_popup(self):
        win = getattr(self, "_popup", None)
        if win is None:
            return
        self._popup = None
        try:
            self.root.unbind("<Button-1>", self._popup_bind)
        except Exception:
            pass
        try:
            win.destroy()
        except Exception:
            pass

    def _popup_click(self, event):
        win = getattr(self, "_popup", None)
        if win is None:
            return
        try:
            x = win.winfo_rootx()
            y = win.winfo_rooty()
            w = win.winfo_width()
            h = win.winfo_height()
        except Exception:
            self._close_popup()
            return
        if not (x <= event.x_root <= x + w and y <= event.y_root <= y + h):
            self._close_popup()

    def relearn_button(self, name, channel):
        if not self._check_serial():
            return
        self._start_learn(name, channel)

    def delete_button(self, name, channel):
        if not NeonConfirm(self.root, "删除按键",
                           "确定删除按键「" + name + "」(CH " +
                           format(channel, "02X") + ")？").result:
            return
        self.config["remotes"][self.active_remote]["buttons"].pop(name, None)
        self.save_config()
        self.render_buttons()
        self.log("已删除按键: " + name + " (CH " + format(channel, "02X") + ")", "warn")

    # -------------------- 学习模式 --------------------
    def _next_free_channel(self):
        used = set(self.config["remotes"][self.active_remote].get("buttons", {}).values())
        for i in range(256):
            if i not in used:
                return i
        return None

    def _start_learn(self, name, channel):
        self._learn_busy = True
        self.dev_led.set_state("on", Theme.AMBER)
        self.dev_led.start_pulse()
        self.set_status("正在学习 " + name + " -> 通道 " + format(channel, "02X") + " ...")
        self.log("进入学习模式: " + name + " -> CH " + format(channel, "02X") +
                 ", 请对准原遥控器按键", "cmd")
        threading.Thread(target=self._learn_worker, args=(name, channel),
                         daemon=True).start()

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
        dlg = NeonDialog(self.root, "学习按键",
                         "请输入按键名称（如: 电源、音量+）:")
        name = dlg.result
        if not name:
            return
        if name in self.config["remotes"][self.active_remote]["buttons"]:
            messagebox.showwarning("提示", "按键 " + name + " 已存在")
            return
        self._start_learn(name, free)

    def _learn_worker(self, name, channel):
        ok, msg = self.learn_ir(channel)
        self.root.after(0, lambda: self._learn_done(name, channel, ok, msg))

    def _learn_done(self, name, channel, ok, msg):
        self._learn_busy = False
        self.dev_led.set_state("on", Theme.GREEN)
        self.dev_led.start_pulse()
        if ok:
            self.config["remotes"][self.active_remote]["buttons"][name] = channel
            self.save_config()
            self.render_buttons()
            self.set_status("学习成功: " + name + " -> 通道 " + format(channel, "02X"))
            self.log("学习成功: " + name + " -> CH " + format(channel, "02X"), "ok")
        else:
            self.set_status("学习失败: " + msg)
            self.log("学习失败: " + msg, "err")
            messagebox.showerror("学习失败", msg)

    def learn_loop(self):
        if not self._check_serial():
            return
        if not self.active_remote:
            messagebox.showwarning("提示", "请先选择或新建遥控器")
            return
        win = tk.Toplevel(self.root)
        win.title("连续学习模式")
        win.configure(bg=Theme.BG_PANEL)
        win.geometry("560x460")
        win.transient(self.root)
        center_window(win, self.root)
        self._loop_count = 0

        tk.Label(win, text="连续学习模式 · BATCH LEARN", bg=Theme.BG_PANEL,
                 fg=Theme.CYAN, font=(Theme.FONT_CN, 13, "bold")).pack(
                     anchor="w", padx=18, pady=(16, 4))
        tk.Label(win, text="输入按键名称后点击「学习」，对准原遥控器按下对应按键",
                 bg=Theme.BG_PANEL, fg=Theme.TEXT_DIM,
                 font=(Theme.FONT_CN, 9)).pack(anchor="w", padx=18)

        row = tk.Frame(win, bg=Theme.BG_PANEL)
        row.pack(fill="x", padx=18, pady=10)
        entry = tk.Entry(row, bg=Theme.BG_INPUT, fg=Theme.TEXT,
                         font=(Theme.FONT_CN, 11), relief="flat",
                         insertbackground=Theme.CYAN, highlightthickness=1,
                         highlightbackground=Theme.BORDER)
        entry.pack(side="left", fill="x", expand=True, ipady=5)
        entry.focus_set()

        log_view = TerminalLog(win, height=120)
        log_view.pack(fill="both", expand=True, padx=18, pady=(0, 8))

        bottom = tk.Frame(win, bg=Theme.BG_PANEL)
        bottom.pack(fill="x", padx=18, pady=(0, 14))
        lbl_count = tk.Label(bottom, text="本次已学习 0 个按键",
                             bg=Theme.BG_PANEL, fg=Theme.TEXT_DIM,
                             font=(Theme.FONT_CN, 9))
        lbl_count.pack(side="left")

        def do_learn():
            name = entry.get().strip()
            if not name:
                return
            if name in self.config["remotes"][self.active_remote]["buttons"]:
                log_view.log("警告: 按键 " + name + " 已存在, 跳过", "warn")
                return
            free = self._next_free_channel()
            if free is None:
                log_view.log("警告: 通道已用完", "warn")
                return
            log_view.log("进入学习模式: " + name + " -> CH " + format(free, "02X"),
                         "cmd")
            threading.Thread(target=self._loop_worker,
                             args=(name, free, log_view.log, lbl_count),
                             daemon=True).start()
            entry.delete(0, "end")

        NeonButton(row, "学 习", do_learn, Theme.CYAN, width=96,
                   height=36).pack(side="left", padx=(8, 0))
        NeonButton(bottom, "完 成", lambda: (self.save_config(), win.destroy()),
                   Theme.GREEN, width=100, height=34).pack(side="right")
        entry.bind("<Return>", lambda e: do_learn())

    def _loop_worker(self, name, channel, log_fn, lbl_count):
        ok, msg = self.learn_ir(channel)
        self.root.after(0, lambda: self._loop_done(name, channel, ok, msg,
                                                   log_fn, lbl_count))

    def _loop_done(self, name, channel, ok, msg, log_fn, lbl_count):
        if ok:
            self.config["remotes"][self.active_remote]["buttons"][name] = channel
            self._loop_count += 1
            lbl_count.config(text="本次已学习 " + str(self._loop_count) + " 个按键")
            log_fn("成功: " + name + " -> CH " + format(channel, "02X"), "ok")
            self.render_buttons()
        else:
            log_fn("失败: " + name + " - " + msg, "err")


# ==================== 协议工具 ====================
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


# ==================== 入口 ====================
def main():
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    root = tk.Tk()
    root.title("电脑红外遥控器 - IR03T")
    root.configure(bg=Theme.BG)
    root.geometry("1000x880")
    root.minsize(880, 750)

    try:
        from tkinter import font as tkfont
        if "Cascadia Mono" in set(tkfont.families()):
            Theme.FONT_MONO = "Cascadia Mono"
    except Exception:
        pass

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure("TCombobox", background=Theme.BG_CARD,
                    foreground=Theme.TEXT, fieldbackground=Theme.BG_INPUT,
                    arrowcolor=Theme.CYAN, bordercolor=Theme.BORDER,
                    lightcolor=Theme.BG_CARD, darkcolor=Theme.BG_CARD,
                    insertcolor=Theme.CYAN, padding=(4, 3))
    style.map("TCombobox",
              background=[("readonly", Theme.BG_CARD)],
              foreground=[("readonly", Theme.TEXT)],
              fieldbackground=[("readonly", Theme.BG_INPUT)],
              arrowcolor=[("readonly", Theme.CYAN)])
    root.option_add("*TCombobox*Listbox.background", Theme.BG_INPUT)
    root.option_add("*TCombobox*Listbox.foreground", Theme.TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground",
                    blend(Theme.CYAN, Theme.BG_INPUT, 0.7))
    root.option_add("*TCombobox*Listbox.selectForeground", "#FFFFFF")
    style.configure("Vertical.TScrollbar", background=Theme.BG_CARD,
                    troughcolor=Theme.BG_PANEL, arrowcolor=Theme.CYAN,
                    bordercolor=Theme.BORDER, lightcolor=Theme.BG_CARD,
                    darkcolor=Theme.BG_CARD, width=10)
    style.map("Vertical.TScrollbar",
              background=[("active", blend(Theme.CYAN, Theme.BG_CARD, 0.25))],
              arrowcolor=[("active", Theme.CYAN)])

    app = IRRemoteApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()