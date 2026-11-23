"""Code-made parts that must be exact regardless of what the AI drew."""
from __future__ import annotations

import numpy as np
from scipy import ndimage


def add_clock_hub(mask: np.ndarray, width_mm: float, hub_frac: float, hole_mm: float) -> np.ndarray:
    """Solid hub disk (hub_frac of the design diameter) + movement shaft hole, at the design center."""
    h, w = mask.shape
    px_per_mm = w / width_mm
    cy, cx = (h - 1) / 2, (w - 1) / 2
    yy, xx = np.ogrid[:h, :w]
    dist2 = (yy - cy) ** 2 + (xx - cx) ** 2
    hub_r = hub_frac * min(h, w) / 2
    hole_r = hole_mm / 2 * px_per_mm
    out = mask | (dist2 <= hub_r ** 2)
    out &= ~(dist2 <= hole_r ** 2)
    return out


def fill_center_hole(mask: np.ndarray) -> np.ndarray:
    """The clock shaft hole filled back with metal, so it can be drawn as an exact circle instead of a
    traced one (a traced 10 mm hole on a large size is only a few pixels wide)."""
    h, w = mask.shape
    cy, cx = (h - 1) // 2, (w - 1) // 2
    if mask[cy, cx]:
        return mask
    labels, _ = ndimage.label(~mask)
    hole = labels == labels[cy, cx]
    touches_edge = hole[0].any() or hole[-1].any() or hole[:, 0].any() or hole[:, -1].any()
    if touches_edge or hole.sum() > 0.02 * mask.size:  # not an enclosed hub hole
        return mask
    return mask | hole
