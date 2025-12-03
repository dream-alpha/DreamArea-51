#!/usr/bin/env python3
# Copyright (C) 2018-2026 by dream-alpha
# License: GNU General Public License v3.0 (see LICENSE file for details)

"""
XNXX Video Processing

This module handles all video-related functionality for the XNXX provider,
including video discovery, extraction, and metadata processing.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from debug import get_logger
from string_utils import sanitize_for_json
from auth_utils import get_headers
from constants import MAX_VIDEOS

logger = get_logger(__file__)


class Video:
    """Handles XNXX video processing and extraction"""

    def __init__(self, provider):
        """Initialize with reference to parent provider"""
        self.provider = provider

    def get_media_items(self, category: dict, _page: int = 1, limit: int = MAX_VIDEOS) -> list[dict[str, Any]]:
        """Get media items for a specific category"""
        url = category.get("url", "none")
        logger.info("Getting media items from URL: %s, limit: %d", url, limit)

        try:
            headers = get_headers("browser")

            response = self.provider.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()

            html = response.text
            soup = BeautifulSoup(html, "html.parser")
            videos = []

            # Try to find video containers - XNXX uses multiple possible structures
            containers = (
                soup.select(".mozaique .thumb-block")
                or soup.select(".thumb-block")
                or soup.select("div[class*='thumb']")
                or soup.select(".video-block")
                or soup.select("div[class*='video']")
            )
            logger.info("Found %d containers on XNXX page", len(containers))

            # Debug: Log the actual HTML structure for troubleshooting
            if not containers:
                logger.warning("No video containers found. Page structure may have changed.")
                # Log first few divs to help debug structure
                all_divs = soup.find_all('div', limit=10)
                for i, div in enumerate(all_divs):
                    logger.debug("Div %d classes: %s", i, div.get('class', []))

            if containers:
                logger.info("Processing %d video containers found", len(containers))
                for i, container in enumerate(containers):
                    try:
                        # XNXX structure: .thumb-under p a contains the title and URL
                        title_link = container.select_one(".thumb-under p a")
                        if not title_link:
                            logger.debug("No title link found in container")
                            continue

                        href = title_link.get("href", "")
                        if not href:
                            logger.debug("No href found in title link")
                            continue

                        if not href.startswith("http"):
                            href = urljoin(self.provider.base_url, href)

                        # Get title from title attribute or text content
                        title = title_link.get("title", "") or title_link.get_text(strip=True)
                        if not title:
                            logger.debug("No title found for href: %s", href)
                            continue

                        # Get thumbnail from .thumb img with data-src attribute
                        img = container.select_one(".thumb img")
                        thumbnail = ""
                        if img:
                            thumbnail = img.get("data-src", img.get("src", ""))
                            if thumbnail and not thumbnail.startswith("http"):
                                thumbnail = f"https:{thumbnail}" if thumbnail.startswith("//") else thumbnail

                        # Get metadata (duration, views)
                        duration = "Unknown"
                        views = "0"

                        metadata = container.select_one(".metadata")
                        if metadata:
                            # Views are in .right span
                            views_elem = metadata.select_one(".right")
                            if views_elem:
                                views_text = views_elem.get_text(strip=True)
                                views = views_text.split()[0] if views_text else "0"

                        # Extract video title and clean it
                        clean_title = sanitize_for_json(title)

                        # Add the video without resolving the URL
                        video_data = {
                            "title": clean_title,
                            "duration": duration,
                            "url": href,
                            "page_url": href,           # Keep original page URL for reference
                            "thumbnail": thumbnail,
                            "views": views,
                            "provider_id": self.provider.provider_id,
                            "format": "mp4",
                        }

                        videos.append(video_data)
                        logger.debug("Prepared video %d: %s", i + 1, video_data.get('title', 'No title'))

                    except Exception as e:
                        logger.warning("Error processing video container: %s", e, exc_info=True)
                        continue

                logger.info("Found %d videos from XNXX", len(videos))
            else:
                logger.info("No video containers found on XNXX page")

            # Apply limit if specified
            if limit and len(videos) > limit:
                logger.info("Limiting results from %d to %d videos", len(videos), limit)
                videos = videos[:limit]

            logger.info("Returning %d videos (limit: %d)", len(videos), limit)
            return videos

        except Exception as e:
            logger.info("Error getting video list from XNXX: %s", e)
            return []
