from functools import reduce
import math
import random
import redis
import time

from bibliopixel.animation.matrix import Matrix
import bibliopixel as bp

# Cheating to avoid passing layout to sub-animations
WIDTH = 200
HEIGHT = 2


def now_us():
    return int(time.time() * 1000000)

class Clock:
    """BPM clock to sync animations to music."""
    def __init__(self, bpm, multiple):
        self.set_bpm_attrs(bpm, multiple)
        self._reltime = self._last_zero_time = now_us()
        self._frac = 0

    def set_bpm_attrs(self, bpm, multiple):
        """Update timing args, call to change bpm or multiple.

        The important var is _usbpm, or "microseconds per beat multiple". It's
        the interval in microseconds ("us") between beat-multiple events. E.g.
        at 100 BPM, multiple 4, there's 150000 us between events.
        """
        self._bpm = bpm
        self._multiple = multiple
        self._usbpm = 60000000 // (self._bpm * self._multiple)

    @property
    def bpm(self):
        return self._bpm

    @bpm.setter
    def bpm(self, val):
        self.set_bpm_attrs(val, self.multiple)

    @property
    def multiple(self):
        return self._multiple

    @multiple.setter
    def multiple(self, val):
        self.set_multiple_attrs(self.bpm, val)

    @property
    def usbpm(self):
        return self._usbpm

    @property
    def frac(self):
        return self._frac

    def update(self):
        """Updates internal timestamps, call from step.

        Call this before using frac in animations.

        This updates:
            _frac: how far we are into the current beat-multiple
            _reltime: the current time in us mod _usbpm, used to calculate
                      _frac
            _last_reltime: _reltime as of the last update
            _last_zero_time: the (interpolated) timestamp of the last
                             beat-multiple, we use it to calculate _reltime.
                             Note that we can't just use `now % _usbpm` because
                             we want to move smoothly between nearby bpms.
        """
        self._last_reltime = self._reltime
        now = now_us()
        self._reltime = (now - self._last_zero_time) % self._usbpm
        if self._reltime < self._last_reltime:
            self._last_zero_time = now - self._reltime
        self._frac = self._reltime / self._usbpm


# Component animations to use with Combo
########################################


class Looperball:
    """Fireball that loops"""
    def __init__(self, length, clock, hue=0):
        self._length = length
        self._clock = clock
        self._hue = hue

        self._hsvs = [[(0, 0, 0) for i in range(WIDTH)]
                      for j in range(HEIGHT)]
        self._embers = {}
        self._ef_hi = 1.1
        self._ef_lo = .65
        self._ember_update_rate = .5

        self._last_head = 0
        self._last_blank = 0

    def step(self):
        # draw the fireball, overwriting still-flickering embers if necessary
        head = int(self._clock.frac * WIDTH)
        # print("head: {}\t #embers: {}".format(head, len(self._embers)))
        for ll in range(self._length):
            w = head - ll
            # don't let negative width indexes leak through
            if w < 0:
                w = WIDTH + w
            b = 255 - 10 * ll
            for strip in range(HEIGHT):
                self._hsvs[strip][w] = (self._hue, 255, b)  # TODO: palette

        # clear the last pixel behind the tail
        blank = head - self._length
        if blank < 0:
            blank = WIDTH + blank
        # print("head: {}\tblank: {}\tfrac:{}".format(head, blank, self._clock.frac))
        for strip in range(HEIGHT):
            self._hsvs[strip][blank] = (self._hue, 255, 0)  # TODO: palette
        if self._last_blank < blank - 1:
            for ob in range(self._last_blank, blank):
                for strip in range(HEIGHT):
                    self._hsvs[strip][ob] = (self._hue, 255, 0)  # TODO: palette
        # might have looped, blank the end and beginning of both strips
        elif self._last_blank > blank:
            for ob in range(self._last_blank, WIDTH):
                for strip in range(HEIGHT):
                    self._hsvs[strip][ob] = (self._hue, 255, 0)  # TODO: palette
            for ob in range(0, blank):
                for strip in range(HEIGHT):
                    self._hsvs[strip][ob] = (self._hue, 255, 0)  # TODO: palette
        self._last_blank = blank

        # start a new ember at the head and any pixels we skipped over since
        # the last update
        for strip in range(HEIGHT):
            self._embers[(strip, head)] = [self._hue, 255, 255]  # TODO
        if self._last_head < head - 1:
            for ob in range(self._last_head, head):
                for strip in range(HEIGHT):
                    self._embers[(strip, ob)] = [self._hue, 255, 255]  # TODO
        # might have looped, ignite the end and beginning of both strips
        elif self._last_head > head:
            for ob in range(self._last_head, WIDTH):
                for strip in range(HEIGHT):
                    self._embers[(strip, head)] = [self._hue, 255, 255]  # TODO
            for strip in range(0, head):
                for strip in range(HEIGHT):
                    self._embers[(strip, head)] = [self._hue, 255, 255]  # TODO
        self._last_head = head

        # clear the dead embers....
        self._embers = {k: v for k, v in self._embers.items()
                        if v[2] > 0}
        # ...and flicker the live ones
        for k in self._embers:
            if (self._ember_update_rate != 1 and random.random() <
                    self._ember_update_rate):
                self._embers[k][2] = \
                    min(255,
                        int(
                            (self._embers[k][2] *
                             (self._ef_lo + (self._ef_hi - self._ef_lo) *
                              random.random()))))
                self._hsvs[k[0]][k[1]] = self._embers[k]
        return self._hsvs


