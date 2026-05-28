# -*- coding: utf-8 -*-
__title__  = 'Check Beam\nTags'
__author__ = 'Dima'
__doc__    = '''Version = 2.0
Date      = 30.03.2026
Description: Checks if all beams on the active view have tags.
             Works with both host model and linked models.
             Highlights untagged beams and offers to add tags.
How-To:
    Open a plan/section/elevation view with beams and run the script.
    Untagged beams (host + links) will be listed and selected.
    You can choose to add tags automatically.
'''

import sys
from Autodesk.Revit.DB import *
from Autodesk.Revit.DB.Structure import StructuralType
from Autodesk.Revit.UI import *
from pyrevit import forms, script
from System.Collections.Generic import List

doc        = __revit__.ActiveUIDocument.Document
uidoc      = __revit__.ActiveUIDocument
app        = __revit__.Application
output     = script.get_output()
active_view = doc.ActiveView

# ─── 0. View type guard ───
ALLOWED_VIEW_TYPES = [
    ViewType.FloorPlan,
    ViewType.CeilingPlan,
    ViewType.Section,
    ViewType.Elevation,
    ViewType.EngineeringPlan,
]
if active_view.ViewType not in ALLOWED_VIEW_TYPES:
    forms.alert(
        'This script works only on Plan / Section / Elevation views.\n'
        'Current view type: {}'.format(active_view.ViewType),
        title='Check Beam Tags'
    )
    script.exit()


# ══════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════

def is_beam(elem):
    """Return True if element is a structural beam."""
    try:
        return elem.StructuralType == StructuralType.Beam
    except Exception:
        return False


def get_view_outline_in_link_space(view, link_transform):
    """
    Build an Outline (axis-aligned bounding box) in the link's local coordinate
    system that matches the visible region of the host view.
    Used to pre-filter link beams by spatial location.
    """
    crop_box  = view.CropBox
    box_t     = crop_box.Transform   # crop-box local → world
    mn, mx    = crop_box.Min, crop_box.Max

    # 8 corners of the crop box → world coordinates
    corners_world = [
        box_t.OfPoint(XYZ(x, y, z))
        for x in [mn.X, mx.X]
        for y in [mn.Y, mx.Y]
        for z in [mn.Z, mx.Z]
    ]

    # World → link-local
    inv = link_transform.Inverse
    corners_link = [inv.OfPoint(p) for p in corners_world]

    xs = [p.X for p in corners_link]
    ys = [p.Y for p in corners_link]
    zs = [p.Z for p in corners_link]

    # Expand Z so plan-view range (not reflected in crop box depth) is covered
    Z_EXPAND_FT = 50.0   # ~15 m — enough for any floor-to-floor height

    return Outline(
        XYZ(min(xs), min(ys), min(zs) - Z_EXPAND_FT),
        XYZ(max(xs), max(ys), max(zs) + Z_EXPAND_FT)
    )


def get_midpoint(elem):
    """Return midpoint XYZ of element location curve/point."""
    loc = elem.Location
    if isinstance(loc, LocationCurve):
        return loc.Curve.Evaluate(0.5, True)
    elif isinstance(loc, LocationPoint):
        return loc.Point
    return None


def offset_point(pt, index, view):
    """
    Offset tag placement point to reduce overlap.
    Alternates direction based on index.
    Offset is 0.3 m = ~1 ft in the view's up direction.
    """
    offset_ft = 0.3 / 0.3048  # 0.3 m in feet
    direction = 1 if index % 2 == 0 else -1
    try:
        up = view.UpDirection
        return XYZ(
            pt.X + up.X * offset_ft * direction,
            pt.Y + up.Y * offset_ft * direction,
            pt.Z + up.Z * offset_ft * direction
        )
    except Exception:
        return pt


# ══════════════════════════════════════════════════════════
# 1. COLLECT BEAMS — HOST MODEL
# ══════════════════════════════════════════════════════════

host_beams = [
    b for b in
    FilteredElementCollector(doc, active_view.Id)
        .OfCategory(BuiltInCategory.OST_StructuralFraming)
        .WhereElementIsNotElementType()
        .ToElements()
    if is_beam(b)
]

# Each entry: {'elem': Element, 'link_instance': None|RevitLinkInstance,
#              'link_doc': None|Document, 'ref': Reference}
all_beam_entries = []

for b in host_beams:
    all_beam_entries.append({
        'elem':          b,
        'link_instance': None,
        'link_doc':      None,
        'ref':           Reference(b),
        'label':         'Host',
    })

