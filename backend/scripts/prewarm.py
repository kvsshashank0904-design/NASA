"""One-time data warm-up so the app is fast from the first click.

Downloads (all cached under MARSX_CACHE_DIR, skipped when present):
  * global MOLA 16 px/deg grid (2 x 33 MB)  - long-range routing + 3D globe relief
  * Jezero CTX DTM (9.7 MB)
  * HiRISE 1 m DEM windows for the guided missions (resampled to 2 m)
  * MOLA 128 px/deg bands around Gale and Jezero
and pre-computes the guided mission plans.

Run:  python scripts/prewarm.py [mola16] [ctx] [patches] [bands] [missions]
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)

from app.services import dem  # noqa: E402


def step(name, fn):
    t = time.time()
    try:
        out = fn()
        print(f"[ok] {name} in {time.time() - t:.1f}s {out or ''}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[FAILED] {name}: {type(e).__name__}: {e}", flush=True)


def main():
    only = set(sys.argv[1:])
    want = lambda k: not only or k in only  # noqa: E731
    if want("mola16"):
        step("global MOLA 16 px/deg", lambda: dem.mola16()[0].shape)
    if want("ctx"):
        step("Jezero CTX DTM", lambda: dem.ctx_grid() is not None)
    if want("patches"):
        for pid in dem.HIRES_PATCHES:
            if (dem.settings.cache_dir / "hires" / f"{pid}.npz").exists():
                print(f"[ok] patch {pid} already cached", flush=True)
                continue
            step(f"HiRISE patch {pid}", lambda pid=pid: dem.build_patch(pid).z.shape)
    if want("bands"):
        step("MOLA 128 bands, Gale", lambda: dem.mola_window(136.2, -6.6, 139.0, -3.4).z.shape)
        step("MOLA 128 bands, Jezero", lambda: dem.mola_window(76.0, 17.0, 79.0, 20.0).z.shape)
    if want("missions"):
        from app.services import guided
        for mid in guided.MISSIONS:
            step(f"guided mission {mid}", lambda mid=mid: guided.plan(mid, refresh=True)["totals"])


if __name__ == "__main__":
    main()
