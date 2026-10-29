# Time and the sun for Travel Globe.
#
# Times are kept as (day, second): whole days since 2000-01-01 UTC plus the
# seconds into that day. The badge's floats are single precision, so a plain
# count of seconds since 2000 would only be good to about a minute.

import math
import time

DAY = 86400


def days_from_civil(year, month, day):
    """Days from 2000-01-01 to a Gregorian date (Howard Hinnant's algorithm)."""
    if month <= 2:
        year -= 1
    era = year // 400
    yoe = year - era * 400
    doy = (153 * (month - 3 if month > 2 else month + 9) + 2) // 5 + day - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 730425


def civil_from_days(days):
    """(year, month, day) for a count of days since 2000-01-01."""
    z = days + 730425
    era = z // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    day = doy - (153 * mp + 2) // 5 + 1
    month = mp + 3 if mp < 10 else mp - 9
    return yoe + era * 400 + (1 if month <= 2 else 0), month, day


def weekday(days):
    """0 for Monday through 6 for Sunday; 2000-01-01 was a Saturday."""
    return (days + 5) % 7


def nth_sunday(year, month, n):
    first = days_from_civil(year, month, 1)
    return first + (6 - weekday(first)) % 7 + 7 * (n - 1)


def last_sunday(year, month):
    if month == 12:
        last = days_from_civil(year + 1, 1, 1) - 1
    else:
        last = days_from_civil(year, month + 1, 1) - 1
    return last - (weekday(last) + 1) % 7


def summer_time(rule, year, standard_hours, t):
    """Whether daylight saving is on at t (seconds since 2000, UTC).

    "us": from 2:00 local time on the second Sunday of March to 2:00 local
    (daylight) time on the first Sunday of November.
    "eu": from 01:00 UTC on the last Sunday of March to 01:00 UTC on the last
    Sunday of October.
    """
    if rule == "us":
        start = nth_sunday(year, 3, 2) * DAY + (2 - standard_hours) * 3600
        end = nth_sunday(year, 11, 1) * DAY + (1 - standard_hours) * 3600
    elif rule == "eu":
        start = last_sunday(year, 3) * DAY + 3600
        end = last_sunday(year, 10) * DAY + 3600
    else:
        return False
    return start <= t < end


def local_time(day, second, standard_hours, rule):
    """(hours, minutes, is_summer_time) for a place, from a UTC (day, second)."""
    t = day * DAY + int(second)
    year = civil_from_days(day)[0]
    summer = summer_time(rule, year, standard_hours, t)
    minutes = (t // 60 + int(standard_hours * 60) + (60 if summer else 0)) % 1440
    return minutes // 60, minutes % 60, summer


def sun_position(day, second):
    """The latitude and longitude where the sun is overhead, in degrees.

    The low precision formulae from the Astronomical Almanac, good to about
    0.01 degrees this century. Each term is split into whole days and the
    fraction of a day so single precision floats keep their accuracy.
    """
    part = second / DAY - 0.5          # days since J2000.0 is day + part
    mean_longitude = (280.460 + 0.9856474 * day + 0.9856474 * part) % 360.0
    anomaly = math.radians((357.528 + 0.9856003 * day + 0.9856003 * part) % 360.0)
    ecliptic = math.radians(mean_longitude + 1.915 * math.sin(anomaly) + 0.020 * math.sin(2 * anomaly))
    obliquity = math.radians(23.439 - 0.0000004 * (day + part))
    declination = math.asin(math.sin(obliquity) * math.sin(ecliptic))
    right_ascension = math.degrees(math.atan2(math.cos(obliquity) * math.sin(ecliptic), math.cos(ecliptic)))
    # Greenwich sidereal time; the whole turns from 360 * day are dropped.
    sidereal = (280.46061837 + 0.98564736629 * day + 360.98564736629 * part) % 360.0
    longitude = (right_ascension - sidereal + 540.0) % 360.0 - 180.0
    return math.degrees(declination), longitude


def to_vector(lat, lon):
    """A unit vector for a place: x towards 0E on the equator, y towards 90E, z north."""
    phi = math.radians(lat)
    lam = math.radians(lon)
    c = math.cos(phi)
    return (c * math.cos(lam), c * math.sin(lam), math.sin(phi))


def rtc_now():
    """The badge clock as (day, second, plausible). The clock is taken as UTC."""
    year, month, mday, hour, minute, second = time.gmtime()[:6]
    return days_from_civil(year, month, mday), hour * 3600 + minute * 60 + second, year >= 2025


class Clock:
    """The time the globe shows: the badge clock, or a time-lapse running ahead of it."""

    # A clock that was never set reads 2000 or 2021: keep its time of day but
    # show the June solstice, so the night side still looks like the real thing.
    FALLBACK_DAY = days_from_civil(2026, 6, 21)

    def __init__(self):
        self.correction = 0            # seconds to add to the badge clock, from NTP
        self.speed = 1                 # globe seconds per real second
        self.ahead_days = 0            # how far a time-lapse has run ahead
        self.ahead_seconds = 0.0
        self.day = 0
        self.second = 0.0
        self.valid = True
        self.read()

    def read(self):
        day, second, valid = rtc_now()
        self.valid = valid
        if not valid:
            day = self.FALLBACK_DAY
        second += self.correction + self.ahead_seconds
        day += self.ahead_days
        while second >= DAY:
            second -= DAY
            day += 1
        while second < 0:
            second += DAY
            day -= 1
        self.day, self.second = day, second

    def advance(self, elapsed_ms):
        if self.speed != 1:
            self.ahead_seconds += elapsed_ms * (self.speed - 1) / 1000
            while self.ahead_seconds >= DAY:
                self.ahead_seconds -= DAY
                self.ahead_days += 1
        self.read()

    def live(self):
        self.speed = 1
        self.ahead_days = 0
        self.ahead_seconds = 0.0
        self.read()

    def hours_minutes(self):
        whole = int(self.second)
        return whole // 3600, whole // 60 % 60
