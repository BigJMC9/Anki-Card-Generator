import streamlit as st

CurrentPageStateKey = "CurrentPageKey"
BusyActionStateKey = "BusyActionName"


def EnsureUiSessionState(defaultPageKey: str) -> None:
    if CurrentPageStateKey not in st.session_state:
        st.session_state[CurrentPageStateKey] = defaultPageKey
    if BusyActionStateKey not in st.session_state:
        st.session_state[BusyActionStateKey] = ""


def GetCurrentPageKey(defaultPageKey: str) -> str:
    return st.session_state.get(CurrentPageStateKey, defaultPageKey)


def SetCurrentPageKey(pageKey: str) -> None:
    st.session_state[CurrentPageStateKey] = pageKey


def IsBusy() -> bool:
    return bool(st.session_state.get(BusyActionStateKey, ""))


def GetBusyActionName() -> str:
    return st.session_state.get(BusyActionStateKey, "")


def BeginBusyAction(actionName: str) -> bool:
    if IsBusy():
        return False
    st.session_state[BusyActionStateKey] = actionName
    return True


def EndBusyAction() -> None:
    st.session_state[BusyActionStateKey] = ""

