"""pdf/api.py — ビューア（PDF と画像）。見る・画像にする・テキストにする。

  ・画像（PNG / JPEG / GIF / WebP / BMP / TIFF）も同じ窓で見られる。
    TIFF は WebView2 が表示できないので、Pillow で PNG にしてから渡す（複数ページの TIFF も 1 ページずつ）

  ・見る     … 画面側（ui/viewer.js）が PDF.js で描く。Python は「開いてよいファイル」の受け渡しだけ
  ・画像にする … cli.py（manifest の actions。L1 の仕組みをそのまま使う）
  ・テキストにする … PyMuPDF で文字を取り出す。文字が無いページ（スキャン）は OCR する
        OCR は ① Windows 標準の OCR（追加のインストール不要。Windows の言語に日本語があれば日本語も読める）
              ② Tesseract（入っていれば）の順に使う
  ・「プログラムから開く」への登録 … 自分のユーザーの範囲（HKCU）だけに書く。管理者権限は不要

開いてよいのは、利用者がドロップ・選択・関連付けで開いた PDF だけ（open_doc で登録したもの）。
画面からは id（key）でしか指せないので、他のファイルを勝手に読まれることはない。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_ctx = None
RECENT_MAX = 30
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".jpe", ".jfif", ".gif", ".webp", ".bmp", ".tif", ".tiff"}
MD_EXTS = {".md", ".markdown"}
TEXT_EXTS = {".txt", ".text"}
RTF_EXTS = {".rtf"}
MD_MAX_BYTES = 5 * 1024 * 1024          # これより大きい文章は読まない（表示が重くなる）
OFFICE_EXTS = {".docx", ".xlsx", ".pptx"}
DOC_EXTS = {".pdf"} | IMAGE_EXTS | MD_EXTS | TEXT_EXTS | RTF_EXTS | OFFICE_EXTS
WRITABLE = MD_EXTS | TEXT_EXTS          # 「書く」で直せる種類（rtf は書式を壊すので読むだけ）
NEEDS_PNG = {".tif", ".tiff"}          # WebView2 で直接表示できない形式


class PdfError(Exception):
    pass


def setup(ctx):
    global _ctx
    _ctx = ctx


# ---------- 開いた PDF の登録 ----------
def _key(path: Path) -> str:
    return hashlib.sha1(str(path).lower().encode("utf-8")).hexdigest()[:12]


def _docs() -> dict:
    return _ctx.store.get("pdf", "docs", {}) or {}


def _path_of(key: str) -> Path:
    d = _docs().get(key)
    if not d:
        raise PdfError("この PDF は開かれていない（もう一度開いてください）")
    p = Path(d["path"])
    if not p.is_file():
        raise PdfError(f"ファイルが見つからない: {p}")
    return p


def _kind(p: Path) -> str:
    ext = p.suffix.lower()
    if ext == ".pdf":
        return "pdf"
    if ext in MD_EXTS:
        return "md"
    if ext in TEXT_EXTS:
        return "text"
    if ext in RTF_EXTS:
        return "rtf"
    if ext in OFFICE_EXTS:
        return "office"
    return "image"


def _decode(raw: bytes) -> tuple[str, str]:
    """(文字, 文字コード)。メモ帳の保存形式（UTF-8・BOM 付き・UTF-16・日本語の Windows の cp932）を見分ける。"""
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16"), "utf-16"
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="replace"), "utf-8-sig"
    for enc in ("utf-8", "cp932"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8"


_RTF_SKIP = {"fonttbl", "colortbl", "stylesheet", "info", "pict", "header", "footer", "listtable",
             "listoverridetable", "themedata", "colorschememapping", "latentstyles", "datastore", "xmlnstbl",
             "rsidtbl", "generator", "object", "filetbl", "revtbl"}


def rtf_to_text(rtf: str) -> str:
    """RTF から文字だけを取り出す（書式は捨てる）。日本語（\\'hh の cp932、\\u の Unicode）にも対応。"""
    import re
    m = re.search(r"\\ansicpg(\d+)", rtf)
    codepage = f"cp{m.group(1)}" if m else "cp932"
    out: list[str] = []
    pend = bytearray()                       # \'hh を貯めて、まとめて文字にする（2 バイト文字のため）
    stack: list[tuple[bool, int]] = []
    skip, uc, drop = False, 1, 0
    def flush():
        if pend:
            out.append(pend.decode(codepage, errors="replace"))
            pend.clear()
    i, n = 0, len(rtf)
    while i < n:
        c = rtf[i]
        if c == "{":
            flush(); stack.append((skip, uc)); i += 1
        elif c == "}":
            flush(); skip, uc = stack.pop() if stack else (False, 1); i += 1
        elif c == "\\":
            if i + 1 < n and rtf[i + 1] in "\\{}":
                flush(); drop = 0
                if not skip: out.append(rtf[i + 1])
                i += 2; continue
            if i + 1 < n and rtf[i + 1] == "'":
                if drop: drop -= 1
                elif not skip: pend += bytes([int(rtf[i + 2:i + 4], 16)])
                i += 4; continue
            if i + 1 < n and rtf[i + 1] == "*":
                skip = True; i += 2; continue
            m = re.match(r"\\([a-zA-Z]+)(-?\d+)? ?", rtf[i:])
            if not m:
                i += 2; continue
            word, arg = m.group(1), m.group(2)
            i += m.end()
            flush()
            if word in _RTF_SKIP:
                skip = True
            elif word == "uc":
                uc = int(arg or 1)
            elif word == "u" and not skip:
                v = int(arg); out.append(chr(v + 65536 if v < 0 else v)); drop = uc
            elif not skip and word in ("par", "line", "sect", "row"):
                out.append("\n")
            elif not skip and word == "tab":
                out.append("\t")
        elif c in "\r\n":
            i += 1
        else:
            if drop:
                drop -= 1
            elif not skip:
                flush(); out.append(c)
            i += 1
    flush()
    return re.sub(r"\n{3,}", "\n\n", "".join(out)).strip() + "\n"


