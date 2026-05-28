# -*- coding: utf-8 -*-
__title__  = 'Export Names\nfor Translation'
__author__ = 'Dima'
__doc__    = '''Version = 1.0
Date      = 2026-04-27
Description:
    Collects every renameable user-visible element in the project
    (views, schedules, sheets, templates, filters, materials,
    levels, grids, phases, group types) and exports them to a TSV
    file with columns: Category, Id, CurrentName, NewName.
    Edit NewName in Excel, then run "Apply Translations".
How-To:
    1. Run the script.
    2. Pick an output .tsv path.
    3. Open the file in Excel — items with Cyrillic names appear first.
    4. Fill the NewName column for each row to translate.
    5. Save (UTF-8 with tab separator).
    6. Run the "Apply Translations" button to apply renames.
'''

import codecs
import sys
from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory,
    View, ViewType, ViewSchedule,
    ParameterFilterElement, Material, Phase, GroupType
)
from pyrevit import forms, script

doc = __revit__.ActiveUIDocument.Document


# ------------------------------------------------------------------
# Pick output file
# ------------------------------------------------------------------
out_path = forms.save_file(
    file_ext='tsv',
    default_name='revit_names_translation.tsv'
)
if not out_path:
    sys.exit()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def has_cyrillic(s):
    if not s:
        return False
    for c in s:
        if u'Ѐ' <= c <= u'ӿ':
            return True
    return False


def safe(name):
    """Strip TSV-breaking characters."""
    if name is None:
        return ''
    return name.replace('\t', ' ').replace('\r', ' ').replace('\n', ' ')


rows = []   # list of tuples (Category, Id, CurrentName)


# ------------------------------------------------------------------
# 1. Views — schedules, sheets, templates, plans, sections, legends...
# ------------------------------------------------------------------
for v in FilteredElementCollector(doc).OfClass(View).ToElements():
    try:
        # Skip system schedules (revision schedules on title blocks)
        if isinstance(v, ViewSchedule):
            try:
                if v.IsTitleblockRevisionSchedule:
                    continue
            except Exception:
                pass
            cat = 'View Template (Schedule)' if v.IsTemplate else 'Schedule'
        elif v.IsTemplate:
            cat = 'View Template ({})'.format(str(v.ViewType))
        elif v.ViewType == ViewType.DrawingSheet:
            cat = 'Sheet'
        elif v.ViewType == ViewType.Legend:
            cat = 'Legend'
        elif v.ViewType == ViewType.DraftingView:
            cat = 'Drafting View'
        elif v.ViewType in (ViewType.Internal, ViewType.SystemBrowser,
                            ViewType.ProjectBrowser, ViewType.Undefined):
            continue
        else:
            cat = 'View ({})'.format(str(v.ViewType))

        rows.append((cat, v.Id.IntegerValue, v.Name))
    except Exception:
        pass


# ------------------------------------------------------------------
# 2. Filters
# ------------------------------------------------------------------
for f in FilteredElementCollector(doc).OfClass(ParameterFilterElement):
    try:
        rows.append(('Filter', f.Id.IntegerValue, f.Name))
    except Exception:
        pass


# ------------------------------------------------------------------
# 3. Materials
# ------------------------------------------------------------------
for m in FilteredElementCollector(doc).OfClass(Material):
    try:
        rows.append(('Material', m.Id.IntegerValue, m.Name))
    except Exception:
        pass


# ------------------------------------------------------------------
# 4. Levels
# ------------------------------------------------------------------
for l in (FilteredElementCollector(doc)
          .OfCategory(BuiltInCategory.OST_Levels)
          .WhereElementIsNotElementType()):
    try:
        rows.append(('Level', l.Id.IntegerValue, l.Name))
    except Exception:
        pass


# ------------------------------------------------------------------
# 5. Grids
# ------------------------------------------------------------------
for g in (FilteredElementCollector(doc)
          .OfCategory(BuiltInCategory.OST_Grids)
          .WhereElementIsNotElementType()):
    try:
        rows.append(('Grid', g.Id.IntegerValue, g.Name))
    except Exception:
        pass


# ------------------------------------------------------------------
# 6. Phases
# ------------------------------------------------------------------
for p in FilteredElementCollector(doc).OfClass(Phase):
    try:
        rows.append(('Phase', p.Id.IntegerValue, p.Name))
    except Exception:
        pass


# ------------------------------------------------------------------
# 7. Group Types (model + detail groups)
# ------------------------------------------------------------------
for gt in FilteredElementCollector(doc).OfClass(GroupType):
    try:
        rows.append(('Group Type', gt.Id.IntegerValue, gt.Name))
    except Exception:
        pass


# ------------------------------------------------------------------
# Sort: Cyrillic items first (they likely need translating),
# then by category, then by name
# ------------------------------------------------------------------
rows.sort(key=lambda r: (
    0 if has_cyrillic(r[2]) else 1,
    r[0],
    r[2].lower()
))


# ------------------------------------------------------------------
# Write TSV
# ------------------------------------------------------------------
with codecs.open(out_path, 'w', encoding='utf-8-sig') as f:
    f.write('Category\tId\tCurrentName\tNewName\n')
    for cat, eid, name in rows:
        f.write('{}\t{}\t{}\t\n'.format(cat, eid, safe(name)))


cyr_count = sum(1 for r in rows if has_cyrillic(r[2]))

forms.alert(
    'Exported {} items.\n'
    '{} contain Cyrillic and probably need translation.\n\n'
    'File: {}\n\n'
    'Open in Excel, fill the NewName column,\n'
    'then run "Apply Translations".'.format(len(rows), cyr_count, out_path),
    title='Export complete'
)
