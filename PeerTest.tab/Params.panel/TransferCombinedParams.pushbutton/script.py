# -*- coding: utf-8 -*-
"""Transfer Combined Parameters from a source document to the active document.

WHY THIS IS NEEDED
------------------
Combined parameters are ScheduleFields stored inside each ViewSchedule.
Each member of a combined parameter is referenced by its ElementId, which is
unique per document. The same shared parameter (same GUID) will have a
different ElementId in every project — so copying schedules or using Transfer
Project Standards does not fix them.

HOW IT WORKS
------------
1. You pick the SOURCE document (must already be open in Revit).
2. The script reads every combined parameter field from every schedule in
   the source, resolving each member's ElementId → SharedParameter GUID.
3. In the TARGET (active) document it finds the matching schedules by name,
   then the matching combined-parameter fields by column heading.
4. For each match it rebuilds the entry list using the target document's
   ElementIds (looked up by GUID) and calls SetCombinedParameters().

WHAT IS MATCHED
---------------
- Schedule: by exact Name
- Combined param field: by ColumnHeading (= the combined parameter name)
- Member parameter: by SharedParameter GUID

REPORT
------
Prints a per-field summary: updated / skipped (no matching schedule or field) /
errors. Opens a save dialog for a CSV log.
"""

import os
import codecs
import csv
import datetime

from System.Collections.Generic import List

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    ViewSchedule,
    SharedParameterElement,
    ParameterElement,
    ScheduleFieldType,
    Transaction,
    ElementId,
)
from pyrevit import revit, script, forms

doc = revit.doc  # target (active) document
out = script.get_output()
out.close_others()

# ── Pick source document ─────────────────────────────────────────────────────
all_docs = list(revit.uiapp.Application.Documents)
other_docs = [d for d in all_docs if d.PathName != doc.PathName and not d.IsFamilyDocument]

if not other_docs:
    forms.alert('No other project documents are open.\n'
                'Open the SOURCE document in Revit first, then run this script.',
                exitscript=True)


class _DocItem(object):
    def __init__(self, d):
        self.doc = d
        self.name = d.Title + ('  [%s]' % os.path.basename(d.PathName) if d.PathName else '')


items = [_DocItem(d) for d in other_docs]
selected = forms.SelectFromList.show(
    items,
    name_attr='name',
    title='SOURCE document — copy combined params FROM',
    multiselect=False,
)
if not selected:
    script.exit()

src_doc = selected.doc

# ── Helper: build id→(name,guid) lookup for a document ─────────────────────
def build_id_lookup(d):
    result = {}
    for pe in FilteredElementCollector(d).OfClass(ParameterElement):
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
        result[pe.Id.IntegerValue] = (name, guid)
    return result


def build_guid_lookup(d):
    """GUID → ElementId for shared parameters in document d."""
    result = {}
    for pe in FilteredElementCollector(d).OfClass(SharedParameterElement):
        try:
            guid = str(pe.GuidValue)
            result[guid] = pe.Id
        except Exception:
            pass
    return result


src_id_lookup = build_id_lookup(src_doc)
tgt_guid_to_id = build_guid_lookup(doc)

# ── Read combined params from source ────────────────────────────────────────
# Structure: {sched_name: {combined_name: [entry_dicts]}}
# entry_dict: {guid, name, prefix, suffix, separator, position}

src_data = {}  # sched_name → {combined_name → [entry_dicts]}

for vs in FilteredElementCollector(src_doc).OfClass(ViewSchedule):
    sname = vs.Name
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

        combined_name = field.ColumnHeading or ''
        try:
            entries = list(field.GetCombinedParameters())
        except Exception:
            continue

        entry_dicts = []
        for entry in entries:
            mid = -1
            try:
                mid = entry.ParameterId.IntegerValue
            except Exception:
                pass
            ename, eguid = src_id_lookup.get(mid, ('<not found>', ''))
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
            entry_dicts.append({
                'guid': eguid,
                'name': ename,
                'prefix': prefix,
                'suffix': suffix,
                'separator': separator,
            })

        if sname not in src_data:
            src_data[sname] = {}
        src_data[sname][combined_name] = entry_dicts

if not src_data:
    forms.alert('No combined parameter fields found in source document:\n%s' % src_doc.Title,
                exitscript=True)

total_combined = sum(len(v) for v in src_data.values())
out.print_md('# Transfer Combined Parameters')
out.print_md('- Source: **%s**' % src_doc.Title)
out.print_md('- Target: **%s**' % doc.Title)
out.print_md('- Combined params found in source: **%d** (across **%d** schedules)' % (
    total_combined, len(src_data)
))

# ── Build target schedule lookup ─────────────────────────────────────────────
tgt_schedules = {}  # name → ViewSchedule
for vs in FilteredElementCollector(doc).OfClass(ViewSchedule):
    tgt_schedules[vs.Name] = vs

# ── Try to get CombinedParameterData class for constructing new entries ──────
CombinedParameterData = None
try:
    from Autodesk.Revit.DB import CombinedParameterData as _CPD
    CombinedParameterData = _CPD
except ImportError:
    pass


