# -*- coding: utf-8 -*-
__title__  = 'Exploded 3D\nSetup'
__author__ = 'Dima'
__doc__    = '''Version = 1.0
Date      = 06.05.2026
Description:
    Настраивает активный 3D-вид для презентации exploded-модели КЖ:
    - создаёт фильтры _EXPLODE_Foundation / _EXPLODE_Walls_Upper / _EXPLODE_Slab_Upper
    - применяет к виду цветовые переопределения (solid fill, transparency, projection lines)
    - выставляет DetailLevel = Fine, DisplayStyle = Shaded with Edges
    - включает тени, ambient shadows, silhouettes (где доступно через API)

How-To:
    1. Откройте 3D-вид
    2. Запустите скрипт
    3. Выберите уровни, которые относятся к "низу" (фундамент / нижняя плита)
    4. Остальные уровни считаются "верхом"
    5. Скрипт создаст/обновит фильтры и применит их к активному виду
'''

from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, ElementId, Category,
    Transaction, View3D, ViewDetailLevel, DisplayStyle,
    OverrideGraphicSettings, Color, FillPatternElement, FillPatternTarget,
    ParameterFilterElement, ElementLevelFilter, LogicalOrFilter,
    ElementFilter, Level, BuiltInParameter
)
from Autodesk.Revit.UI import TaskDialog
from System.Collections.Generic import List
from pyrevit import forms, script

doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
app   = __revit__.Application

# ---------------- Константы ----------------
FILTER_FOUNDATION   = '_EXPLODE_Foundation'
FILTER_WALLS_UPPER  = '_EXPLODE_Walls_Upper'
FILTER_SLAB_UPPER   = '_EXPLODE_Slab_Upper'

COLOR_FOUNDATION    = (170, 170, 170)   # тёплый серый
COLOR_WALLS_UPPER   = (91, 155, 213)    # синий
COLOR_SLAB_UPPER    = (230, 210, 180)   # светло-бежевый
COLOR_LINES         = (80, 80, 80)      # тёмно-серый

CATS_FOUNDATION = [BuiltInCategory.OST_StructuralFoundation,
                   BuiltInCategory.OST_Floors]
CATS_WALLS      = [BuiltInCategory.OST_Walls,
                   BuiltInCategory.OST_StructuralColumns]
CATS_SLAB       = [BuiltInCategory.OST_Floors]


# ---------------- Хелперы ----------------
def get_solid_fill_pattern_id():
    for fpe in FilteredElementCollector(doc).OfClass(FillPatternElement):
        try:
            fp = fpe.GetFillPattern()
            if fp.IsSolidFill and fpe.GetFillPattern().Target == FillPatternTarget.Drafting:
                return fpe.Id
        except Exception:
            pass
    # fallback — любой solid
    for fpe in FilteredElementCollector(doc).OfClass(FillPatternElement):
        try:
            if fpe.GetFillPattern().IsSolidFill:
                return fpe.Id
        except Exception:
            pass
    return ElementId.InvalidElementId


def cats_to_ids(bics):
    ids = List[ElementId]()
    for bic in bics:
        cat = Category.GetCategory(doc, bic)
        if cat is not None:
            ids.Add(cat.Id)
    return ids


def make_level_filter(level_ids):
    """LogicalOrFilter из ElementLevelFilter по списку уровней. None если пусто."""
    if not level_ids:
        return None
    filters = List[ElementFilter]()
    for lid in level_ids:
        filters.Add(ElementLevelFilter(lid))
    if filters.Count == 1:
        return filters[0]
    return LogicalOrFilter(filters)


def find_filter_by_name(name):
    for f in FilteredElementCollector(doc).OfClass(ParameterFilterElement):
        if f.Name == name:
            return f
    return None


