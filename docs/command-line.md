# Command line

`coaster_gen.py` makes coasters from a terminal, with the same generator as the app. It needs Python 3.10 or newer and the packages in `requirements.txt` (see [Development](development.md)).

```
python coaster_gen.py --shape hexagon --seed 42
python coaster_gen.py --pattern classical --center 20 --formats 3mf,step
python coaster_gen.py --shape flower --petals 5 --wall 1.5 --gap 1.5
python coaster_gen.py --outline my_shape.dxf
python coaster_gen.py --examples        # 10 starter designs
python coaster_gen.py --help            # every option
```

Each run prints the checks as PASS or FAIL, and any note about the centre size. Files go to the `output` folder unless `--out` names another.

## Options

| Option | Default | What it does |
|---|---|---|
| `--shape` | `circle` | `circle`, `hexagon`, `octagon`, `rounded-square` or `flower` |
| `--outline FILE` | | a closed outline in a DXF file, in mm, instead of `--shape` |
| `--pattern` | `theta` | `theta` for a random maze, `classical` for a classical labyrinth |
| `--size` | 100 | overall width in mm |
| `--rim` | 3 | solid border in mm |
| `--wall`, `--gap` | 1, 1 | wall thickness and channel width in mm |
| `--base`, `--wall-height` | 2, 2 | floor thickness and wall height above it, in mm |
| `--center` | 6 for `theta`, 16 for `classical` | centre diameter in mm; it can grow by up to two steps of wall plus gap |
| `--corner-r` | 4, or 12 for `rounded-square` | corner radius in mm |
| `--petals` | 6 | petal count for `flower` |
| `--seed` | random | the maze's seed; the same seed and settings give the same maze |
| `--algo` | `dfs` | `dfs` for long corridors, `prim` for bushy |
| `--bias` | `none` | `ring` for runs around the rings, `radial` for runs outward |
| `--cell-length` | 1.5 × (wall + gap) | shortest maze cell in mm; bigger gives a coarser maze |
| `--formats` | `3mf,dxf,svg` | the files to write, from `3mf`, `stl`, `step`, `dxf` and `svg` |
| `--name` | from the settings | file name without the extension |
| `--out` | `output` | output folder |
| `--examples` | | writes 10 starter designs instead of one |
| `--skip-checks` | | leaves out the wall and gap checks, which saves a few seconds |

[Settings](settings.md) explains what each one does in more detail, and [Files](file-formats.md) what each file holds.
