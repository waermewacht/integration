"""All source templates, by key.

Each maker has its module (profiles.py holds the core and the Bosch
templates); this module only collects them, so the makers' modules can
import from profiles.py without a cycle.
"""

from __future__ import annotations

from .profiles import BOSCH_HOMECOM, EMS_ESP, Template
from .profiles_esphome_ecodan import ESPHOME_ECODAN
from .profiles_f1p import F1P
from .profiles_heishamon import HEISHAMON
from .profiles_idm import IDM
from .profiles_lambda import LAMBDA
from .profiles_luxtronik import LUXTRONIK
from .profiles_melcloud import MELCLOUD
from .profiles_stiebel import STIEBEL_ISG
from .profiles_vaillant import VAILLANT
from .profiles_viessmann import VICARE
from .profiles_waterkotte import WATERKOTTE

TEMPLATES: dict[str, Template] = {
    t.key: t
    for t in (
        EMS_ESP,
        BOSCH_HOMECOM,
        LUXTRONIK,
        STIEBEL_ISG,
        HEISHAMON,
        LAMBDA,
        IDM,
        VICARE,
        MELCLOUD,
        VAILLANT,
        F1P,
        WATERKOTTE,
        ESPHOME_ECODAN,
    )
}
