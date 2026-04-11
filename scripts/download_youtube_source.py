from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


DEFAULT_BROWSER_ORDER = ["chrome", "safari", "edge", "firefox", "brave"]
DEFAULT_SUBTITLE_LANGS = ["zh-Hans", "zh-Hant", "zh", "en", "en-orig"]
DEFAULT_VIDEO_FORMAT = "bv*[height<=720]+ba/b[height<=720]"
VIDEO_EXTENSIONS = {".mp4"}
AUDIO_EXTENSIONS = {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav", ".webm"}
AUTH_REQUIRED_RE = re.compile(
    r"(sign in to confirm you.?re not a bot|use --cookies-from-browser|login required|cookies|age-restricted)",
    re.IGNORECASE,
)


@dataclass
class DownloadResult:
    url: str
    output_dir: Path
    video_id: str
    title: str
    video_path: Path | None
    audio_path: Path | None
    subtitle_paths: list[Path]
    selected_subtitle_languages: list[str]
    used_auth: str
    media_type: str


def parse_args() -> argparse.Namespace:
    examples = """Examples:
  python3 download_youtube_source.py "https://www.youtube.com/watch?v=3DlXq9nsQOE"
  python3 download_youtube_source.py "https://www.youtube.com/watch?v=3DlXq9nsQOE" --output-dir "/path/to/output"
  python3 download_youtube_source.py "https://www.youtube.com/watch?v=3DlXq9nsQOE" --cookies-from-browser chrome
  python3 download_youtube_source.py "https://www.youtube.com/watch?v=3DlXq9nsQOE" --prefer-subtitle-langs "zh-Hans,zh-Hant,zh,en,en-orig"
  python3 download_youtube_source.py "https://www.youtube.com/watch?v=3DlXq9nsQOE" --media-type audio
  python3 download_youtube_source.py "https://www.youtube.com/watch?v=3DlXq9nsQOE" --media-type subtitle
"""
    parser = argparse.ArgumentParser(
        description="Download YouTube video, audio, or subtitles with preferred English/Chinese subtitle selection and cookie-based retries.",
        epilog=examples,
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument(
        "--output-dir",
        default=".",
        help="Directory to save the media and subtitle files. Defaults to the current directory.",
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
        help="Fallback browser order when a retry needs cookies and --cookies-from-browser is not provided.",
    )
    parser.add_argument(
        "--prefer-subtitle-langs",
        default=",".join(DEFAULT_SUBTITLE_LANGS),
        help="Preferred subtitle language order. Defaults to zh-Hans,zh-Hant,zh,en,en-orig.",
    )
    parser.add_argument(
        "--format",
        default=DEFAULT_VIDEO_FORMAT,
        help=(
            "yt-dlp video format selector. Defaults to a 720p cap "
            f"({DEFAULT_VIDEO_FORMAT}). For audio downloads, defaults to ba."
        ),
    )
    parser.add_argument(
        "--media-type",
        choices=("video", "audio", "subtitle"),
        default="video",
        help="Download video, audio, or subtitles only. Defaults to video.",
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
    return parser.parse_args()


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )


def looks_like_auth_failure(output: str) -> bool:
    return AUTH_REQUIRED_RE.search(output) is not None


def unique_auth_candidates(
    cookies_path: str | None,
    cookies_from_browser: str | None,
    browser_order: list[str],
) -> list[tuple[str, list[str]]]:
    candidates: list[tuple[str, list[str]]] = [("anonymous", [])]
    seen: set[str] = {"anonymous"}

    if cookies_path:
        candidates.append(("cookies-file", ["--cookies", cookies_path]))
        seen.add("cookies-file")

    browsers: list[str] = []
    if cookies_from_browser:
        browsers.append(cookies_from_browser)
    browsers.extend(browser_order)

    for browser in browsers:
        browser = browser.strip()
        if not browser:
            continue
        label = f"browser:{browser}"
        if label in seen:
            continue
        candidates.append((label, ["--cookies-from-browser", browser]))
        seen.add(label)

    return candidates


def metadata_command(url: str, js_runtime: str, auth_args: list[str]) -> list[str]:
    return [
        "yt-dlp",
        "--js-runtimes",
        js_runtime,
        "--dump-single-json",
        "--no-warnings",
        "--skip-download",
        *auth_args,
        url,
    ]


def fetch_metadata(
    url: str,
    js_runtime: str,
    cookies_path: str | None,
    cookies_from_browser: str | None,
    browser_order: list[str],
) -> tuple[dict, str]:
    candidates = unique_auth_candidates(cookies_path, cookies_from_browser, browser_order)
    failures: list[tuple[str, str]] = []

    for label, auth_args in candidates:
        result = run_command(metadata_command(url=url, js_runtime=js_runtime, auth_args=auth_args))
        if result.returncode == 0:
            return json.loads(result.stdout), label
        failures.append((label, result.stdout))
        if label == "anonymous" and not looks_like_auth_failure(result.stdout):
            break

    if failures:
        label, output = failures[-1]
        raise RuntimeError(f"yt-dlp metadata lookup failed after {label}: {output.strip()}")
    raise RuntimeError("yt-dlp metadata lookup failed without any output.")


def is_chinese_lang(language: str) -> bool:
    lowered = language.lower()
    return lowered.startswith("zh")


def is_english_lang(language: str) -> bool:
    lowered = language.lower()
    return lowered.startswith("en")


def pick_preferred_language(preferred: list[str], manual: set[str], automatic: set[str], matcher) -> str | None:
    for language in preferred:
        if matcher(language) and language in manual:
            return language
    for language in preferred:
        if matcher(language) and language in automatic:
            return language
    return None


def choose_subtitle_languages(metadata: dict, preferred: list[str]) -> list[str]:
    manual = set((metadata.get("subtitles") or {}).keys())
    automatic = set((metadata.get("automatic_captions") or {}).keys())

    selected: list[str] = []
    for candidate in (
        pick_preferred_language(preferred, manual, automatic, is_chinese_lang),
        pick_preferred_language(preferred, manual, automatic, is_english_lang),
    ):
        if candidate and candidate not in selected:
            selected.append(candidate)
    return selected


def download_command(
    url: str,
    output_dir: Path,
    fmt: str,
    media_type: str,
    audio_format: str,
    js_runtime: str,
    auth_args: list[str],
    subtitle_languages: list[str],
) -> list[str]:
    command = [
        "yt-dlp",
        "--js-runtimes",
        js_runtime,
        "-o",
        "%(title)s [%(id)s].%(ext)s",
        "-P",
        str(output_dir),
    ]
    if media_type == "subtitle":
        command.append("--skip-download")
    else:
        selected_format = fmt if media_type == "video" else (fmt if fmt != DEFAULT_VIDEO_FORMAT else "ba")
        command.extend(
            [
                "-f",
                selected_format,
            ]
        )
    if media_type == "video":
        command.extend(["--merge-output-format", "mp4"])
    elif media_type == "audio":
        command.extend(["-x", "--audio-format", audio_format])
    if subtitle_languages:
        command.extend(
            [
                "--write-subs",
                "--write-auto-subs",
                "--sub-format",
                "srt/best",
                "--convert-subs",
                "srt",
                "--sub-langs",
                ",".join(subtitle_languages),
            ]
        )
    command.extend(auth_args)
    command.append(url)
    return command


def find_downloaded_files(output_dir: Path, video_id: str) -> tuple[Path | None, Path | None, list[Path]]:
    marker = f"[{video_id}]"
    video_path: Path | None = None
    audio_path: Path | None = None
    subtitle_paths: list[Path] = []

    for path in sorted(output_dir.iterdir()):
        if not path.is_file() or marker not in path.name or path.name.endswith(".part"):
            continue
        suffix = path.suffix.lower()
        if suffix in VIDEO_EXTENSIONS:
            video_path = path
        elif suffix in AUDIO_EXTENSIONS:
            audio_path = path
        elif suffix == ".srt":
            subtitle_paths.append(path)

    return video_path, audio_path, subtitle_paths


def download_youtube(
    url: str,
    output_dir: Path,
    fmt: str,
    media_type: str,
    audio_format: str,
    js_runtime: str,
    cookies_path: str | None,
    cookies_from_browser: str | None,
    browser_order: list[str],
    preferred_subtitle_langs: list[str],
) -> DownloadResult:
    output_dir.mkdir(parents=True, exist_ok=True)

    metadata, used_auth = fetch_metadata(
        url=url,
        js_runtime=js_runtime,
        cookies_path=cookies_path,
        cookies_from_browser=cookies_from_browser,
        browser_order=browser_order,
    )
    selected_subtitle_languages = choose_subtitle_languages(metadata=metadata, preferred=preferred_subtitle_langs)

    auth_args: list[str] = []
    if used_auth == "cookies-file" and cookies_path:
        auth_args = ["--cookies", cookies_path]
    elif used_auth.startswith("browser:"):
        auth_args = ["--cookies-from-browser", used_auth.split(":", 1)[1]]

    result = run_command(
        download_command(
            url=url,
            output_dir=output_dir,
            fmt=fmt,
            media_type=media_type,
            audio_format=audio_format,
            js_runtime=js_runtime,
            auth_args=auth_args,
            subtitle_languages=selected_subtitle_languages,
        )
    )
    if result.returncode != 0:
        raise RuntimeError(result.stdout.strip())

    video_id = metadata.get("id")
    title = metadata.get("title") or video_id or "downloaded-video"
    video_path, audio_path, subtitle_paths = find_downloaded_files(output_dir=output_dir, video_id=video_id)

    return DownloadResult(
        url=url,
        output_dir=output_dir,
        video_id=video_id,
        title=title,
        video_path=video_path,
        audio_path=audio_path,
        subtitle_paths=subtitle_paths,
        selected_subtitle_languages=selected_subtitle_languages,
        used_auth=used_auth,
        media_type=media_type,
    )


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir).expanduser().resolve()
    preferred_subtitle_langs = [item.strip() for item in args.prefer_subtitle_langs.split(",") if item.strip()]
    browser_order = [item.strip() for item in args.cookie_browser_order.split(",") if item.strip()]

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

    print(f"Title: {result.title}")
    print(f"Video ID: {result.video_id}")
    print(f"Auth: {result.used_auth}")
    print(f"Media type: {result.media_type}")
    print(f"Requested subtitle langs: {', '.join(result.selected_subtitle_languages) or 'none'}")
    if result.video_path is not None:
        print(result.video_path)
    if result.audio_path is not None:
        print(result.audio_path)
    if result.video_path is None and result.audio_path is None:
        print("Media file not found after download.")
    for subtitle_path in result.subtitle_paths:
        print(subtitle_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
