import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "fetch_nicos_weg_lesson.py"
spec = importlib.util.spec_from_file_location("fetch_nicos_weg_lesson", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def test_parse_dw_url_extracts_ids():
    parsed = mod.parse_dw_url("https://learngerman.dw.com/zh/%E4%BD%A0%E6%83%B3%E5%BF%B5%E4%BB%80%E4%B9%881/l-50402839/e-50411378")
    assert parsed.lesson_id == 50402839
    assert parsed.exercise_id == 50411378
    assert parsed.lang == "zh"


def test_safe_filename_keeps_german_and_chinese_readable():
    assert mod.safe_filename("你想念什么？（1） | Leben in Deutschland") == "你想念什么-1-Leben-in-Deutschland"


def test_fill_cloze_text_replaces_placeholders_and_preserves_speakers():
    text = "<p><strong>Tarek:</strong> Fehlt #p# das Essen?<br><strong>Nico:</strong> Ja, fehlt #p#.</p>"
    answers = ["dir", "mir"]
    assert mod.fill_cloze_text(text, answers) == "**Tarek:** Fehlt **dir** das Essen?\n**Nico:** Ja, fehlt **mir**."


def test_extract_inquiry_answers_from_sub_inquiries():
    state = {
        "Inquiry:1": {"subInquiries": [{"__ref": "Inquiry:2"}, {"__ref": "Inquiry:3"}]},
        "Inquiry:2": {"correctAnswers": ["dir"]},
        "Inquiry:3": {"alternatives": [{"isCorrect": True, "text": "mir"}]},
    }
    assert mod.extract_answers(state, {"__ref": "Inquiry:1"}) == ["dir", "mir"]


def test_extract_inquiry_answers_resolves_alternative_refs():
    state = {
        "Inquiry:1": {"subInquiries": [{"__ref": "Inquiry:2"}]},
        "Inquiry:2": {"inquiryText": "CONTINUOUS_TEXT", "alternatives": [{"__ref": "Alternative:9"}]},
        "Alternative:9": {"isCorrect": True, "alternativeText": "dir"},
    }
    assert mod.extract_answers(state, {"__ref": "Inquiry:1"}) == ["dir"]


def test_build_lesson_data_preserves_utf8_chinese():
    state = {
        "Lesson:1": {"id": 1, "name": "Leben in Deutschland", "language": "CHINESE", "namedUrl": "/zh/leben/l-1", "dkLearningLevel": 0, "overviewParts": []},
        "Exercise:2": {"id": 2, "name": "你想念什么？（1）", "description": "<p>说明</p>", "inquiries": []},
    }
    data = mod.build_lesson_data("https://learngerman.dw.com/zh/x/l-1/e-2", state, mod.setup_logger(None))
    assert data.exercise_name == "你想念什么？（1）"

def test_fetch_text_quotes_non_ascii_urls(monkeypatch):
    seen = {}

    class FakeHeaders:
        def get_content_charset(self):
            return "utf-8"

    class FakeResponse:
        headers = FakeHeaders()
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self):
            return "ok".encode("utf-8")

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        return FakeResponse()

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    assert mod.fetch_text("https://learngerman.dw.com/zh/ich-träume-von/l-1") == "ok"
    assert "träume" not in seen["url"]
    assert "tr%C3%A4ume" in seen["url"]

def test_render_markdown_uses_expression_practice_heading():
    data = mod.LessonData(
        source_url="https://learngerman.dw.com/zh/x/l-1/e-2",
        lang="zh",
        lesson_id=1,
        exercise_id=2,
        lesson_name="Lesson",
        lesson_url="https://learngerman.dw.com/zh/lesson/l-1",
        exercise_name="Exercise",
        exercise_description="说明",
        level="A1",
        first_publication_date="",
        overview_parts=[],
        exercise_blocks=[],
        manuscript_html="",
        manuscript_markdown="",
        vocab=[],
        grammar=[],
        expressions=[],
    )
    rendered = mod.render_markdown(data)
    assert "## 表达练习" in rendered
    assert "\n## 表达\n" not in rendered
    assert "## 💬 常用表达" in rendered


