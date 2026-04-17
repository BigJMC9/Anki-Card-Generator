from __future__ import annotations

import argparse
import json
import mimetypes
import os
import random
import shutil
import sqlite3
import sys
import time
import traceback
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if "ANKI_APP_DIR" not in os.environ:
    os.environ["ANKI_APP_DIR"] = str((PROJECT_ROOT / "anki_workspace").resolve())

from dotenv import load_dotenv

from AnkiDeckBuilder.AppConfig import (
    AppTitle,
    CardSchemas,
    DefaultModel,
    MediaDir,
    SupportedAudioExtensions,
    SupportedImageExtensions,
    SupportedVideoExtensions,
)
from AnkiDeckBuilder.CsvService import ImportCsvCards
from AnkiDeckBuilder.DatabaseService import (
    AddCard,
    AddGlobalCard,
    CountCardsInDeck,
    CountGlobalCards,
    CreateCollection,
    CreateDeck,
    DeckHasCandidate,
    DeckHasKanjiWordForm,
    DecodeJsonStringList,
    DeleteCardsByIds,
    DeleteGlobalCardsByIds,
    GetDashboardRows,
    GetDeckCardCounts,
    GetDeckCards,
    GetTotalCardCount,
    GetTotalDeckCount,
    ImportDeckCardsToGlobal,
    ImportGlobalCardsToDeck,
    ListCollections,
    ListDecks,
    ListGlobalCards,
    OpenDatabaseConnection,
    RenameCollection,
    RenameDeck,
    UpdateCardContent,
    UpdateCardField,
    UpdateCardMedia,
    UpdateCardsSchemaByIds,
)
from AnkiDeckBuilder.ExportService import ExportDeckPackage
from AnkiDeckBuilder.JamdictService import (
    BuildCardFromDictionaryEntry,
    BuildConjugatedForms,
    BuildGlobalCardFromDictionaryEntry,
    ConjugateVerbSurface,
    FormatDictionaryEntryOption,
    GetDictionaryEntryById,
    IsVerbEntry,
    LooksLikePoliteMasuSurface,
    ResolveBestDictionaryEntry,
    SearchDictionaryEntries,
    VerbFormLabels,
    VerbTypeLabels,
)
from AnkiDeckBuilder.OpenAiService import ExtractCardsFromImages, GetOpenAiClient
from AnkiDeckBuilder.Pages import (
    BuildScanCandidateNote,
    ExpandExtractedScanCandidates,
    ParseCommaSeparatedTags,
)
from AnkiDeckBuilder.WorkspaceService import EnsureWorkspaceDirectories


load_dotenv(PROJECT_ROOT / ".env")


_CONNECTION: Optional[sqlite3.Connection] = None

PRACTICE_BASE_CORRECT_POINTS = 10
PRACTICE_INCORRECT_PENALTY_POINTS = 2
PRACTICE_BUCKET_LABELS = {
    "ichidan": "Ichidan",
    "godan": "Godan",
    "i_adj": "I-adjective (い)",
    "na_adj": "Na-adjective (な)",
}
GODAN_E_ROW_MAP = {
    "う": "え",
    "く": "け",
    "ぐ": "げ",
    "す": "せ",
    "つ": "て",
    "ぬ": "ね",
    "ぶ": "べ",
    "む": "め",
    "る": "れ",
}
GODAN_A_ROW_MAP = {
    "う": "わ",
    "く": "か",
    "ぐ": "が",
    "す": "さ",
    "つ": "た",
    "ぬ": "な",
    "ぶ": "ば",
    "む": "ま",
    "る": "ら",
}


@dataclass
class LocalInputFile:
    name: str
    type: str
    _data: bytes

    def getbuffer(self) -> memoryview:
        return memoryview(self._data)

    def getvalue(self) -> bytes:
        return self._data


def get_connection() -> sqlite3.Connection:
    global _CONNECTION
    if _CONNECTION is None:
        EnsureWorkspaceDirectories()
        _CONNECTION = OpenDatabaseConnection()
    return _CONNECTION


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def normalize_search_text(value: Any) -> str:
    return "".join(normalize_text(value).lower().split())


def normalize_string_list(values: Any) -> List[str]:
    result: List[str] = []
    for raw in values or []:
        text = normalize_text(raw)
        if text and text not in result:
            result.append(text)
    return result


def parse_tags(value: Any) -> List[str]:
    if isinstance(value, list):
        return normalize_string_list(value)
    return ParseCommaSeparatedTags(normalize_text(value))


def get_card_text(card: Any, field_name: str) -> str:
    try:
        value = card[field_name]
    except Exception:
        if isinstance(card, dict):
            value = card.get(field_name, "")
        else:
            value = ""
    return normalize_text(value)


def build_card_face_text(card: Any, field_names: List[str]) -> str:
    values: List[str] = []
    for field_name in field_names:
        text = get_card_text(card, field_name)
        if text and text not in values:
            values.append(text)
    return " | ".join(values)


def build_practice_prompt(card: Any) -> str:
    base_word = get_card_text(card, "dictionary_headword") or get_card_text(card, "kanji")
    base_reading = get_card_text(card, "dictionary_reading") or get_card_text(card, "kana")
    if base_word and base_reading and base_word != base_reading:
        return f"{base_word} [{base_reading}]"
    return base_word or base_reading


def build_practice_hint(card: Any) -> str:
    return get_card_text(card, "dictionary_gloss") or get_card_text(card, "english")


def detect_practice_verb_bucket(card: Any) -> str:
    verb_type = get_card_text(card, "verb_type")
    if verb_type in {"ichidan", "godan"}:
        return verb_type

    pos_text = get_card_text(card, "dictionary_pos").lower()
    if "ichidan verb" in pos_text:
        return "ichidan"
    if "godan verb" in pos_text:
        return "godan"
    return ""


def detect_practice_verb_type(card: Any) -> str:
    verb_type = get_card_text(card, "verb_type")
    if verb_type in {"ichidan", "godan", "suru", "suru_noun", "kuru"}:
        return verb_type

    pos_text = get_card_text(card, "dictionary_pos").lower()
    if "kuru verb" in pos_text:
        return "kuru"
    if "noun or participle which takes the aux. verb suru" in pos_text:
        return "suru_noun"
    if "suru verb" in pos_text:
        return "suru"
    if "ichidan verb" in pos_text:
        return "ichidan"
    if "godan verb" in pos_text:
        return "godan"

    dictionary_reading = get_card_text(card, "dictionary_reading") or get_card_text(card, "kana")
    dictionary_headword = get_card_text(card, "dictionary_headword") or get_card_text(card, "kanji")
    if dictionary_reading.endswith("する") or dictionary_headword.endswith("する"):
        return "suru"
    if dictionary_reading.endswith("くる") or dictionary_headword.endswith("来る"):
        return "kuru"
    return ""


