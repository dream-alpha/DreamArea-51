#!/usr/bin/env python3
# Copyright (C) 2018-2026 by dream-alpha
# License: GNU General Public License v3.0 (see LICENSE file for details)

"""
xHamster Resolver Implementation

This module contains the xHamster resolver class with methods for:
- Resolving xHamster video page URLs to streaming URLs
- Extracting video metadata and quality options
- Handling advanced anti-403 protections
"""

from __future__ import annotations

import os
import sys
import re
import json
from typing import Any
from base_resolver import BaseResolver
from auth_utils import AuthTokens
from quality_utils import select_best_source, extract_metadata_from_url
from debug import get_logger

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = get_logger(__file__)


class Resolver(BaseResolver):
    """xHamster URL resolver with anti-403 protection"""

    def __init__(self, args: dict):
        super().__init__(args)
        self.auth_tokens = AuthTokens()

    def resolve_url(self) -> dict[str, Any] | None:
        """
        Resolve xHamster video URL to streaming sources using centralized auth utilities.
        """

        logger.info("=== xHamster Resolver START ===")
        logger.info("Resolving xHamster URL: %s", self.url)
        logger.info("Video title from args: %s", self.resolve_result.get("title", "N/A"))
        logger.info("Provider ID: %s", self.provider_id)

        # Use centralized authentication with fallback methods
        html = self.auth_tokens.fetch_with_fallback(self.url, "https://xhamster.com")

        if html:
            sources = self._parse_html_for_sources(html)
            if sources:
                logger.info("URL resolution successful using method: %s", self.auth_tokens.method)

                # Select the optimal quality URL from available sources using quality preference
                best_source = select_best_source(sources, self.quality, codec_aware=True, av1=self.av1)
                resolved_url = best_source["url"] if best_source else self.url

                # Check if the resolved URL is a template URL and use base resolver template resolution
                if self._is_template_url(resolved_url):
                    logger.info("Detected template URL, using base resolver template resolution")
                    template_resolved_url = self._resolve_template_url(resolved_url, self.quality)
                    if template_resolved_url and template_resolved_url != resolved_url:
                        resolved_url = template_resolved_url
                        logger.info("Template resolved: %s", resolved_url[:100] + "..." if len(resolved_url) > 100 else resolved_url)

                logger.info("Selected quality: %s (requested: %s) - %s",
                            best_source.get("quality", "Unknown") if best_source else "None",
                            self.quality,
                            resolved_url)

                # Additional debugging for xHamster CDN URLs
                if "xhcdn.com" in resolved_url:
                    logger.info("xHamster CDN URL detected - ensuring proper headers are set")
                    if "referer=" in resolved_url.lower():
                        logger.info("URL contains referer validation - headers are critical for playback")

                # Determine recorder type based on URL characteristics
                recorder_id = self.determine_recorder_id(resolved_url)

                # Convert to FFmpeg format
                ffmpeg_headers = self.auth_tokens.get_ffmpeg_headers()

                # Ensure the session has the updated headers
                session = self.auth_tokens.session
                if session:
                    # Ensure critical headers are set for xHamster CDN access
                    # xHamster CDN requires proper Referer header
                    session.headers["Referer"] = "https://xhamster.com/"
                    session.headers["Origin"] = "https://xhamster.com"
                    logger.info("Updated session headers for xHamster CDN access")

                self.resolve_result.update({
                    "resolved_url": resolved_url,
                    "session": session,
                    "ffmpeg_headers": ffmpeg_headers,
                    "recorder_id": recorder_id,
                })
                logger.info("=== xHamster Resolver END (SUCCESS) ===")
                logger.info("Final resolved URL: %s", resolved_url[:100] + "..." if len(resolved_url) > 100 else resolved_url)
                logger.info("Final video title: %s", self.resolve_result.get("title", "N/A"))
                return self.resolve_result

        # If all methods failed
        logger.error("All resolution methods failed for xHamster URL")
        return None

    def _get_video_id(self) -> str:
        """Extract video ID from URL for caching purposes"""
        match = re.search(r'xhamster\.com/videos/([^/]+)-(\d+)', self.url)
        if match:
            return match.group(2)
        return ""

    def _parse_qualities_from_url_params(self, url: str) -> list[str]:
        """
        Parse available qualities from URL parameters (xHamster style).

        Args:
            url (str): URL to parse

        Returns:
            list[str]: List of available qualities
        """
        # Parse available qualities from the URL
        # Example: multi=256x144:144p:,426x240:240p:,854x480:480p:

        multi_pattern = r'multi=([^/&]+)'
        multi_match = re.search(multi_pattern, url)

        if multi_match:
            multi_string = multi_match.group(1)
            # Extract quality info: resolution:quality (comma or end-of-string after quality)
            # Example: 256x144:144p,426x240:240p,854x480:480p
            quality_pattern = r'(\d+x\d+):(\d+p)'
            quality_matches = re.findall(quality_pattern, multi_string)

            qualities = [quality for _resolution, quality in quality_matches]

            if qualities:
                logger.info("Parsed qualities from URL parameters: %s", qualities)
                return qualities

        return []

    def _parse_html_for_sources(self, html: str) -> list[dict[str, Any]]:
        """Parse HTML content to extract video sources"""
        if not html:
            return []

        sources = []
        method_counts = {"method1": 0, "method2": 0, "method3": 0, "method4": 0}

        # Method 1: Pattern for JSON url/label pairs (most common in xHamster)
        json_pattern = r'"url":"([^"]+)"[^}]*"label":"([^"]+)"'
        json_matches = re.findall(json_pattern, html, re.IGNORECASE)

        for video_url, quality_label in json_matches:
            # Clean up the URL (unescape JSON)
            clean_url = (
                video_url.replace("\\/", "/").replace("\\\\", "").replace("\\", "")
            )

            # Skip non-video URLs (filter out thumbnails and ads)
            if not clean_url or not any(
                indicator in clean_url.lower()
                for indicator in ("mp4", "m3u8", "video")
            ):
                continue

            # Skip thumbnail URLs
            if "thumb" in clean_url.lower():
                continue

            # Skip preview/trailer URLs - these are usually short clips
            # Look for indicators like "preview", "trailer", "sample" in the URL
            if any(indicator in clean_url.lower() for indicator in ("preview", "trailer", "sample", "promo")):
                logger.info("Skipping preview/trailer URL: %s", clean_url)
                continue

            # Extract metadata from URL
            metadata = extract_metadata_from_url(clean_url)

            # For M3U8 URLs, check if they are master playlists (adaptive streams)
            # Master playlists should be marked as "adaptive" so they get expanded
            if metadata.get("format") == "m3u8":
                # If URL contains indicators of a master playlist, mark as adaptive
                # Master playlists typically have patterns like:
                # - /multi= (xHamster master with quality list)
                # - /_TPL_ (template URL for different qualities)
                # - /master.m3u8
                if any(indicator in clean_url.lower() for indicator in ("/multi=", "/_tpl_", "/master.m3u8", "master=")):
                    metadata["quality"] = "adaptive"
                    logger.info("1: Detected master playlist (adaptive), will be expanded")
                elif quality_label and quality_label != "adaptive":
                    # Single quality M3U8 (not master)
                    metadata["quality"] = quality_label
            elif quality_label and quality_label != "adaptive":
                # Non-M3U8 formats use the label directly
                metadata["quality"] = quality_label

            logger.info("1: Found source - Quality: %s, URL: %s", metadata.get("quality", "Unknown"), clean_url[:80] + "..." if len(clean_url) > 80 else clean_url)
            sources.append({"url": clean_url, **metadata})
            method_counts["method1"] += 1

        logger.info("Method 1 (JSON url/label): Found %d sources", method_counts["method1"])

        # Method 2: Look for xHamster's newer player format (newer site versions)
        # Try multiple patterns for different player initialization formats
        player_patterns = [
            r'window\.initPlayer\s*\(\s*(\{.+?\})\s*\)',  # window.initPlayer({...})
            r'initPlayer\s*\(\s*(\{.+?\})\s*\)',          # initPlayer({...})
            r'playerInitConfig\s*=\s*(\{.+?\});',          # playerInitConfig = {...};
            r'sources\s*:\s*(\[.+?\])',                    # sources: [...]
        ]

        for pattern in player_patterns:
            player_match = re.search(pattern, html, re.DOTALL)
            if player_match:
                logger.info("Found player init with pattern: %s", pattern[:50])
                try:
                    player_data_str = player_match.group(1)

                    # Try to parse as JSON
                    try:
                        player_data = json.loads(player_data_str)
                    except json.JSONDecodeError:
                        # Fix potential JSON issues
                        player_data_str = re.sub(r'([{,])\s*(\w+):', r'\1"\2":', player_data_str)
                        player_data_str = player_data_str.replace("'", '"')
                        player_data = json.loads(player_data_str)

                    # Handle both formats: {sources: [...]} and just [...]
                    source_list = player_data if isinstance(player_data, list) else player_data.get("sources", [])

                    if source_list:
                        for source in source_list:
                            if isinstance(source, dict) and "url" in source:
                                url = source["url"].replace("\\/", "/")
                                metadata = extract_metadata_from_url(url)

                                # For M3U8 URLs, check if they are master playlists
                                quality_from_json = source.get("quality") or source.get("label")
                                if metadata.get("format") == "m3u8":
                                    # Detect master playlists and mark as adaptive
                                    if any(indicator in url.lower() for indicator in ("/multi=", "/_tpl_", "/master.m3u8", "master=")):
                                        metadata["quality"] = "adaptive"
                                        logger.info("2: Detected master playlist (adaptive), will be expanded")
                                    elif quality_from_json:
                                        metadata["quality"] = quality_from_json
                                elif quality_from_json:
                                    metadata["quality"] = quality_from_json

                                logger.info("2: Found source - Quality: %s, URL: %s", metadata.get("quality", "Unknown"), url[:80] + "..." if len(url) > 80 else url)
                                sources.append({"url": url, **metadata})
                                method_counts["method2"] += 1
                        break  # Found sources, stop trying patterns
                except (json.JSONDecodeError, AttributeError) as e:
                    logger.warning("Failed to parse player data with pattern %s: %s", pattern[:30], e)
                    continue

        logger.info("Method 2 (player init): Found %d sources", method_counts["method2"])

        # Method 3: Direct MP4 URLs (main video streams only)
        mp4_pattern = (
            r'(https?://video[^\s"<>]*\.mp4[^\s"<>]*)'  # Focus on video CDN URLs
        )
        mp4_matches = re.findall(mp4_pattern, html, re.IGNORECASE)

        for mp4_url in mp4_matches:
            if mp4_url and mp4_url not in [s["url"] for s in sources]:
                # Skip if this is actually an HLS URL (ends with .m3u8)
                if mp4_url.lower().endswith('.m3u8'):
                    continue

                # Skip thumbnails
                if "thumb" in mp4_url.lower():
                    continue

                # Skip preview/trailer URLs
                if any(indicator in mp4_url.lower() for indicator in ("preview", "trailer", "sample", "promo")):
                    logger.info("Skipping preview/trailer URL: %s", mp4_url)
                    continue

                # Extract metadata from URL with fallback quality
                metadata = extract_metadata_from_url(mp4_url)
                if not metadata["quality"]:
                    metadata["quality"] = "480p"  # Fallback quality

                logger.info("3: Found source - Quality: %s, URL: %s", metadata.get("quality", "Unknown"), mp4_url)
                sources.append({"url": mp4_url, **metadata})
                method_counts["method3"] += 1

        logger.info("Method 3 (direct MP4): Found %d sources", method_counts["method3"])

        # Method 4: HLS manifest URLs (for adaptive streaming)
        # xHamster uses tokenized CDN URLs ending in /media (not .m3u8 extension)
        # Example: https://video-cf.xhcdn.com/I5oRdGec%2F%2FhFc00g0kj%2BqIZ08SnC3flL9mGG7iDd6gM%3D/121/1761526800/media

        # Search for both .m3u8 URLs and /media CDN URLs
        hls_patterns = [
            r'(https?://[^\s"<>]*\.m3u8[^\s"<>]*)',  # Standard .m3u8 URLs with full path
        ]

        hls_matches = []
        for pattern in hls_patterns:
            hls_matches.extend(re.findall(pattern, html, re.IGNORECASE))

        for hls_url in hls_matches:
            if hls_url and hls_url not in [s["url"] for s in sources]:
                # Skip thumbnails
                if "thumb" in hls_url.lower():
                    continue

                # Skip preview/trailer URLs
                if any(indicator in hls_url.lower() for indicator in ("preview", "trailer", "sample", "promo")):
                    logger.info("Skipping preview/trailer HLS URL: %s", hls_url)
                    continue

                # For template URLs, let the base resolver handle template resolution
                # We'll mark them as adaptive for proper quality selection
                metadata = extract_metadata_from_url(hls_url)
                if not metadata["quality"]:
                    metadata["quality"] = "adaptive"  # HLS adaptive streaming - highest priority
                if "_TPL_" in hls_url and "multi=" in hls_url:
                    logger.info("Found HLS template URL, will be resolved by base template resolver")
                logger.info("4: Found source - Quality: %s, URL: %s", metadata.get("quality", "Unknown"), hls_url)
                sources.append({"url": hls_url, **metadata})
                method_counts["method4"] += 1

        logger.info("Method 4 (HLS): Found %d sources", method_counts["method4"])

        if sources:
            # Remove duplicates and sort by quality
            seen_urls = set()
            unique_sources = []
            for source in sources:
                if source["url"] not in seen_urls:
                    seen_urls.add(source["url"])
                    unique_sources.append(source)

            # Sorting is now handled internally by select_best_source()
            logger.info("Found %d sources through HTML parsing", len(unique_sources))
            return unique_sources
        return None
