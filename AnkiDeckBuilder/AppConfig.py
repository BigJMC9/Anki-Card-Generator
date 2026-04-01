from pathlib import Path

AppTitle = "Japanese Anki Deck Builder"

AppDir = Path("./anki_workspace")
CollectionsDir = AppDir / "collections"
MediaDir = AppDir / "media"
TempDir = AppDir / "tmp"
DatabasePath = AppDir / "app.db"
ExportDir = AppDir / "exports"

DefaultModel = "gpt-4o"

SupportedImageExtensions = {".png", ".jpg", ".jpeg", ".webp"}
SupportedVideoExtensions = {".mp4", ".webm", ".mov"}
SupportedAudioExtensions = {".mp3", ".wav", ".m4a", ".ogg"}

CardSchemas = {
    "kana_kanji_front_english_back": {
        "Label": "Front: Hiragana/Katakana + Kanji | Back: English",
        "FrontFields": ["kana", "kanji"],
        "BackFields": ["english"],
    },
    "kanji_front_kana_english_back": {
        "Label": "Front: Kanji | Back: Hiragana/Katakana + English",
        "FrontFields": ["kanji"],
        "BackFields": ["kana", "english"],
    },
    "kanji_okurigana_front_reading_english_back": {
        "Label": "Front: Kanji With Okurigana | Back: Full Reading + English",
        "FrontFields": ["kanji"],
        "BackFields": ["kana", "english"],
    },
    "kana_front_kanji_english_back": {
        "Label": "Front: Hiragana/Katakana | Back: Kanji + English",
        "FrontFields": ["kana"],
        "BackFields": ["kanji", "english"],
    },
    "english_front_japanese_back": {
        "Label": "Front: English | Back: Kanji + Hiragana/Katakana",
        "FrontFields": ["english"],
        "BackFields": ["kanji", "kana"],
    },
}

NoteModelId = 1894375291

SystemPrompt = """
You extract Japanese study cards from source text or OCR text.
Return only valid JSON.
Each card must be atomic and unambiguous.
Prefer one concept per card.
Use this schema:
{
  "cards": [
    {
      "kanji": "",
      "kana": "",
      "english": "",
      "notes": "",
      "source_text": "",
      "tags": ["..."]
    }
  ]
}
Rules:
- kana should contain hiragana or katakana reading.
- kanji may be blank if the word truly has no kanji form.
- english should be short and natural.
- source_text should be the exact source span when possible.
- skip cards that are duplicates, unclear, or not useful vocabulary.
""".strip()

ImageOcrPrompt = """
Read the image carefully and extract Japanese words or short phrases that are clearly visible.
Return only valid JSON with this schema:
{
  "items": [
    {
      "visible_text": "",
      "kanji": "",
      "kana": "",
      "english": "",
      "confidence": 0.0
    }
  ]
}
Rules:
- Only include Japanese text that is actually visible in the image.
- confidence must be between 0 and 1.
- If kana or english are uncertain, do your best but keep visible_text exact.
- Do not include duplicates.
""".strip()
