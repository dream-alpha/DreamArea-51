#!/usr/bin/env python3
# Copyright (C) 2018-2026 by dream-alpha
# License: GNU General Public License v3.0 (see LICENSE file for details)

"""
XVideos Site Implementation - Modular Provider

This module contains the XVideos provider coordinator that delegates to
specialized category and video managers for better code organization.
"""

from __future__ import annotations

from typing import Any
from base_provider import BaseProvider
from debug import get_logger
from constants import MAX_VIDEOS
from .category import CategoryManager
from .video import VideoManager

logger = get_logger(__file__)


class Provider(BaseProvider):
    """XVideos provider coordinator - delegates to specialized managers"""

    def __init__(self, args: dict):
        super().__init__(args)
        self.base_url = "https://www.xvideos.com/"

        # Initialize modular components
        self.category_manager = CategoryManager(self.session, self)
        self.video_manager = VideoManager(self.session, self)

    def get_categories(self) -> list[dict[str, str]]:
        """Get XVideos categories - delegates to category manager"""
        return self.category_manager.get_categories()

    def get_media_items(self, category: dict, page: int = 1, limit: int = MAX_VIDEOS) -> list[dict[str, Any]]:
        """Get videos from category - delegates to video manager"""
        return self.video_manager.get_media_items(category, page, limit)