def make_lesson_data(**overrides):
    values = dict(
        source_url="https://learngerman.dw.com/zh/x/l-1/e-2",
        lang="zh",
        lesson_id=1,
        exercise_id=2,
        lesson_name="Leben in Deutschland",
        lesson_url="https://learngerman.dw.com/zh/lesson/l-1",
        exercise_name="你想念什么？（1）",
        exercise_description="说明",
        level="A1",
        first_publication_date="",
        overview_parts=[],
        exercise_blocks=[],
        manuscript_html="",
        manuscript_markdown="",
        vocab=[],
        grammar=[],
        expressions=[],
    )
    values.update(overrides)
    return mod.LessonData(**values)


def test_render_prompt_card_filename_uses_main_note_stem():
    path = Path("DW-A1-E18-未来的梦想.md")
    assert mod.render_prompt_card_filename(path).name == "DW-A1-E18-未来的梦想-对话练习提示卡.md"


def test_extract_dialogue_turns_from_manuscript_speaker_blocks():
    text = "**NICO:**\nIch wünsche mir so einen Laden.\n\n**TAREK:**\nDas ist meins."
    turns = mod.extract_dialogue_turns(text, "课文对话")
    assert [(t.source, t.speaker, t.answer) for t in turns] == [
        ("课文对话", "NICO", "Ich wünsche mir so einen Laden."),
        ("课文对话", "TAREK", "Das ist meins."),
    ]


def test_extract_dialogue_turns_from_inline_exercise_lines():
    text = "**Tarek:** Fehlt **dir** das spanische Essen?\n**Nico:** Ja, fehlt **mir**."
    turns = mod.extract_dialogue_turns(text, "对话练习")
    assert turns[0].speaker == "Tarek"
    assert turns[0].answer == "Fehlt dir das spanische Essen?"
    assert turns[1].answer == "Ja, fehlt mir."


def test_extract_dialogue_turns_supports_bold_name_then_colon_and_blockquote():
    text = "> **Tarek:** Fehlt **dir** das spanische Essen?\n> **Nico**: Ja, manchmal fehlt **mir** das spanische Essen.\nTarek: Und dir?"
    source = "".join(chr(x) for x in [0x5bf9, 0x8bdd, 0x7ec3, 0x4e60, 0x20, 0x31])
    turns = mod.extract_dialogue_turns(text, source)
    assert [(t.speaker, t.answer) for t in turns] == [
        ("Tarek", "Fehlt dir das spanische Essen?"),
        ("Nico", "Ja, manchmal fehlt mir das spanische Essen."),
        ("Tarek", "Und dir?"),
    ]


def test_collect_dialogue_turns_keeps_each_exercise_block_as_separate_source():
    exercise_source_1 = "".join(chr(x) for x in [0x5bf9, 0x8bdd, 0x7ec3, 0x4e60, 0x20, 0x31])
    exercise_source_2 = "".join(chr(x) for x in [0x5bf9, 0x8bdd, 0x7ec3, 0x4e60, 0x20, 0x32])
    data = make_lesson_data(
        manuscript_markdown="",
        exercise_blocks=[
            mod.ExerciseBlock(1, "", "", "", "**Tarek:** Fehlt dir das Essen?\n**Nico**: Ja, fehlt mir.", [], None),
            mod.ExerciseBlock(2, "", "", "", "**Tarek:** Magst du Deutschland?\n**Nico**: Ja, es gefällt mir.", [], None),
        ],
    )
    turns = mod.collect_dialogue_turns(data)
    assert [t.source for t in turns] == [exercise_source_1, exercise_source_1, exercise_source_2, exercise_source_2]
    rendered = mod.render_dialogue_prompt_card(data, turns)
    assert f"## {exercise_source_1}" in rendered
    assert f"## {exercise_source_2}" in rendered
    assert rendered.count("> [!question]- 第 1 轮：Tarek") == 2
    assert "Nico:" not in turns[0].answer


