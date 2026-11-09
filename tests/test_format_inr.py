"""
=============================================================================
test_format_inr.py : tests for format_inr(), the "₹1,23,456.78" formatter
=============================================================================
Indian number grouping is different from Western grouping:
  - the LAST 3 digits form one group
  - then groups of 2 digits going left
  Western:  1,000,000      Indian:  10,00,000   (ten lakh)

Useful names: 1 lakh = 1,00,000       1 crore = 1,00,00,000

format_inr() always shows exactly 2 decimals (paise), so real money is never
silently rounded away. The tests are pure input -> output checks: no
database, no login, just call the function and compare the text.
=============================================================================
"""

import pytest

from app.main import format_inr, templates


"""
TEST: small amounts have no comma
Up to 3 digits needs no comma.
Example: 999 -> "₹999.00".

Each tuple is (input number, exact text we expect back).
"""
@pytest.mark.parametrize(
    "value, expected",
    [
        (0, "₹0.00"),
        (5, "₹5.00"),
        (999, "₹999.00"),  # 3 digits: no comma yet
    ],
)
def test_small_amounts_have_no_comma(value, expected):
    assert format_inr(value) == expected


"""
TEST: lakh grouping
Indian style: last 3 digits, then groups of 2.
Example: 100000 -> "₹1,00,000.00" (1 lakh). The Western style would be 100,000.
"""
@pytest.mark.parametrize(
    "value, expected",
    [
        (1000, "₹1,000.00"),  # thousand
        (12345, "₹12,345.00"),  # first group of 2 appears
        (99999, "₹99,999.00"),
        (100000, "₹1,00,000.00"),  # 1 lakh (Western would print 100,000)
        (1234567, "₹12,34,567.00"),  # 12 lakh
        (9999999, "₹99,99,999.00"),  # largest value below 1 crore
    ],
)
def test_lakh_grouping(value, expected):
    assert format_inr(value) == expected


"""
TEST: crore grouping
The same rule keeps going for bigger numbers.
Example: 10000000 -> "₹1,00,00,000.00" (1 crore).
"""
@pytest.mark.parametrize(
    "value, expected",
    [
        (10000000, "₹1,00,00,000.00"),  # exactly 1 crore
        (123456789, "₹12,34,56,789.00"),  # 12 crore 34 lakh ...
        (1000000000, "₹1,00,00,00,000.00"),  # 100 crore
    ],
)
def test_crore_grouping(value, expected):
    assert format_inr(value) == expected


"""
TEST: paise are always two decimals
Paise always show as exactly 2 digits.
Example: 0.5 -> "₹0.50" and 0.05 -> "₹0.05".
"""
@pytest.mark.parametrize(
    "value, expected",
    [
        (0.5, "₹0.50"),  # one decimal digit is padded to two
        (0.05, "₹0.05"),  # leading zero in the paise is kept
        (1234.56, "₹1,234.56"),
        (100000.01, "₹1,00,000.01"),
        (7475.0, "₹7,475.00"),  # a float with no paise still shows .00
    ],
)
def test_paise_are_always_two_decimals(value, expected):
    assert format_inr(value) == expected


"""
TEST: the 2900 point 4 case shows paise not a rounded rupee
The old bug: 2900.4 used to show as "₹2,900" and hide 40 paise.
Example: 2900.4 -> "₹2,900.40".
"""
def test_the_2900_point_4_case_shows_paise_not_a_rounded_rupee():
    """
    The bug this function was written to fix: 2900.4 used to print as
    "₹2,900", hiding 40 paise. Floats cannot store 2900.4 exactly (it is
    really 2900.399999...), so the code rounds the whole value in paise.
    """
    assert format_inr(2900.4) == "₹2,900.40"


"""
TEST: paise rounding carries into rupees
Rounding can push the number up to the next rupee, or even the next group.
Example: 0.999 -> "₹1.00" and 99999.995 -> "₹1,00,000.00".
"""
def test_paise_rounding_carries_into_rupees():
    # 0.999 rupees is 99.9 paise, which rounds to 100 paise = 1 rupee.
    assert format_inr(0.999) == "₹1.00"
    # 99999.995 rounds up across the lakh boundary.
    assert format_inr(99999.995) == "₹1,00,000.00"


"""
TEST: negative values put the minus before the rupee sign
Negative amounts show the minus sign first.
Example: -1500 -> "-₹1,500.00".
"""
@pytest.mark.parametrize(
    "value, expected",
    [
        (-1, "-₹1.00"),
        (-1500, "-₹1,500.00"),
        (-0.5, "-₹0.50"),
        (-100000.25, "-₹1,00,000.25"),  # grouping works the same for negatives
        (-2900.4, "-₹2,900.40"),
    ],
)
def test_negative_values_put_the_minus_before_the_rupee_sign(value, expected):
    assert format_inr(value) == expected


"""
TEST: integers and floats format identically
A whole number and the same number with .0 look the same.
Example: 6500 and 6500.0 both give "₹6,500.00".
"""
def test_integers_and_floats_format_identically():
    assert format_inr(6500) == format_inr(6500.0) == "₹6,500.00"


"""
TEST: it is registered as the inr template filter
HTML pages can only use {{ amount | inr }} if the function is registered as "inr".
Example: this test checks the "inr" filter really is format_inr.
"""
def test_it_is_registered_as_the_inr_template_filter():
    # In the HTML templates we write {{ amount | inr }}. That only works if
    # the function was registered under the name "inr".
    assert templates.env.filters["inr"] is format_inr
