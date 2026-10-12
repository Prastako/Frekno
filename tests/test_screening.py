"""Tests for pipeline/screening.py."""

import numpy as np
import pytest
from rasterio.transform import from_origin

from pipeline.acoustics import air_absorption_db_per_km
from pipeline.screening import (
    prepare_dem,
    pair_attenuation,
    screen_candidates,
)


@pytest.fixture
def flat_dem():
    """Flat 3000x3000 terrain at 250 m."""
    return np.full((3000, 3000), 250.0, dtype=np.float32)


@pytest.fixture
def tr():
    """Transform: origin (0, 30000), 10 m cell size."""
    return from_origin(0, 30000, 10, 10)


@pytest.fixture
def cfg(flat_dem, tr):
    return {
        "temp_c": 10,
        "humidity_percent": 70,
        "pressure_kpa": 101.325,
        "ref_class": "medium",
        "ref_character": "very_bass_heavy",
        "radius_m": 10000,
        "sector_deg": 5,
        "rings_m": [0, 1000, 2000, 4000, 7000, 10000],
        "source_h": 2,
        "receptor_h": 4,
        "n_points": 200,
        "keep_per_type": 20,
    }


class TestPrepareDem:
    def test_nodata_to_nan(self):
        a = np.array([[1.0, -9999.0]], dtype=np.float32)
        result = prepare_dem(a)
        assert result.dtype == np.float64
        assert result[0, 0] == pytest.approx(1.0, abs=1e-9)
        assert np.isnan(result[0, 1])
        # Original not modified
        assert a[0, 1] == -9999.0


class TestPairAttenuation:
    def test_flat_terrain(self, flat_dem, tr, cfg):
        """Attenuation on flat terrain at 1000 m distance."""
        alpha = air_absorption_db_per_km(10, 70)
        att = pair_attenuation(
            flat_dem, tr,
            15000, 15000,
            [16000], [15000],
            2, 4, 200, alpha,
        )
        assert att.shape == (1, 9)

        d = 1000.0
        expected = 20.0 * np.log10(d) + np.array(alpha) * (d - 1) / 1000.0
        np.testing.assert_allclose(att[0], expected, atol=1e-6)
        # 31.5 Hz specific check
        assert att[0, 0] == pytest.approx(60.031997, abs=1e-6)

    def test_wall_blocks(self, flat_dem, tr, cfg):
        """A wall between source and receptor raises attenuation."""
        dem = flat_dem.copy()
        dem[:, 1550:1555] = 330.0
        alpha = air_absorption_db_per_km(10, 70)

        att_flat = pair_attenuation(
            flat_dem, tr,
            15000, 15000,
            [16000], [15000],
            2, 4, 200, alpha,
        )

        att_wall = pair_attenuation(
            dem, tr,
            15000, 15000,
            [16000], [15000],
            2, 4, 200, alpha,
        )

        # 31.5 Hz: no terrain credit (forced to 0)
        assert att_wall[0, 0] == pytest.approx(att_flat[0, 0], abs=1e-9)

        # Other bands: at least 0.01 dB higher
        for b in range(1, 9):
            assert att_wall[0, b] >= att_flat[0, b] + 0.01

    def test_zero_receptors(self, flat_dem, tr, cfg):
        """P == 0 returns zeros with correct shape."""
        alpha = air_absorption_db_per_km(10, 70)
        att = pair_attenuation(
            flat_dem, tr,
            15000, 15000,
            [], [],
            2, 4, 200, alpha,
        )
        assert att.shape == (0, 9)


