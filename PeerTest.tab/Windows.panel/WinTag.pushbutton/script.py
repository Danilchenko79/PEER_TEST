# -*- coding: utf-8 -*-
"""WinTag - parameters for windows + missing tags on plan views.

WHAT IT DOES
============
For EVERY window in the project, compute the geometry above the window
(closest slab above; closest upper window, if any) and write 4 instance
parameters:

    MD_WallThickness_cm    - host wall thickness (cm, integer)
    MD_TopGap_cm           - clean gap from window top to slab bottom (cm)
    MD_BottomFromLevel_cm  - clean gap from slab top to upper-window sill (cm)
                             (0 if there is no slab or no upper window)
    MD_TagString           - human-readable tag for the wall section

If the active view is a plan view, the user is asked which tag family type
to use (or "skip"). Then, for every window in the active view that:
    - has no tag in this view, AND
    - is actually under a slab (XY footprint covered)
the script adds an IndependentTag with the chosen type at a default position.

GEOMETRY (everything via absolute Z, cm at the end)
===================================================
    win_top_z   = base.Elevation + sill + height
    slab_bot_z  = closest slab's BBox.Min.Z (XY covers window center + tol)
    slab_top_z  = closest slab's BBox.Max.Z
    above_sill_z = upper_window.level.Elevation + upper_window.sill
    top_gap_cm  = slab_bot_z - win_top_z         (0 if slab missing)
                  or above_sill_z - win_top_z    (no slab, has upper window)
                  or 0
    slab_cm     = slab_top_z - slab_bot_z        (BBox vertical extent)
    above_sill  = above_sill_z - slab_top_z      (only when both slab & upper)

TAG STRING RULES
================
Two beam segments around the slab. Slab thickness is ABSORBED into seg1
(the lower beam) by default. Only "Балка сверху" omits the slab entirely
in the visible tag.

    case                              seg1              seg2
    ---------------------------------------------------------------
    Обычная     gap>0, upper sill>0   top_gap+slab_cm   above_sill
    Балка снизу gap>0, upper sill=0   top_gap+slab_cm   0
    Балка сверху gap=0, upper sill>0  0                 above_sill
    Нет балки   gap=0, upper sill=0   0                 0      -> ""
    No upper window                   top_gap+slab_cm   0
    No slab                           top_gap           0

Formatting (any /0 segment is dropped):
    seg1>0, seg2>0 : "wall/seg1+aboveWall/seg2"
    seg2>0 only    : "+aboveWall/seg2"
    seg1>0 only    : "wall/seg1"
    both 0         : ""

REPORT
======
A pyRevit output is printed with one row per window: clickable ID, level,
geometry, slab info, beam type, tag. Rows are sorted by level elevation.
"""

__title__  = 'WinTag'
__author__ = 'Dima'

import sys
from collections import Counter
from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, BuiltInParameter,
    StorageType, ElementId, Element, UnitUtils, UnitTypeId,
    LocationPoint, LocationCurve, Wall, FamilySymbol,
    IndependentTag, TagOrientation, Reference, Transaction, ViewPlan,
)
from pyrevit import forms, script

doc  = __revit__.ActiveUIDocument.Document
view = doc.ActiveView


# =====================================================================
# 0. CONSTANTS
# =====================================================================
P_WALL_THK = 'MD_WallThickness_cm'
P_TOP_GAP  = 'MD_TopGap_cm'
P_BOTTOM   = 'MD_BottomFromLevel_cm'
P_TAGSTR   = 'MD_TagString'

XY_TOL_CM       = 5.0      # baseline XY tolerance, cm
XY_TOL_FT       = XY_TOL_CM / 30.48
DEFAULT_WALL_CM = 20.0     # fallback wall thickness for non-Wall hosts
TAG_OFFSET_CM   = 20.0     # default vertical offset above window center


# =====================================================================
# 1. UNITS
# =====================================================================
def cm_to_ft(cm):
    return UnitUtils.ConvertToInternalUnits(float(cm), UnitTypeId.Centimeters)

def ft_to_cm(ft):
    return UnitUtils.ConvertFromInternalUnits(float(ft), UnitTypeId.Centimeters)

def cm_int(ft):
    return int(round(ft_to_cm(ft), 0))


