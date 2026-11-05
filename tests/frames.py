"""Synthetic grayscale frames for the settle and click-watch tests: drawn
in code, no screenshot and nothing from a real session."""
W, H = 96, 60


def frame(*rects, fill=0):
    """A W x H frame; each rect is (x, y, w, h, value)."""
    px = bytearray([fill]) * (W * H)
    for x, y, w, h, v in rects:
        for yy in range(y, min(H, y + h)):
            row = yy * W
            px[row + x:row + min(W, x + w)] = bytes([v]) * (min(W, x + w) - x)
    return bytes(px)


BLANK = frame()
BLINK = frame((10, 10, 2, 2, 255))        # a text cursor
MENU = frame((20, 5, 20, 30, 200))        # an opened dropdown
