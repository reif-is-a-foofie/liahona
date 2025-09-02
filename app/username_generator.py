from datetime import datetime
from hashlib import sha256
from typing import Dict

MALE_NAMES = [
    "adam", "abel", "enos", "noah", "moses", "abraham", "isaac", "jacob",
    "lehi", "nephi", "alma", "helaman", "mormon", "moroni",
]
FEMALE_NAMES = [
    "eve", "sarah", "rebecca", "ruth", "mary", "martha", "sariah",
    "abish", "isabel", "rhoda", "emma", "phoebe", "naomi",
]

existing_usernames: Dict[str, str] = {}


def generate_username(gender: str, signup_date: datetime) -> str:
    names = MALE_NAMES if gender.lower() == "male" else FEMALE_NAMES
    key = f"{gender}:{signup_date.isoformat()}"
    digest = sha256(key.encode()).hexdigest()
    index = int(digest, 16) % len(names)
    base_name = names[index]
    username = base_name
    counter = 1
    while username in existing_usernames:
        counter += 1
        username = f"{base_name}{counter}"
    existing_usernames[username] = key
    return username

