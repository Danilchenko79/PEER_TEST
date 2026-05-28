# -*- coding: utf-8 -*-
__title__  = 'Expand\nMulti-Bar'
__author__ = 'Dima'
__doc__    = '''Version = 1.0
Date      = 2026-05-24
Description:
    Sets presentation mode to "show ALL bars" on the active view,
    but ONLY for rebar sets that contain more than one bar.
    Single-bar sets are left untouched.
    Works on free Rebar (shape-driven & free-form), and on the
    individual RebarInSystem bars of Area/Path Reinforcement.
How-To:
    Open a plan/section view, run the button. All multi-bar sets
    visible in the view get expanded (every bar shown).
'''

from Autodesk.Revit.DB import *
from Autodesk.Revit.DB.Structure import *
from Autodesk.Revit.UI import *
from pyrevit import forms, script

doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

view = doc.ActiveView


def quantity(rebar):
    """Return number of bars in a Rebar / RebarInSystem set."""
    try:
        return rebar.NumberOfBarPositions
    except Exception:
        # Fallback: some elements expose the count via parameter
        p = rebar.get_Parameter(BuiltInParameter.REBAR_ELEM_QUANTITY_OF_BARS)
        if p:
            return p.AsInteger()
        return 1


def set_show_all(rebar, target_view):
    """Force the whole set to be visible (all bars) in the given view."""
    # Make sure the set itself is solid/visible in this view first
    try:
        rebar.SetSolidInView(target_view, True)
    except Exception:
        pass
    try:
        rebar.SetUnobscuredInView(target_view, True)
    except Exception:
        pass

    # Presentation mode = show every bar in the set
    try:
        rebar.SetPresentationMode(target_view, RebarPresentationMode.All)
        return True
    except Exception:
        # RebarInSystem (Area/Path members) may not accept presentation mode
        # in every Revit version; visibility above is then the best we can do.
        return False


def collect_rebar(target_view):
    """All Rebar + RebarInSystem visible in the view."""
    elems = []
    for cls in (Rebar, RebarInSystem):
        col = FilteredElementCollector(doc, target_view.Id) \
            .OfClass(cls) \
            .WhereElementIsNotElementType() \
            .ToElements()
        elems.extend(col)
    return elems


def main():
    if view is None or not view.CanBePrinted:
        # CanBePrinted is False for things like schedules / browser
        pass

    rebars = collect_rebar(view)
    if not rebars:
        forms.alert('No rebar found in the active view.', title='Nothing to do')
        return

    changed = []
    skipped_single = 0
    no_presentation = 0   # multi-bar sets whose class doesn't accept presentation mode
    errors = []

    with Transaction(doc, 'Expand multi-bar rebar sets') as t:
        t.Start()
        for r in rebars:
            try:
                n = quantity(r)
                if n is None or n <= 1:
                    skipped_single += 1
                    continue
                ok = set_show_all(r, view)
                if ok:
                    changed.append((r, n))
                else:
                    no_presentation += 1
            except Exception as e:
                errors.append('{}: {}'.format(r.Id, str(e)))
        t.Commit()

    output = script.get_output()
    if changed:
        data = [[output.linkify(r.Id), str(n)] for r, n in changed]
        output.print_table(
            table_data=data,
            columns=['Rebar ID', 'Bars in set'],
            title='Expanded multi-bar sets: {}'.format(len(changed))
        )

    msg = 'Expanded: {}\nSingle-bar skipped: {}'.format(len(changed), skipped_single)
    if no_presentation:
        msg += '\nMulti-bar but no presentation API: {}'.format(no_presentation)
    if errors:
        msg += '\nWarnings: {}'.format(len(errors))
        forms.alert(msg + '\n\n' + '\n'.join(errors[:5]), title='Done (with warnings)')
    else:
        forms.alert(msg, title='Done')


main()
