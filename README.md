# yt_bundle

Utilities for:

- downloading YouTube videos with preferred Chinese or English subtitles
- retrying protected downloads with browser cookies or `cookies.txt`
- generating transcript bundles from local video or subtitle files
- generating extra Chinese reading and summary outputs when the source is English

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

## Common Usage

Unified pipeline:

```bash
python3 scripts/yt_bundle.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

Use browser cookies when YouTube blocks anonymous requests:

```bash
python3 scripts/yt_bundle.py "https://www.youtube.com/watch?v=VIDEO_ID" --cookies-from-browser chrome
```

Generate from an existing local subtitle or video:

```bash
python3 scripts/make_transcript_bundle.py "/path/to/file.srt"
python3 scripts/make_transcript_bundle.py "/path/to/file.mp4"
```

Batch process a directory:

```bash
python3 scripts/make_transcript_bundle.py "/path/to/dir" --batch
```
