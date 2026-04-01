import base64
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from openai import OpenAI

from AnkiDeckBuilder.AppConfig import AppDir, CardSchemas, ImageOcrPrompt, SystemPrompt

ProgressCallback = Optional[Callable[[int, int, str], None]]
SupportedWordForms = {
    "dictionary": "dictionary/plain form",
    "masu": "polite masu form",
    "past": "past tense",
    "te": "te-form",
    "future": "future expression",
}
PoliteMasuEndings = ("ませんでした", "ました", "ません", "ましょう", "ます")
TrailingPunctuationPattern = re.compile(r"[ \t\r\n。．.!?！？]+$")
AnnotationStartCharacters = ("[", "(", "（", "【", "〈", "《", "＜", "<")
OpenAiDebugLogDefaultPath = AppDir / "openai_api_debug.log"
OpenAiDebugLogMaxCharsDefault = 16000
OpenAiBatchMaxItemsDefault = 40
OpenAiBatchMaxCharsDefault = 6500
OpenAiRateLimitRetriesDefault = 3
OpenAiRateLimitRetrySecondsDefault = 1.5


def GetOpenAiClient() -> OpenAI:
    apiKey = os.environ.get("OPENAI_API_KEY", "").strip()
    if not apiKey:
        raise RuntimeError("OPENAI_API_KEY is not set.")
    return OpenAI(api_key=apiKey)


