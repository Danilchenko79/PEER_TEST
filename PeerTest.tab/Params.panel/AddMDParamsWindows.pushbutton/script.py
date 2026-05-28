# -*- coding: utf-8 -*-
__title__  = 'Add MD Params\nto Windows'
__author__ = 'Dima'
__doc__    = '''Version = 1.0
Date      = 2026-05-26
Description:
    Adds the 4 MD_ shared parameters (group "Windows" from PR_FOPv4.txt)
    to project parameters as Instance binding for the Windows category.
    The script temporarily switches the active SPF to PR_FOPv4.txt,
    adds the parameters, then restores the original SPF.
How-To:
    1. Open any project.
    2. Run the script — no input required.
    3. Check Manage -> Project Parameters to verify.
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

SPF_PATH    = r'F:\P-O-S-T\DIMA.D\Revit\Tamplate\Shared Parameters\PR_FOPv4.txt'
GROUP_NAME  = 'Windows'
PARAM_PREFIX = 'MD_'

# ------------------------------------------------------------------
# 1. Sanity check
# ------------------------------------------------------------------
if doc.IsFamilyDocument:
    forms.alert('Run in a PROJECT document, not a family.',
                title='Wrong document type', exitscript=True)

import os
if not os.path.isfile(SPF_PATH):
    forms.alert(
        'Shared parameter file not found:\n{}'.format(SPF_PATH),
        title='File not found', exitscript=True
    )

# ------------------------------------------------------------------
# 2. Switch SPF, read parameters, restore
# ------------------------------------------------------------------
original_spf = app.SharedParametersFilename
try:
    app.SharedParametersFilename = SPF_PATH
    def_file = app.OpenSharedParameterFile()
    if def_file is None:
        forms.alert('Could not open:\n{}'.format(SPF_PATH),
                    title='SPF error', exitscript=True)

    # Find the "Windows" group
    target_group = None
    for grp in def_file.Groups:
        if grp.Name == GROUP_NAME:
            target_group = grp
            break

    if target_group is None:
        forms.alert(
            'Group "{}" not found in SPF.\n{}'.format(GROUP_NAME, SPF_PATH),
            title='Group not found', exitscript=True
        )

    # Collect MD_ definitions
    md_defs = [d for d in target_group.Definitions
               if d.Name.startswith(PARAM_PREFIX)]

    if not md_defs:
        forms.alert(
            'No parameters with prefix "{}" found in group "{}".'.format(
                PARAM_PREFIX, GROUP_NAME),
            title='Nothing to add', exitscript=True
        )

    # ------------------------------------------------------------------
    # 3. Get Windows category + CategorySet
    # ------------------------------------------------------------------
    windows_cat = doc.Settings.Categories.get_Item(BuiltInCategory.OST_Windows)
    if windows_cat is None:
        forms.alert('OST_Windows category not found in this document.',
                    title='Category error', exitscript=True)

    cat_set = app.Create.NewCategorySet()
    cat_set.Insert(windows_cat)

    # ------------------------------------------------------------------
    # 4. Add parameters in a transaction
    # ------------------------------------------------------------------
    results = []

    with Transaction(doc, 'Add MD_ Params to Windows') as t:
        t.Start()

        for ext_def in md_defs:
            existing = doc.ParameterBindings.get_Item(ext_def)
            if existing is not None:
                results.append([ext_def.Name, 'Already exists — skipped'])
                continue
            try:
                binding = app.Create.NewInstanceBinding(cat_set)
                ok = doc.ParameterBindings.Insert(
                    ext_def, binding, ext_def.ParameterGroup
                )
                if not ok:
                    ok = doc.ParameterBindings.ReInsert(
                        ext_def, binding, ext_def.ParameterGroup
                    )
                results.append([ext_def.Name, 'OK' if ok else 'Insert returned False'])
            except Exception as ex:
                results.append([ext_def.Name, 'Error: ' + str(ex)])

        t.Commit()

finally:
    # Always restore original SPF
    app.SharedParametersFilename = original_spf

# ------------------------------------------------------------------
# 5. Report
# ------------------------------------------------------------------
ok_count   = sum(1 for r in results if r[1] == 'OK')
skip_count = sum(1 for r in results if r[1].startswith('Already'))
err_count  = len(results) - ok_count - skip_count

output.print_md('## Add MD_ Parameters to Windows — Report')
output.print_md(
    '**SPF:** `{}`  |  **Group:** {}  |  **Binding:** Instance'.format(
        SPF_PATH, GROUP_NAME)
)
output.print_table(
    table_data=results,
    columns=['Parameter Name', 'Status']
)

if err_count == 0:
    forms.alert(
        '{} parameters added to Windows (Instance).\n'
        '{} already existed (skipped).'.format(ok_count, skip_count),
        title='Done'
    )
else:
    forms.alert(
        '{} added.\n{} already existed.\n{} errors.\n'
        'See the report for details.'.format(ok_count, skip_count, err_count),
        title='Partial Success'
    )
