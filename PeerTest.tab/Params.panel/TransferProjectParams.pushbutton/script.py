# -*- coding: utf-8 -*-
__title__  = 'Transfer\nProject Params'
__author__ = 'Dima'
__doc__    = '''Version = 1.0
Date      = 2026-04-28
Description:
    Reads ALL project parameters (SharedParameterElement with bindings)
    from a selected Russian source project (.rvt) and registers them
    in the CURRENT clean template using the ATTACHED new SPF (matched by GUID).

    Key guarantee:
    - Names come ONLY from the new SPF (the Russian ExternalDefinitions from
      the source project are never passed to the target template).
    - If a GUID is absent from the new SPF the parameter is SKIPPED
      (listed in the report as "GUID not found in SPF").

How-To:
    1. Open the CLEAN target template in Revit.
    2. Attach the new (English/renamed) SPF via Manage -> Shared Parameters.
    3. Run this script.
    4. Pick the Russian source .rvt file.
    5. Confirm the summary dialog.
    6. Check the report for any GUID-not-found warnings.
'''

import sys
import traceback
from Autodesk.Revit.DB import (
    FilteredElementCollector, SharedParameterElement,
    InstanceBinding, TypeBinding,
    OpenOptions, ModelPathUtils,
    DetachFromCentralOption,
    WorksetConfiguration, WorksetConfigurationOption,
    Transaction
)
from Autodesk.Revit.UI import *
from pyrevit import forms, script

doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
app   = __revit__.Application

output = script.get_output()
output.close_others()


# ------------------------------------------------------------------
# 0. Sanity checks
# ------------------------------------------------------------------
if doc.IsFamilyDocument:
    forms.alert('Run this script in a PROJECT or TEMPLATE document, not in a family.',
                title='Wrong document type', exitscript=True)


# ------------------------------------------------------------------
# 1. Build SPF index from the ATTACHED new SPF (GUID -> ExternalDefinition)
# ------------------------------------------------------------------
def_file = app.OpenSharedParameterFile()
if def_file is None:
    forms.alert(
        'No Shared Parameter File is attached to the current document.\n\n'
        'Attach the new SPF via Manage -> Shared Parameters and run again.',
        title='SPF not found', exitscript=True
    )

spf_by_guid = {}
for grp in def_file.Groups:
    for d in grp.Definitions:
        spf_by_guid[str(d.GUID)] = d

if not spf_by_guid:
    forms.alert('The attached SPF has no definitions. Check the file.',
                title='Empty SPF', exitscript=True)


# ------------------------------------------------------------------
# 2. Pick source Russian project (.rvt)
# ------------------------------------------------------------------
src_path = forms.pick_file(
    file_ext='rvt',
    title='Select the source Russian project (.rvt)'
)
if not src_path:
    sys.exit()


# ------------------------------------------------------------------
# 3. Open source document (Detach, close worksets silently)
# ------------------------------------------------------------------
src_doc = None
try:
    mp = ModelPathUtils.ConvertUserVisiblePathToModelPath(src_path)

    open_opts = OpenOptions()
    open_opts.DetachFromCentralOption = DetachFromCentralOption.DetachAndPreserveWorksets
    open_opts.Audit = False

    # Open all worksets closed to speed things up — we only need parameter metadata
    wc = WorksetConfiguration(WorksetConfigurationOption.CloseAllWorksets)
    open_opts.SetOpenWorksetsConfiguration(wc)

    src_doc = app.OpenDocumentFile(mp, open_opts)

except Exception as ex:
    forms.alert(
        'Could not open the source file:\n{}\n\nError:\n{}'.format(src_path, str(ex)),
        title='Open error', exitscript=True
    )


# ------------------------------------------------------------------
# 4. Collect parameter metadata from source (primitives only — no
#    ExternalDefinition objects cross the document boundary)
# ------------------------------------------------------------------
agg = {}
# agg[guid_str] = {
#   'old_name_ru': str,
#   'group':       BuiltInParameterGroup,
#   'is_instance': bool,
#   'bic_ints':    list[int],   # Category.Id.IntegerValue
# }

scan_errors = []

try:
    shared_params = list(
        FilteredElementCollector(src_doc).OfClass(SharedParameterElement)
    )

    for sp in shared_params:
        try:
            ext_def  = sp.GetDefinition()
            guid_str = str(sp.GuidValue)

            binding = src_doc.ParameterBindings.get_Item(ext_def)
            if binding is None:
                # Not a project parameter (no category binding) — skip
                continue

            is_instance = isinstance(binding, InstanceBinding)
            group       = ext_def.ParameterGroup
            old_name_ru = ext_def.Name   # stored as plain string, never inserted

            bic_ints = [c.Id.IntegerValue for c in binding.Categories]

            agg[guid_str] = {
                'old_name_ru': old_name_ru,
                'group':       group,
                'is_instance': is_instance,
                'bic_ints':    bic_ints,
            }

        except Exception as ex:
            scan_errors.append('GUID {}: {}'.format(
                getattr(sp, 'GuidValue', '?'), str(ex)
            ))

finally:
    # Always close the source — no changes saved
    if src_doc is not None:
        try:
            src_doc.Close(False)
        except Exception:
            pass


