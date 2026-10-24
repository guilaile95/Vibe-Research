"""Production routes with only the isolated fixture's domain clock replaced."""
from temporal_clock import install

install()
from app import app  # noqa: E402