# =====================================================================
# 2. PARAMETER UTILITIES
# =====================================================================
def _double_bip(elem, bip):
    try:
        p = elem.get_Parameter(bip)
        if p and p.StorageType == StorageType.Double:
            return p.AsDouble()
    except Exception:
        pass
    return None

def _norm(s):
    return ' '.join(str(s or '').strip().split()).lower()

def find_param(elem, name):
    """Case-insensitive parameter lookup."""
    if not elem:
        return None
    p = elem.LookupParameter(name)
    if p:
        return p
    target = _norm(name)
    for pp in elem.Parameters:
        try:
            if _norm(pp.Definition.Name) == target:
                return pp
        except Exception:
            pass
    return None

def set_double(elem, name, value_cm):
    p = find_param(elem, name)
    if p and not p.IsReadOnly and p.StorageType == StorageType.Double:
        p.Set(cm_to_ft(value_cm))
        return True
    return False

def set_string(elem, name, txt):
    p = find_param(elem, name)
    if p and not p.IsReadOnly and p.StorageType == StorageType.String:
        p.Set('' if txt is None else str(txt))
        return True
    return False

def read_length_cm(elem, name):
    """Read a Double length param and return integer cm, or None."""
    p = find_param(elem, name)
    if p and p.StorageType == StorageType.Double:
        try:
            return cm_int(p.AsDouble())
        except Exception:
            return None
    return None

def read_string(elem, name):
    """Read a String param, return '' if not set, or None if no such param."""
    p = find_param(elem, name)
    if p and p.StorageType == StorageType.String:
        return p.AsString() or ''
    return None


# =====================================================================
# 3. WINDOW HELPERS
# =====================================================================
def window_center(win):
    loc = win.Location
    if isinstance(loc, LocationPoint):
        return loc.Point
    if isinstance(loc, LocationCurve):
        return loc.Curve.Evaluate(0.5, True)
    return None

def window_sill_ft(win):
    return _double_bip(win, BuiltInParameter.INSTANCE_SILL_HEIGHT_PARAM)

def window_height_ft(win):
    sym = win.Symbol
    if not sym:
        return None
    return _double_bip(sym, BuiltInParameter.FAMILY_HEIGHT_PARAM)

def host_wall_width_ft(win):
    """Wall.Width if host is a Wall, else 0."""
    host = getattr(win, 'Host', None)
    if isinstance(host, Wall):
        return host.WallType.Width
    return 0.0

def wall_thk_cm_eff(win):
    """Effective wall thickness in cm: host width, or DEFAULT_WALL_CM if no Wall."""
    w_ft = host_wall_width_ft(win)
    return cm_int(w_ft) if w_ft > 0 else int(DEFAULT_WALL_CM)


# =====================================================================
# 4. SLAB HELPERS (Floors + Roofs)
# =====================================================================
def slab_z_range(slab):
    bb = slab.get_BoundingBox(None)
    return (bb.Min.Z, bb.Max.Z) if bb else (None, None)

def slab_xy_covers(slab, x, y, tol_ft):
    bb = slab.get_BoundingBox(None)
    if not bb:
        return False
    return (bb.Min.X - tol_ft <= x <= bb.Max.X + tol_ft and
            bb.Min.Y - tol_ft <= y <= bb.Max.Y + tol_ft)


# =====================================================================
# 5. COLLECT ALL ENTITIES
# =====================================================================
all_windows = list(FilteredElementCollector(doc)
                   .OfCategory(BuiltInCategory.OST_Windows)
                   .WhereElementIsNotElementType().ToElements())

wins_in_view = list(FilteredElementCollector(doc, view.Id)
                    .OfCategory(BuiltInCategory.OST_Windows)
                    .WhereElementIsNotElementType().ToElements())

all_slabs = []
for _cat in (BuiltInCategory.OST_Floors, BuiltInCategory.OST_Roofs):
    all_slabs.extend(FilteredElementCollector(doc)
                     .OfCategory(_cat)
                     .WhereElementIsNotElementType().ToElements())


