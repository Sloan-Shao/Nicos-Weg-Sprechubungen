---
name: nicos-weg-dialogue-note
description: Generate Obsidian Markdown lesson notes from DW Learn German Nicos Weg dialogue or cloze exercise URLs. Use when the user provides a learngerman.dw.com Nicos Weg exercise URL and wants the current exercise's complete solved dialogue text, Loesungsaudio answer audio, lesson vocabulary with audio, grammar points, manuscript dialogue, and common expressions formatted like their Nicos Weg Obsidian notes.
---

# Nicos Weg Dialogue Note

Use this skill to turn one or more same-lesson DW Learn German Nicos Weg exercise URLs into an Obsidian-ready lesson note plus local MP3 files. It supports dialogue, cloze, and reading-comprehension exercises; when source dialogue/reading text is available, the script also creates separate same-folder prompt-card notes for manuscript practice and exercise-page practice.

## Workflow

1. Read `references/output-format.md` if you need to inspect the exact note layout.
2. Run the bundled script from the workspace. Prefer passing the Nicos Weg vault root as `--out-dir`; the script resolves the final course/unit/lesson folder:

   ```powershell
   python "E:\workspace\Nicos-Weg-Sprechübungen\.codex\skills\nicos-weg-dialogue-note\scripts\fetch_nicos_weg_lesson.py" "DW_EXERCISE_URL_1" "DW_EXERCISE_URL_2" --out-dir "E:\workspace\Nicos-Weg-Sprechübungen"
   ```

3. Ensure every run writes a debug log. If the caller does not pass `--log-file`, the script writes one under the resolved final lesson folder's `.debug-logs/`.
4. If the script generated prompt-card files, open each split prompt-card file and translate/refine only the Chinese text in `你要表达` and `一级提示：中文意思` so it reads like natural Chinese learning goals. These two fields must contain only the corresponding Chinese meaning and must not contain the full German source sentence. Do not change German reference answers, keywords, sentence patterns, source headings, speaker names, or turn order.
5. Before reporting completion, inspect the generated main note and prompt cards for display regressions:
   - It must not contain `????`, `�`, or other replacement characters in Chinese labels.
   - It must not contain raw `<details>` or `<summary>` HTML.
   - Main note dialogue/source text must not contain residual bold-speaker artifacts such as `**Selma: **`, `**Nico: **`, or the regex `\*\*[A-ZÄÖÜẞ][^*]{0,40}: \*\*`; speaker labels must render as `**Selma:** text`.
   - Reference answers must use nested Obsidian callouts: `> > [!example]- 参考答案`.
   - In prompt cards, `你要表达` and `一级提示：中文意思` must not contain the full German answer sentence; if they still say `请补充中文意思`, replace them with a natural Chinese translation using Codex before reporting completion.
6. Report the generated main note path, every prompt-card path when present, and debug log path to the user.

## Script behavior

- Parse `/l-<lessonId>/e-<exerciseId>` from each URL. Multiple URLs are allowed only when all have the same `lessonId`; otherwise abort and log the mismatch.
- Fetch each exercise page and the related lesson pages (`lesson`, `/lm`, `/lv`, `/lg`).
- Parse `window.__APOLLO_STATE__` for exercises, inquiries, content links, knowledges, grammar, vocabulary, and manuscript data.
- Fill cloze `#p#` placeholders using discovered sub-inquiry answers when present; unresolved placeholders become `____`. For reading-comprehension pages, use `Exercise.inputText` as the source/reading text and keep multiple-choice answers only in the answer table.
- Download answer-feedback audio, source audio when DW exposes it, and vocabulary MP3s into `audio/`; if a download fails, keep the remote URL in the note and log the exception. Do not label Loesungsaudio as source/dialogue audio.
- Resolve vault output folders when `--out-dir` points at the Nicos Weg vault root:
  - Course folders are `Nicos Weg A1/` and `Nicos Weg A2/`.
  - Unit folders are named `<two-digit number> <unit name>`, for example `18 Eine neue Heimat`.
  - Each lesson gets its own folder named from the note stem, for example `DW-A1-E18-Anders-als-zu-Hause`.
  - The lesson folder contains `audio/`, the main note, and any prompt-card notes.
  - Existing matching unit folders are reused; missing unit folders are named from the DW Course `groupName` when available, then from the built-in A1/A2 unit-name map.
  - If the unit code or unit name cannot be resolved, fall back to the provided `--out-dir` and log the fallback instead of guessing.