def test_merge_lesson_data_combines_same_lesson_pages_in_input_order():
    data1 = make_lesson_data(
        lesson_id=10,
        exercise_id=101,
        exercise_name="Exercise 1",
        exercise_blocks=[
            mod.ExerciseBlock(1, "Q1", "", "", "**A:** Hallo.", [], "https://example.test/A1_E18_A1.mp3")
        ],
    )
    data1.exercise_pages = [
        mod.ExercisePage(data1.source_url, data1.exercise_id, data1.exercise_name, data1.exercise_description, data1.exercise_blocks, [])
    ]
    data2 = make_lesson_data(
        source_url="https://learngerman.dw.com/zh/y/l-10/e-102",
        lesson_id=10,
        exercise_id=102,
        exercise_name="Exercise 2",
        exercise_blocks=[
            mod.ExerciseBlock(1, "Q2", "", "", "**B:** Guten Tag.", [], "https://example.test/A1_E18_A2.mp3")
        ],
    )
    data2.exercise_pages = [
        mod.ExercisePage(data2.source_url, data2.exercise_id, data2.exercise_name, data2.exercise_description, data2.exercise_blocks, [])
    ]
    merged = mod.merge_lesson_data([data1, data2])
    assert [page.exercise_name for page in merged.exercise_pages] == ["Exercise 1", "Exercise 2"]
    assert len(merged.exercise_blocks) == 2
    rendered = mod.render_markdown(merged)
    practice_page_label = "".join(chr(x) for x in [0x7ec3, 0x4e60, 0x9875])
    practice_label = "".join(chr(x) for x in [0x7ec3, 0x4e60])
    colon = chr(0xFF1A)
    assert f"### {practice_page_label} 1{colon}Exercise 1" in rendered
    assert f"**{practice_label} 1.1: Q1**" in rendered
    assert f"### {practice_page_label} 2{colon}Exercise 2" in rendered
    assert f"**{practice_label} 2.1: Q2**" in rendered

def test_merge_lesson_data_rejects_different_lesson_ids():
    data1 = make_lesson_data(lesson_id=10)
    data2 = make_lesson_data(source_url="https://learngerman.dw.com/zh/y/l-11/e-2", lesson_id=11)
    try:
        mod.merge_lesson_data([data1, data2])
    except ValueError as exc:
        assert "same lesson" in str(exc)
    else:
        raise AssertionError("Expected ValueError for mismatched lesson ids")


def test_generate_rejects_multiple_urls_with_different_lesson_ids(monkeypatch, tmp_path):
    calls = []

    def fake_load_combined_state(url, logger):
        calls.append(url)
        return ({}, "")

    monkeypatch.setattr(mod, "load_combined_state", fake_load_combined_state)
    urls = [
        "https://learngerman.dw.com/zh/a/l-10/e-101",
        "https://learngerman.dw.com/zh/b/l-11/e-102",
    ]
    try:
        mod.generate(urls, tmp_path, download=False, log_file=tmp_path / "debug.log")
    except ValueError as exc:
        assert "same lesson" in str(exc)
    else:
        raise AssertionError("Expected ValueError for mismatched lesson ids")
    assert calls == []


def test_split_prompt_card_filenames_and_content(tmp_path):
    note_path = tmp_path / "DW-A1-E18-Leben-in-Deutschland.md"
    manuscript_suffix = "".join(chr(x) for x in [0x8bfe, 0x6587, 0x7ec3, 0x4e60, 0x63d0, 0x793a, 0x5361])
    exercise_suffix = "".join(chr(x) for x in [0x5bf9, 0x8bdd, 0x7ec3, 0x4e60, 0x63d0, 0x793a, 0x5361])
    assert mod.render_manuscript_prompt_card_filename(note_path).name == f"DW-A1-E18-Leben-in-Deutschland-{manuscript_suffix}.md"
    assert mod.render_exercise_prompt_card_filename(note_path, 2).name == f"DW-A1-E18-Leben-in-Deutschland-{exercise_suffix}-02.md"

    page = mod.ExercisePage(
        "https://learngerman.dw.com/zh/x/l-1/e-2",
        2,
        "Exercise",
        "",
        [mod.ExerciseBlock(1, "", "", "", "**Tarek:** Hallo.\n**Nico:** Guten Tag.", [], None)],
        [],
    )
    data = make_lesson_data(
        manuscript_markdown="**NICO:**\nIch w?nsche mir so einen Laden.",
        exercise_pages=[page],
        exercise_blocks=page.exercise_blocks,
    )
    paths = mod.write_dialogue_prompt_cards(data, note_path, mod.setup_logger(None))
    manuscript_name = mod.render_manuscript_prompt_card_filename(note_path).name
    exercise_name = mod.render_exercise_prompt_card_filename(note_path, 1).name
    names = [path.name for path in paths]
    assert manuscript_name in names
    assert exercise_name in names
    manuscript_text = (tmp_path / manuscript_name).read_text(encoding="utf-8")
    exercise_text = (tmp_path / exercise_name).read_text(encoding="utf-8")
    manuscript_heading = "## " + "".join(chr(x) for x in [0x8bfe, 0x6587, 0x5bf9, 0x8bdd])
    exercise_heading = "## " + "".join(chr(x) for x in [0x5bf9, 0x8bdd, 0x7ec3, 0x4e60])
    assert manuscript_heading in manuscript_text
    assert exercise_heading not in manuscript_text
    assert exercise_heading + " 1" in exercise_text
    assert manuscript_heading not in exercise_text

