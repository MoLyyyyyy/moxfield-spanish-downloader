from __future__ import annotations

import hashlib
import html
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

MAGICCARDSINFO_BASE = "https://magiccards.info"


class MagicCardsInfoClient:
    """Best-effort Spanish scan fallback for low-res Scryfall cards."""

    def __init__(
        self,
        cache_dir: Path,
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.cache_dir = cache_dir / "magiccardsinfo"
        self.html_cache = self.cache_dir / "html"
        self.html_cache.mkdir(parents=True, exist_ok=True)
        self._owns_client = http_client is None
        self.client = http_client or httpx.Client(
            timeout=25.0,
            follow_redirects=True,
            headers={
                "User-Agent": "MoxfieldCartasES/0.1 (MagicCardsInfo fallback)",
                "Accept": "text/html,application/xhtml+xml,*/*",
            },
        )

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def find_spanish_scan(
        self,
        *,
        name: str,
        set_code: str | None = None,
        collector_number: str | None = None,
    ) -> dict[str, Any] | None:
        query = name.strip()
        if not query:
            return None

        search_html = self._request_html(
            "/query",
            params={
                "q": f"!{query}",
                "v": "card",
                "s": "cname",
            },
        )
        if not search_html:
            return None

        direct_image = self._extract_best_image_url(search_html)
        if direct_image:
            return self._build_result(
                image_url=direct_image,
                name=name,
                set_code=set_code,
                collector_number=collector_number,
            )

        detail_urls = self._extract_detail_urls(search_html)
        if not detail_urls:
            return None

        preferred = self._prefer_detail_urls(
            detail_urls,
            set_code=set_code,
            collector_number=collector_number,
        )
        for detail_url in preferred[:8]:
            detail_html = self._request_html(detail_url)
            if not detail_html:
                continue
            image_url = self._extract_best_image_url(detail_html)
            if image_url:
                return self._build_result(
                    image_url=image_url,
                    name=name,
                    set_code=set_code,
                    collector_number=collector_number,
                )
        return None

    def _build_result(
        self,
        *,
        image_url: str,
        name: str,
        set_code: str | None,
        collector_number: str | None,
    ) -> dict[str, Any]:
        extension = ".png" if image_url.lower().endswith(".png") else ".jpg"
        return {
            "lang": "es",
            "name": name,
            "printed_name": name,
            "set": set_code,
            "collector_number": collector_number,
            "image_status": "highres_scan",
            "highres_image": True,
            "image_uris": {
                "png" if extension == ".png" else "large": image_url,
            },
            "_provider": "magiccardsinfo",
            "_image_provider": "magiccardsinfo",
        }

    def _request_html(
        self,
        path_or_url: str,
        *,
        params: dict[str, str] | None = None,
    ) -> str | None:
        cache_key = json.dumps(
            [path_or_url, params],
            ensure_ascii=False,
            sort_keys=True,
        )
        cache_path = self.html_cache / (
            hashlib.sha256(cache_key.encode("utf-8")).hexdigest() + ".html"
        )
        if cache_path.exists() and cache_path.stat().st_size > 0:
            try:
                return cache_path.read_text(encoding="utf-8")
            except OSError:
                cache_path.unlink(missing_ok=True)

        url = (
            path_or_url
            if path_or_url.startswith("http://") or path_or_url.startswith("https://")
            else f"{MAGICCARDSINFO_BASE}{path_or_url}"
        )
        try:
            response = self.client.get(url, params=params)
            response.raise_for_status()
        except httpx.HTTPError:
            return None

        text = response.text
        if not text.strip():
            return None
        try:
            cache_path.write_text(text, encoding="utf-8")
        except OSError:
            pass
        return text

    def _extract_best_image_url(self, html_text: str) -> str | None:
        candidates = []
        for match in re.finditer(
            r'<img[^>]+src=["\'](?P<url>[^"\']+\.(?:png|jpe?g))["\']',
            html_text,
            flags=re.IGNORECASE,
        ):
            url = urljoin(MAGICCARDSINFO_BASE + "/", html.unescape(match.group("url")))
            score = self._image_score(url)
            if score > 0:
                candidates.append((score, url))
        if not candidates:
            return None
        candidates.sort(key=lambda item: (-item[0], item[1]))
        return candidates[0][1]

    def _extract_detail_urls(self, html_text: str) -> list[str]:
        urls: list[str] = []
        seen: set[str] = set()
        for match in re.finditer(
            r'href=["\'](?P<url>[^"\']+\.html(?:\?[^"\']*)?)["\']',
            html_text,
            flags=re.IGNORECASE,
        ):
            url = urljoin(MAGICCARDSINFO_BASE + "/", html.unescape(match.group("url")))
            if url in seen:
                continue
            seen.add(url)
            urls.append(url)
        return urls

    def _prefer_detail_urls(
        self,
        urls: list[str],
        *,
        set_code: str | None,
        collector_number: str | None,
    ) -> list[str]:
        set_code = (set_code or "").casefold()
        collector_number = (collector_number or "").casefold()

        def score(url: str) -> tuple[int, int]:
            lowered = url.casefold()
            points = 0
            if "/es/" in lowered or "_es/" in lowered:
                points += 10
            if set_code and set_code in lowered:
                points += 5
            if collector_number and collector_number in lowered:
                points += 3
            return (-points, len(lowered))

        return sorted(urls, key=score)

    @staticmethod
    def _image_score(url: str) -> int:
        lowered = url.casefold()
        if "cardback" in lowered or "back" in lowered:
            return 0
        score = 1
        if "scans" in lowered or "/scan/" in lowered or "scan/" in lowered:
            score += 6
        if "/cards/" in lowered:
            score += 4
        if "/es/" in lowered or "_es/" in lowered:
            score += 2
        if lowered.endswith(".png"):
            score += 2
        return score
