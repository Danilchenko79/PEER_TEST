# -*- coding: utf-8 -*-
"""For each ADSK_* / PR_* shared parameter in the project, show:

- GUID
- visible Name
- categories it is bound to
- whether it is the SAME parameter as another one (matching GUID)

Lets you see if `ADSK_Метка основы` and `PR_Host Mark` share a GUID
(then they're literally the same parameter, just renamed) or have
different GUIDs (then they're two separate parameters and the schedule
field is bound to the OLD one).
"""

from collections import defaultdict
from Autodesk.Revit.DB import (
    FilteredElementCollector,
    SharedParameterElement,
    InstanceBinding,
    TypeBinding,
)
from pyrevit import revit, script

doc = revit.doc
out = script.get_output()
out.close_others()

bm = doc.ParameterBindings

# Build (GUID -> [SharedParameterElement])
by_guid = defaultdict(list)
for sp in FilteredElementCollector(doc).OfClass(SharedParameterElement):
    by_guid[str(sp.GuidValue)].append(sp)


def cats_for(definition):
    """Return list of category names the definition is bound to in this project."""
    try:
        b = bm.get_Item(definition)
    except Exception:
        b = None
    if b is None:
        return ('<not bound>', '')
    kind = 'Instance' if isinstance(b, InstanceBinding) else (
        'Type' if isinstance(b, TypeBinding) else 'Other')
    cats = []
    try:
        for c in b.Categories:
            cats.append(c.Name)
    except Exception:
        pass
    return (kind, ', '.join(sorted(cats)))


out.print_md('# Shared Parameters in the project')
out.print_md('Total: **%d** parameters, **%d** unique GUIDs' %
             (sum(len(v) for v in by_guid.values()), len(by_guid)))

# Section 1: GUIDs that have more than one entry (= renamed but old still around?)
collisions = {g: lst for g, lst in by_guid.items() if len(lst) > 1}
if collisions:
    out.print_md('## ⚠ Same GUID — multiple SharedParameterElements')
    for g, lst in collisions.items():
        out.print_md('- **%s**' % g)
        for sp in lst:
            d = sp.GetDefinition()
            kind, cats = cats_for(d)
            out.print_md('   - `%s`  binding=%s  cats=[%s]' % (d.Name, kind, cats))
else:
    out.print_md('No GUID collisions.')

# Section 2: full table sorted by name
out.print_md('## All shared parameters (sorted)')
out.print_md('| Name | GUID | Binding | Categories |')
out.print_md('|---|---|---|---|')
flat = []
for g, lst in by_guid.items():
    for sp in lst:
        d = sp.GetDefinition()
        kind, cats = cats_for(d)
        flat.append((d.Name, g, kind, cats))
for name, g, kind, cats in sorted(flat, key=lambda x: x[0].lower()):
    out.print_md('| %s | `%s` | %s | %s |' % (name, g, kind, cats))

# Section 3: targeted ADSK_* vs PR_* pairs
out.print_md('## ADSK_* / PR_* lookups')
adsk = [(n, g, k, c) for n, g, k, c in flat if n.startswith('ADSK_')]
pr = [(n, g, k, c) for n, g, k, c in flat if n.startswith('PR_')]
out.print_md('- ADSK_*: **%d** | PR_*: **%d**' % (len(adsk), len(pr)))

pr_by_guid = {g: n for n, g, k, c in pr}
adsk_by_guid = {g: n for n, g, k, c in adsk}

shared_guids = set(pr_by_guid) & set(adsk_by_guid)
if shared_guids:
    out.print_md('### Same GUID under both ADSK_ and PR_ names')
    for g in shared_guids:
        out.print_md('- `%s` → ADSK=%s | PR=%s' %
                     (g, adsk_by_guid[g], pr_by_guid[g]))
else:
    out.print_md('### No shared GUIDs — ADSK_* and PR_* are different parameters.')

# Section 4: orphan ADSK_ params not bound to any category
out.print_md('## ADSK_* parameters that are NOT bound to any category (orphans)')
for n, g, k, c in adsk:
    if k == '<not bound>':
        out.print_md('- %s  `%s`' % (n, g))
