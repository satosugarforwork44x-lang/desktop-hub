"""timer/api.py — 1 本だけのシンプルなタイマー。

状態は Hub の保存データに置くので、窓を閉じても・Hub を再起動しても続く。
  running: end（終わる時刻, epoch 秒）を持つ
  paused : remain（残り秒）を持つ
終わったあと DONE_KEEP 秒はバーに「終了」を出し、その後は消える。
"""
from __future__ import annotations

import time

_ctx = None
DONE_KEEP = 10 * 60
MAX_MIN = 24 * 60


class TimerError(Exception):
    pass


def setup(ctx):
    global _ctx
    _ctx = ctx


def _get() -> dict | None:
    return _ctx.store.get("timer", "state", None)


def _set(s: dict | None) -> dict | None:
    _ctx.store.set("timer", "state", s)
    return state()


def state(now: float | None = None) -> dict | None:
    """画面用。{label, total, end|None, remain, paused, done} / 止まっていれば None"""
    s = _get()
    if not s:
        return None
    now = time.time() if now is None else now
    if s.get("end"):
        remain = max(0.0, s["end"] - now)
        return {**s, "remain": remain, "paused": False, "done": remain <= 0}
    return {**s, "paused": True, "done": False}


def start(minutes: float, label: str = "") -> dict | None:
    try:
        minutes = float(minutes)
    except (TypeError, ValueError):
        raise TimerError("分を数字で指定する") from None
    if not 0 < minutes <= MAX_MIN:
        raise TimerError("1 秒〜24 時間で指定する")
    total = minutes * 60
    return _set({"label": (label or "").strip()[:40], "total": total, "end": time.time() + total, "remain": total})


def pause() -> dict | None:
    s = state()
    if not s or s["paused"] or s["done"]:
        return s
    return _set({"label": s["label"], "total": s["total"], "end": None, "remain": s["remain"]})


def resume() -> dict | None:
    s = state()
    if not s or not s["paused"]:
        return s
    return _set({"label": s["label"], "total": s["total"], "end": time.time() + s["remain"], "remain": s["remain"]})


def reset() -> None:
    _set(None)


def status() -> dict | None:
    """バー用。bar.js は countdown=True のとき end まで 1 秒ごとに数える。"""
    s = state()
    if not s:
        return None
    if s["done"] and time.time() - s["end"] > DONE_KEEP:
        _set(None)
        return None
    return {"icon": "timer", "prefix": s["label"], "countdown": True,
            "end": s["end"], "remain": s["remain"], "paused": s["paused"], "done": s["done"]}
