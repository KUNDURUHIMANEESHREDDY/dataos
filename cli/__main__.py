"""Entry point for `python -m cli`.

Keeping this separate from cli/__init__.py avoids the RuntimeWarning that
`python -m cli.main` emits, because __init__ imports .main at package import.
"""

from .main import main

main()
