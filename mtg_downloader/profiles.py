from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DownloadProfile:
    key: str
    label: str
    description: str
    resolution_mode: str
    quality_mode: str
    allow_english: bool


PROFILES: tuple[DownloadProfile, ...] = (
    DownloadProfile(
        key="balanced",
        label="Equilibrado — recomendado",
        description=(
            "Intenta respetar la edición, prioriza imágenes de alta resolución "
            "y usa inglés cuando sea necesario. Las imágenes low-res quedan "
            "como último recurso."
        ),
        resolution_mode="exact_first",
        quality_mode="prefer_highres",
        allow_english=True,
    ),
    DownloadProfile(
        key="fidelity",
        label="Fidelidad al listado",
        description=(
            "Solo utiliza la edición y el número indicados. Prioriza español y "
            "después inglés, aunque la imagen disponible sea low-res."
        ),
        resolution_mode="exact_only",
        quality_mode="allow_lowres",
        allow_english=True,
    ),
    DownloadProfile(
        key="maximum_quality",
        label="Máxima calidad",
        description=(
            "Ignora la edición indicada y busca una imagen de alta resolución: "
            "primero en español y después en inglés. Omite las cartas para las "
            "que solo exista una imagen low-res."
        ),
        resolution_mode="flexible",
        quality_mode="highres_only",
        allow_english=True,
    ),
    DownloadProfile(
        key="spanish_only",
        label="Solo español",
        description=(
            "Nunca utiliza imágenes inglesas. Intenta respetar la edición, "
            "pero puede cambiar a otra impresión española de mejor calidad."
        ),
        resolution_mode="exact_first",
        quality_mode="prefer_highres",
        allow_english=False,
    ),
)


def get_profile(key: str) -> DownloadProfile:
    for profile in PROFILES:
        if profile.key == key:
            return profile
    raise ValueError(f"Perfil desconocido: {key}")
