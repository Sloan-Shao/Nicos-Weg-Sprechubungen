# Output Format Reference

Generate notes in this order.

## File and folder naming

File and folder names use the course level, detected unit code, and lesson title:

- Preferred: `DW-<level>-<E##>-<lesson-name>.md`, e.g. `DW-A1-E18-Leben-in-Deutschland.md`.
- Fallback when no unit code is detectable: `DW-<level>-<lesson-name>.md`.
- Do not include DW internal ids such as `50402839` or exercise titles such as `你想念什么？（1）` in file/folder names.
- When multiple URLs are provided, they must belong to the same DW lesson id. Keep one lesson-level output folder and one merged main note.

## Main note

1. YAML frontmatter with `title`, `source`, `course`, `lesson`, `exercise`, `date`, and tags.
2. `## 表达练习` with Obsidian callout questions from all exercise inquiries.
3. `## 对话练习` with one complete group per input URL; do not create a separate repeated audio group:
   - `### 练习页 1：<exercise name>`
   - `#### 练习说明`
   - `#### 阅读/原文文本` for reading `Exercise.inputText`, or `#### 完整填空文本` for solved cloze `Inquiry.text`.
   - `#### 题目与答案` for questions and answer tables.
   - `#### 答题反馈音频` for Loesungsaudio/answer-feedback audio. If source audio is absent, explicitly say it is not source/dialogue audio.
4. `## 📉 课文对话 (Manuskript)`
   - Speaker names bolded as `**Speaker:** Text`.
   - Normalize DW HTML such as `<strong>Selma: </strong>Wir...`; do not output residual artifacts like `**Selma: **Wir...`.
   - DW vocabulary placeholders bolded when present in the source manuscript.
5. `## 📎 本课词汇表 (Wortschatz)`
   - Use HTML table, not Markdown table.
   - Use `<strong>` for German terms.
   - Use `<audio controls preload="none" src="audio/name.mp3" style="width:240px; max-width:240px;"></audio>` in the audio column.
6. `## 📑 语法要点`
   - Include each DW `GRAMMAR` knowledge item in lesson order.
   - If there is no `GRAMMAR` knowledge, use grammar-like same-lesson exercise `inputText` such as als/wie comparison summaries.
   - Preserve grammar `<table>` content as readable HTML tables with borders, padding, and full-width layout.
7. `## 💬 常用表达`
   - Prefer vocabulary items attached to the current exercise page(s).
   - Use an HTML table with a fixed-width audio column.
8. `## 🔗 相关链接`
   - Include every input exercise URL, the lesson URL, and DW audio CDN note.

If a section is unavailable in the DW page state, keep the heading and write a short Chinese placeholder such as `（未找到课文对话。）`.

## Prompt-card files

Prompt cards are split into separate same-folder Markdown files. Do not generate the old combined `<stem>-对话练习提示卡.md` file.

### 1. Manuscript prompt card

Create only when recognizable turns exist in `课文对话 / Manuskript`:

`<主文件名去掉.md>-课文练习提示卡.md`

This file contains only manuscript turns and must not contain `## 对话练习` sections from exercise pages.

### 2. Exercise prompt cards

Create one file per input URL when that URL has recognizable source/solved dialogue turns:

- `<主文件名去掉.md>-对话练习提示卡-01.md`
- `<主文件名去掉.md>-对话练习提示卡-02.md`

Each file contains only the source exercise turns from the corresponding input URL: reading `Exercise.inputText` when present, otherwise solved cloze text. Do not mix manuscript turns into these files. Do not mix turns from different input URLs.

Do not create empty prompt-card files. If no turns are found, keep only the other generated files and write a clear skipped reason to the debug log.

Prompt-card structure uses Obsidian callouts and nested reference-answer callouts, never raw `<details>` / `<summary>`.

Within each prompt-card turn, field content is fixed:

- `你要表达`: only the Chinese meaning of the German answer; never include the full German source sentence.
- `一级提示：中文意思`: only the same/natural Chinese meaning; never include the full German source sentence.
- `二级提示：关键词`: German keywords only.
- `三级提示：句型`: German sentence-pattern hint only.
- `参考答案`: the complete German answer.

The script may emit the placeholder `请补充中文意思` for the Chinese fields. Before delivery, the running Codex agent must replace those placeholders with natural Chinese translations without changing German keywords, sentence patterns, or reference answers. Do not add a separate LLM/API dependency to the script for this translation.

Speaker parsing must treat `**Nico:**`, `**Nico**:`, `Nico:`, `> **Nico**:`, and HTML-converted `**Selma: **Wir...` variants as speaker starts, not as continuation text. Render normalized speaker labels as `**Nico:** text`, with the colon inside bold markup and no trailing space before the closing `**`.

## Display QA requirements

- Main notes and prompt cards must not contain `????`, `�`, or mojibake in Chinese labels such as `参考答案`.
- Main exercise/source text must not contain residual bold-speaker artifacts matching examples like `**Selma: **`, `**Ibrahim: **`, `**Aya: **`, `**Nico: **`, or `**Tarek: **`; only normal answer emphasis like `**so**` is allowed.
- Reference-answer headings must appear exactly as `> > [!example]- 参考答案`.
- Prompt-card `你要表达` and `一级提示：中文意思` must not contain the full German reference answer.
- Do not use raw `<details>` / `<summary>` for reference answers inside callouts.
- Vocabulary and common-expression audio columns must stay wide enough for Obsidian playback controls.
- When inspecting or rewriting generated Markdown on Windows, read and write with explicit UTF-8; do not paste Chinese text from a garbled console.

