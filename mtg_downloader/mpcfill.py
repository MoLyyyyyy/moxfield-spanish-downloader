from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

from .image_processing import (
    CROP_AUTO,
    process_mpc_image_bytes,
)
from .models import DeckCard, ImageFace, ResolvedCard

MPCFILL_BASE_URL = "https://mpcfill.com"


class MpcFillError(RuntimeError):
    pass


class MpcFillClient:
    def __init__(
        self,
        cache_dir: Path,
        *,
        base_url: str = MPCFILL_BASE_URL,
        client: httpx.Client | None = None,
    ) -> None:
        self.cache_dir = cache_dir
        self.json_cache = cache_dir / "json"
        self.image_cache = cache_dir / "images"
        self.preview_cache = cache_dir / "previews"
        self.json_cache.mkdir(parents=True, exist_ok=True)
        self.image_cache.mkdir(parents=True, exist_ok=True)
        self.preview_cache.mkdir(parents=True, exist_ok=True)
        self.base_url = base_url.rstrip("/") + "/"
        self._owns_client = client is None
        self.client = client or httpx.Client(
            timeout=50.0,
            follow_redirects=True,
            headers={
                "User-Agent": "ProxyMaker/0.2 (uso personal)",
                "Accept": "application/json",
            },
        )

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "MpcFillClient":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def search_designs(
        self,
        name: str,
        *,
        languages: tuple[str, ...] = (),
        minimum_dpi: int = 300,
        max_results: int = 9,
        card_type: str = "CARD",
    ) -> list[dict[str, Any]]:
        if max_results < 1:
            return []

        identifiers = self._search_identifiers(
            name,
            languages=languages,
            minimum_dpi=minimum_dpi,
            card_type=card_type,
        )
        if not identifiers:
            return []

        # La API de cards admite hasta 1000, pero para una sola carta no es
        # necesario descargar cientos de metadatos.
        cards = self._get_cards(identifiers[:120])
        language_set = {language.upper() for language in languages}

        candidates = [
            self._normalise_candidate(candidate)
            for candidate in cards
            if isinstance(candidate, dict)
        ]
        candidates = [
            candidate
            for candidate in candidates
            if candidate.get("download_url")
            and int(candidate.get("dpi") or 0) >= minimum_dpi
            and (
                not language_set
                or str(candidate.get("language") or "").upper() in language_set
            )
        ]
        candidates.sort(
            key=lambda candidate: (
                -int(candidate.get("dpi") or 0),
                int(candidate.get("priority") or 9999),
                str(candidate.get("name") or "").casefold(),
            )
        )
        return candidates[:max_results]

    def search_cardbacks(
        self,
        name: str,
        *,
        minimum_dpi: int = 300,
        max_results: int = 9,
    ) -> list[dict[str, Any]]:
        return self.search_designs(
            name,
            languages=(),
            minimum_dpi=minimum_dpi,
            max_results=max_results,
            card_type="CARDBACK",
        )

    def preview_bytes(
        self,
        candidate: dict[str, Any],
        *,
        crop_mode: str = CROP_AUTO,
        crop_shift_x: int = 0,
        crop_shift_y: int = 0,
    ) -> bytes:
        preview_url = (
            candidate.get("mediumThumbnailUrl")
            or candidate.get("smallThumbnailUrl")
            or candidate.get("download_url")
        )
        if not isinstance(preview_url, str) or not preview_url:
            raise MpcFillError("Este diseño no ofrece una imagen de previsualización.")

        key = hashlib.sha256(
            f"{preview_url}|{crop_mode}|{crop_shift_x}|{crop_shift_y}|preview-v2".encode("utf-8")
        ).hexdigest()
        path = self.preview_cache / f"{key}.jpg"
        if path.exists() and path.stat().st_size > 0:
            return path.read_bytes()

        raw = self._download(preview_url)
        processed = process_mpc_image_bytes(
            raw,
            crop_mode=crop_mode,
            crop_shift_x=crop_shift_x,
            crop_shift_y=crop_shift_y,
            max_preview_size=600,
        )
        path.write_bytes(processed.data)
        return processed.data

    def resolve_candidate(
        self,
        card: DeckCard,
        candidate: dict[str, Any],
        *,
        crop_mode: str = CROP_AUTO,
        crop_shift_x: int = 0,
        crop_shift_y: int = 0,
        type_line: str | None = None,
    ) -> ResolvedCard:
        download_url = candidate.get("download_url")
        if not isinstance(download_url, str) or not download_url:
            return ResolvedCard(
                source=card,
                status="Sin imagen",
                provider="mpcfill",
                type_line=type_line,
                error="MPCFill no ofrece un enlace de descarga para este diseño.",
            )

        extension = _extension(candidate.get("extension"), download_url)
        identifier = str(candidate.get("identifier") or "")
        dpi = int(candidate.get("dpi") or 0)
        data = dict(candidate)
        data["provider"] = "mpcfill"
        data["crop_mode"] = crop_mode
        data["crop_shift_x"] = crop_shift_x
        data["crop_shift_y"] = crop_shift_y

        return ResolvedCard(
            source=card,
            status="Diseño MPCFill",
            provider="mpcfill",
            type_line=type_line,
            language=str(candidate.get("language") or "").lower() or None,
            printed_name=str(candidate.get("name") or card.name),
            selected_set="MPCFILL",
            collector_number=identifier[:12],
            faces=[
                ImageFace(
                    label=str(candidate.get("name") or card.name),
                    url=download_url,
                    extension=extension,
                    provider="mpcfill",
                    crop_mode=crop_mode,
                    crop_shift_x=crop_shift_x,
                    crop_shift_y=crop_shift_y,
                )
            ],
            scryfall_data=data,
            downloaded_format=extension.lstrip(".").upper(),
            image_status=f"{dpi} dpi" if dpi else "DPI desconocido",
            highres_image=dpi >= 300 if dpi else None,
        )

    def _search_identifiers(
        self,
        name: str,
        *,
        languages: tuple[str, ...],
        minimum_dpi: int,
        card_type: str = "CARD",
    ) -> list[str]:
        query = _normalise_query(name)
        payload = {
            "searchSettings": {
                "searchTypeSettings": {
                    "fuzzySearch": False,
                    "filterCardbacks": card_type == "CARDBACK",
                },
                "sourceSettings": {
                    "sources": self._source_rows(),
                },
                "filterSettings": {
                    "minimumDPI": minimum_dpi,
                    "maximumDPI": 1500,
                    "maximumSize": 30,
                    "languages": [language.upper() for language in languages],
                    "includesTags": [],
                    "excludesTags": ["NSFW"],
                },
            },
            "queries": [
                {
                    "query": query,
                    "cardType": card_type,
                }
            ],
        }
        response = self._request_json(
            "2/editorSearch/",
            method="POST",
            payload=payload,
        )
        results = response.get("results")
        if not isinstance(results, dict):
            return []

        direct = results.get(query)
        if isinstance(direct, dict):
            identifiers = direct.get(card_type)
            if isinstance(identifiers, list):
                return [str(value) for value in identifiers]

        # Respaldo para backends que normalizan la consulta de otra manera.
        found: list[str] = []
        for value in results.values():
            if not isinstance(value, dict):
                continue
            identifiers = value.get(card_type)
            if isinstance(identifiers, list):
                found.extend(str(identifier) for identifier in identifiers)
        return list(dict.fromkeys(found))

    def _source_rows(self) -> list[list[int | bool]]:
        cache_path = self.json_cache / "sources.json"
        if cache_path.exists() and cache_path.stat().st_size > 0:
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                if isinstance(cached, list) and cached:
                    return cached
            except (OSError, json.JSONDecodeError):
                pass

        response = self._request_json("2/sources/")
        results = response.get("results")
        if not isinstance(results, dict):
            raise MpcFillError("MPCFill no devolvió su lista de fuentes.")

        rows: list[list[int | bool]] = []
        for key, source in results.items():
            primary_key: Any = key
            if isinstance(source, dict):
                primary_key = source.get("pk", key)
            try:
                rows.append([int(primary_key), True])
            except (TypeError, ValueError):
                continue

        if not rows:
            raise MpcFillError("MPCFill no tiene fuentes de imágenes disponibles.")

        cache_path.write_text(
            json.dumps(rows, ensure_ascii=False),
            encoding="utf-8",
        )
        return rows

    def _get_cards(self, identifiers: list[str]) -> list[dict[str, Any]]:
        cards: list[dict[str, Any]] = []
        for start in range(0, len(identifiers), 1000):
            response = self._request_json(
                "2/cards/",
                method="POST",
                payload={
                    "cardIdentifiers": identifiers[start : start + 1000],
                },
            )
            results = response.get("results")
            if isinstance(results, dict):
                cards.extend(
                    value
                    for value in results.values()
                    if isinstance(value, dict)
                )
        return cards

    def _normalise_candidate(
        self,
        candidate: dict[str, Any],
    ) -> dict[str, Any]:
        result = dict(candidate)
        result["provider"] = "mpcfill"
        result["download_url"] = _download_url(result)
        return result

    def _request_json(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = urljoin(self.base_url, path)
        try:
            response = self.client.request(
                method,
                url,
                json=payload,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Referer": self.base_url,
                },
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise MpcFillError(
                "No se ha podido consultar MPCFill en este momento."
            ) from exc

        if not isinstance(data, dict):
            raise MpcFillError("MPCFill devolvió una respuesta inesperada.")
        return data

    def _download(self, url: str) -> bytes:
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        path = self.image_cache / key
        if path.exists() and path.stat().st_size > 0:
            return path.read_bytes()

        try:
            response = self.client.get(
                url,
                headers={
                    "Accept": "image/avif,image/webp,image/png,image/jpeg,*/*",
                    "Referer": self.base_url,
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MpcFillError(
                "No se ha podido descargar la imagen de MPCFill."
            ) from exc

        content_type = response.headers.get("content-type", "")
        if "text/html" in content_type.casefold():
            raise MpcFillError(
                "MPCFill devolvió una página HTML en lugar de una imagen."
            )

        path.write_bytes(response.content)
        return response.content


def mpc_candidate_key(candidate: dict[str, Any]) -> str:
    identifier = candidate.get("identifier")
    if identifier:
        return str(identifier)
    return hashlib.sha256(
        json.dumps(candidate, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]


def mpc_candidate_label(candidate: dict[str, Any]) -> str:
    name = str(candidate.get("name") or "Diseño sin nombre")
    source = str(
        candidate.get("sourceName")
        or candidate.get("sourceVerbose")
        or candidate.get("source")
        or "Fuente desconocida"
    )
    language = str(candidate.get("language") or "?").upper()
    dpi = candidate.get("dpi") or "?"
    return f"{name} · {source} · {language} · {dpi} dpi"


def _normalise_query(value: str) -> str:
    value = value.casefold().strip()
    value = re.sub(r"\s+", " ", value)
    return value


def _download_url(candidate: dict[str, Any]) -> str | None:
    for key in ("downloadLink", "download_url"):
        value = candidate.get(key)
        if isinstance(value, str) and value:
            return value

    identifier = candidate.get("identifier")
    source_type = str(candidate.get("sourceType") or "")
    if identifier and source_type.casefold() == "google drive":
        return (
            "https://drive.google.com/uc?"
            f"id={identifier}&export=download"
        )

    source = candidate.get("source")
    if isinstance(source, str) and source.startswith(("https://", "http://")):
        return source

    for key in ("mediumThumbnailUrl", "smallThumbnailUrl"):
        value = candidate.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _extension(value: Any, url: str) -> str:
    text = str(value or "").lower().strip().lstrip(".")
    if text in {"png", "jpg", "jpeg", "webp"}:
        return ".jpg" if text == "jpeg" else f".{text}"

    path = url.casefold().split("?", 1)[0]
    for extension in (".png", ".jpg", ".jpeg", ".webp"):
        if path.endswith(extension):
            return ".jpg" if extension == ".jpeg" else extension
    return ".jpg"
