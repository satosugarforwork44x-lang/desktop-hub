"""app.py — 窓の管理（バー・パネル）と、パスを開く等のOS操作。

窓の種類:
  bar   … 画面の端に貼り付く細いバー。マウスを乗せると広がる（dock: top / bottom / left / right）
  panel … モジュールごとの窓。自由に配置でき、位置・大きさ・開閉状態は次回起動時に復元する

実際の窓は Backend が作る。本番は pywebview、開発・テスト時は NullBackend（窓を作らずURLだけ返す）。
"""
from __future__ import annotations

import json
import os
import functools
import platform
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from .registry import ModuleError
from .version import VERSION

BAR_THICK_COLLAPSED = 6     # 畳んだときの太さ(px)。この線にマウスを乗せると広がる
BAR_THICK_EXPANDED = 52     # 広げたときの太さ(px)
BAR_THICK_EXPANDED_SIDE = 64  # 左右の端に置いたときの広げた太さ(px)
WINDOW_BG = "#0B0C10"       # 窓の地の色（読み込み前の一瞬に見える色。hub.css の --ink と合わせる）
WINDOW_BG_LIGHT = "#F3F4F7"


def windows_prefers_light() -> bool:
    """Windows の「アプリのモード」がライトか（設定 → 個人用設定 → 色）。"""
    if os.name != "nt":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 1
    except OSError:
        return False


def window_bg(mode: str) -> str:
    light = mode == "light" or (mode == "auto" and windows_prefers_light())
    return WINDOW_BG_LIGHT if light else WINDOW_BG

# Windows 11 の角丸（DWM）。Windows 10 では効かないだけで害はない
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWM_CORNER = {"round": 2, "small": 3, "square": 1}


def round_corners(hwnd: int, style: str = "round") -> bool:
    """枠なし窓に OS 標準の角丸と縁取りを付ける（Windows 11 以降）。"""
    if os.name != "nt" or not hwnd:
        return False
    try:
        import ctypes
        pref = ctypes.c_int(DWM_CORNER.get(style, 2))
        res = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(hwnd), ctypes.c_uint(DWMWA_WINDOW_CORNER_PREFERENCE), ctypes.byref(pref), ctypes.sizeof(pref))
        return res == 0
    except Exception:
        return False
PANEL_HEADER_H = 32         # パネルを見出しだけに畳んだときの高さ(px)


# ---------- Windows: 作業領域と物理ピクセルでの配置 ----------
# 画面の拡大率（125% など）が掛かっていると、pywebview の座標と画面の大きさの単位がずれて
# 「右端に置いたつもりが画面の外」になる。バーだけは Win32 API で、同じ単位（物理ピクセル）で測って置く。
def _win_work_area() -> tuple[int, int, int, int] | None:
    """メインモニターの作業領域（タスクバーを除いた範囲）: (left, top, right, bottom)。"""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        r = wintypes.RECT()
        if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0):  # SPI_GETWORKAREA
            return (r.left, r.top, r.right, r.bottom)
    except Exception:
        pass
    return None


ICON_PATH = Path(__file__).resolve().parent.parent / "assets" / "hub.ico"


def set_window_icon(hwnd: int, ico: Path = ICON_PATH) -> bool:
    """窓とタスクバーのアイコンを Hub のものにする（何もしなければ Python のアイコンになる）。"""
    if os.name != "nt" or not hwnd or not ico.exists():
        return False
    try:
        import ctypes
        user32 = ctypes.windll.user32
        user32.LoadImageW.restype = ctypes.c_void_p
        IMAGE_ICON, LR_LOADFROMFILE, WM_SETICON = 1, 0x10, 0x0080
        for which, size in ((0, 16), (1, 32)):   # ICON_SMALL, ICON_BIG
            h = user32.LoadImageW(None, str(ico), IMAGE_ICON, size, size, LR_LOADFROMFILE)
            if h:
                user32.SendMessageW(ctypes.c_void_p(hwnd), WM_SETICON, which, ctypes.c_void_p(h))
        return True
    except Exception:
        return False


def set_app_id(app_id: str = "s-tanuki.Hub") -> None:
    """タスクバーで python.exe ではなく「Hub」として扱われるようにする（アイコンもまとまる）。"""
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        pass


def _win_scale(hwnd: int) -> float:
    try:
        import ctypes
        dpi = ctypes.windll.user32.GetDpiForWindow(ctypes.c_void_p(hwnd))
        return (dpi or 96) / 96
    except Exception:
        return 1.0


def _win_set_rect(hwnd: int, x: int, y: int, w: int, h: int) -> bool:
    try:
        import ctypes
        SWP_NOZORDER, SWP_NOACTIVATE = 0x0004, 0x0010
        return bool(ctypes.windll.user32.SetWindowPos(ctypes.c_void_p(hwnd), None, int(x), int(y), int(w), int(h),
                                                      SWP_NOZORDER | SWP_NOACTIVATE))
    except Exception:
        return False


