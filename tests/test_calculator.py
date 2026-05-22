import pytest

from app.calculator import add, divide, multiply, subtract


def test_add_3_plus_2():
    assert add(3, 2) == 5


def test_add_mixed_types_and_negatives():
    assert add(1.5, 2) == 3.5
    assert add(-3, 2.5) == -0.5
    assert add(-1, -1) == -2
    assert add(0, 0) == 0
    assert add(0.1, 0.2) == pytest.approx(0.3) # Test floating point precision


def test_subtract():
    assert subtract(3, 2) == 1


def test_multiply():
    assert multiply(3, 2) == 6


def test_divide():
    assert divide(6, 2) == 3


def test_divide_by_zero():
    with pytest.raises(ValueError):
        divide(1, 0)
