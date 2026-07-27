from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from .models import DeckCard, ImageFace, ResolvedCard

SCRYFALL_API = "https://api.scryfall.com"


class ScryfallError(RuntimeError):
    pass


class ScryfallClient:
    def __init__(self, cache_dir: Path, image_quality: str = "large") -> None:
        self.cache_dir = cache_dir
        self.json_cache = cache_dir / "json"
        self.image_cache = cache_dir / "images"
        self.json_cache.mkdir(parents=True, exist_ok=True)
        self.image_cache.mkdir(parents=True, exist_ok=True)
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
        resolution_mode: str = "exact_first",
    ) -> ResolvedCard:
        selected: dict[str, Any] | None = None
        status = ""

        if resolution_mode not in {"exact_first", "exact_only", "flexible"}:
            raise ValueError(f"Modo de resolución desconocido: {resolution_mode}")

        has_exact_printing = bool(card.set_code and card.collector_number)

        if resolution_mode in {"exact_first", "exact_only"} and has_exact_printing:
            # 1. Misma impresión en español.
            selected = self._get_card_by_printing(
                card.set_code or "",
                card.collector_number or "",
                language="es",
            )
            if selected:
                status = "Misma impresión en español"

            # 2. Misma impresión en inglés.
            if not selected and allow_english_fallback:
                selected = self._get_card_by_printing(
                    card.set_code or "",
                    card.collector_number or "",
                    language=None,
                )
                if selected:
                    status = "Misma impresión en inglés"

        if resolution_mode == "exact_only":
            # Si no se indicó edición/número, no hay una impresión exacta que respetar.
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
            # 3. Cualquier impresión oficial en español.
            if not selected:
                selected = self._find_spanish_printing(card.name)
                if selected:
                    status = "Otra impresión en español"

            # 4. Otra impresión en inglés.
            if not selected and allow_english_fallback:
                selected = self._get_named(card.name)
                if selected:
                    status = "Otra impresión en inglés"

        elif resolution_mode == "flexible":
            # Ignora la impresión indicada y prioriza el idioma.
            selected = self._find_spanish_printing(card.name)
            if selected:
                status = "Impresión flexible en español"

            if not selected and allow_english_fallback:
                selected = self._get_named(card.name)
                if selected:
                    status = "Impresión flexible en inglés"

        if not selected:
            return ResolvedCard(
                source=card,
                status="No encontrada",
                error="No se encontró una imagen válida en Scryfall.",
            )

        faces = self._extract_faces(selected)
        if not faces:
            return ResolvedCard(
                source=card,
                status="Sin imagen",
                language=selected.get("lang"),
                printed_name=selected.get("printed_name") or selected.get("name"),
                selected_set=selected.get("set"),
                collector_number=str(selected.get("collector_number") or ""),
                scryfall_data=selected,
                error="Scryfall encontró la carta, pero no ofrece una imagen descargable.",
            )

        return ResolvedCard(
            source=card,
            status=status,
            language=selected.get("lang"),
            printed_name=selected.get("printed_name") or selected.get("name"),
            selected_set=selected.get("set"),
            collector_number=str(selected.get("collector_number") or ""),
            faces=faces,
            scryfall_data=selected,
            downloaded_format=faces[0].extension.lstrip(".").upper() if faces else None,
        )

    def download_image(self, face: ImageFace) -> bytes:
        key = hashlib.sha256(face.url.encode("utf-8")).hexdigest()
        path = self.image_cache / f"{key}{face.extension}"
        if path.exists() and path.stat().st_size > 0:
            return path.read_bytes()

        response = self.client.get(
            face.url,
            headers={
                "User-Agent": "MoxfieldCartasES/0.1 (aplicacion personal)",
                "Accept": "image/avif,image/webp,image/png,image/jpeg,*/*",
            },
        )
        response.raise_for_status()
        path.write_bytes(response.content)
        return response.content

    def _get_card_by_printing(
        self, set_code: str, collector_number: str, language: str | None
    ) -> dict[str, Any] | None:
        suffix = f"/{language}" if language else ""
        encoded_set = quote(set_code.lower(), safe="")
        encoded_number = quote(str(collector_number), safe="")
        path = f"/cards/{encoded_set}/{encoded_number}{suffix}"
        return self._request_json(path, allow_not_found=True)

    def _find_spanish_printing(self, name: str) -> dict[str, Any] | None:
        escaped = name.replace("\\", "\\\\").replace('"', '\\"')
        data = self._request_json(
            "/cards/search",
            params={
                "q": f'!"{escaped}" lang:es game:paper',
                "order": "released",
                "dir": "desc",
                "unique": "prints",
            },
            allow_not_found=True,
        )
        if not data:
            return None
        cards = data.get("data") if isinstance(data, dict) else None
        if not isinstance(cards, list):
            return None
        for candidate in cards:
            if isinstance(candidate, dict) and candidate.get("image_status") != "missing":
                return candidate
        return next((item for item in cards if isinstance(item, dict)), None)

    def _get_named(self, name: str) -> dict[str, Any] | None:
        return self._request_json(
            "/cards/named", params={"exact": name}, allow_not_found=True
        )

    def _extract_faces(self, card: dict[str, Any]) -> list[ImageFace]:
        image_uris = card.get("image_uris")
        if isinstance(image_uris, dict):
            face = self._face_from_uris(
                card.get("printed_name") or card.get("name") or "Carta", image_uris
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
                face = self._face_from_uris(str(label), uris)
                if face:
                    result.append(face)
        return result

    def _face_from_uris(
        self, label: str, uris: dict[str, Any]
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
                return ImageFace(label=label, url=url, extension=extension)
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
