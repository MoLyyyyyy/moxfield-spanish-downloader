from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from .image_processing import process_mpc_image_bytes
from .models import DeckCard, ImageFace, ResolvedCard

SCRYFALL_API = "https://api.scryfall.com"


class ScryfallError(RuntimeError):
    pass


class ScryfallClient:
    def __init__(self, cache_dir: Path, image_quality: str = "large") -> None:
        self.cache_dir = cache_dir
        self.json_cache = cache_dir / "json"
        self.image_cache = cache_dir / "images"
        self.raw_image_cache = cache_dir / "raw_images"
        self.json_cache.mkdir(parents=True, exist_ok=True)
        self.image_cache.mkdir(parents=True, exist_ok=True)
        self.raw_image_cache.mkdir(parents=True, exist_ok=True)
        self.image_quality = image_quality
        self._last_api_request = 0.0
        self.client = httpx.Client(
            timeout=40.0,
            follow_redirects=True,
            headers={
                "User-Agent": "MoxfieldCartasES/0.1 (aplicacion personal)",
                "Accept": "application/json",
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
        resolution_mode: str = "exact_first",
        quality_mode: str = "prefer_highres",
    ) -> ResolvedCard:
        if resolution_mode not in {"exact_first", "exact_only", "flexible"}:
            raise ValueError(f"Modo de resolución desconocido: {resolution_mode}")
        if quality_mode not in {"allow_lowres", "prefer_highres", "highres_only"}:
            raise ValueError(f"Modo de calidad desconocido: {quality_mode}")

        has_exact_printing = bool(card.set_code and card.collector_number)
        prefer_highres_search = quality_mode != "allow_lowres"
        candidates: list[tuple[str, dict[str, Any]]] = []

        def add_candidate(status: str, candidate: dict[str, Any] | None) -> None:
            if candidate and self._has_usable_image(candidate):
                candidates.append((status, candidate))

        if resolution_mode in {"exact_first", "exact_only"} and has_exact_printing:
            add_candidate(
                "Misma impresión en español",
                self._get_card_by_printing(
                    card.set_code or "",
                    card.collector_number or "",
                    language="es",
                ),
            )
            if allow_english_fallback:
                add_candidate(
                    "Misma impresión en inglés",
                    self._get_card_by_printing(
                        card.set_code or "",
                        card.collector_number or "",
                        language=None,
                    ),
                )

        if resolution_mode == "exact_only":
            if not has_exact_printing:
                return ResolvedCard(
                    source=card,
                    status="Sin impresión exacta",
                    error=(
                        "La carta no incluye edición y número de coleccionista "
                        "en la lista."
                    ),
                )

        elif resolution_mode == "exact_first":
            add_candidate(
                "Otra impresión en español",
                self._find_printing(
                    card.name,
                    language="es",
                    prefer_highres=prefer_highres_search,
                ),
            )
            if allow_english_fallback:
                add_candidate(
                    "Otra impresión en inglés",
                    self._find_printing(
                        card.name,
                        language="en",
                        prefer_highres=prefer_highres_search,
                    ),
                )

        elif resolution_mode == "flexible":
            add_candidate(
                "Impresión flexible en español",
                self._find_printing(
                    card.name,
                    language="es",
                    prefer_highres=prefer_highres_search,
                ),
            )
            if allow_english_fallback:
                add_candidate(
                    "Impresión flexible en inglés",
                    self._find_printing(
                        card.name,
                        language="en",
                        prefer_highres=prefer_highres_search,
                    ),
                )

        selected_pair: tuple[str, dict[str, Any]] | None = None
        if quality_mode == "allow_lowres":
            selected_pair = candidates[0] if candidates else None
        else:
            selected_pair = next(
                (
                    pair
                    for pair in candidates
                    if self._is_highres(pair[1])
                ),
                None,
            )
            if not selected_pair and quality_mode == "prefer_highres":
                selected_pair = candidates[0] if candidates else None

        if (
            not selected_pair
            and allow_english_if_missing
            and not allow_english_fallback
            and not candidates
        ):
            english_candidates: list[tuple[str, dict[str, Any]]] = []

            def add_english_candidate(
                status: str,
                candidate: dict[str, Any] | None,
            ) -> None:
                if candidate and self._has_usable_image(candidate):
                    english_candidates.append((status, candidate))

            if (
                resolution_mode in {"exact_first", "exact_only"}
                and has_exact_printing
            ):
                add_english_candidate(
                    "Misma impresión en inglés (sin imagen en español)",
                    self._get_card_by_printing(
                        card.set_code or "",
                        card.collector_number or "",
                        language=None,
                    ),
                )

            if resolution_mode == "exact_first":
                add_english_candidate(
                    "Otra impresión en inglés (sin imagen en español)",
                    self._find_printing(
                        card.name,
                        language="en",
                        prefer_highres=prefer_highres_search,
                    ),
                )
            elif resolution_mode == "flexible":
                add_english_candidate(
                    "Impresión flexible en inglés (sin imagen en español)",
                    self._find_printing(
                        card.name,
                        language="en",
                        prefer_highres=prefer_highres_search,
                    ),
                )

            if quality_mode == "allow_lowres":
                selected_pair = (
                    english_candidates[0] if english_candidates else None
                )
            else:
                selected_pair = next(
                    (
                        pair
                        for pair in english_candidates
                        if self._is_highres(pair[1])
                    ),
                    None,
                )
                if not selected_pair and quality_mode == "prefer_highres":
                    selected_pair = (
                        english_candidates[0] if english_candidates else None
                    )
            if english_candidates:
                candidates.extend(english_candidates)

        if not selected_pair:
            quality_error = (
                "No se encontró una impresión con imagen de alta resolución."
                if quality_mode == "highres_only" and candidates
                else "No se encontró una imagen válida en Scryfall."
            )
            return ResolvedCard(
                source=card,
                status=(
                    "Sin alta resolución"
                    if quality_mode == "highres_only" and candidates
                    else "No encontrada"
                ),
                error=quality_error,
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
        if max_results < 1:
            return []

        language_groups: list[list[dict[str, Any]]] = []
        for language in languages:
            candidates = [
                candidate
                for candidate in self._search_printings(name, language)
                if self._has_usable_image(candidate)
                and (not highres_only or self._is_highres(candidate))
            ]
            candidates = sorted(
                candidates,
                key=lambda candidate: not self._is_highres(candidate),
            )
            language_groups.append(candidates)

        selected: list[dict[str, Any]] = []
        seen: set[str] = set()
        quota = max(1, max_results // max(len(language_groups), 1))

        for group in language_groups:
            for candidate in group[:quota]:
                key = self._candidate_identity(candidate)
                if key not in seen:
                    seen.add(key)
                    selected.append(candidate)

        if len(selected) < max_results:
            for group in language_groups:
                for candidate in group[quota:]:
                    key = self._candidate_identity(candidate)
                    if key in seen:
                        continue
                    seen.add(key)
                    selected.append(candidate)
                    if len(selected) >= max_results:
                        return selected

        return selected[:max_results]

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
                    "User-Agent": "MoxfieldCartasES/0.4 (aplicacion personal)",
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
    ) -> list[dict[str, Any]]:
        escaped = name.replace("\\", "\\\\").replace('"', '\\"')
        data = self._request_json(
            "/cards/search",
            params={
                "q": f'!"{escaped}" lang:{language} game:paper',
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

        return [
            candidate
            for candidate in cards
            if isinstance(candidate, dict)
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

        self._respect_rate_limit()
        url = f"{SCRYFALL_API}{path}"
        response: httpx.Response | None = None
        for attempt in range(3):
            response = self.client.get(url, params=params)
            self._last_api_request = time.monotonic()
            if response.status_code != 429:
                break
            retry_after = float(response.headers.get("Retry-After", "1"))
            time.sleep(max(retry_after, 1.0) * (attempt + 1))

        if response is None:
            raise ScryfallError("No se recibió respuesta de Scryfall.")
        if response.status_code == 404 and allow_not_found:
            return None
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ScryfallError(
                f"Scryfall devolvió el error HTTP {response.status_code}."
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise ScryfallError("Scryfall no devolvió un JSON válido.") from exc
        if not isinstance(payload, dict):
            raise ScryfallError("Scryfall devolvió un formato inesperado.")

        cache_path.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        return payload

    def _respect_rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_api_request
        remaining = 0.11 - elapsed
        if remaining > 0:
            time.sleep(remaining)
