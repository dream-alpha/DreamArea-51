#!/usr/bin/env python3
# Copyright (C) 2018-2026 by dream-alpha
# License: GNU General Public License v3.0 (see LICENSE file for details)

"""
XVideos Video Management

This module handles video extraction, metadata parsing, and URL processing for XVideos provider.
Supports both old and new XVideos URL structures with search-video pattern detection.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin
from typing import Any
from bs4 import BeautifulSoup
from auth_utils import get_headers
from string_utils import sanitize_for_json
from debug import get_logger
from constants import MAX_VIDEOS

logger = get_logger(__file__)


class VideoManager:
    """Manages XVideos video extraction and processing"""

    def __init__(self, session, base_provider):
        """Initialize video manager with session and base provider utilities"""
        self.session = session
        self.base_provider = base_provider
        self.base_url = "https://www.xvideos.com/"
        self.provider_id = "xvideos"

    def get_media_items(self, category: dict, page: int = 1, limit: int = MAX_VIDEOS) -> list[dict[str, Any]]:
        """Get videos from XVideos category"""
        category_url = category.get("url", "none")
        if "?" in category_url:
            url = f"{category_url}&p={page - 1}"
        else:
            url = f"{category_url}?p={page - 1}"

        # Fetch single page - XVideos repeats content across pages, so additional pages don't add unique videos
        result = self._get_video_list(url, page, limit)
        all_videos = result.get("videos", [])

        # SAFETY CHECK: Log search URLs but allow them through for debugging XVideos structure change
        filtered_videos = []
        search_url_count = 0

        for video in all_videos:
            video_url = video.get("url", "")
            if "/search-video/" in video_url:
                search_url_count += 1
                logger.info("XVideos structure change - found search-video URL pattern")
                # Keep the video for now to see what happens
            filtered_videos.append(video)

        if search_url_count > 0:
            logger.info("XVideos returned %d search-video URLs out of %d total videos", search_url_count, len(all_videos))
            logger.info("This suggests XVideos has changed their page structure")

        # Remove duplicates based on URL (keep first occurrence)
        seen_urls = set()
        unique_videos = []
        for video in filtered_videos:
            video_url = video.get("url", "")
            if video_url not in seen_urls:
                seen_urls.add(video_url)
                unique_videos.append(video)

        logger.info("Processed %d total videos from single page, removed %d duplicates, %d unique videos remaining",
                    len(filtered_videos), len(filtered_videos) - len(unique_videos), len(unique_videos))

        # Sort videos alphabetically by title
        unique_videos.sort(key=lambda x: x['title'].lower())

        # Apply natural capping - return up to MAX_VIDEOS if available
        return unique_videos[:MAX_VIDEOS] if len(unique_videos) > MAX_VIDEOS else unique_videos

    def _get_video_list(self, url: str, page: int, limit: int = MAX_VIDEOS) -> dict[str, Any]:
        """Parse video list from XVideos page"""
        try:
            headers = get_headers("browser")
            logger.info("Fetching XVideos URL: %s", url)
            response = self.session.get(url, headers=headers, timeout=30)
            html = response.text

            logger.info("Response status: %d, Content length: %d", response.status_code, len(html))

            # Debug: Check if we got blocked or redirected
            if "Access denied" in html or "blocked" in html.lower():
                logger.error("XVideos access appears to be blocked")
            elif len(html) < 1000:
                logger.warning("Suspiciously short response from XVideos")

            # Debug: Save a snippet of the HTML to see the actual structure
            logger.info("HTML snippet (first 1000 chars): %s", html[:1000])

            # Look for video-related patterns in the HTML
            video_patterns = [
                'class="thumb',
                'class="video',
                'class="item',
                'data-id=',
                '/video.',
            ]
            for pattern in video_patterns:
                count = html.count(pattern)
                logger.info("Pattern '%s' found %d times in HTML", pattern, count)

            soup = BeautifulSoup(html, 'html.parser')
            videos = []

            # Look for video thumbnails with multiple selectors (expanded for new XVideos structure)
            video_elements = (
                soup.find_all('div', class_='thumb-block')
                + soup.find_all('div', class_='thumb')
                + soup.find_all('div', class_='mozaique')
                + soup.find_all('div', class_='thumb-inside')
                + soup.find_all('div', class_='thumb-image')
                + soup.find_all('div', class_=re.compile(r'thumb'))
                + soup.find_all('div', class_=re.compile(r'video'))
                + soup.find_all('article')  # Some sites use article tags
                + soup.find_all('div', class_=re.compile(r'item'))
            )

            logger.info("Found %d potential video elements on page", len(video_elements))

            for i, element in enumerate(video_elements[:limit]):
                try:
                    # Find the correct video link - look for the one with a title attribute
                    # XVideos has multiple links: quality indicator link and main video link
                    all_links = element.find_all('a', href=True)

                    # Find the main video link (has title attribute and longer text)
                    main_link = None
                    if i < 3:  # Debug first few elements
                        logger.debug("Element %d: Found %d links total", i, len(all_links))

                    for link in all_links:
                        if (link.get('title')
                                and len(link.get('title', '')) > 10
                                and '/video.' in link.get('href', '')):
                            main_link = link
                            if i < 3:
                                logger.debug("Element %d: Selected main_link with title='%s'", i, link.get('title', '')[:100])
                            break

                    if not main_link:
                        continue

                    href = main_link.get('href')
                    video_url = urljoin(self.base_url, href)

                    # Debug: Log element structure for first few videos
                    if i < 3:
                        logger.debug("Element %d classes: %s", i, element.get('class', []))
                        logger.debug("Element %d HTML snippet: %s", i, str(element)[:500])

                    # Extract title from the main video link
                    title = ""
                    strategy_used = ""

                    # Strategy 1: Use the title attribute from the main link (most reliable)
                    if main_link and main_link.get('title'):
                        title = main_link.get('title', '').strip()
                        strategy_used = "main_link.title"

                    # Strategy 2: Fallback to other title elements if main link title is empty
                    if not title:
                        title_elem = element.find('p', class_='title')
                        if title_elem:
                            title = title_elem.get_text().strip()
                            strategy_used = "p.title"

                    # Strategy 3: Use main link text if no title attribute
                    if not title and main_link:
                        link_text = main_link.get_text().strip()
                        # Extract title part before duration (e.g., "Title 14 min" -> "Title")
                        title = re.sub(r'\s+\d+\s+min\s*$', '', link_text).strip()
                        if title:
                            strategy_used = "main_link.text"

                    # Skip if we still don't have a valid title
                    if not title or len(title) < 3:
                        logger.debug("Skipping element with no valid title")
                        continue

                    # Debug: Log the raw title before cleaning
                    if i < 3:  # Only log first 3 for debugging
                        logger.debug("Element %d: Raw title extracted: '%s' (strategy: %s)", i, title, strategy_used)

                    # Remove duration from title if it's appended
                    # Common patterns: "Title - 12:34", "Title (12:34)", "Title 12:34"
                    # Also handle: "Title - 15 min", "Title (8 mins)", "Title 2 minutes"
                    title = re.sub(r'\s*[-\(\s]*\d{1,2}:\d{2}[\)\s]*$', '', title)
                    title = re.sub(r'\s*\d{1,2}:\d{2}\s*$', '', title)
                    title = re.sub(r'\s*[-\(\s]*\d{1,3}\s*mins?\s*[\)\s]*$', '', title, flags=re.IGNORECASE)
                    title = re.sub(r'\s*[-\(\s]*\d{1,3}\s*minutes?\s*[\)\s]*$', '', title, flags=re.IGNORECASE)

                    # Clean and sanitize title for JSON
                    title = sanitize_for_json(title)

                    # Extract duration
                    duration_elem = element.find('span', class_='duration')
                    duration = duration_elem.get_text().strip() if duration_elem else "N/A"

                    # Extract thumbnail
                    img_elem = element.find('img')
                    thumbnail = img_elem.get('data-src') or img_elem.get('src') if img_elem else ""

                    # Debug: Log final cleaned title
                    if i < 5:  # Only log first 5 for debugging
                        logger.debug("Element %d: Final title: '%s', duration: '%s'", i, title, duration)

                    # Sanity check: Don't use resolution values or poor quality titles
                    if title and re.match(r'^\d{3,4}p$', title):
                        logger.warning("Element %d: Title appears to be resolution ('%s'), skipping", i, title)
                        continue

                    # Skip obviously broken or too short titles
                    if not title or len(title.strip()) < 5:
                        logger.debug("Element %d: Title too short or empty ('%s'), skipping", i, title)
                        continue

                    # Skip titles that are mostly non-alphabetic (likely parsing errors)
                    alpha_chars = sum(1 for c in title if c.isalpha())
                    if len(title) > 10 and alpha_chars / len(title) < 0.5:
                        logger.debug("Element %d: Title has too few alphabetic characters ('%s'), skipping", i, title)
                        continue

                    videos.append({
                        "title": title,
                        "duration": duration,
                        "url": video_url,
                        "thumbnail": thumbnail,
                        "provider_id": self.provider_id,
                    })

                except Exception as e:
                    logger.info("Error parsing video element: %s", e)
                    continue

        except Exception as e:
            logger.error("Error getting video list: %s", e)
            videos = []

        logger.info("Successfully parsed %d videos from XVideos page", len(videos))

        # Check for next page
        has_next = bool(
            re.search(r'href="([^"]+)" class="no-page next-page', html, re.IGNORECASE)
        )

        return {
            "videos": videos,
            "page": page,
            "has_next_page": has_next,
            "total_results": len(videos),
        }
