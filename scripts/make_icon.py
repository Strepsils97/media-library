"""Знак застосунку: SVG для інтерфейсу та .ico для екзешника.

Знак зібраний з примітивів, які вже є в інтерфейсі: недомкнене кільце
схожості з картки результату, жовтий #e9d34a на майже чорному. Побудова на
сітці 128: коло r 50, обведення 13, розрив 66 з 314 (21%) угорі, на 12
годині. Усередині монограма ML — Plex Mono 700.

Правило деградації: до 24 px літери зливаються в пляму, тому дрібні розміри
беруть замість монограми крапку, а обведення стає товщим. Межа — 28 px.

Літери не лишаються текстом: у SVG вони переведені в контури, у растрі
малюються тими самими контурами. Інакше знак залежав би від того, чи є
потрібний шрифт у системі, — а іконку екзешника малює взагалі не наш код.

  python scripts/make_icon.py
"""

from __future__ import annotations

import math
from pathlib import Path

from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "brand"
FONT = (
    ROOT / "frontend/node_modules/@fontsource/ibm-plex-mono/files"
    / "ibm-plex-mono-latin-700-normal.woff"
)

GRID = 128
CENTER = GRID / 2
RADIUS = 50
GAP_SHARE = 66 / 314  # розрив кільця — така сама частка, як у картці результату

ACCENT = "#e9d34a"
TILE_TOP = (29, 31, 36)      # #1d1f24
TILE_BOTTOM = (12, 13, 16)   # #0c0d10

TEXT_SIZE = 38
TRACKING = -1.5

# Плитка іконки: 52 px, радіус 13, знак 33 — пропорції з макета. На дрібних
# розмірах поля з'їдають кільце цілком, тому там знак займає більше плитки.
TILE_RADIUS_SHARE = 13 / 52
MARK_SHARE = 33 / 52
MARK_SHARE_SMALL = 0.78
SMALL_TILE = 24

# Дрібні розміри малюються крапкою; обведення при цьому товстішає, щоб
# кільце не розсипалося на пікселях.
DOT_RADIUS = 15
STROKE_BY_SIZE = ((16, 17), (24, 15), (10**9, 13))
MONOGRAM_FROM = 28


def stroke_for(size: int) -> int:
    return next(width for limit, width in STROKE_BY_SIZE if size <= limit)


class _Flatten(BasePen):
    """Контури гліфа у вигляді ламаних: їх однаково легко залити й вивести в SVG."""

    STEPS = 24

    def __init__(self, glyph_set, scale: float, offset: tuple[float, float]) -> None:
        super().__init__(glyph_set)
        self.scale = scale
        self.dx, self.dy = offset
        self.contours: list[list[tuple[float, float]]] = []
        self._current: list[tuple[float, float]] = []

    def _point(self, pt):
        # У шрифті вісь Y дивиться вгору, у SVG і в растрі — вниз.
        return (pt[0] * self.scale + self.dx, -pt[1] * self.scale + self.dy)

    def _moveTo(self, pt):
        self._closePath()
        self._current = [self._point(pt)]

    def _lineTo(self, pt):
        self._current.append(self._point(pt))

    def _curveToOne(self, p1, p2, p3):
        start = self._current[-1]
        a, b, c = self._point(p1), self._point(p2), self._point(p3)
        for step in range(1, self.STEPS + 1):
            t = step / self.STEPS
            u = 1 - t
            self._current.append((
                u**3 * start[0] + 3 * u * u * t * a[0] + 3 * u * t * t * b[0] + t**3 * c[0],
                u**3 * start[1] + 3 * u * u * t * a[1] + 3 * u * t * t * b[1] + t**3 * c[1],
            ))

    def _qCurveToOne(self, p1, p2):
        start = self._current[-1]
        a, b = self._point(p1), self._point(p2)
        for step in range(1, self.STEPS + 1):
            t = step / self.STEPS
            u = 1 - t
            self._current.append((
                u * u * start[0] + 2 * u * t * a[0] + t * t * b[0],
                u * u * start[1] + 2 * u * t * a[1] + t * t * b[1],
            ))

    def _closePath(self):
        if len(self._current) > 2:
            self.contours.append(self._current)
        self._current = []

    _endPath = _closePath

    def done(self) -> list[list[tuple[float, float]]]:
        self._closePath()
        return self.contours


