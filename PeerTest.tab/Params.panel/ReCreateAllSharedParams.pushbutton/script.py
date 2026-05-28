# -*- coding: utf-8 -*-
__title__  = 'ReCreate\nAll Params'
__author__ = 'Dima'
__doc__    = '''Version = 1.0
Date      = 2026-04-27
Description:
    Recreates ALL shared parameters in the project from the currently
    attached Shared Parameter File (SPF), matching by GUID.
    Preserves: category bindings, Instance/Type kind, parameter group.
    Use as Step 3 of the "translate template to English" workflow.
How-To:
    1. Attach the new English SPF via Manage -> Shared Parameters.
    2. Run this script (make a backup of the template first!).
    3. Confirm the summary dialog.
    4. The script deletes every shared parameter and immediately
       re-inserts it from the SPF using the same GUID, categories and group.
    5. Check the report table for any GUID-not-found errors.
'''

import sys
from Autodesk.Revit.DB import (
    FilteredElementCollector, SharedParameterElement,
    InstanceBinding, TypeBinding, Transaction
)
from Autodesk.Revit.UI import *
from pyrevit import forms, script

doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
app   = __revit__.Application

output = script.get_output()
output.close_others()


# ------------------------------------------------------------------
# 1. Open attached SPF and build GUID -> ExternalDefinition index
# ------------------------------------------------------------------
def_file = app.OpenSharedParameterFile()
if def_file is None:
    forms.alert(
        'No Shared Parameter File is attached.\n'
        'Attach it via Manage -> Shared Parameters and run again.',
        title='SPF not found', exitscript=True
    )

spf_by_guid = {}
for grp in def_file.Groups:
    for d in grp.Definitions:
        guid_key = str(d.GUID)
        spf_by_guid[guid_key] = d


# ------------------------------------------------------------------
# 2. Collect all SharedParameterElement and read their bindings
# ------------------------------------------------------------------
shared_params = list(
    FilteredElementCollector(doc).OfClass(SharedParameterElement)
)

if not shared_params:
    forms.alert('No shared parameters found in the project.',
                title='Nothing to do', exitscript=True)

param_data   = []   # dicts with all info needed for re-insert
skipped_data = []   # params with no binding (project params without categories)

for sp in shared_params:
    ext_def  = sp.GetDefinition()
    guid_key = str(sp.GuidValue)
    old_name = ext_def.Name
    group    = ext_def.ParameterGroup

    binding = doc.ParameterBindings.get_Item(ext_def)
    if binding is None:
        skipped_data.append({'old_name': old_name, 'guid': guid_key,
                              'status': 'Skipped (no binding)'})
        continue

    is_instance = isinstance(binding, InstanceBinding)

    # Copy categories into a fresh CategorySet BEFORE deletion
    cat_set = app.Create.NewCategorySet()
    for c in binding.Categories:
        cat_set.Insert(c)

    param_data.append({
        'elem_id':     sp.Id,
        'guid':        guid_key,
        'old_name':    old_name,
        'group':       group,
        'is_instance': is_instance,
        'cat_set':     cat_set,
    })


# ------------------------------------------------------------------
# 3. Confirmation
# ------------------------------------------------------------------
summary_msg = (
    'Found {} shared parameters to recreate.\n'
    '{} skipped (no binding in project).\n\n'
    'The script will DELETE all shared parameters and immediately\n'
    're-INSERT them from the attached SPF using the same GUID.\n\n'
    'MAKE SURE YOU HAVE A BACKUP before continuing!\n\n'
    'Continue?'
).format(len(param_data), len(skipped_data))

answer = forms.alert(summary_msg, title='Recreate All Shared Parameters',
                     yes=True, no=True)
if not answer:
    sys.exit()


# ------------------------------------------------------------------
# 4. Single transaction: delete all → re-insert all
# ------------------------------------------------------------------
results = []   # list of dicts for report table

try:
    with Transaction(doc, 'Recreate All Shared Parameters') as t:
        t.Start()

        # --- Phase A: delete every collected shared parameter ----
        for item in param_data:
            try:
                doc.Delete(item['elem_id'])
            except Exception as ex:
                item['delete_error'] = str(ex)

        # --- Phase B: re-insert from SPF by GUID -----------------
        for item in param_data:
            if 'delete_error' in item:
                results.append([item['old_name'], '—', '—',
                                 'Delete failed: ' + item['delete_error']])
                continue

            guid_key = item['guid']

            # Find ExternalDefinition in SPF by GUID
            new_ext_def = spf_by_guid.get(guid_key, None)
            if new_ext_def is None:
                results.append([item['old_name'], '—', guid_key,
                                 'GUID not found in SPF'])
                continue

            new_name = new_ext_def.Name

            # Build binding of the same type with the saved CategorySet
            try:
                if item['is_instance']:
                    new_binding = app.Create.NewInstanceBinding(item['cat_set'])
                else:
                    new_binding = app.Create.NewTypeBinding(item['cat_set'])

                ok = doc.ParameterBindings.Insert(
                    new_ext_def, new_binding, item['group']
                )
                if not ok:
                    # May already be re-inserted; try ReInsert
                    ok = doc.ParameterBindings.ReInsert(
                        new_ext_def, new_binding, item['group']
                    )

                if ok:
                    binding_kind = 'Instance' if item['is_instance'] else 'Type'
                    results.append([item['old_name'], new_name, guid_key,
                                    'OK ({})'.format(binding_kind)])
                else:
                    results.append([item['old_name'], new_name, guid_key,
                                    'Insert returned False'])

            except Exception as ex:
                results.append([item['old_name'], new_ext_def.Name, guid_key,
                                 'Insert error: ' + str(ex)])

        t.Commit()

except Exception as top_ex:
    forms.alert(
        'Transaction failed — no changes were saved.\n\nError:\n{}'.format(str(top_ex)),
        title='Transaction Error', exitscript=True
    )


# ------------------------------------------------------------------
# 5. Report
# ------------------------------------------------------------------
# Add skipped params to results
for s in skipped_data:
    results.append([s['old_name'], '—', s['guid'], s['status']])

ok_count  = sum(1 for r in results if r[3].startswith('OK'))
err_count = len(results) - ok_count

output.print_md('## Recreate All Shared Parameters — Report')
output.print_md('**Processed:** {}  |  **OK:** {}  |  **Errors/Skipped:** {}'.format(
    len(results), ok_count, err_count
))

output.print_table(
    table_data=results,
    columns=['Old name', 'New name (from SPF)', 'GUID', 'Status']
)

if err_count == 0:
    forms.alert(
        'All {} shared parameters recreated successfully!'.format(ok_count),
        title='Done'
    )
else:
    forms.alert(
        '{} parameters recreated OK.\n{} errors or skipped.\nSee the report table for details.'.format(
            ok_count, err_count
        ),
        title='Partial Success'
    )
