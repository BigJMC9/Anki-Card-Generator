from dataclasses import dataclass
from typing import Dict, List


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


def GetPagesBySection() -> Dict[str, List[PageDefinition]]:
    pagesBySection: Dict[str, List[PageDefinition]] = {section: [] for section in SectionOrder}
    for page in PageDefinitions:
        pagesBySection.setdefault(page.Section, []).append(page)
    return pagesBySection
