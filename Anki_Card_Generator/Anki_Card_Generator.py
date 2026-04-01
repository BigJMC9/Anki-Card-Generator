import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from dotenv import load_dotenv
import reflex as rx

from AnkiDeckBuilder.AppConfig import (
    AppDir,
    AppTitle,
    CardSchemas,
    DefaultModel,
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
    DeleteCardsByIds,
    GetDashboardRows,
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
    BuildGlobalCardFromDictionaryEntry,
    FormatDictionaryEntryOption,
    IsVerbEntry,
    LooksLikePoliteMasuSurface,
    ResolveBestDictionaryEntry,
    SearchDictionaryEntries,
    VerbFormLabels,
)
from AnkiDeckBuilder.Navigation import GetDefaultPageKey, PageDefinitions, SectionOrder
from AnkiDeckBuilder.OpenAiService import ExtractCardsFromImages, GetOpenAiClient
from AnkiDeckBuilder.Pages import (
    BuildScanCandidateNote,
    ExpandExtractedScanCandidates,
    FormatDeckLabel,
    ParseCommaSeparatedTags,
)
from AnkiDeckBuilder.UiTheme import ThemeStyles
from AnkiDeckBuilder.WorkspaceService import CopyUploadedMedia, EnsureWorkspaceDirectories

load_dotenv()

_DatabaseConnection: Optional[sqlite3.Connection] = None


def GetConnection() -> sqlite3.Connection:
    global _DatabaseConnection
    if _DatabaseConnection is None:
        EnsureWorkspaceDirectories()
        _DatabaseConnection = OpenDatabaseConnection()
    return _DatabaseConnection


def SafeJsonLoadList(raw: str) -> List[str]:
    try:
        value = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    result: List[str] = []
    for item in value:
        normalized = str(item).strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def CompactStringList(values: List[str], max_items: int = 4) -> str:
    if not values:
        return ""
    visible = values[:max_items]
    text = ", ".join(visible)
    hidden = len(values) - len(visible)
    if hidden > 0:
        text += f" (+{hidden} more)"
    return text


@dataclass
class UploadedFileAdapter:
    name: str
    type: str
    _data: bytes

    def getbuffer(self) -> memoryview:
        return memoryview(self._data)

    def getvalue(self) -> bytes:
        return self._data


async def BuildUploadAdapters(files: list[rx.UploadFile]) -> List[UploadedFileAdapter]:
    adapters: List[UploadedFileAdapter] = []
    for upload in files or []:
        fileBytes = await upload.read()
        fileName = str(getattr(upload, "filename", "") or "upload.bin")
        contentType = str(getattr(upload, "content_type", "") or "application/octet-stream")
        adapters.append(UploadedFileAdapter(name=fileName, type=contentType, _data=fileBytes))
    return adapters


CardSchemaOptionRows = [{"key": key, "label": definition["Label"]} for key, definition in CardSchemas.items()]
VerbFormOptionRows = [{"key": key, "label": label} for key, label in VerbFormLabels.items()]
AddDestinationOptions = [{"key": "global", "label": "Global pool"}, {"key": "deck", "label": "Deck"}]
ReviewReplaceTargetOptions = [
    {"key": "english", "label": "English"},
    {"key": "kana", "label": "Kana"},
    {"key": "kanji", "label": "Kanji"},
    {"key": "none", "label": "None"},
]
ReviewMediaTypeOptions = [
    {"key": "image", "label": "Image"},
    {"key": "audio", "label": "Audio"},
    {"key": "video", "label": "Video"},
]


