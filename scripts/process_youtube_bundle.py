from __future__ import annotations

import argparse
from pathlib import Path

from download_youtube_source import (
    DEFAULT_BROWSER_ORDER,
    DEFAULT_SUBTITLE_LANGS,
    download_youtube,
)
from make_transcript_bundle import (
    bundle_status,
    canonical_base_name,
    generate_bundle,
    infer_language_from_candidates,
    source_priority,
)


def parse_args() -> argparse.Namespace:
    examples = """Examples:
  python3 yt_bundle.py "https://www.youtube.com/watch?v=3DlXq9nsQOE"
  python3 yt_bundle.py "https://www.youtube.com/watch?v=3DlXq9nsQOE" --output-dir "/path/to/output"
  python3 yt_bundle.py "https://www.youtube.com/watch?v=3DlXq9nsQOE" --cookies-from-browser chrome
  python3 yt_bundle.py "https://www.youtube.com/watch?v=3DlXq9nsQOE" --cookies /path/to/cookies.txt
  python3 yt_bundle.py "https://www.youtube.com/watch?v=3DlXq9nsQOE" --media-type audio
"""
    parser = argparse.ArgumentParser(
        description="Download a YouTube video or audio source, choose the best available subtitle/media source, and generate the transcript bundle.",
        epilog=examples,
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument(
        "--output-dir",
        default=".",
        help="Directory to save downloaded files and generated bundle outputs. Defaults to the current directory.",
    )
    parser.add_argument(
        "--cookies",
        help="Path to a cookies.txt file for authenticated downloads.",
    )
    parser.add_argument(
        "--cookies-from-browser",
        help="Browser name to read cookies from, for example chrome or safari.",
    )
    parser.add_argument(
        "--cookie-browser-order",
        default=",".join(DEFAULT_BROWSER_ORDER),
        help="Fallback browser order when authenticated retry is needed.",
    )
    parser.add_argument(
        "--prefer-subtitle-langs",
        default=",".join(DEFAULT_SUBTITLE_LANGS),
        help="Preferred subtitle language order. Defaults to zh-Hans,zh-Hant,zh,en,en-orig.",
    )
    parser.add_argument(
        "--format",
        default="bv*+ba/b",
        help="yt-dlp video format selector. Defaults to bv*+ba/b. For audio downloads, defaults to ba.",
    )
    parser.add_argument(
        "--media-type",
        choices=("video", "audio"),
        default="video",
        help="Download video or audio before bundle generation. Defaults to video.",
    )
    parser.add_argument(
        "--audio-format",
        default="mp3",
        help="Audio format used with --media-type audio. Defaults to mp3.",
    )
    parser.add_argument(
        "--js-runtime",
        default="node",
        help="Runtime passed to yt-dlp --js-runtimes. Defaults to node.",
    )
    parser.add_argument(
        "--whisper-model",
        default="small",
        help="Whisper model name for video transcription fallback. Defaults to small.",
    )
    parser.add_argument(
        "--bootstrap-whisper",
        action="store_true",
        help="Create a temporary Whisper environment if no runtime is currently available.",
    )
    parser.add_argument(
        "--summary-points",
        type=int,
        default=10,
        help="Number of summary bullets to generate. Defaults to 10.",
    )
    return parser.parse_args()


def choose_processing_source(
    video_path: Path | None,
    audio_path: Path | None,
    subtitle_paths: list[Path],
) -> tuple[Path, list[Path]]:
    candidates = list(subtitle_paths)
    if audio_path is not None:
        candidates.append(audio_path)
    if video_path is not None:
        candidates.append(video_path)
    if not candidates:
        raise RuntimeError("Download finished but no video, audio, or subtitle source was found for bundle generation.")
    return min(candidates, key=source_priority), candidates


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir).expanduser().resolve()
    preferred_subtitle_langs = [item.strip() for item in args.prefer_subtitle_langs.split(",") if item.strip()]
    browser_order = [item.strip() for item in args.cookie_browser_order.split(",") if item.strip()]

    print(f"[download] {args.url}", flush=True)
    result = download_youtube(
        url=args.url,
        output_dir=output_dir,
        fmt=args.format,
        media_type=args.media_type,
        audio_format=args.audio_format,
        js_runtime=args.js_runtime,
        cookies_path=args.cookies,
        cookies_from_browser=args.cookies_from_browser,
        browser_order=browser_order,
        preferred_subtitle_langs=preferred_subtitle_langs,
    )

    source_path, candidates = choose_processing_source(
        video_path=result.video_path,
        audio_path=result.audio_path,
        subtitle_paths=result.subtitle_paths,
    )
    base_name = canonical_base_name(source_path)
    status = bundle_status(output_dir=output_dir, base_name=base_name, candidates=candidates)
    language_hint = infer_language_from_candidates(candidates)

    print(f"[source] using {source_path.name}", flush=True)
    generate_bundle(
        input_path=source_path,
        output_dir=output_dir,
        base_name=base_name,
        whisper_model=args.whisper_model,
        bootstrap_whisper=args.bootstrap_whisper,
        summary_points=args.summary_points,
        status=status,
        language_hint=language_hint,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
