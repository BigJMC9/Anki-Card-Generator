from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class PageDefinition:
    Key: str
    Label: str
    Description: str
    Section: str


PageDefinitions: List[PageDefinition] = [
    PageDefinition("Dictionary", "Dictionary", "Search, inspect, and add Japanese cards from dictionary entries.", "Overview"),
    PageDefinition("Cards", "Cards", "Manage cards, decks, media replacement, scan, and imports/exports in one workspace.", "Overview"),
]

PageOrder = [page.Key for page in PageDefinitions]
PageByKey: Dict[str, PageDefinition] = {page.Key: page for page in PageDefinitions}
SectionOrder = ["Overview"]


def GetDefaultPageKey() -> str:
    return "Dictionary"


def GetPageDefinition(pageKey: str) -> PageDefinition:
    return PageByKey.get(pageKey, PageByKey[GetDefaultPageKey()])


def GetPagesBySection() -> Dict[str, List[PageDefinition]]:
    pagesBySection: Dict[str, List[PageDefinition]] = {section: [] for section in SectionOrder}
    for page in PageDefinitions:
        pagesBySection.setdefault(page.Section, []).append(page)
    return pagesBySection