def ParseBooleanEnvironmentVariable(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalizedValue = value.strip().lower()
    return normalizedValue in {"1", "true", "yes", "on"}


def ParseIntegerEnvironmentVariable(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return max(256, int(value.strip()))
    except (TypeError, ValueError):
        return default


def ParsePositiveIntegerEnvironmentVariable(name: str, default: int, minimum: int = 1) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return max(minimum, int(value.strip()))
    except (TypeError, ValueError):
        return default


def ParseFloatEnvironmentVariable(name: str, default: float, minimum: float = 0.0) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return max(minimum, float(value.strip()))
    except (TypeError, ValueError):
        return default


def IsOpenAiDebugLoggingEnabled() -> bool:
    return ParseBooleanEnvironmentVariable("OPENAI_DEBUG_LOG", default=False)


def GetOpenAiDebugLogPath() -> Path:
    configuredPath = (os.environ.get("OPENAI_DEBUG_LOG_PATH") or "").strip()
    if not configuredPath:
        return OpenAiDebugLogDefaultPath
    return Path(configuredPath)


def GetOpenAiBatchMaxItems() -> int:
    return ParsePositiveIntegerEnvironmentVariable("OPENAI_BATCH_MAX_ITEMS", OpenAiBatchMaxItemsDefault, minimum=1)


def GetOpenAiBatchMaxChars() -> int:
    return ParsePositiveIntegerEnvironmentVariable("OPENAI_BATCH_MAX_CHARS", OpenAiBatchMaxCharsDefault, minimum=512)


def GetOpenAiRateLimitRetryCount() -> int:
    return ParsePositiveIntegerEnvironmentVariable(
        "OPENAI_RATE_LIMIT_RETRIES",
        OpenAiRateLimitRetriesDefault,
        minimum=0,
    )


def GetOpenAiRateLimitRetryBaseSeconds() -> float:
    return ParseFloatEnvironmentVariable(
        "OPENAI_RATE_LIMIT_RETRY_SECONDS",
        OpenAiRateLimitRetrySecondsDefault,
        minimum=0.1,
    )


def RedactDebugPayload(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: RedactDebugPayload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [RedactDebugPayload(item) for item in value]
    if isinstance(value, tuple):
        return [RedactDebugPayload(item) for item in value]
    if isinstance(value, str) and value.startswith("data:"):
        return f"<data-url redacted; length={len(value)}>"
    return value


def ConvertToSerializableDebugValue(value: Any) -> Any:
    if isinstance(value, (dict, list, str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump()
        except Exception:
            pass
    return repr(value)


def TruncateDebugValue(value: Any, maxCharacters: int) -> Any:
    if isinstance(value, str):
        if len(value) <= maxCharacters:
            return value
        hiddenCharacterCount = len(value) - maxCharacters
        return f"{value[:maxCharacters]}... [truncated {hiddenCharacterCount} chars]"
    if isinstance(value, list):
        return [TruncateDebugValue(item, maxCharacters) for item in value]
    if isinstance(value, dict):
        return {key: TruncateDebugValue(item, maxCharacters) for key, item in value.items()}
    return value


def BuildPayloadBatches(payloadItems: List[Dict[str, str]]) -> List[List[Dict[str, str]]]:
    if not payloadItems:
        return []

    maxItemsPerBatch = GetOpenAiBatchMaxItems()
    maxCharsPerBatch = GetOpenAiBatchMaxChars()
    batches: List[List[Dict[str, str]]] = []
    currentBatch: List[Dict[str, str]] = []
    currentBatchChars = 2  # [] wrapper overhead

    for item in payloadItems:
        serializedItem = json.dumps(item, ensure_ascii=False)
        itemChars = len(serializedItem)
        itemOverhead = 1 if currentBatch else 0
        projectedChars = currentBatchChars + itemOverhead + itemChars

        shouldFlush = bool(currentBatch) and (
            len(currentBatch) >= maxItemsPerBatch or projectedChars > maxCharsPerBatch
        )
        if shouldFlush:
            batches.append(currentBatch)
            currentBatch = []
            currentBatchChars = 2
            projectedChars = currentBatchChars + itemChars

        currentBatch.append(item)
        currentBatchChars = projectedChars

    if currentBatch:
        batches.append(currentBatch)

    return batches


def LooksLikeOpenAiRateLimitError(exc: Exception) -> bool:
    statusCode = getattr(exc, "status_code", None)
    if statusCode == 429:
        return True

    errorText = str(exc).lower()
    return "rate_limit_exceeded" in errorText or "tokens per min" in errorText


def WriteOpenAiDebugLog(eventType: str, payload: Dict[str, Any]) -> None:
    if not IsOpenAiDebugLoggingEnabled():
        return

    logPath = GetOpenAiDebugLogPath()
    maxCharacters = ParseIntegerEnvironmentVariable("OPENAI_DEBUG_LOG_MAX_CHARS", OpenAiDebugLogMaxCharsDefault)
    logEntry = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "event": eventType,
        **payload,
    }
    serializableEntry = ConvertToSerializableDebugValue(RedactDebugPayload(logEntry))
    truncatedEntry = TruncateDebugValue(serializableEntry, maxCharacters)

    try:
        logPath.parent.mkdir(parents=True, exist_ok=True)
        with open(logPath, "a", encoding="utf-8") as logFile:
            logFile.write(json.dumps(truncatedEntry, ensure_ascii=False, default=str))
            logFile.write("\n")
    except Exception:
        # Debug logging should never break app behavior.
        return


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
    WriteOpenAiDebugLog(
        "openai_request",
        {
            "model": model,
            "input": RedactDebugPayload(ConvertToSerializableDebugValue(inputPayload)),
        },
    )

    maxRetries = GetOpenAiRateLimitRetryCount()
    baseRetrySeconds = GetOpenAiRateLimitRetryBaseSeconds()
    attempt = 0
    while True:
        try:
            response = client.responses.create(model=model, input=inputPayload)
            break
        except Exception as exc:
            isRetryable = LooksLikeOpenAiRateLimitError(exc) and attempt < maxRetries
            if isRetryable:
                sleepSeconds = baseRetrySeconds * (2**attempt)
                WriteOpenAiDebugLog(
                    "openai_retry",
                    {
                        "model": model,
                        "attempt": attempt + 1,
                        "max_retries": maxRetries,
                        "sleep_seconds": sleepSeconds,
                        "error": str(exc),
                    },
                )
                time.sleep(sleepSeconds)
                attempt += 1
                continue

            WriteOpenAiDebugLog(
                "openai_error",
                {
                    "model": model,
                    "error": str(exc),
                },
            )
            raise

    WriteOpenAiDebugLog(
        "openai_response",
        {
            "model": model,
            "response": RedactDebugPayload(ConvertToSerializableDebugValue(response)),
        },
    )

    extractedText = ExtractTextFromResponse(response)
    WriteOpenAiDebugLog(
        "openai_output_text",
        {
            "model": model,
            "output_text": extractedText,
        },
    )
    return extractedText


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


def GetCardTextField(card: Any, fieldName: str) -> str:
    value: Any = ""
    if isinstance(card, dict):
        value = card.get(fieldName, "")
    else:
        try:
            value = card[fieldName]
        except (KeyError, IndexError, TypeError):
            value = ""

    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def SplitLeadingTextAndSuffix(value: str) -> Tuple[str, str]:
    text = (value or "").strip()
    if not text:
        return "", ""

    markerIndexes = [text.find(marker) for marker in AnnotationStartCharacters if text.find(marker) >= 0]
    if not markerIndexes:
        return text, ""

    firstMarkerIndex = min(markerIndexes)
    if firstMarkerIndex <= 0:
        return text, ""
    return text[:firstMarkerIndex].rstrip(), text[firstMarkerIndex:]


def ExtractLeadingConvertibleText(value: str) -> str:
    leadingText, _ = SplitLeadingTextAndSuffix(value)
    if leadingText:
        return leadingText
    return (value or "").strip()


def MergeConvertedLeadingText(convertedLeadingText: str, originalValue: str) -> str:
    convertedText = (convertedLeadingText or "").strip()
    originalText = (originalValue or "").strip()
    if not convertedText:
        return originalText

    _, suffix = SplitLeadingTextAndSuffix(originalText)
    if suffix:
        return f"{convertedText}{suffix}"
    return convertedText


def NormalizeForEndingCheck(value: str) -> str:
    return TrailingPunctuationPattern.sub("", (value or "").strip())


def LooksLikePoliteMasuForm(value: str) -> bool:
    leadingText, _ = SplitLeadingTextAndSuffix(value)
    normalizedValue = NormalizeForEndingCheck(leadingText or value)
    return any(normalizedValue.endswith(ending) for ending in PoliteMasuEndings)


def BuildWordConversionSystemPrompt(targetForm: str, strictDictionary: bool = False) -> str:
    promptParts = [
        "You transform Japanese vocabulary into requested forms.",
        'Return only valid JSON in schema {"items":[{"id":"","kanji":"","kana":""}]}.',
        "Return one item for every input id. Keep id unchanged.",
        "Never return blank kanji or kana fields; keep the original field when unknown.",
    ]

    if targetForm == "dictionary":
        promptParts.append(
            "For dictionary/plain form, output dictionary form for verbs and adjectives in kanji and kana fields whenever possible."
        )
        promptParts.append(
            "Do not end verbs with ます, ません, ました, ませんでした, ましょう or any other form, we just want the plain dictionary form."
        )
        promptParts.append(
            "If text includes usage notes in brackets/parentheses, convert only the headword before the note."
        )
        promptParts.append(
            "Keep the bracket/parenthesis note unchanged in place after conversion."
        )
        promptParts.append(
            "Examples: 食べます->食べる, 行きました->行く, 見ません->見る, "
            "はいります[おふろに〜]->はいる[おふろに〜], しました->する, 来ました->来る."
        )
        if strictDictionary:
            promptParts.append(
                "This is a retry because previous output still had polite endings; correct them now."
            )
    else:
        promptParts.append("If a field cannot be transformed, keep the original value.")

    return " ".join(promptParts)


def RequestWordFormConversions(
    client: OpenAI,
    model: str,
    targetForm: str,
    targetFormLabel: str,
    payloadItems: List[Dict[str, str]],
    strictDictionary: bool = False,
) -> List[Dict[str, Any]]:
    raw = RequestResponseText(
        client,
        model,
        [
            {
                "role": "system",
                "content": BuildWordConversionSystemPrompt(targetForm, strictDictionary),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "target_form_key": targetForm,
                        "target_form": targetFormLabel,
                        "items": payloadItems,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    )
    parsed = ParseJsonResponse(raw)
    items = parsed.get("items", [])
    if isinstance(items, list):
        return items
    return []


def BuildConversionMap(
    responseItems: List[Dict[str, Any]],
    originalById: Dict[str, Dict[str, str]],
) -> Dict[str, Dict[str, str]]:
    convertedById: Dict[str, Dict[str, str]] = {}
    for item in responseItems:
        if not isinstance(item, dict):
            continue
        itemId = (item.get("id") or "").strip()
        if not itemId or itemId not in originalById:
            continue

        original = originalById[itemId]
        kanji = (item.get("kanji") or "").strip() or original["kanji"]
        kana = (item.get("kana") or "").strip() or original["kana"]
        convertedById[itemId] = {"id": itemId, "kanji": kanji, "kana": kana}

    return convertedById


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
    cards: List[Any],
    targetForm: str,
    progressCallback: ProgressCallback = None,
) -> Tuple[List[Dict[str, str]], List[str]]:
    conversions: List[Dict[str, str]] = []
    errors: List[str] = []
    if not cards:
        return conversions, errors

    targetFormLabel = SupportedWordForms.get(targetForm, SupportedWordForms["dictionary"])
    payloadItems = []
    for card in cards:
        itemId = GetCardTextField(card, "id")
        if not itemId:
            continue
        payloadItems.append(
            {
                "id": itemId,
                "kanji": GetCardTextField(card, "kanji"),
                "kana": GetCardTextField(card, "kana"),
            }
        )

    if not payloadItems:
        return conversions, errors

    originalById = {item["id"]: item for item in payloadItems}

    if progressCallback:
        progressCallback(0, 1, f"Converting selected cards to {targetFormLabel}...")

    try:
        convertedById: Dict[str, Dict[str, str]] = {}
        payloadBatches = BuildPayloadBatches(payloadItems)
        totalPayloadBatches = max(len(payloadBatches), 1)
        for batchIndex, payloadBatch in enumerate(payloadBatches, start=1):
            if progressCallback:
                progressCallback(
                    batchIndex - 1,
                    totalPayloadBatches,
                    f"Converting selected cards batch {batchIndex}/{totalPayloadBatches}...",
                )
            batchOriginalById = {item["id"]: item for item in payloadBatch}
            try:
                initialResponseItems = RequestWordFormConversions(
                    client,
                    model,
                    targetForm,
                    targetFormLabel,
                    payloadBatch,
                    strictDictionary=False,
                )
                convertedById.update(BuildConversionMap(initialResponseItems, batchOriginalById))
            except Exception as exc:
                errors.append(f"Batch {batchIndex}/{totalPayloadBatches}: {exc}")

            for item in payloadBatch:
                if item["id"] not in convertedById:
                    convertedById[item["id"]] = {
                        "id": item["id"],
                        "kanji": item["kanji"],
                        "kana": item["kana"],
                    }

        if targetForm == "dictionary":
            unresolvedIds = [
                itemId
                for itemId, convertedItem in convertedById.items()
                if LooksLikePoliteMasuForm(convertedItem["kanji"]) or LooksLikePoliteMasuForm(convertedItem["kana"])
            ]
            if unresolvedIds:
                retryPayload = [originalById[itemId] for itemId in unresolvedIds if itemId in originalById]
                retryBatches = BuildPayloadBatches(retryPayload)
                totalRetryBatches = max(len(retryBatches), 1)
                for retryIndex, retryBatch in enumerate(retryBatches, start=1):
                    if progressCallback:
                        progressCallback(
                            retryIndex - 1,
                            totalRetryBatches,
                            f"Retrying dictionary batch {retryIndex}/{totalRetryBatches} still in polite form...",
                        )
                    retryBatchById = {item["id"]: item for item in retryBatch}
                    try:
                        retryResponseItems = RequestWordFormConversions(
                            client,
                            model,
                            targetForm,
                            targetFormLabel,
                            retryBatch,
                            strictDictionary=True,
                        )
                        convertedById.update(BuildConversionMap(retryResponseItems, retryBatchById))
                    except Exception as exc:
                        errors.append(f"Dictionary retry batch {retryIndex}/{totalRetryBatches}: {exc}")

            unresolvedAfterRetry = [
                itemId
                for itemId in originalById
                if itemId in convertedById
                and (
                    LooksLikePoliteMasuForm(convertedById[itemId]["kanji"])
                    or LooksLikePoliteMasuForm(convertedById[itemId]["kana"])
                )
            ]

            annotationRetryIds = [
                itemId
                for itemId in unresolvedAfterRetry
                if SplitLeadingTextAndSuffix(originalById[itemId]["kanji"])[1]
                or SplitLeadingTextAndSuffix(originalById[itemId]["kana"])[1]
            ]
            if annotationRetryIds:
                annotationPayload: List[Dict[str, str]] = []
                for itemId in annotationRetryIds:
                    originalItem = originalById[itemId]
                    annotationItem = {
                        "id": itemId,
                        "kanji": ExtractLeadingConvertibleText(originalItem["kanji"]),
                        "kana": ExtractLeadingConvertibleText(originalItem["kana"]),
                    }
                    annotationPayload.append(annotationItem)

                annotationBatches = BuildPayloadBatches(annotationPayload)
                totalAnnotationBatches = max(len(annotationBatches), 1)
                for annotationIndex, annotationBatch in enumerate(annotationBatches, start=1):
                    if progressCallback:
                        progressCallback(
                            annotationIndex - 1,
                            totalAnnotationBatches,
                            f"Retrying annotated dictionary batch {annotationIndex}/{totalAnnotationBatches}...",
                        )

                    annotationOriginalById = {item["id"]: item for item in annotationBatch}
                    try:
                        annotationResponseItems = RequestWordFormConversions(
                            client,
                            model,
                            targetForm,
                            targetFormLabel,
                            annotationBatch,
                            strictDictionary=True,
                        )
                        annotationById = BuildConversionMap(annotationResponseItems, annotationOriginalById)
                        for itemId, annotationConverted in annotationById.items():
                            originalItem = originalById[itemId]
                            existingItem = convertedById.get(itemId, originalItem)
                            mergedKanji = MergeConvertedLeadingText(annotationConverted["kanji"], originalItem["kanji"])
                            mergedKana = MergeConvertedLeadingText(annotationConverted["kana"], originalItem["kana"])
                            convertedById[itemId] = {
                                "id": itemId,
                                "kanji": mergedKanji or existingItem["kanji"],
                                "kana": mergedKana or existingItem["kana"],
                            }
                    except Exception as exc:
                        errors.append(
                            f"Annotated dictionary retry batch {annotationIndex}/{totalAnnotationBatches}: {exc}"
                        )

            unresolvedFinalIds = [
                itemId
                for itemId in originalById
                if itemId in convertedById
                and (
                    LooksLikePoliteMasuForm(convertedById[itemId]["kanji"])
                    or LooksLikePoliteMasuForm(convertedById[itemId]["kana"])
                )
            ]
            if unresolvedFinalIds:
                errors.append(
                    f"{len(unresolvedFinalIds)} item(s) still look like polite masu form after retries."
                )

        for item in payloadItems:
            conversion = convertedById.get(item["id"])
            if conversion:
                conversions.append(conversion)
    except Exception as exc:
        errors.append(str(exc))
    finally:
        if progressCallback:
            progressCallback(1, 1, f"Converted selected cards to {targetFormLabel}.")

    return conversions, errors


def GenerateEnglishTranslations(
    client: OpenAI,
    model: str,
    cards: List[Any],
    progressCallback: ProgressCallback = None,
) -> Tuple[List[Dict[str, str]], List[str]]:
    translations: List[Dict[str, str]] = []
    errors: List[str] = []
    if not cards:
        return translations, errors

    payloadItems = []
    for card in cards:
        itemId = GetCardTextField(card, "id")
        if not itemId:
            continue
        payloadItems.append(
            {
                "id": itemId,
                "kanji": GetCardTextField(card, "kanji"),
                "kana": GetCardTextField(card, "kana"),
                "source_text": GetCardTextField(card, "source_text"),
                "notes": GetCardTextField(card, "notes"),
            }
        )

    if not payloadItems:
        return translations, errors

    if progressCallback:
        progressCallback(0, 1, "Generating missing English translations...")

    try:
        translationById: Dict[str, str] = {}
        payloadBatches = BuildPayloadBatches(payloadItems)
        totalPayloadBatches = max(len(payloadBatches), 1)
        for batchIndex, payloadBatch in enumerate(payloadBatches, start=1):
            if progressCallback:
                progressCallback(
                    batchIndex - 1,
                    totalPayloadBatches,
                    f"Generating missing English translations batch {batchIndex}/{totalPayloadBatches}...",
                )
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
                        {"role": "user", "content": json.dumps({"items": payloadBatch}, ensure_ascii=False)},
                    ],
                )
                parsed = ParseJsonResponse(raw)
                for item in parsed.get("items", []):
                    itemId = (item.get("id") or "").strip()
                    english = (item.get("english") or "").strip()
                    if itemId and english:
                        translationById[itemId] = english
            except Exception as exc:
                errors.append(f"Batch {batchIndex}/{totalPayloadBatches}: {exc}")

        for item in payloadItems:
            itemId = item["id"]
            english = translationById.get(itemId, "")
            if english:
                translations.append({"id": itemId, "english": english})
    except Exception as exc:
        errors.append(str(exc))
    finally:
        if progressCallback:
            progressCallback(1, 1, "Generated missing English translations.")

    return translations, errors


def BuildVerificationSystemPrompt(targetFormLabel: str, schemaLabel: str, schemaKey: str) -> str:
    promptParts = [
        "You verify and correct Japanese flashcard entries.",
        'Return only valid JSON in schema {"items":[{"id":"","kanji":"","kana":"","english":""}]}.',
        "Return exactly one output item for each input id and keep id unchanged.",
        "Ensure kanji and kana represent the same word/expression.",
        "Ensure kana is full reading in hiragana/katakana.",
        "Ensure english is concise and accurate.",
        f"Ensure Japanese fields match this target form: {targetFormLabel}.",
        f"Card format label: {schemaLabel}.",
    ]

    if schemaKey == "kanji_okurigana_front_reading_english_back":
        promptParts.append(
            "For kanji field, prefer natural kanji spelling with okurigana when applicable."
        )

    promptParts.append("Do not modify notes.")
    promptParts.append("If uncertain, keep the original value.")
    return " ".join(promptParts)


def VerifyCardsAgainstSelection(
    client: OpenAI,
    model: str,
    cards: List[Any],
    targetForm: str,
    schemaKey: str,
    progressCallback: ProgressCallback = None,
) -> Tuple[List[Dict[str, str]], List[str]]:
    verifiedCards: List[Dict[str, str]] = []
    errors: List[str] = []
    if not cards:
        return verifiedCards, errors

    targetFormLabel = SupportedWordForms.get(targetForm, SupportedWordForms["dictionary"])
    schemaLabel = CardSchemas.get(schemaKey, {}).get("Label", schemaKey)

    payloadItems: List[Dict[str, str]] = []
    for card in cards:
        itemId = GetCardTextField(card, "id")
        if not itemId:
            continue
        payloadItems.append(
            {
                "id": itemId,
                "kanji": GetCardTextField(card, "kanji"),
                "kana": GetCardTextField(card, "kana"),
                "english": GetCardTextField(card, "english"),
                "notes": GetCardTextField(card, "notes"),
                "source_text": GetCardTextField(card, "source_text"),
            }
        )

    if not payloadItems:
        return verifiedCards, errors

    originalById = {item["id"]: item for item in payloadItems}
    verifiedById: Dict[str, Dict[str, str]] = {}

    payloadBatches = BuildPayloadBatches(payloadItems)
    totalPayloadBatches = max(len(payloadBatches), 1)

    for batchIndex, payloadBatch in enumerate(payloadBatches, start=1):
        if progressCallback:
            progressCallback(
                batchIndex - 1,
                totalPayloadBatches,
                f"Verifying selected cards batch {batchIndex}/{totalPayloadBatches}...",
            )

        try:
            raw = RequestResponseText(
                client,
                model,
                [
                    {
                        "role": "system",
                        "content": BuildVerificationSystemPrompt(targetFormLabel, schemaLabel, schemaKey),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "target_form_key": targetForm,
                                "target_form": targetFormLabel,
                                "schema_key": schemaKey,
                                "schema_label": schemaLabel,
                                "items": payloadBatch,
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
            )
            parsed = ParseJsonResponse(raw)
            for item in parsed.get("items", []):
                if not isinstance(item, dict):
                    continue
                itemId = (item.get("id") or "").strip()
                if not itemId or itemId not in originalById:
                    continue
                original = originalById[itemId]
                verifiedById[itemId] = {
                    "id": itemId,
                    "kanji": (item.get("kanji") or "").strip() or original["kanji"],
                    "kana": (item.get("kana") or "").strip() or original["kana"],
                    "english": (item.get("english") or "").strip() or original["english"],
                    "notes": original["notes"],
                }
        except Exception as exc:
            errors.append(f"Batch {batchIndex}/{totalPayloadBatches}: {exc}")

    for item in payloadItems:
        itemId = item["id"]
        verifiedItem = verifiedById.get(itemId)
        if verifiedItem:
            verifiedCards.append(verifiedItem)
        else:
            verifiedCards.append(
                {
                    "id": itemId,
                    "kanji": item["kanji"],
                    "kana": item["kana"],
                    "english": item["english"],
                    "notes": item["notes"],
                }
            )

    if progressCallback:
        progressCallback(1, 1, "Verification complete.")

    return verifiedCards, errors