class Fireball:
    def __init__(self, us, length=10, hue=0):
        self._us = int(us)
        self._length = length
        self._hue = hue
        now = now_us()

        self._hsvs = [[0, 0, 0] for px in range(WIDTH)]
        # when to light up each pixel in the strip, we need timestamps beyone
        # the end of the strip to draw the tail
        self._when = [now + x * us // (WIDTH + self._length)
                      for x in range(WIDTH + self._length)]
        # print(now)
        # print(self._when)

        # how much to change the starting color over WIDTH pixels, 255 (or
        # -255) to go full rainbow
        # self._rotate_color = 255
        # self._rcm = self._rotate_color / WIDTH
        # print(self._rcm)
        # print([(self._hue + int(self._rcm * w)) % 255 for w in range(WIDTH)])

        # self._tail_min_brightness = 100
        self._tail_min_brightness = 0
        self._tail_bright = [255 - int(x / (self._length - 1) *
                                       (255 - self._tail_min_brightness))
                             for x in range(self._length)]

        self._tail_change = 80
        self._tail_color = [int(x / (self._length - 1) * self._tail_change)
                            for x in range(self._length)]

        self._embers = {}
        self._ef_hi = 1.5
        self._ef_lo = .35
        # self._ember_update_rate = .75
        self._ember_update_rate = 1

        ### problems
        # embers apply from head, look weird
        #
        # update_rate 1 looks nice, but there are no embers, make sure to keep
        # as option
        #
        ### problems

        self._last_head = 0
        self._last_blank = 0
        self._gone = False
        self._ded = False

    def _get_color(self, b, w=0, ll=0):
        """
        b: brightness
        w: pixel pos on the strip
        ll: position in tail in [0, self._length)
        """
        # hue = (self._hue + int(self._rcm * w)) % 255
        # hue = self._hue
        # hue = (self._hue + w) % 255
        # hue = (self._hue + 2 * ll) % 255
        hue = (self._hue + self._tail_color[ll]) % 255
        return (hue, 255, b)

    # def _get_ember_color(self, ):
    #     return (self._hue, 255, b)

    def _mod_ember_color(self, hsv, amount):
        h, s, v = hsv
        v = min(255, int(v * amount))
        return (h, s, v)

    def _get_blank(self):
        return self._get_color(0)

    def step(self):
        if self._ded:
            return None

        # # did we pass the end of the strip in the last update?
        # if not self._gone and self._last_head > len(self._when):
        #     # print(self._last_head, self._length, WIDTH)
        #     self._gone = True
        # # else:
        # #     print("step", id(self))

        # only redraw the head if we're still in range of the strip, otherwise
        # just redraw the embers
        if not self._gone:
            now = now_us()
            head = self._last_head
            while now > self._when[head]:
                head += 1
                if head == len(self._when):
                    self._gone = True
                    break

            # draw the head, fading to 0 towards the tail
            for ll in range(self._length):
                w = head - ll
                if 0 < w < WIDTH:
                    # b = 255 - int(ll * 255 / self._length)
                    b = self._tail_bright[ll]
                    self._hsvs[w] = self._get_color(b, w, ll)

            # clear the last pixel behind the tail and any we skipped over
            # since the last update
            blank = head - self._length
            if 0 <= blank < WIDTH:
                for px in range(self._last_blank, blank):
                    self._hsvs[px] = self._get_blank()
                    # put an ember in the blank
                    self._embers[px] = self._get_color(
                        self._tail_min_brightness, px, self._length - 1)
                self._last_blank = blank


            # # start a new ember burning at the head and any pixels we skipped
            # # over since the last update
            # if head < WIDTH:
            #     self._embers[head] = self._get_color(255)
            #     if self._last_head < head - 1:
            #         for px in range(self._last_head, head):
            #             self._embers[px] = self._get_color(255)

            self._last_head = head

        # clear the dead embers....
        self._embers = {px: [h, s, v] for px, (h, s, v) in self._embers.items()
                        if v > 0}
        # ...and flicker the live ones
        if self._embers:
            for px in self._embers:
                if (self._ember_update_rate != 1 and
                        random.random() < self._ember_update_rate):
                    self._embers[px] = self._mod_ember_color(
                        self._embers[px],
                        (self._ef_lo + (self._ef_hi - self._ef_lo) *
                         random.random()))

                    # self._embers[px][2] = \
                    #     min(255,
                    #         int(
                    #             (self._embers[px][2] *
                    #              (self._ef_lo + (self._ef_hi - self._ef_lo) *
                    #               random.random()))))

                    self._hsvs[px] = self._embers[px]
        # if the tail is past the end of the strip we won't be starting any new
        # embers, this fireball is dead and gone
        elif self._gone:
            self._ded = True
            return None

        return self._hsvs


