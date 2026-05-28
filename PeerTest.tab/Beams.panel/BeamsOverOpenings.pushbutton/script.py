# -*- coding: utf-8 -*-
__title__  = 'Балки над\nпроёмами'
__author__ = 'Dima'
__doc__    = '''Version = 2.0
Date      = 16.04.2026
Description:
    Автоматическое размещение конструктивных балок
    над проёмами (окна, двери) по linked arch-файлу.

    Логика Z (по скетчу):
      beam_bot_z = верх окна НИЖЕ выбранного уровня
      beam_top_z = низ окна ВЫШЕ выбранного уровня
                   (если нет — верх арх. стены)
      hн = часть балки ниже перекрытия
      hб = часть балки выше перекрытия

How-To:
    1. Запустите скрипт
    2. Выберите уровень перекрытия
    3. Выберите linked arch-файл (если их несколько)
    4. Выберите базовое семейство балок
    5. Скрипт разместит балки на выбранном уровне
'''

import math

from Autodesk.Revit.DB import (
    FilteredElementCollector, Level, RevitLinkInstance,
    BuiltInCategory, FamilySymbol, Wall, Line, XYZ,
    Transaction, ElementId, BuiltInParameter,
    LocationCurve, LocationPoint
)
from Autodesk.Revit.DB.Structure import StructuralType, StructuralWallUsage
from Autodesk.Revit.UI import TaskDialog, TaskDialogCommonButtons
from Autodesk.Revit.UI import TaskDialogCommandLinkId, TaskDialogResult

# Предопределённые переменные pyRevit — не переопределять
doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
app   = __revit__.Application

# ============================================================
# КОНСТАНТЫ
# ============================================================
TOL_WALL_MM   = 50.0   # допуск поиска конструктивных стен (мм)
TOL_BEAM_MM   = 10.0   # допуск проверки дублирования балок (мм)
TOL_COL_MM    = 150.0  # допуск группировки окон в одну «колонку» (мм)
MM_TO_FT      = 1.0 / 304.8
FT_TO_MM      = 304.8


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ — ДИАЛОГИ
# ============================================================

