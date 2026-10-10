"""notes/api.py — メモと ToDo を 1 つにしたもの。

  ・1 行書いて Enter で追加。チェックを付けると ToDo（終わったら完了）
  ・画像（スクリーンショット）を貼り付けられる。画像は data/notes/ に保存する
  ・削除は直前の 1 件を元に戻せる
保存先は Hub の保存データ（hub.db）。並びは新しい順。
"""
from __future__ import annotations

import base64
import time
import uuid
from pathlib import Path

_ctx = None
MAX_ITEMS = 500
MAX_IMAGE = 8 * 1024 * 1024


class NotesError(Exception):
    pass


def setup(ctx):
    global _ctx
    _ctx = ctx
    _img_dir().mkdir(parents=True, exist_ok=True)


def _img_dir() -> Path:
    return Path(_ctx.data_dir) / "images"


def _load() -> list[dict]:
    return _ctx.store.get("notes", "items", []) or []


def _save(items: list[dict]) -> None:
    _ctx.store.set("notes", "items", items[:MAX_ITEMS])


def items() -> list[dict]:
    return _load()


def add(text: str = "", todo: bool = False, image: str | None = None) -> dict:
    text = (text or "").strip()
    if not text and not image:
        raise NotesError("空のメモは追加できない")
    item = {"id": uuid.uuid4().hex[:10], "text": text[:4000], "todo": bool(todo), "done": False,
            "image": image, "created": time.time()}
    _save([item] + _load())
    return item


def update(id: str, text: str | None = None, todo: bool | None = None, done: bool | None = None) -> dict:
    items_ = _load()
    for it in items_:
        if it["id"] == id:
            if text is not None:
                it["text"] = text.strip()[:4000]
            if todo is not None:
                it["todo"] = bool(todo)
                if not it["todo"]:
                    it["done"] = False
            if done is not None:
                it["done"] = bool(done) and it["todo"]
                it["doneAt"] = time.time() if it["done"] else None
            _save(items_)
            return it
    raise NotesError("見つからない")


def remove(id: str) -> dict:
    items_ = _load()
    keep = [i for i in items_ if i["id"] != id]
    gone = [i for i in items_ if i["id"] == id]
    _save(keep)
    _ctx.store.set("notes", "lastRemoved", gone)
    return {"removed": len(gone)}


def restore() -> dict:
    gone = _ctx.store.get("notes", "lastRemoved", []) or []
    if gone:
        _save(sorted(gone + _load(), key=lambda i: -i["created"]))
        _ctx.store.set("notes", "lastRemoved", [])
    return {"restored": len(gone)}


def clear_done() -> dict:
    items_ = _load()
    gone = [i for i in items_ if i.get("todo") and i.get("done")]
    _save([i for i in items_ if i not in gone])
    _ctx.store.set("notes", "lastRemoved", gone)
    return {"removed": len(gone)}


def add_image(data_url: str, text: str = "") -> dict:
    """貼り付けた画像（data:image/png;base64,...）を保存して、画像のメモを作る。"""
    head, _, b64 = (data_url or "").partition(",")
    ext = {"data:image/png;base64": "png", "data:image/jpeg;base64": "jpg", "data:image/gif;base64": "gif",
           "data:image/webp;base64": "webp"}.get(head)
    if not ext:
        raise NotesError("貼り付けられるのは PNG / JPEG / GIF / WebP の画像だけ")
    raw = base64.b64decode(b64)
    if len(raw) > MAX_IMAGE:
        raise NotesError("画像が大きすぎる（8MB まで）")
    name = f"{uuid.uuid4().hex[:12]}.{ext}"
    (_img_dir() / name).write_bytes(raw)
    return add(text=text, image=name)


def image_path(name: str) -> Path:
    """画面に画像を渡す（server.py の /blob/notes/<name>）。保存場所の外は渡さない。"""
    p = (_img_dir() / name).resolve()
    if p.parent != _img_dir().resolve():
        raise NotesError("不正な名前")
    return p