def _blend_hsvs(hsv1, hsv2):
    h1, s1, v1 = hsv1
    if v1 == 0:
        return hsv2
    h2, s2, v2 = hsv2
    if v2 == 0:
        return hsv1

    ratio = v1 / (v1 + v2)
    if h1 == h2:
        hn = h1
    else:
        diff = (h2 - h1) % 255
        if diff % 255 <= 128:
            moveby = int((1 - ratio) * diff)
            hn = (h1 + moveby) % 255
        else:
            diff = 255 - diff
            moveby = int((1 - ratio) * diff)
            hn = (h1 - moveby) % 255

    sn = int(ratio * s1 + (1 - ratio) * s2)
    vn = v1 + v2
    return (hn, sn, vn)


def blend_hsvs(hsvs):
    """Combine HSVs, winging it"""
    return reduce(_blend_hsvs, hsvs)


class FBLauncher:
    def __init__(self, clock):
        self.clock = clock
        self._balls = []
        self._last_frac = 0

    def step(self, amt=1):
        # print(len(self._balls))
        frac = self.clock.frac
        # self._balls = [ball for ball in self._balls if not ball._ded]
        if frac < self._last_frac:
            if random.random() > .5:
                self._balls.append(Fireball(self.clock.usbpm * random.randint(1, 10),
                                            length=random.randint(4, 55),
                                            hue=random.randint(0, 255)))
        self._last_frac = frac

        for bb in self._balls:
            bb.step()

        hsvs_set = [x for x in (ball.step() for ball in self._balls)
                    if x is not None]

        if hsvs_set:

            hsvs = [blend_hsvs(x) for x in zip(*hsvs_set)]

            # TODO separate strips
            return [hsvs for h in range(HEIGHT)]
        else:
            return None


