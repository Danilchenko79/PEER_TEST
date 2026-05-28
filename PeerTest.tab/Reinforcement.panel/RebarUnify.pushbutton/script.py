# -*- coding: utf-8 -*-
__title__  = 'Унификация\nАрматуры'
__author__ = 'Dima'
__doc__    = '''Version = 2.0
Date      = 2026-05-28
Description: Двухступенчатая унификация арматуры.
   Шаг 1: выбор формы из таблицы со сводкой
   Шаг 2: таблица параметров (A, B) для выбранной формы + детекция перевёртышей
   Действия: Выделить в Revit, Унифицировать (PR_A или PR_B), Поменять A↔B.
How-To:
   1. Запустите кнопку — откроется окно
   2. Сверху выберите ОДНУ форму → внизу появится таблица её вариантов
   3. Оранжевые строки = перевёртыши (A↔B), жёлтые = одиночные
   4. Выделите строки (Ctrl/Shift) и нажмите нужное действие
'''

import clr
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')
clr.AddReference('System.Data')

import System
from System.Data import DataTable
from System.Windows import Window, MessageBox, MessageBoxButton, MessageBoxResult
from System.Windows.Markup import XamlReader
from System.Collections.Generic import List

from Autodesk.Revit.DB import FilteredElementCollector, Transaction, ElementId
from Autodesk.Revit.DB.Structure import Rebar
from pyrevit import forms

uiapp = __revit__
uidoc = uiapp.ActiveUIDocument
doc   = uidoc.Document

FEET_TO_MM = 304.8
SWAP_TOL   = 30.0  # mm tolerance for approximate swap detection


# ============================================================
# Data collection
# ============================================================

def get_param(elem, name, ptype='string'):
    try:
        p = elem.LookupParameter(name)
        if p is None:
            return None
        if ptype == 'string':
            return p.AsString() or p.AsValueString() or ''
        elif ptype == 'double':
            return p.AsDouble()
        elif ptype == 'int':
            return p.AsInteger()
    except Exception:
        return None


def collect_all(rvt_doc):
    """Collect rebar grouped by (shape, diam, A, B).
       Also build shape summary and swap-candidate set."""
    collector = FilteredElementCollector(rvt_doc).OfClass(Rebar).ToElements()
    groups = {}
    for rb in collector:
        try:
            shape_num = get_param(rb, 'PR_Rebar Shape', 'int') or 0
            diam_ft   = get_param(rb, 'Bar Diameter', 'double') or 0.0
            diam_mm   = int(round(diam_ft * FEET_TO_MM))
            a_mm      = round((get_param(rb, 'PR_A', 'double') or 0.0) * FEET_TO_MM, 1)
            b_mm      = round((get_param(rb, 'PR_B', 'double') or 0.0) * FEET_TO_MM, 1)
            pos       = get_param(rb, 'PR_Position', 'string') or ''
            key = (shape_num, diam_mm, a_mm, b_mm)
            if key not in groups:
                groups[key] = {'count': 0, 'positions': set(), 'ids': []}
            groups[key]['count'] += 1
            if pos:
                groups[key]['positions'].add(pos)
            groups[key]['ids'].append(rb.Id.IntegerValue)
        except Exception:
            continue

    # Approximate swap detection: pair (a1,b1) and (a2,b2) are swap candidates
    # if |a1-b2| < SWAP_TOL and |b1-a2| < SWAP_TOL AND they have different
    # orientation (i.e. not just exact duplicates).
    swap_keys = set()
    klist = [k for k in groups.keys() if not (k[2] == 0 and k[3] == 0)]
    for i in range(len(klist)):
        sh1, d1, a1, b1 = klist[i]
        if a1 == 0 or b1 == 0:
            continue
        for j in range(i + 1, len(klist)):
            sh2, d2, a2, b2 = klist[j]
            if sh1 != sh2 or d1 != d2:
                continue
            if a2 == 0 or b2 == 0:
                continue
            if abs(a1 - b2) <= SWAP_TOL and abs(b1 - a2) <= SWAP_TOL:
                if abs(a1 - a2) > SWAP_TOL or abs(b1 - b2) > SWAP_TOL:
                    swap_keys.add(klist[i])
                    swap_keys.add(klist[j])

    # Shape summary
    shapes_summary = {}
    for k in groups.keys():
        sh = k[0]
        if sh not in shapes_summary:
            shapes_summary[sh] = {'count': 0, 'variants': 0, 'swap': 0}
        shapes_summary[sh]['count']    += groups[k]['count']
        shapes_summary[sh]['variants'] += 1
        if k in swap_keys:
            shapes_summary[sh]['swap'] += 1

    return groups, shapes_summary, swap_keys


