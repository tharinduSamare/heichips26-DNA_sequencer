#!/usr/bin/env python3

import argparse
import os
import sys
from pathlib import Path

# benchmark/firmware -> benchmark -> repository root
REPO_ROOT = Path(__file__).resolve().parents[2]

SCRIPTS_DIR = REPO_ROOT / "macros" / "heichips26_dna_sequencer" / "scripts"

sys.path.insert(0, str(SCRIPTS_DIR))
import data_gen_and_validation as dg


# ============================================================
# Memory configuration
# ============================================================

# IMPORTANT:
# The custom RISC-V data memory is WORD addressed.
#
# Therefore:
#
#     LW x1, 1(x2)
#
# means:
#
#     x1 = SRAM[word_address = x2 + 1]
#
# There is NO multiplication by 4 for data-memory addresses.

# ============================================================

RESULT_REG_ADDR = 0x200
STATUS_REG_ADDR = 0x201

FIFO_LOW_ADDR = 0x200
FIFO_HIGH_ADDR = 0x201

MEM_DEPTH = 1024

# Sequence data starts at SRAM word 320.
DATA_START_WORD = 320

# Number of FIFO entries that are filled before
# reading the results.
BEAT_SIZE = 16


# ============================================================
# STATUS register bits
# ============================================================

# STATUS:
#
#   bit 3 = sequence FIFO full
#   bit 2 = sequence FIFO empty
#   bit 1 = result FIFO full
#   bit 0 = result FIFO empty

RESULT_FIFO_EMPTY_BIT = 0


# ============================================================
# Sequence packing
# ============================================================

ENCODING = {
    "A": 0,
    "C": 1,
    "G": 2,
    "T": 3,
    "a": 0,
    "c": 1,
    "g": 2,
    "t": 3,
}


def encode_sequence(seq):
    return [ENCODING[c] for c in seq]


def pack_s_words(seq):
    """
    Matches the SystemVerilog testbench:

        s_seq[(N-1-i)*2 +: 2] = tmp[1:0]

    S type = 1.

    For an 8-base sequence:

        low  = bits [7:0]
        high = bits [15:8]
        bit 8 of high = sequence type = 1
    """

    bases = encode_sequence(seq)

    packed = 0
    n = len(bases)

    for i, base in enumerate(bases):
        packed |= base << ((n - 1 - i) * 2)

    low = packed & 0xFF
    high = (packed >> 8) & 0xFF

    # S type = 1
    high |= (1 << 8)

    return low, high


def pack_t_words(seq):
    """
    Matches the SystemVerilog testbench:

        t_seq[i*2 +: 2] = tmp[1:0]

    T type = 0.
    """

    bases = encode_sequence(seq)

    packed = 0

    for i, base in enumerate(bases):
        packed |= base << (i * 2)

    low = packed & 0xFF
    high = (packed >> 8) & 0xFF

    return low, high


# ============================================================
# RV32I encoders
# ============================================================

def check_reg(r):
    if not 0 <= r <= 31:
        raise ValueError(f"invalid register x{r}")


def signed_imm(imm, bits):
    lo = -(1 << (bits - 1))
    hi = (1 << (bits - 1)) - 1

    if not lo <= imm <= hi:
        raise ValueError(
            f"immediate {imm} does not fit in {bits} bits"
        )

    return imm & ((1 << bits) - 1)


def i_type(imm, rs1, funct3, rd, opcode):
    check_reg(rs1)
    check_reg(rd)

    imm = signed_imm(imm, 12)

    return (
        (imm << 20)
        | (rs1 << 15)
        | (funct3 << 12)
        | (rd << 7)
        | opcode
    )


def s_type(imm, rs1, rs2, funct3):
    check_reg(rs1)
    check_reg(rs2)

    imm = signed_imm(imm, 12)

    return (
        (((imm >> 5) & 0x7F) << 25)
        | (rs2 << 20)
        | (rs1 << 15)
        | (funct3 << 12)
        | ((imm & 0x1F) << 7)
        | 0x23
    )


