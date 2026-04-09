# yt_bundle

Utilities for:

- downloading YouTube videos with preferred Chinese or English subtitles
- retrying protected downloads with browser cookies or `cookies.txt`
- generating transcript bundles from local video or subtitle files
- generating extra Chinese reading and summary outputs when the source is English

## What It Does

This repo is built around one practical workflow:

1. Download a YouTube video.
2. Prefer Chinese subtitles when available, otherwise prefer English subtitles.
3. Fall back to video transcription when subtitles are unavailable.
4. Generate a transcript bundle:
   - raw transcript `.txt`
   - reading draft `.md`
   - minimal summary `.md`
5. If the source is English, also generate:
   - Chinese reading draft `.md`
   - Chinese minimal summary `.md`

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
- `requests` is used by the older bilingual helper script.

## Recommended Entry Point

The shortest daily-use command is:

```bash
python3 scripts/yt_bundle.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

This will:

- download the video
- try to fetch subtitles
- choose the best available processing source
- generate the bundle automatically

## Scripts

- `scripts/yt_bundle.py`
  Unified entry point. Download a YouTube link, choose the best available subtitle or video source, and generate the bundle.
- `scripts/process_youtube_bundle.py`
  Full pipeline entry point used by `yt_bundle.py`.
- `scripts/download_youtube_source.py`
  Download-only helper with subtitle selection and cookie retry logic.
- `scripts/make_transcript_bundle.py`
  Generate transcript `.txt`, reading draft `.md`, and minimal summary `.md` from a local video or `.srt`.
- `scripts/make_bilingual_reading_md.py`
  Older helper for bilingual reading markdown generation.

## Codex Skill

The repository also tracks the Codex skill metadata for this workflow:

- `skills/yt-bundle/SKILL.md`
- `skills/yt-bundle/agents/openai.yaml`
- `skills/yt-bundle/references/workflow.md`

The live auto-discovered local skill can be installed under `~/.codex/skills/yt-bundle`. The repository keeps the trigger text, UI metadata, and workflow reference in version control alongside the scripts.

## Quick Start

Unified pipeline:

```bash
python3 scripts/yt_bundle.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

Use browser cookies when YouTube blocks anonymous requests:

```bash
python3 scripts/yt_bundle.py "https://www.youtube.com/watch?v=VIDEO_ID" --cookies-from-browser chrome
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

Generate from an existing local subtitle or video:

```bash
python3 scripts/make_transcript_bundle.py "/path/to/file.srt"
python3 scripts/make_transcript_bundle.py "/path/to/file.mp4"
```

When the local source is English, this script also writes Chinese reading and summary files.

Batch process a directory:

```bash
python3 scripts/make_transcript_bundle.py "/path/to/dir" --batch
```

## Typical Outputs

For a source named `Example Video [abc123].mp4` or `Example Video [abc123].en.srt`, the bundle generator creates:

- `Example Video [abc123].txt`
- `Example Video [abc123] 阅读整理稿.md`
- `Example Video [abc123] 极简摘要稿.md`

If the source is English, it also creates:

- `Example Video [abc123] 中文阅读整理稿.md`
- `Example Video [abc123] 中文极简摘要稿.md`

## Help

Each script supports `-h` / `--help`:

```bash
python3 scripts/yt_bundle.py -h
python3 scripts/download_youtube_source.py -h
python3 scripts/make_transcript_bundle.py -h
```