def dialog_select_from_list(title, instruction, items, name_fn=None):
    """
    Постраничный выбор элемента через TaskDialog (3 элемента на страницу).
    Возвращает выбранный элемент или None при отмене.
    """
    if name_fn is None:
        name_fn = str

    LINK_IDS = [
        TaskDialogCommandLinkId.CommandLink1,
        TaskDialogCommandLinkId.CommandLink2,
        TaskDialogCommandLinkId.CommandLink3,
        TaskDialogCommandLinkId.CommandLink4,
    ]
    LINK_RESULTS = [
        TaskDialogResult.CommandLink1,
        TaskDialogResult.CommandLink2,
        TaskDialogResult.CommandLink3,
        TaskDialogResult.CommandLink4,
    ]

    PER_PAGE    = 3
    page        = 0
    total_pages = max(1, (len(items) + PER_PAGE - 1) // PER_PAGE)

    while True:
        start      = page * PER_PAGE
        page_items = items[start: start + PER_PAGE]
        has_next   = (page + 1) < total_pages

        td = TaskDialog(title)
        td.MainInstruction = instruction
        if total_pages > 1:
            td.MainContent = 'Страница {} из {}'.format(page + 1, total_pages)
        td.CommonButtons = TaskDialogCommonButtons.Cancel

        for i, item in enumerate(page_items):
            td.AddCommandLink(LINK_IDS[i], name_fn(item))

        if has_next:
            td.AddCommandLink(LINK_IDS[len(page_items)], 'Следующая страница...')

        result = td.Show()

        if result == TaskDialogResult.Cancel:
            return None

        idx = None
        for i, lr in enumerate(LINK_RESULTS):
            if result == lr:
                idx = i
                break

        if idx is None:
            return None

        if has_next and idx == len(page_items):
            page += 1
            continue

        if idx < len(page_items):
            return page_items[idx]

        return None


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ — ГЕОМЕТРИЯ ПРОЁМОВ
# ============================================================

def xy_dist(pt1, pt2):
    """Расстояние по XY без учёта Z."""
    return math.sqrt((pt1.X - pt2.X) ** 2 + (pt1.Y - pt2.Y) ** 2)


def get_opening_geometry(inst):
    """
    Получить геометрию проёма из arch-linked-документа.
    Возвращает словарь или None.

    Ключи:
      inst, host_wall, wall_dir,
      center_pt    — точка вставки (XYZ)
      sill_z       — низ проёма (футы)
      top_z        — верх проёма (футы)
      width        — ширина проёма (футы)
      left_edge_xy — XY левого края при Z=0
      right_edge_xy— XY правого края при Z=0
      proj_along   — проекция center_pt на wall_dir (для группировки)
    """
    try:
        host_wall = inst.Host
        if host_wall is None:
            return None

        wall_loc = host_wall.Location
        if not isinstance(wall_loc, LocationCurve):
            return None

        wall_dir = wall_loc.Curve.Direction.Normalize()

        # Bounding box — самый надёжный источник Z
        bb = inst.get_BoundingBox(None)
        if bb is None:
            return None
        sill_z = bb.Min.Z
        top_z  = bb.Max.Z

        # Точка вставки
        inst_loc = inst.Location
        if not isinstance(inst_loc, LocationPoint):
            return None
        center_pt = inst_loc.Point

        # Ширина проёма
        width = None
        for bip in [BuiltInParameter.FAMILY_WIDTH_PARAM,
                    BuiltInParameter.DOOR_WIDTH]:
            for src in [inst, inst.Symbol]:
                try:
                    p = src.get_Parameter(bip)
                    if p and p.AsDouble() > 0.001:
                        width = p.AsDouble()
                        break
                except Exception:
                    pass
            if width:
                break

        if not width:
            for src in [inst, inst.Symbol]:
                p = src.LookupParameter('Width')
                if p and p.AsDouble() > 0.001:
                    width = p.AsDouble()
                    break

        if not width:
            # Проекция bounding box на направление стены
            diag  = XYZ(bb.Max.X - bb.Min.X, bb.Max.Y - bb.Min.Y, 0.0)
            width = abs(diag.DotProduct(wall_dir))

        if width < 0.001:
            return None

        half_w = width / 2.0

        # Края проёма в XY (Z=0 — только для поиска конструктивных стен)
        left_edge_xy  = XYZ(center_pt.X - wall_dir.X * half_w,
                            center_pt.Y - wall_dir.Y * half_w,
                            0.0)
        right_edge_xy = XYZ(center_pt.X + wall_dir.X * half_w,
                            center_pt.Y + wall_dir.Y * half_w,
                            0.0)

        # Проекция по стене для группировки колонок
        proj_along = center_pt.X * wall_dir.X + center_pt.Y * wall_dir.Y

        return {
            'inst':          inst,
            'host_wall':     host_wall,
            'wall_dir':      wall_dir,
            'center_pt':     center_pt,
            'sill_z':        sill_z,
            'top_z':         top_z,
            'width':         width,
            'left_edge_xy':  left_edge_xy,
            'right_edge_xy': right_edge_xy,
            'proj_along':    proj_along,
        }
    except Exception:
        return None


def get_wall_top_z(wall, source_doc):
    """Абсолютная Z верха арх. стены (в футах)."""
    base_param  = wall.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT)
    base_lvl    = source_doc.GetElement(base_param.AsElementId()) if base_param else None
    base_elev   = base_lvl.Elevation if base_lvl else 0.0

    base_off_p  = wall.get_Parameter(BuiltInParameter.WALL_BASE_OFFSET)
    base_offset = base_off_p.AsDouble() if base_off_p else 0.0

    top_type_p  = wall.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE)
    if top_type_p:
        top_lvl_id = top_type_p.AsElementId()
        if top_lvl_id != ElementId.InvalidElementId:
            top_lvl    = source_doc.GetElement(top_lvl_id)
            top_off_p  = wall.get_Parameter(BuiltInParameter.WALL_TOP_OFFSET)
            top_offset = top_off_p.AsDouble() if top_off_p else 0.0
            if top_lvl:
                return top_lvl.Elevation + top_offset

    h_param = wall.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM)
    if h_param:
        return base_elev + base_offset + h_param.AsDouble()

    return base_elev + base_offset + (3.0 / 0.3048)  # запасной вариант 3 м


