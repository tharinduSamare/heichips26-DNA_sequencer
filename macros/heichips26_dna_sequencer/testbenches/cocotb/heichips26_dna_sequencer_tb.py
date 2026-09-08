# SPDX-FileCopyrightText: 2026 Simon Dorrer and Harald Pretl
# SPDX-License-Identifier: Apache-2.0 WITH SHL-2.1
#
# cocotb testbench for the heichips26_dna_sequencer macro.
#
# It drives the chip-level pins (ui_in / uio_in / uo_out) with the same
# register protocol that testbenches/verilog/heichips26_dna_sequencer_tb.sv
# uses, and checks the Smith-Waterman scores against the golden vectors in
# scripts/output/.
#
#   make sim-rtl-cocotb CELL=heichips26_dna_sequencer   # RTL sources
#   make sim-gl-cocotb  CELL=heichips26_dna_sequencer   # yosys/LibreLane netlist
#
# The accelerator now buffers on both sides: seq_fifo holds queued input
# sequences and result_fifo holds finished scores, both `FIFO_DEPTH deep. The
# Verilog bench exploits that by working in "beats" - it pushes up to
# BEAT_SIZE half-word writes without reading anything back, then drains one
# result per T sequence it sent. This bench mirrors that flow, so a regression
# in the queueing shows up here too.
#
# Note on RTL mode: iverilog cannot parse the `state inside {...}` concurrent
# assertion in rtl/accelerator/systolic_array.sv (`-gno-assertions` suppresses the
# other assertions but the `inside` expression still fails to parse). Drop or guard
# that one assertion to run the RTL flavour with iverilog; GL mode is unaffected,
# since the synthesised netlist contains no assertions.
#
# Environment overrides:
#   GL=1              simulate the gate-level netlist instead of the RTL
#   GL_NETLIST=<path> use this netlist instead of the auto-discovered one
#   PDK_ROOT / PDK / SCL   standard-cell models used in GL mode
#   VECTOR_DIR=<path> directory holding seq1.txt / seq2.txt / final_op.txt
#   TEST_CASES=<n>    only run the first n vectors
#   CLK_PERIOD_NS=<f> clock period (default 10 ns, matching CLOCK_PERIOD)

import os
import re
import hashlib
import logging
from collections import deque
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer, RisingEdge, FallingEdge, ClockCycles
from cocotb_tools.runner import get_runner

sim      = os.getenv("SIM", "icarus")
pdk      = os.getenv("PDK", "ihp-sg13cmos5l")
scl      = os.getenv("SCL", "sg13cmos5l_stdcell")
# GL=1 selects the gate-level netlist; anything else (unset, "0", "") stays in RTL mode.
gl       = os.getenv("GL", "0").strip().lower() in ("1", "true", "yes", "on")

hdl_toplevel = "heichips26_dna_sequencer"

PROJ_PATH = Path(__file__).resolve().parent          # testbenches/cocotb
MACRO_DIR = PROJ_PATH.parent.parent                  # macros/heichips26_dna_sequencer
RTL_DIR   = MACRO_DIR / "rtl"
SRC_DIR   = RTL_DIR / "accelerator"

# top-level logger name sits outside that tree and its records go nowhere.
logger = logging.getLogger("cocotb.heichips26_dna_sequencer_tb")


def _clog2(value):
    """$clog2() as defined by IEEE 1800: ceil(log2(value))."""
    return max(0, (value - 1).bit_length())


def _read_macros(path=RTL_DIR / "macros.svh"):
    """Pull the `define values this testbench cares about out of macros.svh."""
    defaults = {"N": 8, "MATCH": 2, "FIFO_DEPTH": 16}
    try:
        text = Path(path).read_text()
    except OSError:
        return defaults

    out = dict(defaults)
    for name in defaults:
        m = re.search(rf"^\s*`define\s+{name}\s+(-?\d+)", text, re.MULTILINE)
        if m:
            out[name] = int(m.group(1))
    return out


_MACROS = _read_macros()

