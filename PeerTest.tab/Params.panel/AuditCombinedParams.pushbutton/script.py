# -*- coding: utf-8 -*-
"""Dump all Combined Parameters from every schedule in the active document.

Combined parameters are ScheduleFields with FieldType == CombinedParameter.
Each member references a parameter by ElementId, which differs between
projects. This script resolves IDs to name + GUID for cross-project comparison.

CSV columns:
    schedule_name   - ViewSchedule name
    combined_name   - column heading (= combined parameter display name)
    position        - 1-based member index
    member_id       - ElementId of the member ParameterElement in THIS doc
    member_name     - resolved parameter name
    member_guid     - GUID if shared, else empty
    prefix          - prefix string (e.g. "A=")
    suffix          - suffix string
    separator       - separator (e.g. ";")

Run on project A then B, compare by combined_name + position.
Same combined_name should have the same member_guid in both files.
"""

import os
import codecs
import csv
import datetime

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    ViewSchedule,
    SharedParameterElement,
    ParameterElement,
    ScheduleFieldType,
)
from pyrevit import revit, script, forms

doc = revit.doc
out = script.get_output()
out.close_others()

# ── id → (name, guid) lookup ────────────────────────────────────────────────
id_to_info = {}
for pe in FilteredElementCollector(doc).OfClass(ParameterElement):
    try:
        name = pe.GetDefinition().Name
    except Exception:
        name = '<unknown>'
    guid = ''
    if isinstance(pe, SharedParameterElement):
        try:
            guid = str(pe.GuidValue)
        except Exception:
            pass
    id_to_info[pe.Id.IntegerValue] = (name, guid)

# ── Collect combined parameter fields ───────────────────────────────────────
rows = []

for vs in FilteredElementCollector(doc).OfClass(ViewSchedule):
    sched_name = vs.Name
    sched_def = vs.Definition
    try:
        field_ids = sched_def.GetFieldOrder()
    except Exception:
        continue

    for fid in field_ids:
        try:
            field = sched_def.GetField(fid)
        except Exception:
            continue
        if field.FieldType != ScheduleFieldType.CombinedParameter:
            continue

        combined_name = field.ColumnHeading or '<no heading>'

        try:
            entries = list(field.GetCombinedParameters())
        except Exception:
            entries = []

        if not entries:
            rows.append({
                'schedule_name': sched_name,
                'combined_name': combined_name,
                'position': '',
                'member_id': '',
                'member_name': '<no entries>',
                'member_guid': '',
                'prefix': '',
                'suffix': '',
                'separator': '',
            })
            continue

        for pos, entry in enumerate(entries, start=1):
            mid_int = -1
            try:
                mid_int = entry.ParameterId.IntegerValue
            except Exception:
                pass
            member_name, member_guid = id_to_info.get(mid_int, ('<not found>', ''))

            prefix = suffix = separator = ''
            try:
                prefix = entry.Prefix or ''
            except Exception:
                pass
            try:
                suffix = entry.Suffix or ''
            except Exception:
                pass
            try:
                separator = entry.Separator or ''
            except Exception:
                pass

            rows.append({
                'schedule_name': sched_name,
                'combined_name': combined_name,
                'position': pos,
                'member_id': mid_int,
                'member_name': member_name,
                'member_guid': member_guid,
                'prefix': prefix,
                'suffix': suffix,
                'separator': separator,
            })

# ── Output ───────────────────────────────────────────────────────────────────
FIELDS = ['schedule_name', 'combined_name', 'position',
          'member_id', 'member_name', 'member_guid',
          'prefix', 'suffix', 'separator']

out.print_md('# Combined Parameters — `%s`' % doc.Title)

if not rows:
    out.print_md('**No combined parameter fields found.**')
    forms.alert('No combined parameters found.\n%s' % doc.Title,
                title='Audit Combined Parameters')
else:
    unique = set((r['schedule_name'], r['combined_name']) for r in rows)
    out.print_md('Found **%d** combined parameter(s) across **%d** schedule(s).' % (
        len(unique), len(set(r['schedule_name'] for r in rows))
    ))
    out.print_md('')
    out.print_md('| Schedule | Combined Name | # | member_name | member_guid | Prefix | Sep |')
    out.print_md('|---|---|---|---|---|---|---|')
    for r in rows:
        out.print_md('| %s | %s | %s | %s | `%s` | %s | %s |' % (
            r['schedule_name'], r['combined_name'], r['position'],
            r['member_name'], r['member_guid'], r['prefix'], r['separator']
        ))

    safe = ''.join(c if c.isalnum() or c in '-_.' else '_' for c in doc.Title)
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    out_path = os.path.join(os.environ.get('TEMP', '.'),
                            'combined_params_%s_%s.csv' % (safe, ts))
    with codecs.open(out_path, 'w', encoding='utf-8-sig') as fh:
        writer = csv.writer(fh)
        writer.writerow(FIELDS)
        for r in rows:
            writer.writerow([
                (r[k].encode('utf-8') if isinstance(r[k], unicode) else str(r[k]))
                for k in FIELDS
            ])

    out.print_md('')
    out.print_md('CSV: `%s`' % out_path)
    forms.alert('Found %d combined parameter(s).\nCSV:\n%s' % (len(unique), out_path),
                title='Audit Combined Parameters')
