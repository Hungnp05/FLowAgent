import unicodedata

VIETNAMESE_D = str.maketrans({"đ": "d", "Đ": "d"})


def fold_text(text: str) -> str:
    """Lowercase and strip Vietnamese diacritics so matching ignores case and accents."""
    decomposed = unicodedata.normalize("NFD", text.translate(VIETNAMESE_D))
    return "".join(char for char in decomposed if not unicodedata.combining(char)).lower()


def contains_all_words(text: str, query: str) -> bool:
    """Report whether every word of the query appears in the text, ignoring case and accents."""
    folded_text = fold_text(text)
    return all(word in folded_text for word in fold_text(query).split())
