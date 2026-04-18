# Workflow Reference

## Main Entry Point

Use `scripts/yt_bundle.py` for the normal end-to-end case:

```bash
python3 scripts/yt_bundle.py "<youtube-url>" --output-dir "<dir>"
python3 scripts/yt_bundle.py "<youtube-url>" --media-type audio --output-dir "<dir>"
python3 scripts/yt_bundle.py "<youtube-url>" --media-type subtitle --output-dir "<dir>"
python3 scripts/yt_bundle.py "<youtube-url>" --bilingual-docx --output-dir "<dir>"
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
- then prefer `zh-TW`, `zh-Hans`, `zh-Hant`, `zh`
- retry protected downloads with cookies
- use `--media-type audio` when the user asks to download audio only
- use `--media-type subtitle` when the user wants subtitle-only download before bundle generation

## Local Bundle Generation

Use `scripts/make_transcript_bundle.py` for:

- a local `.mp4`, `.mov`, `.mkv`, `.webm`, or similar video file
- a local `.mp3`, `.m4a`, `.wav`, `.flac`, `.opus`, or similar audio file
- a local `.srt`
- a directory that should be batch processed
- a mixed directory where batch mode should use the existing `.srt` files first, then optionally fall back to media transcription

Examples:

```bash
python3 scripts/make_transcript_bundle.py "/path/to/file.srt"
python3 scripts/make_transcript_bundle.py "/path/to/file.mp4"
python3 scripts/make_transcript_bundle.py "/path/to/file.mp3"
python3 scripts/make_transcript_bundle.py "/path/to/dir" --batch
python3 scripts/make_transcript_bundle.py "/path/to/dir" --batch --source-kind audio
python3 scripts/make_transcript_bundle.py "/path/to/file.srt" --bilingual-docx
```

Timing note:

- In the normal workflow, `.srt` is the retained intermediate output.
- When processing video or audio, persist the Whisper transcription as a same-basename `.srt` and build the reading drafts from that subtitle timeline.

## Output Conventions

Base outputs:

- `<stem>.srt` when transcription from media is required
- `<stem> 阅读整理稿.md`

Extra outputs for English sources:

- `<stem> 中文阅读整理稿.md`

Optional bilingual docx output for English sources:

- `<stem> 双语阅读整理稿.docx`

## Guardrails

- Do not delete existing media or generated outputs unless the user explicitly asks.
- Do not assume YouTube anonymous download will work; be ready to retry with cookies.
- Prefer the unified script for URL-based requests so download-source selection stays consistent.
- Prefer `faster-whisper` for media transcription. If it is unavailable, the pipeline may fall back to `openai-whisper`.
- If translation of an English reading draft stalls on a specific paragraph, keep writing the rest of the Chinese markdown and mark the failed paragraph inline rather than failing the entire draft.
- Prefer official translation backends for English-to-Chinese work: DeepL first, then Google Cloud Translation when credentials are available in the environment. If neither key is configured, fall back to the legacy Google translate endpoint so the pipeline can still produce drafts.
- If the needed outputs already exist in a temp directory or nearby workspace, move or reuse them instead of rerunning expensive download, transcription, or translation steps unless the user explicitly asks to regenerate.
- When a directory contains both subtitles and media files, plain `--batch` runs in two stages: existing `.srt` first, then an optional media fallback prompt for items that still have no subtitle. Switch to `--source-kind audio` or `--source-kind video` only when the user explicitly wants a media-first batch pass.
- English subtitle batches still generate Chinese reading companions, so the translation phase can take much longer than the initial transcript and reading-file write.
- For English sources, the Chinese reading markdown should be generated from the English reading markdown after the English draft is written or refreshed. This keeps section timestamps and paragraph grouping aligned with the English source draft.
- The bilingual docx export is only for English sources that already have the paired English and Chinese reading markdown files. Its layout is section-based, with English and Chinese paragraphs alternating inside each section.
- Exported bilingual docx files add centered page numbers in the footer.
