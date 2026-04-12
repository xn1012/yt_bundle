# Workflow Reference

## Main Entry Point

Use `scripts/yt_bundle.py` for the normal end-to-end case:

```bash
python3 scripts/yt_bundle.py "<youtube-url>" --output-dir "<dir>"
python3 scripts/yt_bundle.py "<youtube-url>" --media-type audio --output-dir "<dir>"
python3 scripts/yt_bundle.py "<youtube-url>" --media-type subtitle --output-dir "<dir>"
```

Add cookies when needed:

```bash
python3 scripts/yt_bundle.py "<youtube-url>" --output-dir "<dir>" --cookies-from-browser chrome
python3 scripts/yt_bundle.py "<youtube-url>" --output-dir "<dir>" --cookies /path/to/cookies.txt
```

## Download Only

Use `scripts/download_youtube_source.py` when the user only wants video/audio and subtitle files.

Behavior:

- prefer `en`, `en-orig`
- then prefer `zh-Hans`, `zh-Hant`, `zh`
- retry protected downloads with cookies
- use `--media-type audio` when the user asks to download audio only
- use `--media-type subtitle` when the user wants subtitle-only download before bundle generation

## Local Bundle Generation

Use `scripts/make_transcript_bundle.py` for:

- a local `.mp4`, `.mov`, `.mkv`, `.webm`, or similar video file
- a local `.mp3`, `.m4a`, `.wav`, `.flac`, `.opus`, or similar audio file
- a local `.srt`
- a local `.txt` transcript artifact
- a directory that should be batch processed
- a mixed directory where only subtitle files should be processed via `--source-kind subtitle`

Examples:

```bash
python3 scripts/make_transcript_bundle.py "/path/to/file.srt"
python3 scripts/make_transcript_bundle.py "/path/to/file.mp4"
python3 scripts/make_transcript_bundle.py "/path/to/file.mp3"
python3 scripts/make_transcript_bundle.py "/path/to/file.txt"
python3 scripts/make_transcript_bundle.py "/path/to/dir" --batch
python3 scripts/make_transcript_bundle.py "/path/to/dir" --batch --source-kind subtitle
```

Timing note:

- In the normal workflow, `.srt` is the retained intermediate output.
- When processing video or audio, persist the Whisper transcription as a same-basename `.srt` and build the reading drafts from that subtitle timeline.
- When processing a `.txt`, prefer to preserve section timestamps by reusing a same-basename companion `.srt` in the same directory.
- If no companion `.srt` exists, the reading draft can still be generated, but section headings will not have reliable timestamps.

## Output Conventions

Base outputs:

- `<stem>.srt` when transcription from media is required
- `<stem> 阅读整理稿.md`

Extra outputs for English sources:

- `<stem> 中文阅读整理稿.md`

## Guardrails

- Do not delete existing media or generated outputs unless the user explicitly asks.
- Do not assume YouTube anonymous download will work; be ready to retry with cookies.
- Prefer the unified script for URL-based requests so download-source selection stays consistent.
- When a directory contains both subtitles and media files, use `--source-kind subtitle` if the request is based on existing `.srt` files; otherwise the batch pass may also pick up `.mp4`/`.mp3` sources.
- When a directory contains both `.txt` and `.srt` files for the same item, the `.txt` reading draft should still inherit timestamps from the companion subtitle rather than dropping them.
- English subtitle batches still generate Chinese reading companions, so the translation phase can take much longer than the initial transcript and reading-file write.
