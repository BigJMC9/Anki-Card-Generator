import re
import threading
from typing import Any, Dict, List, Optional, Tuple

try:
    from jamdict import Jamdict
except ImportError:  # pragma: no cover - handled at runtime in GetJamdictClient
    Jamdict = None  # type: ignore[assignment]

VerbFormLabels = {
    "dictionary": "Plain (dictionary)",
    "masu": "Masu form",
    "te": "Te form",
    "past": "Past form",
    "negative": "Negative form",
}

VerbTypeLabels = {
    "ichidan": "Ichidan",
    "godan": "Godan",
    "suru": "Suru irregular",
    "suru_noun": "Suru noun",
    "kuru": "Kuru irregular",
    "other": "Non-verb",
}

TrailingKanaPattern = re.compile(r"[ぁ-ゖァ-ヺー]+$")
ContainsKanjiPattern = re.compile(r"[一-龯]")
ContainsKanaPattern = re.compile(r"[ぁ-ゖァ-ヺー]")
ArabicDigitsPattern = re.compile(r"[0-9０-９]+")
FullWidthDigitTranslation = str.maketrans(
    "０１２３４５６７８９",
    "0123456789",
)
KanjiDigitByInt = {
    0: "零",
    1: "一",
    2: "二",
    3: "三",
    4: "四",
    5: "五",
    6: "六",
    7: "七",
    8: "八",
    9: "九",
}
SmallUnits = [(1000, "千"), (100, "百"), (10, "十"), (1, "")]
LargeUnits = ["", "万", "億", "兆", "京"]

GodanIStemMap = {
    "う": "い",
    "く": "き",
    "ぐ": "ぎ",
    "す": "し",
    "つ": "ち",
    "ぬ": "に",
    "ぶ": "び",
    "む": "み",
    "る": "り",
}

GodanTePastMap = {
    "う": ("って", "った"),
    "つ": ("って", "った"),
    "る": ("って", "った"),
    "ぶ": ("んで", "んだ"),
    "む": ("んで", "んだ"),
    "ぬ": ("んで", "んだ"),
    "く": ("いて", "いた"),
    "ぐ": ("いで", "いだ"),
    "す": ("して", "した"),
}

GodanNegativeMap = {
    "う": "わない",
    "く": "かない",
    "ぐ": "がない",
    "す": "さない",
    "つ": "たない",
    "ぬ": "なない",
    "ぶ": "ばない",
    "む": "まない",
    "る": "らない",
}
PoliteMasuEndings = ("ます", "ました", "ません", "ませんでした", "ましょう")
ThreadLocalState = threading.local()


def NormalizeText(value: str) -> str:
    return (value or "").strip()


def ContainsKanji(value: str) -> bool:
    return bool(ContainsKanjiPattern.search(value or ""))


def ContainsKana(value: str) -> bool:
    return bool(ContainsKanaPattern.search(value or ""))


def LooksLikePoliteMasuSurface(value: str) -> bool:
    normalizedValue = NormalizeText(value)
    if not normalizedValue:
        return False
    return any(normalizedValue.endswith(ending) for ending in PoliteMasuEndings)


def ToAsciiDigits(value: str) -> str:
    return (value or "").translate(FullWidthDigitTranslation)


