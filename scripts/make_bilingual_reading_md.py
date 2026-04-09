from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import requests


TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"
CUE_BREAK_RE = re.compile(r"\n\s*\n", re.MULTILINE)


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
    english: str
    chinese: str = ""


def parse_timestamp(value: str) -> int:
    hh, mm, rest = value.split(":")
    ss, ms = rest.split(",")
    return ((int(hh) * 60 + int(mm)) * 60 + int(ss)) * 1000 + int(ms)


def format_timestamp(ms: int) -> str:
    total_seconds = ms // 1000
    hh, rem = divmod(total_seconds, 3600)
    mm, ss = divmod(rem, 60)
    return f"{hh:02d}:{mm:02d}:{ss:02d}"


def normalize_text(text: str) -> str:
    text = text.replace("\r", " ")
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.;:?!])", r"\1", text)
    text = re.sub(r"\bcloud code\b", "Claude Code", text, flags=re.IGNORECASE)
    text = re.sub(r"\bcloud ai\b", "Claude AI", text, flags=re.IGNORECASE)
    text = re.sub(r"\bcloud desktop\b", "Claude Desktop", text, flags=re.IGNORECASE)
    text = re.sub(r"\bcloud skill library\b", "Claude skill library", text, flags=re.IGNORECASE)
    text = re.sub(r"\bcloud skill\b", "Claude skill", text, flags=re.IGNORECASE)
    text = re.sub(r"\bquadr\b", "Claude", text, flags=re.IGNORECASE)
    text = re.sub(r"\bcoowriters\b", "co-writers", text, flags=re.IGNORECASE)
    text = re.sub(r"\bcoowwriter\b", "co-writer", text, flags=re.IGNORECASE)
    text = re.sub(r"\bcoowriting\b", "co-writing", text, flags=re.IGNORECASE)
    text = re.sub(r"\bmasterass\b", "masterclass", text, flags=re.IGNORECASE)
    text = re.sub(r"\bweight list\b", "waitlist", text, flags=re.IGNORECASE)
    text = text.replace(" coowwriting ", " co-writing ")
    return text


def cleanup_translation(text: str) -> str:
    replacements = {
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
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


def load_cues(srt_path: Path) -> list[Cue]:
    cues: list[Cue] = []
    blocks = [block.strip() for block in CUE_BREAK_RE.split(srt_path.read_text(encoding="utf-8")) if block.strip()]
    for block in blocks:
        lines = block.splitlines()
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        start_raw, end_raw = lines[1].split(" --> ")
        cues.append(
            Cue(
                index=int(lines[0]),
                start_ms=parse_timestamp(start_raw),
                end_ms=parse_timestamp(end_raw),
                text=normalize_text(" ".join(lines[2:])),
            )
        )
    return cues


def merge_cues(cues: Iterable[Cue]) -> list[Paragraph]:
    paragraphs: list[Paragraph] = []
    buffer: list[str] = []
    start_ms = 0
    end_ms = 0
    previous_end = 0

    def flush() -> None:
        nonlocal buffer, start_ms, end_ms
        english = normalize_text(" ".join(buffer))
        if english:
            paragraphs.append(Paragraph(start_ms=start_ms, end_ms=end_ms, english=english))
        buffer = []
        start_ms = 0
        end_ms = 0

    for cue in cues:
        if not buffer:
            start_ms = cue.start_ms
        else:
            gap = cue.start_ms - previous_end
            joined = normalize_text(" ".join(buffer))
            if gap >= 2200 or len(joined) >= 900:
                flush()
                start_ms = cue.start_ms
        buffer.append(cue.text)
        end_ms = cue.end_ms
        previous_end = cue.end_ms

        joined = normalize_text(" ".join(buffer))
        sentence_end = joined.endswith((".", "?", "!", '."', '!"', '?"'))
        if len(joined) >= 700 and sentence_end:
            flush()

    flush()
    return paragraphs


def load_cache(cache_path: Path) -> dict[str, str]:
    if not cache_path.exists():
        return {}
    return json.loads(cache_path.read_text(encoding="utf-8"))


def save_cache(cache_path: Path, cache: dict[str, str]) -> None:
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def translate_text(text: str, session: requests.Session) -> str:
    response = session.get(
        TRANSLATE_URL,
        params={
            "client": "gtx",
            "sl": "en",
            "tl": "zh-CN",
            "dt": "t",
            "q": text,
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    pieces = payload[0] or []
    return "".join(piece[0] for piece in pieces if piece and piece[0]).strip()


def translate_paragraphs(paragraphs: list[Paragraph], cache_path: Path) -> None:
    cache = load_cache(cache_path)
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})

    total = len(paragraphs)
    for idx, paragraph in enumerate(paragraphs, start=1):
        if paragraph.english in cache:
            paragraph.chinese = cleanup_translation(cache[paragraph.english])
            continue

        for attempt in range(5):
            try:
                paragraph.chinese = translate_text(paragraph.english, session)
                paragraph.chinese = cleanup_translation(paragraph.chinese)
                cache[paragraph.english] = paragraph.chinese
                save_cache(cache_path, cache)
                print(f"[{idx}/{total}] translated {format_timestamp(paragraph.start_ms)}", flush=True)
                time.sleep(0.35)
                break
            except Exception as exc:  # noqa: BLE001
                if attempt == 4:
                    raise RuntimeError(f"Failed to translate paragraph {idx}: {exc}") from exc
                time.sleep(1.5 * (attempt + 1))


def write_markdown(output_path: Path, source_name: str, paragraphs: list[Paragraph]) -> None:
    lines = [
        f"# {source_name}",
        "",
        "阅读版中英文双语文本。",
        "",
        "- Source: cleaned English auto-subtitles",
        "- Format: paragraph-based reading version",
        "- Note: generated from YouTube auto captions and lightly cleaned for readability",
        "",
    ]

    for paragraph in paragraphs:
        lines.extend(
            [
                f"## {format_timestamp(paragraph.start_ms)}",
                "",
                "**EN**",
                "",
                paragraph.english,
                "",
                "**ZH**",
                "",
                paragraph.chinese,
                "",
            ]
        )

    output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: python3 make_bilingual_reading_md.py <input.srt> <output.md>")
        return 1

    input_path = Path(sys.argv[1]).expanduser().resolve()
    output_path = Path(sys.argv[2]).expanduser().resolve()
    cache_path = output_path.with_suffix(".translation-cache.json")

    cues = load_cues(input_path)
    paragraphs = merge_cues(cues)
    translate_paragraphs(paragraphs, cache_path)
    write_markdown(output_path, input_path.stem, paragraphs)
    print(f"Wrote {len(paragraphs)} bilingual paragraphs to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
