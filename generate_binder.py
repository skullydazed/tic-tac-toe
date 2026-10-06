"""Generate a paper computer: a perfect-play tic-tac-toe binder.

Board strings use nine cells in reading order: X, O, or . for empty.
The game graph and address allocation use only the Python standard library.
ReportLab is loaded only when rendering a PDF.
"""

from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path


EMPTY_BOARD = "." * 9
ROWS_PER_PAGE = 6
TABS_PER_PACK = 8
# In equally good positions, prefer the center, corners, then edges.
MOVE_ORDER = (4, 0, 2, 6, 8, 1, 3, 5, 7)
WIN_LINES = (
    (0, 1, 2), (3, 4, 5), (6, 7, 8),
    (0, 3, 6), (1, 4, 7), (2, 5, 8),
    (0, 4, 8), (2, 4, 6),
)


def outcome(board: str) -> str | None:
    """Return X, O, DRAW, or None if play can continue."""
    for a, b, c in WIN_LINES:
        if board[a] != "." and board[a] == board[b] == board[c]:
            return board[a]
    return "DRAW" if "." not in board else None


def play(board: str, cell: int, player: str) -> str:
    if not 0 <= cell < 9 or board[cell] != ".":
        raise ValueError("A move must use an empty cell between 0 and 8.")
    if player not in ("X", "O") or outcome(board) is not None:
        raise ValueError("A move requires X or O and an unfinished board.")
    return board[:cell] + player + board[cell + 1:]


@lru_cache(maxsize=None)
def minimax(board: str, player: str) -> int:
    """Score from O's perspective: win +1, draw 0, loss -1."""
    result = outcome(board)
    if result is not None:
        return {"O": 1, "DRAW": 0, "X": -1}[result]
    next_player = "X" if player == "O" else "O"
    scores = [
        minimax(play(board, cell, player), next_player)
        for cell in MOVE_ORDER if board[cell] == "."
    ]
    return max(scores) if player == "O" else min(scores)


def choose_o_move(board: str) -> int:
    if outcome(board) is not None or board.count("X") != board.count("O") + 1:
        raise ValueError("Expected an unfinished board just before O's turn.")
    # Minimax treats immediate and eventual wins equally. Finish a winning
    # line now before applying positional preferences to optimal moves.
    for cell in MOVE_ORDER:
        if board[cell] == "." and outcome(play(board, cell, "O")) == "O":
            return cell
    return max(
        (cell for cell in MOVE_ORDER if board[cell] == "."),
        key=lambda cell: minimax(play(board, cell, "O"), "X"),
    )


@dataclass(frozen=True)
class Reply:
    cell: int
    destination: str | None = None
    result: str | None = None


@dataclass(frozen=True)
class GameRow:
    starting_board: str
    o_move: int
    after_o: str
    result: str | None
    replies: tuple[Reply, ...]


@dataclass(frozen=True)
class Address:
    divider_pack: int
    tab: int
    page: int
    row: int

    def __str__(self) -> str:
        return f"{self.divider_pack}-{self.tab}-{self.page}-{self.row}"


def printed_address(address: str) -> str:
    """Group the divider pack (tab row) and tab above the page and game row."""
    pack, tab, page, row = address.split("-")
    return f"{pack}-{tab}\n{page}-{row}"


def generate_game() -> tuple[GameRow, ...]:
    """Breadth-first graph, deduplicating exact boards without rotations."""
    opening_boards = [play(EMPTY_BOARD, cell, "X") for cell in range(9)]
    pending = deque(opening_boards)
    discovered = set(opening_boards)
    rows = []
    while pending:
        before = pending.popleft()
        move = choose_o_move(before)
        after = play(before, move, "O")
        result = outcome(after)
        replies = []
        if result is None:
            for cell in range(9):
                if after[cell] != ".":
                    continue
                next_board = play(after, cell, "X")
                next_result = outcome(next_board)
                if next_result is not None:
                    if next_result == "X":
                        raise AssertionError("The perfect-play strategy let X win.")
                    replies.append(Reply(cell, result=next_result))
                else:
                    replies.append(Reply(cell, destination=next_board))
                    if next_board not in discovered:
                        discovered.add(next_board)
                        pending.append(next_board)
        rows.append(GameRow(before, move, after, result, tuple(replies)))
    return tuple(rows)


