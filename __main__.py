from dotenv import load_dotenv
import streamlit as st

from AnkiDeckBuilder.AppConfig import AppTitle
from AnkiDeckBuilder.DatabaseService import OpenDatabaseConnection
from AnkiDeckBuilder.Navigation import (
    GetDefaultPageKey,
    GetPageDefinition,
    RenderSidebarNavigation,
    RenderTopNavigation,
)
from AnkiDeckBuilder.Pages import RenderPage
from AnkiDeckBuilder.UiState import (
    EnsureUiSessionState,
    GetBusyActionName,
    GetCurrentPageKey,
    IsBusy,
    SetCurrentPageKey,
)
from AnkiDeckBuilder.UiTheme import ApplyGlobalTheme
from AnkiDeckBuilder.WorkspaceService import EnsureWorkspaceDirectories


def main() -> None:
    st.set_page_config(page_title=AppTitle, layout="wide")
    ApplyGlobalTheme()

    EnsureWorkspaceDirectories()
    connection = OpenDatabaseConnection()

    defaultPageKey = GetDefaultPageKey()
    EnsureUiSessionState(defaultPageKey)

    currentPageKey = GetCurrentPageKey(defaultPageKey)
    selectedPageFromSidebar = RenderSidebarNavigation(connection, currentPageKey, IsBusy())
    if selectedPageFromSidebar != currentPageKey:
        SetCurrentPageKey(selectedPageFromSidebar)
        st.rerun()

    currentPageKey = GetCurrentPageKey(defaultPageKey)

    st.title(AppTitle)
    st.caption("Build Japanese decks with jamdict-backed cards, image scanning, review, and Anki export.")

    if IsBusy():
        st.warning(f"Processing: {GetBusyActionName()}")

    selectedPageFromTopNav = RenderTopNavigation(currentPageKey, IsBusy())
    if selectedPageFromTopNav:
        SetCurrentPageKey(selectedPageFromTopNav)
        st.rerun()

    pageDefinition = GetPageDefinition(currentPageKey)
    st.markdown("---")
    st.markdown(f"## {pageDefinition.Label}")
    st.caption(pageDefinition.Description)

    RenderPage(connection, currentPageKey)


if __name__ == "__main__":
    load_dotenv()
    main()
