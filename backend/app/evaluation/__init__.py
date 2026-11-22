"""Synthetic benchmark of the validation pipeline (brief Part L, NEXT_STEPS step 10).

``synthetic`` generates bills with injected errors and their ground truth, ``scoring`` matches
findings to it and computes the metrics, ``runner`` runs everything through the product's own
upload and validation path. Run it with ``python -m app.evaluation``.
"""
