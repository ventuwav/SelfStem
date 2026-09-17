"""Job-facing adapter for the deterministic structure analyzer."""
from __future__ import annotations

import json
from pathlib import Path

from app.pipeline.analyze import _load_audio_ffmpeg
from app.structure_analyzer import analyze_audio


def analyze_stems(stems_dir: Path, duration: float, *, bpm: int | None = None, key: str | None = None, scale: str | None = None) -> dict:
    """Analyze existing local stems and cache the JSON beside them."""
    grid_path = stems_dir / "beats.json"
    grid = json.loads(grid_path.read_text(encoding="utf-8"))
    beats = grid.get("beats") or []
    # grid["bars"] is a sparse meter-*change* log (see
    # app/pipeline/beatgrid.py::_downbeats_to_bars) -- a steady 4/4 track
    # yields a single entry, not one per bar. It is not a downbeat-per-bar
    # list, so it must not be fed to analyze_audio as downbeat_times: doing
    # so starved build_bar_grid down to that handful of sparse marks instead
    # of the real ~1-bar-per-4-beats grid (#1: 873 beats produced 17 bars on
    # a 6:52 house track). No per-bar downbeat data exists in beats.json, so
    # leave downbeat_times empty and let detect_beats_per_bar fall back to
    # the 4/4 default, matching build_bar_grid's documented behavior.
    source = next((stems_dir / f"{name}.wav" for name in ("mix", "original", "other", "drums") if (stems_dir / f"{name}.wav").is_file()), None)
    if source is None:
        raise FileNotFoundError("no audio stem available")
    loaded = _load_audio_ffmpeg(source, duration=None)
    if loaded is None:
        raise RuntimeError("could not decode structure analysis source")
    master, sr = loaded
    stems = {}
    for name in ("drums", "bass", "vocals", "other", "piano", "guitar"):
        loaded_stem = _load_audio_ffmpeg(stems_dir / f"{name}.wav", sr=sr, duration=None) if (stems_dir / f"{name}.wav").is_file() else None
        if loaded_stem is not None:
            stems[name] = loaded_stem[0]
    result = analyze_audio(master, sr, duration, beats, stems=stems, bpm=bpm, key=key, scale=scale)
    temp = stems_dir / "structure.json.tmp"
    temp.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    temp.replace(stems_dir / "structure.json")
    return result
