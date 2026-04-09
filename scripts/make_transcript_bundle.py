from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import urlencode
from urllib.request import Request, urlopen


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".m4v", ".webm", ".avi"}
SUBTITLE_EXTENSIONS = {".srt"}
LANGUAGE_SUFFIXES = {
    "ar",
    "de",
    "en",
    "en-orig",
    "es",
    "fr",
    "hi",
    "id",
    "it",
    "ja",
    "ko",
    "pt",
    "ru",
    "th",
    "vi",
    "zh",
    "zh-cn",
    "zh-hans",
    "zh-hant",
    "zh-tw",
}
TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"
ZH_LANGUAGE_SUFFIXES = {"zh", "zh-cn", "zh-hans", "zh-hant", "zh-tw"}
EN_LANGUAGE_SUFFIXES = {"en", "en-orig"}
SENTENCE_END_CHARS = "。！？!?；;."
ZH_RE = re.compile(r"[\u4e00-\u9fff]+")
EN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+_.-]*")
SRT_BREAK_RE = re.compile(r"\n\s*\n", re.MULTILINE)
CACHE_VERSION = 1

TRANSLATION_REPLACEMENTS = {
    "云代码": "Claude Code",
    "克劳德": "Claude",
    "子堆栈": "Substack",
    "云桌面": "Claude Desktop",
    "共同写作系统": "协同写作系统",
    "共同编写系统": "协同写作系统",
    "coowwriter": "co-writer",
    "coowwriting": "co-writing",
    "云人工智能": "Claude AI",
    "云 AI": "Claude AI",
    "quadr": "Claude",
}

STOPWORDS = {
    "我們",
    "你們",
    "你我",
    "你們",
    "這個",
    "那個",
    "然後",
    "就是",
    "一個",
    "一些",
    "如果",
    "所以",
    "因為",
    "不是",
    "沒有",
    "可以",
    "需要",
    "然後",
    "自己",
    "現在",
    "這裡",
    "那裡",
    "其實",
    "比如",
    "這樣",
    "那樣",
    "還有",
    "以及",
    "進行",
    "完成",
    "使用",
    "問題",
    "用戶",
    "系統",
    "這期",
    "視頻",
    "一個",
    "一下",
    "就是",
    "可能",
    "因爲",
    "所以",
    "我們就",
    "一下子",
    "and",
    "the",
    "for",
    "with",
    "from",
    "that",
    "this",
    "into",
    "your",
    "you",
}


@dataclass
class Cue:
    index: int
    start_ms: int
    end_ms: int
    text: str


@dataclass
class Paragraph:
    start_ms: int
    end_ms: int
    text: str


@dataclass
class BundleStatus:
    raw_exists: bool
    reading_exists: bool
    summary_exists: bool
    zh_reading_exists: bool = False
    zh_summary_exists: bool = False
    needs_zh_extras: bool = False

    @property
    def complete(self) -> bool:
        base_complete = self.raw_exists and self.reading_exists and self.summary_exists
        if not self.needs_zh_extras:
            return base_complete
        return base_complete and self.zh_reading_exists and self.zh_summary_exists


@dataclass
class SourceGroup:
    base_name: str
    source_path: Path
    status: BundleStatus
    language_hint: str | None = None