def detect_practice_adjective_bucket(card: Any) -> str:
    pos_text = get_card_text(card, "dictionary_pos").lower()
    if "adjective (keiyoushi)" in pos_text or "i-adjective" in pos_text:
        return "i_adj"
    if "adjectival noun" in pos_text or "adjectival nouns" in pos_text or "na-adjective" in pos_text:
        return "na_adj"

    check_text = get_card_text(card, "dictionary_reading") or get_card_text(card, "kana") or get_card_text(card, "kanji")
    if check_text.endswith("い") and not check_text.endswith("ない"):
        return "i_adj"
    return ""


def build_practice_dedupe_key(card: Any, bucket: str) -> str:
    dictionary_entry_id = get_card_text(card, "dictionary_entry_id")
    if dictionary_entry_id:
        return f"{dictionary_entry_id}:{bucket}"
    return "|".join(
        [
            bucket,
            get_card_text(card, "dictionary_headword") or get_card_text(card, "kanji"),
            get_card_text(card, "dictionary_reading") or get_card_text(card, "kana"),
        ]
    )


def normalize_practice_answer(value: str) -> str:
    normalized = normalize_text(value)
    return "".join(normalized.split())


def build_extended_verb_forms(word: str, reading: str, verb_type: str) -> Dict[str, Dict[str, str]]:
    dictionary_word = normalize_text(word)
    dictionary_reading = normalize_text(reading)
    normalized_verb_type = normalize_text(verb_type) or "other"

    forms = {
        "dictionary": {"word": dictionary_word, "reading": dictionary_reading},
        "masu": {"word": "", "reading": ""},
        "te": {"word": "", "reading": ""},
        "past": {"word": "", "reading": ""},
        "negative": {"word": "", "reading": ""},
        "potential": {"word": "", "reading": ""},
        "passive": {"word": "", "reading": ""},
        "causative": {"word": "", "reading": ""},
    }

    if not dictionary_reading:
        return forms

    if normalized_verb_type in {"ichidan", "godan", "suru", "suru_noun", "kuru"}:
        for form_key in VerbFormLabels.keys():
            conjugated_word, conjugated_reading = ConjugateVerbSurface(
                dictionary_word,
                dictionary_reading,
                normalized_verb_type,
                form_key,
                isIkuSpecial=False,
            )
            forms[form_key] = {"word": conjugated_word, "reading": conjugated_reading}

    if normalized_verb_type == "ichidan" and dictionary_reading.endswith("る"):
        stem_reading = dictionary_reading[:-1]
        stem_word = dictionary_word[:-1] if dictionary_word.endswith("る") else dictionary_word
        forms["potential"] = {"word": f"{stem_word}られる", "reading": f"{stem_reading}られる"}
        forms["passive"] = {"word": f"{stem_word}られる", "reading": f"{stem_reading}られる"}
        forms["causative"] = {"word": f"{stem_word}させる", "reading": f"{stem_reading}させる"}
        return forms

    if normalized_verb_type in {"suru", "suru_noun"}:
        base_word = dictionary_word[:-2] if dictionary_word.endswith("する") else dictionary_word
        base_reading = dictionary_reading[:-2] if dictionary_reading.endswith("する") else dictionary_reading
        forms["potential"] = {"word": f"{base_word}できる", "reading": f"{base_reading}できる"}
        forms["passive"] = {"word": f"{base_word}される", "reading": f"{base_reading}される"}
        forms["causative"] = {"word": f"{base_word}させる", "reading": f"{base_reading}させる"}
        return forms

    if normalized_verb_type == "kuru":
        if dictionary_word.endswith("来る"):
            base_word = dictionary_word[:-2]
            forms["potential"] = {"word": f"{base_word}来られる", "reading": "こられる"}
            forms["passive"] = {"word": f"{base_word}来られる", "reading": "こられる"}
            forms["causative"] = {"word": f"{base_word}来させる", "reading": "こさせる"}
        else:
            forms["potential"] = {"word": "こられる", "reading": "こられる"}
            forms["passive"] = {"word": "こられる", "reading": "こられる"}
            forms["causative"] = {"word": "こさせる", "reading": "こさせる"}
        return forms

    if normalized_verb_type == "godan" and dictionary_reading:
        ending = dictionary_reading[-1]
        stem_reading = dictionary_reading[:-1]
        stem_word = dictionary_word[:-1] if dictionary_word else dictionary_word
        e_row = GODAN_E_ROW_MAP.get(ending)
        a_row = GODAN_A_ROW_MAP.get(ending)
        if e_row:
            forms["potential"] = {"word": f"{stem_word}{e_row}る", "reading": f"{stem_reading}{e_row}る"}
        if a_row:
            forms["passive"] = {"word": f"{stem_word}{a_row}れる", "reading": f"{stem_reading}{a_row}れる"}
            forms["causative"] = {"word": f"{stem_word}{a_row}せる", "reading": f"{stem_reading}{a_row}せる"}
    return forms


def build_i_adjective_forms(word: str, reading: str) -> Dict[str, Dict[str, str]]:
    normalized_word = normalize_text(word)
    normalized_reading = normalize_text(reading)
    forms = {
        "dictionary": {"word": normalized_word, "reading": normalized_reading},
        "past": {"word": normalized_word, "reading": normalized_reading},
        "negative": {"word": normalized_word, "reading": normalized_reading},
    }
    if normalized_reading.endswith("い"):
        reading_stem = normalized_reading[:-1]
        forms["past"]["reading"] = f"{reading_stem}かった"
        forms["negative"]["reading"] = f"{reading_stem}くない"
    if normalized_word.endswith("い"):
        word_stem = normalized_word[:-1]
        forms["past"]["word"] = f"{word_stem}かった"
        forms["negative"]["word"] = f"{word_stem}くない"
    return forms


def build_na_adjective_forms(word: str, reading: str) -> Dict[str, Dict[str, str]]:
    normalized_word = normalize_text(word)
    normalized_reading = normalize_text(reading)
    forms = {
        "dictionary": {"word": normalized_word, "reading": normalized_reading},
        "past": {"word": f"{normalized_word}だった", "reading": f"{normalized_reading}だった"},
        "negative": {"word": f"{normalized_word}じゃない", "reading": f"{normalized_reading}じゃない"},
    }
    return forms


def build_search_terms_from_forms(forms: Dict[str, Dict[str, str]]) -> List[str]:
    terms: List[str] = []
    for value in forms.values():
        word = normalize_text(value.get("word", ""))
        reading = normalize_text(value.get("reading", ""))
        if word:
            terms.append(word)
        if reading:
            terms.append(reading)
    return normalize_string_list(terms)


