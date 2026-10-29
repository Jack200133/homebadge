# Travel Globe: the countries you have visited, unlocked on a spinning 3D
# globe with live day and night, twilight and city lights on the night side.
#
# Controls:
#   tilt the badge  the globe leans and turns with it
#   left / right    fly to the previous / next unlocked country
#   up / down       zoom in / out (hold)
#   select          start or stop a tour of your countries
#   menu            time-lapse: live, then an hour or four hours a second
#   back            back to the spinning overview, at the live time

import json
import math
import os
import sys
import time

APP_DIR = "/system/apps/travel_globe"
os.chdir(APP_DIR)
sys.path.insert(0, APP_DIR)

import flags
import sky
from globe import Globe

# ---- the countries you have visited -------------------------------------
# Add a line to unlock another country: its ISO 3166 alpha-3 code (as listed
# in assets/countries.json), the name to show, its standard UTC offset in
# hours, its summer time rule ("us", "eu" or None), how close to zoom in on
# it, and its colour. Up to 14 countries get colours of their own.
VISITED = (
    ("USA", "USA", -5, "us", 1.25, (255, 176, 59)),       # local time for the East Coast
    ("CRI", "Costa Rica", -6, None, 2.7, (64, 222, 145)),
    ("PRI", "Puerto Rico", -4, None, 2.8, (255, 99, 170)),
    ("SLV", "El Salvador", -6, None, 2.9, (90, 160, 255)),
    ("HND", "Honduras", -6, None, 2.6, (255, 226, 80)),
    ("COL", "Colombia", -5, None, 1.7, (255, 84, 84)),
    ("PAN", "Panamá", -5, None, 2.7, (180, 120, 255)),
    ("ESP", "España", 1, "eu", 2.0, (255, 140, 50)),
    ("ITA", "Italia", 1, "eu", 2.1, (150, 232, 80)),
    ("DEU", "Alemania", 1, "eu", 2.4, (50, 215, 220)),
)
WORLD_COUNTRIES = 195

badge.mode(HIRES | VSYNC)
screen.antialias = image.X2
WIDTH, HEIGHT = screen.width, screen.height

CENTRE_X, CENTRE_Y = WIDTH / 2, 114
RADIUS = 94
ZOOM_MIN, ZOOM_MAX = 1.0, 3.2
ZOOM_RATE = 1.4             # what a second of holding up multiplies the zoom by
SPIN_DEGREES_PER_S = 6.0    # a turn a minute
SPIN_LAT = 18.0             # the overview looks down from a little north of the equator
FLY_MS = 420                # time constant of the camera's ease towards its target
TOUR_MS = 6500              # how long the tour stays on each country
NEARBY_DEGREES = 24.0       # a country this close to the middle gets the info card
TIME_SPEEDS = (1, 3600, 14400)

# Tilt, smoothed like the menu's Mona: sideways turns the globe, forward
# and back leans it, and the rest position drifts to how the badge is held.
TILT_GRAVITY = 16384.0
TILT_SMOOTH_MS = 160
TILT_RECENTRE_MS = 3000
TILT_LON_DEGREES = 38.0
TILT_LAT_DEGREES = 26.0
TILT_ROLL_DEGREES = 9.0

# Rendering the globe costs about the same for every pixel. While it moves,
# a frame that would take longer than this is drawn at half resolution and
# scaled up; once the view holds still it is drawn again at full resolution.
FULL_RES_MS = 75
HALF_RES_BELOW_MS = 55
SETTLE_FRAMES = 3

SPACE = color.rgb(2, 4, 12)
WHITE = color.rgb(240, 244, 248)
TEXT = color.rgb(226, 232, 240)
MUTED = color.rgb(140, 150, 166)
ACCENT = color.rgb(95, 237, 131)
CARD = color.rgb(6, 10, 22, 200)
CARD_EDGE = color.rgb(255, 255, 255, 36)
SUN_PEN = color.rgb(255, 210, 80)
MOON_PEN = color.rgb(214, 222, 240)
TWILIGHT_PEN = color.rgb(255, 150, 90)
LOCKED_TEXT = color.rgb(110, 118, 132)

name_font = font.absolute
small_font = font.sins
time_font = font.absolute