def parse_args() -> argparse.Namespace:
    examples = """Examples:
  python3 make_transcript_bundle.py "/path/to/video.mp4"
  python3 make_transcript_bundle.py "/path/to/subtitle.srt"
  python3 make_transcript_bundle.py "/path/to/video.mp4" --output-dir "/path/to/output"
  python3 make_transcript_bundle.py "/path/to/dir" --batch
"""
    parser = argparse.ArgumentParser(
        description="Generate raw transcript txt, reading markdown, and summary markdown from a video or subtitle file.",
        epilog=examples,
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("input", help="Path to a video file, subtitle file, or directory")
    parser.add_argument(
        "--output-dir",
        help="Directory for generated files. Defaults to the input file's directory.",
    )
    parser.add_argument(
        "--whisper-model",
        default="small",
        help="Whisper model name for video transcription. Defaults to 'small'.",
    )
    parser.add_argument(
        "--bootstrap-whisper",
        action="store_true",
        help="Create a temporary venv and install openai-whisper if no Whisper runtime is found.",
    )
    parser.add_argument(
        "--summary-points",
        type=int,
        default=10,
        help="Number of summary bullets to generate. Defaults to 10.",
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Treat the input path as a directory and batch-process unhandled files inside it.",
    )
    return parser.parse_args()


def parse_timestamp(value: str) -> int:
    hh, mm, rest = value.split(":")
    ss, ms = rest.split(",")
    return ((int(hh) * 60 + int(mm)) * 60 + int(ss)) * 1000 + int(ms)


def format_timestamp(ms: int) -> str:
    total_seconds = ms // 1000
    hh, rem = divmod(total_seconds, 3600)
    mm, ss = divmod(rem, 60)
    return f"{hh:02d}:{mm:02d}:{ss:02d}"


def normalize_line(text: str) -> str:
    text = text.replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.;:?!])", r"\1", text)
    text = re.sub(r"\s+([。！？；：，、])", r"\1", text)
    text = re.sub(r"([（《“])\s+", r"\1", text)
    text = re.sub(r"\s+([）》”])", r"\1", text)
    return text


def cleanup_translation(text: str) -> str:
    for source, target in TRANSLATION_REPLACEMENTS.items():
        text = text.replace(source, target)
    return normalize_line(text)


def detect_language_from_text(text: str) -> str:
    normalized = normalize_line(text)
    if not normalized:
        return "unknown"

    zh_chars = sum(len(chunk) for chunk in ZH_RE.findall(normalized))
    en_words = len(EN_RE.findall(normalized))
    if zh_chars >= 20 and zh_chars >= en_words:
        return "zh"
    if en_words >= 20 and en_words * 2 >= max(1, zh_chars):
        return "en"
    return "unknown"


def detect_language_from_cues(cues: list[Cue]) -> str:
    sample = " ".join(cue.text for cue in cues[:160])
    return detect_language_from_text(sample)


def infer_language_from_path(path: Path) -> str | None:
    if path.suffix.lower() not in SUBTITLE_EXTENSIONS:
        return None

    suffix = path.stem.rpartition(".")[2].lower()
    if suffix in ZH_LANGUAGE_SUFFIXES:
        return "zh"
    if suffix in EN_LANGUAGE_SUFFIXES:
        return "en"
    return None


def infer_language_from_candidates(candidates: list[Path]) -> str | None:
    for path in candidates:
        language = infer_language_from_path(path)
        if language == "zh":
            return "zh"
    for path in candidates:
        language = infer_language_from_path(path)
        if language == "en":
            return "en"
    return None


def translation_cache_dir(output_dir: Path) -> Path:
    cache_dir = output_dir / ".transcript-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def translation_cache_path(output_dir: Path, base_name: str) -> Path:
    digest = hashlib.sha1(base_name.encode("utf-8")).hexdigest()
    return translation_cache_dir(output_dir) / f"{digest}.zh.json"


def load_translation_cache(cache_path: Path) -> dict[str, str]:
    if not cache_path.exists():
        return {}
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    if payload.get("version") != CACHE_VERSION:
        return {}
    return payload.get("translations", {})


def save_translation_cache(cache_path: Path, cache: dict[str, str]) -> None:
    payload = {
        "version": CACHE_VERSION,
        "translations": cache,
    }
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def translate_text(text: str) -> str:
    params = urlencode(
        {
            "client": "gtx",
            "sl": "en",
            "tl": "zh-CN",
            "dt": "t",
            "q": text,
        }
    )
    request = Request(f"{TRANSLATE_URL}?{params}", headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=30) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))
    pieces = payload[0] or []
    translated = "".join(piece[0] for piece in pieces if piece and piece[0]).strip()
    return cleanup_translation(translated)


