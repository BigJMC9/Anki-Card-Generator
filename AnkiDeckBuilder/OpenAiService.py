import base64
import json
import os
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from openai import OpenAI

from AnkiDeckBuilder.AppConfig import CardSchemas, ImageOcrPrompt, SystemPrompt

ProgressCallback = Optional[Callable[[int, int, str], None]]
SupportedWordForms = {
    "dictionary": "dictionary/plain form",
    "masu": "polite masu form",
    "past": "past tense",
    "te": "te-form",
    "future": "future expression",
}


def GetOpenAiClient() -> OpenAI:
    apiKey = os.environ.get("OPENAI_API_KEY", "").strip()
    if not apiKey:
        raise RuntimeError("OPENAI_API_KEY is not set.")
    return OpenAI(api_key=apiKey)


def SplitTextIntoChunks(text: str, maxCharacters: int = 3000) -> List[str]:
    normalizedText = text.strip()
    if not normalizedText:
        return []

    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", normalizedText) if paragraph.strip()]
    chunks: List[str] = []
    currentChunk = ""
    for paragraph in paragraphs:
        if len(currentChunk) + len(paragraph) + 2 <= maxCharacters:
            currentChunk = f"{currentChunk}\n\n{paragraph}".strip()
        else:
            if currentChunk:
                chunks.append(currentChunk)
            currentChunk = paragraph

    if currentChunk:
        chunks.append(currentChunk)
    return chunks


def RequestResponseText(client: OpenAI, model: str, inputPayload: Any) -> str:
    response = client.responses.create(model=model, input=inputPayload)
    return ExtractTextFromResponse(response)


def ExtractTextFromResponse(response: Any) -> str:
    directText = (getattr(response, "output_text", "") or "").strip()
    if directText:
        return directText

    fragments: List[str] = []
    outputItems = getattr(response, "output", None)
    if outputItems is None and isinstance(response, dict):
        outputItems = response.get("output")

    if not outputItems:
        return ""

    for outputItem in outputItems:
        contentItems = _GetContentItems(outputItem)
        for contentItem in contentItems:
            textValue = _GetTextValue(contentItem)
            if textValue:
                fragments.append(textValue)

    return "\n".join(fragment.strip() for fragment in fragments if fragment).strip()


def _GetContentItems(outputItem: Any) -> List[Any]:
    if isinstance(outputItem, dict):
        return outputItem.get("content") or []
    return getattr(outputItem, "content", []) or []


def _GetTextValue(contentItem: Any) -> str:
    if isinstance(contentItem, dict):
        textCandidate = contentItem.get("text")
        if isinstance(textCandidate, str):
            return textCandidate
        if isinstance(textCandidate, dict):
            nestedValue = textCandidate.get("value")
            if isinstance(nestedValue, str):
                return nestedValue
        return ""

    textCandidate = getattr(contentItem, "text", None)
    if isinstance(textCandidate, str):
        return textCandidate

    nestedValue = getattr(textCandidate, "value", None)
    if isinstance(nestedValue, str):
        return nestedValue

    return ""


def ParseJsonResponse(rawText: str) -> Dict[str, Any]:
    cleanedText = (rawText or "").strip()
    if not cleanedText:
        raise ValueError("The AI response was empty. Please retry.")

    cleanedText = StripCodeFence(cleanedText)

    try:
        return json.loads(cleanedText)
    except json.JSONDecodeError:
        embeddedJson = ExtractEmbeddedJson(cleanedText)
        if not embeddedJson:
            snippet = cleanedText.replace("\n", " ")[:220]
            raise ValueError(f"Could not parse AI JSON response. Preview: {snippet}") from None
        try:
            return json.loads(embeddedJson)
        except json.JSONDecodeError:
            snippet = embeddedJson.replace("\n", " ")[:220]
            raise ValueError(f"Could not parse AI JSON response. Preview: {snippet}") from None


