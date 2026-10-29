"""Dashboard-only native plugin; its manifest declares the UI and API."""


def register(ctx):
    """No model tools or background hooks are registered by this application."""
    return None
