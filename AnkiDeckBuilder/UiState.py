from dataclasses import dataclass


@dataclass
class BusyState:
    ActionName: str = ""

    @property
    def IsBusy(self) -> bool:
        return bool(self.ActionName.strip())


def BeginBusyAction(state: BusyState, actionName: str) -> bool:
    if state.IsBusy:
        return False
    state.ActionName = (actionName or "").strip()
    return bool(state.ActionName)


def EndBusyAction(state: BusyState) -> None:
    state.ActionName = ""