def make_entry(existing_entry, new_param_id):
    """Clone an existing entry but with a new ParameterId."""
    if CombinedParameterData is not None:
        try:
            e = CombinedParameterData(new_param_id)
            try:
                e.Prefix = existing_entry['prefix']
            except Exception:
                pass
            try:
                e.Suffix = existing_entry['suffix']
            except Exception:
                pass
            try:
                e.Separator = existing_entry['separator']
            except Exception:
                pass
            return e
        except Exception:
            pass
    return None


# ── Apply to target ──────────────────────────────────────────────────────────
log_rows = []
updated = skipped_no_sched = skipped_no_field = skipped_bad_entries = errors = 0

t = Transaction(doc, 'Transfer Combined Parameters')
t.Start()

try:
    for sched_name, combined_dict in src_data.items():
        tgt_vs = tgt_schedules.get(sched_name)
        if tgt_vs is None:
            for cname in combined_dict:
                log_rows.append((sched_name, cname, 'SKIP — schedule not found in target'))
                skipped_no_sched += 1
            continue

        tgt_def = tgt_vs.Definition
        try:
            tgt_field_ids = list(tgt_def.GetFieldOrder())
        except Exception:
            for cname in combined_dict:
                log_rows.append((sched_name, cname, 'SKIP — cannot read target schedule fields'))
                skipped_no_field += 1
            continue

        # Build combined-name → field lookup in target schedule
        tgt_combined_fields = {}
        for fid in tgt_field_ids:
            try:
                f = tgt_def.GetField(fid)
                if f.FieldType == ScheduleFieldType.CombinedParameter:
                    tgt_combined_fields[f.ColumnHeading or ''] = f
            except Exception:
                pass

        for combined_name, entry_dicts in combined_dict.items():
            tgt_field = tgt_combined_fields.get(combined_name)
            if tgt_field is None:
                log_rows.append((sched_name, combined_name,
                                 'SKIP — combined field not found in target schedule'))
                skipped_no_field += 1
                continue

            # Build new entry list
            new_entries = []
            bad = False
            for ed in entry_dicts:
                guid = ed['guid']
                if not guid:
                    log_rows.append((sched_name, combined_name,
                                     'SKIP — member "%s" has no GUID (not a shared param)' % ed['name']))
                    bad = True
                    break
                new_id = tgt_guid_to_id.get(guid)
                if new_id is None:
                    log_rows.append((sched_name, combined_name,
                                     'SKIP — GUID %s (%s) not found in target doc' % (guid, ed['name'])))
                    bad = True
                    break
                entry_obj = make_entry(ed, new_id)
                if entry_obj is None:
                    log_rows.append((sched_name, combined_name,
                                     'ERROR — cannot construct CombinedParameterData for GUID %s' % guid))
                    bad = True
                    break
                new_entries.append(entry_obj)

            if bad:
                skipped_bad_entries += 1
                continue

            try:
                entry_list = List[CombinedParameterData](new_entries)
                tgt_field.SetCombinedParameters(entry_list)
                log_rows.append((sched_name, combined_name,
                                 'OK — %d members updated' % len(new_entries)))
                updated += 1
            except Exception as ex:
                log_rows.append((sched_name, combined_name, 'ERROR — %s' % ex))
                errors += 1

    t.Commit()

except Exception as ex:
    t.RollBack()
    forms.alert('Transaction failed: %s' % ex, exitscript=True)

# ── Report ───────────────────────────────────────────────────────────────────
out.print_md('')
out.print_md('## Results')
out.print_md('- Updated: **%d**' % updated)
out.print_md('- Skipped (no matching schedule): **%d**' % skipped_no_sched)
out.print_md('- Skipped (no matching field): **%d**' % skipped_no_field)
out.print_md('- Skipped (bad entries): **%d**' % skipped_bad_entries)
out.print_md('- Errors: **%d**' % errors)
out.print_md('')
out.print_md('| Schedule | Combined Name | Status |')
out.print_md('|---|---|---|')
for sname, cname, status in log_rows:
    out.print_md('| %s | %s | %s |' % (sname, cname, status))

# Save log CSV
safe = ''.join(c if c.isalnum() or c in '-_.' else '_' for c in doc.Title)
ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
log_path = os.path.join(os.environ.get('TEMP', '.'),
                        'transfer_combined_%s_%s.csv' % (safe, ts))
with codecs.open(log_path, 'w', encoding='utf-8-sig') as fh:
    writer = csv.writer(fh)
    writer.writerow(['schedule_name', 'combined_name', 'status'])
    for sname, cname, status in log_rows:
        writer.writerow([
            sname.encode('utf-8') if isinstance(sname, unicode) else sname,
            cname.encode('utf-8') if isinstance(cname, unicode) else cname,
            status.encode('utf-8') if isinstance(status, unicode) else status,
        ])

out.print_md('Log CSV: `%s`' % log_path)

forms.alert(
    'Done.\nUpdated: %d  |  Skipped: %d  |  Errors: %d\n\nLog: %s' % (
        updated, skipped_no_sched + skipped_no_field + skipped_bad_entries,
        errors, log_path),
    title='Transfer Combined Parameters'
)
