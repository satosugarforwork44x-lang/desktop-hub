"""folders/api.py — フォルダ管理（フォルダ窓）。

考え方:
  ・「レジストリ」= 設定の root 直下にある1つのフォルダ。1レジストリ = 1パネル窓
    （既存の C:/.../registries/<名前> フォルダをそのまま使えるので、移行作業が要らない）
  ・移動は上書きしない（同名があれば「名前 (2)」にする）
  ・移動は「元に戻す」で取り消せる（レジストリごとに直近30回分）
  ・削除はごみ箱へ（完全削除しない）
"""
from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

_ctx = None
HISTORY_MAX = 30


class FolderError(Exception):
    pass



def _pip(pkg: str) -> str:
    """入れ方の案内。`py` だけだと最新の Python（3.15 など）に入ってしまうので、今 Hub を動かしている Python を名指しする。"""
    exe = sys.executable.replace("pythonw.exe", "python.exe")
    return f'"{exe}" -m pip install --user {pkg}'

def setup(ctx):
    global _ctx
    _ctx = ctx
    root = _root()
    root.mkdir(parents=True, exist_ok=True)
    # 初回: 空なら最初のフォルダ窓を1つ作っておく（バーに何も無い状態を避ける）
    if not any(d.is_dir() and not d.name.startswith(("_", ".")) for d in root.iterdir()):
        (root / "Inbox").mkdir(exist_ok=True)


def _root() -> Path:
    root = (_ctx.config or {}).get("root") if _ctx else None
    if not root:
        raise FolderError("hub.config.json の modules.folders.root にフォルダの場所を設定してください")
    return Path(root).expanduser()


def _reg_dir(registry: str) -> Path:
    if not registry or registry.startswith(("_", ".")) or "/" in registry or "\\" in registry:
        raise FolderError(f"レジストリ名が不正: {registry}")
    d = _root() / registry
    if not d.is_dir():
        raise FolderError(f"レジストリ「{registry}」が見つからない")
    return d


def _inside(registry: str, rel: str = "") -> Path:
    """レジストリ内の相対パス → 実パス。外に出るパスは拒否する。"""
    base = _reg_dir(registry).resolve()
    p = (base / rel).resolve() if rel else base
    try:
        p.relative_to(base)
    except ValueError:
        raise FolderError("レジストリの外は操作できない")
    return p


def _rel(registry: str, p: Path) -> str:
    return p.resolve().relative_to(_reg_dir(registry).resolve()).as_posix()


def _unique(dest: Path) -> Path:
    """同名があれば「名前 (2).拡張子」…と番号を付ける（上書き防止）。"""
    if not dest.exists():
        return dest
    stem, suffix = (dest.name, "") if dest.is_dir() else (dest.stem, dest.suffix)
    i = 2
    while True:
        cand = dest.with_name(f"{stem} ({i}){suffix}")
        if not cand.exists():
            return cand
        i += 1


def _move(src: Path, dest_dir: Path) -> Path:
    if not src.exists():
        raise FolderError(f"見つからない: {src}")
    if src.is_dir():
        try:  # 自分自身の中への移動を防ぐ
            dest_dir.resolve().relative_to(src.resolve())
            raise FolderError("フォルダを自分自身の中には移動できない")
        except ValueError:
            pass
    if src.parent.resolve() == dest_dir.resolve():
        return src  # 同じ場所なら何もしない
    dest = _unique(dest_dir / src.name)
    shutil.move(str(src), str(dest))
    return dest


def _push_history(registry: str, batch: list[dict]) -> None:
    if not batch:
        return
    hist = _ctx.store.get("history", registry, [])
    hist.append({"t": time.time(), "moves": batch})
    _ctx.store.set("history", registry, hist[-HISTORY_MAX:])


# ================= 公開関数（manifest.exports に載せたものだけ画面から呼べる） =================

def instances() -> list[dict]:
    """バーに並べるレジストリの一覧。"""
    root = _root()
    names = sorted(d.name for d in root.iterdir() if d.is_dir() and not d.name.startswith(("_", ".")))
    return [{"id": n, "label": n} for n in names]


