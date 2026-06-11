# -*- coding: utf-8 -*-
__title__  = 'Унификация\nАрматуры'
__author__ = 'Dima'
__doc__    = '''Version = 1.0
Date      = 2026-05-28
Description: Анализ и унификация арматуры (Rebar) по параметрам PR_A и PR_B.
How-To:
    1. Запустите кнопку — откроется таблица всей арматуры проекта
    2. Жёлтые строки — одиночные элементы (поставлены по геометрии)
    3. Выберите строки (Ctrl/Shift для множественного выбора)
    4. Выберите параметр (PR_A или PR_B) и введите целевое значение в мм
    5. "Унифицировать" — изменяет параметр у выбранных элементов
    6. "Выделить в Revit" — выделяет элементы в модели без изменений
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
from pyrevit import forms, script

doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

FEET_TO_MM = 304.8

XAML_STR = '''<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Унификация арматуры" Width="950" Height="740"
    WindowStartupLocation="CenterScreen">
    <Grid Margin="10">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <!-- Filter bar -->
        <Border Grid.Row="0" BorderBrush="#CCCCCC" BorderThickness="1"
                CornerRadius="3" Padding="8,6" Margin="0,0,0,6">
            <WrapPanel>
                <Label Content="Форма:" VerticalAlignment="Center"/>
                <ComboBox x:Name="cbShape" Width="65" Margin="4,0,10,0" VerticalAlignment="Center"/>
                <Label Content="Диам, мм:" VerticalAlignment="Center"/>
                <ComboBox x:Name="cbDiam" Width="65" Margin="4,0,10,0" VerticalAlignment="Center"/>
                <Label Content="Позиция:" VerticalAlignment="Center"/>
                <TextBox x:Name="tbPos" Width="65" Margin="4,0,10,0" VerticalAlignment="Center" Height="22"/>
                <Button x:Name="btnFilter" Content="Фильтр" Padding="10,3" Margin="0,0,6,0" VerticalAlignment="Center"/>
                <Button x:Name="btnReset" Content="Сброс" Padding="10,3" VerticalAlignment="Center"/>
                <Label x:Name="lblTotal" Content="" Margin="14,0,0,0"
                       VerticalAlignment="Center" Foreground="#555555" FontStyle="Italic"/>
            </WrapPanel>
        </Border>

        <!-- Rebar table -->
        <DataGrid Grid.Row="1" x:Name="dgRebar"
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
                        <DataTrigger Binding="{Binding [IsUnique]}" Value="True">
                            <Setter Property="Background" Value="#FFFDE7"/>
                            <Setter Property="ToolTip" Value="Одиночный элемент — поставлен по геометрии"/>
                        </DataTrigger>
                    </Style.Triggers>
                </Style>
            </DataGrid.RowStyle>
            <DataGrid.Columns>
                <DataGridTextColumn Header="Форма"    Binding="{Binding [Форма]}"   Width="65"/>
                <DataGridTextColumn Header="Диам, мм" Binding="{Binding [Диам]}"    Width="80"/>
                <DataGridTextColumn Header="A, мм"    Binding="{Binding [A], StringFormat=F1}"  Width="90"/>
                <DataGridTextColumn Header="B, мм"    Binding="{Binding [B], StringFormat=F1}"  Width="90"/>
                <DataGridTextColumn Header="Кол-во"   Binding="{Binding [Кол-во]}"  Width="70"/>
                <DataGridTextColumn Header="Позиции"  Binding="{Binding [Позиции]}" Width="*"/>
                <DataGridTextColumn Binding="{Binding [IDs]}" Visibility="Collapsed" Width="0"/>
            </DataGrid.Columns>
        </DataGrid>

        <!-- Bottom action bar -->
        <Border Grid.Row="2" BorderBrush="#CCCCCC" BorderThickness="1"
                CornerRadius="3" Padding="10,8">
            <DockPanel>
                <StackPanel DockPanel.Dock="Right" Orientation="Horizontal" VerticalAlignment="Center">
                    <Button x:Name="btnSelect" Content="Выделить в Revit" Padding="10,5" Margin="0,0,8,0"/>
                    <Button x:Name="btnUnify"  Content="Унифицировать"    Padding="10,5"
                            Background="#1565C0" Foreground="White" FontWeight="Bold"/>
                </StackPanel>
                <StackPanel Orientation="Horizontal" VerticalAlignment="Center">
                    <Label x:Name="lblSelected" Content="Выбрано строк: 0 (0 элементов)"
                           FontWeight="SemiBold" Margin="0,0,16,0"/>
                    <Label Content="Параметр:" Margin="0,0,4,0"/>
                    <ComboBox x:Name="cbParam" Width="65" Margin="0,0,10,0">
                        <ComboBoxItem Content="PR_A" IsSelected="True"/>
                        <ComboBoxItem Content="PR_B"/>
                    </ComboBox>
                    <Label Content="Значение (мм):" Margin="0,0,4,0"/>
                    <TextBox x:Name="tbTarget" Width="85" Height="22"/>
                </StackPanel>
            </DockPanel>
        </Border>
    </Grid>
