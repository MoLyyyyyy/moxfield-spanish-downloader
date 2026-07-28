from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


@dataclass(frozen=True, slots=True)
class DeckPrintPosition:
    index: int
    name: str
    cards: int
    start_sheet: int
    start_slot: int
    end_sheet: int
    end_slot: int

    @property
    def start_label(self) -> str:
        return f"Hoja {self.start_sheet}, posición {self.start_slot}"

    @property
    def end_label(self) -> str:
        return f"Hoja {self.end_sheet}, posición {self.end_slot}"


def build_print_map(
    summaries: list[dict[str, Any]],
    *,
    slots_per_sheet: int = 9,
) -> list[DeckPrintPosition]:
    if slots_per_sheet < 1:
        raise ValueError("Las posiciones por hoja deben ser mayores que cero.")

    rows: list[DeckPrintPosition] = []
    offset = 0
    for position, summary in enumerate(summaries, start=1):
        cards = int(summary.get("copies") or 0)
        if cards < 1:
            continue
        start = offset
        end = offset + cards - 1
        rows.append(
            DeckPrintPosition(
                index=int(summary.get("index") or position),
                name=str(summary.get("name") or f"Mazo {position}"),
                cards=cards,
                start_sheet=start // slots_per_sheet + 1,
                start_slot=start % slots_per_sheet + 1,
                end_sheet=end // slots_per_sheet + 1,
                end_slot=end % slots_per_sheet + 1,
            )
        )
        offset += cards
    return rows


def preferred_page_pair_breaks(
    summaries: list[dict[str, Any]],
    *,
    slots_per_sheet: int = 9,
) -> set[int]:
    """Return page-pair boundaries that coincide exactly with deck endings."""
    breaks: set[int] = set()
    cumulative = 0
    for summary in summaries[:-1]:
        cumulative += int(summary.get("copies") or 0)
        if cumulative and cumulative % slots_per_sheet == 0:
            breaks.add(cumulative // slots_per_sheet)
    return breaks


def print_map_csv(rows: list[DeckPrintPosition]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        [
            "Orden",
            "Mazo",
            "Cartas",
            "Hoja inicial",
            "Posición inicial",
            "Hoja final",
            "Posición final",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row.index,
                row.name,
                row.cards,
                row.start_sheet,
                row.start_slot,
                row.end_sheet,
                row.end_slot,
            ]
        )
    return output.getvalue().encode("utf-8-sig")


def print_map_pdf(
    rows: list[DeckPrintPosition],
    *,
    title: str = "Mapa de posiciones de impresión",
) -> bytes:
    output = io.BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=14 * mm,
        leftMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=title,
    )
    styles = getSampleStyleSheet()
    story = [Paragraph(title, styles["Title"]), Spacer(1, 5 * mm)]
    data: list[list[Any]] = [
        ["#", "Mazo", "Cartas", "Comienza", "Termina"]
    ]
    for row in rows:
        data.append(
            [
                str(row.index),
                Paragraph(row.name, styles["BodyText"]),
                str(row.cards),
                row.start_label,
                row.end_label,
            ]
        )
    table = Table(
        data,
        colWidths=[10 * mm, 64 * mm, 17 * mm, 42 * mm, 42 * mm],
        repeatRows=1,
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E9ECEF")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8F9FA")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 5 * mm))
    story.append(
        Paragraph(
            "Las posiciones se cuentan de izquierda a derecha y de arriba "
            "abajo dentro de cada hoja 3x3. Los mazos se imprimen sin saltos "
            "de hoja entre ellos.",
            styles["BodyText"],
        )
    )
    document.build(story)
    return output.getvalue()
