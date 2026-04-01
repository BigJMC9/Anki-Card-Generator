import base64
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from openai import OpenAI

from AnkiDeckBuilder.AppConfig import AppDir, ImageOcrPrompt

ProgressCallback = Optional[Callable[[int, int, str], None]]
OpenAiDebugLogDefaultPath = AppDir / "openai_api_debug.log"
OpenAiDebugLogMaxCharsDefault = 16000
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


def ParseIntegerEnvironmentVariable(name: str, default: int, minimum: int = 0) -> int:
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


def GetOpenAiRateLimitRetryCount() -> int:
    return ParseIntegerEnvironmentVariable(
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
    maxCharacters = ParseIntegerEnvironmentVariable(
        "OPENAI_DEBUG_LOG_MAX_CHARS",
        OpenAiDebugLogMaxCharsDefault,
        minimum=256,
    )
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
        return


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


def FileToDataUrl(uploadedFile: Any) -> str:
    mimeType = uploadedFile.type or "application/octet-stream"
    payload = base64.b64encode(uploadedFile.getbuffer()).decode("ascii")
    return f"data:{mimeType};base64,{payload}"


def ExtractCardsFromImages(
    client: OpenAI,
    model: str,
    uploads: List[Any],
    progressCallback: ProgressCallback = None,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    candidates: List[Dict[str, Any]] = []
    errors: List[str] = []
    totalUploads = len(uploads)

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
                            {
                                "type": "input_text",
                                "text": (
                                    "Extract visible Japanese vocabulary candidates for dictionary lookup. "
                                    "Prioritize canonical kanji+okurigana spellings when visible. "
                                    "If only kana is visible, keep kana."
                                ),
                            },
                            {
                                "type": "input_text",
                                "text": (
                                    "Return each item with visible_text plus best-effort kanji and kana. "
                                    "Do not invent words that are not clearly visible."
                                ),
                            },
                            {"type": "input_image", "image_url": FileToDataUrl(upload)},
                        ],
                    },
                ],
            )
            parsed = ParseJsonResponse(raw)
            for item in parsed.get("items", []):
                visibleText = (item.get("visible_text") or "").strip()
                kanji = (item.get("kanji") or visibleText).strip()
                kana = (item.get("kana") or "").strip()
                confidence = float(item.get("confidence") or 0)
                if not (kanji or kana or visibleText):
                    continue
                candidates.append(
                    {
                        "visible_text": visibleText,
                        "kanji": kanji,
                        "kana": kana,
                        "confidence": confidence,
                        "image_name": upload.name,
                    }
                )
        except Exception as exc:
            errors.append(f"{upload.name}: {exc}")
        finally:
            if progressCallback:
                progressCallback(uploadIndex, totalUploads, f"Scanned {upload.name} ({uploadIndex}/{totalUploads})")

    return candidates, errors
