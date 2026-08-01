from app.knowledge.text_chunker import TextChunker


def test_chunk_empty_text():
    chunker = TextChunker()
    assert chunker.chunk("") == []
    assert chunker.chunk("   \n\t ") == []


def test_chunk_short_text():
    chunker = TextChunker()
    short_text = "This is a short text."
    result = chunker.chunk(short_text)
    assert len(result) == 1
    assert result[0] == "This is a short text."


def test_chunk_short_text_with_whitespace():
    chunker = TextChunker()
    text = "  Hello World  \n"
    result = chunker.chunk(text)
    assert len(result) == 1
    assert result[0] == "Hello World"


def test_chunk_long_text_and_overlap():
    chunker = TextChunker()
    # 2500文字のテキスト作成
    text = "A" * 2500
    chunks = chunker.chunk(text)

    # 1200文字制限・ステップ1000（1200 - 200）で進む
    # Chunk 0: 0 ~ 1200
    # Chunk 1: 1000 ~ 2200
    # Chunk 2: 2000 ~ 2500
    assert len(chunks) == 3
    assert len(chunks[0]) == 1200
    assert len(chunks[1]) == 1200
    assert len(chunks[2]) == 500


def test_chunk_overlap_content():
    chunker = TextChunker()
    # 識別可能なインデックス文字列を作成
    part1 = "A" * 1000
    part_overlap = "B" * 200
    part2 = "C" * 1000

    text = part1 + part_overlap + part2  # 全体で2200文字
    chunks = chunker.chunk(text)

    assert len(chunks) == 2
    # chunk 0 は part1 (1000) + part_overlap (200)
    assert chunks[0] == part1 + part_overlap
    # chunk 1 は part_overlap (200) + part2 (1000)
    assert chunks[1] == part_overlap + part2
    # 重複部分が両方のチャンクに含まれることを確認
    assert chunks[0][-200:] == part_overlap
    assert chunks[1][:200] == part_overlap