def create_or_update_filter(name, category_ids, element_filter):
    """Создаёт ParameterFilterElement или обновляет существующий."""
    existing = find_filter_by_name(name)
    if existing is not None:
        try:
            existing.SetCategories(category_ids)
            if element_filter is not None:
                existing.SetElementFilter(element_filter)
        except Exception:
            pass
        return existing, False  # не создан, а обновлён

    if element_filter is not None:
        new_f = ParameterFilterElement.Create(doc, name, category_ids, element_filter)
    else:
        new_f = ParameterFilterElement.Create(doc, name, category_ids)
    return new_f, True


def make_ogs(rgb, solid_id):
    ogs = OverrideGraphicSettings()
    color = Color(rgb[0], rgb[1], rgb[2])
    line_color = Color(COLOR_LINES[0], COLOR_LINES[1], COLOR_LINES[2])
    try:
        ogs.SetSurfaceForegroundPatternColor(color)
        ogs.SetSurfaceForegroundPatternId(solid_id)
        ogs.SetSurfaceForegroundPatternVisible(True)
    except Exception:
        pass
    try:
        ogs.SetSurfaceTransparency(10)
    except Exception:
        pass
    try:
        ogs.SetProjectionLineWeight(1)
        ogs.SetProjectionLineColor(line_color)
    except Exception:
        pass
    return ogs


def apply_filter_to_view(view, pfe, ogs):
    fid = pfe.Id
    try:
        if fid not in view.GetFilters():
            view.AddFilter(fid)
        view.SetFilterOverrides(fid, ogs)
        view.SetFilterVisibility(fid, True)
        return True
    except Exception:
        return False


def set_view_graphics(view):
    """Настройка графики 3D-вида. Каждый шаг защищён try/except."""
    results = []
    try:
        view.DetailLevel = ViewDetailLevel.Fine
        results.append('DetailLevel = Fine')
    except Exception as e:
        results.append('DetailLevel: ' + str(e))

    try:
        view.DisplayStyle = DisplayStyle.ShadingWithEdges
        results.append('DisplayStyle = ShadingWithEdges')
    except Exception as e:
        results.append('DisplayStyle: ' + str(e))

    # Тени
    try:
        p = view.get_Parameter(BuiltInParameter.VIEW_GRAPH_STYLE_SHADOWS_CAST)
        if p and not p.IsReadOnly:
            p.Set(1)
            results.append('Cast Shadows = ON')
    except Exception:
        pass

    try:
        p = view.get_Parameter(BuiltInParameter.VIEW_GRAPH_STYLE_SHADOWS_AMBIENT)
        if p and not p.IsReadOnly:
            p.Set(1)
            results.append('Ambient Shadows = ON')
    except Exception:
        pass

    # Silhouettes — задаём не-нулевой LinePattern/Weight через параметр, если есть
    try:
        p = view.get_Parameter(BuiltInParameter.MODEL_GRAPHICS_STYLE_SILHOUETTE)
        if p and not p.IsReadOnly:
            # значение — ElementId веса/стиля линий; ставим вес 5 как ID
            results.append('Silhouettes parameter found (set manually if needed)')
    except Exception:
        pass

    # Sketchy lines OFF
    try:
        p = view.get_Parameter(BuiltInParameter.MODEL_GRAPHICS_STYLE_SKETCH_ENABLE)
        if p and not p.IsReadOnly:
            p.Set(0)
            results.append('Sketchy Lines = OFF')
    except Exception:
        pass

    return results


# ---------------- Основная логика ----------------
view = doc.ActiveView
if not isinstance(view, View3D):
    forms.alert('Активный вид должен быть 3D.', title='Exploded 3D Setup', exitscript=True)

if view.IsTemplate:
    forms.alert('Активный вид — шаблон. Откройте обычный 3D-вид.',
                title='Exploded 3D Setup', exitscript=True)

# Сбор уровней
all_levels = list(FilteredElementCollector(doc).OfClass(Level).ToElements())
all_levels.sort(key=lambda l: l.Elevation)

