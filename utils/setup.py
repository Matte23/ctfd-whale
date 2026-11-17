from .config import fill_missing_configs


def setup_default_configs():
    """Fill in missing settings. Safe to run on every startup.

    The redirect templates (WhaleRedirectTemplate) are no longer created:
    access info comes from the router for admins and players alike.
    """
    fill_missing_configs()
