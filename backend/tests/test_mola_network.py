"""MOLA MEGDR range-request access. Needs the PDS Geosciences Node (or a warm cache)."""
import pytest

from app.services import dem


def _mola_ok():
    try:
        dem.sample_elevation(137.4417, -4.5895)
        return True
    except dem.DemUnavailable:
        return False


pytestmark = pytest.mark.skipif(not _mola_ok(), reason="PDS MOLA not reachable and not cached")


def test_known_elevations():
    assert dem.sample_elevation(137.4417, -4.5895)["elevation_m"] == pytest.approx(-4501, abs=30)   # Bradbury Landing
    assert dem.sample_elevation(-133.8, 18.65)["elevation_m"] > 19000                               # Olympus Mons summit region


def test_window_geometry_and_quality_flags():
    g = dem.mola_window(137.0, -5.5, 138.0, -4.5)
    assert g.z.shape == (128, 128) and g.dlat == pytest.approx(1 / 128)
    assert g.lats[0] > g.lats[-1] and g.lons[0] < g.lons[-1]
    assert set(map(int, set(g.quality.ravel()))) <= {dem.Q_MEASURED, dem.Q_INTERPOLATED}
    assert 0 < (g.quality == dem.Q_INTERPOLATED).mean() < 1      # equatorial MOLA has gaps between tracks


def test_window_limits():
    with pytest.raises(dem.DemUnavailable):
        dem.mola_window(0, 0, 30, 5)
    with pytest.raises(dem.DemUnavailable):
        dem.mola_window(0, 88.5, 1, 89.5)
