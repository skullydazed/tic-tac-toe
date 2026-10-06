"""Exhaustive navigation checks and print-artifact integration tests."""

from contextlib import redirect_stderr, redirect_stdout
from functools import lru_cache
import importlib.util
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import generate_binder as binder


# Independent result calculation for exhaustive path checks.
def result_of(board):
    lines = [board[0:3], board[3:6], board[6:9],
             board[0::3], board[1::3], board[2::3],
             board[0] + board[4] + board[8], board[2] + board[4] + board[6]]
    if "XXX" in lines:
        return "X"
    if "OOO" in lines:
        return "O"
    return "DRAW" if "." not in board else None


class GameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = binder.generate_game()
        cls.addresses = binder.allocate_addresses(cls.rows, 2)
        cls.manifest = binder.build_manifest(cls.rows, cls.addresses, 2)

    def test_every_playable_path_is_legal_and_x_never_wins(self):
        """Walk all move sequences through actual manifest addresses."""
        by_address = {row["address"]: row for row in self.manifest["rows"]}
        visited = set()
        final_results = set()

        def follow(address, expected_board):
            row = by_address[address]
            visited.add(address)
            self.assertEqual(row["starting_board"], expected_board)
            self.assertIsNone(result_of(expected_board))
            self.assertEqual(expected_board.count("X"), expected_board.count("O") + 1)
            cell = row["o_move"]
            self.assertEqual(expected_board[cell], ".")
            after = expected_board[:cell] + "O" + expected_board[cell + 1:]
            self.assertEqual(row["after_o"], after)
            self.assertEqual(row["result"], result_of(after))
            if row["result"]:
                self.assertEqual(row["result"], "O")
                self.assertEqual(row["replies"], [])
                final_results.add("O")
                return
            replies = row["replies"]
            self.assertEqual(sorted(reply["cell"] for reply in replies),
                             [i for i, mark in enumerate(after) if mark == "."])
            for reply in replies:
                cell = reply["cell"]
                child_board = after[:cell] + "X" + after[cell + 1:]
                self.assertNotEqual(result_of(child_board), "X")
                if "result" in reply:
                    self.assertEqual(reply, {"cell": cell, "result": "DRAW"})
                    self.assertEqual(result_of(child_board), "DRAW")
                    final_results.add("DRAW")
                else:
                    self.assertIsNone(result_of(child_board))
                    follow(reply["address"], child_board)

        opening = self.manifest["opening"]
        self.assertEqual(opening["board"], "." * 9)
        self.assertEqual([reply["cell"] for reply in opening["replies"]], list(range(9)))
        for reply in opening["replies"]:
            cell = reply["cell"]
            follow(reply["address"], "." * cell + "X" + "." * (8 - cell))
        self.assertEqual(visited, set(by_address))
        self.assertEqual(final_results, {"O", "DRAW"})

    def test_all_o_choices_are_optimal_against_an_independent_solver(self):
        @lru_cache(None)
        def solve(board, player):
            result = result_of(board)
            if result:
                return {"X": -1, "O": 1, "DRAW": 0}[result]
            values = []
            for cell in range(9):
                if board[cell] == ".":
                    next_board = board[:cell] + player + board[cell + 1:]
                    values.append(solve(next_board, "O" if player == "X" else "X"))
            return max(values) if player == "O" else min(values)

        for row in self.rows:
            with self.subTest(board=row.starting_board):
                self.assertEqual(solve(row.after_o, "X"), solve(row.starting_board, "O"))
                self.assertGreaterEqual(solve(row.after_o, "X"), 0)

    def test_strategy_is_stable_and_preserves_orientation(self):
        self.assertEqual(binder.generate_game(), self.rows)
        occupied = [row.starting_board.count("X") + row.starting_board.count("O")
                    for row in self.rows]
        self.assertEqual(occupied, sorted(occupied))
        for cell, row in enumerate(self.rows[:9]):
            self.assertEqual(row.starting_board, "." * cell + "X" + "." * (8 - cell))
            self.assertEqual(row.o_move, 0 if cell == 4 else 4)
        binder.validate_game(self.rows, self.addresses)

    def test_reported_position_takes_the_immediate_win(self):
        board = "XOX.O.X.."
        self.assertEqual(binder.choose_o_move(board), 7)
        row = next(row for row in self.rows if row.starting_board == board)
        self.assertEqual(row.o_move, 7)
        self.assertEqual(row.result, "O")
        self.assertEqual(row.replies, ())

    def test_immediate_wins_are_taken_on_every_legal_o_turn(self):
        # Cover boards outside this binder too, so strategy changes cannot
        # reintroduce the bug on a newly reachable position.
        visited = set()
        winning_positions = set()

        def visit(board, player):
            if board in visited or result_of(board) is not None:
                return
            visited.add(board)
            if player == "O":
                wins = {
                    cell for cell, mark in enumerate(board)
                    if mark == "." and result_of(board[:cell] + "O" + board[cell + 1:]) == "O"
                }
                if wins:
                    winning_positions.add(board)
                    with self.subTest(board=board):
                        self.assertIn(binder.choose_o_move(board), wins)
            for cell, mark in enumerate(board):
                if mark == ".":
                    visit(board[:cell] + player + board[cell + 1:],
                          "O" if player == "X" else "X")

        visit(".........", "X")
        self.assertGreater(len(winning_positions), 100)

    def test_default_counts_and_terminal_rows(self):
        self.assertEqual(self.manifest["materials"], {
            "game_rows": 267, "game_pages": 45, "opening_pages": 1,
            "total_printed_pages": 46, "tabs": 23, "divider_packs": 3,
        })
        self.assertEqual(sum(row.result == "O" for row in self.rows), 141)
        draw_boards = {
            row.after_o[:reply.cell] + "X" + row.after_o[reply.cell + 1:]
            for row in self.rows for reply in row.replies if reply.result == "DRAW"
        }
        self.assertEqual(len(draw_boards), 12)
        self.assertTrue(all(result_of(row.starting_board) is None for row in self.rows))

    def test_addresses_at_page_tab_and_pack_boundaries(self):
        expected = {
            0: "1-1-1-1", 5: "1-1-1-6", 6: "1-1-2-1",
            11: "1-1-2-6", 12: "1-2-1-1", 95: "1-8-2-6",
            96: "2-1-1-1", 191: "2-8-2-6", 192: "3-1-1-1",
            266: "3-7-1-3",
        }
        for index, address in expected.items():
            self.assertEqual(str(self.addresses[self.rows[index].starting_board]), address)
        self.assertEqual(len(set(self.addresses.values())), 267)

    def test_packing_changes_addresses_but_not_game(self):
        for pages, tabs, packs in ((1, 45, 6), (2, 23, 3), (5, 9, 2), (100, 1, 1)):
            with self.subTest(pages_per_tab=pages):
                addresses = binder.allocate_addresses(self.rows, pages)
                manifest = binder.build_manifest(self.rows, addresses, pages)
                self.assertEqual(manifest["materials"]["tabs"], tabs)
                self.assertEqual(manifest["materials"]["divider_packs"], packs)
                for row, default_row in zip(manifest["rows"], self.manifest["rows"]):
                    self.assertEqual(row["starting_board"], default_row["starting_board"])
                    self.assertEqual(row["o_move"], default_row["o_move"])
                for address in addresses.values():
                    self.assertTrue(1 <= address.tab <= 8)
                    self.assertTrue(1 <= address.page <= pages)
                    self.assertTrue(1 <= address.row <= 6)
                binder.validate_game(self.rows, addresses)

    def test_invalid_moves_and_finished_boards_are_rejected(self):
        for board, cell, player in (("X........", 0, "O"), (".........", -1, "X"),
                                    (".........", 9, "X"), (".........", 0, "Z"),
                                    ("OOOXX....", 5, "X")):
            with self.assertRaises(ValueError):
                binder.play(board, cell, player)
        for board in (".........", "OOOXX....", "XOXOXOXOX"):
            with self.assertRaises(ValueError):
                binder.choose_o_move(board)


