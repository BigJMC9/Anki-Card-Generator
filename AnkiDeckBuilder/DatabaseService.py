import hashlib
import json
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from AnkiDeckBuilder.AppConfig import (
    DatabasePath,
    SupportedImageExtensions,
    SupportedVideoExtensions,
)
from AnkiDeckBuilder.WorkspaceService import EnsureWorkspaceDirectories

AllowedCardFieldsToUpdate = {"kanji", "kana", "english", "notes", "schema_key", "media_type"}
CardColumnDefinitions = {
    "dictionary_entry_id": "TEXT NOT NULL DEFAULT ''",
    "dictionary_headword": "TEXT NOT NULL DEFAULT ''",
    "dictionary_reading": "TEXT NOT NULL DEFAULT ''",
    "dictionary_gloss": "TEXT NOT NULL DEFAULT ''",
    "dictionary_pos": "TEXT NOT NULL DEFAULT ''",
    "verb_type": "TEXT NOT NULL DEFAULT ''",
    "word_form": "TEXT NOT NULL DEFAULT 'dictionary'",
}
GlobalCardColumnDefinitions = {
    "kanji": "TEXT NOT NULL DEFAULT ''",
    "kana": "TEXT NOT NULL DEFAULT ''",
    "english": "TEXT NOT NULL DEFAULT ''",
    "notes": "TEXT NOT NULL DEFAULT ''",
    "kanji_masu": "TEXT NOT NULL DEFAULT ''",
    "kana_masu": "TEXT NOT NULL DEFAULT ''",
    "kanji_te": "TEXT NOT NULL DEFAULT ''",
    "kana_te": "TEXT NOT NULL DEFAULT ''",
    "kanji_past": "TEXT NOT NULL DEFAULT ''",
    "kana_past": "TEXT NOT NULL DEFAULT ''",
    "kanji_negative": "TEXT NOT NULL DEFAULT ''",
    "kana_negative": "TEXT NOT NULL DEFAULT ''",
    "image_files_json": "TEXT NOT NULL DEFAULT '[]'",
    "video_files_json": "TEXT NOT NULL DEFAULT '[]'",
    "tags_json": "TEXT NOT NULL DEFAULT '[]'",
    "dictionary_entry_id": "TEXT NOT NULL DEFAULT ''",
    "dictionary_headword": "TEXT NOT NULL DEFAULT ''",
    "dictionary_reading": "TEXT NOT NULL DEFAULT ''",
    "dictionary_gloss": "TEXT NOT NULL DEFAULT ''",
    "dictionary_pos": "TEXT NOT NULL DEFAULT ''",
    "verb_type": "TEXT NOT NULL DEFAULT ''",
    "unique_key": "TEXT NOT NULL DEFAULT ''",
    "created_at": "REAL NOT NULL DEFAULT 0",
}
WordFormFieldByKey = {
    "dictionary": ("kanji", "kana"),
    "masu": ("kanji_masu", "kana_masu"),
    "te": ("kanji_te", "kana_te"),
    "past": ("kanji_past", "kana_past"),
    "negative": ("kanji_negative", "kana_negative"),
}


