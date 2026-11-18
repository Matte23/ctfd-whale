from .config import fill_missing_configs


def setup_default_configs():
    """Fill in missing settings. Safe to run on every startup."""
    fill_missing_configs()
