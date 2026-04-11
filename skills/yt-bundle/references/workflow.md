# Workflow Reference

## Main Entry Point

Use `scripts/yt_bundle.py` for the normal end-to-end case:

```bash
python3 scripts/yt_bundle.py "<youtube-url>" --output-dir "<dir>"
python3 scripts/yt_bundle.py "<youtube-url>" --media-type audio --output-dir "<dir>"
```

Add cookies when needed:

```bash
python3 scripts/yt_bundle.py "<youtube-url>" --output-dir "<dir>" --cookies-from-browser chrome
python3 scripts/yt_bundle.py "<youtube-url>" --output-dir "<dir>" --cookies /path/to/cookies.txt
```

## Download Only

Use `scripts/download_youtube_source.py` when the user only wants video/audio and subtitle files.

Behavior:

- prefer `zh-Hans`, `zh-Hant`, `zh`
- then prefer `en`, `en-orig`
- retry protected downloads with cookies
- use `--media-type audio` when the user asks to download audio only

## Local Bundle Generation

Use `scripts/make_transcript_bundle.py` for:

- a local `.mp4`, `.mov`, `.mkv`, `.webm`, or similar video file
- a local `.mp3`, `.m4a`, `.wav`, `.flac`, `.opus`, or similar audio file
- a local `.srt`
- a directory that should be batch processed
- a mixed directory where only subtitle files should be processed via `--source-kind subtitle`

Examples:

```bash
python3 scripts/make_transcript_bundle.py "/path/to/file.srt"
python3 scripts/make_transcript_bundle.py "/path/to/file.mp4"
python3 scripts/make_transcript_bundle.py "/path/to/file.mp3"
python3 scripts/make_transcript_bundle.py "/path/to/dir" --batch
python3 scripts/make_transcript_bundle.py "/path/to/dir" --batch --source-kind subtitle
```

## Output Conventions

Base outputs:

- `<stem>.txt`
- `<stem> 阅读整理稿.md`
- `<stem> 极简摘要稿.md`

Extra outputs for English sources:

- `<stem> 中文阅读整理稿.md`
- `<stem> 中文极简摘要稿.md`

## Guardrails

- Do not delete existing media or generated outputs unless the user explicitly asks.
- Do not assume YouTube anonymous download will work; be ready to retry with cookies.
- Prefer the unified script for URL-based requests so download-source selection stays consistent.
- When a directory contains both subtitles and media files, use `--source-kind subtitle` if the request is based on existing `.srt` files; otherwise the batch pass may also pick up `.mp4`/`.mp3` sources.
- English subtitle batches still generate Chinese companion outputs, so the translation phase can take much longer than the initial three-file write.
