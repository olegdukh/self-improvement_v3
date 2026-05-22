"""A tiny calculator module used by the self-improvement demo project."""


def add(a: int | float, b: int | float) -> int | float:
    """Return the sum of two numbers."""
    return a + b


def subtract(a: int | float, b: int | float) -> int | float:
    """Return the difference between two numbers."""
    return a - b


def multiply(a: int | float, b: int | float) -> int | float:
    """Return the product of two numbers."""
    return a * b


def divide(a: int | float, b: int | float) -> int | float:
    """Return the quotient of two numbers.

    Raises:
        ValueError: If b is zero.
    """
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b