def translate_paragraphs(paragraphs: list[Paragraph], output_dir: Path, base_name: str) -> list[Paragraph]:
    cache_path = translation_cache_path(output_dir=output_dir, base_name=base_name)
    cache = load_translation_cache(cache_path)
    translated: list[Paragraph] = []

    for index, paragraph in enumerate(paragraphs, start=1):
        source_text = paragraph.text
        if source_text in cache:
            translated_text = cleanup_translation(cache[source_text])
        else:
            last_error: Exception | None = None
            for attempt in range(5):
                try:
                    translated_text = translate_text(source_text)
                    cache[source_text] = translated_text
                    save_translation_cache(cache_path, cache)
                    time.sleep(0.35)
                    break
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    time.sleep(1.2 * (attempt + 1))
            else:
                raise RuntimeError(f"Failed to translate paragraph {index}: {last_error}") from last_error

        translated.append(
            Paragraph(
                start_ms=paragraph.start_ms,
                end_ms=paragraph.end_ms,
                text=translated_text,
            )
        )

    return translated


def load_srt(path: Path) -> list[Cue]:
    cues: list[Cue] = []
    blocks = [block.strip() for block in SRT_BREAK_RE.split(path.read_text(encoding="utf-8")) if block.strip()]
    for block in blocks:
        lines = block.splitlines()
        if len(lines) < 2:
            continue
        if "-->" in lines[0]:
            index = len(cues) + 1
            start_raw, end_raw = lines[0].split(" --> ")
            text_lines = lines[1:]
        elif len(lines) >= 3 and "-->" in lines[1]:
            index = int(lines[0]) if lines[0].isdigit() else len(cues) + 1
            start_raw, end_raw = lines[1].split(" --> ")
            text_lines = lines[2:]
        else:
            continue
        text = normalize_line(" ".join(text_lines))
        if not text:
            continue
        cues.append(Cue(index=index, start_ms=parse_timestamp(start_raw), end_ms=parse_timestamp(end_raw), text=text))
    return cues


def dedupe_lines(lines: Iterable[str]) -> list[str]:
    cleaned: list[str] = []
    previous = ""
    for raw in lines:
        line = normalize_line(raw)
        if not line:
            continue
        if line == previous:
            continue
        cleaned.append(line)
        previous = line
    return cleaned


def cues_to_raw_lines(cues: Iterable[Cue]) -> list[str]:
    return dedupe_lines(cue.text for cue in cues)


def build_paragraphs(cues: list[Cue]) -> list[Paragraph]:
    paragraphs: list[Paragraph] = []
    buffer: list[str] = []
    start_ms = 0
    end_ms = 0
    sentence_count = 0

    def flush() -> None:
        nonlocal buffer, start_ms, end_ms, sentence_count
        text = normalize_line(" ".join(buffer))
        if text:
            paragraphs.append(Paragraph(start_ms=start_ms, end_ms=end_ms, text=text))
        buffer = []
        start_ms = 0
        end_ms = 0
        sentence_count = 0

    for cue in cues:
        if not buffer:
            start_ms = cue.start_ms
        else:
            gap_ms = cue.start_ms - end_ms
            current_text = normalize_line(" ".join(buffer))
            should_flush = (
                gap_ms >= 2000
                or len(current_text) >= 240
                or (sentence_count >= 3 and current_text.endswith(tuple(SENTENCE_END_CHARS)))
            )
            if should_flush:
                flush()
                start_ms = cue.start_ms

        buffer.append(cue.text)
        end_ms = cue.end_ms
        sentence_count += sum(ch in SENTENCE_END_CHARS for ch in cue.text)

    flush()
    return paragraphs


def chunk_sections(paragraphs: list[Paragraph]) -> list[list[Paragraph]]:
    if not paragraphs:
        return []

    sections: list[list[Paragraph]] = []
    current: list[Paragraph] = []
    current_chars = 0
    section_start = paragraphs[0].start_ms

    for paragraph in paragraphs:
        if current:
            duration_ms = paragraph.end_ms - section_start
            if len(current) >= 4 and (current_chars >= 1000 or duration_ms >= 240000):
                sections.append(current)
                current = []
                current_chars = 0
                section_start = paragraph.start_ms

        if not current:
            section_start = paragraph.start_ms
        current.append(paragraph)
        current_chars += len(paragraph.text)

    if current:
        sections.append(current)
    return sections


