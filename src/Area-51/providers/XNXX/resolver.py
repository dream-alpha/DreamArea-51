#!/usr/bin/env python3
# Copyright (C) 2018-2026 by dream-alpha
# License: GNU General Public License v3.0 (see LICENSE file for details)

"""
XNXX Resolver Implementation

This module contains the XNXX resolver class with methods for:
- Resolving XNXX video page URLs to streaming URLs
- Extracting video quality options and streaming formats
"""

from __future__ import annotations

import re
from typing import Any
import json
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from base_resolver import BaseResolver
from auth_utils import AuthTokens
from quality_utils import select_best_source, extract_metadata_from_url
from debug import get_logger

logger = get_logger(__file__)


class Resolver(BaseResolver):
    """XNXX URL resolver"""

    def __init__(self, args: dict):
        super().__init__(args)
        self.auth_tokens = AuthTokens()

    def resolve_url(self) -> dict[str, Any] | None:
        """
        Resolve XNXX URL to streaming URLs using centralized auth utilities

        Returns:
            Dictionary with resolved status and streaming information
        """
        try:
            logger.info("Resolving XNXX URL: %s", self.url)

            # Use centralized authentication with fallback methods
            html = self.auth_tokens.fetch_with_fallback(self.url, "https://www.xnxx.com")

            if not html:
                logger.error("Failed to fetch XNXX page content")
                return None
            soup = BeautifulSoup(html, "html.parser")

            sources = []

            # Method 1: Look for JavaScript video configuration
            # XNXX typically stores video URLs in window.wpn_mobile or similar variables
            js_patterns = [
                # Structured patterns with quality information
                (r'html5player\.setVideoUrlLow\(["\']([^"\']+)["\']', "360p"),
                (r'html5player\.setVideoUrlHigh\(["\']([^"\']+)["\']', "720p"),
                (r'html5player\.setVideoHLS\(["\']([^"\']+)["\']', "adaptive"),
                (r'html5player\.setVideoUrl1080p\(["\']([^"\']+)["\']', "1080p"),
                (r'html5player\.setVideoUrl720p\(["\']([^"\']+)["\']', "720p"),
                (r'html5player\.setVideoUrl480p\(["\']([^"\']+)["\']', "480p"),
                (r'html5player\.setVideoUrl360p\(["\']([^"\']+)["\']', "360p"),
                (r'html5player\.setVideoUrl240p\(["\']([^"\']+)["\']', "240p"),
                # Generic patterns
                (r'setVideoUrl\(["\']([^"\']+)["\']', "Unknown"),
                (r'video_url["\']?\s*[:=]\s*["\']([^"\']+)["\']', "Unknown"),
                (r'["\']url["\']?\s*:\s*["\']([^"\']+\.mp4[^"\']*)["\']', "Unknown"),
                (r'["\']file["\']?\s*:\s*["\']([^"\']+\.mp4[^"\']*)["\']', "Unknown"),
                # Additional patterns to catch HLS streams
                (r'["\']hls["\']?\s*[:=]\s*["\']([^"\']+\.m3u8[^"\']*)["\']', "adaptive"),
                (r'["\']url["\']?\s*[:=]\s*["\']([^"\']+\.m3u8[^"\']*)["\']', "adaptive"),
            ]

            for pattern, default_quality in js_patterns:
                matches = re.findall(pattern, html, re.IGNORECASE)
                for match in matches:
                    if match and ("http" in match or match.startswith("//")):
                        # Clean up the URL
                        clean_url = match.replace("\\/", "/").replace("\\", "")
                        if clean_url.startswith("//"):
                            clean_url = "https:" + clean_url

                        # Extract metadata from URL
                        metadata = extract_metadata_from_url(clean_url)

                        # Use default_quality if no quality extracted and it's not "Unknown"
                        if not metadata["quality"] and default_quality != "Unknown":
                            metadata["quality"] = default_quality
                        elif not metadata["quality"]:
                            # Final fallback: adaptive for HLS, 480p for MP4
                            if metadata["format"] == "m3u8":
                                metadata["quality"] = "adaptive"
                            else:
                                metadata["quality"] = "480p"

                        logger.info("Found video source: %s (%s/%s)", clean_url, metadata["quality"], metadata["format"])
                        sources.append({"url": clean_url, **metadata})

            # Method 2: Look for JSON-LD structured data
            json_scripts = soup.find_all("script", type="application/ld+json")
            for script in json_scripts:
                try:
                    data = json.loads(script.get_text())
                    if isinstance(data, dict) and "contentUrl" in data:
                        metadata = extract_metadata_from_url(data["contentUrl"])
                        if not metadata["quality"]:
                            metadata["quality"] = "480p"
                        sources.append({"url": data["contentUrl"], **metadata})
                except (ValueError, KeyError):
                    pass

            # Method 3: Look for HTML5 video elements
            video_elements = soup.find_all("video")
            for video in video_elements:
                video_sources = video.find_all("source")
                for source in video_sources:
                    src = source.get("src")
                    if src:
                        if not src.startswith("http"):
                            if src.startswith("//"):
                                src = "https:" + src
                            else:
                                src = urljoin(self.url, src)

                        # Extract metadata from URL
                        metadata = extract_metadata_from_url(src)

                        # Extract quality information from source attributes
                        source_quality = source.get("label", "")
                        if not source_quality:
                            source_quality = source.get("data-res", "")

                        # Normalize HLS quality labels to "adaptive"
                        if source_quality and ("HLS" in source_quality.upper() or source_quality.upper() == "HLS"):
                            source_quality = "adaptive"

                        # Use attribute quality if available, otherwise use extracted quality
                        if source_quality:
                            metadata["quality"] = source_quality
                        elif not metadata["quality"]:
                            # Final fallback: adaptive for HLS, 480p for MP4
                            if metadata["format"] == "m3u8":
                                metadata["quality"] = "adaptive"
                            else:
                                metadata["quality"] = "480p"

                        sources.append({"url": src, **metadata})

            # Remove duplicates and invalid URLs
            unique_sources = []
            seen_urls = set()
            for source in sources:
                source_url = source["url"]
                if (
                    source_url not in seen_urls
                    and source_url.startswith("http")
                    and any(
                        ext in source_url.lower()
                        for ext in (".mp4", ".m3u8", "video", "stream")
                    )
                ):
                    unique_sources.append(source)
                    seen_urls.add(source_url)

            if unique_sources:
                # Sorting is now handled internally by select_best_source()
                # Log the sources for debugging
                logger.info("Found video sources: %s",
                            ", ".join([f"{s['quality']}/{s['format']}" for s in unique_sources[:3]]))

                # If we have HLS streams, make sure they're prioritized
                hls_streams = [s for s in unique_sources if s["format"] == "m3u8"]
                if hls_streams:
                    logger.info("Found %d HLS streams - prioritizing them", len(hls_streams))

                # Log the best quality found
                if unique_sources:
                    logger.info("Best quality found: %s/%s",
                                unique_sources[0]["quality"], unique_sources[0]["format"])

                # Select the optimal quality URL from available sources using quality preference
                logger.info("=== XNXX RESOLVER DEBUG ===")
                logger.info("About to call select_best_source with quality='%s'", self.quality)
                logger.info("Available sources for selection: %s",
                            [f"{s['quality']}/{s['format']}" for s in unique_sources])
                best_source = select_best_source(unique_sources, self.quality, codec_aware=True, av1=self.av1)
                resolved_url = best_source["url"] if best_source else self.url

                logger.info("Selected quality: %s (requested: %s) - %s",
                            best_source.get("quality", "Unknown") if best_source else "None",
                            self.quality,
                            resolved_url[:100] + "..." if len(resolved_url) > 100 else resolved_url)

                # Determine recorder type based on URL characteristics
                recorder_id = self.determine_recorder_id(resolved_url)

                # Create FFmpeg headers from auth tokens for M4S recorder
                ffmpeg_headers = self.auth_tokens.get_ffmpeg_headers()

                self.resolve_result.update({
                    "resolved_url": resolved_url,
                    "session": self.auth_tokens.session,  # Include authenticated session for reuse
                    "ffmpeg_headers": ffmpeg_headers,  # Include FFmpeg headers for M4S recorder
                    "recorder_id": recorder_id,
                })
                return self.resolve_result

            # No sources found
            logger.error("No video sources found in XNXX page")
            return None

        except Exception as e:
            logger.error("XNXX resolution error: %s", e)
            return None
