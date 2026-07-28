from __future__ import annotations

import hashlib
import json
import random
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from .image_processing import process_mpc_image_bytes
from .card_names import canonical_card_name, normalised_card_name
from .models import DeckCard, ImageFace, ResolvedCard

SCRYFALL_API = "https://api.scryfall.com"


class ScryfallError(RuntimeError):
    pass



def _canonical_card_name(value: str) -> str:
    """Backward-compatible wrapper around shared name normalisation."""
    return canonical_card_name(value)


def _normalised_card_name(value: str) -> str:
    return normalised_card_name(value)


def _candidate_matches_full_name(
    candidate: dict[str, Any],
    requested_name: str,
) -> bool:
    candidate_name = str(candidate.get("name") or "")
    if not candidate_name:
        return False
    return (
        _normalised_card_name(candidate_name)
        == _normalised_card_name(requested_name)
    )


class ScryfallClient:
    def __init__(
        self,
        cache_dir: Path,
        image_quality: str = "large",
        *,
        retry_callback: Callable[
            [int | None, int, int, float],
            None,
        ]
        | None = None,
    ) -> None:
        self.cache_dir = cache_dir
        self.json_cache = cache_dir / "json"
        self.image_cache = cache_dir / "images"
        self.raw_image_cache = cache_dir / "raw_images"
        self.json_cache.mkdir(parents=True, exist_ok=True)
        self.image_cache.mkdir(parents=True, exist_ok=True)
        self.raw_image_cache.mkdir(parents=True, exist_ok=True)
        self.image_quality = image_quality
        self.retry_callback = retry_callback
        self._last_api_request = 0.0
        self.client = httpx.Client(
            timeout=40.0,
            follow_redirects=True,
            headers={
                "User-Agent": "ProxyMaker/0.1 (aplicacion personal)",
                "Accept": "application/json;q=0.9,*/*;q=0.8",
            },
        )

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "ScryfallClient":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def resolve(
        self,
        card: DeckCard,
        allow_english_fallback: bool = True,
        allow_english_if_missing: bool = False,
        preferred_language: str | None = None,
        allow_language_fallback: bool | None = None,
        resolution_mode: str = "exact_first",
        quality_mode: str = "prefer_highres",
    ) -> ResolvedCard:
        if resolution_mode not in {"exact_first", "exact_only", "flexible"}:
            raise ValueError(f"Modo de resolución desconocido: {resolution_mode}")
        if quality_mode not in {"allow_lowres", "prefer_highres", "highres_only"}:
            raise ValueError(f"Modo de calidad desconocido: {quality_mode}")

        if preferred_language is not None:
            return self._resolve_preferred_language(
                card,
                preferred_language=preferred_language,
                allow_language_fallback=bool(allow_language_fallback),
                resolution_mode=resolution_mode,
                quality_mode=quality_mode,
            )

        has_exact_printing = bool(card.set_code)
        prefer_highres_search = quality_mode != "allow_lowres"
        first_usable: tuple[str, dict[str, Any]] | None = None
        found_spanish = False

        def consider(
            status: str,
            candidate: dict[str, Any] | None,
            *,
            spanish: bool,
        ) -> tuple[str, dict[str, Any]] | None:
            nonlocal first_usable, found_spanish
            if not candidate or not self._has_usable_image(candidate):
                return None

            pair = (status, candidate)
            if first_usable is None:
                first_usable = pair
            if spanish:
                found_spanish = True

            if quality_mode == "allow_lowres":
                return pair
            if self._is_highres(candidate):
                return pair
            return None

        def exact_candidate(
            *,
            language: str | None,
            status: str,
            spanish: bool,
        ) -> tuple[str, dict[str, Any]] | None:
            if not has_exact_printing:
                return None

            if card.collector_number:
                candidate = self._get_card_by_printing(
                    card.set_code or "",
                    card.collector_number,
                    language=language,
                )
            else:
                candidate = self._find_printing_in_set(
                    card.name,
                    set_code=card.set_code or "",
                    language="es" if language == "es" else "en",
                    prefer_highres=prefer_highres_search,
                )

            return consider(
                status,
                candidate,
                spanish=spanish,
            )

        def flexible_candidate(
            *,
            language: str,
            status: str,
            spanish: bool,
        ) -> tuple[str, dict[str, Any]] | None:
            return consider(
                status,
                self._find_printing(
                    card.name,
                    language=language,
                    prefer_highres=prefer_highres_search,
                ),
                spanish=spanish,
            )

        selected_pair: tuple[str, dict[str, Any]] | None = None

        if resolution_mode in {"exact_first", "exact_only"}:
            if not has_exact_printing and resolution_mode == "exact_only":
                return ResolvedCard(
                    source=card,
                    status="Sin impresión exacta",
                    error=(
                        "La carta no incluye edición en la lista."
                    ),
                )

            selected_pair = exact_candidate(
                language="es",
                status="Misma impresión en español",
                spanish=True,
            )
            if not selected_pair and allow_english_fallback:
                selected_pair = exact_candidate(
                    language=None,
                    status="Misma impresión en inglés",
                    spanish=False,
                )

        if not selected_pair and resolution_mode == "exact_first":
            selected_pair = flexible_candidate(
                language="es",
                status="Otra impresión en español",
                spanish=True,
            )
            if not selected_pair and allow_english_fallback:
                selected_pair = flexible_candidate(
                    language="en",
                    status="Otra impresión en inglés",
                    spanish=False,
                )

        if not selected_pair and resolution_mode == "flexible":
            selected_pair = flexible_candidate(
                language="es",
                status="Impresión flexible en español",
                spanish=True,
            )
            if not selected_pair and allow_english_fallback:
                selected_pair = flexible_candidate(
                    language="en",
                    status="Impresión flexible en inglés",
                    spanish=False,
                )

        if (
            not selected_pair
            and allow_english_if_missing
            and not allow_english_fallback
            and not found_spanish
        ):
            if resolution_mode in {"exact_first", "exact_only"}:
                selected_pair = exact_candidate(
                    language=None,
                    status="Misma impresión en inglés (sin imagen en español)",
                    spanish=False,
                )
            if not selected_pair and resolution_mode == "exact_first":
                selected_pair = flexible_candidate(
                    language="en",
                    status="Otra impresión en inglés (sin imagen en español)",
                    spanish=False,
                )
            if not selected_pair and resolution_mode == "flexible":
                selected_pair = flexible_candidate(
                    language="en",
                    status="Impresión flexible en inglés (sin imagen en español)",
                    spanish=False,
                )

        if not selected_pair and quality_mode == "prefer_highres":
            selected_pair = first_usable

        if not selected_pair:
            quality_error = (
                "No se encontró una impresión con imagen de alta resolución."
                if quality_mode == "highres_only" and first_usable
                else "No se encontró una imagen válida en Scryfall."
            )
            return ResolvedCard(
                source=card,
                status=(
                    "Sin alta resolución"
                    if quality_mode == "highres_only" and first_usable
                    else "No encontrada"
                ),
                error=quality_error,
            )

        status, selected = selected_pair
        return self.resolve_from_candidate(card, selected, status=status)

    def _resolve_preferred_language(
        self,
        card: DeckCard,
        *,
        preferred_language: str,
        allow_language_fallback: bool,
        resolution_mode: str,
        quality_mode: str,
    ) -> ResolvedCard:
        if preferred_language not in {"es", "en"}:
            raise ValueError(
                f"Idioma principal desconocido: {preferred_language}"
            )

        has_exact_printing = bool(card.set_code)
        prefer_highres = quality_mode != "allow_lowres"
        fallback_language = "en" if preferred_language == "es" else "es"
        language_labels = {"es": "español", "en": "inglés"}

        def exact_language_parameter(language: str) -> str | None:
            return "es" if language == "es" else None

        def choose_for_language(
            language: str,
            *,
            fallback: bool,
        ) -> tuple[str, dict[str, Any]] | None:
            first_usable: tuple[str, dict[str, Any]] | None = None
            label = language_labels[language]
            suffix = (
                f" (respaldo en {label})"
                if fallback
                else ""
            )

            def consider(
                status: str,
                candidate: dict[str, Any] | None,
            ) -> tuple[str, dict[str, Any]] | None:
                nonlocal first_usable
                if not candidate or not self._has_usable_image(candidate):
                    return None
                pair = (status, candidate)
                if first_usable is None:
                    first_usable = pair
                if quality_mode == "allow_lowres":
                    return pair
                if self._is_highres(candidate):
                    return pair
                return None

            selected: tuple[str, dict[str, Any]] | None = None

            if resolution_mode in {"exact_first", "exact_only"}:
                if not has_exact_printing:
                    if resolution_mode == "exact_only":
                        return None
                else:
                    if card.collector_number:
                        exact_candidate = self._get_card_by_printing(
                            card.set_code or "",
                            card.collector_number,
                            language=exact_language_parameter(language),
                        )
                    else:
                        exact_candidate = self._find_printing_in_set(
                            card.name,
                            set_code=card.set_code or "",
                            language=language,
                            prefer_highres=prefer_highres,
                        )

                    selected = consider(
                        f"Misma impresión en {label}{suffix}",
                        exact_candidate,
                    )

            if not selected and resolution_mode == "exact_first":
                selected = consider(
                    f"Otra impresión en {label}{suffix}",
                    self._find_printing(
                        card.name,
                        language=language,
                        prefer_highres=prefer_highres,
                    ),
                )

            if not selected and resolution_mode == "flexible":
                selected = consider(
                    f"Impresión flexible en {label}{suffix}",
                    self._find_printing(
                        card.name,
                        language=language,
                        prefer_highres=prefer_highres,
                    ),
                )

            if not selected and quality_mode == "prefer_highres":
                selected = first_usable
            return selected

        if resolution_mode == "exact_only" and not has_exact_printing:
            return ResolvedCard(
                source=card,
                status="Sin impresión exacta",
                error=(
                    "La carta no incluye edición en la lista."
                ),
            )

        selected_pair = choose_for_language(
            preferred_language,
            fallback=False,
        )
        if not selected_pair and allow_language_fallback:
            selected_pair = choose_for_language(
                fallback_language,
                fallback=True,
            )

        if not selected_pair:
            return ResolvedCard(
                source=card,
                status=(
                    "Sin alta resolución"
                    if quality_mode == "highres_only"
                    else "No encontrada"
                ),
                error=(
                    "No se encontró una imagen con la calidad e idioma "
                    "solicitados."
                ),
            )

        status, selected = selected_pair
        return self.resolve_from_candidate(card, selected, status=status)

    def resolve_from_candidate(
        self,
        card: DeckCard,
        selected: dict[str, Any],
        *,
        status: str = "Selección manual",
    ) -> ResolvedCard:
        faces = self._extract_faces(selected)
        if not faces:
            return ResolvedCard(
                source=card,
                status="Sin imagen",
                type_line=selected.get("type_line"),
                language=selected.get("lang"),
                printed_name=selected.get("printed_name") or selected.get("name"),
                selected_set=selected.get("set"),
                collector_number=str(selected.get("collector_number") or ""),
                scryfall_data=selected,
                image_status=selected.get("image_status"),
                highres_image=selected.get("highres_image"),
                error=(
                    "Scryfall encontró la carta, pero no ofrece una "
                    "imagen descargable."
                ),
            )

        return ResolvedCard(
            source=card,
            status=status,
            provider=str(selected.get("_provider") or "scryfall"),
            type_line=selected.get("type_line"),
            language=selected.get("lang"),
            printed_name=selected.get("printed_name") or selected.get("name"),
            selected_set=selected.get("set"),
            collector_number=str(selected.get("collector_number") or ""),
            faces=faces,
            scryfall_data=selected,
            downloaded_format=faces[0].extension.lstrip(".").upper(),
            image_status=selected.get("image_status"),
            highres_image=selected.get("highres_image"),
        )

    def search_alternatives(
        self,
        name: str,
        *,
        languages: tuple[str, ...] = ("es", "en"),
        highres_only: bool = False,
        max_results: int = 12,
    ) -> list[dict[str, Any]]:
        """Return official printings from newest to oldest."""
        if max_results < 1:
            return []

        ranked: list[tuple[dict[str, Any], int]] = []
        seen: set[str] = set()

        for language_priority, language in enumerate(languages):
            for candidate in self._search_printings(name, language):
                if not self._has_usable_image(candidate):
                    continue
                if highres_only and not self._is_highres(candidate):
                    continue

                identity = self._candidate_identity(candidate)
                if identity in seen:
                    continue
                seen.add(identity)
                ranked.append((candidate, language_priority))

        ranked.sort(
            key=lambda item: (
                str(item[0].get("released_at") or ""),
                self._is_highres(item[0]),
                -item[1],
            ),
            reverse=True,
        )
        return [
            candidate
            for candidate, _language_priority in ranked[:max_results]
        ]

    def cache_path_for_face(self, face: ImageFace) -> Path:
        cache_identity = (
            f"{face.url}|{face.provider}|{face.crop_mode or 'none'}|"
            f"{face.crop_shift_x}|{face.crop_shift_y}|v3"
        )
        key = hashlib.sha256(cache_identity.encode("utf-8")).hexdigest()
        return self.image_cache / f"{key}{face.extension}"

    def is_face_cached(self, face: ImageFace) -> bool:
        path = self.cache_path_for_face(face)
        return path.exists() and path.stat().st_size > 0

    def download_raw_image(self, face: ImageFace) -> bytes:
        key = hashlib.sha256(face.url.encode("utf-8")).hexdigest()
        path = self.raw_image_cache / f"{key}{face.extension}"
        if path.exists() and path.stat().st_size > 0:
            return path.read_bytes()

        try:
            response = self.client.get(
                face.url,
                headers={
                    "User-Agent": "ProxyMaker/0.4 (aplicacion personal)",
                    "Accept": "image/avif,image/webp,image/png,image/jpeg,*/*",
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ScryfallError(
                f"No se ha podido descargar la imagen de {face.label}."
            ) from exc

        path.write_bytes(response.content)
        return response.content

    def download_image(self, face: ImageFace) -> bytes:
        path = self.cache_path_for_face(face)
        if path.exists() and path.stat().st_size > 0:
            return path.read_bytes()

        data = self.download_raw_image(face)

        if face.provider == "mpcfill":
            data = process_mpc_image_bytes(
                data,
                crop_mode=face.crop_mode or "auto",
                crop_shift_x=face.crop_shift_x,
                crop_shift_y=face.crop_shift_y,
            ).data

        path.write_bytes(data)
        return data

    def _get_card_by_printing(
        self, set_code: str, collector_number: str, language: str | None
    ) -> dict[str, Any] | None:
        suffix = f"/{language}" if language else ""
        encoded_set = quote(set_code.lower(), safe="")
        encoded_number = quote(str(collector_number), safe="")
        path = f"/cards/{encoded_set}/{encoded_number}{suffix}"
        return self._request_json(path, allow_not_found=True)

    def _search_printings(
        self,
        name: str,
        language: str,
        *,
        set_code: str | None = None,
    ) -> list[dict[str, Any]]:
        canonical_name = _canonical_card_name(name)
        escaped = canonical_name.replace("\\", "\\\\").replace('"', '\\"')
        query_parts = [
            f'!"{escaped}"',
            f"lang:{language}",
            "game:paper",
        ]
        if set_code:
            query_parts.append(f"set:{set_code.lower()}")

        data = self._request_json(
            "/cards/search",
            params={
                "q": " ".join(query_parts),
                "order": "released",
                "dir": "desc",
                "unique": "prints",
            },
            allow_not_found=True,
        )
        if not data:
            return []

        cards = data.get("data") if isinstance(data, dict) else None
        if not isinstance(cards, list):
            return []

        expected_set = set_code.casefold() if set_code else None
        return [
            candidate
            for candidate in cards
            if isinstance(candidate, dict)
            and _candidate_matches_full_name(candidate, canonical_name)
            and (
                expected_set is None
                or str(candidate.get("set") or "").casefold() == expected_set
            )
        ]

    @staticmethod
    def _candidate_identity(candidate: dict[str, Any]) -> str:
        if candidate.get("id"):
            return str(candidate["id"])
        return "|".join(
            [
                str(candidate.get("lang") or ""),
                str(candidate.get("set") or ""),
                str(candidate.get("collector_number") or ""),
                str(candidate.get("name") or ""),
            ]
        )

    def _find_printing_in_set(
        self,
        name: str,
        *,
        set_code: str,
        language: str,
        prefer_highres: bool,
    ) -> dict[str, Any] | None:
        usable = [
            candidate
            for candidate in self._search_printings(
                name,
                language,
                set_code=set_code,
            )
            if self._has_usable_image(candidate)
        ]
        if prefer_highres:
            highres = next(
                (
                    candidate
                    for candidate in usable
                    if self._is_highres(candidate)
                ),
                None,
            )
            if highres:
                return highres
        return usable[0] if usable else None

    def _find_printing(
        self,
        name: str,
        *,
        language: str,
        prefer_highres: bool,
    ) -> dict[str, Any] | None:
        usable = [
            candidate
            for candidate in self._search_printings(name, language)
            if self._has_usable_image(candidate)
        ]
        if prefer_highres:
            highres = next(
                (candidate for candidate in usable if self._is_highres(candidate)),
                None,
            )
            if highres:
                return highres
        return usable[0] if usable else None

    @staticmethod
    def _has_usable_image(card: dict[str, Any]) -> bool:
        return card.get("image_status") not in {"missing", "placeholder"}

    @staticmethod
    def _is_highres(card: dict[str, Any]) -> bool:
        return (
            card.get("image_status") == "highres_scan"
            or card.get("highres_image") is True
        )

    def _extract_faces(self, card: dict[str, Any]) -> list[ImageFace]:
        provider = str(card.get("_image_provider") or card.get("_provider") or "scryfall")
        image_uris = card.get("image_uris")
        if isinstance(image_uris, dict):
            face = self._face_from_uris(
                card.get("printed_name") or card.get("name") or "Carta",
                image_uris,
                provider=provider,
            )
            return [face] if face else []

        result: list[ImageFace] = []
        card_faces = card.get("card_faces")
        if isinstance(card_faces, list):
            for index, card_face in enumerate(card_faces, start=1):
                if not isinstance(card_face, dict):
                    continue
                uris = card_face.get("image_uris")
                if not isinstance(uris, dict):
                    continue
                label = (
                    card_face.get("printed_name")
                    or card_face.get("name")
                    or f"Cara {index}"
                )
                face = self._face_from_uris(str(label), uris, provider=provider)
                if face:
                    result.append(face)
        return result

    def _face_from_uris(
        self, label: str, uris: dict[str, Any], *, provider: str = "scryfall"
    ) -> ImageFace | None:
        preferred = [self.image_quality]
        if self.image_quality == "png":
            preferred.extend(["large", "normal", "small"])
        else:
            preferred.extend(["large", "normal", "png", "small"])

        for quality in preferred:
            url = uris.get(quality)
            if isinstance(url, str) and url:
                extension = ".png" if quality == "png" else ".jpg"
                return ImageFace(
                    label=label,
                    url=url,
                    extension=extension,
                    provider=provider,
                )
        return None

    def _request_json(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
        allow_not_found: bool = False,
    ) -> dict[str, Any] | None:
        cache_key = json.dumps([path, params], ensure_ascii=False, sort_keys=True)
        cache_path = self.json_cache / (
            hashlib.sha256(cache_key.encode("utf-8")).hexdigest() + ".json"
        )
        if cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                return cached if isinstance(cached, dict) else None
            except (OSError, json.JSONDecodeError):
                cache_path.unlink(missing_ok=True)

        url = f"{SCRYFALL_API}{path}"
        retryable_statuses = {429, 500, 502, 503, 504}
        max_attempts = 5
        response: httpx.Response | None = None
        last_transport_error: httpx.TransportError | None = None

        for attempt_index in range(max_attempts):
            self._respect_rate_limit()
            try:
                response = self.client.get(url, params=params)
                last_transport_error = None
            except httpx.TransportError as exc:
                response = None
                last_transport_error = exc
            finally:
                self._last_api_request = time.monotonic()

            status_code = response.status_code if response is not None else None
            should_retry = (
                last_transport_error is not None
                or status_code in retryable_statuses
            )
            final_attempt = attempt_index == max_attempts - 1

            if not should_retry or final_attempt:
                break

            delay = self._retry_delay(
                response,
                attempt_index=attempt_index,
            )
            if self.retry_callback is not None:
                self.retry_callback(
                    status_code,
                    attempt_index + 1,
                    max_attempts - 1,
                    delay,
                )
            time.sleep(delay)

        if response is None:
            message = (
                "No se pudo conectar con Scryfall después de varios intentos."
            )
            if last_transport_error is not None:
                raise ScryfallError(message) from last_transport_error
            raise ScryfallError(message)

        if response.status_code == 404 and allow_not_found:
            try:
                cache_path.write_text("{}", encoding="utf-8")
            except OSError:
                pass
            return None

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if response.status_code == 503:
                message = (
                    "Scryfall sigue temporalmente no disponible (HTTP 503) "
                    "después de varios reintentos."
                )
            elif response.status_code == 429:
                message = (
                    "Scryfall ha limitado temporalmente las peticiones "
                    "(HTTP 429)."
                )
            else:
                message = (
                    f"Scryfall devolvió el error HTTP "
                    f"{response.status_code}."
                )
            raise ScryfallError(message) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise ScryfallError("Scryfall no devolvió un JSON válido.") from exc
        if not isinstance(payload, dict):
            raise ScryfallError("Scryfall devolvió un formato inesperado.")

        try:
            cache_path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass
        return payload

    @staticmethod
    def _retry_delay(
        response: httpx.Response | None,
        *,
        attempt_index: int,
    ) -> float:
        retry_after = 0.0
        if response is not None:
            raw_retry_after = response.headers.get("Retry-After")
            if raw_retry_after:
                try:
                    retry_after = max(float(raw_retry_after), 0.0)
                except ValueError:
                    retry_after = 0.0

        exponential = min(0.8 * (2**attempt_index), 8.0)
        jitter = random.uniform(0.0, 0.35)
        if response is not None and response.status_code == 429:
            exponential = max(exponential, 1.5)
        return min(max(retry_after, exponential + jitter), 12.0)

    def _respect_rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_api_request
        # Five-to-six API requests per second is gentler for shared cloud IPs.
        remaining = 0.18 - elapsed
        if remaining > 0:
            time.sleep(remaining)
