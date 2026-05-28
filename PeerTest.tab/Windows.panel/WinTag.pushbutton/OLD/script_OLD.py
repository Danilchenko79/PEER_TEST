# -*- coding: utf-8 -*-
"""WinTag - update window MD_* params and replace IndependentTags in active view.

Pipeline:
  0. Constants and user input (XY tolerance).
  1. Param / unit utilities.
  2. Window helpers     (center / sill / height / host wall thickness).
  3. Floor (slab) helpers (level / offset / thickness / XY-match).
  4. Index the model    (levels, floors-by-level, windows-by-XY).
  5. Tag helpers        (existing-tags-by-window, default placement).
  6. compute_for_window - all the math + tag string for ONE window.
  7. Transaction        - write params, regenerate, replace tags.
  8. Report.
"""

__title__  = 'WinTag'
__author__ = 'Dima'

import sys
from Autodesk.Revit.DB import (
    FilteredElementCollector, Level, IndependentTag, Transaction,
    BuiltInParameter, BuiltInCategory, StorageType, ElementId, Element,
    LocationPoint, LocationCurve, Wall, UnitUtils, UnitTypeId,
    FamilySymbol, TagOrientation, Reference, ViewPlan
)
from pyrevit import forms, script

doc  = __revit__.ActiveUIDocument.Document
view = doc.ActiveView


# =====================================================================
# 0. CONSTANTS
# =====================================================================
P_WALL_THK    = 'MD_WallThickness_cm'
P_TOP_GAP     = 'MD_TopGap_cm'
P_BOTTOM      = 'MD_BottomFromLevel_cm'
P_TAGSTR      = 'MD_TagString'

XY_TOL_CM     = 5.0     # cm - XY tolerance for stacked-window matching
XY_TOL_FT     = XY_TOL_CM / 30.48
TAG_OFFSET_CM = 20.0    # cm - default tag head offset above window center


# =====================================================================
# 1. PARAM / UNIT UTILITIES
# =====================================================================
def cm_to_ft(cm): return UnitUtils.ConvertToInternalUnits(float(cm), UnitTypeId.Centimeters)
def ft_to_cm(ft): return UnitUtils.ConvertFromInternalUnits(float(ft), UnitTypeId.Centimeters)
def cm_int(ft):   return int(round(ft_to_cm(ft), 0))

def _norm(s): return ' '.join(str(s or '').strip().split()).lower()

def find_param(elem, name):
    """LookupParameter + case-insensitive fallback over all parameters."""
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

def _double_param(elem, bips, names):
    """Read first Double param from a list of BuiltInParameters then names."""
    for bip in bips:
        try:
            p = elem.get_Parameter(bip)
            if p and p.StorageType == StorageType.Double:
                return p.AsDouble()
        except Exception:
            pass
    for n in names:
        p = elem.LookupParameter(n)
        if p and p.StorageType == StorageType.Double:
            return p.AsDouble()
    return None

def _eid_param(elem, bips):
    for bip in bips:
        try:
            p = elem.get_Parameter(bip)
            if p:
                eid = p.AsElementId()
                if eid and eid != ElementId.InvalidElementId:
                    return eid
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
        p.Set(txt or '')
        return True
    return False


# =====================================================================
# 2. WINDOW HELPERS
# =====================================================================
def window_center(win):
    loc = win.Location
    if isinstance(loc, LocationPoint):
        return loc.Point
    if isinstance(loc, LocationCurve):
        return loc.Curve.Evaluate(0.5, True)
    return None

def get_sill_ft(win):
    return _double_param(win,
        [BuiltInParameter.INSTANCE_SILL_HEIGHT_PARAM],
        ['Sill Height', u'גובה אדן', u'גובה סף'])

def get_height_ft(win):
    sym = win.Symbol
    if not sym:
        return None
    return _double_param(sym,
        [BuiltInParameter.FAMILY_HEIGHT_PARAM],
        ['Height', u'גובה'])

def wall_thk_cm(elem, fallback=0):
    host = getattr(elem, 'Host', None) if elem else None
    if isinstance(host, Wall):
        return cm_int(host.WallType.Width)
    return fallback


