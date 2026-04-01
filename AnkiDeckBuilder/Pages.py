import json
import re
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
    DeckHasKanjiWordForm,
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
    UpdateCardsSchemaByIds,
)
from AnkiDeckBuilder.ExportService import ExportDeckPackage
from AnkiDeckBuilder.JamdictService import (
    BuildCardFromDictionaryEntry,
    FormatDictionaryEntryOption,
    GetVerbFormOptions,
    IsVerbEntry,
    LooksLikePoliteMasuSurface,
    NormalizeNumericJapaneseSurface,
    ResolveBestDictionaryEntry,
    SearchDictionaryEntries,
    VerbFormLabels,
)
from AnkiDeckBuilder.OpenAiService import ExtractCardsFromImages, GetOpenAiClient
from AnkiDeckBuilder.UiState import BeginBusyAction, EndBusyAction, IsBusy
from AnkiDeckBuilder.WorkspaceService import CopyUploadedMedia

AddCardsResultsStateKey = "AddCardsSearchResults"
AddCardsQueryStateKey = "AddCardsSearchQuery"
JapaneseSegmentPattern = re.compile(r"[一-龯々〆ヶぁ-ゖァ-ヺー]+")
KanjiOnlyPattern = re.compile(r"^[一-龯々〆ヶ]+$")
KanaOnlyPattern = re.compile(r"^[ぁ-ゖァ-ヺー]+$")
NumeralKanjiPattern = re.compile(r"[一二三四五六七八九十百千万〇零]")
NumericFunCompoundPattern = re.compile(r"^[一二三四五六七八九十百千万〇零]+分$")
ScanExpressionConnectors = ("の", "ノ", "/", "／")


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


def SearchAndRenderDictionaryOptions() -> List[Dict[str, Any]]:
    st.markdown("### Dictionary search")
    searchColumns = st.columns([4.0, 1.0])
    with searchColumns[0]:
        query = st.text_input(
            "Search word",
            key=AddCardsQueryStateKey,
            placeholder="Type kanji or kana (example: 食べる, たべる, 勉強)",
        )
    with searchColumns[1]:
        searchClicked = st.button("Search", width="stretch")

    if searchClicked:
        normalizedQuery = (query or "").strip()
        if not normalizedQuery:
            st.warning("Enter a word to search.")
            st.session_state[AddCardsResultsStateKey] = []
        else:
            try:
                st.session_state[AddCardsResultsStateKey] = SearchDictionaryEntries(normalizedQuery, limit=30)
            except Exception as exc:
                st.session_state[AddCardsResultsStateKey] = []
                st.error(str(exc))

    return st.session_state.get(AddCardsResultsStateKey, [])