# =====================================================================
# 6. STACKED-WINDOW SEARCH
#    Distance-based, NOT bucket-based -> windows near bucket boundaries
#    are not missed.  Picks the closest level (above or below).
# =====================================================================
def _stacked(win_pt, base_elev, direction):
    if win_pt is None or base_elev is None:
        return None
    tol_sq = XY_TOL_FT * XY_TOL_FT
    best, best_elev = None, None
    for w in all_windows:
        if w.LevelId is None:
            continue
        lvl = doc.GetElement(w.LevelId)
        if lvl is None:
            continue
        if direction > 0 and lvl.Elevation <= base_elev + 1e-6:
            continue
        if direction < 0 and lvl.Elevation >= base_elev - 1e-6:
            continue
        pt = window_center(w)
        if pt is None:
            continue
        dx, dy = pt.X - win_pt.X, pt.Y - win_pt.Y
        if dx * dx + dy * dy > tol_sq:
            continue
        if (best_elev is None
                or (direction > 0 and lvl.Elevation < best_elev)
                or (direction < 0 and lvl.Elevation > best_elev)):
            best_elev = lvl.Elevation
            best = w
    return best

def find_above_window(win_pt, base_elev): return _stacked(win_pt, base_elev,  1)
def find_below_window(win_pt, base_elev): return _stacked(win_pt, base_elev, -1)


# =====================================================================
# 7. SLAB ABOVE A WINDOW
#    * slab bottom Z >= win_top_z (allow exact contact - 1e-3 ft tolerance)
#    * if ceiling_z (upper-window sill) is known, slab top must be <= ceiling
#    * window XY must be inside slab BBox + xy_tol_ft
# =====================================================================
def find_slab_above(win_pt, win_top_z, ceiling_z, xy_tol_ft):
    if win_pt is None:
        return None
    best, best_bot = None, None
    for s in all_slabs:
        bot, top = slab_z_range(s)
        if bot is None:
            continue
        if bot < win_top_z - 1e-3:
            continue
        if ceiling_z is not None and top > ceiling_z + 1e-3:
            continue
        if not slab_xy_covers(s, win_pt.X, win_pt.Y, xy_tol_ft):
            continue
        if best_bot is None or bot < best_bot:
            best_bot = bot
            best = s
    return best


# =====================================================================
# 8. EXISTING TAGS IN ACTIVE VIEW
# =====================================================================
def tagged_window_ids(tag):
    try:
        return [eid.IntegerValue for eid in tag.GetTaggedLocalElementIds()]
    except Exception:
        pass
    try:
        return [tag.TaggedLocalElementId.IntegerValue]
    except Exception:
        return []

tags_by_window = {}     # window_id (int) -> [(tag_id, head_pt)]
for _t in (FilteredElementCollector(doc, view.Id)
            .OfClass(IndependentTag).ToElements()):
    try:
        _head = _t.TagHeadPosition
    except Exception:
        _head = None
    for _wid in tagged_window_ids(_t):
        tags_by_window.setdefault(_wid, []).append((_t.Id, _head))


# =====================================================================
# 9a. USER CHOICE - run mode (Apply vs Dry-run)
# =====================================================================
_mode = forms.alert(
    'Применить - обновит параметры окон и (на плане) добавит недостающие теги.\n'
    'Только проверить - покажет что изменится, без записи в модель. '
    'Полезно перед печатью листа: узнать, актуальны ли теги.',
    options=[u'Применить', u'Только проверить (dry-run)'],
    title='WinTag - режим запуска',
)
if _mode is None:
    sys.exit()
DRY_RUN = _mode.startswith(u'Только')


# =====================================================================
# 9b. USER CHOICE - tag family type (only on plan + Apply mode)
# =====================================================================
IS_PLAN  = isinstance(view, ViewPlan)
TAG_TYPE = None

if IS_PLAN and not DRY_RUN:
    _tag_types = list(FilteredElementCollector(doc)
                      .OfClass(FamilySymbol)
                      .OfCategory(BuiltInCategory.OST_WindowTags)
                      .ToElements())

    _SKIP = u'⊘  Не добавлять теги (только обновить параметры)'
    _labels = [_SKIP]
    _label_to_type = {}
    for _tt in _tag_types:
        try:
            _name = '{} : {}'.format(_tt.Family.Name,
                                      Element.Name.GetValue(_tt))
        except Exception:
            _name = str(_tt.Id)
        _labels.append(_name)
        _label_to_type[_name] = _tt

    _missing = sum(1 for w in wins_in_view
                   if w.Id.IntegerValue not in tags_by_window)

    _choice = forms.SelectFromList.show(
        _labels,
        title='WinTag - добавить недостающие теги ({} окон без тега)'.format(_missing),
        button_name='OK',
        multiselect=False)
    if _choice is None:
        sys.exit()
    TAG_TYPE = None if _choice == _SKIP else _label_to_type.get(_choice)


