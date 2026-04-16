from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from make_bilingual_reading_docx import bilingual_docx_output_path, write_bilingual_docx


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".m4v", ".webm", ".avi"}
AUDIO_EXTENSIONS = {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav", ".webm"}
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
SENTENCE_SPLIT_RE = re.compile(r'(?<=[。！？!?])\s+|(?<=[.])\s+(?=(?:["“”‘’\']?[A-Z]))')
CACHE_VERSION = 2

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
    source_exists: bool
    reading_exists: bool
    zh_reading_exists: bool = False
    needs_zh_extras: bool = False

    @property
    def complete(self) -> bool:
        base_complete = self.source_exists and self.reading_exists
        if not self.needs_zh_extras:
            return base_complete
        return base_complete and self.zh_reading_exists


@dataclass
class SourceGroup:
    base_name: str
    source_path: Path
    status: BundleStatus
    language_hint: str | None = None


@dataclass
class ProcessingResult:
    cues: list[Cue]
    source_path: Path
    generated_subtitle_path: Path | None = None
    reference_cues: list[Cue] | None = None


def parse_args() -> argparse.Namespace:
    examples = """Examples:
  python3 make_transcript_bundle.py "/path/to/video.mp4"
  python3 make_transcript_bundle.py "/path/to/audio.mp3"
  python3 make_transcript_bundle.py "/path/to/subtitle.srt"
  python3 make_transcript_bundle.py "/path/to/video.mp4" --output-dir "/path/to/output"
  python3 make_transcript_bundle.py "/path/to/dir" --batch
  python3 make_transcript_bundle.py "/path/to/dir" --batch --source-kind audio
  python3 make_transcript_bundle.py "/path/to/file.srt" --bilingual-docx
"""
    parser = argparse.ArgumentParser(
        description="Generate reading markdown from a video, audio, subtitle, or source directory.",
        epilog=examples,
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("input", help="Path to a video file, audio file, subtitle file, or directory")
    parser.add_argument(
        "--output-dir",
        help="Directory for generated files. Defaults to the input file's directory.",
    )
    parser.add_argument(
        "--whisper-model",
        default="small",
        help="Whisper model name for video/audio transcription. Defaults to 'small'.",
    )
    parser.add_argument(
        "--bootstrap-whisper",
        action="store_true",
        help="Create a temporary venv and install openai-whisper if no Whisper runtime is found.",
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Treat the input path as a directory and batch-process unhandled files inside it.",
    )
    parser.add_argument(
        "--source-kind",
        choices=("auto", "subtitle", "audio", "video"),
        default="auto",
        help=(
            "Limit which source files are considered. "
            "For directories, 'auto' runs a subtitle-first batch pass and then offers media fallback as stage 2. "
            "Use 'audio' or 'video' to force media-only batch runs."
        ),
    )
    parser.add_argument(
        "--bilingual-docx",
        action="store_true",
        help="For English sources with Chinese companion markdown, also write a section-aligned bilingual .docx.",
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


def request_translation(text: str) -> str:
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


def split_translation_chunk(text: str, max_chars: int) -> list[str]:
    words = text.split()
    if not words:
        return [text] if text else []

    chunks: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = word
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def split_for_translation(text: str, max_chars: int = 240) -> list[str]:
    normalized = normalize_line(text)
    if not normalized:
        return []

    sentences = [part.strip() for part in SENTENCE_SPLIT_RE.split(normalized) if part and part.strip()]
    if not sentences:
        sentences = [normalized]

    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = sentence if not current else f"{current} {sentence}"
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = sentence
        else:
            current = candidate

    if current:
        chunks.append(current)

    final_chunks: list[str] = []
    for chunk in chunks:
        if len(chunk) > max_chars:
            final_chunks.extend(split_translation_chunk(chunk, max_chars=max_chars))
        else:
            final_chunks.append(chunk)
    return final_chunks


def translate_text(text: str, max_chars: int = 240) -> str:
    chunks = split_for_translation(text, max_chars=max_chars)
    if not chunks:
        return ""
    if len(chunks) == 1:
        translated = request_translation(chunks[0])
        if detect_language_from_text(chunks[0]) == "en" and detect_language_from_text(translated) == "en" and len(chunks[0]) > 120:
            finer_chunks = split_for_translation(chunks[0], max_chars=120)
            if len(finer_chunks) > 1:
                return cleanup_translation(" ".join(request_translation(chunk) for chunk in finer_chunks))
        return translated
    return cleanup_translation(" ".join(request_translation(chunk) for chunk in chunks))


def translate_paragraphs(paragraphs: list[Paragraph], output_dir: Path, base_name: str) -> list[Paragraph]:
    cache_path = translation_cache_path(output_dir=output_dir, base_name=base_name)
    cache = load_translation_cache(cache_path)
    translated: list[Paragraph] = []
    total = len(paragraphs)

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
        if index == 1 or index == total or index % 25 == 0:
            print(f"  [zh] {index}/{total}", flush=True)

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


def ends_with_sentence_boundary(text: str) -> bool:
    return normalize_line(text).endswith(tuple(SENTENCE_END_CHARS))


def split_completed_sentences(text: str) -> tuple[list[str], str]:
    normalized = normalize_line(text)
    if not normalized:
        return [], ""

    parts = [part.strip() for part in SENTENCE_SPLIT_RE.split(normalized) if part and part.strip()]
    if not parts:
        return [], normalized

    if ends_with_sentence_boundary(normalized):
        return parts, ""
    return parts[:-1], parts[-1]


def build_paragraphs(cues: list[Cue]) -> list[Paragraph]:
    if not cues:
        return []

    timestamp_free_source = all(cue.start_ms == 0 and cue.end_ms == 0 for cue in cues)
    sentence_units: list[Paragraph] = []
    pending_text = ""
    sentence_start_ms = 0
    last_end_ms = 0
    long_gap_ms = 0 if timestamp_free_source else 2400
    absolute_sentence_chars = 680 if timestamp_free_source else 1800

    def flush_sentence(text: str, end_ms: int) -> None:
        nonlocal sentence_start_ms
        text = normalize_line(text)
        if text:
            sentence_units.append(Paragraph(start_ms=sentence_start_ms, end_ms=end_ms, text=text))
        sentence_start_ms = 0

    for cue in cues:
        if not pending_text:
            sentence_start_ms = cue.start_ms
        else:
            gap_ms = cue.start_ms - last_end_ms
            if gap_ms >= long_gap_ms and len(normalize_line(pending_text)) >= 140:
                flush_sentence(pending_text, last_end_ms)
                pending_text = ""
                sentence_start_ms = cue.start_ms

        pending_text = normalize_line(" ".join(part for part in (pending_text, cue.text) if part))
        completed_sentences, pending_text = split_completed_sentences(pending_text)
        for sentence in completed_sentences:
            flush_sentence(sentence, cue.end_ms)
            sentence_start_ms = cue.end_ms

        if len(normalize_line(pending_text)) >= absolute_sentence_chars:
            flush_sentence(pending_text, cue.end_ms)
            pending_text = ""

        last_end_ms = cue.end_ms

    if pending_text:
        flush_sentence(pending_text, last_end_ms)

    paragraphs: list[Paragraph] = []
    paragraph_buffer: list[Paragraph] = []
    target_chars = 320 if timestamp_free_source else 420
    preferred_max_chars = 520 if timestamp_free_source else 760
    max_sentences = 3 if timestamp_free_source else 4

    def flush_paragraph() -> None:
        nonlocal paragraph_buffer
        if not paragraph_buffer:
            return
        text = normalize_line(" ".join(item.text for item in paragraph_buffer))
        paragraphs.append(
            Paragraph(
                start_ms=paragraph_buffer[0].start_ms,
                end_ms=paragraph_buffer[-1].end_ms,
                text=text,
            )
        )
        paragraph_buffer = []

    for sentence in sentence_units:
        candidate_buffer = paragraph_buffer + [sentence]
        candidate_len = len(normalize_line(" ".join(item.text for item in candidate_buffer)))
        if paragraph_buffer and (candidate_len > preferred_max_chars or len(candidate_buffer) > max_sentences):
            flush_paragraph()
        paragraph_buffer.append(sentence)
        current_len = len(normalize_line(" ".join(item.text for item in paragraph_buffer)))
        if current_len >= preferred_max_chars:
            flush_paragraph()
        elif len(paragraph_buffer) >= 2 and current_len >= target_chars:
            flush_paragraph()

    flush_paragraph()
    return paragraphs


def paragraph_weights(paragraphs: list[Paragraph]) -> list[int]:
    return [max(len(normalize_line(paragraph.text)), 1) for paragraph in paragraphs]


def cues_as_paragraphs(cues: list[Cue]) -> list[Paragraph]:
    return [Paragraph(start_ms=cue.start_ms, end_ms=cue.end_ms, text=cue.text) for cue in cues]


def reanchor_paragraph_times(paragraphs: list[Paragraph], reference_units: list[Paragraph]) -> list[Paragraph]:
    if not paragraphs or not reference_units:
        return paragraphs
    if all(paragraph.start_ms == 0 and paragraph.end_ms == 0 for paragraph in reference_units):
        return paragraphs

    reference_weights = paragraph_weights(reference_units)
    paragraph_weights_local = paragraph_weights(paragraphs)
    reference_breakpoints: list[int] = []
    running_total = 0
    for weight in reference_weights:
        running_total += weight
        reference_breakpoints.append(running_total)

    total_reference = reference_breakpoints[-1]
    total_target = sum(paragraph_weights_local)
    consumed = 0
    anchored: list[Paragraph] = []

    for paragraph, weight in zip(paragraphs, paragraph_weights_local):
        start_position = max(1, int(consumed / max(total_target, 1) * total_reference))
        end_position = max(1, int((consumed + weight) / max(total_target, 1) * total_reference))
        start_index = min(len(reference_units) - 1, bisect.bisect_left(reference_breakpoints, start_position))
        end_index = min(len(reference_units) - 1, bisect.bisect_left(reference_breakpoints, end_position))
        start_ms = reference_units[start_index].start_ms
        end_ms = reference_units[end_index].end_ms
        if end_ms < start_ms:
            end_ms = max(start_ms, reference_units[start_index].end_ms)
        anchored.append(
            Paragraph(
                start_ms=start_ms,
                end_ms=end_ms,
                text=paragraph.text,
            )
        )
        consumed += weight

    return anchored


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


def apply_section_lengths(paragraphs: list[Paragraph], section_lengths: list[int] | None) -> list[list[Paragraph]]:
    if not paragraphs:
        return []
    if not section_lengths:
        return chunk_sections(paragraphs)

    sections: list[list[Paragraph]] = []
    cursor = 0
    total = len(paragraphs)

    for length in section_lengths:
        if cursor >= total:
            break
        if length <= 0:
            continue
        next_cursor = min(total, cursor + length)
        sections.append(paragraphs[cursor:next_cursor])
        cursor = next_cursor

    if cursor < total:
        if sections:
            sections[-1].extend(paragraphs[cursor:])
        else:
            sections.append(paragraphs[cursor:])

    return [section for section in sections if section]


def write_text(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_reading_md(
    path: Path,
    title: str,
    source_path: Path,
    paragraphs: list[Paragraph],
    language: str,
    translated_from: str | None = None,
    section_lengths: list[int] | None = None,
) -> None:
    sections = apply_section_lengths(paragraphs, section_lengths)
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
        if section[0].start_ms == 0 and section[-1].end_ms == 0:
            heading = f"## Section {section_index}" if language == "en" else f"## 第 {section_index} 部分"
        else:
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


def reading_md_source_name(path: Path) -> str | None:
    if not path.exists():
        return None

    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None

    match = re.search(r"^- Source: `([^`]+)`\s*$", content, flags=re.MULTILINE)
    if not match:
        return None
    return match.group(1).strip()


def reading_md_timestamp_ranges(path: Path) -> list[tuple[str, str]]:
    if not path.exists():
        return []

    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return []

    return re.findall(r"^## .+?(\d{2}:\d{2}:\d{2})\s*-\s*(\d{2}:\d{2}:\d{2}).*$", content, flags=re.MULTILINE)


def reading_md_body_paragraphs(path: Path) -> list[str]:
    if not path.exists():
        return []

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    paragraphs: list[str] = []
    buffer: list[str] = []
    in_section = False
    for line in lines:
        if line.startswith("## "):
            if buffer:
                paragraph = normalize_line(" ".join(buffer))
                if paragraph:
                    paragraphs.append(paragraph)
                buffer = []
            in_section = True
            continue
        if not in_section:
            continue
        if not line.strip():
            if buffer:
                paragraph = normalize_line(" ".join(buffer))
                if paragraph:
                    paragraphs.append(paragraph)
                buffer = []
            continue
        buffer.append(line.strip())

    if buffer:
        paragraph = normalize_line(" ".join(buffer))
        if paragraph:
            paragraphs.append(paragraph)
    return paragraphs


def translated_md_has_untranslated_paragraphs(path: Path) -> bool:
    for paragraph in reading_md_body_paragraphs(path):
        if detect_language_from_text(paragraph) == "en":
            return True
    return False


def bilingual_sections_need_refresh(english_path: Path, chinese_path: Path) -> bool:
    if not english_path.exists() or not chinese_path.exists():
        return False

    english_ranges = reading_md_timestamp_ranges(english_path)
    chinese_ranges = reading_md_timestamp_ranges(chinese_path)
    if not english_ranges or not chinese_ranges:
        return False
    return english_ranges != chinese_ranges


def reading_md_needs_refresh(path: Path, subtitle_exists: bool) -> bool:
    if not subtitle_exists or not path.exists():
        return False

    source_name = reading_md_source_name(path)
    if source_name is None:
        return False
    return Path(source_name).suffix.lower() == ".txt"


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


def generated_subtitle_path(output_dir: Path, base_name: str) -> Path:
    return output_dir / f"{base_name}.srt"


def transcribe_media_to_cues(
    media_path: Path,
    model_name: str,
    bootstrap: bool,
    output_dir: Path,
    base_name: str,
) -> ProcessingResult:
    whisper_python = ensure_whisper_python(bootstrap=bootstrap)
    media_kind = "audio" if media_path.suffix.lower() in AUDIO_EXTENSIONS else "video"
    print(f"Transcribing {media_kind} with Whisper: {media_path.name} (model={model_name})", flush=True)

    with tempfile.TemporaryDirectory(prefix="aiwriting_whisper_") as temp_dir:
        run_command(
            [
                whisper_python,
                "-m",
                "whisper",
                str(media_path),
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
        srt_path = Path(temp_dir) / f"{media_path.stem}.srt"
        if not srt_path.exists():
            raise RuntimeError(f"Whisper finished but did not produce expected srt file: {srt_path}")
        persisted_srt_path = generated_subtitle_path(output_dir=output_dir, base_name=base_name)
        shutil.copy2(srt_path, persisted_srt_path)
        return ProcessingResult(
            cues=load_srt(persisted_srt_path),
            source_path=persisted_srt_path,
            generated_subtitle_path=persisted_srt_path,
        )


def process_input(
    input_path: Path,
    whisper_model: str,
    bootstrap_whisper: bool,
    output_dir: Path,
    base_name: str,
) -> ProcessingResult:
    suffix = input_path.suffix.lower()
    if suffix in SUBTITLE_EXTENSIONS:
        return ProcessingResult(cues=load_srt(input_path), source_path=input_path)
    if suffix in VIDEO_EXTENSIONS or suffix in AUDIO_EXTENSIONS:
        return transcribe_media_to_cues(
            input_path,
            model_name=whisper_model,
            bootstrap=bootstrap_whisper,
            output_dir=output_dir,
            base_name=base_name,
        )
    raise ValueError(f"Unsupported input type: {input_path.suffix}")


def allowed_extensions(source_kind: str) -> set[str]:
    if source_kind == "subtitle":
        return SUBTITLE_EXTENSIONS
    if source_kind == "audio":
        return AUDIO_EXTENSIONS
    if source_kind == "video":
        return VIDEO_EXTENSIONS
    return VIDEO_EXTENSIONS.union(AUDIO_EXTENSIONS, SUBTITLE_EXTENSIONS)


def collect_directory_candidates(directory: Path) -> dict[str, list[Path]]:
    grouped: dict[str, list[Path]] = {}
    for path in sorted(directory.iterdir()):
        if path.name.startswith(".") or not is_supported_source(path, source_kind="auto"):
            continue
        grouped.setdefault(canonical_base_name(path), []).append(path)
    return grouped


def select_source_path(candidates: list[Path], source_kind: str) -> Path | None:
    filtered = [candidate for candidate in candidates if candidate.suffix.lower() in allowed_extensions(source_kind)]
    if not filtered:
        return None
    return min(filtered, key=source_priority)


def canonical_base_name(path: Path) -> str:
    stem = path.stem.strip()
    if path.suffix.lower() not in SUBTITLE_EXTENSIONS:
        return stem

    prefix, dot, maybe_lang = stem.rpartition(".")
    if dot and maybe_lang.lower() in LANGUAGE_SUFFIXES:
        return prefix.strip()
    return stem


def is_supported_source(path: Path, source_kind: str = "auto") -> bool:
    return path.is_file() and path.suffix.lower() in allowed_extensions(source_kind)


def source_priority(path: Path) -> tuple[int, int, str]:
    suffix = path.suffix.lower()
    if suffix in SUBTITLE_EXTENSIONS:
        language = path.stem.rpartition(".")[2].lower()
        language_order = {
            "en": 0,
            "en-orig": 1,
            "zh-hans": 2,
            "zh-cn": 3,
            "zh": 4,
            "zh-hant": 5,
            "zh-tw": 6,
        }
        return (0, language_order.get(language, 50), path.name.lower())
    if suffix in AUDIO_EXTENSIONS:
        return (1, 0, path.name.lower())
    return (2, 0, path.name.lower())


def translated_output_path(output_dir: Path, base_name: str) -> Path:
    return output_dir / f"{base_name} 中文阅读整理稿.md"


def bilingual_docx_path(output_dir: Path, base_name: str) -> Path:
    english_md = output_dir / f"{base_name} 阅读整理稿.md"
    return bilingual_docx_output_path(english_md)


def bilingual_docx_complete(output_dir: Path, base_name: str, needs_zh_extras: bool) -> bool:
    if not needs_zh_extras:
        return True
    return bilingual_docx_path(output_dir=output_dir, base_name=base_name).exists()


def ensure_bilingual_docx(output_dir: Path, base_name: str) -> Path | None:
    english_md = output_dir / f"{base_name} 阅读整理稿.md"
    chinese_md = translated_output_path(output_dir=output_dir, base_name=base_name)
    if not english_md.exists() or not chinese_md.exists():
        return None
    output_path = bilingual_docx_path(output_dir=output_dir, base_name=base_name)
    return write_bilingual_docx(english_md=english_md, chinese_md=chinese_md, output_path=output_path)


def bundle_status(output_dir: Path, base_name: str, candidates: list[Path]) -> BundleStatus:
    subtitle_exists = generated_subtitle_path(output_dir=output_dir, base_name=base_name).exists() or any(
        candidate.suffix.lower() in SUBTITLE_EXTENSIONS for candidate in candidates
    )

    reading_paths = [output_dir / name for name in (
        f"{base_name} 阅读整理稿.md",
        f"{base_name} 阅读版.md",
        f"{base_name} 整理版.md",
    )]
    existing_reading_paths = [path for path in reading_paths if path.exists()]
    reading_exists = bool(existing_reading_paths) and not any(
        reading_md_needs_refresh(path, subtitle_exists=subtitle_exists)
        for path in existing_reading_paths
    )
    reading_path = existing_reading_paths[0] if existing_reading_paths else reading_paths[0]
    zh_reading_path = translated_output_path(output_dir=output_dir, base_name=base_name)
    zh_reading_exists = zh_reading_path.exists() and not reading_md_needs_refresh(
        zh_reading_path,
        subtitle_exists=subtitle_exists,
    )

    language_hint = infer_language_from_candidates(candidates)
    if language_hint is None:
        subtitle_candidates = [candidate for candidate in candidates if candidate.suffix.lower() in SUBTITLE_EXTENSIONS]
        generated_subtitle = generated_subtitle_path(output_dir=output_dir, base_name=base_name)
        if generated_subtitle.exists():
            subtitle_candidates.append(generated_subtitle)
        for subtitle_candidate in subtitle_candidates:
            language_hint = infer_language_from_path(subtitle_candidate)
            if language_hint:
                break
            try:
                language_hint = detect_language_from_cues(load_srt(subtitle_candidate))
            except Exception:  # noqa: BLE001
                language_hint = None
            if language_hint and language_hint != "unknown":
                break
        if language_hint == "unknown":
            language_hint = None

    if language_hint == "en" and reading_exists and zh_reading_exists:
        if bilingual_sections_need_refresh(reading_path, zh_reading_path):
            zh_reading_exists = False
        elif translated_md_has_untranslated_paragraphs(zh_reading_path):
            zh_reading_exists = False

    return BundleStatus(
        source_exists=subtitle_exists,
        reading_exists=reading_exists,
        zh_reading_exists=zh_reading_exists,
        needs_zh_extras=language_hint == "en",
    )


def build_source_groups(directory: Path, output_dir: Path, source_kind: str = "auto") -> list[SourceGroup]:
    groups: list[SourceGroup] = []
    for base_name, candidates in sorted(collect_directory_candidates(directory).items()):
        source_path = select_source_path(candidates, source_kind)
        if source_path is None:
            continue
        groups.append(
            SourceGroup(
                base_name=base_name,
                source_path=source_path,
                status=bundle_status(output_dir=output_dir, base_name=base_name, candidates=candidates),
                language_hint=infer_language_from_candidates(candidates),
            )
        )
    return groups


def build_media_fallback_groups(directory: Path, output_dir: Path) -> list[SourceGroup]:
    groups: list[SourceGroup] = []
    media_extensions = AUDIO_EXTENSIONS.union(VIDEO_EXTENSIONS)
    for base_name, candidates in sorted(collect_directory_candidates(directory).items()):
        media_candidates = [candidate for candidate in candidates if candidate.suffix.lower() in media_extensions]
        if not media_candidates:
            continue
        subtitle_exists = generated_subtitle_path(output_dir=output_dir, base_name=base_name).exists() or any(
            candidate.suffix.lower() in SUBTITLE_EXTENSIONS for candidate in candidates
        )
        if subtitle_exists:
            continue
        groups.append(
            SourceGroup(
                base_name=base_name,
                source_path=min(media_candidates, key=source_priority),
                status=bundle_status(output_dir=output_dir, base_name=base_name, candidates=candidates),
                language_hint=infer_language_from_candidates(candidates),
            )
        )
    return groups


def prompt_media_fallback(groups: list[SourceGroup]) -> bool:
    if not groups:
        return False

    print(
        f"Stage 2 available: found {len(groups)} media-only source group(s) with no subtitle yet.",
        flush=True,
    )
    for group in groups[:10]:
        print(f"  - {group.base_name} ({group.source_path.name})", flush=True)
    if len(groups) > 10:
        print(f"  ... and {len(groups) - 10} more", flush=True)

    if not sys.stdin.isatty():
        print(
            "Skipping stage 2 in non-interactive mode. "
            "Re-run with --source-kind audio or --source-kind video to transcribe media explicitly.",
            flush=True,
        )
        return False

    try:
        answer = input("Stage 2 will transcribe media and generate new .srt files. Continue? [y/N] ").strip().lower()
    except EOFError:
        return False
    return answer in {"y", "yes"}


def output_paths(output_dir: Path, base_name: str) -> tuple[Path, Path]:
    return (
        generated_subtitle_path(output_dir=output_dir, base_name=base_name),
        output_dir / f"{base_name} 阅读整理稿.md",
    )


def generate_bundle(
    input_path: Path,
    output_dir: Path,
    base_name: str,
    whisper_model: str,
    bootstrap_whisper: bool,
    bilingual_docx: bool = False,
    status: BundleStatus | None = None,
    language_hint: str | None = None,
) -> None:
    status = status or BundleStatus(source_exists=False, reading_exists=False)
    if status.complete and bilingual_docx and status.needs_zh_extras:
        output_path = ensure_bilingual_docx(output_dir=output_dir, base_name=base_name)
        if output_path is not None:
            print(f"Writing bilingual docx for {base_name}", flush=True)
            print(output_path, flush=True)
        print(f"Skipping complete bundle: {base_name}", flush=True)
        return
    if status.complete:
        print(f"Skipping complete bundle: {base_name}", flush=True)
        return

    print(f"[1/4] Loading source: {input_path}", flush=True)
    processing = process_input(
        input_path,
        whisper_model=whisper_model,
        bootstrap_whisper=bootstrap_whisper,
        output_dir=output_dir,
        base_name=base_name,
    )
    if processing.reference_cues is not None and processing.source_path != input_path:
        print(f"[1/4] Using companion subtitle timing: {processing.source_path.name}", flush=True)
    cues = processing.cues
    source_language = language_hint or infer_language_from_path(processing.source_path) or detect_language_from_cues(cues)

    print(f"[2/4] Building reading paragraphs for {base_name}", flush=True)
    paragraphs = build_paragraphs(cues)
    if processing.reference_cues:
        paragraphs = reanchor_paragraph_times(
            paragraphs=paragraphs,
            reference_units=cues_as_paragraphs(processing.reference_cues),
        )
    section_lengths = [len(section) for section in chunk_sections(paragraphs)]
    needs_zh_extras = status.needs_zh_extras or source_language == "en"

    subtitle_path, reading_md_path = output_paths(output_dir=output_dir, base_name=base_name)
    zh_reading_md_path = translated_output_path(output_dir=output_dir, base_name=base_name)

    print(f"[3/4] Writing outputs for {base_name}", flush=True)
    if processing.generated_subtitle_path is not None:
        print(subtitle_path, flush=True)
    if not status.reading_exists:
        write_reading_md(
            reading_md_path,
            title=base_name,
            source_path=processing.source_path,
            paragraphs=paragraphs,
            language=source_language,
            section_lengths=section_lengths,
        )
        print(reading_md_path, flush=True)
    if needs_zh_extras and not status.zh_reading_exists:
        print(f"Translating English source into Chinese companion outputs for {base_name}", flush=True)
        translated_paragraphs = translate_paragraphs(paragraphs=paragraphs, output_dir=output_dir, base_name=base_name)
    if needs_zh_extras and not status.zh_reading_exists:
        write_reading_md(
            zh_reading_md_path,
            title=base_name,
            source_path=processing.source_path,
            paragraphs=translated_paragraphs,
            language="zh",
            translated_from="en",
            section_lengths=section_lengths,
        )
        print(zh_reading_md_path, flush=True)
    if bilingual_docx and needs_zh_extras:
        output_path = ensure_bilingual_docx(output_dir=output_dir, base_name=base_name)
        if output_path is not None:
            print(output_path, flush=True)

    print("[4/4] Done", flush=True)


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    auto_directory_mode = (args.batch or input_path.is_dir()) and args.source_kind == "auto"
    effective_source_kind = args.source_kind
    if auto_directory_mode:
        effective_source_kind = "subtitle"

    if input_path.is_file() and not is_supported_source(input_path, source_kind=effective_source_kind):
        raise ValueError(
            f"Input file {input_path.name} does not match --source-kind {effective_source_kind!r}"
        )

    default_output_dir = input_path if input_path.is_dir() else input_path.parent
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else default_output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.batch or input_path.is_dir():
        if not input_path.is_dir():
            raise ValueError("--batch requires a directory input")

        groups = build_source_groups(directory=input_path, output_dir=output_dir, source_kind=effective_source_kind)
        pending = [
            group
            for group in groups
            if (not group.status.complete)
            or (args.bilingual_docx and not bilingual_docx_complete(output_dir, group.base_name, group.status.needs_zh_extras))
        ]
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
                bilingual_docx=args.bilingual_docx,
                status=group.status,
                language_hint=group.language_hint,
            )
        if not pending:
            print("Nothing to do.", flush=True)
        if auto_directory_mode:
            fallback_groups = [group for group in build_media_fallback_groups(input_path, output_dir) if not group.status.complete]
            if prompt_media_fallback(fallback_groups):
                for index, group in enumerate(fallback_groups, start=1):
                    print(
                        f"=== [stage2 {index}/{len(fallback_groups)}] {group.base_name} "
                        f"(source: {group.source_path.name}) ===",
                        flush=True,
                    )
                    generate_bundle(
                        input_path=group.source_path,
                        output_dir=output_dir,
                        base_name=group.base_name,
                        whisper_model=args.whisper_model,
                        bootstrap_whisper=args.bootstrap_whisper,
                        bilingual_docx=args.bilingual_docx,
                        status=group.status,
                        language_hint=group.language_hint,
                    )
        return 0

    status = bundle_status(output_dir=output_dir, base_name=canonical_base_name(input_path), candidates=[input_path])
    generate_bundle(
        input_path=input_path,
        output_dir=output_dir,
        base_name=canonical_base_name(input_path),
        whisper_model=args.whisper_model,
        bootstrap_whisper=args.bootstrap_whisper,
        bilingual_docx=args.bilingual_docx,
        status=status,
        language_hint=infer_language_from_path(input_path),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
