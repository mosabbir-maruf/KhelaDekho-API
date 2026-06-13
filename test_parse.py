import asyncio
import httpx
from bs4 import BeautifulSoup
from app.utils.http import fetch_page
from app.config import settings
from app.scrapers import parse_matches_from_html, parse_channels_from_html

async def main():
    async with httpx.AsyncClient() as client:
        try:
            print(f"Fetching {settings.target_url}...")
            html = await fetch_page(client, settings.target_url)
            print("Fetched successfully. HTML length:", len(html))
            print("HTML Snippet:\n", html[:2000])
            
            soup = BeautifulSoup(html, "lxml")
            
            # Print some basic elements to check structure
            print("\nPage title:", soup.title.string if soup.title else "No title")
            
            # Check for match card selectors
            match_cards = soup.select(
                ".match-card[data-match-id], "
                ".match-card[data-match-status], "
                "div[data-match-id]"
            )
            print(f"Number of match card elements found: {len(match_cards)}")
            
            # Check for CHANNELS in JS
            import re
            pattern = r"CHANNELS\s*=\s*(\[.+?\])\s*;"
            match = re.search(pattern, html, re.DOTALL)
            print(f"CHANNELS JS match found: {match is not None}")
            if match:
                print("CHANNELS JS snippet:", match.group(0)[:200])

            # Run actual scraper parsers
            matches = parse_matches_from_html(html)
            channels, stats = parse_channels_from_html(html)
            
            print(f"\nParsed {len(matches)} matches:")
            for m in matches[:3]:
                print(f" - {m.team1.name} vs {m.team2.name} (Status: {m.status}, ID: {m.match_id})")
                
            print(f"\nParsed {len(channels)} channels:")
            for c in channels[:3]:
                print(f" - {c.name} (Key: {c.key}, Live Viewers: {c.live_viewers})")
                
            print(f"\nPlatform stats: {stats}")
            
        except Exception as e:
            import traceback
            traceback.print_exc()

asyncio.run(main())
