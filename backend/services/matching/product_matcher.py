from rapidfuzz import fuzz

from models.product import Product
from services.matching.normaliser import normalise_name, normalise_size

class ProductMatcher:
    def __init__(self, threshold: float = 90.0):
        self._threshold = threshold

    def _check_product_compatibility(self, product_a: Product, product_b: Product) -> tuple:
        brand_match = None
        if product_a.brand is not None and product_b.brand is not None:
            brand_match = (normalise_name(product_a.brand) == normalise_name(product_b.brand))

        size_match = None
        size_a = normalise_size(product_a.quantity, product_a.unit)
        size_b = normalise_size(product_b.quantity, product_b.unit)

        if size_a is not None and size_b is not None:
            size_match = (size_a == size_b)

        amount_match = None
        if product_a.amount is not None and product_b.amount is not None:
            amount_match = product_a.amount == product_b.amount

        return brand_match, size_match, amount_match
            

    def _calculate_match_score(self, product_a: Product, product_b: Product) -> float:
        compatibility = self._check_product_compatibility(product_a, product_b)
        if False in compatibility:
            return 0.0
        name_a = normalise_name(product_a.name)
        name_b = normalise_name(product_b.name)

        raw_score = fuzz.WRatio(name_a, name_b)

        return raw_score

    def find_matches() -> list:
        pass




if __name__ == "__main__":
    from services.sample_product_pairs import LABELLED_PRODUCT_PAIRS

    matcher = ProductMatcher()

    tp = 0  # True positives
    fp = 0  # False positives
    tn = 0  # True negatives
    fn = 0  # False negatives

    for product_a, product_b, expected_match in LABELLED_PRODUCT_PAIRS:
        score = matcher._calculate_match_score(product_a, product_b)
        predicted_match = score >= matcher._threshold

        if predicted_match and expected_match:
            tp += 1
        elif predicted_match and not expected_match:
            fp += 1
        elif not predicted_match and expected_match:
            fn += 1
        else:
            tn += 1

        if predicted_match != expected_match:
            print(f"\nNew World: {product_a.name}")
            print(f"Woolworths: {product_b.name}")
            print(f"Expected match: {expected_match}")
            print(f"Predicted match: {predicted_match}")
            print(f"Compatibility: {matcher._check_product_compatibility(product_a, product_b)}")
            print(f"Score: {score:.2f}")

    total = tp + fp + tn + fn

    precision = tp / (tp + fp) if tp + fp else 0
    recall = tp / (tp + fn) if tp + fn else 0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
    accuracy = (tp + tn) / total if total else 0

    print(f"\nTotal pairs: {total}")
    print(f"True positives: {tp}")
    print(f"False positives: {fp}")
    print(f"True negatives: {tn}")
    print(f"False negatives: {fn}")

    print(f"\nPrecision: {precision:.2%}")
    print(f"Recall: {recall:.2%}")
    print(f"F1 score: {f1:.2%}")
    print(f"Accuracy: {accuracy:.2%}")