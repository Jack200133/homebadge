# The globe: an orthographic, texture-mapped sphere drawn a pixel at a time.
#
# Every pixel of the disc is turned back into a direction on the Earth, then
# into a texel of a 1024 x 512 map of country ids. Lighting comes from the
# angle to the sun, so the night side, the twilight band and the city lights
# fall out of the same lookup. The inner loop is integer only (2^14 fixed
# point) and runs as viper code on the badge. The simulator runs viper as
# plain Python, where it is still quick enough at half resolution.

import math
import sys
from array import array

from micropython import const

SIMULATOR = sys.platform == "webassembly"
if SIMULATOR:
    # The simulator's ptr8/ptr16/ptr32 helpers wrap every access in
    # struct calls; indexing the arrays directly is ten times faster and
    # reads the same values.
    def ptr8(buffer):
        return buffer

    ptr16 = ptr32 = ptr8

TEX_W = const(1024)
TEX_H = const(512)
ONE = const(16384)

# Lookup tables, packed into one array of unsigned 16-bit values:
#   sqrt(1 - r^2) for the depth of each pixel, by r^2 in 4096ths;
#   the map row for each height z;
#   the map column for each (x, y), on a 258 x 258 grid;
#   the lighting level for each angle to the sun.
# Each index is offset a little past -1 so values a rounding error beyond the
# unit sphere still land inside its table.
_O_LAT = const(4113)
_O_LON = const(8226)
_O_SHADE = const(74790)
_TABLES = const(75048)
_PALETTE = const(32)
LEVELS = const(32)

# The lighting levels: 0 is full night, 1-16 cover the twilight band in
# fine steps, 17-31 the day side from low sun to noon.
TWILIGHT_FROM = -0.24
TWILIGHT_TO = 0.16


def level_of(dot):
    if dot < TWILIGHT_FROM:
        return 0
    if dot < TWILIGHT_TO:
        return 1 + int((dot - TWILIGHT_FROM) / (TWILIGHT_TO - TWILIGHT_FROM) * 16)
    return min(31, 17 + int((dot - TWILIGHT_TO) / (1.0 - TWILIGHT_TO) * 15))


def dot_of(level):
    if level == 0:
        return TWILIGHT_FROM - 0.1
    if level <= 16:
        return TWILIGHT_FROM + (level - 0.5) * (TWILIGHT_TO - TWILIGHT_FROM) / 16
    return TWILIGHT_TO + (level - 16.5) * (1.0 - TWILIGHT_TO) / 15


def build_tables():
    tab = array("H", bytes(2 * _TABLES))
    for i in range(4097):
        tab[i] = int(ONE * math.sqrt(1.0 - i / 4096) + 0.5)
    for j in range(_O_LON - _O_LAT):
        z = max(-1.0, min(1.0, (j * 8 - 16444) / ONE))
        row = int((90.0 - math.degrees(math.asin(z))) / 180.0 * TEX_H)
        tab[_O_LAT + j] = max(0, min(TEX_H - 1, row))
    # The longitude grid is symmetric about both axes: work out one quadrant
    # and mirror it, which saves three quarters of the atan2 calls.
    scale = TEX_W / (2 * math.pi)
    half = TEX_W // 2
    for qy in range(129, 258):
        y = qy * 128 - 16448
        top = _O_LON + qy * 258
        bottom = _O_LON + (257 - qy) * 258
        for qx in range(129, 258):
            a = int(math.atan2(y, qx * 128 - 16448) * scale)   # 0 to a quarter turn
            mirror = 257 - qx
            tab[top + qx] = (half + a) % TEX_W
            tab[top + mirror] = (TEX_W + TEX_W - a) % TEX_W
            tab[bottom + qx] = (half - a) % TEX_W
            tab[bottom + mirror] = a % TEX_W
    for k in range(_TABLES - _O_SHADE):
        tab[_O_SHADE + k] = level_of((k * 128 - 16448) / ONE)
    return tab


@micropython.viper
def _combine(ids, aux, lut, count: int):
    # Turn country ids plus border and light bits into render classes, in place in aux.
    a = ptr8(ids)
    b = ptr8(aux)
    c = ptr8(lut)
    i = 0
    while i < count:
        x = b[i]
        b[i] = ((x & 7) << 5) | c[(a[i] << 1) | ((x >> 3) & 1)]
        i += 1