def _register(p: Path, derived: bool = False) -> str:
    key = _key(p)
    docs = _docs()
    docs[key] = {"path": str(p), "name": p.name, "opened": time.time(), "kind": _kind(p)}
    if derived:
        docs[key]["derived"] = True        # Office から作った PDF（「最近開いたもの」には出さない）
    if len(docs) > RECENT_MAX:  # 古いものから忘れる
        for k, _ in sorted(docs.items(), key=lambda kv: kv[1]["opened"])[: len(docs) - RECENT_MAX]:
            docs.pop(k)
    _ctx.store.set("pdf", "docs", docs)
    return key


def open_doc(path: str) -> dict:
    """PDF・画像・Markdown を開く。返り値の panel を host.openPanel に渡すとビューアの窓が開く。"""
    p = Path(path).expanduser()
    if p.suffix.lower() not in DOC_EXTS or not p.is_file():
        raise PdfError(f"開けない種類のファイル: {path}")
    p = p.resolve()
    key = _register(p)
    return {"key": key, "name": p.name, "panel": f"pdf:{key}", "kind": _kind(p)}


def neighbor(key: str, step: int = 1) -> dict:
    """同じフォルダの、前（step=-1）/ 次（step=1）の画像を開く（写真を順に見るため）。名前順でぐるっと回る。"""
    cur = _path_of(key)
    files = sorted((f for f in cur.parent.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTS),
                   key=lambda f: f.name.lower())
    if not files:
        raise PdfError("同じフォルダに画像がない")
    try:
        i = [f.name for f in files].index(cur.name)
    except ValueError:
        i = -1 if step > 0 else 0
    nxt = files[(i + (1 if step > 0 else -1)) % len(files)]
    k = _register(nxt.resolve())
    return {"key": k, "name": nxt.name, "index": files.index(nxt) + 1, "count": len(files)}


def read_text(key: str) -> dict:
    """Markdown・テキスト・RTF の中身（表示は画面の markdown.js）。RTF は文字だけにする。"""
    p = _path_of(key)
    kind = _kind(p)
    if kind not in ("md", "text", "rtf"):
        raise PdfError("文章のファイルではない")
    st = p.stat()
    if st.st_size > MD_MAX_BYTES:
        raise PdfError(f"大きすぎて表示できない（{MD_MAX_BYTES // 1048576}MB まで）")
    text, enc = _decode(p.read_bytes())
    if kind == "rtf":
        text = rtf_to_text(text)
    return {"text": text, "mtime": st.st_mtime, "folder": str(p.parent), "path": str(p), "kind": kind,
            "encoding": enc, "writable": p.suffix.lower() in WRITABLE}