# =====================================================================
# 10. CORE COMPUTATION FOR ONE WINDOW
# =====================================================================
def compute_for_window(w):
    """Return per-window dict (params + debug info) or None to skip."""
    base = doc.GetElement(w.LevelId) if w.LevelId else None
    if base is None:
        return None
    sill_ft   = window_sill_ft(w)
    height_ft = window_height_ft(w)
    win_pt    = window_center(w)
    if sill_ft is None or height_ft is None or win_pt is None:
        return None

    win_top_z = base.Elevation + sill_ft + height_ft

    # Effective wall thickness + the slab XY tolerance derived from it
    wall_cm     = wall_thk_cm_eff(w)
    wall_thk_ft = host_wall_width_ft(w)
    xy_tol_ft   = max(XY_TOL_FT,
                      wall_thk_ft if wall_thk_ft > 0
                      else cm_to_ft(DEFAULT_WALL_CM))

    # ---- upper / lower windows (debug + math)
    above_win    = find_above_window(win_pt, base.Elevation)
    above_sill_z = None
    above_lvl    = None
    above_wall   = wall_cm
    if above_win is not None:
        s = window_sill_ft(above_win)
        ab_base = (doc.GetElement(above_win.LevelId)
                   if above_win.LevelId else None)
        if s is not None and ab_base is not None:
            above_sill_z = ab_base.Elevation + s
            above_lvl    = ab_base.Name
        above_wall = wall_thk_cm_eff(above_win)

    below_win = find_below_window(win_pt, base.Elevation)
    below_lvl = None
    if below_win is not None:
        bl = doc.GetElement(below_win.LevelId) if below_win.LevelId else None
        if bl is not None:
            below_lvl = bl.Name

    # ---- slab above (constrained by upper sill if known)
    slab = find_slab_above(win_pt, win_top_z, above_sill_z, xy_tol_ft)

    slab_cm  = 0
    slab_bot = None
    slab_top = None
    slab_lvl = None
    if slab is not None:
        bot_ft, top_ft = slab_z_range(slab)
        slab_bot = cm_int(bot_ft)
        slab_top = cm_int(top_ft)
        slab_cm  = cm_int(top_ft - bot_ft)
        try:
            sl = doc.GetElement(slab.LevelId) if slab.LevelId else None
            slab_lvl = sl.Name if sl else None
        except Exception:
            pass

    # ---- top_gap (cm): "clean" gap between window top and slab bottom,
    #      or to upper sill if no slab, or 0 otherwise
    if slab is not None:
        top_gap = max(0, cm_int(slab_z_range(slab)[0] - win_top_z))
    elif above_sill_z is not None:
        top_gap = max(0, cm_int(above_sill_z - win_top_z))
    else:
        top_gap = 0

    # ---- above_sill (cm): "clean" distance from slab top to upper sill;
    #      only meaningful when BOTH slab and upper window exist
    above_sill = None
    if above_sill_z is not None and slab is not None:
        above_sill = max(0, cm_int(above_sill_z - slab_z_range(slab)[1]))

    # ---- segments
    if above_sill is not None and slab is not None:
        if top_gap > 0:
            seg1, seg2 = top_gap + slab_cm, above_sill
        else:
            seg1, seg2 = 0, above_sill
    elif slab is not None:
        seg1, seg2 = top_gap + slab_cm, 0
    else:
        seg1, seg2 = top_gap, 0

    # ---- tag string
    if seg1 > 0 and seg2 > 0:
        tag = '{}/{}+{}/{}'.format(wall_cm, seg1, above_wall, seg2)
    elif seg2 > 0:
        tag = '+{}/{}'.format(above_wall, seg2)
    elif seg1 > 0:
        tag = '{}/{}'.format(wall_cm, seg1)
    else:
        tag = ''

    # ---- beam type classification
    has_lower = top_gap > 0
    has_upper = (above_sill is not None and above_sill > 0)
    if slab is None:
        beam_type = u'Нет перекрытия'
    elif has_lower and has_upper:
        beam_type = u'Обычная'
    elif has_lower and not has_upper:
        beam_type = u'Балка снизу'
    elif (not has_lower) and has_upper:
        beam_type = u'Балка сверху'
    else:
        beam_type = u'Нет балки'

    return {
        'window':     w,
        'center':     win_pt,
        # parameters written to the model
        'wall_cm':    wall_cm,
        'top_gap':    top_gap,
        'bottom':     above_sill if above_sill is not None else 0,
        'tag':        tag,
        # context info for the report
        'level_name': base.Name,
        'level_elev': cm_int(base.Elevation),
        'win_top':    cm_int(win_top_z),
        'wall_kind':  'Wall' if wall_thk_ft > 0 else 'Other',
        'xy_tol':     cm_int(xy_tol_ft),
        'above_lvl':  above_lvl,
        'above_sill': above_sill,
        'below_lvl':  below_lvl,
        'has_slab':   slab is not None,
        'slab_id':    slab.Id if slab is not None else None,
        'slab_lvl':   slab_lvl,
        'slab_bot':   slab_bot,
        'slab_top':   slab_top,
        'slab_thk':   slab_cm if slab is not None else None,
        'beam_type':  beam_type,
    }


