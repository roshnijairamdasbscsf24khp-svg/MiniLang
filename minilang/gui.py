"""MiniLang workbench: editor on the left, one page per compiler stage on the right."""
import itertools
import json
import math
import os
import re
import time
import tkinter as tk
from tkinter import filedialog, font as tkfont, ttk

from .ast_nodes import describe
from .compiler import compare_strategies, compile_source
from .interpreter import Machine
from .parser import COMPARE_OPS, STRATEGIES, STRATEGY_BLURB, STRATEGY_NAMES, RepairOptions
from .recovery import build_items
from .runtime import format_value
from .samples import SAMPLES
from .tokens import TokenType, token_category

# ---------------------------------------------------------------- themes
THEME_FILE = os.path.join(os.path.expanduser("~"), ".minilang_theme")


def _rgb(c):
    return [int(c[i:i + 2], 16) for i in (1, 3, 5)]


def blend(a, b, t):
    """t of colour a over colour b."""
    return "#%02x%02x%02x" % tuple(round(x * t + y * (1 - t)) for x, y in zip(_rgb(a), _rgb(b)))


LIGHT_INK = dict(GREEN="#3f7d4e", RED="#c0392b", BLUE="#2f6f8f", PLUM="#8a5a7a", SAND="#8a6d2f",
                 TEAL="#2a7f7a", ORANGE="#c06a2b")
DARK_INK = dict(GREEN="#3ddc97", RED="#ff5d6c", BLUE="#4cc2ff", PLUM="#ff7ab6", SAND="#ffd166",
                TEAL="#2ee6d6", ORANGE="#ff8a3d")
THEMES = {
    "Obsidian": dict(dark=True, BG="#06080c", PANEL="#0e121a", PANEL2="#151b26", SIDEBAR="#090c11", LINE="#222b3a",
                     TEXT="#eef2f8", MUTED="#7f8b9d", ACCENT="#ffb020", ON_ACCENT="#1a1203"),
    "Emerald": dict(dark=True, BG="#05090a", PANEL="#0c1415", PANEL2="#132022", SIDEBAR="#070d0e", LINE="#1f3335",
                    TEXT="#e9f5f1", MUTED="#7a9690", ACCENT="#3ddc97", ON_ACCENT="#04150d"),
    "Ruby": dict(dark=True, BG="#0a0608", PANEL="#150d11", PANEL2="#1e1318", SIDEBAR="#0d080a", LINE="#33202a",
                 TEXT="#f7ecef", MUTED="#a08890", ACCENT="#ff5d6c", ON_ACCENT="#1c0508"),
    "Paper": dict(dark=False, BG="#f3efe6", PANEL="#fffdf9", PANEL2="#ebe5d8", SIDEBAR="#e4dccb", LINE="#d2c9b6",
                  TEXT="#2b2824", MUTED="#7d7567", ACCENT="#b4532a", ON_ACCENT="#ffffff"),
}
THEME_NAME = "Obsidian"


def apply_theme(name):
    """Sets the module-level colours; call it before creating the window."""
    global THEME_NAME, KIND_COLORS, TOKEN_COLORS
    t, g = THEMES[name], globals()
    THEME_NAME = name
    g.update({k: v for k, v in t.items() if k != "dark"})
    g.update(DARK_INK if t["dark"] else LIGHT_INK)
    g["HOVER"] = blend(t["TEXT"], t["PANEL2"], 0.08)
    g["ACCENT_HOVER"] = blend(t["ACCENT"], "#ffffff", 0.85)
    g["SEL"] = g["ROWSEL"] = blend(t["ACCENT"], t["PANEL"], 0.25)
    g["HL"] = blend(g["SAND"], t["PANEL"], 0.35)
    g["ERRBG"] = blend(g["RED"], t["PANEL"], 0.18)
    mix = 0.20 if t["dark"] else 0.16
    g["GLOW"] = t["dark"]                    # soft neon halo around nodes on the black themes
    edges = {"program": t["ACCENT"], "decl": g["GREEN"], "assign": g["BLUE"], "print": g["PLUM"], "op": g["SAND"],
             "ident": g["TEAL"], "literal": blend(t["TEXT"], t["PANEL"], 0.6), "control": g["ORANGE"], "other": t["MUTED"]}
    KIND_COLORS = {k: (blend(e, t["PANEL"], mix), e) for k, e in edges.items()}     # kind -> (fill, edge/label)
    TOKEN_COLORS = {"keyword": t["ACCENT"], "literal": g["BLUE"], "identifier": g["TEAL"], "operator": g["SAND"],
                    "punct": t["MUTED"], "eof": t["MUTED"]}


def saved_theme():
    try:
        with open(THEME_FILE, encoding="utf-8") as f:
            name = f.read().strip()
        return name if name in THEMES else "Obsidian"
    except OSError:
        return "Obsidian"


apply_theme(saved_theme())

KIND_OF = {"Program": "program", "Block": "other", "VarDecl": "decl", "Assign": "assign", "Print": "print",
           "If": "control", "While": "control", "Binary": "op", "Unary": "op", "Variable": "ident",
           "Literal": "literal"}
STATE_OF = {"ok": "ok", "fail": "fail", "skipped": "skip"}


def pick_font(candidates, fallback="Courier New"):
    have = set(tkfont.families())
    for c in candidates:
        if c in have:
            return c
    return fallback


def flat_button(parent, text, command, accent=False):
    base, hover = (ACCENT, ACCENT_HOVER) if accent else (PANEL, HOVER)
    b = tk.Label(parent, text=text, bg=base, fg=ON_ACCENT if accent else TEXT, padx=10, pady=5, cursor="hand2",
                 font=("Segoe UI", 9, "bold" if accent else "normal"),
                 highlightthickness=0 if accent else 1, highlightbackground=LINE)
    b.bind("<Enter>", lambda e: b.config(bg=hover))
    b.bind("<Leave>", lambda e: b.config(bg=base))
    b.bind("<Button-1>", lambda e: command())
    return b


# ---------------------------------------------------------------- syntax tree view
class VNode:
    def __init__(self, label, detail, kind, line, role, order):
        self.label, self.detail, self.kind, self.line, self.role, self.order = label, detail, kind, line, role, order
        self.children = []
        self.collapsed = False
        self.w = self.h = self.sw = self.cx = self.y = 0
        self.rect_id = None


def build_vtree(node, role="", counter=None):
    counter = counter or itertools.count()
    label, detail, kids = describe(node)
    v = VNode(label, detail, KIND_OF.get(label, "other"), getattr(node, "line", 0) or None, role, next(counter))
    v.children = [build_vtree(c, r, counter) for r, c in kids]   # pre-order numbering: parents come first
    return v


def count_desc(n):
    return sum(1 + count_desc(c) for c in n.children)


class ScrubBar(tk.Canvas):
    """A slider that matches the theme: accent progress line with a glowing handle."""

    def __init__(self, master, command):
        super().__init__(master, height=26, bg=PANEL2, highlightthickness=0, cursor="hand2")
        self.command, self.to, self.value = command, 1.0, 0.0
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Button-1>", self._drag)
        self.bind("<B1-Motion>", self._drag)

    def set(self, value, to=None):
        self.value = value
        if to:
            self.to = float(to)
        self._draw()

    def _draw(self):
        self.delete("all")
        w, mid = max(self.winfo_width(), 40), 13
        x = 10 + (w - 20) * (self.value / self.to if self.to else 0)
        self.create_line(10, mid, w - 10, mid, fill=LINE, width=4, capstyle="round")
        self.create_line(10, mid, x, mid, fill=ACCENT, width=4, capstyle="round")
        if GLOW:
            self.create_oval(x - 10, mid - 10, x + 10, mid + 10, outline=blend(ACCENT, PANEL2, 0.3), width=3)
        self.create_oval(x - 6, mid - 6, x + 6, mid + 6, fill=ACCENT, outline="")

    def _drag(self, e):
        w = max(self.winfo_width(), 40)
        v = min(1.0, max(0.0, (e.x - 10) / (w - 20))) * self.to
        self.value = v
        self._draw()
        self.command(v)


def _partial(pts, f):
    """The first fraction f of a polyline (used to grow an edge from its parent)."""
    segs = list(zip(pts, pts[1:]))
    lens = [math.hypot(q[0] - p[0], q[1] - p[1]) for p, q in segs]
    goal, acc, out = sum(lens) * f, 0.0, [pts[0]]
    for (p, q), ln in zip(segs, lens):
        if acc + ln <= goal:
            out.append(q)
            acc += ln
        else:
            r = (goal - acc) / ln if ln else 0
            out.append((p[0] + (q[0] - p[0]) * r, p[1] + (q[1] - p[1]) * r))
            break
    return out if len(out) > 1 else out + out


def _ease(a):                      # fast start, soft landing
    return 1 - (1 - a) ** 3


