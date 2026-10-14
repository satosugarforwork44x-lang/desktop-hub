"""server.py — 画面(HTML/JS)とPythonをつなぐ、自分のPC内だけで動くHTTPサーバー。

・127.0.0.1（このPCの中）でだけ待ち受ける
・/api/* は起動ごとに作る合言葉（トークン）が無いと受け付けない
  → 他のWebサイトが裏でこのサーバーを呼んでファイルを動かす、といった悪用を防ぐ
・画面ファイルは ui/ と、各モジュールの ui/ フォルダの中だけを配信する
"""
from __future__ import annotations

import json
import mimetypes
import re
import secrets
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .config import APP_ROOT
from .registry import ModuleError

UI_DIR = APP_ROOT / "ui"
UPLOAD_MAX = 256 * 1024 * 1024   # 画面からモジュールへ送れるファイルの上限（/upload）
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("application/octet-stream", ".bcmap")
for _ext, _ct in ((".webp", "image/webp"), (".jfif", "image/jpeg"), (".m4a", "audio/mp4"), (".m4v", "video/mp4"),
                  (".flac", "audio/flac"), (".opus", "audio/ogg"), (".oga", "audio/ogg"), (".mkv", "video/x-matroska"),
                  (".webm", "video/webm"), (".aac", "audio/aac"), (".wav", "audio/wav"), (".mp3", "audio/mpeg")):
    mimetypes.add_type(_ct, _ext)   # Windows のレジストリに無い／違う種類で登録されていることがあるので固定する


def _safe_join(base: Path, rel: str) -> Path | None:
    """base の外に出るパス（../ など）は拒否する。"""
    target = (base / rel).resolve()
    try:
        target.relative_to(base.resolve())
    except ValueError:
        return None
    return target


