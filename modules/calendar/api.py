"""calendar/api.py — 予定（iCal 形式）を読み取り専用で表示する。

考え方:
  ・Google カレンダー / Outlook.com / iCloud の「iCal 形式の非公開 URL」を貼るだけで使える（OAuth 不要）
  ・読み取り専用。予定の作成・編集はそれぞれのサービスで行う
  ・取得に失敗したら、前回取れた内容（data/calendar/cache.ics）で表示を続ける（オフライン対策）
  ・URL は設定ファイル（modules.calendar.urls）か、パネルから登録したもの（store）を使う
"""
from __future__ import annotations

import time
import urllib.request
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dateutil.rrule import rrulestr
from icalendar import Calendar

_ctx = None
REFRESH_SEC = 10 * 60      # 10分ごとに取り直す
LOOKAHEAD_DAYS = 14        # 何日先まで展開するか
_cache: dict = {"at": 0.0, "events": [], "error": ""}


class CalendarError(Exception):
    pass


def setup(ctx):
    global _ctx
    _ctx = ctx
    if ctx and ctx.data_dir:
        Path(ctx.data_dir).mkdir(parents=True, exist_ok=True)


# ---------- 設定 ----------
def _urls() -> list[str]:
    cfg = list((_ctx.config or {}).get("urls", [])) if _ctx else []
    saved = _ctx.store.get("calendar", "urls", []) if _ctx else []
    return [u for u in dict.fromkeys(cfg + list(saved or [])) if u]


def set_urls(urls: list[str]) -> dict:
    """パネルから iCal URL を登録する（設定ファイルの分は消さない）。"""
    clean = [u.strip() for u in urls if isinstance(u, str) and u.strip()]
    for u in clean:
        if not (u.startswith(("https://", "http://", "webcal://")) or Path(u).suffix.lower() == ".ics"):
            raise CalendarError(f"iCal の URL（https://…）か .ics ファイルを指定してください: {u}")
    _ctx.store.set("calendar", "urls", clean)
    _cache["at"] = 0.0
    return {"urls": _urls()}


