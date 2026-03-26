"""
scrapers/ — Publisher scraper registry.

To add a new publisher family:
  1. Create scrapers/<publisher>.py with a class implementing BaseScraper
  2. Add it to SCRAPERS below with the publisher key matching fields.json
"""

from .aps import APSScraper
from .nature import NatureScraper
from .science import ScienceScraper

SCRAPERS: dict = {
    "aps":     APSScraper,
    "nature":  NatureScraper,
    "science": ScienceScraper,
}
