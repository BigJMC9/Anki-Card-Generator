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

    if IsBusy():
        st.warning(f"Processing: {GetBusyActionName()}")

    pageDefinition = GetPageDefinition(currentPageKey)
    st.markdown(f"## {pageDefinition.Label}")
    st.caption(pageDefinition.Description)

    RenderPage(connection, currentPageKey)


if __name__ == "__main__":
    load_dotenv()
    main()
