"""pdf/cli.py — PDFを画像（PNG / JPEG / TIFF）にする単体コマンド（Hub の PDF パネルの「画像にする」もこれを使う）。

  python cli.py <PDF> [--format png|jpeg|tiff] [--dpi 200] [--pages all|1,3-5]
                      [--tiff-mode color|gray|bw] [--out 出力フォルダ]

最後の行に {"outputs": [...]} のJSONを出す（Hubが結果一覧に使う）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def parse_pages(spec: str, count: int) -> list[int]:
    """'all' / '1,3-5' → 0始まりのページ番号の一覧。範囲外は無視せずエラーにする。"""
    spec = (spec or "all").strip().lower()
    if spec in ("", "all"):
        return list(range(count))
    pages: list[int] = []
    for part in spec.replace(" ", "").split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            start, end = int(a), int(b)
        else:
            start = end = int(part)
        if not (1 <= start <= end <= count):
            raise ValueError(f"ページ指定 '{part}' が範囲外（このPDFは 1〜{count} ページ）")
        pages.extend(range(start - 1, end))
    return sorted(set(pages))


def convert(pdf: Path, fmt: str, dpi: int, pages: str, tiff_mode: str, out: Path | None) -> list[str]:
    import pymupdf  # PyMuPDF（Poppler不要）
    from PIL import Image

    doc = pymupdf.open(pdf)
    idx = parse_pages(pages, doc.page_count)
    out_dir = out or pdf.with_name(f"{pdf.stem}_images")
    out_dir.mkdir(parents=True, exist_ok=True)

    def render(i: int) -> "Image.Image":
        pix = doc[i].get_pixmap(dpi=dpi, alpha=False)          # ページを画像にする
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

    outputs: list[str] = []
    if fmt == "tiff":
        mode, comp = {"color": ("RGB", "tiff_lzw"), "gray": ("L", "tiff_lzw"), "bw": ("1", "group4")}[tiff_mode]
        frames = [render(i).convert(mode) for i in idx]
        suffix = "" if len(idx) == doc.page_count else f"_p{idx[0] + 1}-{idx[-1] + 1}"
        target = out_dir / f"{pdf.stem}{suffix}.tif"
        frames[0].save(target, format="TIFF", save_all=True, append_images=frames[1:],
                       compression=comp, dpi=(dpi, dpi))
        outputs.append(str(target))
    else:
        ext, pil_fmt = ("jpg", "JPEG") if fmt == "jpeg" else ("png", "PNG")  # Pillowの形式名は "JPEG"
        for i in idx:
            target = out_dir / f"{pdf.stem}_p{i + 1:03d}.{ext}"
            kwargs = {"quality": 92} if pil_fmt == "JPEG" else {}
            render(i).save(target, format=pil_fmt, dpi=(dpi, dpi), **kwargs)
            outputs.append(str(target))
            print(f"{i + 1}ページ → {target.name}", flush=True)
    return outputs


def main() -> int:
    ap = argparse.ArgumentParser(description="PDFを画像にする")
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--format", choices=["png", "jpeg", "tiff"], default="png")
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--pages", default="all")
    ap.add_argument("--tiff-mode", choices=["color", "gray", "bw"], default="color")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()

    if not a.pdf.is_file():
        print(f"PDFが見つからない: {a.pdf}", file=sys.stderr)
        return 2
    if not 50 <= a.dpi <= 600:
        print("dpi は 50〜600", file=sys.stderr)
        return 2
    try:
        outputs = convert(a.pdf, a.format, a.dpi, a.pages, a.tiff_mode, a.out)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    print(f"{len(outputs)} ファイルを書き出した")
    print(json.dumps({"outputs": outputs, "folder": str(Path(outputs[0]).parent) if outputs else ""}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