def build_shape_dt(shapes_summary):
    dt = DataTable()
    dt.Columns.Add('Форма',     System.Int32)
    dt.Columns.Add('Элементов', System.Int32)
    dt.Columns.Add('Вариантов', System.Int32)
    dt.Columns.Add('Swap',      System.Int32)
    dt.Columns.Add('HasSwap',   System.Boolean)
    for sh in sorted(shapes_summary.keys()):
        s = shapes_summary[sh]
        row = dt.NewRow()
        row['Форма']     = sh
        row['Элементов'] = s['count']
        row['Вариантов'] = s['variants']
        row['Swap']      = s['swap']
        row['HasSwap']   = bool(s['swap'] > 0)
        dt.Rows.Add(row)
    return dt


def build_param_dt(groups, swap_keys, shape, f_diam='Все', f_pos='', only_swap=False):
    dt = DataTable()
    dt.Columns.Add('Диам',     System.Int32)
    dt.Columns.Add('A',        System.Double)
    dt.Columns.Add('B',        System.Double)
    dt.Columns.Add('Сумма',    System.Double)
    dt.Columns.Add('Кол-во',   System.Int32)
    dt.Columns.Add('Позиции',  System.String)
    dt.Columns.Add('IsUnique', System.Boolean)
    dt.Columns.Add('IsSwap',   System.Boolean)

    f_diam_str = '' if f_diam is None else str(f_diam).strip()
    f_pos_str  = '' if f_pos  is None else str(f_pos).strip()

    for key in sorted(groups.keys()):
        sh, diam, a, b = key
        if sh != shape:
            continue
        if f_diam_str and f_diam_str != 'Все':
            if str(diam) != f_diam_str:
                continue
        g = groups[key]
        if f_pos_str:
            if not any(f_pos_str in p for p in g['positions']):
                continue
        is_swap = key in swap_keys
        if only_swap and not is_swap:
            continue

        pos_list = sorted(g['positions'])
        pos_str  = ', '.join(pos_list[:6])
        if len(g['positions']) > 6:
            pos_str += '...'

        row = dt.NewRow()
        row['Диам']     = diam
        row['A']        = float(a)
        row['B']        = float(b)
        row['Сумма']    = float(a + b)
        row['Кол-во']   = g['count']
        row['Позиции']  = pos_str
        row['IsUnique'] = bool(g['count'] == 1)
        row['IsSwap']   = bool(is_swap)
        dt.Rows.Add(row)
    return dt


# ============================================================
# XAML
# ============================================================