def allocate_addresses(
    rows: tuple[GameRow, ...], pages_per_tab: int,
) -> dict[str, Address]:
    if pages_per_tab < 1:
        raise ValueError("Pages per tab must be positive.")
    addresses = {}
    for index, row in enumerate(rows):
        page_index, row_index = divmod(index, ROWS_PER_PAGE)
        tab_index, page_in_tab = divmod(page_index, pages_per_tab)
        pack_index, tab_in_pack = divmod(tab_index, TABS_PER_PACK)
        addresses[row.starting_board] = Address(
            pack_index + 1, tab_in_pack + 1, page_in_tab + 1, row_index + 1,
        )
    return addresses


def material_counts(row_count: int, pages_per_tab: int) -> dict[str, int]:
    game_pages = (row_count + ROWS_PER_PAGE - 1) // ROWS_PER_PAGE
    tabs = (game_pages + pages_per_tab - 1) // pages_per_tab
    return {
        "game_rows": row_count,
        "game_pages": game_pages,
        "opening_pages": 1,
        "total_printed_pages": game_pages + 1,
        "tabs": tabs,
        "divider_packs": (tabs + TABS_PER_PACK - 1) // TABS_PER_PACK,
    }


def build_manifest(
    rows: tuple[GameRow, ...], addresses: dict[str, Address], pages_per_tab: int,
) -> dict:
    def reply_data(reply: Reply) -> dict:
        if reply.destination is not None:
            return {"cell": reply.cell, "address": str(addresses[reply.destination])}
        return {"cell": reply.cell, "result": reply.result}

    return {
        "schema_version": 1,
        "board_encoding": "Nine characters in reading order; . empty, X child, O binder.",
        "cell_numbering": "Zero-based, 0 through 8 in reading order.",
        "address_format": "dividerPack-tab-page-row (all one-based)",
        "printed_address_format": "{tabRow}-{tabNum}\n{pageNum}-{rowNum}",
        "tabRow": "Divider pack number; the first component of the address.",
        "settings": {
            "pages_per_tab": pages_per_tab,
            "rows_per_page": ROWS_PER_PAGE,
            "tabs_per_pack": TABS_PER_PACK,
            "o_tie_break_order": list(MOVE_ORDER),
            "o_strategy": "Take an immediate win; otherwise maximize minimax score, breaking ties by o_tie_break_order.",
            "paper": "US Letter",
            "printing": "single-sided",
            "game_page_layout": "Odd game pages: left, holes on right. Even game pages: right, holes on left. Opening sheet excluded from parity.",
        },
        "materials": material_counts(len(rows), pages_per_tab),
        "opening": {
            "board": EMPTY_BOARD,
            "replies": [
                {"cell": cell, "address": str(addresses[play(EMPTY_BOARD, cell, "X")])}
                for cell in range(9)
            ],
        },
        "rows": [
            {
                "address": str(addresses[row.starting_board]),
                "starting_board": row.starting_board,
                "o_move": row.o_move,
                "after_o": row.after_o,
                "result": row.result,
                "replies": [reply_data(reply) for reply in row.replies],
            }
            for row in rows
        ],
    }