class TreeCanvas(tk.Frame):
    HGAP, LEVEL = 14, 84
    SPEEDS = (("0.5x", 1.2), ("1x", 2.6), ("2x", 5.5), ("4x", 11.0))

    def __init__(self, master, family, on_select):
        super().__init__(master, bg=BG)
        self.family, self.on_select = family, on_select
        self.root_node, self.zoom, self.selected = None, 1.0, None
        self.t, self.playing, self.speed, self.speed_name, self.auto = None, False, 2.6, "1x", True
        self._job, self._fonts, self._total, self._nodes = None, {}, 0, []
        self._f_name = tkfont.Font(family=family, size=10, weight="bold")
        self._f_det = tkfont.Font(family=family, size=9)

        bar = tk.Frame(self, bg=PANEL2)
        bar.pack(fill="x")
        for text, cmd in (("Fit", self.fit_button), ("+", lambda: self.set_zoom(1.2)), ("-", lambda: self.set_zoom(1 / 1.2)),
                          ("Expand", lambda: self.set_all(False)), ("Collapse", lambda: self.set_all(True)),
                          ("SVG", self.export_svg), ("JSON", self.export_json)):
            flat_button(bar, text, cmd).pack(side="left", padx=(8, 0), pady=6)

        pl = tk.Frame(self, bg=PANEL2)                       # player: play / scrub / speed
        pl.pack(fill="x", pady=(1, 0))
        self.play_btn = flat_button(pl, "Play", self.play_toggle, accent=True)
        self.play_btn.config(width=8)
        self.play_btn.pack(side="left", padx=8, pady=6)
        for name, v in reversed(self.SPEEDS):
            flat_button(pl, name, lambda n=name, v=v: self.set_speed(n, v)).pack(side="right", padx=(0, 6), pady=6)
        self.step_lbl = tk.Label(bar, text="", bg=PANEL2, fg=ACCENT, font=(family, 9), width=30, anchor="e")
        self.step_lbl.pack(side="right", padx=10)
        self.scale = ScrubBar(pl, self._on_scrub)
        self.scale.pack(side="left", fill="x", expand=True, padx=6)

        tk.Label(self, text="click a node: jump to its line    double-click: fold    wheel: zoom    drag: pan    "
                 "slider: scrub the build", bg=BG, fg=MUTED, font=("Segoe UI", 8), anchor="w"
                 ).pack(side="bottom", fill="x", padx=8)
        self.canvas = tk.Canvas(self, bg=PANEL, highlightthickness=1, highlightbackground=LINE)
        self.canvas.pack(fill="both", expand=True)
        c = self.canvas
        c.bind("<ButtonPress-1>", lambda e: c.scan_mark(e.x, e.y))
        c.bind("<B1-Motion>", lambda e: c.scan_dragto(e.x, e.y, gain=1))
        c.bind("<MouseWheel>", lambda e: self.set_zoom(1.1 if e.delta > 0 else 1 / 1.1))
        c.bind("<Button-4>", lambda e: self.set_zoom(1.1))
        c.bind("<Button-5>", lambda e: self.set_zoom(1 / 1.1))
        c.bind("<Configure>", lambda e: self.fit() if (self.auto and not self.playing) else None)
        c.bind("<ButtonPress-1>", self._press)                  # one handler for all nodes (fast with big trees)
        c.bind("<Double-Button-1>", self._double)
        c.bind("<B1-Motion>", self._drag)
        c.bind("<ButtonRelease-1>", lambda e: self._schedule_cull(0))
        self._wc, self._tagmap, self._cull, self._last = {}, {}, None, 0.0
        self.bind("<Destroy>", lambda e: self._stop() if e.widget is self else None)

    def font(self, size, bold=False):
        size = max(5, round(size * self.zoom))
        if (size, bold) not in self._fonts:
            self._fonts[(size, bold)] = tkfont.Font(family=self.family, size=size, weight="bold" if bold else "normal")
        return self._fonts[(size, bold)]

    def _text_w(self, font, text):
        """Text width with a cache - measuring fonts is slow, and labels repeat a lot."""
        key = (id(font), text)
        if key not in self._wc:
            self._wc[key] = font.measure(text)
        return self._wc[key]

    # ---- data
    def set_tree(self, ast):
        self._stop()
        self.root_node = build_vtree(ast) if ast is not None else None
        self.selected, self.t, self.auto = None, None, True
        self._nodes = []

        def flat(n):
            self._nodes.append(n)
            for k in n.children:
                flat(k)
        if self.root_node:
            flat(self.root_node)
        self._total = len(self._nodes)
        self._sync()
        if self.winfo_ismapped():                    # a hidden page is drawn when it is opened
            self.fit()

    def _stop(self):
        self.playing = False
        if self._job:
            self.after_cancel(self._job)
            self._job = None

    def _sync(self):
        """Keeps the play button, slider and caption in step with the animation state."""
        self.scale.set(float(self._total if self.t is None else min(self.t, self._total)), to=max(1, self._total))
        self.play_btn.config(text="Pause" if self.playing else "Play")
        if self.root_node is None:
            txt = ""
        elif self.t is None:
            txt = "%d nodes   (%s)" % (self._total, self.speed_name)
        else:
            i = min(int(self.t), self._total - 1)
            n = self._nodes[i]
            txt = ("%d/%d  %s %s" % (i + 1, self._total, n.label, n.detail.split("  :")[0])).strip()
        self.step_lbl.config(text=txt[:34])

    # ---- player
    def play_toggle(self):
        if self.root_node is None:
            return
        if self.playing:
            self._stop()
            self._sync()
            return
        if self.t is None or self.t >= self._total:
            self._unfold()
            self.t, self.auto = 0.0, True
            self.fit()
        self.playing, self._last = True, time.monotonic()
        self._frame()

    def play_from_start(self):
        """Always restarts the build animation (used after compile and on start-up)."""
        if self.root_node is None:
            return
        self._stop()
        self._unfold()
        self.t, self.auto, self.playing, self._last = 0.0, True, True, time.monotonic()
        self.fit()
        self._frame()

    def _frame(self):
        if not self.playing:
            return
        now = time.monotonic()                               # real time, so slow frames never slow the animation
        dt, self._last = min(0.25, now - self._last), now
        self.t += self.speed * max(1.0, self._total / 40.0) * dt      # big trees play faster
        if self.t >= self._total + 0.7:                      # last node has landed -> back to normal mode
            self.t, self.playing, self._job = None, False, None
            self.redraw()
            self._sync()
            return
        self.redraw()
        self._sync()
        self._job = self.after(33, self._frame)

    def _on_scrub(self, v):
        if self.root_node is None:
            return
        self._stop()
        self.t = float(v)
        self.redraw()
        self._sync()

    def set_speed(self, name, v):
        self.speed, self.speed_name = v, name
        self._sync()

    def _unfold(self):
        def walk(n):
            n.collapsed = False
            for k in n.children:
                walk(k)
        if self.root_node:
            walk(self.root_node)

    # ---- layout (unscaled units)
    def _kids(self, n):
        return [] if n.collapsed else n.children

    def _layout(self):
        def measure(n):
            n.w = max(self._text_w(self._f_name, n.label), self._text_w(self._f_det, n.detail) if n.detail else 0) + 22
            n.h = 50 if n.detail else 34
            kids = self._kids(n)
            for k in kids:
                measure(k)
            cw = sum(k.sw for k in kids) + self.HGAP * (len(kids) - 1) if kids else 0
            n.sw = max(n.w, cw)

        def place(n, x, y):
            kids = self._kids(n)
            n.cx, n.y = x + n.sw / 2, y
            cw = sum(k.sw for k in kids) + self.HGAP * (len(kids) - 1) if kids else 0
            cx = x + (n.sw - cw) / 2
            for k in kids:
                place(k, cx, y + self.LEVEL)
                cx += k.sw + self.HGAP
        measure(self.root_node)
        place(self.root_node, 0, 0)

    def _depth(self, n):
        return 1 + max((self._depth(k) for k in self._kids(n)), default=0)

    def _visible(self, n=None):
        n = n or self.root_node
        yield n
        for k in self._kids(n):
            yield from self._visible(k)

    # ---- drawing
    def redraw(self):
        c = self.canvas
        c.delete("all")
        self._tagmap = {}
        if self.root_node is None:
            c.create_text(max(c.winfo_width(), 300) / 2, max(c.winfo_height(), 200) / 2, fill=MUTED,
                          text="No syntax tree yet.\nPress F5 to compile.", font=(self.family, 12), justify="center")
            return
        self._layout()
        z, pad, t = self.zoom, 40, self.t
        big = self._total > 250                       # big tree: only draw what is on screen, no fancy effects
        fast = big or z < 0.45
        cw, ch = max(c.winfo_width(), 300), max(c.winfo_height(), 200)
        vx0, vy0, vx1, vy1 = c.canvasx(0) - 120, c.canvasy(0) - 120, c.canvasx(cw) + 120, c.canvasy(ch) + 120

        def off(x1, y1, x2, y2):
            return big and (x2 < vx0 or x1 > vx1 or y2 < vy0 or y1 > vy1)
        alpha = (lambda n: 1.0) if t is None else (lambda n: max(0.0, min(1.0, t - n.order)))
        nodes = [n for n in self._visible() if alpha(n) > 0]
        for n in nodes:                                                   # edges first
            for k in self._kids(n):
                a = alpha(k)
                if a <= 0:
                    continue
                x1, y1 = n.cx * z + pad, (n.y + n.h) * z + pad
                x2, y2 = k.cx * z + pad, k.y * z + pad
                if off(min(x1, x2), y1, max(x1, x2), y2):
                    continue
                ym = (y1 + y2) / 2
                seg = [(x1, y1), (x1, ym), (x2, ym), (x2, y2)] if a >= 1 else \
                    _partial([(x1, y1), (x1, ym), (x2, ym), (x2, y2)], _ease(a))
                flat = [v for pt in seg for v in pt]
                ecol = blend(KIND_COLORS[k.kind][1], PANEL, 0.55)
                if GLOW and not fast:
                    c.create_line(*flat, fill=blend(ecol, PANEL, 0.25), width=max(3, round(5 * z)))
                c.create_line(*flat, fill=ACCENT if a < 1 else ecol, width=max(1, round(1.6 * z)))
                if a < 1 and not fast:                                    # bright head of the growing edge
                    hx, hy = seg[-1]
                    c.create_oval(hx - 4 * z, hy - 4 * z, hx + 4 * z, hy + 4 * z, fill=ACCENT, outline="")
        text_ok = z >= (0.5 if big else 0.3)
        for n in nodes:
            a = alpha(n)
            e = _ease(a)
            fill, edge = KIND_COLORS[n.kind]
            sc = 1.0 if fast else 0.55 + 0.45 * e
            cx, cy = n.cx * z + pad, (n.y + n.h / 2) * z + pad
            hw, hh, r = n.w * z / 2 * sc, n.h * z / 2 * sc, 8 * z * sc
            x1, x2, y1, y2 = cx - hw, cx + hw, cy - hh, cy + hh
            if off(x1, y1, x2, y2):
                continue
            tag, sel = "n%d" % id(n), n is self.selected
            self._tagmap[tag] = n
            if fast:
                n.rect_id = c.create_rectangle(x1, y1, x2, y2, fill=fill, outline=ACCENT if sel else edge,
                                               width=2 if sel else 1, tags=(tag,))
                if text_ok:
                    if n.detail and z >= 0.65:
                        c.create_text(cx, y1 + 15 * z, text=n.label, fill=edge, font=self.font(10, True), tags=(tag,))
                        c.create_text(cx, y1 + 34 * z, text=n.detail, fill=TEXT, font=self.font(9), tags=(tag,))
                    else:
                        c.create_text(cx, cy, text=n.label, fill=edge, font=self.font(10, True), tags=(tag,))
                if n.collapsed and n.children:
                    c.create_text(x2 - 2, y2 + 8, text="+%d" % count_desc(n), fill=ACCENT, anchor="e",
                                  font=self.font(9, True), tags=(tag,))
                continue

            def rounded(grow=0.0, _x1=x1, _x2=x2, _y1=y1, _y2=y2, _r=r):
                g = grow
                l, rt, tp, bt = _x1 - g, _x2 + g, _y1 - g, _y2 + g
                return [l + _r, tp, rt - _r, tp, rt, tp, rt, tp + _r, rt, bt - _r, rt, bt, rt - _r, bt, l + _r, bt,
                        l, bt, l, bt - _r, l, tp + _r, l, tp]
            if GLOW:
                for grow, f in ((7 * z, 0.10), (4 * z, 0.20), (2 * z, 0.38)):
                    c.create_polygon(rounded(grow), smooth=True, fill="", outline=blend(edge, PANEL, f), width=2 * z + 1)
            if a < 1:                                                      # arrival flash
                c.create_polygon(rounded((6 + 14 * (1 - e)) * z), smooth=True, fill="",
                                 outline=blend(ACCENT, PANEL, 0.12 + 0.5 * (1 - e)), width=max(2, 3 * z))
            n.rect_id = c.create_polygon(rounded(), smooth=True, fill=fill, outline=ACCENT if sel else edge,
                                         width=2.5 if sel else 1.3, tags=(tag,))
            if a >= 0.55:
                if n.detail:
                    c.create_text(cx, y1 + 15 * z * sc, text=n.label, fill=edge, font=self.font(10, True), tags=(tag,))
                    c.create_text(cx, y1 + 34 * z * sc, text=n.detail, fill=TEXT, font=self.font(9), tags=(tag,))
                else:
                    c.create_text(cx, cy, text=n.label, fill=edge, font=self.font(10, True), tags=(tag,))
            if n.role and n is not self.root_node and a >= 0.8:
                c.create_text(cx, y1 - 9 * z, text=n.role, fill=MUTED, font=self.font(8))
            if n.collapsed and n.children:
                c.create_text(x2 - 4 * z, y2 + 10 * z, text="+%d" % count_desc(n), fill=ACCENT,
                              font=self.font(9, True), anchor="e", tags=(tag,))
        if big and not text_ok:
            c.create_text(c.canvasx(12), c.canvasy(10), anchor="nw", fill=ACCENT, font=(self.family, 10, "bold"),
                          text="Large tree (%d nodes): zoom in with the wheel to read the names, drag to move around."
                               % self._total)
        w = self.root_node.sw * z + 2 * pad
        h = self._depth(self.root_node) * self.LEVEL * z + pad
        c.config(scrollregion=(0, 0, max(w, cw), max(h, ch)))

    # ---- mouse (one handler for the whole canvas instead of three bindings per node)
    def _node_at(self):
        c = self.canvas
        for it in c.find_withtag("current"):
            for tg in c.gettags(it):
                if tg in self._tagmap:
                    return self._tagmap[tg]
        return None

    def _press(self, e):
        self.canvas.scan_mark(e.x, e.y)
        n = self._node_at()
        if n is not None:
            self._click(n)

    def _double(self, e):
        n = self._node_at()
        if n is not None:
            self._toggle(n)

    def _drag(self, e):
        self.canvas.scan_dragto(e.x, e.y, gain=1)
        self._schedule_cull()

    def _schedule_cull(self, delay=70):
        """Big trees only draw what is visible, so panning needs a (throttled) redraw."""
        if self._total > 250 and self._cull is None:
            self._cull = self.after(delay, self._do_cull)

    def _do_cull(self):
        self._cull = None
        if self.root_node is not None and not self.playing:
            self.redraw()

    def _click(self, n):
        old, self.selected = self.selected, n
        if old is not None and old.rect_id:
            self.canvas.itemconfig(old.rect_id, outline=KIND_COLORS[old.kind][1], width=1.3)
        if n.rect_id:
            self.canvas.itemconfig(n.rect_id, outline=ACCENT, width=2.5)
        self.on_select(n.line)

    def _toggle(self, n):
        if n.children:
            self._stop()
            self.t = None
            n.collapsed = not n.collapsed
            self._sync()
            self.redraw()

    def set_all(self, collapsed):
        if self.root_node is None:
            return
        self._stop()
        self.t = None

        def walk(n, top):
            if n.children:
                n.collapsed = collapsed and not top
            for k in n.children:
                walk(k, False)
        walk(self.root_node, True)
        self._sync()
        self.redraw()

    def set_zoom(self, factor):
        self.auto = False
        self.zoom = min(3.0, max(0.25, self.zoom * factor))
        self.redraw()

    def fit_button(self):
        self._stop()
        self.t, self.auto = None, True
        self._sync()
        self.fit()

    def fit(self):
        if self.root_node is None:
            self.redraw()
            return
        self._layout()
        cw, ch = max(self.canvas.winfo_width(), 300), max(self.canvas.winfo_height(), 200)
        w, h = self.root_node.sw, self._depth(self.root_node) * self.LEVEL
        self.zoom = max(0.25, min(1.4, (cw - 90) / w, (ch - 70) / h))     # 40px padding on each side stays unscaled
        self.redraw()
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)

    def export_json(self):
        """Saves the tree as JSON (handy for reports or other tools)."""
        if self.root_node is None:
            return
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
        if not path:
            return

        def conv(n):
            d = {"node": n.label}
            if n.role:
                d["role"] = n.role
            if n.detail:
                d["detail"] = n.detail
            if n.line:
                d["line"] = n.line
            if n.children:
                d["children"] = [conv(k) for k in n.children]
            return d
        with open(path, "w", encoding="utf-8") as f:
            json.dump(conv(self.root_node), f, indent=2, ensure_ascii=False)

    def export_svg(self):
        if self.root_node is None:
            return
        path = filedialog.asksaveasfilename(defaultextension=".svg", filetypes=[("SVG image", "*.svg")])
        if not path:
            return
        self._layout()
        pad = 30
        W, H = self.root_node.sw + 2 * pad, self._depth(self.root_node) * self.LEVEL + 2 * pad
        esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        out = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" font-family="Consolas, monospace">'
               % (W, H), '<rect width="100%%" height="100%%" fill="%s"/>' % PANEL]
        for n in self._visible():
            for k in self._kids(n):
                ym = (n.y + n.h + k.y) / 2
                out.append('<polyline points="%.0f,%.0f %.0f,%.0f %.0f,%.0f %.0f,%.0f" fill="none" stroke="%s" '
                           'stroke-width="1.5"/>' % (n.cx + pad, n.y + n.h + pad, n.cx + pad, ym + pad,
                                                     k.cx + pad, ym + pad, k.cx + pad, k.y + pad, LINE))
        for n in self._visible():
            fill, edge = KIND_COLORS[n.kind]
            x, y = n.cx - n.w / 2 + pad, n.y + pad
            out.append('<rect x="%.0f" y="%.0f" width="%.0f" height="%.0f" rx="8" fill="%s" stroke="%s"/>'
                       % (x, y, n.w, n.h, fill, edge))
            if n.detail:
                out.append('<text x="%.0f" y="%.0f" fill="%s" font-size="12" font-weight="bold" text-anchor="middle">'
                           '%s</text>' % (n.cx + pad, y + 18, edge, esc(n.label)))
                out.append('<text x="%.0f" y="%.0f" fill="%s" font-size="11" text-anchor="middle">%s</text>'
                           % (n.cx + pad, y + 38, TEXT, esc(n.detail)))
            else:
                out.append('<text x="%.0f" y="%.0f" fill="%s" font-size="12" font-weight="bold" text-anchor="middle">'
                           '%s</text>' % (n.cx + pad, y + n.h / 2 + 4, edge, esc(n.label)))
        out.append("</svg>")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(out))