# ============================================================
# ГРУППИРОВКА ПРОЁМОВ В «КОЛОНКИ»
# ============================================================

def group_into_columns(wall_geoms, tol_ft):
    """
    Сгруппировать проёмы одной арх. стены по горизонтальной позиции
    (проекция center_pt на направление стены).
    Возвращает список списков геометрий.
    """
    columns = []   # [{'proj': float, 'geoms': [g, ...]}, ...]

    for g in wall_geoms:
        proj    = g['proj_along']
        placed  = False
        for col in columns:
            if abs(proj - col['proj']) <= tol_ft:
                col['geoms'].append(g)
                placed = True
                break
        if not placed:
            columns.append({'proj': proj, 'geoms': [g]})

    return [col['geoms'] for col in columns]


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ — КОНСТРУКТИВНЫЕ СТЕНЫ
# ============================================================

def find_adjacent_struct_walls(left_xy, right_xy, struct_walls, tol_ft):
    """
    Найти конструктивные стены слева и справа от проёма.
    left_xy, right_xy — XYZ с Z=0 (поиск только по XY).
    Возвращает (left_wall, right_wall, left_pt, right_pt) или (None, None, None, None).
    """
    left_wall  = None
    right_wall = None
    left_pt    = None
    right_pt   = None

    for wall in struct_walls:
        loc = wall.Location
        if not isinstance(loc, LocationCurve):
            continue
        pt0 = loc.Curve.GetEndPoint(0)
        pt1 = loc.Curve.GetEndPoint(1)

        for pt in [pt0, pt1]:
            # Сравниваем только XY
            pt_xy = XYZ(pt.X, pt.Y, 0.0)
            if left_wall is None and xy_dist(pt_xy, left_xy) <= tol_ft:
                left_wall = wall
                left_pt   = pt   # оригинальная точка с Z
                break
            if right_wall is None and xy_dist(pt_xy, right_xy) <= tol_ft:
                right_wall = wall
                right_pt   = pt
                break

        if left_wall and right_wall:
            break

    return left_wall, right_wall, left_pt, right_pt


def get_wall_width_mm(wall):
    """Ширина стены в мм."""
    return int(round(wall.Width * FT_TO_MM))


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ — ТИПОРАЗМЕРЫ БАЛОК
# ============================================================

def collect_beam_families(document):
    """
    Собрать все FamilySymbol категории StructuralFraming.
    Возвращает dict: family_name -> [FamilySymbol, ...]
    """
    symbols = (
        FilteredElementCollector(document)
        .OfCategory(BuiltInCategory.OST_StructuralFraming)
        .OfClass(FamilySymbol)
        .ToElements()
    )
    families = {}
    for sym in symbols:
        fname = sym.Family.Name
        if fname not in families:
            families[fname] = []
        families[fname].append(sym)
    return families


def get_or_create_beam_type(document, families, base_family_name, b_mm, h_mm):
    """
    Найти или создать типоразмер 'b_mm/h_mm' в семействе base_family_name.
    Возвращает FamilySymbol или None.
    """
    target_name = '{}/{}'.format(int(b_mm), int(h_mm))
    symbols     = families.get(base_family_name, [])

    for sym in symbols:
        if sym.Name == target_name:
            return sym

    if not symbols:
        return None
    base_sym = symbols[0]

    try:
        new_sym = base_sym.Duplicate(target_name)
        families[base_family_name].append(new_sym)

        p_b = new_sym.LookupParameter('b')
        if p_b and not p_b.IsReadOnly:
            p_b.Set(b_mm * MM_TO_FT)

        p_h = new_sym.LookupParameter('h')
        if p_h and not p_h.IsReadOnly:
            p_h.Set(h_mm * MM_TO_FT)

        if not new_sym.IsActive:
            new_sym.Activate()

        return new_sym
    except Exception:
        return None


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ — ПРОВЕРКА ДУБЛИРОВАНИЯ БАЛОК
# ============================================================