# =====================================================================
# 11a. PHASE 1 - compute new values + read current values (no transaction)
# =====================================================================
window_data = {}     # window_id -> compute result + 'current' subdict + 'changed'
errors      = []

for w in all_windows:
    try:
        d = compute_for_window(w)
        if d is None:
            continue
        # snapshot of what's currently stored on the window
        d['current'] = {
            'wall':    read_length_cm(w, P_WALL_THK),
            'top_gap': read_length_cm(w, P_TOP_GAP),
            'bottom':  read_length_cm(w, P_BOTTOM),
            'tag':     read_string(w, P_TAGSTR),
        }
        d['changed'] = (
            d['current']['wall']    != d['wall_cm'] or
            d['current']['top_gap'] != d['top_gap'] or
            d['current']['bottom']  != d['bottom']  or
            (d['current']['tag'] or '') != (d['tag'] or '')
        )
        window_data[w.Id.IntegerValue] = d
    except Exception as e:
        errors.append('Compute {}: {}'.format(w.Id.IntegerValue, str(e)))

changed_count = sum(1 for d in window_data.values() if d['changed'])


# =====================================================================
# 11b. PHASE 2 - transaction (only if not dry-run)
# =====================================================================
updated      = 0
tags_created = 0

if not DRY_RUN:
    with Transaction(doc, 'WinTag') as tx:
        tx.Start()

        # parameters for EVERY window in the project
        for w in all_windows:
            d = window_data.get(w.Id.IntegerValue)
            if d is None:
                continue
            try:
                ok = (set_double(w, P_WALL_THK, d['wall_cm']) and
                      set_double(w, P_TOP_GAP,  d['top_gap']) and
                      set_double(w, P_BOTTOM,   d['bottom'])  and
                      set_string(w, P_TAGSTR,   d['tag']))
                if ok:
                    updated += 1
            except Exception as e:
                errors.append('Write {}: {}'.format(w.Id.IntegerValue, str(e)))

        doc.Regenerate()

        # add tags only on plan views, for untagged windows under a slab
        if TAG_TYPE is not None:
            if not TAG_TYPE.IsActive:
                TAG_TYPE.Activate()
                doc.Regenerate()
            for w in wins_in_view:
                wid = w.Id.IntegerValue
                if wid in tags_by_window:
                    continue
                d = window_data.get(wid)
                if d is None or not d['has_slab']:
                    continue
                try:
                    head_pt = d['center'].Add(
                        view.UpDirection.Multiply(cm_to_ft(TAG_OFFSET_CM)))
                    IndependentTag.Create(
                        doc, TAG_TYPE.Id, view.Id, Reference(w),
                        False, TagOrientation.Horizontal, head_pt)
                    tags_created += 1
                except Exception as e:
                    errors.append('Tag {}: {}'.format(wid, str(e)))

        tx.Commit()


# =====================================================================
# 12. REPORT
# =====================================================================
output = script.get_output()
output.set_title('WinTag - Dry Run' if DRY_RUN else 'WinTag')

mode_label = u'🔍 DRY-RUN (без записи)' if DRY_RUN else u'✏️ APPLY'
output.print_md('# WinTag - {}'.format(mode_label))

