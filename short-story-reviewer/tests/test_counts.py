from reviewer import counts


def run(*paras):
    return counts.count_story(list(paras))


def test_lower_case_speech_only_counts_opening_quotes():
    c = run('"The pipe," said he.', 'He said, "the dog is here."', 'She called: "come in."')
    hits = c["speech_opened_lower_case_after_comma_or_colon"]
    assert hits["count"] == 2
    assert 'He said, "the' in hits["examples"][0]


def test_speech_verbs_other_than_said():
    c = run('"Go," she whispered.', '"No," he said.', '"Why?" asked Tom.')
    assert c["speech_verbs"]["said"] == 1
    assert c["speech_verbs"]["other"] == {"whispered": 1, "asked": 1}


def test_exclamations_outside_speech_only():
    c = run('"Stop!" she cried. It was over!', '"Yes!"')
    assert c["exclamation_marks_outside_speech"]["count"] == 1


def test_ellipses_split_by_speech_and_narration():
    c = run('"Well…" she said. He waited...')
    assert c["ellipses"]["in_speech"]["count"] == 1
    assert c["ellipses"]["in_narration"]["count"] == 1


def test_filter_verbs_ignore_speech():
    c = run('She felt cold and noticed the door. "I realised," he said.')
    assert c["filter_verbs"]["by_verb"] == {"feel": 1, "notice": 1}


def test_name_variants():
    c = run("Then came Framton again.", "They saw Framton leave.", "and Frampton ran.")
    forms = [set(v["forms"]) for v in c["name_variants"]]
    assert {"Framton", "Frampton"} in forms


def test_quotation_mark_mix():
    c = run('"Straight," she said. “Curly,” he said.')
    assert c["quotation_marks"]["mixed"] is True


def test_single_quote_speech_with_apostrophes():
    c = run("‘I don’t know,’ she said. ‘It’s late!’")
    assert c["speech_quotation_style"] == "single"
    assert c["exclamation_marks_outside_speech"]["count"] == 0


def test_tense_shift_candidates():
    c = run(
        "He walked to the door and opened it. She waited outside.",
        "The wind howled. He turns and looks at her.",
    )
    shifts = c["tense"]["candidate_shifts"]
    assert c["tense"]["dominant_in_narration"] == "past"
    assert shifts["count"] == 1
    assert "He turns and looks at her." in shifts["examples"][0]


def test_summary_lines_render():
    lines = counts.summary_lines(run("A plain sentence was here."))
    assert any(line.startswith("Candidate tense shifts") for line in lines)
