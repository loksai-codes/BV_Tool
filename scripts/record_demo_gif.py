"""Record docs/assets/demo.gif from a running app (MOCK demo data).

    streamlit run app.py --server.port 8599 --server.headless true   (separate terminal)
    python -m scripts.record_demo_gif [--url http://127.0.0.1:8599]
"""
from __future__ import annotations

import argparse
import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import Page, sync_playwright

OUT = Path(__file__).resolve().parent.parent / "docs" / "assets" / "demo.gif"
SIZE = (1280, 800)
FINAL_W = 960


def _font(size: int):
    for f in ("C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf",
              "/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default()


def snap(page: Page, caption: str) -> Image.Image:
    img = Image.open(io.BytesIO(page.screenshot())).convert("RGB")
    bar_h = 56
    canvas = Image.new("RGB", (img.width, img.height + bar_h), "#0b1220")
    canvas.paste(img, (0, 0))
    d = ImageDraw.Draw(canvas)
    d.text((24, img.height + 14), caption, fill="#ffffff", font=_font(24))
    d.text((canvas.width - 220, img.height + 18), "MOCK demo data", fill="#fab219", font=_font(18))
    return canvas.resize((FINAL_W, int(canvas.height * FINAL_W / canvas.width)), Image.LANCZOS)


def nav(page: Page, label: str, wait_text: str) -> None:
    page.get_by_role("link", name=label).first.click()
    page.get_by_text(wait_text).first.wait_for(timeout=60_000)
    page.wait_for_timeout(1800)


def record(url: str) -> list[tuple[Image.Image, int]]:
    frames: list[tuple[Image.Image, int]] = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": SIZE[0], "height": SIZE[1]})
        page.goto(url)
        page.get_by_role("button", name="Run demo with mock data").wait_for(timeout=60_000)
        page.wait_for_timeout(1500)
        frames.append((snap(page, "1  Home — start a comparison or run the demo"), 2600))

        page.get_by_role("button", name="Run demo with mock data").click()
        page.get_by_text("Visuals by status").wait_for(timeout=60_000)
        page.wait_for_timeout(2500)
        frames.append((snap(page, "2  Dashboard — overall status with the reasons"), 2800))
        page.mouse.move(800, 500)
        page.mouse.wheel(0, 560)
        page.wait_for_timeout(1500)
        frames.append((snap(page, "3  Visuals by status and differences per visual"), 3000))

        nav(page, "Visual details", "Visual comparison details")
        frames.append((snap(page, "4  Details — every visual, side by side"), 2200))
        page.locator("[data-testid=\"stSelectbox\"]").first.click()
        page.get_by_role("option", name="Sales by Category and Month").first.click()
        page.wait_for_timeout(2000)
        frames.append((snap(page, "5  A failing visual — why it failed"), 2600))
        page.mouse.move(800, 500)
        page.mouse.wheel(0, 520)
        page.wait_for_timeout(1200)
        frames.append((snap(page, "6  Value mismatches with absolute and % difference"), 3000))
        page.get_by_role("tab", name="Missing").click()
        page.wait_for_timeout(1200)
        frames.append((snap(page, "7  Missing records (in original, absent in migrated)"), 2600))
        page.get_by_role("tab", name="Additional").click()
        page.wait_for_timeout(1200)
        frames.append((snap(page, "8  Additional records (only in migrated)"), 2600))

        nav(page, "Export & history", "Previous runs")
        frames.append((snap(page, "9  Export Excel, CSV, JSON, HTML · compare past runs"), 3200))
        b.close()
    return frames


def build_gif(frames: list[tuple[Image.Image, int]], fade_steps: int = 3) -> None:
    seq, durations = [], []
    for i, (img, hold) in enumerate(frames):
        if i:
            prev = frames[i - 1][0]
            for k in range(1, fade_steps + 1):
                seq.append(Image.blend(prev, img, k / (fade_steps + 1)))
                durations.append(70)
        seq.append(img)
        durations.append(hold)
    pal = [im.quantize(colors=256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE) for im in seq]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    pal[0].save(OUT, save_all=True, append_images=pal[1:], duration=durations, loop=0, optimize=True, disposal=1)
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB, {len(seq)} frames)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8599/")
    build_gif(record(ap.parse_args().url))
