import uuid
from pathlib import Path

from AnkiDeckBuilder.AppConfig import AppDir, CollectionsDir, ExportDir, MediaDir, TempDir


def EnsureWorkspaceDirectories() -> None:
    for path in [AppDir, CollectionsDir, MediaDir, TempDir, ExportDir]:
        path.mkdir(parents=True, exist_ok=True)


def CopyUploadedMedia(uploadedFile, deckId: str) -> str:
    deckMediaDirectory = MediaDir / deckId
    deckMediaDirectory.mkdir(parents=True, exist_ok=True)
    suffix = Path(uploadedFile.name).suffix.lower()
    safeName = f"{uuid.uuid4().hex}{suffix}"
    targetPath = deckMediaDirectory / safeName
    with open(targetPath, "wb") as outputFile:
        outputFile.write(uploadedFile.getbuffer())
    return str(targetPath)

