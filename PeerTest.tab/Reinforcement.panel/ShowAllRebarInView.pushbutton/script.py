# -*- coding: utf-8 -*-
__title__  = 'Show All\nRebar'
__author__ = 'Dima'
__doc__    = '''Version = 1.0
Date      = 2026-05-24
Description:
    Sets presentation mode to "show ALL bars" for EVERY rebar
    visible in the active view (single-bar and multi-bar alike).
    Also forces each set solid & unobscured in the view.
How-To:
    Open a plan/section view, run the button.
'''

from Autodesk.Revit.DB import *
from Autodesk.Revit.DB.Structure import *
from Autodesk.Revit.UI import *
from pyrevit import forms, script

doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

view = doc.ActiveView


def set_show_all(rebar, target_view):
    """Force the whole set visible (all bars) in the given view."""
    try:
        rebar.SetSolidInView(target_view, True)
    except Exception:
        pass
    try:
        rebar.SetUnobscuredInView(target_view, True)
    except Exception:
        pass
    try:
        rebar.SetPresentationMode(target_view, RebarPresentationMode.All)
        return True
    except Exception:
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
    rebars = collect_rebar(view)
    if not rebars:
        forms.alert('No rebar found in the active view.', title='Nothing to do')
        return

    changed = 0
    errors = []

    with Transaction(doc, 'Show all rebar in view') as t:
        t.Start()
        for r in rebars:
            try:
                if set_show_all(r, view):
                    changed += 1
            except Exception as e:
                errors.append('{}: {}'.format(r.Id, str(e)))
        t.Commit()

    msg = 'Set "show all bars" on {} of {} rebar elements.'.format(changed, len(rebars))
    if errors:
        forms.alert(msg + '\n\nWarnings:\n' + '\n'.join(errors[:5]),
                    title='Done (with warnings)')
    else:
        forms.alert(msg, title='Done')


main()