def build_deck_card_search_terms(card: sqlite3.Row) -> List[str]:
    terms: List[str] = [
        card["kanji"] or "",
        card["kana"] or "",
        card["english"] or "",
        card["notes"] or "",
        card["dictionary_entry_id"] or "",
        card["dictionary_headword"] or "",
        card["dictionary_reading"] or "",
        card["dictionary_gloss"] or "",
        card["dictionary_pos"] or "",
        card["word_form"] or "",
    ]

    verb_type = normalize_text(card["verb_type"])
    base_word = normalize_text(card["dictionary_headword"]) or normalize_text(card["kanji"])
    base_reading = normalize_text(card["dictionary_reading"]) or normalize_text(card["kana"])
    if verb_type in {"ichidan", "godan", "suru", "suru_noun", "kuru"} and base_reading:
        terms.extend(build_search_terms_from_forms(build_extended_verb_forms(base_word, base_reading, verb_type)))

    if normalize_text(card["dictionary_pos"]).lower().find("adjective") >= 0:
        if base_reading.endswith("い") and not base_reading.endswith("ない"):
            terms.extend(build_search_terms_from_forms(build_i_adjective_forms(base_word, base_reading)))
        else:
            terms.extend(build_search_terms_from_forms(build_na_adjective_forms(base_word, base_reading)))

    return normalize_string_list(terms)


def build_global_card_search_terms(card: sqlite3.Row) -> List[str]:
    terms: List[str] = [
        card["kanji"] or "",
        card["kana"] or "",
        card["english"] or "",
        card["notes"] or "",
        card["kanji_masu"] or "",
        card["kana_masu"] or "",
        card["kanji_te"] or "",
        card["kana_te"] or "",
        card["kanji_past"] or "",
        card["kana_past"] or "",
        card["kanji_negative"] or "",
        card["kana_negative"] or "",
        card["dictionary_entry_id"] or "",
        card["dictionary_headword"] or "",
        card["dictionary_reading"] or "",
        card["dictionary_gloss"] or "",
        card["dictionary_pos"] or "",
    ]
    terms.extend(DecodeJsonStringList(card["tags_json"]))

    verb_type = normalize_text(card["verb_type"])
    base_word = normalize_text(card["dictionary_headword"]) or normalize_text(card["kanji"])
    base_reading = normalize_text(card["dictionary_reading"]) or normalize_text(card["kana"])
    if verb_type in {"ichidan", "godan", "suru", "suru_noun", "kuru"} and base_reading:
        terms.extend(build_search_terms_from_forms(build_extended_verb_forms(base_word, base_reading, verb_type)))
    return normalize_string_list(terms)


def matches_search(normalized_query: str, terms: List[str]) -> bool:
    if not normalized_query:
        return True
    for term in terms:
        normalized_term = normalize_search_text(term)
        if normalized_term and normalized_query in normalized_term:
            return True
    return False


def resolve_media_type_from_paths(paths: List[str]) -> str:
    if not paths:
        return "none"

    image_count = 0
    video_count = 0
    audio_count = 0
    for path in paths:
        suffix = Path(path).suffix.lower()
        if suffix in SupportedImageExtensions:
            image_count += 1
        elif suffix in SupportedVideoExtensions:
            video_count += 1
        elif suffix in SupportedAudioExtensions:
            audio_count += 1

    if image_count and not video_count and not audio_count:
        return "image"
    if video_count and not image_count and not audio_count:
        return "video"
    if audio_count and not image_count and not video_count:
        return "audio"
    return "none"


def split_global_media(paths: List[str]) -> Tuple[List[str], List[str]]:
    image_files: List[str] = []
    video_files: List[str] = []
    for path in paths:
        suffix = Path(path).suffix.lower()
        if suffix in SupportedImageExtensions:
            image_files.append(path)
        elif suffix in SupportedVideoExtensions:
            video_files.append(path)
    return normalize_string_list(image_files), normalize_string_list(video_files)


def read_local_file(path_text: str) -> LocalInputFile:
    path = Path(path_text)
    if not path.exists() or not path.is_file():
        raise RuntimeError(f"File does not exist: {path}")
    mime_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    return LocalInputFile(name=path.name, type=mime_type, _data=path.read_bytes())


