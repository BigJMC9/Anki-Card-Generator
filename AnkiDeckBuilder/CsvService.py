import csv
import io
import sqlite3
from typing import Tuple

from AnkiDeckBuilder.DatabaseService import AddCard


def ImportCsvCards(connection: sqlite3.Connection, deckId: str, file) -> Tuple[int, int]:
    content = file.getvalue().decode("utf-8")
    reader = csv.DictReader(io.StringIO(content))
    added = 0
    skipped = 0
    for row in reader:
        isAdded = AddCard(
            connection,
            deckId,
            {
                "kanji": row.get("kanji", ""),
                "kana": row.get("kana", ""),
                "english": row.get("english", ""),
                "notes": row.get("notes", ""),
                "source_text": row.get("source_text", ""),
                "schema_key": row.get("schema_key", "kana_kanji_front_english_back"),
                "media_type": row.get("media_type", "none"),
                "media_files": [],
                "tags": [tag.strip() for tag in row.get("tags", "").split(",") if tag.strip()],
                "dictionary_entry_id": row.get("dictionary_entry_id", ""),
                "dictionary_headword": row.get("dictionary_headword", ""),
                "dictionary_reading": row.get("dictionary_reading", ""),
                "dictionary_gloss": row.get("dictionary_gloss", ""),
                "dictionary_pos": row.get("dictionary_pos", ""),
                "verb_type": row.get("verb_type", ""),
                "word_form": row.get("word_form", "dictionary"),
            },
        )
        added += int(isAdded)
        skipped += int(not isAdded)
    return added, skipped
