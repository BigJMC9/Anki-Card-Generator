import json
import sqlite3
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

from AnkiDeckBuilder.AppConfig import CardSchemas, DefaultModel
from AnkiDeckBuilder.CsvService import ImportCsvCards
from AnkiDeckBuilder.DatabaseService import (
    AddCard,
    CountCardsInDeck,
    CreateCollection,
    CreateDeck,
    DeleteCardsByIds,
    DeckHasCandidate,
    GetDashboardRows,
    GetDeckCards,
    GetTotalCardCount,
    GetTotalDeckCount,
    ListCollections,
    ListDecks,
    RenameCollection,
    RenameDeck,
    UpdateCardContent,
    UpdateCardField,
    UpdateCardMedia,
)
from AnkiDeckBuilder.ExportService import ExportDeckPackage
from AnkiDeckBuilder.OpenAiService import (
    ConvertJapaneseWords,
    ExtractCardsFromImages,
    GenerateCardsFromText,
    GenerateEnglishTranslations,
    GetOpenAiClient,
    SupportedWordForms,
    VerifyCardsAgainstSelection,
)
from AnkiDeckBuilder.UiState import BeginBusyAction, EndBusyAction, IsBusy
from AnkiDeckBuilder.WorkspaceService import CopyUploadedMedia


def FormatDeckLabel(deck: Dict[str, Any]) -> str:
    collectionName = deck.get("collection_name", "Unknown collection")
    return f"{collectionName} :: {deck['name']}"


def ChooseDeck(connection: sqlite3.Connection, keyPrefix: str) -> Optional[Dict[str, Any]]:
    decks = ListDecks(connection, includeCollectionName=True)
    if not decks:
        st.warning("No decks available. Create a collection and deck first.")
        return None

    return st.selectbox(
        "Deck",
        decks,
        key=f"{keyPrefix}_DeckSelect",
        format_func=FormatDeckLabel,
    )


def BuildProgressUpdater(progressBar):
    def UpdateProgress(completed: int, total: int, message: str) -> None:
        if total <= 0:
            percent = 0
        else:
            percent = int((completed / total) * 100)
        progressBar.progress(min(max(percent, 0), 100), text=message)

    return UpdateProgress


def RenderErrorList(errors: List[str], title: str) -> None:
    if not errors:
        return
    with st.expander(title):
        for error in errors:
            st.write(f"- {error}")


def RenderDashboardPage(connection: sqlite3.Connection) -> None:
    collections = ListCollections(connection)
    totalDecks = GetTotalDeckCount(connection)
    totalCards = GetTotalCardCount(connection)

    metricOne, metricTwo, metricThree = st.columns(3)
    metricOne.metric("Collections", len(collections))
    metricTwo.metric("Decks", totalDecks)
    metricThree.metric("Cards", totalCards)

    rows = GetDashboardRows(connection)
    if rows:
        rowDictionaryList = [dict(row) for row in rows]
        st.dataframe(pd.DataFrame(rowDictionaryList), width="stretch", hide_index=True)
    else:
        st.info("Create a collection and a deck to get started.")


def RenderCollectionEditorPage(connection: sqlite3.Connection) -> None:
    with st.form("CreateCollectionForm"):
        name = st.text_input("New collection name")
        submitted = st.form_submit_button("Add collection", disabled=IsBusy())
        if submitted:
            if not name.strip():
                st.error("Enter a collection name.")
            else:
                try:
                    CreateCollection(connection, name)
                    st.success("Collection created.")
                except sqlite3.IntegrityError:
                    st.error("A collection with that name already exists.")

    collections = ListCollections(connection)
    if collections:
        with st.form("RenameCollectionForm"):
            selectedCollection = st.selectbox("Collection", collections, format_func=lambda row: row["name"])
            newName = st.text_input("New collection name")
            submitted = st.form_submit_button("Rename collection", disabled=IsBusy())
            if submitted:
                if not newName.strip():
                    st.error("Enter a new name.")
                else:
                    try:
                        RenameCollection(connection, selectedCollection["id"], newName)
                        st.success("Collection renamed.")
                    except sqlite3.IntegrityError:
                        st.error("A collection with that name already exists.")


