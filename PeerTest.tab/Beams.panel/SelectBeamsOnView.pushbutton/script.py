# -*- coding: utf-8 -*-
__title__  = 'Select Beams\nOn View'
__author__ = 'Dima'
__doc__    = '''Version = 1.3
Date      = 30.03.2026
Description: Finds StructuralFraming elements WITHOUT tags on the active view.
             Host untagged elements are selected and listed with clickable IDs.
             Link untagged elements are listed in the output table.
How-To:
    Open any plan / section / elevation and run the script.
'''

from Autodesk.Revit.DB import *
from pyrevit import script
from System.Collections.Generic import List

doc         = __revit__.ActiveUIDocument.Document
uidoc       = __revit__.ActiveUIDocument
active_view = doc.ActiveView
output      = script.get_output()


def get_view_outline_in_link_space(view, link_transform):
    crop_box = view.CropBox
    box_t    = crop_box.Transform
    mn, mx   = crop_box.Min, crop_box.Max

    corners_world = [
        box_t.OfPoint(XYZ(x, y, z))
        for x in [mn.X, mx.X]
        for y in [mn.Y, mx.Y]
        for z in [mn.Z, mx.Z]
    ]

    inv          = link_transform.Inverse
    corners_link = [inv.OfPoint(p) for p in corners_world]

    xs = [p.X for p in corners_link]
    ys = [p.Y for p in corners_link]
    zs = [p.Z for p in corners_link]

    return Outline(
        XYZ(min(xs), min(ys), min(zs) - 50.0),
        XYZ(max(xs), max(ys), max(zs) + 50.0)
    )


# ══════════════════════════════════════════════════════════
# 1. COLLECT ALL TAGS ON VIEW
#    — build sets of tagged IDs for fast lookup
# ══════════════════════════════════════════════════════════

# tagged_host_ids  : set of ElementId  (host elements that have a tag)
# tagged_link_keys : set of (link_inst_id_int, elem_id_int)
tagged_host_ids  = set()
tagged_link_keys = set()

all_tags = (
    FilteredElementCollector(doc, active_view.Id)
        .OfClass(IndependentTag)
        .WhereElementIsNotElementType()
        .ToElements()
)

for tag in all_tags:
    try:
        # GetTaggedElementIds() — основной метод (Revit 2022+)
        # LinkElementId.LinkInstanceId  = Id линк-инстанса (Invalid → хост)
        # LinkElementId.LinkedElementId = Id элемента внутри линка
        for leid in tag.GetTaggedElementIds():
            if leid.LinkInstanceId == ElementId.InvalidElementId:
                tagged_host_ids.add(leid.HostElementId)
            else:
                tagged_link_keys.add((
                    leid.LinkInstanceId.IntegerValue,
                    leid.LinkedElementId.IntegerValue,
                ))
    except Exception:
        # Fallback для старых версий Revit
        try:
            local_id = tag.TaggedLocalElementId
            if local_id and local_id != ElementId.InvalidElementId:
                tagged_host_ids.add(local_id)
        except Exception:
            pass
        try:
            ref = tag.GetTaggedReference()
            if ref is not None:
                if ref.LinkedElementId == ElementId.InvalidElementId:
                    tagged_host_ids.add(ref.ElementId)
                else:
                    tagged_link_keys.add((
                        ref.ElementId.IntegerValue,
                        ref.LinkedElementId.IntegerValue,
                    ))
        except Exception:
            pass


# ══════════════════════════════════════════════════════════
# 2. COLLECT HOST StructuralFraming — filter untagged
# ══════════════════════════════════════════════════════════

host_untagged = [
    e for e in
    FilteredElementCollector(doc, active_view.Id)
        .OfCategory(BuiltInCategory.OST_StructuralFraming)
        .WhereElementIsNotElementType()
        .ToElements()
    if e.Id not in tagged_host_ids
]


# ══════════════════════════════════════════════════════════
# 3. COLLECT LINK StructuralFraming — filter untagged
# ══════════════════════════════════════════════════════════

# list of (elem, link_inst_id_int, link_title)
link_untagged = []

link_instances = list(
    FilteredElementCollector(doc, active_view.Id)
        .OfClass(RevitLinkInstance)
        .ToElements()
)

for link_inst in link_instances:
    try:
        link_doc = link_inst.GetLinkDocument()
        if link_doc is None:
            continue

        transform = link_inst.GetTotalTransform()

        try:
            outline   = get_view_outline_in_link_space(active_view, transform)
            bb_filter = BoundingBoxIntersectsFilter(outline)
            collector = (
                FilteredElementCollector(link_doc)
                    .OfCategory(BuiltInCategory.OST_StructuralFraming)
                    .WhereElementIsNotElementType()
                    .WherePasses(bb_filter)
            )
        except Exception:
            collector = (
                FilteredElementCollector(link_doc)
                    .OfCategory(BuiltInCategory.OST_StructuralFraming)
                    .WhereElementIsNotElementType()
            )

        link_inst_id_int = link_inst.Id.IntegerValue

        for b in collector.ToElements():
            key = (link_inst_id_int, b.Id.IntegerValue)
            if key not in tagged_link_keys:
                link_untagged.append((b, link_inst, link_doc.Title))

    except Exception:
        pass


# ══════════════════════════════════════════════════════════
# 4. SELECT untagged elements (host + links)
# ══════════════════════════════════════════════════════════

sel = uidoc.Selection

# Host — SetElementIds (полноценное выделение)
sel.SetElementIds(
    List[ElementId]([e.Id for e in host_untagged])
)

# Links — SetReferences (выделяет, но Properties покажет "from linked document")
if link_untagged:
    try:
        link_refs = [
            Reference(e).CreateLinkReference(link_inst)
            for e, link_inst, _ in link_untagged
        ]
        sel.SetReferences(List[Reference](link_refs))
    except Exception:
        pass


# ══════════════════════════════════════════════════════════
# 5. OUTPUT TABLE
# ══════════════════════════════════════════════════════════

total = len(host_untagged) + len(link_untagged)

output.print_md('# Untagged StructuralFraming — {}'.format(active_view.Name))
output.print_md('**{} element(s) without tags**'.format(total))

if total == 0:
    output.print_md('✅ All StructuralFraming elements have tags!')
else:
    rows = []

    for e in host_untagged:
        try:
            type_name = doc.GetElement(e.GetTypeId()).Name
        except Exception:
            type_name = '—'
        rows.append([
            output.linkify(e.Id),   # click → select & zoom
            'Host',
            type_name,
        ])

    for e, link_inst, link_title in link_untagged:
        try:
            type_name = e.Document.GetElement(e.GetTypeId()).Name
        except Exception:
            type_name = '—'
        rows.append([
            str(e.Id.IntegerValue),
            link_title,
            type_name,
        ])

    output.print_table(
        table_data=rows,
        columns=['ID', 'Source', 'Type'],
    )

    output.print_md('---')
    output.print_md('Host untagged: **{}** (selected in Revit)  |  Link untagged: **{}**'.format(
        len(host_untagged), len(link_untagged)
    ))
