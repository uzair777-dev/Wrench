"""Python 3.15 Native Explicit Lazy Import Demonstration (PEP 810).

In Python 3.15+, `lazy import <module>` defers module execution until an
attribute on the module is first resolved.
"""

lazy import json
lazy import math


def calculate_square_root(value: float) -> float:
    """Calculate square root using lazily-imported math."""
    return math.sqrt(value)


def serialize_json(data: dict) -> str:
    """Serialize dictionary using lazily-imported json."""
    return json.dumps(data)


if __name__ == "__main__":
    import sys

    print("Executing under Python version:", sys.version)
    print("Math result:", calculate_square_root(25.0))
    print("JSON result:", serialize_json({"wrench": "lazy_import", "python": "3.15"}))
