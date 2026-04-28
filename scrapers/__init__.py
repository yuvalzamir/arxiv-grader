"""
scrapers/ — Publisher scraper registry.

To add a new publisher family:
  1. Create scrapers/<publisher>.py with a class implementing BaseScraper
  2. Add it to SCRAPERS below with the publisher key matching fields.json
"""

from .acs import ACSScraper
from .aip import AIPScraper
from .aps import APSScraper
from .cambridge import CambridgeScraper
from .cell import CellScraper
from .edp import EDPScraper
from .elsevier import ElsevierScraper
from .iop import IOPScraper
from .nature import NatureScraper
from .optica import OpticaScraper
from .oup import OUPScraper
from .plos import PlosScraper
from .pnas import PnasScraper
from .royalsociety import RoyalSocietyScraper
from .science import ScienceScraper
from .scipost import SciPostScraper
from .wiley import WileyScraper

SCRAPERS: dict = {
    "acs":          ACSScraper,
    "aip":          AIPScraper,
    "aps":          APSScraper,
    "cambridge":    CambridgeScraper,
    "cell":         CellScraper,
    "edp":          EDPScraper,
    "elsevier":     ElsevierScraper,
    "iop":          IOPScraper,
    "nature":       NatureScraper,
    "optica":       OpticaScraper,
    "oup":          OUPScraper,
    "plos":         PlosScraper,
    "pnas":         PnasScraper,
    "royalsociety": RoyalSocietyScraper,
    "science":      ScienceScraper,
    "scipost":      SciPostScraper,
    "wiley":        WileyScraper,
}