</Window>'''


def get_param(elem, name, ptype='string'):
    p = elem.LookupParameter(name)
    if p is None:
        return None
    try:
        if ptype == 'string':
            return p.AsString() or p.AsValueString() or ''
        elif ptype == 'double':
            return p.AsDouble()
        elif ptype == 'int':
            return p.AsInteger()
    except Exception:
        return None


def collect_groups():
    collector = FilteredElementCollector(doc).OfClass(Rebar).ToElements()
    groups = {}
    for rb in collector:
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
    return groups


def build_dt(groups, f_shape='Все', f_diam='Все', f_pos=''):
    dt = DataTable()
    dt.Columns.Add('Форма',    System.Int32)
    dt.Columns.Add('Диам',     System.Int32)
    dt.Columns.Add('A',        System.Double)
    dt.Columns.Add('B',        System.Double)
    dt.Columns.Add('Кол-во',   System.Int32)
    dt.Columns.Add('Позиции',  System.String)
    dt.Columns.Add('IDs',      System.String)
    dt.Columns.Add('IsUnique', System.Boolean)

    for key in sorted(groups.keys()):
        shape, diam, a, b = key
        g = groups[key]

        if f_shape != 'Все':
            try:
                if shape != int(f_shape):
                    continue
            except Exception:
                pass
        if f_diam != 'Все':
            try:
                if diam != int(f_diam):
                    continue
            except Exception:
                pass
        if f_pos.strip():
            if not any(f_pos.strip() in p for p in g['positions']):
                continue

        pos_list = sorted(g['positions'])
        pos_str  = ', '.join(pos_list[:6])
        if len(g['positions']) > 6:
            pos_str += '...'

        row = dt.NewRow()
        row['Форма']    = shape
        row['Диам']     = diam
        row['A']        = a
        row['B']        = b
        row['Кол-во']   = g['count']
        row['Позиции']  = pos_str
        row['IDs']      = ','.join(str(i) for i in g['ids'])
        row['IsUnique'] = (g['count'] == 1)
        dt.Rows.Add(row)

    return dt


class RebarUnifyWindow(object):

    def __init__(self):
        self.groups = collect_groups()
        self.window = XamlReader.Parse(XAML_STR)

        self.dg         = self.window.FindName('dgRebar')
        self.cb_shape   = self.window.FindName('cbShape')
        self.cb_diam    = self.window.FindName('cbDiam')
        self.tb_pos     = self.window.FindName('tbPos')
        self.btn_filter = self.window.FindName('btnFilter')
        self.btn_reset  = self.window.FindName('btnReset')
        self.lbl_total  = self.window.FindName('lblTotal')
        self.lbl_sel    = self.window.FindName('lblSelected')
        self.cb_param   = self.window.FindName('cbParam')
        self.tb_target  = self.window.FindName('tbTarget')
        self.btn_select = self.window.FindName('btnSelect')
        self.btn_unify  = self.window.FindName('btnUnify')

        self._fill_combos()
        self._refresh_grid()

        self.btn_filter.Click        += self._on_filter
        self.btn_reset.Click         += self._on_reset
        self.btn_select.Click        += self._on_select
        self.btn_unify.Click         += self._on_unify
        self.dg.SelectionChanged     += self._on_sel_changed

        self.window.Show()

    def _fill_combos(self):
        self.cb_shape.Items.Clear()
        self.cb_shape.Items.Add('Все')
        for s in sorted(set(k[0] for k in self.groups.keys())):
            self.cb_shape.Items.Add(str(s))
        self.cb_shape.SelectedIndex = 0

        self.cb_diam.Items.Clear()
        self.cb_diam.Items.Add('Все')
        for d in sorted(set(k[1] for k in self.groups.keys())):
            self.cb_diam.Items.Add(str(d))
        self.cb_diam.SelectedIndex = 0

    def _refresh_grid(self):
        f_shape = str(self.cb_shape.SelectedItem or 'Все')
        f_diam  = str(self.cb_diam.SelectedItem  or 'Все')
        f_pos   = self.tb_pos.Text or ''

        dt = build_dt(self.groups, f_shape, f_diam, f_pos)
        self.dg.ItemsSource = dt.DefaultView

        total_elems = sum(g['count'] for g in self.groups.values())
        self.lbl_total.Content = 'Всего: {} групп, {} элементов'.format(
            len(self.groups), total_elems)
        self._update_sel_label()

    def _on_filter(self, sender, args):
        self._refresh_grid()

    def _on_reset(self, sender, args):
        self.cb_shape.SelectedIndex = 0
        self.cb_diam.SelectedIndex  = 0
        self.tb_pos.Text = ''
        self._refresh_grid()

    def _on_sel_changed(self, sender, args):
        self._update_sel_label()

    def _update_sel_label(self):
        rows    = list(self.dg.SelectedItems)
        n_rows  = len(rows)
        n_elems = 0
        for row in rows:
            try:
                n_elems += int(row['Кол-во'])
            except Exception:
                pass
        self.lbl_sel.Content = 'Выбрано строк: {} ({} элементов)'.format(n_rows, n_elems)

    def _get_selected_ids(self):
        ids = []
        for row in self.dg.SelectedItems:
            try:
                for id_str in str(row['IDs']).split(','):
                    id_str = id_str.strip()
                    if id_str:
                        ids.append(int(id_str))
            except Exception:
                pass
        return ids

    def _on_select(self, sender, args):
        ids = self._get_selected_ids()
        if not ids:
            MessageBox.Show('Нет выбранных строк.', 'Выделение', MessageBoxButton.OK)
            return
        id_list = List[ElementId]([ElementId(i) for i in ids])
        uidoc.Selection.SetElementIds(id_list)

    def _on_unify(self, sender, args):
        ids = self._get_selected_ids()
        if not ids:
            MessageBox.Show('Выберите строки в таблице.', 'Унификация', MessageBoxButton.OK)
            return

        sel_item = self.cb_param.SelectedItem
        if sel_item is None:
            MessageBox.Show('Выберите параметр.', 'Ошибка', MessageBoxButton.OK)
            return
        param_name = str(sel_item.Content) if hasattr(sel_item, 'Content') else str(sel_item)

        raw = self.tb_target.Text.strip().replace(',', '.')
        try:
            target_mm = float(raw)
        except Exception:
            MessageBox.Show('Введите числовое значение в мм.', 'Ошибка', MessageBoxButton.OK)
            return

        target_ft = target_mm / FEET_TO_MM

        confirm = MessageBox.Show(
            'Изменить {} = {:.1f} мм для {} элементов?'.format(param_name, target_mm, len(ids)),
            'Подтверждение', MessageBoxButton.OKCancel)
        if confirm != MessageBoxResult.OK:
            return

        changed = 0
        errors  = []
        t = Transaction(doc, 'Унификация арматуры')
        t.Start()
        for elem_id in ids:
            try:
                elem = doc.GetElement(ElementId(elem_id))
                if elem is None:
                    continue
                p = elem.LookupParameter(param_name)
                if p is not None and not p.IsReadOnly:
                    p.Set(target_ft)
                    changed += 1
                else:
                    errors.append('ID {}: параметр недоступен'.format(elem_id))
            except Exception as ex:
                errors.append('ID {}: {}'.format(elem_id, str(ex)))
        t.Commit()

        # Reload and refresh
        self.groups = collect_groups()
        self._fill_combos()
        self._refresh_grid()

        msg = 'Изменено: {} элементов'.format(changed)
        if errors:
            msg += '\nОшибок: {}\n\n{}'.format(len(errors), '\n'.join(errors[:5]))
        MessageBox.Show(msg, 'Готово', MessageBoxButton.OK)


# Module-level reference keeps the window alive after the script finishes
_win_instance = None

try:
    _win_instance = RebarUnifyWindow()
except Exception as ex:
    import traceback
    forms.alert('Ошибка:\n{}\n\n{}'.format(str(ex), traceback.format_exc()), title='Ошибка запуска')