# =====================================================================
# 3. SLAB GEOMETRY (Z-based - works regardless of level/offset/category)
# =====================================================================
def slab_z_range(slab):
    """(bottom_z, top_z) from BoundingBox; or (None, None)."""
    bb = slab.get_BoundingBox(None)
    return (bb.Min.Z, bb.Max.Z) if bb else (None, None)

def slab_xy_covers(slab, x, y, tol_ft):
    bb = slab.get_BoundingBox(None)
    if not bb:
        return False
    return (bb.Min.X - tol_ft <= x <= bb.Max.X + tol_ft and
            bb.Min.Y - tol_ft <= y <= bb.Max.Y + tol_ft)


# =====================================================================
# 4. INDEX THE MODEL
# =====================================================================
levels = sorted(FilteredElementCollector(doc).OfClass(Level).ToElements(),
                key=lambda l: l.Elevation)

# All slab-like elements (Floors + Roofs) as a flat list
all_slabs = []
for _cat in (BuiltInCategory.OST_Floors, BuiltInCategory.OST_Roofs):
    all_slabs.extend(FilteredElementCollector(doc)
                     .OfCategory(_cat)
                     .WhereElementIsNotElementType().ToElements())

def next_level(base):
    """First level strictly above base."""
    for lv in levels:
        if lv.Elevation > base.Elevation + 1e-6:
            return lv
    return None

def slab_above_window(win_pt, win_top_z, ceiling_z=None, tol_ft=None):
    """Slab whose XY covers the window, with bottom strictly above win_top_z.
       If ceiling_z is given, slab top must also be at/below ceiling_z + tol
       (so we do not pick a slab that lies above the upper window).
       tol_ft = XY tolerance for the BBox check (defaults to XY_TOL_FT).
       Returns the closest such slab, or None."""
    if win_pt is None:
        return None
    if tol_ft is None:
        tol_ft = XY_TOL_FT
    best = None
    best_z = None
    for slab in all_slabs:
        bot, top = slab_z_range(slab)
        if bot is None:
            continue
        # Slab bottom must be AT or above window top (allow exact contact)
        if bot < win_top_z - 1e-3:
            continue
        # Slab top must be AT or below upper window sill (allow exact contact)
        if ceiling_z is not None and top > ceiling_z + 1e-3:
            continue
        if not slab_xy_covers(slab, win_pt.X, win_pt.Y, tol_ft):
            continue
        if best_z is None or bot < best_z:
            best_z = bot
            best = slab
    return best

def _stacked(win_pt, base, direction):
    """Closest stacked window in given direction (+1 above, -1 below).
       Uses true XY distance check (not bucketing), so windows near
       bucket boundaries are not missed."""
    if win_pt is None or base is None:
        return None
    tol_sq = XY_TOL_FT * XY_TOL_FT
    best = None
    best_elev = None
    for w in wins_all:
        if w.LevelId is None:
            continue
        lvl = doc.GetElement(w.LevelId)
        if lvl is None:
            continue
        if direction > 0 and lvl.Elevation <= base.Elevation + 1e-6:
            continue
        if direction < 0 and lvl.Elevation >= base.Elevation - 1e-6:
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

def find_above_window(win_pt, base): return _stacked(win_pt, base,  1)
def find_below_window(win_pt, base): return _stacked(win_pt, base, -1)

# All windows in project
wins_all = list(FilteredElementCollector(doc)
                .OfCategory(BuiltInCategory.OST_Windows)
                .WhereElementIsNotElementType().ToElements())

# Windows in active view - only used for tag creation
wins_in_view = list(FilteredElementCollector(doc, view.Id)
                    .OfCategory(BuiltInCategory.OST_Windows)
                    .WhereElementIsNotElementType().ToElements())


# =====================================================================
# 5. TAG HELPERS
# =====================================================================
def tagged_ids(tag):
    try:
        return [eid.IntegerValue for eid in tag.GetTaggedLocalElementIds()]
    except Exception:
        pass
    try:
        return [tag.TaggedLocalElementId.IntegerValue]
    except Exception:
        return []

