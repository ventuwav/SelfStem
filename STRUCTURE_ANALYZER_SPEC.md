# SelfStem — Deterministic Track Structure Analyzer

## Context

This repository is a customized fork of StemDeck (now renamed SelfStem):

https://github.com/ventuwav/SelfStem

The goal is to add a **fully local, deterministic musical structure analyzer** to SelfStem.

Do NOT use an LLM, OpenAI API, cloud AI service, or any generative AI model for the analysis itself.

The analyzer must infer the musical structure of electronic music from the audio and the stems that SelfStem already generates.

The desired output is similar to:

```text
TRACK: Example.mp3
BPM: 126
KEY: A minor
TIME SIGNATURE: 4/4

STRUCTURE

00:00  INTRO
       Bars 1–16 · 16 bars
       Kick
       Atmosphere
       FX

00:30  GROOVE
       Bars 17–32 · 16 bars
       Kick
       Bass
       Hats
       Percussion

01:06  BUILD
       Bars 33–40 · 8 bars
       + Snare roll
       + Rising FX
       - Bass

01:21  DROP
       Bars 41–72 · 32 bars
       Kick
       Bass
       Main synth
       Percussion

02:22  BREAKDOWN
       Bars 73–88 · 16 bars
       Vocal
       Pad
       FX
```

The important requirement is that sections must be expressed in **bars**, not only seconds.

The analyzer should eventually identify:

* BPM
* key
* time signature
* beat grid
* downbeats
* bars
* phrases
* structural sections
* intro
* groove
* build
* drop
* breakdown
* outro
* fills
* risers
* impacts
* instrument/stem entrances
* instrument/stem exits
* meaningful changes inside sections

---

# IMPORTANT DEVELOPMENT RULE

Before modifying code:

1. Inspect the entire existing repository.
2. Understand the current architecture.
3. Identify the existing audio analysis pipeline.
4. Identify how BPM/key are currently calculated.
5. Identify how Demucs stems are generated and stored.
6. Identify the existing waveform implementation.
7. Identify the existing section model/API/UI.
8. Identify all existing tests.
9. Do NOT replace existing functionality.
10. Do NOT rewrite unrelated code.
11. Preserve all existing user modifications.

Create a short implementation plan before making changes.

---

# Architecture

Add the analyzer as a separate backend module.

Preferred structure:

```text
app/
    ...
    structure_analyzer.py
    ...
```

If the repository architecture suggests a better location, follow the existing conventions rather than blindly creating this exact path.

The structure analyzer should be independent from:

* HTTP routes
* frontend code
* Demucs execution
* database persistence

It should accept audio/features and return a structured analysis result.

---

# Core Pipeline

Implement this pipeline:

```text
MASTER AUDIO
     ↓
Tempo / Beat Analysis
     ↓
Beat Grid
     ↓
Downbeat Detection
     ↓
Bar Grid
     ↓
Per-Bar Feature Extraction
     ↓
Change Point Detection
     ↓
Phrase Detection
     ↓
Section Classification
     ↓
Musical Event Detection
     ↓
Structured JSON Result
     ↓
Existing SelfStem UI
```

---

# STEP 1 — Beat and Bar Grid

Use local DSP libraries already present in the project where possible.

Preferred tools:

* librosa
* numpy
* scipy

Do not introduce a large ML model for basic beat/bar detection.

The analyzer should determine:

```json
{
  "bpm": 126,
  "time_signature": "4/4",
  "total_bars": 128
}
```

Represent every bar with:

```json
{
  "bar": 1,
  "start_time": 0.0,
  "end_time": 1.9048
}
```

For 126 BPM and 4/4:

```text
beat duration ≈ 0.47619 sec
bar duration ≈ 1.90476 sec
```

Do NOT hardcode these values.

Calculate them from the detected BPM and time signature.

---

# STEP 2 — Per-Bar Feature Extraction

For every bar calculate normalized features.

At minimum:

## Master

* RMS energy
* peak
* spectral centroid
* spectral bandwidth
* spectral rolloff
* spectral flux
* zero crossing rate
* onset density

## Drums

From drums stem:

* RMS
* onset density
* transient density
* low-frequency energy
* mid-frequency energy
* high-frequency energy

## Bass

From bass stem:

* RMS
* low-frequency energy
* onset density
* activity ratio

## Vocals

From vocals stem:

* RMS
* activity ratio
* onset density

## Other

From other/piano/guitar/etc. stems when available:

* RMS
* activity ratio
* spectral energy

All features should be normalized so tracks with different loudness levels remain comparable.

---

# STEP 3 — Stem Activity

Create a simple binary/continuous activity model for each stem.

Example:

```json
{
  "bass": {
    "active": true,
    "activity": 0.82
  },
  "drums": {
    "active": true,
    "activity": 0.94
  },
  "vocals": {
    "active": false,
    "activity": 0.03
  }
}
```

Do not rely only on absolute dB.

Use relative thresholds based on the track/stem itself.

For example:

* calculate a noise floor / percentile baseline
* normalize energy
* determine activity relative to that baseline

This is important because different tracks have dramatically different mastering levels.

---

# STEP 4 — Change Point Detection

