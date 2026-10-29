# Small national flags for the info card, drawn with shapes so they stay sharp.

RED = color.rgb(206, 17, 38)
WHITE = color.rgb(255, 255, 255)
BLUE = color.rgb(0, 56, 147)
NAVY = color.rgb(10, 49, 97)
YELLOW = color.rgb(252, 209, 22)
GOLD = color.rgb(255, 206, 0)
BLACK = color.rgb(0, 0, 0)
GREEN = color.rgb(0, 146, 70)
SKY = color.rgb(0, 71, 171)
LIGHT_BLUE = color.rgb(15, 71, 175)
SPANISH_RED = color.rgb(170, 21, 27)
SPANISH_YELLOW = color.rgb(241, 191, 0)
OUTLINE = color.rgb(255, 255, 255, 90)


def bands(x, y, w, h, colours, weights=None, vertical=False):
    """Stripes across (or down) the flag, sized by weights."""
    weights = weights or [1] * len(colours)
    total = sum(weights)
    at = 0
    for pen, weight in zip(colours, weights):
        screen.pen = pen
        if vertical:
            screen.rectangle(x + w * at / total, y, w * weight / total + 0.5, h)
        else:
            screen.rectangle(x, y + h * at / total, w, h * weight / total + 0.5)
        at += weight


def star(cx, cy, size, pen):
    screen.pen = pen
    screen.shape(shape.star(cx, cy, 5, size * 0.42, size))


def usa(x, y, w, h):
    bands(x, y, w, h, [RED, WHITE] * 3 + [RED])
    screen.pen = NAVY
    screen.rectangle(x, y, w * 0.42, h * 4 / 7)
    screen.pen = WHITE
    for row in range(3):
        for col in range(4):
            screen.rectangle(x + 1.5 + col * w * 0.1, y + 1.5 + row * h * 0.17, 1, 1)


def costa_rica(x, y, w, h):
    bands(x, y, w, h, [BLUE, WHITE, RED, WHITE, BLUE], [1, 1, 2, 1, 1])


def puerto_rico(x, y, w, h):
    bands(x, y, w, h, [RED, WHITE, RED, WHITE, RED])
    screen.pen = color.rgb(0, 80, 240)
    screen.shape(shape.custom([vec2(x, y), vec2(x + w * 0.45, y + h / 2), vec2(x, y + h)]))
    star(x + w * 0.15, y + h / 2, h * 0.17, WHITE)


def el_salvador(x, y, w, h):
    bands(x, y, w, h, [LIGHT_BLUE, WHITE, LIGHT_BLUE])
    screen.pen = color.rgb(220, 180, 60)
    screen.shape(shape.circle(x + w / 2, y + h / 2, h * 0.11))


def honduras(x, y, w, h):
    bands(x, y, w, h, [color.rgb(0, 115, 207), WHITE, color.rgb(0, 115, 207)])
    screen.pen = color.rgb(0, 115, 207)
    cx, cy, gap = x + w / 2, y + h / 2, h * 0.13
    for dx, dy in ((-2, -0.7), (2, -0.7), (0, 0), (-2, 0.7), (2, 0.7)):
        screen.shape(shape.circle(cx + dx * gap, cy + dy * gap, 0.8))


def colombia(x, y, w, h):
    bands(x, y, w, h, [YELLOW, color.rgb(0, 56, 147), RED], [2, 1, 1])


def panama(x, y, w, h):
    screen.pen = WHITE
    screen.rectangle(x, y, w, h)
    screen.pen = RED
    screen.rectangle(x + w / 2, y, w / 2, h / 2)
    screen.pen = color.rgb(0, 82, 147)
    screen.rectangle(x, y + h / 2, w / 2, h / 2)
    star(x + w / 4, y + h / 4, h * 0.16, color.rgb(0, 82, 147))
    star(x + w * 3 / 4, y + h * 3 / 4, h * 0.16, RED)


def spain(x, y, w, h):
    bands(x, y, w, h, [SPANISH_RED, SPANISH_YELLOW, SPANISH_RED], [1, 2, 1])
    screen.pen = color.rgb(170, 21, 27, 200)
    screen.rectangle(x + w * 0.25, y + h * 0.38, w * 0.1, h * 0.24)


def italy(x, y, w, h):
    bands(x, y, w, h, [GREEN, WHITE, RED], vertical=True)


def germany(x, y, w, h):
    bands(x, y, w, h, [BLACK, RED, GOLD])


FLAGS = {
    "USA": usa,
    "CRI": costa_rica,
    "PRI": puerto_rico,
    "SLV": el_salvador,
    "HND": honduras,
    "COL": colombia,
    "PAN": panama,
    "ESP": spain,
    "ITA": italy,
    "DEU": germany,
}


def draw(code, x, y, w, h):
    """Draw the flag for an ISO 3166 alpha-3 code. Returns False when there is none."""
    painter = FLAGS.get(code)
    if painter is None:
        return False
    painter(x, y, w, h)
    screen.pen = OUTLINE
    screen.shape(shape.rectangle(x, y, w, h).stroke(1))
    return True