def copy_media_paths_to_workspace(paths: List[str], deck_id: str) -> List[str]:
    if not paths:
        return []
    target_dir = MediaDir / normalize_text(deck_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    saved_paths: List[str] = []
    for raw_path in paths:
        source_path = Path(raw_path)
        if not source_path.exists() or not source_path.is_file():
            continue
        suffix = source_path.suffix.lower()
        safe_name = f"{uuid.uuid4().hex}{suffix}"
        target_path = target_dir / safe_name
        shutil.copy2(source_path, target_path)
        saved_paths.append(str(target_path))
    return saved_paths


def serialize_collection(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": normalize_text(row.get("id", "")),
        "name": normalize_text(row.get("name", "")),
    }


def serialize_deck(row: Dict[str, Any], card_count_by_id: Dict[str, int]) -> Dict[str, Any]:
    collection_name = normalize_text(row.get("collection_name", ""))
    deck_name = normalize_text(row.get("name", ""))
    return {
        "id": normalize_text(row.get("id", "")),
        "collection_id": normalize_text(row.get("collection_id", "")),
        "collection_name": collection_name,
        "name": deck_name,
        "label": f"{collection_name} :: {deck_name}" if collection_name else deck_name,
        "card_count": int(card_count_by_id.get(normalize_text(row.get("id", "")), 0)),
    }


def serialize_dictionary_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    payload = {
        **entry,
        "option_label": FormatDictionaryEntryOption(entry),
        "is_verb": IsVerbEntry(entry),
    }
    if IsVerbEntry(entry):
        payload["forms"] = BuildConjugatedForms(entry)
    else:
        payload["forms"] = {"dictionary": {"kanji": entry.get("headword", ""), "kana": entry.get("reading", "")}}
    return payload


def serialize_global_card(row: sqlite3.Row) -> Dict[str, Any]:
    image_files = DecodeJsonStringList(row["image_files_json"])
    video_files = DecodeJsonStringList(row["video_files_json"])
    tags = DecodeJsonStringList(row["tags_json"])
    return {
        "id": row["id"],
        "kanji": normalize_text(row["kanji"]),
        "kana": normalize_text(row["kana"]),
        "english": normalize_text(row["english"]),
        "notes": normalize_text(row["notes"]),
        "kanji_masu": normalize_text(row["kanji_masu"]),
        "kana_masu": normalize_text(row["kana_masu"]),
        "kanji_te": normalize_text(row["kanji_te"]),
        "kana_te": normalize_text(row["kana_te"]),
        "kanji_past": normalize_text(row["kanji_past"]),
        "kana_past": normalize_text(row["kana_past"]),
        "kanji_negative": normalize_text(row["kanji_negative"]),
        "kana_negative": normalize_text(row["kana_negative"]),
        "dictionary_entry_id": normalize_text(row["dictionary_entry_id"]),
        "dictionary_headword": normalize_text(row["dictionary_headword"]),
        "dictionary_reading": normalize_text(row["dictionary_reading"]),
        "dictionary_gloss": normalize_text(row["dictionary_gloss"]),
        "dictionary_pos": normalize_text(row["dictionary_pos"]),
        "verb_type": normalize_text(row["verb_type"]),
        "image_files": image_files,
        "video_files": video_files,
        "tags": tags,
        "media_type": "image" if image_files and not video_files else "video" if video_files and not image_files else "none",
    }


def serialize_deck_card(card: sqlite3.Row, index: int) -> Dict[str, Any]:
    schema_key = normalize_text(card["schema_key"]) or "kana_kanji_front_english_back"
    schema_label = CardSchemas.get(schema_key, {}).get("Label", schema_key)
    return {
        "id": card["id"],
        "index": index,
        "kanji": normalize_text(card["kanji"]),
        "kana": normalize_text(card["kana"]),
        "english": normalize_text(card["english"]),
        "notes": normalize_text(card["notes"]),
        "schema_key": schema_key,
        "schema_label": schema_label,
        "word_form": normalize_text(card["word_form"]) or "dictionary",
        "dictionary_entry_id": normalize_text(card["dictionary_entry_id"]),
        "dictionary_headword": normalize_text(card["dictionary_headword"]),
        "dictionary_reading": normalize_text(card["dictionary_reading"]),
        "dictionary_gloss": normalize_text(card["dictionary_gloss"]),
        "dictionary_pos": normalize_text(card["dictionary_pos"]),
        "verb_type": normalize_text(card["verb_type"]),
        "media_type": normalize_text(card["media_type"]) or "none",
        "media_files": DecodeJsonStringList(card["media_files_json"]),
        "tags": DecodeJsonStringList(card["tags_json"]),
    }


def choose_surface_by_word_form(
    base_kanji: str,
    base_kana: str,
    verb_type: str,
    forms: Dict[str, Dict[str, str]],
    word_form: str,
) -> Tuple[str, str, str]:
    normalized_word_form = normalize_text(word_form) or "dictionary"
    if normalized_word_form not in {"dictionary", "masu", "te", "past", "negative"}:
        normalized_word_form = "dictionary"

    if verb_type not in {"ichidan", "godan", "suru", "suru_noun", "kuru"}:
        return base_kanji, base_kana, "dictionary"

    if normalized_word_form == "dictionary":
        return base_kanji, base_kana, normalized_word_form

    selected = forms.get(normalized_word_form, {})
    selected_word = normalize_text(selected.get("word", "")) or base_kanji
    selected_reading = normalize_text(selected.get("reading", "")) or base_kana
    return selected_word, selected_reading, normalized_word_form


def action_bootstrap(_: Dict[str, Any]) -> Dict[str, Any]:
    connection = get_connection()
    collections = ListCollections(connection)
    decks = ListDecks(connection, includeCollectionName=True)
    card_count_by_id = GetDeckCardCounts(connection)
    deck_rows = [serialize_deck(deck, card_count_by_id) for deck in decks]

    return {
        "app_title": AppTitle,
        "card_schemas": [{"key": key, "label": definition["Label"]} for key, definition in CardSchemas.items()],
        "verb_forms": [{"key": key, "label": label} for key, label in VerbFormLabels.items()],
        "verb_types": [
            {"key": "other", "label": "Non-verb / Other"},
            {"key": "ichidan", "label": VerbTypeLabels.get("ichidan", "Ichidan")},
            {"key": "godan", "label": VerbTypeLabels.get("godan", "Godan")},
            {"key": "suru", "label": VerbTypeLabels.get("suru", "Suru irregular")},
            {"key": "suru_noun", "label": VerbTypeLabels.get("suru_noun", "Suru noun")},
            {"key": "kuru", "label": VerbTypeLabels.get("kuru", "Kuru irregular")},
            {"key": "i_adj", "label": "I-adjective"},
            {"key": "na_adj", "label": "Na-adjective"},
            {"key": "noun", "label": "Noun"},
        ],
        "collections": [serialize_collection(row) for row in collections],
        "decks": deck_rows,
        "dashboard": {
            "collection_count": len(collections),
            "deck_count": GetTotalDeckCount(connection),
            "card_count": GetTotalCardCount(connection),
            "global_card_count": CountGlobalCards(connection),
            "rows": [
                {
                    "collection_name": row["collection_name"],
                    "deck_name": row["deck_name"],
                    "card_count": int(row["card_count"]),
                }
                for row in GetDashboardRows(connection)
            ],
        },
        "defaults": {
            "schema_key": "kana_kanji_front_english_back",
            "word_form": "dictionary",
            "practice_modes": [
                {"key": "verb_sort", "label": "Verb Sort (Ichidan vs Godan)"},
                {"key": "adjective_sort", "label": "Adjective Sort (い vs な)"},
                {"key": "te_form", "label": "Te Form Builder"},
            ],
        },
    }


def action_create_collection(payload: Dict[str, Any]) -> Dict[str, Any]:
    name = normalize_text(payload.get("name", ""))
    if not name:
        raise RuntimeError("Collection name is required.")
    CreateCollection(get_connection(), name)
    return {"created": True, "name": name}


def action_rename_collection(payload: Dict[str, Any]) -> Dict[str, Any]:
    collection_id = normalize_text(payload.get("collection_id", ""))
    name = normalize_text(payload.get("name", ""))
    if not collection_id:
        raise RuntimeError("collection_id is required.")
    if not name:
        raise RuntimeError("New collection name is required.")
    RenameCollection(get_connection(), collection_id, name)
    return {"updated": True, "collection_id": collection_id, "name": name}


def action_create_deck(payload: Dict[str, Any]) -> Dict[str, Any]:
    collection_id = normalize_text(payload.get("collection_id", ""))
    name = normalize_text(payload.get("name", ""))
    if not collection_id:
        raise RuntimeError("collection_id is required.")
    if not name:
        raise RuntimeError("Deck name is required.")
    CreateDeck(get_connection(), collection_id, name)
    return {"created": True, "collection_id": collection_id, "name": name}


def action_rename_deck(payload: Dict[str, Any]) -> Dict[str, Any]:
    deck_id = normalize_text(payload.get("deck_id", ""))
    name = normalize_text(payload.get("name", ""))
    if not deck_id:
        raise RuntimeError("deck_id is required.")
    if not name:
        raise RuntimeError("New deck name is required.")
    RenameDeck(get_connection(), deck_id, name)
    return {"updated": True, "deck_id": deck_id, "name": name}


def action_search_dictionary(payload: Dict[str, Any]) -> Dict[str, Any]:
    query = normalize_text(payload.get("query", ""))
    limit = int(payload.get("limit", 50) or 50)
    if not query:
        return {"query": query, "results": []}

    results = SearchDictionaryEntries(query, limit=limit)
    return {
        "query": query,
        "results": [serialize_dictionary_entry(entry) for entry in results],
    }


def action_add_dictionary_entries(payload: Dict[str, Any]) -> Dict[str, Any]:
    entry_ids = normalize_string_list(payload.get("entry_ids", []))
    destination = normalize_text(payload.get("destination", "global")) or "global"
    deck_id = normalize_text(payload.get("deck_id", ""))
    schema_key = normalize_text(payload.get("schema_key", "")) or "kana_kanji_front_english_back"
    word_form = normalize_text(payload.get("word_form", "")) or "dictionary"
    tags = parse_tags(payload.get("tags", []))
    notes = normalize_text(payload.get("notes", ""))
    english_override = normalize_text(payload.get("english_override", ""))

    if not entry_ids:
        raise RuntimeError("Select one or more dictionary entries first.")
    if destination == "deck" and not deck_id:
        raise RuntimeError("deck_id is required when destination is deck.")

    connection = get_connection()
    added = 0
    skipped = 0
    missing: List[str] = []

    for entry_id in entry_ids:
        entry = GetDictionaryEntryById(entry_id)
        if not entry:
            missing.append(entry_id)
            skipped += 1
            continue

        if destination == "global":
            card_payload = BuildGlobalCardFromDictionaryEntry(
                entry,
                tags=tags,
                notes=notes,
                englishOverride=english_override,
            )
            is_added = AddGlobalCard(connection, card_payload)
        else:
            card_payload = BuildCardFromDictionaryEntry(
                entry,
                schema_key,
                word_form,
                tags,
                notes,
                englishOverride=english_override,
            )
            is_added = AddCard(connection, deck_id, card_payload)

        added += int(is_added)
        skipped += int(not is_added)

    return {
        "added": added,
        "skipped": skipped,
        "missing_entry_ids": missing,
        "destination": destination,
    }


def action_quick_add_dictionary_entry(payload: Dict[str, Any]) -> Dict[str, Any]:
    return action_add_dictionary_entries(
        {
            "entry_ids": [normalize_text(payload.get("entry_id", ""))],
            "destination": payload.get("destination", "global"),
            "deck_id": payload.get("deck_id", ""),
            "schema_key": payload.get("schema_key", "kana_kanji_front_english_back"),
            "word_form": payload.get("word_form", "dictionary"),
            "tags": payload.get("tags", []),
            "notes": payload.get("notes", ""),
            "english_override": payload.get("english_override", ""),
        }
    )


def action_build_word_forms(payload: Dict[str, Any]) -> Dict[str, Any]:
    word = normalize_text(payload.get("word", ""))
    reading = normalize_text(payload.get("reading", ""))
    word_kind = normalize_text(payload.get("word_kind", "noun")) or "noun"

    if word_kind in {"ichidan", "godan", "suru", "suru_noun", "kuru"}:
        forms = build_extended_verb_forms(word, reading, word_kind)
    elif word_kind == "i_adj":
        forms = build_i_adjective_forms(word, reading)
    elif word_kind == "na_adj":
        forms = build_na_adjective_forms(word, reading)
    else:
        forms = {"dictionary": {"word": word, "reading": reading}}

    return {"word_kind": word_kind, "forms": forms}


def action_add_manual_card(payload: Dict[str, Any]) -> Dict[str, Any]:
    destination = normalize_text(payload.get("destination", "global")) or "global"
    deck_id = normalize_text(payload.get("deck_id", ""))
    schema_key = normalize_text(payload.get("schema_key", "")) or "kana_kanji_front_english_back"
    word_form = normalize_text(payload.get("word_form", "")) or "dictionary"
    word_kind = normalize_text(payload.get("word_kind", "noun")) or "noun"

    kanji = normalize_text(payload.get("kanji", ""))
    kana = normalize_text(payload.get("kana", ""))
    english = normalize_text(payload.get("english", ""))
    notes = normalize_text(payload.get("notes", ""))
    tags = parse_tags(payload.get("tags", []))
    media_paths = normalize_string_list(payload.get("media_paths", []))

    if not kanji or not kana or not english:
        raise RuntimeError("kanji, kana, and english are required.")
    if destination == "deck" and not deck_id:
        raise RuntimeError("deck_id is required when destination is deck.")

    forms_payload = payload.get("forms", {}) or {}
    forms = {
        "dictionary": {
            "word": normalize_text(forms_payload.get("dictionary", {}).get("word", "")) or kanji,
            "reading": normalize_text(forms_payload.get("dictionary", {}).get("reading", "")) or kana,
        },
        "masu": {
            "word": normalize_text(forms_payload.get("masu", {}).get("word", "")),
            "reading": normalize_text(forms_payload.get("masu", {}).get("reading", "")),
        },
        "te": {
            "word": normalize_text(forms_payload.get("te", {}).get("word", "")),
            "reading": normalize_text(forms_payload.get("te", {}).get("reading", "")),
        },
        "past": {
            "word": normalize_text(forms_payload.get("past", {}).get("word", "")),
            "reading": normalize_text(forms_payload.get("past", {}).get("reading", "")),
        },
        "negative": {
            "word": normalize_text(forms_payload.get("negative", {}).get("word", "")),
            "reading": normalize_text(forms_payload.get("negative", {}).get("reading", "")),
        },
    }

    dictionary_entry_id = normalize_text(payload.get("dictionary_entry_id", ""))
    dictionary_headword = normalize_text(payload.get("dictionary_headword", "")) or kanji
    dictionary_reading = normalize_text(payload.get("dictionary_reading", "")) or kana
    dictionary_gloss = normalize_text(payload.get("dictionary_gloss", "")) or english
    dictionary_pos = normalize_text(payload.get("dictionary_pos", ""))
    verb_type = normalize_text(payload.get("verb_type", ""))
    if not verb_type and word_kind in {"ichidan", "godan", "suru", "suru_noun", "kuru"}:
        verb_type = word_kind

    media_deck_id = deck_id if destination == "deck" else "_global_pool"
    saved_media_paths = copy_media_paths_to_workspace(media_paths, media_deck_id)
    image_files, video_files = split_global_media(saved_media_paths)

    connection = get_connection()
    if destination == "global":
        global_payload = {
            "kanji": kanji,
            "kana": kana,
            "english": english,
            "notes": notes,
            "kanji_masu": forms["masu"]["word"],
            "kana_masu": forms["masu"]["reading"],
            "kanji_te": forms["te"]["word"],
            "kana_te": forms["te"]["reading"],
            "kanji_past": forms["past"]["word"],
            "kana_past": forms["past"]["reading"],
            "kanji_negative": forms["negative"]["word"],
            "kana_negative": forms["negative"]["reading"],
            "image_files": image_files,
            "video_files": video_files,
            "tags": tags,
            "dictionary_entry_id": dictionary_entry_id,
            "dictionary_headword": dictionary_headword,
            "dictionary_reading": dictionary_reading,
            "dictionary_gloss": dictionary_gloss,
            "dictionary_pos": dictionary_pos,
            "verb_type": verb_type,
        }
        is_added = AddGlobalCard(connection, global_payload)
        return {"destination": "global", "added": bool(is_added), "saved_media_paths": saved_media_paths}

    selected_kanji, selected_kana, selected_word_form = choose_surface_by_word_form(
        kanji,
        kana,
        verb_type,
        forms,
        word_form,
    )

    deck_payload = {
        "kanji": selected_kanji,
        "kana": selected_kana,
        "english": english,
        "notes": notes,
        "source_text": "manual:custom",
        "schema_key": schema_key,
        "media_type": resolve_media_type_from_paths(saved_media_paths),
        "media_files": saved_media_paths,
        "tags": tags,
        "dictionary_entry_id": dictionary_entry_id,
        "dictionary_headword": dictionary_headword,
        "dictionary_reading": dictionary_reading,
        "dictionary_gloss": dictionary_gloss,
        "dictionary_pos": dictionary_pos,
        "verb_type": verb_type,
        "word_form": selected_word_form,
    }
    is_added = AddCard(connection, deck_id, deck_payload)
    return {
        "destination": "deck",
        "deck_id": deck_id,
        "added": bool(is_added),
        "saved_media_paths": saved_media_paths,
        "word_form": selected_word_form,
    }


def action_import_deck_to_global(payload: Dict[str, Any]) -> Dict[str, Any]:
    deck_id = normalize_text(payload.get("deck_id", ""))
    if not deck_id:
        raise RuntimeError("deck_id is required.")
    added, skipped = ImportDeckCardsToGlobal(get_connection(), deck_id)
    return {"deck_id": deck_id, "added": int(added), "skipped": int(skipped)}


def action_list_global_cards(payload: Dict[str, Any]) -> Dict[str, Any]:
    normalized_query = normalize_search_text(payload.get("search", ""))
    rows: List[Dict[str, Any]] = []
    for row in ListGlobalCards(get_connection()):
        if not matches_search(normalized_query, build_global_card_search_terms(row)):
            continue
        rows.append(serialize_global_card(row))

    return {
        "search": normalize_text(payload.get("search", "")),
        "count": len(rows),
        "rows": rows,
    }


def action_delete_global_cards(payload: Dict[str, Any]) -> Dict[str, Any]:
    ids = normalize_string_list(payload.get("ids", []))
    if not ids:
        raise RuntimeError("Select one or more global cards first.")
    deleted = DeleteGlobalCardsByIds(get_connection(), ids)
    return {"deleted": int(deleted)}


def action_import_global_to_deck(payload: Dict[str, Any]) -> Dict[str, Any]:
    deck_id = normalize_text(payload.get("deck_id", ""))
    ids = normalize_string_list(payload.get("global_card_ids", []))
    schema_key = normalize_text(payload.get("schema_key", "")) or "kana_kanji_front_english_back"
    word_form = normalize_text(payload.get("word_form", "")) or "dictionary"
    tags = parse_tags(payload.get("tags", []))
    if not deck_id:
        raise RuntimeError("deck_id is required.")
    if not ids:
        raise RuntimeError("Select one or more global cards first.")
    added, skipped = ImportGlobalCardsToDeck(
        get_connection(),
        deck_id,
        ids,
        schema_key,
        word_form,
        extraTags=tags,
    )
    return {"added": int(added), "skipped": int(skipped), "deck_id": deck_id}


def action_list_deck_cards(payload: Dict[str, Any]) -> Dict[str, Any]:
    deck_id = normalize_text(payload.get("deck_id", ""))
    if not deck_id:
        return {"deck_id": "", "count": 0, "rows": []}

    normalized_query = normalize_search_text(payload.get("search", ""))
    rows: List[Dict[str, Any]] = []
    for index, card in enumerate(GetDeckCards(get_connection(), deck_id), start=1):
        if not matches_search(normalized_query, build_deck_card_search_terms(card)):
            continue
        rows.append(serialize_deck_card(card, index))
    return {"deck_id": deck_id, "count": len(rows), "rows": rows}


def action_bulk_update_card_schema(payload: Dict[str, Any]) -> Dict[str, Any]:
    deck_id = normalize_text(payload.get("deck_id", ""))
    card_ids = normalize_string_list(payload.get("card_ids", []))
    schema_key = normalize_text(payload.get("schema_key", "")) or "kana_kanji_front_english_back"
    if not deck_id:
        raise RuntimeError("deck_id is required.")
    if not card_ids:
        raise RuntimeError("Select one or more cards first.")
    updated = UpdateCardsSchemaByIds(get_connection(), deck_id, card_ids, schema_key)
    return {
        "updated": int(updated),
        "skipped": max(0, len(card_ids) - int(updated)),
    }


def action_delete_deck_cards(payload: Dict[str, Any]) -> Dict[str, Any]:
    deck_id = normalize_text(payload.get("deck_id", ""))
    card_ids = normalize_string_list(payload.get("card_ids", []))
    if not deck_id:
        raise RuntimeError("deck_id is required.")
    if not card_ids:
        raise RuntimeError("Select one or more cards first.")
    deleted = DeleteCardsByIds(get_connection(), deck_id, card_ids)
    return {"deleted": int(deleted)}


def action_update_card(payload: Dict[str, Any]) -> Dict[str, Any]:
    deck_id = normalize_text(payload.get("deck_id", ""))
    card_id = normalize_text(payload.get("card_id", ""))
    if not deck_id or not card_id:
        raise RuntimeError("deck_id and card_id are required.")
    updated = UpdateCardContent(
        get_connection(),
        deck_id,
        card_id,
        normalize_text(payload.get("kanji", "")),
        normalize_text(payload.get("kana", "")),
        normalize_text(payload.get("english", "")),
        normalize_text(payload.get("notes", "")),
        normalize_text(payload.get("schema_key", "")) or "kana_kanji_front_english_back",
    )
    return {"updated": bool(updated)}


def action_replace_card_media(payload: Dict[str, Any]) -> Dict[str, Any]:
    deck_id = normalize_text(payload.get("deck_id", ""))
    card_id = normalize_text(payload.get("card_id", ""))
    replace_target = normalize_text(payload.get("replace_target", "none")) or "none"
    media_type = normalize_text(payload.get("media_type", "image")) or "image"
    media_paths = normalize_string_list(payload.get("media_paths", []))

    if not deck_id or not card_id:
        raise RuntimeError("deck_id and card_id are required.")
    if replace_target not in {"kanji", "kana", "english", "none"}:
        raise RuntimeError("replace_target must be one of: kanji, kana, english, none.")
    if media_type not in {"image", "audio", "video"}:
        raise RuntimeError("media_type must be one of: image, audio, video.")
    if not media_paths:
        raise RuntimeError("Select at least one media file.")

    saved_paths = copy_media_paths_to_workspace(media_paths, deck_id)
    if not saved_paths:
        raise RuntimeError("No media files were copied.")

    if replace_target in {"kanji", "kana", "english"}:
        UpdateCardField(get_connection(), card_id, replace_target, f"[{media_type.upper()}]")
    UpdateCardMedia(get_connection(), card_id, media_type, saved_paths)
    return {"updated": True, "saved_media_paths": saved_paths}


def action_scan_images(payload: Dict[str, Any]) -> Dict[str, Any]:
    deck_id = normalize_text(payload.get("deck_id", ""))
    image_paths = normalize_string_list(payload.get("image_paths", []))
    scan_schema_key = normalize_text(payload.get("schema_key", "")) or "kana_kanji_front_english_back"
    scan_word_form = normalize_text(payload.get("word_form", "")) or "dictionary"
    scan_tags = parse_tags(payload.get("tags", []))

    if not deck_id:
        raise RuntimeError("deck_id is required.")
    if not image_paths:
        raise RuntimeError("Select one or more image files first.")

    upload_adapters = [read_local_file(path) for path in image_paths]
    connection = get_connection()
    client = GetOpenAiClient()

    extracted_candidates, errors = ExtractCardsFromImages(
        client,
        DefaultModel,
        upload_adapters,
        progressCallback=None,
    )
    expanded_candidates = ExpandExtractedScanCandidates(
        extracted_candidates,
        dictionaryLookup=lambda query: SearchDictionaryEntries(query, limit=1),
    )

    resolved_cards: List[Dict[str, Any]] = []
    preview_rows: List[Dict[str, Any]] = []
    dictionary_matched_count = 0
    dictionary_miss_count = 0
    polite_surface_skipped_count = 0
    duplicate_entry_skipped_count = 0
    seen_surface_and_form = set()

    for candidate in expanded_candidates:
        resolved_entry = ResolveBestDictionaryEntry(
            sourceKanji=candidate.get("kanji", ""),
            sourceKana=candidate.get("kana", ""),
            visibleText=candidate.get("visible_text", ""),
        )
        note_text = BuildScanCandidateNote(candidate)
        source_text = candidate.get("origin_visible_text") or candidate.get("visible_text", "")

        if resolved_entry:
            card = BuildCardFromDictionaryEntry(
                resolved_entry,
                scan_schema_key,
                scan_word_form,
                scan_tags + ["image_ocr"],
                notes=note_text,
                sourceText=source_text,
            )
        else:
            dictionary_miss_count += 1
            continue

        if scan_word_form == "dictionary" and (
            LooksLikePoliteMasuSurface(card.get("kanji", "")) or LooksLikePoliteMasuSurface(card.get("kana", ""))
        ):
            polite_surface_skipped_count += 1
            continue

        card_word_form = normalize_text(card.get("word_form", "dictionary")) or "dictionary"
        surface_key = normalize_text(card.get("kanji", "")) or normalize_text(card.get("dictionary_headword", "")) or normalize_text(card.get("kana", ""))
        dedupe_key = (surface_key, card_word_form)
        if surface_key and dedupe_key in seen_surface_and_form:
            duplicate_entry_skipped_count += 1
            continue
        if surface_key:
            seen_surface_and_form.add(dedupe_key)

        dictionary_matched_count += 1
        resolved_cards.append(card)
        preview_rows.append(
            {
                "visible_text": candidate.get("visible_text", ""),
                "source_text": candidate.get("origin_visible_text", ""),
                "dictionary_entry_id": card.get("dictionary_entry_id", ""),
                "kanji": card.get("kanji", ""),
                "kana": card.get("kana", ""),
                "english": card.get("english", ""),
            }
        )

    added = 0
    duplicates = 0
    for card in resolved_cards:
        if DeckHasKanjiWordForm(
            connection,
            deck_id,
            card.get("schema_key", ""),
            card.get("word_form", "dictionary"),
            card.get("kanji", ""),
        ):
            duplicates += 1
            continue
        if DeckHasCandidate(connection, deck_id, card):
            duplicates += 1
            continue
        if AddCard(connection, deck_id, card):
            added += 1

    summary = (
        f"Scanned {len(upload_adapters)} images. Added {added} new cards and skipped {duplicates} duplicates.\n"
        f"OCR produced {len(extracted_candidates)} raw candidate(s), expanded to {len(expanded_candidates)} term candidate(s).\n"
        f"Dictionary matched {dictionary_matched_count} candidate(s); "
        f"skipped {dictionary_miss_count} unmatched candidate(s); "
        f"skipped {polite_surface_skipped_count} candidate(s) that still looked like polite/masu while dictionary form was selected; "
        f"skipped {duplicate_entry_skipped_count} duplicate dictionary-entry candidate(s)."
    )

    return {
        "added": added,
        "duplicates": duplicates,
        "summary": summary,
        "preview_rows": preview_rows,
        "errors": errors,
    }


def action_import_csv(payload: Dict[str, Any]) -> Dict[str, Any]:
    deck_id = normalize_text(payload.get("deck_id", ""))
    csv_path = normalize_text(payload.get("csv_path", ""))
    if not deck_id:
        raise RuntimeError("deck_id is required.")
    if not csv_path:
        raise RuntimeError("csv_path is required.")
    csv_file = read_local_file(csv_path)
    added, skipped = ImportCsvCards(get_connection(), deck_id, csv_file)
    return {"added": int(added), "skipped": int(skipped)}


def action_export_deck(payload: Dict[str, Any]) -> Dict[str, Any]:
    deck_id = normalize_text(payload.get("deck_id", ""))
    if not deck_id:
        raise RuntimeError("deck_id is required.")
    export_path = ExportDeckPackage(get_connection(), deck_id)
    return {"export_path": str(export_path), "filename": export_path.name}


def action_get_revision_cards(payload: Dict[str, Any]) -> Dict[str, Any]:
    deck_id = normalize_text(payload.get("deck_id", ""))
    if not deck_id:
        return {"deck_id": "", "rows": []}

    rows: List[Dict[str, Any]] = []
    for card in GetDeckCards(get_connection(), deck_id):
        schema_key = normalize_text(card["schema_key"]) or "kana_kanji_front_english_back"
        schema = CardSchemas.get(schema_key, {})
        front_fields = schema.get("FrontFields", ["kana", "kanji"])
        back_fields = schema.get("BackFields", ["english"])
        front_text = build_card_face_text(card, front_fields) or build_card_face_text(card, ["kana", "kanji"])
        back_text = build_card_face_text(card, back_fields) or build_card_face_text(card, ["english", "kana", "kanji"])
        rows.append(
            {
                "id": card["id"],
                "front": front_text,
                "back": back_text,
                "notes": normalize_text(card["notes"]),
                "schema_label": CardSchemas.get(schema_key, {}).get("Label", schema_key),
                "word_form": normalize_text(card["word_form"]) or "dictionary",
            }
        )
    return {"deck_id": deck_id, "rows": rows}


def build_practice_round_cards(deck_id: str, mode: str) -> List[Dict[str, Any]]:
    if not deck_id:
        return []

    rows: List[Dict[str, Any]] = []
    seen_keys = set()
    for card in GetDeckCards(get_connection(), deck_id):
        if mode == "verb_sort":
            bucket = detect_practice_verb_bucket(card)
        elif mode == "adjective_sort":
            bucket = detect_practice_adjective_bucket(card)
        else:
            verb_type = detect_practice_verb_type(card)
            if not verb_type:
                continue
            base_word = get_card_text(card, "dictionary_headword") or get_card_text(card, "kanji")
            base_reading = get_card_text(card, "dictionary_reading") or get_card_text(card, "kana")
            if not base_reading:
                continue
            if not base_word:
                base_word = base_reading

            forms = build_extended_verb_forms(base_word, base_reading, verb_type)
            expected_word = normalize_text(forms.get("te", {}).get("word", ""))
            expected_reading = normalize_text(forms.get("te", {}).get("reading", ""))
            if not expected_word and not expected_reading:
                continue

            accepted_answers: List[str] = []
            for answer in [expected_word, expected_reading]:
                normalized_answer = normalize_practice_answer(answer)
                if normalized_answer and normalized_answer not in accepted_answers:
                    accepted_answers.append(normalized_answer)
            if not accepted_answers:
                continue

            dedupe_key = build_practice_dedupe_key(card, "te_form")
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)

            prompt = build_practice_prompt(card)
            if not prompt:
                continue

            expected_display = expected_word
            if expected_word and expected_reading and expected_word != expected_reading:
                expected_display = f"{expected_word} [{expected_reading}]"
            elif not expected_display:
                expected_display = expected_reading

            rows.append(
                {
                    "id": dedupe_key,
                    "prompt": prompt,
                    "hint": build_practice_hint(card),
                    "expected": expected_display,
                    "expected_display": expected_display,
                    "accepted_answers": accepted_answers,
                }
            )
            continue

        if not bucket:
            continue
        dedupe_key = build_practice_dedupe_key(card, bucket)
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)

        prompt = build_practice_prompt(card)
        if not prompt:
            continue
        rows.append(
            {
                "id": dedupe_key,
                "prompt": prompt,
                "hint": build_practice_hint(card),
                "expected": bucket,
            }
        )

    random.shuffle(rows)
    return rows