def shortest(degrees):
    return (degrees + 180.0) % 360.0 - 180.0


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def loading(step, done=[0]):
    """A plain page while the map loads; each step moves the bar on."""
    done[0] += 1
    screen.pen = SPACE
    screen.clear()
    screen.font = name_font
    screen.pen = WHITE
    title = "Travel Globe"
    w, _ = screen.measure_text(title)
    screen.text(title, (WIDTH - w) / 2, 92)
    screen.font = small_font
    screen.pen = MUTED
    w, _ = screen.measure_text(step)
    screen.text(step, (WIDTH - w) / 2, 124)
    screen.pen = color.rgb(255, 255, 255, 40)
    screen.rectangle(90, 146, 140, 3)
    screen.pen = ACCENT
    screen.rectangle(90, 146, 140 * min(1.0, done[0] / 6), 3)
    badge.update()


class TimeSync:
    """Sets the globe's clock from the internet once, when Wi-Fi is configured.

    The badge clock may hold local time (the Clock app sets it that way), and
    the sun has to be placed from UTC, so an NTP reading wins when one comes.
    """

    GIVE_UP_MS = 60000
    RETRY_MS = 8000
    ATTEMPTS = 3

    def __init__(self):
        self.state = "off"
        self.wifi = None
        # Wi-Fi only sharpens the clock, so nothing it does may stop the globe.
        try:
            import missing_details
            if missing_details.missing("WIFI_SSID"):
                return
            import wifi
            # Retries are set high so wifi never puts up its own error page;
            # this gives up on its own after GIVE_UP_MS instead.
            wifi.connect(timeout=10, retries=100000)
        except Exception as reason:
            print("travel_globe: no Wi-Fi:", reason)
            return
        self.wifi = wifi
        self.started = badge.ticks
        self.retry_at = 0
        self.attempts = 0
        self.state = "connecting"

    def finish(self, state):
        self.state = state
        disconnect = getattr(self.wifi, "disconnect", None)
        if disconnect is not None:
            try:
                disconnect()            # the radio is not needed again
            except Exception:
                pass

    def step(self, clock):
        if self.state != "connecting":
            return
        now = badge.ticks
        if now - self.started > self.GIVE_UP_MS:
            self.finish("failed")
            return
        if now < self.retry_at:
            return
        try:
            if not self.wifi.connect():
                return
            import ntptime
            # The request blocks for up to this long, once.
            ntptime.timeout = 1
            clock.correction = ntptime.time() - time.time()
        except Exception as reason:
            self.attempts += 1
            print("travel_globe: time sync failed:", reason)
            if self.attempts >= self.ATTEMPTS:
                self.finish("failed")
            else:
                self.retry_at = now + self.RETRY_MS
            return
        clock.read()
        self.finish("synced")


booted_at = time.ticks_ms()
loading("Opening the atlas")
# The radio starts before the map is read, so it can associate meanwhile.
sync = TimeSync()
with open("assets/countries.json", "r") as handle:
    COUNTRIES = json.load(handle)            # [code, name, label lon, label lat] by id - 1
ids_by_code = {entry[0]: index + 1 for index, entry in enumerate(COUNTRIES)}


class Place:
    def __init__(self, slot, code, label, utc_hours, rule, zoom, rgb):
        self.slot = slot
        self.code = code
        self.label = label
        self.utc_hours = utc_hours
        self.rule = rule
        self.zoom = zoom
        self.pen = color.rgb(*rgb)
        self.ring = color.rgb(rgb[0], rgb[1], rgb[2], 150)
        _, _, self.lon, self.lat = COUNTRIES[ids_by_code[code] - 1]
        self.vector = sky.to_vector(self.lat, self.lon)


places = []
for code, label, utc_hours, rule, zoom, rgb in VISITED:
    if code not in ids_by_code:
        print("travel_globe: no country with code", code)
        continue
    places.append(Place(len(places), code, label, utc_hours, rule, zoom, rgb))

globe = Globe({ids_by_code[p.code]: p.slot for p in places}, [v[5] for v in VISITED if v[0] in ids_by_code], loading)


class Tilt:
    def __init__(self):
        self.x = 0.0
        self.y = 0.0
        self.rest_z = None
        self.last_ticks = None
        self.flipped = None

    def update(self):
        ax, ay, az = badge.imu()[:3]
        if not (ax or ay or az):
            return                  # no reading from the sensor yet
        # Upside down, the display turns half a turn in its own plane: across
        # the screen reverses, towards the viewer does not.
        flipped = badge.rotate_180()
        if flipped:
            ax = -ax
        if flipped != self.flipped:
            self.flipped = flipped
            self.rest_z = None
        now = badge.ticks
        dt = min(now - self.last_ticks, 200) if self.last_ticks is not None else 0
        self.last_ticks = now
        smooth = 1 - math.exp(-dt / TILT_SMOOTH_MS)
        recentre = 1 - math.exp(-dt / TILT_RECENTRE_MS)
        if self.rest_z is None:
            self.rest_z = az
        self.rest_z += (az - self.rest_z) * recentre
        target_x = max(-1.0, min(1.0, -ax / TILT_GRAVITY * 2))
        target_y = max(-1.0, min(1.0, (az - self.rest_z) / TILT_GRAVITY * 2))
        self.x += (target_x - self.x) * smooth
        self.y += (target_y - self.y) * smooth


