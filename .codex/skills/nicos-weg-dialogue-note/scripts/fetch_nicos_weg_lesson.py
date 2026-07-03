#!/usr/bin/env python3
"""Generate an Obsidian note from a DW Nicos Weg dialogue/cloze exercise URL."""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import html
import json
import logging
import re
import sys
import traceback
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable


@dataclasses.dataclass(frozen=True)
class ParsedUrl:
    url: str
    lang: str
    lesson_id: int
    exercise_id: int | None


@dataclasses.dataclass
class ExerciseBlock:
    index: int
    question: str
    description: str
    raw_text: str
    filled_text: str
    answers: list[str]
    audio_url: str | None
    audio_file: str | None = None
    audio_kind: str = "answer_audio"


@dataclasses.dataclass
class VocabularyEntry:
    name: str
    meaning: str
    sub_title: str
    audio_url: str | None
    audio_file: str | None = None


@dataclasses.dataclass
class ExercisePage:
    source_url: str
    exercise_id: int | None
    exercise_name: str
    exercise_description: str
    exercise_blocks: list[ExerciseBlock]
    expressions: list[VocabularyEntry]
    input_text: str = ""
    input_type: str = ""
    exercise_kind: str = ""
    source_text_markdown: str = ""
    source_audio_url: str | None = None
    source_audio_file: str | None = None


@dataclasses.dataclass
class LessonData:
    source_url: str
    lang: str
    lesson_id: int
    exercise_id: int | None
    lesson_name: str
    lesson_url: str
    exercise_name: str
    exercise_description: str
    level: str
    first_publication_date: str
    overview_parts: list[dict[str, Any]]
    exercise_blocks: list[ExerciseBlock]
    manuscript_html: str
    manuscript_markdown: str
    vocab: list[VocabularyEntry]
    grammar: list[dict[str, str]]
    expressions: list[VocabularyEntry]
    exercise_pages: list[ExercisePage] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class DialogueTurn:
    source: str
    index: int
    speaker: str
    answer: str
    keywords: str
    pattern: str
    chinese_target: str


USER_AGENT = "Mozilla/5.0 (Codex Nicos Weg note generator)"
BASE_URL = "https://learngerman.dw.com"
AUDIO_EXT_RE = re.compile(r"\.mp3(?:\?.*)?$", re.I)
SPEAKER_LINE_RE = re.compile(r"^\s*>?\s*(?:[-*]\s*)?(?:\*\*)?([A-ZÄÖÜẞ][A-Za-zÄÖÜäöüß .'-]{0,40}?)(?:\*\*)?:(?:\*\*)?\s*(.*)$")
GERMAN_STOPWORDS = {
    "ich", "du", "er", "sie", "es", "wir", "ihr", "mich", "dich", "mir", "dir", "uns", "euch",
    "mein", "meine", "meinen", "meinem", "meiner", "dein", "deine", "sein", "seine", "ihr", "ihre",
    "der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "einem", "einer", "so",
    "und", "oder", "aber", "auch", "nicht", "kein", "keine", "ja", "nein", "doch", "mal", "sehr",
    "zu", "zum", "zur", "im", "in", "am", "an", "auf", "aus", "von", "für", "mit", "nach", "bei",
    "ist", "bin", "bist", "sind", "seid", "war", "waren", "habe", "hast", "hat", "haben",
}


def parse_dw_url(url: str) -> ParsedUrl:
    parsed = urllib.parse.urlparse(url)
    parts = [urllib.parse.unquote(p) for p in parsed.path.split("/") if p]
    lang = parts[0] if parts else "zh"
    lesson_id = None
    exercise_id = None
    for part in parts:
        if re.fullmatch(r"l-\d+", part):
            lesson_id = int(part[2:])
        elif re.fullmatch(r"e-\d+", part):
            exercise_id = int(part[2:])
    if lesson_id is None:
        raise ValueError(f"Cannot find lesson id (/l-...) in URL: {url}")
    return ParsedUrl(url=url, lang=lang, lesson_id=lesson_id, exercise_id=exercise_id)


def safe_filename(value: str, max_len: int = 100) -> str:
    value = html.unescape(value).strip()
    value = re.sub(r"[\s_/\\|:：]+", "-", value)
    value = re.sub(r"[()（）]+", "-", value)
    value = re.sub(r"[\?？!！,，.。;；'\"“”‘’\[\]{}<>《》…]+", "", value)
    value = re.sub(r"-+", "-", value).strip("- ")
    return (value or "nicos-weg-note")[:max_len].strip("-")


def fetch_text(url: str, timeout: int = 30) -> str:
    url = urllib.parse.quote(url, safe=":/?&=#%")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        body = response.read()
        try:
            return body.decode("utf-8")
        except UnicodeDecodeError:
            charset = response.headers.get_content_charset() or "utf-8"
            return body.decode(charset, errors="replace")


def extract_apollo_state(page_html: str) -> dict[str, Any]:
    match = re.search(r"window\.__APOLLO_STATE__=(.*?);</script>", page_html, re.S)
    if not match:
        raise ValueError("Cannot find window.__APOLLO_STATE__ in DW page HTML")
    return json.loads(match.group(1))


def ref_id(ref: Any) -> str | None:
    return ref.get("__ref") if isinstance(ref, dict) else None


def resolve_ref(state: dict[str, Any], ref: Any) -> dict[str, Any]:
    rid = ref_id(ref)
    return state.get(rid, {}) if rid else {}