Detect structural changes between bars.

Calculate differences between consecutive bars and/or short rolling windows.

Examples:

```text
bass energy:      +72%
drum energy:      +41%
spectral energy:  +35%
overall energy:   +48%
```

Create a change score.

Example conceptual model:

```text
change_score =
    weighted_energy_change
    + weighted_spectral_change
    + weighted_stem_change
    + weighted_onset_change
```

The exact weights should be configurable.

Do NOT hardcode the final section labels directly into this stage.

First detect objective structural boundaries.

---

# STEP 5 — Phrase Detection

Electronic music frequently uses:

* 4-bar phrases
* 8-bar phrases
* 16-bar phrases
* 32-bar phrases

Prefer boundaries that align with musically meaningful phrase lengths.

Implement a phrase detector that scores candidate boundaries.

For example:

```text
4 bars
8 bars
16 bars
32 bars
```

A strong structural change at bar 33 is preferable to an arbitrary change at bar 31.

However, do NOT force every section to be a multiple of 8 or 16 bars.

The algorithm must allow unusual structures.

---

# STEP 6 — Section Classification

Classify detected structural regions using deterministic rules.

No AI.

No LLM.

No neural classifier.

Use measurable features.

## INTRO

Typical characteristics:

* low/moderate energy
* limited number of active stems
* gradual addition of elements
* frequently drums and/or atmosphere before bass/full instrumentation

## GROOVE

Typical characteristics:

* stable energy
* drums active
* bass active
* repeating rhythmic pattern
* low structural change rate

## BUILD

Typical characteristics:

* positive energy slope
* increasing transient density
* increasing high-frequency activity
* snare/perc density increasing
* bass may reduce or disappear
* often immediately precedes a large energy transition

## DROP

Typical characteristics:

* significant positive energy transition
* bass strongly active
* drums strongly active
* multiple stems active
* high rhythmic density
* often follows a build/breakdown

## BREAKDOWN

Typical characteristics:

* major reduction in drum activity
* major reduction in bass activity
* reduced overall energy
* vocals/pads/FX may remain active
* often precedes a build

## OUTRO

Typical characteristics:

* declining energy
* progressive removal of elements
* commonly occurs near the end
* may retain kick/drums while melodic elements disappear

The classifier should return:

```json
{
  "label": "build",
  "confidence": 0.84
}
```

Confidence must be based on the rule scores, not fabricated.

---

# STEP 7 — Musical Events

Detect events inside sections.

At minimum:

## STEM ENTER

Example:

```json
{
  "bar": 49,
  "type": "stem_enter",
  "stem": "vocals"
}
```

## STEM EXIT

```json
{
  "bar": 57,
  "type": "stem_exit",
  "stem": "bass"
}
```

## ENERGY RISE

```json
{
  "bar": 37,
  "type": "energy_rise"
}
```

## ENERGY DROP

```json
{
  "bar": 73,
  "type": "energy_drop"
}
```

## FILL

Detect unusually high transient/onset density relative to neighboring bars.

Example:

```json
{
  "bar": 72,
  "type": "fill"
}
```

## RISER

Detect sustained increasing high-frequency/spectral energy over several bars.

Example:

```json
{
  "bar_start": 33,
  "bar_end": 40,
  "type": "riser"
}
```

## IMPACT

Detect strong transient/energy spike following a low-energy region.

Example:

```json
{
  "bar": 41,
  "type": "impact"
}
```

Do not over-classify events.

Only report events when confidence exceeds configurable thresholds.

---

# STEP 8 — Section Description

Generate deterministic descriptions from detected features.

DO NOT use an LLM.

For example:

If:

```text
bass activity drops
snare density rises
high frequency energy rises
```

generate:

```text
- Bass reduced
- Snare density increasing
- High-frequency energy rising
```

If:

```text
bass enters
drums enter
energy jumps
```

generate:

```text
+ Bass enters
+ Full drums
+ Energy increases
```

Use a fixed vocabulary.

Possible vocabulary:

```text
Bass
Kick
Drums
Percussion
Hats
Snare
Vocals
Synth
Pad
FX
Energy
Riser
Fill
Impact
```

---

# Output Schema

Create a stable JSON schema similar to:

```json
{
  "track": {
    "bpm": 126,
    "key": "A",
    "scale": "minor",
    "time_signature": "4/4",
    "duration": 245.2
  },

  "grid": {
    "total_bars": 128,
    "beats_per_bar": 4
  },

  "sections": [
    {
      "id": 1,
      "label": "intro",
      "start_bar": 1,
      "end_bar": 16,
      "duration_bars": 16,
      "start_time": 0.0,
      "end_time": 30.48,
      "confidence": 0.91,

      "elements": [
        "kick",
        "atmosphere",
        "fx"
      ],

      "events": []
    }
  ]
}
```

The schema should be extensible.

---

# Existing API Integration

Inspect the existing section API before modifying it.

The repository already has section persistence.

Reuse it wherever possible.

Do not create a duplicate section system.

If necessary, extend the existing API so automatically detected sections can be:

```text
generated
edited
deleted
saved
re-analyzed
```