def create_registry(name: str) -> dict:
    name = (name or "").strip()
    if not name or any(c in name for c in '\\/:*?"<>|') or name.startswith(("_", ".")):
        raise FolderError("使えない名前（\\ / : * ? \" < > | と先頭の _ . は不可）")
    d = _root() / name
    if d.exists():
        raise FolderError(f"「{name}」は既にある")
    d.mkdir(parents=True)
    return {"id": name}


def adopt_folders(paths: list[str], names: list[str] | None = None) -> dict:
    """フォルダの一覧の窓にエクスプローラーからフォルダを落としたとき: そのフォルダをフォルダ窓の置き場所へ移し、
    新しいフォルダ窓にする（ほかの場所にあるフォルダをバーから使えるように）。ファイルは受け取らない。"""
    root = _root()
    added, errors = [], []
    for raw in _top_level(paths, names):
        src = Path(raw)
        if not src.is_dir():
            errors.append(f"{src.name}: フォルダだけを登録できます")
            continue
        if src.name.startswith(("_", ".")):
            errors.append(f"{src.name}: 先頭が _ . の名前はフォルダ窓にできません")
            continue
        try:
            root.resolve().relative_to(src.resolve())
            errors.append(f"{src.name}: フォルダ窓の置き場所を含むフォルダは移せません")
            continue
        except ValueError:
            pass
        try:
            dest = _move(src, root)
            added.append(dest.name)
        except (FolderError, OSError) as e:
            errors.append(f"{src.name}: {e}")
    return {"added": added, "errors": errors}


def list_dir(registry: str, rel: str = "") -> dict:
    """フォルダの中身（1階層だけ。開いたときに読み込む）。フォルダが先、名前順。"""
    d = _inside(registry, rel)
    if not d.is_dir():
        raise FolderError("フォルダではない")
    items = []
    for p in d.iterdir():
        if p.name.startswith(".") or p.name.lower() in ("desktop.ini", "thumbs.db"):
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        items.append({"name": p.name, "rel": _rel(registry, p), "dir": p.is_dir(),
                      "ext": p.suffix.lower().lstrip("."), "size": st.st_size, "mtime": st.st_mtime})
    items.sort(key=lambda i: (not i["dir"], i["name"].lower()))
    return {"registry": registry, "rel": rel, "path": str(d), "items": items,
            "undo": len(_ctx.store.get("history", registry, []))}


def _top_level(paths: list[str], names: list[str] | None) -> list[str]:
    """ドロップされた「いちばん上の項目」のパスに直す。
    Windows の画面部品（WebView2）は、フォルダを落とすとフォルダではなく中のファイルを渡すことがある。
    そのままだと中身だけがばらばらに移るので、画面側で分かる項目名（names）を手がかりに、そのフォルダ自身に戻す。"""
    if not names:
        return list(paths or [])
    want = set(names)
    out: list[str] = []
    for raw in paths or []:
        p = Path(raw)
        hit = next((a for a in [p, *p.parents] if a.name in want), None)
        cand = str(hit) if hit is not None else str(p)
        if cand not in out:
            out.append(cand)
    # ほかの項目の中にあるもの（フォルダとその中身の両方が届いたとき）は除く
    return [c for c in out if not any(c != o and Path(c).is_relative_to(o) for o in out)]


def move_in(registry: str, paths: list[str], dest_rel: str = "", names: list[str] | None = None) -> dict:
    """外（エクスプローラー等）からドロップされたファイル・フォルダを移動して取り込む。
    names: 画面で分かった「落とした項目の名前」（フォルダを中身でなくフォルダごと移すため）。"""
    paths = _top_level(paths, names)
    dest_dir = _inside(registry, dest_rel)
    if not dest_dir.is_dir():
        dest_dir = dest_dir.parent  # ファイル行に落とした場合はそのファイルのあるフォルダへ
    batch, moved, errors = [], [], []
    for raw in paths or []:
        src = Path(raw)
        try:
            dest = _move(src, dest_dir)
            if dest != src:
                batch.append({"from": str(src), "to": str(dest)})
                moved.append(dest.name)
        except (FolderError, OSError) as e:
            errors.append(f"{src.name}: {e}")
    _push_history(registry, batch)
    return {"moved": moved, "errors": errors}