def b_type(offset, rs1, rs2, funct3=0):
    """
    offset is a PC-relative BYTE offset.

    PC advances by 4 bytes per instruction.
    """

    check_reg(rs1)
    check_reg(rs2)

    if offset % 2:
        raise ValueError(
            "branch offset must be 2-byte aligned"
        )

    if offset < -4096 or offset > 4094:
        raise ValueError(
            "branch offset out of range"
        )

    imm = offset & 0x1FFF

    return (
        (((imm >> 12) & 1) << 31)
        | (((imm >> 5) & 0x3F) << 25)
        | (rs2 << 20)
        | (rs1 << 15)
        | (funct3 << 12)
        | (((imm >> 1) & 0xF) << 8)
        | (((imm >> 11) & 1) << 7)
        | 0x63
    )


def ADDI(rd, rs1, imm):
    return i_type(
        imm, rs1, 0b000, rd, 0x13
    )


def ANDI(rd, rs1, imm):
    return i_type(
        imm, rs1, 0b111, rd, 0x13
    )


def LW(rd, rs1, imm):
    return i_type(
        imm, rs1, 0b010, rd, 0x03
    )


def SW(rs2, rs1, imm):
    return s_type(
        imm, rs1, rs2, 0b010
    )


def BEQZ(rs1, offset):
    return b_type(
        offset, rs1, 0
    )


# ============================================================
# Program representation
# ============================================================

class Program:

    def __init__(self):

        # Each instruction:
        #
        # [assembly_text, machine_code, label_ref, rs1]
        #
        self.items = []

        # label -> BYTE PC
        self.labels = {}

    @property
    def pc(self):
        """
        Current PC in BYTE addresses.
        """

        return len(self.items) * 4

    def label(self, name):
        """
        Add a label at the current PC.

        Labels do not consume a memory word.
        """

        if name in self.labels:
            raise ValueError(
                f"duplicate label: {name}"
            )

        self.labels[name] = self.pc

    def emit(
        self,
        text,
        machine=None,
        label_ref=None,
        rs1=None,
    ):
        self.items.append([
            text,
            machine,
            label_ref,
            rs1,
        ])

    def resolve(self):
        """
        Resolve symbolic BEQZ targets.
        """

        for idx, item in enumerate(self.items):

            text, machine, label_ref, rs1 = item

            if label_ref is None:
                continue

            if label_ref not in self.labels:
                raise ValueError(
                    f"unknown label: {label_ref}"
                )

            offset = self.labels[label_ref] - idx * 4

            item[1] = BEQZ(rs1, offset)


# ============================================================
# Emit sequence -> FIFO
# ============================================================

def emit_mem_to_fifo(
    p,
    seq_name,
    idx,
    offset,
    fifo_addr,
):
    """
    Load one 32-bit word from SRAM and write it to the
    corresponding accelerator FIFO address.
    """

    if seq_name == "S":

        suffix = (
            "low"
            if offset == 0
            else "high + type"
        )

    else:

        suffix = (
            "low"
            if offset == 2
            else "high + type"
        )

    p.emit(
        f"lw x1, {offset}(x2)                  "
        f"# {seq_name}{idx} {suffix}",
        LW(1, 2, offset),
    )

    p.emit(
        f"sw x1, 0x{fifo_addr:x}(x0)            "
        f"# FIFO_{'LOW' if fifo_addr == FIFO_LOW_ADDR else 'HIGH'}",
        SW(1, 0, fifo_addr),
    )


def emit_sequence_pair_to_fifo(p, pair_idx):
    """
    TEST_TYPE = 2

    Send:

        S(pair_idx)
        T(pair_idx)

    to the accelerator.

    Each sequence requires two writes:

        LOW
        HIGH + TYPE

    Therefore one alignment requires 4 FIFO writes.
    """

    pair_base = DATA_START_WORD + pair_idx * 4

    p.emit(
        f"addi x2, x0, {pair_base}              "
        f"# SRAM word address of pair {pair_idx}",
        ADDI(2, 0, pair_base),
    )

    # --------------------------------------------------------
    # S sequence
    # --------------------------------------------------------

    emit_mem_to_fifo(
        p,
        "S",
        pair_idx,
        0,
        FIFO_LOW_ADDR,
    )

    emit_mem_to_fifo(
        p,
        "S",
        pair_idx,
        1,
        FIFO_HIGH_ADDR,
    )

    # --------------------------------------------------------
    # T sequence
    # --------------------------------------------------------

    emit_mem_to_fifo(
        p,
        "T",
        pair_idx,
        2,
        FIFO_LOW_ADDR,
    )

    emit_mem_to_fifo(
        p,
        "T",
        pair_idx,
        3,
        FIFO_HIGH_ADDR,
    )