XAML_STR = '''<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Унификация арматуры" Width="980" Height="820"
    WindowStartupLocation="CenterScreen">
    <Grid Margin="10">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>   <!-- title -->
            <RowDefinition Height="Auto"/>   <!-- Step 1 label -->
            <RowDefinition Height="180"/>    <!-- shapes table -->
            <RowDefinition Height="Auto"/>   <!-- Step 2 label + filters -->
            <RowDefinition Height="*"/>      <!-- params table -->
            <RowDefinition Height="Auto"/>   <!-- unify panel -->
            <RowDefinition Height="Auto"/>   <!-- action buttons -->
        </Grid.RowDefinitions>

        <TextBlock Grid.Row="0" Text="Унификация арматуры" FontSize="16" FontWeight="Bold" Margin="0,0,0,6"/>

        <!-- ============ STEP 1: shape selection ============ -->
        <DockPanel Grid.Row="1" Margin="0,0,0,4">
            <TextBlock Text="ШАГ 1: Выберите форму" FontWeight="SemiBold" Foreground="#1565C0"/>
            <TextBlock x:Name="lblShapeHelp" Text="" Margin="14,0,0,0" Foreground="#666666" FontStyle="Italic"/>
        </DockPanel>

        <DataGrid Grid.Row="2" x:Name="dgShapes"
                  AutoGenerateColumns="False"
                  SelectionMode="Single"
                  IsReadOnly="True"
                  CanUserSortColumns="True"
                  GridLinesVisibility="Horizontal"
                  HeadersVisibility="Column"
                  FontSize="13"
                  Margin="0,0,0,8">
            <DataGrid.RowStyle>
                <Style TargetType="DataGridRow">
                    <Style.Triggers>
                        <DataTrigger Binding="{Binding [HasSwap]}" Value="True">
                            <Setter Property="Background" Value="#FFE0B2"/>
                        </DataTrigger>
                    </Style.Triggers>
                </Style>
            </DataGrid.RowStyle>
            <DataGrid.Columns>
                <DataGridTextColumn Header="Форма"            Binding="{Binding [Форма]}"     Width="80"/>
                <DataGridTextColumn Header="Элементов всего"  Binding="{Binding [Элементов]}" Width="140"/>
                <DataGridTextColumn Header="Уник. вариантов"  Binding="{Binding [Вариантов]}" Width="140"/>
                <DataGridTextColumn Header="Перевёрнутых"     Binding="{Binding [Swap]}"      Width="120"/>
            </DataGrid.Columns>
        </DataGrid>

        <!-- ============ STEP 2: params filters ============ -->
        <Border Grid.Row="3" BorderBrush="#CCCCCC" BorderThickness="1" CornerRadius="3"
                Padding="8,6" Margin="0,0,0,4">
            <DockPanel>
                <TextBlock DockPanel.Dock="Left" Text="ШАГ 2:" FontWeight="SemiBold"
                           Foreground="#1565C0" VerticalAlignment="Center" Margin="0,0,12,0"/>
                <WrapPanel>
                    <Label Content="Диам, мм:" VerticalAlignment="Center"/>
                    <ComboBox x:Name="cbDiam" Width="70" Margin="4,0,12,0" VerticalAlignment="Center"/>
                    <Label Content="Позиция:" VerticalAlignment="Center"/>
                    <TextBox x:Name="tbPos" Width="70" Margin="4,0,12,0" VerticalAlignment="Center" Height="22"/>
                    <CheckBox x:Name="cbSwapOnly" Content="Только перевёрнутые"
                              VerticalAlignment="Center" Margin="0,0,12,0"/>
                    <Button x:Name="btnFilter" Content="Применить" Padding="10,3" Margin="0,0,6,0"/>
                    <Button x:Name="btnReset"  Content="Сброс"     Padding="10,3"/>
                </WrapPanel>
            </DockPanel>
        </Border>

        <DataGrid Grid.Row="4" x:Name="dgParams"
                  AutoGenerateColumns="False"
                  SelectionMode="Extended"
                  IsReadOnly="True"
                  CanUserSortColumns="True"
                  CanUserResizeColumns="True"
                  GridLinesVisibility="Horizontal"
                  HeadersVisibility="Column"
                  FontSize="13"
                  Margin="0,0,0,6">
            <DataGrid.RowStyle>
                <Style TargetType="DataGridRow">
                    <Style.Triggers>
                        <DataTrigger Binding="{Binding [IsSwap]}" Value="True">
                            <Setter Property="Background" Value="#FFCC80"/>
                            <Setter Property="ToolTip"    Value="Перевёртыш: есть пара с переставленными A и B"/>
                        </DataTrigger>
                        <DataTrigger Binding="{Binding [IsUnique]}" Value="True">
                            <Setter Property="Background" Value="#FFFDE7"/>
                        </DataTrigger>
                    </Style.Triggers>
                </Style>
            </DataGrid.RowStyle>
            <DataGrid.Columns>
                <DataGridTextColumn Header="Диам, мм" Binding="{Binding [Диам]}"  Width="80"/>
                <DataGridTextColumn Header="A, мм"    Binding="{Binding [A], StringFormat=F1}"     Width="90"/>
                <DataGridTextColumn Header="B, мм"    Binding="{Binding [B], StringFormat=F1}"     Width="90"/>
                <DataGridTextColumn Header="A+B, мм" Binding="{Binding [Сумма], StringFormat=F1}"  Width="90"/>
                <DataGridTextColumn Header="Кол-во"  Binding="{Binding [Кол-во]}"                  Width="70"/>
                <DataGridTextColumn Header="Позиции" Binding="{Binding [Позиции]}"                 Width="*"/>
            </DataGrid.Columns>
        </DataGrid>

        <!-- ============ Unify controls ============ -->
        <Border Grid.Row="5" BorderBrush="#CCCCCC" BorderThickness="1" CornerRadius="3" Padding="10,6" Margin="0,0,0,6">
            <StackPanel Orientation="Horizontal" VerticalAlignment="Center">
                <Label x:Name="lblSel" Content="Выбрано: 0 строк (0 элементов)" FontWeight="SemiBold" Margin="0,0,16,0"/>
                <Label Content="Параметр:" Margin="0,0,4,0"/>
                <ComboBox x:Name="cbParam" Width="65" Margin="0,0,12,0">
                    <ComboBoxItem Content="PR_A" IsSelected="True"/>
                    <ComboBoxItem Content="PR_B"/>
                </ComboBox>
                <Label Content="Значение (мм):" Margin="0,0,4,0"/>
                <TextBox x:Name="tbValue" Width="85" Height="22"/>
            </StackPanel>
        </Border>

        <!-- ============ Action buttons ============ -->
        <DockPanel Grid.Row="6">
            <Button x:Name="btnClose"  DockPanel.Dock="Right" Content="Закрыть"            Padding="10,5" Margin="6,0,0,0"/>
            <Button x:Name="btnUnify"  DockPanel.Dock="Right" Content="Унифицировать"      Padding="10,5" Margin="6,0,0,0"
                    Background="#1565C0" Foreground="White" FontWeight="Bold"/>
            <Button x:Name="btnSelect" DockPanel.Dock="Right" Content="Выделить и закрыть" Padding="10,5" Margin="6,0,0,0"/>
            <Button x:Name="btnSwap"   DockPanel.Dock="Right" Content="Поменять A↔B"       Padding="10,5" Margin="6,0,0,0"
                    Background="#F57C00" Foreground="White"/>
            <Button x:Name="btnReload" DockPanel.Dock="Left"  Content="Перечитать модель"  Padding="10,5"/>
        </DockPanel>
    </Grid>
</Window>'''


