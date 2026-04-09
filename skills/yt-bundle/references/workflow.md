# Workflow Reference

## Main Entry Point

Use `scripts/yt_bundle.py` for the normal end-to-end case:

```bash
python3 scripts/yt_bundle.py "<youtube-url>" --output-dir "<dir>"
```

Add cookies when needed:

```bash
python3 scripts/yt_bundle.py "<youtube-url>" --output-dir "<dir>" --cookies-from-browser chrome
python3 scripts/yt_bundle.py "<youtube-url>" --output-dir "<dir>" --cookies /path/to/cookies.txt
```

## Download Only

Use `scripts/download_youtube_source.py` when the user only wants video and subtitle files.

Behavior:

- prefer `zh-Hans`, `zh-Hant`, `zh`
- then prefer `en`, `en-orig`
- retry protected downloads with cookies

## Local Bundle Generation

Use `scripts/make_transcript_bundle.py` for:

- a local `.mp4`, `.mov`, `.mkv`, `.webm`, or similar video file
- a local `.srt`
- a directory that should be batch processed

Examples:

```bash
python3 scripts/make_transcript_bundle.py "/path/to/file.srt"
python3 scripts/make_transcript_bundle.py "/path/to/file.mp4"
python3 scripts/make_transcript_bundle.py "/path/to/dir" --batch
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
