---
name: yt-bundle
description: Download YouTube videos with preferred Chinese or English subtitles, retry protected downloads with browser cookies or cookies.txt, and generate transcript bundles from YouTube links, local video files, subtitle files, or source directories. Use when Codex needs to fetch YouTube material, transcribe videos, turn subtitles into raw transcript txt plus reading and summary markdown, or generate extra Chinese reading and summary outputs for English sources.
---

# Yt Bundle

Use this skill to run the existing YouTube download and transcript-bundle workflow instead of rebuilding the process manually.

## Quick Decision

- If the user gives a YouTube URL and wants the whole workflow, run `scripts/yt_bundle.py` from the repository root.
- If the user gives a YouTube URL and wants download only, run `scripts/download_youtube_source.py`.
- If the user gives a local video file or subtitle file, run `scripts/make_transcript_bundle.py`.
- If the user gives a directory and wants missing bundles filled in, run `scripts/make_transcript_bundle.py <dir> --batch`.

## Default Behavior

- Write outputs into the user-requested directory. If none is given, use the current working directory.
- Prefer Chinese subtitles over English subtitles when both exist.
- Fall back to video transcription when subtitles are unavailable.
- Preserve existing downloaded media and generated outputs unless the user explicitly asks to delete or overwrite.
- Expect English sources to produce:
  - raw transcript `.txt`
  - source-language reading draft `.md`
  - source-language minimal summary `.md`
  - Chinese reading draft `.md`
  - Chinese minimal summary `.md`

## Commands

Run the unified workflow:

```bash
python3 scripts/yt_bundle.py "<youtube-url>" [--output-dir "<dir>"] [--cookies-from-browser chrome]
```

Run download only:

```bash
python3 scripts/download_youtube_source.py "<youtube-url>" [--output-dir "<dir>"] [--cookies-from-browser chrome]
```

Run local bundle generation:

```bash
python3 scripts/make_transcript_bundle.py "<video-or-srt-path>" [--output-dir "<dir>"]
python3 scripts/make_transcript_bundle.py "<dir>" --batch
```

## Working Notes

- Use `-h` on any bundled script if options are unclear.
- Use `--cookies-from-browser chrome` first when YouTube blocks anonymous access and the user has not provided a cookies file.
- Use `--bootstrap-whisper` only when video transcription is required and no working Whisper runtime is already available.
- Read [references/workflow.md](references/workflow.md) when you need the exact output conventions or a reminder of which script to call.
