"""office.py — Word / Excel / PowerPoint（.docx .xlsx .pptx）から文字を取り出す。標準ライブラリだけで読む（追加の依存なし）。

Office のファイルは中身が XML の zip なので、文字の入った部分だけを読む。書式・図・グラフは捨てる。
  ・docx: 段落ごとに 1 行。見出しは「#」、表は「 | 」区切り、箇条書きは「・」
  ・xlsx: シートごとに「--- シート: 名前 ---」、行はタブ区切り（計算式は保存されている結果の値）
  ・pptx: スライドごとに「--- スライド N ---」、ノートがあれば「（ノート）」として続ける
使う所: フォルダ窓の read_text（Claude が読む MCP）と、ビューアの xlsx / pptx の簡易表示。
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

OFFICE_EXTS = {".docx", ".xlsx", ".pptx"}
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PKG = "{http://schemas.openxmlformats.org/package/2006/relationships}"
MAX_XML = 50 * 1024 * 1024       # 1 つの XML の上限（壊れたファイル・zip 爆弾の対策）


class OfficeError(Exception):
    pass


def _xml(z: zipfile.ZipFile, name: str):
    try:
        info = z.getinfo(name)
    except KeyError:
        return None
    if info.file_size > MAX_XML:
        raise OfficeError("中身が大きすぎて読めない")
    return ET.fromstring(z.read(name))


def _docx(z: zipfile.ZipFile) -> str:
    root = _xml(z, "word/document.xml")
    if root is None:
        raise OfficeError("Word の文書ではない")

    def para(p) -> str:
        out = []
        for el in p.iter():
            if el.tag == _W + "t":
                out.append(el.text or "")
            elif el.tag == _W + "tab":
                out.append("\t")
            elif el.tag in (_W + "br", _W + "cr"):
                out.append("\n")
        text = "".join(out)
        style = p.find(f"{_W}pPr/{_W}pStyle")
        name = (style.get(_W + "val") if style is not None else "") or ""
        m = re.search(r"(?:heading|見出し)\s*(\d)", name, re.I)
        if m and text.strip():
            return "#" * int(m.group(1)) + " " + text
        if (p.find(f"{_W}pPr/{_W}numPr") is not None or re.search(r"list|リスト|箇条", name, re.I)) and text.strip():
            return "・" + text
        return text

    lines = []
    body = root.find(_W + "body")
    for el in (body if body is not None else []):
        if el.tag == _W + "p":
            lines.append(para(el))
        elif el.tag == _W + "tbl":
            for tr in el.iter(_W + "tr"):
                cells = [" ".join(para(p) for p in tc.iter(_W + "p")).strip() for tc in tr.findall(_W + "tc")]
                lines.append(" | ".join(cells))
            lines.append("")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _xlsx(z: zipfile.ZipFile, max_rows: int = 2000) -> str:
    wb = _xml(z, "xl/workbook.xml")
    if wb is None:
        raise OfficeError("Excel のブックではない")
    shared = []
    ss = _xml(z, "xl/sharedStrings.xml")
    if ss is not None:
        for si in ss.findall(_S + "si"):
            shared.append("".join(t.text or "" for t in si.iter(_S + "t")))
    rels = {}
    rr = _xml(z, "xl/_rels/workbook.xml.rels")
    if rr is not None:
        for r in rr.findall(_PKG + "Relationship"):
            target = r.get("Target", "").lstrip("/")
            rels[r.get("Id")] = target if target.startswith("xl/") else "xl/" + target
    col_re = re.compile(r"([A-Z]+)")

    def col_index(ref: str) -> int:
        m = col_re.match(ref or "")
        n = 0
        for ch in (m.group(1) if m else "A"):
            n = n * 26 + (ord(ch) - 64)
        return n - 1

    parts = []
    for sh in wb.iter(_S + "sheet"):
        name = sh.get("name", "")
        path = rels.get(sh.get(_R + "id"), "")
        root = _xml(z, path) if path else None
        rows = []
        if root is not None:
            for row in root.iter(_S + "row"):
                if len(rows) >= max_rows:
                    rows.append("…（以下省略）")
                    break
                vals: dict[int, str] = {}
                for c in row.findall(_S + "c"):
                    t, v = c.get("t"), c.find(_S + "v")
                    if t == "s" and v is not None:
                        val = shared[int(v.text)] if v.text and int(v.text) < len(shared) else ""
                    elif t == "inlineStr":
                        val = "".join(x.text or "" for x in c.iter(_S + "t"))
                    elif t == "b" and v is not None:
                        val = "TRUE" if v.text == "1" else "FALSE"
                    else:
                        val = v.text if v is not None and v.text is not None else ""
                    vals[col_index(c.get("r", ""))] = val.replace("\t", " ").replace("\n", " ")
                if vals:
                    rows.append("\t".join(vals.get(i, "") for i in range(max(vals) + 1)).rstrip("\t"))
        parts.append(f"--- シート: {name} ---\n" + "\n".join(rows))
    return "\n\n".join(parts).strip()


def _pptx(z: zipfile.ZipFile) -> str:
    names = sorted((n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                   key=lambda n: int(re.search(r"(\d+)", n.rsplit("/", 1)[1]).group(1)))
    if not names:
        raise OfficeError("PowerPoint のファイルではない")

    def text_of(root) -> str:
        paras = []
        for p in root.iter(_A + "p"):
            t = "".join(x.text or "" for x in p.iter(_A + "t")).strip()
            if t:
                paras.append(t)
        return "\n".join(paras)

    parts = []
    for i, n in enumerate(names, 1):
        body = text_of(_xml(z, n))
        note_name = n.replace("slides/slide", "notesSlides/notesSlide")
        note = _xml(z, note_name)
        note_text = text_of(note) if note is not None else ""
        note_text = "\n".join(l for l in note_text.splitlines() if not l.strip().isdigit())   # ノートのページ番号を除く
        parts.append(f"--- スライド {i} ---\n{body}" + (f"\n（ノート）{note_text}" if note_text.strip() else ""))
    return "\n\n".join(parts).strip()


def office_text(path: str | Path) -> str:
    """docx / xlsx / pptx の文字。読めないときは OfficeError（理由付き）。"""
    p = Path(path)
    ext = p.suffix.lower()
    if ext not in OFFICE_EXTS:
        raise OfficeError("Office のファイル（docx / xlsx / pptx）ではない")
    try:
        with zipfile.ZipFile(p) as z:
            return {".docx": _docx, ".xlsx": _xlsx, ".pptx": _pptx}[ext](z)
    except zipfile.BadZipFile:
        raise OfficeError("ファイルが壊れているか、古い形式（.doc / .xls / .ppt）か、パスワード付き") from None
    except ET.ParseError:
        raise OfficeError("中身を読めなかった（壊れている可能性）") from None
