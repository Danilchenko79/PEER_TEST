# -*- coding: utf-8 -*-
__title__  = 'Replace\nMaterial'
__author__ = 'Dima'
__doc__    = '''Version = 1.0
Date      = 2026-05-05
Description: Batch replace materials in element types (Floors, Walls, Beams,
             Columns, Foundations). Analyzes used materials, lets user pick
             a target material and source materials to replace.
How-To:
    1. Run script
    2. Select TARGET material (single)
    3. Select SOURCE materials to replace (multi)
    4. Select categories to process (multi)
    5. Done
'''

from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, BuiltInParameter,
    Transaction, ElementId, Material, HostObjAttributes,
    StorageType
)
from pyrevit import forms, script

doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
output = script.get_output()


# --- Categories we work with -------------------------------------------------
# Two groups: host types (with CompoundStructure) vs single-material types
HOST_CATS = {
    'Floors (Полы)':                    BuiltInCategory.OST_Floors,
    'Walls (Стены)':                    BuiltInCategory.OST_Walls,
    'Roofs (Крыши)':                    BuiltInCategory.OST_Roofs,
    'Foundations (Фундаменты)':         BuiltInCategory.OST_StructuralFoundation,
}

FAMILY_CATS = {
    'Structural Framing (Балки)':       BuiltInCategory.OST_StructuralFraming,
    'Structural Columns (Колонны)':     BuiltInCategory.OST_StructuralColumns,
    'Columns (Архитектурные колонны)':  BuiltInCategory.OST_Columns,
}

ALL_CATS = {}
ALL_CATS.update(HOST_CATS)
ALL_CATS.update(FAMILY_CATS)


# --- Helpers -----------------------------------------------------------------
def get_types_of_cat(bic):
    return list(FilteredElementCollector(doc)
                .OfCategory(bic)
                .WhereElementIsElementType()
                .ToElements())


def get_material_params(t):
    """Return ALL parameters of the type whose current value is a Material.
    Covers builtin Structural Material, GeneralMaterial, and any custom
    shared/project parameters that hold a material reference."""
    result = []
    for p in t.Parameters:
        if p is None or p.IsReadOnly:
            continue
        if p.StorageType != StorageType.ElementId:
            continue
        mid = p.AsElementId()
        if not mid or mid.IntegerValue <= 0:
            continue
        el = doc.GetElement(mid)
        if isinstance(el, Material):
            result.append(p)
    return result


def get_compound_structure(t):
    """Return CompoundStructure if the type is a HostObjAttributes (Wall/Floor/Roof/Foundation)."""
    if isinstance(t, HostObjAttributes):
        try:
            return t.GetCompoundStructure()
        except Exception:
            return None
    return None


def collect_used_materials():
    """Scan all types in our categories and collect material ids actually used."""
    used = {}  # mat_id_int -> Material
    type_index = []  # (type_elem, cat_label, is_host)

    for label, bic in ALL_CATS.items():
        is_host = label in HOST_CATS
        for t in get_types_of_cat(bic):
            type_index.append((t, label, is_host))

            # 1. ALL material-typed parameters of the type
            for p in get_material_params(t):
                mid = p.AsElementId()
                if mid and mid.IntegerValue > 0:
                    m = doc.GetElement(mid)
                    if isinstance(m, Material):
                        used[mid.IntegerValue] = m

            # 2. Compound structure layers
            cs = get_compound_structure(t)
            if cs is not None:
                for i in range(cs.LayerCount):
                    mid = cs.GetMaterialId(i)
                    if mid and mid.IntegerValue > 0:
                        m = doc.GetElement(mid)
                        if isinstance(m, Material):
                            used[mid.IntegerValue] = m

    return used, type_index


# --- Step 1: collect ---------------------------------------------------------
used_mats, type_index = collect_used_materials()

if not used_mats:
    forms.alert('No materials found in types of selected categories.',
                title='Nothing to do', exitscript=True)