def emit_s0_to_fifo(p):
    """
    TEST_TYPE = 1

    Send S0 exactly once.

    S0 occupies one FIFO entry.

    The sequence is stored at:

        DATA_START_WORD + 0
        DATA_START_WORD + 1

    No other S sequence is sent.
    """

    s_base = DATA_START_WORD

    p.emit(
        f"addi x2, x0, {s_base}              "
        f"# SRAM word address of S0",
        ADDI(2, 0, s_base),
    )

    # S0 low
    emit_mem_to_fifo(
        p,
        "S",
        0,
        0,
        FIFO_LOW_ADDR,
    )

    # S0 high + type
    emit_mem_to_fifo(
        p,
        "S",
        0,
        1,
        FIFO_HIGH_ADDR,
    )


def emit_t_to_fifo(p, pair_idx):
    """
    TEST_TYPE = 1

    Send only T(pair_idx).

    No S sequence is sent.

    T sequence data is stored at:

        DATA_START_WORD + pair_idx * 4 + 2
        DATA_START_WORD + pair_idx * 4 + 3
    """

    pair_base = DATA_START_WORD + pair_idx * 4

    p.emit(
        f"addi x2, x0, {pair_base}              "
        f"# SRAM word address of T{pair_idx}",
        ADDI(2, 0, pair_base),
    )

    # T low
    emit_mem_to_fifo(
        p,
        "T",
        pair_idx,
        2,
        FIFO_LOW_ADDR,
    )

    # T high + type
    emit_mem_to_fifo(
        p,
        "T",
        pair_idx,
        3,
        FIFO_HIGH_ADDR,
    )


# ============================================================
# Poll result FIFO
# ============================================================

def emit_read_result(
    p,
    pair_idx,
    calculated_addr,
):
    """
    Wait until the result FIFO is not empty.

    STATUS[0]:
        1 = result FIFO empty
        0 = result FIFO has data
    """

    poll_label = f"poll_result_{pair_idx}"
    ready_label = f"result_ready_{pair_idx}"

    p.label(poll_label)

    # Read STATUS
    p.emit(
        "lw x1, 0x201(x0)                       "
        "# STATUS",
        LW(1, 0, STATUS_REG_ADDR),
    )

    # STATUS[0] = result_fifo_empty
    p.emit(
        "andi x1, x1, 1                         "
        "# STATUS[0]",
        ANDI(1, 1, 1),
    )

    # If STATUS[0] == 0, result is available
    p.emit(
        f"beqz x1, {ready_label}                "
        "# empty == 0 -> result available",
        label_ref=ready_label,
        rs1=1,
    )

    # Otherwise FIFO is empty -> poll again
    p.emit(
        f"beqz x0, {poll_label}                 "
        "# empty == 1 -> poll again",
        label_ref=poll_label,
        rs1=0,
    )

    # Result available
    p.label(ready_label)

    p.emit(
        "lw x1, 0x200(x0)                       "
        "# RESULT",
        LW(1, 0, RESULT_REG_ADDR),
    )

    p.emit(
        f"sw x1, {calculated_addr}(x0)           "
        f"# calculated result[{pair_idx}]",
        SW(1, 0, calculated_addr),
    )


# ============================================================
# Generate DNA test pairs
# ============================================================

