#!/usr/bin/env python3
# Copyright (C) 2018-2026 by dream-alpha
# License: GNU General Public License v3.0 (see LICENSE file for details)

"""
XVideos Category Management

This module handles category extraction and processing for XVideos provider.
Supports multiple parsing methods including JSON-LD structured data and regex fallbacks.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urljoin
from auth_utils import get_headers
from string_utils import sanitize_for_json
from debug import get_logger
from constants import MAX_CATEGORIES

logger = get_logger(__file__)


class CategoryManager:
    """Manages XVideos category extraction and processing"""

    def __init__(self, session, base_provider):
        """Initialize category manager with session and base provider utilities"""
        self.session = session
        self.base_provider = base_provider
        self.base_url = "https://www.xvideos.com/"

    def get_categories(self) -> list[dict[str, str]]:
        """Get XVideos categories by scraping multiple sources"""
        xvideos_categories = []
        headers = get_headers("browser")

        # Try parsing JSON-LD data first
        try:
            # Try accessing a category page to get structured data
            for category_type in ("categories", "tags"):
                try:
                    url = f"{self.base_url}{category_type}"
                    response = self.session.get(url, headers=headers, timeout=30)
                    html = response.text

                    # Look for JSON-LD data
                    json_ld_match = re.search(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL)
                    if json_ld_match:
                        try:
                            data = json.loads(json_ld_match.group(1))
                            # Extract categories from JSON-LD if available
                            if isinstance(data, dict) and 'itemList' in data:
                                for item in data['itemList']:
                                    if isinstance(item, dict):
                                        name = item.get('name', '').strip()
                                        url = item.get('url', '').strip()
                                        if name and url:
                                            xvideos_categories.append({
                                                "name": name,
                                                "url": url,
                                                "video_count": "N/A"
                                            })
                        except json.JSONDecodeError:
                            pass

                    if xvideos_categories:
                        break
                except Exception:
                    continue

            # If still no categories, try regex parsing
            if not xvideos_categories:
                response = self.session.get(self.base_url, headers=headers, timeout=30)
                html = response.text

                # Regex patterns for category links
                patterns = [
                    r'<a[^>]*href="(/c/[^"]+)"[^>]*>([^<]+)</a>',
                    r'<a[^>]*href="([^"]*categories/[^"]*)"[^>]*>([^<]+)</a>',
                ]

                for pattern in patterns:
                    matches = re.findall(pattern, html, re.IGNORECASE)
                    for href, name in matches:
                        if href and name and len(name.strip()) > 1:
                            # Clean up the name and URL
                            clean_name = sanitize_for_json(name)
                            if clean_name:
                                full_url = urljoin(self.base_url, href)
                                xvideos_categories.append({
                                    "name": clean_name,
                                    "url": full_url,
                                    "video_count": "N/A"
                                })

                # Remove duplicates
                seen_names = set()
                unique_categories = []
                for category in xvideos_categories:
                    if category["name"] not in seen_names:
                        seen_names.add(category["name"])
                        unique_categories.append(category)
                xvideos_categories = unique_categories

            # Sort categories alphabetically by name
            xvideos_categories.sort(key=lambda x: x['name'].lower())

            logger.info("XVideos categories loaded: %d", len(xvideos_categories))

            # Apply natural capping - return up to MAX_CATEGORIES if available
            return xvideos_categories[:MAX_CATEGORIES] if len(xvideos_categories) > MAX_CATEGORIES else xvideos_categories

        except Exception as e:
            logger.info("Error getting XVideos categories: %s", e)
            return []  # Return empty list instead of fallback
