"""Unit tests for e_nodes.py E1/E6.

Uses a small synthetic IBTrACS-shaped CSV fixture (not the real 113MB file)
so these tests run fast and don't depend on raw data being present.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from backend.e_nodes import e1_load_typhoon_data, e6_build_viz_payload  # noqa: E402

_PORT_LAT = 10.0
_PORT_LON = 130.0
_RADIUS_KM = 300.0

_CSV_HEADER = "SID,SEASON,NAME,ISO_TIME,LAT,LON,USA_WIND,USA_SSHS\n"
_CSV_UNITS = ",,,,deg,deg,kts,\n"

_CSV_ROWS = [
    # storm A: 3 points, near port, qualifies (max cat 3)
    "2020001S01001,2020,TESTA,2020-08-01 00:00:00,10.5,130.5,90,2\n",
    "2020001S01001,2020,TESTA,2020-08-01 06:00:00,10.2,130.2,100,3\n",
    "2020001S01001,2020,TESTA,2020-08-01 12:00:00,9.8,129.8,85,2\n",
    # storm B: far from port (~2700 km away) — excluded
    "2020002S02002,2020,TESTB,2020-09-01 00:00:00,30.0,150.0,120,4\n",
    "2020002S02002,2020,TESTB,2020-09-01 06:00:00,30.2,150.2,120,4\n",
    # storm C: in range but outside study_years filter — excluded
    "1980001S03003,1980,TESTC,1980-08-01 00:00:00,10.3,130.3,90,2\n",
    "1980001S03003,1980,TESTC,1980-08-01 06:00:00,10.1,130.1,90,2\n",
]


def _write_fixture_csv(path: Path) -> Path:
    csv_path = path / "ibtracs_test.csv"
    csv_path.write_text(_CSV_HEADER + _CSV_UNITS + "".join(_CSV_ROWS))
    return csv_path


def test_e1_filters_by_distance_and_study_years(tmp_path):
    csv_path = _write_fixture_csv(tmp_path)
    result = e1_load_typhoon_data(
        ibtracs_path=csv_path,
        port_lat=_PORT_LAT,
        port_lon=_PORT_LON,
        radius_km=_RADIUS_KM,
        study_years=(1994, 2026),
    )
    assert result.total_event_count == 1
    assert result.events[0].storm_id == "2020001S01001"
    assert result.events[0].name == "Testa"


def test_e1_classifies_scenario_consistently(tmp_path):
    csv_path = _write_fixture_csv(tmp_path)
    result = e1_load_typhoon_data(
        ibtracs_path=csv_path,
        port_lat=_PORT_LAT,
        port_lon=_PORT_LON,
        radius_km=_RADIUS_KM,
        study_years=(1994, 2026),
    )
    event = result.events[0]
    assert event.saffir_simpson_cat == 3  # max USA_SSHS among near points
    assert 1 <= event.distance_bin <= 5
    assert event.scenario_id == (event.saffir_simpson_cat - 1) * 5 + event.distance_bin
    assert len(event.track_points) == 3
    assert event.min_distance_km >= 0


def test_e6_builds_viz_payload_from_e1_output(tmp_path):
    csv_path = _write_fixture_csv(tmp_path)
    track_data = e1_load_typhoon_data(
        ibtracs_path=csv_path,
        port_lat=_PORT_LAT,
        port_lon=_PORT_LON,
        radius_km=_RADIUS_KM,
        study_years=(1994, 2026),
        port_name="NPT",
    )
    viz = e6_build_viz_payload(track_data)
    assert viz.port_marker.lat == _PORT_LAT
    assert viz.port_marker.lon == _PORT_LON
    assert viz.port_marker.name == "NPT"
    assert len(viz.typhoon_tracks) == 1
    track = viz.typhoon_tracks[0]
    assert track.storm_id == "2020001S01001"
    assert len(track.path) == 3
    assert track.path[0] == [130.5, 10.5]  # [lon, lat]
    assert track.category == 3
    assert len(track.color_rgba) == 4
