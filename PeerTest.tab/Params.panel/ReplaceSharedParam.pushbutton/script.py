# -*- coding: utf-8 -*-
__title__  = 'Replace\nShared Param'
__author__ = 'Dima'
__doc__    = '''Version = 1.0
Date      = 2026-04-27
Description:
    Replaces a selected shared parameter in the project with another one
    from the currently attached Shared Parameter File (SPF), preserving
    category bindings, binding type (Instance/Type) and parameter group.
How-To:
    1. Make sure the correct SPF is attached (Manage -> Shared Parameters).
    2. Run the script.
    3. Pick the shared parameter to replace.
    4. Type the exact English name of the new parameter from the SPF.
'''

from Autodesk.Revit.DB import (
    FilteredElementCollector, SharedParameterElement, Transaction,
    InstanceBinding, TypeBinding, CategorySet
)
from Autodesk.Revit.UI import *
from pyrevit import forms, script

doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
app   = __revit__.Application

output = script.get_output()


# ------------------------------------------------------------------
# 1. Collect all SharedParameterElement in the project
# ------------------------------------------------------------------
shared_params = list(
    FilteredElementCollector(doc).OfClass(SharedParameterElement)
)

if not shared_params:
    forms.alert('No shared parameters found in the project.',
                title='Replace Shared Parameter', exitscript=True)


# Wrap each SharedParameterElement so SelectFromList shows its name
class SPWrap(object):
    def __init__(self, sp):
        self.sp = sp
        self.definition = sp.GetDefinition()
        self.name = self.definition.Name

    def __str__(self):
        return self.name


wrapped = sorted([SPWrap(sp) for sp in shared_params], key=lambda x: x.name.lower())

selected = forms.SelectFromList.show(
    wrapped,
    title='Select shared parameter to REPLACE',
    name_attr='name',
    multiselect=False,
    button_name='Replace this parameter'
)

if not selected:
    script.exit()

old_sp_elem = selected.sp
old_def     = selected.definition
old_name    = selected.name


# ------------------------------------------------------------------
# 2. Ask user for the new parameter name (must exist in attached SPF)
# ------------------------------------------------------------------
new_name = forms.ask_for_string(
    default='',
    prompt='Введите новое английское имя параметра (как в ФОП):',
    title='New parameter name'
)

if not new_name:
    script.exit()

new_name = new_name.strip()


# ------------------------------------------------------------------
# 3. Open currently attached SPF and find the ExternalDefinition
# ------------------------------------------------------------------
def_file = app.OpenSharedParameterFile()
if def_file is None:
    forms.alert('No Shared Parameter File is currently attached.\n'
                'Set one in Manage -> Shared Parameters.',
                title='SPF not found', exitscript=True)

new_ext_def = None
for grp in def_file.Groups:
    for d in grp.Definitions:
        if d.Name == new_name:
            new_ext_def = d
            break
    if new_ext_def is not None:
        break

if new_ext_def is None:
    forms.alert('Parameter "{}" not found in the attached SPF.\n'
                'Check spelling and the active SPF.'.format(new_name),
                title='Not found in SPF', exitscript=True)


# ------------------------------------------------------------------
# 4. Read the current binding of the OLD parameter
# ------------------------------------------------------------------
bindings = doc.ParameterBindings
old_binding = bindings.get_Item(old_def)

if old_binding is None:
    forms.alert('The selected parameter has no binding in this project.\n'
                'Nothing to transfer.',
                title='No binding', exitscript=True)

# Determine binding type
is_instance = isinstance(old_binding, InstanceBinding)

# Copy categories into a fresh CategorySet (so we can survive Delete)
old_cats = old_binding.Categories
cat_set = app.Create.NewCategorySet()
for c in old_cats:
    cat_set.Insert(c)

# Parameter group is stored on the Definition
old_group = old_def.ParameterGroup


# ------------------------------------------------------------------
# 5. Replace inside one transaction
# ------------------------------------------------------------------
try:
    with Transaction(doc, 'Replace shared parameter') as t:
        t.Start()

        # Delete the old SharedParameterElement (this also drops the binding)
        doc.Delete(old_sp_elem.Id)

        # Build a new binding of the same type with the same categories
        if is_instance:
            new_binding = app.Create.NewInstanceBinding(cat_set)
        else:
            new_binding = app.Create.NewTypeBinding(cat_set)

        # Insert the new parameter into the project with the same group
        ok = doc.ParameterBindings.Insert(new_ext_def, new_binding, old_group)
        if not ok:
            # Fallback: try ReInsert in case the parameter is already present
            ok = doc.ParameterBindings.ReInsert(new_ext_def, new_binding, old_group)

        if not ok:
            t.RollBack()
            forms.alert(
                'Failed to insert parameter "{}" into project bindings.'.format(new_name),
                title='Insert failed', exitscript=True
            )

        t.Commit()

except Exception as ex:
    forms.alert('Error during replacement:\n{}'.format(str(ex)),
                title='Error', exitscript=True)


# ------------------------------------------------------------------
# 6. Report
# ------------------------------------------------------------------
binding_kind = 'Instance' if is_instance else 'Type'
cat_names = sorted([c.Name for c in cat_set])

output.print_md('### Shared parameter replaced')
output.print_md('- **Old:** `{}`'.format(old_name))
output.print_md('- **New:** `{}`'.format(new_name))
output.print_md('- **Binding:** {}'.format(binding_kind))
output.print_md('- **Group:** {}'.format(str(old_group)))
output.print_md('- **Categories ({}):** {}'.format(len(cat_names), ', '.join(cat_names)))

forms.alert(
    'Replaced "{}" -> "{}".\n\nBinding: {}\nCategories: {}'.format(
        old_name, new_name, binding_kind, len(cat_names)
    ),
    title='Done'
)