class TestScreenCandidates:
    def test_basic(self, flat_dem, tr, cfg):
        """One candidate, three home receptors."""
        candidates, pairs = screen_candidates(
            flat_dem, tr,
            [15000], [15000],
            [15000, 15000, 15000],
            [15500, 16000, 17000],
            ["home", "home", "home"],
            ["h0", "h1", "h2"],
            cfg,
        )
        assert len(candidates) == 1
        c = candidates[0]
        assert c["candidate_id"] == 0
        assert c["n_home"] == 3
        assert c["n_cottage"] == 0
        assert c["worst_cottage_dba"] is None

        # Pairs
        assert len(pairs) == 3
        ids = [p["receptor_id"] for p in pairs]
        assert ids == ["h0", "h1", "h2"]
        ranks = [p["rank"] for p in pairs]
        assert ranks == [1, 2, 3]

        # dB(A) values
        assert pairs[0]["ref_level_dba"] == pytest.approx(69.2787, abs=0.01)
        assert pairs[1]["ref_level_dba"] == pytest.approx(62.1615, abs=0.01)
        assert pairs[2]["ref_level_dba"] == pytest.approx(54.5970, abs=0.01)

        # Distances
        assert pairs[0]["dist_m"] == pytest.approx(500, abs=0.01)
        assert pairs[1]["dist_m"] == pytest.approx(1000, abs=0.01)
        assert pairs[2]["dist_m"] == pytest.approx(2000, abs=0.01)

        # Bearings (all due north = 0 deg)
        for p in pairs:
            assert p["bearing_deg"] == pytest.approx(0, abs=0.01)

        # worst_home_dba
        assert c["worst_home_dba"] == pytest.approx(69.2787, abs=0.01)

    def test_no_receptors(self, flat_dem, tr, cfg):
        """No receptors returns empty pairs and zero counts."""
        candidates, pairs = screen_candidates(
            flat_dem, tr,
            [15000], [15000],
            [], [],
            [],
            [],
            cfg,
        )
        assert len(candidates) == 1
        assert len(pairs) == 0
        c = candidates[0]
        assert c["n_home"] == 0
        assert c["worst_home_dba"] is None

    def test_nodata_line_of_sight(self, flat_dem, tr, cfg):
        """No-data cells along the LOS should not produce NaN."""
        dem = flat_dem.copy()
        dem[:, 1550:1555] = -9999.0

        candidates, pairs = screen_candidates(
            dem, tr,
            [15000], [15000],
            [16000], [15000],
            ["home"],
            ["h0"],
            cfg,
        )

        # Compare with flat result
        flat_candidates, flat_pairs = screen_candidates(
            flat_dem, tr,
            [15000], [15000],
            [16000], [15000],
            ["home"],
            ["h0"],
            cfg,
        )

        assert pairs[0]["ref_level_dba"] == pytest.approx(
            flat_pairs[0]["ref_level_dba"], abs=1e-6
        )

        # No NaN in any pair row value
        for v in pairs[0].values():
            if isinstance(v, float):
                assert not np.isnan(v)


def test_pairs_follow_loudness_order_behind_a_wall(flat_dem, tr):
    """When terrain changes loudness order, pair rows carry data from the right receptor."""
    from pipeline.acoustics import air_absorption_db_per_km

    dem = np.full((3000, 3000), 250.0, dtype=np.float32)
    dem[1475:1480, :] = 330.0

    cfg = {
        "temp_c": 10,
        "humidity_percent": 70,
        "pressure_kpa": 101.325,
        "ref_class": "medium",
        "ref_character": "very_bass_heavy",
        "radius_m": 10000,
        "sector_deg": 5,
        "rings_m": [0, 1000, 2000, 4000, 7000, 10000],
        "source_h": 2,
        "receptor_h": 4,
        "n_points": 200,
        "keep_per_type": 20,
    }

    candidates, pairs = screen_candidates(
        dem, tr,
        [15000], [15000],
        [15000, 16000, 14000],
        [15500, 15000, 15000],
        ["home"] * 3,
        ["north", "east", "west"],
        cfg,
    )

    # The last pair row is "north"
    assert pairs[-1]["receptor_id"] == "north"

    # For every pair row, (rx, ry) equals the coordinates of its receptor_id
    coord_map = {
        "north": (15000.0, 15500.0),
        "east": (16000.0, 15000.0),
        "west": (14000.0, 15000.0),
    }
    for p in pairs:
        expected_rx, expected_ry = coord_map[p["receptor_id"]]
        assert p["rx"] == pytest.approx(expected_rx, abs=1e-6)
        assert p["ry"] == pytest.approx(expected_ry, abs=1e-6)
        assert p["dist_m"] == pytest.approx(
            np.hypot(p["rx"] - 15000, p["ry"] - 15000), abs=1e-6
        )

    # With keep_per_type=1 and only the first two receptors, the pair row is "east"
    candidates2, pairs2 = screen_candidates(
        dem, tr,
        [15000], [15000],
        [15000, 16000],
        [15500, 15000],
        ["home", "home"],
        ["north", "east"],
        {**cfg, "keep_per_type": 1},
    )
    assert len(pairs2) == 1
    assert pairs2[0]["receptor_id"] == "east"
    assert pairs2[0]["rx"] == pytest.approx(16000.0, abs=1e-6)