tags_by_window = {}
for _t in FilteredElementCollector(doc, view.Id).OfClass(IndependentTag).ToElements():
    try:
        _pos = _t.TagHeadPosition
    except Exception:
        _pos = None
    for _wid in tagged_ids(_t):
        tags_by_window.setdefault(_wid, []).append((_t.Id, _pos))

def default_tag_pt(center):
    return center.Add(view.UpDirection.Multiply(cm_to_ft(TAG_OFFSET_CM)))


# =====================================================================
# 5b. USER CHOICE - tag type (only on plan views)
# =====================================================================
IS_PLAN  = isinstance(view, ViewPlan)
TAG_TYPE = None

if IS_PLAN:
    _tag_types = list(FilteredElementCollector(doc)
                      .OfClass(FamilySymbol)
                      .OfCategory(BuiltInCategory.OST_WindowTags)
                      .ToElements())

    SKIP_LABEL = u'⊘  Не добавлять теги (только обновить параметры)'

    _labels = [SKIP_LABEL]
    _label_to_type = {}
    for _tt in _tag_types:
        _lbl = '{} : {}'.format(_tt.Family.Name, Element.Name.GetValue(_tt))
        _labels.append(_lbl)
        _label_to_type[_lbl] = _tt

    _missing = sum(1 for _w in wins_in_view
                   if _w.Id.IntegerValue not in tags_by_window)

    _choice = forms.SelectFromList.show(
        _labels,
        title='WinTag - добавить недостающие теги ({} окон без тега)'.format(_missing),
        button_name='OK',
        multiselect=False
    )
    if _choice is None:
        sys.exit()

    TAG_TYPE = None if _choice == SKIP_LABEL else _label_to_type.get(_choice)