def write_text(key: str, text: str, base_mtime: float) -> dict:
    """「書く」で直した文章を保存する。読んだ後に外で書き換えられていたら（Claude など）上書きせずに知らせる。
    文字コードと改行は元のファイルに合わせる（メモ帳で作った cp932 の txt を UTF-8 に変えてしまわない）。"""
    p = _path_of(key)
    if p.suffix.lower() not in WRITABLE:
        raise PdfError("この種類のファイルは書き換えられない")
    st = p.stat()
    if abs(st.st_mtime - float(base_mtime)) > 1e-3:
        return {"conflict": True, "mtime": st.st_mtime}
    raw = p.read_bytes()
    _, enc = _decode(raw)
    crlf = b"\r\n" in raw or (not raw and os.name == "nt")
    body = (text or "").replace("\r\n", "\n")
    if crlf:
        body = body.replace("\n", "\r\n")
    try:
        data = body.encode(enc)
    except UnicodeEncodeError:            # cp932 にない字（絵文字など）を書いたら UTF-8（BOM 付き）にする
        enc, data = "utf-8-sig", body.encode("utf-8-sig")
    tmp = p.with_name(f".{p.name}.hubtmp")
    tmp.write_bytes(data)
    os.replace(tmp, p)
    return {"conflict": False, "mtime": p.stat().st_mtime, "encoding": enc}


def mtime(key: str) -> float:
    """外で書き換えられたかを見る（Claude が書き直したときに自動で読み直すため）。"""
    return _path_of(key).stat().st_mtime


def open_path(path: str) -> str:
    """「プログラムから開く」などで渡された PDF を開き、開くべきパネルの id を返す（host から呼ぶ）。"""
    return open_doc(path)["panel"]


def instance_title(key: str) -> str:
    """窓のタイトル（タスクバーに出る名前）。"""
    d = _docs().get(key)
    return f"{d['name']} — Hub" if d else "Hub"


ASSET_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
ASSET_MAX = 30 * 1024 * 1024


def _asset_of(md: Path, rel: str) -> Path:
    """md から見た相対パスの画像（写真・手書き）。md のあるフォルダの外・画像以外は渡さない。"""
    base = md.parent.resolve()
    p = (base / rel).resolve()
    if not p.is_relative_to(base) or p.suffix.lower() not in ASSET_EXTS or not p.is_file():
        raise PdfError("表示できない画像")
    return p


def save_asset(data: bytes, key: str, ext: str = "png", kind: str = "img") -> dict:
    """メモに貼った写真・手書きを、md の横の「<名前>_files」フォルダに保存する（/upload/pdf/save_asset）。
    返す rel を md に ![](rel) で書く。保存先は Hub が決める（画面からパスは受け取らない）。"""
    md = _path_of(key)
    if md.suffix.lower() not in MD_EXTS:
        raise PdfError("写真と手書きは Markdown（.md）のメモで使えます")
    ext = "." + str(ext).lower().lstrip(".")
    if ext not in ASSET_EXTS:
        raise PdfError("貼れるのは png / jpg / gif / webp / svg の画像だけ")
    if len(data) > ASSET_MAX:
        raise PdfError(f"画像が大きすぎる（{ASSET_MAX // 1048576}MB まで）")
    if ext == ".svg":
        head = data[:4096].lower()
        if not head.lstrip().startswith((b"<svg", b"<?xml")) or b"<script" in data.lower():
            raise PdfError("手書きの形式が正しくない")
    d = md.parent / f"{md.stem}_files"
    d.mkdir(exist_ok=True)
    prefix = "ink" if kind == "ink" else "img"
    name = f"{prefix}-{time.strftime('%Y%m%d-%H%M%S')}{ext}"
    p, i = d / name, 2
    while p.exists():
        p, i = d / f"{prefix}-{time.strftime('%Y%m%d-%H%M%S')}-{i}{ext}", i + 1
    p.write_bytes(data)
    return {"rel": f"{d.name}/{p.name}"}


def blob_path(key: str) -> Path:
    """画面に渡すファイル。server.py の /blob/pdf/<key>（TIFF のページは <key>/<ページ番号>、
    メモの画像は <key>/a/<md から見た相対パス>）から呼ばれる。"""
    key, _, page = key.partition("/")
    p = _path_of(key)
    if page.startswith("a/"):
        return _asset_of(p, page[2:])
    if p.suffix.lower() in NEEDS_PNG:
        return _as_png(p, int(page or 1))
    return p