def validate_game(rows: tuple[GameRow, ...], addresses: dict[str, Address]) -> None:
    """Check navigation and game invariants before producing print artifacts."""
    by_board = {row.starting_board: row for row in rows}
    if len(by_board) != len(rows) or set(addresses) != set(by_board):
        raise AssertionError("Every game board must have exactly one row and address.")
    if len(set(addresses.values())) != len(rows):
        raise AssertionError("Row addresses must be unique.")
    for cell in range(9):
        if play(EMPTY_BOARD, cell, "X") not in by_board:
            raise AssertionError("An opening move is missing.")
    for row in rows:
        before, after = row.starting_board, row.after_o
        if outcome(before) is not None or before.count("X") != before.count("O") + 1:
            raise AssertionError("Invalid starting board.")
        if after != play(before, row.o_move, "O") or row.result != outcome(after):
            raise AssertionError("Invalid O move or result.")
        if row.result != "O" and any(
            outcome(play(before, cell, "O")) == "O"
            for cell in range(9) if before[cell] == "."
        ):
            raise AssertionError("O must take an available immediate win.")
        if minimax(after, "X") < 0:
            raise AssertionError("O must never choose a losing move.")
        expected_cells = {i for i, value in enumerate(after) if value == "."}
        actual_cells = {reply.cell for reply in row.replies}
        if row.result is not None:
            if row.result != "O" or row.replies:
                raise AssertionError("A winning row must end immediately.")
            continue
        if actual_cells != expected_cells or len(actual_cells) != len(row.replies):
            raise AssertionError("Every empty reply cell must have one destination.")
        for reply in row.replies:
            next_board = play(after, reply.cell, "X")
            if reply.result is not None:
                if reply.result != "DRAW" or outcome(next_board) != "DRAW" or reply.destination:
                    raise AssertionError("Only drawing moves may replace addresses with DRAW.")
            elif reply.destination != next_board or next_board not in by_board:
                raise AssertionError("A reply address points to the wrong board.")