# =====================================================================
# 6. CORE COMPUTATION FOR ONE WINDOW
# =====================================================================
def compute_for_window(w):
    """Compute MD_* parameter values and tag string for one window.

    Geometry (everything via absolute Z, then converted to cm):
        win_top_z    = window_top Z in project coordinates
        slab_bot_z   = bottom face Z of the closest slab above (XY match)
        slab_top_z   = top    face Z of that slab
        top_gap_cm   = slab_bot_z - win_top_z   (>= 0)
        slab_cm      = slab_top_z - slab_bot_z  (slab thickness)
        above_sill   = sill of upper window (if any) measured from its level

    Tag segments (the two beams around the slab):
        seg1 = current-wall beam BELOW the slab top
        seg2 = upper-wall beam ABOVE the slab top, up to upper window sill
    Slab joins seg1 when there is a beam below (top_gap > 0) or no upper window.
    Slab joins seg2 only when the window meets the slab directly (top_gap == 0)
    AND there is an upper window above.
    Any segment with value 0 is omitted from the tag.
    """
    base = doc.GetElement(w.LevelId) if w.LevelId else None
    if not base:
        return None
    sill_ft   = get_sill_ft(w)
    height_ft = get_height_ft(w)
    win_pt    = window_center(w)
    if sill_ft is None or height_ft is None or win_pt is None:
        return None

    # --- absolute Z of window top
    win_top_z = base.Elevation + sill_ft + height_ft

    # --- host wall thickness (used as XY tolerance for slab BBox check)
    wall_cm = wall_thk_cm(w, fallback=0)
    host = getattr(w, 'Host', None)
    wall_thk_ft = host.WallType.Width if isinstance(host, Wall) else 0.0
    slab_xy_tol = max(XY_TOL_FT, wall_thk_ft)   # generous: handle wall thickness

    # --- upper window first (any higher level, distance-based)
    above_win  = find_above_window(win_pt, base)
    above_sill = None
    above_sill_z = None                 # absolute Z of upper window sill (ft)
    above_level_name = None
    if above_win is not None:
        s = get_sill_ft(above_win)
        ab_base = doc.GetElement(above_win.LevelId) if above_win.LevelId else None
        if s is not None and ab_base is not None:
            above_sill   = int(round(ft_to_cm(s), 0))
            above_sill_z = ab_base.Elevation + s
            above_level_name = ab_base.Name

    # --- lower window (debug only - not used in math)
    below_win = find_below_window(win_pt, base)
    below_level_name = None
    if below_win is not None:
        bl_base = doc.GetElement(below_win.LevelId) if below_win.LevelId else None
        if bl_base is not None:
            below_level_name = bl_base.Name

    # --- slab above this window (Z + XY, constrained by upper window sill)
    slab = slab_above_window(win_pt, win_top_z,
                             ceiling_z=above_sill_z, tol_ft=slab_xy_tol)
    if slab is not None:
        slab_bot_z, slab_top_z = slab_z_range(slab)
        slab_cm     = cm_int(slab_top_z - slab_bot_z)
        slab_bot_cm = cm_int(slab_bot_z)
        slab_top_cm = cm_int(slab_top_z)
        top_gap     = max(0, cm_int(slab_bot_z - win_top_z))
    else:
        slab_cm     = 0
        slab_bot_cm = None
        slab_top_cm = None
        # No slab - top_gap goes up to the next level (or the upper window)
        if above_sill_z is not None:
            top_gap = max(0, cm_int(above_sill_z - win_top_z))
        else:
            story_fallback = next_level(base)
            if story_fallback is None:
                return None
            top_gap = max(0, cm_int(story_fallback.Elevation - win_top_z))

    above_wall = wall_thk_cm(above_win, fallback=wall_cm) if above_win else wall_cm

    # --- segments
    #   "Обычная"     (top_gap>0, above_sill>0): seg1 = top_gap+slab, seg2 = above_sill
    #   "Балка сверху" (top_gap=0, above_sill>0): seg1 = 0,            seg2 = above_sill
    #   "Балка снизу"  (top_gap>0, above_sill=0): seg1 = top_gap+slab, seg2 = 0
    #   no upper window:                          seg1 = top_gap+slab, seg2 = 0
    # NOTE: slab thickness is NEVER added to seg2. The "Балка сверху" tag
    #       shows only above_sill (distance from slab top to upper sill).
    if above_sill is not None:
        bottom_cm = above_sill
        if top_gap > 0:
            seg1, seg2 = top_gap + slab_cm, above_sill
        else:
            seg1, seg2 = 0, above_sill
    else:
        bottom_cm = 0
        seg1, seg2 = top_gap + slab_cm, 0

    # --- tag string (skip any /0 segment)
    if seg1 > 0 and seg2 > 0:
        tag = '{}/{}+{}/{}'.format(wall_cm, seg1, above_wall, seg2)
    elif seg2 > 0:
        tag = '+{}/{}'.format(above_wall, seg2)
    elif seg1 > 0:
        tag = '{}/{}'.format(wall_cm, seg1)
    else:
        tag = ''

    # --- classify beam type (based on slab presence and surrounding concrete)
    has_lower_beam = top_gap > 0
    has_upper_beam = (above_sill is not None and above_sill > 0)
    if slab is None:
        beam_type = u'Нет перекрытия'
    elif has_lower_beam and has_upper_beam:
        beam_type = u'Обычная'
    elif has_lower_beam and not has_upper_beam:
        beam_type = u'Балка снизу'
    elif (not has_lower_beam) and has_upper_beam:
        beam_type = u'Балка сверху'
    else:
        beam_type = u'Нет балки'

    return {'wall_cm':    wall_cm,
            'top_gap':    top_gap,
            'bottom':     bottom_cm,
            'tag':        tag,
            'center':     win_pt,
            'under_slab': slab is not None,
            'slab_thk':   slab_cm,
            'slab_bot':   slab_bot_cm,
            'slab_top':   slab_top_cm,
            'beam_type':  beam_type,
            # debug info for the report
            'level_name':  base.Name,
            'level_elev':  cm_int(base.Elevation),
            'win_top_cm':  cm_int(win_top_z),
            'above_lvl':   above_level_name,
            'above_sill':  above_sill,
            'below_lvl':   below_level_name}


# =====================================================================
# 7. TRANSACTION - write params for ALL windows + add missing tags in view
# =====================================================================
updated       = 0
tags_created  = 0
errors        = []
window_data   = {}    # window_id -> compute result (center + under_slab flag)

