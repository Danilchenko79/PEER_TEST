# -*- coding: utf-8 -*-
__title__  = 'Partition\nдля армирования'
__author__ = 'Dima'
__doc__    = '''Version = 1.0
Date      = 04.05.2026
Description:
    Заполняет параметр "Partition" у элементов:
      - Армирование по площади  (Area Reinforcement)
      - Армирование по траектории (Path Reinforcement)

    Скрипт определяет, какая арматура задана в элементе:
        - только нижняя           -> "Низ"
        - только верхняя          -> "Верх"
        - и верхняя, и нижняя     -> "Верх+Низ"
    и записывает соответствующее значение в Partition.

How-To:
    1. (Опционально) Выделите нужные элементы армирования
    2. Запустите скрипт
    3. Выберите режим: "Выделенные" или "Весь проект"
    4. Скрипт обновит Partition и покажет отчёт
'''

from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, BuiltInParameter,
    Transaction, ElementId
)
from Autodesk.Revit.DB.Structure import AreaReinforcement, PathReinforcement
from pyrevit import forms, script

doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
app   = __revit__.Application

# ------------------------------------------------------------
# Значения, которые будут записаны в Partition
# При необходимости отредактируйте здесь:
VAL_TOP    = 'Верх'
VAL_BOTTOM = 'Низ'
VAL_BOTH   = 'Верх+Низ'
PARAM_NAME = 'Partition'
# ------------------------------------------------------------

output = script.get_output()


# ----------------------------------------------------------------------
# Вспомогательные функции
# ----------------------------------------------------------------------
def get_param_int_safe(elem, bip):
    """Безопасно читает integer-значение BuiltInParameter. Возвращает None если нет."""
    try:
        p = elem.get_Parameter(bip)
        if p is None or not p.HasValue:
            return None
        return p.AsInteger()
    except Exception:
        return None


def area_has_top(area):
    """True, если у Area Reinforcement активна верхняя арматура (major или minor)."""
    # Сначала пробуем boolean-параметры активности слоёв
    flags = []
    for bip_name in ('REBAR_SYSTEM_ACTIVE_TOP_MAJOR_DIRECTION',
                     'REBAR_SYSTEM_ACTIVE_TOP_MINOR_DIRECTION'):
        bip = getattr(BuiltInParameter, bip_name, None)
        if bip is not None:
            v = get_param_int_safe(area, bip)
            if v is not None:
                flags.append(v == 1)
    if flags:
        return any(flags)

    # Fallback: LayoutRule != 0 (0 = None / нет арматуры)
    for bip_name in ('REBAR_SYSTEM_LAYOUT_RULE_TOP_MAJOR_DIRECTION',
                     'REBAR_SYSTEM_LAYOUT_RULE_TOP_MINOR_DIRECTION'):
        bip = getattr(BuiltInParameter, bip_name, None)
        if bip is not None:
            v = get_param_int_safe(area, bip)
            if v is not None and v != 0:
                return True
    return False


def area_has_bottom(area):
    """True, если у Area Reinforcement активна нижняя арматура (major или minor)."""
    flags = []
    for bip_name in ('REBAR_SYSTEM_ACTIVE_BOTTOM_MAJOR_DIRECTION',
                     'REBAR_SYSTEM_ACTIVE_BOTTOM_MINOR_DIRECTION'):
        bip = getattr(BuiltInParameter, bip_name, None)
        if bip is not None:
            v = get_param_int_safe(area, bip)
            if v is not None:
                flags.append(v == 1)
    if flags:
        return any(flags)

    for bip_name in ('REBAR_SYSTEM_LAYOUT_RULE_BOTTOM_MAJOR_DIRECTION',
                     'REBAR_SYSTEM_LAYOUT_RULE_BOTTOM_MINOR_DIRECTION'):
        bip = getattr(BuiltInParameter, bip_name, None)
        if bip is not None:
            v = get_param_int_safe(area, bip)
            if v is not None and v != 0:
                return True
    return False


def path_face_value(path):
    """
    Возвращает 'top' / 'bottom' / None для PathReinforcement.
    PATH_REIN_FACE: 0 = Top (Far), 1 = Bottom (Near)  (как правило)
    Используем оба источника — параметр и свойство Face — для надёжности.
    """
    bip = getattr(BuiltInParameter, 'PATH_REIN_FACE', None)
    if bip is not None:
        v = get_param_int_safe(path, bip)
        if v == 0:
            return 'top'
        elif v == 1:
            return 'bottom'

    # Fallback через свойство .Face (enum со строковым представлением)
    try:
        face = getattr(path, 'Face', None)
        if face is not None:
            s = str(face).lower()
            if 'top' in s or 'far' in s:
                return 'top'
            if 'bottom' in s or 'near' in s:
                return 'bottom'
    except Exception:
        pass
    return None


def decide_partition(has_top, has_bottom):
    """Возвращает строку для Partition или None если арматура не определена."""
    if has_top and has_bottom:
        return VAL_BOTH
    if has_top:
        return VAL_TOP
    if has_bottom:
        return VAL_BOTTOM
    return None


