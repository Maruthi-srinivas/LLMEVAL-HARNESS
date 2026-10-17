"""Text normalization shared by metrics and the sample mock."""


def normalize_text(value: str) -> str:
    return " ".join(value.casefold().split())