# ══════════════════════════════════════════════════════════
# 2. COLLECT BEAMS — LINKED MODELS
# ══════════════════════════════════════════════════════════

link_instances = FilteredElementCollector(doc, active_view.Id) \
    .OfClass(RevitLinkInstance) \
    .ToElements()

for link_inst in link_instances:
    try:
        link_doc = link_inst.GetLinkDocument()
        if link_doc is None:
            continue

        transform = link_inst.GetTotalTransform()

        # ── Filter link beams by view crop region ──────────────────────────
        # Build a bounding box in the link's local coordinate system that
        # matches what is visible on the active view, then pass it as a
        # spatial pre-filter so we only get beams actually shown on the view.
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
            # Fallback: no spatial filter (collects all beams from link)
            collector = (
                FilteredElementCollector(link_doc)
                    .OfCategory(BuiltInCategory.OST_StructuralFraming)
                    .WhereElementIsNotElementType()
            )

        link_beams = [b for b in collector.ToElements() if is_beam(b)]

        for b in link_beams:
            local_ref  = Reference(b)
            linked_ref = local_ref.CreateLinkReference(link_inst)

            all_beam_entries.append({
                'elem':          b,
                'link_instance': link_inst,
                'link_doc':      link_doc,
                'ref':           linked_ref,
                'label':         link_doc.Title,
                'transform':     transform,
            })
    except Exception as e:
        output.print_md('**Link error** ({}): {}'.format(link_inst.Id, str(e)))

if not all_beam_entries:
    forms.alert('No beams found on the active view (host + links).', title='Check Beam Tags')
    script.exit()

# ══════════════════════════════════════════════════════════
# 3. COLLECT EXISTING TAGS → find already-tagged beam IDs
# ══════════════════════════════════════════════════════════

all_tags = FilteredElementCollector(doc, active_view.Id) \
    .OfClass(IndependentTag) \
    .ToElements()

# tagged_local  — host element IntegerValue ids
# tagged_linked — (linkInstanceId, linkedElementId) tuples
tagged_local  = set()
tagged_linked = set()  # set of (link_inst_id_int, elem_id_int)

for tag in all_tags:
    try:
        # Revit 2022+ — local ids
        for eid in tag.GetTaggedLocalElementIds():
            tagged_local.add(eid.IntegerValue)
    except Exception:
        try:
            tagged_local.add(tag.TaggedLocalElementId.IntegerValue)
        except Exception:
            pass

    # Check linked reference
    try:
        tagged_elem_id = tag.TaggedElementId          # LinkElementId
        if tagged_elem_id is not None:
            li_id  = tagged_elem_id.LinkInstanceId
            el_id  = tagged_elem_id.LinkedElementId
            if li_id is not None and el_id is not None:
                tagged_linked.add((li_id.IntegerValue, el_id.IntegerValue))
    except Exception:
        pass


def is_tagged(entry):
    """Return True if beam entry already has a tag."""
    elem = entry['elem']
    li   = entry['link_instance']
    if li is None:
        return elem.Id.IntegerValue in tagged_local
    else:
        return (li.Id.IntegerValue, elem.Id.IntegerValue) in tagged_linked


# ══════════════════════════════════════════════════════════
# 4. FIND UNTAGGED BEAMS
# ══════════════════════════════════════════════════════════

untagged = [e for e in all_beam_entries if not is_tagged(e)]
total    = len(all_beam_entries)

if not untagged:
    forms.alert(
        'All {} beams on this view already have tags.'.format(total),
        title='Check Beam Tags'
    )
    script.exit()

# ══════════════════════════════════════════════════════════
# 5. HIGHLIGHT UNTAGGED HOST BEAMS + SHOW OUTPUT TABLE
# ══════════════════════════════════════════════════════════

host_untagged_ids = List[ElementId]([
    e['elem'].Id for e in untagged if e['link_instance'] is None
])
if host_untagged_ids.Count > 0:
    uidoc.Selection.SetElementIds(host_untagged_ids)

output.print_md('## Untagged Beams — {} / {}'.format(len(untagged), total))