def ConvertSmallIntegerToKanji(number: int) -> str:
    if number <= 0:
        return ""
    parts: List[str] = []
    for unitValue, unitLabel in SmallUnits:
        digit = (number // unitValue) % 10
        if digit == 0:
            continue
        if digit == 1 and unitValue > 1:
            parts.append(unitLabel)
        else:
            parts.append(f"{KanjiDigitByInt[digit]}{unitLabel}")
    return "".join(parts)


def ConvertDigitSequenceToKanji(numberText: str) -> str:
    asciiDigits = ToAsciiDigits(numberText).lstrip("0")
    if not asciiDigits:
        return KanjiDigitByInt[0]
    if not asciiDigits.isdigit():
        return numberText

    numberValue = int(asciiDigits)
    if numberValue == 0:
        return KanjiDigitByInt[0]

    groups: List[int] = []
    while numberValue > 0:
        groups.append(numberValue % 10000)
        numberValue //= 10000

    parts: List[str] = []
    for groupIndex in range(len(groups) - 1, -1, -1):
        groupValue = groups[groupIndex]
        if groupValue == 0:
            continue
        groupText = ConvertSmallIntegerToKanji(groupValue)
        unitText = LargeUnits[groupIndex] if groupIndex < len(LargeUnits) else ""
        parts.append(f"{groupText}{unitText}")

    return "".join(parts) if parts else KanjiDigitByInt[0]


def NormalizeNumericJapaneseSurface(value: str) -> str:
    text = NormalizeText(value)
    if not text:
        return text
    return ArabicDigitsPattern.sub(lambda match: ConvertDigitSequenceToKanji(match.group(0)), text)


def GetJamdictClient() -> Any:
    if Jamdict is None:
        raise RuntimeError(
            "jamdict is not installed. Install with: pip install jamdict jamdict-data"
        )
    cachedClient = getattr(ThreadLocalState, "jamdict_client", None)
    if cachedClient is None:
        cachedClient = Jamdict()
        ThreadLocalState.jamdict_client = cachedClient
    return cachedClient


def ExtractForms(forms: Any) -> List[str]:
    normalizedForms: List[str] = []
    for rawForm in forms or []:
        form = str(rawForm).strip()
        if not form:
            continue
        for variant in [form, NormalizeNumericJapaneseSurface(form)]:
            if variant and variant not in normalizedForms:
                normalizedForms.append(variant)
    return normalizedForms


def ExtractGlosses(rawEntry: Any, maxItems: int = 5) -> List[str]:
    glosses: List[str] = []
    for sense in getattr(rawEntry, "senses", []) or []:
        for gloss in getattr(sense, "gloss", []) or []:
            text = str(gloss).strip()
            if not text or text in glosses:
                continue
            glosses.append(text)
            if len(glosses) >= maxItems:
                return glosses
    return glosses


def ExtractPosLabels(rawEntry: Any, maxItems: int = 8) -> List[str]:
    labels: List[str] = []
    for sense in getattr(rawEntry, "senses", []) or []:
        for pos in getattr(sense, "pos", []) or []:
            text = str(pos).strip()
            if not text or text in labels:
                continue
            labels.append(text)
            if len(labels) >= maxItems:
                return labels
    return labels


def ExtractSenseRows(rawEntry: Any, maxSenses: int = 8, maxGlosses: int = 6) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for sense in getattr(rawEntry, "senses", []) or []:
        glosses: List[str] = []
        for gloss in getattr(sense, "gloss", []) or []:
            text = str(gloss).strip()
            if not text or text in glosses:
                continue
            glosses.append(text)
            if len(glosses) >= maxGlosses:
                break

        posLabels: List[str] = []
        for pos in getattr(sense, "pos", []) or []:
            text = str(pos).strip()
            if not text or text in posLabels:
                continue
            posLabels.append(text)

        notes: List[str] = []
        for attributeName in ("misc", "info", "field", "dial"):
            for value in getattr(sense, attributeName, []) or []:
                text = str(value).strip()
                if not text or text in notes:
                    continue
                notes.append(text)

        if not glosses and not posLabels and not notes:
            continue

        rows.append(
            {
                "sense_index": len(rows) + 1,
                "glosses": glosses,
                "pos_labels": posLabels,
                "notes": notes,
            }
        )
        if len(rows) >= maxSenses:
            break

    return rows


def ExtractExampleSentences(rawEntry: Any, maxItems: int = 8) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    seen = set()
    for sense in getattr(rawEntry, "senses", []) or []:
        rawExamples: List[Any] = []
        for attributeName in ("examples", "example", "sentences"):
            value = getattr(sense, attributeName, None)
            if not value:
                continue
            if isinstance(value, list):
                rawExamples.extend(value)
            else:
                rawExamples.append(value)

        for rawExample in rawExamples:
            japanese = ""
            reading = ""
            english = ""

            if isinstance(rawExample, str):
                japanese = rawExample.strip()
            elif isinstance(rawExample, dict):
                japanese = str(
                    rawExample.get("japanese")
                    or rawExample.get("text")
                    or rawExample.get("sentence")
                    or rawExample.get("ja")
                    or rawExample.get("jpn")
                    or ""
                ).strip()
                reading = str(rawExample.get("reading") or rawExample.get("kana") or "").strip()
                english = str(
                    rawExample.get("english")
                    or rawExample.get("translation")
                    or rawExample.get("en")
                    or ""
                ).strip()
            else:
                japanese = str(
                    getattr(rawExample, "japanese", None)
                    or getattr(rawExample, "text", None)
                    or getattr(rawExample, "sentence", None)
                    or getattr(rawExample, "ja", None)
                    or getattr(rawExample, "jpn", None)
                    or ""
                ).strip()
                reading = str(
                    getattr(rawExample, "reading", None)
                    or getattr(rawExample, "kana", None)
                    or ""
                ).strip()
                english = str(
                    getattr(rawExample, "english", None)
                    or getattr(rawExample, "translation", None)
                    or getattr(rawExample, "en", None)
                    or ""
                ).strip()

            if not japanese and not english:
                continue

            dedupeKey = (japanese, reading, english)
            if dedupeKey in seen:
                continue
            seen.add(dedupeKey)

            rows.append(
                {
                    "japanese": japanese,
                    "reading": reading,
                    "english": english,
                }
            )
            if len(rows) >= maxItems:
                return rows

    return rows


def DetectVerbType(posLabels: List[str]) -> str:
    normalized = " | ".join(posLabels).lower()
    if "kuru verb" in normalized:
        return "kuru"
    if "suru verb" in normalized:
        return "suru"
    if "noun or participle which takes the aux. verb suru" in normalized:
        return "suru_noun"
    if "ichidan verb" in normalized:
        return "ichidan"
    if "godan verb" in normalized:
        return "godan"
    return "other"


def ChooseDictionaryLikeForm(forms: List[str]) -> str:
    if not forms:
        return ""
    for form in forms:
        if not LooksLikePoliteMasuSurface(form):
            return form
    return forms[0]


def IsIkuSpecial(posLabels: List[str]) -> bool:
    normalized = " | ".join(posLabels).lower()
    return "iku/yuku special class" in normalized


def NormalizeDictionaryEntry(rawEntry: Any) -> Dict[str, Any]:
    kanjiForms = ExtractForms(getattr(rawEntry, "kanji_forms", []))
    kanaForms = ExtractForms(getattr(rawEntry, "kana_forms", []))
    posLabels = ExtractPosLabels(rawEntry)
    glosses = ExtractGlosses(rawEntry)
    verbType = DetectVerbType(posLabels)
    senses = ExtractSenseRows(rawEntry)
    examples = ExtractExampleSentences(rawEntry)

    headword = kanjiForms[0] if kanjiForms else (kanaForms[0] if kanaForms else "")
    reading = kanaForms[0] if kanaForms else headword
    if verbType != "other":
        preferredHeadword = ChooseDictionaryLikeForm(kanjiForms) or ChooseDictionaryLikeForm(kanaForms)
        preferredReading = ChooseDictionaryLikeForm(kanaForms) or reading
        if preferredHeadword:
            headword = preferredHeadword
        if preferredReading:
            reading = preferredReading

    headword = NormalizeNumericJapaneseSurface(headword)
    reading = NormalizeText(reading)

    english = "; ".join(glosses[:3])

    return {
        "entry_id": str(getattr(rawEntry, "idseq", "") or ""),
        "headword": headword,
        "reading": reading,
        "english": english,
        "glosses": glosses,
        "senses": senses,
        "examples": examples,
        "pos_labels": posLabels,
        "kanji_forms": kanjiForms,
        "kana_forms": kanaForms,
        "verb_type": verbType,
        "verb_type_label": VerbTypeLabels.get(verbType, VerbTypeLabels["other"]),
        "is_iku_special": IsIkuSpecial(posLabels),
    }


def SearchDictionaryEntries(query: str, limit: int = 25) -> List[Dict[str, Any]]:
    normalizedQuery = NormalizeText(query)
    if not normalizedQuery:
        return []
    normalizedNumericQuery = NormalizeNumericJapaneseSurface(normalizedQuery)

    client = GetJamdictClient()
    seenIds = set()
    results: List[Dict[str, Any]] = []

    for lookupQuery in [normalizedQuery, normalizedNumericQuery]:
        exactResult = client.lookup(lookupQuery)
        for rawEntry in getattr(exactResult, "entries", []) or []:
            entry = NormalizeDictionaryEntry(rawEntry)
            entryId = entry["entry_id"]
            if not entryId or entryId in seenIds:
                continue
            seenIds.add(entryId)
            results.append(entry)
            if len(results) >= limit:
                return results

    if results:
        return results

    for lookupQuery in [normalizedQuery, normalizedNumericQuery]:
        iterResult = client.lookup_iter(lookupQuery)
        for rawEntry in getattr(iterResult, "entries", []) or []:
            entry = NormalizeDictionaryEntry(rawEntry)
            entryId = entry["entry_id"]
            if not entryId or entryId in seenIds:
                continue
            seenIds.add(entryId)
            results.append(entry)
            if len(results) >= limit:
                break
        if len(results) >= limit:
            break

    return results


def GetDictionaryEntryById(entryId: str) -> Optional[Dict[str, Any]]:
    normalizedEntryId = NormalizeText(entryId)
    if not normalizedEntryId:
        return None

    client = GetJamdictClient()
    rawEntry = client.jmdict.get_entry(normalizedEntryId)
    if not rawEntry:
        return None
    return NormalizeDictionaryEntry(rawEntry)


def FormatDictionaryEntryOption(entry: Dict[str, Any]) -> str:
    headword = entry.get("headword", "")
    reading = entry.get("reading", "")
    english = entry.get("english", "")
    pos = ", ".join(entry.get("pos_labels", [])[:2])
    identifier = entry.get("entry_id", "")

    summaryParts = [f"{headword} [{reading}]"]
    if pos:
        summaryParts.append(pos)
    if english:
        summaryParts.append(english)
    if identifier:
        summaryParts.append(f"JMDict #{identifier}")
    return " | ".join(summaryParts)


def IsVerbEntry(entry: Dict[str, Any]) -> bool:
    return entry.get("verb_type", "other") in {"ichidan", "godan", "suru", "suru_noun", "kuru"}


def GetVerbFormOptions(entry: Dict[str, Any]) -> List[str]:
    if IsVerbEntry(entry):
        return list(VerbFormLabels.keys())
    return ["dictionary"]


def IsSupportedVerbForm(wordForm: str) -> bool:
    return wordForm in VerbFormLabels


def BuildDictionaryReferenceNote(entry: Dict[str, Any]) -> str:
    headword = entry.get("headword", "")
    reading = entry.get("reading", "")
    english = entry.get("english", "")
    entryId = entry.get("entry_id", "")
    pos = ", ".join(entry.get("pos_labels", [])[:2])

    summary = f"{headword} [{reading}]".strip()
    details = [item for item in [english, pos] if item]
    suffix = f" - {' | '.join(details)}" if details else ""
    return f"JMDict #{entryId}: {summary}{suffix}".strip()


def ConjugateIchidanKana(dictionaryKana: str, wordForm: str) -> str:
    if not dictionaryKana.endswith("る"):
        return dictionaryKana
    stem = dictionaryKana[:-1]
    suffixByForm = {
        "dictionary": "る",
        "masu": "ます",
        "te": "て",
        "past": "た",
        "negative": "ない",
    }
    return stem + suffixByForm.get(wordForm, "る")


def ConjugateGodanKana(dictionaryKana: str, wordForm: str, isIkuSpecial: bool = False) -> str:
    if not dictionaryKana:
        return dictionaryKana
    ending = dictionaryKana[-1]
    stem = dictionaryKana[:-1]

    if wordForm == "dictionary":
        return dictionaryKana
    if wordForm == "masu":
        return stem + GodanIStemMap.get(ending, ending) + "ます"
    if wordForm == "negative":
        return stem + GodanNegativeMap.get(ending, ending + "ない")
    if wordForm in {"te", "past"}:
        if isIkuSpecial and ending == "く":
            return stem + ("って" if wordForm == "te" else "った")
        teEnding, pastEnding = GodanTePastMap.get(ending, ("", ""))
        if not teEnding or not pastEnding:
            return dictionaryKana
        return stem + (teEnding if wordForm == "te" else pastEnding)

    return dictionaryKana


def ApplyOkuriganaToKanji(dictionaryKanji: str, dictionaryKana: str, conjugatedKana: str) -> str:
    if not dictionaryKanji:
        return conjugatedKana
    if dictionaryKanji == dictionaryKana:
        return conjugatedKana

    trailingKanaMatch = TrailingKanaPattern.search(dictionaryKanji)
    if trailingKanaMatch:
        originalSuffix = trailingKanaMatch.group(0)
        if dictionaryKana.endswith(originalSuffix):
            kanaStem = dictionaryKana[: -len(originalSuffix)]
            if conjugatedKana.startswith(kanaStem):
                nextSuffix = conjugatedKana[len(kanaStem) :]
                return dictionaryKanji[: -len(originalSuffix)] + nextSuffix

    return conjugatedKana


def SplitSuruBase(surface: str) -> str:
    for ending in ("する", "為る", "為す"):
        if surface.endswith(ending):
            return surface[: -len(ending)]
    return surface


def ConjugateSuru(kanji: str, kana: str, wordForm: str, suruNoun: bool = False) -> Tuple[str, str]:
    kanjiBase = kanji if suruNoun else SplitSuruBase(kanji)
    kanaBase = kana if suruNoun else (kana[:-2] if kana.endswith("する") else SplitSuruBase(kana))

    suffixByForm = {
        "dictionary": ("する", "する"),
        "masu": ("します", "します"),
        "te": ("して", "して"),
        "past": ("した", "した"),
        "negative": ("しない", "しない"),
    }
    kanjiSuffix, kanaSuffix = suffixByForm.get(wordForm, suffixByForm["dictionary"])
    return kanjiBase + kanjiSuffix, kanaBase + kanaSuffix


def ConjugateKuru(kanji: str, kana: str, wordForm: str) -> Tuple[str, str]:
    kanaBase = kana[:-2] if kana.endswith("くる") else kana
    kanaSuffixByForm = {
        "dictionary": "くる",
        "masu": "きます",
        "te": "きて",
        "past": "きた",
        "negative": "こない",
    }
    kanjiSuffixByForm = {
        "dictionary": "来る",
        "masu": "来ます",
        "te": "来て",
        "past": "来た",
        "negative": "来ない",
    }

    conjugatedKana = kanaBase + kanaSuffixByForm.get(wordForm, kanaSuffixByForm["dictionary"])

    if kanji.endswith("来る"):
        kanjiBase = kanji[:-2]
        conjugatedKanji = kanjiBase + kanjiSuffixByForm.get(wordForm, kanjiSuffixByForm["dictionary"])
        return conjugatedKanji, conjugatedKana

    if kanji.endswith("くる"):
        return kanaBase + kanaSuffixByForm.get(wordForm, kanaSuffixByForm["dictionary"]), conjugatedKana

    return conjugatedKana, conjugatedKana


def ConjugateVerbSurface(
    kanji: str,
    kana: str,
    verbType: str,
    wordForm: str,
    isIkuSpecial: bool = False,
) -> Tuple[str, str]:
    normalizedWordForm = wordForm if IsSupportedVerbForm(wordForm) else "dictionary"
    normalizedKana = NormalizeText(kana)
    normalizedKanji = NormalizeText(kanji) or normalizedKana

    if verbType == "suru_noun":
        return ConjugateSuru(normalizedKanji, normalizedKana, normalizedWordForm, suruNoun=True)
    if verbType == "suru":
        return ConjugateSuru(normalizedKanji, normalizedKana, normalizedWordForm, suruNoun=False)
    if verbType == "kuru":
        return ConjugateKuru(normalizedKanji, normalizedKana, normalizedWordForm)
    if verbType == "ichidan":
        conjugatedKana = ConjugateIchidanKana(normalizedKana, normalizedWordForm)
        conjugatedKanji = ApplyOkuriganaToKanji(normalizedKanji, normalizedKana, conjugatedKana)
        return conjugatedKanji, conjugatedKana
    if verbType == "godan":
        conjugatedKana = ConjugateGodanKana(normalizedKana, normalizedWordForm, isIkuSpecial=isIkuSpecial)
        conjugatedKanji = ApplyOkuriganaToKanji(normalizedKanji, normalizedKana, conjugatedKana)
        return conjugatedKanji, conjugatedKana

    return normalizedKanji, normalizedKana


def ResolveWordSurface(entry: Dict[str, Any], requestedWordForm: str) -> Tuple[str, str, str]:
    if not IsVerbEntry(entry):
        return entry.get("headword", ""), entry.get("reading", ""), "dictionary"

    selectedWordForm = requestedWordForm if IsSupportedVerbForm(requestedWordForm) else "dictionary"
    kanji, kana = ConjugateVerbSurface(
        entry.get("headword", ""),
        entry.get("reading", ""),
        entry.get("verb_type", "other"),
        selectedWordForm,
        isIkuSpecial=bool(entry.get("is_iku_special", False)),
    )
    return kanji, kana, selectedWordForm


def BuildCardFromDictionaryEntry(
    entry: Dict[str, Any],
    schemaKey: str,
    requestedWordForm: str,
    tags: List[str],
    notes: str,
    englishOverride: str = "",
    sourceText: str = "",
) -> Dict[str, Any]:
    kanji, kana, appliedWordForm = ResolveWordSurface(entry, requestedWordForm)
    english = NormalizeText(englishOverride) or entry.get("english", "")
    combinedNotes = NormalizeText(notes)

    return {
        "kanji": kanji,
        "kana": kana,
        "english": english,
        "notes": combinedNotes,
        "source_text": NormalizeText(sourceText) or f"jamdict:{entry.get('entry_id', '')}",
        "schema_key": schemaKey,
        "media_type": "none",
        "media_files": [],
        "tags": sorted(set((tags or []) + ["jamdict"])),
        "dictionary_entry_id": entry.get("entry_id", ""),
        "dictionary_headword": entry.get("headword", ""),
        "dictionary_reading": entry.get("reading", ""),
        "dictionary_gloss": entry.get("english", ""),
        "dictionary_pos": ", ".join(entry.get("pos_labels", [])),
        "verb_type": entry.get("verb_type", ""),
        "word_form": appliedWordForm,
    }


def BuildConjugatedForms(entry: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    forms: Dict[str, Dict[str, str]] = {}
    for wordForm in VerbFormLabels.keys():
        kanji, kana, appliedWordForm = ResolveWordSurface(entry, wordForm)
        forms[appliedWordForm] = {
            "kanji": NormalizeText(kanji),
            "kana": NormalizeText(kana),
        }
    return forms


def BuildGlobalCardFromDictionaryEntry(
    entry: Dict[str, Any],
    tags: Optional[List[str]] = None,
    notes: str = "",
    englishOverride: str = "",
) -> Dict[str, Any]:
    forms = BuildConjugatedForms(entry)
    dictionarySurface = forms.get(
        "dictionary",
        {
            "kanji": NormalizeText(entry.get("headword", "")),
            "kana": NormalizeText(entry.get("reading", "")),
        },
    )
    english = NormalizeText(englishOverride) or NormalizeText(entry.get("english", ""))

    masuSurface = forms.get("masu", {})
    teSurface = forms.get("te", {})
    pastSurface = forms.get("past", {})
    negativeSurface = forms.get("negative", {})

    return {
        "kanji": dictionarySurface.get("kanji", ""),
        "kana": dictionarySurface.get("kana", ""),
        "english": english,
        "notes": NormalizeText(notes),
        "kanji_masu": masuSurface.get("kanji", ""),
        "kana_masu": masuSurface.get("kana", ""),
        "kanji_te": teSurface.get("kanji", ""),
        "kana_te": teSurface.get("kana", ""),
        "kanji_past": pastSurface.get("kanji", ""),
        "kana_past": pastSurface.get("kana", ""),
        "kanji_negative": negativeSurface.get("kanji", ""),
        "kana_negative": negativeSurface.get("kana", ""),
        "image_files": [],
        "video_files": [],
        "tags": sorted(set((tags or []) + ["jamdict"])),
        "dictionary_entry_id": entry.get("entry_id", ""),
        "dictionary_headword": entry.get("headword", ""),
        "dictionary_reading": entry.get("reading", ""),
        "dictionary_gloss": entry.get("english", ""),
        "dictionary_pos": ", ".join(entry.get("pos_labels", [])),
        "verb_type": entry.get("verb_type", ""),
    }


def ScoreDictionaryMatch(
    entry: Dict[str, Any],
    query: str,
    sourceKanji: str,
    sourceKana: str,
    visibleText: str,
    queryIndex: int,
    resultIndex: int,
) -> int:
    score = 0
    headword = NormalizeNumericJapaneseSurface(entry.get("headword", ""))
    reading = NormalizeText(entry.get("reading", ""))
    kanjiForms = {NormalizeNumericJapaneseSurface(form) for form in entry.get("kanji_forms", [])}
    kanaForms = {NormalizeText(form) for form in entry.get("kana_forms", [])}
    normalizedQuery = NormalizeNumericJapaneseSurface(query)
    normalizedSourceKanji = NormalizeNumericJapaneseSurface(sourceKanji)
    normalizedSourceKana = NormalizeText(sourceKana)
    normalizedVisibleText = NormalizeNumericJapaneseSurface(visibleText)

    if normalizedQuery == headword:
        score += 40
    if normalizedQuery == reading:
        score += 35
    if normalizedQuery in kanjiForms or normalizedQuery in kanaForms:
        score += 30

    if normalizedSourceKanji:
        if normalizedSourceKanji == headword:
            score += 130
        elif normalizedSourceKanji in kanjiForms:
            score += 120

        if ContainsKanji(normalizedSourceKanji) and ContainsKana(normalizedSourceKanji):
            if normalizedSourceKanji == headword:
                score += 35
            elif normalizedSourceKanji in kanjiForms:
                score += 25

    if normalizedSourceKana:
        if normalizedSourceKana == reading:
            score += 95
        elif normalizedSourceKana in kanaForms:
            score += 85

    if normalizedVisibleText:
        if normalizedVisibleText == headword:
            score += 60
        elif normalizedVisibleText in kanjiForms or normalizedVisibleText in kanaForms:
            score += 50

    if re.search(r"[0-9０-９]", headword):
        score -= 20

    score -= queryIndex * 4
    score -= resultIndex
    return score


def ResolveBestDictionaryEntry(
    sourceKanji: str = "",
    sourceKana: str = "",
    visibleText: str = "",
) -> Optional[Dict[str, Any]]:
    queryCandidates: List[str] = []
    for candidate in [sourceKanji, sourceKana, visibleText]:
        normalizedCandidate = NormalizeText(candidate)
        if not normalizedCandidate or normalizedCandidate in queryCandidates:
            continue
        queryCandidates.append(normalizedCandidate)

    if not queryCandidates:
        return None

    bestEntry: Optional[Dict[str, Any]] = None
    bestScore: Optional[int] = None

    for queryIndex, query in enumerate(queryCandidates):
        entries = SearchDictionaryEntries(query, limit=20)
        for resultIndex, entry in enumerate(entries):
            score = ScoreDictionaryMatch(
                entry,
                query,
                NormalizeText(sourceKanji),
                NormalizeText(sourceKana),
                NormalizeText(visibleText),
                queryIndex,
                resultIndex,
            )
            if bestEntry is None or bestScore is None or score > bestScore:
                bestEntry = entry
                bestScore = score

    if bestEntry is None or bestScore is None or bestScore < 35:
        return None
    return bestEntry