# ---------- 取得 ----------
def _fetch(src: str) -> bytes:
    if src.startswith("webcal://"):
        src = "https://" + src[len("webcal://"):]
    if src.startswith(("https://", "http://")):
        req = urllib.request.Request(src, headers={"User-Agent": "Hub-calendar/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read()
    return Path(src).expanduser().read_bytes()


def _local(dt) -> tuple[datetime, bool]:
    """iCal の日時 → (ローカル時刻の naive datetime, 終日か)。"""
    if isinstance(dt, datetime):
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        return dt, False
    return datetime(dt.year, dt.month, dt.day), True  # date = 終日


def parse_ics(data: bytes, now: datetime | None = None, days: int = LOOKAHEAD_DAYS) -> list[dict]:
    """ics の中身 → 期間内の予定（繰り返しは展開済み）。テストしやすいよう純粋関数にしている。"""
    now = now or datetime.now()
    win_start, win_end = now - timedelta(days=1), now + timedelta(days=days)
    cal = Calendar.from_ical(data)
    overridden: set[tuple[str, datetime]] = set()
    singles, recurring = [], []
    for ev in cal.walk("VEVENT"):
        if str(ev.get("STATUS", "")).upper() == "CANCELLED":
            continue
        if ev.get("RECURRENCE-ID"):
            overridden.add((str(ev.get("UID")), _local(ev.decoded("RECURRENCE-ID"))[0]))
            singles.append(ev)
        elif ev.get("RRULE"):
            recurring.append(ev)
        else:
            singles.append(ev)

    out: list[dict] = []

    def add(ev, start: datetime, all_day: bool, dur: timedelta):
        end = start + dur
        if end < win_start or start > win_end:
            return
        out.append({
            "uid": str(ev.get("UID", "")),
            "title": str(ev.get("SUMMARY", "")).strip() or "(no title)",
            "location": str(ev.get("LOCATION", "")).strip(),
            "start": start.isoformat(timespec="minutes"),
            "end": end.isoformat(timespec="minutes"),
            "allDay": all_day,
        })

    def duration(ev, start, all_day) -> timedelta:
        if ev.get("DTEND"):
            return _local(ev.decoded("DTEND"))[0] - start
        if ev.get("DURATION"):
            return ev.decoded("DURATION")
        return timedelta(days=1) if all_day else timedelta(0)

    for ev in singles:
        if not ev.get("DTSTART"):
            continue
        start, all_day = _local(ev.decoded("DTSTART"))
        add(ev, start, all_day, duration(ev, start, all_day))

    for ev in recurring:
        start, all_day = _local(ev.decoded("DTSTART"))
        dur = duration(ev, start, all_day)
        rule = ev.get("RRULE").to_ical().decode()
        # UNTIL が UTC 指定（…Z）でも、ローカルの naive 時刻と比べられるようにする
        if "UNTIL=" in rule:
            parts = []
            for p in rule.split(";"):
                if p.startswith("UNTIL=") and p.endswith("Z"):
                    u = datetime.strptime(p[6:], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
                    p = "UNTIL=" + u.astimezone().replace(tzinfo=None).strftime("%Y%m%dT%H%M%S")
                parts.append(p)
            rule = ";".join(parts)
        try:
            occ = rrulestr(rule, dtstart=start).between(win_start - dur, win_end, inc=True)
        except (ValueError, TypeError):
            continue  # 解釈できない繰り返し規則は飛ばす（他の予定は表示する）
        exdates: set[datetime] = set()
        ex = ev.get("EXDATE")
        for exl in (ex if isinstance(ex, list) else [ex] if ex else []):
            for d in exl.dts:
                exdates.add(_local(d.dt)[0])
        uid = str(ev.get("UID"))
        for s in occ:
            if s in exdates or (uid, s) in overridden:
                continue
            add(ev, s, all_day, dur)

    out.sort(key=lambda e: (e["start"], not e["allDay"]))
    return out


def _load(force: bool = False) -> None:
    if not force and time.time() - _cache["at"] < REFRESH_SEC:
        return
    urls = _urls()
    cache_file = Path(_ctx.data_dir) / "cache.json" if _ctx and _ctx.data_dir else None
    events, errors = [], []
    for u in urls:
        try:
            events += parse_ics(_fetch(u))
        except Exception as e:  # 1つ失敗しても他のカレンダーは表示する
            errors.append(f"{type(e).__name__}: {e}")
    if urls and errors and not events and cache_file and cache_file.exists():
        events = json.loads(cache_file.read_text(encoding="utf-8"))  # オフライン時は前回の内容
    elif cache_file and events:
        cache_file.write_text(json.dumps(events, ensure_ascii=False), encoding="utf-8")
    events.sort(key=lambda e: (e["start"], not e["allDay"]))
    _cache.update(at=time.time(), events=events, error="; ".join(errors))


# ---------- 公開関数 ----------
def upcoming(days: int = 7, refresh: bool = False) -> dict:
    """パネル用: これから days 日分の予定。"""
    _load(force=refresh)
    now = datetime.now()
    limit = (now + timedelta(days=days)).isoformat(timespec="minutes")
    today = now.date().isoformat()
    items = [e for e in _cache["events"]
             if (e["end"] > now.isoformat(timespec="minutes") or (e["allDay"] and e["start"][:10] >= today))
             and e["start"] < limit]
    return {"events": items, "configured": bool(_urls()), "error": _cache["error"], "urls": _urls()}


def status() -> dict | None:
    """バー用: 次の予定（終日の予定は除く）。予定が無ければ None。"""
    _load()
    now = datetime.now().isoformat(timespec="minutes")
    nxt = next((e for e in _cache["events"] if not e["allDay"] and e["end"] > now), None)
    if not nxt:
        return None
    return {"icon": "calendar", "prefix": "next", "at": nxt["start"], "text": nxt["title"],
            "detail": nxt["location"], "live": nxt["start"] <= now}