def _win_z_order(hwnd: int, where: str) -> bool:
    """窓の重なり順を変える。where: "top"（常に手前）/ "normal"（普通）/ "bottom"（他の窓の後ろ）。"""
    try:
        import ctypes
        HWND_TOPMOST, HWND_NOTOPMOST, HWND_BOTTOM = -1, -2, 1
        SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
        flags = SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
        user32 = ctypes.windll.user32
        if where == "top":
            return bool(user32.SetWindowPos(ctypes.c_void_p(hwnd), ctypes.c_void_p(HWND_TOPMOST), 0, 0, 0, 0, flags))
        user32.SetWindowPos(ctypes.c_void_p(hwnd), ctypes.c_void_p(HWND_NOTOPMOST), 0, 0, 0, 0, flags)
        if where == "bottom":
            return bool(user32.SetWindowPos(ctypes.c_void_p(hwnd), ctypes.c_void_p(HWND_BOTTOM), 0, 0, 0, 0, flags))
        return True
    except Exception:
        return False


def _win_get_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    try:
        import ctypes
        from ctypes import wintypes
        r = wintypes.RECT()
        if ctypes.windll.user32.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(r)):
            return (r.left, r.top, r.right - r.left, r.bottom - r.top)
    except Exception:
        pass
    return None


class NullBackend:
    """窓を作らないバックエンド（--dev とテスト用）。ブラウザでURLを開いて確認する。"""

    def __init__(self):
        self.windows: dict[str, dict] = {}

    def create(self, wid, title, url, x, y, w, h, on_top, on_closed, on_moved, on_resized, on_shown=None):
        self.windows[wid] = {"url": url, "geom": [x, y, w, h], "on_top": on_top}
        if on_shown:
            on_shown(wid)

    def create_web(self, wid, title, url, x, y, w, h, on_closed, on_geom):
        self.windows[wid] = {"url": url, "geom": [x, y, w, h], "web": True}

    def work_area(self, wid=None):
        """(left, top, right, bottom, 拡大率)。開発・テストでは 1920x1080 の画面とみなす。"""
        return (0, 0, 1920, 1080, 1.0)

    def screen_rects(self):
        """つながっている全モニターの (x, y, 幅, 高さ)。パネルの位置と同じ単位。"""
        return [(0, 0, 1920, 1080)]

    def place(self, wid, x, y, w, h):
        if wid in self.windows:
            self.windows[wid]["geom"] = [x, y, w, h]

    def rect(self, wid):
        return tuple(self.windows[wid]["geom"]) if wid in self.windows else None

    def destroy(self, wid):
        self.windows.pop(wid, None)

    def resize(self, wid, w, h, anchor="nw"):
        if wid in self.windows:
            self.windows[wid]["geom"][2:] = [w, h]

    def move(self, wid, x, y):
        if wid in self.windows:
            self.windows[wid]["geom"][:2] = [x, y]

    def exists(self, wid):
        return wid in self.windows

    def screen(self):
        return (1920, 1080)

    def pick_files(self, wid, multiple=True):
        return None

    def set_on_top(self, wid, value):
        if wid in self.windows:
            self.windows[wid]["on_top"] = value

    def pick_folder(self, wid):
        return None

    def z_order(self, wid, where):
        if wid in self.windows:
            self.windows[wid]["z"] = where

    def focus(self, wid):
        pass

    def reload_all(self):
        pass

    def reload(self, wid):
        if wid in self.windows:
            self.windows[wid]["reloads"] = self.windows[wid].get("reloads", 0) + 1

    def set_corners(self, style):
        pass


