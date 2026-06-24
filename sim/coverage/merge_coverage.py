"""Merge cocotb-coverage YAML reports and gate only declared critical bins."""

import argparse
from pathlib import Path

import yaml


CRITICAL = {
    "neuron.type": ["midget", "parasol"],
    "neuron.stimulus": ["negative", "zero", "moderate", "strong"],
    "neuron.spike_outcome": ["no_spike", "spike"],
    "neuron.voltage_region": ["below_reset", "reset", "subthreshold", "threshold"],
    "controller.foveation_region": ["center", "distance_44", "distance_45", "periphery", "corner"],
    "controller.start_state_x_outcome": [
        "('idle', 'accepted')", "('scanning', 'ignored')", "('draining', 'ignored')"
    ],
    "axis.frame_spike_count": ["zero", "one", "many"],
    "axis.stall_duration": ["zero", "one", "many"],
    "fifo.occupancy": ["empty", "partial", "full"],
    "fifo.event": ["simultaneous_full_read_write", "overflow_drop", "clear_overflow"],
    "dma.packet_kind": ["exact", "short", "long", "stalled"],
    "axil.write_order": ["aw_first", "w_first", "simultaneous"],
    "axil.read_behavior": ["normal", "backpressure"],
    "wrapper.collision": ["dma_vs_axil_write", "dma_vs_axil_read"],
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", action="append", required=True)
    parser.add_argument("--yaml", required=True)
    parser.add_argument("--markdown", required=True)
    args = parser.parse_args()

    merged = {}
    for filename in args.input:
        with open(filename, encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        overlap = set(merged).intersection(data)
        if overlap:
            raise SystemExit(f"duplicate coverage names: {sorted(overlap)}")
        merged.update(data)

    failures = []
    rows = []
    for point, required_bins in CRITICAL.items():
        item = merged.get(point)
        if item is None:
            failures.append(f"missing critical coverpoint {point}")
            continue
        hits = {str(name): count for name, count in item.get("bins:_hits", {}).items()}
        at_least = int(item.get("at_least", 1))
        for required in required_bins:
            count = int(hits.get(required, 0))
            passed = count >= at_least
            rows.append((point, required, count, at_least, passed))
            if not passed:
                failures.append(
                    f"{point} bin {required!r}: {count} hits, requires {at_least}"
                )

    total_size = sum(int(item.get("size", 0)) for item in merged.values())
    total_covered = sum(int(item.get("coverage", 0)) for item in merged.values())
    percentage = 100.0 * total_covered / total_size if total_size else 0.0
    critical_bin_count = sum(len(bins) for bins in CRITICAL.values())
    output = {
        "metadata": {
            "suite": "deterministic functional coverage",
            "overall_percentage_informational": round(percentage, 2),
            "gate": "declared critical bins only",
            "critical_bin_count": critical_bin_count,
        },
        "coverage": merged,
        "critical_bin_gate": {
            "passed": not failures,
            "failures": failures,
        },
    }
    Path(args.yaml).write_text(yaml.safe_dump(output, sort_keys=True), encoding="utf-8")

    lines = [
        "# Functional Coverage Summary",
        "",
        f"- Critical-bin gate: **{'PASS' if not failures else 'FAIL'}**",
        f"- Declared critical bins: **{critical_bin_count}**",
        f"- Overall weighted coverage (informational): **{percentage:.2f}%**",
        "- Gate policy: only the declared critical bins below are gating.",
        "",
        "| Coverpoint | Critical bin | Hits | Required | Result |",
        "|---|---:|---:|---:|---|",
    ]
    lines.extend(
        f"| `{point}` | `{bin_name}` | {hits} | {required} | {'PASS' if passed else 'FAIL'} |"
        for point, bin_name, hits, required, passed in rows
    )
    if failures:
        lines.extend(["", "## Failures", ""])
        lines.extend(f"- {failure}" for failure in failures)
    Path(args.markdown).write_text("\n".join(lines) + "\n", encoding="utf-8")

    if failures:
        raise SystemExit("critical functional coverage bins missed:\n- " + "\n- ".join(failures))


if __name__ == "__main__":
    main()