@micropython.viper
def _render(out, tex, tab, prm):
    o = ptr32(out)
    t = ptr8(tex)
    tb = ptr16(tab)
    p = ptr32(prm)
    width = p[0]
    cx = p[2]
    cy = p[3]
    radius = p[4]
    ex = p[5]
    ey = p[6]
    ez = p[7]
    nx = p[8]
    ny = p[9]
    nz = p[10]
    kx = p[11]
    ky = p[12]
    kz = p[13]
    sx = p[14]
    sy = p[15]
    sz = p[16]
    q = p[17]
    y = p[18]
    y1 = p[19]
    x0 = p[20]
    x1 = p[21]
    inv = p[22]
    stepx = p[23]
    stepy = p[24]
    stepz = p[25]
    while y < y1:
        dy = y - cy
        dy2 = dy * dy
        row = y * width
        xs = x1
        xe = x1
        si = (dy2 * q) >> 16
        if si <= 4096:
            half = (radius * tb[si]) >> 14
            xs = cx - half
            xe = cx + half + 1
            if xs < x0:
                xs = x0
            if xe > x1:
                xe = x1
            if xs > xe:
                xs = xe
        i = row + x0
        stop = row + xs
        while i < stop:
            o[i] = 0
            i += 1
        if xs < xe:
            # Screen x and y as fractions of the radius, then the part of the
            # world direction that is linear across the row (2^28 units).
            vy = ((0 - dy) * inv) >> 6
            dx = xs - cx
            vx = (dx * inv) >> 6
            ax = ex * vx + nx * vy
            ay = ey * vx + ny * vy
            az = ez * vx + nz * vy
            r2 = dx * dx + dy2
            stop = row + xe
            while i < stop:
                si = (r2 * q) >> 16
                if si > 4096:
                    si = 4096
                vz = tb[si]
                wx = (ax + kx * vz) >> 14
                wy = (ay + ky * vz) >> 14
                wz = (az + kz * vz) >> 14
                lat = tb[_O_LAT + ((wz + 16448) >> 3)]
                lon = tb[_O_LON + ((wy + 16512) >> 7) * 258 + ((wx + 16512) >> 7)]
                v = t[(lat << 10) + lon]
                d = (wx * sx + wy * sy + wz * sz) >> 14
                o[i] = p[_PALETTE + (v << 5) + tb[_O_SHADE + ((d + 16512) >> 7)]]
                ax += stepx
                ay += stepy
                az += stepz
                r2 += dx + dx + 1
                dx += 1
                i += 1
        stop = row + x1
        while i < stop:
            o[i] = 0
            i += 1
        y += 1


def smoothstep(a, b, x):
    if x <= a:
        return 0.0
    if x >= b:
        return 1.0
    x = (x - a) / (b - a)
    return x * x * (3 - 2 * x)


def pack(r, g, b):
    """An opaque pixel as the signed 32-bit value the frame buffer holds (RGBA bytes)."""
    r = max(0, min(255, int(r)))
    g = max(0, min(255, int(g)))
    b = max(0, min(255, int(b)))
    return ((b << 16) | (g << 8) | r) - 16777216


OCEAN_DAY = (24, 86, 170)
OCEAN_NIGHT = (3, 8, 24)
LOCKED_DAY = (92, 101, 110)
LOCKED_EDGE_DAY = (138, 147, 156)
LOCKED_NIGHT = (17, 21, 31)
LOCKED_EDGE_NIGHT = (30, 35, 48)
CITY_LIGHT = (255, 204, 112)
SUNSET = (255, 132, 48)


def class_colours(visited_colours):
    """(day colour, night colour, has city lights) for each of the 32 classes."""
    classes = [(OCEAN_DAY, OCEAN_NIGHT, False),
               (LOCKED_DAY, LOCKED_NIGHT, True),
               (LOCKED_EDGE_DAY, LOCKED_EDGE_NIGHT, True)]
    for r, g, b in visited_colours:
        # Unlocked countries keep a little of their colour at night.
        classes.append(((r, g, b), (r * 0.2 + 6, g * 0.2 + 6, b * 0.2 + 10), True))
        classes.append(((r * 0.5 + 128, g * 0.5 + 128, b * 0.5 + 128),
                        (r * 0.45 + 30, g * 0.45 + 30, b * 0.45 + 30), True))
    while len(classes) < 32:
        classes.append(classes[1])
    return classes[:32]


def build_palette(prm, visited_colours):
    classes = class_colours(visited_colours)
    weights = []
    for level in range(LEVELS):
        dot = dot_of(level)
        daylight = smoothstep(-0.15, 0.1, dot)
        sun = 0.3 + 0.7 * max(0.0, dot) ** 0.8
        glow = math.exp(-((dot + 0.02) / 0.05) ** 2) * 0.32
        lights = (1.0 - smoothstep(-0.14, 0.02, dot)) ** 1.5
        weights.append((daylight * sun, 1.0 - daylight, glow, lights))
    for value in range(256):
        day, night, lit = classes[value & 31]
        brightness = (value >> 5) / 7
        light = brightness * brightness * 0.9 if lit else 0.0
        base = _PALETTE + (value << 5)
        for level in range(LEVELS):
            d, n, glow, lights = weights[level]
            shine = light * lights
            prm[base + level] = pack(
                day[0] * d + night[0] * n + SUNSET[0] * glow * 0.5 + CITY_LIGHT[0] * shine,
                day[1] * d + night[1] * n + SUNSET[1] * glow * 0.4 + CITY_LIGHT[1] * shine,
                day[2] * d + night[2] * n + SUNSET[2] * glow * 0.3 + CITY_LIGHT[2] * shine,
            )