def generate_pairs(n, generation_type):
    """
    type 1:
        Generate one S sequence and reuse it for all T
        sequences.

        S0 is therefore shared by:

            S0/T0
            S0/T1
            S0/T2
            ...

        Only S0 will be sent to the accelerator.

    type 2:
        Generate independent S/T pairs.
    """

    pairs = []

    previous_s = ""

    for _ in range(n):

        seq1_len = (
            0
            if generation_type == "1"
            and previous_s
            else 8
        )

        seq2_len = 8

        s_seq, t_seq = dg.generate_dna_pair(
            seq1_len,
            seq2_len,
            0.5,
        )

        if (
            generation_type == "1"
            and previous_s
        ):
            s_seq = previous_s

        result = dg.smith_waterman_impl(
            seq1=s_seq,
            seq2=t_seq,
            match=2,
            mismatch=-1,
            alpha=-2,
            beta=-1,
        )["max_alignment_score"]

        pairs.append({
            "s_seq": s_seq,
            "t_seq": t_seq,
            "expected": result,
        })

        previous_s = s_seq

    return pairs


# ============================================================
# Build RISC-V program
# ============================================================

def build_program(
    pairs,
    expected_start,
    calculated_start,
    generation_type,
    beat_size,
):
    """
    Generate the RISC-V test program.

    ============================================================
    TEST_TYPE = 1
    ============================================================

    Only S0 is sent.

    S0 occupies one FIFO entry.

    With BEAT_SIZE = 16:

        S0
        T0
        T1
        ...
        T14

    This fills all 16 FIFO entries.

    Then all 15 corresponding results are read.

    After that, the remaining T sequences are sent without
    sending another S sequence.

    For N = 20:

        Batch 1:
            S0
            T0 ... T14

            result 0 ... result 14

        Batch 2:
            T15 ... T19

            result 15 ... result 19

    ============================================================
    TEST_TYPE = 2
    ============================================================

    Each alignment consists of:

        S
        T

    Each sequence requires one FIFO entry.

    Therefore each alignment consumes two FIFO entries.

    With BEAT_SIZE = 16:

        S0 T0
        S1 T1
        ...
        S7 T7

    Then results 0 ... 7 are read.
    """

    p = Program()

    total_pairs = len(pairs)

    # ========================================================
    # TEST_TYPE = 1
    # ========================================================

    if generation_type == "1":

        if beat_size < 2:
            raise ValueError(
                "BEAT_SIZE must be at least 2 for TEST_TYPE=1"
            )

        # ----------------------------------------------------
        # Send S0 exactly once
        # ----------------------------------------------------

        emit_s0_to_fifo(p)

        # ----------------------------------------------------
        # The first FIFO batch has one S entry already used.
        #
        # Therefore the first batch can contain:
        #
        #     BEAT_SIZE - 1
        #
        # T sequences.
        #
        # Every following batch can contain BEAT_SIZE T
        # sequences.
        # ----------------------------------------------------

        test_index = 0

        first_batch = True

        while test_index < total_pairs:

            if first_batch:

                t_batch_size = beat_size - 1

                first_batch = False

            else:

                t_batch_size = beat_size

            batch_end = min(
                test_index + t_batch_size,
                total_pairs,
            )

            # ------------------------------------------------
            # Fill T sequences
            # ------------------------------------------------

            for pair_idx in range(
                test_index,
                batch_end,
            ):

                emit_t_to_fifo(
                    p,
                    pair_idx,
                )

            # ------------------------------------------------
            # Read all results belonging to this batch
            # ------------------------------------------------

            for pair_idx in range(
                test_index,
                batch_end,
            ):

                calculated_addr = (
                    calculated_start + pair_idx
                )

                emit_read_result(
                    p,
                    pair_idx,
                    calculated_addr,
                )

            test_index = batch_end

    # ========================================================
    # TEST_TYPE = 2
    # ========================================================

    elif generation_type == "2":

        batch_size = beat_size // 2

        for batch_start in range(
            0,
            total_pairs,
            batch_size,
        ):

            batch_end = min(
                batch_start + batch_size,
                total_pairs,
            )

            # ------------------------------------------------
            # Fill input FIFO
            # ------------------------------------------------

            for pair_idx in range(
                batch_start,
                batch_end,
            ):

                emit_sequence_pair_to_fifo(
                    p,
                    pair_idx,
                )

            # ------------------------------------------------
            # Read all results
            # ------------------------------------------------

            for pair_idx in range(
                batch_start,
                batch_end,
            ):

                calculated_addr = (
                    calculated_start + pair_idx
                )

                emit_read_result(
                    p,
                    pair_idx,
                    calculated_addr,
                )

    else:

        raise ValueError(
            f"Unsupported TEST_TYPE: {generation_type}"
        )

    # ========================================================
    # Infinite loop at the end
    # ========================================================

    done_label = "done"

    p.label(done_label)

    p.emit(
        "beqz x0, done",
        label_ref=done_label,
        rs1=0,
    )

    p.resolve()

    return p


