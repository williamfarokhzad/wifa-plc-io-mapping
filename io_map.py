"""Map symbolic digital I/O to an offline PLC process image."""
import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re

ADDRESS = re.compile(r"%([IQ])X(0|[1-9][0-9]{0,3})\.([0-7])")
TAG = re.compile(r"[a-z][a-z0-9_]*")


def fields(value, expected, label):
    if not isinstance(value, dict):
        raise ValueError(f"{label}: expected an object")
    missing, extra = expected - value.keys(), value.keys() - expected
    if missing or extra:
        raise ValueError(f"{label}: missing {sorted(missing)}; unexpected {sorted(extra)}")


def bit(value, label):
    if type(value) is not int or value not in (0, 1):
        raise ValueError(f"{label}: expected integer 0 or 1")
    return value


@dataclass(frozen=True)
class Channel:
    tag: str
    address: str
    direction: str
    active_low: bool

    def invert_if_needed(self, value):
        # XOR by 1 flips 0 and 1; XOR by 0 keeps them.
        return value ^ int(self.active_low)


def compile_map(spec):
    """Validate the whole map before allowing any snapshot to run."""
    fields(spec, {"channels"}, "map")
    if not isinstance(spec["channels"], list) or not spec["channels"]:
        raise ValueError("channels: expected a nonempty array")
    compiled, addresses = {}, set()
    for index, row in enumerate(spec["channels"], start=1):
        label = f"channel {index}"
        fields(row, {"tag", "address", "direction", "active_low"}, label)
        tag, address = row["tag"], row["address"]
        direction, active_low = row["direction"], row["active_low"]
        if not isinstance(tag, str) or not TAG.fullmatch(tag):
            raise ValueError(f"{label}: invalid symbolic tag")
        if tag in compiled:
            raise ValueError(f"{label}: duplicate tag {tag}")
        match = ADDRESS.fullmatch(address) if isinstance(address, str) else None
        if not match:
            raise ValueError(f"{label}: expected %IXbyte.bit or %QXbyte.bit (bit 0–7)")
        if direction not in ("input", "output") or match[1] != ("I" if direction == "input" else "Q"):
            raise ValueError(f"{label}: direction does not match {address}")
        if type(active_low) is not bool:
            raise ValueError(f"{label}: active_low must be true or false")
        if address in addresses:
            raise ValueError(f"{label}: duplicate address {address}")
        addresses.add(address)
        compiled[tag] = Channel(tag, address, direction, active_low)
    return compiled


def evaluate(compiled, input_image, logic):
    """Decode a supplied input snapshot, call logic once, encode its output image."""
    inputs = [ch for ch in compiled.values() if ch.direction == "input"]
    outputs = [ch for ch in compiled.values() if ch.direction == "output"]
    fields(input_image, {ch.address for ch in inputs}, "input image")
    named = {ch.tag: ch.invert_if_needed(bit(input_image[ch.address], ch.address)) for ch in inputs}
    commanded = logic(named.copy())
    fields(commanded, {ch.tag for ch in outputs}, "output commands")
    out = {ch.address: ch.invert_if_needed(bit(commanded[ch.tag], ch.tag)) for ch in outputs}
    return {"inputs": named, "commands": commanded, "output_image": out}


def lamp_logic(inputs):
    """A desk lamp model with two named inputs, no memory, and no hardware."""
    return {"lamp_on": int(inputs["part_present"] == 1 and inputs["bin_full"] == 0)}


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key {key!r}")
        value[key] = item
    return value


def run_case(case):
    fields(case, {"map", "input_image"}, "case")
    mapping = compile_map(case["map"])
    required = {"part_present": "input", "bin_full": "input", "lamp_on": "output"}
    if {name: ch.direction for name, ch in mapping.items()} != required:
        raise ValueError("lamp example requires inputs part_present, bin_full and output lamp_on")
    return evaluate(mapping, case["input_image"], lamp_logic)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("case", type=Path, help="JSON case to replay")
    arg = cli.parse_args()
    try:
        case = json.loads(arg.case.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
        result = run_case(case)
    except (OSError, ValueError) as exc:
        cli.exit(2, f"error: {exc}\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