# ============================================================
# Main window
# ============================================================

class RebarWindow(object):

    def __init__(self):
        self.groups, self.shapes_summary, self.swap_keys = collect_all(doc)
        self.current_shape = None

        self.window = XamlReader.Parse(XAML_STR)

        self.dg_shapes  = self.window.FindName('dgShapes')
        self.dg_params  = self.window.FindName('dgParams')
        self.lbl_help   = self.window.FindName('lblShapeHelp')
        self.cb_diam    = self.window.FindName('cbDiam')
        self.tb_pos     = self.window.FindName('tbPos')
        self.cb_swap    = self.window.FindName('cbSwapOnly')
        self.btn_filter = self.window.FindName('btnFilter')
        self.btn_reset  = self.window.FindName('btnReset')
        self.lbl_sel    = self.window.FindName('lblSel')
        self.cb_param   = self.window.FindName('cbParam')
        self.tb_value   = self.window.FindName('tbValue')
        self.btn_swap   = self.window.FindName('btnSwap')
        self.btn_select = self.window.FindName('btnSelect')
        self.btn_unify  = self.window.FindName('btnUnify')
        self.btn_reload = self.window.FindName('btnReload')
        self.btn_close  = self.window.FindName('btnClose')

        # Fill shapes table
        self._refresh_shapes()
        self._fill_diam_combo()

        # Empty params table initially
        self.dg_params.ItemsSource = build_param_dt(
            self.groups, self.swap_keys, -1).DefaultView

        # Wire events
        self.dg_shapes.SelectionChanged += self._safe(self._on_shape_selected)
        self.dg_params.SelectionChanged += self._safe(self._on_params_selected)
        self.btn_filter.Click += self._safe(self._on_filter)
        self.btn_reset.Click  += self._safe(self._on_reset)
        self.btn_select.Click += self._safe(self._on_select)
        self.btn_unify.Click  += self._safe(self._on_unify)
        self.btn_swap.Click   += self._safe(self._on_swap)
        self.btn_reload.Click += self._safe(self._on_reload)
        self.btn_close.Click  += self._safe(self._on_close)

        # Auto-select first shape for convenience
        if self.dg_shapes.Items.Count > 0:
            self.dg_shapes.SelectedIndex = 0

        # MODAL — selection and transactions work synchronously
        self.window.ShowDialog()

    # ---------------- safety ----------------
    def _safe(self, fn):
        def wrapper(sender, args):
            try:
                fn(sender, args)
            except Exception as ex:
                import traceback
                try:
                    MessageBox.Show('Ошибка:\n{}\n\n{}'.format(
                        str(ex), traceback.format_exc()),
                        'Ошибка', MessageBoxButton.OK)
                except Exception:
                    pass
        return wrapper

    # ---------------- robust row read ----------------
    def _row_get(self, row, col_name, col_index):
        for fn in (lambda: row[col_name],
                   lambda: row.Row[col_name],
                   lambda: row[col_index]):
            try:
                v = fn()
                if v is not None:
                    return v
            except Exception:
                pass
        return None

    # ---------------- shapes table ----------------
    def _refresh_shapes(self):
        dt = build_shape_dt(self.shapes_summary)
        self.dg_shapes.ItemsSource = dt.DefaultView
        total = sum(s['count'] for s in self.shapes_summary.values())
        total_swap = sum(s['swap'] for s in self.shapes_summary.values())
        # lbl_help is a TextBlock -> use .Text, not .Content
        self.lbl_help.Text = 'Всего: {} элементов, {} форм. Перевёртышей: {}'.format(
            total, len(self.shapes_summary), total_swap)

    def _on_shape_selected(self, sender, args):
        if self.dg_shapes.SelectedItem is None:
            return
        row = self.dg_shapes.SelectedItem
        sh = self._row_get(row, 'Форма', 0)
        if sh is None:
            return
        self.current_shape = int(sh)
        self._fill_diam_combo()
        self._refresh_params()

    # ---------------- diam combo ----------------
    def _fill_diam_combo(self):
        self.cb_diam.Items.Clear()
        self.cb_diam.Items.Add('Все')
        diams = sorted(set(k[1] for k in self.groups.keys()
                       if self.current_shape is None or k[0] == self.current_shape))
        for d in diams:
            self.cb_diam.Items.Add(str(d))
        self.cb_diam.SelectedIndex = 0

    # ---------------- params table ----------------
    def _refresh_params(self):
        if self.current_shape is None:
            return
        f_diam = str(self.cb_diam.SelectedItem or 'Все')
        f_pos  = self.tb_pos.Text or ''
        only_swap = bool(self.cb_swap.IsChecked)
        dt = build_param_dt(self.groups, self.swap_keys,
                            self.current_shape, f_diam, f_pos, only_swap)
        self.dg_params.ItemsSource = dt.DefaultView
        self._update_sel_label()

    def _on_filter(self, sender, args):
        self._refresh_params()

    def _on_reset(self, sender, args):
        self.cb_diam.SelectedIndex = 0
        self.tb_pos.Text = ''
        self.cb_swap.IsChecked = False
        self._refresh_params()

    def _on_params_selected(self, sender, args):
        self._update_sel_label()

    def _update_sel_label(self):
        rows = list(self.dg_params.SelectedItems)
        n_rows = len(rows)
        n_elems = 0
        for row in rows:
            v = self._row_get(row, 'Кол-во', 4)
            try:
                if v is not None:
                    n_elems += int(v)
            except Exception:
                pass
        self.lbl_sel.Content = 'Выбрано: {} строк ({} элементов)'.format(n_rows, n_elems)

    # ---------------- get selected keys / ids ----------------
    def _selected_keys(self):
        """Return list of (shape, diam, a, b) keys for selected rows."""
        keys = []
        if self.current_shape is None:
            return keys
        for row in self.dg_params.SelectedItems:
            try:
                d = self._row_get(row, 'Диам', 0)
                a = self._row_get(row, 'A',    1)
                b = self._row_get(row, 'B',    2)
                if None in (d, a, b):
                    continue
                d = int(d); a = float(a); b = float(b)
                # exact match
                key = (self.current_shape, d, round(a, 1), round(b, 1))
                if key in self.groups:
                    keys.append(key)
                    continue
                # fuzzy match
                for k in self.groups.keys():
                    if (k[0] == self.current_shape and k[1] == d
                            and abs(k[2] - a) < 0.05
                            and abs(k[3] - b) < 0.05):
                        keys.append(k)
                        break
            except Exception:
                pass
        return keys

    def _selected_ids(self):
        ids = []
        for k in self._selected_keys():
            ids.extend(self.groups[k]['ids'])
        return ids

    # ---------------- actions ----------------
    def _on_select(self, sender, args):
        ids = self._selected_ids()
        if not ids:
            MessageBox.Show('Выделите строки в нижней таблице.',
                            'Выделение', MessageBoxButton.OK)
            return
        id_list = List[ElementId]([ElementId(i) for i in ids])
        uidoc.Selection.SetElementIds(id_list)
        try:
            uidoc.ShowElements(id_list)
        except Exception:
            pass
        self.window.Close()

    def _on_unify(self, sender, args):
        keys = self._selected_keys()
        ids  = []
        for k in keys:
            ids.extend(self.groups[k]['ids'])
        if not ids:
            MessageBox.Show('Выделите строки в нижней таблице.',
                            'Унификация', MessageBoxButton.OK)
            return

        sel = self.cb_param.SelectedItem
        if sel is None:
            MessageBox.Show('Выберите параметр.', 'Ошибка', MessageBoxButton.OK)
            return
        try:
            pname = str(sel.Content)
        except Exception:
            pname = 'PR_A'

        raw = (self.tb_value.Text or '').strip().replace(',', '.')
        if not raw:
            MessageBox.Show('Введите значение в мм.', 'Ошибка', MessageBoxButton.OK)
            return
        try:
            tgt_mm = float(raw)
        except Exception:
            MessageBox.Show('Не разобрать число: "{}"'.format(raw),
                            'Ошибка', MessageBoxButton.OK)
            return

        confirm = MessageBox.Show(
            'Изменить {} = {:.1f} мм для {} элементов?'.format(pname, tgt_mm, len(ids)),
            'Подтверждение', MessageBoxButton.OKCancel)
        if confirm != MessageBoxResult.OK:
            return

        tgt_ft = tgt_mm / FEET_TO_MM
        changed, errors = self._apply_set(ids, pname, tgt_ft)

        self._reload_and_refresh()
        msg = 'Изменено: {} элементов'.format(changed)
        if errors:
            msg += '\nОшибок: {}\n\n{}'.format(len(errors), '\n'.join(errors[:5]))
        MessageBox.Show(msg, 'Готово', MessageBoxButton.OK)

    def _on_swap(self, sender, args):
        """For each selected rebar, swap PR_A and PR_B values."""
        keys = self._selected_keys()
        ids  = []
        for k in keys:
            ids.extend(self.groups[k]['ids'])
        if not ids:
            MessageBox.Show('Выделите строки в нижней таблице.',
                            'A↔B', MessageBoxButton.OK)
            return

        confirm = MessageBox.Show(
            'Поменять местами PR_A ↔ PR_B для {} элементов?'.format(len(ids)),
            'Подтверждение', MessageBoxButton.OKCancel)
        if confirm != MessageBoxResult.OK:
            return

        changed, errors = self._apply_swap(ids)
        self._reload_and_refresh()
        msg = 'Поменяно A↔B: {} элементов'.format(changed)
        if errors:
            msg += '\nОшибок: {}\n\n{}'.format(len(errors), '\n'.join(errors[:5]))
        MessageBox.Show(msg, 'Готово', MessageBoxButton.OK)

    def _on_reload(self, sender, args):
        self._reload_and_refresh()

    def _on_close(self, sender, args):
        self.window.Close()

    # ---------------- transaction helpers ----------------
    def _apply_set(self, ids, param_name, value_ft):
        changed = 0
        errors = []
        t = Transaction(doc, 'Унификация {}'.format(param_name))
        t.Start()
        try:
            for eid in ids:
                try:
                    el = doc.GetElement(ElementId(eid))
                    if el is None:
                        continue
                    p = el.LookupParameter(param_name)
                    if p is not None and not p.IsReadOnly:
                        p.Set(value_ft)
                        changed += 1
                    else:
                        errors.append('ID {}: {} недоступен'.format(eid, param_name))
                except Exception as ex:
                    errors.append('ID {}: {}'.format(eid, str(ex)))
            t.Commit()
        except Exception as ex:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
            errors.append('Transaction: {}'.format(str(ex)))
        return changed, errors

    def _apply_swap(self, ids):
        changed = 0
        errors = []
        t = Transaction(doc, 'Swap PR_A <-> PR_B')
        t.Start()
        try:
            for eid in ids:
                try:
                    el = doc.GetElement(ElementId(eid))
                    if el is None:
                        continue
                    pA = el.LookupParameter('PR_A')
                    pB = el.LookupParameter('PR_B')
                    if (pA is None or pB is None
                            or pA.IsReadOnly or pB.IsReadOnly):
                        errors.append('ID {}: PR_A или PR_B недоступен'.format(eid))
                        continue
                    a = pA.AsDouble()
                    b = pB.AsDouble()
                    pA.Set(b)
                    pB.Set(a)
                    changed += 1
                except Exception as ex:
                    errors.append('ID {}: {}'.format(eid, str(ex)))
            t.Commit()
        except Exception as ex:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
            errors.append('Transaction: {}'.format(str(ex)))
        return changed, errors

    # ---------------- refresh after edit ----------------
    def _reload_and_refresh(self):
        prev_shape = self.current_shape
        self.groups, self.shapes_summary, self.swap_keys = collect_all(doc)
        self._refresh_shapes()
        # Restore previously selected shape
        if prev_shape is not None:
            for i in range(self.dg_shapes.Items.Count):
                row = self.dg_shapes.Items[i]
                sh = self._row_get(row, 'Форма', 0)
                if sh is not None and int(sh) == prev_shape:
                    self.dg_shapes.SelectedIndex = i
                    break
        else:
            self._refresh_params()


# ============================================================
# Entry point
# ============================================================
try:
    RebarWindow()
except Exception as ex:
    import traceback
    try:
        forms.alert('Ошибка запуска:\n{}\n\n{}'.format(str(ex), traceback.format_exc()),
                    title='RebarUnify')
    except Exception:
        pass