def monogram(text: str = "ML") -> list[list[tuple[float, float]]]:
    """Контури монограми, вирівняні по центру сітки за чорнилом, а не за метриками.

    Метрики шрифту лишають зверху місце під надрядкові елементи, яких у
    «ML» немає, — знак від цього виглядав би зсунутим донизу.
    """
    font = TTFont(FONT)
    glyph_set = font.getGlyphSet()
    cmap = font.getBestCmap()
    metrics = font["hmtx"]
    scale = TEXT_SIZE / font["head"].unitsPerEm

    contours: list[list[tuple[float, float]]] = []
    pen_x = 0.0
    for char in text:
        name = cmap[ord(char)]
        pen = _Flatten(glyph_set, scale, (pen_x, 0.0))
        glyph_set[name].draw(pen)
        contours += pen.done()
        pen_x += metrics[name][0] * scale + TRACKING

    xs = [x for contour in contours for x, _ in contour]
    ys = [y for contour in contours for _, y in contour]
    dx = CENTER - (min(xs) + max(xs)) / 2
    dy = CENTER - (min(ys) + max(ys)) / 2
    return [[(x + dx, y + dy) for x, y in contour] for contour in contours]


def _ring_path(stroke: int) -> str:
    """Дуга кільця в координатах SVG. Розрив закінчується рівно на 12 годині."""
    sweep = (1 - GAP_SHARE) * 360
    start = math.radians(-90)
    end = math.radians(-90 + sweep)
    x1, y1 = CENTER + RADIUS * math.cos(start), CENTER + RADIUS * math.sin(start)
    x2, y2 = CENTER + RADIUS * math.cos(end), CENTER + RADIUS * math.sin(end)
    large = 1 if sweep > 180 else 0
    return (
        f'<path d="M {x1:.2f} {y1:.2f} A {RADIUS} {RADIUS} 0 {large} 1 {x2:.2f} {y2:.2f}" '
        f'fill="none" stroke="{ACCENT}" stroke-width="{stroke}" stroke-linecap="round"/>'
    )


def svg(*, monogram_inside: bool) -> str:
    stroke = 13 if monogram_inside else 15
    parts = [_ring_path(stroke)]
    if monogram_inside:
        for contour in monogram():
            points = " ".join(f"{x:.2f} {y:.2f}" for x, y in contour)
            parts.append(f'<path d="M {points} Z" fill="{ACCENT}"/>')
    else:
        parts.append(
            f'<circle cx="{CENTER:.0f}" cy="{CENTER:.0f}" r="{DOT_RADIUS}" fill="{ACCENT}"/>'
        )

    body = "\n  ".join(parts)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {GRID} {GRID}" '
        f'width="{GRID}" height="{GRID}">\n  {body}\n</svg>\n'
    )


def tile_svg() -> str:
    """Знак на темній плитці — для фавікона: на світлій сторінці жовте саме по собі тоне."""
    inner = "\n    ".join(svg(monogram_inside=False).splitlines()[1:-1]).strip()
    shift = GRID * (1 - MARK_SHARE_SMALL) / 2
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {GRID} {GRID}" '
        f'width="{GRID}" height="{GRID}">\n'
        f'  <rect width="{GRID}" height="{GRID}" rx="{GRID * TILE_RADIUS_SHARE:.0f}" '
        f'fill="#14161a"/>\n'
        f'  <g transform="translate({shift:.1f} {shift:.1f}) scale({MARK_SHARE_SMALL})">\n'
        f'    {inner}\n  </g>\n</svg>\n'
    )


COMPONENT = '''// Згенеровано scripts/make_icon.py — правити там, не тут.
//
// Знак застосунку. До 28 px монограма зливається в пляму, тому дрібні
// розміри малюються крапкою — те саме правило, що і в іконці екзешника.

interface Props {{
  size?: number;
  className?: string;
}}

export function Mark({{ size = 21, className }}: Props) {{
  const dot = size < {monogram_from};
  return (
    <svg
      width={{size}}
      height={{size}}
      viewBox="0 0 {grid} {grid}"
      className={{className}}
      aria-hidden="true"
    >
      <path
        d="{ring}"
        fill="none"
        stroke="currentColor"
        strokeWidth={{dot ? 15 : 13}}
        strokeLinecap="round"
      />
      {{dot ? (
        <circle cx="{center}" cy="{center}" r="{dot_radius}" fill="currentColor" />
      ) : (
        <>
{letters}
        </>
      )}}
    </svg>
  );
}}
'''


