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
DEFAULT_PREFERRED_SOURCES = (
    "MrTeferi",
    "PsilosX",
    "Chilli_Axe",
)


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
        preferred_sources: tuple[str, ...] = (),
        fuzzy_search: bool = False,
        expansion_code: str | None = None,
        collector_number: str | None = None,
    ) -> list[dict[str, Any]]:
        if max_results < 1:
            return []

        identifiers = self._search_identifiers(
            name,
            languages=languages,
            minimum_dpi=minimum_dpi,
            card_type=card_type,
            preferred_sources=preferred_sources,
            fuzzy_search=fuzzy_search,
            expansion_code=expansion_code,
            collector_number=collector_number,
        )
        if not identifiers:
            return []

        language_set = {language.upper() for language in languages}
        candidates: list[dict[str, Any]] = []

        # MPCFill returns identifiers following the configured source order.
        # Fetch progressively instead of discarding every identifier after
        # position 120, which could hide a preferred creator entirely.
        identifiers = identifiers[:1000]
        batch_size = 200
        for batch_start in range(0, len(identifiers), batch_size):
            cards = self._get_cards(
                identifiers[batch_start : batch_start + batch_size]
            )
            for raw_candidate in cards:
                if not isinstance(raw_candidate, dict):
                    continue
                candidate = self._normalise_candidate(raw_candidate)
                if not candidate.get("download_url"):
                    continue
                if int(candidate.get("dpi") or 0) < minimum_dpi:
                    continue
                if (
                    language_set
                    and str(candidate.get("language") or "").upper()
                    not in language_set
                ):
                    continue
                candidates.append(candidate)

            if len(candidates) >= max_results:
                break

        candidates.sort(
            key=lambda candidate: (
                _preferred_source_rank(candidate, preferred_sources),
                -int(candidate.get("dpi") or 0),
                -int(candidate.get("priority") or 0),
                _source_name(candidate).casefold(),
                str(candidate.get("name") or "").casefold(),
            )
        )
        return candidates[:max_results]

    def resolve_auto(
        self,
        card: DeckCard,
        *,
        preferred_language: str = "es",
        allow_language_fallback: bool = True,
        resolution_mode: str = "exact_first",
        quality_mode: str = "prefer_highres",
        preferred_sources: tuple[str, ...] = DEFAULT_PREFERRED_SOURCES,
        type_line: str | None = None,
    ) -> ResolvedCard:
        if preferred_language not in {"es", "en"}:
            preferred_language = "es"
        if resolution_mode not in {"exact_first", "exact_only", "flexible"}:
            resolution_mode = "exact_first"

        languages_to_try = [preferred_language]
        if allow_language_fallback:
            fallback = "en" if preferred_language == "es" else "es"
            languages_to_try.append(fallback)

        dpi_attempts = {
            "allow_lowres": (300,),
            # A preference is not a hard minimum: try 600 first and then
            # accept a printable design from 300 DPI.
            "prefer_highres": (600, 300),
            "highres_only": (800,),
        }.get(quality_mode, (600, 300))

        has_printing = bool(card.set_code and card.collector_number)
        search_modes: list[tuple[bool, str | None, str | None]]
        if resolution_mode == "exact_only":
            if not has_printing:
                return ResolvedCard(
                    source=card,
                    status="Sin impresión exacta",
                    provider="mpcfill",
                    type_line=type_line,
                    error=(
                        "La carta no incluye edición y número de "
                        "coleccionista en la lista."
                    ),
                )
            search_modes = [
                (False, card.set_code, card.collector_number),
            ]
        elif resolution_mode == "exact_first":
            search_modes = []
            if has_printing:
                search_modes.append(
                    (False, card.set_code, card.collector_number)
                )
            search_modes.append((False, None, None))
        else:
            # Any edition means no printing restriction and fuzzy matching.
            search_modes = [(True, None, None)]

        names_to_try = [card.name]
        if " // " in card.name:
            front_name = card.name.split(" // ", 1)[0].strip()
            if front_name and front_name not in names_to_try:
                names_to_try.append(front_name)

        attempted: set[tuple[object, ...]] = set()
        for language in languages_to_try:
            # Exact printing remains ahead of a different printing even when
            # the latter has more DPI.
            for fuzzy_search, expansion_code, collector_number in search_modes:
                for minimum_dpi in dpi_attempts:
                    for name in names_to_try:
                        attempt_key = (
                            language,
                            minimum_dpi,
                            fuzzy_search,
                            expansion_code,
                            collector_number,
                            name.casefold(),
                        )
                        if attempt_key in attempted:
                            continue
                        attempted.add(attempt_key)

                        designs = self.search_designs(
                            name,
                            languages=(language.upper(),),
                            minimum_dpi=minimum_dpi,
                            max_results=24,
                            preferred_sources=preferred_sources,
                            fuzzy_search=fuzzy_search,
                            expansion_code=expansion_code,
                            collector_number=collector_number,
                        )
                        if not designs:
                            continue

                        candidate = designs[0]
                        result = self.resolve_candidate(
                            card,
                            candidate,
                            crop_mode=CROP_AUTO,
                            type_line=type_line,
                        )

                        language_label = (
                            "español" if language == "es" else "inglés"
                        )
                        preferred_suffix = (
                            " preferido"
                            if _preferred_source_rank(
                                candidate,
                                preferred_sources,
                            )
                            < len(preferred_sources)
                            else ""
                        )
                        fallback_suffix = (
                            f" (respaldo en {language_label})"
                            if language != preferred_language
                            else ""
                        )
                        dpi_suffix = (
                            " · calidad de respaldo"
                            if (
                                quality_mode == "prefer_highres"
                                and minimum_dpi == 300
                            )
                            else ""
                        )
                        result.status = (
                            f"Diseño MPCFill{preferred_suffix}"
                            f"{fallback_suffix}{dpi_suffix}"
                        )
                        return result

        return ResolvedCard(
            source=card,
            status=(
                "Sin alta resolución"
                if quality_mode == "highres_only"
                else "No encontrada"
            ),
            provider="mpcfill",
            type_line=type_line,
            error=(
                "MPCFill no encontró una imagen con la edición, idioma y "
                "calidad solicitados."
            ),
        )

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
            preferred_sources=(),
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
        preferred_sources: tuple[str, ...] = (),
        fuzzy_search: bool = False,
        expansion_code: str | None = None,
        collector_number: str | None = None,
    ) -> list[str]:
        query = _normalise_query(name)
        search_settings = {
            "searchTypeSettings": {
                "fuzzySearch": fuzzy_search,
                "filterCardbacks": card_type == "CARDBACK",
            },
            "sourceSettings": {
                "sources": self._source_rows(preferred_sources),
            },
            "filterSettings": {
                "minimumDPI": minimum_dpi,
                "maximumDPI": 1500,
                "maximumSize": 30,
                "languages": [
                    language.upper() for language in languages
                ],
                "includesTags": [],
                "excludesTags": ["NSFW"],
            },
        }
        search_query: dict[str, Any] = {
            "query": query,
            "cardType": card_type,
        }
        if expansion_code:
            search_query["expansionCode"] = expansion_code.upper()
        if collector_number:
            search_query["collectorNumber"] = collector_number

        query_key = hashlib.sha256(
            json.dumps(
                search_query,
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()[:24]
        current_payload = {
            "searchSettings": search_settings,
            "queries": {query_key: search_query},
        }

        try:
            response = self._request_json(
                "3/editorSearch/",
                method="POST",
                payload=current_payload,
            )
            results = response.get("results")
            if isinstance(results, dict):
                identifiers = results.get(query_key)
                if isinstance(identifiers, list):
                    return list(
                        dict.fromkeys(str(value) for value in identifiers)
                    )
        except MpcFillError:
            # Compatibility with older/self-hosted backends.
            pass

        legacy_payload = {
            "searchSettings": search_settings,
            "queries": [search_query],
        }
        response = self._request_json(
            "2/editorSearch/",
            method="POST",
            payload=legacy_payload,
        )
        results = response.get("results")
        if not isinstance(results, dict):
            return []

        direct = results.get(query)
        if isinstance(direct, dict):
            identifiers = direct.get(card_type)
            if isinstance(identifiers, list):
                return list(
                    dict.fromkeys(str(value) for value in identifiers)
                )

        found: list[str] = []
        for value in results.values():
            if not isinstance(value, dict):
                continue
            identifiers = value.get(card_type)
            if isinstance(identifiers, list):
                found.extend(str(identifier) for identifier in identifiers)
        return list(dict.fromkeys(found))

    def _source_rows(
        self,
        preferred_sources: tuple[str, ...] = (),
    ) -> list[list[int | bool]]:
        sources = self._source_documents()
        prepared: list[tuple[int, int, int]] = []

        for original_index, (key, source) in enumerate(sources.items()):
            primary_key: Any = key
            source_name = str(key)
            if isinstance(source, dict):
                primary_key = source.get("pk", key)
                source_name = str(
                    source.get("name")
                    or source.get("key")
                    or key
                )
            try:
                pk = int(primary_key)
            except (TypeError, ValueError):
                continue

            prepared.append(
                (
                    _preferred_name_rank(
                        source_name,
                        preferred_sources,
                    ),
                    original_index,
                    pk,
                )
            )

        if not prepared:
            raise MpcFillError(
                "MPCFill no tiene fuentes de imágenes disponibles."
            )

        prepared.sort(key=lambda row: (row[0], row[1]))
        return [[pk, True] for _, _, pk in prepared]

    def _source_documents(self) -> dict[str, Any]:
        # The previous cache stored only numeric rows and therefore lost the
        # creator names required for source ordering.
        cache_path = self.json_cache / "sources-v2.json"
        if cache_path.exists() and cache_path.stat().st_size > 0:
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                if isinstance(cached, dict) and cached:
                    return cached
            except (OSError, json.JSONDecodeError):
                cache_path.unlink(missing_ok=True)

        response = self._request_json("2/sources/")
        results = response.get("results")
        if not isinstance(results, dict):
            raise MpcFillError(
                "MPCFill no devolvió su lista de fuentes."
            )

        try:
            cache_path.write_text(
                json.dumps(results, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass
        return results

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




def _source_name(candidate: dict[str, Any]) -> str:
    return str(
        candidate.get("sourceName")
        or candidate.get("sourceVerbose")
        or candidate.get("source")
        or ""
    ).strip()


def _normalise_source_name(value: str) -> str:
    return re.sub(r"[\s_-]+", "", value.casefold()).strip()


def _preferred_name_rank(
    source_name: str,
    preferred_sources: tuple[str, ...],
) -> int:
    if not preferred_sources:
        return 9999

    normalised_source = _normalise_source_name(source_name)
    for index, preferred in enumerate(preferred_sources):
        normalised_preferred = _normalise_source_name(str(preferred))
        if (
            normalised_source == normalised_preferred
            or normalised_preferred in normalised_source
            or normalised_source in normalised_preferred
        ):
            return index
    return len(preferred_sources) + 1


def _preferred_source_rank(
    candidate: dict[str, Any],
    preferred_sources: tuple[str, ...],
) -> int:
    return _preferred_name_rank(
        _source_name(candidate),
        preferred_sources,
    )
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
