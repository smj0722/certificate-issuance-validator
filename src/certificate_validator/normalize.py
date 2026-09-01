from __future__ import annotations
import re
from difflib import SequenceMatcher

_COMPANY_WORDS = ("주식회사", "(주)", "㈜")


def compact(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = re.sub(r"[\s\-_.,·ㆍ*'\"`~!@#$%^&+=:;?/\\|()\[\]{}<>]", "", text)
    return text


def normalize_company(value: object) -> str:
    text = str(value or "")
    for token in _COMPANY_WORDS:
        text = text.replace(token, "")
    return compact(text)


def normalize_project(value: object) -> str:
    return compact(value)


def similarity(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def project_match(a: str, b: str) -> tuple[bool, bool, float]:
    na, nb = normalize_project(a), normalize_project(b)
    if na == nb:
        return True, False, 1.0
    score = similarity(na, nb)
    if na and nb and (na in nb or nb in na):
        return True, True, score
    return score >= 0.78, score >= 0.78, score


def company_match(a: str, b: str) -> tuple[bool, bool, float]:
    na, nb = normalize_company(a), normalize_company(b)
    if na == nb:
        return True, False, 1.0
    score = similarity(na, nb)
    if na and nb and (na in nb or nb in na):
        return True, True, score
    return score >= 0.82, score >= 0.82, score