class Flash:
    """Quick flash every beat"""
    def __init__(self, clock):
        self.clock = clock
        # frames per color
        self.fpc = 2
        self.colors = [(0, 255, 255),
                       (85, 255, 255),
                       (170, 255, 255)]
        self._blink = None
        self._last_frac = 0

    def step(self, amt=1):
        if self.clock.frac < self._last_frac:
            self._blink = 0
        self._last_frac = self.clock.frac

        # blank most of the time
        if self._blink is None:
            return None

        # avoid an IndexError if either attr changes in the next couple
        # lines
        fpc = self.fpc
        colors = self.colors

        ci = self._blink // fpc
        if ci >= len(colors):
            self._blink = None
            return [[(0, 0, 0) for i in range(WIDTH)] for j in range(HEIGHT)]
        hsv = colors[self._blink // fpc]
        self._blink += 1
        return [[hsv for i in range(WIDTH)] for j in range(HEIGHT)]


class BumpMix:
    """Bump to the music"""
    def __init__(self, clock, hue=128):
        self.hue = hue
        self.clock = clock

    def step(self, amt=1):
        # regular interpolation: however far we are into the interval, light up
        # the strip that much
        if self.clock.usbpm > 150000:
            bright = 255 - int(self.clock.frac * 255)
        # the animation gets blurry at high frame rates, use quartiles instead,
        # spend half the time either off or at full brightness
        elif self.clock.usbpm > 45000:
            if self.clock.frac > 3/4:
                bright = 255
            elif self.clock.frac > 1/2:
                bright = 159  # = 255 * 5/8
            elif self.clock.frac > 1/4:
                bright = 96  # = 255 * 3/8
            else:
                bright = 0
        # full strobe mode baby
        elif self.clock.usbpm > 22000:
            bright = 255 if self.clock.frac > .5 else 0
        # too fast, give up
        else:
            bright = 255

        # print("{}\t{}".format(bright, self.hue))
        # self.layout.fillHSV((self.hue, 255, bright))
        return [[[self.hue, 255 // 2, bright // 2] for i in range(WIDTH)]
                for j in range(HEIGHT)]


def many_hsvs_to_rgb(hsvs):
    """Combine list of hsvs otf [[(h, s, v), ...], ...] and return RGB list."""
    num_strips = len(hsvs[0])
    num_leds = len(hsvs[0][0])
    res = [[[0, 0, 0] for ll in range(num_leds)] for ss in range(num_strips)]
    for strip in range(num_strips):
        for led in range(num_leds):
            # for some reason the conversion screws this up?
            #
            # import bibliopixel as bp
            # c1 = bp.colors.conversions.hsv2rgb((0, 0, 0))
            # c2 = bp.colors.conversions.hsv2rgb((0, 0, 0))
            # c3 = bp.colors.conversions.hsv2rgb((0, 0, 0))
            # bp.colors.arithmetic.color_blend(
            #     bp.colors.arithmetic.color_blend(c1, c2),
            #     c3)
            #
            # = (2, 2, 2)
            if all(hsv[strip][led][2] == 0 for hsv in hsvs):
                rgb = (0, 0, 0)
            else:
                rgbs = [bp.colors.conversions.hsv2rgb(hsv[strip][led])
                        for hsv in hsvs]
                rgb = reduce(bp.colors.arithmetic.color_blend, rgbs)
            res[strip][led] = rgb
    return res


class Combo(Matrix):
    """Combine other animations."""
    def __init__(self, *args,
                 bpm=30,
                 multiple=1,
                 **kwds):
        super().__init__(*args, **kwds)
        self.clock = Clock(bpm, multiple)
        self.clock2 = Clock(int(3 / 2 * bpm), 2)
        # self.clock3 = Clock(4 * bpm, 1)
        self.fireballs = [
            FBLauncher(self.clock),
            # Looperball(5, self.clock, hue=40),
            # Looperball(5, self.clock2, hue=100),
            # Flash(self.clock),
            # Looperball(30, self.clock, hue=200),
        ]

    def step(self, amt=1):
        self.clock.update()
        self.clock2.update()
        # self.clock3.update()

        hsv_sets = [ball.step() for ball in self.fireballs]
        hsv_sets = [x for x in hsv_sets if x is not None]
        if not hsv_sets:
            return

        # for ball in self.fireballs:
        #     ball.step()
        # hsvs = Looperball.combine_hsvs(self.fireballs)

        # rgbs = many_hsvs_to_rgb([fb._hsvs for fb in self.fireballs])
        rgbs = many_hsvs_to_rgb(hsv_sets)
        # hsvs = self.fireballs[0]._hsvs

        # for h, strip in enumerate(self.fireballs[0]._hsvs):
        for h, strip in enumerate(rgbs):
            for w in range(len(strip)):
                rgb = strip[w]
                self.layout.set(w, h, rgb)

# Stand-alone animations
########################


class Bump(Matrix):
    """Bump to the music"""
    def __init__(self, *args,
                 bpm=100,
                 multiple=1,
                 hue=128,
                 **kwds):
        super().__init__(*args, **kwds)
        self.hue = hue
        self.clock = Clock(bpm, multiple)
        self.rc = redis.Redis()
        self._last_fetch = 0
        self.fetch()

    def fetch(self):
        ts, bpm, multiple, hue = map(int, self.rc.mget("ts", "bpm", "multiple",
                                                       "hue"))
        if ts > self._last_fetch:
            self.clock.set_bpm_attrs(bpm, multiple)
            self.hue = hue
            self._last_fetch = ts

    def step(self, amt=1):
        # poll redis for new arg values
        self.fetch()
        # update BPM clock
        self.clock.update()

        # regular interpolation: however far we are into the interval, light up
        # the strip that much
        if self.clock._msbpm > 150:
            bright = 255 - int(self.clock.frac * 255)
        # the animation gets blurry at high frame rates, use quartiles instead,
        # spend half the time either off or at full brightness
        elif self.clock._msbpm > 45:
            if self.clock.frac > 3/4:
                bright = 255
            elif self.clock.frac > 1/2:
                bright = 159  # = 255 * 5/8
            elif self.clock.frac > 1/4:
                bright = 96  # = 255 * 3/8
            else:
                bright = 0
        # full strobe mode baby
        elif self.clock._msbpm > 22:
            bright = 255 if self.clock.frac > .5 else 0
        # too fast, give up
        else:
            bright = 255

        # print("{}\t{}".format(bright, self.hue))
        self.layout.fillHSV((self.hue, 255, bright))


def blend(a, b, perc=.5):
    """Blend two RGBs, use `perc` % of `a`."""
    return [int(a[i] * perc + b[i] * (1 - perc)) for i in range(len(a))]


class Embers(Matrix):
    """Comet with a trail of glowing embers."""
    def __init__(self, *args,
                 fade=0.9,
                 sparkle_prob=0.00125,
                 **kwds):

        self.fade = fade
        self.sparkle_prob = sparkle_prob

        # The base class MUST be initialized by calling super like this
        super().__init__(*args, **kwds)

    # fades pixel at [i,j] by self.fade
    def fade_pixel_random(self, i, j):
        hi, lo = 1.5, .45
        old = self.layout.get(i, j)
        if old != (0,0,0):
            fade = lo + (hi - lo) * random.random()
            self.layout.set(
                i, j,
                [math.floor(x * fade) for x in old]
            )

    def step(self, amt=1):
        leader_size = 8
        # how white (1 full white)
        hw = .4

        stepscale = 7 / 8
        eff_step = int(self._step * stepscale)
        for i in range(self.layout.width):
            # do_sparkle = random.random() < self.sparkle_prob:
            # print(self._step, self.layout.width, self._step % self.layout.width)
            do_light = eff_step % self.layout.width == i
            for j in range(self.layout.height):
                # color = (255,255,255)
                color = self.palette(int(255 * i / self.layout.width))
                # color = self.palette(random.randint(0, 255))
                if do_light:
                    # leading white lights
                    for k in range(leader_size, 0, -1):
                        if i + k < self.layout.width:
                            self.layout.set(i + k, j,
                                blend((255, 255, 255), color,
                                      hw * k / leader_size))
                    self.layout.set(i, j, color)
                self.fade_pixel_random(i, j)

        if self._step > int(1 / stepscale) + 1 and eff_step == 0:
            self._step = 0
        self._step += amt


class Fill(Matrix):
    """Basic redis-controlled HSV fill."""
    def __init__(self, *args,
                 hue=128,
                 sat=128,
                 val=128,
                 **kwds):
        super().__init__(*args, **kwds)
        self._last_fetch = 0
        self.hue = hue
        self.sat = sat
        self.val = val
        self.rc = redis.Redis()

    def fetch(self):
        """Poll redis for new arg values."""
        got = self.rc.mget("ts", "hue", "sat", "val")
        ts = int(got['ts'])
        if ts > self._last_fetch:
            if got['hue']:
                self.hue = got['hue']
            if got['sat']:
                self.sat = got['sat']
            if got['val']:
                self.val = got['val']
            self._last_fetch = ts

    def step(self, amt=1):
        self.fetch()
        self.layout.fillHSV((self.hue, self.sat, self.val))
