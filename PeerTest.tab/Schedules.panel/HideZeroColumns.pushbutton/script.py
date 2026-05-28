# -*- coding: utf-8 -*-
__title__  = 'Скрыть\nнулевые'
__author__ = 'Dima'
__doc__    = '''Version = 2.0
Description: В выбранной спецификации (ведомость расхода стали) для заданного
списка параметров диаметров арматуры скрывает столбцы, где все значения = 0,
и показывает столбцы, где есть ненулевое значение.
Остальные столбцы спецификации не трогаются.
How-To:
    1) Либо предварительно выбрать таблицу на листе, либо запустить и кликнуть.
    2) Скрипт обрабатывает ТОЛЬКО параметры из списка TARGET_PARAMS.
'''

import sys
import re
from Autodesk.Revit.DB import (
    ScheduleSheetInstance, ViewSchedule, SectionType, Transaction
)
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
from pyrevit import forms, script

doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
output = script.get_output()

# ---------------------------------------------------------------------------
# СПИСОК ПАРАМЕТРОВ, КОТОРЫМИ УПРАВЛЯЕТ СКРИПТ
# (если нужно — отредактируй прямо здесь)
# ---------------------------------------------------------------------------
TARGET_PARAMS = [
    u'Ø6 A500',
    u'Ø6.5 A500',
    u'Ø8 A500',
    u'Ø9 A500',
    u'Ø10 A500',
    u'Ø12 A500',
    u'Ø14 A500',
    u'Ø16 A500',
    u'Ø18 A500',
    u'Ø20 A500',
    u'Ø22 A500',
    u'Ø25 A500',
    u'Ø28 A500',
    u'Ø32 A500',
    u'Ø36 A500',
    u'Ø40 A500',
]


# Cyrillic letters visually identical to Latin -> Latin
_CYR_TO_LAT = {
    u'А': u'A', u'В': u'B', u'С': u'C', u'Е': u'E', u'Н': u'H',
    u'К': u'K', u'М': u'M', u'О': u'O', u'Р': u'P', u'Т': u'T',
    u'Х': u'X', u'У': u'Y',
    u'а': u'a', u'в': u'b', u'с': u'c', u'е': u'e', u'н': u'h',
    u'к': u'k', u'м': u'm', u'о': u'o', u'р': u'p', u'т': u't',
    u'х': u'x', u'у': u'y',
}

def normalize(s):
    if s is None:
        return ''
    s = s.strip().replace(' ', '').replace(u' ', '')
    # unify Cyrillic homoglyphs with Latin
    out = []
    for ch in s:
        out.append(_CYR_TO_LAT.get(ch, ch))
    return ''.join(out).lower()

TARGET_SET = set(normalize(p) for p in TARGET_PARAMS)


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------
class ScheduleSheetInstanceFilter(ISelectionFilter):
    def AllowElement(self, elem):
        return isinstance(elem, ScheduleSheetInstance)
    def AllowReference(self, ref, pt):
        return False


def get_schedule_instance():
    for eid in uidoc.Selection.GetElementIds():
        el = doc.GetElement(eid)
        if isinstance(el, (ScheduleSheetInstance, ViewSchedule)):
            return el
    try:
        ref = uidoc.Selection.PickObject(
            ObjectType.Element,
            ScheduleSheetInstanceFilter(),
            'Выберите спецификацию на листе'
        )
    except Exception:
        sys.exit()
    if ref is None:
        sys.exit()
    return doc.GetElement(ref.ElementId)


def get_view_schedule(picked):
    if isinstance(picked, ViewSchedule):
        return picked
    if isinstance(picked, ScheduleSheetInstance):
        return doc.GetElement(picked.ScheduleId)
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_NUM_RE = re.compile(r'-?\d+(?:[.,]\d+)?')

def parse_number(s):
    """Treat as numeric ONLY if the cell starts with digit/sign/dot.
    Anything starting with a letter (Ø, ù, A, etc.) is a header — return None."""
    if s is None:
        return None
    s = s.strip()
    if s == '':
        return None
    first = s[0]
    if not (first.isdigit() or first in ('+', '-', '.', ',')):
        return None
    # strip trailing units (letters, %, спецсимволы)
    m = re.match(r'^[+\-]?\d+(?:[.,]\d+)?', s)
    if not m:
        return None
    try:
        return abs(float(m.group(0).replace(',', '.')))
    except ValueError:
        return None


def field_display_name(fld):
    try:
        n = fld.GetName()
        if n:
            return n
    except Exception:
        pass
    try:
        return fld.ColumnHeading or '<field>'
    except Exception:
        return '<field>'


def is_target_field(fld):
    """Match field by parameter name OR column heading against TARGET_SET."""
    candidates = []
    try:
        candidates.append(fld.GetName())
    except Exception:
        pass
    try:
        candidates.append(fld.ColumnHeading)
    except Exception:
        pass
    for c in candidates:
        if c and normalize(c) in TARGET_SET:
            return True
    return False