def action_get_practice_round(payload: Dict[str, Any]) -> Dict[str, Any]:
    deck_id = normalize_text(payload.get("deck_id", ""))
    mode = normalize_text(payload.get("mode", "verb_sort")) or "verb_sort"
    if mode not in {"verb_sort", "adjective_sort", "te_form"}:
        mode = "verb_sort"
    rows = build_practice_round_cards(deck_id, mode)
    return {
        "deck_id": deck_id,
        "mode": mode,
        "rows": rows,
        "scoring": {
            "base_correct_points": PRACTICE_BASE_CORRECT_POINTS,
            "incorrect_penalty_points": PRACTICE_INCORRECT_PENALTY_POINTS,
            "bucket_labels": PRACTICE_BUCKET_LABELS,
        },
    }


def action_get_counts(payload: Dict[str, Any]) -> Dict[str, Any]:
    deck_id = normalize_text(payload.get("deck_id", ""))
    return {
        "global_card_count": CountGlobalCards(get_connection()),
        "deck_card_count": CountCardsInDeck(get_connection(), deck_id) if deck_id else 0,
    }


ACTIONS = {
    "bootstrap": action_bootstrap,
    "create_collection": action_create_collection,
    "rename_collection": action_rename_collection,
    "create_deck": action_create_deck,
    "rename_deck": action_rename_deck,
    "search_dictionary": action_search_dictionary,
    "add_dictionary_entries": action_add_dictionary_entries,
    "quick_add_dictionary_entry": action_quick_add_dictionary_entry,
    "build_word_forms": action_build_word_forms,
    "add_manual_card": action_add_manual_card,
    "import_deck_to_global": action_import_deck_to_global,
    "list_global_cards": action_list_global_cards,
    "delete_global_cards": action_delete_global_cards,
    "import_global_to_deck": action_import_global_to_deck,
    "list_deck_cards": action_list_deck_cards,
    "bulk_update_card_schema": action_bulk_update_card_schema,
    "delete_deck_cards": action_delete_deck_cards,
    "update_card": action_update_card,
    "replace_card_media": action_replace_card_media,
    "scan_images": action_scan_images,
    "import_csv": action_import_csv,
    "export_deck": action_export_deck,
    "get_revision_cards": action_get_revision_cards,
    "get_practice_round": action_get_practice_round,
    "get_counts": action_get_counts,
}