class Globe:
    """The textures, tables and buffers, and draw() to put the globe on screen."""

    def __init__(self, visited_ids, visited_colours, progress=None):
        """visited_ids maps a country id (index + 1 in countries.json) to its slot."""
        report = progress or (lambda step: None)
        report("Reading the map")
        self.ids_image = image.load("assets/ids.png")
        self.ids = memoryview(self.ids_image)
        lights_image = image.load("assets/aux.png")
        self.tex_image = lights_image
        self.tex = memoryview(lights_image)
        if len(self.ids) != TEX_W * TEX_H or len(self.tex) != TEX_W * TEX_H:
            raise ValueError("the map textures must be 1024 x 512 paletted PNGs")

        report("Unlocking countries")
        lut = bytearray(512)
        for country in range(1, 256):
            slot = visited_ids.get(country)
            base = 1 if slot is None else 3 + 2 * (slot % 14)
            lut[country * 2] = base
            lut[country * 2 + 1] = base + 1
        _combine(self.ids, self.tex, lut, TEX_W * TEX_H)

        report("Measuring the sphere")
        self.tab = build_tables()

        report("Mixing the colours")
        self.prm = array("i", bytes(4 * (_PALETTE + 256 * LEVELS)))
        build_palette(self.prm, visited_colours)

        report("Lighting the cities")
        self.full = array("i", bytes(4 * screen.width * screen.height))
        self.full_image = image(screen.width, screen.height, self.full)
        hw, hh = screen.width // 2, screen.height // 2
        self.half = array("i", bytes(4 * hw * hh))
        self.half_image = image(hw, hh, self.half)
        self.last_key = None
        self.last_scale = 1
        self.last_box = None

    def country_at(self, lat, lon):
        """The country id under a point, 0 for the sea."""
        row = max(0, min(TEX_H - 1, int((90.0 - lat) / 180.0 * TEX_H)))
        col = int((lon + 180.0) / 360.0 * TEX_W) % TEX_W
        return self.ids[row * TEX_W + col]

    def draw(self, cx, cy, radius, east, north, out, sun, scale):
        """Render and blit the globe. Returns True if the pixels were recomputed.

        east, north and out are the world directions of the screen's right,
        up and towards-the-viewer axes; sun is the direction of the sun.
        """
        if scale == 2:
            buffer, picture = self.half, self.half_image
            width, height = screen.width // 2, screen.height // 2
            cx, cy, radius = cx / 2, cy / 2, radius / 2
        else:
            buffer, picture = self.full, self.full_image
            width, height = screen.width, screen.height
        icx, icy, irad = int(cx + 0.5), int(cy + 0.5), max(8, int(radius + 0.5))
        x0, x1 = max(0, icx - irad - 1), min(width, icx + irad + 2)
        y0, y1 = max(0, icy - irad - 1), min(height, icy + irad + 2)
        if x1 <= x0 or y1 <= y0:
            return False

        rows = []
        for vector in (east, north, out, sun):
            rows.extend(int(c * ONE + (0.5 if c >= 0 else -0.5)) for c in vector)
        key = (scale, icx, icy, irad, tuple(rows))
        fresh = key != self.last_key
        if fresh:
            p = self.prm
            inv = (1 << 20) // irad
            p[0] = width
            p[1] = height
            p[2] = icx
            p[3] = icy
            p[4] = irad
            for index in range(12):
                p[5 + index] = rows[index]
            p[17] = (4096 << 16) // (irad * irad)
            p[18] = y0
            p[19] = y1
            p[20] = x0
            p[21] = x1
            p[22] = inv
            p[23] = (rows[0] * inv) >> 6
            p[24] = (rows[1] * inv) >> 6
            p[25] = (rows[2] * inv) >> 6
            _render(buffer, self.tex, self.tab, p)
            self.last_key = key

        if scale == 2:
            screen.blit(picture, rect(x0, y0, x1 - x0, y1 - y0),
                        rect(x0 * 2, y0 * 2, (x1 - x0) * 2, (y1 - y0) * 2))
        else:
            screen.blit(picture, rect(x0, y0, x1 - x0, y1 - y0), rect(x0, y0, x1 - x0, y1 - y0))
        return fresh
