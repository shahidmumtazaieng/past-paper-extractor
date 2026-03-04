"""
Past Paper Question Extractor
==============================
Entry point for the application.
Run: python main.py
"""

import sys
import os

# Ensure the app root is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from log_config import configure_logging
configure_logging()

from ui.app import PastPaperApp


def main():
    app = PastPaperApp()
    app.mainloop()


if __name__ == "__main__":
    main()