# ---------- Office（docx / xlsx / pptx） ----------
# docx は画面（docx-preview）で表示する。xlsx・pptx は LibreOffice があれば PDF にして PDF ビューアで、
# 無ければ文字だけ（host/office.py）を出す。LibreOffice は同梱しない（入っていれば使う。ffmpeg と同じ考え方）
def _soffice() -> Path | None:
    conf = (_ctx.config or {}).get("soffice") if _ctx else None
    cands = [conf] if conf else []
    for env in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(env)
        if base:
            cands.append(str(Path(base) / "LibreOffice" / "program" / "soffice.exe"))
    import shutil
    cands += [shutil.which("soffice"), shutil.which("libreoffice")]
    for c in cands:
        if c and Path(c).is_file():
            return Path(c)
    return None


def office_info() -> dict:
    """LibreOffice が使えるか（設定画面・ビューアの案内用）。"""
    s = _soffice()
    return {"libreoffice": bool(s), "path": str(s) if s else ""}


def office_text(key: str) -> dict:
    """Office の文字だけ（LibreOffice が無いときの簡易表示）。"""
    from host.office import OfficeError, office_text as _text
    p = _path_of(key)
    try:
        return {"text": _text(p), "name": p.name, "path": str(p), "mtime": p.stat().st_mtime}
    except OfficeError as e:
        raise PdfError(str(e)) from None


def office_to_pdf(key: str) -> dict:
    """LibreOffice で PDF にして、PDF ビューアで開ける key を返す。変換した PDF は元のファイルが変わるまで使い回す。"""
    p = _path_of(key)
    if p.suffix.lower() not in OFFICE_EXTS:
        raise PdfError("Office のファイルではない")
    soffice = _soffice()
    if not soffice:
        raise PdfError("LibreOffice が見つからない（入れると見た目どおりに表示できます）")
    st = p.stat()
    out_dir = _cache_dir() / "office" / f"{key}-{int(st.st_mtime)}-{st.st_size}"
    pdf = out_dir / (p.stem + ".pdf")
    if not pdf.is_file():
        out_dir.mkdir(parents=True, exist_ok=True)
        profile = (_cache_dir() / "office" / "lo-profile").resolve().as_uri()   # 開いている LibreOffice とぶつからないよう専用の設定で
        try:
            subprocess.run([str(soffice), f"-env:UserInstallation={profile}", "--headless", "--norestore",
                            "--convert-to", "pdf", "--outdir", str(out_dir), str(p)],
                           capture_output=True, timeout=180, creationflags=0x08000000 if os.name == "nt" else 0)
        except subprocess.TimeoutExpired:
            raise PdfError("変換に時間がかかりすぎた（3 分）") from None
        if not pdf.is_file():
            raise PdfError("LibreOffice で PDF にできなかった（壊れたファイル・パスワード付きの可能性）")
    return {"key": _register(pdf, derived=True), "name": p.name}


def _cache_dir() -> Path:
    d = Path(_ctx.data_dir) / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _as_png(p: Path, page: int) -> Path:
    """TIFF の 1 ページを PNG にする（作ったものは使い回す。元ファイルが変われば作り直す）。"""
    from PIL import Image, ImageOps
    st = p.stat()
    out = _cache_dir() / f"{_key(p)}-{int(st.st_mtime)}-{st.st_size}-p{page}.png"
    if not out.exists():
        for old in _cache_dir().glob(f"{_key(p)}-*-p{page}.png"):
            old.unlink(missing_ok=True)
        with Image.open(p) as im:
            im.seek(max(0, page - 1))
            frame = ImageOps.exif_transpose(im)
            if frame.mode not in ("RGB", "RGBA", "L", "LA"):
                frame = frame.convert("RGBA" if "A" in frame.mode else "RGB")  # 1bit・CMYK なども表示できる形に
            tmp = out.with_suffix(".tmp")
            frame.save(tmp, "PNG")
            tmp.replace(out)
    return out


def _image_info(p: Path) -> dict:
    try:
        from PIL import Image
        with Image.open(p) as im:
            return {"width": im.width, "height": im.height, "pages": getattr(im, "n_frames", 1) if p.suffix.lower() in NEEDS_PNG else 1,
                    "format": im.format or p.suffix[1:].upper()}
    except Exception:
        return {"pages": 1, "format": p.suffix[1:].upper()}


