"""
scrapers/ — Publisher scraper registry.

To add a new publisher family:
  1. Create scrapers/<publisher>.py with a class implementing BaseScraper
  2. Add it to SCRAPERS below with the publisher key matching fields.json
"""

from .acs import ACSScraper
from .aps import APSScraper
from .nature import NatureScraper
from .science import ScienceScraper
from .wiley import WileyScraper

SCRAPERS: dict = {
    "acs":     ACSScraper,
    "aps":     APSScraper,
    "nature":  NatureScraper,
    "science": ScienceScraper,
    "wiley":   WileyScraper,
}
