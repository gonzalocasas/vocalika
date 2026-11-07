# /// script
# requires-python = ">=3.10"
# dependencies = ["resvg-py==0.2.6"]
# ///
"""Render every raster brand asset from the SVG masters in docs/brand/.

    uv run scripts/render_brand.py

The masters were vectorised from the hero lockup in docs/brand.png. After this
script, regenerate the desktop icon set from the 1024 px source it writes:

    cd desktop && npx tauri icon src-tauri/app-icon.png
"""

import re
import shutil
from pathlib import Path

import resvg_py

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "docs" / "brand"
PUBLIC = ROOT / "frontend" / "public" / "brand"
INK = "#0E1011"


def master(name: str) -> str:
    return (BRAND / f"{name}.svg").read_text()


def view_box(svg: str) -> tuple[float, float, float, float]:
    x, y, w, h = map(float, re.search(r'viewBox="([^"]+)"', svg)[1].split())
    return x, y, w, h


def inner(svg: str) -> str:
    """The drawable content of a master, without its <svg> wrapper and title."""
    body = re.search(r"<svg[^>]*>(.*)</svg>", svg, re.S)[1]
    return re.sub(r"<title>.*?</title>", "", body)


def framed(
    name: str, width: float, height: float, content_width: float, background: str | None = None
) -> str:
    """A master centred in a width x height canvas, scaled to content_width."""
    svg = master(name)
    x, y, w, h = view_box(svg)
    s = content_width / w
    tx, ty = (width - w * s) / 2 - x * s, (height - h * s) / 2 - y * s
    bg = ""
    if background:
        bg = f'<rect width="{width:g}" height="{height:g}" fill="{background}"/>'
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:g} {height:g}"'
        f' width="{width:g}" height="{height:g}">'
        f'{bg}<g transform="translate({tx:.3f} {ty:.3f}) scale({s:.5f})">{inner(svg)}</g></svg>'
    )


def render(svg: str, out: Path, width: int, height: int | None = None) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    png = resvg_py.svg_to_bytes(svg_string=svg, width=width, height=height)
    out.write_bytes(bytes(png))
    print(f"{out.relative_to(ROOT)}  {width}px")


def main() -> None:
    # README banner: the lockup on the brand ink, at 3x its 720 px display width.
    render(framed("lockup", 1080, 300, 960, INK), ROOT / "docs" / "logo-banner.png", 2160)

    # Web UI: SVGs for the header and favicon, PNG fallbacks for apple-touch-icon etc.
    shutil.copyfile(BRAND / "mark.svg", PUBLIC / "favicon.svg")
    shutil.copyfile(BRAND / "lockup.svg", PUBLIC / "header-logo.svg")
    render(framed("mark", 512, 512, 488), PUBLIC / "favicon.png", 512)
    x, y, w, h = view_box(master("lockup"))
    render(master("lockup"), PUBLIC / "header-logo.png", round(240 * w / h))
    x, y, w, h = view_box(master("wordmark"))
    render(master("wordmark"), PUBLIC / "logo.png", round(220 * w / h))

    # Desktop: the launcher's progress screen, and the 1024 px source that
    # `tauri icon` expands into every platform size.
    shutil.copyfile(BRAND / "lockup.svg", ROOT / "desktop" / "ui" / "lockup.svg")
    render(master("app-icon"), ROOT / "desktop" / "src-tauri" / "app-icon.png", 1024)

    # Website: the lockup and favicon, the app icon for home screens, and the
    # card link previews show (1200x630, the size Open Graph asks for).
    site = ROOT / "site" / "brand"
    site.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(BRAND / "lockup.svg", site / "lockup.svg")
    shutil.copyfile(BRAND / "mark.svg", site / "favicon.svg")
    shutil.copyfile(BRAND / "wordmark.svg", site / "wordmark.svg")
    render(master("app-icon"), site / "app-icon.png", 180)
    render(framed("lockup", 1200, 630, 940, INK), site / "social.png", 1200)


if __name__ == "__main__":
    main()
