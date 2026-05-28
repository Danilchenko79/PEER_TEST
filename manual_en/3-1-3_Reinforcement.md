# 3.1.3 Reinforcement

> Source: [3.1.3 Армирование (bim2b.ru)](https://manual2021.bim2b.ru/kzh/3-1-vkladka-konstrukczii-3-shablon-kzh/3-1-3-armirovanie/)
> Parameter naming follows the new English SPF (`PR_*` prefix). The original Russian template used the `ADSK_*` prefix.

---

## Rebar classes in the template

The following reinforcement classes are pre-configured:

| Rebar class | Nominal diameter, mm | Standard |
|---|---|---|
| A240 | 4–40 | GOST 34028-2016 |
| A400 | 4–40 | GOST 34028-2016 |
| A500 | 4–40 | GOST 34028-2016 |
| A600 | 4–40 | GOST 34028-2016 |
| A800 | 4–40 | GOST 34028-2016 |
| A1000 | 4–40 | GOST 34028-2016 |
| Ap600 | 4–40 | GOST 34028-2016 |
| B500C | 4–12 | GOST R 52544-2006 |
| B-II | 3–8 | GOST 7348-81 |
| Bp-I | 3–5 | GOST 6727-80 |
| Bp-II | 3–8 | GOST 7348-81 |

> To use a rebar class with additional technical requirements per GOST 34028-2016, append the corresponding letter to the class name (per Section 6 of the standard) and rename the material accordingly.

![Rebar classes table](https://manual2021.bim2b.ru/wp-content/uploads/2022/11/2022-11-30_12-29-57.png)

![Rebar classes settings](https://manual2021.bim2b.ru/wp-content/uploads/2022/11/2022-11-30_12-26-56.png)

---

## Rebar parameters

| Parameter | Description |
|---|---|
| `PR_Rolled Steel Code` | IFC rebar codes (e.g. 500.3 — A500C; 500.4 — A500SP) |
| `PR_Designation` | Standard/specification reference for this rebar class |
| `Material` | Built-in parameter; name matches the rebar class |
| `Standard Bend Diameter` | Minimum bend diameter per SP 63.13330.2012 |
| `Standard Hook Bend Diameter` | Equal to the standard bend diameter |
| `Stirrup Bend Diameter` | Equal to the standard bend diameter |
| `PR_Dimension in Linear Meters` | Off by default |
| `PR_Rebar as Family` | On for IFC rebar; off for standard rebar |
| `PR_Mass per Unit Length` | Mass per unit length of rolled steel |
| `PR_Frame` | Off by default |
| `PR_Embedded Detail` | Off by default |

![Rebar parameters](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-344.png)

![Material settings](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-345.png)

![Bend diameters](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-346.png)

![Linear meters parameter](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-347.png)

![Rebar as family parameter](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-348.png)

---

## Subcategories of structural rebar

For the **Structural Rebar** category, subcategories with distinct colors have been created for visual recognition.

---

## Rebar shape types

Shapes follow naming patterns based on shape style and bend count.

### Style prefixes

- **O_1** — straight rebar, *Standard* style
- **O_11** — one bend, first form
- **O_(11)** — one bend formed by hooks, 90°
- **O_(22)** — two bends, 180°
- **O_24** — two bends, fourth form
- **O_(24)_45°_45°** — fourth form, 45° hooks on both sides
- **X_22** — *Stirrup/Tie* style
- **X_(22)** — stirrup formed by hooks, 180°

![Shape types overview](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-349.png)

![Shape examples 1](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-350.png)

![Shape examples 2](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-351.png)

---

## Rebar type prefixes

Type names indicate the surface, direction, and special role:

| Type name | Description |
|---|---|
| `A500 Ø12` | Main reference rebar; comment: *main* |
| `Bx_A500 Ø12` | Additional zones; in plan — top face along X; in walls — inner face |
| `By_A500 Ø12` | Additional zones; in plan — top face along Y; in walls — inner face |
| `Hx_A500 Ø12` | Additional zones; in walls — bottom/outer face along X |
| `Hy_A500 Ø12` | Additional zones; in plan — bottom face along Y; in walls — outer face |
| `v_A500 Ø12` | Starter bars; comment: *main starters* |
| `d_A500 Ø12` | Detail bars; comment: *main details* |
| `f_A500 Ø12` | Frames; comment: *main frames* |
| `dz_A500 Ø12` | Embedded part element; comment: *embedded details* |
| `zd_A500 Ø12` | Standalone embedded part; comment: *embedded details* |
| `lm_Bx_A500 Ø12` | In linear meters; top/inner face along X |
| `lm_By_A500 Ø12` | In linear meters; top/inner face along Y |
| `lm_Hx_A500 Ø12` | In linear meters; bottom/outer face along X |
| `lm_Hy_A500 Ø12` | In linear meters; bottom/outer face along Y |
| `lm_v_A500 Ø12` | Starters in linear meters |
| `lm_d_A500 Ø12` | Details in linear meters |
| `lm_dz_A500 Ø12` | Embedded elements in linear meters |
| `lm_zd_A500 Ø12` | Embedded details in linear meters |

> **Naming legend** (translated from the Russian template):
> `В` (top/inner) → `B`,  `Н` (bottom/outer) → `H`,
> `в` (starters) → `v`,  `д` (details) → `d`,  `к` (frames) → `f`,
> `дз` (embedded element) → `dz`,  `зд` (embedded part) → `zd`,
> `мп_` (linear meters) → `lm_`.

![Type prefixes 1](https://manual2021.bim2b.ru/wp-content/uploads/2022/06/image-25.png)

![Type prefixes 2](https://manual2021.bim2b.ru/wp-content/uploads/2022/06/image-26.png)

![Type prefixes 3](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-354.png)

---

## Shape family parameters

The shape family (rebar shape definition) carries:

- `PR_Rebar Shape` — numeric shape value
- `PR_Shape by Bends` — *Yes* if the shape is formed by hooks/bends
- `PR_Detail_Prefix` — letter code shown in schedules
- *Shape image* — raster image used in bills of materials

---

## Cover layers

Default cover layers are pre-configured in the template; adjust as needed for your project.

![Cover layers](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-355.png)

---

## Area reinforcement

Area reinforcement is created with the **Distributed** tool using the appropriate rebar types.

### Mesh face types

- **Bx** — top/inner face along X
- **By** — top/inner face along Y
- **Hx** — bottom/outer face along X
- **Hy** — bottom/outer face along Y
- **details** — for detail bars
- **main** — background or general-purpose mesh

> Always keep a single consistent **Major Direction** across all area reinforcement on a slab/wall.

![Area reinforcement 1](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-356.png)
![Area reinforcement 2](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-357.png)
![Area reinforcement 3](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-358.png)
![Area reinforcement 4](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-359.png)
![Area reinforcement 5](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-360.png)
![Area reinforcement 6](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-361.png)
![Area reinforcement 7](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-362.png)
![Area reinforcement 8](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-363.png)
![Area reinforcement 9](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-364.png)
![Area reinforcement 10](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-365.png)
![Area reinforcement 11](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-366.png)
![Area reinforcement 12](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-367.png)
![Area reinforcement 13](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-368.png)

---

## Path reinforcement

Path reinforcement is laid along an edge with the matching rebar type.

### Path edge types

- **Bx** — inner/top along X
- **By** — inner/top along Y
- **Hx** — outer/bottom along X
- **Hy** — outer/bottom along Y
- **starters** — for starter bars
- **details** — for detail bars
- **main** — background reinforcement

### Hooks for starter bars

Hook length is measured **from the bend face**, ensuring proper anchorage length.

![Path reinforcement 1](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-369.png)
![Path reinforcement 2](https://manual2021.bim2b.ru/wp-content/uploads/2022/06/image-146.png)
![Path reinforcement 3](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-371.png)
![Path reinforcement 4](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-372.png)
![Path reinforcement 5](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-373.png)
![Path reinforcement 6](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-374.png)
![Path reinforcement 7](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-375.png)
![Path reinforcement 8](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-376.png)
![Path reinforcement 9](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-377.png)
![Path reinforcement 10](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-378.png)

---

## Wire mesh reinforcement

When using **Fabric Reinforcement**, pick the desired type. The template includes meshes per GOST 23279-2012.

To create a custom mesh:

1. Create the wire rebar types
2. Set the wire diameter and the bend diameter
3. Set the rolled steel code
4. Set the GOST reference

![Wire mesh 1](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-379.png)
![Wire mesh 2](https://manual2021.bim2b.ru/wp-content/uploads/2022/06/image-27.png)
![Wire mesh 3](https://manual2021.bim2b.ru/wp-content/uploads/2022/06/image-28.png)
![Wire mesh 4](https://manual2021.bim2b.ru/wp-content/uploads/2022/06/image-29.png)

---

## Rebar bar — creation methods

When creating a rebar bar, pick a shape from the drop-down list or use the **Shape Browser**.

> For complex shapes, **draw the bar by sketch** or use the **Free Form** tool.

![Rebar creation 1](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-383.png)
![Rebar creation 2](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-384.png)
![Rebar creation 3](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-385.png)

---

## Embedded parts

Embedded parts (Series 1.400-15 issue 1) are pre-loaded in the template.

Embedded parts are modelled as the **Structural Rebar** category using profile, plate and bar families. They are placed on the faces of concrete elements.

### Embedded part parameters

Nested families carry the comment **"embedded details"** and the **`dz_`** prefix.

IFC rebar families use:

- `PR_Host Category`
- `PR_Host Mark`
- `PR_Host Quantity`
- `PR_Rolled Steel Code`

> `PR_Host Quantity` is required for the *Reinforcement per RC element* schedule.

To indicate which assembly an element belongs to, set **`PR_Product Mark`**.

![Embedded parts 1](https://manual2021.bim2b.ru/wp-content/uploads/2022/06/image-30.png)
![Embedded parts 2](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-387.png)
![Embedded parts 3](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-388.png)
![Embedded parts 4](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-389.png)
![Embedded parts 5](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-390.png)
![Embedded parts 6](https://manual2021.bim2b.ru/wp-content/uploads/2022/06/image-147.png)
![Embedded parts 7](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-396.png)
![Embedded parts 8](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-397.png)

---

## Rebar frames (cages)

Rebar cages are built with the **Group** tool from individual rebar bars.

Workflow:

1. Model the bars with the standard tools
2. Create a **Group** from the selected bars
3. Copy the group throughout the project

### Frame parameters

- `PR_Product Mark` — assembly the frame belongs to
- `PR_Assembly Main Detail` — flag for a single bar or array
- Rebar types use the **`f_`** or **`lm_f_`** prefix

> When the frame is built in linear meters, you must tick **`PR_Assembly Main Detail`** on one of the bars.

### Spatial frames

Spatial cages require:

- `PR_Structure Mark`
- `PR_Spatial Frame` — checked
- `PR_Structure Main Detail` — flag for one bar

> Spatial cages must be built from rebar types **without the surface prefix** (the only allowed prefix is `lm_`).

![Rebar frames 1](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-398.png)
![Rebar frames 2](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-400.png)

---

## IFC rebar

IFC rebar is used for embedded parts and complex non-standard shapes.

It requires manual entry of:

- `PR_Host Category`
- `PR_Host Mark`
- `PR_Host Quantity`

> `PR_Quantity` is filled in when each individual element does not need to be modelled separately.

![IFC rebar 1](http://manual.bim2b.ru/wp-content/uploads/2020/04/word-image-401.png)
![IFC rebar 2](https://manual2021.bim2b.ru/wp-content/uploads/2022/06/image-31.png)

---

## Technical requirements

> To use rebar per GOST 34028-2016 with additional technical requirements (Section 6 of the standard), append the requirement letter to the class name and rename the corresponding material.

---

## Parameter cross-reference (RU → EN)

Quick lookup for parameters mentioned on this page:

| Russian (ADSK_) | English (PR_) |
|---|---|
| ADSK_Арматура семейством | PR_Rebar as Family |
| ADSK_Главная деталь изделия | PR_Assembly Main Detail |
| ADSK_Главная деталь конструкции | PR_Structure Main Detail |
| ADSK_Деталь_Префикс | PR_Detail_Prefix |
| ADSK_Закладная деталь | PR_Embedded Detail |
| ADSK_Каркас | PR_Frame |
| ADSK_Категория основы | PR_Host Category |
| ADSK_Код металлопроката | PR_Rolled Steel Code |
| ADSK_Количество | PR_Quantity |
| ADSK_Количество основы | PR_Host Quantity |
| ADSK_Марка изделия | PR_Product Mark |
| ADSK_Марка конструкции | PR_Structure Mark |
| ADSK_Масса на единицу длины | PR_Mass per Unit Length |
| ADSK_Метка основы | PR_Host Mark |
| ADSK_Обозначение | PR_Designation |
| ADSK_Пространственный каркас | PR_Spatial Frame |
| ADSK_Размер в погонных метрах | PR_Dimension in Linear Meters |
| ADSK_Форма арматуры | PR_Rebar Shape |
| ADSK_Форма отгибами | PR_Shape by Bends |
