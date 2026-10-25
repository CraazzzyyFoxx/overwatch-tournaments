"""The matchup picture a lineup card shows: a 1200x630 PNG drawn here, from the stored lineup.

:func:`src.render.mix.lineup_picture` decides what the picture says; this module lays
it out in the site's own look -- the mix board's matchup card (one panel, two
team columns around a VS seam, a tile per seat with role, rank badge, name,
the captain's crown and rating) over the next map's art.

Pictures come by URL: the map's art as the database holds it (``image_path``)
and the game ladder's rank emblem, served by the site (:mod:`src.render.mix`). The
caller fetches them (``LineupPicture.image_urls``) and hands the bytes to
:func:`render_png`; one missing from them is simply left out of the picture,
the post still goes. Fonts (Onest for headings, Inter for the rest -- the
site's two faces), the role glyphs and the captain's crown (Lucide's ``Crown``,
as the board draws it) are local copies in ``assets/lineup``.

``LineupPicture.filename`` hashes everything drawn: a card whose picture would
come out the same names the same file, so the projector can tell an unchanged
card from a changed one without drawing anything.
"""

from __future__ import annotations

import colorsys
import hashlib
import io
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from loguru import logger
from PIL import Image, ImageDraw, ImageFilter, ImageFont, UnidentifiedImageError

__all__ = ("LineupPicture", "LineupSeat", "LineupTeam", "render_png")

_ASSETS = Path(__file__).resolve().parents[2] / "assets" / "lineup"

WIDTH, HEIGHT = 1200, 630
_MARGIN = 40


def _hsl(h: float, s: float, lightness: float) -> tuple[int, int, int]:
    """A ``globals.css`` token, written the way the stylesheet writes it."""
    r, g, b = colorsys.hls_to_rgb(h / 360, lightness / 100, s / 100)
    return round(r * 255), round(g * 255), round(b * 255)


# The site's dark theme (``frontend/src/app/globals.css``, ``--aqt-*``).
_BG = _hsl(220, 21, 5)
_BG_2 = _hsl(220, 22, 7)
_CARD = _hsl(220, 22, 8)
_BORDER = _hsl(219, 19, 15)
_BORDER_2 = _hsl(217, 17, 21)
_FG = _hsl(214, 33, 96)
_FG_MUTED = _hsl(212, 13, 65)
_FG_FAINT = _hsl(214, 10, 52)
#: ``--aqt-amber``: the captain's crown on either team, as the board tints it.
_AMBER = _hsl(36, 88, 65)
#: Team accents, in the board's order (``pickup-chrome.ts``): teal, then amber.
_SIDES = (_hsl(172, 70, 49), _AMBER)
#: ``--tracking-label``: the eyebrow's 0.08em.
_LABEL_TRACKING = 0.08


@dataclass(frozen=True, slots=True)
class LineupSeat:
    #: ``tank``/``damage``/``support``; anything else draws no role glyph.
    role: str
    name: str
    rating: int
    #: The rank badge's URL, ``None`` for none.
    division_icon: str | None
    captain: bool = False


@dataclass(frozen=True, slots=True)
class LineupTeam:
    name: str
    average: int | None
    seats: tuple[LineupSeat, ...]


@dataclass(frozen=True, slots=True)
class LineupPicture:
    kicker: str
    title: str
    #: The metric pills over the teams (``Разрыв по рангу 9``, ``Победа +25``).
    pills: tuple[str, ...]
    teams: tuple[LineupTeam, ...]
    #: ``None`` before anyone rolled a map.
    map_name: str | None
    gamemode: str | None
    map_image: str | None

    @property
    def filename(self) -> str:
        """``lineup-<digest>.png``: the same picture, the same name."""
        digest = hashlib.sha1(repr(self).encode(), usedforsecurity=False).hexdigest()[:12]
        return f"lineup-{digest}.png"

    @property
    def image_urls(self) -> set[str]:
        """Every picture this one is drawn with, by URL: what the caller fetches for :func:`render_png`."""
        icons = {seat.division_icon for team in self.teams for seat in team.seats if seat.division_icon}
        return icons | ({self.map_image} if self.map_image else set())


@cache
def _font(face: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(_ASSETS / f"{face}.ttf"), size)


@cache
def _role_glyph(role: str, size: int) -> Image.Image | None:
    path = _ASSETS / "roles" / f"{role}.png"
    if not path.is_file():
        return None
    with Image.open(path) as source:
        return source.convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)


@cache
def _crown(size: int) -> Image.Image:
    """The captain's crown as a mask, drawn in ``_AMBER`` the way text is."""
    with Image.open(_ASSETS / "crown.png") as source:
        return source.convert("RGBA").getchannel("A").resize((size, size), Image.Resampling.LANCZOS)


