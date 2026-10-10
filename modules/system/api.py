"""system/api.py — PC の負荷を見る（psutil、BSD-3-Clause）。

  ・CPU / メモリ / ディスク（使用率と読み書きの速さ）/ 通信量（上り・下り）… psutil
  ・GPU … NVIDIA は nvidia-smi（ドライバに付いてくる）で使用率・VRAM・温度。ほかの GPU は今は出さない
  ・Ping … OS の ping コマンドを 1 回。宛先は利用者が決める（既定 1.1.1.1）
回線の速度テスト（大きなデータを送受信して測る）はしない。通信量は「今どれだけ流れているか」の実測。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time

_ctx = None
HOST_RE = re.compile(r"[A-Za-z0-9:][A-Za-z0-9.\-:]{0,252}")   # ホスト名か IP だけ。「-」始まり（ping のオプション扱い）は不可
_last: dict = {}
_gpu_cache = {"at": 0.0, "data": None}
_lock = threading.Lock()
NOWIN = 0x08000000 if os.name == "nt" else 0       # 黒い画面を出さない


class SystemError_(Exception):
    pass


def setup(ctx):
    global _ctx
    _ctx = ctx


def _ps():
    try:
        import psutil
        return psutil
    except ImportError:
        raise SystemError_("psutil が入っていません（py -m pip install --user psutil）") from None


def prefs() -> dict:
    p = _ctx.store.get("system", "prefs", {}) or {}
    return {"pingHost": p.get("pingHost", "1.1.1.1"), "bar": bool(p.get("bar", False))}


def set_prefs(pingHost: str | None = None, bar: bool | None = None) -> dict:
    p = prefs()
    if pingHost is not None:
        h = pingHost.strip()
        if not HOST_RE.fullmatch(h):
            raise SystemError_("ホスト名か IP アドレスを入れてください（例: 1.1.1.1）")
        p["pingHost"] = h
    if bar is not None:
        p["bar"] = bool(bar)
    _ctx.store.set("system", "prefs", p)
    return p


def _rates(now: float, disk, net) -> dict:
    """前回からの差で「1 秒あたり」を出す。初回は 0。"""
    with _lock:
        prev = _last.get("io")
        _last["io"] = (now, disk, net)
    if not prev:
        return {"read": 0, "write": 0, "down": 0, "up": 0}
    dt = max(0.2, now - prev[0])
    d0, n0 = prev[1], prev[2]
    r = lambda a, b: max(0, int((a - b) / dt))  # noqa: E731
    return {
        "read": r(disk.read_bytes, d0.read_bytes) if disk and d0 else 0,
        "write": r(disk.write_bytes, d0.write_bytes) if disk and d0 else 0,
        "down": r(net.bytes_recv, n0.bytes_recv) if net and n0 else 0,
        "up": r(net.bytes_sent, n0.bytes_sent) if net and n0 else 0,
    }


def _gpu() -> list[dict] | None:
    """NVIDIA の GPU（nvidia-smi があれば）。2 秒は前の値を使う。"""
    if time.time() - _gpu_cache["at"] < 2:
        return _gpu_cache["data"]
    exe = shutil.which("nvidia-smi") or (r"C:\Windows\System32\nvidia-smi.exe" if os.name == "nt" and os.path.exists(r"C:\Windows\System32\nvidia-smi.exe") else None)
    data = None
    if exe:
        try:
            out = subprocess.run([exe, "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
                                  "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=3, creationflags=NOWIN).stdout
            data = []
            for line in out.strip().splitlines():
                name, util, mu, mt, temp, pw = [x.strip() for x in line.split(",")]
                num = lambda x: float(x) if re.fullmatch(r"[\d.]+", x) else None  # noqa: E731
                data.append({"name": name, "util": num(util), "memUsed": num(mu), "memTotal": num(mt), "temp": num(temp), "power": num(pw)})
        except (OSError, ValueError, subprocess.TimeoutExpired):
            data = None
    _gpu_cache.update(at=time.time(), data=data)
    return data


def sample() -> dict:
    ps = _ps()
    now = time.time()
    vm = ps.virtual_memory()
    sysdrive = (os.environ.get("SystemDrive", "C:") + "\\") if os.name == "nt" else "/"
    try:
        du = ps.disk_usage(sysdrive)
    except OSError:
        du = None
    try:
        dio = ps.disk_io_counters()
    except (RuntimeError, OSError):
        dio = None
    nio = ps.net_io_counters()
    freq = ps.cpu_freq()
    bat = ps.sensors_battery() if hasattr(ps, "sensors_battery") else None
    return {
        "cpu": ps.cpu_percent(interval=None),          # 前回呼んでからの平均（最初の 1 回は 0）
        "cores": ps.cpu_count(logical=True),
        "freq": round(freq.current) if freq else None,
        "mem": {"used": vm.total - vm.available, "total": vm.total, "pct": vm.percent},
        "disk": {"pct": du.percent if du else None, "free": du.free if du else None, "drive": sysdrive.rstrip("\\/") or "/"},
        "io": _rates(now, dio, nio),
        "gpu": _gpu(),
        "battery": {"pct": round(bat.percent), "plugged": bat.power_plugged} if bat else None,
        "uptime": int(now - ps.boot_time()),
    }


def top(n: int = 5) -> list[dict]:
    """CPU を多く使っているアプリ（同じ名前のプロセスはまとめる。例: chrome.exe が 30 個 → 1 行）。"""
    ps = _ps()
    cores = ps.cpu_count(logical=True) or 1
    groups: dict[str, dict] = {}
    for p in ps.process_iter(["name", "memory_info"]):
        try:
            name = p.info["name"] or "?"
            if name.lower() in ("system idle process", "idle", "system", "memory compression", "registry"):
                continue
            cpu = p.cpu_percent(interval=None) / cores     # タスクマネージャーと同じく「全体に対する %」
            g = groups.setdefault(name, {"name": name, "cpu": 0.0, "mem": 0, "count": 0})
            g["cpu"] += cpu
            g["mem"] += p.info["memory_info"].rss if p.info["memory_info"] else 0
            g["count"] += 1
        except (ps.NoSuchProcess, ps.AccessDenied, ps.ZombieProcess):
            continue
    rows = sorted(groups.values(), key=lambda g: (-g["cpu"], -g["mem"]))[: max(1, min(int(n), 15))]
    for r in rows:
        r["cpu"] = round(r["cpu"], 1)
    return rows


def ping(host: str | None = None) -> dict:
    """1 回だけ ping する。{ms: 応答時間 or None（届かない）}"""
    host = host or prefs()["pingHost"]
    if not HOST_RE.fullmatch(host):
        raise SystemError_("ホスト名か IP アドレスを入れてください")
    args = ["ping", "-n", "1", "-w", "1500", host] if os.name == "nt" else ["ping", "-c", "1", "-W", "2", host]
    t0 = time.perf_counter()
    try:
        r = subprocess.run(args, capture_output=True, timeout=4, creationflags=NOWIN)
    except (OSError, subprocess.TimeoutExpired):
        return {"host": host, "ms": None}
    out = r.stdout.decode("mbcs" if os.name == "nt" else "utf-8", errors="replace")   # 日本語版 Windows は Shift_JIS で出る
    m = re.search(r"(?:time|時間)\s*[=<]\s*([\d.]+)\s*ms", out, re.I)       # 「time=12ms」「時間 =12ms」「time<1ms」
    if r.returncode != 0 or not m:
        return {"host": host, "ms": None}
    return {"host": host, "ms": float(m.group(1)), "wall": round((time.perf_counter() - t0) * 1000)}


def status() -> dict | None:
    """バー用（設定で ON のときだけ）。"""
    if not prefs()["bar"]:
        return None
    ps = _ps()
    return {"icon": "gauge", "metric": True,
            "items": [["CPU", f"{round(ps.cpu_percent(interval=None))}%"], ["MEM", f"{round(ps.virtual_memory().percent)}%"]]}
