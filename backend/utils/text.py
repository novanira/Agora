from rapidfuzz import fuzz

def clean_text(text: str):
    return text.lower().strip()

def fuzzy_similarity(text1, text2):
    num = 0
    num += 0.7 * fuzz.token_set_ratio(clean_text(text1), clean_text(text2))
    num += 0.3 * fuzz.token_sort_ratio(clean_text(text1), clean_text(text2))
    return num

test_names = [
    ['Coca-Cola Zero Sugar Soft Drink', 'Coca-Cola Soft Drink Zero Sugar 2.25L'],
    ['Eta Ripple Cut Sour Cream & Chives Potato Chips', 'Eta Ripples Chips Sour Cream & Chives 150g']
]

def test_fuzzy_similarity(text1, text2):
    print(text1)
    print(text2)
    print(fuzzy_similarity(text1, text2))
    return True

for names in test_names:
    test_fuzzy_similarity(names[0], names[1])