N               = _MACROS["N"]                       # sequence length / number of PEs
MATCH           = _MACROS["MATCH"]
FIFO_DEPTH      = _MACROS["FIFO_DEPTH"]              # depth of seq_fifo and result_fifo
SYMBOL_BITS     = 2                                  # bits per base inside the FIFO word
CHA_SEQ_LENGTH  = N * SYMBOL_BITS                    # payload bits of a FIFO word
MAX_SCORE       = N * MATCH
REG_WIDTH       = _clog2(MAX_SCORE + 1) + 1          # width of data_out (== uo_out[REG_WIDTH-1:0])
DATA_MASK       = (1 << REG_WIDTH) - 1

S_SEQ_PREFIX    = 1
T_SEQ_PREFIX    = 0

FIFO_LOW_ADDR   = 0
FIFO_HIGH_ADDR  = 1
RESULT_ADDR     = 0
STATUS_ADDR     = 1

# status_reg = {'0, seq_fifo_full, seq_fifo_empty, result_fifo_full, result_fifo_empty}
STATUS_RESULT_FIFO_EMPTY = 1 << 0
STATUS_RESULT_FIFO_FULL  = 1 << 1
STATUS_SEQ_FIFO_EMPTY    = 1 << 2
STATUS_SEQ_FIFO_FULL     = 1 << 3

PIPELINE_DELAY  = 0                                  # idle cycles between the two FIFO half-writes
BEAT_SIZE       = 8                                  # half-word writes pushed before draining results
CYCLES_PER_CALC = 21                                 # worst case per T sequence, plus margin

CLK_PERIOD_NS   = float(os.getenv("CLK_PERIOD_NS", "10"))   # CLOCK_PERIOD from flow/librelane/config.yaml
POLL_TIMEOUT    = 2000                               # max register reads before a poll gives up

VECTOR_DIR      = Path(os.getenv("VECTOR_DIR", MACRO_DIR / "scripts" / "output"))


def _parse_seq_line(line):
    """'[11,10,...,01]' -> [0b11, 0b10, ..., 0b01]"""
    body = line[line.index("[") + 1: line.index("]")]
    return [int(tok.strip(), 2) & 0b11 for tok in body.split(",")]


def _pack_seq(bases, reverse, prefix):
    """Pack 2-bit bases into a FIFO word {seq_type, seq[CHA_SEQ_LENGTH-1:0]}.

    The S sequence is fed into the array back-to-front, the T sequence front-to-back
    (same ordering as read_s_seq_from_file()/read_t_seq_from_file() in the Verilog bench).
    """
    assert len(bases) == N, f"expected {N} bases per sequence, got {len(bases)}"
    word = 0
    for i, base in enumerate(bases):
        pos = (N - 1 - i) if reverse else i
        word |= base << (pos * SYMBOL_BITS)
    return word | (prefix << CHA_SEQ_LENGTH)


def _load_vectors(vector_dir=VECTOR_DIR):
    """Read seq1.txt / seq2.txt / final_op.txt into a list of (s_word, t_word, score)."""
    def lines(name):
        path = Path(vector_dir) / name
        assert path.is_file(), f"missing vector file {path}"
        return [ln for ln in path.read_text().splitlines() if ln.strip()]

    s_lines, t_lines, op_lines = lines("seq1.txt"), lines("seq2.txt"), lines("final_op.txt")

    count = min(len(s_lines), len(t_lines), len(op_lines))
    assert count > 0, f"no test cases found in {vector_dir}"

    limit = os.getenv("TEST_CASES")
    if limit:
        count = min(count, int(limit))

    return [
        (
            _pack_seq(_parse_seq_line(s_lines[i]), reverse=True,  prefix=S_SEQ_PREFIX),
            _pack_seq(_parse_seq_line(t_lines[i]), reverse=False, prefix=T_SEQ_PREFIX),
            int(op_lines[i].strip()),
        )
        for i in range(count)
    ]


# ------------------------------------------------------------------------------------------------
# Pin-level helpers
#
#   ui_in[0] = addr, ui_in[1] = wr_en, ui_in[2] = rd_en, ui_in[3] = seq_type
#   uio_in[7:0] = seq_in (one FIFO half-word)
#   uo_out[REG_WIDTH-1:0] = data_out
# ------------------------------------------------------------------------------------------------

