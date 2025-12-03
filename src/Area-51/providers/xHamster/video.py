#!/usr/bin/env python3
# Copyright (C) 2018-2026 by dream-alpha
# License: GNU General Public License v3.0 (see LICENSE file for details)

"""
xHamster Video Processing

This module handles all video-related functionality for the xHamster provider,
including video discovery, extraction, metadata processing, and URL resolution.
"""

from __future__ import annotations

import re
import html as html_parser
from typing import Any
from urllib.parse import urljoin
from debug import get_logger
from string_utils import clean_text, sanitize_for_json
from constants import PAGE_ENTRIES, MAX_VIDEOS

logger = get_logger(__file__)


class Video:
    """Handles xHamster video processing and extraction"""

    def __init__(self, provider):
        """Initialize with reference to parent provider"""
        self.provider = provider

    def get_media_items(self, category: dict, page: int = 1, limit: int = PAGE_ENTRIES) -> list[dict[str, Any]]:
        """Get videos from specific category on xHamster - optimized for performance"""
        category_url = category.get("url", "none")
        try:
            logger.info("Fetching videos from category: %s", category_url)

            # Fetch videos until we run out OR reach MAX_VIDEOS limit
            all_videos = []
            current_page = page

            while len(all_videos) < MAX_VIDEOS:
                url = f"{category_url}/{current_page}"
                site_result = self._get_video_list(url, current_page, PAGE_ENTRIES)  # Always fetch full page
                site_videos = site_result.get("videos", []) if site_result else []

                if not site_videos:
                    logger.info("No more videos found on page %d, stopping", current_page)
                    break

                all_videos.extend(site_videos)
                logger.info("Page %d: Found %d videos, total so far: %d", current_page, len(site_videos), len(all_videos))

                # Check if page indicates no more pages available
                if not site_result.get("has_next_page", True):
                    logger.info("No more pages available, stopping")
                    break

                current_page += 1

            if all_videos:
                # Cap at MAX_VIDEOS but don't force it - return what we actually found
                final_count = min(len(all_videos), MAX_VIDEOS)
                all_videos = all_videos[:final_count]

                logger.info("Found %d total videos from %d pages (capped at MAX_VIDEOS=%d)",
                            len(all_videos), current_page - page, MAX_VIDEOS)

                # Return site data with enhanced structure (no resolution yet)
                enhanced_videos = []
                category_name = self.provider.category_manager.extract_category_from_url(category_url)
                for video in all_videos:
                    enhanced_video = self._create_enhanced_video(video, category_name)
                    logger.info("Prepared video: %s", enhanced_video)
                    enhanced_videos.append(enhanced_video)

                # Sort videos alphabetically by title
                enhanced_videos.sort(key=lambda x: x['title'].lower())

                logger.info("Performance Summary: %d videos prepared (no resolution performed)", len(enhanced_videos))
                return enhanced_videos

            logger.info("Site scraping returned: 0 videos")
            # Try direct scraping as fallback
            logger.info("Trying direct category scraping...")
            direct_videos = self._scrape_category_direct_optimized(category_url, limit)
            if direct_videos:
                logger.info("Direct scraping returned: %d videos", len(direct_videos))
                # Sort videos alphabetically by title
                direct_videos.sort(key=lambda x: x['title'].lower())
                return direct_videos

            logger.info("All scraping methods failed - no videos available")
            return []

        except Exception as e:
            logger.info("Error getting xHamster videos: %s", e)
            return []

    def _create_enhanced_video(self, video: dict[str, Any], _category: str = "Unknown") -> dict[str, Any]:
        """Create standardized enhanced video structure from raw video data"""
        video_url = video.get("url", "").strip()
        raw_title = video.get("title", "Unknown Title").strip()
        try:
            title = html_parser.unescape(raw_title)
        except (AttributeError, TypeError):
            title = raw_title

        # Generate fallback title if missing or generic
        if not title or title in {"Unknown Title", "Unknown Video", "Video"}:
            title = f"xHamster Video {self.provider.extract_video_id(video_url)[:8]}"

        # Sanitize all strings to prevent JSON serialization issues
        clean_title = sanitize_for_json(title)
        clean_thumbnail = video.get("thumbnail", "").strip()
        clean_duration = video.get("duration", "").strip()

        return {
            "title": clean_title,
            "duration": clean_duration,
            "url": video_url,
            "thumbnail": clean_thumbnail,
            "provider_id": self.provider.provider_id,
        }

    def _get_videos_from_url(self, url: str, page: int, category: str, limit: int = PAGE_ENTRIES) -> list[dict[str, Any]]:
        """Generic method to fetch videos from a URL and return enhanced video list"""
        try:
            site_result = self._get_video_list(url, page, limit)
            site_videos = site_result.get("videos", []) if site_result else []

            if not site_videos:
                return []

            # Return site data without resolution (performance optimized)
            enhanced_videos = []
            for video in site_videos[:limit]:
                enhanced_video = self._create_enhanced_video(video, category)
                enhanced_videos.append(enhanced_video)

            # Sort videos alphabetically by title
            enhanced_videos.sort(key=lambda x: x['title'].lower())

            return enhanced_videos

        except Exception as e:
            logger.info("Error getting xHamster videos from %s: %s", url, e)
            return []

    def _get_video_list(self, url: str, page: int, _limit: int = PAGE_ENTRIES) -> dict[str, Any]:
        """Parse video list from xHamster page with enhanced title extraction"""
        try:
            headers = self.provider.get_standard_headers("scraping")

            logger.info("Fetching URL: %s", url)
            response = self.provider.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()

            # Get properly decoded text
            html = self.provider.get_response_text(response)

            logger.info("Received %d bytes of HTML", len(html))

            if not html:
                logger.error("Failed to decode response content")
                return {"videos": [], "next_page": False}

            videos = []
            seen_urls = set()  # Track URLs to avoid duplicates
            seen_video_ids = set()  # Track video IDs to catch same video with different URLs

            # xHamster video patterns - updated for current structure
            video_patterns = [
                r'<div[^>]*class="[^"]*thumb-list__item[^"]*"[^>]*>(.*?)</div>',
                r'<div[^>]*class="[^"]*thumb[^"]*"[^>]*>(.*?)</div>',
                r'<article[^>]*class="[^"]*thumb[^"]*"[^>]*>(.*?)</article>',
                r'<div[^>]*class="[^"]*video-thumb[^"]*"[^>]*>(.*?)</div>',
                r'<div[^>]*class="[^"]*thumb-list-item[^"]*"[^>]*>(.*?)</div>',
            ]

            for i, pattern in enumerate(video_patterns):
                video_matches = list(re.finditer(pattern, html, re.DOTALL | re.IGNORECASE))
                logger.info("Pattern %d matched %d elements", i, len(video_matches))

                for match in video_matches:
                    video_html = match.group(1)

                    # Extract video URL - improved patterns
                    video_url_match = re.search(
                        r'<a[^>]*href=[\'"]((?:https?://)?[^\'"\s]*(?:xhamster\.com)?[^\'"\s]*/videos/[^\'"\s]+)[\'"][^>]*>',
                        video_html, re.IGNORECASE
                    )

                    # Fallback patterns if main pattern fails
                    if not video_url_match:
                        fallback_patterns = [
                            r'href=[\'"](/videos/[^\'"\s]+)[\'"]',
                            r'href=[\'"](https?://[^\'"\s]*xhamster[^\'"\s]*/videos/[^\'"\s]+)[\'"]',
                            r'data-video-url=[\'"](.*?)[\'"]',
                        ]
                        for fallback_pattern in fallback_patterns:
                            video_url_match = re.search(fallback_pattern, video_html, re.IGNORECASE)
                            if video_url_match:
                                break

                    # Enhanced title extraction - multiple patterns for better accuracy
                    title = "Unknown Video"
                    title_patterns = [
                        # Title attribute (most reliable)
                        r'title=[\'"](.*?)[\'"]',
                        # Alt attribute on images
                        r'alt=[\'"](.*?)[\'"]',
                        # Link text content
                        r'<a[^>]*>[^<]*<[^>]*>[^<]*</[^>]*>([^<]+)</a>',
                        r'<a[^>]*>([^<]+)</a>',
                        # Span or div with title/video text
                        r'<(?:span|div)[^>]*(?:class="[^"]*title[^"]*"|title)[^>]*>([^<]+)</(?:span|div)>',
                        # Video title in data attributes
                        r'data-title=[\'"](.*?)[\'"]',
                    ]

                    for title_pattern in title_patterns:
                        title_match = re.search(title_pattern, video_html, re.IGNORECASE)
                        if title_match:
                            raw_title = title_match.group(1).strip()
                            try:
                                potential_title = html_parser.unescape(raw_title)
                            except (AttributeError, TypeError):
                                potential_title = raw_title
                            # Skip very short or generic titles
                            if len(potential_title) > 5 and potential_title.lower() not in ['video', 'watch', 'click']:
                                title = potential_title
                                break

                    # Extract thumbnail
                    img_match = re.search(
                        r'(?:data-src|src)=[\'"](https?://[^\'"\s]+\.(?:jpg|jpeg|png|webp)[^\'"\s]*)[\'"]',
                        video_html, re.IGNORECASE
                    )

                    # Extract duration with better patterns
                    duration = ""
                    duration_patterns = [
                        r'(?:duration[\'"][^>]*>|<span[^>]*duration[^>]*>)([0-9:]+)',
                        r'<(?:span|div)[^>]*class="[^"]*duration[^"]*"[^>]*>([0-9:]+)',
                        r'data-duration=[\'"](.*?)[\'"]',
                        r'([0-9]+:[0-9:]+)',  # Generic time format
                    ]

                    for duration_pattern in duration_patterns:
                        duration_match = re.search(duration_pattern, video_html, re.IGNORECASE)
                        if duration_match:
                            duration = duration_match.group(1).strip()
                            break

                    if video_url_match:
                        video_url = video_url_match.group(1)
                        if not video_url.startswith("http"):
                            video_url = urljoin(self.provider.base_url, video_url)

                        # Extract video ID to detect true duplicates (same video, different URL)
                        video_id = self.provider.extract_video_id(video_url)

                        # Skip if we've already seen this URL or video ID
                        if video_url in seen_urls or video_id in seen_video_ids:
                            logger.debug("Skipping duplicate video: %s (ID: %s)", video_url, video_id)
                            continue
                        seen_urls.add(video_url)
                        seen_video_ids.add(video_id)

                        # Clean and validate title
                        title = clean_text(title)
                        if not title or title.lower() in {'unknown video', 'video', 'untitled'}:
                            # Generate title from URL if needed
                            title = f"xHamster Video {self.provider.extract_video_id(video_url)[:8]}"

                        # Skip preview/trailer videos
                        skip_keywords = ['preview', 'trailer', 'sample', 'promo', 'teaser', 'clip']
                        video_url_lower = video_url.lower()
                        title_lower = title.lower()

                        if any(keyword in video_url_lower for keyword in skip_keywords):
                            logger.info("Skipping preview/trailer URL: %s", video_url)
                            continue

                        if any(keyword in title_lower for keyword in skip_keywords):
                            logger.info("Skipping preview/trailer by title: %s", title)
                            continue

                        # Skip videos with very short durations (< 2 minutes)
                        if duration:
                            duration_parts = duration.split(':')
                            try:
                                if len(duration_parts) == 2:  # MM:SS format
                                    minutes = int(duration_parts[0])
                                    if minutes < 2:
                                        logger.info("Skipping short video (< 2 min): %s - %s", title, duration)
                                        continue
                                elif len(duration_parts) == 3:  # HH:MM:SS format
                                    hours = int(duration_parts[0])
                                    if hours == 0:
                                        minutes = int(duration_parts[1])
                                        if minutes < 2:
                                            logger.info("Skipping short video (< 2 min): %s - %s", title, duration)
                                            continue
                            except (ValueError, IndexError):
                                pass

                        # Sanitize data to prevent JSON issues
                        clean_title = sanitize_for_json(title)
                        clean_url = video_url.strip()
                        clean_thumbnail = (img_match.group(1) if img_match else "").strip()
                        clean_duration = duration.strip()

                        video_data = {
                            "title": clean_title,
                            "duration": clean_duration,
                            "url": clean_url,
                            "thumbnail": clean_thumbnail,
                        }
                        videos.append(video_data)
                        logger.debug("Added video %d: %s - %s", len(videos), clean_title[:50], video_id)

                if videos:  # If we found videos with this pattern, stop trying others
                    break

            logger.info("Found %d videos after filtering (before limit)", len(videos))
            logger.info("Unique video IDs found: %d", len(seen_video_ids))
            if videos:
                logger.info("Sample videos: First=%s, Last=%s",
                            videos[0]['url'][-30:] if videos[0]['url'] else 'None',
                            videos[-1]['url'][-30:] if videos[-1]['url'] else 'None')

            # Check for next page
            has_next = bool(re.search(r'(?:next|>)[\'"][^>]*>', html, re.IGNORECASE))

            return {
                "videos": videos,  # Return all videos without limiting
                "page": page,
                "has_next_page": has_next,
                "total_results": len(videos),
            }

        except Exception as e:
            return {
                "videos": [],
                "page": page,
                "has_next_page": False,
                "total_results": 0,
                "error": str(e),
            }

    def _scrape_category_direct_optimized(self, category_url: str, limit: int) -> list[dict[str, Any]]:
        """Direct category scraping optimized for performance (no resolution)"""
        logger.info("Directly scraping category URL: %s", category_url)
        try:
            headers = self.provider.get_standard_headers("scraping")

            response = self.provider.session.get(category_url, headers=headers, timeout=15)
            response.raise_for_status()
            html = response.text

            # Extract video data with titles (improved extraction)
            video_data_list = []

            # Look for video containers with more complete data
            video_containers = re.findall(
                r'<(?:div|article|a)[^>]*(?:class="[^"]*video[^"]*"|href="/videos/)[^>]*>.*?</(?:div|article|a)>',
                html,
                re.DOTALL | re.IGNORECASE
            )

            for container in video_containers[:limit * 2]:  # Get more containers to filter from
                # Extract URL
                url_match = re.search(r'href="([^"]*(?:/videos/[^"]+|xhamster\.com/videos/[^"]+))"', container)
                if not url_match:
                    continue

                video_url = url_match.group(1)
                if not video_url.startswith('http'):
                    video_url = f"https://xhamster.com{video_url}"

                # Extract title - try multiple patterns
                title = ""
                title_patterns = [
                    r'title="([^"]+)"',
                    r'alt="([^"]+)"',
                    r'<[^>]*class="[^"]*title[^"]*"[^>]*>([^<]+)<',
                    r'>([^<>{]+(?:Video|HD)[^<>]*)</(?:span|div|a)',
                ]

                for title_pattern in title_patterns:
                    title_match = re.search(title_pattern, container, re.IGNORECASE)
                    if title_match:
                        raw_title = title_match.group(1).strip()
                        try:
                            potential_title = html_parser.unescape(raw_title)
                        except (AttributeError, TypeError):
                            potential_title = raw_title
                        if len(potential_title) > 10 and potential_title.lower() not in {'video', 'watch'}:
                            title = potential_title
                            break

                # Extract thumbnail
                thumbnail = ""
                img_match = re.search(r'(?:data-src|src)="([^"]+\.(?:jpg|jpeg|png|webp)[^"]*)"', container, re.IGNORECASE)
                if img_match:
                    thumbnail = img_match.group(1)

                # Extract duration
                duration = ""
                duration_match = re.search(r'(\d{1,2}:\d{2}(?::\d{2})?)', container)
                if duration_match:
                    duration = duration_match.group(1)

                video_data = {
                    "title": title,
                    "duration": duration,
                    "url": video_url,
                    "thumbnail": thumbnail
                }

                video_data_list.append(video_data)

                if len(video_data_list) >= limit:
                    break

            # Convert to enhanced video structure
            enhanced_videos = []
            category = self.provider.category_manager.extract_category_from_url(category_url)
            for video_data in video_data_list:
                enhanced_video = self._create_enhanced_video(video_data, category)
                enhanced_videos.append(enhanced_video)

            # Sort videos alphabetically by title
            enhanced_videos.sort(key=lambda x: x['title'].lower())

            logger.info("Successfully extracted %d videos (performance optimized)", len(enhanced_videos))
            return enhanced_videos

        except Exception as e:
            logger.info("Direct optimized scraping error: %s", e)
            return []