def component() -> str:
    letters = "\n".join(
        '          <path d="M '
        + " ".join(f"{x:.2f} {y:.2f}" for x, y in contour)
        + ' Z" fill="currentColor" />'
        for contour in monogram()
    )
    ring = _ring_path(13).split('d="', 1)[1].split('"', 1)[0]
    return COMPONENT.format(
        monogram_from=MONOGRAM_FROM,
        grid=GRID,
        center=f"{CENTER:.0f}",
        dot_radius=DOT_RADIUS,
        ring=ring,
        letters=letters,
    )


def _draw_mark(size: int, scale: float) -> Image.Image:
    """Знак на прозорому тлі. `size` — у скільки пікселів він урешті ляже."""
    side = round(GRID * scale)
    image = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    width = stroke_for(size) * scale

    # Pillow нарощує товщину дуги всередину від межі рамки, а обведення в SVG
    # росте на два боки від лінії — інакше круглі шапки вилазили б назовні.
    outer = RADIUS * scale + width / 2
    box = [CENTER * scale - outer, CENTER * scale - outer,
           CENTER * scale + outer, CENTER * scale + outer]
    sweep = (1 - GAP_SHARE) * 360
    draw.arc(box, start=-90, end=-90 + sweep, fill=ACCENT, width=round(width))

    # Pillow малює дугу з рівними кінцями — круглі шапки домальовуємо самі.
    for angle in (-90, -90 + sweep):
        cx = (CENTER + RADIUS * math.cos(math.radians(angle))) * scale
        cy = (CENTER + RADIUS * math.sin(math.radians(angle))) * scale
        draw.ellipse([cx - width / 2, cy - width / 2, cx + width / 2, cy + width / 2], fill=ACCENT)

    if size >= MONOGRAM_FROM:
        for contour in monogram():
            draw.polygon([(x * scale, y * scale) for x, y in contour], fill=ACCENT)
    else:
        r = DOT_RADIUS * scale
        draw.ellipse(
            [CENTER * scale - r, CENTER * scale - r, CENTER * scale + r, CENTER * scale + r],
            fill=ACCENT,
        )
    return image


def tile(size: int, supersample: int = 8) -> Image.Image:
    """Темна плитка зі знаком — так іконка читається і на світлій панелі задач."""
    side = size * supersample

    gradient = Image.new("RGB", (1, side))
    pixels = gradient.load()
    for y in range(side):
        t = y / max(1, side - 1)
        pixels[0, y] = tuple(round(a + (b - a) * t) for a, b in zip(TILE_TOP, TILE_BOTTOM))
    gradient = gradient.resize((side, side))

    mask = Image.new("L", (side, side), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, side - 1, side - 1], radius=round(side * TILE_RADIUS_SHARE), fill=255
    )

    image = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    image.paste(gradient, (0, 0), mask)

    share = MARK_SHARE_SMALL if size <= SMALL_TILE else MARK_SHARE
    # Правило деградації міряє сам знак, а не плитку: у 32-піксельній іконці
    # на нього припадає близько двадцяти пікселів — літерам там уже тісно.
    mark = _draw_mark(round(size * share), side * share / GRID)
    offset = (side - mark.width) // 2
    image.alpha_composite(mark, (offset, offset))

    return image.resize((size, size), Image.LANCZOS)


def main() -> None:
    BRAND.mkdir(exist_ok=True)

    (BRAND / "ml-mark.svg").write_text(svg(monogram_inside=True), encoding="utf-8")
    (BRAND / "ml-mark-small.svg").write_text(svg(monogram_inside=False), encoding="utf-8")
    (BRAND / "ml-tile.svg").write_text(tile_svg(), encoding="utf-8")

    public = ROOT / "frontend" / "public"
    public.mkdir(exist_ok=True)
    (public / "favicon.svg").write_text(tile_svg(), encoding="utf-8")
    (ROOT / "frontend" / "src" / "components" / "Mark.tsx").write_text(
        component(), encoding="utf-8"
    )

    sizes = [16, 20, 24, 32, 48, 64, 128, 256]
    layers = [tile(size) for size in sizes]
    ico = BRAND / "media-library.ico"
    layers[-1].save(ico, format="ICO", sizes=[(s, s) for s in sizes], append_images=layers[:-1])
    layers[-1].save(BRAND / "media-library-256.png")

    print("brand/ml-mark.svg · brand/ml-mark-small.svg · brand/ml-tile.svg")
    print("frontend/public/favicon.svg · frontend/src/components/Mark.tsx")
    print(f"brand/media-library.ico · розміри {', '.join(str(s) for s in sizes)}")


if __name__ == "__main__":
    main()