The user must be able to manually correct automatically detected sections.

Automatic analysis should NEVER permanently overwrite manual corrections without explicit user action.

---

# Frontend

Integrate the analysis into the existing waveform UI.

Do not create a completely separate page unless the existing architecture makes that necessary.

The waveform should display:

```text
INTRO       GROOVE       BUILD           DROP
16 bars     16 bars       8 bars          32 bars
```

Show bar numbers.

Example:

```text
1  2  3  4 ... 16 | 17 ... 32 | 33 ... 40 | 41 ... 72
```

Sections should be clickable.

When a section is clicked:

* select its time range
* allow loop
* synchronize playback
* highlight the section
* show its details

---

# Section Detail Panel

When a section is selected, display:

```text
BUILD

Bars 33–40
8 bars
01:06–01:21

Elements
+ Snare
+ Rising FX
- Bass

Events
Bar 37 — energy rising
Bar 40 — impact preparation
```

Keep the UI compact and useful for music analysis.

---

# Manual Editing

Users must be able to:

* change section label
* change start bar
* change end bar
* split section
* merge sections
* delete section
* save corrections

Manual edits must be persisted.

---

# Configuration

Create configurable thresholds rather than scattering magic numbers throughout the code.

Example:

```python
STRUCTURE_CONFIG = {
    "energy_change_threshold": ...,
    "bass_enter_threshold": ...,
    "bass_exit_threshold": ...,
    "fill_density_multiplier": ...,
    "riser_min_bars": ...,
    "impact_threshold": ...,
    "section_confidence_threshold": ...
}
```

Prefer a dataclass/config object if consistent with the existing project.

---

# Performance

The analyzer should run locally.

Do not upload audio anywhere.

Do not call external APIs.

Avoid unnecessarily recomputing Demucs stems.

If stems already exist for the job, reuse them.

Cache analysis results when practical.

A second analysis of the same audio should not unnecessarily repeat expensive processing.

---

# Testing

Create tests for:

1. bar duration calculation
2. beat-to-bar conversion
3. feature normalization
4. stem activity detection
5. energy change detection
6. phrase boundary scoring
7. section classification
8. event detection
9. JSON serialization
10. malformed/missing stem handling

Use synthetic audio fixtures where possible.

Also create at least a few integration tests using short audio fixtures.

---

# Important Edge Cases

Handle:

* variable BPM
* inaccurate BPM detection
* tracks that begin before the first clear downbeat
* tracks without vocals
* tracks without bass
* tracks without separate guitar/piano stems
* very quiet stems
* heavily compressed tracks
* long ambient intros
* unusual time signatures when detectable
* half-time/double-time BPM interpretations

Do not assume every electronic track is exactly 4/4.

However, 4/4 should be the default when confidence is high and no reliable alternative is detected.

---

# UX Philosophy

This is a music analysis/debugging tool.

The goal is not to produce vague AI-style descriptions.

Every reported event should ideally correspond to measurable audio evidence.

Prefer:

```text
Bass enters
Energy +34%
Snare density +120%
```

over:

```text
The producer creates excitement here.
```

Do not speculate about artistic intent.

---

# Development Process

Implement in small steps.

Recommended order:

## Phase 1

* structure analyzer module
* beat/downbeat/bar grid
* JSON output
* tests

## Phase 2

* per-bar feature extraction
* stem activity
* change-point detection

## Phase 3

* phrase detection
* deterministic section classification

## Phase 4

* event detection
* deterministic descriptions

## Phase 5

* API integration
* persistence

## Phase 6

* waveform visualization
* section interaction
* manual editing

## Phase 7

* performance optimization
* caching
* test coverage
* polish

After each phase:

1. Run tests.
2. Run the application.
3. Verify existing functionality still works.
4. Do not continue if a regression appears.

---

# Acceptance Criteria

The implementation is successful when I can load an electronic music track and SelfStem automatically produces something approximately like:

```text
126 BPM
A minor
4/4

INTRO
Bars 1–16
16 bars
Kick · Atmosphere · FX

GROOVE
Bars 17–32
16 bars
Kick · Bass · Hats · Percussion

BUILD
Bars 33–40
8 bars
+ Snare
+ Rising FX
- Bass

DROP
Bars 41–72
32 bars
Kick · Bass · Synth · Percussion

BREAKDOWN
Bars 73–88
16 bars
Vocals · Pad · FX

DROP 2
Bars 89–120
32 bars
Full drums · Bass · Synth
```

The exact labels may vary depending on the track.

The important requirements are:

* sections align to actual musical bars
* duration is expressed in bars
* start/end bars are available
* timestamps are available
* meaningful stem changes are detected
* fills/risers/impacts can be detected
* everything runs locally
* no generative AI is required
* user can manually correct the result
* existing SelfStem functionality remains intact

---

# Final requirement

Before finishing, provide:

1. Files changed
2. New dependencies
3. New API endpoints or modifications
4. New UI components
5. Analysis algorithm summary
6. Test results
7. Known limitations
8. Example JSON output
9. Instructions for running the analyzer locally

Do not claim that the analyzer is musically perfect.

The system should expose confidence scores and make its uncertainty visible.