def _sig_int(handle, what):
    """int() of a signal, with a readable error when the netlist drives X/Z."""
    bits = str(handle.value)
    assert all(b in "01" for b in bits), f"{what} is not fully driven: {bits}"
    return int(bits, 2)


def _drive(dut, addr=0, wr_en=0, rd_en=0, seq_type=0, seq_byte=0):
    dut.ui_in.value = ((addr & 1) << 0) | ((wr_en & 1) << 1) | ((rd_en & 1) << 2) | ((seq_type & 1) << 3)
    dut.uio_in.value = seq_byte & 0xFF


async def start_clock(clock, period_ns=CLK_PERIOD_NS):
    """Start the clock with the given period."""
    cocotb.start_soon(Clock(clock, period_ns, "ns").start())


async def reset(dut, cycles=5):
    """Pulse the active-low reset and park all inputs in their idle state."""
    logger.info("Reset asserted...")

    dut.ena.value = 1
    _drive(dut)
    dut.rst_n.value = 0

    await ClockCycles(dut.clk, cycles)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1
    await FallingEdge(dut.clk)

    logger.info("Reset deasserted.")


async def start_up(dut):
    """Startup sequence: clock + reset, all control pins idle."""
    await start_clock(dut.clk)
    await reset(dut)


async def read_reg(dut, addr):
    """Single-cycle register read; returns data_out (uo_out[REG_WIDTH-1:0]).

    Reading RESULT_ADDR pops one entry off the result FIFO, so only call it once
    per score you intend to consume. Reading STATUS_ADDR has no side effects.
    """
    await FallingEdge(dut.clk)
    _drive(dut, addr=addr, rd_en=1)
    await FallingEdge(dut.clk)
    _drive(dut)
    return _sig_int(dut.uo_out, "uo_out") & DATA_MASK


async def send_seq(dut, word):
    """Push one {seq_type, seq} word into seq_fifo as a low and a high half-write."""
    await FallingEdge(dut.clk)
    _drive(dut, addr=FIFO_LOW_ADDR, wr_en=1, seq_byte=word & 0xFF)
    await FallingEdge(dut.clk)
    _drive(dut)

    for _ in range(PIPELINE_DELAY):
        await FallingEdge(dut.clk)

    _drive(dut,
           addr=FIFO_HIGH_ADDR,
           wr_en=1,
           seq_byte=(word >> N) & 0xFF,
           seq_type=(word >> CHA_SEQ_LENGTH) & 1)
    await FallingEdge(dut.clk)
    _drive(dut)


async def poll_status(dut, done, what):
    """Read the status register until `done(status)` holds; returns the last status."""
    for _ in range(POLL_TIMEOUT):
        status = await read_reg(dut, STATUS_ADDR)
        if done(status):
            return status
    raise AssertionError(f"timeout after {POLL_TIMEOUT} status reads waiting for {what}")


async def wait_seq_fifo_not_full(dut):
    return await poll_status(dut, lambda s: not (s & STATUS_SEQ_FIFO_FULL),
                             "the sequence FIFO to drain")


async def wait_result_available(dut):
    return await poll_status(dut, lambda s: not (s & STATUS_RESULT_FIFO_EMPTY),
                             "a result to arrive")


