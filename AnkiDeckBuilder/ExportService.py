import hashlib
import html
import json
from pathlib import Path
from typing import Tuple

import genanki
import sqlite3

from AnkiDeckBuilder.AppConfig import (
    CardSchemas,
    ExportDir,
    NoteModelId,
    SupportedAudioExtensions,
    SupportedImageExtensions,
    SupportedVideoExtensions,
)
from AnkiDeckBuilder.DatabaseService import GetDeckCards, GetDeckRow


def RenderField(fieldName: str, card: sqlite3.Row) -> str:
    value = (card[fieldName] or "").strip()
    if not value:
        return ""
    return html.escape(value)


def RenderMedia(card: sqlite3.Row) -> str:
    mediaType = card["media_type"]
    mediaFiles = json.loads(card["media_files_json"])
    if not mediaFiles:
        return ""

    tags = []
    for filePath in mediaFiles:
        name = Path(filePath).name
        extension = Path(name).suffix.lower()
        if mediaType == "image" or extension in SupportedImageExtensions:
            tags.append(f'<div><img src="{html.escape(name)}" style="max-width: 95%;"></div>')
        elif mediaType == "audio" or extension in SupportedAudioExtensions:
            tags.append(f"[sound:{name}]")
        elif mediaType == "video" or extension in SupportedVideoExtensions:
            tags.append(
                f'<video controls style="max-width: 95%;"><source src="{html.escape(name)}"></video>'
            )
    return "<br>".join(tags)


def RenderDictionaryReference(card: sqlite3.Row) -> str:
    entryId = (card["dictionary_entry_id"] or "").strip()
    if not entryId:
        return ""

    headword = html.escape((card["dictionary_headword"] or "").strip())
    reading = html.escape((card["dictionary_reading"] or "").strip())
    gloss = html.escape((card["dictionary_gloss"] or "").strip())
    wordForm = html.escape((card["word_form"] or "").strip())

    summary = f"{headword} [{reading}]".strip() if reading else headword
    detailParts = [item for item in [summary, gloss] if item]
    detail = " - ".join(detailParts)
    formText = f" | form: {wordForm}" if wordForm else ""
    return f"<small>JMDict #{html.escape(entryId)}: {detail}{formText}</small>"


def BuildNoteFields(card: sqlite3.Row) -> Tuple[str, str, str]:
    schema = CardSchemas[card["schema_key"]]

    frontParts = [RenderField(field, card) for field in schema["FrontFields"] if RenderField(field, card)]
    backParts = [RenderField(field, card) for field in schema["BackFields"] if RenderField(field, card)]

    mediaHtml = RenderMedia(card)
    dictionaryReferenceHtml = RenderDictionaryReference(card)
    notes = RenderField("notes", card)

    frontHtml = "<br>".join(frontParts)
    backHtml = "<br>".join(backParts)

    if notes:
        backHtml += f"<hr>{notes}" if backHtml else notes
    if dictionaryReferenceHtml:
        backHtml += f"<hr>{dictionaryReferenceHtml}" if backHtml else dictionaryReferenceHtml
    if mediaHtml:
        backHtml += f"<hr>{mediaHtml}" if backHtml else mediaHtml

    sortField = RenderField("kanji", card) or RenderField("kana", card) or RenderField("english", card)
    return frontHtml, backHtml, sortField


def CreateAnkiModel() -> genanki.Model:
    return genanki.Model(
        NoteModelId,
        "Japanese Builder Model",
        fields=[
            {"name": "Front"},
            {"name": "Back"},
            {"name": "Sort"},
        ],
        templates=[
            {
                "name": "Card 1",
                "qfmt": "{{Front}}",
                "afmt": "{{FrontSide}}<hr id='answer'>{{Back}}",
            }
        ],
        css="""
        .card {
          font-family: Arial, sans-serif;
          font-size: 28px;
          text-align: center;
          color: black;
          background-color: white;
        }
        img { max-width: 95%; height: auto; }
        video { max-width: 95%; }
        """,
    )


def CreateStableDeckId(collectionName: str, deckName: str) -> int:
    seed = hashlib.sha1(f"{collectionName}::{deckName}".encode("utf-8")).hexdigest()[:10]
    return int(seed, 16)


def ExportDeckPackage(connection: sqlite3.Connection, deckId: str) -> Path:
    deckRow = GetDeckRow(connection, deckId)
    cards = GetDeckCards(connection, deckId)
    model = CreateAnkiModel()
    deck = genanki.Deck(
        CreateStableDeckId(deckRow["collection_name"], deckRow["deck_name"]),
        f'{deckRow["collection_name"]}::{deckRow["deck_name"]}',
    )

    mediaFiles = []
    for card in cards:
        frontHtml, backHtml, sortField = BuildNoteFields(card)
        note = genanki.Note(model=model, fields=[frontHtml, backHtml, sortField])
        deck.add_note(note)
        mediaFiles.extend(json.loads(card["media_files_json"]))

    exportPath = ExportDir / f"{deckRow['collection_name']}__{deckRow['deck_name']}.apkg"
    package = genanki.Package(deck)
    package.media_files = sorted(set(mediaFiles))
    package.write_to_file(str(exportPath))
    return exportPath