def doc_info(key: str) -> dict:
    p = _path_of(key)
    st = p.stat()
    info = {"key": key, "name": p.name, "folder": str(p.parent), "size": st.st_size, "mtime": st.st_mtime, "kind": _kind(p)}
    if info["kind"] == "image":
        info.update(_image_info(p))
    return info


def recent() -> list[dict]:
    out = []
    for k, d in sorted(_docs().items(), key=lambda kv: -kv[1]["opened"]):
        if d.get("derived"):
            continue
        out.append({"key": k, "name": d["name"], "folder": str(Path(d["path"]).parent), "kind": d.get("kind", "pdf"),
                    "opened": d["opened"], "exists": Path(d["path"]).is_file()})
    return out


def forget(key: str) -> dict:
    docs = _docs()
    docs.pop(key, None)
    _ctx.store.set("pdf", "docs", docs)
    return {"forgot": key}


def reveal_path(key: str) -> str:
    return str(_path_of(key))


# ---------- テキストにする（OCR つき） ----------
def _parse_pages(spec: str, count: int) -> list[int]:
    sys.path.insert(0, str(Path(__file__).parent))
    from cli import parse_pages  # 「画像にする」と同じページ指定の読み方
    try:
        return parse_pages(spec, count)
    except ValueError as e:
        raise PdfError(str(e))


_CJK = r"\u3000-\u30ff\u3400-\u9fff\uf900-\ufaff\uff00-\uffef"


def _tidy_ocr(text: str) -> str:
    """Windows の OCR は日本語の文字の間に空白を入れるので取り除く（英単語の間の空白は残す）。"""
    return re.sub(rf"(?<=[{_CJK}]) (?=[{_CJK}])", "", text)