def OpenDatabaseConnection() -> sqlite3.Connection:
    EnsureWorkspaceDirectories()
    connection = sqlite3.connect(DatabasePath, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    EnsureDatabaseSchema(connection)
    return connection


def EnsureDatabaseSchema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS collections (
            id TEXT PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS decks (
            id TEXT PRIMARY KEY,
            collection_id TEXT NOT NULL,
            name TEXT NOT NULL,
            created_at REAL NOT NULL,
            UNIQUE(collection_id, name),
            FOREIGN KEY(collection_id) REFERENCES collections(id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS cards (
            id TEXT PRIMARY KEY,
            deck_id TEXT NOT NULL,
            kanji TEXT NOT NULL DEFAULT '',
            kana TEXT NOT NULL DEFAULT '',
            english TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            source_text TEXT NOT NULL DEFAULT '',
            schema_key TEXT NOT NULL,
            media_type TEXT NOT NULL DEFAULT 'none',
            media_files_json TEXT NOT NULL DEFAULT '[]',
            tags_json TEXT NOT NULL DEFAULT '[]',
            dictionary_entry_id TEXT NOT NULL DEFAULT '',
            dictionary_headword TEXT NOT NULL DEFAULT '',
            dictionary_reading TEXT NOT NULL DEFAULT '',
            dictionary_gloss TEXT NOT NULL DEFAULT '',
            dictionary_pos TEXT NOT NULL DEFAULT '',
            verb_type TEXT NOT NULL DEFAULT '',
            word_form TEXT NOT NULL DEFAULT 'dictionary',
            unique_key TEXT NOT NULL,
            created_at REAL NOT NULL,
            UNIQUE(deck_id, unique_key),
            FOREIGN KEY(deck_id) REFERENCES decks(id)
        )
        """
    )
    EnsureCardsTableColumns(connection)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS global_cards (
            id TEXT PRIMARY KEY,
            kanji TEXT NOT NULL DEFAULT '',
            kana TEXT NOT NULL DEFAULT '',
            english TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            kanji_masu TEXT NOT NULL DEFAULT '',
            kana_masu TEXT NOT NULL DEFAULT '',
            kanji_te TEXT NOT NULL DEFAULT '',
            kana_te TEXT NOT NULL DEFAULT '',
            kanji_past TEXT NOT NULL DEFAULT '',
            kana_past TEXT NOT NULL DEFAULT '',
            kanji_negative TEXT NOT NULL DEFAULT '',
            kana_negative TEXT NOT NULL DEFAULT '',
            image_files_json TEXT NOT NULL DEFAULT '[]',
            video_files_json TEXT NOT NULL DEFAULT '[]',
            tags_json TEXT NOT NULL DEFAULT '[]',
            dictionary_entry_id TEXT NOT NULL DEFAULT '',
            dictionary_headword TEXT NOT NULL DEFAULT '',
            dictionary_reading TEXT NOT NULL DEFAULT '',
            dictionary_gloss TEXT NOT NULL DEFAULT '',
            dictionary_pos TEXT NOT NULL DEFAULT '',
            verb_type TEXT NOT NULL DEFAULT '',
            unique_key TEXT NOT NULL,
            created_at REAL NOT NULL,
            UNIQUE(unique_key)
        )
        """
    )
    EnsureGlobalCardsTableColumns(connection)
    connection.commit()


def EnsureCardsTableColumns(connection: sqlite3.Connection) -> None:
    existingColumns = {
        row["name"] for row in connection.execute("PRAGMA table_info(cards)").fetchall()
    }
    for columnName, definition in CardColumnDefinitions.items():
        if columnName in existingColumns:
            continue
        connection.execute(f"ALTER TABLE cards ADD COLUMN {columnName} {definition}")


def EnsureGlobalCardsTableColumns(connection: sqlite3.Connection) -> None:
    existingColumns = {
        row["name"] for row in connection.execute("PRAGMA table_info(global_cards)").fetchall()
    }
    for columnName, definition in GlobalCardColumnDefinitions.items():
        if columnName in existingColumns:
            continue
        connection.execute(f"ALTER TABLE global_cards ADD COLUMN {columnName} {definition}")


def NormalizeText(value: str) -> str:
    normalizedValue = (value or "").strip().lower()
    normalizedValue = re.sub(r"\s+", " ", normalizedValue)
    return normalizedValue


def BuildCardUniqueKey(schemaKey: str, kanji: str, kana: str) -> str:
    raw = "|".join([NormalizeText(schemaKey), NormalizeText(kanji), NormalizeText(kana)])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def BuildGlobalCardUniqueKey(kanji: str, kana: str) -> str:
    raw = "|".join([NormalizeText(kanji), NormalizeText(kana)])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def DecodeJsonStringList(raw: str) -> List[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []

    normalizedItems: List[str] = []
    for item in parsed:
        value = str(item).strip()
        if not value or value in normalizedItems:
            continue
        normalizedItems.append(value)
    return normalizedItems


def NormalizeStringList(values: List[Any]) -> List[str]:
    normalizedItems: List[str] = []
    for rawValue in values or []:
        value = str(rawValue).strip()
        if not value or value in normalizedItems:
            continue
        normalizedItems.append(value)
    return normalizedItems


def BuildMediaTypeFromGlobalCard(imageFiles: List[str], videoFiles: List[str]) -> str:
    if imageFiles and not videoFiles:
        return "image"
    if videoFiles and not imageFiles:
        return "video"
    if imageFiles or videoFiles:
        return "none"
    return "none"


def SelectSurfaceFromGlobalCard(globalCard: sqlite3.Row, requestedWordForm: str) -> Tuple[str, str, str]:
    selectedWordForm = (requestedWordForm or "dictionary").strip() or "dictionary"
    if selectedWordForm not in WordFormFieldByKey:
        selectedWordForm = "dictionary"

    defaultKanji = (globalCard["kanji"] or "").strip()
    defaultKana = (globalCard["kana"] or "").strip()

    if selectedWordForm == "dictionary":
        return defaultKanji, defaultKana, "dictionary"

    kanjiField, kanaField = WordFormFieldByKey[selectedWordForm]
    formKanji = (globalCard[kanjiField] or "").strip()
    formKana = (globalCard[kanaField] or "").strip()
    if formKanji and formKana:
        return formKanji, formKana, selectedWordForm
    return defaultKanji, defaultKana, "dictionary"


def CardWordExistsInSchema(
    connection: sqlite3.Connection,
    deckId: str,
    schemaKey: str,
    kanji: str,
    kana: str,
    excludeCardId: Optional[str] = None,
) -> bool:
    targetKey = BuildCardUniqueKey(schemaKey, kanji, kana)
    rows = connection.execute(
        "SELECT id, schema_key, kanji, kana FROM cards WHERE deck_id = ? AND schema_key = ?",
        (deckId, schemaKey),
    ).fetchall()
    for row in rows:
        if excludeCardId and row["id"] == excludeCardId:
            continue
        rowKey = BuildCardUniqueKey(row["schema_key"], row["kanji"], row["kana"])
        if rowKey == targetKey:
            return True
    return False


def ListCollections(connection: sqlite3.Connection) -> List[Dict[str, Any]]:
    return [dict(row) for row in connection.execute("SELECT * FROM collections ORDER BY name")]


def ListDecks(
    connection: sqlite3.Connection,
    collectionId: Optional[str] = None,
    includeCollectionName: bool = False,
) -> List[Dict[str, Any]]:
    parameters: tuple = ()
    if includeCollectionName:
        query = """
            SELECT decks.*, collections.name AS collection_name
            FROM decks
            JOIN collections ON collections.id = decks.collection_id
        """
    else:
        query = "SELECT * FROM decks"

    if collectionId:
        query += " WHERE collection_id = ?"
        parameters = (collectionId,)

    if includeCollectionName:
        query += " ORDER BY collections.name, decks.name"
    else:
        query += " ORDER BY name"
    return [dict(row) for row in connection.execute(query, parameters)]


def CreateCollection(connection: sqlite3.Connection, name: str) -> None:
    connection.execute(
        "INSERT INTO collections (id, name, created_at) VALUES (?, ?, ?)",
        (str(uuid.uuid4()), name.strip(), time.time()),
    )
    connection.commit()


def RenameCollection(connection: sqlite3.Connection, collectionId: str, newName: str) -> None:
    connection.execute("UPDATE collections SET name = ? WHERE id = ?", (newName.strip(), collectionId))
    connection.commit()


def CreateDeck(connection: sqlite3.Connection, collectionId: str, name: str) -> None:
    connection.execute(
        "INSERT INTO decks (id, collection_id, name, created_at) VALUES (?, ?, ?, ?)",
        (str(uuid.uuid4()), collectionId, name.strip(), time.time()),
    )
    connection.commit()


def RenameDeck(connection: sqlite3.Connection, deckId: str, newName: str) -> None:
    connection.execute("UPDATE decks SET name = ? WHERE id = ?", (newName.strip(), deckId))
    connection.commit()


def GetDeckRow(connection: sqlite3.Connection, deckId: str) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT decks.id AS deck_id, decks.name AS deck_name, collections.name AS collection_name
        FROM decks
        JOIN collections ON collections.id = decks.collection_id
        WHERE decks.id = ?
        """,
        (deckId,),
    ).fetchone()
    if row is None:
        raise RuntimeError("Deck not found.")
    return row


def GetDeckCards(connection: sqlite3.Connection, deckId: str) -> List[sqlite3.Row]:
    return list(
        connection.execute(
            "SELECT * FROM cards WHERE deck_id = ? ORDER BY created_at DESC",
            (deckId,),
        )
    )


def CountCardsInDeck(connection: sqlite3.Connection, deckId: str) -> int:
    return int(connection.execute("SELECT COUNT(*) FROM cards WHERE deck_id = ?", (deckId,)).fetchone()[0])


def GetDeckCardCounts(connection: sqlite3.Connection) -> Dict[str, int]:
    rows = connection.execute(
        """
        SELECT deck_id, COUNT(*) AS count
        FROM cards
        GROUP BY deck_id
        """
    ).fetchall()
    return {row["deck_id"]: int(row["count"]) for row in rows}


def AddCard(connection: sqlite3.Connection, deckId: str, card: Dict[str, Any]) -> bool:
    schemaKey = card.get("schema_key") or "kana_kanji_front_english_back"
    kanji = (card.get("kanji") or "").strip()
    kana = (card.get("kana") or "").strip()
    english = (card.get("english") or "").strip()
    dictionaryEntryId = (card.get("dictionary_entry_id") or "").strip()
    dictionaryHeadword = (card.get("dictionary_headword") or "").strip()
    dictionaryReading = (card.get("dictionary_reading") or "").strip()
    dictionaryGloss = (card.get("dictionary_gloss") or "").strip()
    dictionaryPos = (card.get("dictionary_pos") or "").strip()
    verbType = (card.get("verb_type") or "").strip()
    wordForm = (card.get("word_form") or "dictionary").strip() or "dictionary"

    if CardWordExistsInSchema(connection, deckId, schemaKey, kanji, kana):
        return False

    uniqueKey = BuildCardUniqueKey(schemaKey, kanji, kana)
    try:
        connection.execute(
            """
            INSERT INTO cards (
                id, deck_id, kanji, kana, english, notes, source_text, schema_key,
                media_type, media_files_json, tags_json,
                dictionary_entry_id, dictionary_headword, dictionary_reading,
                dictionary_gloss, dictionary_pos, verb_type, word_form,
                unique_key, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                deckId,
                kanji,
                kana,
                english,
                (card.get("notes") or "").strip(),
                (card.get("source_text") or "").strip(),
                schemaKey,
                card.get("media_type") or "none",
                json.dumps(card.get("media_files") or [], ensure_ascii=False),
                json.dumps(card.get("tags") or [], ensure_ascii=False),
                dictionaryEntryId,
                dictionaryHeadword,
                dictionaryReading,
                dictionaryGloss,
                dictionaryPos,
                verbType,
                wordForm,
                uniqueKey,
                time.time(),
            ),
        )
        connection.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def GlobalCardExists(
    connection: sqlite3.Connection,
    kanji: str,
    kana: str,
    excludeCardId: Optional[str] = None,
) -> bool:
    uniqueKey = BuildGlobalCardUniqueKey(kanji, kana)
    if excludeCardId:
        row = connection.execute(
            "SELECT 1 FROM global_cards WHERE unique_key = ? AND id != ? LIMIT 1",
            (uniqueKey, excludeCardId),
        ).fetchone()
    else:
        row = connection.execute(
            "SELECT 1 FROM global_cards WHERE unique_key = ? LIMIT 1",
            (uniqueKey,),
        ).fetchone()
    return row is not None


def AddGlobalCard(connection: sqlite3.Connection, card: Dict[str, Any]) -> bool:
    kanji = (card.get("kanji") or "").strip()
    kana = (card.get("kana") or "").strip()
    english = (card.get("english") or "").strip()
    if not kanji or not kana or not english:
        return False

    if GlobalCardExists(connection, kanji, kana):
        return False

    kanjiMasu = (card.get("kanji_masu") or "").strip()
    kanaMasu = (card.get("kana_masu") or "").strip()
    kanjiTe = (card.get("kanji_te") or "").strip()
    kanaTe = (card.get("kana_te") or "").strip()
    kanjiPast = (card.get("kanji_past") or "").strip()
    kanaPast = (card.get("kana_past") or "").strip()
    kanjiNegative = (card.get("kanji_negative") or "").strip()
    kanaNegative = (card.get("kana_negative") or "").strip()
    notes = (card.get("notes") or "").strip()
    dictionaryEntryId = (card.get("dictionary_entry_id") or "").strip()
    dictionaryHeadword = (card.get("dictionary_headword") or "").strip()
    dictionaryReading = (card.get("dictionary_reading") or "").strip()
    dictionaryGloss = (card.get("dictionary_gloss") or "").strip()
    dictionaryPos = (card.get("dictionary_pos") or "").strip()
    verbType = (card.get("verb_type") or "").strip()

    imageFiles = NormalizeStringList(card.get("image_files") or [])
    videoFiles = NormalizeStringList(card.get("video_files") or [])
    tags = NormalizeStringList(card.get("tags") or [])
    uniqueKey = BuildGlobalCardUniqueKey(kanji, kana)

    try:
        connection.execute(
            """
            INSERT INTO global_cards (
                id, kanji, kana, english, notes,
                kanji_masu, kana_masu, kanji_te, kana_te,
                kanji_past, kana_past, kanji_negative, kana_negative,
                image_files_json, video_files_json, tags_json,
                dictionary_entry_id, dictionary_headword, dictionary_reading,
                dictionary_gloss, dictionary_pos, verb_type,
                unique_key, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                kanji,
                kana,
                english,
                notes,
                kanjiMasu,
                kanaMasu,
                kanjiTe,
                kanaTe,
                kanjiPast,
                kanaPast,
                kanjiNegative,
                kanaNegative,
                json.dumps(imageFiles, ensure_ascii=False),
                json.dumps(videoFiles, ensure_ascii=False),
                json.dumps(tags, ensure_ascii=False),
                dictionaryEntryId,
                dictionaryHeadword,
                dictionaryReading,
                dictionaryGloss,
                dictionaryPos,
                verbType,
                uniqueKey,
                time.time(),
            ),
        )
        connection.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def GetGlobalCardBySurface(connection: sqlite3.Connection, kanji: str, kana: str) -> Optional[sqlite3.Row]:
    uniqueKey = BuildGlobalCardUniqueKey(kanji, kana)
    return connection.execute(
        "SELECT * FROM global_cards WHERE unique_key = ? LIMIT 1",
        (uniqueKey,),
    ).fetchone()


def MergeOptionalText(existingValue: str, incomingValue: str) -> str:
    normalizedExisting = (existingValue or "").strip()
    normalizedIncoming = (incomingValue or "").strip()
    return normalizedExisting or normalizedIncoming


def MergeNotes(existingValue: str, incomingValue: str) -> str:
    normalizedExisting = (existingValue or "").strip()
    normalizedIncoming = (incomingValue or "").strip()
    if not normalizedExisting:
        return normalizedIncoming
    if not normalizedIncoming or normalizedIncoming == normalizedExisting:
        return normalizedExisting
    return f"{normalizedExisting} | {normalizedIncoming}"


def MergeGlobalCard(connection: sqlite3.Connection, existingCard: sqlite3.Row, incomingCard: Dict[str, Any]) -> bool:
    mergedValues = {
        "kanji": MergeOptionalText(existingCard["kanji"], incomingCard.get("kanji", "")),
        "kana": MergeOptionalText(existingCard["kana"], incomingCard.get("kana", "")),
        "english": MergeOptionalText(existingCard["english"], incomingCard.get("english", "")),
        "notes": MergeNotes(existingCard["notes"], incomingCard.get("notes", "")),
        "kanji_masu": MergeOptionalText(existingCard["kanji_masu"], incomingCard.get("kanji_masu", "")),
        "kana_masu": MergeOptionalText(existingCard["kana_masu"], incomingCard.get("kana_masu", "")),
        "kanji_te": MergeOptionalText(existingCard["kanji_te"], incomingCard.get("kanji_te", "")),
        "kana_te": MergeOptionalText(existingCard["kana_te"], incomingCard.get("kana_te", "")),
        "kanji_past": MergeOptionalText(existingCard["kanji_past"], incomingCard.get("kanji_past", "")),
        "kana_past": MergeOptionalText(existingCard["kana_past"], incomingCard.get("kana_past", "")),
        "kanji_negative": MergeOptionalText(
            existingCard["kanji_negative"],
            incomingCard.get("kanji_negative", ""),
        ),
        "kana_negative": MergeOptionalText(
            existingCard["kana_negative"],
            incomingCard.get("kana_negative", ""),
        ),
        "dictionary_entry_id": MergeOptionalText(
            existingCard["dictionary_entry_id"],
            incomingCard.get("dictionary_entry_id", ""),
        ),
        "dictionary_headword": MergeOptionalText(
            existingCard["dictionary_headword"],
            incomingCard.get("dictionary_headword", ""),
        ),
        "dictionary_reading": MergeOptionalText(
            existingCard["dictionary_reading"],
            incomingCard.get("dictionary_reading", ""),
        ),
        "dictionary_gloss": MergeOptionalText(
            existingCard["dictionary_gloss"],
            incomingCard.get("dictionary_gloss", ""),
        ),
        "dictionary_pos": MergeOptionalText(
            existingCard["dictionary_pos"],
            incomingCard.get("dictionary_pos", ""),
        ),
        "verb_type": MergeOptionalText(existingCard["verb_type"], incomingCard.get("verb_type", "")),
    }
    mergedImageFiles = NormalizeStringList(
        DecodeJsonStringList(existingCard["image_files_json"]) + NormalizeStringList(incomingCard.get("image_files") or [])
    )
    mergedVideoFiles = NormalizeStringList(
        DecodeJsonStringList(existingCard["video_files_json"]) + NormalizeStringList(incomingCard.get("video_files") or [])
    )
    mergedTags = NormalizeStringList(
        DecodeJsonStringList(existingCard["tags_json"]) + NormalizeStringList(incomingCard.get("tags") or [])
    )

    hasChanges = False
    for key, mergedValue in mergedValues.items():
        if (existingCard[key] or "").strip() != mergedValue:
            hasChanges = True
            break
    if not hasChanges and mergedImageFiles != DecodeJsonStringList(existingCard["image_files_json"]):
        hasChanges = True
    if not hasChanges and mergedVideoFiles != DecodeJsonStringList(existingCard["video_files_json"]):
        hasChanges = True
    if not hasChanges and mergedTags != DecodeJsonStringList(existingCard["tags_json"]):
        hasChanges = True

    if not hasChanges:
        return False

    connection.execute(
        """
        UPDATE global_cards
        SET
            kanji = ?,
            kana = ?,
            english = ?,
            notes = ?,
            kanji_masu = ?,
            kana_masu = ?,
            kanji_te = ?,
            kana_te = ?,
            kanji_past = ?,
            kana_past = ?,
            kanji_negative = ?,
            kana_negative = ?,
            image_files_json = ?,
            video_files_json = ?,
            tags_json = ?,
            dictionary_entry_id = ?,
            dictionary_headword = ?,
            dictionary_reading = ?,
            dictionary_gloss = ?,
            dictionary_pos = ?,
            verb_type = ?
        WHERE id = ?
        """,
        (
            mergedValues["kanji"],
            mergedValues["kana"],
            mergedValues["english"],
            mergedValues["notes"],
            mergedValues["kanji_masu"],
            mergedValues["kana_masu"],
            mergedValues["kanji_te"],
            mergedValues["kana_te"],
            mergedValues["kanji_past"],
            mergedValues["kana_past"],
            mergedValues["kanji_negative"],
            mergedValues["kana_negative"],
            json.dumps(mergedImageFiles, ensure_ascii=False),
            json.dumps(mergedVideoFiles, ensure_ascii=False),
            json.dumps(mergedTags, ensure_ascii=False),
            mergedValues["dictionary_entry_id"],
            mergedValues["dictionary_headword"],
            mergedValues["dictionary_reading"],
            mergedValues["dictionary_gloss"],
            mergedValues["dictionary_pos"],
            mergedValues["verb_type"],
            existingCard["id"],
        ),
    )
    connection.commit()
    return True


def ListGlobalCards(connection: sqlite3.Connection) -> List[sqlite3.Row]:
    return list(
        connection.execute(
            "SELECT * FROM global_cards ORDER BY created_at DESC"
        )
    )


def CountGlobalCards(connection: sqlite3.Connection) -> int:
    return int(connection.execute("SELECT COUNT(*) FROM global_cards").fetchone()[0])


def GetGlobalCardsByIds(connection: sqlite3.Connection, globalCardIds: List[str]) -> List[sqlite3.Row]:
    if not globalCardIds:
        return []
    placeholders = ", ".join(["?"] * len(globalCardIds))
    return list(
        connection.execute(
            f"SELECT * FROM global_cards WHERE id IN ({placeholders})",
            globalCardIds,
        )
    )


def BuildDeckCardPayloadFromGlobalCard(
    globalCard: sqlite3.Row,
    schemaKey: str,
    requestedWordForm: str,
    extraTags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    kanji, kana, appliedWordForm = SelectSurfaceFromGlobalCard(globalCard, requestedWordForm)
    imageFiles = DecodeJsonStringList(globalCard["image_files_json"])
    videoFiles = DecodeJsonStringList(globalCard["video_files_json"])
    mediaFiles = NormalizeStringList([*imageFiles, *videoFiles])
    mediaType = BuildMediaTypeFromGlobalCard(imageFiles, videoFiles)
    baseTags = DecodeJsonStringList(globalCard["tags_json"])
    tags = NormalizeStringList([*baseTags, *(extraTags or []), "global_pool"])

    return {
        "kanji": kanji,
        "kana": kana,
        "english": (globalCard["english"] or "").strip(),
        "notes": (globalCard["notes"] or "").strip(),
        "source_text": f"global:{globalCard['id']}",
        "schema_key": (schemaKey or "").strip() or "kana_kanji_front_english_back",
        "media_type": mediaType,
        "media_files": mediaFiles,
        "tags": tags,
        "dictionary_entry_id": (globalCard["dictionary_entry_id"] or "").strip(),
        "dictionary_headword": (globalCard["dictionary_headword"] or "").strip(),
        "dictionary_reading": (globalCard["dictionary_reading"] or "").strip(),
        "dictionary_gloss": (globalCard["dictionary_gloss"] or "").strip(),
        "dictionary_pos": (globalCard["dictionary_pos"] or "").strip(),
        "verb_type": (globalCard["verb_type"] or "").strip(),
        "word_form": appliedWordForm,
    }


def ImportDeckCardsToGlobal(connection: sqlite3.Connection, deckId: str) -> Tuple[int, int]:
    cards = GetDeckCards(connection, deckId)
    added = 0
    skipped = 0
    for card in cards:
        sourceWordForm = (card["word_form"] or "dictionary").strip() or "dictionary"
        baseKanji = (card["dictionary_headword"] or "").strip() or (card["kanji"] or "").strip()
        baseKana = (card["dictionary_reading"] or "").strip() or (card["kana"] or "").strip()
        if not baseKanji or not baseKana:
            skipped += 1
            continue

        mediaFiles = DecodeJsonStringList(card["media_files_json"])
        imageFiles: List[str] = []
        videoFiles: List[str] = []
        mediaType = (card["media_type"] or "").strip()
        if mediaType == "image":
            imageFiles = NormalizeStringList(mediaFiles)
        elif mediaType == "video":
            videoFiles = NormalizeStringList(mediaFiles)
        else:
            for mediaPath in mediaFiles:
                suffix = Path(mediaPath).suffix.lower()
                if suffix in SupportedImageExtensions:
                    imageFiles.append(mediaPath)
                elif suffix in SupportedVideoExtensions:
                    videoFiles.append(mediaPath)
            imageFiles = NormalizeStringList(imageFiles)
            videoFiles = NormalizeStringList(videoFiles)

        globalCard: Dict[str, Any] = {
            "kanji": baseKanji,
            "kana": baseKana,
            "english": (card["dictionary_gloss"] or "").strip() or (card["english"] or "").strip(),
            "notes": (card["notes"] or "").strip(),
            "kanji_masu": "",
            "kana_masu": "",
            "kanji_te": "",
            "kana_te": "",
            "kanji_past": "",
            "kana_past": "",
            "kanji_negative": "",
            "kana_negative": "",
            "image_files": imageFiles,
            "video_files": videoFiles,
            "tags": DecodeJsonStringList(card["tags_json"]),
            "dictionary_entry_id": (card["dictionary_entry_id"] or "").strip(),
            "dictionary_headword": (card["dictionary_headword"] or "").strip(),
            "dictionary_reading": (card["dictionary_reading"] or "").strip(),
            "dictionary_gloss": (card["dictionary_gloss"] or "").strip(),
            "dictionary_pos": (card["dictionary_pos"] or "").strip(),
            "verb_type": (card["verb_type"] or "").strip(),
        }

        if sourceWordForm in WordFormFieldByKey and sourceWordForm != "dictionary":
            kanjiField, kanaField = WordFormFieldByKey[sourceWordForm]
            globalCard[kanjiField] = (card["kanji"] or "").strip()
            globalCard[kanaField] = (card["kana"] or "").strip()

        existingGlobalCard = GetGlobalCardBySurface(connection, baseKanji, baseKana)
        if existingGlobalCard is not None:
            isMerged = MergeGlobalCard(connection, existingGlobalCard, globalCard)
            added += int(isMerged)
            skipped += int(not isMerged)
            continue

        isAdded = AddGlobalCard(connection, globalCard)
        added += int(isAdded)
        skipped += int(not isAdded)

    return added, skipped


def ImportGlobalCardsToDeck(
    connection: sqlite3.Connection,
    deckId: str,
    globalCardIds: List[str],
    schemaKey: str,
    requestedWordForm: str,
    extraTags: Optional[List[str]] = None,
) -> Tuple[int, int]:
    globalCards = GetGlobalCardsByIds(connection, globalCardIds)
    added = 0
    skipped = 0
    for globalCard in globalCards:
        deckCard = BuildDeckCardPayloadFromGlobalCard(
            globalCard,
            schemaKey,
            requestedWordForm,
            extraTags=extraTags or [],
        )
        if not (deckCard.get("kanji") or "").strip() or not (deckCard.get("kana") or "").strip():
            skipped += 1
            continue

        isAdded = AddCard(connection, deckId, deckCard)
        added += int(isAdded)
        skipped += int(not isAdded)

    return added, skipped


def UpdateCardContent(
    connection: sqlite3.Connection,
    deckId: str,
    cardId: str,
    kanji: str,
    kana: str,
    english: str,
    notes: str,
    schemaKey: str,
) -> bool:
    normalizedKanji = (kanji or "").strip()
    normalizedKana = (kana or "").strip()
    normalizedEnglish = (english or "").strip()
    normalizedNotes = (notes or "").strip()
    normalizedSchemaKey = (schemaKey or "").strip() or "kana_kanji_front_english_back"

    if CardWordExistsInSchema(
        connection,
        deckId,
        normalizedSchemaKey,
        normalizedKanji,
        normalizedKana,
        excludeCardId=cardId,
    ):
        return False

    uniqueKey = BuildCardUniqueKey(normalizedSchemaKey, normalizedKanji, normalizedKana)
    try:
        cursor = connection.execute(
            """
            UPDATE cards
            SET kanji = ?, kana = ?, english = ?, notes = ?, schema_key = ?, unique_key = ?
            WHERE id = ? AND deck_id = ?
            """,
            (
                normalizedKanji,
                normalizedKana,
                normalizedEnglish,
                normalizedNotes,
                normalizedSchemaKey,
                uniqueKey,
                cardId,
                deckId,
            ),
        )
        connection.commit()
        return max(cursor.rowcount, 0) > 0
    except sqlite3.IntegrityError:
        return False


def UpdateCardField(connection: sqlite3.Connection, cardId: str, fieldName: str, value: str) -> None:
    if fieldName not in AllowedCardFieldsToUpdate:
        raise ValueError("Invalid field")

    if fieldName not in {"kanji", "kana", "schema_key"}:
        connection.execute(f"UPDATE cards SET {fieldName} = ? WHERE id = ?", (value, cardId))
        connection.commit()
        return

    cardRow = connection.execute(
        "SELECT deck_id, schema_key, kanji, kana FROM cards WHERE id = ?",
        (cardId,),
    ).fetchone()
    if cardRow is None:
        raise RuntimeError("Card not found.")

    updatedSchemaKey = cardRow["schema_key"]
    updatedKanji = cardRow["kanji"]
    updatedKana = cardRow["kana"]

    if fieldName == "schema_key":
        updatedSchemaKey = value
    elif fieldName == "kanji":
        updatedKanji = value
    elif fieldName == "kana":
        updatedKana = value

    if CardWordExistsInSchema(
        connection,
        cardRow["deck_id"],
        updatedSchemaKey,
        updatedKanji,
        updatedKana,
        excludeCardId=cardId,
    ):
        raise sqlite3.IntegrityError("Duplicate word in the selected card format.")

    uniqueKey = BuildCardUniqueKey(updatedSchemaKey, updatedKanji, updatedKana)
    connection.execute(
        f"UPDATE cards SET {fieldName} = ?, unique_key = ? WHERE id = ?",
        (value, uniqueKey, cardId),
    )
    connection.commit()


def UpdateCardMedia(connection: sqlite3.Connection, cardId: str, mediaType: str, mediaFiles: List[str]) -> None:
    connection.execute(
        "UPDATE cards SET media_type = ?, media_files_json = ? WHERE id = ?",
        (mediaType, json.dumps(mediaFiles, ensure_ascii=False), cardId),
    )
    connection.commit()


def UpdateCardsSchemaByIds(
    connection: sqlite3.Connection,
    deckId: str,
    cardIds: List[str],
    schemaKey: str,
) -> int:
    if not cardIds:
        return 0

    placeholders = ", ".join(["?"] * len(cardIds))
    selectedRows = connection.execute(
        f"SELECT id, kanji, kana FROM cards WHERE deck_id = ? AND id IN ({placeholders})",
        [deckId, *cardIds],
    ).fetchall()

    updatedCount = 0
    for row in selectedRows:
        if CardWordExistsInSchema(
            connection,
            deckId,
            schemaKey,
            row["kanji"],
            row["kana"],
            excludeCardId=row["id"],
        ):
            continue

        uniqueKey = BuildCardUniqueKey(schemaKey, row["kanji"], row["kana"])
        cursor = connection.execute(
            "UPDATE cards SET schema_key = ?, unique_key = ? WHERE deck_id = ? AND id = ?",
            (schemaKey, uniqueKey, deckId, row["id"]),
        )
        updatedCount += max(cursor.rowcount, 0)

    connection.commit()
    return updatedCount


def DeleteCardsByIds(connection: sqlite3.Connection, deckId: str, cardIds: List[str]) -> int:
    if not cardIds:
        return 0

    placeholders = ", ".join(["?"] * len(cardIds))
    parameters: List[str] = [deckId, *cardIds]
    cursor = connection.execute(
        f"DELETE FROM cards WHERE deck_id = ? AND id IN ({placeholders})",
        parameters,
    )
    connection.commit()
    return max(cursor.rowcount, 0)


def DeleteGlobalCardsByIds(connection: sqlite3.Connection, globalCardIds: List[str]) -> int:
    if not globalCardIds:
        return 0

    placeholders = ", ".join(["?"] * len(globalCardIds))
    cursor = connection.execute(
        f"DELETE FROM global_cards WHERE id IN ({placeholders})",
        list(globalCardIds),
    )
    connection.commit()
    return max(cursor.rowcount, 0)


def DeckNameToId(connection: sqlite3.Connection, collectionName: str, deckName: str) -> Optional[str]:
    row = connection.execute(
        """
        SELECT decks.id
        FROM decks
        JOIN collections ON collections.id = decks.collection_id
        WHERE collections.name = ? AND decks.name = ?
        """,
        (collectionName, deckName),
    ).fetchone()
    return row[0] if row else None


def DeckHasCandidate(connection: sqlite3.Connection, deckId: str, card: Dict[str, Any]) -> bool:
    schemaKey = card.get("schema_key") or "kana_kanji_front_english_back"
    kanji = card.get("kanji", "")
    kana = card.get("kana", "")
    return CardWordExistsInSchema(connection, deckId, schemaKey, kanji, kana)


def DeckHasKanjiWordForm(
    connection: sqlite3.Connection,
    deckId: str,
    schemaKey: str,
    wordForm: str,
    kanji: str,
) -> bool:
    normalizedKanji = (kanji or "").strip()
    if not normalizedKanji:
        return False

    row = connection.execute(
        """
        SELECT 1
        FROM cards
        WHERE deck_id = ?
          AND schema_key = ?
          AND word_form = ?
          AND lower(trim(kanji)) = lower(trim(?))
        LIMIT 1
        """,
        (
            deckId,
            (schemaKey or "").strip() or "kana_kanji_front_english_back",
            (wordForm or "dictionary").strip() or "dictionary",
            normalizedKanji,
        ),
    ).fetchone()
    return row is not None


def GetDashboardRows(connection: sqlite3.Connection) -> List[sqlite3.Row]:
    return connection.execute(
        """
        SELECT collections.name AS collection_name, decks.name AS deck_name, COUNT(cards.id) AS card_count
        FROM decks
        JOIN collections ON collections.id = decks.collection_id
        LEFT JOIN cards ON cards.deck_id = decks.id
        GROUP BY decks.id
        ORDER BY collections.name, decks.name
        """
    ).fetchall()


def GetTotalDeckCount(connection: sqlite3.Connection) -> int:
    return int(connection.execute("SELECT COUNT(*) FROM decks").fetchone()[0])


def GetTotalCardCount(connection: sqlite3.Connection) -> int:
    return int(connection.execute("SELECT COUNT(*) FROM cards").fetchone()[0])
