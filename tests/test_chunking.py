from backend.knowledge.rag import _chunk_text


class TestChunkText:
    def test_basic_chunking(self):
        text = "Line of text.\n" * 200  # ~3000 chars
        chunks = _chunk_text(text, "test.md")
        assert len(chunks) >= 2

    def test_section_headers(self):
        text = "# Title\nIntro\n## Diagnosis\nStep 1\n" * 50
        chunks = _chunk_text(text, "test.md")
        sections = {c["section"] for c in chunks}
        assert "diagnosis" in sections

    def test_overlap(self):
        text = "Line of text.\n" * 200
        chunks = _chunk_text(text, "test.md")
        if len(chunks) >= 2:
            last_lines_first = chunks[0]["text"].split("\n")[-3:]
            first_lines_second = chunks[1]["text"].split("\n")[:5]
            overlap = set(last_lines_first) & set(first_lines_second)
            assert len(overlap) > 0

    def test_empty_input(self):
        assert _chunk_text("", "test.md") == []

    def test_single_line(self):
        chunks = _chunk_text("Hello world", "test.md")
        assert len(chunks) == 1
        assert chunks[0]["text"] == "Hello world"

    def test_source_preserved(self):
        chunks = _chunk_text("Some text content", "my_runbook.md")
        for chunk in chunks:
            assert chunk["source"] == "my_runbook.md"

    def test_default_section_is_overview(self):
        chunks = _chunk_text("No headers here, just plain text.", "test.md")
        assert chunks[0]["section"] == "overview"

    def test_multiple_sections(self):
        # Text must be long enough to produce multiple chunks spanning sections
        text = "Intro text\n" + "x " * 400 + "\n## First\n" + "y " * 400 + "\n## Second\n" + "z " * 400
        chunks = _chunk_text(text, "test.md")
        sections = {c["section"] for c in chunks}
        assert len(sections) >= 2