def test_render_dialogue_prompt_card_contains_callout_keywords_pattern_details():
    turns = mod.extract_dialogue_turns("**NICO:**\nIch wünsche mir so einen Laden.", "课文对话")
    rendered = mod.render_dialogue_prompt_card(make_lesson_data(), turns)
    assert "## 课文对话" in rendered
    assert "> [!question]- 第 1 轮：NICO" in rendered
    assert "二级提示：关键词" in rendered
    assert "三级提示：句型" in rendered
    assert "Ich wünsche mir ..." in rendered
    assert "> > [!example]- 参考答案" in rendered
    assert "<details>" not in rendered
    assert "<summary>" not in rendered
    assert "????" not in rendered
    assert "Ich wünsche mir so einen Laden." in rendered


def test_write_dialogue_prompt_card_skips_without_dialogue(tmp_path):
    data = make_lesson_data()
    note_path = tmp_path / "note.md"
    result = mod.write_dialogue_prompt_card(data, note_path, mod.setup_logger(None))
    assert result is None
    assert not (tmp_path / "note-对话练习提示卡.md").exists()


def test_extract_unit_code_from_audio_urls_is_dynamic():
    data = make_lesson_data(
        exercise_blocks=[
            mod.ExerciseBlock(
                index=1,
                question="",
                description="",
                raw_text="",
                filled_text="",
                answers=[],
                audio_url="https://example.test/kurse/a1/A1_E18_L2_S5_A1_Loesungsaudio.mp3",
            )
        ]
    )
    assert mod.extract_unit_code(data) == "E18"

    other = make_lesson_data(
        exercise_blocks=[
            mod.ExerciseBlock(
                index=1,
                question="",
                description="",
                raw_text="",
                filled_text="",
                answers=[],
                audio_url="https://example.test/kurse/a1/A1-E07-L2-S1-A1-Loesungsaudio.mp3",
            )
        ]
    )
    assert mod.extract_unit_code(other) == "E07"


def test_render_note_filename_uses_unit_and_lesson_not_internal_id_or_exercise_title():
    data = make_lesson_data(
        lesson_id=50402839,
        level="A1",
        lesson_name="Leben in Deutschland",
        exercise_name="你想念什么？（1）",
        exercise_blocks=[
            mod.ExerciseBlock(
                index=1,
                question="",
                description="",
                raw_text="",
                filled_text="",
                answers=[],
                audio_url="https://example.test/A1_E18_L2_S5_A1_Loesungsaudio.mp3",
            )
        ],
    )
    filename = mod.render_note_filename(data)
    assert filename == "DW-A1-E18-Leben-in-Deutschland.md"
    assert "50402839" not in filename
    assert "你想念什么" not in filename


def test_render_note_filename_falls_back_without_unit_and_still_omits_internal_id():
    data = make_lesson_data(
        lesson_id=50402839,
        level="A1",
        lesson_name="Leben in Deutschland",
        exercise_name="你想念什么？（1）",
    )
    assert mod.render_note_filename(data) == "DW-A1-Leben-in-Deutschland.md"


