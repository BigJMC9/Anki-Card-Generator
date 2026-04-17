import os
from pathlib import Path

AppTitle = "Japanese Anki Deck Builder"

AppDir = Path(os.getenv("ANKI_APP_DIR", "./anki_workspace")).expanduser().resolve()
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
- Prefer canonical kanji with okurigana when visible (for example: 食べる, 行きます).
- confidence must be between 0 and 1.
- If kana is uncertain, do your best but keep visible_text exact.
- Do not include duplicates.
""".strip()
