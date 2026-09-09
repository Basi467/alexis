import re
import string


def clean_query(text: str) -> str:
    filler_words = ["find me", "find", "search for", "my", "me"]
    query = text
    for word in filler_words:
        query = re.sub(rf"\b{word}\b", "", query, flags=re.IGNORECASE)
    return query.strip(string.punctuation + " ")