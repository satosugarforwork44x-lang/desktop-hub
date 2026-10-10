"""web/api.py — Web ショートカット。

開き方（ショートカットごとに選ぶ）:
  mini     … Hub のミニ窓（WebView2。ログイン状態は Hub の中だけで覚える）
  default  … いつものブラウザ
  chrome / edge … そのブラウザの「アプリ窓」（アドレスバーの無い小さな窓。ブラウザのログイン状態のまま使える）
  firefox  … Firefox の新しい窓（Firefox にはアプリ窓が無い）
Claude には一覧（名前と URL）だけを見せる（hub_mcp.py の web_shortcuts）。ページの中身を Hub が取りに行くことはない。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

_ctx = None
MODES = ("mini", "default", "chrome", "edge", "firefox")
MAX_ITEMS = 200


class WebError(Exception):
    pass


def setup(ctx):
    global _ctx
    _ctx = ctx


def _load() -> list[dict]:
    return _ctx.store.get("web", "items", []) or []


def _store(items: list[dict]) -> None:
    _ctx.store.set("web", "items", items[:MAX_ITEMS])


def items() -> list[dict]:
    return _load()


def _clean_url(url: str) -> str:
    url = (url or "").strip()
    if re.match(r"[A-Za-z][\w+.-]*:(?!\d)", url) and not re.match(r"https?://", url, re.I):
        raise WebError("http:// か https:// で始まる URL を入れてください")   # javascript: や file: は受け付けない
    if url and "://" not in url:
        url = "https://" + url               # 「news.example.com」だけでも入れられるように
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.netloc:
        raise WebError("http:// か https:// で始まる URL を入れてください")
    return url


def save(url: str, name: str = "", open: str = "mini", id: str | None = None) -> dict:
    url = _clean_url(url)
    if open not in MODES:
        raise WebError(f"開き方が不明: {open}")
    name = (name or "").strip()[:60] or urlparse(url).netloc.removeprefix("www.")
    its = _load()
    if id:
        for it in its:
            if it["id"] == id:
                it.update(name=name, url=url, open=open)
                _store(its)
                return it
        raise WebError("見つからない")
    it = {"id": uuid.uuid4().hex[:8], "name": name, "url": url, "open": open}
    _store(its + [it])
    return it


def remove(id: str) -> dict:
    _store([i for i in _load() if i["id"] != id])
    return {"removed": id}


def reorder(ids: list[str]) -> list[dict]:
    its = {i["id"]: i for i in _load()}
    ordered = [its.pop(i) for i in ids if i in its] + list(its.values())
    _store(ordered)
    return ordered


# ---------- ブラウザ ----------
def _candidates() -> dict[str, list[Path]]:
    pf = [Path(os.environ.get(k, "")) for k in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA") if os.environ.get(k)]
    return {
        "chrome": [b / "Google" / "Chrome" / "Application" / "chrome.exe" for b in pf],
        "edge": [b / "Microsoft" / "Edge" / "Application" / "msedge.exe" for b in pf],
        "firefox": [b / "Mozilla Firefox" / "firefox.exe" for b in pf],
    }


def _exe(name: str) -> str | None:
    if os.name == "nt":
        for p in _candidates()[name]:
            if p.is_file():
                return str(p)
        return None
    return shutil.which({"chrome": "google-chrome", "edge": "microsoft-edge", "firefox": "firefox"}[name])


def browsers() -> dict:
    """入っているブラウザ（画面の「開き方」に出す）。"""
    return {b: bool(_exe(b)) for b in ("chrome", "edge", "firefox")}


def launch(id: str) -> dict:
    """ブラウザで開く。mode が mini のときは開かずに URL を返す（画面側が host.openWeb でミニ窓を開く）。"""
    it = next((i for i in _load() if i["id"] == id), None)
    if not it:
        raise WebError("見つからない")
    url, mode = _clean_url(it["url"]), it.get("open", "mini")
    if mode == "mini":
        return {"mini": True, "url": url, "name": it["name"]}
    if mode == "default":
        webbrowser.open(url)
        return {"opened": "default"}
    exe = _exe(mode)
    if not exe:
        raise WebError(f"{mode} が見つからない（いつものブラウザで開くか、開き方を変えてください）")
    args = [exe, f"--app={url}", "--window-size=520,820"] if mode in ("chrome", "edge") else [exe, "-new-window", url]
    subprocess.Popen(args, close_fds=True)
    return {"opened": mode}