def test_render_grammar_html_preserves_table_readability():
    html = """
    <p>第二格：<em>Schmeckt dir die Paella?</em></p>
    <table>
      <tr><th>第一格</th><th>第四格</th><th>第三格</th></tr>
      <tr><td>ich</td><td>mich</td><td>mir</td></tr>
    </table>
    """
    rendered = mod.html_to_markdown(html, bold_placeholders=True, preserve_tables=True)
    assert '<table class="grammar-table"' in rendered
    assert 'border="1"' in rendered
    assert 'cellpadding="6"' in rendered
    assert "<th>第一格</th>" in rendered
    assert "<th>第四格</th>" in rendered
    assert "<th>第三格</th>" in rendered
    assert "<td>ich</td>" in rendered
    assert "<td>mir</td>" in rendered


def test_render_expressions_table_uses_fixed_audio_column_html():
    expressions = [
        mod.VocabularyEntry(
            name="jemandem fehlen",
            meaning="想念",
            sub_title="",
            audio_url="audio/BAKU-A1-fehlen.mp3",
        )
    ]
    rendered = mod.render_expressions_table(expressions)
    assert '<table class="expressions-audio-table">' in rendered
    assert '<col style="width: 260px; min-width: 260px;">' in rendered
    assert '<strong>jemandem fehlen</strong>' in rendered
    assert 'style="width:240px; max-width:240px;"' in rendered
    assert "| 表达 | 中文 | 音频 |" not in rendered


def test_repair_indented_grammar_table_converts_pseudo_table_to_html():
    nominative = "".join(chr(x) for x in [0x7b2c, 0x4e00, 0x683c])
    accusative = "".join(chr(x) for x in [0x7b2c, 0x56db, 0x683c])
    dative = "".join(chr(x) for x in [0x7b2c, 0x4e09, 0x683c])
    next_heading = "".join(chr(x) for x in [0x4e0b, 0x4e00, 0x8282])
    markdown = f"""{dative}?*Schmeckt **dir** die Paella?*

			{nominative}
			{accusative}
			{dative}

			ich
			mich
			mir

			du
			dich
			dir

### 2. {next_heading}"""
    rendered = mod.repair_indented_grammar_tables(markdown)
    assert '<table class="grammar-table"' in rendered
    assert f'<th style="text-align:left; min-width: 120px;">{nominative}</th>' in rendered
    assert '<td style="min-width: 120px;">ich</td>' in rendered
    assert '<td style="min-width: 120px;">mir</td>' in rendered
    assert f"\t\t\t{nominative}" not in rendered
    assert f"### 2. {next_heading}" in rendered


def test_reading_input_text_becomes_source_text_and_prompt_turns():
    state = {
        "Lesson:1": {"id": 1, "name": "Lesson", "language": "CHINESE", "namedUrl": "/zh/lesson/l-1", "dkLearningLevel": 0, "overviewParts": []},
        "Exercise:2": {
            "id": 2,
            "name": "??",
            "description": "<p>?????</p>",
            "inputType": "TEXT",
            "inputText": "<p><strong>Selma:</strong> Ich vermisse Syrien.<br><strong>Ibrahim:</strong> Mir fehlt Syrien.</p>",
            "inquiries": [{"__ref": "Inquiry:3"}],
        },
        "Inquiry:3": {"inquiryType": "ASSOCIATION", "inquiryText": "W?hl die richtige Aussage.", "text": "", "subInquiries": [{"__ref": "Inquiry:4"}]},
        "Inquiry:4": {"alternatives": [{"__ref": "Alternative:5"}]},
        "Alternative:5": {"isCorrect": True, "alternativeText": "Ibrahim findet Deutsch lernen sehr wichtig."},
    }
    data = mod.build_lesson_data("https://learngerman.dw.com/zh/x/l-1/e-2", state, mod.setup_logger(None))
    page = data.exercise_pages[0]
    assert page.exercise_kind == "reading_text"
    assert "Ich vermisse Syrien" in page.source_text_markdown
    assert data.exercise_blocks[0].filled_text == ""
    assert data.exercise_blocks[0].answers == ["Ibrahim findet Deutsch lernen sehr wichtig."]
    turns = mod.collect_exercise_page_turns(page)
    assert [(t.speaker, t.answer) for t in turns] == [("Selma", "Ich vermisse Syrien."), ("Ibrahim", "Mir fehlt Syrien.")]


