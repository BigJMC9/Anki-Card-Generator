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
        "Dictionary",
        "Dictionary",
        "Search jamdict entries and review their details.",
        "Overview",
    ),
    PageDefinition("Cards", "Cards", "Manage global/deck cards, deck structure, and OCR scans.", "Workspace"),
    PageDefinition("AddCards", "Add Cards", "Add dictionary cards or custom cards to global pool/decks.", "Workspace"),
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
SectionOrder = ["Overview", "Workspace", "Maintain"]


def GetDefaultPageKey() -> str:
    return "Dashboard"


def GetPageDefinition(pageKey: str) -> PageDefinition:
    return PageByKey.get(pageKey, PageByKey[GetDefaultPageKey()])


def GetPagesBySection() -> Dict[str, List[PageDefinition]]:
    pagesBySection: Dict[str, List[PageDefinition]] = {section: [] for section in SectionOrder}
    for page in PageDefinitions:
        pagesBySection.setdefault(page.Section, []).append(page)
    return pagesBySection