def RenderDeckEditorPage(connection: sqlite3.Connection) -> None:
    collections = ListCollections(connection)
    if not collections:
        st.warning("Create a collection first.")
        return

    with st.form("CreateDeckForm"):
        selectedCollection = st.selectbox("Collection", collections, format_func=lambda row: row["name"])
        deckName = st.text_input("New deck name")
        submitted = st.form_submit_button("Add deck", disabled=IsBusy())
        if submitted:
            if not deckName.strip():
                st.error("Enter a deck name.")
            else:
                try:
                    CreateDeck(connection, selectedCollection["id"], deckName)
                    st.success("Deck created.")
                except sqlite3.IntegrityError:
                    st.error("A deck with that name already exists in this collection.")

    decks = ListDecks(connection, includeCollectionName=True)
    if decks:
        with st.form("RenameDeckForm"):
            selectedDeck = st.selectbox("Deck", decks, format_func=FormatDeckLabel)
            newName = st.text_input("New deck name")
            submitted = st.form_submit_button("Rename deck", disabled=IsBusy())
            if submitted:
                if not newName.strip():
                    st.error("Enter a new deck name.")
                else:
                    try:
                        RenameDeck(connection, selectedDeck["id"], newName)
                        st.success("Deck renamed.")
                    except sqlite3.IntegrityError:
                        st.error("A deck with that name already exists in this collection.")


def HandleTextGeneration(
    connection: sqlite3.Connection,
    deckId: str,
    sourceText: str,
    schemaKey: str,
    extraTags: List[str],
) -> None:
    if not BeginBusyAction("Generating cards from text"):
        st.warning("A request is already in progress.")
        return

    progressBar = st.progress(0, text="Preparing OpenAI request...")
    try:
        client = GetOpenAiClient()
        generatedCards, errors = GenerateCardsFromText(
            client,
            DefaultModel,
            sourceText,
            schemaKey,
            extraTags,
            BuildProgressUpdater(progressBar),
        )
        added = sum(AddCard(connection, deckId, card) for card in generatedCards)
        skipped = len(generatedCards) - added
        progressBar.progress(100, text="Card generation complete.")
        st.success(f"Generated {len(generatedCards)} candidates. Added {added}, skipped {skipped} duplicates.")
        RenderErrorList(errors, "Some chunks could not be parsed")
    except Exception as exc:
        st.error(str(exc))
    finally:
        EndBusyAction()


def RenderAddCardsPage(connection: sqlite3.Connection) -> None:
    deck = ChooseDeck(connection, "AddCards")
    if deck is None:
        return

    schemaKey = st.selectbox(
        "Card format",
        list(CardSchemas.keys()),
        format_func=lambda key: CardSchemas[key]["Label"],
    )
    tagsText = st.text_input("Extra tags (comma separated)", value="japanese")
    extraTags = [tag.strip() for tag in tagsText.split(",") if tag.strip()]

    mode = st.radio("Source", ["Paste text", "Upload text file", "Manual single card"])

    if mode == "Paste text":
        with st.form("AddCardsFromTextForm"):
            sourceText = st.text_area("Japanese source text", height=220)
            submitted = st.form_submit_button(
                "Generate cards from text",
                disabled=IsBusy(),
            )
        if submitted:
            if not sourceText.strip():
                st.error("Paste source text before generating cards.")
            else:
                HandleTextGeneration(connection, deck["id"], sourceText, schemaKey, extraTags)

    elif mode == "Upload text file":
        uploadedFile = st.file_uploader("Upload .txt or .md", type=["txt", "md"])
        with st.form("AddCardsFromFileForm"):
            submitted = st.form_submit_button(
                "Generate cards from uploaded text",
                disabled=IsBusy() or uploadedFile is None,
            )
        if submitted and uploadedFile:
            try:
                sourceText = uploadedFile.getvalue().decode("utf-8")
            except UnicodeDecodeError:
                st.error("Could not decode file. Please upload UTF-8 text.")
                return
            if not sourceText.strip():
                st.error("The uploaded file is empty.")
                return
            HandleTextGeneration(connection, deck["id"], sourceText, schemaKey, extraTags)
    else:
        with st.form("AddManualCardForm"):
            kanji = st.text_input("Kanji")
            kana = st.text_input("Hiragana / Katakana")
            english = st.text_input("English")
            notes = st.text_area("Notes")
            submitted = st.form_submit_button("Add card", disabled=IsBusy())
            if submitted:
                isAdded = AddCard(
                    connection,
                    deck["id"],
                    {
                        "kanji": kanji,
                        "kana": kana,
                        "english": english,
                        "notes": notes,
                        "source_text": "manual",
                        "schema_key": schemaKey,
                        "media_type": "none",
                        "media_files": [],
                        "tags": extraTags,
                    },
                )
                if isAdded:
                    st.success("Card added.")
                else:
                    st.warning("Duplicate card skipped.")