def _decode(images: Mapping[str, bytes], url: str | None) -> Image.Image | None:
    if url is None or url not in images:
        return None
    try:
        with Image.open(io.BytesIO(images[url])) as source:
            return source.convert("RGBA")
    except (UnidentifiedImageError, OSError):
        logger.warning(f"Lineup picture: {url} is not an image")
        return None


def _fit(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: float) -> str:
    """``text``, cut with an ellipsis until it fits ``width``."""
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text.rstrip() + "…"


def _tracked_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> float:
    gap = font.size * _LABEL_TRACKING
    return sum(draw.textlength(char, font=font) for char in text) + gap * max(len(text) - 1, 0)


def _label(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, ...],
    *,
    align: str = "left",
) -> None:
    """The site's eyebrow: uppercase, wide-tracked (Pillow has no letter-spacing, so per glyph)."""
    text = text.upper()
    x, y = xy
    if align == "right":
        x -= _tracked_width(draw, text, font)
    elif align == "center":
        x -= _tracked_width(draw, text, font) / 2
    gap = font.size * _LABEL_TRACKING
    for char in text:
        draw.text((x, y), char, font=font, fill=fill, anchor="lm")
        x += draw.textlength(char, font=font) + gap


def _panel(
    image: Image.Image,
    box: tuple[int, int, int, int],
    *,
    radius: int,
    fill: tuple[int, ...] | None = None,
    outline: tuple[int, ...] | None = None,
) -> None:
    """A rounded box blended onto ``image``, drawn 3x and scaled down so its corners are smooth."""
    left, top, right, bottom = box
    scale = 3
    width, height = (right - left) * scale, (bottom - top) * scale
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(
        (0, 0, width - 1, height - 1), radius=radius * scale, fill=fill, outline=outline, width=scale
    )
    image.alpha_composite(layer.resize((right - left, bottom - top), Image.Resampling.LANCZOS), (left, top))


