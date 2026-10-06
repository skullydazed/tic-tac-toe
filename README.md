# Tic-tac-toe paper computer

A reusable Python script generates a printable three-ring binder that plays
tic-tac-toe. The child plays X first; the binder plays O using perfect play.
Each game row shows the starting board on the left and the computer's new red O
on the right. The child chooses a remaining square for X and follows the address
printed inside it.

## Run with uv

Requires [uv](https://docs.astral.sh/uv/) and Python 3.11 or newer. `uv run`
sets up the environment and installs the ReportLab dependency.

```sh
uv run generate_binder.py --stats-only
uv run generate_binder.py
```

The second command writes `output/binder.pdf` and `output/manifest.json`.
Rerunning replaces these generated files. To choose another output directory or
pack more pages behind each tab:

```sh
uv run generate_binder.py --pages-per-tab 5 --output-dir output-five-pages
```

`--pages-per-tab` accepts any positive integer and defaults to 2. `--stats-only`
validates the game and prints material counts without writing output files.
It can also run with plain `python3` without installing PDF dependencies.

## Print and assemble

Print the PDF on **US Letter, portrait, single-sided, at actual size (100%)**.
Game pages alternate sides in an open binder: odd game pages sit on the **left**
with a one-inch **right** margin for holes; even game pages sit on the **right**
with a one-inch **left** margin. The outer margin is half an inch. Page headers
and game-page numbers align to the outside edge. Parity follows the continuous
game-page number, excluding the opening sheet. Row numbers and two-line addresses
sit outside the boards: on the left for odd pages and on the right for even pages.
The starting board always appears before O's move. Even-page instructions and the
footer legend align right. There are six numbered row slots
per game page; the last page has three occupied slots.

With the default two pages per tab, the binder contains:

| Item | Count |
| --- | ---: |
| Game rows | 267 |
| Game pages | 45 |
| Opening/instructions sheet | 1 |
| Total sheets to print | 46 |
| Tabs used | 23 |
| Packs of eight dividers | 3 |

Keep the opening sheet at the front, before the numbered tabs. Label each pack
1, 2, 3, and label its tabs 1 through 8 (for example, `2-3` for pack 2, tab 3).
With the default two pages per tab, mount page 1 on the **back of its divider**
and page 2 on the **front of the following divider**. Grabbing a tab and opening
it reveals the two-page spread for that tab. Keep the sequence continuous across
divider packs. The final tab has only page 1 on its back; its facing right-hand
page is blank. For configurations ending with a right-hand game page, use a
blank backing sheet if there is no following divider.
Page numbers restart at 1 for every tab. Other `--pages-per-tab` values still
alternate left and right layouts by continuous game-page number, but only the
default two-page setting puts every tab's pages together in one spread.

Printed addresses use two lines, with larger text:

```text
{tabRow}-{tabNum}
{pageNum}-{rowNum}
```

`tabRow` is the divider pack number. All numbers start at 1. For example:

```text
2-3
1-4
```

means pack 2, tab 3, page 1, row 4. The opening sheet is outside this
addressing scheme. Both cell destinations and row labels use this format.

| Pages per tab | Game pages | Tabs | Packs of eight |
| --- | ---: | ---: | ---: |
| 1 | 45 | 45 | 6 |
| 2 (default) | 45 | 23 | 3 |
| 5 | 45 | 9 | 2 |

## How to play

1. Choose your first X square on the opening board and follow its address.
2. Check the left board. The right board adds the computer's new O in red;
   older Xs and Os remain black.
3. Choose an available square on the right for your next X. Imagine placing X
   there, then follow its address. The next row's starting board must match.
4. A cell marked `DRAW` ends the game when you choose it. A row marked `O WINS`
   ends immediately after the red O is placed. Restart from the opening sheet.

On winning rows, unused squares are blank because play has ended. A perfect
binder never loses: the child can force a draw, and mistakes can let O win.

## How it works

The script evaluates moves with minimax: it assumes each side will choose its
best possible reply. O scores a win as +1, a draw as 0, and a loss as -1.
O always takes an immediate win when one is available. Otherwise, equally good
minimax moves use a fixed order: center; top-left, top-right, bottom-left,
bottom-right corners; then top, left, right, bottom edges.

The generator includes every legal X reply to those chosen O moves. It traverses
positions breadth-first, with X cells in reading order, and reuses identical
positions reached by different move sequences. Rotated and reflected positions
remain separate so children never have to turn a board mentally. Winning O moves
finish in their own row; drawing X replies use `DRAW` instead of another row.

The JSON manifest records settings, material counts, opening addresses, and every
row's address, starting board, O move, resulting board, and reply destinations.
Machine-readable addresses remain `pack-tab-page-row`; the manifest records
the two-line printed format separately.
Boards use nine characters in reading order (`.` empty, `X`, `O`). Move and reply
cells are numbered **0 through 8**; binder addresses are **one-based**. A reply
has either an `address` or a terminal `result: "DRAW"`. A row's `result` is `null`
or `"O"`. Changing pages per tab changes addresses, not moves or row order.

## Verify

```sh
uv run python -m unittest discover -s tests -v
```

Tests explore every reachable game, check immediate wins across every legal
O-turn position, and check perfect play and legal navigation,
verify packing boundaries, and check reproducible PDF and manifest output.
Game generation, address allocation, and PDF rendering are separate functions
in `generate_binder.py`.