def strip_tags_to_text(fragment: str | None) -> str:
    if not fragment:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    text = re.sub(r"</p\s*>", "\n\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace("\xa0", " ")
    text = re.sub(r"\*\*([A-Z????][A-Za-z??????? .'-]{0,40}:)\s*\*\*\s*", r"**\1** ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def render_html_table(match: re.Match[str]) -> str:
    table = match.group(0)
    table = re.sub(r"<table\b[^>]*>", '<table class="grammar-table" border="1" cellpadding="6" cellspacing="0" style="border-collapse: collapse; width: 100%; margin: 0.75em 0;">', table, count=1, flags=re.I)
    table = re.sub(r"<th\b[^>]*>", "<th>", table, flags=re.I)
    table = re.sub(r"<td\b[^>]*>", "<td>", table, flags=re.I)
    table = re.sub(r"<br\s*/?>", "<br>", table, flags=re.I)
    table = html.unescape(table).replace("\xa0", " ")
    table = re.sub(r">\s+<", "><", table)
    return "\n\n" + table.strip() + "\n\n"




def render_grammar_matrix_table(headers: list[str], rows: list[list[str]]) -> str:
    """Render a compact grammar matrix as an Obsidian-readable HTML table."""
    lines = [
        '<table class="grammar-table" border="1" cellpadding="6" cellspacing="0" style="border-collapse: collapse; width: 100%; margin: 0.75em 0; table-layout: fixed;">',
        '  <thead><tr>' + ''.join(f'<th style="text-align:left; min-width: 120px;">{html.escape(h)}</th>' for h in headers) + '</tr></thead>',
        '  <tbody>',
    ]
    for row in rows:
        lines.append('    <tr>' + ''.join(f'<td style="min-width: 120px;">{html.escape(cell)}</td>' for cell in row) + '</tr>')
    lines.extend(['  </tbody>', '</table>'])
    return '\n'.join(lines)


def repair_indented_grammar_tables(markdown: str) -> str:
    """Convert DW grammar pseudo-tables that arrive as indented lines into HTML tables.

    Some DW grammar blocks are not delivered as real <table> HTML. After tag stripping they
    become tab-indented one-cell-per-line code blocks in Obsidian. Detect the common
    three-column pronoun matrix and render it as a real HTML table.
    """
    lines = markdown.splitlines()
    output: list[str] = []
    i = 0
    pronoun_headers = ["".join(chr(x) for x in [0x7b2c, 0x4e00, 0x683c]), "".join(chr(x) for x in [0x7b2c, 0x56db, 0x683c]), "".join(chr(x) for x in [0x7b2c, 0x4e09, 0x683c])]
    while i < len(lines):
        window = [lines[j].strip() for j in range(i, min(i + 3, len(lines)))]
        if window == pronoun_headers:
            j = i + 3
            cells: list[str] = []
            while j < len(lines):
                raw = lines[j]
                stripped = raw.strip()
                if not stripped:
                    j += 1
                    continue
                if stripped.startswith("#") or stripped.endswith("?") or stripped.startswith("###"):
                    break
                if not raw.startswith(("\t", "    ")) and cells and len(cells) % 3 == 0:
                    break
                cells.append(stripped)
                j += 1
            rows = [cells[k:k + 3] for k in range(0, len(cells), 3) if len(cells[k:k + 3]) == 3]
            if rows:
                if output and output[-1] != "":
                    output.append("")
                output.append(render_grammar_matrix_table(pronoun_headers, rows))
                output.append("")
                i = j
                continue
        output.append(lines[i])
        i += 1
    return "\n".join(output).strip()


def html_to_markdown(fragment: str | None, *, bold_placeholders: bool = False, preserve_tables: bool = False) -> str:
    if not fragment:
        return ""
    text = fragment
    table_placeholders: list[str] = []
    if preserve_tables:
        def store_table(match: re.Match[str]) -> str:
            table_placeholders.append(render_html_table(match))
            return f"\n\n@@GRAMMAR_TABLE_{len(table_placeholders) - 1}@@\n\n"

        text = re.sub(r"<table\b.*?</table>", store_table, text, flags=re.I | re.S)
    text = re.sub(r"<strong>(.*?)</strong>", r"**\1**", text, flags=re.I | re.S)
    text = re.sub(r"<b>(.*?)</b>", r"**\1**", text, flags=re.I | re.S)
    text = re.sub(r"<em>(.*?)</em>", r"*\1*", text, flags=re.I | re.S)
    if bold_placeholders:
        text = re.sub(r"<span\b[^>]*class=\"[^\"]*placeholder[^\"]*\"[^>]*>(.*?)</span>", r"**\1**", text, flags=re.I | re.S)
    else:
        text = re.sub(r"<span\b[^>]*>(.*?)</span>", r"\1", text, flags=re.I | re.S)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p\s*>", "\n\n", text, flags=re.I)
    text = re.sub(r"<p\b[^>]*>", "", text, flags=re.I)
    text = re.sub(r"<figure\b.*?</figure>", "", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace("\xa0", " ")
    text = re.sub(r"\*\*([A-Z][A-Za-z .'-]{0,40}:)\s*\*\*\s*", r"**\1** ", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    for i, table in enumerate(table_placeholders):
        text = text.replace(f"@@GRAMMAR_TABLE_{i}@@", table.strip())
    text = re.sub(r"\n{3,}", "\n\n", text)
    if preserve_tables:
        text = repair_indented_grammar_tables(text)
    return text.strip()


def extract_answers(state: dict[str, Any], inquiry_ref: Any) -> list[str]:
    inquiry = resolve_ref(state, inquiry_ref) if "__ref" in inquiry_ref else inquiry_ref
    answers: list[str] = []
    for sub_ref in inquiry.get("subInquiries") or []:
        sub = resolve_ref(state, sub_ref)
        found = False
        for key in ("correctAnswers", "answers"):
            vals = sub.get(key)
            if isinstance(vals, list) and vals:
                first = vals[0]
                answers.append(str(first.get("text") if isinstance(first, dict) else first))
                found = True
                break
        if found:
            continue
        for alt_ref in sub.get("alternatives") or []:
            alt = resolve_ref(state, alt_ref) if ref_id(alt_ref) else alt_ref
            if alt.get("isCorrect") or alt.get("correct"):
                answers.append(strip_tags_to_text(str(alt.get("alternativeText") or alt.get("text") or alt.get("label") or alt.get("title") or "")))
                found = True
                break
        if found:
            continue
        text = sub.get("text") or sub.get("inquiryText") or sub.get("inquiryDescription") or ""
        if text and "#p#" not in text and strip_tags_to_text(text):
            answers.append(strip_tags_to_text(text))
    return answers


def fill_cloze_text(text: str, answers: list[str]) -> str:
    markdown = html_to_markdown(text)
    for answer in answers:
        markdown = markdown.replace("#p#", f"**{answer}**", 1)
    markdown = markdown.replace("#p#", "**____**")
    return markdown.strip()


def has_cloze_text(text: str) -> bool:
    return bool(text and ("#p#" in text or strip_tags_to_text(text)))


def exercise_source_audio_url(exercise: dict[str, Any]) -> str | None:
    for audio in exercise.get("audios") or []:
        if isinstance(audio, dict) and audio.get("mp3Src"):
            return audio.get("mp3Src")
    for link in exercise.get("contentLinks") or []:
        target = link.get("target") if isinstance(link, dict) else None
        if isinstance(target, dict) and target.get("mp3Src"):
            return target.get("mp3Src")
    return None


def classify_exercise_page(exercise: dict[str, Any], blocks: list[ExerciseBlock]) -> tuple[str, str]:
    input_text = exercise.get("inputText") or ""
    input_type = exercise.get("inputType") or ""
    if input_text and strip_tags_to_text(input_text):
        return "reading_text", html_to_markdown(input_text, bold_placeholders=True)
    for block in blocks:
        if has_cloze_text(block.raw_text) and block.filled_text:
            return "cloze_text", block.filled_text
    return (input_type.lower() or "exercise"), ""


def is_grammar_overview_part(part: dict[str, Any]) -> bool:
    target = part.get("target") or {}
    title = str(target.get("name") or "")
    lower = title.casefold()
    return any(token in lower for token in ["grammar", "grammatik", "als", "wie", "nico学德语"]) or any(token in title for token in ["语法", "比较"])


def extract_fallback_grammar_from_overview(state: dict[str, Any], lesson: dict[str, Any], parsed: ParsedUrl, logger: logging.Logger) -> list[dict[str, str]]:
    grammar: list[dict[str, str]] = []
    seen: set[int] = set()
    for part in lesson.get("overviewParts") or []:
        if part.get("lessonPart") != "EXERCISE" or not is_grammar_overview_part(part):
            continue
        target_id = part.get("targetId")
        if not isinstance(target_id, int) or target_id in seen:
            continue
        seen.add(target_id)
        target = part.get("target") or {}
        title = target.get("name") or f"Exercise {target_id}"
        exercise = state.get(f"Exercise:{target_id}")
        if not exercise:
            named_url = target.get(f'namedUrl({{"contextId":{parsed.lesson_id}}})') or target.get("namedUrl")
            if named_url:
                fetch_url = urllib.parse.urljoin(BASE_URL, named_url)
                try:
                    logger.info("Fetching fallback grammar exercise page: %s", fetch_url)
                    extra_state = extract_apollo_state(fetch_text(fetch_url))
                    state.update(extra_state)
                    exercise = state.get(f"Exercise:{target_id}")
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed to fetch fallback grammar exercise %s: %s", fetch_url, exc)
        input_text = (exercise or {}).get("inputText") or ""
        if input_text and strip_tags_to_text(input_text):
            grammar.append({
                "name": str(title).strip(),
                "shortTitle": str(title).strip(),
                "text": html_to_markdown(input_text, bold_placeholders=True, preserve_tables=True),
            })
            logger.info("Added fallback grammar from exercise %s: %s", target_id, title)
    return grammar


def strip_markdown(text: str) -> str:
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"__(.*?)__", r"\1", text)
    text = re.sub(r"\*(.*?)\*", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_keywords(answer: str, limit: int = 5) -> str:
    tokens = re.findall(r"[A-Za-zÄÖÜäöüß]+(?:-[A-Za-zÄÖÜäöüß]+)?", strip_markdown(answer))
    keywords: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        key = token.casefold()
        if key in GERMAN_STOPWORDS or len(token) <= 2 or key in seen:
            continue
        seen.add(key)
        keywords.append(token)
        if len(keywords) >= limit:
            break
    return " / ".join(keywords) if keywords else "（请根据参考答案提取关键词）"


def extract_sentence_pattern(answer: str) -> str:
    clean = strip_markdown(answer)
    words = re.findall(r"[A-Za-zÄÖÜäöüß]+|[?!.,;:]", clean)
    word_tokens = [w for w in words if re.match(r"[A-Za-zÄÖÜäöüß]+$", w)]
    if not word_tokens:
        return "..."
    end = "?" if clean.endswith("?") else ""
    first = word_tokens[0]
    if len(word_tokens) >= 3 and first.lower() in {"ich", "du", "er", "sie", "es", "wir", "ihr"}:
        return " ".join(word_tokens[:3]) + f" ...{end}"
    if len(word_tokens) >= 2:
        return " ".join(word_tokens[:2]) + f" ...{end}"
    return first + f" ...{end}"


def build_chinese_target(answer: str) -> str:
    return "请补充中文意思"


def extract_dialogue_turns(text: str, source: str) -> list[DialogueTurn]:
    turns: list[DialogueTurn] = []
    current_speaker: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_speaker, current_lines
        if not current_speaker:
            return
        answer = strip_markdown(" ".join(line.strip() for line in current_lines if line.strip()))
        if answer:
            turns.append(
                DialogueTurn(
                    source=source,
                    index=len(turns) + 1,
                    speaker=current_speaker.strip(),
                    answer=answer,
                    keywords=extract_keywords(answer),
                    pattern=extract_sentence_pattern(answer),
                    chinese_target=build_chinese_target(answer),
                )
            )
        current_speaker = None
        current_lines = []

    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line in {"---", "***"}:
            continue
        match = SPEAKER_LINE_RE.match(line)
        if match:
            flush()
            current_speaker = strip_markdown(match.group(1)).strip()
            inline = match.group(2).strip()
            current_lines = [inline] if inline else []
        elif current_speaker:
            current_lines.append(line)
    flush()
    return turns


def collect_dialogue_turns(data: LessonData) -> list[DialogueTurn]:
    turns: list[DialogueTurn] = []
    turns.extend(extract_dialogue_turns(data.manuscript_markdown, "课文对话"))
    for block in data.exercise_blocks:
            turns.extend(extract_dialogue_turns(block.filled_text, f"对话练习 {block.index}"))
    return turns


def collect_manuscript_turns(data: LessonData) -> list[DialogueTurn]:
    return extract_dialogue_turns(data.manuscript_markdown, "课文对话")


def collect_exercise_page_turns(page: ExercisePage) -> list[DialogueTurn]:
    turns: list[DialogueTurn] = []
    if page.source_text_markdown:
        turns.extend(extract_dialogue_turns(page.source_text_markdown, "对话练习 1"))
        if turns:
            return turns
    for block in page.exercise_blocks:
        if block.filled_text:
            turns.extend(extract_dialogue_turns(block.filled_text, f"对话练习 {block.index}"))
    return turns


def render_prompt_card_filename(note_path: Path) -> Path:
    return note_path.with_name(f"{note_path.stem}-对话练习提示卡.md")


def render_manuscript_prompt_card_filename(note_path: Path) -> Path:
    return note_path.with_name(f"{note_path.stem}-课文练习提示卡.md")


def render_exercise_prompt_card_filename(note_path: Path, page_index: int) -> Path:
    return note_path.with_name(f"{note_path.stem}-对话练习提示卡-{page_index:02d}.md")


def render_dialogue_prompt_card(data: LessonData, turns: list[DialogueTurn]) -> str:
    today = dt.date.today().isoformat()
    lines = [
        "---",
        f"title: {yaml_escape('对话练习提示卡：' + (data.exercise_name or data.lesson_name or 'Nicos Weg'))}",
        f"source: {yaml_escape(data.source_url)}",
        f"lesson: {yaml_escape(data.lesson_name)}",
        f"exercise: {yaml_escape(data.exercise_name)}",
        f"date: {today}",
        "tags:",
        "  - Deutsch",
        "  - NicosWeg",
        "  - 对话练习",
        "---",
        "",
        f"# 对话练习提示卡：{data.exercise_name or data.lesson_name or 'Nicos Weg'}",
        "",
        "> 使用方法：先看中文目标、关键词和句型提示进行半脱稿表达；需要时再展开参考答案。",
        "",
    ]
    grouped: dict[str, list[DialogueTurn]] = {}
    for turn in turns:
        grouped.setdefault(turn.source, []).append(turn)
    for source, source_turns in grouped.items():
        lines += [f"## {source}", ""]
        for i, turn in enumerate(source_turns, 1):
            lines += [
                f"> [!question]- 第 {i} 轮：{turn.speaker}",
                f"> **你要表达：** {turn.chinese_target}",
                ">",
                "> **一级提示：中文意思**",
                f"> {turn.chinese_target}",
                ">",
                "> **二级提示：关键词**",
                f"> {turn.keywords}",
                ">",
                "> **三级提示：句型**",
                f"> {turn.pattern}",
                ">",
                "> > [!example]- 参考答案",
                f"> > {turn.answer}",
                "",
            ]
    return "\n".join(lines)


def count_turn_sources(turns: list[DialogueTurn]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for turn in turns:
        counts[turn.source] = counts.get(turn.source, 0) + 1
    return counts


def write_dialogue_prompt_cards(data: LessonData, note_path: Path, logger: logging.Logger) -> list[Path]:
    written: list[Path] = []
    manuscript_turns = collect_manuscript_turns(data)
    if manuscript_turns:
        card_path = render_manuscript_prompt_card_filename(note_path)
        card_path.write_text(render_dialogue_prompt_card(data, manuscript_turns), encoding="utf-8")
        written.append(card_path)
        logger.info("Wrote manuscript prompt card: %s turns=%d sources=%s", card_path, len(manuscript_turns), count_turn_sources(manuscript_turns))
    else:
        logger.info("Manuscript prompt card skipped: no manuscript dialogue turns found")

    pages = data.exercise_pages or [ExercisePage(data.source_url, data.exercise_id, data.exercise_name, data.exercise_description, data.exercise_blocks, data.expressions)]
    for page_index, page in enumerate(pages, 1):
        turns = collect_exercise_page_turns(page)
        if not turns:
            logger.info("Exercise prompt card skipped: page=%d exercise=%s no dialogue turns found", page_index, page.exercise_name)
            continue
        card_path = render_exercise_prompt_card_filename(note_path, page_index)
        page_data = dataclasses.replace(
            data,
            source_url=page.source_url,
            exercise_id=page.exercise_id,
            exercise_name=page.exercise_name,
            exercise_description=page.exercise_description,
            exercise_blocks=page.exercise_blocks,
            expressions=page.expressions,
            exercise_pages=[page],
        )
        card_path.write_text(render_dialogue_prompt_card(page_data, turns), encoding="utf-8")
        written.append(card_path)
        logger.info("Wrote exercise prompt card: %s page=%d turns=%d sources=%s", card_path, page_index, len(turns), count_turn_sources(turns))
    if not written:
        logger.info("Dialogue prompt cards skipped: no dialogue turns found")
    return written


def write_dialogue_prompt_card(data: LessonData, note_path: Path, logger: logging.Logger) -> Path | None:
    written = write_dialogue_prompt_cards(data, note_path, logger)
    return written[0] if written else None


def content_audio_url(state: dict[str, Any], inquiry: dict[str, Any]) -> str | None:
    links = inquiry.get('contentLinks({"targetTypes":["AUDIO"]})') or inquiry.get("contentLinks") or []
    for link_ref in links:
        link = resolve_ref(state, link_ref) if ref_id(link_ref) else link_ref
        target = link.get("target") or {}
        url = target.get("mp3Src") or link.get("mp3Src")
        if url:
            return url
    return None


def normalize_lesson_url(raw: str, lang: str, lesson_id: int) -> str:
    if raw:
        return urllib.parse.urljoin(BASE_URL, raw)
    return f"{BASE_URL}/{lang}/l-{lesson_id}"


def related_lesson_urls(lesson_url: str) -> list[str]:
    base = lesson_url.rstrip("/")
    return [base, base + "/lm", base + "/lv", base + "/lg"]


def load_combined_state(url: str, logger: logging.Logger) -> tuple[dict[str, Any], str]:
    first_html = fetch_text(url)
    state = extract_apollo_state(first_html)
    parsed = parse_dw_url(url)
    lesson = state.get(f"Lesson:{parsed.lesson_id}", {})
    lesson_url = normalize_lesson_url(lesson.get("namedUrl", ""), parsed.lang, parsed.lesson_id)
    for extra_url in related_lesson_urls(lesson_url):
        try:
            logger.info("Fetching related page: %s", extra_url)
            extra_state = extract_apollo_state(fetch_text(extra_url))
            state.update(extra_state)
        except Exception as exc:  # noqa: BLE001 - log and continue on optional pages
            logger.warning("Failed to fetch related page %s: %s", extra_url, exc)
    return state, first_html


def level_name(value: Any) -> str:
    mapping = {0: "A1", 1: "A2", 2: "B1", 3: "B2", 4: "C1", 5: "C2"}
    return mapping.get(value, str(value or ""))


def audio_basename(url: str, fallback: str) -> str:
    path = urllib.parse.urlparse(url).path
    name = urllib.parse.unquote(Path(path).name)
    if AUDIO_EXT_RE.search(name):
        return safe_filename(Path(name).stem, 80) + ".mp3"
    return safe_filename(fallback, 80) + ".mp3"


def extract_unit_code(data: LessonData) -> str | None:
    candidates: list[str] = []
    for block in data.exercise_blocks:
        if block.audio_url:
            candidates.append(block.audio_url)
        if block.audio_file:
            candidates.append(block.audio_file)
    for entry in [*data.vocab, *data.expressions]:
        if entry.audio_url:
            candidates.append(entry.audio_url)
        if entry.audio_file:
            candidates.append(entry.audio_file)
    candidates.extend([data.lesson_name, data.exercise_name, data.lesson_url, data.source_url])
    for part in data.overview_parts:
        candidates.extend(str(v) for v in part.values() if isinstance(v, (str, int)))

    for value in candidates:
        text = urllib.parse.unquote(str(value))
        match = re.search(r"(?:^|[_\-/\s])(?:A\d[_-])?E(\d{1,2})(?:[_\-/\s]|$)", text, flags=re.I)
        if match:
            return f"E{int(match.group(1)):02d}"
        match = re.search(r"\bLektion\s*(\d{1,2})\b", text, flags=re.I)
        if match:
            return f"E{int(match.group(1)):02d}"
        match = re.search(r"第\s*(\d{1,2})\s*(?:课|单元|章)", text)
        if match:
            return f"E{int(match.group(1)):02d}"
    return None


def render_note_stem(data: LessonData) -> str:
    parts = ["DW", data.level or "Nicos-Weg"]
    unit = extract_unit_code(data)
    if unit:
        parts.append(unit)
    parts.append(safe_filename(data.lesson_name or "Nicos-Weg"))
    return "-".join(part for part in parts if part)


def render_note_filename(data: LessonData) -> str:
    return f"{render_note_stem(data)}.md"


def download_file(url: str, destination: Path, logger: logging.Logger) -> bool:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=45) as response:
            destination.write_bytes(response.read())
        logger.info("Downloaded %s -> %s (%d bytes)", url, destination, destination.stat().st_size)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to download %s -> %s: %s", url, destination, exc)
        return False


def build_lesson_data(url: str, state: dict[str, Any], logger: logging.Logger) -> LessonData:
    parsed = parse_dw_url(url)
    lesson = state.get(f"Lesson:{parsed.lesson_id}") or {}
    if not lesson:
        raise ValueError(f"Lesson:{parsed.lesson_id} not found in Apollo state")
    exercise = state.get(f"Exercise:{parsed.exercise_id}") if parsed.exercise_id else None
    if not exercise and parsed.exercise_id:
        raise ValueError(f"Exercise:{parsed.exercise_id} not found in Apollo state")
    exercise = exercise or {}

    blocks: list[ExerciseBlock] = []
    for i, inquiry_ref in enumerate(exercise.get("inquiries") or [], 1):
        inquiry = resolve_ref(state, inquiry_ref)
        if not inquiry:
            continue
        answers = extract_answers(state, inquiry_ref)
        raw_text = inquiry.get("text") or ""
        filled_text = fill_cloze_text(raw_text, answers) if has_cloze_text(raw_text) else ""
        blocks.append(
            ExerciseBlock(
                index=i,
                question=strip_tags_to_text(inquiry.get("inquiryText")),
                description=strip_tags_to_text(inquiry.get("inquiryDescription")),
                raw_text=raw_text,
                filled_text=filled_text,
                answers=answers,
                audio_url=content_audio_url(state, inquiry),
                audio_kind="answer_audio",
            )
        )

    vocab: list[VocabularyEntry] = []
    grammar: list[dict[str, str]] = []
    for key, knowledge in state.items():
        if not key.startswith("Knowledge:") or not isinstance(knowledge, dict):
            continue
        ktype = knowledge.get("knowledgeType")
        if ktype == "VOCABULARY":
            audios = knowledge.get("audios") or []
            vocab.append(
                VocabularyEntry(
                    name=(knowledge.get("name") or knowledge.get("shortTitle") or "").strip(),
                    meaning=strip_tags_to_text(knowledge.get("text")),
                    sub_title=(knowledge.get("subTitle") or "").strip(),
                    audio_url=(audios[0].get("mp3Src") if audios else None),
                )
            )
        elif ktype == "GRAMMAR":
            grammar.append(
                {
                    "name": (knowledge.get("name") or knowledge.get("shortTitle") or "").strip(),
                    "shortTitle": (knowledge.get("shortTitle") or "").strip(),
                    "text": html_to_markdown(knowledge.get("text"), bold_placeholders=True, preserve_tables=True),
                }
            )

    if not grammar:
        grammar.extend(extract_fallback_grammar_from_overview(state, lesson, parsed, logger))

    order = {part.get("targetId"): idx for idx, part in enumerate(lesson.get("overviewParts") or [])}
    vocab.sort(key=lambda v: order.get(next((int(k.split(":")[1]) for k, obj in state.items() if isinstance(obj, dict) and obj.get("name") == v.name and k.startswith("Knowledge:")), 10**9), 10**9))
    grammar.sort(key=lambda g: order.get(next((int(k.split(":")[1]) for k, obj in state.items() if isinstance(obj, dict) and obj.get("name") == g["name"] and k.startswith("Knowledge:")), 10**9), 10**9))

    expression_ids = set()
    for ref in exercise.get("knowledges") or []:
        rid = ref_id(ref)
        if rid and rid.startswith("Knowledge:"):
            expression_ids.add(rid)
    expressions = []
    for rid in expression_ids:
        k = state.get(rid, {})
        if k.get("knowledgeType") == "VOCABULARY":
            audios = k.get("audios") or []
            expressions.append(VocabularyEntry(k.get("name") or k.get("shortTitle") or "", strip_tags_to_text(k.get("text")), k.get("subTitle") or "", audios[0].get("mp3Src") if audios else None))

    lesson_url = normalize_lesson_url(lesson.get("namedUrl", ""), parsed.lang, parsed.lesson_id)
    exercise_name = exercise.get("name") or lesson.get("name") or "Nicos Weg"
    exercise_description = strip_tags_to_text(exercise.get("description"))
    exercise_kind, source_text_markdown = classify_exercise_page(exercise, blocks)
    page = ExercisePage(
        source_url=url,
        exercise_id=parsed.exercise_id,
        exercise_name=exercise_name,
        exercise_description=exercise_description,
        exercise_blocks=blocks,
        expressions=expressions,
        input_text=exercise.get("inputText") or "",
        input_type=exercise.get("inputType") or "",
        exercise_kind=exercise_kind,
        source_text_markdown=source_text_markdown,
        source_audio_url=exercise_source_audio_url(exercise),
    )
    logger.info("Exercise page classified: id=%s name=%s input_type=%s kind=%s source_text_chars=%d source_audio=%s answer_audio_count=%d", parsed.exercise_id, exercise_name, page.input_type, exercise_kind, len(source_text_markdown), bool(page.source_audio_url), sum(1 for b in blocks if b.audio_url))
    return LessonData(
        source_url=url,
        lang=parsed.lang,
        lesson_id=parsed.lesson_id,
        exercise_id=parsed.exercise_id,
        lesson_name=lesson.get("name") or "",
        lesson_url=lesson_url,
        exercise_name=exercise_name,
        exercise_description=exercise_description,
        level=level_name(lesson.get("dkLearningLevel")),
        first_publication_date=(exercise.get("firstPublicationDate") or lesson.get("firstPublicationDate") or "")[:10],
        overview_parts=lesson.get("overviewParts") or [],
        exercise_blocks=blocks,
        manuscript_html=lesson.get("manuscript") or "",
        manuscript_markdown=html_to_markdown(lesson.get("manuscript"), bold_placeholders=True),
        vocab=vocab,
        grammar=grammar,
        expressions=expressions,
        exercise_pages=[page],
    )


def merge_lesson_data(items: list[LessonData]) -> LessonData:
    if not items:
        raise ValueError("At least one LessonData item is required")
    base = items[0]
    mismatched = [item.source_url for item in items if item.lesson_id != base.lesson_id]
    if mismatched:
        raise ValueError(f"All URLs must belong to the same lesson id {base.lesson_id}; mismatched URLs: {mismatched}")
    pages: list[ExercisePage] = []
    blocks: list[ExerciseBlock] = []
    expressions: list[VocabularyEntry] = []
    for page_index, item in enumerate(items, 1):
        item_pages = item.exercise_pages or [ExercisePage(item.source_url, item.exercise_id, item.exercise_name, item.exercise_description, item.exercise_blocks, item.expressions)]
        for page in item_pages:
            new_page_blocks: list[ExerciseBlock] = []
            for block in page.exercise_blocks:
                copied = dataclasses.replace(block, index=len(new_page_blocks) + 1)
                new_page_blocks.append(copied)
                blocks.append(dataclasses.replace(block, index=len(blocks) + 1))
            pages.append(dataclasses.replace(page, exercise_blocks=new_page_blocks))
        expressions.extend(item.expressions)
    exercise_name = chr(0xFF1B).join(page.exercise_name for page in pages if page.exercise_name) or base.exercise_name
    exercise_description = chr(10).join(["", ""]).join(page.exercise_description for page in pages if page.exercise_description)
    return dataclasses.replace(
        base,
        source_url=base.source_url,
        exercise_id=base.exercise_id,
        exercise_name=exercise_name,
        exercise_description=exercise_description,
        exercise_blocks=blocks,
        expressions=expressions,
        exercise_pages=pages,
    )


def prepare_audio(data: LessonData, out_dir: Path, download: bool, logger: logging.Logger) -> None:
    audio_dir = out_dir / "audio"
    used: set[str] = set()

    def unique(name: str) -> str:
        stem, suffix = Path(name).stem, Path(name).suffix
        candidate = name
        n = 2
        while candidate.lower() in used:
            candidate = f"{stem}-{n}{suffix}"
            n += 1
        used.add(candidate.lower())
        return candidate

    audio_file_by_url: dict[str, str] = {}
    for block in data.exercise_blocks:
        if not block.audio_url:
            continue
        name = unique(audio_basename(block.audio_url, f"A{block.index}_Loesungsaudio"))
        block.audio_file = f"audio/{name}"
        audio_file_by_url[block.audio_url] = block.audio_file
        if download:
            download_file(block.audio_url, audio_dir / name, logger)
    for page in data.exercise_pages:
        for block in page.exercise_blocks:
            if block.audio_url:
                block.audio_file = audio_file_by_url.get(block.audio_url, block.audio_file)
        if page.source_audio_url:
            if page.source_audio_url in audio_file_by_url:
                page.source_audio_file = audio_file_by_url[page.source_audio_url]
            else:
                name = unique(audio_basename(page.source_audio_url, f"source_audio_{page.exercise_id or 'page'}"))
                page.source_audio_file = f"audio/{name}"
                audio_file_by_url[page.source_audio_url] = page.source_audio_file
                logger.info("Source audio prepared for page=%s url=%s file=%s", page.exercise_name, page.source_audio_url, page.source_audio_file)
                if download:
                    download_file(page.source_audio_url, audio_dir / name, logger)
    for entry in data.vocab:
        if not entry.audio_url:
            continue
        name = unique(audio_basename(entry.audio_url, entry.name))
        entry.audio_file = f"audio/{name}"
        if download:
            download_file(entry.audio_url, audio_dir / name, logger)
    for entry in data.expressions:
        if entry.audio_url and not entry.audio_file:
            match = next((v for v in data.vocab if v.audio_url == entry.audio_url), None)
            entry.audio_file = match.audio_file if match else None
    vocab_by_audio = {v.audio_url: v.audio_file for v in data.vocab if v.audio_url and v.audio_file}
    for page in data.exercise_pages:
        for entry in page.expressions:
            if entry.audio_url and not entry.audio_file:
                entry.audio_file = vocab_by_audio.get(entry.audio_url)


def yaml_escape(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def render_vocab_table(vocab: list[VocabularyEntry]) -> str:
    lines = [
        '<table class="vocab-audio-table">',
        '  <colgroup>',
        '    <col style="width: 38%;">',
        '    <col style="width: 22%;">',
        '    <col style="width: 260px; min-width: 260px;">',
        '    <col style="width: 18%;">',
        '  </colgroup>',
        '  <thead><tr><th>德语</th><th>中文</th><th>音频</th><th>词形/说明</th></tr></thead>',
        '  <tbody>',
    ]
    for v in vocab:
        src = v.audio_file or v.audio_url or ""
        audio = f'<audio controls preload="none" src="{html.escape(src)}" style="width:240px; max-width:240px;"></audio>' if src else ""
        lines.extend([
            "  <tr>",
            f"    <td><strong>{html.escape(v.name)}</strong></td>",
            f"    <td>{html.escape(v.meaning)}</td>",
            f"    <td class=\"audio-cell\">{audio}</td>",
            f"    <td>{html.escape(v.sub_title)}</td>",
            "  </tr>",
        ])
    lines.extend(["  </tbody>", "</table>"])
    return "\n".join(lines)


def render_expressions_table(expressions: list[VocabularyEntry]) -> str:
    lines = [
        '<table class="expressions-audio-table">',
        '  <colgroup>',
        '    <col style="width: 45%;">',
        '    <col style="width: 25%;">',
        '    <col style="width: 260px; min-width: 260px;">',
        '  </colgroup>',
        '  <thead><tr><th>表达</th><th>中文</th><th>音频</th></tr></thead>',
        '  <tbody>',
    ]
    for expr in expressions:
        src = expr.audio_file or expr.audio_url or ""
        audio = f'<audio controls preload="none" src="{html.escape(src)}" style="width:240px; max-width:240px;"></audio>' if src else ""
        lines.extend([
            "  <tr>",
            f"    <td><strong>{html.escape(expr.name)}</strong></td>",
            f"    <td>{html.escape(expr.meaning)}</td>",
            f"    <td class=\"audio-cell\">{audio}</td>",
            "  </tr>",
        ])
    lines.extend(["  </tbody>", "</table>"])
    return "\n".join(lines)


def quote_markdown(text: str) -> str:
    if not text:
        return ""
    return "> " + text.replace("\n", "\n> ")


def render_answers_table(answers: list[str]) -> list[str]:
    if not answers:
        return ["（未找到答案。）"]
    lines = ["| # | 答案 |", "|---|------|"]
    for i, answer in enumerate(answers, 1):
        lines.append(f"| {i} | {answer} |")
    return lines


def render_markdown(data: LessonData) -> str:
    today = dt.date.today().isoformat()
    source_title = f"DW Nicos Weg {data.level} - {data.exercise_name} ({data.lesson_name})".strip()
    pages = data.exercise_pages or [ExercisePage(data.source_url, data.exercise_id, data.exercise_name, data.exercise_description, data.exercise_blocks, data.expressions)]
    lines = [
        "---",
        f"title: {yaml_escape(source_title)}",
        f"source: {yaml_escape(data.source_url)}",
        f"course: {yaml_escape('Nicos Weg (' + data.level + ')' if data.level else 'Nicos Weg')}",
        f"lesson: {yaml_escape(data.lesson_name)}",
        f"exercise: {yaml_escape(data.exercise_name + (f' (Exercise {data.exercise_id})' if data.exercise_id else ''))}",
        f"date: {today}",
        "tags:",
        "  - Deutsch",
        "  - DW",
        f"  - {data.level or 'NicosWeg'}",
        "  - NicosWeg",
        "---",
        "",
        "## 表达练习",
    ]
    if data.exercise_blocks:
        for page_index, page in enumerate(pages, 1):
            for block in page.exercise_blocks:
                if block.question:
                    prefix = f"{page_index}.{block.index}" if len(pages) > 1 else str(block.index)
                    lines += [f"> [!question]- 练习 {prefix}：{block.question}", f"> {block.question}", ""]
    else:
        lines += ["> [!question]- 本页问题", "> 请根据练习内容回答。", ""]

    lines += ["## 对话练习", ""]
    for page_index, page in enumerate(pages, 1):
        page_title = page.exercise_name or data.exercise_name
        lines += [f"### 练习页 {page_index}：{page_title}", ""]
        lines += ["#### 练习说明", "", page.exercise_description or "（未找到练习说明。）", ""]

        source_heading = "#### 阅读/原文文本" if page.exercise_kind == "reading_text" else "#### 完整填空文本"
        source_text = page.source_text_markdown.strip()
        if source_text:
            lines += [source_heading, "", source_text, ""]
        else:
            cloze_blocks = [block for block in page.exercise_blocks if block.filled_text]
            if cloze_blocks:
                lines += ["#### 完整填空文本", ""]
                for block in cloze_blocks:
                    if len(cloze_blocks) > 1:
                        lines += [f"**练习 {page_index}.{block.index}: {block.question or page_title}**", ""]
                    lines += [quote_markdown(block.filled_text), ""]
            else:
                lines += ["#### 阅读/原文文本", "", "（未找到可作为原文/对话的文本；选择题答案仅列在下方答案表中。）", ""]

        lines += ["#### 题目与答案", ""]
        for block in page.exercise_blocks:
            lines += [f"**练习 {page_index}.{block.index}: {block.question or page_title}**", ""]
            if block.description:
                lines += [f"> {block.description}", ""]
            lines += render_answers_table(block.answers)
            lines += [""]

        lines += ["#### 答题反馈音频", ""]
        source_audio = page.source_audio_file or page.source_audio_url
        if source_audio:
            lines += [f"- 原文/对话音频：![[{source_audio}]]"]
        else:
            lines += ["- （未找到原文音频；以下如有音频，仅为答题反馈音频。）"]
        answer_audio_found = False
        for block in page.exercise_blocks:
            audio_src = block.audio_file or block.audio_url
            if audio_src:
                answer_audio_found = True
                lines += [f"- 练习 {page_index}.{block.index} 答题反馈音频：![[{audio_src}]]"]
        if not answer_audio_found:
            lines += ["- （未找到答题反馈音频。）"]
        lines += ["", "---", ""]

    lines += ["## 📉 课文对话 (Manuskript)", "", data.manuscript_markdown or "（未找到课文对话。）", "", "---", ""]
    lines += ["## 📎 本课词汇表 (Wortschatz)", "", render_vocab_table(data.vocab) if data.vocab else "（未找到词汇表。）", "", "---", ""]
    lines += ["## 📑 语法要点", ""]
    if data.grammar:
        for i, item in enumerate(data.grammar, 1):
            lines += [f"### {i}. {item['name']}", "", item["text"] or "（无说明。）", ""]
    else:
        lines += ["（未找到语法要点。）", ""]
    lines += ["---", "", "## 💬 常用表达", ""]
    if data.expressions:
        lines += [render_expressions_table(data.expressions)]
    else:
        lines += ["（当前练习未提供额外常用表达；可参考上方词汇表。）"]
    links = []
    for i, page in enumerate(pages, 1):
        links.append(f"- **练习页 {i}:** [{page.exercise_name or data.exercise_name}]({page.source_url})")
    lines += ["", "---", "", "## 🔗 相关链接", "", *links, f"- **章节页面:** [{data.lesson_name}]({data.lesson_url})", "- **音频 CDN 域名:** `radiodownloaddw-a.akamaihd.net/Events/dwelle/deutschkurse/nicosweg/`", ""]
    return "\n".join(lines)

def setup_logger(log_file: Path | None) -> logging.Logger:
    logger = logging.getLogger("nicos_weg_dialogue_note")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(formatter)
    stream.setLevel(logging.INFO)
    logger.addHandler(stream)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.DEBUG)
        logger.addHandler(file_handler)
    return logger


def generate(url: str | list[str], out_dir: Path, *, download: bool = True, log_file: Path | None = None) -> Path:
    logger = setup_logger(log_file)
    logger.info("Start generating Nicos Weg note")
    urls = [url] if isinstance(url, str) else list(url)
    if not urls:
        raise ValueError("At least one DW exercise URL is required")
    logger.info("URL count: %d", len(urls))
    for i, item in enumerate(urls, 1):
        logger.info("URL %d: %s", i, item)
    logger.info("Output dir: %s", out_dir)
    try:
        parsed_urls = [parse_dw_url(item) for item in urls]
        lesson_ids = {parsed.lesson_id for parsed in parsed_urls}
        if len(lesson_ids) != 1:
            logger.error("URL lesson id mismatch: %s", sorted(lesson_ids))
            raise ValueError(f"All URLs must belong to the same lesson; got lesson ids {sorted(lesson_ids)}")
        items: list[LessonData] = []
        for item in urls:
            state, _ = load_combined_state(item, logger)
            logger.info("Apollo objects for %s: total=%d lesson=%d exercise=%d inquiry=%d knowledge=%d contentLink=%d", item, len(state), sum(k.startswith('Lesson:') for k in state), sum(k.startswith('Exercise:') for k in state), sum(k.startswith('Inquiry:') for k in state), sum(k.startswith('Knowledge:') for k in state), sum(k.startswith('ContentLink:') for k in state))
            item_data = build_lesson_data(item, state, logger)
            logger.info("Parsed lesson=%s exercise=%s exercise_id=%s blocks=%d vocab=%d grammar=%d manuscript_chars=%d", item_data.lesson_name, item_data.exercise_name, item_data.exercise_id, len(item_data.exercise_blocks), len(item_data.vocab), len(item_data.grammar), len(item_data.manuscript_markdown))
            items.append(item_data)
        data = merge_lesson_data(items)
        logger.info("Merged lesson=%s pages=%d blocks=%d vocab=%d grammar=%d manuscript_chars=%d", data.lesson_name, len(data.exercise_pages), len(data.exercise_blocks), len(data.vocab), len(data.grammar), len(data.manuscript_markdown))
        out_dir.mkdir(parents=True, exist_ok=True)
        prepare_audio(data, out_dir, download, logger)
        filename = render_note_filename(data)
        if not extract_unit_code(data):
            logger.info("Unit code not found; note filename omits unit code and internal lesson id")
        note_path = out_dir / filename
        note_path.write_text(render_markdown(data), encoding="utf-8")
        logger.info("Wrote note: %s", note_path)
        write_dialogue_prompt_cards(data, note_path, logger)
        return note_path
    except Exception:
        logger.error("Generation failed:\n%s", traceback.format_exc())
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("urls", nargs="+", help="One or more DW Learn German Nicos Weg exercise URLs from the same lesson")
    parser.add_argument("--out-dir", type=Path, default=Path.cwd(), help="Output directory for the note and audio/")
    parser.add_argument("--no-download", action="store_true", help="Do not download mp3 files; keep remote URLs")
    parser.add_argument("--log-file", type=Path, default=None, help="Debug log file path")
    args = parser.parse_args(argv)
    log_file = args.log_file
    if log_file is None:
        safe = safe_filename(args.urls[0].split("/")[-1] or "run")
        log_file = args.out_dir / ".debug-logs" / f"nicos-weg-dialogue-note-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-{safe}.log"
    note = generate(args.urls, args.out_dir, download=not args.no_download, log_file=log_file)
    print(note)
    print(f"DEBUG_LOG={log_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

