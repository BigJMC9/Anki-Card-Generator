import re
from typing import Any, Dict, List

from AnkiDeckBuilder.JamdictService import NormalizeNumericJapaneseSurface

JapaneseSegmentPattern = re.compile(r"[一-龯々〆ヶぁ-ゖァ-ヺー]+")
KanjiOnlyPattern = re.compile(r"^[一-龯々〆ヶ]+$")
KanaOnlyPattern = re.compile(r"^[ぁ-ゖァ-ヺー]+$")
NumeralKanjiPattern = re.compile(r"[一二三四五六七八九十百千万〇零]")
NumericFunCompoundPattern = re.compile(r"^[一二三四五六七八九十百千万〇零]+分$")
ScanExpressionConnectors = ("の", "ノ", "/", "／")


def FormatDeckLabel(deck: Dict[str, Any]) -> str:
    collectionName = deck.get("collection_name", "Unknown collection")
    return f"{collectionName} :: {deck['name']}"


def ParseCommaSeparatedTags(tagsText: str) -> List[str]:
    normalizedTags: List[str] = []
    for rawTag in (tagsText or "").split(","):
        tag = rawTag.strip()
        if not tag or tag in normalizedTags:
            continue
        normalizedTags.append(tag)
    return normalizedTags


def NormalizeScanText(value: str) -> str:
    normalizedValue = re.sub(r"\s+", "", (value or "").strip())
    return NormalizeNumericJapaneseSurface(normalizedValue)


def ExtractScanTermsFromExpression(expression: str) -> List[str]:
    normalizedExpression = NormalizeScanText(expression)
    if not normalizedExpression:
        return []

    containsConnector = any(connector in normalizedExpression for connector in ScanExpressionConnectors)
    if containsConnector:
        rawParts = re.split(r"[のノ/／]+", normalizedExpression)
        segments: List[str] = []
        for rawPart in rawParts:
            segments.extend(JapaneseSegmentPattern.findall(rawPart))
    else:
        segments = JapaneseSegmentPattern.findall(normalizedExpression)

    if not segments:
        return [normalizedExpression]

    if not containsConnector:
        terms: List[str] = []
        for segment in segments:
            if segment and segment not in terms:
                terms.append(segment)
        return terms

    terms: List[str] = []
    for segment in segments:
        if not segment:
            continue

        isKanjiCompound = len(segment) > 1 and KanjiOnlyPattern.match(segment) is not None
        isNumericCompound = isKanjiCompound and NumeralKanjiPattern.search(segment) is not None
        if isNumericCompound:
            for character in segment:
                if character not in terms:
                    terms.append(character)
        else:
            if segment not in terms:
                terms.append(segment)

    return terms


def ExpandExtractedScanCandidates(
    candidates: List[Dict[str, Any]],
    dictionaryLookup: Any,
) -> List[Dict[str, Any]]:
    expandedCandidates: List[Dict[str, Any]] = []
    seenKeys = set()
    dictionaryMatchCache: Dict[str, bool] = {}

    for candidate in candidates:
        originalVisibleText = NormalizeScanText(candidate.get("visible_text", ""))
        originalKanjiText = NormalizeScanText(candidate.get("kanji", ""))
        originalKanaText = NormalizeScanText(candidate.get("kana", ""))

        seedExpressions: List[str] = []
        for seed in [originalKanjiText, originalVisibleText]:
            if seed and seed not in seedExpressions:
                seedExpressions.append(seed)

        derivedTerms: List[str] = []
        for expression in seedExpressions:
            for term in ExtractScanTermsFromExpression(expression):
                if term and term not in derivedTerms:
                    derivedTerms.append(term)

        refinedTerms: List[str] = []
        for term in derivedTerms:
            normalizedTerm = NormalizeScanText(term)
            if not normalizedTerm:
                continue

            forceSplitNumericFunCompound = NumericFunCompoundPattern.match(normalizedTerm) is not None
            if forceSplitNumericFunCompound:
                for character in normalizedTerm:
                    if character not in refinedTerms:
                        refinedTerms.append(character)
                continue

            shouldSplitUnmatchedCompound = (
                len(normalizedTerm) > 1
                and KanjiOnlyPattern.match(normalizedTerm) is not None
            )
            if shouldSplitUnmatchedCompound:
                if normalizedTerm not in dictionaryMatchCache:
                    try:
                        dictionaryMatchCache[normalizedTerm] = bool(dictionaryLookup(normalizedTerm))
                    except Exception:
                        dictionaryMatchCache[normalizedTerm] = True

                if not dictionaryMatchCache[normalizedTerm]:
                    for character in normalizedTerm:
                        if character not in refinedTerms:
                            refinedTerms.append(character)
                    continue

            if normalizedTerm not in refinedTerms:
                refinedTerms.append(normalizedTerm)

        if not refinedTerms:
            fallbackTerm = originalKanjiText or originalVisibleText
            if fallbackTerm:
                refinedTerms = [fallbackTerm]

        originText = originalVisibleText or originalKanjiText
        for term in refinedTerms:
            normalizedOrigin = NormalizeScanText(originText)
            normalizedTerm = NormalizeScanText(term)
            isKanaOnlyTerm = KanaOnlyPattern.match(normalizedTerm or "") is not None
            isKanaOnlyOrigin = KanaOnlyPattern.match(normalizedOrigin or "") is not None
            if isKanaOnlyTerm and isKanaOnlyOrigin:
                continue

            candidateKey = (term, "")
            if candidateKey in seenKeys:
                continue
            seenKeys.add(candidateKey)

            keepOriginalKana = len(refinedTerms) == 1 and term in {originalKanjiText, originalVisibleText}
            expandedCandidates.append(
                {
                    **candidate,
                    "origin_visible_text": originText or term,
                    "visible_text": term,
                    "kanji": term,
                    "kana": originalKanaText if keepOriginalKana else "",
                }
            )

    return expandedCandidates


def BuildScanCandidateNote(candidate: Dict[str, Any]) -> str:
    imageName = (candidate.get("image_name") or "").strip()
    originText = NormalizeScanText(candidate.get("origin_visible_text", ""))
    termText = NormalizeScanText(candidate.get("visible_text", "")) or NormalizeScanText(candidate.get("kanji", ""))

    note = f"Extracted from image: {imageName}" if imageName else "Extracted from image"
    if originText and originText != termText:
        note += f" | Derived from: {originText}"
    return note
