from datetime import datetime

from app.username_generator import generate_username, existing_usernames


def test_username_deterministic():
    date = datetime(2023, 1, 1)
    u1 = generate_username("male", date)
    existing_usernames.clear()
    u2 = generate_username("male", date)
    assert u1 == u2


def test_username_uniqueness():
    date = datetime(2023, 1, 2)
    u1 = generate_username("female", date)
    u2 = generate_username("female", date)
    assert u1 != u2