# ---------------------------------------------------------------- control-flow graph view
class FlowCanvas(tk.Frame):
    def __init__(self, master, family):
        super().__init__(master, bg=BG)
        self.family, self.showing_optimized = family, True
        self.on_toggle = None
        self.pos, self.W, self.total_h = {}, 0, 1
        self._blocks, self._dirty = [], False
        bar = tk.Frame(self, bg=PANEL2)
        bar.pack(fill="x")
        self.toggle = flat_button(bar, "Showing: optimized", self._toggle)
        self.toggle.pack(side="left", padx=8, pady=6)
        tk.Label(bar, text="green = condition true, red = false, grey = fall through / jump",
                 bg=PANEL2, fg=MUTED, font=("Segoe UI", 8)).pack(side="right", padx=10)
        self.canvas = tk.Canvas(self, bg=PANEL, highlightthickness=1, highlightbackground=LINE)
        self.canvas.pack(fill="both", expand=True)
        c = self.canvas
        c.bind("<ButtonPress-1>", lambda e: c.scan_mark(e.x, e.y))
        c.bind("<B1-Motion>", lambda e: c.scan_dragto(e.x, e.y, gain=1))
        c.bind("<MouseWheel>", lambda e: c.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        c.bind("<Button-4>", lambda e: c.yview_scroll(-1, "units"))
        c.bind("<Button-5>", lambda e: c.yview_scroll(1, "units"))

    def _toggle(self):
        self.showing_optimized = not self.showing_optimized
        self.toggle.config(text="Showing: optimized" if self.showing_optimized else "Showing: original")
        if self.on_toggle:
            self.on_toggle()

    def show(self, blocks):
        self._blocks, self._dirty = blocks, True
        if self.winfo_ismapped():
            self.refresh()

    def refresh(self):
        """Draws the graph when the page is actually visible."""
        if self._dirty:
            self._dirty = False
            self._render(self._blocks)

    def _render(self, blocks):
        c = self.canvas
        c.delete("all")
        if not blocks:
            c.create_text(300, 120, text="No flow graph yet.\nCompile a valid program first.", fill=MUTED,
                          font=(self.family, 12), justify="center")
            return
        f, lh = tkfont.Font(family=self.family, size=10), 18
        lines = {b.id: [str(i) for i in b.instrs] for b in blocks}
        W = max(len(t) for ls in lines.values() for t in ls) * f.measure("0") + 36     # monospace font
        x0, y, pos = 80, 36, {}
        for b in blocks:
            h = len(lines[b.id]) * lh + 18
            pos[b.id] = (x0, y, h)
            y += h + 46
        # boxes
        for b in blocks:
            bx, by, bh = pos[b.id]
            c.create_rectangle(bx, by, bx + W, by + bh, fill=BG, outline=LINE, width=1.5)
            c.create_text(bx - 10, by + 10, text="B%d" % b.id, anchor="e", fill=MUTED, font=(self.family, 9, "bold"))
            for k, ins in enumerate(b.instrs):
                col = ACCENT if ins.op == "label" else SAND if ins.op in ("jump", "ifFalse", "ifTrue") \
                    else PLUM if ins.op == "print" else TEXT
                c.create_text(bx + 14, by + 9 + lh * k + lh / 2, text=str(ins), anchor="w", fill=col, font=f)
        # edges
        lane = 0
        colors = {"true": GREEN, "false": RED, "": MUTED}
        for b in blocks:
            bx, by, bh = pos[b.id]
            for tgt, kind in b.succ:
                tx, ty, th = pos[tgt]
                col = colors[kind]
                if tgt == b.id + 1:
                    c.create_line(bx + W / 2, by + bh, bx + W / 2, ty, fill=col, width=2, arrow="last")
                    if kind:
                        c.create_text(bx + W / 2 + 8, by + bh + 14, text=kind, anchor="w", fill=col,
                                      font=(self.family, 8))
                else:
                    lx = bx + W + 26 + lane * 16
                    lane += 1
                    ys, yd = by + bh - 10, ty + 14
                    c.create_line(bx + W, ys, lx, ys, lx, yd, bx + W, yd, fill=col, width=2, arrow="last")
                    if kind:
                        c.create_text(bx + W + 6, ys - 8, text=kind, anchor="w", fill=col, font=(self.family, 8))
        self.pos, self.W, self.total_h = pos, W, y + 30
        c.config(scrollregion=(0, 0, x0 + W + 60 + lane * 16, y + 30))
        c.xview_moveto(0)
        c.yview_moveto(0)

    def mark(self, current, counts):
        """Overlay for the debugger: glow on the block being executed, a bar and 'xN' on visited blocks."""
        if self._dirty:
            return
        c = self.canvas
        c.delete("dyn")
        for bid, (x, y, h) in self.pos.items():
            n = counts.get(bid, 0)
            if n:
                c.create_rectangle(x, y, x + 4, y + h, fill=GREEN, outline="", tags="dyn")
                c.create_text(x + self.W - 8, y + 10, text="x%d" % n, anchor="e", fill=ACCENT,
                              font=(self.family, 9, "bold"), tags="dyn")
        if current in self.pos:
            x, y, h = self.pos[current]
            for grow, f in ((9, 0.12), (6, 0.25), (3, 0.5)):
                c.create_rectangle(x - grow, y - grow, x + self.W + grow, y + h + grow,
                                   outline=blend(ACCENT, PANEL, f), width=2, tags="dyn")
            c.create_rectangle(x, y, x + self.W, y + h, outline=ACCENT, width=3, tags="dyn")
            if y < c.canvasy(0) or y + h > c.canvasy(c.winfo_height()):
                c.yview_moveto(max(0.0, (y - 60) / max(1, self.total_h)))


# ---------------------------------------------------------------- error recovery view
def _round_pts(x1, y1, x2, y2, r):
    return [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
            x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]


class RecoveryView(tk.Frame):
    """Compares the three error-handling strategies and replays what the chosen one did to the tokens."""
    SPEEDS = (("1x", 3.5), ("2x", 7.0), ("4x", 14.0))

    def __init__(self, master, family, on_pick, on_option=None):
        super().__init__(master, bg=BG)
        self.family, self.on_pick, self.on_option = family, on_pick, on_option
        self.f = tkfont.Font(family=family, size=10, weight="bold")
        self.items, self.t, self.playing, self.speed, self._job = [], None, False, 7.0, None
        self.result = self.compare = None
        self.strategy = "phrase"
        self._sel, self._dirty, self._wc, self._cull = None, False, {}, None

        self.opts_row = tk.Frame(self, bg=PANEL2)               # phrase-level repair settings
        self.opts_row.pack(fill="x", pady=(0, 6))
        self.cards = tk.Frame(self, bg=BG)
        self.cards.pack(fill="x", pady=(0, 6))
        self.note = tk.Label(self, text="", bg=BG, fg=MUTED, font=("Segoe UI", 9), anchor="w", justify="left",
                             wraplength=640)
        self.note.pack(fill="x", padx=4, pady=(0, 4))
        bar = tk.Frame(self, bg=PANEL2)
        bar.pack(fill="x")
        flat_button(bar, "Replay", self.play_from_start, accent=True).pack(side="left", padx=8, pady=6)
        for name, v in self.SPEEDS:
            flat_button(bar, name, lambda v=v: self.set_speed(v)).pack(side="left", padx=(0, 6), pady=6)
        for text, color in (("replaced", GREEN), ("inserted", ACCENT), ("skipped", RED), ("error", RED)):
            tk.Label(bar, text="\u25CF " + text, bg=PANEL2, fg=color, font=("Segoe UI", 8)).pack(side="right", padx=6)
        self.canvas = tk.Canvas(self, bg=PANEL, highlightthickness=1, highlightbackground=LINE, height=150)
        self.canvas.pack(fill="both", expand=True)
        c = self.canvas
        c.bind("<ButtonPress-1>", lambda e: c.scan_mark(e.x, e.y))
        c.bind("<B1-Motion>", lambda e: c.scan_dragto(e.x, e.y, gain=1))
        c.bind("<MouseWheel>", lambda e: c.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        c.bind("<MouseWheel>", lambda e: (c.yview_scroll(-1 if e.delta > 0 else 1, "units"), self._schedule()))
        c.bind("<B1-Motion>", lambda e: (c.scan_dragto(e.x, e.y, gain=1), self._schedule()))
        c.bind("<ButtonRelease-1>", lambda e: self._schedule(0))
        self.log = tk.Text(self, bg=PANEL, fg=TEXT, relief="flat", font=(family, 10), height=8, width=10, padx=10,
                           pady=6, state="disabled", highlightthickness=1, highlightbackground=LINE, wrap="word")
        self.log.pack(fill="x", pady=(6, 0))
        for tag, color in (("pos", MUTED), ("msg", TEXT), ("fix", GREEN), ("dim", MUTED)):
            self.log.tag_config(tag, foreground=color)
        self.bind("<Destroy>", lambda e: self._stop() if e.widget is self else None)

    # ---- content
    def _opt_button(self, parent, text, on, cmd):
        b = tk.Label(parent, text=text, padx=8, pady=3, cursor="hand2", font=("Segoe UI", 9, "bold" if on else "normal"),
                     bg=ACCENT if on else PANEL, fg=ON_ACCENT if on else TEXT, highlightthickness=1,
                     highlightbackground=ACCENT if on else LINE)
        b.bind("<Button-1>", lambda e: cmd())
        b.pack(side="left", padx=(0, 5))

    def _build_repair_options(self, rep, active):
        """Checkboxes for every local repair + the operator an '=' inside a condition becomes."""
        for w in self.opts_row.winfo_children():
            w.destroy()
        r1, r2 = tk.Frame(self.opts_row, bg=PANEL2), tk.Frame(self.opts_row, bg=PANEL2)
        r1.pack(fill="x", padx=8, pady=(6, 3))
        r2.pack(fill="x", padx=8, pady=(0, 6))
        tk.Label(r1, text="Phrase-level repairs:" if active else "Phrase-level repairs (used by Phrase-level only):",
                 bg=PANEL2, fg=TEXT if active else MUTED, font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 8))
        for key, text in (("keywords", "fix keywords"), ("insert", "insert ; ) ( ="), ("delete", "delete stray ; ) }"),
                          ("operators", "fix = / ==")):
            on = getattr(rep, key)
            self._opt_button(r1, ("\u2713 " if on else "") + text, on, lambda k=key, v=on: self.on_option(k, not v))
        tk.Label(r2, text="'=' inside a condition becomes:", bg=PANEL2, fg=TEXT if active else MUTED,
                 font=("Segoe UI", 9)).pack(side="left", padx=(0, 8))
        for op in COMPARE_OPS:
            self._opt_button(r2, op, rep.compare_op == op, lambda o=op: self.on_option("compare_op", o))

    def show(self, r, compare, strategy, repairs=None):
        self._stop()
        self.t, self.result, self.compare, self.strategy = None, r, compare, strategy
        if repairs is not None:
            self._build_repair_options(repairs, strategy == "phrase")
        for w in self.cards.winfo_children():
            w.destroy()
        if compare is None:
            self.note.config(text="Fix the lexical errors first - the parser only runs on a clean stream of tokens.")
            self.items, self._dirty = [], False
            self._write_log(None)
            self._draw()
            return
        for res in compare:
            self._card(res, res.key == strategy)
        sel = next(x for x in compare if x.key == strategy)
        if any(x.errors for x in compare):
            self.note.config(text=STRATEGY_BLURB[strategy])
        else:
            self.note.config(text="No syntax errors, so no recovery was needed. Load Samples > "
                                  "12 Errors: recovery demo to see the strategies at work.")
        self._sel, self._dirty = sel, True
        if self.winfo_ismapped():                    # hidden pages are prepared when they are opened
            self._ensure()
            self._draw()

    def _ensure(self):
        if self._dirty and self._sel is not None:
            self._dirty = False
            self.items = build_items(self.result.tokens, self._sel.events)
            self._layout()
            self._write_log(self._sel)

    def _schedule(self, delay=70):
        if len(self.items) > 300 and self._cull is None:
            self._cull = self.after(delay, self._do_cull)

    def _do_cull(self):
        self._cull = None
        if not self.playing:
            self._draw()

    def _card(self, res, selected):
        card = tk.Frame(self.cards, bg=PANEL, cursor="hand2", highlightthickness=2 if selected else 1,
                        highlightbackground=ACCENT if selected else LINE)
        card.pack(side="left", fill="both", expand=True, padx=3)
        n = len(res.errors)
        lines = [(res.name, ("Segoe UI", 10, "bold"), ACCENT if selected else TEXT),
                 ("%d error%s" % (n, "" if n == 1 else "s"), ("Segoe UI", 17, "bold"), RED if n else GREEN),
                 ("%d statements kept  -  %d nodes" % (res.statements, res.nodes), ("Segoe UI", 9), TEXT),
                 ("skip %d  -  add %d  -  fix %d" % (res.skipped, res.inserted, res.replaced),
                  ("Segoe UI", 9), MUTED)]
        widgets = [card]
        for text, font, color in lines:
            lbl = tk.Label(card, text=text, bg=PANEL, fg=color, font=font, anchor="w", justify="left")
            lbl.pack(fill="x", padx=10, pady=(6 if font[1] == 10 else 0, 0))
            widgets.append(lbl)
        tk.Frame(card, bg=PANEL, height=8).pack()
        for w in widgets:
            w.bind("<Button-1>", lambda e, k=res.key: self.on_pick(k))

    def _write_log(self, res):
        lg = self.log
        lg.config(state="normal")
        lg.delete("1.0", "end")
        if res is None:
            lg.insert("end", "No parser run.", "dim")
        elif not res.errors:
            lg.insert("end", "No syntax errors.", "dim")
        for e in (res.errors if res else []):
            lg.insert("end", "line %d, col %d   " % (e.line, e.column), "pos")
            lg.insert("end", e.message + "\n", "msg")
            fix = res.fixes.get((e.line, e.column, e.message))
            if fix:
                lg.insert("end", "      -> " + fix + "\n", "fix")
        if res is not None and res.halted:
            lg.insert("end", "\nParsing stopped here: the rest of the program was never read.", "dim")
        lg.config(state="disabled")

    # ---- layout and drawing
    def _layout(self):
        lines = sorted({it["row"] for it in self.items})
        ridx = {l: i for i, l in enumerate(lines)}
        cursor = {l: 44 for l in lines}
        for it in self.items:
            it["label"] = it["text"] if not it.get("new") else "%s > %s" % (it["text"], it["new"].strip("'"))
            if it["label"] not in self._wc:
                self._wc[it["label"]] = self.f.measure(it["label"])
            it["w"] = self._wc[it["label"]] + 18
            it["x"], it["y"] = cursor[it["row"]], 16 + ridx[it["row"]] * 46
            cursor[it["row"]] += it["w"] + 8
        self.lines, self.ridx = lines, ridx
        self.extent = (max(cursor.values(), default=100) + 30, 16 + len(lines) * 46 + 20)

    def _draw(self):
        c = self.canvas
        c.delete("all")
        if not self.items:
            c.create_text(200, 60, text="Nothing to show yet.", fill=MUTED, font=(self.family, 11))
            return
        t = self.t
        fast = len(self.items) > 300                      # long program: draw only what is visible, no effects
        cw, ch = max(c.winfo_width(), 300), max(c.winfo_height(), 100)
        vx0, vy0, vx1, vy1 = c.canvasx(0) - 60, c.canvasy(0) - 60, c.canvasx(cw) + 60, c.canvasy(ch) + 60
        for l in self.lines:
            y = 16 + self.ridx[l] * 46
            if fast and (y + 28 < vy0 or y > vy1):
                continue
            c.create_text(12, y + 14, text=str(l), anchor="w", fill=MUTED, font=(self.family, 9))
        cur = None if t is None else min(int(t), len(self.items) - 1)
        for k, it in enumerate(self.items):
            age = 9.0 if t is None else t - k
            if age <= 0:
                continue
            if fast and (it["y"] + 30 < vy0 or it["y"] - 10 > vy1 or it["x"] + it["w"] < vx0 or it["x"] > vx1):
                continue
            e = _ease(min(1.0, age))
            sc = 1.0 if fast else 0.6 + 0.4 * e
            w, h = it["w"] * sc, 28 * sc
            cx, cy = it["x"] + it["w"] / 2, it["y"] + 14
            x1, x2, y1, y2 = cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2
            col, dash, strike, ring = TOKEN_COLORS.get(it.get("cat", "punct"), MUTED), None, False, None
            state = it.get("state", "ok")
            if it["kind"] == "ins":
                fill, edge, txt, dash = blend(ACCENT, PANEL, 0.2), ACCENT, ACCENT, (4, 3)
            elif state in ("skipped", "deleted"):
                if age >= 1.4:
                    fill, edge, txt, strike = blend(RED, PANEL, 0.10), blend(RED, PANEL, 0.45), MUTED, True
                else:
                    fill, edge, txt, ring = blend(col, PANEL, 0.16), col, col, RED
            elif state == "replaced":
                fill, edge, txt = blend(GREEN, PANEL, 0.18), GREEN, GREEN
            elif state == "unread":
                fill, edge, txt, dash = PANEL, LINE, blend(MUTED, PANEL, 0.6), (2, 3)
            else:
                fill, edge, txt = blend(col, PANEL, 0.16), col, col
            if fast:
                c.create_rectangle(x1, y1, x2, y2, fill=fill, outline=RED if it.get("err") else edge,
                                   width=2 if it.get("err") else 1, dash=dash)
            else:
                if GLOW and not strike and state != "unread":
                    c.create_polygon(_round_pts(x1 - 3, y1 - 3, x2 + 3, y2 + 3, 9), smooth=True, fill="",
                                     outline=blend(edge, PANEL, 0.22), width=3)
                if it.get("err"):
                    c.create_polygon(_round_pts(x1 - 5, y1 - 5, x2 + 5, y2 + 5, 10), smooth=True, fill="",
                                     outline=RED, width=2)
                if ring or age < 1.0:                                   # arrival flash
                    flash = blend(ring or ACCENT, PANEL, 0.15 + 0.5 * (1 - e))
                    c.create_polygon(_round_pts(x1 - 8, y1 - 8, x2 + 8, y2 + 8, 12), smooth=True, fill="",
                                     outline=flash, width=3)
                c.create_polygon(_round_pts(x1, y1, x2, y2, 8), smooth=True, fill=fill, outline=edge, width=1.4,
                                 dash=dash)
            if age >= 0.5:
                c.create_text(cx, cy, text=it["label"], fill=txt, font=self.f)
            if strike:
                c.create_line(x1 + 5, cy, x2 - 5, cy, fill=RED, width=2)
            if k == cur and self.playing:                               # cursor
                c.create_polygon(cx - 5, y1 - 11, cx + 5, y1 - 11, cx, y1 - 4, fill=ACCENT, outline="")
        c.config(scrollregion=(0, 0, self.extent[0], self.extent[1]))

    # ---- player
    def _stop(self):
        self.playing = False
        if self._job:
            self.after_cancel(self._job)
            self._job = None

    def set_speed(self, v):
        self.speed = v

    def play_from_start(self, auto=False):
        self._ensure()
        if not self.items:
            return
        self._stop()
        if auto and len(self.items) > 300:                # long programs: show the result, Replay plays it
            self.t = None
            self._draw()
            return
        self.t, self.playing, self._last = 0.0, True, time.monotonic()
        self.canvas.xview_moveto(0)
        self._frame()

    def _frame(self):
        if not self.playing:
            return
        now = time.monotonic()
        dt, self._last = min(0.25, now - self._last), now
        self.t += self.speed * max(1.0, len(self.items) / 40.0) * dt
        if self.t >= len(self.items) + 1.6:
            self.t, self.playing, self._job = None, False, None
            self._draw()
            return
        self._draw()
        k = min(int(self.t), len(self.items) - 1)
        it = self.items[k]
        right = self.canvas.canvasx(self.canvas.winfo_width())
        if it["x"] + it["w"] > right - 20:                                # follow the cursor
            self.canvas.xview_moveto(max(0.0, (it["x"] - 120) / max(1, self.extent[0])))
        self._job = self.after(33, self._frame)


# ---------------------------------------------------------------- sidebar entry
class NavItem(tk.Frame):
    def __init__(self, master, text, command):
        super().__init__(master, bg=SIDEBAR, cursor="hand2")
        self.command, self.active = command, False
        self.bar = tk.Frame(self, width=3, bg=SIDEBAR)
        self.bar.pack(side="left", fill="y")
        self.dot = tk.Canvas(self, width=14, height=14, bg=SIDEBAR, highlightthickness=0)
        self.dot.pack(side="left", padx=(12, 8), pady=10)
        self.oval = self.dot.create_oval(3, 3, 11, 11, fill=MUTED, outline="")
        self.label = tk.Label(self, text=text, bg=SIDEBAR, fg=TEXT, font=("Segoe UI", 10), anchor="w")
        self.label.pack(side="left", fill="x", expand=True)
        for w in (self, self.dot, self.label, self.bar):
            w.bind("<Button-1>", lambda e: self.command())
            w.bind("<Enter>", lambda e: self._paint(True))
            w.bind("<Leave>", lambda e: self._paint(False))

    def _paint(self, hover=False):
        bg = PANEL if self.active else HOVER if hover else SIDEBAR
        for w in (self, self.dot, self.label):
            w.config(bg=bg)
        self.bar.config(bg=ACCENT if self.active else bg)

    def set_active(self, on):
        self.active = on
        self._paint()

    def set_state(self, state):
        colors = {"idle": MUTED, "ok": GREEN, "fail": RED, "skip": blend(MUTED, SIDEBAR, 0.45)}
        self.dot.itemconfig(self.oval, fill=colors[state])


# ---------------------------------------------------------------- main window
class App(tk.Tk):
    PAGES = ["Tokens", "Syntax tree", "Symbol table", "Intermediate code", "Flow graph", "Run & debug", "Recovery",
             "Errors"]
    STAGE_OF = {"Tokens": "lexical", "Syntax tree": "syntax", "Symbol table": "semantic",
                "Intermediate code": "codegen", "Flow graph": "codegen", "Run & debug": "codegen"}

    def __init__(self, source=None, page=None, geometry=None):
        super().__init__()
        self.title("MiniLang Compiler")
        self.geometry(geometry or "1320x800")
        self.minsize(980, 700)
        self.configure(bg=BG)
        self.mono = pick_font(["Cascadia Code", "Cascadia Mono", "JetBrains Mono", "Consolas", "Menlo",
                               "DejaVu Sans Mono"])
        self.ed_font = tkfont.Font(family=self.mono, size=12)
        self.restart, self.keep = False, None
        self.strategy, self.compare, self._jobs = "phrase", None, []
        self.repairs = RepairOptions()
        self.result, self.machine, self.live, self._live_job = None, None, False, None
        self.run_optimized = True
        self.pc_block, self.block_start, self.block_counts, self.cur_block, self._prev_env = {}, {}, {}, None, {}
        self._style()
        self._build()
        self.editor.insert("1.0", source if source is not None else SAMPLES[0][1])
        self._highlight()
        self._gutter()
        self.bind("<F5>", lambda e: self.compile(True))
        self.bind("<Control-o>", lambda e: self.open_file())
        self.bind("<Control-s>", lambda e: self.save_file())
        self.bind("<F6>", lambda e: (self.show("Run & debug"), self.run_step()))
        self.compile()
        self.show(page or "Syntax tree")
        if (page or "Syntax tree") == "Syntax tree":
            self._later(600, self._autoplay)                          # little intro animation

    def _later(self, ms, fn):
        job = self.after(ms, fn)
        self._jobs.append(job)
        return job

    def destroy(self):
        for job in self._jobs:                       # no timer may fire after the window is gone (theme switch, exit)
            try:
                self.after_cancel(job)
            except tk.TclError:
                pass
        super().destroy()

    def _style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT, rowheight=26,
                    borderwidth=0, font=(self.mono, 10))
        s.configure("Treeview", bordercolor=PANEL, lightcolor=PANEL, darkcolor=PANEL)
        s.configure("Treeview.Heading", background=PANEL2, foreground=MUTED, relief="flat",
                    font=("Segoe UI", 9, "bold"))
        s.map("Treeview", background=[("selected", ROWSEL)], foreground=[("selected", TEXT)])
        s.map("Treeview.Heading", background=[("active", PANEL2)])
        s.configure("Vertical.TScrollbar", background=PANEL2, troughcolor=BG, bordercolor=BG, arrowcolor=MUTED)

    # ------------------------------------------------------------ layout
    def _build(self):
        side = tk.Frame(self, bg=SIDEBAR, width=214)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        tk.Label(side, text="MiniLang", bg=SIDEBAR, fg=ACCENT, font=("Segoe UI", 16, "bold"),
                 anchor="w").pack(fill="x", padx=18, pady=(18, 0))
        tk.Label(side, text="compiler workbench", bg=SIDEBAR, fg=MUTED, font=("Segoe UI", 9),
                 anchor="w").pack(fill="x", padx=18, pady=(0, 14))
        flat_button(side, "Compile   F5", lambda: self.compile(True), accent=True).pack(fill="x", padx=14, pady=(0, 6))
        row = tk.Frame(side, bg=SIDEBAR)
        row.pack(fill="x", padx=14, pady=(0, 6))
        self.samples_btn = flat_button(row, "Samples", self.pick_sample)
        self.samples_btn.pack(side="left", fill="x", expand=True)
        flat_button(row, "Open", self.open_file).pack(side="left", padx=(6, 0))
        flat_button(row, "Save", self.save_file).pack(side="left", padx=(6, 0))
        self.live_btn = flat_button(side, "Live compile: off", self.toggle_live)
        self.live_btn.pack(fill="x", padx=14, pady=(0, 6))
        self.strat_btn = flat_button(side, "Recovery: " + STRATEGY_NAMES[self.strategy], self.pick_strategy)
        self.strat_btn.pack(fill="x", padx=14, pady=(0, 16))
        tk.Label(side, text="STAGES", bg=SIDEBAR, fg=MUTED, font=("Segoe UI", 8, "bold"),
                 anchor="w").pack(fill="x", padx=18, pady=(0, 4))
        self.nav = {}
        for name in self.PAGES:
            item = NavItem(side, name, lambda n=name: self.show(n))
            item.pack(fill="x")
            self.nav[name] = item
        self.theme_btn = flat_button(side, "Theme: " + THEME_NAME + "  \u25B8 next", self.cycle_theme)
        self.theme_btn.pack(side="bottom", fill="x", padx=14, pady=(0, 14))
        self.status = tk.Label(side, text="Ready", bg=SIDEBAR, fg=MUTED, font=("Segoe UI", 9), anchor="w",
                               justify="left", wraplength=180)
        self.status.pack(side="bottom", fill="x", padx=18, pady=(14, 8))

        panes = tk.PanedWindow(self, orient="horizontal", bg=BG, sashwidth=5, sashrelief="flat", bd=0)
        panes.pack(side="left", fill="both", expand=True)

        left = tk.Frame(panes, bg=BG)
        tk.Label(left, text="SOURCE", bg=BG, fg=MUTED, font=("Segoe UI", 8, "bold"),
                 anchor="w").pack(fill="x", padx=12, pady=(10, 4))
        wrap = tk.Frame(left, bg=PANEL, highlightthickness=1, highlightbackground=LINE)
        wrap.pack(fill="both", expand=True, padx=(12, 4), pady=(0, 2))
        self.pos_label = tk.Label(left, text="Ln 1, Col 1", bg=BG, fg=MUTED, font=("Segoe UI", 8), anchor="e")
        self.pos_label.pack(fill="x", padx=(12, 6), pady=(0, 8))
        self.gutter = tk.Canvas(wrap, width=44, bg=PANEL, highlightthickness=0)
        self.gutter.pack(side="left", fill="y")
        self.editor = tk.Text(wrap, bg=PANEL, fg=TEXT, insertbackground=ACCENT, selectbackground=SEL,
                              relief="flat", font=self.ed_font, undo=True, wrap="none", padx=8, pady=6,
                              highlightthickness=0, width=10, height=10)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.editor.yview)
        self.editor.config(yscrollcommand=lambda a, b: (sb.set(a, b), self._gutter()))
        sb.pack(side="right", fill="y")
        self.editor.pack(side="left", fill="both", expand=True)
        for tag, color in (("kw", ACCENT), ("num", BLUE), ("str", GREEN), ("com", MUTED)):
            self.editor.tag_config(tag, foreground=color)
        self.editor.tag_config("errline", background=ERRBG)
        self.editor.tag_config("hl", background=HL)
        self.editor.tag_raise("sel")
        self.editor.bind("<KeyRelease>", self._on_key)
        self.editor.bind("<ButtonRelease-1>", lambda e: self._pos())
        self.editor.bind("<Return>", self._on_return)
        self.editor.bind("<Tab>", lambda e: (self.editor.insert("insert", "    "), "break")[1])
        for key, d in (("<Control-equal>", 1), ("<Control-plus>", 1), ("<Control-minus>", -1)):
            self.editor.bind(key, lambda e, d=d: (self._font_size(d), "break")[1])
        self.editor.bind("<MouseWheel>", lambda e: self.after_idle(self._gutter))
        panes.add(left, minsize=300, width=400)

        right = tk.Frame(panes, bg=BG)
        self.page_title = tk.Label(right, text="", bg=BG, fg=MUTED, font=("Segoe UI", 8, "bold"), anchor="w")
        self.page_title.pack(fill="x", padx=12, pady=(10, 4))
        self.stage = tk.Frame(right, bg=BG)
        self.stage.pack(fill="both", expand=True, padx=(8, 12), pady=(0, 12))
        panes.add(right, minsize=460)

        self.pages = {}
        self.tok_tree = self._table(["Type", "Lexeme", "Line", "Col"], (140, 150, 60, 60))
        for cat, color in TOKEN_COLORS.items():
            self.tok_tree.tag_configure(cat, foreground=color)
        self.pages["Tokens"] = self.tok_tree.master
        self.tree_view = TreeCanvas(self.stage, self.mono, self._jump_to_line)
        self.pages["Syntax tree"] = self.tree_view
        self.sym_tree = self._table(["Name", "Type", "Line", "Scope", "Has value", "Uses"], (130, 80, 60, 60, 90, 60))
        self.pages["Symbol table"] = self.sym_tree.master
        self._build_code_page()
        self.flow = FlowCanvas(self.stage, self.mono)
        self.flow.on_toggle = self._fill_flow
        self.pages["Flow graph"] = self.flow
        self._build_run_page()
        self.recovery = RecoveryView(self.stage, self.mono, self.set_strategy, self.set_repair)
        self.pages["Recovery"] = self.recovery
        self.err_tree = self._table(["Stage", "Line", "Col", "Message", "Recovery"], (70, 48, 42, 340, 170))
        self.err_tree.bind("<Double-1>", self._error_click)
        self.err_tree.bind("<<TreeviewSelect>>", self._error_select)
        self.err_detail = tk.Label(self.err_tree.master, text="Double-click an error to jump to its line.",
                                   bg=PANEL2, fg=TEXT, font=(self.mono, 10), anchor="w", justify="left",
                                   padx=12, pady=8, wraplength=560)
        self.err_detail.pack(side="bottom", fill="x")
        self.pages["Errors"] = self.err_tree.master

    def _table(self, cols, widths):
        frame = tk.Frame(self.stage, bg=PANEL, highlightthickness=1, highlightbackground=LINE)
        tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="browse")
        for c, w in zip(cols, widths):
            tree.heading(c, text=c)
            tree.column(c, width=w, anchor="w", stretch=(c in ("Message", "Lexeme")))
        sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        tree.pack(fill="both", expand=True)
        return tree

    def _code_text(self, parent):
        t = tk.Text(parent, bg=PANEL, fg=TEXT, relief="flat", font=(self.mono, 11), padx=12, pady=8,
                    state="disabled", highlightthickness=1, highlightbackground=LINE, highlightcolor=LINE, wrap="none",
                    width=10, height=10)
        t.tag_config("label", foreground=ACCENT)
        t.tag_config("jump", foreground=SAND)
        t.tag_config("print", foreground=PLUM)
        t.tag_config("dim", foreground=MUTED)
        t.tag_config("pc", background=HL)
        return t

    def _build_code_page(self):
        frame = tk.Frame(self.stage, bg=BG)
        heads = tk.Frame(frame, bg=BG)
        heads.pack(fill="x")
        self.orig_head = tk.Label(heads, text="ORIGINAL", bg=BG, fg=MUTED, font=("Segoe UI", 8, "bold"), anchor="w")
        self.orig_head.pack(side="left", expand=True, fill="x", padx=4)
        self.opt_head = tk.Label(heads, text="OPTIMIZED", bg=BG, fg=MUTED, font=("Segoe UI", 8, "bold"), anchor="w")
        self.opt_head.pack(side="left", expand=True, fill="x", padx=4)
        body = tk.Frame(frame, bg=BG)
        body.pack(fill="both", expand=True)
        self.code_orig = self._code_text(body)
        self.code_opt = self._code_text(body)
        self.code_orig.pack(side="left", fill="both", expand=True, padx=(0, 4))
        self.code_opt.pack(side="left", fill="both", expand=True)
        row = tk.Frame(frame, bg=PANEL2)
        row.pack(fill="x", pady=(6, 0))
        self.opt_stats = tk.Label(row, text="", bg=PANEL2, fg=TEXT, font=("Segoe UI", 9), anchor="w", padx=12, pady=6)
        self.opt_stats.pack(side="left", fill="x", expand=True)
        flat_button(row, "Save code...", self.save_code).pack(side="right", padx=6, pady=4)
        self.pages["Intermediate code"] = frame

    def _build_run_page(self):
        frame = tk.Frame(self.stage, bg=BG)
        bar = tk.Frame(frame, bg=PANEL2)
        bar.pack(fill="x")
        for text, cmd in (("Run", self.run_all), ("Step", self.run_step), ("Reset", self.run_reset)):
            flat_button(bar, text, cmd, accent=(text == "Run")).pack(side="left", padx=(8, 0), pady=6)
        self.src_btn = flat_button(bar, "Code: optimized", self.toggle_run_source)
        self.src_btn.pack(side="left", padx=(8, 0), pady=6)
        self.run_info = tk.Label(bar, text="", bg=PANEL2, fg=MUTED, font=("Segoe UI", 9))
        self.run_info.pack(side="right", padx=10)
        body = tk.PanedWindow(frame, orient="horizontal", bg=BG, sashwidth=4, bd=0)
        body.pack(fill="both", expand=True, pady=(6, 0))
        self.run_code = self._code_text(body)
        body.add(self.run_code, minsize=200, width=280)
        right = tk.Frame(body, bg=BG)
        tk.Label(right, text="VARIABLES", bg=BG, fg=MUTED, font=("Segoe UI", 8, "bold"), anchor="w").pack(fill="x")
        vframe = tk.Frame(right, bg=PANEL, highlightthickness=1, highlightbackground=LINE)
        vframe.pack(fill="both", expand=True)
        self.var_tree = ttk.Treeview(vframe, columns=("Name", "Value"), show="headings", height=8)
        self.var_tree.heading("Name", text="Name")
        self.var_tree.heading("Value", text="Value")
        self.var_tree.column("Name", width=110)
        self.var_tree.column("Value", width=160)
        self.var_tree.tag_configure("temp", foreground=MUTED)
        self.var_tree.tag_configure("changed", background=HL)
        self.var_tree.pack(fill="both", expand=True)
        tk.Label(right, text="OUTPUT", bg=BG, fg=MUTED, font=("Segoe UI", 8, "bold"), anchor="w").pack(fill="x", pady=(8, 0))
        self.out_text = tk.Text(right, bg=PANEL, fg=GREEN, relief="flat", font=(self.mono, 11), height=6, padx=10,
                                pady=6, state="disabled", highlightthickness=1, highlightbackground=LINE, highlightcolor=LINE,
                                width=10)
        self.out_text.tag_config("err", foreground=RED)
        self.out_text.pack(fill="both", expand=True)
        body.add(right, minsize=240)
        self.pages["Run & debug"] = frame

    def show(self, name):
        for p in self.pages.values():
            p.pack_forget()
        self.pages[name].pack(fill="both", expand=True)
        for n, item in self.nav.items():
            item.set_active(n == name)
        self.page_title.config(text=name.upper())
        self.current = name
        if name == "Syntax tree":
            self._later(30, self.tree_view.fit_button)
        elif name == "Recovery":
            self._later(80, lambda: self.recovery.play_from_start(True))
        elif name == "Flow graph":
            self.flow.refresh()
            self._mark_flow()

    # ------------------------------------------------------------ editor
    def _on_key(self, _):
        self._highlight()
        self._gutter()
        self._pos()
        if self.live:
            if self._live_job:
                self.after_cancel(self._live_job)
            self._live_job = self._later(500, self.compile)

    def _highlight(self):
        t = self.editor
        for tag in ("kw", "num", "str", "com"):
            t.tag_remove(tag, "1.0", "end")
        src = t.get("1.0", "end-1c")
        for tag, pat in (("num", r"\b\d+(?:\.\d+)?\b"),
                         ("kw", r"\b(?:int|float|string|bool|print|if|else|while|true|false)\b"),
                         ("str", r'"(?:\\.|[^"\\\n])*"'), ("com", r"//[^\n]*")):
            for m in re.finditer(pat, src):
                t.tag_add(tag, "1.0+%dc" % m.start(), "1.0+%dc" % m.end())

    def _gutter(self):
        g = self.gutter
        g.delete("all")
        i = self.editor.index("@0,0")
        while True:
            d = self.editor.dlineinfo(i)
            if d is None:
                break
            g.create_text(36, d[1] + d[3] / 2, text=i.split(".")[0], anchor="e", fill=MUTED, font=(self.mono, 10))
            nxt = self.editor.index("%s+1line" % i)
            if nxt == i:
                break
            i = nxt

    def _jump_to_line(self, line):
        if not line:
            return
        self.editor.tag_remove("hl", "1.0", "end")
        self.editor.tag_add("hl", "%d.0" % line, "%d.0lineend" % line)
        self.editor.see("%d.0" % line)

    def _set_source(self, text):
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", text)
        self._highlight()
        self._gutter()
        self.compile(True)

    def pick_sample(self):
        menu = tk.Menu(self, tearoff=0, bg=PANEL2, fg=TEXT, activebackground=ACCENT, activeforeground=ON_ACCENT, bd=0)
        for name, code in SAMPLES:
            menu.add_command(label=name, command=lambda c=code: self._set_source(c))
        b = self.samples_btn
        menu.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height())

    def open_file(self):
        path = filedialog.askopenfilename(filetypes=[("MiniLang", "*.ml"), ("All files", "*.*")])
        if path:
            with open(path, encoding="utf-8") as f:
                self._set_source(f.read())

    def save_file(self):
        path = filedialog.asksaveasfilename(defaultextension=".ml", filetypes=[("MiniLang", "*.ml")])
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.editor.get("1.0", "end-1c"))

    def _autoplay(self):
        if getattr(self, "current", "") == "Syntax tree" and self.tree_view._total <= 300:
            self.tree_view.play_from_start()                 # big trees are shown at once (Play still animates them)

    def save_code(self):
        r = self.result
        if r is None or r.stages.get("codegen") != "ok":
            return
        path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text", "*.txt")])
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write("// original\n" + "\n".join(r.intermediate_code))
                f.write("\n\n// optimized\n" + "\n".join(r.optimized_code) + "\n")

    def cycle_theme(self):
        names = list(THEMES)
        nxt = names[(names.index(THEME_NAME) + 1) % len(names)]
        apply_theme(nxt)
        try:
            with open(THEME_FILE, "w", encoding="utf-8") as f:
                f.write(nxt)
        except OSError:
            pass
        self.keep = (self.editor.get("1.0", "end-1c"), getattr(self, "current", None), self.geometry())
        self.restart = True
        self.destroy()                      # launch() builds the window again in the new colours

    def _pos(self):
        line, col = self.editor.index("insert").split(".")
        self.pos_label.config(text=f"Ln {line}, Col {int(col) + 1}")

    def _on_return(self, _):
        before = self.editor.get("insert linestart", "insert")
        indent = re.match(r"[ \t]*", before).group()
        if before.rstrip().endswith("{"):
            indent += "    "
        self.editor.insert("insert", "\n" + indent)
        self.editor.see("insert")
        self._on_key(None)
        return "break"

    def _font_size(self, delta):
        self.ed_font.configure(size=max(8, min(28, self.ed_font.cget("size") + delta)))
        self._gutter()

    def pick_strategy(self):
        menu = tk.Menu(self, tearoff=0, bg=PANEL2, fg=TEXT, activebackground=ACCENT, activeforeground=ON_ACCENT, bd=0)
        for key in STRATEGIES:
            menu.add_command(label=("\u2713  " if key == self.strategy else "     ") + STRATEGY_NAMES[key],
                             command=lambda k=key: self.set_strategy(k))
        b = self.strat_btn
        menu.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height())

    def set_strategy(self, key):
        """Chooses how the parser reacts to syntax errors, recompiles and replays the recovery."""
        self.strategy = key
        self.strat_btn.config(text="Recovery: " + STRATEGY_NAMES[key])
        self.compile()
        if getattr(self, "current", "") == "Recovery":
            self.recovery.play_from_start()

    def set_repair(self, field, value):
        """A phrase-level repair switch or the operator choice changed: recompile and replay."""
        setattr(self.repairs, field, value)
        self.compile()
        if getattr(self, "current", "") == "Recovery":
            self.recovery.play_from_start()

    def toggle_live(self):
        self.live = not self.live
        self.live_btn.config(text="Live compile: on" if self.live else "Live compile: off")

    # ------------------------------------------------------------ compile + fill pages
    def compile(self, animate=False):
        try:
            self._compile(animate)
        except Exception as exc:                          # never let an internal problem close the window
            import traceback
            traceback.print_exc()
            self.status.config(text="Internal error: %s" % exc, fg=RED)

    def _compile(self, animate=False):
        src = self.editor.get("1.0", "end-1c")
        r = compile_source(src, strategy=self.strategy, repairs=self.repairs)
        self.compare = compare_strategies(src, self.repairs)
        self.result = r
        self.editor.tag_remove("errline", "1.0", "end")
        self.editor.tag_remove("hl", "1.0", "end")
        self._fill_tokens(r)
        self.tree_view.set_tree(r.ast)
        self._fill_symbols(r)
        self._fill_code(r)
        self._fill_flow()
        self.run_reset()
        self._fill_errors(r)
        self.recovery.show(r, self.compare, self.strategy, self.repairs)
        self._set_status(r)
        cur = getattr(self, "current", "Syntax tree")
        if r.errors and cur not in ("Errors", "Recovery") and not self.live:   # stay on Recovery while experimenting
            self.show("Errors")
        elif r.success and cur == "Errors":
            self.show("Syntax tree")
        if animate and r.ast is not None and getattr(self, "current", "") == "Syntax tree":
            self._later(220, self._autoplay)                          # watch the tree being built
        elif animate and getattr(self, "current", "") == "Recovery":
            self._later(220, lambda: self.recovery.play_from_start(True))

    def _fill_tokens(self, r):
        self.tok_tree.delete(*self.tok_tree.get_children())
        for t in r.tokens:
            if t.type != TokenType.EOF:
                self.tok_tree.insert("", "end", values=(t.type.name, t.lexeme, t.line, t.column),
                                     tags=(token_category(t.type),))

    def _fill_symbols(self, r):
        self.sym_tree.delete(*self.sym_tree.get_children())
        if r.symbols is not None:
            for s in r.symbols.all():
                self.sym_tree.insert("", "end", values=(s.name, str(s.type), s.declared_line, s.scope,
                                                        "yes" if s.initialized else "no", s.uses))

    def _put_code(self, widget, instrs, empty_msg):
        widget.config(state="normal")
        widget.delete("1.0", "end")
        if instrs is None:
            widget.insert("end", empty_msg, "dim")
        for i, ins in enumerate(instrs or []):
            tag = ins.op if ins.op in ("label", "print") else "jump" if ins.op in ("jump", "ifFalse", "ifTrue") else ""
            widget.insert("end", "%3d  " % i, "dim")
            widget.insert("end", ("" if ins.op == "label" else "  ") + str(ins) + "\n", tag)
        widget.config(state="disabled")

    def _fill_code(self, r):
        ok = r.stages.get("codegen") == "ok"
        msg = "Not generated - fix the errors first."
        self._put_code(self.code_orig, r.instructions if ok else None, msg)
        self._put_code(self.code_opt, r.optimized if ok else None, msg)
        self.orig_head.config(text="ORIGINAL  (%d instructions)" % len(r.instructions) if ok else "ORIGINAL")
        self.opt_head.config(text="OPTIMIZED  (%d instructions)" % len(r.optimized) if ok else "OPTIMIZED")
        s = r.opt_stats
        self.opt_stats.config(text=("constants folded: %(folded)d     values propagated: %(propagated)d     "
                                    "branches decided: %(branches)d     instructions removed: %(removed)d" % s)
                              if ok and s else "")

    def _fill_flow(self):
        r = self.result
        if r is None:
            return
        self.flow.show(r.cfg if self.flow.showing_optimized else r.cfg_original)
        self._mark_flow()

    def _fill_errors(self, r):
        self.err_tree.delete(*self.err_tree.get_children())
        for e in r.errors:
            self.err_tree.insert("", "end", values=(e.stage, e.line, e.column, e.message,
                                                    r.fixes.get((e.line, e.column, e.message), "")))
            self.editor.tag_add("errline", "%d.0" % e.line, "%d.0lineend+1c" % e.line)

    def _error_select(self, _):
        sel = self.err_tree.selection()
        if sel:
            stage, line, col, msg, fixed = self.err_tree.item(sel[0], "values")
            lines = self.result.source.split("\n") if self.result else []
            ln, cn = int(line), int(col)
            text = f"{stage} error at line {ln}, column {cn}\n{msg}" + (f"\nRecovery: {fixed}" if fixed else "")
            if 0 < ln <= len(lines):
                text += f"\n\n{lines[ln - 1]}\n{' ' * (cn - 1)}^"
            self.err_detail.config(text=text)

    def _error_click(self, _):
        sel = self.err_tree.selection()
        if sel:
            self._jump_to_line(int(self.err_tree.item(sel[0], "values")[1]))

    def _set_status(self, r):
        for page, stage in self.STAGE_OF.items():
            self.nav[page].set_state(STATE_OF[r.stages[stage]])
        self.nav["Errors"].set_state("fail" if r.errors else "idle")
        syntax_errors = any(e.stage == "Syntax" for e in r.errors)
        self.nav["Recovery"].set_state("skip" if r.stages["lexical"] == "fail" else "fail" if syntax_errors else "idle")
        if r.success:
            self.status.config(text="Compiled without errors", fg=GREEN)
        else:
            self.status.config(text="%d error(s)" % len(r.errors), fg=RED)

    # ------------------------------------------------------------ run & debug
    def _run_code(self):
        r = self.result
        return r.optimized if self.run_optimized else r.instructions

    def toggle_run_source(self):
        self.run_optimized = not self.run_optimized
        self.src_btn.config(text="Code: optimized" if self.run_optimized else "Code: original")
        self.run_reset()

    def run_reset(self):
        r = self.result
        self.block_counts, self.cur_block, self._prev_env = {}, None, {}
        if r is None or r.stages.get("codegen") != "ok":
            self.machine, self.pc_block, self.block_start = None, {}, {}
            self._put_code(self.run_code, None, "Nothing to run - fix the errors first.")
        else:
            code = self._run_code()
            self.machine = Machine(code)
            blocks = r.cfg if self.run_optimized else r.cfg_original
            owner = {id(i): b.id for b in blocks for i in b.instrs}
            self.pc_block = {pc: owner.get(id(i)) for pc, i in enumerate(code)}
            self.block_start = {}
            for pc, i in enumerate(code):
                bid = self.pc_block[pc]
                if bid is not None and i.op != "label":
                    self.block_start.setdefault(bid, pc)
            self._put_code(self.run_code, code, "")
            self._track()
        self._refresh_run()

    def _track(self):
        """Follows the program counter through the flow graph: current block + how often each block ran."""
        m = self.machine
        if m is None:
            return
        bid = self.pc_block.get(m.pc)
        self.cur_block = bid
        if bid is not None and m.pc == self.block_start.get(bid):
            self.block_counts[bid] = self.block_counts.get(bid, 0) + 1

    def run_all(self):
        m = self.machine
        if m is None:
            return
        if m.finished:
            m.reset()
            self.block_counts, self._prev_env = {}, {}
            self._track()
        while True:
            more = m.step()
            self._track()
            if not more:
                break
        self._refresh_run()

    def run_step(self):
        if self.machine is None:
            return
        self.machine.step()
        self._track()
        self._refresh_run()

    def _mark_flow(self):
        m = self.machine
        if m is None or self.flow.showing_optimized != self.run_optimized:
            self.flow.mark(None, {})
            return
        self.flow.mark(None if m.finished else self.cur_block, self.block_counts)

    def _refresh_run(self):
        m = self.machine
        self.run_code.tag_remove("pc", "1.0", "end")
        self.var_tree.delete(*self.var_tree.get_children())
        self.out_text.config(state="normal")
        self.out_text.delete("1.0", "end")
        if m is None:
            self.run_info.config(text="")
            self._prev_env = {}
        else:
            if not m.finished:
                self.run_code.tag_add("pc", "%d.0" % (m.pc + 1), "%d.0lineend+1c" % (m.pc + 1))
                self.run_code.see("%d.0" % (m.pc + 1))
            for name, val in sorted(m.env.items(), key=lambda kv: (bool(re.match(r"t\d+$", kv[0])), kv[0])):
                shown = json.dumps(val) if isinstance(val, str) else format_value(val)
                tags = []
                if re.match(r"t\d+$", name):
                    tags.append("temp")
                if name not in self._prev_env or self._prev_env[name] != val:
                    tags.append("changed")                              # flash what the last step changed
                self.var_tree.insert("", "end", values=(name, shown), tags=tuple(tags))
            self._prev_env = dict(m.env)
            self.out_text.insert("end", "\n".join(m.output))
            if m.error:
                self.out_text.insert("end", ("\n" if m.output else "") + m.error, "err")
            self.out_text.see("end")
            state = "error" if m.error else "finished" if m.finished else "paused"
            self.run_info.config(text="%s  -  %d instructions executed" % (state, m.steps))
        self.out_text.config(state="disabled")
        self._mark_flow()


def launch():
    source = page = geometry = None
    while True:
        app = App(source, page, geometry)
        app.mainloop()
        if not app.restart:
            break
        source, page, geometry = app.keep