def make_stars(count):
    """Star positions in four brightness groups, so each group needs one pen."""
    groups = [[], [], [], []]
    seed = 1234567
    for index in range(count):
        seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
        x = seed % WIDTH
        seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
        groups[index % 4].append((x, seed % HEIGHT))
    return groups


STARS = make_stars(90)
STAR_PENS = [color.rgb(v, v, v + 10) for v in (60, 95, 140, 210)]

# Past this radius the globe covers the whole screen: from the centre of the
# globe to the furthest corner.
COVERS_SCREEN = math.sqrt(max(CENTRE_X, WIDTH - CENTRE_X) ** 2 + max(CENTRE_Y, HEIGHT - CENTRE_Y) ** 2)

GLOW_STOPS = [
    (0.0, color.rgb(70, 150, 255, 0)),
    (0.84, color.rgb(70, 150, 255, 0)),
    (0.86, color.rgb(90, 170, 255, 120)),
    (0.92, color.rgb(70, 140, 255, 40)),
    (1.0, color.rgb(60, 120, 255, 0)),
]
RIM_STOPS = [
    (0.0, color.rgb(120, 190, 255, 0)),
    (0.78, color.rgb(120, 190, 255, 0)),
    (0.97, color.rgb(120, 190, 255, 70)),
    (1.0, color.rgb(160, 210, 255, 140)),
]
GLOW_REACH = 1.17
GLOW_FROM = 0.97            # the glow is clear inside this much of the radius
RIM_FROM = 0.77             # and so is the rim
glow_brush = brush.gradient(brush.RADIAL, 0.5, 0.5, 1.0, 0.5, GLOW_STOPS, mat3())
rim_brush = brush.gradient(brush.RADIAL, 0.5, 0.5, 1.0, 0.5, RIM_STOPS, mat3())

clock = sky.Clock()
tilt = Tilt()
print("travel_globe: ready in %d ms" % time.ticks_diff(time.ticks_ms(), booted_at))

mode = "spin"               # spin, focus or tour
focus = None                # the Place in view, when focused or touring
focused_at = 0
speed_index = 0
spin_lon = -70.0            # start over the Americas
cam_lon, cam_lat = spin_lon, SPIN_LAT
zoom = 1.0
zoom_target = 1.0
scale = 1
cost_us = 2.0               # measured microseconds a globe pixel
still_frames = 0
last_view = None
held_view = None            # the view actually drawn, which moves in pixel steps
sun = (1.0, 0.0, 0.0)
sun_at = None               # (day, second) the sun was last placed for
SUN_EVERY_S = 30            # the terminator moves a quarter of a degree a minute
frames = 0
report_at = 0
started_at = badge.ticks
hint_done = False           # any button press puts the info card back


def nearest_place(vector):
    best, best_dot = None, -2.0
    for place in places:
        d = dot(place.vector, vector)
        if d > best_dot:
            best, best_dot = place, d
    return best, best_dot


def fly_to(place, how):
    global mode, focus, focused_at, zoom_target
    mode = how
    focus = place
    focused_at = badge.ticks
    zoom_target = place.zoom


def step_focus(step, view):
    if not places:
        return
    if focus is None:
        place, _ = nearest_place(view)
        if step < 0:
            place = places[(place.slot - 1) % len(places)] if place is not None else places[-1]
    else:
        place = places[(focus.slot + step) % len(places)]
    fly_to(place, "tour" if mode == "tour" else "focus")


def overview():
    global mode, focus, spin_lon, zoom_target, speed_index
    mode = "spin"
    focus = None
    spin_lon = cam_lon
    zoom_target = 1.0
    speed_index = 0
    clock.live()


