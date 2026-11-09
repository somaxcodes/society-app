"""
=============================================================================
test_auth.py : tests for "who is allowed to see which page"
=============================================================================
Authentication = proving who you are (logging in).
Authorization = what you are allowed to do once logged in.

HTTP status codes used in this file:
  200 = OK, here is the page
  401 = "you are not logged in"
  403 = "you are logged in, but you are not allowed here"
  303 = "redirect": go to another page (used after a successful login)

BASIC TEST SHAPE: a test is just a function whose name starts with test_.
It does something, then uses "assert" to state what must be true. If an
assert is false, the test fails. If all asserts are true, it passes.
=============================================================================
"""

import pytest


"""
TEST: resident gets 403 on staff routes
A resident must not open staff pages.
Example: Priya (a resident) types /staff/dashboard in her browser -> she gets 403 (forbidden).

@pytest.mark.parametrize runs the SAME test several times with different
values. Here the test runs twice: once with path="/staff/dashboard" and once
with path="/staff/complaints". It saves us from copy-pasting the test.
"""
@pytest.mark.parametrize("path", ["/staff/dashboard", "/staff/complaints"])
def test_resident_gets_403_on_staff_routes(resident_client, path):
    # resident_client is a fixture (see conftest.py): a browser logged in as a
    # resident. A resident must be blocked from staff pages.
    assert resident_client.get(path).status_code == 403


"""
TEST: staff gets 403 on resident routes
Staff must not open resident-only pages.
Example: a staff member opens /bills (a resident's own bill page) -> 403.
"""
@pytest.mark.parametrize("path", ["/bills", "/complaints/new"])
def test_staff_gets_403_on_resident_routes(staff_client, path):
    # The reverse: staff must be blocked from resident-only pages.
    assert staff_client.get(path).status_code == 403


"""
TEST: unauthenticated request gets 401
Someone who is not logged in is turned away from every protected page.
Example: a stranger opens /bills without logging in -> 401 (please log in).
"""
@pytest.mark.parametrize(
    "path",
    ["/bills", "/me", "/staff/dashboard", "/staff/complaints", "/complaints", "/complaints/new"],
)
def test_unauthenticated_request_gets_401(client, path):
    # "client" is the anonymous browser (not logged in). Every protected page
    # must answer 401. This test runs 6 times, once per path in the list.
    assert client.get(path).status_code == 401


"""
TEST: staff can reach staff routes
The happy path: staff CAN open staff pages.
Example: a staff member opens /staff/dashboard -> 200 (the page loads).
"""
def test_staff_can_reach_staff_routes(staff_client):
    # The "happy path": the right role CAN open its own pages (200 = success).
    # This guards against a bug where we block everyone, including the right people.
    assert staff_client.get("/staff/dashboard").status_code == 200
    assert staff_client.get("/staff/complaints").status_code == 200


"""
TEST: resident can reach resident routes
The happy path: a resident CAN open their own pages.
Example: a resident opens /bills and sees their bill -> 200.
"""
def test_resident_can_reach_resident_routes(resident_client, bill):
    """
    "bill" is listed so a bill exists in the database; the /bills page needs
    one to show. We never use the bill variable directly, we just need
    pytest to run that fixture.
    """
    assert resident_client.get("/bills").status_code == 200
    assert resident_client.get("/complaints/new").status_code == 200


"""
TEST: wrong password does not log in
A wrong password must not log anyone in.
Example: right email, password "wrong" -> the login form shows
"Invalid email or password", and /me still says 401 (not logged in).
"""
def test_wrong_password_does_not_log_in(client, resident_user):
    # resident_user makes sure the account exists, so the only thing wrong
    # is the password.
    response = client.post(
        "/login",
        data={"email": "resident@test.com", "password": "wrong"},
        follow_redirects=False,
    )
    assert response.status_code == 200  # re-renders the form, no redirect
    # "x in y" checks whether text x appears inside text y. response.text is
    # the HTML the server sent back.
    assert "Invalid email or password" in response.text
    # Proof that login really failed: /me needs a login, and we still get 401.
    assert client.get("/me").status_code == 401