def detect_header_row_count(body, definition):
    headings = set()
    for i in range(definition.GetFieldCount()):
        fld = definition.GetField(i)
        for v in (getattr(fld, 'ColumnHeading', None),
                  fld.GetName() if hasattr(fld, 'GetName') else None):
            if v:
                headings.add(v.strip())
    n_rows = body.NumberOfRows
    n_cols = body.NumberOfColumns
    header_rows = 0
    for row in range(n_rows):
        is_header = False
        for col in range(n_cols):
            try:
                txt = body.GetCellText(row, col)
            except Exception:
                txt = None
            if txt and txt.strip() in headings:
                is_header = True
                break
        if is_header:
            header_rows = row + 1
        else:
            break
    if header_rows == 0 and n_rows > 1:
        header_rows = 1
    return header_rows


def column_is_all_zero(body, body_col, header_rows):
    """Скрывать столбец только если ВСЕ строки данных (после шапки)
    либо пустые, либо распознаются как число = 0.
    Если хотя бы одна строка данных непустая и не равна нулю
    (включая случай, когда значение не парсится как число —
    например, нестандартный формат), — НЕ скрываем."""
    n_rows = body.NumberOfRows
    has_any_data = False
    for row in range(header_rows, n_rows):
        try:
            txt = body.GetCellText(row, body_col)
        except Exception:
            continue
        if txt is None:
            continue
        s = txt.strip()
        if s == '':
            continue
        has_any_data = True
        num = parse_number(s)
        if num is None:
            # непустая ячейка, не распознаётся как число —
            # считаем содержимым, столбец оставляем
            return False
        if num != 0.0:
            return False
    return has_any_data


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    picked = get_schedule_instance()
    vs = get_view_schedule(picked)
    if vs is None:
        forms.alert('Не удалось получить спецификацию.', title='Ошибка')
        return

    definition = vs.Definition
    field_count = definition.GetFieldCount()

    # Indices of target fields among ALL fields (display order).
    target_field_indices = []
    for i in range(field_count):
        fld = definition.GetField(i)
        if is_target_field(fld):
            target_field_indices.append(i)

    if not target_field_indices:
        forms.alert(
            'В спецификации не найдено ни одного из целевых параметров.\n\n'
            'Список ищется в TARGET_PARAMS внутри script.py.',
            title='Готово'
        )
        return

    hidden_names = []
    shown_names  = []
    errors = []

    with Transaction(doc, 'Авто-скрытие нулевых диаметров') as t:
        t.Start()

        # 1. Развернуть только целевые поля (чтобы прочитать их данные).
        for i in target_field_indices:
            try:
                fld = definition.GetField(i)
                if fld.IsHidden:
                    fld.IsHidden = False
            except Exception as e:
                errors.append('show #{}: {}'.format(i, e))

        try:
            doc.Regenerate()
        except Exception:
            pass

        body = vs.GetTableData().GetSectionData(SectionType.Body)
        n_rows = body.NumberOfRows
        n_cols = body.NumberOfColumns
        if n_rows == 0 or n_cols == 0:
            t.RollBack()
            forms.alert('В спецификации нет данных.', title='Готово')
            return

        header_rows = detect_header_row_count(body, definition)

        # 2. Body column index -> field display index (по всем видимым полям).
        col_to_field = []
        for i in range(field_count):
            try:
                fld = definition.GetField(i)
                if not fld.IsHidden:
                    col_to_field.append(i)
            except Exception:
                pass

        target_set_idx = set(target_field_indices)

        # 3. Скрыть нулевые ИЗ ЦЕЛЕВЫХ.
        debug_rows = []  # list of (name, [cell_texts])
        for col in range(min(n_cols, len(col_to_field))):
            field_idx = col_to_field[col]
            if field_idx not in target_set_idx:
                continue
            try:
                fld = definition.GetField(field_idx)
                name = field_display_name(fld)

                # собрать содержимое ячеек этого столбца для отчёта
                cells = []
                for r in range(n_rows):
                    try:
                        cells.append(body.GetCellText(r, col))
                    except Exception:
                        cells.append('<err>')
                debug_rows.append((name, col, cells))

                if column_is_all_zero(body, col, header_rows):
                    fld.IsHidden = True
                    hidden_names.append(name)
                else:
                    shown_names.append(name)
            except Exception as e:
                errors.append('field #{}: {}'.format(field_idx, e))

        t.Commit()

    # ---- Диагностика по ячейкам ----
    output.print_md('### Содержимое ячеек по целевым столбцам')
    output.print_md('(всего строк в body: **{}**, header_rows={})'.format(
        n_rows, header_rows))
    for name, col, cells in debug_rows:
        output.print_md('**{}**  (body col {})'.format(name, col))
        for i, c in enumerate(cells):
            shown = '<None>' if c is None else (
                '<empty>' if c.strip() == '' else repr(c))
            output.print_md('- row {}: {}'.format(i, shown))

    output.print_md('### Скрыто (нулевые): **{}**'.format(len(hidden_names)))
    for n in hidden_names:
        output.print_md('- {}'.format(n))
    output.print_md('### Показано (есть значения): **{}**'.format(len(shown_names)))
    for n in shown_names:
        output.print_md('- {}'.format(n))
    if errors:
        output.print_md('### Ошибки:')
        for e in errors[:10]:
            output.print_md('- {}'.format(e))


main()