async def run_beats(dut, vectors, test_type):
    """Feed `vectors` through the accelerator in beats, exactly as the Verilog bench does.

    Each beat pushes at most BEAT_SIZE sequences into seq_fifo without reading
    anything back, waits for the array to chew through them, then drains one
    result per T sequence that was sent. Returns (failures, leftover_expected).
    """
    total = len(vectors)
    expected_q = deque()
    failures = []

    idx = 0           # next vector to consume, mirroring the sequential file reads
    checked = 0       # results verified so far, used only for the log line
    test_count = 0
    while test_count < total:
        input_count = 0
        t_count = 0
        s_count = 0

        # ---- fill one beat -------------------------------------------------
        while input_count < BEAT_SIZE and (test_count + t_count) < total:
            s_word, t_word, expected = vectors[idx]
            idx += 1
            expected_q.append(expected)

            # send s_seq (skipped after the first case when a single S is shared)
            if not (test_type == 1 and (test_count + t_count) > 0):
                if input_count >= BEAT_SIZE:
                    break
                await send_seq(dut, s_word)
                s_count += 1
                input_count += 1

            # send t_seq
            if input_count >= BEAT_SIZE:
                break
            await send_seq(dut, t_word)
            t_count += 1
            input_count += 1

        assert t_count > 0, \
            f"beat pushed {s_count} S sequence(s) but no T sequence; BEAT_SIZE={BEAT_SIZE} " \
            f"is too small to make progress"

        await ClockCycles(dut.clk, t_count * CYCLES_PER_CALC, rising=False)
        await wait_result_available(dut)

        # ---- drain one score per T sequence sent ---------------------------
        for _ in range(t_count):
            result = await read_reg(dut, RESULT_ADDR)
            expected = expected_q.popleft()
            if result == expected:
                logger.info("[%2d] correct result: %d", checked, result)
            else:
                logger.error("[%2d] wrong result: %d, expected %d", checked, result, expected)
                failures.append((checked, result, expected))
            checked += 1

        test_count += t_count

    return failures, expected_q


# ------------------------------------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------------------------------------

MISMATCH_HINT = (
    "this usually means the netlist under test was built from different RTL "
    f"than rtl/macros.svh describes (N={N}, REG_WIDTH={REG_WIDTH}); "
    "check the netlist reported by the runner and set GL_NETLIST if it is stale"
)


@cocotb.test()
async def test_netlist_matches_rtl(dut):
    """Tie-offs that identify the design: uio is input-only and uo_out[7:REG_WIDTH] is 0.

    This runs first because it is the cheapest way to notice that GL is simulating
    the wrong netlist; every later failure would otherwise be a confusing symptom.
    """
    logger.info("Startup sequence...")
    await start_up(dut)

    await ClockCycles(dut.clk, 4)

    assert _sig_int(dut.uio_oe, "uio_oe") == 0, \
        f"uio_oe must be 0 (uio is input-only), got {dut.uio_oe.value} -- {MISMATCH_HINT}"
    assert _sig_int(dut.uio_out, "uio_out") == 0, \
        f"uio_out must be 0, got {dut.uio_out.value} -- {MISMATCH_HINT}"

    unused = _sig_int(dut.uo_out, "uo_out") >> REG_WIDTH
    assert unused == 0, \
        f"uo_out[7:{REG_WIDTH}] must be tied to 0, got {dut.uo_out.value} -- {MISMATCH_HINT}"

    logger.info("Done!")


@cocotb.test()
async def test_reset_state(dut):
    """After reset both FIFOs report empty and neither reports full."""
    logger.info("Startup sequence...")
    await start_up(dut)

    assert _sig_int(dut.uo_out, "uo_out") == 0, \
        f"uo_out not zero after reset (got {dut.uo_out.value})"

    status = await read_reg(dut, STATUS_ADDR)
    assert status & STATUS_SEQ_FIFO_EMPTY, \
        f"sequence FIFO not empty after reset (status {status:#06b})"
    assert not status & STATUS_SEQ_FIFO_FULL, \
        f"sequence FIFO full after reset (status {status:#06b})"
    assert status & STATUS_RESULT_FIFO_EMPTY, \
        f"result FIFO not empty after reset (status {status:#06b})"
    assert not status & STATUS_RESULT_FIFO_FULL, \
        f"result FIFO full after reset (status {status:#06b})"

    logger.info("Done!")