def split_sentences(text: str) -> list[str]:
    text = normalize_line(text)
    if not text:
        return []

    parts = re.split(r"(?<=[。！？!?；;\.])\s*", text)
    sentences = [part.strip() for part in parts if part.strip()]
    if not sentences:
        sentences = [text]
    return sentences


def extract_tokens(text: str) -> set[str]:
    tokens: set[str] = set()

    for match in EN_RE.findall(text.lower()):
        if match not in STOPWORDS and len(match) > 1:
            tokens.add(match)

    for chunk in ZH_RE.findall(text):
        compact = chunk.strip()
        if len(compact) == 1:
            continue
        if len(compact) <= 4:
            if compact not in STOPWORDS:
                tokens.add(compact)
            continue
        for idx in range(len(compact) - 1):
            token = compact[idx : idx + 2]
            if token not in STOPWORDS:
                tokens.add(token)

    return tokens


def build_summary_points(paragraphs: list[Paragraph], count: int) -> list[str]:
    sentences: list[tuple[int, str, set[str]]] = []
    for para_idx, paragraph in enumerate(paragraphs):
        for sentence in split_sentences(paragraph.text):
            cleaned = sentence.strip(" ，、；：")
            if len(cleaned) < 10:
                continue
            sentences.append((para_idx, cleaned, extract_tokens(cleaned)))

    if not sentences:
        return []

    frequencies: Counter[str] = Counter()
    for _, _, tokens in sentences:
        frequencies.update(tokens)

    scored: list[tuple[float, int, str, set[str]]] = []
    total = len(sentences)
    for idx, (para_idx, sentence, tokens) in enumerate(sentences):
        if not tokens:
            continue
        lexical_score = sum(frequencies[token] for token in tokens) / (len(tokens) ** 0.6)
        position_bonus = 1.0 + (1.0 - idx / total) * 0.35
        scored.append((lexical_score * position_bonus, idx, sentence, tokens))

    scored.sort(key=lambda item: item[0], reverse=True)

    selected: list[tuple[int, str, set[str]]] = []
    for _, idx, sentence, tokens in scored:
        overlap = 0.0
        for _, _, chosen_tokens in selected:
            union = tokens | chosen_tokens
            if not union:
                continue
            overlap = max(overlap, len(tokens & chosen_tokens) / len(union))
        if overlap > 0.72:
            continue
        selected.append((idx, sentence, tokens))
        if len(selected) >= count:
            break

    if len(selected) < min(count, len(scored)):
        chosen_indexes = {idx for idx, _, _ in selected}
        for _, idx, sentence, tokens in scored:
            if idx in chosen_indexes:
                continue
            selected.append((idx, sentence, tokens))
            if len(selected) >= count:
                break

    selected.sort(key=lambda item: item[0])
    bullets: list[str] = []
    for _, sentence, _ in selected[:count]:
        normalized = sentence.strip()
        if len(normalized) > 72:
            for separator in ("。", "；", "：", "，"):
                head = normalized.split(separator)[0].strip()
                if 18 <= len(head) <= 72:
                    normalized = head
                    break
        if len(normalized) > 72:
            normalized = normalized[:69].rstrip("，、；： ") + "…"
        if normalized[-1] not in "。！？!?.":  # keep source-language punctuation
            normalized += "." if detect_language_from_text(normalized) == "en" else "。"
        bullets.append(normalized)
    return bullets