def RenderReviewCardsPage(connection: sqlite3.Connection) -> None:
    deck = ChooseDeck(connection, "ReviewCards")
    if deck is None:
        return

    cards = GetDeckCards(connection, deck["id"])
    if not cards:
        st.info("No cards in this deck yet.")
        return

    cardById = {card["id"]: card for card in cards}
    selectionStateKey = f"ReviewCardSelection_{deck['id']}"
    previousSelection = st.session_state.get(selectionStateKey, {})
    normalizedSelection = {cardId: bool(previousSelection.get(cardId, False)) for cardId in cardById}
    st.session_state[selectionStateKey] = normalizedSelection

    selectColumn, clearColumn = st.columns(2)
    with selectColumn:
        if st.button("Select all cards", disabled=IsBusy(), width="stretch"):
            st.session_state[selectionStateKey] = {cardId: True for cardId in cardById}
            st.rerun()
    with clearColumn:
        if st.button("Clear selection", disabled=IsBusy(), width="stretch"):
            st.session_state[selectionStateKey] = {cardId: False for cardId in cardById}
            st.rerun()

    searchText = st.text_input("Search cards", placeholder="Search kanji, kana, english, or notes")
    rows = []
    for index, card in enumerate(cards, start=1):
        rows.append(
            {
                "Select": st.session_state[selectionStateKey].get(card["id"], False),
                "CardId": card["id"],
                "Index": index,
                "Kanji": card["kanji"],
                "Kana": card["kana"],
                "English": card["english"],
                "Format": CardSchemas[card["schema_key"]]["Label"],
                "Notes": card["notes"],
            }
        )
    browserFrame = pd.DataFrame(rows)

    if searchText.strip():
        normalizedSearch = searchText.strip().lower()
        searchColumns = ["Kanji", "Kana", "English", "Notes"]
        mask = browserFrame[searchColumns].fillna("").apply(
            lambda row: row.astype(str).str.lower().str.contains(normalizedSearch).any(),
            axis=1,
        )
        browserFrame = browserFrame[mask].reset_index(drop=True)

    if browserFrame.empty:
        st.info("No cards match the current search.")
        return

    editedFrame = st.data_editor(
        browserFrame,
        hide_index=True,
        width="stretch",
        key=f"ReviewCardBrowser_{deck['id']}",
        disabled=["CardId", "Index", "Kanji", "Kana", "English", "Format", "Notes"],
        column_config={
            "Select": st.column_config.CheckboxColumn("Select"),
            "CardId": None,
        },
    )

    updatedSelection = st.session_state[selectionStateKey]
    for _, row in editedFrame.iterrows():
        updatedSelection[row["CardId"]] = bool(row["Select"])
    st.session_state[selectionStateKey] = updatedSelection

    selectedCardIds = [cardId for cardId, isSelected in updatedSelection.items() if isSelected and cardId in cardById]
    st.caption(f"Selected cards: {len(selectedCardIds)}")

    st.markdown("### Bulk actions")
    formatSelection = st.selectbox(
        "New card format for selected cards",
        list(CardSchemas.keys()),
        format_func=lambda key: CardSchemas[key]["Label"],
        key=f"BulkFormat_{deck['id']}",
    )

    conversionForm = st.selectbox(
        "Japanese word form for selected cards",
        list(SupportedWordForms.keys()),
        format_func=lambda key: SupportedWordForms[key],
        key=f"BulkWordForm_{deck['id']}",
    )
    requireEnglishTranslation = st.checkbox(
        "Require English translation",
        key=f"BulkRequireEnglish_{deck['id']}",
        help="If checked, missing English is generated for selected cards during Apply.",
    )

    applyColumn, verifyColumn, confirmDeleteColumn, deleteColumn = st.columns([1.1, 1.1, 1.0, 1.0])
    with applyColumn:
        applySubmitted = st.button(
            "Apply selected changes",
            disabled=IsBusy() or not selectedCardIds,
            width="stretch",
            type="primary",
        )
    with verifyColumn:
        verifySubmitted = st.button(
            "Verify selected cards",
            disabled=IsBusy() or not selectedCardIds,
            width="stretch",
        )
    with confirmDeleteColumn:
        confirmDelete = st.checkbox(
            "Confirm delete selected cards",
            key=f"ConfirmDelete_{deck['id']}",
        )
    with deleteColumn:
        deleteSubmitted = st.button(
            "Delete selected cards",
            disabled=IsBusy() or not selectedCardIds or not confirmDelete,
            width="stretch",
        )

    if applySubmitted:
        if not BeginBusyAction("Applying bulk changes"):
            st.warning("A request is already in progress.")
            return

        progressBar = st.progress(0, text="Applying bulk changes...")
        try:
            selectedCardsForApply = [cardById[cardId] for cardId in selectedCardIds if cardId in cardById]
            cardUpdatesById: Dict[str, Dict[str, str]] = {
                card["id"]: {
                    "kanji": card["kanji"],
                    "kana": card["kana"],
                    "english": card["english"],
                    "notes": card["notes"],
                    "schema_key": formatSelection,
                }
                for card in selectedCardsForApply
            }

            client = GetOpenAiClient()
            conversions, conversionErrors = ConvertJapaneseWords(
                client,
                DefaultModel,
                selectedCardsForApply,
                conversionForm,
                BuildProgressUpdater(progressBar),
            )
            convertedCount = 0
            for item in conversions:
                cardId = item["id"]
                if cardId not in cardUpdatesById:
                    continue
                currentKanji = cardUpdatesById[cardId]["kanji"]
                currentKana = cardUpdatesById[cardId]["kana"]
                nextKanji = item.get("kanji", currentKanji)
                nextKana = item.get("kana", currentKana)
                if nextKanji != currentKanji or nextKana != currentKana:
                    convertedCount += 1
                cardUpdatesById[cardId]["kanji"] = nextKanji
                cardUpdatesById[cardId]["kana"] = nextKana

            translatedCount = 0
            translationErrors: List[str] = []
            cardsMissingEnglish = []
            for card in selectedCardsForApply:
                updated = cardUpdatesById[card["id"]]
                if not (updated["english"] or "").strip():
                    cardsMissingEnglish.append(
                        {
                            "id": card["id"],
                            "kanji": updated["kanji"],
                            "kana": updated["kana"],
                            "source_text": card["source_text"],
                            "notes": card["notes"],
                        }
                    )

            if requireEnglishTranslation and cardsMissingEnglish:
                translations, translationErrors = GenerateEnglishTranslations(
                    client,
                    DefaultModel,
                    cardsMissingEnglish,
                    BuildProgressUpdater(progressBar),
                )
                for item in translations:
                    cardId = item["id"]
                    if cardId not in cardUpdatesById:
                        continue
                    currentEnglish = cardUpdatesById[cardId]["english"]
                    nextEnglish = item["english"]
                    if currentEnglish != nextEnglish:
                        translatedCount += 1
                    cardUpdatesById[cardId]["english"] = nextEnglish

            appliedCount = 0
            duplicateSkippedCount = 0
            for card in selectedCardsForApply:
                updated = cardUpdatesById[card["id"]]
                isApplied = UpdateCardContent(
                    connection,
                    deck["id"],
                    card["id"],
                    updated["kanji"],
                    updated["kana"],
                    updated["english"],
                    updated["notes"],
                    updated["schema_key"],
                )
                if isApplied:
                    appliedCount += 1
                else:
                    duplicateSkippedCount += 1

            progressBar.progress(100, text="Bulk changes applied.")
            statusParts = [
                f"Applied changes to {appliedCount} card(s)",
                f"converted {convertedCount} card(s) to {SupportedWordForms[conversionForm]}",
            ]
            if requireEnglishTranslation:
                statusParts.append(f"generated English for {translatedCount} card(s)")
            if duplicateSkippedCount:
                statusParts.append(f"skipped {duplicateSkippedCount} duplicate word(s) in the selected format")
            st.success("; ".join(statusParts) + ".")
            if requireEnglishTranslation and not cardsMissingEnglish:
                st.info("All selected cards already include English translations.")
            RenderErrorList(conversionErrors, "Some conversions failed")
            RenderErrorList(translationErrors, "Translation errors")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
        finally:
            EndBusyAction()

    if verifySubmitted:
        if not BeginBusyAction("Verifying selected cards"):
            st.warning("A request is already in progress.")
            return

        progressBar = st.progress(0, text="Verifying selected cards...")
        try:
            selectedCardsForVerify = [cardById[cardId] for cardId in selectedCardIds if cardId in cardById]
            client = GetOpenAiClient()
            verifiedCards, verificationErrors = VerifyCardsAgainstSelection(
                client,
                DefaultModel,
                selectedCardsForVerify,
                conversionForm,
                formatSelection,
                BuildProgressUpdater(progressBar),
            )
            verifiedById = {item["id"]: item for item in verifiedCards}

            verifiedCount = 0
            duplicateSkippedCount = 0
            for card in selectedCardsForVerify:
                verified = verifiedById.get(card["id"])
                if not verified:
                    continue
                isApplied = UpdateCardContent(
                    connection,
                    deck["id"],
                    card["id"],
                    verified["kanji"],
                    verified["kana"],
                    verified["english"],
                    verified["notes"],
                    formatSelection,
                )
                if isApplied:
                    verifiedCount += 1
                else:
                    duplicateSkippedCount += 1

            progressBar.progress(100, text="Verification complete.")
            statusParts = [f"Verified and updated {verifiedCount} card(s)"]
            if duplicateSkippedCount:
                statusParts.append(f"skipped {duplicateSkippedCount} duplicate word(s) in the selected format")
            st.success("; ".join(statusParts) + ".")
            RenderErrorList(verificationErrors, "Verification issues")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
        finally:
            EndBusyAction()

    if deleteSubmitted:
        deletedCount = DeleteCardsByIds(connection, deck["id"], selectedCardIds)
        st.success(f"Deleted {deletedCount} card(s).")
        st.rerun()

    selectedCards = [cardById[cardId] for cardId in selectedCardIds if cardId in cardById]
    if len(selectedCards) != 1:
        st.info("Select exactly one card above for detailed text/media editing.")
        return

    card = selectedCards[0]
    st.markdown("### Single card edit")
    st.write(
        {
            "kanji": card["kanji"],
            "kana": card["kana"],
            "english": card["english"],
            "notes": card["notes"],
            "schema": CardSchemas[card["schema_key"]]["Label"],
            "media_type": card["media_type"],
            "media_files": json.loads(card["media_files_json"]),
        }
    )

    with st.form("EditCardTextForm"):
        kanji = st.text_input("Kanji", value=card["kanji"])
        kana = st.text_input("Hiragana / Katakana", value=card["kana"])
        english = st.text_input("English", value=card["english"])
        notes = st.text_area("Notes", value=card["notes"])
        schemaKey = st.selectbox(
            "Card format",
            list(CardSchemas.keys()),
            index=list(CardSchemas.keys()).index(card["schema_key"]),
            format_func=lambda key: CardSchemas[key]["Label"],
        )
        submitted = st.form_submit_button("Save text changes", disabled=IsBusy())
        if submitted:
            isUpdated = UpdateCardContent(
                connection,
                deck["id"],
                card["id"],
                kanji,
                kana,
                english,
                notes,
                schemaKey,
            )
            if isUpdated:
                st.success("Card updated.")
                st.rerun()
            else:
                st.warning("Update skipped: duplicate word already exists in this format.")

    with st.form("GenerateMissingEnglishForm"):
        st.caption("Generate English translation if this card is missing English text.")
        submittedGenerateEnglish = st.form_submit_button(
            "Generate missing English translation",
            disabled=IsBusy() or bool(card["english"].strip()),
        )
        if submittedGenerateEnglish:
            if not BeginBusyAction("Generating missing English translations"):
                st.warning("A request is already in progress.")
                return
            progressBar = st.progress(0, text="Preparing translation...")
            try:
                client = GetOpenAiClient()
                translations, translationErrors = GenerateEnglishTranslations(
                    client,
                    DefaultModel,
                    [card],
                    BuildProgressUpdater(progressBar),
                )
                generatedCount = 0
                for item in translations:
                    if item["id"] != card["id"]:
                        continue
                    isUpdated = UpdateCardContent(
                        connection,
                        deck["id"],
                        card["id"],
                        card["kanji"],
                        card["kana"],
                        item["english"],
                        card["notes"],
                        card["schema_key"],
                    )
                    generatedCount += int(isUpdated)
                progressBar.progress(100, text="English translation generation complete.")
                if generatedCount > 0:
                    st.success("Generated English translation for this card.")
                    st.rerun()
                else:
                    st.warning("No translation was generated (or update was skipped as duplicate).")
                RenderErrorList(translationErrors, "Translation errors")
            except Exception as exc:
                st.error(str(exc))
            finally:
                EndBusyAction()

    st.markdown("### Replace text with media")
    with st.form("ReplaceWithMediaForm"):
        replaceTarget = st.selectbox("Replace which concept", ["english", "kana", "kanji", "none"])
        mediaType = st.selectbox("Media type", ["image", "audio", "video"])
        uploads = st.file_uploader(
            "Upload one or more media files",
            accept_multiple_files=True,
            type=["png", "jpg", "jpeg", "webp", "mp3", "wav", "m4a", "ogg", "mp4", "webm", "mov"],
        )
        submitted = st.form_submit_button("Apply media replacement", disabled=IsBusy())
        if submitted:
            if replaceTarget == "none" or not uploads:
                st.warning("Pick a target and upload at least one media file.")
            else:
                try:
                    savedPaths = [CopyUploadedMedia(upload, deck["id"]) for upload in uploads]
                    if replaceTarget in {"english", "kana", "kanji"}:
                        UpdateCardField(connection, card["id"], replaceTarget, f"[{mediaType.upper()}]")
                    UpdateCardMedia(connection, card["id"], mediaType, savedPaths)
                    st.success("Media attached to card.")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("Media replacement skipped: duplicate word already exists in this format.")