def StripCodeFence(text: str) -> str:
    codeFencePattern = re.compile(r"^```(?:json)?\s*([\s\S]*?)\s*```$", re.IGNORECASE)
    match = codeFencePattern.match(text)
    if match:
        return match.group(1).strip()
    return text


def ExtractEmbeddedJson(text: str) -> str:
    objectMatch = re.search(r"\{[\s\S]*\}", text)
    if objectMatch:
        return objectMatch.group(0)

    arrayMatch = re.search(r"\[[\s\S]*\]", text)
    if arrayMatch:
        return arrayMatch.group(0)

    return ""


def FileToDataUrl(uploadedFile) -> str:
    mimeType = uploadedFile.type or "application/octet-stream"
    payload = base64.b64encode(uploadedFile.getbuffer()).decode("ascii")
    return f"data:{mimeType};base64,{payload}"


def GenerateCardsFromText(
    client: OpenAI,
    model: str,
    text: str,
    schemaKey: str,
    extraTags: List[str],
    progressCallback: ProgressCallback = None,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    chunks = SplitTextIntoChunks(text)
    results: List[Dict[str, Any]] = []
    errors: List[str] = []

    if not chunks:
        return results, errors

    for chunkIndex, chunk in enumerate(chunks, start=1):
        if progressCallback:
            progressCallback(chunkIndex - 1, len(chunks), f"Requesting chunk {chunkIndex}/{len(chunks)}")

        try:
            userPrompt = {
                "schema_key": schemaKey,
                "schema_description": CardSchemas[schemaKey]["Label"],
                "text": chunk,
            }
            raw = RequestResponseText(
                client,
                model,
                [
                    {"role": "system", "content": SystemPrompt},
                    {"role": "user", "content": json.dumps(userPrompt, ensure_ascii=False)},
                ],
            )
            parsed = ParseJsonResponse(raw)
            for card in parsed.get("cards", []):
                card["schema_key"] = schemaKey
                card["media_type"] = "none"
                card["media_files"] = []
                card["tags"] = sorted(set((card.get("tags") or []) + extraTags))
                if any((card.get(fieldName) or "").strip() for fieldName in ["kanji", "kana", "english"]):
                    results.append(card)
        except Exception as exc:
            errors.append(f"Chunk {chunkIndex}: {exc}")
        finally:
            if progressCallback:
                progressCallback(chunkIndex, len(chunks), f"Processed chunk {chunkIndex}/{len(chunks)}")

    return results, errors


def ExtractCardsFromImages(
    client: OpenAI,
    model: str,
    uploads,
    schemaKey: str,
    extraTags: List[str],
    wordForm: str = "dictionary",
    progressCallback: ProgressCallback = None,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    results: List[Dict[str, Any]] = []
    errors: List[str] = []
    totalUploads = len(uploads)

    targetFormLabel = SupportedWordForms.get(wordForm, SupportedWordForms["dictionary"])

    for uploadIndex, upload in enumerate(uploads, start=1):
        if progressCallback:
            progressCallback(uploadIndex - 1, totalUploads, f"Scanning {upload.name} ({uploadIndex}/{totalUploads})")

        try:
            raw = RequestResponseText(
                client,
                model,
                [
                    {"role": "system", "content": ImageOcrPrompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": "Extract Japanese text and build vocabulary candidates."},
                            {
                                "type": "input_text",
                                "text": (
                                    "When possible, normalize verbs/adjectives in kanji and kana to "
                                    f"{targetFormLabel}."
                                ),
                            },
                            {"type": "input_image", "image_url": FileToDataUrl(upload)},
                        ],
                    },
                ],
            )
            parsed = ParseJsonResponse(raw)
            for item in parsed.get("items", []):
                card = {
                    "kanji": (item.get("kanji") or item.get("visible_text") or "").strip(),
                    "kana": (item.get("kana") or "").strip(),
                    "english": (item.get("english") or "").strip(),
                    "notes": f"Extracted from image: {upload.name}",
                    "source_text": (item.get("visible_text") or "").strip(),
                    "schema_key": schemaKey,
                    "media_type": "none",
                    "media_files": [],
                    "tags": sorted(set(extraTags + ["image_ocr"])),
                }
                if any(card[fieldName] for fieldName in ["kanji", "kana", "english"]):
                    results.append(card)
        except Exception as exc:
            errors.append(f"{upload.name}: {exc}")
        finally:
            if progressCallback:
                progressCallback(uploadIndex, totalUploads, f"Scanned {upload.name} ({uploadIndex}/{totalUploads})")

    return results, errors


def ConvertJapaneseWords(
    client: OpenAI,
    model: str,
    cards: List[Dict[str, Any]],
    targetForm: str,
    progressCallback: ProgressCallback = None,
) -> Tuple[List[Dict[str, str]], List[str]]:
    conversions: List[Dict[str, str]] = []
    errors: List[str] = []
    if not cards:
        return conversions, errors

    targetFormLabel = SupportedWordForms.get(targetForm, SupportedWordForms["dictionary"])
    payloadItems = [
        {
            "id": card["id"],
            "kanji": card.get("kanji", ""),
            "kana": card.get("kana", ""),
        }
        for card in cards
    ]

    if progressCallback:
        progressCallback(0, 1, f"Converting selected cards to {targetFormLabel}...")

    try:
        raw = RequestResponseText(
            client,
            model,
            [
                {
                    "role": "system",
                    "content": (
                        "You transform Japanese words into requested forms. Return only valid JSON in schema "
                        '{"items":[{"id":"","kanji":"","kana":""}]}. Keep id unchanged. '
                        "If a field cannot be transformed, keep the original value."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "target_form": targetFormLabel,
                            "items": payloadItems,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        )
        parsed = ParseJsonResponse(raw)
        for item in parsed.get("items", []):
            itemId = (item.get("id") or "").strip()
            if not itemId:
                continue
            conversions.append(
                {
                    "id": itemId,
                    "kanji": (item.get("kanji") or "").strip(),
                    "kana": (item.get("kana") or "").strip(),
                }
            )
    except Exception as exc:
        errors.append(str(exc))
    finally:
        if progressCallback:
            progressCallback(1, 1, f"Converted selected cards to {targetFormLabel}.")

    return conversions, errors


def GenerateEnglishTranslations(
    client: OpenAI,
    model: str,
    cards: List[Dict[str, Any]],
    progressCallback: ProgressCallback = None,
) -> Tuple[List[Dict[str, str]], List[str]]:
    translations: List[Dict[str, str]] = []
    errors: List[str] = []
    if not cards:
        return translations, errors

    payloadItems = [
        {
            "id": card["id"],
            "kanji": card.get("kanji", ""),
            "kana": card.get("kana", ""),
            "source_text": card.get("source_text", ""),
            "notes": card.get("notes", ""),
        }
        for card in cards
    ]

    if progressCallback:
        progressCallback(0, 1, "Generating missing English translations...")

    try:
        raw = RequestResponseText(
            client,
            model,
            [
                {
                    "role": "system",
                    "content": (
                        "Generate concise English translations for Japanese vocabulary cards. "
                        'Return only valid JSON in schema {"items":[{"id":"","english":""}]}. '
                        "Keep id unchanged and keep english short."
                    ),
                },
                {"role": "user", "content": json.dumps({"items": payloadItems}, ensure_ascii=False)},
            ],
        )
        parsed = ParseJsonResponse(raw)
        for item in parsed.get("items", []):
            itemId = (item.get("id") or "").strip()
            english = (item.get("english") or "").strip()
            if itemId and english:
                translations.append({"id": itemId, "english": english})
    except Exception as exc:
        errors.append(str(exc))
    finally:
        if progressCallback:
            progressCallback(1, 1, "Generated missing English translations.")

    return translations, errors
