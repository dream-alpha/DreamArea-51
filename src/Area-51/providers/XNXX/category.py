#!/usr/bin/env python3
# Copyright (C) 2018-2026 by dream-alpha
# License: GNU General Public License v3.0 (see LICENSE file for details)

"""
XNXX Category Management

This module handles all category-related functionality for the XNXX provider,
including category discovery and metadata extraction.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin
from debug import get_logger
from string_utils import sanitize_for_json
from auth_utils import get_headers

logger = get_logger(__file__)


class Category:
    """Handles XNXX category management and scraping"""

    def __init__(self, provider):
        """Initialize with reference to parent provider"""
        self.provider = provider

    def get_categories(self) -> list[dict[str, str]]:
        """Get XNXX categories by scraping JSON from main page"""
        try:
            headers = get_headers("browser")

            response = self.provider.session.get(self.provider.base_url, headers=headers, timeout=30)
            response.raise_for_status()

            html = response.text
            xvideos_categories = []

            # XNXX has categories in JavaScript - use regex to extract individual entries
            # Find individual category entries using regex patterns
            # Pattern matches: {"label":"CategoryName","url":"/search/category","nbvids":12345...}
            category_patterns = re.findall(
                r'\{"label":"([^"]+)","url":"([^"]+)"[^}]*"nbvids":(\d+)[^}]*\}', html
            )

            for label, url, nbvids in category_patterns[:100]:  # Limit to reasonable number
                # Clean up the category name and URL
                category_name = sanitize_for_json(label)
                category_name = category_name.replace("\\/", "/")

                # Clean up the URL - remove escape characters
                clean_url = url.replace("\\/", "/")

                # Skip very generic categories and navigation items
                skip_categories = ["more", "preview", "suggestions", "porn games", "sex stories", "photos", "best of"]

                # Skip premium-only categories that don't have free content
                premium_only_categories = ["shemale", "gay porn", "gay", "trans", "transgender"]

                has_valid_length = category_name and 1 < len(category_name) < 40
                is_not_generic = category_name.lower() not in skip_categories
                is_not_premium_only = category_name.lower() not in premium_only_categories
                has_no_html_chars = not any(char in category_name for char in ("<", ">", "\\"))
                has_enough_videos = int(nbvids) > 1000

                if has_valid_length and is_not_generic and is_not_premium_only and has_no_html_chars and has_enough_videos:
                    full_url = (
                        urljoin(self.provider.base_url, clean_url)
                        if not clean_url.startswith("http")
                        else clean_url
                    )

                    category_data = {
                        "name": sanitize_for_json(category_name),
                        "url": full_url,
                        "thumbnail": "",  # XNXX doesn't provide category thumbnails
                        "video_count": nbvids,
                        "site": "xnxx",
                        "category_id": self._extract_category_id(clean_url),
                    }
                    xvideos_categories.append(category_data)

            # Sort categories alphabetically
            xvideos_categories.sort(key=lambda cat: cat['name'].lower())

            logger.info("Found %d XNXX categories", len(xvideos_categories))
            return xvideos_categories

        except Exception as e:
            logger.info("Error getting XNXX categories: %s", e)
            return []

    def _extract_category_id(self, url: str) -> str:
        """Extract category ID from URL"""
        if not url:
            return ""

        # Extract from XNXX URL patterns
        patterns = [
            r'/search/([^/?]+)',
            r'/c/([^/?]+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)

        return ""