WIN_OCR_PS = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType=WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType=WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, $type) { $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
$engine = $null
if ($env:HUB_OCR_LANG) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage((New-Object Windows.Globalization.Language $env:HUB_OCR_LANG)) }
if (-not $engine) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
if (-not $engine) { Write-Error 'NO_OCR_ENGINE'; exit 3 }
$out = @()
foreach ($path in (Get-Content -LiteralPath $env:HUB_OCR_LIST -Encoding UTF8)) {
  $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) ([Windows.Storage.StorageFile])
  $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
  $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
  $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
  $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
  $out += ,(($result.Lines | ForEach-Object { $_.Text }) -join "`n")
  $stream.Dispose()
}
$out | ConvertTo-Json -Compress
"""


def _windows_ocr(images: list[Path], lang: str | None) -> list[str] | None:
    """Windows 標準の OCR で画像を読む。使えなければ None。"""
    if os.name != "nt":
        return None
    with tempfile.TemporaryDirectory() as td:
        lst = Path(td) / "list.txt"
        lst.write_text("\n".join(str(p) for p in images), encoding="utf-8")
        env = {**os.environ, "HUB_OCR_LIST": str(lst), "HUB_OCR_LANG": lang or ""}
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", WIN_OCR_PS],
                               env=env, capture_output=True, timeout=60 + 20 * len(images), creationflags=0x08000000)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if r.returncode != 0:
            return None
        try:
            data = json.loads(r.stdout.decode("utf-8-sig").strip() or "[]")
        except ValueError:
            return None
        texts = data if isinstance(data, list) else [data]
        return [_tidy_ocr(t or "") for t in texts]


def _tesseract_ocr(page, lang: str) -> str | None:
    """Tesseract（入っていれば）で 1 ページ読む。"""
    try:
        tp = page.get_textpage_ocr(language=lang, dpi=300, full=True)
        return page.get_text(textpage=tp)
    except Exception:
        return None


def ocr_status() -> dict:
    """OCR が使えそうか（画面に案内を出すため）。実際に読めるかは試すまで分からない。"""
    tess = bool(os.environ.get("TESSDATA_PREFIX")) or any(
        Path(p).exists() for p in (r"C:\Program Files\Tesseract-OCR\tesseract.exe",))
    return {"windows": os.name == "nt", "tesseract": tess}


def extract_text(key: str, pages: str = "all", ocr: str = "auto", lang: str = "") -> dict:
    """PDF（または画像）をテキストにして、同じ場所に「<名前>.txt」で保存する（同名があれば「名前 (2).txt」）。
    ocr: auto（文字が無いページだけ OCR）/ off（OCR しない）/ force（全ページ OCR）。画像は常に OCR"""
    import pymupdf
    pdf = _path_of(key)
    doc = pymupdf.open(pdf)          # PyMuPDF は画像（複数ページの TIFF も）を「ページ」として開ける
    if _kind(pdf) == "image":
        ocr = "force"
    idx = _parse_pages(pages, doc.page_count)
    texts: dict[int, str] = {}
    need_ocr: list[int] = []
    for i in idx:
        t = doc[i].get_text("text") if ocr != "force" else ""
        texts[i] = t
        if ocr != "off" and len(t.strip()) < 3:  # 文字がほぼ無い = スキャンした画像のページ
            need_ocr.append(i)

    engine = ""
    if need_ocr:
        with tempfile.TemporaryDirectory() as td:
            imgs = []
            for i in need_ocr:
                pix = doc[i].get_pixmap(dpi=220, alpha=False)
                img = Path(td) / f"p{i + 1:04d}.png"
                pix.save(str(img))
                imgs.append(img)
            got = _windows_ocr(imgs, lang or None)
            if got is not None and len(got) == len(need_ocr):
                engine = "windows"
                for i, t in zip(need_ocr, got):
                    texts[i] = t
            else:
                ok = 0
                for i in need_ocr:
                    t = _tesseract_ocr(doc[i], "jpn+eng" if not lang or lang.startswith("ja") else "eng")
                    if t is not None:
                        texts[i] = t
                        ok += 1
                engine = "tesseract" if ok else ""
    missing = [i + 1 for i in need_ocr if len(texts[i].strip()) < 3]

    body = "\n\n".join(f"--- p.{i + 1} ---\n{texts[i].strip()}" for i in idx)
    target = pdf.with_suffix(".txt")
    n = 2
    while target.exists():
        target = pdf.with_name(f"{pdf.stem} ({n}).txt")
        n += 1
    target.write_text(body + "\n", encoding="utf-8")
    return {"path": str(target), "name": target.name, "pages": len(idx), "ocrPages": [i + 1 for i in need_ocr],
            "engine": engine, "unreadPages": missing, "chars": len(body)}


# ---------- 「プログラムから開く」への登録（Windows・HKCU） ----------
PROGID = "Hub.PDF"          # 名前は前の版のまま（登録済みの環境をそのまま使えるように）。画像もこれで開く


def _command() -> str:
    root = Path(__file__).resolve().parent.parent.parent
    pyw = Path(sys.executable).with_name("pythonw.exe")
    exe = pyw if pyw.exists() else Path(sys.executable)
    return f'"{exe}" "{root / "hub.py"}" --open "%1"'


def association() -> dict:
    if os.name != "nt":
        return {"supported": False, "registered": False}
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROGID}\shell\open\command") as k:
            cmd = winreg.QueryValueEx(k, "")[0]
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\.txt\OpenWithProgids") as k:
            winreg.QueryValueEx(k, PROGID)          # 新しく足した種類（.txt）の登録がない（前の版で登録した）なら、登録し直しを促す
        return {"supported": True, "registered": True, "current": cmd == _command()}
    except OSError:
        return {"supported": True, "registered": False}


def set_association(on: bool) -> dict:
    """PDF・画像・Markdown の「プログラムから開く」に Hub を出す（on=True）／消す。既定のアプリにするかは Windows 側で利用者が選ぶ。"""
    if os.name != "nt":
        raise PdfError("Windows でだけ使えます")
    import ctypes
    import winreg
    icon = Path(__file__).resolve().parent.parent.parent / "assets" / "hub.ico"
    base = rf"Software\Classes\{PROGID}"
    if on:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "Hub")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base + r"\DefaultIcon") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, f'"{icon}",0')
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base + r"\shell\open\command") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, _command())
        for ext in sorted(DOC_EXTS):
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{ext}\OpenWithProgids") as k:
                winreg.SetValueEx(k, PROGID, 0, winreg.REG_NONE, b"")
    else:
        for ext in sorted(DOC_EXTS):
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{ext}\OpenWithProgids", 0, winreg.KEY_SET_VALUE) as k:
                    winreg.DeleteValue(k, PROGID)
            except OSError:
                pass
        for sub in (r"\shell\open\command", r"\shell\open", r"\shell", r"\DefaultIcon", ""):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, base + sub)
            except OSError:
                pass
    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)  # SHCNE_ASSOCCHANGED: エクスプローラーに知らせる
    return association()