class CommandTests(unittest.TestCase):
    def test_stats_only_creates_no_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "must-not-exist"
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(binder.main(["--stats-only", "--output-dir", str(target)]), 0)
            self.assertFalse(target.exists())
            self.assertIn("Divider packs of 8: 3", output.getvalue())

    def test_invalid_pages_per_tab_are_rejected_before_output(self):
        for value in ("0", "-1", "1.5", "abc"):
            with self.subTest(value=value), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as exit_context:
                    binder.main(["--pages-per-tab", value])
                self.assertEqual(exit_context.exception.code, 2)


@unittest.skipUnless(importlib.util.find_spec("reportlab"), "ReportLab is not installed")
class ArtifactTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("pdftotext"), "PDF text extraction requires Poppler's pdftotext")
    def test_opening_pdf_preserves_line_and_paragraph_breaks(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "opening.md"
            source.write_text("Alpha  \nBeta\n\nGamma\n", encoding="utf-8")
            with patch.object(binder, "OPENING_MARKDOWN", source), redirect_stdout(io.StringIO()):
                binder.main(["--output-dir", str(directory)])
            extraction = subprocess.run(
                ["pdftotext", "-f", "1", "-l", "1", "-bbox",
                 str(directory / "binder.pdf"), "-"],
                check=True, capture_output=True, text=True,
            )
            root = ET.fromstring(extraction.stdout)
            words = root.findall(".//{http://www.w3.org/1999/xhtml}word")
            positions = {
                word.text: float(word.attrib["yMin"])
                for word in words if word.text in {"Alpha", "Beta", "Gamma"}
            }
            # Check printed spacing independently of the editable instructions.
            self.assertAlmostEqual(positions["Beta"] - positions["Alpha"], 15)
            self.assertAlmostEqual(positions["Gamma"] - positions["Beta"], 30)

    def test_pdf_and_manifest_generation_is_reproducible(self):
        with tempfile.TemporaryDirectory() as temporary:
            dirs = [Path(temporary) / name for name in ("first", "second")]
            for directory in dirs:
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(binder.main(["--output-dir", str(directory)]), 0)
            pdf = (dirs[0] / "binder.pdf").read_bytes()
            self.assertTrue(pdf.startswith(b"%PDF-"))
            self.assertEqual(len(re.findall(rb"/Type\s*/Page\b", pdf)), 46)
            self.assertEqual(len(re.findall(rb"/MediaBox\s*\[\s*0\s+0\s+612\s+792\s*\]", pdf)), 46)
            self.assertEqual(pdf, (dirs[1] / "binder.pdf").read_bytes())
            self.assertEqual((dirs[0] / "manifest.json").read_bytes(),
                             (dirs[1] / "manifest.json").read_bytes())
            manifest = json.loads((dirs[0] / "manifest.json").read_text())
            self.assertEqual(len(manifest["rows"]), 267)
            self.assertEqual(manifest["rows"][-1]["address"], "3-7-1-3")

    def test_other_packing_layouts_render(self):
        with tempfile.TemporaryDirectory() as temporary:
            for pages in (1, 5, 100):
                with self.subTest(pages_per_tab=pages), redirect_stdout(io.StringIO()):
                    directory = Path(temporary) / str(pages)
                    binder.main(["--pages-per-tab", str(pages), "--output-dir", str(directory)])
                    pdf = (directory / "binder.pdf").read_bytes()
                    self.assertEqual(len(re.findall(rb"/Type\s*/Page\b", pdf)), 46)


if __name__ == "__main__":
    unittest.main()
