#!/usr/bin/env python3
# Copyright (C) 2018-2026 by dream-alpha
# License: GNU General Public License v3.0 (see LICENSE file for details)

"""
XNXX Site Implementation

This module contains the XNXX provider class that coordinates:
- Category management via category.py
- Video processing via video.py
- URL resolution via resolver.py
"""

from __future__ import annotations

from typing import Any
from base_provider import BaseProvider
from debug import get_logger
from constants import MAX_VIDEOS
from .category import Category
from .video import Video

logger = get_logger(__file__)


class Provider(BaseProvider):
    """XNXX provider class - modular implementation"""

    def __init__(self, args: dict):
        super().__init__(args)
        self.base_url = "https://www.xnxx.com/"

        # Initialize modular components
        self.category_manager = Category(self)
        self.video_manager = Video(self)

    def get_categories(self) -> list[dict[str, str]]:
        """Get XNXX categories using modular category manager"""
        return self.category_manager.get_categories()

    def get_media_items(self, category: dict, page: int = 1, limit: int = MAX_VIDEOS) -> list[dict[str, Any]]:
        """Get media items using modular video manager"""
        return self.video_manager.get_media_items(category, page, limit)
