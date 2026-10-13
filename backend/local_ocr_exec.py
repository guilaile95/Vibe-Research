"""Isolated local OCR child launcher; internal fixed arguments only.

Invoked with the server interpreter in isolated/no-site mode. Resource limits
apply before exec and survive into the native executable and its children.
"""
import os
import resource
import sys


def main():
    if not sys.platform.startswith("linux") or len(sys.argv) < 2:
        raise SystemExit(78)
    # All budgets are fixed server constants, never user settings.
    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (90, 90))
    resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.execv(sys.argv[1], sys.argv[1:])


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError):
        raise SystemExit(78)
