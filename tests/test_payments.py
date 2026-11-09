"""
=============================================================================
test_payments.py : tests for paying a bill at POST /bills/pay
=============================================================================
Rules being tested:
  - You can pay any amount above 0, up to the outstanding balance
    (outstanding = amount_due - amount_paid).
  - Overpaying, paying 0 or a negative amount must be rejected, and the bill
    must NOT change.

Pattern used in most tests below:
  1. ACT:    send a payment with resident_client.post(...)
  2. CHECK:  look at the response (status code, text on the page)
  3. VERIFY: reload the bill from the database and check amount_paid

db_session.refresh(bill) is step 3's key move. The "bill" object in the test
is a stale copy in memory; refresh() re-reads the latest values from the
database so we see what the app really saved.
=============================================================================
"""

import pytest

# The exact error text the page should show for a bad amount.
ERROR = "Enter an amount greater than 0 and no more than the outstanding balance"


"""
TEST: overpayment is rejected and not applied
You cannot pay more than you owe.
Example: the bill is 6500, the resident tries to pay 6500.01 -> error shown, amount_paid stays 0.
"""
def test_overpayment_is_rejected_and_not_applied(resident_client, db_session, bill):
    # The bill is 6500, so 6500.01 is one paisa too much.
    # data={...} is the form data, like a browser submitting a form.
    response = resident_client.post("/bills/pay", data={"amount": 6500.01}, follow_redirects=False)

    assert response.status_code == 200  # form re-rendered, not redirected
    assert ERROR in response.text  # the error message is visible to the user
    db_session.refresh(bill)
    assert bill.amount_paid == 0  # nothing was recorded


"""
TEST: zero or negative payment is rejected
Payments of 0 or less make no sense, so they are refused.
Example: paying 0, -50 or -0.01 -> error shown, amount_paid stays 0.

parametrize again: this test runs 3 times, with amount = 0, then -50, then -0.01.
"""
@pytest.mark.parametrize("amount", [0, -50, -0.01])
def test_zero_or_negative_payment_is_rejected(resident_client, db_session, bill, amount):
    response = resident_client.post("/bills/pay", data={"amount": amount}, follow_redirects=False)

    assert response.status_code == 200
    assert ERROR in response.text
    db_session.refresh(bill)
    assert bill.amount_paid == 0


"""
TEST: valid payment increases amount paid
A normal payment is saved.
Example: the resident pays 1000 on a 6500 bill -> amount_paid becomes 1000.
"""
def test_valid_payment_increases_amount_paid(resident_client, db_session, bill):
    response = resident_client.post("/bills/pay", data={"amount": 1000}, follow_redirects=False)

    # 303 = redirect. After a successful payment the app sends the user back to
    # /bills?paid=1, and "location" is the header that says where to go.
    assert response.status_code == 303
    assert response.headers["location"] == "/bills?paid=1"
    db_session.refresh(bill)
    assert bill.amount_paid == 1000


"""
TEST: resident sees success banner after paying
After paying, the resident sees a "Payment received" message.
Example: pay 1000 -> the browser lands on /bills?paid=1 and shows the banner.
"""
def test_resident_sees_success_banner_after_paying(resident_client, bill):
    """
    Default follow_redirects=True: land on /bills?paid=1 like a browser would.
    This time we let the client follow the redirect, so "response" is the
    final page the user would actually see.
    """
    response = resident_client.post("/bills/pay", data={"amount": 1000})

    assert response.status_code == 200
    assert "Payment received" in response.text
    # "not in" is the opposite check: the error must NOT be on the page.
    assert ERROR not in response.text


"""
TEST: two payments accumulate
Part payments add up.
Example: pay 1000, then pay 2500 -> amount_paid is 3500.
"""
def test_two_payments_accumulate(resident_client, db_session, bill):
    # Part payments should add up: 1000 + 2500 = 3500.
    resident_client.post("/bills/pay", data={"amount": 1000}, follow_redirects=False)
    resident_client.post("/bills/pay", data={"amount": 2500}, follow_redirects=False)

    db_session.refresh(bill)
    assert bill.amount_paid == 3500


"""
TEST: paying exact outstanding balance is allowed
Paying the full remaining amount is allowed (an edge case).
Example: the bill is 6500, the resident pays exactly 6500 -> accepted, bill fully paid.
"""
def test_paying_exact_outstanding_balance_is_allowed(resident_client, db_session, bill):
    """
    Boundary test: exactly the full amount is the largest allowed payment.
    Tests right at the edge of a rule catch "off by one" mistakes (using
    "<" where "<=" was meant).
    """
    response = resident_client.post("/bills/pay", data={"amount": 6500}, follow_redirects=False)

    assert response.status_code == 303
    db_session.refresh(bill)
    assert bill.amount_paid == bill.amount_due


"""
TEST: cannot pay again once fully paid
Once a bill is fully paid, nothing more can be paid.
Example: pay 6500 (all of it), then try to pay 1 more -> error, amount_paid stays 6500.
"""
def test_cannot_pay_again_once_fully_paid(resident_client, db_session, bill):
    # First payment clears the bill completely. We don't check its response,
    # because this test is about what happens next.
    resident_client.post("/bills/pay", data={"amount": 6500}, follow_redirects=False)
    # Outstanding balance is now 0, so even 1 rupee is "more than outstanding".
    response = resident_client.post("/bills/pay", data={"amount": 1}, follow_redirects=False)

    assert response.status_code == 200
    assert ERROR in response.text
    db_session.refresh(bill)
    assert bill.amount_paid == 6500  # unchanged by the rejected payment


"""
TEST: staff cannot pay a bill
Staff are not residents, so they cannot pay a bill.
Example: a staff member sends a payment of 100 -> 403 and the bill is untouched.
"""
def test_staff_cannot_pay_a_bill(staff_client, db_session, bill):
    # Staff are logged in but are not residents, so require_role("resident")
    # must answer 403 (forbidden), and the bill must stay untouched.
    response = staff_client.post("/bills/pay", data={"amount": 100}, follow_redirects=False)

    assert response.status_code == 403
    db_session.refresh(bill)
    assert bill.amount_paid == 0


"""
TEST: anonymous cannot pay
Someone who is not logged in cannot pay.
Example: an anonymous visitor sends a payment of 100 -> 401 and the bill is untouched.
"""
def test_anonymous_cannot_pay(client, db_session, bill):
    # "client" is not logged in, so the payment must be refused with 401
    # and the bill must stay untouched.
    response = client.post("/bills/pay", data={"amount": 100}, follow_redirects=False)

    assert response.status_code == 401
    db_session.refresh(bill)
    assert bill.amount_paid == 0