def beam_exists(document, start_xy, end_xy, beam_bot_z, tol_ft):
    """
    Проверить, существует ли уже балка с теми же XY start/end и bot Z.
    """
    existing = (
        FilteredElementCollector(document)
        .OfCategory(BuiltInCategory.OST_StructuralFraming)
        .WhereElementIsNotElementType()
        .ToElements()
    )
    s_xy = XYZ(start_xy.X, start_xy.Y, 0.0)
    e_xy = XYZ(end_xy.X,   end_xy.Y,   0.0)

    for beam in existing:
        loc = beam.Location
        if not isinstance(loc, LocationCurve):
            continue
        s = loc.Curve.GetEndPoint(0)
        e = loc.Curve.GetEndPoint(1)

        s2 = XYZ(s.X, s.Y, 0.0)
        e2 = XYZ(e.X, e.Y, 0.0)

        fwd = xy_dist(s2, s_xy) < tol_ft and xy_dist(e2, e_xy) < tol_ft
        rev = xy_dist(s2, e_xy) < tol_ft and xy_dist(e2, s_xy) < tol_ft

        if (fwd or rev) and abs(s.Z - beam_bot_z) < tol_ft:
            return True

    return False


# ============================================================
# ГЛАВНАЯ ЛОГИКА
# ============================================================

