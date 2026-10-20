"""PDF из общего report DTO (fpdf2). Без CV inference."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fpdf import FPDF


def _font_path() -> Path | None:
    candidates = [
        Path(r"C:\Windows\Fonts\arial.ttf"),
        Path(r"C:\Windows\Fonts\Arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


class _ReportPDF(FPDF):
    def __init__(self, title: str) -> None:
        super().__init__(format="A4")
        self._title = title
        self.set_auto_page_break(auto=True, margin=16)
        font = _font_path()
        if font:
            self.add_font("PS", "", str(font))
            bold = Path(r"C:\Windows\Fonts\arialbd.ttf")
            if bold.exists():
                self.add_font("PS", "B", str(bold))
            else:
                self.add_font("PS", "B", str(font))
            self._family = "PS"
        else:
            self._family = "Helvetica"

    def header(self) -> None:
        self.set_font(self._family, "B" if self._family == "PS" else "", 9)
        self.set_text_color(40, 55, 80)
        self.cell(0, 6, self._title[:90], align="L")
        self.ln(8)

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font(self._family, "", 8)
        self.set_text_color(100, 110, 130)
        self.cell(0, 8, f"стр. {self.page_no()} · PlanSight", align="C")

    def heading(self, text: str, size: int = 13) -> None:
        self.set_x(self.l_margin)
        self.set_font(self._family, "B" if self._family == "PS" else "", size)
        self.set_text_color(20, 40, 70)
        self.multi_cell(self.epw, 7, text)
        self.ln(2)

    def para(self, text: str, size: int = 10) -> None:
        self.set_x(self.l_margin)
        self.set_font(self._family, "", size)
        self.set_text_color(40, 55, 75)
        self.multi_cell(self.epw, 5, text or "Не зафиксировано")
        self.ln(1)

    def kv(self, key: str, value: str) -> None:
        self.set_x(self.l_margin)
        self.set_font(self._family, "B" if self._family == "PS" else "", 9)
        label_w = 48
        y = self.get_y()
        self.cell(label_w, 5, key)
        self.set_xy(self.l_margin + label_w, y)
        self.set_font(self._family, "", 9)
        self.multi_cell(self.epw - label_w, 5, value or "Не зафиксировано")


def _resolve_frame_file(fid: int) -> Path | None:
    from app.core.config import get_settings
    from app.db.models import Frame, SessionLocal

    db = SessionLocal()
    try:
        row = db.get(Frame, int(fid))
        if row and row.file_path:
            p = Path(row.file_path)
            if p.exists():
                return p
    finally:
        db.close()
    settings = get_settings()
    candidates = list(settings.frames_dir().glob(f"**/frame_{fid}.*"))
    candidates += list(settings.frames_dir().glob(f"**/{fid}.*"))
    return next((c for c in candidates if c.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")), None)


def _embed_frame(pdf: _ReportPDF, fr: dict[str, Any], project_id: int) -> None:
    del project_id  # reserved for future project-scoped storage layout
    fid = fr.get("frame_id")
    caption = (
        f"Frame #{fid} · {fr.get('captured_at') or '—'} · "
        f"камера {fr.get('camera_id') or '—'} · {fr.get('timestamp_source') or '—'}"
    )
    pdf.para(caption, size=8)
    if not fid:
        pdf.para("Изображение недоступно")
        return
    img = _resolve_frame_file(int(fid))
    if img is None:
        pdf.para("Изображение недоступно в хранилище отчёта")
        return
    try:
        x = pdf.get_x()
        pdf.image(str(img), x=x, w=90)
        pdf.ln(58)
    except Exception:
        pdf.para("Не удалось вложить изображение")


def render_finding_pdf(dto: dict[str, Any], out_path: Path) -> Path:
    project = dto.get("project") or {}
    finding = dto.get("finding") or {}
    title = f"PlanSight · finding {finding.get('finding_id')}"
    pdf = _ReportPDF(title)
    pdf.add_page()
    pdf.heading("Отчёт по предупреждению")
    pdf.kv("Проект", str(project.get("name") or project.get("id")))
    pdf.kv("Адрес", str(project.get("address") or "Не зафиксировано"))
    pdf.kv("Finding ID", str(finding.get("finding_id")))
    pdf.kv("Сформирован", str(dto.get("generated_at")))
    pdf.kv("Автор", str(dto.get("author")))
    pdf.ln(2)
    pdf.heading("Краткое резюме", 11)
    pdf.para(str(finding.get("explanation_ru")))
    pdf.kv("Код", str(finding.get("code")))
    pdf.kv("Lifecycle", str(finding.get("lifecycle")))
    pdf.kv("Matching", str(finding.get("match_status")))
    pdf.kv("HumanVerdict", str(finding.get("last_verdict") or "нет"))
    si = finding.get("schedule_item")
    if si:
        pdf.kv("Работа КСГ", str(si.get("name")))
    elif finding.get("schedule_item_refused_reason"):
        pdf.para(str(finding["schedule_item_refused_reason"]))
    pdf.heading("Ожидалось / наблюдалось", 11)
    pdf.para("Ожидалось: " + ", ".join(str(x) for x in (finding.get("expected") or [])) or "Не зафиксировано")
    pdf.para("Наблюдалось: " + ", ".join(str(x) for x in (finding.get("observed") or [])) or "Не зафиксировано")
    pdf.heading("Decision Trace", 11)
    tr = finding.get("decision_trace") or {}
    pdf.kv("Статус trace", str(tr.get("trace_status")))
    for step in tr.get("user_logic") or []:
        pdf.para(f"• {step.get('title')}: {step.get('body')}")
    pdf.heading("Ограничения", 11)
    for lim in finding.get("limitations") or ["Не зафиксировано"]:
        pdf.para(f"• {lim}")
    pdf.heading("Кадры-доказательства", 11)
    frames = finding.get("frames") or []
    if not frames:
        pdf.para("Нет связанных кадров")
    for fr in frames:
        _embed_frame(pdf, fr, int(project.get("id") or 0))
        dets = fr.get("detections") or []
        if dets:
            pdf.para(
                "Детекции: "
                + "; ".join(
                    f"{d.get('equipment_code')} ({d.get('confidence')})"
                    for d in dets[:8]
                ),
                size=8,
            )
    pdf.heading("История решений", 11)
    hist = finding.get("verdict_history") or []
    if not hist:
        pdf.para("История пуста")
    for v in hist:
        pdf.para(f"{v.get('created_at') or '—'} · {v.get('verdict')} · {v.get('user_id') or '—'}")
    pdf.heading("Рекомендация", 11)
    pdf.para(str(finding.get("recommendation")))
    pdf.ln(3)
    pdf.para(str(dto.get("disclaimer")))
    pdf.para(str(dto.get("methodology_note")), size=8)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out_path))
    return out_path


def render_project_pdf(dto: dict[str, Any], out_path: Path) -> Path:
    project = dto.get("project") or {}
    title = f"PlanSight · {project.get('name') or project.get('id')}"
    pdf = _ReportPDF(title)
    pdf.add_page()
    pdf.heading("Отчёт по отклонениям проекта")
    pdf.kv("Проект", str(project.get("name")))
    pdf.kv("Период", f"{(dto.get('period') or {}).get('date_from') or '—'} — {(dto.get('period') or {}).get('date_to') or '—'}")
    pdf.kv("Сформирован", str(dto.get("generated_at")))
    pdf.kv("Версия КСГ", str(dto.get("schedule_version_id") or "Не зафиксировано"))
    pdf.ln(2)
    pdf.heading("Управленческое резюме", 11)
    s = dto.get("summary") or {}
    for k, label in (
        ("total", "Всего findings"),
        ("open", "Открытые / в проверке"),
        ("confirmed_by_specialist", "Подтверждены специалистом"),
        ("rejected_false_positive", "Ложные срабатывания"),
        ("no_data", "NO_DATA / coverage gap"),
        ("cv_verified", "CV_VERIFIED_FINDING"),
    ):
        pdf.kv(label, str(s.get(k, 0)))
    pdf.para(str(dto.get("disclaimer")))
    pdf.heading("Реестр отклонений", 11)
    for row in dto.get("registry") or []:
        pdf.para(
            f"#{row.get('finding_id')} · {row.get('code')} · {row.get('lifecycle')} · "
            f"match={row.get('match_status')} · кадры={row.get('evidence_frames')} · "
            f"{(row.get('explanation_ru') or '')[:160]}"
        )
    for f in dto.get("findings") or []:
        pdf.add_page()
        pdf.heading(f"Finding #{f.get('finding_id')}", 12)
        pdf.para(str(f.get("explanation_ru")))
        pdf.kv("Matching", str(f.get("match_status")))
        if f.get("schedule_item"):
            pdf.kv("КСГ", str((f.get("schedule_item") or {}).get("name")))
        elif f.get("schedule_item_refused_reason"):
            pdf.para(str(f["schedule_item_refused_reason"]))
        for fr in (f.get("frames") or [])[:3]:
            _embed_frame(pdf, fr, int(project.get("id") or 0))
    pdf.add_page()
    pdf.heading("Методика и ограничения", 11)
    pdf.para(str(dto.get("methodology_note")))
    pdf.para(f"Фильтры: {dto.get('filters')}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out_path))
    return out_path
