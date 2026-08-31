# -*- coding: utf-8 -*-
"""
番茄钟 · Pomodoro —— 简洁黑白双主题

在参考程序 study_timer.py 的基础上重新设计：
  · 番茄工作法循环：专注 → 短休息 → … → 每 4 个番茄进入长休息
  · 深色 / 浅色（黑 / 白）主题一键切换，极简高级风格（单色设计）
  · 专注 / 短休 / 长休时长可调
  · 待办事项管理
  · 今日与近 7 天专注统计（纯 tkinter 绘制，无第三方依赖）

运行：python pomodoro.py
快捷键：空格 开始 / 暂停
"""

import json
import math
import os
import time
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta

import tkinter as tk

try:
    import winsound
except ImportError:
    winsound = None

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(APP_DIR, "pomodoro_data.json")

# ---- 黑白双主题（单色极简配色）----
THEMES = {
    "dark": {
        "name": "深色",
        "bg": "#0C0C0E",
        "surface": "#151517",
        "text": "#F5F5F6",
        "muted": "#84848A",
        "faint": "#3A3A40",
        "line": "#232327",
        "ring_track": "#1F1F23",
        "primary_bg": "#F5F5F6",
        "primary_fg": "#0C0C0E",
        "primary_hover": "#D9D9DC",
        "sel_bg": "#26262B",
    },
    "light": {
        "name": "浅色",
        "bg": "#FAFAFA",
        "surface": "#FFFFFF",
        "text": "#121214",
        "muted": "#8C8C92",
        "faint": "#D7D7DB",
        "line": "#E9E9EC",
        "ring_track": "#E9E9EC",
        "primary_bg": "#121214",
        "primary_fg": "#FAFAFA",
        "primary_hover": "#3B3B40",
        "sel_bg": "#E3E3E7",
    },
}

PHASE_ORDER = ("focus", "short", "long")
PHASE_NAMES = {"focus": "专注", "short": "短休息", "long": "长休息"}
PHASE_KIND = {"focus": "focus", "short": "break", "long": "break"}
DEFAULT_DURATIONS = {"focus": 25, "short": 5, "long": 15}
DURATION_LIMITS = {"focus": (1, 120), "short": (1, 30), "long": (1, 60)}
WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
FONT_UI = "Microsoft YaHei UI"
FONT_TIME = "Segoe UI Light"


def fmt_time(secs):
    """将秒数格式化为 MM:SS 或 H:MM:SS。"""
    secs = max(0, int(math.ceil(secs)))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


class PomodoroApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("番茄钟")
        self.root.geometry("480x720+140+100")
        self.root.minsize(440, 660)

        self.data = self.load_data()
        cfg = self.data.setdefault("config", {})

        # 主题（可用环境变量 POMODORO_THEME 强制初始主题，便于测试）
        self.theme = os.environ.get("POMODORO_THEME") or cfg.get("theme", "dark")
        if self.theme not in THEMES:
            self.theme = "dark"

        self.durations = dict(DEFAULT_DURATIONS)
        for k in self.durations:
            try:
                self.durations[k] = int(cfg.get(k, self.durations[k]))
            except (TypeError, ValueError):
                pass
            lo, hi = DURATION_LIMITS[k]
            self.durations[k] = max(lo, min(hi, self.durations[k]))

        # 计时状态
        self.phase = "focus"                 # 当前阶段 focus / short / long
        self.running = False
        self.paused = False
        self.accumulated = 0.0
        self.run_start = 0.0
        self.focus_count_cycle = int(cfg.get("cycle_count", 0) or 0)
        self.today = date.today()

        # 需要随主题重绘的控件集合
        self.frames = []
        self.labels = []
        self.lines = []
        self.entries = []
        self.listboxes = []
        self.scrollbars = []
        self.canvases = []
        self.primary_btns = []
        self.text_btns = []

        self.build_ui()
        self.apply_theme()

        # 初始显示
        self.update_date_label()
        self.update_ring_display(self.durations[self.phase] * 60)
        self.update_cycle_label()
        self.update_status_default()
        self.update_controls()
        self.update_seg_labels()
        self.refresh_todos()
        self.refresh_stats()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.bind("<space>", self.on_space)
        self.root.after(200, self.tick)

    # ---------------- 数据读写 ----------------
    def load_data(self):
        if os.path.exists(DATA_PATH):
            try:
                with open(DATA_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    data.setdefault("sessions", [])
                    data.setdefault("todos", [])
                    data.setdefault("config", {})
                    return data
            except Exception:
                pass
        return {"sessions": [], "todos": [], "config": {}}

    def save_data(self):
        try:
            with open(DATA_PATH, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ---------------- 控件工厂 ----------------
    def _frame(self, parent):
        f = tk.Frame(parent)
        self.frames.append(f)
        return f

    def _label(self, parent, **kw):
        kw.setdefault("font", (FONT_UI, 11))
        l = tk.Label(parent, **kw)
        self.labels.append(l)
        return l

    def _line(self, parent):
        ln = tk.Frame(parent, height=1)
        self.lines.append(ln)
        return ln

    def _btn_primary(self, parent, text, command, small=False):
        kw = dict(
            text=text, command=command, relief="flat", bd=0, cursor="hand2",
            font=(FONT_UI, 12 if not small else 11),
            padx=34 if not small else 18, pady=9 if not small else 6,
        )
        b = tk.Button(parent, **kw)
        self.primary_btns.append(b)
        b.bind("<Enter>", lambda e: b.configure(bg=self.pal["primary_hover"]))
        b.bind("<Leave>", lambda e: b.configure(bg=self.pal["primary_bg"]))
        return b

    def _btn_text(self, parent, text, command, font_size=11):
        b = tk.Button(
            parent, text=text, command=command, relief="flat", bd=0,
            cursor="hand2", font=(FONT_UI, font_size), padx=4, pady=4,
        )
        self.text_btns.append(b)
        b.bind("<Enter>", lambda e: b.configure(fg=self.pal["text"]))
        b.bind("<Leave>", lambda e: b.configure(fg=self.pal["muted"]))
        return b

    # ---------------- 界面搭建 ----------------
    def build_ui(self):
        root = self.root

        # 顶栏：标题 + 日期 + 主题切换
        top = self._frame(root)
        top.pack(fill="x", padx=26, pady=(20, 6))
        self.title_lbl = self._label(top, text="番茄钟", font=(FONT_UI, 16, "bold"))
        self.title_lbl.pack(side="left")
        self.theme_btn = self._btn_text(top, text="◐ 深色", command=self.toggle_theme, font_size=10)
        self.theme_btn.pack(side="right")
        self.date_lbl = self._label(top, text="", font=(FONT_UI, 10))
        self.date_lbl.pack(side="right", padx=(0, 16))

        self._line(root).pack(fill="x", padx=26, pady=(0, 4))

        # 标签页：计时 / 待办 / 统计
        tabbar = self._frame(root)
        tabbar.pack(fill="x", padx=26)
        self.tab_widgets = {}
        for key, name in (("timer", "计时"), ("todo", "待办"), ("stats", "统计")):
            cell = self._frame(tabbar)
            cell.pack(side="left", padx=(0, 26))
            lbl = self._label(cell, text=name, font=(FONT_UI, 12), cursor="hand2")
            lbl.pack()
            und = tk.Frame(cell, width=28, height=2)
            self.frames.append(und)
            und.pack(pady=(3, 0))
            lbl.bind("<Button-1>", lambda e, k=key: self.show_tab(k))
            self.tab_widgets[key] = (lbl, und)

        # 内容区
        self.content = self._frame(root)
        self.content.pack(fill="both", expand=True, padx=26, pady=(8, 14))
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)
        self.timer_tab = self._frame(self.content)
        self.todo_tab = self._frame(self.content)
        self.stats_tab = self._frame(self.content)
        for frm in (self.timer_tab, self.todo_tab, self.stats_tab):
            frm.grid(row=0, column=0, sticky="nsew")

        self.build_timer_tab()
        self.build_todo_tab()
        self.build_stats_tab()
        self.current_tab = "timer"
        self.timer_tab.tkraise()

    def build_timer_tab(self):
        frm = self.timer_tab

        # 阶段分段控件
        seg = self._frame(frm)
        seg.pack(pady=(4, 0))
        self.seg_widgets = {}
        for ph in PHASE_ORDER:
            cell = self._frame(seg)
            cell.pack(side="left", padx=14)
            lbl = self._label(cell, text=PHASE_NAMES[ph], font=(FONT_UI, 12), cursor="hand2")
            lbl.pack()
            und = tk.Frame(cell, width=32, height=2)
            self.frames.append(und)
            und.pack(pady=(4, 0))
            lbl.bind("<Button-1>", lambda e, p=ph: self.switch_phase(p))
            self.seg_widgets[ph] = (lbl, und)

        # 环形进度 + 时间
        self.ring = tk.Canvas(frm, width=340, height=330, highlightthickness=0)
        self.canvases.append(self.ring)
        self.ring.pack(pady=(6, 0))
        self.cx, self.cy, self.r = 170, 164, 130
        self.track_id = self.ring.create_oval(
            self.cx - self.r, self.cy - self.r, self.cx + self.r, self.cy + self.r,
            width=7, fill="",
        )
        self.arc_id = self.ring.create_arc(
            self.cx - self.r, self.cy - self.r, self.cx + self.r, self.cy + self.r,
            start=-90, extent=0, style=tk.ARC, width=7,
        )
        self.time_id = self.ring.create_text(self.cx, self.cy - 14, text="25:00", font=(FONT_TIME, 54))
        self.phase_id = self.ring.create_text(self.cx, self.cy + 44, text="专注", font=(FONT_UI, 12))

        # 本轮进度
        self.cycle_lbl = self._label(frm, text="", font=(FONT_UI, 10))
        self.cycle_lbl.pack(pady=(2, 0))
        # 状态提示
        self.status_lbl = self._label(frm, text="", font=(FONT_UI, 10))
        self.status_lbl.pack(pady=(2, 0))

        # 控制按钮
        ctl = self._frame(frm)
        ctl.pack(pady=(12, 0))
        self.main_btn = self._btn_primary(ctl, text="开始", command=self.toggle_start_pause)
        self.main_btn.pack(side="left")
        self.reset_btn = self._btn_text(ctl, text="重置", command=self.reset_timer)
        self.reset_btn.pack(side="left", padx=(14, 0))
        self.skip_btn = self._btn_text(ctl, text="跳过", command=self.skip_phase)
        self.skip_btn.pack(side="left", padx=(8, 0))

        # 时长调整
        dur = self._frame(frm)
        dur.pack(pady=(18, 0))
        self.steppers = {}
        for i, ph in enumerate(PHASE_ORDER):
            cell = self._frame(dur)
            cell.pack(side="left", padx=(0 if i == 0 else 24, 0))
            self._label(cell, text=PHASE_NAMES[ph], font=(FONT_UI, 10)).pack(side="left")
            minus = self._btn_text(cell, text="−", command=lambda p=ph: self.step_duration(p, -1), font_size=12)
            minus.pack(side="left", padx=(8, 0))
            val = self._label(cell, text="25", font=(FONT_UI, 11, "bold"), width=3, anchor="center")
            val.pack(side="left", padx=2)
            plus = self._btn_text(cell, text="+", command=lambda p=ph: self.step_duration(p, 1), font_size=12)
            plus.pack(side="left")
            self.steppers[ph] = (minus, val, plus)

        hint = self._label(frm, text="空格键 开始 / 暂停", font=(FONT_UI, 9))
        hint.pack(side="bottom", pady=(6, 0))

    def build_todo_tab(self):
        frm = self.todo_tab

        add = self._frame(frm)
        add.pack(fill="x", pady=(12, 8))
        self.todo_entry = tk.Entry(add, font=(FONT_UI, 11), relief="flat", highlightthickness=1)
        self.entries.append(self.todo_entry)
        self.todo_entry.pack(side="left", fill="x", expand=True, ipady=6)
        self.add_btn = self._btn_primary(add, text="添加", command=self.add_todo, small=True)
        self.add_btn.pack(side="left", padx=(10, 0))

        body = self._frame(frm)
        body.pack(fill="both", expand=True)
        self.todo_list = tk.Listbox(
            body, font=(FONT_UI, 11), relief="flat", highlightthickness=0,
            activestyle="none", selectborderwidth=0, exportselection=False,
        )
        self.listboxes.append(self.todo_list)
        self.todo_list.pack(side="left", fill="both", expand=True)
        sb = tk.Scrollbar(body, orient="vertical", command=self.todo_list.yview, relief="flat", bd=0)
        self.scrollbars.append(sb)
        sb.pack(side="right", fill="y")
        self.todo_list.configure(yscrollcommand=sb.set)
        self.todo_list.bind("<Double-1>", lambda e: self.toggle_todo())
        self.todo_list.bind("<Return>", lambda e: self.toggle_todo())
        self.todo_entry.bind("<Return>", lambda e: self.add_todo())

        ops = self._frame(frm)
        ops.pack(pady=(10, 0))
        self.done_btn = self._btn_text(ops, text="✓ 完成", command=self.toggle_todo)
        self.done_btn.pack(side="left", padx=(0, 16))
        self.del_btn = self._btn_text(ops, text="删除", command=self.delete_todo)
        self.del_btn.pack(side="left", padx=(0, 16))
        self.clear_btn = self._btn_text(ops, text="清空已完成", command=self.clear_done)
        self.clear_btn.pack(side="left")

        hint = self._label(frm, text="双击条目切换完成状态", font=(FONT_UI, 9))
        hint.pack(side="bottom", pady=(6, 0))

    def build_stats_tab(self):
        frm = self.stats_tab
        self.summary_lbl = self._label(frm, text="", font=(FONT_UI, 12))
        self.summary_lbl.pack(anchor="w", pady=(14, 4))
        self.chart = tk.Canvas(frm, width=420, height=250, highlightthickness=0)
        self.canvases.append(self.chart)
        self.chart.pack(fill="x", pady=(4, 0))
        self.chart.bind("<Configure>", lambda e: self.draw_chart())
        cap = self._label(frm, text="近 7 天专注时长（分钟）", font=(FONT_UI, 10))
        cap.pack(anchor="w", pady=(6, 0))
        hint = self._label(frm, text="每完成一个完整的专注周期会自动记录", font=(FONT_UI, 9))
        hint.pack(side="bottom", pady=(6, 0))

    # ---------------- 主题 ----------------
    def toggle_theme(self):
        self.theme = "light" if self.theme == "dark" else "dark"
        self.data.setdefault("config", {})["theme"] = self.theme
        self.save_data()
        self.apply_theme()

    def apply_theme(self):
        pal = THEMES[self.theme]
        self.pal = pal
        self.root.configure(bg=pal["bg"])
        for f in self.frames:
            f.configure(bg=pal["bg"])
        for ln in self.lines:
            ln.configure(bg=pal["line"])
        for l in self.labels:
            l.configure(bg=pal["bg"], fg=pal["text"])
        for b in self.primary_btns:
            b.configure(bg=pal["primary_bg"], fg=pal["primary_fg"],
                        activebackground=pal["primary_hover"], activeforeground=pal["primary_fg"])
        for b in self.text_btns:
            b.configure(bg=pal["bg"], fg=pal["muted"], activebackground=pal["bg"],
                        activeforeground=pal["text"])
        for e in self.entries:
            e.configure(bg=pal["surface"], fg=pal["text"], insertbackground=pal["text"],
                        highlightbackground=pal["line"], highlightcolor=pal["line"])
        for lb in self.listboxes:
            lb.configure(bg=pal["surface"], fg=pal["text"],
                         selectbackground=pal["sel_bg"], selectforeground=pal["text"])
        for sb in self.scrollbars:
            sb.configure(bg=pal["surface"], troughcolor=pal["bg"], activebackground=pal["faint"],
                         highlightthickness=0)
        for c in self.canvases:
            c.configure(bg=pal["bg"], highlightbackground=pal["bg"])

        self.theme_btn.configure(text="◐ " + pal["name"])
        self.cycle_lbl.configure(fg=pal["muted"])
        self.date_lbl.configure(fg=pal["muted"])

        # 环形画布元素
        self.ring.itemconfig(self.track_id, outline=pal["ring_track"])
        self.ring.itemconfig(self.arc_id, outline=pal["text"])
        self.ring.itemconfig(self.time_id, fill=pal["text"])
        self.ring.itemconfig(self.phase_id, fill=pal["muted"])

        self.update_tab_colors()
        self.draw_chart()

    def update_tab_colors(self):
        pal = self.pal
        for key, (lbl, und) in self.tab_widgets.items():
            active = (key == self.current_tab)
            lbl.configure(fg=pal["text"] if active else pal["muted"])
            und.configure(bg=pal["text"] if active else pal["bg"])
        for ph, (lbl, und) in self.seg_widgets.items():
            active = (ph == self.phase)
            lbl.configure(fg=pal["text"] if active else pal["muted"])
            und.configure(bg=pal["text"] if active else pal["bg"])

    def show_tab(self, key):
        self.current_tab = key
        {
            "timer": self.timer_tab,
            "todo": self.todo_tab,
            "stats": self.stats_tab,
        }[key].tkraise()
        if key == "todo":
            self.todo_entry.focus_set()
        if key == "stats":
            self.refresh_stats()
        self.update_tab_colors()

    # ---------------- 计时核心 ----------------
    def current_elapsed(self):
        if not (self.running or self.paused):
            return 0.0
        if self.paused:
            return self.accumulated
        return self.accumulated + (time.monotonic() - self.run_start)

    def toggle_start_pause(self):
        if not self.running and not self.paused:
            self.start_timer()
        elif self.running and not self.paused:
            self.pause_timer()
        else:
            self.resume_timer()

    def start_timer(self):
        if self.running or self.paused:
            return
        self.accumulated = 0.0
        self.run_start = time.monotonic()
        self.running = True
        self.paused = False
        self.status_lbl.configure(text=self.status_text(self.phase))
        self.update_controls()

    def pause_timer(self):
        if not self.running or self.paused:
            return
        self.accumulated += time.monotonic() - self.run_start
        self.paused = True
        self.status_lbl.configure(text="已暂停")
        self.update_controls()

    def resume_timer(self):
        if not self.paused:
            return
        self.run_start = time.monotonic()
        self.paused = False
        self.running = True
        self.status_lbl.configure(text=self.status_text(self.phase))
        self.update_controls()

    def reset_timer(self):
        self.running = False
        self.paused = False
        self.accumulated = 0.0
        self.status_lbl.configure(text="已重置")
        self.update_ring_display(self.durations[self.phase] * 60)
        self.update_controls()

    def skip_phase(self):
        self.running = False
        self.paused = False
        self.accumulated = 0.0
        self.advance_phase(message="已跳过")

    def advance_phase(self, message=None):
        if self.phase == "focus":
            nxt = "short"
        else:
            nxt = "focus"
        self.phase = nxt
        if message:
            self.status_lbl.configure(text=message)
        else:
            self.status_lbl.configure(text=self.status_text(self.phase))
        self.update_ring_display(self.durations[self.phase] * 60)
        self.update_cycle_label()
        self.update_tab_colors()
        self.update_controls()

    def switch_phase(self, ph):
        if ph == self.phase:
            return
        if self.running or self.paused:
            return  # 计时中不允许直接切换
        self.phase = ph
        self.accumulated = 0.0
        self.status_lbl.configure(text=self.status_text(ph))
        self.update_ring_display(self.durations[ph] * 60)
        self.update_cycle_label()
        self.update_tab_colors()

    def finish_phase(self):
        self.running = False
        self.paused = False
        self.accumulated = 0.0
        self.beep()

        kind = PHASE_KIND[self.phase]
        if kind == "focus":
            self.record_focus()
            self.focus_count_cycle += 1
            if self.focus_count_cycle % 4 == 0:
                nxt = "long"
                self.focus_count_cycle = 0
                msg = "第 4 个番茄完成 · 进入长休息"
            else:
                nxt = "short"
                msg = "专注完成 · 休息一下"
        else:
            nxt = "focus"
            msg = "休息结束 · 开始专注"

        self.data.setdefault("config", {})["cycle_count"] = self.focus_count_cycle
        self.save_data()

        self.phase = nxt
        self.status_lbl.configure(text=msg)
        self.update_ring_display(self.durations[self.phase] * 60)
        self.update_cycle_label()
        self.update_tab_colors()
        self.update_controls()
        self.refresh_stats()

    def record_focus(self):
        end = datetime.now()
        start = end - timedelta(seconds=self.durations["focus"] * 60)
        session = {
            "id": str(uuid.uuid4())[:8],
            "phase": "focus",
            "seconds": self.durations["focus"] * 60,
            "start_time": start.strftime("%Y-%m-%d %H:%M:%S"),
            "end_time": end.strftime("%Y-%m-%d %H:%M:%S"),
            "date": start.strftime("%Y-%m-%d"),
        }
        self.data["sessions"].append(session)

    def beep(self):
        if winsound:
            try:
                winsound.Beep(880, 240)
                winsound.Beep(1319, 240)
            except Exception:
                pass

    def tick(self):
        if self.running and not self.paused:
            total = self.durations[self.phase] * 60
            remain = total - self.current_elapsed()
            if remain <= 0:
                self.update_ring_display(0)
                self.finish_phase()
            else:
                self.update_ring_display(remain)
        self.update_date_label()
        self.root.after(200, self.tick)

    def update_ring_display(self, remain):
        total = self.durations[self.phase] * 60
        frac = 0.0 if total <= 0 else min(1.0, max(0.0, (total - remain) / total))
        self.ring.itemconfig(self.time_id, text=fmt_time(remain))
        self.ring.itemconfig(self.arc_id, extent=-359.9 * frac)
        self.ring.itemconfig(self.phase_id, text=PHASE_NAMES[self.phase])

    def update_controls(self):
        if self.running and not self.paused:
            self.main_btn.configure(text="暂停")
        elif self.paused:
            self.main_btn.configure(text="继续")
        else:
            self.main_btn.configure(text="开始")
        state = "disabled" if (self.running or self.paused) else "normal"
        for ph in PHASE_ORDER:
            minus, _, plus = self.steppers[ph]
            minus.configure(state=state)
            plus.configure(state=state)

    def status_text(self, ph):
        d = self.durations[ph]
        if ph == "focus":
            return f"专注 {d} 分钟 · 保持节奏"
        if ph == "short":
            return f"休息 {d} 分钟 · 放松一下"
        return f"长休息 {d} 分钟 · 彻底放松"

    def update_cycle_label(self):
        if self.phase == "long":
            self.cycle_lbl.configure(text="已完成 4 个番茄 · 长休息")
        elif self.focus_count_cycle == 0:
            self.cycle_lbl.configure(text="本轮 0 / 4 个番茄")
        else:
            self.cycle_lbl.configure(text=f"本轮已完成 {self.focus_count_cycle} / 4 个番茄")

    def update_status_default(self):
        self.status_lbl.configure(text=self.status_text(self.phase))

    def update_seg_labels(self):
        for ph in PHASE_ORDER:
            lbl, _ = self.seg_widgets[ph]
            lbl.configure(text=f"{PHASE_NAMES[ph]} {self.durations[ph]}")

    def step_duration(self, ph, delta):
        if self.running or self.paused:
            return
        lo, hi = DURATION_LIMITS[ph]
        v = max(lo, min(hi, self.durations[ph] + delta))
        if v == self.durations[ph]:
            return
        self.durations[ph] = v
        self.data.setdefault("config", {})[ph] = v
        self.save_data()
        self.steppers[ph][1].configure(text=str(v))
        self.update_seg_labels()
        if ph == self.phase:
            self.update_ring_display(self.durations[ph] * 60)
            self.status_lbl.configure(text=self.status_text(ph))

    def update_date_label(self):
        today = date.today()
        if today != self.today:
            self.today = today
            self.refresh_stats()
        self.date_lbl.configure(
            text=f"{today.month}月{today.day}日 · {WEEKDAYS[today.weekday()]}"
        )

    def on_space(self, _event):
        w = self.root.focus_get()
        if isinstance(w, (tk.Entry, tk.Listbox)):
            return
        self.toggle_start_pause()

    # ---------------- 待办事项 ----------------
    def add_todo(self):
        text = self.todo_entry.get().strip()
        if not text:
            return
        self.data["todos"].append({
            "id": str(uuid.uuid4())[:8],
            "text": text,
            "done": False,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        })
        self.save_data()
        self.todo_entry.delete(0, "end")
        self.refresh_todos()
        self.todo_entry.focus_set()

    def selected_todo_index(self):
        sel = self.todo_list.curselection()
        return sel[0] if sel else None

    def toggle_todo(self):
        idx = self.selected_todo_index()
        if idx is None:
            return
        todo = self.data["todos"][idx]
        todo["done"] = not todo["done"]
        self.save_data()
        self.refresh_todos()
        if idx < self.todo_list.size():
            self.todo_list.selection_set(idx)

    def delete_todo(self):
        idx = self.selected_todo_index()
        if idx is None:
            return
        del self.data["todos"][idx]
        self.save_data()
        self.refresh_todos()

    def clear_done(self):
        self.data["todos"] = [t for t in self.data["todos"] if not t["done"]]
        self.save_data()
        self.refresh_todos()

    def refresh_todos(self):
        self.todo_list.delete(0, "end")
        for todo in self.data["todos"]:
            mark = "✓ " if todo["done"] else "   "
            self.todo_list.insert("end", mark + todo["text"])

    # ---------------- 统计 ----------------
    def refresh_stats(self):
        sessions = self.data["sessions"]
        total_count = len(sessions)
        total_seconds = sum(s.get("seconds", 0) for s in sessions)
        today_str = self.today.strftime("%Y-%m-%d")
        today_count = sum(1 for s in sessions if s.get("date") == today_str)
        today_seconds = sum(s.get("seconds", 0) for s in sessions if s.get("date") == today_str)
        self.summary_lbl.configure(
            text=f"今日  {today_count} 个番茄 · {today_seconds // 60} 分钟        "
                 f"累计  {total_count} 个番茄 · {total_seconds // 3600} 小时 {total_seconds % 3600 // 60} 分钟"
        )
        self.draw_chart()

    def draw_chart(self):
        c = self.chart
        c.delete("all")
        pal = self.pal
        tw = c.winfo_width()
        th = c.winfo_height()
        if tw < 60:
            tw = 420
        if th < 60:
            th = 250

        pad_l, pad_r, pad_t, pad_b = 10, 10, 26, 30
        inner_w = tw - pad_l - pad_r
        inner_h = th - pad_t - pad_b

        today = date.today()
        days = [today - timedelta(days=i) for i in range(6, -1, -1)]
        daily = defaultdict(int)
        for s in self.data["sessions"]:
            daily[s.get("date", "")] += s.get("seconds", 0)
        vals = [daily[d.strftime("%Y-%m-%d")] / 60.0 for d in days]
        mx = max(max(vals, default=0.0), 1.0)

        base_y = pad_t + inner_h
        c.create_line(pad_l, base_y, pad_l + inner_w, base_y, fill=pal["line"])
        slot = inner_w / 7.0
        for i, (d, v) in enumerate(zip(days, vals)):
            x0 = pad_l + slot * i + slot * 0.24
            x1 = pad_l + slot * (i + 1) - slot * 0.24
            bar_h = (v / mx) * (inner_h - 16) if v > 0 else 2.5
            fill = pal["text"] if i == 6 else pal["faint"]
            c.create_rectangle(x0, base_y - bar_h, x1, base_y, fill=fill, outline="")
            if v > 0:
                c.create_text((x0 + x1) / 2, base_y - bar_h - 9, text=f"{v:.0f}",
                              fill=pal["muted"], font=(FONT_UI, 8))
            c.create_text((x0 + x1) / 2, base_y + 14, text=d.strftime("%m-%d"),
                          fill=pal["text"] if i == 6 else pal["muted"], font=(FONT_UI, 8))

    # ---------------- 退出 ----------------
    def on_close(self):
        self.save_data()
        self.root.destroy()


def main():
    root = tk.Tk()
    PomodoroApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
