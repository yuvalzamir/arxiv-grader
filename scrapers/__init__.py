"""
scrapers/ — Publisher scraper registry.

To add a new publisher family:
  1. Create scrapers/<publisher>.py with a class implementing BaseScraper
  2. Add it to SCRAPERS below with the publisher key matching fields.json
"""

from .acs import ACSScraper
from .aps import APSScraper
from .cell import CellScraper
from .nature import NatureScraper
from .optica import OpticaScraper
from .plos import PlosScraper
from .pnas import PnasScraper
from .science import ScienceScraper
from .wiley import WileyScraper

SCRAPERS: dict = {
    "acs":     ACSScraper,
    "aps":     APSScraper,
    "cell":    CellScraper,
    "nature":  NatureScraper,
    "optica":  OpticaScraper,
    "plos":    PlosScraper,
    "pnas":    PnasScraper,
    "science": ScienceScraper,
    "wiley":   WileyScraper,
}
