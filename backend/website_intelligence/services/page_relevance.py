from urllib.parse import urlparse


IGNORED_PATHS = [
    "/login",
    "/signup",
    "/register",
    "/logout",
    "/cart",
    "/checkout",
    "/account",
    "/author/",
    "/tag/",
    "/search",
]


def is_relevant_page(url):

    parsed = urlparse(url)

    path = parsed.path.lower()

    for ignored_path in IGNORED_PATHS:

        if path.startswith(ignored_path):
            return False

    return True