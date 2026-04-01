from dataclasses import dataclass
from typing import Dict, List, Optional

import sqlite3
import streamlit as st

from AnkiDeckBuilder.AppConfig import AppDir, AppTitle
from AnkiDeckBuilder.DatabaseService import CountCardsInDeck, ListCollections, ListDecks


@dataclass(frozen=True)
class PageDefinition:
    Key: str
    Label: str
    Description: str
    Section: str


PageDefinitions: List[PageDefinition] = [
    PageDefinition("Dashboard", "Dashboard", "Deck and card totals across your workspace.", "Overview"),
    PageDefinition(
        "CreateCollections",
        "Create / Rename Collections",
        "Set up collection groups before building decks.",
        "Build",
    ),
    PageDefinition(
        "CreateDecks",
        "Create / Rename Decks",
        "Create decks inside collections and keep names organized.",
        "Build",
    ),
    PageDefinition(
        "AddCards",
        "Search Dictionary / Add Cards",
        "Search jamdict and add selected entries to global pool or decks.",
        "Build",
    ),
    PageDefinition(
        "GlobalCards",
        "Global Card Pool",
        "Manage reusable global cards and import between global pool and decks.",
        "Build",
    ),
    PageDefinition(
        "ReviewCards",
        "Review Cards / Replace With Media",
        "Edit card text, adjust card formats, and attach media replacements.",
        "Maintain",
    ),
    PageDefinition(
        "ScanImages",
        "Scan Images For Missing Cards",
        "Extract visible text from images and add missing cards.",
        "Build",
    ),
    PageDefinition(
        "ImportCsv",
        "Import CSV",
        "Bulk import cards from a CSV file.",
        "Maintain",
    ),
    PageDefinition(
        "ExportDeck",
        "Export Deck",
        "Build and download Anki .apkg deck packages.",
        "Maintain",
    ),
]

PageOrder = [page.Key for page in PageDefinitions]
PageByKey: Dict[str, PageDefinition] = {page.Key: page for page in PageDefinitions}
SectionOrder = ["Overview", "Build", "Maintain"]


def GetDefaultPageKey() -> str:
    return "Dashboard"


def GetPageDefinition(pageKey: str) -> PageDefinition:
    return PageByKey.get(pageKey, PageByKey[GetDefaultPageKey()])


def RenderSidebarNavigation(
    connection: sqlite3.Connection,
    currentPageKey: str,
    disableNavigation: bool,
) -> str:
    st.sidebar.title(AppTitle)
    st.sidebar.caption(f"Workspace: {AppDir.resolve()}")

    selectedPageKey = currentPageKey
    for section in SectionOrder:
        pagesInSection = [page for page in PageDefinitions if page.Section == section]
        if not pagesInSection:
            continue
        st.sidebar.markdown(f"**{section}**")
        for page in pagesInSection:
            isCurrentPage = currentPageKey == page.Key
            label = f"\u203a {page.Label}" if isCurrentPage else page.Label
            if st.sidebar.button(
                label,
                key=f"SidebarNav_{page.Key}",
                width="stretch",
                type="secondary",
                disabled=disableNavigation,
            ):
                selectedPageKey = page.Key
        st.sidebar.caption("")

    st.sidebar.markdown("---")
    RenderCollectionSummary(connection)
    return selectedPageKey


def RenderCollectionSummary(connection: sqlite3.Connection) -> None:
    collections = ListCollections(connection)
    st.sidebar.subheader("Current collections")

    if not collections:
        st.sidebar.info("No collections yet.")
        return

    for collection in collections:
        st.sidebar.markdown(f"**{collection['name']}**")
        decks = ListDecks(connection, collection["id"])
        if not decks:
            st.sidebar.caption("No decks")
            continue
        for deck in decks:
            cardCount = CountCardsInDeck(connection, deck["id"])
            st.sidebar.caption(f"- {deck['name']} ({cardCount} cards)")


def RenderTopNavigation(currentPageKey: str, disableNavigation: bool) -> Optional[str]:
    selectedPageKey: Optional[str] = None
    currentIndex = PageOrder.index(currentPageKey) if currentPageKey in PageOrder else 0
    previousPage = PageDefinitions[currentIndex - 1] if currentIndex > 0 else None
    nextPage = PageDefinitions[currentIndex + 1] if currentIndex < len(PageDefinitions) - 1 else None

    leftColumn, centerColumn, rightColumn = st.columns([1, 2, 1])
    with leftColumn:
        if previousPage and st.button(
            f"\u2190 {previousPage.Label}",
            key=f"TopNavPrevious_{currentPageKey}",
            disabled=disableNavigation,
            width="stretch",
        ):
            selectedPageKey = previousPage.Key

    with centerColumn:
        currentPage = GetPageDefinition(currentPageKey)
        st.markdown(f"### {currentPage.Label}")
        st.caption(currentPage.Description)

    with rightColumn:
        if nextPage and st.button(
            f"{nextPage.Label} \u2192",
            key=f"TopNavNext_{currentPageKey}",
            disabled=disableNavigation,
            width="stretch",
        ):
            selectedPageKey = nextPage.Key

    return selectedPageKey
