# -*- coding: utf-8 -*-
"""Renumber PR_Position in the active schedule, in the schedule's exact display order.
Counter restarts per PR_Detail_Prefix value: each prefix starts from 1.
PR_Position gets only the digit (the prefix is concatenated elsewhere).

Approach: temporarily flip the schedule into "Itemize Every Instance" mode, read the
body row-by-row (each row = one element), determine display order of unique
"row signatures", then restore Itemize and write numbers grouped by signature so that
identical merge-rows still get the same number.
All inside one transaction.
"""

from Autodesk.Revit.DB import (
    ViewSchedule,
    SectionType,
    FilteredElementCollector,
    Transaction,
    BuiltInParameter,
)
from pyrevit import revit, forms, script

doc = revit.doc
out = script.get_output()
out.close_others()

PREFIX_NAME = "PR_Detail_Prefix"
POSITION_NAME = "PR_Position"


# ---------- preconditions ----------
view = doc.ActiveView
if not isinstance(view, ViewSchedule) or view.IsTemplate:
    forms.alert("Активным должен быть вид-ведомость (ViewSchedule).",
                exitscript=True)

sd = view.Definition


# ---------- map columns ----------
visible = []  # list of (body_col_idx, field, name)
body_col = 0
for fid in sd.GetFieldOrder():
    f = sd.GetField(fid)
    if f.IsHidden:
        continue
    visible.append((body_col, f, f.GetName()))
    body_col += 1

prefix_param_id = None
position_param_id = None

# scan ALL fields (visible + hidden) to find prefix/position param ids by name.
for fid in sd.GetFieldOrder():
    f = sd.GetField(fid)
    name = f.GetName()
    if name == PREFIX_NAME and f.ParameterId is not None and f.ParameterId.IntegerValue != 0:
        prefix_param_id = f.ParameterId
    if name == POSITION_NAME and f.ParameterId is not None and f.ParameterId.IntegerValue != 0:
        position_param_id = f.ParameterId

# Signature columns: ALL visible non-formula non-combined columns EXCEPT PR_Position.
# In itemized mode there's no aggregation, so we don't need a numeric blacklist.
sig_cols = []        # body column indices
sig_param_ids = []   # corresponding ParameterId on element side
sig_field_names = [] # for diagnostics
for col_idx, f, name in visible:
    if name == POSITION_NAME:
        continue
    is_calc = False
    is_combo = False
    try:
        is_calc = bool(f.IsCalculatedField)
    except Exception:
        pass
    try:
        is_combo = bool(f.IsCombinedParameterField)
    except Exception:
        pass
    if is_calc or is_combo:
        continue
    pid = f.ParameterId
    if pid is None or pid.IntegerValue == 0:
        continue
    sig_cols.append(col_idx)
    sig_param_ids.append(pid)
    sig_field_names.append(name)

if prefix_param_id is None:
    forms.alert(u"В таблице нет поля '%s' (даже среди скрытых)." % PREFIX_NAME,
                exitscript=True)
if position_param_id is None:
    forms.alert(u"В таблице нет поля '%s' (даже среди скрытых)." % POSITION_NAME,
                exitscript=True)
if not sig_cols:
    forms.alert(u"В таблице не нашлось ни одной видимой не-формульной колонки "
                u"для построения подписи. Откройте видимыми хотя бы одно реальное "
                u"поле (например, диаметр или длину).",
                exitscript=True)


# ---------- helpers ----------
def _get_param(el, pid):
    if pid is None or pid.IntegerValue == 0:
        return None
    if pid.IntegerValue < 0:
        try:
            bip = BuiltInParameter(pid.IntegerValue)
            return el.get_Parameter(bip)
        except Exception:
            return None
    pe = doc.GetElement(pid)
    if pe is None:
        return None
    try:
        return el.get_Parameter(pe.GetDefinition())
    except Exception:
        return None


def _param_text(el, pid):
    p = _get_param(el, pid)
    if p is None:
        return u""
    v = p.AsValueString()
    if v is None or v == "":
        v = p.AsString() or u""
    return v or u""


# ---------- everything inside one transaction ----------
t = Transaction(doc, "Renumber PR_Position")
t.Start()

written = 0
errors = []
order_sigs = []     # unique signatures in first-occurrence order
counters = {}
unmatched_sigs = []

try:
    orig_itemized = sd.IsItemized

    # Force itemize ON so each body row == one element instance.
    if not orig_itemized:
        sd.IsItemized = True
    doc.Regenerate()

    body = view.GetTableData().GetSectionData(SectionType.Body)
    n_rows = body.NumberOfRows

    seen = set()
    for r in range(n_rows):
        sig = tuple((body.GetCellText(r, c) or u"") for c in sig_cols)
        if sig in seen:
            continue
        seen.add(sig)
        order_sigs.append(sig)

    # Restore original itemize state BEFORE writing positions, so writes reflect
    # the user's normal merge-grouping.
    if sd.IsItemized != orig_itemized:
        sd.IsItemized = orig_itemized
    doc.Regenerate()

    # Collect elements (filter applied by schedule).
    elements = list(
        FilteredElementCollector(doc, view.Id)
        .WhereElementIsNotElementType()
        .ToElements()
    )

    # Group elements by the same signature (using their parameter values).
    sig_to_els = {}
    for el in elements:
        sig = tuple(_param_text(el, pid) for pid in sig_param_ids)
        sig_to_els.setdefault(sig, []).append(el)

    # Assign in display order (one number per unique signature, restart per prefix).
    assignments = []
    for sig in order_sigs:
        matched = sig_to_els.get(sig)
        if not matched:
            unmatched_sigs.append(sig)
            continue
        pref = _param_text(matched[0], prefix_param_id)
        counters[pref] = counters.get(pref, 0) + 1
        new_val = u"%d" % counters[pref]
        assignments.append((matched, new_val))

    # Write.
    for elems, val in assignments:
        for el in elems:
            p = _get_param(el, position_param_id)
            if p is None:
                errors.append("eid %s: no PR_Position param" % el.Id)
                continue
            if p.IsReadOnly:
                errors.append("eid %s: PR_Position is read-only" % el.Id)
                continue
            try:
                p.Set(val)
                written += 1
            except Exception as ex:
                errors.append("eid %s: %s" % (el.Id, ex))

    t.Commit()
except Exception as ex:
    if t.HasStarted() and not t.HasEnded():
        t.RollBack()
    forms.alert(u"Ошибка: %s" % ex, exitscript=True)


# ---------- report ----------
out.print_md("# PR_Position renumbered")
out.print_md("- Schedule: **%s**" % view.Name)
out.print_md("- Unique row signatures (display order): **%d**" % len(order_sigs))
out.print_md("- Element params written: **%d**" % written)

if counters:
    out.print_md("### Counters per prefix")
    out.print_md("| Prefix | Count |")
    out.print_md("|---|---:|")
    for k in sorted(counters):
        shown = k if k else "<empty>"
        out.print_md("| `%s` | %d |" % (shown, counters[k]))

if unmatched_sigs:
    out.print_md("### Signatures without matching elements (skipped)")
    out.print_md("Total: **%d**" % len(unmatched_sigs))
    for sig in unmatched_sigs[:10]:
        out.print_md("- `%s`" % " | ".join(sig))
    if len(unmatched_sigs) > 10:
        out.print_md("- _…and %d more_" % (len(unmatched_sigs) - 10))

if errors:
    out.print_md("### Write errors")
    for e in errors[:20]:
        out.print_md("- %s" % e)
    if len(errors) > 20:
        out.print_md("- _…and %d more_" % (len(errors) - 20))
