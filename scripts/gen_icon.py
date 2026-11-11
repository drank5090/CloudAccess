"""生成应用图标 resources/icon.png 与 resources/icon.ico。"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw

SIZE = 512
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "resources")


def main() -> None:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 蓝色圆角方块背景
    radius = int(SIZE * 0.22)
    d.rounded_rectangle([0, 0, SIZE, SIZE], radius=radius, fill=(59, 130, 246, 255))

    # 顶部到底部渐变高光
    highlight = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    dh = ImageDraw.Draw(highlight)
    for y in range(SIZE):
        alpha = max(0, 70 - y * 70 // SIZE)
        dh.line([(0, y), (SIZE, y)], fill=(255, 255, 255, alpha))
    mask = Image.new("L", (SIZE, SIZE), 0)
    dm = ImageDraw.Draw(mask)
    dm.rounded_rectangle([0, 0, SIZE, SIZE], radius=radius, fill=255)
    img.paste(highlight, (0, 0), mask)

    # 白色闪电
    bolt = [
        (SIZE * 0.58, SIZE * 0.10),
        (SIZE * 0.26, SIZE * 0.55),
        (SIZE * 0.46, SIZE * 0.55),
        (SIZE * 0.42, SIZE * 0.90),
        (SIZE * 0.74, SIZE * 0.40),
        (SIZE * 0.54, SIZE * 0.40),
    ]
    d.polygon(bolt, fill=(255, 255, 255, 255))

    os.makedirs(OUT_DIR, exist_ok=True)
    img.save(os.path.join(OUT_DIR, "icon.png"))
    img.save(os.path.join(OUT_DIR, "icon.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("icon.png / icon.ico generated")


if __name__ == "__main__":
    main()