def handle_input(dt, view):
    global zoom_target, mode, speed_index, hint_done
    if badge.pressed():
        hint_done = True
    if badge.pressed(BUTTON_RIGHT):
        step_focus(1, view)
    if badge.pressed(BUTTON_LEFT):
        step_focus(-1, view)
    grow = 1 + (ZOOM_RATE - 1) * dt / 1000
    if badge.held(BUTTON_UP):
        zoom_target = min(ZOOM_MAX, zoom_target * grow)
    if badge.held(BUTTON_DOWN):
        zoom_target = max(ZOOM_MIN, zoom_target / grow)
    if badge.pressed(BUTTON_SELECT) and places:
        if mode == "tour":
            mode = "focus"
        else:
            place = focus or nearest_place(view)[0]
            fly_to(place, "tour")
    if badge.pressed(BUTTON_MENU):
        speed_index = (speed_index + 1) % len(TIME_SPEEDS)
        if TIME_SPEEDS[speed_index] == 1:
            clock.live()
        else:
            clock.speed = TIME_SPEEDS[speed_index]
    if badge.pressed(BUTTON_BACK):
        overview()


def move_camera(dt):
    global spin_lon, cam_lon, cam_lat, zoom
    if mode == "tour" and badge.ticks - focused_at > TOUR_MS:
        fly_to(places[(focus.slot + 1) % len(places)], "tour")
    if mode == "spin":
        spin_lon -= SPIN_DEGREES_PER_S * dt / 1000
        target_lon, target_lat = spin_lon, SPIN_LAT
    else:
        target_lon, target_lat = focus.lon, focus.lat
    ease = 1 - math.exp(-dt / FLY_MS)
    cam_lon = shortest(cam_lon + shortest(target_lon - cam_lon) * ease)
    cam_lat += (target_lat - cam_lat) * ease
    zoom *= math.exp(math.log(zoom_target / zoom) * ease)


def view_axes(radius):
    """Screen right, up and out of the screen, as world directions.

    The view only moves once the camera has gone about half a pixel, so a
    hand's tremor does not redraw a globe that looks the same.
    """
    global held_view
    lon = cam_lon - tilt.x * TILT_LON_DEGREES
    lat = max(-80.0, min(80.0, cam_lat + tilt.y * TILT_LAT_DEGREES))
    roll = tilt.x * TILT_ROLL_DEGREES
    step = max(0.05, math.degrees(0.5 / radius))
    if held_view is not None:
        held_lon, held_lat, held_roll = held_view
        if abs(shortest(lon - held_lon)) < step and abs(lat - held_lat) < step and abs(roll - held_roll) < 4 * step:
            lon, lat, roll = held_view
    held_view = (lon, lat, roll)
    roll = math.radians(roll)
    lam, phi = math.radians(lon), math.radians(lat)
    cl, sl, cp, sp = math.cos(lam), math.sin(lam), math.cos(phi), math.sin(phi)
    out = (cp * cl, cp * sl, sp)
    east = (-sl, cl, 0.0)
    north = (-sp * cl, -sp * sl, cp)
    cr, sr = math.cos(roll), math.sin(roll)
    right = tuple(east[i] * cr + north[i] * sr for i in range(3))
    up = tuple(north[i] * cr - east[i] * sr for i in range(3))
    return right, up, out, lat, lon


def update_sun():
    """Place the sun: every frame in a time-lapse, every SUN_EVERY_S when live."""
    global sun, sun_at
    if (clock.speed == 1 and sun_at is not None and sun_at[0] == clock.day
            and 0 <= clock.second - sun_at[1] < SUN_EVERY_S):
        return
    sun_at = (clock.day, clock.second)
    lat, lon = sky.sun_position(clock.day, clock.second)
    sun = sky.to_vector(lat, lon)


def draw_stars(radius):
    if radius > COVERS_SCREEN:
        return
    # Nearer (brighter) stars drift further as the badge tilts; one star in
    # a few dozen blinks out for a moment.
    blink = badge.ticks // 90 % 37
    for level in range(4):
        dx = int(tilt.x * 1.5 * (level + 1))
        dy = int(-tilt.y * (level + 1))
        screen.pen = STAR_PENS[level]
        for index, (x, y) in enumerate(STARS[level]):
            if index != blink:
                screen.put((x + dx) % WIDTH, (y + dy) % HEIGHT)


def draw_glow(radius):
    """The atmosphere outside the disc, as a ring so the hidden middle costs nothing."""
    if radius * GLOW_FROM > COVERS_SCREEN:
        return
    reach = radius * GLOW_REACH
    glow_brush.geometry(0.5, 0.5, 1.0, 0.5, mat3().translate(CENTRE_X - reach, CENTRE_Y - reach).scale(reach * 2, reach * 2))
    screen.pen = glow_brush
    screen.shape(shape.arc(CENTRE_X, CENTRE_Y, radius * GLOW_FROM, reach, 0, 360))