def RenderAddCardsPage(connection: sqlite3.Connection) -> None:
    deck = ChooseDeck(connection, "AddCards")
    if deck is None:
        return

    schemaKey = st.selectbox(
        "Card format",
        list(CardSchemas.keys()),
        format_func=lambda key: CardSchemas[key]["Label"],
        key="AddCardsSchema",
    )
    tagsText = st.text_input("Extra tags (comma separated)", value="japanese,manual", key="AddCardsTags")
    extraTags = [tag.strip() for tag in tagsText.split(",") if tag.strip()]

    entries = SearchAndRenderDictionaryOptions()
    if not entries:
        st.info("Search jamdict and select an entry to add a card.")
        return

    optionById = {entry["entry_id"]: entry for entry in entries if entry.get("entry_id")}
    optionIds = list(optionById.keys())
    if not optionIds:
        st.warning("Dictionary returned entries without IDs; try a different search.")
        return

    selectedEntryId = st.selectbox(
        "Dictionary entries",
        optionIds,
        format_func=lambda entryId: FormatDictionaryEntryOption(optionById[entryId]),
        key="AddCardsEntrySelect",
    )
    selectedEntry = optionById[selectedEntryId]

    wordFormOptions = GetVerbFormOptions(selectedEntry)
    requestedWordForm = st.selectbox(
        "Word form",
        wordFormOptions,
        format_func=lambda key: VerbFormLabels[key],
        key=f"AddCardsWordForm_{selectedEntryId}",
    )
    if not IsVerbEntry(selectedEntry):
        st.caption("Selected entry is not a verb. Plain dictionary form will be used.")
    else:
        st.caption(f"Verb type: {selectedEntry.get('verb_type_label', 'Verb')}")

    englishOverride = st.text_input(
        "English (optional override)",
        value=selectedEntry.get("english", ""),
        key=f"AddCardsEnglishOverride_{selectedEntryId}",
    )
    notes = st.text_area(
        "Notes (optional)",
        value="",
        key=f"AddCardsNotes_{selectedEntryId}",
    )

    previewCard = BuildCardFromDictionaryEntry(
        selectedEntry,
        schemaKey,
        requestedWordForm,
        extraTags,
        notes,
        englishOverride=englishOverride,
    )
    st.markdown("### Card preview")
    st.write(
        {
            "kanji": previewCard["kanji"],
            "kana": previewCard["kana"],
            "english": previewCard["english"],
            "word_form": previewCard["word_form"],
            "dictionary_entry_id": previewCard["dictionary_entry_id"],
        }
    )

    if st.button("Add selected dictionary entry", disabled=IsBusy(), width="stretch", type="primary"):
        isAdded = AddCard(connection, deck["id"], previewCard)
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

    searchText = st.text_input("Search cards", placeholder="Search kanji, kana, english, notes, dictionary id")
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
                "WordForm": card["word_form"] or "dictionary",
                "DictionaryId": card["dictionary_entry_id"] or "",
                "Notes": card["notes"],
            }
        )
    browserFrame = pd.DataFrame(rows)

    if searchText.strip():
        normalizedSearch = searchText.strip().lower()
        searchColumns = ["Kanji", "Kana", "English", "Notes", "DictionaryId"]
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
        disabled=["CardId", "Index", "Kanji", "Kana", "English", "Format", "WordForm", "DictionaryId", "Notes"],
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

    applyColumn, confirmDeleteColumn, deleteColumn = st.columns([1.1, 1.0, 1.0])
    with applyColumn:
        applyFormatSubmitted = st.button(
            "Apply selected format",
            disabled=IsBusy() or not selectedCardIds,
            width="stretch",
            type="primary",
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

    if applyFormatSubmitted:
        updatedCount = UpdateCardsSchemaByIds(connection, deck["id"], selectedCardIds, formatSelection)
        skippedCount = len(selectedCardIds) - updatedCount
        statusParts = [f"Updated format for {updatedCount} card(s)"]
        if skippedCount:
            statusParts.append(f"skipped {skippedCount} duplicate word(s)")
        st.success("; ".join(statusParts) + ".")
        st.rerun()

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
            "word_form": card["word_form"],
            "dictionary_entry_id": card["dictionary_entry_id"],
            "dictionary_headword": card["dictionary_headword"],
            "dictionary_reading": card["dictionary_reading"],
            "dictionary_gloss": card["dictionary_gloss"],
            "dictionary_pos": card["dictionary_pos"],
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


def NormalizeScanText(value: str) -> str:
    normalizedValue = re.sub(r"\s+", "", (value or "").strip())
    return NormalizeNumericJapaneseSurface(normalizedValue)


def ExtractScanTermsFromExpression(expression: str) -> List[str]:
    normalizedExpression = NormalizeScanText(expression)
    if not normalizedExpression:
        return []

    containsConnector = any(connector in normalizedExpression for connector in ScanExpressionConnectors)
    if containsConnector:
        rawParts = re.split(r"[のノ/／]+", normalizedExpression)
        segments: List[str] = []
        for rawPart in rawParts:
            segments.extend(JapaneseSegmentPattern.findall(rawPart))
    else:
        segments = JapaneseSegmentPattern.findall(normalizedExpression)

    if not segments:
        return [normalizedExpression]

    if not containsConnector:
        terms: List[str] = []
        for segment in segments:
            if segment and segment not in terms:
                terms.append(segment)
        return terms

    # Connector expressions with numeric compounds should expand to atomic terms.
    # Example: 四分の三 -> 四, 分, 三
    terms: List[str] = []
    for segment in segments:
        if not segment:
            continue

        isKanjiCompound = len(segment) > 1 and KanjiOnlyPattern.match(segment) is not None
        isNumericCompound = isKanjiCompound and NumeralKanjiPattern.search(segment) is not None
        if isNumericCompound:
            for character in segment:
                if character not in terms:
                    terms.append(character)
        else:
            if segment not in terms:
                terms.append(segment)

    return terms


def ExpandExtractedScanCandidates(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    expandedCandidates: List[Dict[str, Any]] = []
    seenKeys = set()
    dictionaryMatchCache: Dict[str, bool] = {}

    for candidate in candidates:
        originalVisibleText = NormalizeScanText(candidate.get("visible_text", ""))
        originalKanjiText = NormalizeScanText(candidate.get("kanji", ""))
        originalKanaText = NormalizeScanText(candidate.get("kana", ""))

        seedExpressions: List[str] = []
        for seed in [originalKanjiText, originalVisibleText]:
            if seed and seed not in seedExpressions:
                seedExpressions.append(seed)

        derivedTerms: List[str] = []
        for expression in seedExpressions:
            for term in ExtractScanTermsFromExpression(expression):
                if term and term not in derivedTerms:
                    derivedTerms.append(term)

        refinedTerms: List[str] = []
        for term in derivedTerms:
            normalizedTerm = NormalizeScanText(term)
            if not normalizedTerm:
                continue

            forceSplitNumericFunCompound = NumericFunCompoundPattern.match(normalizedTerm) is not None
            if forceSplitNumericFunCompound:
                for character in normalizedTerm:
                    if character not in refinedTerms:
                        refinedTerms.append(character)
                continue

            shouldSplitUnmatchedCompound = (
                len(normalizedTerm) > 1
                and KanjiOnlyPattern.match(normalizedTerm) is not None
            )
            if shouldSplitUnmatchedCompound:
                if normalizedTerm not in dictionaryMatchCache:
                    try:
                        dictionaryMatchCache[normalizedTerm] = bool(
                            SearchDictionaryEntries(normalizedTerm, limit=1)
                        )
                    except Exception:
                        # If dictionary search fails, keep original compound to avoid data loss.
                        dictionaryMatchCache[normalizedTerm] = True

                if not dictionaryMatchCache[normalizedTerm]:
                    for character in normalizedTerm:
                        if character not in refinedTerms:
                            refinedTerms.append(character)
                    continue

            if normalizedTerm not in refinedTerms:
                refinedTerms.append(normalizedTerm)

        if not refinedTerms:
            fallbackTerm = originalKanjiText or originalVisibleText
            if fallbackTerm:
                refinedTerms = [fallbackTerm]

        originText = originalVisibleText or originalKanjiText
        for term in refinedTerms:
            normalizedOrigin = NormalizeScanText(originText)
            normalizedTerm = NormalizeScanText(term)
            isKanaOnlyTerm = KanaOnlyPattern.match(normalizedTerm or "") is not None
            isKanaOnlyOrigin = KanaOnlyPattern.match(normalizedOrigin or "") is not None
            if isKanaOnlyTerm and isKanaOnlyOrigin:
                # Kana-only OCR terms are highly ambiguous and generate noisy homophone matches.
                continue

            candidateKey = (term, "")
            if candidateKey in seenKeys:
                continue
            seenKeys.add(candidateKey)

            keepOriginalKana = len(refinedTerms) == 1 and term in {originalKanjiText, originalVisibleText}
            expandedCandidates.append(
                {
                    **candidate,
                    "origin_visible_text": originText or term,
                    "visible_text": term,
                    "kanji": term,
                    "kana": originalKanaText if keepOriginalKana else "",
                }
            )

    return expandedCandidates


def BuildScanCandidateNote(candidate: Dict[str, Any]) -> str:
    imageName = (candidate.get("image_name") or "").strip()
    originText = NormalizeScanText(candidate.get("origin_visible_text", ""))
    termText = NormalizeScanText(candidate.get("visible_text", "")) or NormalizeScanText(candidate.get("kanji", ""))

    note = f"Extracted from image: {imageName}" if imageName else "Extracted from image"
    if originText and originText != termText:
        note += f" | Derived from: {originText}"
    return note


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
        "Verb form for matched dictionary verbs",
        list(VerbFormLabels.keys()),
        format_func=lambda key: VerbFormLabels[key],
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
            extractedCandidates, errors = ExtractCardsFromImages(
                client,
                DefaultModel,
                uploads,
                BuildProgressUpdater(progressBar),
            )
            expandedCandidates = ExpandExtractedScanCandidates(extractedCandidates)

            resolvedCards: List[Dict[str, Any]] = []
            previewRows: List[Dict[str, Any]] = []
            dictionaryMatchedCount = 0
            dictionaryMissCount = 0
            politeSurfaceSkippedCount = 0
            duplicateEntrySkippedCount = 0
            seenSurfaceAndForm = set()

            for index, candidate in enumerate(expandedCandidates, start=1):
                progressBar.progress(
                    min(95, 30 + int((index / max(len(expandedCandidates), 1)) * 60)),
                    text=f"Matching dictionary entries ({index}/{len(expandedCandidates)})...",
                )
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
                        schemaKey,
                        wordForm,
                        extraTags + ["image_ocr"],
                        notes=noteText,
                        sourceText=sourceText,
                    )
                else:
                    dictionaryMissCount += 1
                    continue

                if wordForm == "dictionary" and (
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
                        "matched_dictionary": bool(resolvedEntry),
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
                    deck["id"],
                    card.get("schema_key", ""),
                    card.get("word_form", "dictionary"),
                    card.get("kanji", ""),
                ):
                    duplicates += 1
                    continue
                if DeckHasCandidate(connection, deck["id"], card):
                    duplicates += 1
                    continue
                if AddCard(connection, deck["id"], card):
                    added += 1

            progressBar.progress(100, text="Image scan complete.")
            st.success(
                f"Scanned {len(uploads)} images. Added {added} new cards and skipped {duplicates} duplicates."
            )
            st.info(
                f"OCR produced {len(extractedCandidates)} raw candidate(s), expanded to {len(expandedCandidates)} term candidate(s). "
                f"Dictionary matched {dictionaryMatchedCount} candidate(s); "
                f"skipped {dictionaryMissCount} unmatched candidate(s); "
                f"skipped {politeSurfaceSkippedCount} candidate(s) that still looked like polite/masu while dictionary form was selected; "
                f"skipped {duplicateEntrySkippedCount} duplicate dictionary-entry candidate(s)."
            )
            if previewRows:
                st.dataframe(pd.DataFrame(previewRows), width="stretch", hide_index=True)
            RenderErrorList(errors, "Some images failed to parse")
        except Exception as exc:
            st.error(str(exc))
        finally:
            EndBusyAction()


def RenderImportCsvPage(connection: sqlite3.Connection) -> None:
    deck = ChooseDeck(connection, "ImportCsv")
    if deck is None:
        return

    st.caption(
        "CSV columns: kanji, kana, english, notes, source_text, schema_key, media_type, tags, "
        "dictionary_entry_id, dictionary_headword, dictionary_reading, dictionary_gloss, "
        "dictionary_pos, verb_type, word_form"
    )
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