with Transaction(doc, 'WinTag') as tx:
    tx.Start()

    # 7a. parameters - EVERY window in project
    for w in wins_all:
        try:
            data = compute_for_window(w)
            if data is None:
                continue
            ok = (set_double(w, P_WALL_THK, data['wall_cm']) and
                  set_double(w, P_TOP_GAP,  data['top_gap']) and
                  set_double(w, P_BOTTOM,   data['bottom'])  and
                  set_string(w, P_TAGSTR,   data['tag']))
            if ok:
                updated += 1
            window_data[w.Id.IntegerValue] = data
        except Exception as e:
            errors.append('Param {}: {}'.format(w.Id.IntegerValue, str(e)))

    doc.Regenerate()

    # 7b. tags - active plan view, untagged windows that are UNDER a slab
    if TAG_TYPE is not None:
        if not TAG_TYPE.IsActive:
            TAG_TYPE.Activate()
            doc.Regenerate()
        for w in wins_in_view:
            wid = w.Id.IntegerValue
            if wid in tags_by_window:
                continue                            # already has a tag
            data = window_data.get(wid)
            if data is None or not data['under_slab']:
                continue                            # not under a slab - skip
            try:
                IndependentTag.Create(
                    doc, TAG_TYPE.Id, view.Id, Reference(w),
                    False, TagOrientation.Horizontal, default_tag_pt(data['center']))
                tags_created += 1
            except Exception as e:
                errors.append('Tag {}: {}'.format(wid, str(e)))

    tx.Commit()


# =====================================================================
# 8. REPORT - rich pyRevit output with clickable window IDs
# =====================================================================
output = script.get_output()
output.set_title('WinTag')

output.print_md('# WinTag')
output.print_md('**View:** {}    **Windows in project:** {}    **Params updated:** {}'
                .format(view.Name, len(wins_all), updated))

if IS_PLAN:
    if TAG_TYPE is None:
        output.print_md('_Plan view_ - Windows in view: **{}** - теги не добавлялись'
                        .format(len(wins_in_view)))
    else:
        output.print_md('_Plan view_ - Windows in view: **{}** - Tags added: **{}**'
                        .format(len(wins_in_view), tags_created))
else:
    output.print_md('_Не план - теги не предлагались_')

# --- breakdown by beam type
from collections import Counter
counts = Counter(d['beam_type'] for d in window_data.values())
if counts:
    output.print_md('### Сводка по типам балок')
    for bt, n in sorted(counts.items(), key=lambda x: -x[1]):
        output.print_md('- **{}**: {}'.format(bt, n))

# --- main table, sorted by level elevation then by window top
def _fmt(v):
    return '-' if v in (None, '') else v

view_ids = {w.Id.IntegerValue for w in wins_in_view}

rows_with_keys = []
for w in wins_all:
    d = window_data.get(w.Id.IntegerValue)
    if d is None:
        continue
    rows_with_keys.append(((d['level_elev'], d['win_top_cm'], w.Id.IntegerValue), w, d))

rows_with_keys.sort(key=lambda r: r[0])

table_rows = []
for _key, w, d in rows_with_keys:
    table_rows.append([
        output.linkify(w.Id),
        u'✓' if w.Id.IntegerValue in view_ids else '',
        d['level_name'],
        d['win_top_cm'],
        _fmt(d['below_lvl']),
        _fmt(d['above_lvl']),
        _fmt(d['above_sill']),
        u'✓' if d['under_slab'] else u'—',
        _fmt(d['slab_bot']),
        _fmt(d['slab_top']),
        _fmt(d['slab_thk']),
        d['top_gap'],
        d['bottom'],
        d['wall_cm'],
        d['beam_type'],
        d['tag'] or '-',
    ])

if table_rows:
    output.print_table(
        table_data=table_rows,
        columns=['Окно', 'View',
                 'Уровень', 'Win top, см',
                 '↓ Окно ниже', '↑ Окно выше', '↑ sill, см',
                 'Перекр?', 'Низ, см', 'Верх, см', 'Толщ, см',
                 'top_gap', 'bottom', 'Стена',
                 'Тип балки', 'Тег'],
        title='Все окна проекта (отсортировано по уровню)')

if errors:
    output.print_md('### Ошибки ({}):'.format(len(errors)))
    for e in errors[:20]:
        output.print_md('- ' + e)
