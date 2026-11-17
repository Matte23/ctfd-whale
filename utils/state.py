from flask import current_app


def whale_state():
    """Per-app storage for objects that are expensive to build (clients, router).

    Lives in app.extensions instead of module or class globals, so each app
    (and each test app) gets its own.
    """
    return current_app.extensions.setdefault("whale", {})
