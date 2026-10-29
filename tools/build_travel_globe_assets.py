#!/usr/bin/env python3
"""Build the Travel Globe app's world textures from Natural Earth data.

Natural Earth (https://www.naturalearthdata.com) is in the public domain. The
script downloads two files from a pinned revision of nvkelso/natural-earth-vector:

* ne_50m_admin_0_countries: country outlines, rasterised to an equirectangular
  map of country ids (assets/ids.png, one palette index per texel).
* ne_10m_populated_places_simple: 7,000+ towns and cities with populations,
  splatted into a night-lights layer.

assets/aux.png packs, per texel, a border flag (bit 3) and a 0-7 night-light
level (bits 0-2). assets/countries.json lists each id's ISO code, name and
label point, so the app can unlock countries by code without re-baking. The
menu icon (icon.png) is a small globe drawn from the same maps.

    python3 tools/build_travel_globe_assets.py
    python3 tools/build_travel_globe_assets.py --cache /tmp/ne   # reuse downloads
"""

import argparse
import json
import math
from pathlib import Path
from urllib.request import urlopen

import numpy as np
from PIL import Image, ImageDraw

REVISION = "ca96624a56bd078437bca8184e78163e5039ad19"
BASE_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/" + REVISION + "/geojson/"
COUNTRIES = "ne_50m_admin_0_countries.geojson"
PLACES = "ne_10m_populated_places_simple.geojson"
APP = Path(__file__).resolve().parents[1] / "badge/apps/travel_globe"
OUTPUT = APP / "assets"

# 1024 x 512 is 0.35 degrees a texel: El Salvador is about 7 x 3 texels.
WIDTH, HEIGHT = 1024, 512
LIGHT_LEVELS = 7


def fetch(name, cache):
    if cache:
        path = Path(cache) / name
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    with urlopen(BASE_URL + name, timeout=120) as response:
        data = response.read()
    if cache:
        Path(cache).mkdir(parents=True, exist_ok=True)
        (Path(cache) / name).write_bytes(data)
    return json.loads(data)


def to_pixel(lon, lat):
    return ((lon + 180.0) / 360.0 * WIDTH, (90.0 - lat) / 180.0 * HEIGHT)


def rings_of(geometry):
    if geometry["type"] == "Polygon":
        return [geometry["coordinates"]]
    return geometry["coordinates"]


def ring_area(ring):
    total = 0.0
    for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
        total += x0 * y1 - x1 * y0
    return abs(total) / 2


def rasterise_countries(features):
    """Country ids on the map, biggest countries first so islands stay on top."""
    ids = Image.new("L", (WIDTH, HEIGHT), 0)
    draw = ImageDraw.Draw(ids)
    order = sorted(
        range(len(features)),
        key=lambda i: -sum(ring_area(poly[0]) for poly in rings_of(features[i]["geometry"])),
    )
    for index in order:
        country_id = index + 1
        for polygon in rings_of(features[index]["geometry"]):
            for hole, ring in enumerate(polygon):
                points = [to_pixel(lon, lat) for lon, lat in ring]
                # An outline as well as the fill keeps islands narrower than a
                # texel on the map.
                if hole == 0:
                    draw.polygon(points, fill=country_id, outline=country_id)
                else:
                    draw.polygon(points, fill=0)
    return np.array(ids, dtype=np.uint8)


def borders(ids):
    """Texels of land next to another country or the sea (the map wraps east-west)."""
    land = ids > 0
    edge = np.zeros_like(land)
    for shift in (1, -1):
        edge |= ids != np.roll(ids, shift, axis=1)
    edge[1:] |= ids[1:] != ids[:-1]
    edge[:-1] |= ids[:-1] != ids[1:]
    return land & edge


def night_lights(places, ids):
    """Each town is a soft glow sized by its population, on land only."""
    glow = np.zeros((HEIGHT, WIDTH), dtype=np.float64)
    for feature in places:
        props = feature["properties"]
        lon, lat = feature["geometry"]["coordinates"][:2]
        population = float(props.get("pop_max") or 0)
        if population < 20000:
            continue
        # Brightness grows faster than the log of the population, so cities
        # outshine towns the way they do from orbit.
        weight = (math.log10(population) - 4.2) ** 1.6
        sigma = min(2.4, max(0.5, 0.5 + 0.45 * (math.log10(population) - 4.5)))
        x, y = to_pixel(lon, lat)
        reach = int(math.ceil(sigma * 3))
        for dy in range(-reach, reach + 1):
            row = int(math.floor(y)) + dy
            if row < 0 or row >= HEIGHT:
                continue
            for dx in range(-reach, reach + 1):
                column = int(math.floor(x)) + dx
                cx, cy = column + 0.5 - x, row + 0.5 - y
                glow[row, column % WIDTH] += weight * math.exp(-(cx * cx + cy * cy) / (2 * sigma * sigma))
    # Coastal cities sit on the edge of the land; let their glow reach one
    # texel out to sea, and no further.
    land = ids > 0
    near_land = land.copy()
    for shift in (1, -1):
        near_land |= np.roll(land, shift, axis=1)
        near_land |= np.roll(land, shift, axis=0)
    glow[~near_land] = 0.0
    levels = np.clip(np.round(np.sqrt(glow / 2.0) * LIGHT_LEVELS), 0, LIGHT_LEVELS)
    return levels.astype(np.uint8)


