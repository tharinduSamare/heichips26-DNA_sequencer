# SPDX-FileCopyrightText: 2026 Simon Dorrer and Harald Pretl
# SPDX-License-Identifier: Apache-2.0 WITH SHL-2.1
#
# cocotb testbench for the heichips26_dna_sequencer macro.
#
# It drives the chip-level pins (ui_in / uio_in / uo_out) with the same
# register protocol that testbenches/verilog/accelerator_tb.sv uses on the
# internal `accelerator` module, and checks the Smith-Waterman scores against
# the golden vectors in scripts/output/.
#
#   make sim-rtl-cocotb CELL=heichips26_dna_sequencer   # RTL sources
#   make sim-gl-cocotb  CELL=heichips26_dna_sequencer   # yosys/LibreLane netlist
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
import logging
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

logger = logging.getLogger("heichips26_dna_sequencer_tb")


def _clog2(value):
    """$clog2() as defined by IEEE 1800: ceil(log2(value))."""
    return max(0, (value - 1).bit_length())


def _read_macros(path=RTL_DIR / "macros.svh"):
    """Pull the `define values this testbench cares about out of macros.svh."""
    defaults = {"N": 8, "MATCH": 2}
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

# status_reg = {..., fifo_empty, fifo_full, result_valid}
STATUS_RESULT_VALID = 1 << 0
STATUS_FIFO_FULL    = 1 << 1
STATUS_FIFO_EMPTY   = 1 << 2

PIPELINE_DELAY  = 4                                  # idle cycles between the two FIFO half-writes
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
    (same ordering as read_s_seq_from_file()/read_t_seq_from_file() in accelerator_tb.sv).
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

    Reading STATUS_ADDR also clears the result_valid bit (read-to-clear).
    """
    await FallingEdge(dut.clk)
    _drive(dut, addr=addr, rd_en=1)
    await FallingEdge(dut.clk)
    _drive(dut)
    return _sig_int(dut.uo_out, "uo_out") & DATA_MASK


async def send_seq(dut, word):
    """Push one {seq_type, seq} word into the FIFO as a low and a high half-write."""
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


async def wait_not_full(dut):
    return await poll_status(dut, lambda s: not (s & STATUS_FIFO_FULL), "the FIFO to drain")


async def wait_result_valid(dut):
    return await poll_status(dut, lambda s: s & STATUS_RESULT_VALID, "a valid result")


async def run_case(dut, s_word, t_word, send_s=True):
    """Feed one (S, T) pair through the accelerator and return the alignment score."""
    if send_s:
        await wait_not_full(dut)
        await FallingEdge(dut.clk)
        await send_seq(dut, s_word)

    await wait_not_full(dut)
    await send_seq(dut, t_word)

    await wait_result_valid(dut)
    return await read_reg(dut, RESULT_ADDR)


# ------------------------------------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------------------------------------

@cocotb.test()
async def test_reset_state(dut):
    """After reset the outputs are cleared and the status register reports an empty FIFO."""
    logger.info("Startup sequence...")
    await start_up(dut)

    assert _sig_int(dut.uo_out, "uo_out") == 0, \
        f"uo_out not zero after reset (got {dut.uo_out.value})"

    status = await read_reg(dut, STATUS_ADDR)
    assert status & STATUS_FIFO_EMPTY, f"FIFO not empty after reset (status {status:#05b})"
    assert not status & STATUS_FIFO_FULL, f"FIFO full after reset (status {status:#05b})"
    assert not status & STATUS_RESULT_VALID, f"result valid after reset (status {status:#05b})"

    logger.info("Done!")


@cocotb.test()
async def test_bidirectional_pins_are_inputs(dut):
    """uio_oe / uio_out are tied off, so the uio bus stays an input."""
    logger.info("Startup sequence...")
    await start_up(dut)

    await ClockCycles(dut.clk, 4)

    assert _sig_int(dut.uio_oe, "uio_oe") == 0, \
        f"uio_oe must be 0 (all inputs), got {dut.uio_oe.value}"
    assert _sig_int(dut.uio_out, "uio_out") == 0, \
        f"uio_out must be 0, got {dut.uio_out.value}"

    logger.info("Done!")


@cocotb.test()
async def test_alignment_scores(dut):
    """Each (S, T) pair from scripts/output/ must produce the golden Smith-Waterman score."""
    vectors = _load_vectors()

    logger.info("Startup sequence...")
    await start_up(dut)

    logger.info("Running %d test case(s) from %s (%s netlist)...",
                len(vectors), VECTOR_DIR, "gate-level" if gl else "RTL")

    failures = []
    for i, (s_word, t_word, expected) in enumerate(vectors):
        result = await run_case(dut, s_word, t_word)

        if result == expected:
            logger.info("[%2d] correct result: %d", i, result)
        else:
            logger.error("[%2d] wrong result: %d, expected %d (S=%05x T=%05x)",
                         i, result, expected, s_word, t_word)
            failures.append((i, result, expected))

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
        # Reusing the loaded S only makes sense when every case aligns against the same S.
        logger.warning("skipped: seq1.txt holds different S sequences, S cannot be shared")
        return

    logger.info("Startup sequence...")
    await start_up(dut)

    logger.info("Streaming %d T sequence(s) against a single S sequence...", len(vectors))

    failures = []
    for i, (s_word, t_word, expected) in enumerate(vectors):
        result = await run_case(dut, s_word, t_word, send_s=(i == 0))

        if result == expected:
            logger.info("[%2d] correct result: %d", i, result)
        else:
            logger.error("[%2d] wrong result: %d, expected %d", i, result, expected)
            failures.append((i, result, expected))

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
    """Locate the synthesised netlist: GL_NETLIST, then the copied/flow outputs, then the last run."""
    if os.getenv("GL_NETLIST"):
        path = Path(os.environ["GL_NETLIST"]).expanduser()
        assert path.is_file(), f"GL_NETLIST={path} does not exist"
        return path

    for rel in (f"netlist/nl/{hdl_toplevel}.nl.v",
                f"final/nl/{hdl_toplevel}.nl.v",
                f"flow/final/nl/{hdl_toplevel}.nl.v"):
        path = MACRO_DIR / rel
        if path.is_file():
            return path

    runs = sorted((MACRO_DIR / "flow" / "librelane" / "runs").glob("*/*-yosys-synthesis"))
    for step in reversed(runs):
        path = step / f"{hdl_toplevel}.nl.v"
        if path.is_file():
            return path

    raise FileNotFoundError(
        f"no gate-level netlist found for {hdl_toplevel}; run `make librelane copy-netlist` "
        f"or point GL_NETLIST at one")


def heichips26_dna_sequencer_runner():

    sources  = []
    defines  = {}
    includes = [RTL_DIR, SRC_DIR]

    if gl:
        pdk_root = _resolve_pdk_root()
        cell_lib = Path(pdk_root) / pdk / "libs.ref" / scl / "verilog"

        # SCL models (UDP primitives first, they are referenced by the cell models)
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
        # Same file list (and order) as SRCS in the Makefile.
        sources += [
            SRC_DIR / "max.sv",
            SRC_DIR / "st_lut.sv",
            SRC_DIR / "PE.sv",
            SRC_DIR / "systolic_array.sv",
            SRC_DIR / "fifo.sv",
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
        build_args = ["--timing", "--trace", "--trace-fst", "--trace-structs"]

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