def main():

    tol_wall_ft = TOL_WALL_MM * MM_TO_FT
    tol_beam_ft = TOL_BEAM_MM * MM_TO_FT
    tol_col_ft  = TOL_COL_MM  * MM_TO_FT

    # ----------------------------------------------------------
    # 1. Выбор уровня
    # ----------------------------------------------------------
    levels = sorted(
        FilteredElementCollector(doc).OfClass(Level).ToElements(),
        key=lambda l: l.Elevation
    )
    if not levels:
        TaskDialog.Show('Ошибка', 'В документе не найдено уровней.')
        return

    selected_level = dialog_select_from_list(
        'Выбор уровня',
        'Выберите уровень перекрытия для размещения балок:',
        list(levels),
        name_fn=lambda l: '{} (отм. {:.2f} м)'.format(
            l.Name, l.Elevation * 0.3048)
    )
    if selected_level is None:
        return

    level_elev = selected_level.Elevation  # Z уровня в футах

    # ----------------------------------------------------------
    # 2. Выбор linked arch-файла
    # ----------------------------------------------------------
    link_instances = list(
        FilteredElementCollector(doc).OfClass(RevitLinkInstance).ToElements()
    )
    if not link_instances:
        TaskDialog.Show('Ошибка', 'Linked-файлы не найдены.')
        return

    if len(link_instances) == 1:
        arch_link = link_instances[0]
    else:
        arch_link = dialog_select_from_list(
            'Выбор linked-файла',
            'Выберите архитектурный linked-файл:',
            link_instances,
            name_fn=lambda li: li.Name
        )
        if arch_link is None:
            return

    linked_doc = arch_link.GetLinkDocument()
    if linked_doc is None:
        TaskDialog.Show('Ошибка',
                        'Не удалось открыть linked-документ.\n'
                        'Убедитесь, что файл загружен.')
        return

    # ----------------------------------------------------------
    # 3. Выбор базового семейства балок
    # ----------------------------------------------------------
    beam_families = collect_beam_families(doc)
    if not beam_families:
        TaskDialog.Show('Ошибка', 'Не загружено ни одного семейства StructuralFraming.')
        return

    base_family_name = dialog_select_from_list(
        'Базовое семейство балок',
        'Выберите семейство-основу для создания типоразмеров:',
        sorted(beam_families.keys()),
        name_fn=lambda n: n
    )
    if base_family_name is None:
        return

    # ----------------------------------------------------------
    # 4. Собрать ВСЕ окна и двери из linked-документа
    #    (не фильтруем по уровню — фильтрация по Z ниже)
    # ----------------------------------------------------------
    all_openings = []
    for cat in [BuiltInCategory.OST_Windows, BuiltInCategory.OST_Doors]:
        all_openings.extend(
            FilteredElementCollector(linked_doc)
            .OfCategory(cat)
            .WhereElementIsNotElementType()
            .ToElements()
        )

    opening_geoms = []
    for inst in all_openings:
        g = get_opening_geometry(inst)
        if g:
            opening_geoms.append(g)

    if not opening_geoms:
        TaskDialog.Show('Информация', 'В linked-файле не найдено окон и дверей.')
        return

    # ----------------------------------------------------------
    # 5. Группировка по арх. стене → по колонкам
    #
    #    Для каждой «колонки» (одно вертикальное гнездо в стене):
    #      lower = окно целиком ниже уровня (top_z <= level_elev)
    #      upper = окно целиком выше уровня (sill_z >= level_elev)
    #
    #      beam_bot_z = top_z нижнего окна (верх проёма снизу)
    #      beam_top_z = sill_z верхнего окна (низ проёма сверху)
    #                   ИЛИ верх арх. стены если нет окна сверху
    # ----------------------------------------------------------
    wall_map = {}
    for g in opening_geoms:
        wid = g['host_wall'].Id.IntegerValue
        if wid not in wall_map:
            wall_map[wid] = []
        wall_map[wid].append(g)

    # Конструктивные стены текущего документа
    struct_walls = []
    for w in (FilteredElementCollector(doc)
              .OfClass(Wall)
              .WhereElementIsNotElementType()
              .ToElements()):
        try:
            if w.StructuralUsage != StructuralWallUsage.NonBearing:
                struct_walls.append(w)
        except Exception:
            continue

    # ----------------------------------------------------------
    # 6. Формирование списка балок для создания
    # ----------------------------------------------------------
    # Каждый элемент: {'label', 'bot_z', 'top_z', 'left_xy', 'right_xy',
    #                  'left_wall', 'right_wall', 'l_pt', 'r_pt', 'b_mm', 'h_mm'}
    beam_tasks = []
    skipped    = []   # [(label, reason), ...]

    for wid, wall_geoms in wall_map.items():
        # Получаем верх арх. стены (нужен если нет окна сверху)
        arch_wall     = wall_geoms[0]['host_wall']
        arch_wall_top = get_wall_top_z(arch_wall, linked_doc)

        # Разбиваем на колонки по горизонтальной позиции
        columns = group_into_columns(wall_geoms, tol_col_ft)

        for column in columns:
            # Нижние окна: целиком ниже уровня перекрытия
            lower_list = [g for g in column if g['top_z'] <= level_elev + tol_beam_ft]
            # Верхние окна: целиком выше уровня перекрытия
            upper_list = [g for g in column if g['sill_z'] >= level_elev - tol_beam_ft]

            if not lower_list:
                # Нет окна снизу — не можем определить низ балки
                for g in column:
                    name = '{} [{}]'.format(
                        g['inst'].Symbol.FamilyName, g['inst'].Id.IntegerValue)
                    skipped.append((name, 'нет окна ниже уровня в этой колонке'))
                continue

            # Берём самое высокое нижнее окно
            best_lower = max(lower_list, key=lambda g: g['top_z'])
            beam_bot_z = best_lower['top_z']

            # Верх балки — самое низкое верхнее окно или верх стены
            if upper_list:
                best_upper = min(upper_list, key=lambda g: g['sill_z'])
                beam_top_z = best_upper['sill_z']
            else:
                beam_top_z = arch_wall_top

            beam_h_mm = (beam_top_z - beam_bot_z) * FT_TO_MM

            label = '{} [{}] на ур. {}'.format(
                best_lower['inst'].Symbol.FamilyName,
                best_lower['inst'].Id.IntegerValue,
                selected_level.Name
            )

            if beam_h_mm <= 0:
                skipped.append((label,
                                'высота балки {:.0f} мм <= 0'.format(beam_h_mm)))
                continue

            # Края проёма в XY (Z=0)
            left_xy  = best_lower['left_edge_xy']
            right_xy = best_lower['right_edge_xy']

            # Конструктивные стены слева и справа
            lw, rw, l_pt, r_pt = find_adjacent_struct_walls(
                left_xy, right_xy, struct_walls, tol_wall_ft)

            if lw is None or rw is None:
                missing = []
                if lw is None: missing.append('левая')
                if rw is None: missing.append('правая')
                skipped.append((label,
                                'не найдена {} стена (tol {} мм)'.format(
                                    ' и '.join(missing), int(TOL_WALL_MM))))
                continue

            b_mm = get_wall_width_mm(lw)
            if b_mm <= 0:
                skipped.append((label, 'ширина конструктивной стены = 0'))
                continue

            # Проверка дублирования
            start_pt = XYZ(l_pt.X, l_pt.Y, beam_bot_z)
            end_pt   = XYZ(r_pt.X, r_pt.Y, beam_bot_z)

            if beam_exists(doc, start_pt, end_pt, beam_bot_z, tol_beam_ft):
                skipped.append((label, 'балка уже существует'))
                continue

            if start_pt.DistanceTo(end_pt) < 0.001:
                skipped.append((label, 'длина балки < 1 мм'))
                continue

            beam_tasks.append({
                'label':     label,
                'bot_z':     beam_bot_z,
                'top_z':     beam_top_z,
                'h_mm':      int(round(beam_h_mm)),
                'b_mm':      b_mm,
                'start_pt':  start_pt,
                'end_pt':    end_pt,
                'level':     selected_level,
            })

    if not beam_tasks:
        msg = 'Нет балок для создания.'
        if skipped:
            lines = [' {} — {}'.format(n, r) for n, r in skipped[:10]]
            msg  += '\n\nПропущено:\n' + '\n'.join(lines)
        TaskDialog.Show('Балки над проёмами', msg)
        return

    # ----------------------------------------------------------
    # 7. Создание балок — одна транзакция, полный откат при ошибке
    # ----------------------------------------------------------
    created_count = 0

    try:
        with Transaction(doc, 'Балки над проёмами') as t:
            t.Start()

            for task in beam_tasks:
                # Найти / создать типоразмер
                beam_sym = get_or_create_beam_type(
                    doc, beam_families, base_family_name,
                    task['b_mm'], task['h_mm']
                )
                if beam_sym is None:
                    skipped.append((task['label'],
                                    'не удалось создать тип {}/{}'.format(
                                        task['b_mm'], task['h_mm'])))
                    continue

                if not beam_sym.IsActive:
                    beam_sym.Activate()
                    doc.Regenerate()

                try:
                    beam_line = Line.CreateBound(task['start_pt'], task['end_pt'])
                    new_beam  = doc.Create.NewFamilyInstance(
                        beam_line,
                        beam_sym,
                        task['level'],
                        StructuralType.Beam
                    )

                    # Задать z-offsets балки
                    # Ось вставки балки = bot_z → z_offset_start и z_offset_end = 0
                    # (bot_z уже зашит в start_pt / end_pt)
                    # Верхний z задаётся через высоту типоразмера (параметр h)
                    created_count += 1

                except Exception as ex:
                    skipped.append((task['label'],
                                    'ошибка API: {}'.format(str(ex))))

            t.Commit()

    except Exception as ex:
        TaskDialog.Show(
            'Ошибка транзакции',
            'Транзакция откатана. Балки не созданы.\n\n{}'.format(str(ex))
        )
        return

    # ----------------------------------------------------------
    # 8. Итоговый отчёт
    # ----------------------------------------------------------
    msg = 'Создано балок: {}\nПропущено: {}'.format(created_count, len(skipped))

    if skipped:
        lines = [' {} — {}'.format(n, r) for n, r in skipped[:20]]
        if len(skipped) > 20:
            lines.append(' ... и ещё {}'.format(len(skipped) - 20))
        msg += '\n\nПричины пропуска:\n' + '\n'.join(lines)

    TaskDialog.Show('Балки над проёмами — результат', msg)


# ============================================================
# ТОЧКА ВХОДА
# ============================================================
main()
