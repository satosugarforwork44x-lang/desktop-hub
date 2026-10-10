"""make_icons.py — ロゴ（A — Edge）から、アイコン一式を描き出す（Pillow だけで描く。SVG の変換ソフトは不要）。

  py tools/make_icons.py
  → assets/hub.ico（16〜256px を1つにまとめたもの）, assets/hub-256.png, assets/hub-512.png

小さいサイズ（32px 以下）では、細いバーが潰れないよう太く・広く描いた版を使う。
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ASSETS = Path(__file__).resolve().parent.parent / "assets"
TEAL, BLUE, VIOLET = (47, 198, 192), (79, 125, 243), (141, 108, 242)


def _lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _bar_color(t: float):
    return _lerp(TEAL, BLUE, t * 2) if t < .5 else _lerp(BLUE, VIOLET, (t - .5) * 2)


def draw(size: int, small: bool) -> Image.Image:
    S = 1024                                   # 大きく描いてから縮める（輪郭をなめらかにする）
    k = S / 168
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    # 本体: 上 #1A1E29 → 下 #090A0E の縦グラデーション
    body = Image.new("RGBA", (S, S))
    bd = ImageDraw.Draw(body)
    for y in range(S):
        bd.line([(0, y), (S, y)], fill=(*_lerp((26, 30, 41), (9, 10, 14), y / S), 255))
    # 上から差す光
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([S * .1, -S * .55, S * .9, S * .45], fill=(110, 124, 245, 120))
    glow = glow.filter(ImageFilter.GaussianBlur(S * .08))
    body = Image.alpha_composite(body, glow)
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([4 * k, 4 * k, 164 * k, 164 * k], radius=38 * k, fill=255)
    img.paste(body, (0, 0), mask)
    # 縁のハイライト
    edge = Image.new("L", (S, S), 0)
    ImageDraw.Draw(edge).rounded_rectangle([4.5 * k, 4.5 * k, 163.5 * k, 163.5 * k], radius=37.5 * k, outline=255, width=max(2, round(k)))
    img.paste((255, 255, 255, 34), (0, 0), edge)
    # 光るバー（小さいサイズは太く・広く）
    x0, y0, x1, y1 = (30, 28, 138, 50) if small else (38, 30, 130, 42)
    bar = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    bdr = ImageDraw.Draw(bar)
    for x in range(round(x0 * k), round(x1 * k)):
        bdr.line([(x, y0 * k), (x, y1 * k)], fill=(*_bar_color((x / k - x0) / (x1 - x0)), 255))
    bmask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(bmask).rounded_rectangle([x0 * k, y0 * k, x1 * k, y1 * k], radius=(y1 - y0) / 2 * k, fill=255)
    if not small:  # 大きいサイズはバーの周りにうっすら光をにじませる
        halo = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        halo.paste(bar, (0, 0), bmask)
        halo = halo.filter(ImageFilter.GaussianBlur(S * .02))
        halo.putalpha(ImageChops.multiply(halo.getchannel("A"), mask))
        img = Image.alpha_composite(img, halo)
    img.paste(bar, (0, 0), bmask)
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    ASSETS.mkdir(exist_ok=True)
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    imgs = [draw(s, small=s <= 32) for s in sizes]
    imgs[-1].save(ASSETS / "hub.ico", sizes=[(s, s) for s in sizes], append_images=imgs[:-1])
    imgs[-1].save(ASSETS / "hub-256.png")
    draw(512, small=False).save(ASSETS / "hub-512.png")
    print("assets/hub.ico, hub-256.png, hub-512.png を書き出しました")


if __name__ == "__main__":
    main()