def draw_rim(radius):
    """Haze inside the edge of the disc."""
    if radius * RIM_FROM > COVERS_SCREEN:
        return
    rim_brush.geometry(0.5, 0.5, 1.0, 0.5, mat3().translate(CENTRE_X - radius, CENTRE_Y - radius).scale(radius * 2, radius * 2))
    screen.pen = rim_brush
    screen.shape(shape.arc(CENTRE_X, CENTRE_Y, radius * RIM_FROM, radius + 0.5, 0, 360))


def project(vector, right, up, out, radius):
    """Screen position of a point on the globe, or None on the far side."""
    depth = dot(vector, out)
    if depth < 0.06:
        return None
    return CENTRE_X + radius * dot(vector, right), CENTRE_Y - radius * dot(vector, up), depth


def draw_markers(right, up, out, radius):
    pulse = (badge.ticks % 1400) / 1400
    for place in places:
        spot = project(place.vector, right, up, out, radius)
        if spot is None:
            continue
        x, y, depth = spot
        if place is focus:
            screen.pen = color.rgb(255, 255, 255, int(200 * (1 - pulse)))
            screen.shape(shape.circle(x, y, 4 + 9 * pulse * zoom).stroke(1.5))
            if zoom > 1.8:
                continue            # close in, the country speaks for itself
        screen.pen = color.rgb(0, 0, 0, 120)
        screen.shape(shape.circle(x, y + 0.6, 3.2))
        screen.pen = WHITE
        screen.shape(shape.circle(x, y, 3.0))
        screen.pen = place.pen
        screen.shape(shape.circle(x, y, 2.0))


def daylight_at(vector):
    d = dot(vector, sun)
    if d > 0.0:
        return "day"
    if d > -0.1:
        return "twilight"
    return "night"


def draw_sun_icon(x, y, when):
    if when == "day":
        screen.pen = SUN_PEN
        screen.shape(shape.circle(x, y, 4))
        for k in range(8):
            a = k * math.pi / 4
            screen.shape(shape.line(vec2(x + math.cos(a) * 6, y + math.sin(a) * 6),
                                    vec2(x + math.cos(a) * 8, y + math.sin(a) * 8), 1.2))
    elif when == "twilight":
        screen.pen = TWILIGHT_PEN
        screen.shape(shape.pie(x, y, 6, 270, 450))     # the top half: 0 is 12 o'clock
        screen.shape(shape.line(vec2(x - 8, y + 1.5), vec2(x + 8, y + 1.5), 1.2))
    else:
        screen.pen = MOON_PEN
        screen.shape(shape.circle(x, y, 5.5))
        screen.pen = CARD
        screen.shape(shape.circle(x + 2.6, y - 1.8, 4.6))


def draw_lock(x, y):
    screen.pen = MUTED
    screen.shape(shape.arc(x + 6, y + 6, 2.6, 4.2, 270, 450))
    screen.shape(shape.rounded_rectangle(x + 1, y + 6, 10, 8, 1.5))


def text_width(text, typeface):
    screen.font = typeface
    return screen.measure_text(text)[0]


def fit(text, typeface, room):
    """The text, cut short with a full stop if it would not fit in room pixels."""
    if text_width(text, typeface) <= room:
        return text
    while len(text) > 1 and text_width(text + ".", typeface) > room:
        text = text[:-1].rstrip()
    return text + "."


HINTS = (
    ("< >  fly to your countries", "^ v  zoom      tilt to look around"),
    ("select  take the tour", "menu  time-lapse      back  overview"),
)
HINT_MS = 4000


