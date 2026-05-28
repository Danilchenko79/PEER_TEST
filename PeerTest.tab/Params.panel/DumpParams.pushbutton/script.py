# -*- coding: utf-8 -*-
"""Dump every parameter known to the active document to a CSV next to your
desktop / temp folder. Run on project A, then on project B, then diff/sort
the two files in Excel.

Columns:
    kind         shared / project / global
    guid         GUID for shared params, empty otherwise
    name         visible parameter name
    type_of      Text / Integer / Number / Length / Yes-No / ...
    binding      Instance / Type / -
    categories   semicolon-separated category names
    group        parameter group (Identity Data, Dimensions, ...)
    is_shared    True/False
    elem_id      ElementId of the SharedParameterElement / ParameterElement
"""

import os
import codecs
import csv
import datetime

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    SharedParameterElement,
    ParameterElement,
    GlobalParameter,
    InstanceBinding,
    TypeBinding,
)
from pyrevit import revit, script, forms

doc = revit.doc
out = script.get_output()
out.close_others()


def _spec_name(definition):
    """Friendly type/spec name across Revit versions."""
    try:
        spec_id = definition.GetDataType()
        try:
            from Autodesk.Revit.DB import SpecUtils, LabelUtils
            return LabelUtils.GetLabelForSpec(spec_id)
        except Exception:
            return str(spec_id.TypeId)
    except Exception:
        try:
            return str(definition.ParameterType)
        except Exception:
            return ''


def _group_name(definition):
    try:
        gid = definition.GetGroupTypeId()
        try:
            from Autodesk.Revit.DB import LabelUtils
            return LabelUtils.GetLabelForGroup(gid)
        except Exception:
            return str(gid.TypeId)
    except Exception:
        try:
            return str(definition.ParameterGroup)
        except Exception:
            return ''


bindings = doc.ParameterBindings


def _binding_for(definition):
    try:
        b = bindings.get_Item(definition)
    except Exception:
        b = None
    if b is None:
        return ('-', '')
    if isinstance(b, InstanceBinding):
        kind = 'Instance'
    elif isinstance(b, TypeBinding):
        kind = 'Type'
    else:
        kind = 'Other'
    cats = []
    try:
        for c in b.Categories:
            cats.append(c.Name)
    except Exception:
        pass
    return (kind, ';'.join(sorted(cats)))


rows = []  # list of dicts

# 1. Shared parameters
for sp in FilteredElementCollector(doc).OfClass(SharedParameterElement):
    d = sp.GetDefinition()
    kind, cats = _binding_for(d)
    rows.append({
        'kind': 'shared',
        'guid': str(sp.GuidValue),
        'name': d.Name,
        'type_of': _spec_name(d),
        'binding': kind,
        'categories': cats,
        'group': _group_name(d),
        'is_shared': 'True',
        'elem_id': sp.Id.IntegerValue,
    })

# 2. Project parameters (non-shared)
for pe in FilteredElementCollector(doc).OfClass(ParameterElement):
    if isinstance(pe, SharedParameterElement):
        continue
    try:
        d = pe.GetDefinition()
    except Exception:
        continue
    kind, cats = _binding_for(d)
    rows.append({
        'kind': 'project',
        'guid': '',
        'name': d.Name,
        'type_of': _spec_name(d),
        'binding': kind,
        'categories': cats,
        'group': _group_name(d),
        'is_shared': 'False',
        'elem_id': pe.Id.IntegerValue,
    })

# 3. Global parameters
for gp in FilteredElementCollector(doc).OfClass(GlobalParameter):
    try:
        d = gp.GetDefinition()
    except Exception:
        continue
    rows.append({
        'kind': 'global',
        'guid': '',
        'name': d.Name,
        'type_of': _spec_name(d),
        'binding': '-',
        'categories': '',
        'group': _group_name(d),
        'is_shared': 'False',
        'elem_id': gp.Id.IntegerValue,
    })


# Sort: shared by GUID, project by name, global last
def _sort_key(r):
    order = {'shared': 0, 'project': 1, 'global': 2}.get(r['kind'], 3)
    return (order, r['guid'] or '', r['name'].lower())


rows.sort(key=_sort_key)

# Output path: %TEMP%\<doc-title>__params.csv
safe_title = ''.join(c if c.isalnum() or c in '-_.' else '_' for c in doc.Title)
ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
out_path = os.path.join(
    os.environ.get('TEMP', '.'),
    'params_%s_%s.csv' % (safe_title, ts)
)

with codecs.open(out_path, 'w', encoding='utf-8-sig') as fh:
    writer = csv.writer(fh)
    writer.writerow(['kind', 'guid', 'name', 'type_of', 'binding',
                     'categories', 'group', 'is_shared', 'elem_id'])
    for r in rows:
        writer.writerow([
            (str(r[k])).encode('utf-8') if isinstance(r[k], unicode) else str(r[k])
            for k in ('kind', 'guid', 'name', 'type_of', 'binding',
                      'categories', 'group', 'is_shared', 'elem_id')
        ])

# Summary in pyRevit output
counts = {'shared': 0, 'project': 0, 'global': 0}
for r in rows:
    counts[r['kind']] = counts.get(r['kind'], 0) + 1

out.print_md('# Parameter dump — `%s`' % doc.Title)
out.print_md('- shared: **%d**' % counts.get('shared', 0))
out.print_md('- project (non-shared): **%d**' % counts.get('project', 0))
out.print_md('- global: **%d**' % counts.get('global', 0))
out.print_md('')
out.print_md('CSV: `%s`' % out_path)
out.print_md('')
out.print_md('### How to compare')
out.print_md('1. Run this on **document A** — gives `params_A_<timestamp>.csv`.')
out.print_md('2. Run this on **document B** — gives `params_B_<timestamp>.csv`.')
out.print_md('3. Open both in Excel, sort by **guid** (or by **name**).')
out.print_md('4. Differences:')
out.print_md('   - same `guid`, different `name` → renamed parameter (OK)')
out.print_md('   - same `guid`, different `binding` / `categories` → bind in target')
out.print_md('   - GUID present in A but not in B → missing in B; add via SPF')
out.print_md('   - row in B with empty `guid` and `kind=project` → local project parameter, will not auto-transfer')

forms.alert('Saved to:\n%s' % out_path, title='Parameter dump')
