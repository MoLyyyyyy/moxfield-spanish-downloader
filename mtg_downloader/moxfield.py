from __future__ import annotations

import re
from typing import Any, Iterable
from urllib.parse import urlparse

import httpx

from .decklist import merge_cards
from .models import DeckCard

MOXFIELD_API = "https://api2.moxfield.com/v3/decks/all/{deck_id}"
_DECK_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,80}$")


class MoxfieldError(RuntimeError):
    pass


def extract_deck_id(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Introduce un enlace o identificador de Moxfield.")

    if _DECK_ID_RE.fullmatch(value):
        return value

    parsed = urlparse(value)
    if parsed.netloc.lower() not in {"moxfield.com", "www.moxfield.com"}:
        raise ValueError("El enlace no pertenece a moxfield.com.")

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2 or parts[0].lower() != "decks":
        raise ValueError("No se ha encontrado el identificador del mazo.")

    deck_id = parts[1]
    if not _DECK_ID_RE.fullmatch(deck_id):
        raise ValueError("El identificador del mazo no tiene un formato válido.")
    return deck_id


def fetch_deck(value: str, timeout: float = 30.0) -> dict[str, Any]:
    deck_id = extract_deck_id(value)
    headers = {
        "Accept": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150 Safari/537.36"
        ),
        "Referer": f"https://www.moxfield.com/decks/{deck_id}",
        "Origin": "https://www.moxfield.com",
    }

    try:
        response = httpx.get(
            MOXFIELD_API.format(deck_id=deck_id),
            headers=headers,
            timeout=timeout,
            follow_redirects=True,
        )
    except httpx.HTTPError as exc:
        raise MoxfieldError(f"No se pudo conectar con Moxfield: {exc}") from exc

    if response.status_code in {401, 403, 429}:
        raise MoxfieldError(
            "Moxfield ha bloqueado la lectura automática mediante su protección. "
            "Pega la exportación de texto del mazo para continuar."
        )
    if response.status_code == 404:
        raise MoxfieldError("El mazo no existe, es privado o el enlace no es correcto.")
    if response.is_error:
        raise MoxfieldError(
            f"Moxfield devolvió el error HTTP {response.status_code}. "
            "Puedes usar la exportación de texto como respaldo."
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise MoxfieldError("Moxfield no devolvió un JSON válido.") from exc

    if not isinstance(data, dict):
        raise MoxfieldError("La respuesta de Moxfield tiene un formato inesperado.")
    return data


def parse_deck(
    data: dict[str, Any],
    *,
    include_sideboard: bool = False,
    include_maybeboard: bool = False,
) -> tuple[str, list[DeckCard]]:
    deck_name = str(data.get("name") or data.get("deckName") or "Mazo de Moxfield")

    zone_names = [
        "commanders",
        "partners",
        "companions",
        "signatureSpells",
        "mainboard",
    ]
    if include_sideboard:
        zone_names.append("sideboard")
    if include_maybeboard:
        zone_names.append("maybeboard")

    cards: list[DeckCard] = []
    boards = data.get("boards") if isinstance(data.get("boards"), dict) else None

    for zone in zone_names:
        # V3 usa boards; versiones antiguas exponían las zonas arriba.
        if boards and zone in boards:
            cards.extend(_parse_zone(boards[zone], zone))
        elif zone in data:
            cards.extend(_parse_zone(data[zone], zone))

    if not cards:
        raise MoxfieldError(
            "No se encontraron cartas. El formato interno de Moxfield puede haber cambiado."
        )

    return deck_name, merge_cards(cards)


def _parse_zone(container: Any, zone: str) -> list[DeckCard]:
    if not container:
        return []

    if isinstance(container, dict) and "cards" in container:
        container = container["cards"]

    entries: Iterable[tuple[str | None, Any]]
    if isinstance(container, dict):
        entries = container.items()
    elif isinstance(container, list):
        entries = ((None, item) for item in container)
    else:
        return []

    cards: list[DeckCard] = []
    for fallback_name, entry in entries:
        if not isinstance(entry, dict):
            continue

        card_data = entry.get("card") if isinstance(entry.get("card"), dict) else entry
        quantity = _to_int(entry.get("quantity") or entry.get("count") or 1, default=1)
        name = _first_text(card_data, "name", "cardName", "oracleName")
        if not name and isinstance(fallback_name, str):
            name = fallback_name
        if not name:
            continue

        set_code = _first_text(card_data, "set", "setCode", "edition", "set_code")
        collector = _first_text(
            card_data, "cn", "collectorNumber", "collector_number", "number"
        )

        cards.append(
            DeckCard(
                quantity=max(quantity, 1),
                name=name,
                zone=zone,
                set_code=set_code.lower() if set_code else None,
                collector_number=collector,
            )
        )
    return cards


def _first_text(source: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = source.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