# The menu icon shows the Americas with these countries unlocked, in the
# colours the app gives them by default.
ICON_COLOURS = {
    "USA": (255, 176, 59), "CRI": (64, 222, 145), "PRI": (255, 99, 170),
    "SLV": (90, 160, 255), "HND": (255, 226, 80), "COL": (255, 84, 84),
    "PAN": (180, 120, 255), "ESP": (255, 140, 50), "ITA": (150, 232, 80),
    "DEU": (50, 215, 220),
}


def render_icon(ids, edges, codes, size=24, centre=(-78.0, 18.0)):
    """A small lit globe, drawn four times larger and scaled down."""
    big = size * 4
    lam0, phi0 = np.radians(centre[0]), np.radians(centre[1])
    ys, xs = np.mgrid[0:big, 0:big]
    vx = (xs + 0.5) / big * 2 - 1
    vy = 1 - (ys + 0.5) / big * 2
    r2 = vx * vx + vy * vy
    inside = r2 <= 0.92 ** 2
    vx, vy = vx / 0.92, vy / 0.92
    vz = np.sqrt(np.clip(1 - vx * vx - vy * vy, 0, 1))
    east = np.array([-np.sin(lam0), np.cos(lam0), 0.0])
    north = np.array([-np.sin(phi0) * np.cos(lam0), -np.sin(phi0) * np.sin(lam0), np.cos(phi0)])
    out = np.array([np.cos(phi0) * np.cos(lam0), np.cos(phi0) * np.sin(lam0), np.sin(phi0)])
    world = vx[..., None] * east + vy[..., None] * north + vz[..., None] * out
    lat = np.degrees(np.arcsin(np.clip(world[..., 2], -1, 1)))
    lon = np.degrees(np.arctan2(world[..., 1], world[..., 0]))
    row = np.clip(((90 - lat) / 180 * HEIGHT).astype(int), 0, HEIGHT - 1)
    col = (((lon + 180) / 360 * WIDTH).astype(int)) % WIDTH
    country = ids[row, col]
    colour = np.zeros((big, big, 3))
    colour[...] = (24, 86, 170)
    colour[country > 0] = (92, 101, 110)
    colour[(country > 0) & edges[row, col]] = (138, 147, 156)
    for code, rgb in ICON_COLOURS.items():
        if code in codes:
            colour[country == codes[code]] = rgb
    light = 0.45 + 0.55 * np.clip(vx * -0.45 + vy * 0.55 + vz * 0.7, 0, 1)
    colour *= light[..., None]
    alpha = np.where(inside, 255, 0)
    rgba = np.dstack([np.clip(colour, 0, 255), alpha]).astype(np.uint8)
    icon = Image.fromarray(rgba, mode="RGBA").resize((size, size), Image.LANCZOS)
    return icon


def save_paletted(array, path, palette):
    image = Image.fromarray(array, mode="L").convert("P")
    image.putpalette(palette)
    image.save(path, optimize=True)


def id_palette(count):
    """Red is the id itself, so the map still reads right if a decoder expands
    the PNG to RGBA; green and blue tell neighbours apart when viewing it."""
    palette = []
    for index in range(256):
        palette += [index, 40 + (index * 89) % 200, 40 + (index * 53) % 200] if index else [0, 20, 48]
    return palette


def aux_palette():
    """Red is the value itself (see id_palette); green and blue show it."""
    palette = []
    for value in range(256):
        light = value & 7
        level = int(255 * light / LIGHT_LEVELS)
        palette += [value, 230 if value & 8 else int(level * 0.8), 160 if value & 8 else int(level * 0.4)]
    return palette


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cache", help="folder to keep the downloaded GeoJSON in")
    args = parser.parse_args()

    countries = fetch(COUNTRIES, args.cache)["features"]
    places = fetch(PLACES, args.cache)["features"]
    if len(countries) > 255:
        raise SystemExit("too many countries for an 8-bit id map")

    ids = rasterise_countries(countries)
    aux = night_lights(places, ids) | (borders(ids).astype(np.uint8) << 3)

    OUTPUT.mkdir(parents=True, exist_ok=True)
    save_paletted(ids, OUTPUT / "ids.png", id_palette(len(countries)))
    save_paletted(aux, OUTPUT / "aux.png", aux_palette())
    codes = {feature["properties"]["ADM0_A3"]: index + 1 for index, feature in enumerate(countries)}
    render_icon(ids, (aux & 8) > 0, codes).save(APP / "icon.png", optimize=True)

    table = []
    for feature in countries:
        props = feature["properties"]
        table.append([
            props["ADM0_A3"],
            props["NAME"],
            round(float(props["LABEL_X"]), 2),
            round(float(props["LABEL_Y"]), 2),
        ])
    (OUTPUT / "countries.json").write_text(json.dumps(table, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")

    for path in (OUTPUT / "ids.png", OUTPUT / "aux.png", OUTPUT / "countries.json", APP / "icon.png"):
        print(f"{path.name}: {path.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