# ============================================================
# Build SRAM data
# ============================================================

def make_data_words(
    pairs,
    expected_start,
    calculated_start,
):
    """
    SRAM layout:

        DATA_START_WORD
            |
            +-- Sequence data
            |
            +-- Expected results
            |
            +-- Calculated results
            |
            +-- unused
    """

    data = {}

    # --------------------------------------------------------
    # Sequence data
    # --------------------------------------------------------

    for i, pair in enumerate(pairs):

        base = DATA_START_WORD + i * 4

        s0, s1 = pack_s_words(
            pair["s_seq"]
        )

        t0, t1 = pack_t_words(
            pair["t_seq"]
        )

        data[base + 0] = s0
        data[base + 1] = s1
        data[base + 2] = t0
        data[base + 3] = t1

    # --------------------------------------------------------
    # Expected results
    # --------------------------------------------------------

    for i, pair in enumerate(pairs):

        data[expected_start + i] = (
            pair["expected"]
            & 0xFFFFFFFF
        )

    # --------------------------------------------------------
    # Calculated results
    # --------------------------------------------------------

    for i in range(len(pairs)):

        data[calculated_start + i] = 0

    return data


# ============================================================
# Write complete memory initialization
# ============================================================

def write_mem_init(
    filename,
    program,
    data,
):

    memory = [0] * MEM_DEPTH

    # --------------------------------------------------------
    # Program
    # --------------------------------------------------------

    for i, item in enumerate(program.items):

        if i >= MEM_DEPTH:
            raise ValueError(
                "Program exceeds memory depth"
            )

        memory[i] = (
            item[1]
            & 0xFFFFFFFF
        )

    # --------------------------------------------------------
    # Data
    # --------------------------------------------------------

    for addr, value in data.items():

        if not 0 <= addr < MEM_DEPTH:
            raise ValueError(
                f"memory address {addr} "
                f"out of range"
            )

        memory[addr] = (
            value
            & 0xFFFFFFFF
        )

    with open(filename, "w") as f:

        for word in memory:

            f.write(
                f"{word:08x}\n"
            )


# ============================================================
# Write assembly listing
# ============================================================