def RenderScanImagesPage(connection: sqlite3.Connection) -> None:
    deck = ChooseDeck(connection, "ScanImages")
    if deck is None:
        return

    schemaKey = st.selectbox(
        "Card format for new cards",
        list(CardSchemas.keys()),
        format_func=lambda key: CardSchemas[key]["Label"],
        key="ScanImagesSchema",
    )
    tagsText = st.text_input("Extra tags", value="japanese,image-scan", key="ScanImagesTags")
    extraTags = [tag.strip() for tag in tagsText.split(",") if tag.strip()]
    wordForm = st.selectbox(
        "Word form for extracted Japanese words",
        list(SupportedWordForms.keys()),
        format_func=lambda key: SupportedWordForms[key],
        key="ScanImagesWordForm",
    )

    uploads = st.file_uploader(
        "Upload one or more images",
        type=["png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
        key="ScanImagesUploader",
    )

    if uploads:
        fileRows = [
            {
                "file_name": upload.name,
                "size_mb": round(upload.size / (1024 * 1024), 2),
            }
            for upload in uploads
        ]
        st.dataframe(pd.DataFrame(fileRows), width="stretch", hide_index=True)

    if st.button(
        "Scan images and add missing cards",
        disabled=IsBusy() or not uploads,
        width="stretch",
    ):
        if not BeginBusyAction("Scanning images and adding missing cards"):
            st.warning("A request is already in progress.")
            return

        progressBar = st.progress(0, text="Preparing image scan...")
        try:
            client = GetOpenAiClient()
            extractedCards, errors = ExtractCardsFromImages(
                client,
                DefaultModel,
                uploads,
                schemaKey,
                extraTags,
                wordForm,
                BuildProgressUpdater(progressBar),
            )
            cardsMissingEnglish = [card for card in extractedCards if not (card.get("english") or "").strip()]
            if cardsMissingEnglish:
                progressBar.progress(65, text="Generating missing English translations...")
                translationCards = [
                    {
                        "id": str(index),
                        "kanji": card.get("kanji", ""),
                        "kana": card.get("kana", ""),
                        "source_text": card.get("source_text", ""),
                        "notes": card.get("notes", ""),
                    }
                    for index, card in enumerate(cardsMissingEnglish)
                ]
                translations, translationErrors = GenerateEnglishTranslations(
                    client,
                    DefaultModel,
                    translationCards,
                    BuildProgressUpdater(progressBar),
                )
                translationById = {item["id"]: item["english"] for item in translations}
                for index, card in enumerate(cardsMissingEnglish):
                    english = translationById.get(str(index), "")
                    if english:
                        card["english"] = english
                errors.extend([f"Translation: {error}" for error in translationErrors])

            added = 0
            duplicates = 0
            for card in extractedCards:
                if DeckHasCandidate(connection, deck["id"], card):
                    duplicates += 1
                    continue
                if AddCard(connection, deck["id"], card):
                    added += 1

            progressBar.progress(100, text="Image scan complete.")
            st.success(
                f"Scanned {len(uploads)} images. Added {added} new cards and skipped {duplicates} duplicates."
            )
            if extractedCards:
                st.dataframe(pd.DataFrame(extractedCards), width="stretch", hide_index=True)
            missingEnglishCount = sum(1 for card in extractedCards if not (card.get("english") or "").strip())
            if missingEnglishCount > 0:
                st.warning(f"{missingEnglishCount} extracted card(s) are still missing English translations.")
            RenderErrorList(errors, "Some images failed to parse")
        except Exception as exc:
            st.error(str(exc))
        finally:
            EndBusyAction()


def RenderImportCsvPage(connection: sqlite3.Connection) -> None:
    deck = ChooseDeck(connection, "ImportCsv")
    if deck is None:
        return

    st.caption("CSV columns: kanji, kana, english, notes, source_text, schema_key, media_type, tags")
    uploaded = st.file_uploader("Upload CSV", type=["csv"], key="ImportCsvUploader")

    if st.button(
        "Import CSV cards",
        disabled=IsBusy() or uploaded is None,
        width="stretch",
    ):
        if not BeginBusyAction("Importing CSV cards"):
            st.warning("A request is already in progress.")
            return

        progressBar = st.progress(25, text="Reading CSV...")
        try:
            added, skipped = ImportCsvCards(connection, deck["id"], uploaded)
            progressBar.progress(100, text="CSV import complete.")
            st.success(f"Added {added} cards and skipped {skipped} duplicates.")
        except Exception as exc:
            st.error(str(exc))
        finally:
            EndBusyAction()


def RenderExportPage(connection: sqlite3.Connection) -> None:
    deck = ChooseDeck(connection, "ExportDeck")
    if deck is None:
        return

    if CountCardsInDeck(connection, deck["id"]) == 0:
        st.info("This deck has no cards yet.")

    if st.button("Build .apkg", disabled=IsBusy(), width="stretch"):
        if not BeginBusyAction("Exporting Anki package"):
            st.warning("A request is already in progress.")
            return

        progressBar = st.progress(35, text="Building Anki package...")
        try:
            path = ExportDeckPackage(connection, deck["id"])
            progressBar.progress(100, text="Export complete.")
            st.success(f"Exported to {path}")
            with open(path, "rb") as outputFile:
                st.download_button(
                    "Download .apkg",
                    data=outputFile.read(),
                    file_name=path.name,
                    mime="application/octet-stream",
                )
        except Exception as exc:
            st.error(str(exc))
        finally:
            EndBusyAction()


PageRendererByKey = {
    "Dashboard": RenderDashboardPage,
    "CreateCollections": RenderCollectionEditorPage,
    "CreateDecks": RenderDeckEditorPage,
    "AddCards": RenderAddCardsPage,
    "ReviewCards": RenderReviewCardsPage,
    "ScanImages": RenderScanImagesPage,
    "ImportCsv": RenderImportCsvPage,
    "ExportDeck": RenderExportPage,
}


def RenderPage(connection: sqlite3.Connection, pageKey: str) -> None:
    renderer = PageRendererByKey.get(pageKey, RenderDashboardPage)
    renderer(connection)
