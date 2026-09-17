"""Local, deterministic musical structure analysis.

This module intentionally has no FastAPI, Demucs, registry, or persistence
dependencies.  Callers provide decoded audio, optional stems, and an optional
beat grid; the result is a JSON-serialisable dictionary.  This keeps the DSP
pipeline testable and makes its evidence available to the UI without coupling
it to the job runner.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import median
from typing import Iterable

import numpy as np


@dataclass(frozen=True)
class StructureConfig:
    """Tunable deterministic thresholds used by later analysis stages."""

    default_beats_per_bar: int = 4
    energy_change_threshold: float = 0.18
    spectral_change_threshold: float = 0.18
    stem_change_threshold: float = 0.20
    onset_change_threshold: float = 0.20
    phrase_lengths: tuple[int, ...] = (4, 8, 16, 32)
    phrase_alignment_weight: float = 0.25
    bass_enter_threshold: float = 0.35
    bass_exit_threshold: float = 0.20
    fill_density_multiplier: float = 1.8
    riser_min_bars: int = 3
    impact_threshold: float = 0.55
    section_confidence_threshold: float = 0.45


DEFAULT_CONFIG = StructureConfig()


def _finite_sorted(values: Iterable[float]) -> list[float]:
    result: list[float] = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number >= 0 and number != float("inf") and number == number:
            result.append(number)
    return sorted(set(result))


def estimate_bpm(beat_times: Iterable[float]) -> float | None:
    """Return BPM from the median positive beat interval, or ``None``."""
    beats = _finite_sorted(beat_times)
    intervals = [right - left for left, right in zip(beats, beats[1:], strict=False) if right > left]
    if not intervals:
        return None
    interval = median(intervals)
    return 60.0 / interval if interval > 0 else None


def detect_beats_per_bar(
    beat_times: Iterable[float], downbeat_times: Iterable[float], default: int = 4
) -> int:
    """Infer a stable meter from detected downbeats, falling back to 4/4.

    The existing beat tracker supplies downbeats when available.  We only
    accept a repeated integer spacing, so a stray downbeat cannot change the
    meter.  Audio-only meter inference is deliberately conservative.
    """
    beats = _finite_sorted(beat_times)
    downbeats = _finite_sorted(downbeat_times)
    if len(beats) < 2 or len(downbeats) < 3:
        return default
    indices: list[int] = []
    for downbeat in downbeats:
        nearest = min(range(len(beats)), key=lambda index: abs(beats[index] - downbeat))
        if abs(beats[nearest] - downbeat) <= 0.08:
            indices.append(nearest)
    spacings = [right - left for left, right in zip(indices, indices[1:], strict=False) if right > left]
    if len(spacings) < 2:
        return default
    candidate = int(round(median(spacings)))
    if not 2 <= candidate <= 16:
        return default
    agreeing = sum(abs(spacing - candidate) <= 1 for spacing in spacings)
    return candidate if agreeing / len(spacings) >= 0.75 else default


def build_bar_grid(
    duration: float,
    beat_times: Iterable[float],
    downbeat_times: Iterable[float] = (),
    beats_per_bar: int | None = None,
) -> list[dict[str, float | int]]:
    """Build contiguous, one-indexed bars from an actual beat grid.

    If the first detected beat is after time zero, a leading partial bar is
    retained.  This handles tracks that begin before the first clear downbeat
    without inventing a missing beat.  With no usable beat grid, callers get
    an empty grid rather than a hard-coded tempo.
    """
    if duration <= 0:
        return []
    beats = [beat for beat in _finite_sorted(beat_times) if beat <= duration]
    if len(beats) < 2:
        return []
    meter = beats_per_bar or detect_beats_per_bar(beats, downbeat_times)
    meter = max(1, int(meter))
    starts: list[float] = [0.0] if beats[0] > 1e-3 else []

    downbeats = _finite_sorted(downbeat_times)
    matched = [beat for beat in beats if any(abs(beat - downbeat) <= 0.08 for downbeat in downbeats)]
    if len(matched) >= 2:
        starts.extend(matched)
    else:
        starts.extend(beats[::meter])
    starts = sorted(set(round(start, 6) for start in starts if start < duration))
    if not starts:
        return []

    interval = median([right - left for left, right in zip(beats, beats[1:], strict=False)])
    bars: list[dict[str, float | int]] = []
    for index, start in enumerate(starts, start=1):
        end = starts[index] if index < len(starts) else min(duration, start + meter * interval)
        if end <= start:
            continue
        bars.append({"bar": len(bars) + 1, "start_time": round(start, 6), "end_time": round(end, 6)})
    if bars and float(bars[-1]["end_time"]) < duration:
        bars[-1]["end_time"] = round(duration, 6)
    return bars


def empty_analysis(
    *,
    duration: float,
    beat_times: Iterable[float],
    downbeat_times: Iterable[float] = (),
    bpm: float | None = None,
    key: str | None = None,
    scale: str | None = None,
    beats_per_bar: int | None = None,
    config: StructureConfig = DEFAULT_CONFIG,
) -> dict:
    """Create the stable Phase-1 JSON document; later stages populate it."""
    meter = beats_per_bar or detect_beats_per_bar(
        beat_times, downbeat_times, config.default_beats_per_bar
    )
    bars = build_bar_grid(duration, beat_times, downbeat_times, meter)
    resolved_bpm = bpm if bpm is not None else estimate_bpm(beat_times)
    return {
        "version": 1,
        "track": {
            "bpm": round(resolved_bpm, 3) if resolved_bpm is not None else None,
            "key": key,
            "scale": scale,
            "time_signature": f"{meter}/4",
            "duration": round(float(duration), 6),
        },
        "grid": {
            "total_bars": len(bars),
            "beats_per_bar": meter,
            "beats": _finite_sorted(beat_times),
            "downbeats": _finite_sorted(downbeat_times),
            "bars": bars,
        },
        "sections": [],
        "events": [],
        "config": asdict(config),
    }


def normalize_feature(values: Iterable[float]) -> list[float]:
    """Robustly normalize one track feature to [0, 1] using its own range."""
    array = np.asarray(list(values), dtype=float)
    if array.size == 0:
        return []
    array[~np.isfinite(array)] = 0.0
    low, high = np.percentile(array, (10, 95))
    if high <= low + 1e-12:
        return [0.0] * len(array)
    return np.clip((array - low) / (high - low), 0, 1).round(6).tolist()


def _band_energy(y: np.ndarray, sr: int, low: float, high: float) -> float:
    import librosa

    spectrum = np.abs(librosa.stft(y, n_fft=min(2048, max(256, len(y)))) ) ** 2
    frequencies = librosa.fft_frequencies(sr=sr, n_fft=(spectrum.shape[0] - 1) * 2)
    selected = spectrum[(frequencies >= low) & (frequencies < high)]
    return float(selected.mean()) if selected.size else 0.0


def _bar_feature(y: np.ndarray, sr: int, start: float, end: float, stem: str | None = None) -> dict[str, float]:
    import librosa

    part = y[max(0, round(start * sr)) : max(0, round(end * sr))]
    if part.size < 32:
        return {"rms": 0.0, "peak": 0.0, "onset_density": 0.0}
    hop = min(512, max(64, len(part) // 16))
    rms = float(np.sqrt(np.mean(part**2)))
    onset = librosa.onset.onset_strength(y=part, sr=sr, hop_length=hop)
    onset_density = float(np.count_nonzero(onset > np.percentile(onset, 75)) / max(1, end - start))
    result = {"rms": rms, "peak": float(np.max(np.abs(part))), "onset_density": onset_density}
    if stem is None:
        centroid = librosa.feature.spectral_centroid(y=part, sr=sr, hop_length=hop)
        bandwidth = librosa.feature.spectral_bandwidth(y=part, sr=sr, hop_length=hop)
        rolloff = librosa.feature.spectral_rolloff(y=part, sr=sr, hop_length=hop)
        result.update({
            "spectral_centroid": float(centroid.mean()),
            "spectral_bandwidth": float(bandwidth.mean()),
            "spectral_rolloff": float(rolloff.mean()),
            "spectral_flux": float(np.abs(np.diff(onset)).mean()) if len(onset) > 1 else 0.0,
            "zero_crossing_rate": float(librosa.feature.zero_crossing_rate(part, hop_length=hop).mean()),
        })
    else:
        result.update({
            "low_energy": _band_energy(part, sr, 20, 250),
            "mid_energy": _band_energy(part, sr, 250, 2000),
            "high_energy": _band_energy(part, sr, 2000, sr / 2),
        })
        if stem == "drums":
            result["transient_density"] = onset_density
        if stem in {"bass", "vocals", "other", "piano", "guitar"}:
            result["spectral_energy"] = result["low_energy"] + result["mid_energy"] + result["high_energy"]
    return result


def extract_bar_features(
    master: np.ndarray, sr: int, bars: list[dict[str, float | int]], stems: dict[str, np.ndarray] | None = None
) -> list[dict]:
    """Extract and per-track normalize measurable master/stem bar features."""
    stems = stems or {}
    output = [{"bar": bar["bar"], "master": _bar_feature(master, sr, float(bar["start_time"]), float(bar["end_time"]))} for bar in bars]
    for name, audio in stems.items():
        if not isinstance(audio, np.ndarray):
            continue
        raw = [_bar_feature(audio, sr, float(bar["start_time"]), float(bar["end_time"]), name) for bar in bars]
        for key in {key for item in raw for key in item}:
            normalized = normalize_feature(item.get(key, 0.0) for item in raw)
            for item, value in zip(raw, normalized, strict=True):
                item[key] = value
        for destination, source in zip(output, raw, strict=True):
            destination.setdefault("stems", {})[name] = source
    for key in {key for item in output for key in item["master"]}:
        normalized = normalize_feature(item["master"].get(key, 0.0) for item in output)
        for item, value in zip(output, normalized, strict=True):
            item["master"][key] = value
    return output


def add_activity(features: list[dict]) -> list[dict]:
    """Add relative continuous/binary activity, never an absolute dB gate."""
    names = {name for item in features for name in item.get("stems", {})}
    for name in names:
        energies = [item.get("stems", {}).get(name, {}).get("rms", 0.0) for item in features]
        floor, ceiling = np.percentile(energies, (15, 90)) if energies else (0.0, 0.0)
        scale = max(1e-9, ceiling - floor)
        for item, energy in zip(features, energies, strict=True):
            activity = float(np.clip((energy - floor) / scale, 0, 1))
            item["stems"][name]["activity"] = round(activity, 6)
            item["stems"][name]["active"] = activity >= 0.2
    return features


def detect_changes(features: list[dict], config: StructureConfig = DEFAULT_CONFIG) -> list[float]:
    """Objective weighted boundary scores; labels are intentionally absent."""
    scores = [0.0]
    for previous, current in zip(features, features[1:], strict=False):
        master = abs(current["master"].get("rms", 0) - previous["master"].get("rms", 0))
        spectral = abs(current["master"].get("spectral_centroid", 0) - previous["master"].get("spectral_centroid", 0))
        onset = abs(current["master"].get("onset_density", 0) - previous["master"].get("onset_density", 0))
        names = set(current.get("stems", {})) | set(previous.get("stems", {}))
        stem = np.mean([abs(current.get("stems", {}).get(n, {}).get("activity", 0) - previous.get("stems", {}).get(n, {}).get("activity", 0)) for n in names]) if names else 0.0
        scores.append(round(float((master + spectral + onset + stem) / 4), 6))
    return scores


def phrase_boundaries(change_scores: list[float], config: StructureConfig = DEFAULT_CONFIG) -> list[int]:
    """Select structural boundaries with a preference, never a requirement, for phrases."""
    if len(change_scores) < 2:
        return [0]
    boundaries = [0]
    # The phrase-length bonus should only nudge a borderline change into a
    # boundary, never manufacture one out of near-zero audio evidence on its
    # own. phrase_alignment_weight can exceed energy_change_threshold under
    # the default config (0.25 > 0.18), so an unguarded additive bonus alone
    # already clears the threshold on every single phrase-length-aligned bar
    # regardless of the actual audio -- this floor requires some real signal
    # first (#2: 220-bar track produced 110 near-identical 1-4 bar sections).
    signal_floor = config.energy_change_threshold * 0.4
    for index in range(1, len(change_scores)):
        distance = index - boundaries[-1]
        phrase_bonus = max((1.0 if distance % length == 0 else 0.0) for length in config.phrase_lengths)
        score = change_scores[index] + config.phrase_alignment_weight * phrase_bonus
        if change_scores[index] >= signal_floor and score >= config.energy_change_threshold:
            boundaries.append(index)
    if boundaries[-1] != len(change_scores):
        boundaries.append(len(change_scores))
    return boundaries


def _mean(items: list[dict], path: tuple[str, ...]) -> float:
    values = []
    for item in items:
        value: object = item
        for key in path:
            if not isinstance(value, dict):
                value = 0.0
                break
            value = value.get(key, 0.0)
        values.append(float(value) if isinstance(value, (int, float)) else 0.0)
    return float(np.mean(values)) if values else 0.0


def classify_sections(features: list[dict], boundaries: list[int], change_scores: list[float]) -> list[dict]:
    """Classify segments using transparent feature scores and confidence margins."""
    result = []
    total = max(1, len(features))
    for start, end in zip(boundaries, boundaries[1:], strict=False):
        span = features[start:end]
        energy = _mean(span, ("master", "rms")); drums = _mean(span, ("stems", "drums", "activity")); bass = _mean(span, ("stems", "bass", "activity"))
        onset = _mean(span, ("master", "onset_density")); high = _mean(span, ("stems", "drums", "high_energy"))
        active = _mean(span, ("stems", "drums", "active")) + _mean(span, ("stems", "bass", "active")) + _mean(span, ("stems", "vocals", "active"))
        slope = (span[-1]["master"].get("rms", 0) - span[0]["master"].get("rms", 0)) if len(span) > 1 else 0.0
        prior_change = change_scores[start] if start < len(change_scores) else 0.0
        scores = {
            "intro": (1 - energy) * 0.5 + (1 - min(active, 1)) * 0.3 + (0.25 if start == 0 else 0),
            "outro": (1 - energy) * 0.4 + max(0, -slope) * 0.4 + (0.25 if end >= total else 0),
            "build": max(0, slope) * 0.5 + onset * 0.2 + high * 0.2 + prior_change * 0.1,
            "drop": energy * 0.35 + drums * 0.25 + bass * 0.25 + onset * 0.15 + prior_change * 0.15,
            "breakdown": (1 - drums) * 0.35 + (1 - bass) * 0.3 + (1 - energy) * 0.25,
            "groove": drums * 0.4 + bass * 0.35 + energy * 0.15 + (1 - min(1, abs(slope) * 3)) * 0.1,
        }
        ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        label, score = ordered[0]; margin = score - ordered[1][1]
        result.append({"label": label, "confidence": round(float(np.clip(score * 0.7 + margin * 0.3, 0, 1)), 3), "start_index": start, "end_index": end})
    # Adjacent phrase-sized segments classified with the same label are one
    # continuous section, not several -- merge them, weighting confidence by
    # bar span so a long confident run isn't diluted by a short uncertain one.
    merged: list[dict] = []
    for entry in result:
        if merged and merged[-1]["label"] == entry["label"]:
            previous = merged[-1]
            previous_len = previous["end_index"] - previous["start_index"]
            entry_len = entry["end_index"] - entry["start_index"]
            total_len = previous_len + entry_len
            if total_len:
                previous["confidence"] = round(
                    (previous["confidence"] * previous_len + entry["confidence"] * entry_len) / total_len, 3
                )
            previous["end_index"] = entry["end_index"]
        else:
            merged.append(dict(entry))
    return merged


def detect_events(features: list[dict], config: StructureConfig = DEFAULT_CONFIG) -> list[dict]:
    events: list[dict] = []
    for index in range(1, len(features)):
        bar = int(features[index]["bar"]); now, old = features[index], features[index - 1]
        delta = now["master"].get("rms", 0) - old["master"].get("rms", 0)
        if abs(delta) >= config.energy_change_threshold:
            events.append({"bar": bar, "type": "energy_rise" if delta > 0 else "energy_drop", "confidence": round(abs(delta), 3)})
        for stem in set(now.get("stems", {})) | set(old.get("stems", {})):
            activity = now.get("stems", {}).get(stem, {}).get("activity", 0); previous = old.get("stems", {}).get(stem, {}).get("activity", 0)
            if previous < config.bass_enter_threshold <= activity:
                events.append({"bar": bar, "type": "stem_enter", "stem": stem, "confidence": round(activity - previous, 3)})
            if previous >= config.bass_exit_threshold > activity:
                events.append({"bar": bar, "type": "stem_exit", "stem": stem, "confidence": round(previous - activity, 3)})
        if now["master"].get("onset_density", 0) > max(0.01, old["master"].get("onset_density", 0)) * config.fill_density_multiplier:
            events.append({"bar": bar, "type": "fill", "confidence": round(now["master"]["onset_density"], 3)})
        if old["master"].get("rms", 0) < 0.3 and now["master"].get("rms", 0) >= config.impact_threshold:
            events.append({"bar": bar, "type": "impact", "confidence": round(now["master"]["rms"], 3)})
    for start in range(len(features) - config.riser_min_bars + 1):
        span = features[start : start + config.riser_min_bars]
        highs = [item.get("stems", {}).get("drums", {}).get("high_energy", item["master"].get("spectral_centroid", 0)) for item in span]
        if all(right > left for left, right in zip(highs, highs[1:], strict=False)):
            events.append({"bar_start": int(span[0]["bar"]), "bar_end": int(span[-1]["bar"]), "type": "riser", "confidence": round(float(highs[-1] - highs[0]), 3)})
    return events


def analyze_audio(master: np.ndarray, sr: int, duration: float, beat_times: Iterable[float], *, stems: dict[str, np.ndarray] | None = None, downbeat_times: Iterable[float] = (), bpm: float | None = None, key: str | None = None, scale: str | None = None, config: StructureConfig = DEFAULT_CONFIG) -> dict:
    """Run the complete deterministic DSP pipeline on decoded local audio."""
    result = empty_analysis(duration=duration, beat_times=beat_times, downbeat_times=downbeat_times, bpm=bpm, key=key, scale=scale, config=config)
    features = add_activity(extract_bar_features(master, sr, result["grid"]["bars"], stems))
    changes = detect_changes(features, config); boundaries = phrase_boundaries(changes, config); regions = classify_sections(features, boundaries, changes)
    events = detect_events(features, config)
    result["features"] = features; result["change_scores"] = changes; result["events"] = events
    result["sections"] = [{"id": index + 1, "label": region["label"], "start_bar": features[region["start_index"]]["bar"], "end_bar": features[region["end_index"] - 1]["bar"], "duration_bars": region["end_index"] - region["start_index"], "start_time": result["grid"]["bars"][region["start_index"]]["start_time"], "end_time": result["grid"]["bars"][region["end_index"] - 1]["end_time"], "confidence": region["confidence"], "elements": [name for name, value in features[region["start_index"]].get("stems", {}).items() if value.get("active")], "events": [event for event in events if region["start_index"] < event.get("bar", event.get("bar_start", 0)) <= region["end_index"]]} for index, region in enumerate(regions)]
    return result