def write_assembly(
    filename,
    program,
    pairs,
    expected_start,
    calculated_start,
    generation_type,
    beat_size,
):
    """
    Write the assembly listing.
    """

    # --------------------------------------------------------
    # Build PC -> labels map
    # --------------------------------------------------------

    labels_by_pc = {}

    for label, pc in program.labels.items():

        labels_by_pc.setdefault(
            pc,
            [],
        ).append(label)

    with open(filename, "w") as f:

        f.write(
            "# Generated for simplified RV32I "
            "DNA accelerator\n"
        )

        f.write(
            "#\n"
            "# Registers:\n"
            "#   x0 = constant zero\n"
            "#   x1 = data/result register\n"
            "#   x2 = SRAM address register\n"
            "#\n"
        )

        f.write(
            "# Data memory is WORD addressed.\n"
        )

        f.write(
            "# Therefore LW/SW offsets are word offsets.\n"
        )

        f.write(
            "#\n"
            "# Accelerator MMIO:\n"
            "#   0x200 = RESULT / FIFO_LOW\n"
            "#   0x201 = STATUS / FIFO_HIGH\n"
            "#\n"
        )

        f.write(
            "# STATUS bits:\n"
            "#   bit 3 = sequence FIFO full\n"
            "#   bit 2 = sequence FIFO empty\n"
            "#   bit 1 = result FIFO full\n"
            "#   bit 0 = result FIFO empty\n"
            "#\n"
        )

        f.write(
            f"# Input FIFO batch size = {beat_size} entries\n"
        )

        f.write(
            f"# TEST_TYPE = {generation_type}\n"
        )

        if generation_type == "1":

            f.write(
                "# TEST_TYPE 1:\n"
                "#   S0 is sent exactly once.\n"
                "#   S0 is shared by all T sequences.\n"
                "#   No S1, S2, ... sequences are sent.\n"
                "#\n"
            )

            f.write(
                "# First batch:\n"
                f"#   S0 + {beat_size - 1} T sequences\n"
            )

            f.write(
                "# Following batches:\n"
                f"#   T sequences only\n"
            )

        else:

            f.write(
                "# TEST_TYPE 2:\n"
                "#   Each alignment sends:\n"
                "#     S low\n"
                "#     S high/type\n"
                "#     T low\n"
                "#     T high/type\n"
            )

        f.write(
            "#\n"
            "# Results are read from the result FIFO in order.\n"
        )

        f.write("\n")

        # ----------------------------------------------------
        # Instructions
        # ----------------------------------------------------

        for i, item in enumerate(
            program.items
        ):

            text, machine, label_ref, rs1 = item

            pc = i * 4

            # Print labels before instruction.
            if pc in labels_by_pc:

                f.write("\n")

                for label in labels_by_pc[pc]:

                    f.write(
                        f"{label}:\n"
                    )

            # Comment-only entries do not have machine code.
            if machine is None:

                f.write(
                    f"# {text}\n"
                )

            else:

                f.write(
                    f"{i:04d}  "
                    f"0x{machine:08x}  "
                    f"{text}\n"
                )

        # ----------------------------------------------------
        # SRAM data description
        # ----------------------------------------------------

        f.write("\n")
        f.write(
            "# ====================================================\n"
        )
        f.write(
            "# SRAM DATA LAYOUT\n"
        )
        f.write(
            "# ====================================================\n"
        )

        f.write("\n")

        f.write(
            f"# Sequence data starts at WORD "
            f"{DATA_START_WORD}\n"
        )

        f.write(
            f"# Expected results start at WORD "
            f"{expected_start}\n"
        )

        f.write(
            f"# Calculated results start at WORD "
            f"{calculated_start}\n"
        )

        f.write("\n")

        # ----------------------------------------------------
        # Pair information
        # ----------------------------------------------------

        for i, pair in enumerate(pairs):

            base = DATA_START_WORD + i * 4

            s0, s1 = pack_s_words(
                pair["s_seq"]
            )

            t0, t1 = pack_t_words(
                pair["t_seq"]
            )

            expected_addr = (
                expected_start + i
            )

            calculated_addr = (
                calculated_start + i
            )

            f.write(
                "# --------------------------------------------------\n"
            )

            f.write(
                f"# Pair {i}\n"
            )

            f.write(
                f"# Sequence data words: "
                f"{base} .. {base + 3}\n"
            )

            f.write(
                f"#   [{base + 0}] "
                f"S low       = 0x{s0:08x}\n"
            )

            f.write(
                f"#   [{base + 1}] "
                f"S high/type = 0x{s1:08x}\n"
            )

            f.write(
                f"#   [{base + 2}] "
                f"T low       = 0x{t0:08x}\n"
            )

            f.write(
                f"#   [{base + 3}] "
                f"T high/type = 0x{t1:08x}\n"
            )

            f.write(
                f"#\n"
                f"#   S = {pair['s_seq']}\n"
                f"#   T = {pair['t_seq']}\n"
            )

            f.write(
                f"#\n"
                f"# Expected result:\n"
                f"#   SRAM[{expected_addr}] "
                f"= {pair['expected']}\n"
            )

            f.write(
                f"#\n"
                f"# Calculated result:\n"
                f"#   SRAM[{calculated_addr}] "
                f"= accelerator result\n"
            )

            f.write("\n")


# ============================================================
# Write machine code
# ============================================================

def write_machine_code(
    filename,
    program,
):

    with open(filename, "w") as f:

        for item in program.items:

            # Comment-only entries have no machine code.
            if item[1] is not None:

                f.write(
                    f"{item[1]:08x}\n"
                )


# ============================================================
# Write sequence report
# ============================================================

