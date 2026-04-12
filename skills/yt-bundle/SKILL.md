---
name: yt-bundle
description: Download YouTube videos or audio with preferred Chinese or English subtitles, retry protected downloads with browser cookies or cookies.txt, and generate transcript bundles from YouTube links, local video/audio files, subtitle files, or source directories. Use when Codex needs to fetch YouTube material, transcribe videos or audio, preserve subtitle artifacts, turn subtitles into reading markdown, or generate extra Chinese reading outputs for English sources.
---

# Yt Bundle

Use this skill to run the existing YouTube download and transcript-bundle workflow instead of rebuilding the process manually.

## Quick Decision

- If the user gives a YouTube URL and wants the whole workflow, run `scripts/yt_bundle.py` from the repository root.
- If the user gives a YouTube URL and wants audio-only download or audio-based transcription, run `scripts/yt_bundle.py --media-type audio` or `scripts/download_youtube_source.py --media-type audio`.
- If the user gives a YouTube URL and wants subtitle-only download plus downstream processing, run `scripts/yt_bundle.py --media-type subtitle`.
- If the user gives a YouTube URL and wants download only, run `scripts/download_youtube_source.py`.
- If the user gives a local video file, audio file, or subtitle file, run `scripts/make_transcript_bundle.py`.
- If the user gives a directory and wants missing bundles filled in, run `scripts/make_transcript_bundle.py <dir> --batch`.
- If the user specifically wants to process only subtitle files inside a mixed directory, run `scripts/make_transcript_bundle.py <dir> --batch --source-kind subtitle`.

## Default Behavior

- Write outputs into the user-requested directory. If none is given, use the current working directory.
- Prefer English subtitles over Chinese subtitles when both exist.
- Fall back to video or audio transcription when subtitles are unavailable.
- Preserve existing downloaded media and generated outputs unless the user explicitly asks to delete or overwrite.
- Preserve `.srt` as the retained intermediate artifact in the normal workflow.
- Treat `.txt` as a compatibility input, not the primary timing source.
- Expect English sources to produce:
  - subtitle `.srt`
  - source-language reading draft `.md`
  - Chinese reading draft `.md`

## Commands

Run the unified workflow:

```bash
python3 scripts/yt_bundle.py "<youtube-url>" [--output-dir "<dir>"] [--cookies-from-browser chrome]
python3 scripts/yt_bundle.py "<youtube-url>" --media-type audio [--output-dir "<dir>"] [--cookies-from-browser chrome]
python3 scripts/yt_bundle.py "<youtube-url>" --media-type subtitle [--output-dir "<dir>"] [--cookies-from-browser chrome]
```

Run download only:

```bash
python3 scripts/download_youtube_source.py "<youtube-url>" [--output-dir "<dir>"] [--cookies-from-browser chrome]
python3 scripts/download_youtube_source.py "<youtube-url>" --media-type audio [--output-dir "<dir>"] [--cookies-from-browser chrome]
python3 scripts/download_youtube_source.py "<youtube-url>" --media-type subtitle [--output-dir "<dir>"] [--cookies-from-browser chrome]
```

Run local bundle generation:

```bash
python3 scripts/make_transcript_bundle.py "<video-audio-or-srt-path>" [--output-dir "<dir>"]
python3 scripts/make_transcript_bundle.py "<transcript-txt-path>" [--output-dir "<dir>"]
python3 scripts/make_transcript_bundle.py "<dir>" --batch
python3 scripts/make_transcript_bundle.py "<dir>" --batch --source-kind subtitle
```

## Working Notes

- Use `-h` on any bundled script if options are unclear.
- Use `--cookies-from-browser chrome` first when YouTube blocks anonymous access and the user has not provided a cookies file.
- Use `--bootstrap-whisper` only when video transcription is required and no working Whisper runtime is already available.
- For subtitle-only directory jobs, prefer `--source-kind subtitle` so mixed-in `.mp4` or `.mp3` files do not trigger extra source groups or Whisper transcription.
- In the normal workflow, subtitle timing should be preserved all the way through. If the source is video or audio, persist the Whisper transcription as `.srt` and build the reading draft from that subtitle timeline.
- A `.txt` input is a compatibility path. If a same-basename companion `.srt` exists beside the `.txt`, the reading draft should inherit section timestamps from that subtitle timeline.
- English subtitle sources also generate Chinese reading companions, and that translation step can be much slower than writing the base transcript plus reading draft.
- Read [references/workflow.md](references/workflow.md) when you need the exact output conventions or a reminder of which script to call.
