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
- If the user wants a bilingual reading `.docx` for an English source, add `--bilingual-docx`.
- If the user gives a YouTube URL and wants download only, run `scripts/download_youtube_source.py`.
- If the user gives a local video file, audio file, or subtitle file, run `scripts/make_transcript_bundle.py`.
- If the user gives a directory and wants missing bundles filled in, run `scripts/make_transcript_bundle.py <dir> --batch`.
- Directory batch mode is two-stage by default: process existing subtitles first, then offer media transcription as an explicit second stage with a default answer of no. Use `--source-kind audio` or `--source-kind video` only when the user explicitly wants media-only batch regeneration.

## Default Behavior

- Write outputs into the user-requested directory. If none is given, use the current working directory.
- Prefer subtitle languages in this order by default: `en`, `en-orig`, `zh-TW`, `zh-Hans`, `zh-Hant`, `zh`.
- Fall back to video or audio transcription when subtitles are unavailable.
- Preserve existing downloaded media and generated outputs unless the user explicitly asks to delete or overwrite.
- Preserve `.srt` as the retained intermediate artifact in the normal workflow.
- Expect English sources to produce:
  - subtitle `.srt`
  - source-language reading draft `.md`
  - Chinese reading draft `.md`
- If `--bilingual-docx` is enabled for an English source, also produce:
  - section-aligned bilingual reading `.docx`

## Commands

Run the unified workflow:

```bash
python3 scripts/yt_bundle.py "<youtube-url>" [--output-dir "<dir>"] [--cookies-from-browser chrome]
python3 scripts/yt_bundle.py "<youtube-url>" --media-type audio [--output-dir "<dir>"] [--cookies-from-browser chrome]
python3 scripts/yt_bundle.py "<youtube-url>" --media-type subtitle [--output-dir "<dir>"] [--cookies-from-browser chrome]
python3 scripts/yt_bundle.py "<youtube-url>" --bilingual-docx [--output-dir "<dir>"] [--cookies-from-browser chrome]
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
python3 scripts/make_transcript_bundle.py "<dir>" --batch
python3 scripts/make_transcript_bundle.py "<dir>" --batch --source-kind audio
python3 scripts/make_transcript_bundle.py "<video-audio-or-srt-path>" --bilingual-docx
```

## Working Notes

- Use `-h` on any bundled script if options are unclear.
- Use `--cookies-from-browser chrome` first when YouTube blocks anonymous access and the user has not provided a cookies file.
- Use `--bootstrap-whisper` only when media transcription is required and no working transcription runtime is already available. The script now prefers `faster-whisper` and falls back to `openai-whisper` only if needed.
- If usable outputs already exist in a temp directory or nearby workspace, prefer moving, renaming, or reusing those artifacts instead of rerunning expensive download, transcription, or translation steps. Only regenerate when the user explicitly asks for a fresh run.
- For directory jobs based on existing `.srt` files, plain `--batch` is enough. If some items still have only `.mp4` or `.mp3`, the script reports them as a stage-2 fallback and asks before starting Whisper transcription.
- In the normal workflow, subtitle timing should be preserved all the way through. If the source is video or audio, persist the Whisper transcription as `.srt` and build the reading draft from that subtitle timeline.
- English subtitle sources also generate Chinese reading companions. Write or refresh the English reading markdown first, then derive the Chinese markdown from that English reading draft so section headings and paragraph grouping stay aligned.
- The translation step can be much slower than writing the base transcript plus reading draft. If a paragraph keeps timing out, keep the rest of the Chinese draft moving and mark the failed paragraph inline instead of aborting the whole file.
- Official translation backends are preferred for English-to-Chinese drafts: use DeepL first and Google Cloud Translation second when credentials are configured. If neither key is present, the pipeline falls back to the legacy Google translate endpoint so existing workflows can still run, though large batches may be less stable.
- `--bilingual-docx` only applies to English sources with both English and Chinese reading markdown available. The exported `.docx` is section-aligned and alternates English and Chinese paragraphs inside each section.
- Read [references/workflow.md](references/workflow.md) when you need the exact output conventions or a reminder of which script to call.