def set_partition(elem, value):
    """
    Записывает value в параметр Partition. Возвращает (ok, msg).
    """
    p = elem.LookupParameter(PARAM_NAME)
    if p is None:
        return False, 'нет параметра "{}"'.format(PARAM_NAME)
    if p.IsReadOnly:
        return False, 'параметр "{}" только для чтения'.format(PARAM_NAME)
    try:
        p.Set(value)
        return True, 'ok'
    except Exception as e:
        return False, 'ошибка записи: {}'.format(e)


# ----------------------------------------------------------------------
# Сбор элементов
# ----------------------------------------------------------------------
def collect_from_selection():
    sel_ids = uidoc.Selection.GetElementIds()
    areas, paths = [], []
    for eid in sel_ids:
        e = doc.GetElement(eid)
        if isinstance(e, AreaReinforcement):
            areas.append(e)
        elif isinstance(e, PathReinforcement):
            paths.append(e)
    return areas, paths


def collect_from_project():
    areas = list(FilteredElementCollector(doc)
                 .OfCategory(BuiltInCategory.OST_AreaRein)
                 .WhereElementIsNotElementType()
                 .ToElements())
    paths = list(FilteredElementCollector(doc)
                 .OfCategory(BuiltInCategory.OST_PathRein)
                 .WhereElementIsNotElementType()
                 .ToElements())
    # Гарантируем правильный тип (на случай служебных элементов в категории)
    areas = [a for a in areas if isinstance(a, AreaReinforcement)]
    paths = [p for p in paths if isinstance(p, PathReinforcement)]
    return areas, paths


# ----------------------------------------------------------------------
# Главный сценарий
# ----------------------------------------------------------------------
mode = forms.CommandSwitchWindow.show(
    ['Выделенные элементы', 'Весь проект'],
    message='Откуда брать элементы армирования?'
)
if not mode:
    script.exit()

if mode == 'Выделенные элементы':
    areas, paths = collect_from_selection()
    if not areas and not paths:
        forms.alert('В выделении нет Area / Path Reinforcement.\n'
                    'Выделите элементы и запустите скрипт ещё раз,\n'
                    'либо выберите режим "Весь проект".',
                    title='Нет элементов')
        script.exit()
else:
    areas, paths = collect_from_project()
    if not areas and not paths:
        forms.alert('В проекте нет элементов Area / Path Reinforcement.',
                    title='Нет элементов')
        script.exit()

# ----------------------------------------------------------------------
# Обработка
# ----------------------------------------------------------------------
results = []   # [id_link, type, partition, status]
errors  = []
updated = 0
skipped = 0

with Transaction(doc, 'Set Partition for Reinforcement') as t:
    t.Start()

    # --- Area Reinforcement ---
    for a in areas:
        try:
            has_top    = area_has_top(a)
            has_bottom = area_has_bottom(a)
            value = decide_partition(has_top, has_bottom)
            if value is None:
                skipped += 1
                results.append([output.linkify(a.Id), 'Area',
                                '-', 'нет активной арматуры'])
                continue
            ok, msg = set_partition(a, value)
            if ok:
                updated += 1
                results.append([output.linkify(a.Id), 'Area', value, 'OK'])
            else:
                skipped += 1
                results.append([output.linkify(a.Id), 'Area', value, msg])
                errors.append('Area {}: {}'.format(a.Id, msg))
        except Exception as e:
            skipped += 1
            errors.append('Area {}: {}'.format(a.Id, e))
            results.append([output.linkify(a.Id), 'Area', '-', str(e)])

    # --- Path Reinforcement ---
    for p in paths:
        try:
            face = path_face_value(p)
            if face == 'top':
                value = VAL_TOP
            elif face == 'bottom':
                value = VAL_BOTTOM
            else:
                value = None

            if value is None:
                skipped += 1
                results.append([output.linkify(p.Id), 'Path',
                                '-', 'не определена сторона (Top/Bottom)'])
                continue

            ok, msg = set_partition(p, value)
            if ok:
                updated += 1
                results.append([output.linkify(p.Id), 'Path', value, 'OK'])
            else:
                skipped += 1
                results.append([output.linkify(p.Id), 'Path', value, msg])
                errors.append('Path {}: {}'.format(p.Id, msg))
        except Exception as e:
            skipped += 1
            errors.append('Path {}: {}'.format(p.Id, e))
            results.append([output.linkify(p.Id), 'Path', '-', str(e)])

    t.Commit()

# ----------------------------------------------------------------------
# Отчёт
# ----------------------------------------------------------------------
output.print_md('## Partition для армирования')
output.print_md('**Обработано:** Area = {}, Path = {}'.format(len(areas), len(paths)))
output.print_md('**Обновлено:** {}   **Пропущено:** {}'.format(updated, skipped))

if results:
    output.print_table(
        table_data=results,
        columns=['ID', 'Тип', 'Partition', 'Статус']
    )

if errors:
    forms.alert(
        'Готово с замечаниями.\nОбновлено: {}\nПропущено: {}\n\n'
        'Первые ошибки:\n{}'.format(updated, skipped, '\n'.join(errors[:5])),
        title='Partition: частичный успех'
    )
else:
    forms.alert(
        'Готово.\nОбновлено: {}\nПропущено: {}'.format(updated, skipped),
        title='Partition'
    )