if not all_levels:
    forms.alert('В проекте не найдено уровней.', title='Exploded 3D Setup', exitscript=True)

level_options = {}
for lvl in all_levels:
    label = '{}  (Z = {:.2f} m)'.format(lvl.Name, lvl.Elevation * 0.3048)
    level_options[label] = lvl

selected = forms.SelectFromList.show(
    sorted(level_options.keys()),
    title='Выберите НИЖНИЕ уровни (фундамент / нижняя плита)',
    multiselect=True,
    button_name='OK'
)

lower_level_ids = []
if selected:
    for lbl in selected:
        lower_level_ids.append(level_options[lbl].Id)

upper_level_ids = [l.Id for l in all_levels if l.Id not in lower_level_ids]

use_level_split = bool(lower_level_ids) and bool(upper_level_ids)

# Solid fill
solid_id = get_solid_fill_pattern_id()

# ---------------- Транзакция ----------------
created = []
updated = []
applied = []

with Transaction(doc, 'Exploded 3D Setup') as t:
    t.Start()

    # 1) Foundation
    cats_f = cats_to_ids(CATS_FOUNDATION)
    ef_f = make_level_filter(lower_level_ids) if use_level_split else None
    pfe_f, was_created = create_or_update_filter(FILTER_FOUNDATION, cats_f, ef_f)
    (created if was_created else updated).append(FILTER_FOUNDATION)

    # 2) Walls upper (без разделения по уровням, т.к. категории сами по себе)
    cats_w = cats_to_ids(CATS_WALLS)
    ef_w = make_level_filter(upper_level_ids) if use_level_split else None
    pfe_w, was_created = create_or_update_filter(FILTER_WALLS_UPPER, cats_w, ef_w)
    (created if was_created else updated).append(FILTER_WALLS_UPPER)

    # 3) Slab upper — только Floors верхних уровней
    cats_s = cats_to_ids(CATS_SLAB)
    ef_s = make_level_filter(upper_level_ids) if use_level_split else None
    pfe_s, was_created = create_or_update_filter(FILTER_SLAB_UPPER, cats_s, ef_s)
    (created if was_created else updated).append(FILTER_SLAB_UPPER)

    # Применяем к виду
    ogs_f = make_ogs(COLOR_FOUNDATION,  solid_id)
    ogs_w = make_ogs(COLOR_WALLS_UPPER, solid_id)
    ogs_s = make_ogs(COLOR_SLAB_UPPER,  solid_id)

    if apply_filter_to_view(view, pfe_f, ogs_f):
        applied.append(FILTER_FOUNDATION)
    if apply_filter_to_view(view, pfe_w, ogs_w):
        applied.append(FILTER_WALLS_UPPER)
    if apply_filter_to_view(view, pfe_s, ogs_s):
        applied.append(FILTER_SLAB_UPPER)

    # Графика вида
    graphics_log = set_view_graphics(view)

    t.Commit()

# ---------------- Отчёт ----------------
msg = []
msg.append('Активный 3D-вид: {}'.format(view.Name))
msg.append('')
msg.append('Разделение по уровням: {}'.format('ДА' if use_level_split else 'НЕТ (только по категориям)'))
if use_level_split:
    msg.append('  Низ:  {} уровн.'.format(len(lower_level_ids)))
    msg.append('  Верх: {} уровн.'.format(len(upper_level_ids)))
msg.append('')
if created:
    msg.append('Созданы фильтры:')
    for n in created:
        msg.append('  + ' + n)
if updated:
    msg.append('Обновлены фильтры:')
    for n in updated:
        msg.append('  ~ ' + n)
msg.append('')
msg.append('Применены к виду:')
for n in applied:
    msg.append('  > ' + n)
msg.append('')
msg.append('Графика вида:')
for line in graphics_log:
    msg.append('  - ' + line)

TaskDialog.Show('Exploded 3D Setup', '\n'.join(msg))