@cocotb.test()
async def test_seq_fifo_accepts_a_full_beat(dut):
    """A whole beat can be queued without the sequence FIFO going full or losing entries.

    BEAT_SIZE writes must fit in a `FIFO_DEPTH-deep seq_fifo; if the depth is ever
    reduced below BEAT_SIZE this catches it before the score checks turn into a
    confusing wall of wrong values.
    """
    vectors = _load_vectors()

    logger.info("Startup sequence...")
    await start_up(dut)

    status = await read_reg(dut, STATUS_ADDR)
    assert status & STATUS_SEQ_FIFO_EMPTY, "sequence FIFO should start empty"

    queued = min(BEAT_SIZE, 2 * len(vectors))
    for i in range(queued):
        s_word, t_word, _ = vectors[i // 2]
        await send_seq(dut, s_word if i % 2 == 0 else t_word)

    status = await read_reg(dut, STATUS_ADDR)
    assert not status & STATUS_SEQ_FIFO_EMPTY, \
        f"sequence FIFO still reports empty after {queued} writes (status {status:#06b})"
    assert not status & STATUS_SEQ_FIFO_FULL, \
        (f"sequence FIFO went full after {queued} writes but FIFO_DEPTH={FIFO_DEPTH} "
         f"(status {status:#06b}) -- BEAT_SIZE must not exceed FIFO_DEPTH")

    logger.info("Queued %d sequences; seq_fifo neither empty nor full. Done!", queued)


@cocotb.test()
async def test_alignment_scores(dut):
    """Each (S, T) pair from scripts/output/ must produce the golden Smith-Waterman score."""
    vectors = _load_vectors()

    logger.info("Startup sequence...")
    await start_up(dut)

    logger.info("Running %d test case(s) from %s in beats of %d (%s netlist)...",
                len(vectors), VECTOR_DIR, BEAT_SIZE, "gate-level" if gl else "RTL")

    failures, leftover = await run_beats(dut, vectors, test_type=2)

    assert not leftover, \
        f"{len(leftover)} expected score(s) were never checked -- the design returned " \
        f"fewer results than T sequences sent"
    assert not failures, \
        f"{len(failures)}/{len(vectors)} case(s) mismatched: " + \
        ", ".join(f"#{i}: got {got}, expected {exp}" for i, got, exp in failures)

    logger.info("Done!")


@cocotb.test()
async def test_alignment_scores_shared_s(dut):
    """The loaded S sequence is reused for back-to-back T sequences (S is sent only once)."""
    vectors = _load_vectors()

    s_words = {s for s, _, _ in vectors}
    if len(s_words) != 1:
        logger.warning("skipped: seq1.txt holds different S sequences, S cannot be shared")
        return

    logger.info("Startup sequence...")
    await start_up(dut)

    logger.info("Streaming %d T sequence(s) against a single S sequence...", len(vectors))

    failures, leftover = await run_beats(dut, vectors, test_type=1)

    assert not leftover, \
        f"{len(leftover)} expected score(s) were never checked"
    assert not failures, \
        f"{len(failures)}/{len(vectors)} case(s) mismatched: " + \
        ", ".join(f"#{i}: got {got}, expected {exp}" for i, got, exp in failures)

    logger.info("Done!")


def _resolve_pdk_root():
    """Locate a PDK tree that actually carries the standard-cell Verilog models."""
    candidates = []
    if os.getenv("PDK_ROOT"):
        candidates.append(Path(os.environ["PDK_ROOT"]))
    candidates += [
        MACRO_DIR / "IHP-Open-PDK",
        MACRO_DIR.parent.parent / "IHP-Open-PDK",
        Path("~/.ciel").expanduser(),
    ]

    for root in candidates:
        if (root / pdk / "libs.ref" / scl / "verilog" / f"{scl}.v").is_file():
            return root

    raise FileNotFoundError(
        f"could not find {pdk}/libs.ref/{scl}/verilog/{scl}.v in any of: "
        + ", ".join(str(c) for c in candidates)
        + " -- set PDK_ROOT")


def _resolve_gl_netlist():
    """Locate the synthesised netlist: GL_NETLIST, then the flow output, then the copies.

    A macro directory can easily end up holding netlists from *different* builds
    (e.g. netlist/ still carrying an older 16-PE run while final/ holds the 8-PE one).
    Silently picking one of those produces a wall of unrelated failures, so compare
    every candidate and shout if they disagree.
    """
    if os.getenv("GL_NETLIST"):
        path = Path(os.environ["GL_NETLIST"]).expanduser()
        assert path.is_file(), f"GL_NETLIST={path} does not exist"
        return path

    candidates = [MACRO_DIR / rel for rel in (
        f"flow/final/nl/{hdl_toplevel}.nl.v",   # live LibreLane output
        f"final/nl/{hdl_toplevel}.nl.v",        # make copy-final
        f"netlist/nl/{hdl_toplevel}.nl.v",      # make copy-netlist
    )]
    candidates += [step / f"{hdl_toplevel}.nl.v"
                   for step in sorted((MACRO_DIR / "flow" / "librelane" / "runs")
                                      .glob("*/*-yosys-synthesis"), reverse=True)]

    found = [c for c in candidates if c.is_file()]
    if not found:
        raise FileNotFoundError(
            f"no gate-level netlist found for {hdl_toplevel}; run `make librelane copy-netlist` "
            f"or point GL_NETLIST at one")

    digests = {c: hashlib.md5(c.read_bytes()).hexdigest() for c in found}
    if len(set(digests.values())) > 1:
        print(f"[gl] WARNING: the netlists in this macro are NOT from the same build:")
        for c in found:
            marker = "  <-- using" if c == found[0] else ""
            print(f"[gl]   {digests[c][:8]}  {c.stat().st_size:>8} B  "
                  f"{c.relative_to(MACRO_DIR)}{marker}")
        print("[gl]   Re-run the flow and `make copy-netlist copy-final` so they agree, "
              "or set GL_NETLIST explicitly.")

    return found[0]


def heichips26_dna_sequencer_runner():

    sources  = []
    defines  = {}
    includes = [RTL_DIR, SRC_DIR]

    if gl:
        pdk_root = _resolve_pdk_root()
        cell_lib = Path(pdk_root) / pdk / "libs.ref" / scl / "verilog"

        udp = cell_lib / f"{scl.replace('_stdcell', '')}_udp.v"
        if udp.is_file():
            sources.append(udp)
        sources.append(cell_lib / f"{scl}.v")

        # Unpowered gate-level netlist of the macro.
        # Unpowered netlist: USE_POWER_PINS must NOT be defined at all
        # (passing USE_POWER_PINS=False would still define the macro).
        netlist = _resolve_gl_netlist()
        sources.append(netlist)

        print(f"[gl] standard cells: {cell_lib}")
        print(f"[gl] netlist:        {netlist}")
    else:
        sources += [
            SRC_DIR / "max.sv",
            SRC_DIR / "st_lut.sv",
            SRC_DIR / "PE.sv",
            SRC_DIR / "systolic_array.sv",
            SRC_DIR / "seq_fifo.sv",
            SRC_DIR / "result_fifo.sv",
            SRC_DIR / "accelerator.sv",
            SRC_DIR / "heichips26_dna_sequencer.sv",
        ]

    build_args = []

    if sim == "icarus":
        # -gno-specify:    skip specify blocks; sg13cmos5l_stdcell.v uses
        #                  `ifnone with edge-sensitive paths`, which iverilog can't parse.
        # -gno-assertions: the RTL uses concurrent `assert property` (and `inside`),
        #                  neither of which iverilog supports.
        build_args = ["-DSIM", "-gno-specify", "-gno-assertions"]

    if sim == "verilator":
        # -Wno-fatal: the RTL has many benign width mismatches (ALPHA/BETA vs REG_WIDTH,
        # counter compares); they are lint findings, not build errors.
        build_args = ["--timing", "--trace", "--trace-fst", "--trace-structs", "-Wno-fatal"]

    runner = get_runner(sim)
    runner.build(
        sources=sources,
        hdl_toplevel=hdl_toplevel,
        defines=defines,
        always=True,
        includes=includes,
        build_args=build_args,
        waves=True,
        timescale=("1ns", "1fs")
    )

    plusargs = []

    runner.test(
        hdl_toplevel=hdl_toplevel,
        test_module="heichips26_dna_sequencer_tb",
        plusargs=plusargs,
        waves=True,
    )


if __name__ == "__main__":
    heichips26_dna_sequencer_runner()
