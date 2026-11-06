import itertools
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from io_map import compile_map, evaluate, lamp_logic, run_case

ROOT = Path(__file__).resolve().parents[1]


def fixture(name):
    return json.loads((ROOT / "examples" / f"{name}.json").read_text(encoding="utf-8"))


class MappingTests(unittest.TestCase):
    def test_original_documented_snapshot(self):
        self.assertEqual(run_case(fixture("original")), {
            "inputs": {"part_present": 1, "bin_full": 0},
            "commands": {"lamp_on": 1}, "output_image": {"%QX0.0": 1},
        })

    def test_remapped_documented_snapshot(self):
        self.assertEqual(run_case(fixture("remapped")), {
            "inputs": {"part_present": 1, "bin_full": 0},
            "commands": {"lamp_on": 1}, "output_image": {"%QX3.2": 0},
        })

    def test_full_bin_documented_snapshot(self):
        self.assertEqual(run_case(fixture("full-bin")), {
            "inputs": {"part_present": 1, "bin_full": 1},
            "commands": {"lamp_on": 0}, "output_image": {"%QX0.0": 0},
        })

    def test_all_input_combinations_across_maps(self):
        for part, raw_bin in itertools.product((0, 1), repeat=2):
            with self.subTest(part=part, raw_bin=raw_bin):
                a, b = fixture("original"), fixture("remapped")
                a["input_image"].update({"%IX0.0": part, "%IX0.1": raw_bin})
                b["input_image"].update({"%IX2.4": part, "%IX2.5": raw_bin})
                lhs, rhs = run_case(a), run_case(b)
                expected = {(0, 0): 0, (0, 1): 0, (1, 0): 0, (1, 1): 1}[part, raw_bin]
                self.assertEqual(lhs["inputs"], rhs["inputs"])
                self.assertEqual(lhs["commands"], {"lamp_on": expected})
                self.assertEqual(rhs["commands"], {"lamp_on": expected})
                self.assertEqual(lhs["output_image"]["%QX0.0"], expected)
                self.assertEqual(rhs["output_image"]["%QX3.2"], 1 - expected)

    def test_duplicate_address(self):
        with self.assertRaisesRegex(ValueError, r"duplicate address %IX0\.0"):
            run_case(fixture("duplicate"))

    def test_duplicate_tag(self):
        case = fixture("original")
        case["map"]["channels"][1]["tag"] = "part_present"
        with self.assertRaisesRegex(ValueError, "duplicate tag"):
            run_case(case)

    def test_reject_alias_direction_and_noncanonical_addresses(self):
        for address, error in [("%QX0.0", "direction"), ("%IX00.0", "expected"),
                               ("%IX0.8", "expected"), ("%IB0", "expected")]:
            with self.subTest(address=address):
                case = fixture("original")
                case["map"]["channels"][0]["address"] = address
                with self.assertRaisesRegex(ValueError, error):
                    run_case(case)

    def test_incomplete_or_wrong_image_fails_before_logic(self):
        case = fixture("original")
        mapping = compile_map(case["map"])
        def must_not_run(_):
            self.fail("logic ran before input validation")
        for image in ({"%IX0.0": 1}, {"%IX0.0": 1, "%IX0.1": 1, "%IX0.2": 1},
                      {"%IX0.0": True, "%IX0.1": 1}, {"%IX0.0": 2, "%IX0.1": 1}):
            with self.subTest(image=image), self.assertRaises(ValueError):
                evaluate(mapping, image, must_not_run)

    def test_output_command_name_and_bit_validation(self):
        case = fixture("original")
        mapping = compile_map(case["map"])
        for command in ({}, {"typo": 1}, {"lamp_on": "1"}, {"lamp_on": True}):
            with self.subTest(command=command), self.assertRaises(ValueError):
                evaluate(mapping, case["input_image"], lambda _: command)

    def test_logic_receives_isolated_named_inputs(self):
        case = fixture("original")
        mapping = compile_map(case["map"])
        def mutating_logic(tags):
            result = lamp_logic(tags)
            tags["part_present"] = 0
            return result
        output = evaluate(mapping, case["input_image"], mutating_logic)
        self.assertEqual(output["inputs"]["part_present"], 1)
        self.assertEqual(case["input_image"]["%IX0.0"], 1)

    def test_cli_rejects_duplicate_json_key_without_partial_output(self):
        with tempfile.TemporaryDirectory() as directory:
            case = Path(directory) / "case.json"
            case.write_text('{"map":{},"input_image":{},"input_image":{}}', encoding="utf-8")
            result = subprocess.run([sys.executable, str(ROOT / "io_map.py"), str(case)],
                                    capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("duplicate JSON key 'input_image'", result.stderr)


if __name__ == "__main__":
    unittest.main()
