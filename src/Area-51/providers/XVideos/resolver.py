#!/usr/bin/env python3
# Copyright (C) 2018-2026 by dream-alpha
# License: GNU General Public License v3.0 (see LICENSE file for details)

"""
XVideos Resolver Implementation

This module contains the XVideos resolver class with methods for:
- Resolving XVideos video page URLs to streaming URLs
- Extracting video quality options and streaming formats
"""

from __future__ import annotations

import re
import json
from typing import Any
from auth_utils import AuthTokens
from quality_utils import select_best_source, extract_metadata_from_url
from debug import get_logger
from base_resolver import BaseResolver


logger = get_logger(__file__)


class Resolver(BaseResolver):
    """XVideos URL resolver"""

    def __init__(self, args: dict):
        super().__init__(args)
        self.auth_tokens = AuthTokens()

    def resolve_url(self) -> dict[str, Any] | None:
        """
        Resolve XVideos video URL to streaming sources

        Returns:
            Dictionary with resolved status and sources list (no metadata)
        """
        logger.info("Resolving XVideos URL: %s", self.url)

        try:
            # Use centralized authentication with fallback methods
            html = self.auth_tokens.fetch_with_fallback(self.url, "https://www.xvideos.com")

            if not html:
                logger.error("Failed to fetch XVideos page content")
                return None

            # Extract video sources from HTML
            sources = self._extract_sources(html)

            if not sources:
                logger.error("No video sources found")
                return None

            # Select the optimal quality URL from available sources using quality and codec preferences
            best_source = select_best_source(sources, self.quality, codec_aware=True, av1=self.av1)
            resolved_url = best_source["url"] if best_source else self.url

            logger.info("Selected quality: %s (requested: %s) - %s",
                        best_source.get("quality", "Unknown") if best_source else "None",
                        self.quality,
                        resolved_url[:100] + "..." if len(resolved_url) > 100 else resolved_url)

            # Determine recorder type based on URL characteristics
            recorder_id = self.determine_recorder_id(resolved_url)

            # Generate FFmpeg headers for HLS recorders with proper cookie handling
            ffmpeg_headers = self.auth_tokens.get_ffmpeg_headers()

            self.resolve_result.update({
                "resolved_url": resolved_url,
                "ffmpeg_headers": ffmpeg_headers,  # Include FFmpeg headers for HLS recorders
                "session": self.auth_tokens.session,  # Include authenticated session for reuse
                "recorder_id": recorder_id,
            })
            return self.resolve_result

        except Exception as e:
            logger.error("Error resolving XVideos URL: %s", e)
            return None

    def _extract_sources(self, html: str) -> list[dict[str, Any]]:
        """Extract video sources from XVideos HTML"""
        sources = []

        try:
            # Method 1: Extract from HTML5 player config
            # This pattern looks for the JavaScript player initialization data
            player_config_pattern = r'html5player\.setVideoHLS\(\'([^\']+)\'\)'
            player_match = re.search(player_config_pattern, html)

            if player_match:
                # HLS master playlist (contains multiple qualities)
                hls_url = player_match.group(1)
                if hls_url:
                    metadata = extract_metadata_from_url(hls_url)
                    if not metadata["quality"]:
                        metadata["quality"] = "adaptive"  # HLS adaptive streaming
                    sources.append({"url": hls_url, **metadata})
                    logger.info("Found HLS master playlist: %s", hls_url[:80] + "..." if len(hls_url) > 80 else hls_url)

            # Method 2: Look for direct MP4 sources (multiple qualities)
            mp4_low_pattern = r'html5player\.setVideoUrlLow\(\'([^\']+)\'\)'
            mp4_high_pattern = r'html5player\.setVideoUrlHigh\(\'([^\']+)\'\)'

            mp4_low_match = re.search(mp4_low_pattern, html)
            if mp4_low_match and mp4_low_match.group(1):
                mp4_low_url = mp4_low_match.group(1)
                metadata = extract_metadata_from_url(mp4_low_url)
                if not metadata["quality"]:
                    metadata["quality"] = "360p"  # Typically low quality
                sources.append({"url": mp4_low_url, **metadata})
                logger.info("Found low quality MP4: %s", mp4_low_url[:80] + "..." if len(mp4_low_url) > 80 else mp4_low_url)

            mp4_high_match = re.search(mp4_high_pattern, html)
            if mp4_high_match and mp4_high_match.group(1):
                mp4_high_url = mp4_high_match.group(1)
                metadata = extract_metadata_from_url(mp4_high_url)
                if not metadata["quality"]:
                    metadata["quality"] = "720p"  # Typically high quality
                sources.append({"url": mp4_high_url, **metadata})
                logger.info("Found high quality MP4: %s", mp4_high_url[:80] + "..." if len(mp4_high_url) > 80 else mp4_high_url)

            # Method 4: Extract from JSON-LD metadata
            json_ld_pattern = r'<script type="application/ld\+json">([^<]+)</script>'
            json_ld_match = re.search(json_ld_pattern, html)
            if json_ld_match:
                try:
                    json_ld = json.loads(json_ld_match.group(1))
                    if "contentUrl" in json_ld:
                        content_url = json_ld["contentUrl"]
                        # Only add if we don't already have this URL
                        if not any(s["url"] == content_url for s in sources):
                            metadata = extract_metadata_from_url(content_url)
                            if not metadata["quality"]:
                                metadata["quality"] = "720p"  # Usually high quality
                            sources.append({"url": content_url, **metadata})
                except json.JSONDecodeError:
                    logger.warning("Failed to parse JSON-LD metadata")

            # Sorting is now handled internally by select_best_source()
            return sources

        except Exception as e:
            logger.error("Error extracting sources: %s", e)
            return []
