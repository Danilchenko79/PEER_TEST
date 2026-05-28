# -*- coding: utf-8 -*-
__title__  = 'Add Shared\nParams: Win'
__author__ = 'Dima'
__doc__    = '''Version = 1.0
Date      = 2026-05-26
Description:
    Adds selected shared parameters as project parameters
    bound to the Windows category (OST_Windows).
    The parameter group is taken from the SPF definition.
How-To:
    1. Make sure the Shared Parameter File is attached
       (Manage -> Shared Parameters).
    2. Run the script.
    3. Select the parameters you want to add.
    4. Choose Instance or Type binding.
    5. The script adds them and shows the result.
'''

import sys
from Autodesk.Revit.DB import (
    BuiltInCategory, Transaction
)
from Autodesk.Revit.UI import *
from pyrevit import forms, script

doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
app   = __revit__.Application

output = script.get_output()
output.close_others()


# ------------------------------------------------------------------
# 1. Sanity check
# ------------------------------------------------------------------
if doc.IsFamilyDocument:
    forms.alert('Run in a PROJECT document, not a family.',
                title='Wrong document type', exitscript=True)


# ------------------------------------------------------------------
# 2. Open SPF and collect all definitions
# ------------------------------------------------------------------
def_file = app.OpenSharedParameterFile()
if def_file is None:
    forms.alert(
        'No Shared Parameter File is attached.\n'
        'Attach it via Manage -> Shared Parameters and run again.',
        title='SPF not found', exitscript=True
    )

# Build sorted list of (display_label, group_name, param_name, definition)
param_entries = []
for grp in def_file.Groups:
    for d in grp.Definitions:
        label = '[{}]  {}'.format(grp.Name, d.Name)
        param_entries.append((label, grp.Name, d.Name, d))

if not param_entries:
    forms.alert('The Shared Parameter File is empty.',
                title='No parameters', exitscript=True)

param_entries.sort(key=lambda x: x[0].lower())
display_labels = [e[0] for e in param_entries]


# ------------------------------------------------------------------
# 3. User selects parameters
# ------------------------------------------------------------------
selected_labels = forms.SelectFromList.show(
    display_labels,
    title='Select parameters to add to WINDOWS (OST_Windows)',
    multiselect=True,
    button_name='Add to Windows'
)

if not selected_labels:
    sys.exit()

label_set = set(selected_labels)
selected_entries = [e for e in param_entries if e[0] in label_set]


# ------------------------------------------------------------------
# 4. Instance or Type binding?
# ------------------------------------------------------------------
binding_choice = forms.CommandSwitchWindow.show(
    ['Instance (Экземпляр)', 'Type (Тип)'],
    message='Select binding type for all selected parameters:'
)

if not binding_choice:
    sys.exit()

use_instance = binding_choice.startswith('Instance')


# ------------------------------------------------------------------
# 5. Get Windows category and build CategorySet
# ------------------------------------------------------------------
windows_cat = doc.Settings.Categories.get_Item(BuiltInCategory.OST_Windows)
if windows_cat is None:
    forms.alert('Windows category (OST_Windows) not found in this document.',
                title='Category not found', exitscript=True)

cat_set = app.Create.NewCategorySet()
cat_set.Insert(windows_cat)


# ------------------------------------------------------------------
# 6. Add parameters in a single transaction
# ------------------------------------------------------------------
results = []

with Transaction(doc, 'Add Shared Params to Windows') as t:
    t.Start()

    for label, grp_name, param_name, ext_def in selected_entries:
        existing = doc.ParameterBindings.get_Item(ext_def)
        if existing is not None:
            results.append([param_name, grp_name, 'Already exists — skipped'])
            continue

        try:
            if use_instance:
                binding = app.Create.NewInstanceBinding(cat_set)
            else:
                binding = app.Create.NewTypeBinding(cat_set)

            ok = doc.ParameterBindings.Insert(ext_def, binding, ext_def.ParameterGroup)
            if not ok:
                ok = doc.ParameterBindings.ReInsert(ext_def, binding, ext_def.ParameterGroup)

            results.append([param_name, grp_name, 'OK' if ok else 'Insert returned False'])

        except Exception as ex:
            results.append([param_name, grp_name, 'Error: ' + str(ex)])

    t.Commit()


# ------------------------------------------------------------------
# 7. Report
# ------------------------------------------------------------------
ok_count   = sum(1 for r in results if r[2] == 'OK')
skip_count = sum(1 for r in results if r[2].startswith('Already'))
err_count  = len(results) - ok_count - skip_count

output.print_md('## Add Shared Parameters to Windows — Report')
output.print_md(
    '**Added:** {}  |  **Already existed:** {}  |  **Errors:** {}  |  '
    '**Binding:** {}'.format(
        ok_count, skip_count, err_count,
        'Instance' if use_instance else 'Type'
    )
)
output.print_table(
    table_data=results,
    columns=['Parameter Name', 'SPF Group', 'Status']
)

if err_count == 0:
    forms.alert(
        '{} parameters added to Windows.\n'
        '{} already existed (skipped).'.format(ok_count, skip_count),
        title='Done'
    )
else:
    forms.alert(
        '{} parameters added.\n{} already existed.\n{} errors.\n'
        'See the report table for details.'.format(ok_count, skip_count, err_count),
        title='Partial Success'
    )
