#!/usr/bin/env python3
# Copyright (C) 2018-2026 by dream-alpha
# License: GNU General Public License v3.0 (see LICENSE file for details)

"""
xHamster Category Management

This module handles all category-related functionality for the xHamster provider,
including category discovery, thumbnail caching, and metadata extraction.
"""

from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from debug import get_logger
from string_utils import sanitize_for_json
from constants import PAGE_ENTRIES

logger = get_logger(__file__)


class Category:
    """Handles xHamster category management and scraping"""

    def __init__(self, provider):
        """Initialize with reference to parent provider"""
        self.provider = provider
        self.cache_dir = provider.data_dir / 'thumbnails' if provider.data_dir else None
        if self.cache_dir:
            os.makedirs(self.cache_dir, exist_ok=True)

    def get_categories(self) -> list[dict[str, Any]]:
        """Get xHamster categories by scraping the live site with enhanced data structure"""
        try:
            headers = self.provider.get_standard_headers("scraping")

            # Scrape categories from the main categories page
            categories_url = f"{self.provider.base_url}categories"
            response = self.provider.session.get(categories_url, headers=headers, timeout=30)
            response.raise_for_status()

            html = self.provider.get_response_text(response)
            soup = BeautifulSoup(html, "html.parser")

            logger.info("Scraping category groups from: %s", categories_url)
            all_categories = []  # Start with empty list to populate from actual page
            seen_urls = set()  # Track URLs to avoid duplicates across groups
            seen_names = set()  # Also track category names to catch same category with different URLs

            # Add main navigation categories first (these are always available)
            main_navigation_categories = [
                {"name": "Featured", "url": f"{self.provider.base_url}"},
                {"name": "Most Viewed", "url": f"{self.provider.base_url}most-viewed"},
                {"name": "Top Rated", "url": f"{self.provider.base_url}best"},
                {"name": "Newest", "url": f"{self.provider.base_url}newest"},
            ]
            for cat in main_navigation_categories:
                all_categories.append(cat)
                normalized_url = cat["url"].rstrip('/').lower()
                # Normalize category name: lowercase, remove extra spaces, strip
                normalized_name = ' '.join(cat["name"].lower().split())
                seen_urls.add(normalized_url)
                seen_names.add(normalized_name)

            # Look for category groups using the H2 headers structure we discovered
            category_groups = soup.select('h2')
            logger.info("Found %d category group headers", len(category_groups))

            # Process each category group to find the most popular categories in each group
            for group_header in category_groups:
                group_name = group_header.get_text(strip=True)

                # Skip generic headers
                if not group_name or len(group_name) < 3:
                    continue

                logger.debug("Processing category group: %s", group_name)

                # Find the next section after this header that contains category links
                next_section = group_header.find_next_sibling()
                group_categories = []

                # Look for category links in the section following this header
                if next_section:
                    # Search within this section for category links
                    section_links = next_section.find_all('a', href=lambda x: x and '/categories/' in x)

                    for link in section_links[:8]:  # Take top 8 from each group
                        href = link.get('href', '').strip()
                        link_text = link.get_text(strip=True)

                        if not href or not link_text or len(link_text) < 2:
                            continue

                        # Make sure URL is absolute
                        if not href.startswith("http"):
                            href = urljoin(self.provider.base_url, href)

                        # Skip photo categories
                        if "/photos/" in href or "photo" in link_text.lower():
                            continue

                        # Normalize URL and name for duplicate checking
                        normalized_url = href.rstrip('/').lower()
                        # Normalize category name: lowercase, remove extra spaces, strip
                        normalized_name = ' '.join(link_text.lower().split())

                        # Skip if we've already added this URL or category name
                        if normalized_url in seen_urls:
                            logger.debug("Skipping duplicate URL: %s (from group: %s)", href, group_name)
                            continue
                        if normalized_name in seen_names:
                            logger.debug("Skipping duplicate category name: '%s' (from group: %s)", link_text, group_name)
                            continue

                        group_categories.append({
                            "name": sanitize_for_json(link_text),
                            "url": href,
                            "group": group_name
                        })
                        seen_urls.add(normalized_url)
                        seen_names.add(normalized_name)

                # Add the best categories from this group
                all_categories.extend(group_categories)
                logger.debug("Added %d categories from group '%s'", len(group_categories), group_name)

            # If we didn't get enough categories from groups, add some popular individual ones
            if len(all_categories) < 40:
                logger.info("Adding popular individual categories as fallback")
                popular_links = soup.select('a[href*="/categories/"]')
                max_categories = 2 * PAGE_ENTRIES  # Define the limit here too

                # seen_urls already maintained above, no need to rebuild it

                for link in popular_links:
                    if len(all_categories) >= max_categories:  # Stop when we reach the limit
                        break

                    href = link.get('href', '').strip()
                    link_text = link.get_text(strip=True)

                    if not href or not link_text:
                        continue

                    if not href.startswith("http"):
                        href = urljoin(self.provider.base_url, href)

                    # Normalize URL and name for duplicate checking
                    normalized_url = href.rstrip('/').lower()
                    # Normalize category name: lowercase, remove extra spaces, strip
                    normalized_name = ' '.join(link_text.lower().split())

                    if normalized_url in seen_urls:
                        continue
                    if normalized_name in seen_names:
                        continue

                    if "/photos/" in href or "photo" in link_text.lower():
                        continue

                    all_categories.append({
                        "name": sanitize_for_json(link_text),
                        "url": href,
                        "group": "Popular"
                    })
                    seen_urls.add(normalized_url)
                    seen_names.add(normalized_name)

            logger.info("Found %d total categories from groups", len(all_categories))

            # Create enhanced category data structure
            enhanced_categories = []

            # No capping - let's see natural distribution by group
            # max_categories = 2 * PAGE_ENTRIES
            # categories_to_process = all_categories[:max_categories] if len(all_categories) > max_categories else all_categories
            categories_to_process = all_categories  # Use all available categories

            for category in categories_to_process:
                category_name = category.get("name", "Unknown Category")
                category_url = category.get("url", "")
                category_group = category.get("group", "")

                enhanced_category = {
                    "name": category_name,
                    "url": category_url,
                    "thumbnail": "",  # Could add thumbnail support later if needed
                    "video_count": None,  # xHamster doesn't provide counts in category list
                    "site": "xhamster",
                    "category_id": self._extract_category_id(category_url),
                    "group": category_group,  # Add group information
                }
                enhanced_categories.append(enhanced_category)

            # Sort categories alphabetically by name
            enhanced_categories.sort(key=lambda cat: cat['name'].lower())

            logger.info("Returning %d enhanced categories from groups (no capping applied)", len(enhanced_categories))
            return enhanced_categories

        except Exception as e:
            logger.info("Error getting xHamster categories: %s", e)
            return []

    def _extract_category_id(self, url: str) -> str:
        """Extract category ID from URL"""
        if not url:
            return ""

        # Extract from various xHamster URL patterns
        patterns = [
            r'/categories/([^/]+)',
            r'/c/([^/?]+)',
            r'category=([^&]+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)

        return ""

    def extract_category_from_url(self, url: str) -> str:
        """Extract category name from URL"""
        if not url:
            return "unknown"

        patterns = [
            r'/categories/([^/?]+)',
            r'/c/([^/?]+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1).replace('-', ' ').title()

        return "Unknown"
