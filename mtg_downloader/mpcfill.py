from __future__ import annotations

import hashlib
import json
import re
import string
import time
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
    "CompC",
    "Hathwellcrisping",
)


class MpcFillError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code


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
        self.last_batch_stats: dict[str, int] = {}
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

        has_printing = bool(card.set_code)
        search_modes: list[tuple[bool, str | None, str | None]]
        if resolution_mode == "exact_only":
            if not has_printing:
                return ResolvedCard(
                    source=card,
                    status="Sin impresión exacta",
                    provider="mpcfill",
                    type_line=type_line,
                    error=(
                        "La carta no incluye edición en la lista."
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

                        candidate = _select_auto_candidate(
                            designs,
                            preferred_language=preferred_language,
                            allowed_languages=tuple(languages_to_try),
                            quality_mode=quality_mode,
                            preferred_sources=preferred_sources,
                            preferred_set_code=card.set_code,
                            require_set_code=(
                                expansion_code is not None
                                and collector_number is not None
                            ),
                        )
                        if candidate is None:
                            continue

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

    def resolve_many_auto(
        self,
        cards: list[DeckCard],
        *,
        preferred_language: str = "es",
        allow_language_fallback: bool = True,
        resolution_mode: str = "exact_first",
        quality_mode: str = "prefer_highres",
        preferred_sources: tuple[str, ...] = DEFAULT_PREFERRED_SOURCES,
    ) -> list[ResolvedCard]:
        """Resolve a complete deck with a few batched MPCFill requests."""
        if preferred_language not in {"es", "en"}:
            preferred_language = "es"
        if resolution_mode not in {"exact_first", "exact_only", "flexible"}:
            resolution_mode = "exact_first"
        if quality_mode not in {
            "allow_lowres",
            "prefer_highres",
            "highres_only",
        }:
            quality_mode = "prefer_highres"

        cards = list(cards)
        resolved: list[ResolvedCard | None] = [None] * len(cards)
        languages = [preferred_language]
        if allow_language_fallback:
            languages.append(
                "en" if preferred_language == "es" else "es"
            )

        minimum_dpi = 800 if quality_mode == "highres_only" else 300
        stats = {
            "cards": len(cards),
            "search_requests": 0,
            "metadata_requests": 0,
            "queries_with_hits": 0,
            "resolved": 0,
            "preferred_creator": 0,
            "language_fallback": 0,
        }

        def resolve_pass(
            indices: list[int],
            *,
            exact_printing: bool,
            fuzzy_search: bool,
            front_name_only: bool = False,
        ) -> list[int]:
            if not indices:
                return []

            query_documents: dict[str, dict[str, Any]] = {}
            key_to_index: dict[str, int] = {}
            for index in indices:
                card = cards[index]
                query_name = card.name
                if front_name_only and " // " in query_name:
                    query_name = query_name.split(" // ", 1)[0].strip()

                query_document: dict[str, Any] = {
                    "query": _normalise_query(query_name),
                    "cardType": "CARD",
                }
                if exact_printing:
                    if not card.set_code:
                        continue
                    query_document["expansionCode"] = card.set_code.upper()
                    if card.collector_number:
                        query_document["collectorNumber"] = card.collector_number

                query_key = f"{index}:{_search_query_key(query_document)}"
                query_documents[query_key] = query_document
                key_to_index[query_key] = index

            if not query_documents:
                return indices

            identifiers_by_key, request_count = (
                self._search_many_identifiers(
                    query_documents,
                    languages=tuple(language.upper() for language in languages),
                    minimum_dpi=minimum_dpi,
                    preferred_sources=preferred_sources,
                    fuzzy_search=fuzzy_search,
                )
            )
            stats["search_requests"] += request_count
            stats["queries_with_hits"] += sum(
                1
                for identifiers in identifiers_by_key.values()
                if identifiers
            )

            identifiers: list[str] = []
            for values in identifiers_by_key.values():
                identifiers.extend(values[:40])
            identifiers = list(dict.fromkeys(identifiers))

            documents: dict[str, dict[str, Any]] = {}
            for start in range(0, len(identifiers), 1000):
                batch = identifiers[start : start + 1000]
                if not batch:
                    continue
                documents.update(self._get_card_documents(batch))
                stats["metadata_requests"] += 1

            unresolved: list[int] = []
            for query_key, index in key_to_index.items():
                candidate_documents = [
                    documents[identifier]
                    for identifier in identifiers_by_key.get(query_key, [])[:40]
                    if identifier in documents
                ]
                candidate = _select_auto_candidate(
                    candidate_documents,
                    preferred_language=preferred_language,
                    allowed_languages=tuple(languages),
                    quality_mode=quality_mode,
                    preferred_sources=preferred_sources,
                    preferred_set_code=cards[index].set_code,
                    require_set_code=exact_printing and bool(cards[index].set_code),
                )
                if candidate is None:
                    unresolved.append(index)
                    continue

                result = self.resolve_candidate(
                    cards[index],
                    candidate,
                    crop_mode=CROP_AUTO,
                )
                source_rank = _preferred_source_rank(
                    candidate,
                    preferred_sources,
                )
                candidate_language = str(
                    candidate.get("language") or ""
                ).lower()
                status_parts = ["Diseño MPCFill"]
                if source_rank < len(preferred_sources):
                    status_parts.append("autor preferido")
                    stats["preferred_creator"] += 1
                if candidate_language != preferred_language:
                    status_parts.append(
                        "respaldo en "
                        + (
                            "español"
                            if candidate_language == "es"
                            else "inglés"
                        )
                    )
                    stats["language_fallback"] += 1
                if (
                    quality_mode == "prefer_highres"
                    and int(candidate.get("dpi") or 0) < 600
                ):
                    status_parts.append("calidad de respaldo")
                result.status = " · ".join(status_parts)
                resolved[index] = result

            return unresolved

        unresolved = list(range(len(cards)))

        if resolution_mode in {"exact_first", "exact_only"}:
            exact_indices = [
                index
                for index in unresolved
                if cards[index].set_code
            ]
            unresolved_after_exact = resolve_pass(
                exact_indices,
                exact_printing=True,
                fuzzy_search=False,
            )
            exact_index_set = set(exact_indices)
            unresolved = [
                index
                for index in unresolved
                if index not in exact_index_set
            ] + unresolved_after_exact

            if resolution_mode == "exact_only":
                for index in unresolved:
                    resolved[index] = ResolvedCard(
                        source=cards[index],
                        status="Sin impresión exacta",
                        provider="mpcfill",
                        error=(
                            "MPCFill no encontró la edición y número de "
                            "coleccionista indicados."
                        ),
                    )
                unresolved = []

        if unresolved:
            unresolved = resolve_pass(
                unresolved,
                exact_printing=False,
                fuzzy_search=resolution_mode == "flexible",
            )

        dfc_unresolved = [
            index
            for index in unresolved
            if " // " in cards[index].name
        ]
        if dfc_unresolved:
            remaining_dfc = resolve_pass(
                dfc_unresolved,
                exact_printing=False,
                fuzzy_search=True,
                front_name_only=True,
            )
            dfc_set = set(dfc_unresolved)
            remaining_set = set(remaining_dfc)
            unresolved = [
                index
                for index in unresolved
                if index not in dfc_set or index in remaining_set
            ]

        for index in unresolved:
            resolved[index] = ResolvedCard(
                source=cards[index],
                status=(
                    "Sin alta resolución"
                    if quality_mode == "highres_only"
                    else "No encontrada"
                ),
                provider="mpcfill",
                error=(
                    "MPCFill no devolvió diseños compatibles para esta "
                    "consulta."
                ),
            )

        final_results = [
            item
            if item is not None
            else ResolvedCard(
                source=cards[index],
                status="No encontrada",
                provider="mpcfill",
                error="MPCFill no devolvió una selección.",
            )
            for index, item in enumerate(resolved)
        ]
        stats["resolved"] = sum(1 for item in final_results if item.faces)
        self.last_batch_stats = stats
        return final_results

    def _search_many_identifiers(
        self,
        query_documents: dict[str, dict[str, Any]],
        *,
        languages: tuple[str, ...],
        minimum_dpi: int,
        preferred_sources: tuple[str, ...],
        fuzzy_search: bool,
    ) -> tuple[dict[str, list[str]], int]:
        search_settings = {
            "searchTypeSettings": {
                "fuzzySearch": fuzzy_search,
                "filterCardbacks": False,
            },
            "sourceSettings": {
                "sources": self._source_rows(preferred_sources),
            },
            "filterSettings": {
                "minimumDPI": minimum_dpi,
                "maximumDPI": 1500,
                "maximumSize": 30,
                "languages": list(languages),
                "includesTags": [],
                "excludesTags": ["NSFW"],
            },
        }

        results: dict[str, list[str]] = {}
        request_count = 0
        items = list(query_documents.items())
        for start in range(0, len(items), 300):
            chunk = dict(items[start : start + 300])
            payload = {
                "searchSettings": search_settings,
                "queries": chunk,
            }
            try:
                response = self._request_json(
                    "3/editorSearch/",
                    method="POST",
                    payload=payload,
                )
                request_count += 1
                raw_results = response.get("results")
                if not isinstance(raw_results, dict):
                    raise MpcFillError(
                        "MPCFill no devolvió resultados de búsqueda."
                    )
                for key in chunk:
                    identifiers = raw_results.get(key, [])
                    results[key] = (
                        [str(value) for value in identifiers]
                        if isinstance(identifiers, list)
                        else []
                    )
            except MpcFillError as exc:
                if exc.status_code != 404:
                    raise

                legacy_payload = {
                    "searchSettings": search_settings,
                    "queries": list(chunk.values()),
                }
                legacy = self._request_json(
                    "2/editorSearch/",
                    method="POST",
                    payload=legacy_payload,
                )
                request_count += 1
                legacy_results = legacy.get("results")
                if not isinstance(legacy_results, dict):
                    raise MpcFillError(
                        "MPCFill no devolvió resultados de búsqueda."
                    )

                for key, query_document in chunk.items():
                    query = str(query_document.get("query") or "")
                    card_type = str(
                        query_document.get("cardType") or "CARD"
                    )
                    per_query = legacy_results.get(query, {})
                    identifiers = (
                        per_query.get(card_type, [])
                        if isinstance(per_query, dict)
                        else []
                    )
                    results[key] = (
                        [str(value) for value in identifiers]
                        if isinstance(identifiers, list)
                        else []
                    )

        return results, request_count

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

    def _get_card_documents(
        self,
        identifiers: list[str],
    ) -> dict[str, dict[str, Any]]:
        documents: dict[str, dict[str, Any]] = {}
        for start in range(0, len(identifiers), 1000):
            response = self._request_json(
                "2/cards/",
                method="POST",
                payload={
                    "cardIdentifiers": identifiers[start : start + 1000],
                },
            )
            results = response.get("results")
            if not isinstance(results, dict):
                continue
            for identifier, candidate in results.items():
                if isinstance(candidate, dict):
                    documents[str(identifier)] = self._normalise_candidate(
                        candidate
                    )
        return documents

    def _get_cards(self, identifiers: list[str]) -> list[dict[str, Any]]:
        documents = self._get_card_documents(identifiers)
        return [
            documents[identifier]
            for identifier in identifiers
            if identifier in documents
        ]

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
        retryable = {429, 500, 502, 503, 504}
        response: httpx.Response | None = None
        last_transport_error: httpx.TransportError | None = None

        for attempt in range(4):
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
                last_transport_error = None
            except httpx.TransportError as exc:
                response = None
                last_transport_error = exc

            status_code = (
                response.status_code if response is not None else None
            )
            should_retry = (
                last_transport_error is not None
                or status_code in retryable
            )
            if not should_retry or attempt == 3:
                break

            retry_after = 0.0
            if response is not None:
                try:
                    retry_after = float(
                        response.headers.get("Retry-After", "0")
                    )
                except ValueError:
                    retry_after = 0.0
            time.sleep(max(retry_after, 0.8 * (2**attempt)))

        if response is None:
            raise MpcFillError(
                "No se ha podido conectar con MPCFill después de varios "
                "intentos."
            ) from last_transport_error

        try:
            data = response.json()
        except ValueError as exc:
            raise MpcFillError(
                f"MPCFill devolvió HTTP {response.status_code} sin JSON "
                "válido.",
                status_code=response.status_code,
            ) from exc

        if response.is_error:
            name = ""
            message = ""
            if isinstance(data, dict):
                name = str(data.get("name") or "").strip()
                message = str(data.get("message") or "").strip()
            detail = ": ".join(
                value for value in (name, message) if value
            )
            suffix = f" — {detail}" if detail else ""
            raise MpcFillError(
                f"MPCFill devolvió HTTP {response.status_code}{suffix}",
                status_code=response.status_code,
            )

        if not isinstance(data, dict):
            raise MpcFillError(
                "MPCFill devolvió una respuesta inesperada.",
                status_code=response.status_code,
            )
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
    value = value.lower().strip()
    punctuation = string.punctuation.replace("-", "") + "’"
    value = value.translate(str.maketrans("", "", punctuation))
    return re.sub(r"\s+", " ", value).strip()


def _search_query_key(query_document: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            query_document,
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:20]


def _select_auto_candidate(
    candidates: list[dict[str, Any]],
    *,
    preferred_language: str,
    allowed_languages: tuple[str, ...],
    quality_mode: str,
    preferred_sources: tuple[str, ...],
    preferred_set_code: str | None = None,
    require_set_code: bool = False,
) -> dict[str, Any] | None:
    allowed = {language.lower() for language in allowed_languages}
    valid: list[dict[str, Any]] = []
    for raw_candidate in candidates:
        candidate = dict(raw_candidate)
        candidate["download_url"] = _download_url(candidate)
        if not candidate.get("download_url"):
            continue

        language = str(candidate.get("language") or "").lower()
        if allowed and language not in allowed:
            continue

        dpi = int(candidate.get("dpi") or 0)
        if quality_mode == "highres_only" and dpi < 800:
            continue
        if quality_mode != "highres_only" and dpi < 300:
            continue
        if require_set_code and not mpc_candidate_mentions_set_code(
            candidate,
            preferred_set_code,
        ):
            continue
        valid.append(candidate)

    if not valid:
        return None

    def rank(candidate: dict[str, Any]) -> tuple[object, ...]:
        language = str(candidate.get("language") or "").lower()
        dpi = int(candidate.get("dpi") or 0)
        language_rank = 0 if language == preferred_language else 1
        quality_rank = (
            0
            if quality_mode != "prefer_highres" or dpi >= 600
            else 1
        )
        set_code_rank = (
            0
            if mpc_candidate_mentions_set_code(
                candidate,
                preferred_set_code,
            )
            else 1
        )
        return (
            language_rank,
            set_code_rank,
            quality_rank,
            _preferred_source_rank(candidate, preferred_sources),
            -dpi,
            -int(candidate.get("priority") or 0),
            str(candidate.get("name") or "").casefold(),
        )

    return min(valid, key=rank)




def mpc_candidate_mentions_set_code(
    candidate: dict[str, Any],
    set_code: str | None,
) -> bool:
    if not set_code:
        return False

    normalised_target = _normalise_source_name(set_code)
    if not normalised_target:
        return False

    fields = [
        candidate.get("name"),
        candidate.get("displayName"),
        candidate.get("sourceName"),
        candidate.get("sourceVerbose"),
        candidate.get("source"),
        candidate.get("identifier"),
        candidate.get("fileName"),
        candidate.get("filename"),
        candidate.get("downloadLink"),
        candidate.get("download_url"),
        candidate.get("smallThumbnailUrl"),
        candidate.get("mediumThumbnailUrl"),
    ]
    for value in fields:
        raw = str(value or "").strip()
        if not raw:
            continue

        tokens = [
            _normalise_source_name(token)
            for token in re.split(r"[^A-Za-z0-9]+", raw)
            if token
        ]
        if normalised_target in tokens:
            return True

        compact = _normalise_source_name(raw)
        for wrapped in (
            f"({normalised_target})",
            f"[{normalised_target}]",
            f"_{normalised_target}_",
            f"-{normalised_target}-",
            f" {normalised_target} ",
        ):
            if wrapped.strip() and wrapped.strip() in compact:
                return True

    return False

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