def write_sequence_report(
    filename,
    pairs,
):

    with open(filename, "w") as f:

        for i, pair in enumerate(pairs):

            f.write(
                f"PAIR {i}\n"
            )

            f.write(
                f"S: {pair['s_seq']}\n"
            )

            f.write(
                f"T: {pair['t_seq']}\n"
            )

            f.write(
                f"EXPECTED: "
                f"{pair['expected']}\n"
            )

            f.write("\n")


# ============================================================
# Main
# ============================================================

def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--type",
        choices=["1", "2"],
        default="1",
        help=(
            "DNA test type. "
            "Type 1 reuses S0 for all T sequences. "
            "Type 2 uses independent S/T pairs."
        ),
    )

    parser.add_argument(
        "--N",
        type=int,
        default=20,
        help="number of sequence pairs",
    )

    parser.add_argument(
        "--beat-size",
        type=int,
        default=BEAT_SIZE,
        help="number of sequence FIFO entries per batch",
    )

    parser.add_argument(
        "--outdir",
        default="output/custom",
    )

    args = parser.parse_args()

    if not 1 <= args.N <= 256:
        raise ValueError(
            "--N must be between 1 and 256"
        )

    if args.beat_size < 2:
        raise ValueError(
            "--beat-size must be at least 2"
        )

    if (
        args.type == "2"
        and args.beat_size % 2 != 0
    ):
        raise ValueError(
            "--beat-size must be even for TEST_TYPE=2 "
            "because every alignment requires S + T."
        )

    os.makedirs(
        args.outdir,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # Generate DNA pairs
    # --------------------------------------------------------

    pairs = generate_pairs(
        args.N,
        args.type,
    )

    # --------------------------------------------------------
    # SRAM layout
    # --------------------------------------------------------
    #
    # Sequence data:
    #
    #   DATA_START_WORD
    #   ...
    #   DATA_START_WORD + N*4 - 1
    #
    # Expected:
    #
    #   DATA_START_WORD + N*4
    #
    # Calculated:
    #
    #   DATA_START_WORD + N*4 + N
    #
    # --------------------------------------------------------

    expected_start = (
        DATA_START_WORD
        + args.N * 4
    )

    calculated_start = (
        expected_start
        + args.N
    )

    # --------------------------------------------------------
    # Build program
    # --------------------------------------------------------

    program = build_program(
        pairs,
        expected_start,
        calculated_start,
        args.type,
        args.beat_size,
    )

    # --------------------------------------------------------
    # Build SRAM data
    # --------------------------------------------------------

    data = make_data_words(
        pairs,
        expected_start,
        calculated_start,
    )

    # --------------------------------------------------------
    # Output filenames
    # --------------------------------------------------------

    asm_file = os.path.join(
        args.outdir,
        "dna_test.S",
    )

    machine_file = os.path.join(
        args.outdir,
        "machine_code.hex",
    )

    mem_file = os.path.join(
        args.outdir,
        "mem_init.hex",
    )

    seq_file = os.path.join(
        args.outdir,
        "generated_sequences.txt",
    )

    # --------------------------------------------------------
    # Write files
    # --------------------------------------------------------

    write_assembly(
        asm_file,
        program,
        pairs,
        expected_start,
        calculated_start,
        args.type,
        args.beat_size,
    )

    write_machine_code(
        machine_file,
        program,
    )

    write_mem_init(
        mem_file,
        program,
        data,
    )

    write_sequence_report(
        seq_file,
        pairs,
    )

    # --------------------------------------------------------
    # Calculate batch information
    # --------------------------------------------------------

    if args.type == "1":

        # First batch has S0 + T sequences.
        first_batch_t = min(
            args.N,
            args.beat_size - 1,
        )

        remaining = max(
            0,
            args.N - first_batch_t,
        )

        additional_batches = (
            (
                remaining
                + args.beat_size
                - 1
            )
            // args.beat_size
            if remaining > 0
            else 0
        )

        num_batches = (
            1
            if args.N > 0
            else 0
        ) + additional_batches

    else:

        num_pairs_per_batch = (
            args.beat_size // 2
        )

        num_batches = (
            args.N
            + num_pairs_per_batch
            - 1
        ) // num_pairs_per_batch

    # --------------------------------------------------------
    # Print summary
    # --------------------------------------------------------

    print("=" * 70)

    print(
        "DNA accelerator FIFO test files generated"
    )

    print("=" * 70)

    print(
        f"Pairs                   : {args.N}"
    )

    print(
        f"TEST_TYPE               : {args.type}"
    )

    print(
        f"Input FIFO batch size   : "
        f"{args.beat_size}"
    )

    if args.type == "1":

        print(
            f"Shared S sequence      : S0"
        )

        print(
            f"T sequences in first batch: "
            f"{min(args.N, args.beat_size - 1)}"
        )

        if args.N > args.beat_size - 1:

            remaining = (
                args.N
                - (args.beat_size - 1)
            )

            print(
                f"T sequences in later batches: "
                f"up to {args.beat_size}"
            )

        print(
            f"Number of batches       : "
            f"{num_batches}"
        )

    else:

        num_pairs_per_batch = (
            args.beat_size // 2
        )

        print(
            f"Pairs per batch         : "
            f"{num_pairs_per_batch}"
        )

        print(
            f"Number of batches       : "
            f"{num_batches}"
        )

    print(
        f"Program words           : "
        f"{len(program.items)}"
    )

    print(
        f"Sequence data start     : "
        f"word {DATA_START_WORD}"
    )

    print(
        f"Expected results start  : "
        f"word {expected_start}"
    )

    print(
        f"Calculated results start: "
        f"word {calculated_start}"
    )

    print()

    print(
        f"Assembly                : "
        f"{asm_file}"
    )

    print(
        f"Machine code            : "
        f"{machine_file}"
    )

    print(
        f"Memory initialization   : "
        f"{mem_file}"
    )

    print(
        f"Sequences/report        : "
        f"{seq_file}"
    )

    print()

    # --------------------------------------------------------
    # Print pair information
    # --------------------------------------------------------

    for i, pair in enumerate(pairs):

        s0, s1 = pack_s_words(
            pair["s_seq"]
        )

        t0, t1 = pack_t_words(
            pair["t_seq"]
        )

        expected_addr = (
            expected_start + i
        )

        calculated_addr = (
            calculated_start + i
        )

        print(
            f"Pair {i}: "
            f"expected={pair['expected']}"
        )

        print(
            f"  S: {pair['s_seq']}"
        )

        print(
            f"     words = "
            f"0x{s0:08x} "
            f"0x{s1:08x}"
        )

        print(
            f"  T: {pair['t_seq']}"
        )

        print(
            f"     words = "
            f"0x{t0:08x} "
            f"0x{t1:08x}"
        )

        print(
            f"  Expected SRAM word   = "
            f"{expected_addr}"
        )

        print(
            f"  Calculated SRAM word = "
            f"{calculated_addr}"
        )

    print()

    print(
        "Result handling:"
    )

    if args.type == "1":

        print(
            "  1. Send S0 once."
        )

        print(
            f"  2. Send up to {args.beat_size - 1} "
            "T sequences in the first batch."
        )

        print(
            "  3. Poll STATUS[0] until each result "
            "is available."
        )

        print(
            "  4. Read and store the batch results."
        )

        print(
            f"  5. Send up to {args.beat_size} "
            "additional T sequences per batch."
        )

        print(
            "  6. Repeat until all results are stored."
        )

    else:

        print(
            "  1. Fill the input FIFO with "
            "BEAT_SIZE entries."
        )

        print(
            "  2. Poll STATUS[0] until result FIFO "
            "is not empty."
        )

        print(
            "  3. Read one result from 0x200."
        )

        print(
            "  4. Store the result into calculated SRAM."
        )

        print(
            "  5. Repeat until all batch results "
            "are stored."
        )

        print(
            "  6. Continue with the next batch."
        )

    print()

    print(
        "Labels:"
    )

    for label, pc in program.labels.items():

        print(
            f"  {label}: "
            f"PC=0x{pc:04x}, "
            f"instruction word={pc // 4}"
        )


if __name__ == "__main__":
    main()