def draw_card(place, view_vector, lat, lon):
    top = HEIGHT - 38
    screen.pen = CARD
    screen.shape(shape.rounded_rectangle(6, top, WIDTH - 12, 34, 6))
    screen.pen = CARD_EDGE
    screen.shape(shape.rounded_rectangle(6, top, WIDTH - 12, 34, 6).stroke(1))
    shown_for = badge.ticks - started_at
    if not hint_done and shown_for < HINT_MS * len(HINTS):
        screen.font = small_font
        first, second = HINTS[shown_for // HINT_MS]
        screen.pen = TEXT
        screen.text(first, 16, top + 4)
        screen.pen = MUTED
        screen.text(second, 16, top + 18)
        return
    if place is not None:
        hours, minutes, _ = sky.local_time(clock.day, clock.second, place.utc_hours, place.rule)
        stamp = "%02d:%02d" % (hours, minutes)
        when = daylight_at(place.vector)
        left, name, pen = 50, place.label, WHITE
        line = "unlocked %d of %d" % (place.slot + 1, len(places))
        line_pen = place.pen
        flags.draw(place.code, 14, top + 8, 27, 18)
    else:
        # Local solar time from the longitude, when there is no time zone to hand.
        minutes = int(clock.second / 60 + lon * 4) % 1440
        stamp = "~%02d:%02d" % (minutes // 60, minutes % 60)
        when = daylight_at(view_vector)
        country = globe.country_at(lat, lon)
        left, pen, line_pen = 16, MUTED, LOCKED_TEXT
        if country:
            draw_lock(16, top + 9)
            left, name, line = 36, COUNTRIES[country - 1][1], "locked"
        else:
            name, line = "Ocean", "%d of %d countries unlocked" % (len(places), WORLD_COUNTRIES)
    stamp_x = WIDTH - 32 - text_width(stamp, time_font)
    screen.font = name_font
    screen.pen = pen
    screen.text(fit(name, name_font, stamp_x - left - 6), left, top + 3)
    screen.font = small_font
    screen.pen = line_pen
    screen.text(line, left, top + 20)
    screen.font = time_font
    screen.pen = TEXT
    screen.text(stamp, stamp_x, top + 9)
    draw_sun_icon(WIDTH - 21, top + 17, when)


def draw_top():
    screen.font = small_font
    screen.pen = ACCENT
    screen.shape(shape.circle(12, 10, 3))
    screen.pen = TEXT
    screen.text("%d unlocked" % len(places), 20, 3)
    hours, minutes = clock.hours_minutes()
    if clock.speed != 1:
        _, month, mday = sky.civil_from_days(clock.day)
        label = ">> %dh/s  %d/%02d %02d:%02d UTC" % (clock.speed // 3600, mday, month, hours, minutes)
        pen = TWILIGHT_PEN
    elif not clock.valid:
        label = "clock not set"
        pen = TWILIGHT_PEN
    else:
        label = "UTC %02d:%02d" % (hours, minutes)
        pen = TEXT
    screen.pen = pen
    width = text_width(label, small_font)
    screen.text(label, WIDTH - 8 - width, 3)
    if sync.state == "synced" and clock.speed == 1:
        screen.pen = ACCENT
        screen.shape(shape.circle(WIDTH - 12 - width, 10, 1.5))
    if mode == "tour":
        screen.pen = ACCENT
        screen.text("tour", 20, 16)


def choose_scale(radius, view):
    """Full resolution unless the last frames say it would cost too much,
    and always once the view has held still for a few frames."""
    global scale, still_frames, last_view
    pixels = min(WIDTH, 2 * radius + 3) * min(HEIGHT, 2 * radius + 3)
    estimate = pixels * cost_us / 1000
    if estimate > FULL_RES_MS:
        scale = 2
    elif estimate < HALF_RES_BELOW_MS:
        scale = 1
    still_frames = still_frames + 1 if view == last_view else 0
    last_view = view
    return 1 if still_frames >= SETTLE_FRAMES else scale


def update():
    global frames, report_at, cost_us
    dt = min(badge.ticks_delta, 200)
    tilt.update()
    handle_input(dt, sky.to_vector(cam_lat, cam_lon))
    move_camera(dt)
    clock.advance(dt)
    sync.step(clock)
    update_sun()

    radius = RADIUS * zoom
    right, up, out, lat, lon = view_axes(radius)
    shown_scale = choose_scale(radius, (right, up, out, round(radius)))

    screen.pen = SPACE
    screen.clear()
    draw_stars(radius)
    draw_glow(radius)
    spent, rendered = globe.draw(CENTRE_X, CENTRE_Y, radius, right, up, out, sun, shown_scale)
    if rendered:
        cost_us += (spent / rendered - cost_us) * 0.3
    draw_rim(radius)
    draw_markers(right, up, out, radius)

    if focus is not None:
        shown = focus
    else:
        shown, closeness = nearest_place(out)
        if shown is not None and closeness < math.cos(math.radians(NEARBY_DEGREES)):
            shown = None
    draw_top()
    draw_card(shown, out, lat, lon)

    frames += 1
    if badge.ticks >= report_at:
        if report_at:
            print("travel_globe: %.1f fps, %.2f us/px, scale %d" % (frames / 10, cost_us, shown_scale))
        frames = 0
        report_at = badge.ticks + 10000


run(update)