class PywebviewBackend:
    """pywebview（Windowsでは WebView2）で本物の窓を作る。"""

    def __init__(self, corners: str = "round", bg: str = WINDOW_BG):
        import webview  # 開発・テスト環境では読み込まない
        self.corners = corners
        self.window_bg = bg
        from webview.window import FixPoint
        self.webview, self.FixPoint = webview, FixPoint
        self.windows: dict[str, Any] = {}

    def create(self, wid, title, url, x, y, w, h, on_top, on_closed, on_moved, on_resized, on_shown=None):
        win = self.webview.create_window(
            title, url, width=w, height=h, x=x, y=y, frameless=True, easy_drag=False,
            on_top=on_top, resizable=True, min_size=(BAR_THICK_COLLAPSED, BAR_THICK_COLLAPSED),
            background_color=self.window_bg, shadow=True, text_select=False,
        )
        self.windows[wid] = win
        win.events.shown += lambda: self._apply_corners(win, "small" if wid == "bar" else self.corners)
        win.events.shown += lambda: set_window_icon(self._hwnd(wid))
        if on_shown:
            win.events.shown += lambda: on_shown(wid)

        def closed():
            self.windows.pop(wid, None)
            on_closed(wid)

        win.events.closed += closed
        win.events.moved += lambda x, y: on_moved(wid, x, y)
        win.events.resized += lambda width, height: on_resized(wid, width, height)
        win.events.loaded += lambda: self._bind_drop(win)

    def create_web(self, wid, title, url, x, y, w, h, on_closed, on_geom):
        """Web ページを直接表示する普通の窓（OS のタイトルバー付き）。Hub の画面ではないので合言葉も渡さない。"""
        win = self.webview.create_window(title, url, width=w, height=h, x=x, y=y, resizable=True,
                                         background_color=self.window_bg, text_select=True)
        self.windows[wid] = win
        win.events.shown += lambda: set_window_icon(self._hwnd(wid))

        def closed():
            self.windows.pop(wid, None)
            on_closed(wid)

        win.events.closed += closed
        win.events.moved += lambda x, y: on_geom(wid, x=x, y=y)
        win.events.resized += lambda width, height: on_geom(wid, w=width, h=height)

    @staticmethod
    def _apply_corners(win, style):
        if style == "square":
            return
        try:
            round_corners(int(win.native.Handle.ToInt64()), style)  # WinForms の窓ハンドル
        except Exception:
            pass

    def _bind_drop(self, win):
        """エクスプローラーからのドロップで、ファイルのフルパスを受け取り画面側(JS)へ渡す。
        ブラウザ単体ではフルパスは取れないため、pywebview の仕組みを使う。"""
        from webview.dom import DOMEventHandler

        def on_drop(e):
            files = (e.get("dataTransfer") or {}).get("files", [])
            paths = [f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")]
            if paths:
                win.evaluate_js(f"window.hub && window.hub._nativeDrop({json.dumps(paths)})")

        def noop(_e):
            pass

        doc = win.dom.document
        doc.events.dragenter += DOMEventHandler(noop, True, False)
        doc.events.dragover += DOMEventHandler(noop, True, False, debounce=500)
        doc.events.drop += DOMEventHandler(on_drop, True, False)

    def destroy(self, wid):
        win = self.windows.get(wid)
        if win:
            win.destroy()

    def resize(self, wid, w, h, anchor="nw"):
        win = self.windows.get(wid)
        if not win:
            return
        fp = {"nw": self.FixPoint.NORTH | self.FixPoint.WEST, "ne": self.FixPoint.NORTH | self.FixPoint.EAST,
              "sw": self.FixPoint.SOUTH | self.FixPoint.WEST}.get(anchor, self.FixPoint.NORTH | self.FixPoint.WEST)
        win.resize(int(w), int(h), fp)

    def move(self, wid, x, y):
        win = self.windows.get(wid)
        if win:
            win.move(int(x), int(y))

    def exists(self, wid):
        return wid in self.windows

    def _hwnd(self, wid) -> int:
        try:
            return int(self.windows[wid].native.Handle.ToInt64())
        except Exception:
            return 0

    def work_area(self, wid=None):
        """(left, top, right, bottom, 拡大率)。Windows では物理ピクセル、それ以外は pywebview の単位。"""
        wa, hwnd = _win_work_area(), self._hwnd(wid) if wid else 0
        if wa and hwnd:
            return (*wa, _win_scale(hwnd))
        sw, sh = self.screen()
        return (0, 0, sw, sh, 1.0)

    def place(self, wid, x, y, w, h):
        """work_area() と同じ単位で位置と大きさを一度に決める。"""
        hwnd = self._hwnd(wid)
        if hwnd and _win_work_area() and _win_set_rect(hwnd, x, y, w, h):
            return
        self.move(wid, x, y)
        self.resize(wid, w, h)

    def rect(self, wid):
        hwnd = self._hwnd(wid)
        r = _win_get_rect(hwnd) if hwnd else None
        if r:
            return r
        win = self.windows.get(wid)
        return (win.x, win.y, win.width, win.height) if win else None

    def screen_rects(self):
        out = []
        try:
            for sc in self.webview.screens:
                out.append((int(getattr(sc, "x", 0)), int(getattr(sc, "y", 0)), int(sc.width), int(sc.height)))
        except Exception:
            pass
        return out or [(0, 0, *self.screen())]

    def screen(self):
        try:
            s = self.webview.screens[0]
            return (s.width, s.height)
        except Exception:
            return (1920, 1080)

    def pick_files(self, wid, multiple=True):
        win = self.windows.get(wid)
        return list(win.create_file_dialog(allow_multiple=multiple) or []) if win else None

    def set_on_top(self, wid, value):
        win = self.windows.get(wid)
        if win:
            win.on_top = value

    def focus(self, wid):
        """窓を手前に出す（すでに開いている PDF をもう一度開いたときなど）。"""
        win = self.windows.get(wid)
        if not win:
            return
        try:
            win.restore()
            win.show()
        except Exception:
            pass
        hwnd = self._hwnd(wid)
        if hwnd and os.name == "nt":
            try:
                import ctypes
                ctypes.windll.user32.SetForegroundWindow(ctypes.c_void_p(hwnd))
            except Exception:
                pass

    def z_order(self, wid, where):
        hwnd = self._hwnd(wid)
        if hwnd and _win_z_order(hwnd, where):
            return
        win = self.windows.get(wid)  # Windows 以外: 「手前に固定」だけ切り替える
        if win:
            win.on_top = where == "top"

    def pick_folder(self, wid):
        win = self.windows.get(wid)
        if not win:
            return None
        r = win.create_file_dialog(self.webview.FOLDER_DIALOG)
        return r[0] if r else None

    def reload(self, wid):
        win = self.windows.get(wid)
        if win:
            try:
                win.evaluate_js("location.reload()")
            except Exception:
                pass

    def reload_all(self):
        """表示言語を変えたときなど、全部の窓を読み込み直す。"""
        for win in list(self.windows.values()):
            try:
                win.evaluate_js("location.reload()")
            except Exception:
                pass

    def set_corners(self, style):
        self.corners = style
        for wid, win in list(self.windows.items()):
            self._apply_corners(win, "small" if wid == "bar" and style != "square" else style)



@functools.lru_cache(maxsize=1)
def preferred_python() -> Path:
    """Hub を動かす Python（python.exe）。start_hub.bat の `set HUB_PY=3.14` と同じ版を使う。
    ショートカットと Claude 連携の設定がこれを指すので、どこから開いても同じ Python で動く。
    その版が入っていない・Windows でないときは、今動いている Python。"""
    here = Path(sys.executable.replace("pythonw.exe", "python.exe"))
    bat = Path(__file__).resolve().parent.parent / "start_hub.bat"
    if os.name != "nt" or not bat.exists():
        return here
    m = re.search(r"^set HUB_PY=([\d.]+)\s*$", bat.read_text(encoding="utf-8", errors="replace"), re.M)
    if not m:
        return here
    try:
        r = subprocess.run(["py", f"-{m.group(1)}", "-c", "import sys; print(sys.executable)"], capture_output=True,
                           text=True, timeout=15, creationflags=0x08000000)  # CREATE_NO_WINDOW
    except (OSError, subprocess.SubprocessError):
        return here
    exe = Path(r.stdout.strip()) if r.returncode == 0 else None
    return exe if exe and exe.exists() else here

class Host:
    """窓の開閉・配置の記憶・OS操作をまとめる。HTTP API（server.py）から呼ばれる。"""

    def __init__(self, config: dict, store, backend, base_url_fn):
        self.config, self.store, self.backend = config, store, backend
        self._base = base_url_fn            # () -> "http://127.0.0.1:PORT"
        self.token = ""
        self.registry = None                # main で設定
        self._quitting = False
        self._save_timers: dict[str, threading.Timer] = {}
        # 📌（広げたまま）は次回の起動にも引き継ぐ
        self._bar_state = {"expanded": False, "pinned": bool(store.get("ui", "barPinned", False)),
                           "length": int(store.get("ui", "barLength", 640) or 640)}   # length: 中身に合わせた長さ（画面の px。拡大率をかける前）

    # ---------- URL ----------
    def url(self, page: str, **q) -> str:
        q["t"] = self.token
        qs = "&".join(f"{k}={v}" for k, v in q.items())
        return f"{self._base()}/ui/{page}?{qs}"

    # ---------- バー ----------
    def dock(self) -> str:
        d = self.config.get("bar", {}).get("dock", "top")
        return d if d in ("top", "bottom", "left", "right") else "top"

    def _bar_geom(self, expanded: bool) -> list[int]:
        """作業領域（タスクバーを除いた範囲）の端にバーを置く。単位は backend.work_area() と同じ。
        offset は「端に沿ったずれ」を作業領域の長さに対する割合(0〜1)で覚える（拡大率や解像度が変わっても崩れない）。"""
        cfg = self.config.get("bar", {})
        dock = self.dock()
        vertical = dock in ("left", "right")
        left, top, right, bottom, scale = self.backend.work_area("bar")
        aw, ah = right - left, bottom - top
        thick = (BAR_THICK_EXPANDED_SIDE if vertical else BAR_THICK_EXPANDED) if expanded else BAR_THICK_COLLAPSED
        thick = round(thick * scale)
        span = ah if vertical else aw
        want = cfg.get("length", "auto")
        want = self._bar_state["length"] if want == "auto" or not isinstance(want, (int, float)) else want
        length = min(round(int(want) * scale), span - round(40 * scale))
        saved = self.store.get("window", "bar") or {}
        ratio = saved.get("ratio") if saved.get("dock") == dock else None
        pos = round((span - length) * ratio) if isinstance(ratio, (int, float)) else (span - length) // 2
        pos = max(0, min(span - length, pos))
        if dock == "left":
            return [left, top + pos, thick, length]
        if dock == "right":
            return [right - thick, top + pos, thick, length]
        if dock == "bottom":
            return [left + pos, bottom - thick, length, thick]
        return [left + pos, top, length, thick]

    def create_bar(self, intro: bool = False) -> None:
        """バーを作る。intro=True なら起動アニメーション付き（畳んだ線が伸びる → 画面側がバーを広げる → 畳む）。"""
        intro = intro and bool(self.config.get("bar", {}).get("intro", True))
        self._bar_state["expanded"] = False
        x, y, w, h = self._bar_geom(False)
        self.backend.create("bar", "Hub", self.url("bar.html", dock=self.dock(), intro=int(intro)),
                            x, y, w, h, bool(self.config.get("bar", {}).get("onTop", True)),
                            self._on_closed, self._on_bar_moved, lambda *_: None,
                            on_shown=lambda _w: (self.backend.place("bar", *self._bar_geom(self._bar_state["expanded"])),
                                                 self._apply_bar_z()))

    def _apply_bar_z(self) -> None:
        """📌 で広げたままのバーは、他の窓の後ろに回す（作業の邪魔をしない。デスクトップに置いた部品のように振る舞う）。
        畳んだ細い線のときは、マウスで触れるよう常に手前に置く。"""
        if self._bar_state["pinned"]:
            self.backend.z_order("bar", "bottom")
        elif bool(self.config.get("bar", {}).get("onTop", True)):
            self.backend.z_order("bar", "top")

    def recreate_bar(self) -> None:
        """バーの位置（上下左右）や表示の設定を変えたとき、バーだけ作り直す（Hubは終了しない）。"""
        self._recreating = True
        try:
            self.backend.destroy("bar")
        finally:
            self._recreating = False
        self.create_bar()

    def bar_set(self, expanded: bool | None = None, pinned: bool | None = None, length: int | None = None) -> dict:
        """expanded: 広げる/畳む。pinned: 📌。length: 中身に必要な長さ（設定が auto のとき、画面側が測って知らせる）"""
        if length is not None and self.config.get("bar", {}).get("length", "auto") == "auto":
            length = max(160, min(6000, int(length)))
            if abs(length - self._bar_state["length"]) > 2:
                self._bar_state["length"] = length
                self.store.set("ui", "barLength", length)
                self.backend.place("bar", *self._bar_geom(self._bar_state["expanded"]))
        if pinned is not None:
            self._bar_state["pinned"] = bool(pinned)
            self.store.set("ui", "barPinned", bool(pinned))
            self._apply_bar_z()
        if expanded is not None:
            want = bool(expanded) or self._bar_state["pinned"]
            if want != self._bar_state["expanded"]:
                self._bar_state["expanded"] = want
                self.backend.place("bar", *self._bar_geom(want))  # 端に貼り付いたまま広げる・畳む
        return dict(self._bar_state)

    def _on_bar_moved(self, _wid, _x, _y):
        # バーは端に沿ってだけ動かせる。止まったら端に吸い付け直し、端に沿った位置を割合で記憶する
        def settle():
            r = self.backend.rect("bar")
            if not r:
                return
            dock = self.dock()
            left, top, right, bottom, _ = self.backend.work_area("bar")
            vertical = dock in ("left", "right")
            span = (bottom - top) if vertical else (right - left)
            length = r[3] if vertical else r[2]
            pos = (r[1] - top) if vertical else (r[0] - left)
            ratio = max(0.0, min(1.0, pos / max(1, span - length)))
            self.store.set("window", "bar", {"dock": dock, "ratio": round(ratio, 4)})
            self.backend.place("bar", *self._bar_geom(self._bar_state["expanded"]))
        self._debounced_save("bar", settle)

    # ---------- パネル ----------
    @staticmethod
    def module_of(pid: str) -> str:
        return pid.split(":", 1)[0]

    def _default_geom(self, pid: str) -> dict:
        mod = self.registry.get(self.module_of(pid)) if self.registry else None
        size_key = "instanceSize" if ":" in pid and mod and mod.hub.get("instanceSize") else "size"
        w, h = (mod.hub.get(size_key) if mod else None) or [340, 480]
        n = len(self.store.items("window"))
        return {"x": 120 + 36 * (n % 8), "y": 120 + 36 * (n % 8), "w": w, "h": h, "open": False, "collapsed": False}

    def panel_state(self, pid: str) -> dict:
        st = {**self._default_geom(pid), **(self.store.get("window", pid) or {})}
        if not self._visible(st):  # 外したモニターや解像度の変更で画面外に残った窓は、見える場所へ戻す
            d = self._default_geom(pid)
            st.update(x=d["x"], y=d["y"])
        return st

    def _visible(self, st: dict) -> bool:
        """窓の見出し（上端の 120x32 px）が、どこかのモニターに入っていれば見えているとみなす。"""
        try:
            x, y, w = int(st["x"]), int(st["y"]), int(st["w"])
        except (KeyError, TypeError, ValueError):
            return False
        for sx, sy, sw, sh in self.backend.screen_rects():
            visible_w = min(x + w, sx + sw) - max(x, sx)
            if visible_w >= min(120, w) and sy <= y <= sy + sh - 32:
                return True
        return False

    def open_panel(self, pid: str) -> dict:
        mid = self.module_of(pid)
        mod = self.registry.get(mid)  # 未登録ならここでエラー
        if self.backend.exists(pid):
            return {"id": pid, "open": True, "already": True}
        st = self.panel_state(pid)
        h = PANEL_HEADER_H if st.get("collapsed") else st["h"]
        title = mod.manifest.get("name", mid) + (f" — {pid.split(':', 1)[1]}" if ":" in pid else "")
        if ":" in pid and mod.api is not None and hasattr(mod.api, "instance_title"):
            try:
                title = mod.api.instance_title(pid.split(":", 1)[1])  # 例: 「資料.pdf — PDF」（タスクバーに出る名前）
            except Exception:
                pass
        url = self.url("panel.html", id=pid)
        on_top = bool(self.config.get("panels", {}).get("onTop", False))
        self.backend.create(pid, title, url, st["x"], st["y"], st["w"], h, on_top,
                            self._on_closed, self._on_panel_moved, self._on_panel_resized)
        st["open"] = True
        self.store.set("window", pid, st)
        return {"id": pid, "open": True, "url": url}

    def open_web(self, wid: str, url: str, title: str = "") -> dict:
        """Web ショートカットの「ミニ窓」。位置と大きさはショートカットごとに覚える（パネルとは別の場所に保存）。"""
        from urllib.parse import urlparse
        if urlparse(url).scheme not in ("http", "https"):
            raise ModuleError("http / https の URL だけ開けます")
        wid = f"web:{wid}"
        if self.backend.exists(wid):
            self.backend.focus(wid)
            return {"id": wid, "already": True}
        g = self.store.get("webwin", wid, None) or {}
        left, top, right, bottom, _ = self.backend.work_area()
        w, h = int(g.get("w", 480)), int(g.get("h", 760))
        x, y = int(g.get("x", right - w - 24)), int(g.get("y", top + 72))
        if not any(sx <= x + 40 < sx + sw and sy <= y + 20 < sy + sh for sx, sy, sw, sh in self.backend.screen_rects()):
            x, y = right - w - 24, top + 72          # 外したモニターの位置なら戻す
        self.backend.create_web(wid, title or url, url, x, y, w, h, lambda _w: None, self._on_web_geom)
        return {"id": wid, "open": True}

    def _on_web_geom(self, wid, **kw):
        def save():
            g = self.store.get("webwin", wid, None) or {}
            g.update({k: int(v) for k, v in kw.items()})
            self.store.set("webwin", wid, g)
        self._debounced_save(f"webwin:{wid}", save)

    def open_file(self, path: str) -> dict:
        """ファイルを、それを扱うモジュール（manifest の hub.opens に拡張子を書いたもの）で開く。
        「プログラムから開く」や、2 つ目の Hub から頼まれたときに使う。"""
        p = Path(path)
        if not p.is_file():
            raise ModuleError(f"見つからない: {path}")
        for mod in (self.registry.modules.values() if self.registry else []):
            if p.suffix.lower() in [e.lower() for e in mod.hub.get("opens", [])] and mod.api is not None:
                pid = mod.api.open_path(str(p))
                r = self.open_panel(pid)
                self.backend.focus(pid)
                return r
        raise ModuleError(f"{p.suffix} のファイルを開けるモジュールがない")

    def close_panel(self, pid: str) -> dict:
        st = self.panel_state(pid)
        st["open"] = False
        self.store.set("window", pid, st)
        self.backend.destroy(pid)
        return {"id": pid, "open": False}

    def toggle_panel(self, pid: str) -> dict:
        return self.close_panel(pid) if self.backend.exists(pid) else self.open_panel(pid)

    def collapse_panel(self, pid: str, collapsed: bool) -> dict:
        """見出しだけを残して畳む／元の高さに戻す。"""
        st = self.panel_state(pid)
        st["collapsed"] = bool(collapsed)
        self.store.set("window", pid, st)
        self.backend.resize(pid, st["w"], PANEL_HEADER_H if collapsed else st["h"])
        return st

    def resize_panel(self, pid: str, w: int, h: int) -> dict:
        w, h = max(220, int(w)), max(PANEL_HEADER_H, int(h))
        self.backend.resize(pid, w, h)
        st = self.panel_state(pid)
        st.update(w=w, h=h, collapsed=False)
        self.store.set("window", pid, st)
        return st

    def open_panels(self) -> list[str]:
        return [k for k in self.store.items("window") if k != "bar" and self.backend.exists(k)]

    def restore_panels(self) -> None:
        """前回開いていたパネルを開き直す（モジュールが消えていたら飛ばす）。"""
        for pid, st in self.store.items("window").items():
            if pid != "bar" and isinstance(st, dict) and st.get("open"):
                try:
                    self.open_panel(pid)
                except ModuleError:
                    pass

    def _on_panel_moved(self, pid, x, y):
        self._update_geom(pid, x=x, y=y)

    def _on_panel_resized(self, pid, w, h):
        if h > PANEL_HEADER_H + 4:  # 畳んだ状態の高さは「元の高さ」として記憶しない
            self._update_geom(pid, w=w, h=h)

    def _update_geom(self, pid, **kw):
        def save():
            st = self.panel_state(pid)
            st.update(kw)
            self.store.set("window", pid, st)
        self._debounced_save(pid, save)

    def _on_closed(self, wid):
        if wid == "bar" and getattr(self, "_recreating", False):
            return
        if wid == "bar" and not self._quitting:
            self.quit()  # バーを閉じたらHub全体を終了
        elif wid != "bar" and not self._quitting:
            st = self.panel_state(wid)
            st["open"] = False
            self.store.set("window", wid, st)

    def _debounced_save(self, key, fn, delay=0.4):
        """ドラッグ中は moved が連続で来るので、止まってから1回だけ保存する。"""
        old = self._save_timers.get(key)
        if old:
            old.cancel()
        t = threading.Timer(delay, fn)
        t.daemon = True
        self._save_timers[key] = t
        t.start()

    def quit(self) -> dict:
        """全窓を閉じる。開いていたパネルは「開いていた」と記憶したまま（次回復元）。"""
        self._quitting = True
        for wid in list(self.backend.windows.keys()):
            if wid != "bar":
                self.backend.destroy(wid)
        self.backend.destroy("bar")
        return {"quit": True}

    # ---------- 設定 ----------
    def settings_get(self) -> dict:
        from .config import USER_CONFIG, get_in
        c = self.config
        return {
            "lang": c.get("lang", "auto"),
            "dock": self.dock(),
            "labels": get_in(c, ("bar", "labels"), "auto"),
            "corners": get_in(c, ("windows", "corners"), "round"),
            "intro": bool(get_in(c, ("bar", "intro"), True)),
            "mode": get_in(c, ("appearance", "mode"), "dark"),
            "accent": get_in(c, ("appearance", "accent"), "aurora"),
            "autostart": self.autostart(),
            "shortcuts": self.shortcuts(),
            "windows": os.name == "nt",
            "foldersRoot": get_in(c, ("modules", "folders", "root"), "~/Hub"),
            "foldersRootResolved": str(Path(str(get_in(c, ("modules", "folders", "root"), "~/Hub"))).expanduser()),
            "mcpCalendar": bool(get_in(c, ("mcp", "calendar"), True)),
            "mcpWeb": bool(get_in(c, ("mcp", "web"), True)),
            "mcpImages": bool(get_in(c, ("mcp", "images"), False)),
            "barTiles": dict(get_in(c, ("bar", "tiles"), {}) or {}),
            "barFolders": get_in(c, ("bar", "folders"), "auto"),
            "mcpPanels": dict(get_in(c, ("mcp", "panels"), {}) or {}),
            "panels": self._folder_panels(),
            "configPath": str(USER_CONFIG),
            "version": VERSION,
            "userHome": str(USER_CONFIG.parent),
            "appRoot": str(Path(__file__).resolve().parent.parent),
            "python": str(preferred_python()),                 # Claude 連携の設定に貼る Python（Hub と同じ版）
            "pythonVersion": platform.python_version(),
            "native": not isinstance(self.backend, NullBackend),
        }

    def _folder_panels(self) -> list[str]:
        try:
            return [r["id"] for r in self.registry.call("folders", "instances", {})] if self.registry else []
        except Exception:
            return []

    def settings_set(self, changes: dict) -> dict:
        """設定画面からの変更を保存して、反映できるものはその場で反映する。"""
        from .config import _merge, save_settings
        try:
            saved = save_settings(changes, getattr(self, "config_path", None))
        except ValueError as e:
            raise ModuleError(str(e))
        before = self.settings_get()
        self.config = _merge(self.config, saved)
        after = self.settings_get()
        if (before["dock"], before["labels"]) != (after["dock"], after["labels"]):
            self.recreate_bar()
        elif (before["barTiles"], before["barFolders"]) != (after["barTiles"], after["barFolders"]):
            self.backend.reload("bar")     # タイルの並び・表示だけなら、バーを読み込み直すだけ
        if (before["lang"], before["mode"], before["accent"]) != (after["lang"], after["mode"], after["accent"]):
            self.backend.reload_all()   # 言語・見た目は全部の窓を読み込み直して反映
        self.backend.window_bg = window_bg(after["mode"])
        if before["corners"] != after["corners"]:
            self.backend.set_corners(after["corners"])
        restart = before["foldersRoot"] != after["foldersRoot"]
        return {"settings": after, "restart": restart}

    # ---------- Windows のショートカット（起動時に開く・スタートメニュー・デスクトップ） ----------
    # 置き場所は Windows に尋ねる（デスクトップが OneDrive の中に移されていても正しく置ける）
    _CSIDL = {"startup": 7, "startmenu": 2, "desktop": 16}   # Startup / Programs / DesktopDirectory

    @classmethod
    def _shortcut_path(cls, where: str) -> Path:
        if os.name == "nt":
            import ctypes
            buf = ctypes.create_unicode_buffer(260)
            if ctypes.windll.shell32.SHGetFolderPathW(None, cls._CSIDL[where], None, 0, buf) == 0:
                return Path(buf.value) / "Hub.lnk"
        base = Path(os.environ.get("APPDATA", "~")).expanduser() / "Microsoft/Windows/Start Menu/Programs"
        return {"startup": base / "Startup", "startmenu": base, "desktop": Path.home() / "Desktop"}[where] / "Hub.lnk"

    @staticmethod
    def _startup_lnk() -> Path:      # 互換のため残す
        return Host._shortcut_path("startup")

    def shortcuts(self) -> dict:
        return {w: os.name == "nt" and self._shortcut_path(w).exists() for w in self._CSIDL}

    def autostart(self) -> bool:
        return self.shortcuts()["startup"]

    @staticmethod
    def _write_shortcut(lnk: Path) -> None:
        """今の Hub（この場所の hub.py）を、黒い画面なしで開くショートカットを作る。Python は preferred_python()。"""
        root = Path(__file__).resolve().parent.parent
        exe = preferred_python()                       # start_hub.bat と同じ版（今 3.15 で動いていても 3.14 を指す）
        pyw = exe.with_name("pythonw.exe")
        target = pyw if pyw.exists() else exe
        ps = (
            "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:HUB_LNK);"
            "$s.TargetPath=$env:HUB_TARGET;$s.Arguments='\"'+$env:HUB_SCRIPT+'\"';"
            "$s.WorkingDirectory=$env:HUB_ROOT;$s.IconLocation=$env:HUB_ICON;$s.Description='Hub';$s.Save()"
        )
        env = {**os.environ, "HUB_LNK": str(lnk), "HUB_TARGET": str(target), "HUB_SCRIPT": str(root / "hub.py"),
               "HUB_ROOT": str(root), "HUB_ICON": str(ICON_PATH)}
        lnk.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], env=env,
                           capture_output=True, text=True, timeout=20, creationflags=0x08000000)  # CREATE_NO_WINDOW
        if r.returncode != 0 or not lnk.exists():
            raise ModuleError(f"ショートカットを作れませんでした: {(r.stderr or r.stdout).strip()[:200]}")

    def set_shortcut(self, where: str, on: bool) -> dict:
        """where: startup（Windows の起動時に開く）/ startmenu（スタートメニュー。検索・タスクバーへのピン留めもここから）/ desktop"""
        if os.name != "nt":
            raise ModuleError("Windows でだけ使えます")
        if where not in self._CSIDL:
            raise ModuleError(f"不明な場所: {where}")
        lnk = self._shortcut_path(where)
        if on:
            self._write_shortcut(lnk)
        else:
            lnk.unlink(missing_ok=True)
        return self.shortcuts()

    def set_autostart(self, on: bool) -> dict:
        self.set_shortcut("startup", on)
        return {"autostart": on}

    def repair_shortcuts(self) -> list[str]:
        """起動のたびに、今あるショートカットを今の場所で作り直す。
        アプリのフォルダを移動・更新しても、「起動時に開く」やアイコンが古い場所を指したまま動かなくなることを防ぐ。"""
        fixed = []
        if os.name != "nt":
            return fixed
        for where, exists in self.shortcuts().items():
            if exists:
                try:
                    self._write_shortcut(self._shortcut_path(where))
                    fixed.append(where)
                except Exception:
                    pass
        return fixed

    def pick_folder(self, pid: str) -> str | None:
        return self.backend.pick_folder(pid)

    def restart(self) -> dict:
        """Hub を起動し直す（フォルダの場所の変更などを反映するため）。"""
        if isinstance(self.backend, NullBackend):
            raise ModuleError("確認用モード（--dev）では再起動できません")
        root = Path(__file__).resolve().parent.parent
        flags = 0x00000008 | 0x00000200 if os.name == "nt" else 0  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        subprocess.Popen([sys.executable, str(root / "hub.py")], cwd=str(root), creationflags=flags, close_fds=True)
        threading.Timer(0.3, self.quit).start()  # 応答を返してから終了する
        return {"restarting": True}

    # ---------- OS操作 ----------
    @staticmethod
    def open_path(path: str) -> dict:
        p = Path(path)
        if not p.exists():
            raise ModuleError(f"見つからない: {path}")
        if os.name == "nt":
            os.startfile(str(p))  # 関連付けられたアプリで開く
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(p)])
        return {"opened": str(p)}

    @staticmethod
    def reveal_path(path: str) -> dict:
        p = Path(path)
        if not p.exists():
            raise ModuleError(f"見つからない: {path}")
        if os.name == "nt":
            subprocess.Popen(["explorer", "/select,", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p.parent)])
        return {"revealed": str(p)}

    def pick_files(self, pid: str) -> list[str] | None:
        return self.backend.pick_files(pid)
