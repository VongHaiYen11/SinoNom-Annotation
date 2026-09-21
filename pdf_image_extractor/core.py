"""Compatibility imports for the pre-refactor image API.

New code should import focused modules: ``detection``, ``processing``, and
``storage``. This module contains no implementation and keeps existing callers
working.
"""

from .detection import extract_image_pages, load_embedded_image
from .models import MAX_DCI_HEIGHT as MAX_HEIGHT, MAX_DCI_WIDTH as MAX_WIDTH, MAX_LONGEST_DIMENSION
from .processing import fit_longest_dimension as _fit_longest_dimension
from .processing import get_center_dci_portrait_crop as get_center_16_9_crop
from .processing import process_image
from .storage import save_processed_page

__all__ = ["MAX_HEIGHT", "MAX_WIDTH", "MAX_LONGEST_DIMENSION", "extract_image_pages", "get_center_16_9_crop", "load_embedded_image", "process_image", "save_processed_page", "_fit_longest_dimension"]
