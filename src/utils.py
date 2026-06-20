"""Helpers do Apolo AI."""

import re


def extract_code(text: str) -> str:
    for pattern in (r"```python\s*(.*?)```", r"```\w*\s*(.*?)```", r"```\s*(.*?)```"):
        matches = re.findall(pattern, text, re.DOTALL)
        if matches:
            return matches[0].strip()
    return text.strip()


def extract_explanation(text: str) -> str:
    """Retorna o texto antes do primeiro bloco de código."""
    match = re.search(r"```", text)
    if match:
        return text[:match.start()].strip()
    return ""


def sanitize_request(request: str) -> str:
    return request.strip()[:2000]