def parse_payload(payload_json: str, payload_file: str) -> Dict[str, Any]:
    if payload_file:
        payload_text = Path(payload_file).read_text(encoding="utf-8")
    else:
        payload_text = payload_json
    if not payload_text.strip():
        return {}
    payload = json.loads(payload_text)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise RuntimeError("Payload must be a JSON object.")
    return payload


def print_envelope(ok: bool, data: Any = None, error: str = "", include_trace: bool = False) -> None:
    payload: Dict[str, Any] = {"ok": ok}
    if ok:
        payload["data"] = data
    else:
        payload["error"] = {"message": error}
        if include_trace:
            payload["error"]["traceback"] = traceback.format_exc()
    print(json.dumps(payload, ensure_ascii=False))


def run_action(action: str, payload: Dict[str, Any]) -> Any:
    handler = ACTIONS.get(action)
    if handler is None:
        raise RuntimeError(f"Unknown action: {action}")
    return handler(payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="Anki Card Generator Python sidecar")
    parser.add_argument("--ping", action="store_true", help="simple health check")
    parser.add_argument("--action", default="", help="action name")
    parser.add_argument("--payload-json", default="", help="inline JSON payload")
    parser.add_argument("--payload-file", default="", help="path to JSON payload")
    parser.add_argument("--debug-errors", action="store_true", help="include traceback in error payload")
    args = parser.parse_args()

    if args.ping:
        print("pong")
        return 0

    try:
        action = normalize_text(args.action)
        if not action:
            raise RuntimeError("Missing --action argument.")
        payload = parse_payload(args.payload_json, args.payload_file)
        result = run_action(action, payload)
        print_envelope(True, data=result)
        return 0
    except sqlite3.IntegrityError as exc:
        print_envelope(False, error=str(exc), include_trace=args.debug_errors)
        return 1
    except Exception as exc:
        print_envelope(False, error=str(exc), include_trace=args.debug_errors)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