class HubServer:
    def __init__(self, host, registry, port: int = 0):
        self.host, self.registry = host, registry
        self.token = secrets.token_urlsafe(18)
        handler = self._make_handler()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    # ---------- API本体 ----------
    def dispatch(self, path: str, body: dict):
        host, reg = self.host, self.registry
        if path == "/api/registry":
            return reg.list()
        if path == "/api/call":
            return reg.call(body.get("module", ""), body.get("fn", ""), body.get("args") or {})
        if path == "/api/action":
            return reg.run_action(body.get("module", ""), body.get("action", ""), body.get("file", ""), body.get("params") or {})
        if path == "/api/state/get":
            return host.store.get("ui", str(body.get("key", "")), body.get("default"))
        if path == "/api/state/set":
            host.store.set("ui", str(body.get("key", "")), body.get("value"))
            return True
        if path.startswith("/api/host/"):
            op = path.rsplit("/", 1)[1]
            pid = str(body.get("id", ""))
            ops = {
                "config": lambda: {"bar": host.config.get("bar", {}), "theme": host.config.get("theme"),
                                   "lang": host.config.get("lang", "auto"),
                                   "appearance": host.config.get("appearance", {}), "source": host.config.get("_source")},
                "open_panel": lambda: host.open_panel(pid),
                "close_panel": lambda: host.close_panel(pid),
                "toggle_panel": lambda: host.toggle_panel(pid),
                "collapse_panel": lambda: host.collapse_panel(pid, bool(body.get("collapsed"))),
                "resize_panel": lambda: host.resize_panel(pid, body.get("w", 340), body.get("h", 480)),
                "panel_state": lambda: host.panel_state(pid),
                "open_panels": lambda: host.open_panels(),
                "bar": lambda: host.bar_set(body.get("expanded"), body.get("pinned"), body.get("length")),
                "open_path": lambda: host.open_path(str(body.get("path", ""))),
                "reveal_path": lambda: host.reveal_path(str(body.get("path", ""))),
                "pick_files": lambda: host.pick_files(pid),
                "quit": lambda: host.quit(),
                "settings": lambda: host.settings_get(),
                "settings_set": lambda: host.settings_set(body.get("changes") or {}),
                "pick_folder": lambda: host.pick_folder(pid),
                "restart": lambda: host.restart(),
                "autostart": lambda: host.set_autostart(bool(body.get("on"))),
                "shortcut": lambda: host.set_shortcut(str(body.get("where", "")), bool(body.get("on"))),
                "open_file": lambda: host.open_file(str(body.get("path", ""))),
                "open_url": lambda: host.open_url(str(body.get("url", ""))),
                "open_web": lambda: host.open_web(pid, str(body.get("url", "")), str(body.get("title", ""))),
            }
            if op in ops:
                return ops[op]()
        raise ModuleError(f"不明なAPI: {path}")

    def _make_handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):  # コンソールを静かに保つ
                pass

            def _send(self, code: int, payload: bytes, ctype: str):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(payload)

            def _json(self, code: int, obj):
                self._send(code, json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"),
                           "application/json; charset=utf-8")

            def do_GET(self):
                url = urlparse(self.path)
                path = unquote(url.path)
                if path.startswith("/blob/"):
                    self._blob(path, parse_qs(url.query))
                    return
                if path in ("/", "/index.html"):
                    self.send_response(302)
                    self.send_header("Location", f"/ui/bar.html?t={server.token}")
                    self.end_headers()
                    return
                target = None
                if path.startswith("/ui/"):
                    target = _safe_join(UI_DIR, path[len("/ui/"):])
                elif path.startswith("/m/"):  # /m/<module>/ui/xxx.js → そのモジュールの ui/ 内だけ
                    parts = path.split("/", 3)
                    if len(parts) == 4 and parts[2] in server.registry.modules:
                        mdir = server.registry.modules[parts[2]].dir
                        target = _safe_join(mdir / "ui", parts[3][len("ui/"):]) if parts[3].startswith("ui/") else None
                if not target or not target.is_file():
                    self._send(404, b"not found", "text/plain")
                    return
                ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
                if ctype.startswith("text/"):
                    ctype += "; charset=utf-8"
                self._send(200, target.read_bytes(), ctype)

            def _blob(self, path: str, query: dict):
                """/blob/<module>/<key> … モジュールが「渡してよい」と答えたファイルだけを返す（例: PDF ビューアの PDF）。
                合言葉が必要（ヘッダー X-Hub-Token か ?t=）。モジュールは manifest の hub.blob に関数名を書く。"""
                token = self.headers.get("X-Hub-Token") or (query.get("t") or [""])[0]
                if token != server.token:
                    self._send(403, b"forbidden", "text/plain")
                    return
                parts = path.split("/", 3)
                mod = server.registry.modules.get(parts[2]) if len(parts) == 4 else None
                fn = (mod.hub.get("blob") if mod else None) or ""
                try:
                    target = Path(getattr(mod.api, fn)(parts[3])) if mod and mod.api and fn else None
                except Exception:
                    target = None
                if not target or not target.is_file():
                    self._send(404, b"not found", "text/plain")
                    return
                ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
                self._stream(target, ctype)

            def _upload(self, path: str, query: dict):
                """/upload/<module>/<fn>?引数 … 画面からモジュールへバイト列をそのまま送る（base64 にしないので軽い）。
                合言葉が必要。manifest の hub.upload に書いた関数だけが受け取る。大きさは UPLOAD_MAX まで。"""
                if self.headers.get("X-Hub-Token") != server.token:
                    self._json(403, {"ok": False, "error": "トークンが違う"})
                    return
                length = self.headers.get("Content-Length")
                if length is None or not length.isdigit():
                    self._json(411, {"ok": False, "error": "大きさ（Content-Length）が無い"})
                    return
                if int(length) > UPLOAD_MAX:
                    self.close_connection = True          # 本文は読まずに断る
                    self._json(413, {"ok": False, "error": f"大きすぎる（{UPLOAD_MAX // 1048576}MB まで）"})
                    return
                parts = path.split("/")
                if len(parts) != 4:
                    self._json(404, {"ok": False, "error": "not found"})
                    return
                data = self.rfile.read(int(length))
                args = {k: v[0] for k, v in query.items()}
                try:
                    self._json(200, {"ok": True, "data": server.registry.call_upload(parts[2], parts[3], data, args)})
                except ModuleError as e:
                    self._json(200, {"ok": False, "error": str(e)})
                except Exception as e:
                    traceback.print_exc()
                    self._json(200, {"ok": False, "error": f"{type(e).__name__}: {e}"})

            def _stream(self, target: Path, ctype: str):
                """ファイルを少しずつ送る。Range（途中から）にも答える → 動画のシーク・大きなファイルでもメモリを使わない。"""
                size = target.stat().st_size
                start, end = 0, size - 1
                m = re.match(r"bytes=(\d*)-(\d*)$", self.headers.get("Range") or "")
                if m and (m.group(1) or m.group(2)):
                    if m.group(1):
                        start = int(m.group(1))
                        end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
                    else:                                   # bytes=-500（末尾の 500 バイト）
                        start = max(0, size - int(m.group(2)))
                    if start > end or start >= size:
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{size}")
                        self.end_headers()
                        return
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                else:
                    self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(end - start + 1))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                try:
                    with target.open("rb") as f:
                        f.seek(start)
                        left = end - start + 1
                        while left > 0:
                            chunk = f.read(min(1 << 20, left))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            left -= len(chunk)
                except (ConnectionError, OSError):
                    pass   # 再生位置を変えたときなど、画面側が途中で切るのは普通のこと

            def do_POST(self):
                path = urlparse(self.path).path
                if path.startswith("/upload/"):
                    self._upload(path, parse_qs(urlparse(self.path).query))
                    return
                if not path.startswith("/api/"):
                    self._json(404, {"ok": False, "error": "not found"})
                    return
                if self.headers.get("X-Hub-Token") != server.token:
                    self._json(403, {"ok": False, "error": "トークンが違う"})
                    return
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                    body = json.loads(self.rfile.read(length) or b"{}") if length else {}
                    self._json(200, {"ok": True, "data": server.dispatch(path, body)})
                except ModuleError as e:
                    self._json(200, {"ok": False, "error": str(e)})
                except Exception as e:  # 想定外のエラーも画面に理由を返す（Hub全体は止めない）
                    traceback.print_exc()
                    self._json(200, {"ok": False, "error": f"{type(e).__name__}: {e}"})

        return Handler
