# This file handles password security: turning a real password into a
# scrambled ("hashed") version to store in the database, and later
# checking if a password someone types in matches that stored hash.
# We NEVER store real passwords anywhere — only their hash.

import bcrypt


def hash_password(password: str) -> str:
    # bcrypt works with bytes, not plain text, so we encode the password
    # string into bytes first (password.encode()).
    #
    # bcrypt.gensalt() creates a random "salt" — a bit of random data mixed
    # into the hash so that even if two users pick the same password, their
    # stored hashes look different. This makes the hash much harder to crack.
    #
    # bcrypt.hashpw() does the actual scrambling. The result is bytes, so we
    # decode it back into a normal string before returning it, since that's
    # what we'll store in the database (hashed_password: Mapped[str]).
    hashed_bytes = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
    return hashed_bytes.decode()


def verify_password(password: str, hashed: str) -> bool:
    # bcrypt.checkpw() takes the password someone just typed in, and the
    # stored hash, and checks whether that password would produce that same
    # hash. It returns True if they match, False if they don't. We never
    # "unscramble" the hash back into the original password — that's not
    # possible by design, we can only check if a guess matches.
    return bcrypt.checkpw(password.encode(), hashed.encode())
