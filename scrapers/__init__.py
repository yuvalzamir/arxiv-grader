"""
scrapers/ — Publisher scraper registry.

To add a new publisher family:
  1. Create scrapers/<publisher>.py with a class implementing BaseScraper
  2. Add it to SCRAPERS below with the publisher key matching fields.json
"""

from .acm import ACMScraper
from .acs import ACSScraper
from .aip import AIPScraper
from .aps import APSScraper
from .cambridge import CambridgeScraper
from .cell import CellScraper
from .edp import EDPScraper
from .elsevier import ElsevierGeneralScraper, ElsevierScraper
from .ieee import IEEEScraper
from .iop import IOPScraper
from .nature import NatureScraper
from .optica import OpticaScraper
from .oup import OUPScraper
from .plos import PlosScraper
from .pnas import PnasScraper
from .royalsociety import RoyalSocietyScraper
from .science import ScienceScraper
from .scipost import SciPostScraper
from .springer import SpringerScraper
from .tandfonline import TandfonlineScraper
from .wiley import WileyScraper

SCRAPERS: dict = {
    "acm":          ACMScraper,
    "acs":          ACSScraper,
    "aip":          AIPScraper,
    "aps":          APSScraper,
    "cambridge":    CambridgeScraper,
    "cell":         CellScraper,
    "edp":          EDPScraper,
    "elsevier":         ElsevierScraper,
    "elsevier_general": ElsevierGeneralScraper,
    "ieee":         IEEEScraper,
    "iop":          IOPScraper,
    "nature":       NatureScraper,
    "optica":       OpticaScraper,
    "oup":          OUPScraper,
    "plos":         PlosScraper,
    "pnas":         PnasScraper,
    "royalsociety": RoyalSocietyScraper,
    "science":      ScienceScraper,
    "scipost":      SciPostScraper,
    "springer":     SpringerScraper,
    "tandfonline":  TandfonlineScraper,
    "wiley":        WileyScraper,
}
