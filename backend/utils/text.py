from rapidfuzz import fuzz

def clean_text(text: str):
    return text.lower().strip()