# ------------------------------------------------------------------
# 5. Confirmation
# ------------------------------------------------------------------
if not agg:
    msg = 'No project parameters with category bindings found in the source file.'
    if scan_errors:
        msg += '\n\nScan errors:\n' + '\n'.join(scan_errors[:10])
    forms.alert(msg, title='Nothing to transfer', exitscript=True)

confirm = forms.alert(
    'Source: {}\n\n'
    'Found {} project parameters to transfer.\n'
    '{} scan errors.\n\n'
    'Names will be taken from the ATTACHED new SPF (by GUID).\n'
    'Russian names from the source project will NOT appear in the template.\n\n'
    'Register these parameters in the current template?'.format(
        src_path, len(agg), len(scan_errors)
    ),
    title='Transfer Project Parameters',
    yes=True, no=True
)
if not confirm:
    sys.exit()


# ------------------------------------------------------------------
# 6. Build category lookup for the TARGET template
# ------------------------------------------------------------------
proj_cat_by_intid = {}
for c in doc.Settings.Categories:
    try:
        if c.AllowsBoundParameters:
            proj_cat_by_intid[c.Id.IntegerValue] = c
    except Exception:
        pass


# ------------------------------------------------------------------
# 7. Insert bindings in the TARGET template (single transaction)
# ------------------------------------------------------------------
report_rows = []
# columns: Old name (RU) | New name (SPF) | GUID | Group | Kind | Categories | Status

try:
    with Transaction(doc, 'Transfer Project Parameters') as t:
        t.Start()

        for guid_str, rec in agg.items():

            # Look up ExternalDefinition in the NEW SPF — this is the ONLY
            # definition that will be passed to ParameterBindings.Insert.
            new_ext_def = spf_by_guid.get(guid_str)
            if new_ext_def is None:
                report_rows.append([
                    rec['old_name_ru'], '—', guid_str,
                    str(rec['group']),
                    'Instance' if rec['is_instance'] else 'Type',
                    str(len(rec['bic_ints'])),
                    'GUID not found in SPF'
                ])
                continue

            # Build CategorySet from saved int ids mapped to target doc categories
            cat_set     = app.Create.NewCategorySet()
            cats_added  = 0
            cats_missed = 0
            for bic_int in rec['bic_ints']:
                cat = proj_cat_by_intid.get(bic_int)
                if cat is None:
                    cats_missed += 1
                    continue
                try:
                    cat_set.Insert(cat)
                    cats_added += 1
                except Exception:
                    cats_missed += 1

            if cats_added == 0:
                report_rows.append([
                    rec['old_name_ru'], new_ext_def.Name, guid_str,
                    str(rec['group']),
                    'Instance' if rec['is_instance'] else 'Type',
                    '0',
                    'No usable categories (all {} missed)'.format(len(rec['bic_ints']))
                ])
                continue

            # Create binding of the matching type
            try:
                if rec['is_instance']:
                    new_binding = app.Create.NewInstanceBinding(cat_set)
                else:
                    new_binding = app.Create.NewTypeBinding(cat_set)

                ok = doc.ParameterBindings.Insert(new_ext_def, new_binding, rec['group'])
                if not ok:
                    ok = doc.ParameterBindings.ReInsert(new_ext_def, new_binding, rec['group'])

                cat_str = '{} cats'.format(cats_added)
                if cats_missed:
                    cat_str += ' ({} skipped)'.format(cats_missed)

                status = 'OK' if ok else 'Insert returned False'
                report_rows.append([
                    rec['old_name_ru'], new_ext_def.Name, guid_str,
                    str(rec['group']),
                    'Instance' if rec['is_instance'] else 'Type',
                    cat_str,
                    status
                ])

            except Exception as ex:
                report_rows.append([
                    rec['old_name_ru'], new_ext_def.Name, guid_str,
                    str(rec['group']),
                    'Instance' if rec['is_instance'] else 'Type',
                    str(cats_added),
                    'Insert error: ' + str(ex)
                ])

        t.Commit()

except Exception as top_ex:
    forms.alert(
        'Transaction failed — no changes were saved.\n\nError:\n{}'.format(str(top_ex)),
        title='Transaction Error', exitscript=True
    )


# ------------------------------------------------------------------
# 8. Report
# ------------------------------------------------------------------
if scan_errors:
    for e in scan_errors:
        report_rows.append(['—', '—', '—', '—', '—', '—', 'Scan error: ' + e])

ok_count  = sum(1 for r in report_rows if r[6].startswith('OK'))
err_count = len(report_rows) - ok_count

output.print_md('## Transfer Project Parameters — Report')
output.print_md(
    '**Source:** `{}`  \n'
    '**Transferred OK:** {}  |  **Errors / Skipped:** {}'.format(
        src_path, ok_count, err_count
    )
)

output.print_table(
    table_data=report_rows,
    columns=['Old name (RU)', 'New name (SPF)', 'GUID', 'Group', 'Kind', 'Categories', 'Status']
)

if err_count == 0:
    forms.alert(
        'All {} project parameters transferred successfully!\n\n'
        'All names come from the new SPF — no Russian names in the template.'.format(ok_count),
        title='Done'
    )
else:
    forms.alert(
        '{} parameters transferred OK.\n'
        '{} errors or skipped — see the report table for details.'.format(ok_count, err_count),
        title='Partial Success'
    )