def test_render_markdown_groups_each_exercise_page_once_without_duplicate_audio_section():
    page1 = mod.ExercisePage(
        "https://learngerman.dw.com/zh/x/l-1/e-2", 2, "??", "?????",
        [mod.ExerciseBlock(1, "W?hl die richtige Aussage.", "", "", "", ["???"], "https://example.test/answer.mp3")],
        [], input_text="<p>x</p>", input_type="TEXT", exercise_kind="reading_text", source_text_markdown="**Selma:** Hallo.",
    )
    page2 = mod.ExercisePage(
        "https://learngerman.dw.com/zh/y/l-1/e-3", 3, "????", "???",
        [mod.ExerciseBlock(1, "W?hl die fehlenden W?rter.", "", "<p>#p#</p>", "**Selma:** **so**", ["so"], "https://example.test/answer2.mp3")],
        [], input_type="VIDEO", exercise_kind="cloze_text", source_text_markdown="**Selma:** **so**",
    )
    data = make_lesson_data(exercise_pages=[page1, page2], exercise_blocks=[*page1.exercise_blocks, *page2.exercise_blocks], exercise_name="???????")
    rendered = mod.render_markdown(data)
    practice_page_label = "".join(chr(x) for x in [0x7ec3, 0x4e60, 0x9875])
    reading_heading = "#### " + "".join(chr(x) for x in [0x9605, 0x8bfb, 0x2f, 0x539f, 0x6587, 0x6587, 0x672c])
    cloze_heading = "#### " + "".join(chr(x) for x in [0x5b8c, 0x6574, 0x586b, 0x7a7a, 0x6587, 0x672c])
    old_audio_heading = "### " + chr(0x1f3a7) + " " + "".join(chr(x) for x in [0x7ec3, 0x4e60, 0x89e3, 0x7b54, 0x97f3, 0x9891])
    no_source_audio = "".join(chr(x) for x in [0x672a, 0x627e, 0x5230, 0x539f, 0x6587, 0x97f3, 0x9891])
    assert rendered.count(f"### {practice_page_label} 1") == 1
    assert rendered.count(f"### {practice_page_label} 2") == 1
    assert old_audio_heading not in rendered
    assert reading_heading in rendered
    assert cloze_heading in rendered
    assert no_source_audio in rendered
    assert "???????" in rendered


def test_fallback_grammar_extracts_input_text_from_grammar_exercise():
    state = {
        "Lesson:1": {
            "id": 1,
            "name": "Lesson",
            "language": "CHINESE",
            "namedUrl": "/zh/lesson/l-1",
            "dkLearningLevel": 0,
            "overviewParts": [
                {"targetId": 9, "lessonPart": "EXERCISE", "target": {"name": "?als?wie????"}},
            ],
        },
        "Exercise:2": {"id": 2, "name": "Main", "description": "", "inquiries": []},
        "Exercise:9": {"id": 9, "name": "?als?wie????", "inputText": "<p>????????+ <strong>als</strong></p><p>genauso + ??? + <strong>wie</strong></p>"},
    }
    data = mod.build_lesson_data("https://learngerman.dw.com/zh/x/l-1/e-2", state, mod.setup_logger(None))
    assert len(data.grammar) == 1
    assert data.grammar[0]["name"] == "?als?wie????"
    assert "**als**" in data.grammar[0]["text"]
    assert "**wie**" in data.grammar[0]["text"]


def test_exercise_source_audio_is_distinct_from_answer_audio():
    exercise = {"audios": [{"mp3Src": "https://example.test/source.mp3"}], "contentLinks": []}
    assert mod.exercise_source_audio_url(exercise) == "https://example.test/source.mp3"
    block = mod.ExerciseBlock(1, "Q", "", "", "", [], "https://example.test/answer.mp3")
    assert block.audio_kind == "answer_audio"


def test_html_to_markdown_normalizes_bold_speaker_colon_with_trailing_space():
    html = "<p><strong>Selma: </strong>Wir essen #p# viele Regeln.</p>"
    rendered = mod.fill_cloze_text(html, ["so"])
    assert rendered.startswith("**Selma:** Wir essen")
    assert "**Selma: **" not in rendered
    assert "**so**" in rendered