table_data = []
for entry in untagged:
    elem  = entry['elem']
    label = entry['label']
    try:
        elem_type = doc.GetElement(elem.GetTypeId()) if entry['link_instance'] is None \
                    else entry['link_doc'].GetElement(elem.GetTypeId())
        type_name = Element.Name.GetValue(elem_type) if elem_type else '—'
    except Exception:
        type_name = '—'

    if entry['link_instance'] is None:
        id_cell = output.linkify(elem.Id)
    else:
        id_cell = str(elem.Id.IntegerValue)  # linked — can't linkify cross-doc

    table_data.append([id_cell, label, type_name])

output.print_table(
    table_data=table_data,
    columns=['Element ID', 'Source', 'Type Name']
)

# ══════════════════════════════════════════════════════════
# 6. ASK USER
# ══════════════════════════════════════════════════════════

link_count = sum(1 for e in untagged if e['link_instance'] is not None)
host_count = len(untagged) - link_count

msg_parts = [
    '{} out of {} beams have NO tags.'.format(len(untagged), total),
    '  Host model: {}'.format(host_count),
]
if link_count:
    msg_parts.append('  Linked models: {}'.format(link_count))
msg_parts += [
    '',
    'Host beams are now selected in the view.',
    '',
    'Do you want to add tags automatically?',
]

result = forms.alert('\n'.join(msg_parts), title='Check Beam Tags', yes=True, no=True)
if not result:
    script.exit()

# ══════════════════════════════════════════════════════════
# 7. PICK TAG TYPE
# ══════════════════════════════════════════════════════════

tag_types = FilteredElementCollector(doc) \
    .OfCategory(BuiltInCategory.OST_StructuralFramingTags) \
    .WhereElementIsElementType() \
    .ToElements()

if not tag_types:
    forms.alert(
        'No Structural Framing Tag types found in the project.\n'
        'Please load a tag family first.',
        title='Check Beam Tags'
    )
    script.exit()

tag_dict = {}
for tt in tag_types:
    family_name  = tt.FamilyName if tt.FamilyName else 'Unknown'
    type_name    = Element.Name.GetValue(tt) if Element.Name.GetValue(tt) else 'Unnamed'
    display_name = '{} : {}'.format(family_name, type_name)
    tag_dict[display_name] = tt

selected_name = forms.SelectFromList.show(
    sorted(tag_dict.keys()),
    title='Select Tag Type for Beams',
    button_name='Apply',
    multiselect=False
)
if not selected_name:
    script.exit()

selected_tag_type = tag_dict[selected_name]

# ══════════════════════════════════════════════════════════
# 8. PLACE TAGS
# ══════════════════════════════════════════════════════════

errors        = []
tagged_count  = 0

with Transaction(doc, 'Add Beam Tags') as t:
    t.Start()

    for idx, entry in enumerate(untagged):
        elem      = entry['elem']
        link_inst = entry['link_instance']
        ref       = entry['ref']

        try:
            # Get midpoint — for linked beams apply link transform
            mid = get_midpoint(elem)
            if mid is None:
                errors.append('{} ({}): unsupported location type'.format(
                    elem.Id.IntegerValue, entry['label']))
                continue

            if link_inst is not None:
                transform = entry.get('transform')
                if transform is not None:
                    mid = transform.OfPoint(mid)

            # Slight offset to avoid stacked tags
            tag_pt = offset_point(mid, idx, active_view)

            try:
                # Revit 2022+ API
                IndependentTag.Create(
                    doc,
                    selected_tag_type.Id,
                    active_view.Id,
                    ref,
                    False,
                    TagOrientation.Horizontal,
                    tag_pt
                )
            except Exception:
                # Revit 2018–2021 API (host elements only)
                new_tag = IndependentTag.Create(
                    doc,
                    active_view.Id,
                    ref,
                    False,
                    TagMode.TM_ADDBY_CATEGORY,
                    TagOrientation.Horizontal,
                    tag_pt
                )
                new_tag.ChangeTypeId(selected_tag_type.Id)

            tagged_count += 1

        except Exception as e:
            errors.append('{} ({}): {}'.format(
                elem.Id.IntegerValue, entry['label'], str(e)))

    t.Commit()

# ══════════════════════════════════════════════════════════
# 9. FINAL REPORT
# ══════════════════════════════════════════════════════════

msg = 'Tags added: {} / {}'.format(tagged_count, len(untagged))
if errors:
    msg += '\n\nWarnings ({}):\n'.format(len(errors))
    msg += '\n'.join(errors[:10])
    if len(errors) > 10:
        msg += '\n... and {} more'.format(len(errors) - 10)

forms.alert(msg, title='Check Beam Tags')