class AnkiAppState(rx.State):
    current_page_key: str = GetDefaultPageKey()
    busy_action_name: str = ""
    status_level: str = "info"
    status_message: str = ""

    new_collection_name: str = ""
    rename_collection_id: str = ""
    rename_collection_name: str = ""

    new_deck_collection_id: str = ""
    new_deck_name: str = ""
    rename_deck_id: str = ""
    rename_deck_name: str = ""

    add_cards_query: str = ""
    add_cards_results: List[Dict[str, Any]] = []
    add_cards_selected_entry_ids: List[str] = []
    add_cards_destination: str = "global"
    add_cards_tags: str = "japanese,manual"
    add_cards_notes: str = ""
    add_cards_english_override: str = ""
    add_cards_deck_id: str = ""
    add_cards_schema_key: str = "kana_kanji_front_english_back"
    add_cards_word_form: str = "dictionary"

    global_autofill_query: str = ""
    global_autofill_results: List[Dict[str, Any]] = []
    global_autofill_selected_entry_ids: List[str] = []

    global_form_kanji: str = ""
    global_form_kana: str = ""
    global_form_english: str = ""
    global_form_notes: str = ""
    global_form_kanji_masu: str = ""
    global_form_kana_masu: str = ""
    global_form_kanji_te: str = ""
    global_form_kana_te: str = ""
    global_form_kanji_past: str = ""
    global_form_kana_past: str = ""
    global_form_kanji_negative: str = ""
    global_form_kana_negative: str = ""
    global_form_tags: str = "japanese,global_pool"
    global_form_dictionary_entry_id: str = ""
    global_form_dictionary_headword: str = ""
    global_form_dictionary_reading: str = ""
    global_form_dictionary_gloss: str = ""
    global_form_dictionary_pos: str = ""
    global_form_verb_type: str = ""

    global_source_deck_id: str = ""
    global_search_text: str = ""
    global_selected_card_ids: List[str] = []
    global_destination_deck_id: str = ""
    global_destination_schema_key: str = "kana_kanji_front_english_back"
    global_destination_word_form: str = "dictionary"
    global_import_tags: str = "japanese,global_import"

    review_deck_id: str = ""
    review_search_text: str = ""
    review_selected_card_ids: List[str] = []
    review_bulk_format: str = "kana_kanji_front_english_back"
    review_confirm_delete: bool = False

    single_edit_card_id: str = ""
    single_edit_kanji: str = ""
    single_edit_kana: str = ""
    single_edit_english: str = ""
    single_edit_notes: str = ""
    single_edit_schema_key: str = "kana_kanji_front_english_back"

    review_replace_target: str = "none"
    review_replace_media_type: str = "image"

    scan_deck_id: str = ""
    scan_schema_key: str = "kana_kanji_front_english_back"
    scan_tags: str = "japanese,image-scan"
    scan_word_form: str = "dictionary"
    scan_summary: str = ""
    scan_preview_rows: List[Dict[str, Any]] = []
    scan_errors: List[str] = []

    import_deck_id: str = ""
    export_deck_id: str = ""
    last_export_path: str = ""

    @rx.var
    def is_busy(self) -> bool:
        return bool(self.busy_action_name)

    @rx.var
    def has_status_message(self) -> bool:
        return bool(self.status_message.strip())

    @rx.var
    def status_background(self) -> str:
        if self.status_level == "error":
            return "#ffe8e6"
        if self.status_level == "warning":
            return "#fff3dc"
        if self.status_level == "success":
            return "#e6f4ea"
        return "#e6eef8"

    @rx.var
    def status_border(self) -> str:
        if self.status_level == "error":
            return "1px solid #cc2f25"
        if self.status_level == "warning":
            return "1px solid #d79820"
        if self.status_level == "success":
            return "1px solid #2f8f46"
        return "1px solid #3465a4"

    @rx.var
    def current_page_label(self) -> str:
        for page in PageDefinitions:
            if page.Key == self.current_page_key:
                return page.Label
        return PageDefinitions[0].Label

    @rx.var
    def current_page_description(self) -> str:
        for page in PageDefinitions:
            if page.Key == self.current_page_key:
                return page.Description
        return PageDefinitions[0].Description

    @rx.var(cache=False)
    def collection_options(self) -> List[Dict[str, str]]:
        collections = ListCollections(GetConnection())
        return [{"id": row["id"], "label": row["name"]} for row in collections]

    @rx.var(cache=False)
    def deck_options(self) -> List[Dict[str, str]]:
        decks = ListDecks(GetConnection(), includeCollectionName=True)
        return [{"id": row["id"], "label": FormatDeckLabel(row)} for row in decks]

    @rx.var
    def has_collection_options(self) -> bool:
        return bool(self.collection_options)

    @rx.var
    def has_deck_options(self) -> bool:
        return bool(self.deck_options)

    @rx.var(cache=False)
    def sidebar_collection_rows(self) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        connection = GetConnection()
        for collection in ListCollections(connection):
            decks = ListDecks(connection, collection["id"])
            deckLabels = [
                f"{deck['name']} ({CountCardsInDeck(connection, deck['id'])} cards)"
                for deck in decks
            ]
            rows.append(
                {
                    "collection_id": collection["id"],
                    "collection_name": collection["name"],
                    "deck_summary": CompactStringList(deckLabels),
                }
            )
        return rows

    @rx.var
    def has_sidebar_collection_rows(self) -> bool:
        return bool(self.sidebar_collection_rows)

    @rx.var(cache=False)
    def dashboard_collection_count(self) -> int:
        return len(ListCollections(GetConnection()))

    @rx.var(cache=False)
    def dashboard_deck_count(self) -> int:
        return GetTotalDeckCount(GetConnection())

    @rx.var(cache=False)
    def dashboard_card_count(self) -> int:
        return GetTotalCardCount(GetConnection())

    @rx.var(cache=False)
    def dashboard_global_card_count(self) -> int:
        return CountGlobalCards(GetConnection())

    @rx.var(cache=False)
    def dashboard_rows(self) -> List[Dict[str, Any]]:
        return [dict(row) for row in GetDashboardRows(GetConnection())]

    @rx.var
    def has_dashboard_rows(self) -> bool:
        return bool(self.dashboard_rows)

    @rx.var
    def selected_rename_collection_label(self) -> str:
        return self._collection_label_by_id(self.rename_collection_id)

    @rx.var
    def selected_new_deck_collection_label(self) -> str:
        return self._collection_label_by_id(self.new_deck_collection_id)

    @rx.var
    def selected_rename_deck_label(self) -> str:
        return self._deck_label_by_id(self.rename_deck_id)

    @rx.var
    def selected_add_cards_deck_label(self) -> str:
        return self._deck_label_by_id(self.add_cards_deck_id)

    @rx.var
    def selected_global_source_deck_label(self) -> str:
        return self._deck_label_by_id(self.global_source_deck_id)

    @rx.var
    def selected_global_destination_deck_label(self) -> str:
        return self._deck_label_by_id(self.global_destination_deck_id)

    @rx.var
    def selected_review_deck_label(self) -> str:
        return self._deck_label_by_id(self.review_deck_id)

    @rx.var
    def selected_scan_deck_label(self) -> str:
        return self._deck_label_by_id(self.scan_deck_id)

    @rx.var
    def selected_import_deck_label(self) -> str:
        return self._deck_label_by_id(self.import_deck_id)

    @rx.var
    def selected_export_deck_label(self) -> str:
        return self._deck_label_by_id(self.export_deck_id)

    @rx.var
    def add_cards_result_rows(self) -> List[Dict[str, Any]]:
        selectedIds = set(self.add_cards_selected_entry_ids)
        rows: List[Dict[str, Any]] = []
        for entry in self.add_cards_results:
            entryId = str(entry.get("entry_id", "") or "")
            if not entryId:
                continue
            rows.append(
                {
                    "entry_id": entryId,
                    "label": FormatDictionaryEntryOption(entry),
                    "selected": entryId in selectedIds,
                }
            )
        return rows

    @rx.var
    def has_add_cards_results(self) -> bool:
        return bool(self.add_cards_result_rows)

    @rx.var
    def add_cards_selected_count(self) -> int:
        return len(self.add_cards_selected_entry_ids)

    @rx.var
    def add_cards_preview_json(self) -> str:
        selectedEntries = self._get_selected_add_cards_entries()
        if not selectedEntries:
            return ""
        previewEntry = selectedEntries[0]
        extraTags = ParseCommaSeparatedTags(self.add_cards_tags)
        notes = self.add_cards_notes
        englishOverride = self.add_cards_english_override
        if self.add_cards_destination == "global":
            payload = BuildGlobalCardFromDictionaryEntry(
                previewEntry,
                tags=extraTags,
                notes=notes,
                englishOverride=englishOverride,
            )
            preview = {
                "kanji": payload.get("kanji", ""),
                "kana": payload.get("kana", ""),
                "english": payload.get("english", ""),
                "masu": f"{payload.get('kanji_masu', '')} [{payload.get('kana_masu', '')}]",
                "te": f"{payload.get('kanji_te', '')} [{payload.get('kana_te', '')}]",
                "past": f"{payload.get('kanji_past', '')} [{payload.get('kana_past', '')}]",
                "negative": f"{payload.get('kanji_negative', '')} [{payload.get('kana_negative', '')}]",
                "dictionary_entry_id": payload.get("dictionary_entry_id", ""),
            }
        else:
            payload = BuildCardFromDictionaryEntry(
                previewEntry,
                self.add_cards_schema_key,
                self.add_cards_word_form,
                extraTags,
                notes,
                englishOverride=englishOverride,
            )
            preview = {
                "kanji": payload.get("kanji", ""),
                "kana": payload.get("kana", ""),
                "english": payload.get("english", ""),
                "word_form": payload.get("word_form", ""),
                "dictionary_entry_id": payload.get("dictionary_entry_id", ""),
            }
        return json.dumps(preview, ensure_ascii=False, indent=2)

    @rx.var
    def add_cards_preview_note(self) -> str:
        selectedEntries = self._get_selected_add_cards_entries()
        if not selectedEntries:
            return ""
        previewEntry = selectedEntries[0]
        if self.add_cards_destination == "global":
            return ""
        if not IsVerbEntry(previewEntry):
            return "Preview entry is not a verb. Plain dictionary form is used."
        return f"Verb type: {previewEntry.get('verb_type_label', 'Verb')}"

    @rx.var
    def global_autofill_result_rows(self) -> List[Dict[str, Any]]:
        selectedIds = set(self.global_autofill_selected_entry_ids)
        rows: List[Dict[str, Any]] = []
        for entry in self.global_autofill_results:
            entryId = str(entry.get("entry_id", "") or "")
            if not entryId:
                continue
            rows.append(
                {
                    "entry_id": entryId,
                    "label": FormatDictionaryEntryOption(entry),
                    "selected": entryId in selectedIds,
                }
            )
        return rows

    @rx.var
    def has_global_autofill_results(self) -> bool:
        return bool(self.global_autofill_result_rows)

    @rx.var(cache=False)
    def global_card_total(self) -> int:
        return CountGlobalCards(GetConnection())

    @rx.var(cache=False)
    def filtered_global_card_rows(self) -> List[Dict[str, Any]]:
        normalizedSearch = self.global_search_text.strip().lower()
        selectedIds = set(self.global_selected_card_ids)
        rows: List[Dict[str, Any]] = []
        for row in ListGlobalCards(GetConnection()):
            searchableText = " ".join(
                [
                    row["kanji"] or "",
                    row["kana"] or "",
                    row["english"] or "",
                    row["dictionary_entry_id"] or "",
                ]
            ).lower()
            if normalizedSearch and normalizedSearch not in searchableText:
                continue
            rows.append(
                {
                    "id": row["id"],
                    "kanji": row["kanji"] or "",
                    "kana": row["kana"] or "",
                    "english": row["english"] or "",
                    "dictionary_entry_id": row["dictionary_entry_id"] or "",
                    "masu": row["kanji_masu"] or "",
                    "te": row["kanji_te"] or "",
                    "past": row["kanji_past"] or "",
                    "negative": row["kanji_negative"] or "",
                    "selected": row["id"] in selectedIds,
                    "label": f"{row['kanji']} [{row['kana']}] - {row['english']}",
                }
            )
        return rows

    @rx.var
    def has_filtered_global_cards(self) -> bool:
        return bool(self.filtered_global_card_rows)

    @rx.var
    def global_selected_count(self) -> int:
        return len(self.global_selected_card_ids)

    @rx.var(cache=False)
    def review_card_rows(self) -> List[Dict[str, Any]]:
        if not self.review_deck_id:
            return []
        selectedIds = set(self.review_selected_card_ids)
        normalizedSearch = self.review_search_text.strip().lower()
        rows: List[Dict[str, Any]] = []
        cards = GetDeckCards(GetConnection(), self.review_deck_id)
        for index, card in enumerate(cards, start=1):
            schemaLabel = CardSchemas.get(card["schema_key"], {}).get("Label", card["schema_key"])
            dictionaryId = card["dictionary_entry_id"] or ""
            searchable = " ".join(
                [
                    card["kanji"] or "",
                    card["kana"] or "",
                    card["english"] or "",
                    card["notes"] or "",
                    dictionaryId,
                ]
            ).lower()
            if normalizedSearch and normalizedSearch not in searchable:
                continue
            rows.append(
                {
                    "id": card["id"],
                    "index": index,
                    "kanji": card["kanji"] or "",
                    "kana": card["kana"] or "",
                    "english": card["english"] or "",
                    "notes": card["notes"] or "",
                    "schema_label": schemaLabel,
                    "word_form": card["word_form"] or "dictionary",
                    "dictionary_id": dictionaryId,
                    "selected": card["id"] in selectedIds,
                    "label": (
                        f"#{index} | {card['kanji']} [{card['kana']}] | "
                        f"{card['english']} | {schemaLabel}"
                    ),
                }
            )
        return rows

    @rx.var
    def has_review_cards(self) -> bool:
        return bool(self.review_card_rows)

    @rx.var
    def review_selected_count(self) -> int:
        return len(self.review_selected_card_ids)

    @rx.var
    def has_single_edit_card(self) -> bool:
        return bool(self.single_edit_card_id)

    @rx.var
    def single_edit_metadata_json(self) -> str:
        if not self.single_edit_card_id or not self.review_deck_id:
            return ""
        card = self._get_review_card_by_id(self.review_deck_id, self.single_edit_card_id)
        if card is None:
            return ""
        payload = {
            "kanji": card["kanji"] or "",
            "kana": card["kana"] or "",
            "english": card["english"] or "",
            "notes": card["notes"] or "",
            "schema": CardSchemas.get(card["schema_key"], {}).get("Label", card["schema_key"]),
            "word_form": card["word_form"] or "dictionary",
            "dictionary_entry_id": card["dictionary_entry_id"] or "",
            "dictionary_headword": card["dictionary_headword"] or "",
            "dictionary_reading": card["dictionary_reading"] or "",
            "dictionary_gloss": card["dictionary_gloss"] or "",
            "dictionary_pos": card["dictionary_pos"] or "",
            "media_type": card["media_type"] or "none",
            "media_files": SafeJsonLoadList(card["media_files_json"]),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    @rx.var(cache=False)
    def export_selected_deck_card_count(self) -> int:
        if not self.export_deck_id:
            return 0
        return CountCardsInDeck(GetConnection(), self.export_deck_id)

    @rx.var
    def has_scan_preview_rows(self) -> bool:
        return bool(self.scan_preview_rows)

    @rx.var
    def has_scan_errors(self) -> bool:
        return bool(self.scan_errors)

    def initialize(self) -> None:
        EnsureWorkspaceDirectories()
        GetConnection()
        self._sync_defaults()

    def clear_status(self) -> None:
        self.status_message = ""
        self.status_level = "info"

    def _set_status(self, level: str, message: str) -> None:
        self.status_level = level
        self.status_message = message

    def _begin_busy_action(self, actionName: str) -> bool:
        if self.is_busy:
            self._set_status("warning", "A request is already in progress.")
            return False
        self.busy_action_name = actionName
        return True

    def _end_busy_action(self) -> None:
        self.busy_action_name = ""

    def _collection_label_by_id(self, collectionId: str) -> str:
        for option in self.collection_options:
            if option["id"] == collectionId:
                return option["label"]
        return ""

    def _deck_label_by_id(self, deckId: str) -> str:
        for option in self.deck_options:
            if option["id"] == deckId:
                return option["label"]
        return ""

    def _sync_defaults(self) -> None:
        collectionIds = [row["id"] for row in self.collection_options]
        deckIds = [row["id"] for row in self.deck_options]

        def EnsureId(currentId: str, options: List[str]) -> str:
            if currentId in options:
                return currentId
            return options[0] if options else ""

        self.rename_collection_id = EnsureId(self.rename_collection_id, collectionIds)
        self.new_deck_collection_id = EnsureId(self.new_deck_collection_id, collectionIds)
        self.rename_deck_id = EnsureId(self.rename_deck_id, deckIds)
        self.add_cards_deck_id = EnsureId(self.add_cards_deck_id, deckIds)
        self.global_source_deck_id = EnsureId(self.global_source_deck_id, deckIds)
        self.global_destination_deck_id = EnsureId(self.global_destination_deck_id, deckIds)
        self.review_deck_id = EnsureId(self.review_deck_id, deckIds)
        self.scan_deck_id = EnsureId(self.scan_deck_id, deckIds)
        self.import_deck_id = EnsureId(self.import_deck_id, deckIds)
        self.export_deck_id = EnsureId(self.export_deck_id, deckIds)

        if self.review_selected_card_ids:
            validCardIds = {row["id"] for row in self.review_card_rows}
            self.review_selected_card_ids = [
                cardId for cardId in self.review_selected_card_ids if cardId in validCardIds
            ]
        self._sync_single_edit_card_form()

    def _get_selected_add_cards_entries(self) -> List[Dict[str, Any]]:
        byId: Dict[str, Dict[str, Any]] = {}
        for entry in self.add_cards_results:
            entryId = str(entry.get("entry_id", "") or "")
            if entryId:
                byId[entryId] = entry
        return [byId[entryId] for entryId in self.add_cards_selected_entry_ids if entryId in byId]

    def _get_selected_global_autofill_entries(self) -> List[Dict[str, Any]]:
        byId: Dict[str, Dict[str, Any]] = {}
        for entry in self.global_autofill_results:
            entryId = str(entry.get("entry_id", "") or "")
            if entryId:
                byId[entryId] = entry
        return [byId[entryId] for entryId in self.global_autofill_selected_entry_ids if entryId in byId]

    def _get_review_card_by_id(self, deckId: str, cardId: str) -> Optional[sqlite3.Row]:
        if not deckId or not cardId:
            return None
        cards = GetDeckCards(GetConnection(), deckId)
        for card in cards:
            if card["id"] == cardId:
                return card
        return None

    def _sync_single_edit_card_form(self) -> None:
        if len(self.review_selected_card_ids) != 1 or not self.review_deck_id:
            self.single_edit_card_id = ""
            self.single_edit_kanji = ""
            self.single_edit_kana = ""
            self.single_edit_english = ""
            self.single_edit_notes = ""
            self.single_edit_schema_key = "kana_kanji_front_english_back"
            return

        cardId = self.review_selected_card_ids[0]
        card = self._get_review_card_by_id(self.review_deck_id, cardId)
        if card is None:
            self.single_edit_card_id = ""
            return

        self.single_edit_card_id = card["id"]
        self.single_edit_kanji = card["kanji"] or ""
        self.single_edit_kana = card["kana"] or ""
        self.single_edit_english = card["english"] or ""
        self.single_edit_notes = card["notes"] or ""
        self.single_edit_schema_key = card["schema_key"] or "kana_kanji_front_english_back"

    def set_current_page(self, pageKey: str) -> None:
        self.current_page_key = pageKey
        self._sync_defaults()
        self.clear_status()

    def select_rename_collection(self, collectionId: str) -> None:
        self.rename_collection_id = collectionId

    def select_new_deck_collection(self, collectionId: str) -> None:
        self.new_deck_collection_id = collectionId

    def select_rename_deck(self, deckId: str) -> None:
        self.rename_deck_id = deckId

    def select_add_cards_deck(self, deckId: str) -> None:
        self.add_cards_deck_id = deckId

    def select_global_source_deck(self, deckId: str) -> None:
        self.global_source_deck_id = deckId

    def select_global_destination_deck(self, deckId: str) -> None:
        self.global_destination_deck_id = deckId

    def select_review_deck(self, deckId: str) -> None:
        self.review_deck_id = deckId
        self.review_selected_card_ids = []
        self.review_confirm_delete = False
        self._sync_single_edit_card_form()

    def select_scan_deck(self, deckId: str) -> None:
        self.scan_deck_id = deckId

    def select_import_deck(self, deckId: str) -> None:
        self.import_deck_id = deckId

    def select_export_deck(self, deckId: str) -> None:
        self.export_deck_id = deckId

    def set_add_cards_destination(self, destination: str) -> None:
        self.add_cards_destination = destination

    def set_add_cards_schema_key(self, schemaKey: str) -> None:
        self.add_cards_schema_key = schemaKey

    def set_add_cards_word_form(self, wordForm: str) -> None:
        self.add_cards_word_form = wordForm

    def set_global_destination_schema_key(self, schemaKey: str) -> None:
        self.global_destination_schema_key = schemaKey

    def set_global_destination_word_form(self, wordForm: str) -> None:
        self.global_destination_word_form = wordForm

    def set_review_bulk_format(self, schemaKey: str) -> None:
        self.review_bulk_format = schemaKey

    def set_single_edit_schema_key(self, schemaKey: str) -> None:
        self.single_edit_schema_key = schemaKey

    def set_review_replace_target(self, target: str) -> None:
        self.review_replace_target = target

    def set_review_replace_media_type(self, mediaType: str) -> None:
        self.review_replace_media_type = mediaType

    def set_scan_schema_key(self, schemaKey: str) -> None:
        self.scan_schema_key = schemaKey

    def set_scan_word_form(self, wordForm: str) -> None:
        self.scan_word_form = wordForm

    def set_new_collection_name(self, value: str) -> None:
        self.new_collection_name = value

    def set_rename_collection_name(self, value: str) -> None:
        self.rename_collection_name = value

    def set_new_deck_name(self, value: str) -> None:
        self.new_deck_name = value

    def set_rename_deck_name(self, value: str) -> None:
        self.rename_deck_name = value

    def set_add_cards_query(self, value: str) -> None:
        self.add_cards_query = value

    def set_add_cards_tags(self, value: str) -> None:
        self.add_cards_tags = value

    def set_add_cards_notes(self, value: str) -> None:
        self.add_cards_notes = value

    def set_add_cards_english_override(self, value: str) -> None:
        self.add_cards_english_override = value

    def set_global_autofill_query(self, value: str) -> None:
        self.global_autofill_query = value

    def set_global_form_kanji(self, value: str) -> None:
        self.global_form_kanji = value

    def set_global_form_kana(self, value: str) -> None:
        self.global_form_kana = value

    def set_global_form_english(self, value: str) -> None:
        self.global_form_english = value

    def set_global_form_notes(self, value: str) -> None:
        self.global_form_notes = value

    def set_global_form_kanji_masu(self, value: str) -> None:
        self.global_form_kanji_masu = value

    def set_global_form_kana_masu(self, value: str) -> None:
        self.global_form_kana_masu = value

    def set_global_form_kanji_te(self, value: str) -> None:
        self.global_form_kanji_te = value

    def set_global_form_kana_te(self, value: str) -> None:
        self.global_form_kana_te = value

    def set_global_form_kanji_past(self, value: str) -> None:
        self.global_form_kanji_past = value

    def set_global_form_kana_past(self, value: str) -> None:
        self.global_form_kana_past = value

    def set_global_form_kanji_negative(self, value: str) -> None:
        self.global_form_kanji_negative = value

    def set_global_form_kana_negative(self, value: str) -> None:
        self.global_form_kana_negative = value

    def set_global_form_tags(self, value: str) -> None:
        self.global_form_tags = value

    def set_global_form_dictionary_entry_id(self, value: str) -> None:
        self.global_form_dictionary_entry_id = value

    def set_global_form_dictionary_headword(self, value: str) -> None:
        self.global_form_dictionary_headword = value

    def set_global_form_dictionary_reading(self, value: str) -> None:
        self.global_form_dictionary_reading = value

    def set_global_form_dictionary_gloss(self, value: str) -> None:
        self.global_form_dictionary_gloss = value

    def set_global_form_dictionary_pos(self, value: str) -> None:
        self.global_form_dictionary_pos = value

    def set_global_form_verb_type(self, value: str) -> None:
        self.global_form_verb_type = value

    def set_global_search_text(self, value: str) -> None:
        self.global_search_text = value

    def set_global_import_tags(self, value: str) -> None:
        self.global_import_tags = value

    def set_review_search_text(self, value: str) -> None:
        self.review_search_text = value

    def set_single_edit_kanji(self, value: str) -> None:
        self.single_edit_kanji = value

    def set_single_edit_kana(self, value: str) -> None:
        self.single_edit_kana = value

    def set_single_edit_english(self, value: str) -> None:
        self.single_edit_english = value

    def set_single_edit_notes(self, value: str) -> None:
        self.single_edit_notes = value

    def set_scan_tags(self, value: str) -> None:
        self.scan_tags = value

    def create_collection(self) -> None:
        name = self.new_collection_name.strip()
        if not name:
            self._set_status("error", "Enter a collection name.")
            return
        try:
            CreateCollection(GetConnection(), name)
            self.new_collection_name = ""
            self._sync_defaults()
            self._set_status("success", "Collection created.")
        except sqlite3.IntegrityError:
            self._set_status("error", "A collection with that name already exists.")

    def rename_collection(self) -> None:
        newName = self.rename_collection_name.strip()
        if not self.rename_collection_id:
            self._set_status("warning", "Select a collection to rename.")
            return
        if not newName:
            self._set_status("error", "Enter a new collection name.")
            return
        try:
            RenameCollection(GetConnection(), self.rename_collection_id, newName)
            self.rename_collection_name = ""
            self._sync_defaults()
            self._set_status("success", "Collection renamed.")
        except sqlite3.IntegrityError:
            self._set_status("error", "A collection with that name already exists.")

    def create_deck(self) -> None:
        deckName = self.new_deck_name.strip()
        if not self.new_deck_collection_id:
            self._set_status("warning", "Select a collection first.")
            return
        if not deckName:
            self._set_status("error", "Enter a deck name.")
            return
        try:
            CreateDeck(GetConnection(), self.new_deck_collection_id, deckName)
            self.new_deck_name = ""
            self._sync_defaults()
            self._set_status("success", "Deck created.")
        except sqlite3.IntegrityError:
            self._set_status("error", "A deck with that name already exists in this collection.")

    def rename_deck(self) -> None:
        newName = self.rename_deck_name.strip()
        if not self.rename_deck_id:
            self._set_status("warning", "Select a deck to rename.")
            return
        if not newName:
            self._set_status("error", "Enter a new deck name.")
            return
        try:
            RenameDeck(GetConnection(), self.rename_deck_id, newName)
            self.rename_deck_name = ""
            self._sync_defaults()
            self._set_status("success", "Deck renamed.")
        except sqlite3.IntegrityError:
            self._set_status("error", "A deck with that name already exists in this collection.")

    def search_add_cards_dictionary(self) -> None:
        query = self.add_cards_query.strip()
        self.add_cards_selected_entry_ids = []
        if not query:
            self.add_cards_results = []
            self._set_status("info", "Type a word to search jamdict.")
            return
        try:
            self.add_cards_results = SearchDictionaryEntries(query, limit=50)
            if self.add_cards_results:
                self._set_status("success", f"Found {len(self.add_cards_results)} dictionary entries.")
            else:
                self._set_status("warning", "No dictionary entries found for this search.")
        except Exception as exc:
            self.add_cards_results = []
            self._set_status("error", str(exc))

    def clear_add_cards_search(self) -> None:
        self.add_cards_query = ""
        self.add_cards_results = []
        self.add_cards_selected_entry_ids = []

    def toggle_add_cards_entry_selection(self, entryId: str) -> None:
        selected = list(self.add_cards_selected_entry_ids)
        if entryId in selected:
            selected.remove(entryId)
        else:
            selected.append(entryId)
        self.add_cards_selected_entry_ids = selected

    def add_selected_dictionary_entries(self) -> None:
        selectedEntries = self._get_selected_add_cards_entries()
        if not selectedEntries:
            self._set_status("warning", "Select one or more dictionary entries first.")
            return

        connection = GetConnection()
        added = 0
        skipped = 0
        extraTags = ParseCommaSeparatedTags(self.add_cards_tags)
        notes = self.add_cards_notes
        englishOverride = self.add_cards_english_override
        destination = self.add_cards_destination

        for entry in selectedEntries:
            if destination == "global":
                payload = BuildGlobalCardFromDictionaryEntry(
                    entry,
                    tags=extraTags,
                    notes=notes,
                    englishOverride=englishOverride,
                )
                isAdded = AddGlobalCard(connection, payload)
            else:
                if not self.add_cards_deck_id:
                    isAdded = False
                else:
                    payload = BuildCardFromDictionaryEntry(
                        entry,
                        self.add_cards_schema_key,
                        self.add_cards_word_form,
                        extraTags,
                        notes,
                        englishOverride=englishOverride,
                    )
                    isAdded = AddCard(connection, self.add_cards_deck_id, payload)

            added += int(isAdded)
            skipped += int(not isAdded)

        self._set_status("success", f"Added {added} card(s); skipped {skipped} duplicate/invalid card(s).")
        self._sync_defaults()

    def search_global_autofill_dictionary(self) -> None:
        query = self.global_autofill_query.strip()
        self.global_autofill_selected_entry_ids = []
        if not query:
            self.global_autofill_results = []
            self._set_status("info", "Type a word to search jamdict.")
            return
        try:
            self.global_autofill_results = SearchDictionaryEntries(query, limit=50)
            if self.global_autofill_results:
                self._set_status("success", f"Found {len(self.global_autofill_results)} dictionary entries.")
            else:
                self._set_status("warning", "No dictionary entries found for this search.")
        except Exception as exc:
            self.global_autofill_results = []
            self._set_status("error", str(exc))

    def clear_global_autofill_search(self) -> None:
        self.global_autofill_query = ""
        self.global_autofill_results = []
        self.global_autofill_selected_entry_ids = []

    def toggle_global_autofill_entry_selection(self, entryId: str) -> None:
        selected = list(self.global_autofill_selected_entry_ids)
        if entryId in selected:
            selected.remove(entryId)
        else:
            selected.append(entryId)
        self.global_autofill_selected_entry_ids = selected

    def autofill_global_form_from_selected(self) -> None:
        selectedEntries = self._get_selected_global_autofill_entries()
        if not selectedEntries:
            self._set_status("warning", "Select at least one dictionary entry to autofill.")
            return
        payload = BuildGlobalCardFromDictionaryEntry(selectedEntries[0], tags=["manual", "global_pool"])
        self.global_form_kanji = payload.get("kanji", "")
        self.global_form_kana = payload.get("kana", "")
        self.global_form_english = payload.get("english", "")
        self.global_form_notes = payload.get("notes", "")
        self.global_form_kanji_masu = payload.get("kanji_masu", "")
        self.global_form_kana_masu = payload.get("kana_masu", "")
        self.global_form_kanji_te = payload.get("kanji_te", "")
        self.global_form_kana_te = payload.get("kana_te", "")
        self.global_form_kanji_past = payload.get("kanji_past", "")
        self.global_form_kana_past = payload.get("kana_past", "")
        self.global_form_kanji_negative = payload.get("kanji_negative", "")
        self.global_form_kana_negative = payload.get("kana_negative", "")
        self.global_form_dictionary_entry_id = payload.get("dictionary_entry_id", "")
        self.global_form_dictionary_headword = payload.get("dictionary_headword", "")
        self.global_form_dictionary_reading = payload.get("dictionary_reading", "")
        self.global_form_dictionary_gloss = payload.get("dictionary_gloss", "")
        self.global_form_dictionary_pos = payload.get("dictionary_pos", "")
        self.global_form_verb_type = payload.get("verb_type", "")
        self._set_status("success", "Global card form fields were filled from dictionary data.")

    async def add_global_card(self, mediaFiles: list[rx.UploadFile]) -> Any:
        normalizedKanji = self.global_form_kanji.strip()
        normalizedKana = self.global_form_kana.strip()
        normalizedEnglish = self.global_form_english.strip()
        if not normalizedKanji or not normalizedKana or not normalizedEnglish:
            self._set_status("error", "Kanji + okurigana, kana, and english are required.")
            return

        mediaAdapters = await BuildUploadAdapters(mediaFiles)
        imageAdapters: List[UploadedFileAdapter] = []
        videoAdapters: List[UploadedFileAdapter] = []
        for upload in mediaAdapters:
            suffix = Path(upload.name).suffix.lower()
            if suffix in SupportedImageExtensions or upload.type.startswith("image/"):
                imageAdapters.append(upload)
                continue
            if suffix in SupportedVideoExtensions or upload.type.startswith("video/"):
                videoAdapters.append(upload)
                continue

        savedImagePaths = [CopyUploadedMedia(upload, "_global_pool") for upload in imageAdapters]
        savedVideoPaths = [CopyUploadedMedia(upload, "_global_pool") for upload in videoAdapters]

        payload = {
            "kanji": normalizedKanji,
            "kana": normalizedKana,
            "english": normalizedEnglish,
            "notes": self.global_form_notes.strip(),
            "kanji_masu": self.global_form_kanji_masu.strip(),
            "kana_masu": self.global_form_kana_masu.strip(),
            "kanji_te": self.global_form_kanji_te.strip(),
            "kana_te": self.global_form_kana_te.strip(),
            "kanji_past": self.global_form_kanji_past.strip(),
            "kana_past": self.global_form_kana_past.strip(),
            "kanji_negative": self.global_form_kanji_negative.strip(),
            "kana_negative": self.global_form_kana_negative.strip(),
            "image_files": savedImagePaths,
            "video_files": savedVideoPaths,
            "tags": ParseCommaSeparatedTags(self.global_form_tags),
            "dictionary_entry_id": self.global_form_dictionary_entry_id.strip(),
            "dictionary_headword": self.global_form_dictionary_headword.strip(),
            "dictionary_reading": self.global_form_dictionary_reading.strip(),
            "dictionary_gloss": self.global_form_dictionary_gloss.strip(),
            "dictionary_pos": self.global_form_dictionary_pos.strip(),
            "verb_type": self.global_form_verb_type.strip(),
        }
        isAdded = AddGlobalCard(GetConnection(), payload)
        if isAdded:
            self._set_status("success", "Global card added.")
        else:
            self._set_status("warning", "Global card skipped (duplicate or invalid).")
        self._sync_defaults()
        return rx.clear_selected_files("global_media_upload")

    def import_selected_deck_to_global_pool(self) -> None:
        if not self.global_source_deck_id:
            self._set_status("warning", "Select a source deck first.")
            return
        added, skipped = ImportDeckCardsToGlobal(GetConnection(), self.global_source_deck_id)
        self._set_status(
            "success",
            f"Imported {added} card(s) from deck; skipped {skipped} duplicate/invalid card(s).",
        )
        self._sync_defaults()

    def toggle_global_card_selection(self, globalCardId: str) -> None:
        selected = list(self.global_selected_card_ids)
        if globalCardId in selected:
            selected.remove(globalCardId)
        else:
            selected.append(globalCardId)
        self.global_selected_card_ids = selected

    def clear_global_card_selection(self) -> None:
        self.global_selected_card_ids = []

    def import_selected_global_cards_to_deck(self) -> None:
        if not self.global_destination_deck_id:
            self._set_status("warning", "Select a destination deck first.")
            return
        if not self.global_selected_card_ids:
            self._set_status("warning", "Select one or more global cards to import.")
            return
        added, skipped = ImportGlobalCardsToDeck(
            GetConnection(),
            self.global_destination_deck_id,
            self.global_selected_card_ids,
            self.global_destination_schema_key,
            self.global_destination_word_form,
            extraTags=ParseCommaSeparatedTags(self.global_import_tags),
        )
        self._set_status(
            "success",
            f"Imported {added} card(s) into deck; skipped {skipped} duplicate/invalid card(s).",
        )
        self._sync_defaults()

    def toggle_review_card_selection(self, cardId: str) -> None:
        selected = list(self.review_selected_card_ids)
        if cardId in selected:
            selected.remove(cardId)
        else:
            selected.append(cardId)
        self.review_selected_card_ids = selected
        self._sync_single_edit_card_form()

    def select_all_visible_review_cards(self) -> None:
        self.review_selected_card_ids = [row["id"] for row in self.review_card_rows]
        self._sync_single_edit_card_form()

    def clear_review_card_selection(self) -> None:
        self.review_selected_card_ids = []
        self.review_confirm_delete = False
        self._sync_single_edit_card_form()

    def toggle_review_confirm_delete(self) -> None:
        self.review_confirm_delete = not self.review_confirm_delete

    def apply_review_bulk_format(self) -> None:
        if not self.review_deck_id:
            self._set_status("warning", "Select a deck first.")
            return
        if not self.review_selected_card_ids:
            self._set_status("warning", "Select one or more cards first.")
            return
        updatedCount = UpdateCardsSchemaByIds(
            GetConnection(),
            self.review_deck_id,
            self.review_selected_card_ids,
            self.review_bulk_format,
        )
        skippedCount = len(self.review_selected_card_ids) - updatedCount
        parts = [f"Updated format for {updatedCount} card(s)"]
        if skippedCount:
            parts.append(f"skipped {skippedCount} duplicate word(s)")
        self._set_status("success", "; ".join(parts) + ".")
        self._sync_defaults()

    def delete_selected_review_cards(self) -> None:
        if not self.review_deck_id:
            self._set_status("warning", "Select a deck first.")
            return
        if not self.review_selected_card_ids:
            self._set_status("warning", "Select one or more cards first.")
            return
        if not self.review_confirm_delete:
            self._set_status("warning", "Confirm delete before removing selected cards.")
            return
        deletedCount = DeleteCardsByIds(GetConnection(), self.review_deck_id, self.review_selected_card_ids)
        self.review_selected_card_ids = []
        self.review_confirm_delete = False
        self._sync_single_edit_card_form()
        self._set_status("success", f"Deleted {deletedCount} card(s).")
        self._sync_defaults()

    def save_single_review_card_changes(self) -> None:
        if not self.review_deck_id or not self.single_edit_card_id:
            self._set_status("warning", "Select exactly one card first.")
            return
        isUpdated = UpdateCardContent(
            GetConnection(),
            self.review_deck_id,
            self.single_edit_card_id,
            self.single_edit_kanji,
            self.single_edit_kana,
            self.single_edit_english,
            self.single_edit_notes,
            self.single_edit_schema_key,
        )
        if isUpdated:
            self._set_status("success", "Card updated.")
        else:
            self._set_status("warning", "Update skipped: duplicate word already exists in this format.")
        self._sync_defaults()

    async def apply_single_review_media_replacement(self, files: list[rx.UploadFile]) -> Any:
        if not self.review_deck_id or not self.single_edit_card_id:
            self._set_status("warning", "Select exactly one card first.")
            return
        if self.review_replace_target == "none":
            self._set_status("warning", "Pick a text target to replace.")
            return
        uploadAdapters = await BuildUploadAdapters(files)
        if not uploadAdapters:
            self._set_status("warning", "Upload at least one media file.")
            return
        try:
            savedPaths = [CopyUploadedMedia(upload, self.review_deck_id) for upload in uploadAdapters]
            if self.review_replace_target in {"english", "kana", "kanji"}:
                UpdateCardField(
                    GetConnection(),
                    self.single_edit_card_id,
                    self.review_replace_target,
                    f"[{self.review_replace_media_type.upper()}]",
                )
            UpdateCardMedia(
                GetConnection(),
                self.single_edit_card_id,
                self.review_replace_media_type,
                savedPaths,
            )
            self._set_status("success", "Media attached to card.")
            self._sync_defaults()
        except sqlite3.IntegrityError:
            self._set_status("error", "Media replacement skipped: duplicate word already exists in this format.")
        return rx.clear_selected_files("review_media_upload")

    async def scan_images_and_add_missing_cards(self, files: list[rx.UploadFile]) -> Any:
        if not self.scan_deck_id:
            self._set_status("warning", "Select a destination deck first.")
            return
        uploadAdapters = await BuildUploadAdapters(files)
        if not uploadAdapters:
            self._set_status("warning", "Upload one or more images to scan.")
            return
        if not self._begin_busy_action("Scanning images and adding missing cards"):
            return

        self.scan_summary = ""
        self.scan_preview_rows = []
        self.scan_errors = []
        connection = GetConnection()
        try:
            client = GetOpenAiClient()
            extractedCandidates, errors = ExtractCardsFromImages(
                client,
                DefaultModel,
                uploadAdapters,
                progressCallback=None,
            )
            expandedCandidates = ExpandExtractedScanCandidates(
                extractedCandidates,
                dictionaryLookup=lambda query: SearchDictionaryEntries(query, limit=1),
            )

            resolvedCards: List[Dict[str, Any]] = []
            previewRows: List[Dict[str, Any]] = []
            dictionaryMatchedCount = 0
            dictionaryMissCount = 0
            politeSurfaceSkippedCount = 0
            duplicateEntrySkippedCount = 0
            seenSurfaceAndForm = set()
            extraTags = ParseCommaSeparatedTags(self.scan_tags)

            for candidate in expandedCandidates:
                resolvedEntry = ResolveBestDictionaryEntry(
                    sourceKanji=candidate.get("kanji", ""),
                    sourceKana=candidate.get("kana", ""),
                    visibleText=candidate.get("visible_text", ""),
                )
                noteText = BuildScanCandidateNote(candidate)
                sourceText = candidate.get("origin_visible_text") or candidate.get("visible_text", "")
                if resolvedEntry:
                    card = BuildCardFromDictionaryEntry(
                        resolvedEntry,
                        self.scan_schema_key,
                        self.scan_word_form,
                        extraTags + ["image_ocr"],
                        notes=noteText,
                        sourceText=sourceText,
                    )
                else:
                    dictionaryMissCount += 1
                    continue

                if self.scan_word_form == "dictionary" and (
                    LooksLikePoliteMasuSurface(card.get("kanji", ""))
                    or LooksLikePoliteMasuSurface(card.get("kana", ""))
                ):
                    politeSurfaceSkippedCount += 1
                    continue

                cardWordForm = (card.get("word_form") or "dictionary").strip() or "dictionary"
                surfaceKey = (card.get("kanji") or card.get("dictionary_headword") or card.get("kana") or "").strip()
                dedupeKey = (surfaceKey, cardWordForm)
                if surfaceKey and dedupeKey in seenSurfaceAndForm:
                    duplicateEntrySkippedCount += 1
                    continue
                if surfaceKey:
                    seenSurfaceAndForm.add(dedupeKey)

                dictionaryMatchedCount += 1
                resolvedCards.append(card)
                previewRows.append(
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
            for card in resolvedCards:
                if DeckHasKanjiWordForm(
                    connection,
                    self.scan_deck_id,
                    card.get("schema_key", ""),
                    card.get("word_form", "dictionary"),
                    card.get("kanji", ""),
                ):
                    duplicates += 1
                    continue
                if DeckHasCandidate(connection, self.scan_deck_id, card):
                    duplicates += 1
                    continue
                if AddCard(connection, self.scan_deck_id, card):
                    added += 1

            self.scan_summary = (
                f"Scanned {len(uploadAdapters)} images. Added {added} new cards and skipped {duplicates} duplicates.\n"
                f"OCR produced {len(extractedCandidates)} raw candidate(s), expanded to {len(expandedCandidates)} term candidate(s).\n"
                f"Dictionary matched {dictionaryMatchedCount} candidate(s); "
                f"skipped {dictionaryMissCount} unmatched candidate(s); "
                f"skipped {politeSurfaceSkippedCount} candidate(s) that still looked like polite/masu while dictionary form was selected; "
                f"skipped {duplicateEntrySkippedCount} duplicate dictionary-entry candidate(s)."
            )
            self.scan_preview_rows = previewRows
            self.scan_errors = errors
            self._set_status("success", "Image scan complete.")
            self._sync_defaults()
        except Exception as exc:
            self.scan_errors = [str(exc)]
            self._set_status("error", str(exc))
        finally:
            self._end_busy_action()
        return rx.clear_selected_files("scan_images_upload")

    async def import_csv_cards(self, files: list[rx.UploadFile]) -> Any:
        if not self.import_deck_id:
            self._set_status("warning", "Select a destination deck first.")
            return
        uploadAdapters = await BuildUploadAdapters(files)
        if not uploadAdapters:
            self._set_status("warning", "Upload a CSV file first.")
            return
        if not self._begin_busy_action("Importing CSV cards"):
            return
        try:
            added, skipped = ImportCsvCards(GetConnection(), self.import_deck_id, uploadAdapters[0])
            self._set_status("success", f"Added {added} cards and skipped {skipped} duplicates.")
            self._sync_defaults()
        except Exception as exc:
            self._set_status("error", str(exc))
        finally:
            self._end_busy_action()
        return rx.clear_selected_files("import_csv_upload")

    def export_selected_deck_package(self) -> Any:
        if not self.export_deck_id:
            self._set_status("warning", "Select a deck first.")
            return
        if not self._begin_busy_action("Exporting Anki package"):
            return
        try:
            path = ExportDeckPackage(GetConnection(), self.export_deck_id)
            self.last_export_path = str(path)
            self._set_status("success", f"Exported to {path}")
            self._sync_defaults()
            return rx.download(data=path.read_bytes(), filename=path.name)
        except Exception as exc:
            self._set_status("error", str(exc))
            return None
        finally:
            self._end_busy_action()


def section_box(title: str, description: str = "", *children: rx.Component) -> rx.Component:
    descriptionRow = rx.text(description, color=ThemeStyles["MutedText"], size="2") if description else rx.box()
    return rx.box(
        rx.vstack(
            rx.heading(title, size="5"),
            descriptionRow,
            *children,
            spacing="3",
            align="stretch",
            width="100%",
        ),
        background=ThemeStyles["CardBackground"],
        border=ThemeStyles["CardBorder"],
        border_radius="10px",
        padding="16px",
        width="100%",
    )


def choice_button(
    label: str,
    is_selected: rx.Var,
    on_click: Any,
    disabled: rx.Var,
) -> rx.Component:
    return rx.button(
        label,
        on_click=on_click,
        disabled=disabled,
        background=rx.cond(is_selected, "#dce9d6", "white"),
        color="#1f2d1b",
        border="1px solid #c5d4bd",
        border_radius="8px",
        size="2",
    )


def deck_picker(
    title: str,
    selected_label: rx.Var,
    on_pick: Callable[[str], Any],
) -> rx.Component:
    return section_box(
        title,
        "",
        rx.hstack(rx.text("Selected:"), rx.text(selected_label)),
        rx.cond(
            AnkiAppState.has_deck_options,
            rx.flex(
                rx.foreach(
                    AnkiAppState.deck_options,
                    lambda option: choice_button(
                        option["label"],
                        selected_label == option["label"],
                        on_pick(option["id"]),
                        AnkiAppState.is_busy,
                    ),
                ),
                wrap="wrap",
                gap="8px",
            ),
            rx.text("No decks yet."),
        ),
    )


def collection_picker(
    title: str,
    selected_label: rx.Var,
    on_pick: Callable[[str], Any],
) -> rx.Component:
    return section_box(
        title,
        "",
        rx.hstack(rx.text("Selected:"), rx.text(selected_label)),
        rx.cond(
            AnkiAppState.has_collection_options,
            rx.flex(
                rx.foreach(
                    AnkiAppState.collection_options,
                    lambda option: choice_button(
                        option["label"],
                        selected_label == option["label"],
                        on_pick(option["id"]),
                        AnkiAppState.is_busy,
                    ),
                ),
                wrap="wrap",
                gap="8px",
            ),
            rx.text("No collections yet."),
        ),
    )


def schema_picker(
    title: str,
    selected_key: rx.Var,
    on_pick: Callable[[str], Any],
) -> rx.Component:
    return section_box(
        title,
        "",
        rx.flex(
            *[
                choice_button(
                    option["label"],
                    selected_key == option["key"],
                    on_pick(option["key"]),
                    AnkiAppState.is_busy,
                )
                for option in CardSchemaOptionRows
            ],
            wrap="wrap",
            gap="8px",
        ),
    )


def word_form_picker(
    title: str,
    selected_key: rx.Var,
    on_pick: Callable[[str], Any],
) -> rx.Component:
    return section_box(
        title,
        "",
        rx.flex(
            *[
                choice_button(
                    option["label"],
                    selected_key == option["key"],
                    on_pick(option["key"]),
                    AnkiAppState.is_busy,
                )
                for option in VerbFormOptionRows
            ],
            wrap="wrap",
            gap="8px",
        ),
    )


def sidebar() -> rx.Component:
    pageButtons: List[rx.Component] = []
    for section in SectionOrder:
        pageButtons.append(
            rx.text(
                section,
                weight="bold",
                color=ThemeStyles["MutedText"],
                margin_top="6px",
            )
        )
        for page in PageDefinitions:
            if page.Section != section:
                continue
            pageButtons.append(
                rx.button(
                    rx.cond(
                        AnkiAppState.current_page_key == page.Key,
                        f"> {page.Label}",
                        page.Label,
                    ),
                    on_click=AnkiAppState.set_current_page(page.Key),
                    disabled=AnkiAppState.is_busy,
                    width="100%",
                    justify="start",
                    background=rx.cond(
                        AnkiAppState.current_page_key == page.Key,
                        "#d8e4d2",
                        "transparent",
                    ),
                    border="1px solid #cbd8c3",
                    color="#1f2d1b",
                    border_radius="8px",
                    size="2",
                )
            )

    return rx.box(
        rx.vstack(
            rx.heading(AppTitle, size="5"),
            rx.text(f"Workspace: {AppDir.resolve()}", size="1", color=ThemeStyles["MutedText"]),
            rx.box(height="1px", width="100%", background="#cfd9bf"),
            *pageButtons,
            rx.box(height="1px", width="100%", background="#cfd9bf"),
            rx.heading("Current collections", size="4"),
            rx.cond(
                AnkiAppState.has_sidebar_collection_rows,
                rx.vstack(
                    rx.foreach(
                        AnkiAppState.sidebar_collection_rows,
                        lambda row: rx.box(
                            rx.text(row["collection_name"], weight="bold"),
                            rx.cond(
                                row["deck_summary"] != "",
                                rx.text(row["deck_summary"], size="1", color=ThemeStyles["MutedText"]),
                                rx.text("No decks", size="1", color=ThemeStyles["MutedText"]),
                            ),
                            width="100%",
                            padding_y="4px",
                        ),
                    ),
                    align="stretch",
                    spacing="2",
                    width="100%",
                ),
                rx.text("No collections yet.", size="2"),
            ),
            spacing="3",
            align="stretch",
            width="100%",
        ),
        width="320px",
        min_width="300px",
        background=ThemeStyles["SidebarBackground"],
        border_right=ThemeStyles["SidebarBorder"],
        padding="16px",
        min_height="100vh",
    )


def dashboard_page() -> rx.Component:
    return rx.vstack(
        rx.flex(
            section_box("Collections", "", rx.heading(AnkiAppState.dashboard_collection_count, size="6")),
            section_box("Decks", "", rx.heading(AnkiAppState.dashboard_deck_count, size="6")),
            section_box("Deck Cards", "", rx.heading(AnkiAppState.dashboard_card_count, size="6")),
            section_box("Global Cards", "", rx.heading(AnkiAppState.dashboard_global_card_count, size="6")),
            wrap="wrap",
            gap="10px",
            width="100%",
        ),
        section_box(
            "Deck Summary",
            "",
            rx.cond(
                AnkiAppState.has_dashboard_rows,
                rx.vstack(
                    rx.foreach(
                        AnkiAppState.dashboard_rows,
                        lambda row: rx.hstack(
                            rx.text(row["collection_name"], width="32%"),
                            rx.text(row["deck_name"], width="42%"),
                            rx.hstack(rx.text(row["card_count"]), rx.text("cards"), width="26%"),
                            width="100%",
                            border_bottom="1px solid #e2e8d0",
                            padding_y="6px",
                        ),
                    ),
                    align="stretch",
                    spacing="0",
                    width="100%",
                ),
                rx.text("Create a collection and a deck to get started."),
            ),
        ),
        spacing="3",
        width="100%",
    )


def collections_page() -> rx.Component:
    return rx.vstack(
        section_box(
            "Create Collection",
            "",
            rx.input(
                value=AnkiAppState.new_collection_name,
                on_change=AnkiAppState.set_new_collection_name,
                placeholder="New collection name",
            ),
            rx.button(
                "Add collection",
                on_click=AnkiAppState.create_collection,
                disabled=AnkiAppState.is_busy,
                width="220px",
            ),
        ),
        collection_picker(
            "Collection to Rename",
            AnkiAppState.selected_rename_collection_label,
            AnkiAppState.select_rename_collection,
        ),
        section_box(
            "Rename Collection",
            "",
            rx.input(
                value=AnkiAppState.rename_collection_name,
                on_change=AnkiAppState.set_rename_collection_name,
                placeholder="New collection name",
            ),
            rx.button(
                "Rename collection",
                on_click=AnkiAppState.rename_collection,
                disabled=AnkiAppState.is_busy,
                width="220px",
            ),
        ),
        spacing="3",
        width="100%",
    )


def decks_page() -> rx.Component:
    return rx.vstack(
        collection_picker(
            "Collection for New Deck",
            AnkiAppState.selected_new_deck_collection_label,
            AnkiAppState.select_new_deck_collection,
        ),
        section_box(
            "Create Deck",
            "",
            rx.input(
                value=AnkiAppState.new_deck_name,
                on_change=AnkiAppState.set_new_deck_name,
                placeholder="New deck name",
            ),
            rx.button(
                "Add deck",
                on_click=AnkiAppState.create_deck,
                disabled=AnkiAppState.is_busy,
                width="220px",
            ),
        ),
        deck_picker(
            "Deck to Rename",
            AnkiAppState.selected_rename_deck_label,
            AnkiAppState.select_rename_deck,
        ),
        section_box(
            "Rename Deck",
            "",
            rx.input(
                value=AnkiAppState.rename_deck_name,
                on_change=AnkiAppState.set_rename_deck_name,
                placeholder="New deck name",
            ),
            rx.button(
                "Rename deck",
                on_click=AnkiAppState.rename_deck,
                disabled=AnkiAppState.is_busy,
                width="220px",
            ),
        ),
        spacing="3",
        width="100%",
    )


def add_cards_page() -> rx.Component:
    return rx.vstack(
        section_box(
            "Live Dictionary Search",
            "Type kanji or kana (example: 食べる, たべる, 勉強)",
            rx.hstack(
                rx.input(
                    value=AnkiAppState.add_cards_query,
                    on_change=AnkiAppState.set_add_cards_query,
                    placeholder="Search word",
                    width="100%",
                ),
                rx.button("Search", on_click=AnkiAppState.search_add_cards_dictionary, disabled=AnkiAppState.is_busy),
                rx.button("Clear", on_click=AnkiAppState.clear_add_cards_search, disabled=AnkiAppState.is_busy),
                width="100%",
            ),
            rx.cond(
                AnkiAppState.has_add_cards_results,
                rx.vstack(
                    rx.foreach(
                        AnkiAppState.add_cards_result_rows,
                        lambda row: rx.hstack(
                            rx.text(row["label"], width="82%"),
                            rx.button(
                                rx.cond(row["selected"], "Remove", "Select"),
                                on_click=AnkiAppState.toggle_add_cards_entry_selection(row["entry_id"]),
                                disabled=AnkiAppState.is_busy,
                                width="120px",
                            ),
                            width="100%",
                            border_bottom="1px solid #e2e8d0",
                            padding_y="6px",
                        ),
                    ),
                    align="stretch",
                    spacing="0",
                    width="100%",
                ),
                rx.text("Search jamdict and select one or more entries."),
            ),
            rx.hstack(rx.text("Selected entries:"), rx.text(AnkiAppState.add_cards_selected_count)),
        ),
        section_box(
            "Destination",
            "",
            rx.flex(
                *[
                    choice_button(
                        option["label"],
                        AnkiAppState.add_cards_destination == option["key"],
                        AnkiAppState.set_add_cards_destination(option["key"]),
                        AnkiAppState.is_busy,
                    )
                    for option in AddDestinationOptions
                ],
                wrap="wrap",
                gap="8px",
            ),
        ),
        rx.cond(
            AnkiAppState.add_cards_destination == "deck",
            deck_picker(
                "Destination Deck",
                AnkiAppState.selected_add_cards_deck_label,
                AnkiAppState.select_add_cards_deck,
            ),
        ),
        rx.cond(
            AnkiAppState.add_cards_destination == "deck",
            schema_picker("Card Format", AnkiAppState.add_cards_schema_key, AnkiAppState.set_add_cards_schema_key),
        ),
        rx.cond(
            AnkiAppState.add_cards_destination == "deck",
            word_form_picker("Word Form for Verbs", AnkiAppState.add_cards_word_form, AnkiAppState.set_add_cards_word_form),
        ),
        section_box(
            "Extra Fields",
            "",
            rx.input(
                value=AnkiAppState.add_cards_tags,
                on_change=AnkiAppState.set_add_cards_tags,
                placeholder="Extra tags (comma separated)",
            ),
            rx.text_area(
                value=AnkiAppState.add_cards_notes,
                on_change=AnkiAppState.set_add_cards_notes,
                placeholder="Notes (optional)",
            ),
            rx.input(
                value=AnkiAppState.add_cards_english_override,
                on_change=AnkiAppState.set_add_cards_english_override,
                placeholder="English override for selected entries (optional)",
            ),
        ),
        section_box(
            "Preview (first selected entry)",
            "",
            rx.cond(
                AnkiAppState.add_cards_preview_json != "",
                rx.text(AnkiAppState.add_cards_preview_json, white_space="pre-wrap", font_family="monospace"),
                rx.text("Select at least one dictionary entry."),
            ),
            rx.cond(
                AnkiAppState.add_cards_preview_note != "",
                rx.text(AnkiAppState.add_cards_preview_note, size="2", color=ThemeStyles["MutedText"]),
            ),
        ),
        section_box(
            "Create Cards",
            "",
            rx.button(
                "Add selected entries",
                on_click=AnkiAppState.add_selected_dictionary_entries,
                disabled=AnkiAppState.is_busy,
                width="280px",
            ),
        ),
        spacing="3",
        width="100%",
    )


def global_cards_page() -> rx.Component:
    return rx.vstack(
        section_box(
            "Global Card Pool",
            "",
            rx.hstack(rx.text("Global cards:"), rx.heading(AnkiAppState.global_card_total, size="6")),
        ),
        section_box(
            "Autofill Global Card Form from Dictionary",
            "",
            rx.hstack(
                rx.input(
                    value=AnkiAppState.global_autofill_query,
                    on_change=AnkiAppState.set_global_autofill_query,
                    placeholder="Search word",
                    width="100%",
                ),
                rx.button("Search", on_click=AnkiAppState.search_global_autofill_dictionary, disabled=AnkiAppState.is_busy),
                rx.button("Clear", on_click=AnkiAppState.clear_global_autofill_search, disabled=AnkiAppState.is_busy),
                width="100%",
            ),
            rx.cond(
                AnkiAppState.has_global_autofill_results,
                rx.vstack(
                    rx.foreach(
                        AnkiAppState.global_autofill_result_rows,
                        lambda row: rx.hstack(
                            rx.text(row["label"], width="82%"),
                            rx.button(
                                rx.cond(row["selected"], "Remove", "Select"),
                                on_click=AnkiAppState.toggle_global_autofill_entry_selection(row["entry_id"]),
                                disabled=AnkiAppState.is_busy,
                                width="120px",
                            ),
                            width="100%",
                            border_bottom="1px solid #e2e8d0",
                            padding_y="6px",
                        ),
                    ),
                    align="stretch",
                    spacing="0",
                    width="100%",
                ),
                rx.text("No dictionary entries selected."),
            ),
            rx.button(
                "Autofill form from first selected dictionary entry",
                on_click=AnkiAppState.autofill_global_form_from_selected,
                disabled=AnkiAppState.is_busy,
            ),
        ),
        section_box(
            "Add Global Card Manually",
            "",
            rx.input(
                value=AnkiAppState.global_form_kanji,
                on_change=AnkiAppState.set_global_form_kanji,
                placeholder="Kanji + Okurigana (required)",
            ),
            rx.input(
                value=AnkiAppState.global_form_kana,
                on_change=AnkiAppState.set_global_form_kana,
                placeholder="Kana (required)",
            ),
            rx.input(
                value=AnkiAppState.global_form_english,
                on_change=AnkiAppState.set_global_form_english,
                placeholder="English translation (required)",
            ),
            rx.text_area(
                value=AnkiAppState.global_form_notes,
                on_change=AnkiAppState.set_global_form_notes,
                placeholder="Notes (optional)",
            ),
            rx.hstack(
                rx.input(value=AnkiAppState.global_form_kanji_masu, on_change=AnkiAppState.set_global_form_kanji_masu, placeholder="Masu (kanji)"),
                rx.input(value=AnkiAppState.global_form_kana_masu, on_change=AnkiAppState.set_global_form_kana_masu, placeholder="Masu (kana)"),
                width="100%",
            ),
            rx.hstack(
                rx.input(value=AnkiAppState.global_form_kanji_te, on_change=AnkiAppState.set_global_form_kanji_te, placeholder="Te (kanji)"),
                rx.input(value=AnkiAppState.global_form_kana_te, on_change=AnkiAppState.set_global_form_kana_te, placeholder="Te (kana)"),
                width="100%",
            ),
            rx.hstack(
                rx.input(value=AnkiAppState.global_form_kanji_past, on_change=AnkiAppState.set_global_form_kanji_past, placeholder="Past (kanji)"),
                rx.input(value=AnkiAppState.global_form_kana_past, on_change=AnkiAppState.set_global_form_kana_past, placeholder="Past (kana)"),
                width="100%",
            ),
            rx.hstack(
                rx.input(value=AnkiAppState.global_form_kanji_negative, on_change=AnkiAppState.set_global_form_kanji_negative, placeholder="Negative (kanji)"),
                rx.input(value=AnkiAppState.global_form_kana_negative, on_change=AnkiAppState.set_global_form_kana_negative, placeholder="Negative (kana)"),
                width="100%",
            ),
            rx.input(value=AnkiAppState.global_form_tags, on_change=AnkiAppState.set_global_form_tags, placeholder="Tags (comma separated)"),
            rx.input(value=AnkiAppState.global_form_dictionary_entry_id, on_change=AnkiAppState.set_global_form_dictionary_entry_id, placeholder="Dictionary entry id (optional)"),
            rx.input(value=AnkiAppState.global_form_dictionary_headword, on_change=AnkiAppState.set_global_form_dictionary_headword, placeholder="Dictionary headword (optional)"),
            rx.input(value=AnkiAppState.global_form_dictionary_reading, on_change=AnkiAppState.set_global_form_dictionary_reading, placeholder="Dictionary reading (optional)"),
            rx.input(value=AnkiAppState.global_form_dictionary_gloss, on_change=AnkiAppState.set_global_form_dictionary_gloss, placeholder="Dictionary gloss (optional)"),
            rx.input(value=AnkiAppState.global_form_dictionary_pos, on_change=AnkiAppState.set_global_form_dictionary_pos, placeholder="Dictionary part of speech (optional)"),
            rx.input(value=AnkiAppState.global_form_verb_type, on_change=AnkiAppState.set_global_form_verb_type, placeholder="Verb type (optional)"),
            rx.upload(
                rx.button("Select optional images/videos"),
                id="global_media_upload",
                multiple=True,
            ),
            rx.vstack(
                rx.foreach(rx.selected_files("global_media_upload"), rx.text),
                align="stretch",
                spacing="1",
                width="100%",
            ),
            rx.button(
                "Add global card",
                on_click=lambda: AnkiAppState.add_global_card(
                    rx.upload_files(upload_id="global_media_upload")
                ),
                disabled=AnkiAppState.is_busy,
                width="220px",
            ),
        ),
        deck_picker("Import Deck Cards Into Global Pool", AnkiAppState.selected_global_source_deck_label, AnkiAppState.select_global_source_deck),
        section_box(
            "Import Action",
            "",
            rx.button(
                "Import all cards from selected deck to global pool",
                on_click=AnkiAppState.import_selected_deck_to_global_pool,
                disabled=AnkiAppState.is_busy,
                width="360px",
            ),
        ),
        section_box(
            "Global Card Browser",
            "",
            rx.input(
                value=AnkiAppState.global_search_text,
                on_change=AnkiAppState.set_global_search_text,
                placeholder="Search kanji, kana, english, dictionary id",
            ),
            rx.cond(
                AnkiAppState.has_filtered_global_cards,
                rx.vstack(
                    rx.foreach(
                        AnkiAppState.filtered_global_card_rows,
                        lambda row: rx.hstack(
                            rx.vstack(
                                rx.text(row["label"]),
                                rx.flex(
                                    rx.text("dict:", size="1", color=ThemeStyles["MutedText"]),
                                    rx.text(row["dictionary_entry_id"], size="1", color=ThemeStyles["MutedText"]),
                                    rx.text("|", size="1", color=ThemeStyles["MutedText"]),
                                    rx.text("masu:", size="1", color=ThemeStyles["MutedText"]),
                                    rx.text(row["masu"], size="1", color=ThemeStyles["MutedText"]),
                                    rx.text("|", size="1", color=ThemeStyles["MutedText"]),
                                    rx.text("te:", size="1", color=ThemeStyles["MutedText"]),
                                    rx.text(row["te"], size="1", color=ThemeStyles["MutedText"]),
                                    rx.text("|", size="1", color=ThemeStyles["MutedText"]),
                                    rx.text("past:", size="1", color=ThemeStyles["MutedText"]),
                                    rx.text(row["past"], size="1", color=ThemeStyles["MutedText"]),
                                    rx.text("|", size="1", color=ThemeStyles["MutedText"]),
                                    rx.text("negative:", size="1", color=ThemeStyles["MutedText"]),
                                    rx.text(row["negative"], size="1", color=ThemeStyles["MutedText"]),
                                    wrap="wrap",
                                    gap="4px",
                                ),
                                align="start",
                                width="82%",
                            ),
                            rx.button(
                                rx.cond(row["selected"], "Remove", "Select"),
                                on_click=AnkiAppState.toggle_global_card_selection(row["id"]),
                                disabled=AnkiAppState.is_busy,
                                width="120px",
                            ),
                            width="100%",
                            border_bottom="1px solid #e2e8d0",
                            padding_y="6px",
                        ),
                    ),
                    align="stretch",
                    spacing="0",
                    width="100%",
                ),
                rx.text("No global cards match the current search."),
            ),
            rx.hstack(rx.text("Selected global cards:"), rx.text(AnkiAppState.global_selected_count)),
            rx.button(
                "Clear selection",
                on_click=AnkiAppState.clear_global_card_selection,
                disabled=AnkiAppState.is_busy,
                width="160px",
            ),
        ),
        deck_picker("Destination Deck for Selected Global Cards", AnkiAppState.selected_global_destination_deck_label, AnkiAppState.select_global_destination_deck),
        schema_picker("Card Format on Import", AnkiAppState.global_destination_schema_key, AnkiAppState.set_global_destination_schema_key),
        word_form_picker("Word Form on Import", AnkiAppState.global_destination_word_form, AnkiAppState.set_global_destination_word_form),
        section_box(
            "Import Selected Global Cards",
            "",
            rx.input(
                value=AnkiAppState.global_import_tags,
                on_change=AnkiAppState.set_global_import_tags,
                placeholder="Extra tags for deck import (comma separated)",
            ),
            rx.button(
                "Import selected global cards into deck",
                on_click=AnkiAppState.import_selected_global_cards_to_deck,
                disabled=AnkiAppState.is_busy,
                width="320px",
            ),
        ),
        spacing="3",
        width="100%",
    )


def review_cards_page() -> rx.Component:
    return rx.vstack(
        deck_picker("Deck to Review", AnkiAppState.selected_review_deck_label, AnkiAppState.select_review_deck),
        section_box(
            "Card Browser",
            "",
            rx.input(
                value=AnkiAppState.review_search_text,
                on_change=AnkiAppState.set_review_search_text,
                placeholder="Search kanji, kana, english, notes, dictionary id",
            ),
            rx.hstack(
                rx.button("Select all visible", on_click=AnkiAppState.select_all_visible_review_cards, disabled=AnkiAppState.is_busy),
                rx.button("Clear selection", on_click=AnkiAppState.clear_review_card_selection, disabled=AnkiAppState.is_busy),
                width="100%",
            ),
            rx.cond(
                AnkiAppState.has_review_cards,
                rx.vstack(
                    rx.foreach(
                        AnkiAppState.review_card_rows,
                        lambda row: rx.hstack(
                            rx.vstack(
                                rx.text(row["label"]),
                                rx.flex(
                                    rx.text("Word form:", size="1", color=ThemeStyles["MutedText"]),
                                    rx.text(row["word_form"], size="1", color=ThemeStyles["MutedText"]),
                                    rx.text("|", size="1", color=ThemeStyles["MutedText"]),
                                    rx.text("Dictionary:", size="1", color=ThemeStyles["MutedText"]),
                                    rx.text(row["dictionary_id"], size="1", color=ThemeStyles["MutedText"]),
                                    wrap="wrap",
                                    gap="4px",
                                ),
                                align="start",
                                width="82%",
                            ),
                            rx.button(
                                rx.cond(row["selected"], "Remove", "Select"),
                                on_click=AnkiAppState.toggle_review_card_selection(row["id"]),
                                disabled=AnkiAppState.is_busy,
                                width="120px",
                            ),
                            width="100%",
                            border_bottom="1px solid #e2e8d0",
                            padding_y="6px",
                        ),
                    ),
                    align="stretch",
                    spacing="0",
                    width="100%",
                ),
                rx.text("No cards in this deck match the current search."),
            ),
            rx.hstack(rx.text("Selected cards:"), rx.text(AnkiAppState.review_selected_count)),
        ),
        schema_picker("Bulk Format Update", AnkiAppState.review_bulk_format, AnkiAppState.set_review_bulk_format),
        section_box(
            "Bulk Actions",
            "",
            rx.button("Apply selected format", on_click=AnkiAppState.apply_review_bulk_format, disabled=AnkiAppState.is_busy, width="220px"),
            rx.button(
                rx.cond(AnkiAppState.review_confirm_delete, "Delete confirmed", "Confirm delete selected cards"),
                on_click=AnkiAppState.toggle_review_confirm_delete,
                disabled=AnkiAppState.is_busy,
                width="280px",
                background=rx.cond(AnkiAppState.review_confirm_delete, "#f7d7d4", "white"),
            ),
            rx.button("Delete selected cards", on_click=AnkiAppState.delete_selected_review_cards, disabled=AnkiAppState.is_busy, width="220px"),
        ),
        rx.cond(
            AnkiAppState.has_single_edit_card,
            section_box(
                "Single Card Edit",
                "",
                rx.text(AnkiAppState.single_edit_metadata_json, white_space="pre-wrap", font_family="monospace"),
                rx.input(value=AnkiAppState.single_edit_kanji, on_change=AnkiAppState.set_single_edit_kanji, placeholder="Kanji"),
                rx.input(value=AnkiAppState.single_edit_kana, on_change=AnkiAppState.set_single_edit_kana, placeholder="Kana"),
                rx.input(value=AnkiAppState.single_edit_english, on_change=AnkiAppState.set_single_edit_english, placeholder="English"),
                rx.text_area(value=AnkiAppState.single_edit_notes, on_change=AnkiAppState.set_single_edit_notes, placeholder="Notes"),
                rx.flex(
                    *[
                        choice_button(
                            option["label"],
                            AnkiAppState.single_edit_schema_key == option["key"],
                            AnkiAppState.set_single_edit_schema_key(option["key"]),
                            AnkiAppState.is_busy,
                        )
                        for option in CardSchemaOptionRows
                    ],
                    wrap="wrap",
                    gap="8px",
                ),
                rx.button("Save text changes", on_click=AnkiAppState.save_single_review_card_changes, disabled=AnkiAppState.is_busy, width="220px"),
            ),
        ),
        rx.cond(
            AnkiAppState.has_single_edit_card,
            section_box(
                "Replace Text With Media",
                "",
                rx.flex(
                    *[
                        choice_button(
                            option["label"],
                            AnkiAppState.review_replace_target == option["key"],
                            AnkiAppState.set_review_replace_target(option["key"]),
                            AnkiAppState.is_busy,
                        )
                        for option in ReviewReplaceTargetOptions
                    ],
                    wrap="wrap",
                    gap="8px",
                ),
                rx.flex(
                    *[
                        choice_button(
                            option["label"],
                            AnkiAppState.review_replace_media_type == option["key"],
                            AnkiAppState.set_review_replace_media_type(option["key"]),
                            AnkiAppState.is_busy,
                        )
                        for option in ReviewMediaTypeOptions
                    ],
                    wrap="wrap",
                    gap="8px",
                ),
                rx.upload(rx.button("Select media files"), id="review_media_upload", multiple=True),
                rx.vstack(rx.foreach(rx.selected_files("review_media_upload"), rx.text), align="stretch", spacing="1", width="100%"),
                rx.button(
                    "Apply media replacement",
                    on_click=lambda: AnkiAppState.apply_single_review_media_replacement(
                        rx.upload_files(upload_id="review_media_upload")
                    ),
                    disabled=AnkiAppState.is_busy,
                    width="220px",
                ),
            ),
        ),
        spacing="3",
        width="100%",
    )


def scan_images_page() -> rx.Component:
    return rx.vstack(
        deck_picker("Destination Deck", AnkiAppState.selected_scan_deck_label, AnkiAppState.select_scan_deck),
        schema_picker("Card Format for New Cards", AnkiAppState.scan_schema_key, AnkiAppState.set_scan_schema_key),
        word_form_picker("Verb Form for Matched Dictionary Verbs", AnkiAppState.scan_word_form, AnkiAppState.set_scan_word_form),
        section_box(
            "Scan Settings",
            "",
            rx.input(value=AnkiAppState.scan_tags, on_change=AnkiAppState.set_scan_tags, placeholder="Extra tags (comma separated)"),
            rx.upload(rx.button("Select images to scan"), id="scan_images_upload", multiple=True),
            rx.vstack(rx.foreach(rx.selected_files("scan_images_upload"), rx.text), align="stretch", spacing="1", width="100%"),
            rx.button(
                "Scan images and add missing cards",
                on_click=lambda: AnkiAppState.scan_images_and_add_missing_cards(
                    rx.upload_files(upload_id="scan_images_upload")
                ),
                disabled=AnkiAppState.is_busy,
                width="280px",
            ),
        ),
        rx.cond(
            AnkiAppState.scan_summary != "",
            section_box("Scan Summary", "", rx.text(AnkiAppState.scan_summary, white_space="pre-wrap")),
        ),
        rx.cond(
            AnkiAppState.has_scan_preview_rows,
            section_box(
                "Matched Card Preview",
                "",
                rx.vstack(
                    rx.foreach(
                        AnkiAppState.scan_preview_rows,
                        lambda row: rx.box(
                            rx.flex(
                                rx.text(row["visible_text"]),
                                rx.text("->"),
                                rx.text(row["kanji"]),
                                rx.text("["),
                                rx.text(row["kana"]),
                                rx.text("]"),
                                rx.text("|"),
                                rx.text(row["english"]),
                                rx.text("| JMDict #"),
                                rx.text(row["dictionary_entry_id"]),
                                wrap="wrap",
                                gap="4px",
                            ),
                            width="100%",
                            border_bottom="1px solid #e2e8d0",
                            padding_y="6px",
                        ),
                    ),
                    align="stretch",
                    spacing="0",
                    width="100%",
                ),
            ),
        ),
        rx.cond(
            AnkiAppState.has_scan_errors,
            section_box(
                "Scan Errors",
                "",
                rx.vstack(rx.foreach(AnkiAppState.scan_errors, rx.text), align="stretch", spacing="1", width="100%"),
            ),
        ),
        spacing="3",
        width="100%",
    )


def import_csv_page() -> rx.Component:
    return rx.vstack(
        deck_picker("Destination Deck", AnkiAppState.selected_import_deck_label, AnkiAppState.select_import_deck),
        section_box(
            "Import CSV",
            (
                "CSV columns: kanji, kana, english, notes, source_text, schema_key, media_type, tags, "
                "dictionary_entry_id, dictionary_headword, dictionary_reading, dictionary_gloss, "
                "dictionary_pos, verb_type, word_form"
            ),
            rx.upload(rx.button("Select CSV file"), id="import_csv_upload", multiple=False),
            rx.vstack(rx.foreach(rx.selected_files("import_csv_upload"), rx.text), align="stretch", spacing="1", width="100%"),
            rx.button(
                "Import CSV cards",
                on_click=lambda: AnkiAppState.import_csv_cards(
                    rx.upload_files(upload_id="import_csv_upload")
                ),
                disabled=AnkiAppState.is_busy,
                width="220px",
            ),
        ),
        spacing="3",
        width="100%",
    )


def export_deck_page() -> rx.Component:
    return rx.vstack(
        deck_picker("Deck to Export", AnkiAppState.selected_export_deck_label, AnkiAppState.select_export_deck),
        section_box(
            "Export Deck",
            "",
            rx.hstack(rx.text("Selected deck card count:"), rx.text(AnkiAppState.export_selected_deck_card_count)),
            rx.button(
                "Build .apkg and download",
                on_click=AnkiAppState.export_selected_deck_package,
                disabled=AnkiAppState.is_busy,
                width="260px",
            ),
            rx.cond(
                AnkiAppState.last_export_path != "",
                rx.hstack(rx.text("Last export:", size="2"), rx.text(AnkiAppState.last_export_path, size="2")),
            ),
        ),
        spacing="3",
        width="100%",
    )


def page_content() -> rx.Component:
    return rx.vstack(
        rx.cond(AnkiAppState.current_page_key == "Dashboard", dashboard_page()),
        rx.cond(AnkiAppState.current_page_key == "CreateCollections", collections_page()),
        rx.cond(AnkiAppState.current_page_key == "CreateDecks", decks_page()),
        rx.cond(AnkiAppState.current_page_key == "AddCards", add_cards_page()),
        rx.cond(AnkiAppState.current_page_key == "GlobalCards", global_cards_page()),
        rx.cond(AnkiAppState.current_page_key == "ReviewCards", review_cards_page()),
        rx.cond(AnkiAppState.current_page_key == "ScanImages", scan_images_page()),
        rx.cond(AnkiAppState.current_page_key == "ImportCsv", import_csv_page()),
        rx.cond(AnkiAppState.current_page_key == "ExportDeck", export_deck_page()),
        width="100%",
        spacing="3",
    )


def status_banner() -> rx.Component:
    return rx.cond(
        AnkiAppState.has_status_message,
        rx.box(
            rx.text(AnkiAppState.status_message),
            background=AnkiAppState.status_background,
            border=AnkiAppState.status_border,
            border_radius="8px",
            padding="10px",
            width="100%",
        ),
    )


def busy_banner() -> rx.Component:
    return rx.cond(
        AnkiAppState.is_busy,
        rx.box(
            rx.hstack(rx.text("Processing:"), rx.text(AnkiAppState.busy_action_name)),
            background="#fff3dc",
            border="1px solid #d79820",
            border_radius="8px",
            padding="10px",
            width="100%",
        ),
    )


def index() -> rx.Component:
    return rx.box(
        rx.hstack(
            sidebar(),
            rx.box(
                rx.vstack(
                    rx.heading(AnkiAppState.current_page_label, size="7"),
                    rx.text(AnkiAppState.current_page_description, color=ThemeStyles["MutedText"]),
                    busy_banner(),
                    status_banner(),
                    page_content(),
                    spacing="3",
                    align="stretch",
                    width="100%",
                ),
                padding="16px",
                width="calc(100% - 320px)",
            ),
            align="start",
            width="100%",
            spacing="0",
        ),
        min_height="100vh",
        width="100%",
        background=ThemeStyles["AppBackground"],
    )


app = rx.App(
    style={
        "font_family": "IBM Plex Sans, Segoe UI, system-ui, sans-serif",
        "color": "#1f2d1b",
    }
)
app.add_page(index, title=AppTitle, on_load=AnkiAppState.initialize)
