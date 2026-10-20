"""V7.2 — утверждённые product-slug проектов и гарды упаковки."""

from __future__ import annotations

from typing import Any

# Семь продуктовых карточек (+ опциональный скрытый cvlab).
APPROVED_PRODUCT_SLUGS = frozenset(
    {
        "strogino",
        "amursky",
        "teatralny",
        "nevsky",
        "pravda",
        "plekhanova",
        "parkline",
    }
)
LAB_SLUGS = frozenset({"cvlab"})

# Каталожные ЖК из открытых деклараций — видны в /api/portfolio для фильтров.
CATALOG_DATA_ORIGINS = frozenset(
    {
        "BETONIJ_DECLARATIONS",
        "PORTFOLIO_CATALOG",
        "DOMRF_CATALOG",
    }
)


def project_slug(settings: dict[str, Any] | None) -> str:
    return str((settings or {}).get("slug") or "").strip().lower()


def is_approved_product(settings: dict[str, Any] | None) -> bool:
    return project_slug(settings) in APPROVED_PRODUCT_SLUGS


def is_lab_slug(settings: dict[str, Any] | None) -> bool:
    return project_slug(settings) in LAB_SLUGS


def is_catalog_project(settings: dict[str, Any] | None) -> bool:
    origin = str((settings or {}).get("data_origin") or "").strip().upper()
    if origin in CATALOG_DATA_ORIGINS:
        return True
    slug = project_slug(settings)
    return slug.startswith("cat-") or slug.startswith("domrf-")


def is_visible_in_portfolio(settings: dict[str, Any] | None, *, include_lab: bool = False) -> bool:
    slug = project_slug(settings)
    if slug in LAB_SLUGS:
        return include_lab
    if slug in APPROVED_PRODUCT_SLUGS:
        return True
    return is_catalog_project(settings)