def _background(art: Image.Image | None) -> Image.Image:
    """The next map's art, cropped to the card, softened and dimmed under the theme's background."""
    base = Image.new("RGBA", (WIDTH, HEIGHT), (*_BG, 255))
    if art is None:
        return base
    scale = max(WIDTH / art.width, HEIGHT / art.height)
    size = (round(art.width * scale), round(art.height * scale))
    art = art.resize(size, Image.Resampling.LANCZOS)
    left, top = (size[0] - WIDTH) // 2, (size[1] - HEIGHT) // 2
    art = art.crop((left, top, left + WIDTH, top + HEIGHT)).filter(ImageFilter.GaussianBlur(3))
    base.alpha_composite(art)
    # Darker toward the bottom, where the rosters are; the header keeps more of the map.
    shade = Image.linear_gradient("L").resize((WIDTH, HEIGHT)).point(lambda value: 115 + value * 125 // 255)
    veil = Image.new("RGBA", (WIDTH, HEIGHT), (*_BG, 0))
    veil.putalpha(shade)
    base.alpha_composite(veil)
    return base


def _pill(image: Image.Image, draw: ImageDraw.ImageDraw, x: float, middle: int, text: str) -> float:
    """``METRIC_PILL_CLASS``: hairline border, faint fill, tracked label. Returns its width."""
    font = _font("inter-600", 13)
    width = round(_tracked_width(draw, text.upper(), font)) + 28
    _panel(
        image,
        (round(x), middle - 15, round(x) + width, middle + 15),
        radius=15,
        fill=(255, 255, 255, 8),
        outline=(*_BORDER_2, 255),
    )
    _label(draw, (x + 14, middle), text, font, (*_FG_MUTED, 255))
    return width


def _team(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    team: LineupTeam,
    box: tuple[int, int, int, int],
    accent: tuple[int, int, int],
    rows: int,
    images: Mapping[str, bytes],
) -> None:
    left, top, right, bottom = box
    head_y = top + 22
    _panel(image, (left, head_y - 9, left + 3, head_y + 9), radius=1, fill=(*accent, 255))
    average_font = _font("inter-700", 24)
    average = str(team.average) if team.average is not None else "—"
    draw.text((right, head_y), average, font=average_font, fill=_FG, anchor="rm")
    eyebrow = _font("inter-600", 12)
    avg_x = right - draw.textlength(average, font=average_font) - 8
    _label(draw, (avg_x, head_y + 1), "средний", eyebrow, (*_FG_FAINT, 255), align="right")
    name_room = avg_x - _tracked_width(draw, "СРЕДНИЙ", eyebrow) - 16 - (left + 14)
    name_font = _font("onest-700", 24)
    draw.text((left + 14, head_y), _fit(draw, team.name, name_font, name_room), font=name_font, fill=_FG, anchor="lm")
    rule_y = top + 46
    draw.line((left, rule_y, right, rule_y), fill=_BORDER, width=1)

    step = min(62, (bottom - rule_y - 10) // max(rows, 1))
    seat_font, rating_font = _font("inter-600", 20), _font("inter-700", 21)
    for index, seat in enumerate(team.seats):
        tile_top = rule_y + 10 + step * index
        tile_bottom = tile_top + step - 6
        middle = (tile_top + tile_bottom) // 2
        _panel(image, (left, tile_top, right, tile_bottom), radius=10, fill=(255, 255, 255, 6), outline=(*_BORDER, 255))
        glyph = _role_glyph(seat.role, 24)
        if glyph is not None:
            image.alpha_composite(glyph, (left + 14, middle - 12))
        badge = _decode(images, seat.division_icon)
        if badge is not None:
            badge.thumbnail((34, 34), Image.Resampling.LANCZOS)
            image.alpha_composite(badge, (left + 50 + (34 - badge.width) // 2, middle - badge.height // 2))
        rating = str(seat.rating)
        draw.text((right - 16, middle), rating, font=rating_font, fill=_FG, anchor="rm")
        name_x = left + 96
        name_end = right - 16 - draw.textlength(rating, font=rating_font) - 16
        if seat.captain:
            # ``SeatRow``: the crown sits between the name and the rating.
            name_end -= 18
            draw.bitmap((round(name_end), middle - 9), _crown(18), fill=(*_AMBER, 255))
            name_end -= 12
        name = _fit(draw, seat.name, seat_font, name_end - name_x)
        draw.text((name_x, middle), name, font=seat_font, fill=_FG, anchor="lm")


def render_png(picture: LineupPicture, images: Mapping[str, bytes]) -> bytes:
    """``picture`` drawn as a PNG; ``images`` are its ``image_urls`` as the caller fetched them, by URL."""
    image = _background(_decode(images, picture.map_image))
    draw = ImageDraw.Draw(image)

    _label(draw, (_MARGIN, 52), picture.kicker, _font("inter-600", 14), (*_FG_MUTED, 255))
    title_font = _font("onest-700", 42)
    map_room = 0
    if picture.map_name:
        map_font = _font("onest-700", 26)
        _label(draw, (WIDTH - _MARGIN, 52), "Карта", _font("inter-600", 14), (*_FG_MUTED, 255), align="right")
        draw.text((WIDTH - _MARGIN, 94), picture.map_name, font=map_font, fill=_FG, anchor="rm")
        map_room = round(draw.textlength(picture.map_name, font=map_font))
        if picture.gamemode:
            draw.text(
                (WIDTH - _MARGIN, 124), picture.gamemode, font=_font("inter-500", 15), fill=_FG_MUTED, anchor="rm"
            )
    title = _fit(draw, picture.title, title_font, WIDTH - 2 * _MARGIN - map_room - (40 if map_room else 0))
    draw.text((_MARGIN, 96), title, font=title_font, fill=_FG, anchor="lm")

    card = (_MARGIN, 152, WIDTH - _MARGIN, HEIGHT - _MARGIN)
    _panel(image, card, radius=18, fill=(*_CARD, 215), outline=(*_BORDER, 255))
    strip_bottom = card[1] + 50
    if picture.pills:
        widths = [round(_tracked_width(draw, pill.upper(), _font("inter-600", 13))) + 28 for pill in picture.pills]
        x = (WIDTH - sum(widths) - 8 * (len(widths) - 1)) / 2
        for pill in picture.pills:
            x += _pill(image, draw, x, card[1] + 25, pill) + 8
    draw.line((card[0] + 1, strip_bottom, card[2] - 1, strip_bottom), fill=_BORDER, width=1)

    teams = picture.teams or (LineupTeam(name="—", average=None, seats=()),)
    rows = max(len(team.seats) for team in teams)
    seam = 64 if len(teams) == 2 else 0
    inner_left, inner_right = card[0] + 18, card[2] - 18
    column = (inner_right - inner_left - seam - 36 * (len(teams) - 1)) // len(teams)
    x = inner_left
    for index, team in enumerate(teams):
        _team(image, draw, team, (x, strip_bottom + 6, x + column, card[3] - 12), _SIDES[index % 2], rows, images)
        x += column + 18
        if seam and index == 0:
            image.alpha_composite(
                Image.new("RGBA", (seam, card[3] - strip_bottom - 1), (*_BG_2, 200)), (x, strip_bottom + 1)
            )
            draw.line((x, strip_bottom, x, card[3] - 1), fill=_BORDER, width=1)
            draw.line((x + seam, strip_bottom, x + seam, card[3] - 1), fill=_BORDER, width=1)
            _label(
                draw,
                (x + seam / 2, (strip_bottom + card[3]) // 2),
                "vs",
                _font("onest-700", 15),
                (*_FG_FAINT, 255),
                align="center",
            )
            x += seam + 18
    # The seam's fill went over the card's own border; redraw the outline on top.
    _panel(image, card, radius=18, outline=(*_BORDER, 255))

    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, "PNG", optimize=True)
    return buffer.getvalue()
