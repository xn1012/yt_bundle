# yt_bundle

Utilities for:

- downloading YouTube videos with preferred Chinese or English subtitles
- downloading YouTube audio-only sources for transcription workflows
- retrying protected downloads with browser cookies or `cookies.txt`
- generating transcript bundles from local video, audio, subtitle files, or source directories
- generating extra Chinese reading outputs when the source is English

## What It Does

This repo is built around one practical workflow:

1. Download a YouTube video or audio source.
2. Prefer English subtitles when available, then Chinese subtitles.
3. Fall back to video or audio transcription when subtitles are unavailable.
4. Generate a transcript bundle:
   - subtitle `.srt`
   - reading draft `.md`
5. If the source is English, also generate:
   - Chinese reading draft `.md`

## Requirements

- Python 3.10+
- `ffmpeg` available in `PATH`
- network access for YouTube download and English-to-Chinese translation

Install Python dependencies:

```bash
python3 -m pip install -r requirements.txt
```

Notes:

- `yt-dlp` is used for downloading video and subtitle sources.
- `openai-whisper` is used when the pipeline must transcribe from video.
- `ffmpeg` is required by `yt-dlp` audio extraction and Whisper media handling.
- `requests` is used by the older bilingual helper script.

## Recommended Entry Point

The shortest daily-use command is:

```bash
python3 scripts/yt_bundle.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

This will:

- download the video by default
- try to fetch subtitles
- choose the best available processing source, falling back to media transcription
- generate the bundle automatically

In the normal workflow, `.srt` is the retained intermediate artifact. If the pipeline must transcribe from video or audio, Whisper output is persisted as `.srt` and the reading drafts are generated from that subtitle timeline.

## Scripts

- `scripts/yt_bundle.py`
  Unified entry point. Download a YouTube link, choose the best available subtitle, audio, or video source, and generate the bundle.
- `scripts/process_youtube_bundle.py`
  Full pipeline entry point used by `yt_bundle.py`.
- `scripts/download_youtube_source.py`
  Download-only helper with video/audio selection, subtitle selection, and cookie retry logic.
- `scripts/make_transcript_bundle.py`
  Generate subtitle `.srt` when needed plus reading draft `.md` from a local video, audio, `.srt`, or source directory.
- `scripts/make_bilingual_reading_md.py`
  Older helper for bilingual reading markdown generation.

## Codex Skill

The repository also tracks the Codex skill metadata for this workflow:

- `skills/yt-bundle/SKILL.md`
- `skills/yt-bundle/agents/openai.yaml`
- `skills/yt-bundle/references/workflow.md`

The live auto-discovered local skill can be installed under `~/.codex/skills/yt-bundle`. The installer copies the repository-backed skill metadata and the current `scripts/` helpers into that live skill directory.

Install the tracked skill into your local Codex skills directory:

```bash
python3 scripts/install_skill.py
```

Install into a custom skills root for testing:

```bash
python3 scripts/install_skill.py --target-dir /tmp/skill-test
```

Replace an existing installed copy and keep a timestamped backup:

```bash
python3 scripts/install_skill.py --force
```

## Quick Start

Unified pipeline:

```bash
python3 scripts/yt_bundle.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

Use browser cookies when YouTube blocks anonymous requests:

```bash
python3 scripts/yt_bundle.py "https://www.youtube.com/watch?v=VIDEO_ID" --cookies-from-browser chrome
```

Download audio instead of video before generating the bundle:

```bash
python3 scripts/yt_bundle.py "https://www.youtube.com/watch?v=VIDEO_ID" --media-type audio --cookies-from-browser chrome
```

Use a `cookies.txt` file:

```bash
python3 scripts/yt_bundle.py "https://www.youtube.com/watch?v=VIDEO_ID" --cookies /path/to/cookies.txt
```

Send all outputs to a dedicated directory:

```bash
python3 scripts/yt_bundle.py "https://www.youtube.com/watch?v=VIDEO_ID" --output-dir "/path/to/output"
```

## Local Source Processing

Generate from an existing local subtitle, video, or audio file:

```bash
python3 scripts/make_transcript_bundle.py "/path/to/file.srt"
python3 scripts/make_transcript_bundle.py "/path/to/file.mp4"
python3 scripts/make_transcript_bundle.py "/path/to/file.mp3"
```

When the local source is English, this script also writes a Chinese reading file.

When the local source is video or audio, the script persists Whisper output as a same-basename `.srt` beside the final reading drafts.

Batch process a directory:

```bash
python3 scripts/make_transcript_bundle.py "/path/to/dir" --batch
```

In batch mode, plain `--batch` now runs in two stages: process existing `.srt` files first, then report media-only items that still have no subtitle. Interactive runs ask before starting Whisper transcription for that second stage, and the default answer is no.
Use `--source-kind audio` or `--source-kind video` only when you explicitly want media-only regeneration from local files.

## Typical Outputs

For a source named `Example Video [abc123].mp4` or `Example Video [abc123].en.srt`, the bundle generator creates:

- `Example Video [abc123].srt` when transcription from media is required
- `Example Video [abc123] 阅读整理稿.md`

If the source is English, it also creates:

- `Example Video [abc123] 中文阅读整理稿.md`

## Help

Each script supports `-h` / `--help`:

```bash
python3 scripts/yt_bundle.py -h
python3 scripts/download_youtube_source.py -h
python3 scripts/make_transcript_bundle.py -h
```
