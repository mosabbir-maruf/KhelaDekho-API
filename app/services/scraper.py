from __future__ import annotations

from datetime import datetime, timezone, timedelta

import httpx
import structlog
from bs4 import BeautifulSoup

from app.config import settings
from app.models import ScrapeResult, Match, ChannelInfo, PlatformStats
from app.scrapers import parse_matches_from_html, parse_channels_from_html
from app.utils.http import fetch_page, get_shared_client

logger = structlog.get_logger(__name__)

BDT = timezone(timedelta(hours=6))


class KhelaDekhoScraper:
    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = await get_shared_client()
        return self._client


    async def scrape_all(self) -> ScrapeResult:
        errors: list[str] = []

        matches: list[Match] = []
        channels: list[ChannelInfo] = []
        platform_stats: PlatformStats | None = None

        try:
            client = await self._get_client()
            html = await fetch_page(client, settings.target_url)
        except Exception as e:
            logger.error("scrape_failed", url=settings.target_url, error=str(e))
            return ScrapeResult(
                errors=[f"Failed to fetch page: {str(e)}"],
                fetched_at=datetime.now(BDT),
            )

        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception as e:
            logger.error("soup_creation_failed", error=str(e))
            soup = html

        try:
            matches = parse_matches_from_html(soup)
            logger.info("matches_parsed", count=len(matches))
        except Exception as e:
            errors.append(f"Match parsing failed: {str(e)}")
            logger.error("match_parse_failed", error=str(e))

        try:
            channels, platform_stats = parse_channels_from_html(soup, raw_html=html)
            logger.info(
                "channels_parsed",
                channel_count=len(channels),
                stats=platform_stats.model_dump() if platform_stats else None,
            )
        except Exception as e:
            errors.append(f"Channel parsing failed: {str(e)}")
            logger.error("channel_parse_failed", error=str(e))

        return ScrapeResult(
            matches=matches,
            channels=channels,
            platform_stats=platform_stats,
            errors=errors,
            fetched_at=datetime.now(BDT),
        )

    async def scrape_matches(self) -> list[Match]:
        result = await self.scrape_all()
        return result.matches

    async def scrape_channels(self) -> tuple[list[ChannelInfo], PlatformStats | None]:
        result = await self.scrape_all()
        return result.channels, result.platform_stats

    async def close(self):
        from app.utils.http import _client_instance
        if self._client and self._client is not _client_instance:
            await self._client.aclose()
        self._client = None


_scraper_instance: KhelaDekhoScraper | None = None


async def get_scraper() -> KhelaDekhoScraper:
    global _scraper_instance
    if _scraper_instance is None:
        _scraper_instance = KhelaDekhoScraper()
    return _scraper_instance