def write_text(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_raw_txt(path: Path, lines: list[str]) -> None:
    write_text(path, lines)


def write_reading_md(
    path: Path,
    title: str,
    source_path: Path,
    paragraphs: list[Paragraph],
    language: str,
    translated_from: str | None = None,
) -> None:
    sections = chunk_sections(paragraphs)
    if language == "en":
        lines = [
            f"# {title} Reading Draft",
            "",
            "This reading draft is automatically assembled from subtitles or transcript output and merged into paragraphs for easier reading.",
            "",
            f"- Source: `{source_path.name}`",
            f"- Generated: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`",
            f"- Paragraphs: `{len(paragraphs)}`",
            "",
        ]
    else:
        description = "这是一份自动整理的阅读版文本，基于视频转写或原始字幕生成，重点是把碎片化内容合并成更适合通读的段落。"
        if translated_from == "en":
            description = "这是一份根据英文原文自动翻译并整理的中文版阅读稿，便于快速通读主线内容。"
        lines = [
            f"# {title} 阅读整理稿",
            "",
            description,
            "",
            f"- Source: `{source_path.name}`",
            f"- Generated: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`",
            f"- Paragraphs: `{len(paragraphs)}`",
            "",
        ]

    for section_index, section in enumerate(sections, start=1):
        start = format_timestamp(section[0].start_ms)
        end = format_timestamp(section[-1].end_ms)
        heading = (
            f"## Section {section_index} ({start} - {end})"
            if language == "en"
            else f"## 第 {section_index} 部分（{start} - {end}）"
        )
        lines.extend([heading, ""])
        for paragraph in section:
            lines.extend([paragraph.text, ""])

    write_text(path, lines)


def write_summary_md(
    path: Path,
    title: str,
    source_path: Path,
    bullets: list[str],
    language: str,
    translated_from: str | None = None,
) -> None:
    if language == "en":
        lines = [
            f"# {title} Minimal Summary",
            "",
            "This is a compact auto-generated summary for a fast review of the main thread.",
            "",
            f"- Source: `{source_path.name}`",
            f"- Generated: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`",
            "",
        ]
    else:
        description = "这是一份自动生成的极简摘要，适合快速回看视频主线。"
        if translated_from == "en":
            description = "这是一份根据英文原文自动翻译并压缩得到的中文摘要，适合快速回看主线。"
        lines = [
            f"# {title} 极简摘要稿",
            "",
            description,
            "",
            f"- Source: `{source_path.name}`",
            f"- Generated: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`",
            "",
        ]
    for idx, bullet in enumerate(bullets, start=1):
        lines.append(f"{idx}. {bullet}")
        lines.append("")
    write_text(path, lines)


def run_command(command: list[str]) -> None:
    subprocess.run(command, check=True)


def whisper_available(python_executable: str) -> bool:
    result = subprocess.run(
        [python_executable, "-c", "import whisper; print('ok')"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "ok"


def ensure_whisper_python(bootstrap: bool) -> str:
    env_python = os.environ.get("AIWRITING_WHISPER_PYTHON")
    candidates = [
        env_python,
        sys.executable,
        "/tmp/yt_transcribe_env/bin/python",
        "/tmp/aiwriting_whisper_venv/bin/python",
    ]

    for candidate in candidates:
        if candidate and Path(candidate).exists() and whisper_available(candidate):
            return candidate

    if not bootstrap:
        raise RuntimeError(
            "Whisper runtime not found. Set AIWRITING_WHISPER_PYTHON, use an existing env, or rerun with --bootstrap-whisper."
        )

    venv_path = Path("/tmp/aiwriting_whisper_venv")
    if not venv_path.exists():
        run_command([sys.executable, "-m", "venv", str(venv_path)])

    python_executable = str(venv_path / "bin" / "python")
    run_command([python_executable, "-m", "pip", "install", "-U", "pip", "setuptools", "wheel", "openai-whisper"])
    return python_executable


def transcribe_video_to_cues(video_path: Path, model_name: str, bootstrap: bool) -> list[Cue]:
    whisper_python = ensure_whisper_python(bootstrap=bootstrap)
    print(f"Transcribing video with Whisper: {video_path.name} (model={model_name})", flush=True)

    with tempfile.TemporaryDirectory(prefix="aiwriting_whisper_") as temp_dir:
        run_command(
            [
                whisper_python,
                "-m",
                "whisper",
                str(video_path),
                "--model",
                model_name,
                "--task",
                "transcribe",
                "--fp16",
                "False",
                "--output_format",
                "srt",
                "--output_dir",
                temp_dir,
            ]
        )
        srt_path = Path(temp_dir) / f"{video_path.stem}.srt"
        if not srt_path.exists():
            raise RuntimeError(f"Whisper finished but did not produce expected srt file: {srt_path}")
        return load_srt(srt_path)


def process_input(input_path: Path, whisper_model: str, bootstrap_whisper: bool) -> list[Cue]:
    suffix = input_path.suffix.lower()
    if suffix in SUBTITLE_EXTENSIONS:
        return load_srt(input_path)
    if suffix in VIDEO_EXTENSIONS:
        return transcribe_video_to_cues(input_path, model_name=whisper_model, bootstrap=bootstrap_whisper)
    raise ValueError(f"Unsupported input type: {input_path.suffix}")


def canonical_base_name(path: Path) -> str:
    stem = path.stem
    if path.suffix.lower() not in SUBTITLE_EXTENSIONS:
        return stem

    prefix, dot, maybe_lang = stem.rpartition(".")
    if dot and maybe_lang.lower() in LANGUAGE_SUFFIXES:
        return prefix
    return stem


def is_supported_source(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS.union(SUBTITLE_EXTENSIONS)


def source_priority(path: Path) -> tuple[int, int, str]:
    suffix = path.suffix.lower()
    if suffix in SUBTITLE_EXTENSIONS:
        language = path.stem.rpartition(".")[2].lower()
        language_order = {
            "zh-hans": 0,
            "zh-cn": 1,
            "zh": 2,
            "zh-hant": 3,
            "zh-tw": 4,
            "en": 5,
            "en-orig": 6,
        }
        return (0, language_order.get(language, 50), path.name.lower())
    return (1, 0, path.name.lower())


def translated_output_paths(output_dir: Path, base_name: str) -> tuple[Path, Path]:
    return (
        output_dir / f"{base_name} 中文阅读整理稿.md",
        output_dir / f"{base_name} 中文极简摘要稿.md",
    )


def bundle_status(output_dir: Path, base_name: str, candidates: list[Path]) -> BundleStatus:
    raw_exists = (output_dir / f"{base_name}.txt").exists()
    raw_txt_path = output_dir / f"{base_name}.txt"

    reading_names = [
        f"{base_name} 阅读整理稿.md",
        f"{base_name} 阅读版.md",
        f"{base_name} 整理版.md",
    ]
    summary_names = [
        f"{base_name} 极简摘要稿.md",
        f"{base_name} 摘要版.md",
        f"{base_name} 10条摘要.md",
    ]
    reading_exists = any((output_dir / name).exists() for name in reading_names)
    summary_exists = any((output_dir / name).exists() for name in summary_names)
    zh_reading_path, zh_summary_path = translated_output_paths(output_dir=output_dir, base_name=base_name)

    language_hint = infer_language_from_candidates(candidates)
    if language_hint is None and raw_exists:
        sample = raw_txt_path.read_text(encoding="utf-8")[:4000]
        language_hint = detect_language_from_text(sample)

    return BundleStatus(
        raw_exists=raw_exists,
        reading_exists=reading_exists,
        summary_exists=summary_exists,
        zh_reading_exists=zh_reading_path.exists(),
        zh_summary_exists=zh_summary_path.exists(),
        needs_zh_extras=language_hint == "en",
    )


def build_source_groups(directory: Path, output_dir: Path) -> list[SourceGroup]:
    grouped: dict[str, list[Path]] = {}
    for path in sorted(directory.iterdir()):
        if path.name.startswith(".") or not is_supported_source(path):
            continue
        grouped.setdefault(canonical_base_name(path), []).append(path)

    groups: list[SourceGroup] = []
    for base_name, candidates in sorted(grouped.items()):
        source_path = min(candidates, key=source_priority)
        groups.append(
            SourceGroup(
                base_name=base_name,
                source_path=source_path,
                status=bundle_status(output_dir=output_dir, base_name=base_name, candidates=candidates),
                language_hint=infer_language_from_candidates(candidates),
            )
        )
    return groups


def output_paths(output_dir: Path, base_name: str) -> tuple[Path, Path, Path]:
    return (
        output_dir / f"{base_name}.txt",
        output_dir / f"{base_name} 阅读整理稿.md",
        output_dir / f"{base_name} 极简摘要稿.md",
    )


def generate_bundle(
    input_path: Path,
    output_dir: Path,
    base_name: str,
    whisper_model: str,
    bootstrap_whisper: bool,
    summary_points: int,
    status: BundleStatus | None = None,
    language_hint: str | None = None,
) -> None:
    status = status or BundleStatus(raw_exists=False, reading_exists=False, summary_exists=False)
    if status.complete:
        print(f"Skipping complete bundle: {base_name}", flush=True)
        return

    print(f"[1/4] Loading source: {input_path}", flush=True)
    cues = process_input(input_path, whisper_model=whisper_model, bootstrap_whisper=bootstrap_whisper)
    source_language = language_hint or infer_language_from_path(input_path) or detect_language_from_cues(cues)

    print(f"[2/4] Building cleaned raw transcript for {base_name}", flush=True)
    raw_lines = cues_to_raw_lines(cues)
    paragraphs = build_paragraphs(cues)
    summary_bullets = build_summary_points(paragraphs, count=summary_points)
    needs_zh_extras = status.needs_zh_extras or source_language == "en"

    raw_txt_path, reading_md_path, summary_md_path = output_paths(output_dir=output_dir, base_name=base_name)
    zh_reading_md_path, zh_summary_md_path = translated_output_paths(output_dir=output_dir, base_name=base_name)

    print(f"[3/4] Writing outputs for {base_name}", flush=True)
    if not status.raw_exists:
        write_raw_txt(raw_txt_path, raw_lines)
        print(raw_txt_path, flush=True)
    if not status.reading_exists:
        write_reading_md(
            reading_md_path,
            title=base_name,
            source_path=input_path,
            paragraphs=paragraphs,
            language=source_language,
        )
        print(reading_md_path, flush=True)
    if not status.summary_exists:
        write_summary_md(
            summary_md_path,
            title=base_name,
            source_path=input_path,
            bullets=summary_bullets,
            language=source_language,
        )
        print(summary_md_path, flush=True)
    if needs_zh_extras and (not status.zh_reading_exists or not status.zh_summary_exists):
        print(f"Translating English source into Chinese companion outputs for {base_name}", flush=True)
        translated_paragraphs = translate_paragraphs(paragraphs=paragraphs, output_dir=output_dir, base_name=base_name)
        translated_summary_bullets = build_summary_points(translated_paragraphs, count=summary_points)
    if needs_zh_extras and not status.zh_reading_exists:
        write_reading_md(
            zh_reading_md_path,
            title=base_name,
            source_path=input_path,
            paragraphs=translated_paragraphs,
            language="zh",
            translated_from="en",
        )
        print(zh_reading_md_path, flush=True)
    if needs_zh_extras and not status.zh_summary_exists:
        write_summary_md(
            zh_summary_md_path,
            title=base_name,
            source_path=input_path,
            bullets=translated_summary_bullets,
            language="zh",
            translated_from="en",
        )
        print(zh_summary_md_path, flush=True)

    print("[4/4] Done", flush=True)


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    default_output_dir = input_path if input_path.is_dir() else input_path.parent
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else default_output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.batch or input_path.is_dir():
        if not input_path.is_dir():
            raise ValueError("--batch requires a directory input")

        groups = build_source_groups(directory=input_path, output_dir=output_dir)
        pending = [group for group in groups if not group.status.complete]
        print(f"Found {len(groups)} candidate source groups, {len(pending)} pending", flush=True)
        for index, group in enumerate(pending, start=1):
            print(
                f"=== [{index}/{len(pending)}] {group.base_name} "
                f"(source: {group.source_path.name}) ===",
                flush=True,
            )
            generate_bundle(
                input_path=group.source_path,
                output_dir=output_dir,
                base_name=group.base_name,
                whisper_model=args.whisper_model,
                bootstrap_whisper=args.bootstrap_whisper,
                summary_points=args.summary_points,
                status=group.status,
                language_hint=group.language_hint,
            )
        if not pending:
            print("Nothing to do.", flush=True)
        return 0

    generate_bundle(
        input_path=input_path,
        output_dir=output_dir,
        base_name=canonical_base_name(input_path),
        whisper_model=args.whisper_model,
        bootstrap_whisper=args.bootstrap_whisper,
        summary_points=args.summary_points,
        language_hint=infer_language_from_path(input_path),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