- Generate one merged Markdown note with frontmatter, all input exercise pages in input order, source/reading text or solved cloze text, answer tables, answer-feedback audio inside each exercise-page section, one copy of the lesson manuscript, HTML vocabulary table, grammar, expressions, and links. Avoid duplicate top-level exercise-page groups.
- Name generated folders/files from the course level, detected unit code, and lesson title, not the exercise title or DW internal lesson id. Use `DW-<level>-<E## if found>-<lesson-name>.md`; if no unit code is found, omit the unit and log that fallback.
- Generate prompt-card Markdown files in the same output folder, split by purpose:
  - `<main-note-stem>-课文练习提示卡.md` contains only manuscript dialogue turns.
  - `<main-note-stem>-对话练习提示卡-01.md`, `<main-note-stem>-对话练习提示卡-02.md`, etc. each contain only one input URL's solved exercise dialogue turns.
  - Do not mix manuscript and exercise turns in one prompt-card file, and do not mix different input URLs in one exercise prompt-card file.
- Normalize DW bold speaker HTML before rendering or parsing. Inputs such as `<strong>Selma: </strong>Wir...`, `<strong>Nico:</strong> ...`, `**Nico:** ...`, `**Nico**: ...`, `Nico: ...`, and blockquoted `> **Nico**: ...` must become/read as `**Selma:** Wir...`; never leave `**Selma: **Wir...`, and do not merge a new speaker's line into the previous speaker's answer.

- If lesson `GRAMMAR` knowledge is absent, inspect same-lesson overview exercise pages with grammar-like titles such as `als`, `wie`, `比较`, `语法`, or `Nico学德语`, and use their `inputText` as fallback grammar notes.
- Log prompt-card source counts per group, for example `课文对话=17, 对话练习 1=3, 对话练习 2=3`, so missing exercise groups are visible in debug logs.
- Render prompt-card reference answers with nested Obsidian callouts, not HTML details. The expected shape is:
  ```md
  > > [!example]- 参考答案
  > > Ich wünsche mir so einen Laden.
  ```

## Important conventions

- Prefer passing the vault root to `--out-dir`; expected output is `Nicos Weg A1|A2/<NN unit name>/<DW-level-unit-lesson>/`.
- If using legacy mode, passing a final lesson folder directly is allowed; the script then writes the note, prompt cards, and `audio/` in that folder.
- The vocabulary table and common-expressions table must stay as HTML with fixed-width audio columns; Markdown tables make Obsidian audio controls too narrow or hide play buttons.
- Grammar tables should be preserved as readable HTML tables with borders and cell padding; do not flatten them into plain text columns.
- Use `<strong>` inside HTML tables instead of Markdown `**bold**`.
- Outside HTML tables, speaker names should be bolded with the colon inside the bold span and no trailing space inside bold markup: `**Speaker:** Text`, never `**Speaker: **Text`. Placeholder/answer emphasis such as `**so**`, `**wie**`, `**genauso**` is allowed.
- Prompt cards are for A1/A2 speaking practice: keep the Obsidian callout structure stable. Field rules are strict: `你要表达` and `一级提示：中文意思` contain only Chinese meaning; `二级提示：关键词` contains German keywords; `三级提示：句型` contains the German sentence pattern; `参考答案` contains the complete German answer. After generation, use the current Codex session to translate placeholder Chinese prompts such as `请补充中文意思`; do not add a separate LLM/API call to the script.
- Preserve UTF-8 Chinese text when editing generated Markdown. If a console displays Chinese as `????`, do not copy that mojibake back into files; inspect/write files with explicit UTF-8.
- Keep detailed debug logs for all project work.
- For GitHub clone operations in any future extension, use the system proxy as required by the user's project instruction.

## Validation commands

```powershell
python -m pytest "E:\workspace\Nicos-Weg-Sprechübungen\.codex\skills\nicos-weg-dialogue-note\tests\test_fetch_nicos_weg_lesson.py" -q --basetemp "E:\workspace\Nicos-Weg-Sprechübungen\.debug-logs\pytest-tmp"
# Regression covered: test_html_to_markdown_normalizes_bold_speaker_colon_with_trailing_space
python "C:\Users\shaofy\.codex\skills\.system\skill-creator\scripts\quick_validate.py" "E:\workspace\Nicos-Weg-Sprechübungen\.codex\skills\nicos-weg-dialogue-note"
```


