"""Shared building blocks of the comparison checks (not a detector package: discovery never
imports it).

* :mod:`.items`: the item frame, one record per priced item row, read once per run.
* :mod:`.robust`: robust statistics (floats only inside the statistics; what people see comes
  from the exact ``Decimal`` values).
* :mod:`.text_keys`: comparison keys and character n-grams of descriptions.
"""
