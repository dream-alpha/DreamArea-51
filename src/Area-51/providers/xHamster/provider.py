#!/usr/bin/env python3
# Copyright (C) 2018-2026 by dream-alpha
# License: GNU General Public License v3.0 (see LICENSE file for details)

"""
xHamster Provider - Refactored

This module contains the main xHamster provider class that orchestrates
category and video management through dedicated classes.
"""

from __future__ import annotations

from typing import Any
from base_provider import BaseProvider
from debug import get_logger
from .category import Category
from .video import Video

logger = get_logger(__file__)


class Provider(BaseProvider):
    """xHamster provider class with modular architecture"""

    def __init__(self, args: dict):
        """Initialize the xHamster provider with modular components"""
        super().__init__(args)

        # Provider properties
        self.base_url = "https://xhamster.com/"

        # Ensure xHamster-specific headers are set
        self.session.headers.update({
            "Referer": "https://xhamster.com/",
            "Origin": "https://xhamster.com"
        })

        # Initialize modular components
        self.category_manager = Category(self)
        self.video_manager = Video(self)

    def get_categories(self) -> list[dict[str, Any]]:
        """Get xHamster categories using the category manager"""
        return self.category_manager.get_categories()

    def get_media_items(self, category: dict, page: int = 1, limit: int = 28) -> list[dict[str, Any]]:
        """Get videos from specific category using the video manager"""
        return self.video_manager.get_media_items(category, page, limit)
