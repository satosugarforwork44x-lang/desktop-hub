"""media/api.py — 動画と音楽の再生リスト。再生そのものは画面（WebView2 の <video>/<audio>）がする。

  ・そのまま再生できる形式: MP4 / MOV / WebM / MP3 / M4A / AAC / WAV / FLAC / OGG / Opus（MKV は中身による）
  ・それ以外（AVI / WMV / WMA など）は、ffmpeg があれば MP4 / M4A に変換して再生リストに入れる
    ffmpeg は Hub に同梱しない（GPL のため）。利用者が入れたものを探して使う:
      設定の modules.media.ffmpeg → PATH → よくある場所（C:\\ffmpeg\\bin など）
開いてよいのは、利用者が入れたファイルだけ（画面からは key でしか指せない）。
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

_ctx = None
MAX_ITEMS = 1000
VIDEO = {".mp4", ".m4v", ".mov", ".webm", ".mkv", ".avi", ".wmv", ".flv", ".mpg", ".mpeg", ".ts", ".m2ts", ".3gp"}
AUDIO = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".oga", ".opus", ".wma", ".aiff", ".aif", ".ape"}
NATIVE = {".mp4", ".m4v", ".mov", ".webm", ".mkv", ".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".oga", ".opus"}
MEDIA = VIDEO | AUDIO
_jobs: dict[str, dict] = {}
_lock = threading.Lock()


class MediaError(Exception):
    pass


def setup(ctx):
    global _ctx
    _ctx = ctx


def _key(p: Path) -> str:
    return hashlib.sha1(str(p).lower().encode("utf-8")).hexdigest()[:12]


def _items() -> list[dict]:
    return _ctx.store.get("media", "items", []) or []


def _save(items: list[dict]) -> None:
    _ctx.store.set("media", "items", items[:MAX_ITEMS])
    _ctx.store.set("media", "rev", time.time())     # 画面が「変わった」と気づくための印


def _item(p: Path) -> dict:
    ext = p.suffix.lower()
    return {"key": _key(p), "path": str(p), "name": p.stem, "ext": ext[1:],
            "kind": "video" if ext in VIDEO else "audio", "native": ext in NATIVE}


def _expand(path: str) -> list[Path]:
    p = Path(path).expanduser()
    if p.is_dir():   # フォルダは直下の動画・音楽を名前順に（下の階層までは見ない）
        return sorted((f.resolve() for f in p.iterdir() if f.is_file() and f.suffix.lower() in MEDIA), key=lambda f: f.name.lower())
    if p.is_file() and p.suffix.lower() in MEDIA:
        return [p.resolve()]
    return []


def state() -> dict:
    prefs = _ctx.store.get("media", "prefs", {}) or {}
    return {"items": _items(), "current": _ctx.store.get("media", "current", None), "rev": _ctx.store.get("media", "rev", 0),
            "volume": prefs.get("volume", 0.8), "repeat": prefs.get("repeat", "all"), "ffmpeg": bool(_ffmpeg())}


def add(paths: list[str], play: bool = True, replace: bool = False) -> dict:
    """ファイル・フォルダを再生リストに入れる。すでに入っているものは増やさない。play なら最初の 1 つを「今の曲」にする。"""
    files = [f for p in paths for f in _expand(p)]
    if not files:
        raise MediaError("再生できるファイルがない")
    items = [] if replace else _items()
    have = {i["key"] for i in items}
    for f in files:
        it = _item(f)
        if it["key"] not in have:
            items.append(it)
            have.add(it["key"])
    _save(items)
    if play:
        _ctx.store.set("media", "current", _key(files[0]))
    return state()


def open_path(path: str) -> str:
    """「プログラムから開く」などで渡されたファイルを入れて、すぐ再生する（host から呼ぶ）。"""
    add([path], play=True)
    return "media"


def remove(key: str) -> dict:
    _save([i for i in _items() if i["key"] != key])
    return state()


def clear() -> dict:
    _save([])
    _ctx.store.set("media", "current", None)
    return state()


def set_current(key: str | None) -> bool:
    _ctx.store.set("media", "current", key)
    return True


def set_prefs(volume: float | None = None, repeat: str | None = None) -> dict:
    prefs = _ctx.store.get("media", "prefs", {}) or {}
    if volume is not None:
        prefs["volume"] = max(0.0, min(1.0, float(volume)))
    if repeat in ("off", "all", "one"):
        prefs["repeat"] = repeat
    _ctx.store.set("media", "prefs", prefs)
    return prefs


def _path_of(key: str) -> Path:
    it = next((i for i in _items() if i["key"] == key), None)
    if not it:
        raise MediaError("再生リストに無い")
    p = Path(it["path"])
    if not p.is_file():
        raise MediaError(f"ファイルが見つからない: {p}")
    return p


def blob_path(key: str) -> Path:
    """画面（<video>/<audio>）に渡すファイル。server.py の /blob/media/<key> から（途中からの読み込みにも対応）。"""
    return _path_of(key)


def reveal_path(key: str) -> str:
    return str(_path_of(key))


# ---------- ffmpeg（入っていれば使う） ----------
_found: dict = {"at": 0.0, "exe": None}


def _ffmpeg() -> str | None:
    """見つけた場所は 1 分だけ覚える（再生リストを読むたびにディスクを探さないため）。"""
    if time.time() - _found["at"] < 60:
        return _found["exe"]
    _found.update(at=time.time(), exe=_find_ffmpeg())
    return _found["exe"]


def _find_ffmpeg() -> str | None:
    conf = (_ctx.config or {}).get("ffmpeg") if _ctx else None
    cands = [conf] if conf else []
    cands.append(shutil.which("ffmpeg"))
    if os.name == "nt":
        home = Path.home()
        cands += [r"C:\ffmpeg\bin\ffmpeg.exe", r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"]
        for base in (home, home / "Downloads", home / "Documents", Path("C:/")):   # 展開しただけの zip（ffmpeg-*\bin\ffmpeg.exe）も探す
            try:
                cands += [str(p) for p in base.glob("ffmpeg*/bin/ffmpeg.exe")]
                cands += [str(p) for p in base.glob("ffmpeg*/*/bin/ffmpeg.exe")]
            except OSError:
                pass
    for c in cands:
        if c and Path(c).is_file():
            return str(c)
    return None


def ffmpeg_status() -> dict:
    exe = _ffmpeg()
    return {"found": bool(exe), "path": exe or ""}


def _target(src: Path, audio: bool) -> Path:
    ext = ".m4a" if audio else ".mp4"
    out = src.with_suffix(ext)
    n = 2
    while out.exists():
        out = src.with_name(f"{src.stem} ({n}){ext}")
        n += 1
    return out


def convert(key: str) -> dict:
    """再生できない形式を、同じ場所に MP4（動画）/ M4A（音楽）として作る。元のファイルは残す。終わったら再生リストに入る。"""
    exe = _ffmpeg()
    if not exe:
        raise MediaError("ffmpeg が見つからない（設定の modules.media.ffmpeg に ffmpeg.exe の場所を書くか、PATH に入れてください）")
    src = _path_of(key)
    audio = src.suffix.lower() in AUDIO
    out = _target(src, audio)
    with _lock:
        if _jobs.get(key, {}).get("state") == "running":
            return _jobs[key]
        _jobs[key] = {"state": "running", "progress": 0.0, "out": str(out), "error": ""}
    args = [exe, "-hide_banner", "-nostdin", "-y", "-i", str(src)]
    args += (["-vn", "-c:a", "aac", "-b:a", "256k"] if audio else
             ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
              "-movflags", "+faststart"])
    args.append(str(out))
    threading.Thread(target=_run, args=(key, args, out), daemon=True).start()
    return _jobs[key]


def _run(key: str, args: list[str], out: Path) -> None:
    flags = 0x08000000 if os.name == "nt" else 0          # CREATE_NO_WINDOW（黒い画面を出さない）
    dur = 0.0
    tail: list[str] = []
    try:
        pr = subprocess.Popen(args, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, creationflags=flags,
                              text=True, encoding="utf-8", errors="replace")
        for line in iter(lambda: pr.stderr.readline() if pr.stderr else "", ""):
            tail = (tail + [line.strip()])[-6:]
            if not dur and (m := re.search(r"Duration: (\d+):(\d+):([\d.]+)", line)):
                dur = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
            if dur and (m := re.search(r"time=(\d+):(\d+):([\d.]+)", line)):
                done = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
                _jobs[key]["progress"] = round(min(0.99, done / dur), 3)
        code = pr.wait()
        if code != 0 or not out.is_file():
            out.unlink(missing_ok=True)
            raise MediaError("\n".join(tail[-3:]) or f"ffmpeg が失敗した（{code}）")
        st = add([str(out)], play=True)
        _jobs[key].update(state="done", progress=1.0, key=_key(out.resolve()), items=len(st["items"]))
    except Exception as e:  # noqa: BLE001 — 画面に理由を出す
        _jobs[key].update(state="error", error=str(e))


def convert_status(key: str) -> dict:
    return _jobs.get(key, {"state": "none"})