def move_within(registry: str, rels: list[str], dest_rel: str = "") -> dict:
    """同じレジストリ内での移動（パネル内のドラッグ）。"""
    return move_in(registry, [str(_inside(registry, r)) for r in rels], dest_rel)


def move_to(registry: str, rels: list[str], target: str) -> dict:
    """別のレジストリの一番上へ移動する（右クリック→移動先）。"""
    dest_dir = _reg_dir(target)
    batch, moved, errors = [], [], []
    for r in rels:
        src = _inside(registry, r)
        try:
            dest = _move(src, dest_dir)
            batch.append({"from": str(src), "to": str(dest)})
            moved.append(dest.name)
        except (FolderError, OSError) as e:
            errors.append(f"{src.name}: {e}")
    _push_history(registry, batch)
    return {"moved": moved, "errors": errors}


def undo(registry: str) -> dict:
    """直前の移動をまとめて元に戻す。"""
    hist = _ctx.store.get("history", registry, [])
    if not hist:
        return {"restored": [], "errors": ["元に戻せる操作はない"]}
    batch = hist.pop()
    restored, errors = [], []
    for m in reversed(batch["moves"]):
        cur, orig = Path(m["to"]), Path(m["from"])
        try:
            orig.parent.mkdir(parents=True, exist_ok=True)
            dest = _unique(orig)
            shutil.move(str(cur), str(dest))
            restored.append(dest.name)
        except OSError as e:
            errors.append(f"{cur.name}: {e}")
    _ctx.store.set("history", registry, hist)
    return {"restored": restored, "errors": errors}


def rename(registry: str, rel: str, new_name: str) -> dict:
    new_name = (new_name or "").strip()
    if not new_name or any(c in new_name for c in '\\/:*?"<>|'):
        raise FolderError("使えない名前")
    src = _inside(registry, rel)
    dest = src.with_name(new_name)
    if dest.exists():
        raise FolderError(f"「{new_name}」は既にある")
    src.rename(dest)
    _push_history(registry, [{"from": str(src), "to": str(dest)}])
    return {"rel": _rel(registry, dest)}


def make_folder(registry: str, rel: str = "", name: str = "新しいフォルダ") -> dict:
    parent = _inside(registry, rel)
    if not parent.is_dir():
        parent = parent.parent
    d = _unique(parent / name)
    d.mkdir()
    return {"rel": _rel(registry, d)}


def new_note(registry: str, rel: str = "") -> dict:
    """その場所に空のメモ（メモ 2026-10-17.md）を作る。開いて書くのは Hub のビューア。"""
    parent = _inside(registry, rel)
    if not parent.is_dir():
        parent = parent.parent
    p = _unique(parent / f"メモ {time.strftime('%Y-%m-%d')}.md")
    p.write_text("", encoding="utf-8")
    return {"rel": _rel(registry, p), "path": str(p)}


def trash(registry: str, rels: list[str]) -> dict:
    """ごみ箱へ送る。send2trash が無い環境では root/_to_delete へ移す（完全削除はしない）。"""
    done, errors = [], []
    for r in rels:
        p = _inside(registry, r)
        if p == _reg_dir(registry).resolve():
            errors.append("レジストリ自体は削除できない")
            continue
        try:
            try:
                from send2trash import send2trash
                send2trash(str(p))
            except ImportError:
                bin_dir = _root() / "_to_delete"
                bin_dir.mkdir(exist_ok=True)
                shutil.move(str(p), str(_unique(bin_dir / p.name)))
            done.append(p.name)
        except OSError as e:
            errors.append(f"{p.name}: {e}")
    return {"trashed": done, "errors": errors}


def search(query: str, registry: str | None = None, limit: int = 50) -> list[dict]:
    """名前に query を含むファイル・フォルダを探す（大文字小文字は区別しない）。registry を省くと全部から探す。"""
    q = (query or "").strip().lower()
    if not q:
        raise FolderError("探す言葉が空")
    regs = [registry] if registry else [r["id"] for r in instances()]
    out: list[dict] = []
    for reg in regs:
        base = _reg_dir(reg)
        for p in base.rglob("*"):
            if p.name.startswith(".") or p.name.lower() in ("desktop.ini", "thumbs.db"):
                continue
            if q in p.name.lower():
                out.append({"registry": reg, "rel": p.relative_to(base).as_posix(), "dir": p.is_dir()})
                if len(out) >= max(1, min(int(limit), 500)):
                    return out
    return out


