# -*- coding: utf-8 -*-
"""Copy ALL filters (with overrides + visibility + enabled state) from one
View Template to another, in the same project.

Pick SOURCE template, then TARGET template. Existing filters in TARGET that
share the same id are overwritten; everything else in TARGET is left alone.
"""

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    View,
    Transaction,
)
from pyrevit import revit, forms, script

doc = revit.doc
out = script.get_output()
out.close_others()

# Collect all view templates
templates = [v for v in FilteredElementCollector(doc).OfClass(View)
             if v.IsTemplate]

if len(templates) < 2:
    forms.alert('Need at least 2 view templates in the project.', exitscript=True)


class _Opt(forms.TemplateListItem):
    @property
    def name(self):
        return self.item.Name


src = forms.SelectFromList.show(
    sorted(templates, key=lambda v: v.Name),
    name_attr='Name',
    title='SOURCE — copy filters FROM',
    multiselect=False,
)
if not src:
    script.exit()

remaining = [v for v in templates if v.Id != src.Id]
tgt = forms.SelectFromList.show(
    sorted(remaining, key=lambda v: v.Name),
    name_attr='Name',
    title='TARGET — paste filters INTO',
    multiselect=False,
)
if not tgt:
    script.exit()

src_filter_ids = list(src.GetFilters())
if not src_filter_ids:
    forms.alert('Source template "%s" has no filters.' % src.Name, exitscript=True)

# Confirm
ans = forms.alert(
    'Copy %d filter(s) from\n  %s\nto\n  %s ?\n\n'
    'Existing filters with the same id in the target will be overwritten.'
    % (len(src_filter_ids), src.Name, tgt.Name),
    options=['Yes', 'No'])
if ans != 'Yes':
    script.exit()

copied, overwritten, skipped = 0, 0, 0
errors = []

t = Transaction(doc, 'Copy view-template filters')
t.Start()
try:
    existing_target = set(int(fid.IntegerValue) for fid in tgt.GetFilters())
    for fid in src_filter_ids:
        try:
            overrides = src.GetFilterOverrides(fid)
            visible = src.GetFilterVisibility(fid)
            try:
                enabled = src.GetIsFilterEnabled(fid)
            except Exception:
                enabled = True

            if int(fid.IntegerValue) in existing_target:
                tgt.SetFilterOverrides(fid, overrides)
                tgt.SetFilterVisibility(fid, visible)
                try:
                    tgt.SetIsFilterEnabled(fid, enabled)
                except Exception:
                    pass
                overwritten += 1
            else:
                tgt.AddFilter(fid)
                tgt.SetFilterOverrides(fid, overrides)
                tgt.SetFilterVisibility(fid, visible)
                try:
                    tgt.SetIsFilterEnabled(fid, enabled)
                except Exception:
                    pass
                copied += 1
        except Exception as ex:
            skipped += 1
            felem = doc.GetElement(fid)
            fname = felem.Name if felem is not None else '<id %s>' % fid
            errors.append('%s — %s' % (fname, ex))
    t.Commit()
except Exception as ex:
    t.RollBack()
    forms.alert('Failed: %s' % ex, exitscript=True)

out.print_md('# Copy filters: done')
out.print_md('- source: **%s**' % src.Name)
out.print_md('- target: **%s**' % tgt.Name)
out.print_md('- added: **%d**' % copied)
out.print_md('- overwritten in target: **%d**' % overwritten)
out.print_md('- skipped (errors): **%d**' % skipped)
if errors:
    out.print_md('## Errors')
    for e in errors:
        out.print_md('- %s' % e)