def render_pdf(manifest: dict, output_path: Path) -> None:
    """Render the opening sheet and six-row game pages for a three-ring binder."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.pdfgen import canvas

    width, height = letter
    # Base layout has a one-inch left margin and a half-inch right margin.
    # Translate odd game pages left by half an inch to swap those margins.
    left, right = 72, width - 36
    ink = colors.HexColor("#202b38")
    muted = colors.HexColor("#566474")
    red = colors.HexColor("#d5222a")
    blue = colors.HexColor("#174e79")
    rule = colors.HexColor("#cbd3db")
    pdf = canvas.Canvas(str(output_path), pagesize=letter, invariant=1)
    pdf.setTitle("Tic-tac-toe: the paper computer")
    pdf.setAuthor("Tic-tac-toe binder generator")

    def text(x, y, value, size=10, font="Helvetica", color=ink):
        pdf.setFillColor(color)
        pdf.setFont(font, size)
        pdf.drawString(x, y, value)

    def centered(x, y, value, size=10, font="Helvetica", color=ink):
        pdf.setFillColor(color)
        pdf.setFont(font, size)
        pdf.drawCentredString(x, y, value)

    def wrapped(x, y, value, max_width, size=10, leading=15, color=ink):
        words = value.split()
        line = ""
        for word in words:
            candidate = f"{line} {word}".strip()
            if line and stringWidth(candidate, "Helvetica", size) > max_width:
                text(x, y, line, size, color=color)
                y -= leading
                line = word
            else:
                line = candidate
        if line:
            text(x, y, line, size, color=color)
            y -= leading
        return y

    def board(x, top, side, position, labels=None, red_cell=None):
        labels = labels or {}
        cell_size = side / 3
        pdf.setLineWidth(0.8)
        pdf.setStrokeColor(ink)
        pdf.rect(x, top - side, side, side, stroke=1, fill=0)
        for i in (1, 2):
            pdf.line(x + i * cell_size, top, x + i * cell_size, top - side)
            pdf.line(x, top - i * cell_size, x + side, top - i * cell_size)
        for cell, mark in enumerate(position):
            r, c = divmod(cell, 3)
            cx = x + (c + 0.5) * cell_size
            cy = top - (r + 0.5) * cell_size
            if mark == "X":
                delta = cell_size * 0.23
                pdf.setStrokeColor(blue)
                pdf.setLineWidth(max(1.3, cell_size * 0.055))
                pdf.line(cx - delta, cy - delta, cx + delta, cy + delta)
                pdf.line(cx - delta, cy + delta, cx + delta, cy - delta)
            elif mark == "O":
                pdf.setStrokeColor(red if cell == red_cell else blue)
                pdf.setLineWidth(max(1.3, cell_size * 0.055))
                pdf.circle(cx, cy, cell_size * 0.25, stroke=1, fill=0)
            elif cell in labels:
                label = labels[cell]
                font = "Helvetica-Bold" if label == "DRAW" else "Courier-Bold"
                lines = [label] if label == "DRAW" else printed_address(label).splitlines()
                max_size = (9 if side > 100 else 7) if label == "DRAW" else (14 if side > 100 else 11)
                size = min(
                    max_size,
                    (cell_size - 4) / max(stringWidth(line, font, 1) for line in lines),
                    (cell_size - 4) / (1.15 * len(lines)),
                )
                leading = size * 1.15
                for line_number, line in enumerate(lines):
                    baseline = cy + ((len(lines) - 1) / 2 - line_number) * leading - size * 0.32
                    centered(cx, baseline, line, size, font)

    def outside_text(y, value, size=10, font="Helvetica", color=ink, outside_left=False):
        pdf.setFillColor(color)
        pdf.setFont(font, size)
        if outside_left:
            pdf.drawString(left, y, value)
        else:
            pdf.drawRightString(right, y, value)

    def footer(value, outside_left=False, right_content=False):
        pdf.setStrokeColor(rule)
        pdf.setLineWidth(0.6)
        pdf.line(left, 55, right, 55)
        legend = "X = opponent     O = You     Red O = What to Play"
        if right_content:
            outside_text(40, legend, 8, color=muted)
        else:
            text(left, 40, legend, 8, color=muted)
        outside_text(26, value, 8, color=muted, outside_left=outside_left)

    materials = manifest["materials"]
    pages_per_tab = manifest["settings"]["pages_per_tab"]
    text(left, height - 49, "TIC-TAC-TOE", 23, "Helvetica-Bold")
    text(left, height - 71, "Play like a computer!", 14, color=blue)
    y = 687
    y = wrapped(left, y, "Use this book to play Tic-Tac-Toe the way a computer would. Your opponent is X and goes first.", right - left, 11, 17)
    y -= 10
    for instruction in (
        "1. Find the square on the opening board below for your opponent's X."
        "2. Find your position on the left. On the right, the red O is the computer's move.",
        "3. Choose an available square on the right for your next X. Imagine your X in that square, then follow its address. Check that the next starting board matches.",
        "4. If your square says DRAW, the game is over. If the row says O WINS, you have three in a row and have won.",
    ):
        y = wrapped(left, y, instruction, right - left, 10, 15) - 5
    y -= 7
    text(left, y, "HOW TO READ AN ADDRESS", 10, "Helvetica-Bold", blue)
    y = wrapped(left, y - 18, "Top line: divider pack (tab row) - tab. Bottom line: page - row. All numbers start at 1. For example, 2-3 above 1-4 means pack 2, tab 3, page 1, row 4. Tabs restart at 1 in each pack; pages restart at 1 for each tab.", right - left, 10, 15)
    opening_top = y - 30
    centered((left + right) / 2, opening_top + 12, "CHOOSE THE FIRST X", 11, "Helvetica-Bold", blue)
    opening_side = 180
    board((left + right - opening_side) / 2, opening_top, opening_side, EMPTY_BOARD,
          {reply["cell"]: reply["address"] for reply in manifest["opening"]["replies"]})
    footer("Opening sheet - keep at the front")
    pdf.showPage()

    for offset in range(0, len(manifest["rows"]), ROWS_PER_PAGE):
        game_page = offset // ROWS_PER_PAGE + 1
        outside_left = game_page % 2 == 1
        game_page_right = not outside_left
        pdf.saveState()
        if outside_left:
            pdf.translate(-36, 0)
        page_rows = manifest["rows"][offset:offset + ROWS_PER_PAGE]
        pack, tab, page, _ = page_rows[0]["address"].split("-")
        outside_text(749, f"PACK {pack}  /  TAB {tab}  /  PAGE {page}", 16,
                     "Helvetica-Bold", outside_left=outside_left)
        outside_text(728, "Find your row. Play the red O, then follow the address for the next X square.",
                     9, color=muted, outside_left=outside_left)
        for row_index, row in enumerate(page_rows):
            top = 714 - row_index * 108
            outside_text(top - 22, f"ROW {row_index + 1}", 10, "Helvetica-Bold",
                         blue, outside_left=outside_left)
            address_lines = printed_address(row["address"]).splitlines()
            address_size = min(12, 94 / max(stringWidth(line, "Courier-Bold", 1) for line in address_lines))
            for line_number, line in enumerate(address_lines):
                outside_text(top - 40 - line_number * 14, line, address_size,
                             "Courier-Bold", outside_left=outside_left)
            centered(219, top - 9, "STARTING BOARD", 7, "Helvetica-Bold", muted)
            centered(423, top - 9, "O'S MOVE + YOUR CHOICES", 7, "Helvetica-Bold", muted)
            board(174, top - 14, 90, row["starting_board"])
            labels = {reply["cell"]: reply.get("address", reply.get("result")) for reply in row["replies"]}
            board(378, top - 14, 90, row["after_o"], labels, row["o_move"])
            centered(321, top - 49, "O plays", 9, color=muted)
            pdf.setStrokeColor(muted)
            pdf.setLineWidth(0.8)
            pdf.line(287, top - 61, 355, top - 61)
            pdf.line(355, top - 61, 350, top - 57)
            pdf.line(355, top - 61, 350, top - 65)
            if row["result"] == "O":
                text(483, top - 47, "O WINS", 11, "Helvetica-Bold", blue)
                text(483, top - 64, "Game over.", 9, color=muted)
                text(483, top - 78, "Start again.", 9, color=muted)
            elif any(reply.get("result") == "DRAW" for reply in row["replies"]):
                text(483, top - 47, "DRAW", 10, "Helvetica-Bold", blue)
                text(483, top - 64, "Choose that", 8, color=muted)
                text(483, top - 77, "square to tie.", 8, color=muted)
            if row_index < ROWS_PER_PAGE - 1:
                pdf.setStrokeColor(rule)
                pdf.setLineWidth(0.4)
                pdf.line(left, top - 107, right, top - 107)
        footer(f"Game page {game_page} of {materials['game_pages']}", outside_left,
               right_content=game_page_right)
        pdf.restoreState()
        pdf.showPage()
    pdf.save()


def positive_integer(value: str) -> int:
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive integer") from error
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--pages-per-tab", type=positive_integer, default=2,
                        help="game pages behind each tab (default: 2)")
    parser.add_argument("--output-dir", type=Path, default=Path("output"),
                        help="directory for binder.pdf and manifest.json (default: output)")
    parser.add_argument("--stats-only", action="store_true",
                        help="print material counts without creating any files")
    args = parser.parse_args(argv)
    rows = generate_game()
    addresses = allocate_addresses(rows, args.pages_per_tab)
    validate_game(rows, addresses)
    manifest = build_manifest(rows, addresses, args.pages_per_tab)
    materials = manifest["materials"]
    print(f"Game rows: {materials['game_rows']}")
    print(f"Game pages: {materials['game_pages']} (6 row slots per page)")
    print(f"Total printed sheets: {materials['total_printed_pages']} (includes opening sheet)")
    print(f"Pages per tab: {args.pages_per_tab}")
    print(f"Tabs: {materials['tabs']}")
    print(f"Divider packs of 8: {materials['divider_packs']}")
    if args.stats_only:
        return 0
    try:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        render_pdf(manifest, args.output_dir / "binder.pdf")
        (args.output_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8",
        )
    except ImportError as error:
        parser.exit(1, f"PDF dependency missing: {error}. Run with uv run generate_binder.py.\n")
    except OSError as error:
        parser.exit(1, f"Could not write the binder files: {error}\n")
    print(f"PDF: {args.output_dir / 'binder.pdf'}")
    print(f"Manifest: {args.output_dir / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
