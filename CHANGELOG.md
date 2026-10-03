# Changelog

This file records version changes for all skills in this repository.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and version numbers follow [Semantic Versioning](https://semver.org/).

## [Unreleased] — found and fixed during end-to-end validation ahead of the repository's first release

> The 9 items below are the problems that surfaced when the skill was **actually run end to end** (the 3-page sample: narration → segment rendering → concat → burned-in subtitles → SRT), and they are already fixed in this repository.
> They have not yet been ported back to the marketplace version (which is still 1.1.0); after porting, cut 1.1.1. **The first 6 of them all fail silently, so they must be ported back.**

### Changed

- **This repository is now English-only.** The README, `SKILL.md`, this changelog, `references/setup.md`, every script comment and every user-facing message were translated. Two default output names changed along with it: `gen_final.mjs --out` now defaults to `final.mp4` and `gen_srt.mjs --out` to `final.srt` (both were non-ASCII names before, which also made them awkward in shell pipelines).
- `gen_film_ass.py` now reports a missing duration table with a readable one-line message instead of a bare `FileNotFoundError` traceback, matching what `render_all.py` already did for its `--rows` input.
- `tools/pack_skill.py`'s leak check now matches the local username on alphanumeric boundaries. A maintainer handle that merely contains it (for example `cernetman` versus the local account `cerne`) no longer trips the check, while real leaks such as `C:\Users\cerne\...` or `cerne@host` are still caught.

### Fixed

- **Subtitles accumulate a per-page offset (silent failure, most severe)**: `gen_film_ass.py` defaults `--t` to 0.5 (to compensate for xfade transitions), but the three-stage pipeline uses `--mode concat` with **hard cuts** and no overlap → subtitles for page *i* land (i−1)×0.5s early. Measured on 3 pages: the picture flips at 11.736s / 22.608s, but the subtitles settle at 11.236s / 21.608s; **at 50 pages the last page is 24.5s early**, with no error reported anywhere. Fix: pass `--t 0` for hard-cut output (the example and parameter table in SKILL.md are synced); when `--t` is non-zero the script now prints a warning describing this risk.
- **`durations.json` had nowhere to come from**: `render_all.py` takes `--rows` as a required input, but no script in the original 7-step pipeline produced it, so running the pipeline directly just yielded a bare `FileNotFoundError` stack trace. Fix: SKILL.md step 4 now documents how to generate it (use `ffprobe` to measure the real duration of `mp3/NN.mp3`, with a ready-made one-liner); `render_all.py` now emits a friendly error message that explains the format.
- **`gen_film_ass.py` reported the wrong number in its summary line**: it used `max(durs.values())` (the longest single page) rather than the coverage of the whole film, so a 3-page film reported `timeline covers 14.9s` when the real value is 37.5s. Fix: coverage is now computed from how the events actually advance, and the line reads `wrote <file>, N events, timeline covers 0 ~ 37.536s` — any mismatch with the final runtime is obvious at a glance.
- **ASS timestamps wrote milliseconds into the centiseconds field (most severe: the entire subtitle track is misaligned)**: `tss()` used `%02d` to print the millisecond remainder (0–999), so values ≥100 produced three decimal places (`.100` / `.500` / `.999`). In the ASS specification the fractional part is **centiseconds (fixed at 2 digits)**, and libass parses it as centiseconds → the fractional part is **inflated 10×**: an event declared to start at `0:00:00.100` only shows its subtitle at **1.0s**; `.999` is off by 9s. The error jumps around with the millisecond digits of each timestamp (0–9s), **with zero errors reported throughout**. How to confirm it: render the ASS alone onto a black background and use `setpts=PTS+T/TB` to seek to a known instant and count white pixels. Fix: compute in centiseconds and always print 2 digits (one place each in `gen_film_ass.py` and `gen_sentence_ass.py`).
- **`--mode static` silently produced 0 subtitles (the result was a film with no subtitles at all)**: `gen_film_ass.py` looked up `bounds.get(str(1))` = `"1"`, whereas the keys in `bounds_cache.json` are `"01"` (as written by `gen_sentence_ass.py` itself). The latter has a robust `cache_get()` that probes both spellings, but the former did not use it; rolling mode masked the bug by falling back to reading `vo3/NN.txt` when the lookup failed, but static mode has no fallback → 0 events across the whole film. Fix: probe both key spellings, and add a safeguard that refuses to write a subtitle file when there are no events at all.
- **Static subtitles did not wrap or center**: both modes shared one hard-coded ASS header (`WrapStyle: 2` + `Alignment 7` + `MarginV y`, all of which are specific to rolling subtitles) → long static sentences ran off the right edge instead of wrapping. Fix: generate the header per mode — rolling uses `WrapStyle 2`/`Alignment 7`/`MarginV y`, static uses `WrapStyle 0`/`Alignment 2`/`MarginV h−y`, matching the "three subtitle forms" table in SKILL.md.
- **`--w`/`--h` had no effect when passed (portrait support was effectively useless)**: the header hard-coded `PlayResX/PlayResY` at 1920×1080, so `--w 1080 --h 1920` did not change the output. Fix: the header now reads `--w`/`--h` (measured portrait output gives `PlayResX: 1080` / `PlayResY: 1920`).
- **`esc()` did not handle line breaks (pitfall 1 recurring)**: multi-line copy spliced raw newlines into the `Dialogue` line, leaving the second line without a `Dialogue:` prefix → libass parsing fails and **the whole subtitle disappears without any error**. This entry was already in the pitfall list, but neither script's `esc()` implemented it. Fix: escape line by line first, then join with a literal `\N`.
- **`--bounds` robustness**: JSON with a BOM threw a bare stack trace (only `FileNotFoundError` was caught), and so did corrupted JSON. Fix: read with `utf-8-sig` and give a human-readable error when the file is corrupted.

### Documentation

- `references/setup.md` now includes a real preflight output sample and explains that the `page images` item is **inevitably** ❌ before you start work, so it is not mistaken for an environment failure.
- The pitfall list grew from 14 to 18 entries (adding the "centiseconds vs. milliseconds", "`--t` offset", "`durations.json`", and "shared header across both modes" items above).

## [1.1.0] - 2026-10-02

Skill: `ppt-to-explainer-video-ffmpeg`

### Added

- **Rolling marquee subtitles**: subtitles scroll right to left, precisely synchronized sentence by sentence with the speech (measured at 6.6–9.1 characters/second), with adjustable font size; the original "static per-sentence subtitles" remain available, and each page switches between the two forms.
- **Opening card + frozen final page**: can generate a 3-second text opening (with slow push-in and fade in/out support), and the final page can be frozen for an extra N seconds as an outro.
- **Scripts grew from 3 to 7, all parameterized**: `precheck` (environment preflight check before starting) / `gen_sentence_ass` (narration + subtitles in one step) / `render_all` (parallel segment rendering) / `gen_film_ass` (absolute timeline for the whole film) / `gen_final` (final compositing, dual mode) / `gen_ass` / `gen_srt`. Paths, segment names, output names, frame size, font size, transitions, and CRF can all be specified via parameters.
- **Standalone SRT export upgraded to per-sentence granularity** (previously only one cue per page), with a UTF-8 BOM so Chinese text is not garbled in Chinese-language players.
- **Portrait support** (1080×1920 storyboard).

### Changed

- Adopted the three-stage approach "segment rendering (parallel) → `-c copy` hard-cut concat → burn subtitles in a single pass", replacing the previous "burn subtitles per segment + N-1 levels of xfade".
- **The default transition for the final film changed from cross-fade to hard cut + subtitle timeline**. Users who rely on the cross-fade look should pass `--mode xfade` explicitly.
- Environment dependencies are now auto-detected, and **the scripts no longer hard-code absolute paths for any particular machine**; specify them explicitly with `--ff` / `--ffprobe` / `--font` / `--py` when needed.

### Performance

Measured at 50 pages / 1920×1080 / 30fps:

| Stage | 1.0.0 | 1.1.0 |
|---|---|---|
| Segment rendering | 65 s (serial, subtitles burned per segment) | 41.7 s (parallel `--j 4`, no subtitles burned) |
| Transition concat | 63 s (49 levels of xfade, re-encoding the whole film each time) | 1.4 s (hard cut, 0 re-encodes) |
| Burning subtitles | included in segment rendering | once for the whole film: 47.5 s (medium) / 34.8 s (veryfast) |
| **Total** | **128 s** | **90.6 s (-29%)**, 77.9 s on the veryfast preset (-39%) |

Full-film regression: duration 464.5 s → 492.1 s, size 119.5 MB → 47.9 MB (40% of the old version), bitrate 2059 → 778 kbps, and text sharpness looks unchanged when sampling frames by eye.

A bonus benefit: the concat output `master.mp4` is a **subtitle-free master** — changing the subtitle form or the opening card requires neither re-recording the narration nor re-rendering the segments.

### Fixed

- **The first 9 pages were missing subtitles entirely**: the voice-boundary cache had keys `"1"` and `"01"` that did not match, causing a silent empty lookup.
- **Multi-line copy made a whole page's subtitles disappear**: the ASS concatenation order was wrong (escaping must happen before joining with `\N`).
- **Audio was lost after concat**: the opening card lacked a silent audio track.
- **An opening card was requested but silently not produced**: now the script exits with an error and a fix hint.
- SRT start/end times overlapped; missing inputs produced a bare stack trace (now a human-readable message).

## [1.0.0] - 2026-09-28

Skill: `ppt-to-explainer-video-ffmpeg`

### Added

- First release: PPT/PDF → page-by-page explainer video (page images + edge-tts Chinese narration + burned-in subtitles + xfade cross-fade transitions).
- 3 scripts: page image / narration / subtitle generation, segment rendering, and xfade compositing into the final film.
- Fully local rendering: no dependency on online transcription services, and no assets are uploaded.

[1.1.0]: https://github.com/__GH_USER__/agent-skills/releases/tag/v1.1.0
[1.0.0]: https://github.com/__GH_USER__/agent-skills/releases/tag/v1.0.0
