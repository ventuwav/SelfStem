from __future__ import annotations

import json

from app.structure_analyzer import (
    add_activity,
    build_bar_grid,
    classify_sections,
    detect_beats_per_bar,
    detect_changes,
    detect_events,
    empty_analysis,
    estimate_bpm,
    normalize_feature,
    phrase_boundaries,
)


def test_bar_grid_calculates_duration_from_beats() -> None:
    beats = [index * (60 / 126) for index in range(9)]
    bars = build_bar_grid(beats[-1], beats, beats[::4])

    assert len(bars) == 2
    assert bars[0] == {"bar": 1, "start_time": 0.0, "end_time": round(4 * 60 / 126, 6)}
    assert bars[1]["end_time"] == round(beats[-1], 6)


def test_beat_to_bar_conversion_defaults_to_four_four() -> None:
    beats = [index * 0.5 for index in range(12)]

    assert detect_beats_per_bar(beats, []) == 4
    assert estimate_bpm(beats) == 120.0
    assert [bar["start_time"] for bar in build_bar_grid(5.5, beats)] == [0.0, 2.0, 4.0]


def test_downbeats_can_select_a_repeated_unusual_meter() -> None:
    beats = [index * 0.5 for index in range(16)]

    assert detect_beats_per_bar(beats, beats[::3]) == 3


def test_phase_one_result_is_json_serializable() -> None:
    beats = [index * 0.5 for index in range(9)]
    result = empty_analysis(duration=4.0, beat_times=beats, key="A", scale="minor")

    assert result["track"]["time_signature"] == "4/4"
    assert result["grid"]["total_bars"] == 2
    assert json.loads(json.dumps(result))["track"]["key"] == "A"


def _features() -> list[dict]:
    return [
        {"bar": 1, "master": {"rms": 0.1, "spectral_centroid": 0.1, "onset_density": 0.1}, "stems": {"bass": {"rms": 0.0}, "drums": {"rms": 0.0}}},
        {"bar": 2, "master": {"rms": 0.9, "spectral_centroid": 0.9, "onset_density": 0.9}, "stems": {"bass": {"rms": 1.0}, "drums": {"rms": 1.0}}},
    ]


def test_feature_normalization_and_relative_stem_activity() -> None:
    assert normalize_feature([4, 4]) == [0.0, 0.0]
    features = add_activity(_features())
    assert features[0]["stems"]["bass"]["active"] is False
    assert features[1]["stems"]["bass"]["active"] is True


def test_change_phrase_classification_and_events_are_deterministic() -> None:
    features = add_activity(_features())
    changes = detect_changes(features)
    assert changes[1] > 0.18
    assert phrase_boundaries(changes) == [0, 1, 2]
    section = classify_sections(features, [0, 2], changes)[0]
    assert section["label"] in {"intro", "outro", "build", "drop", "breakdown", "groove"}
    assert 0 <= section["confidence"] <= 1
    assert {event["type"] for event in detect_events(features)} >= {"energy_rise", "stem_enter"}