# Big banner: are tags up-to-date?
if changed_count == 0:
    output.print_md(
        '## ✅ Все окна актуальны — ни один тег не изменится')
else:
    verb = u'требуют обновления' if DRY_RUN else u'обновлено'
    output.print_md(
        '## ⚠️ {} из {} окон {}'.format(
            changed_count, len(window_data), verb))

output.print_md(
    '**View:** {}   **Окон в проекте:** {}   **Записано параметров:** {}'
    .format(view.Name, len(all_windows), updated))

if IS_PLAN:
    if DRY_RUN:
        output.print_md(
            '_Plan view_ - Windows in view: **{}** - dry-run, теги не добавлялись'
            .format(len(wins_in_view)))
    elif TAG_TYPE is None:
        output.print_md(
            '_Plan view_ - Windows in view: **{}** - теги не добавлялись'
            .format(len(wins_in_view)))
    else:
        output.print_md(
            '_Plan view_ - Windows in view: **{}** - Tags added: **{}**'
            .format(len(wins_in_view), tags_created))
else:
    output.print_md('_Не план - теги не предлагались_')

# breakdown by beam type
counts = Counter(d['beam_type'] for d in window_data.values())
if counts:
    output.print_md('### Сводка по типам балок')
    for bt, n in sorted(counts.items(), key=lambda x: -x[1]):
        output.print_md('- **{}**: {}'.format(bt, n))

# main table
def _fmt(v):
    return '-' if v in (None, '') else v

view_ids = {w.Id.IntegerValue for w in wins_in_view}

rows_keyed = []
for w in all_windows:
    d = window_data.get(w.Id.IntegerValue)
    if d is None:
        continue
    rows_keyed.append(((d['level_elev'], d['win_top'], w.Id.IntegerValue),
                       w, d))
rows_keyed.sort(key=lambda r: r[0])

table_rows = []
for _key, w, d in rows_keyed:
    slab_link = (output.linkify(d['slab_id'])
                 if d['slab_id'] is not None else u'—')
    cur = d['current']
    status = u'⚠ Изменён' if d['changed'] else u'✓ Актуален'
    table_rows.append([
        output.linkify(w.Id),
        u'✓' if w.Id.IntegerValue in view_ids else '',
        d['level_name'], d['level_elev'], d['win_top'],
        d['wall_cm'], d['wall_kind'], d['xy_tol'],
        _fmt(d['below_lvl']), _fmt(d['above_lvl']), _fmt(d['above_sill']),
        u'✓' if d['has_slab'] else u'—',
        slab_link, _fmt(d['slab_lvl']),
        _fmt(d['slab_bot']), _fmt(d['slab_top']), _fmt(d['slab_thk']),
        d['top_gap'], d['bottom'],
        d['beam_type'],
        _fmt(cur['tag']),     # current tag in model
        d['tag'] or '-',      # newly computed tag
        status,
    ])

if table_rows:
    output.print_table(
        table_data=table_rows,
        columns=['Окно', 'View',
                 'Уровень', 'Lvl Z', 'Win top',
                 'Стена', 'Хост', 'XY tol',
                 '↓ ниже', '↑ выше', '↑ sill',
                 'Перекр?', 'Перекр. ID', 'Уровень перекр.',
                 'Низ', 'Верх', 'Толщ',
                 'top_gap', 'bottom',
                 'Тип балки',
                 'Тег (был)', 'Тег (новый)', 'Изм?'],
        title='Все окна проекта (сортировка по уровню)')

# Detail list: only the windows that changed (or would change)
changed_list = [(w, d) for (_k, w, d) in rows_keyed if d['changed']]
if changed_list:
    output.print_md('### Окна с изменениями ({})'.format(len(changed_list)))
    for w, d in changed_list[:50]:
        output.print_md(
            '- {} | **{}** | было: `{}` → станет: `{}`'.format(
                output.linkify(w.Id),
                d['beam_type'],
                d['current']['tag'] if d['current']['tag'] else '(пусто)',
                d['tag'] if d['tag'] else '(пусто)'))
    if len(changed_list) > 50:
        output.print_md('_... и ещё {} окон_'.format(len(changed_list) - 50))

if errors:
    output.print_md('### Ошибки ({})'.format(len(errors)))
    for e in errors[:30]:
        output.print_md('- ' + e)