# ---------- テキストファイルの読み書き（Claude などに成果物を書いてもらう用） ----------
TEXT_EXTS = {".md", ".txt", ".csv", ".tsv", ".json", ".jsonl", ".html", ".htm", ".xml", ".yaml", ".yml",
             ".ini", ".toml", ".log", ".py", ".js", ".ts", ".css", ".sql", ".bat", ".ps1", ".svg"}
READ_MAX = 2 * 1024 * 1024     # 読むのは 2MB まで
WRITE_MAX = 5 * 1024 * 1024    # 書くのは 5MB まで


def read_text(registry: str, rel: str, max_chars: int = 200_000) -> dict:
    """テキストファイルを読む（UTF-8 / UTF-8 BOM / Shift_JIS を順に試す）。大きいものは先頭だけ。"""
    p = _inside(registry, rel)
    if not p.is_file():
        raise FolderError("ファイルではない")
    if p.suffix.lower() == ".pdf":
        return _read_pdf_text(registry, p, max_chars)
    if p.suffix.lower() not in TEXT_EXTS:
        raise FolderError(f"テキストとして読めるのは {', '.join(sorted(TEXT_EXTS))} だけ")
    raw = p.read_bytes()[:READ_MAX]
    for enc in ("utf-8-sig", "cp932"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")
        enc = "utf-8(replace)"
    limit = max(1, min(int(max_chars), 1_000_000))
    return {"rel": _rel(registry, p), "encoding": enc, "truncated": len(text) > limit or p.stat().st_size > READ_MAX,
            "text": text[:limit]}


def _read_pdf_text(registry: str, p: Path, max_chars: int) -> dict:
    """PDF の文字を読む（ページごとに「--- p.N ---」で区切る）。
    文字が無いページ（スキャン）は読めないので、その旨と、OCR で作った .txt があればその名前を返す。"""
    try:
        import pymupdf
    except ImportError:
        raise FolderError("PDF を読むには PyMuPDF が必要（pip install pymupdf）")
    limit = max(1, min(int(max_chars), 1_000_000))
    doc = pymupdf.open(p)
    parts, empty, total = [], [], 0
    for i, page in enumerate(doc):
        t = page.get_text("text").strip()
        if len(t) < 3:  # 文字がほぼ無い = スキャンした画像のページ
            empty.append(i + 1)
        parts.append(f"--- p.{i + 1} ---\n{t}")
        total += len(parts[-1])
        if total > limit:
            break
    text = "\n\n".join(parts)
    out = {"rel": _rel(registry, p), "encoding": "pdf", "pages": doc.page_count, "truncated": len(text) > limit,
           "text": text[:limit]}
    if empty:
        txt = p.with_suffix(".txt")
        out["scannedPages"] = empty[:50]
        out["hint"] = (f"{len(empty)} page(s) have no text layer (scanned). "
                       + (f"An OCR text file exists: {_rel(registry, txt)}" if txt.exists()
                          else "Ask the user to run 'Convert to text' in Hub's PDF viewer (it OCRs scanned pages and saves a .txt next to the PDF)."))
    return out


def write_text(registry: str, rel: str, content: str, overwrite: bool = False) -> dict:
    """テキストファイルを書く（UTF-8）。途中のフォルダは作る。
    同名があるとき: overwrite=False なら「名前 (2)」で新しく作る。True なら古い方をごみ箱へ送ってから書く（元に戻せる）。"""
    p = _inside(registry, rel)
    if p.suffix.lower() not in TEXT_EXTS:
        raise FolderError(f"書けるのはテキスト形式（{', '.join(sorted(TEXT_EXTS))}）だけ")
    data = (content or "").encode("utf-8")
    if len(data) > WRITE_MAX:
        raise FolderError("大きすぎる（5MB まで）")
    p.parent.mkdir(parents=True, exist_ok=True)
    replaced = False
    if p.exists():
        if p.is_dir():
            raise FolderError("同じ名前のフォルダがある")
        if overwrite:
            r = trash(registry, [_rel(registry, p)])
            if r["errors"]:
                raise FolderError("古いファイルをごみ箱へ送れなかった: " + "; ".join(r["errors"]))
            replaced = True
        else:
            p = _unique(p)
    tmp = p.with_name(p.name + ".hubtmp")
    tmp.write_bytes(data)
    tmp.replace(p)  # 書き終えてから置き換える（途中で止まっても壊れたファイルを残さない）
    return {"rel": _rel(registry, p), "bytes": len(data), "replaced": replaced}


def full_path(registry: str, rel: str = "") -> str:
    """画面から「開く」「エクスプローラーで表示」に渡す実パス。"""
    return str(_inside(registry, rel))


# ---------- 画像を読む（Claude に見せるための縮小。書き込みはしない） ----------
IMAGE_EXTS = {".jpg", ".jpeg", ".jpe", ".jfif", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
RAW_EXTS = {".dng", ".cr2", ".cr3", ".nef", ".arw", ".raf", ".orf", ".rw2", ".pef", ".srw"}
IMAGE_MAX_BYTES = 200 * 1024 * 1024    # これより大きい元ファイルは読まない


def _open_raw(p: Path):
    """RAW は中に入っている JPEG（プレビュー）を使う。無いものだけ簡易に現像する（Claude に見せるだけなので速さ優先）。"""
    try:
        import rawpy
    except ImportError:
        raise FolderError(f"RAW を読むには rawpy が必要です: {_pip('rawpy')}") from None
    import io
    from PIL import Image
    with rawpy.imread(str(p)) as raw:
        try:
            th = raw.extract_thumb()
            if th.format == rawpy.ThumbFormat.JPEG:
                return Image.open(io.BytesIO(th.data))
            if th.format == rawpy.ThumbFormat.BITMAP:
                return Image.fromarray(th.data)
        except (rawpy.LibRawNoThumbnailError, rawpy.LibRawUnsupportedThumbnailError):
            pass
        return Image.fromarray(raw.postprocess(half_size=True, use_camera_wb=True))


def read_image(registry: str, rel: str, max_px: int = 1568) -> dict:
    """画像を、長辺が max_px（256〜2048）以下の JPEG にして返す（base64）。向き（EXIF）は直す。GIF は 1 枚目だけ。"""
    p = _inside(registry, rel)
    if not p.is_file():
        raise FolderError("ファイルではない")
    ext = p.suffix.lower()
    if ext not in IMAGE_EXTS | RAW_EXTS:
        raise FolderError(f"画像として読めるのは {', '.join(sorted(IMAGE_EXTS | RAW_EXTS))} だけ")
    if p.stat().st_size > IMAGE_MAX_BYTES:
        raise FolderError("画像が大きすぎる（200MB まで）")
    try:
        from PIL import Image, ImageOps
    except ImportError:
        raise FolderError(f"画像を読むには Pillow が必要です: {_pip('pillow')}") from None
    import base64
    import io
    max_px = max(256, min(2048, int(max_px)))
    im = _open_raw(p) if ext in RAW_EXTS else Image.open(p)   # 巨大画像の保護（DecompressionBomb）はそのまま
    with im:
        fmt = "RAW" if ext in RAW_EXTS else (im.format or ext[1:].upper())
        if getattr(im, "n_frames", 1) > 1:
            im.seek(0)                                          # 動く GIF・複数ページは 1 枚目
        im = ImageOps.exif_transpose(im)
        size = im.size
        if im.mode not in ("RGB", "L"):
            if "A" in im.mode or im.mode == "P":                # 透明な部分は白にする
                bg = Image.new("RGB", im.size, (255, 255, 255))
                im = im.convert("RGBA")
                bg.paste(im, mask=im.getchannel("A"))
                im = bg
            else:
                im = im.convert("RGB")
        im.thumbnail((max_px, max_px), Image.LANCZOS)
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=85, optimize=True)
    return {"rel": _rel(registry, p), "format": fmt, "width": size[0], "height": size[1],
            "sentWidth": im.size[0], "sentHeight": im.size[1], "mime": "image/jpeg",
            "data": base64.b64encode(buf.getvalue()).decode("ascii")}
