import hashlib
import json
import re
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional

from AnkiDeckBuilder.AppConfig import DatabasePath
from AnkiDeckBuilder.WorkspaceService import EnsureWorkspaceDirectories

AllowedCardFieldsToUpdate = {"kanji", "kana", "english", "notes", "schema_key", "media_type"}


def OpenDatabaseConnection() -> sqlite3.Connection:
    EnsureWorkspaceDirectories()
    connection = sqlite3.connect(DatabasePath)
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
            unique_key TEXT NOT NULL,
            created_at REAL NOT NULL,
            UNIQUE(deck_id, unique_key),
            FOREIGN KEY(deck_id) REFERENCES decks(id)
        )
        """
    )
    connection.commit()


def NormalizeText(value: str) -> str:
    normalizedValue = (value or "").strip().lower()
    normalizedValue = re.sub(r"\s+", " ", normalizedValue)
    return normalizedValue


def BuildCardUniqueKey(kanji: str, kana: str, english: str) -> str:
    raw = "|".join([NormalizeText(kanji), NormalizeText(kana), NormalizeText(english)])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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
    uniqueKey = BuildCardUniqueKey(card.get("kanji", ""), card.get("kana", ""), card.get("english", ""))
    try:
        connection.execute(
            """
            INSERT INTO cards (
                id, deck_id, kanji, kana, english, notes, source_text, schema_key,
                media_type, media_files_json, tags_json, unique_key, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                deckId,
                (card.get("kanji") or "").strip(),
                (card.get("kana") or "").strip(),
                (card.get("english") or "").strip(),
                (card.get("notes") or "").strip(),
                (card.get("source_text") or "").strip(),
                card.get("schema_key") or "kana_kanji_front_english_back",
                card.get("media_type") or "none",
                json.dumps(card.get("media_files") or [], ensure_ascii=False),
                json.dumps(card.get("tags") or [], ensure_ascii=False),
                uniqueKey,
                time.time(),
            ),
        )
        connection.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def UpdateCardField(connection: sqlite3.Connection, cardId: str, fieldName: str, value: str) -> None:
    if fieldName not in AllowedCardFieldsToUpdate:
        raise ValueError("Invalid field")
    connection.execute(f"UPDATE cards SET {fieldName} = ? WHERE id = ?", (value, cardId))
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
    parameters: List[str] = [schemaKey, deckId, *cardIds]
    cursor = connection.execute(
        f"UPDATE cards SET schema_key = ? WHERE deck_id = ? AND id IN ({placeholders})",
        parameters,
    )
    connection.commit()
    return max(cursor.rowcount, 0)


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
    uniqueKey = BuildCardUniqueKey(card.get("kanji", ""), card.get("kana", ""), card.get("english", ""))
    row = connection.execute(
        "SELECT 1 FROM cards WHERE deck_id = ? AND unique_key = ?",
        (deckId, uniqueKey),
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