# --- Step 2: pick TARGET material -------------------------------------------
mats_sorted = sorted(used_mats.values(), key=lambda m: m.Name)
mat_options = {m.Name: m for m in mats_sorted}

target_name = forms.SelectFromList.show(
    sorted(mat_options.keys()),
    title='Step 1/3: Select TARGET material (replace TO)',
    multiselect=False
)
if not target_name:
    script.exit()
target_mat = mat_options[target_name]
target_id  = target_mat.Id


# --- Step 3: pick SOURCE materials (multi) ----------------------------------
source_options = [n for n in sorted(mat_options.keys()) if n != target_name]
if not source_options:
    forms.alert('Only target material exists. Nothing to replace.',
                title='Nothing to do', exitscript=True)

source_names = forms.SelectFromList.show(
    source_options,
    title='Step 2/3: Select SOURCE materials (replace FROM) - multi',
    multiselect=True
)
if not source_names:
    script.exit()
source_ids = set(mat_options[n].Id.IntegerValue for n in source_names)


# --- Step 4: pick categories to process -------------------------------------
cat_choice = forms.SelectFromList.show(
    sorted(ALL_CATS.keys()),
    title='Step 3/3: Select categories to process - multi',
    multiselect=True
)
if not cat_choice:
    script.exit()
cat_choice = set(cat_choice)


# --- Step 5: replace --------------------------------------------------------
types_changed = 0
layers_changed = 0
params_changed = 0
errors = []
param_breakdown = {}  # param name -> count

with Transaction(doc, 'Replace Material in Types') as t:
    t.Start()

    for type_elem, label, is_host in type_index:
        if label not in cat_choice:
            continue

        type_was_changed = False

        # A. ALL Material-typed parameters of the type
        try:
            for p in get_material_params(type_elem):
                mid = p.AsElementId()
                if mid and mid.IntegerValue in source_ids:
                    pname = p.Definition.Name
                    p.Set(target_id)
                    params_changed += 1
                    param_breakdown[pname] = param_breakdown.get(pname, 0) + 1
                    type_was_changed = True
        except Exception as e:
            errors.append('{}: params: {}'.format(type_elem.Id, str(e)))

        # B. Compound structure layers
        if is_host:
            try:
                cs = get_compound_structure(type_elem)
                if cs is not None:
                    cs_dirty = False
                    for i in range(cs.LayerCount):
                        mid = cs.GetMaterialId(i)
                        if mid and mid.IntegerValue in source_ids:
                            cs.SetMaterialId(i, target_id)
                            layers_changed += 1
                            cs_dirty = True
                    if cs_dirty:
                        type_elem.SetCompoundStructure(cs)
                        type_was_changed = True
            except Exception as e:
                errors.append('{}: compound: {}'.format(type_elem.Id, str(e)))

        if type_was_changed:
            types_changed += 1

    t.Commit()


# --- Step 6: report ---------------------------------------------------------
output.print_md('# Material Replacement Report')
output.print_md('**Target material:** {}'.format(target_mat.Name))
output.print_md('**Replaced from:** {}'.format(', '.join(sorted(source_names))))
output.print_md('**Categories:** {}'.format(', '.join(sorted(cat_choice))))
output.print_md('---')
output.print_md('- Types changed: **{}**'.format(types_changed))
output.print_md('- Material parameters updated: **{}**'.format(params_changed))
output.print_md('- Compound structure layers updated: **{}**'.format(layers_changed))

if param_breakdown:
    output.print_md('### By parameter:')
    for pname in sorted(param_breakdown.keys()):
        output.print_md('- `{}`: {}'.format(pname, param_breakdown[pname]))

if errors:
    output.print_md('---')
    output.print_md('### Warnings ({}):'.format(len(errors)))
    for e in errors[:20]:
        output.print_md('- {}'.format(e))

forms.alert(
    'Done.\n\nTypes changed: {}\nMaterial params: {}\nCompound layers: {}'.format(
        types_changed, params_changed, layers_changed),
    title='Replace Material'
)
