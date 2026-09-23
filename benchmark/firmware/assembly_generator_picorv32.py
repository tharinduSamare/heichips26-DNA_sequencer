from pathlib import Path

#!/usr/bin/env python3

import argparse
import os
import sys

# benchmark/firmware -> benchmark -> repository root
REPO_ROOT = Path(__file__).resolve().parents[2]

SCRIPTS_DIR = REPO_ROOT / "macros" / "heichips26_dna_sequencer" / "scripts"

sys.path.insert(0, str(SCRIPTS_DIR))
import data_gen_and_validation as dg


# ============================================================
# PicoRV32 / memory configuration
# ============================================================
#
# PicoRV32 uses BYTE addresses on its memory interface.
#
# The SRAM itself is 32-bit word based, so:
#
#     CPU byte address 0x0000 -> SRAM word 0
#     CPU byte address 0x0004 -> SRAM word 1
#     CPU byte address 0x0008 -> SRAM word 2
#
# The generated mem_init.hex still contains one 32-bit word
# per line.
# ============================================================

MEM_DEPTH = 1024

# Sequence data starts at SRAM word 320.
DATA_START_WORD = 320
DATA_START_ADDR = DATA_START_WORD * 4

# Accelerator FIFO depth.
BEAT_SIZE = 16

# Accelerator MMIO map.
ACCEL_BASE = 0x80000000
FIFO_LOW_OFFSET = 0x00
FIFO_HIGH_OFFSET = 0x04
RESULT_OFFSET = 0x00
STATUS_OFFSET = 0x04

# STATUS[0] = result FIFO empty.
RESULT_FIFO_EMPTY_BIT = 0

# Register allocation.
#
# x0  = zero
# x1  = temporary data / status / result
# x2  = sequence SRAM pointer
# x3  = accelerator MMIO base
# x4  = calculated-result SRAM pointer
# x5  = loop counter
# x6  = optional secondary counter / temporary
#
# x7-x31 remain available for future optimizations.
SEQ_PTR = 2
ACCEL_BASE_REG = 3
RESULT_PTR = 4
LOOP_COUNT = 5
TMP = 6


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
    Matches the accelerator's S-sequence packing:

        s_seq[(N-1-i)*2 +: 2] = base

    S type bit = 1.
    """

    bases = encode_sequence(seq)
    packed = 0
    n = len(bases)

    for i, base in enumerate(bases):
        packed |= base << ((n - 1 - i) * 2)

    low = packed & 0xFF
    high = (packed >> 8) & 0xFF

    high |= 1 << 8

    return low, high


def pack_t_words(seq):
    """
    Matches the accelerator's T-sequence packing:

        t_seq[i*2 +: 2] = base

    T type bit = 0.
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


def unsigned_imm(value, bits):
    if not 0 <= value < (1 << bits):
        raise ValueError(
            f"value 0x{value:x} does not fit in {bits} bits"
        )

    return value


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


def b_type(offset, rs1, rs2, funct3=0b000):
    """
    B-type PC-relative BYTE offset.
    """

    check_reg(rs1)
    check_reg(rs2)

    if offset % 2:
        raise ValueError("branch offset must be 2-byte aligned")

    if offset < -4096 or offset > 4094:
        raise ValueError(
            f"branch offset {offset} out of range"
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


def u_type(imm20, rd, opcode):
    check_reg(rd)
    imm20 = unsigned_imm(imm20, 20)

    return (
        (imm20 << 12)
        | (rd << 7)
        | opcode
    )


def LUI(rd, imm20):
    return u_type(imm20, rd, 0x37)


def ADDI(rd, rs1, imm):
    return i_type(imm, rs1, 0b000, rd, 0x13)


def ANDI(rd, rs1, imm):
    return i_type(imm, rs1, 0b111, rd, 0x13)


def LW(rd, rs1, imm):
    return i_type(imm, rs1, 0b010, rd, 0x03)


def SW(rs2, rs1, imm):
    return s_type(imm, rs1, rs2, 0b010)


def BEQ(rs1, rs2, offset):
    return b_type(offset, rs1, rs2, 0b000)


def BNE(rs1, rs2, offset):
    return b_type(offset, rs1, rs2, 0b001)


# ============================================================
# Address helpers
# ============================================================

def word_addr(word_index):
    if word_index < 0:
        raise ValueError("negative SRAM word address")
    return word_index << 2


def check_signed12_address(addr):
    """
    Check that a CPU-visible byte address can be used directly
    as an I/S-type immediate from x0.
    """

    if not -2048 <= addr <= 2047:
        raise ValueError(
            f"byte address 0x{addr:x} does not fit in signed 12-bit immediate"
        )


# ============================================================
# Program representation
# ============================================================

class Program:

    def __init__(self):
        self.items = []
        self.labels = {}

    @property
    def pc(self):
        return len(self.items) * 4

    def label(self, name):
        if name in self.labels:
            raise ValueError(f"duplicate label: {name}")
        self.labels[name] = self.pc

    def emit(self, text, machine=None, label_ref=None, branch_rs1=None,
             branch_rs2=None, branch_kind="beq"):
        self.items.append({
            "text": text,
            "machine": machine,
            "label_ref": label_ref,
            "branch_rs1": branch_rs1,
            "branch_rs2": branch_rs2,
            "branch_kind": branch_kind,
        })

    def resolve(self):
        for idx, item in enumerate(self.items):
            label_ref = item["label_ref"]

            if label_ref is None:
                continue

            if label_ref not in self.labels:
                raise ValueError(
                    f"unknown label: {label_ref}"
                )

            offset = self.labels[label_ref] - idx * 4

            if item["branch_kind"] == "beq":
                item["machine"] = BEQ(
                    item["branch_rs1"],
                    item["branch_rs2"],
                    offset,
                )
            elif item["branch_kind"] == "bne":
                item["machine"] = BNE(
                    item["branch_rs1"],
                    item["branch_rs2"],
                    offset,
                )
            else:
                raise ValueError(
                    f"unsupported branch kind: {item['branch_kind']}"
                )


# ============================================================
# Small emit helpers
# ============================================================

def emit_load(p, rd, addr_reg, offset, comment):
    p.emit(
        f"lw x{rd}, {offset}(x{addr_reg})    # {comment}",
        LW(rd, addr_reg, offset),
    )


def emit_store(p, rs2, addr_reg, offset, comment):
    p.emit(
        f"sw x{rs2}, {offset}(x{addr_reg})    # {comment}",
        SW(rs2, addr_reg, offset),
    )


def emit_addi(p, rd, rs1, imm, comment):
    p.emit(
        f"addi x{rd}, x{rs1}, {imm}    # {comment}",
        ADDI(rd, rs1, imm),
    )


def emit_set_reg(p, rd, value, comment):
    """
    Efficiently load a 32-bit constant.

    Currently used mainly for the accelerator base.
    """

    if value == 0:
        emit_addi(p, rd, 0, 0, comment)
        return

    # Sign-adjusted LUI/ADDI construction.
    upper = (value + 0x800) >> 12
    lower = value - (upper << 12)

    upper &= 0xFFFFF

    p.emit(
        f"lui x{rd}, 0x{upper:05x}    # {comment}",
        LUI(rd, upper),
    )

    if lower != 0:
        emit_addi(
            p,
            rd,
            rd,
            lower,
            f"{comment} low bits",
        )


def emit_branch_to(p, kind, rs1, rs2, label, comment):
    p.emit(
        f"{kind} x{rs1}, x{rs2}, {label}    # {comment}",
        label_ref=label,
        branch_rs1=rs1,
        branch_rs2=rs2,
        branch_kind=kind,
    )


# ============================================================
# Accelerator interface
# ============================================================

def emit_init_registers(p, calculated_start_word):
    """
    Initialize persistent registers once.

    x3 = 0x80000000 accelerator base
    x4 = calculated-results byte address
    """

    emit_set_reg(
        p,
        ACCEL_BASE_REG,
        ACCEL_BASE,
        "accelerator MMIO base",
    )

    result_addr = word_addr(calculated_start_word)

    emit_set_reg(
        p,
        RESULT_PTR,
        result_addr,
        "calculated-result SRAM pointer",
    )


def emit_send_s_word(p, seq_ptr, offset, fifo_offset, comment):
    emit_load(
        p,
        1,
        seq_ptr,
        offset,
        f"{comment}: load SRAM",
    )

    emit_store(
        p,
        1,
        ACCEL_BASE_REG,
        fifo_offset,
        f"{comment}: accelerator FIFO",
    )


def emit_send_sequence_pair_unrolled(p):
    """
    Send one complete S/T pair.

    x2 points to:
        S low
        S high/type
        T low
        T high/type
    """

    emit_send_s_word(
        p, SEQ_PTR, 0, FIFO_LOW_OFFSET,
        "S low",
    )

    emit_send_s_word(
        p, SEQ_PTR, 4, FIFO_HIGH_OFFSET,
        "S high/type",
    )

    emit_send_s_word(
        p, SEQ_PTR, 8, FIFO_LOW_OFFSET,
        "T low",
    )

    emit_send_s_word(
        p, SEQ_PTR, 12, FIFO_HIGH_OFFSET,
        "T high/type",
    )

    emit_addi(
        p,
        SEQ_PTR,
        SEQ_PTR,
        16,
        "next S/T pair",
    )


def emit_send_t_unrolled(p):
    """
    Type 1:
    x2 points to T low/high words.
    """

    emit_send_s_word(
        p, SEQ_PTR, 0, FIFO_LOW_OFFSET,
        "T low",
    )

    emit_send_s_word(
        p, SEQ_PTR, 4, FIFO_HIGH_OFFSET,
        "T high/type",
    )

    emit_addi(
        p,
        SEQ_PTR,
        SEQ_PTR,
        16,
        "next T sequence",
    )


def emit_result_poll_and_store(p, loop_label):
    """
    Poll STATUS[0], read RESULT, store through x4.

    x1 = status/result
    x4 = result pointer
    """

    p.label(loop_label)

    emit_load(
        p,
        1,
        ACCEL_BASE_REG,
        STATUS_OFFSET,
        "read accelerator STATUS",
    )

    p.emit(
        "andi x1, x1, 1    # result FIFO empty bit",
        ANDI(1, 1, 1),
    )

    emit_branch_to(
        p,
        "bne",
        1,
        0,
        loop_label,
        "wait while result FIFO is empty",
    )

    emit_load(
        p,
        1,
        ACCEL_BASE_REG,
        RESULT_OFFSET,
        "read accelerator RESULT",
    )

    emit_store(
        p,
        1,
        RESULT_PTR,
        0,
        "store calculated result",
    )

    emit_addi(
        p,
        RESULT_PTR,
        RESULT_PTR,
        4,
        "next calculated-result word",
    )


# ============================================================
# Batch loops
# ============================================================

def emit_type2_batch(p, batch_start, batch_end, batch_id):
    """
    TEST_TYPE=2.

    Each pair consumes two FIFO entries.

    The loop body sends:
        S low
        S high/type
        T low
        T high/type

    x5 = number of pairs in this batch
    x2 = sequence pointer
    """

    count = batch_end - batch_start

    if count <= 0:
        return

    seq_addr = word_addr(DATA_START_WORD + batch_start * 4)

    emit_set_reg(
        p,
        SEQ_PTR,
        seq_addr,
        f"type2 batch {batch_id}: sequence pointer",
    )

    emit_set_reg(
        p,
        LOOP_COUNT,
        count,
        f"type2 batch {batch_id}: pair count",
    )

    send_label = f"type2_send_{batch_id}"
    send_done = f"type2_send_done_{batch_id}"

    p.label(send_label)

    emit_send_sequence_pair_unrolled(p)

    emit_addi(
        p,
        LOOP_COUNT,
        LOOP_COUNT,
        -1,
        "decrement pair count",
    )

    emit_branch_to(
        p,
        "bne",
        LOOP_COUNT,
        0,
        send_label,
        "send next pair",
    )

    p.label(send_done)

    # --------------------------------------------------------
    # Result loop
    # --------------------------------------------------------

    emit_set_reg(
        p,
        LOOP_COUNT,
        count,
        f"type2 batch {batch_id}: result count",
    )

    result_label = f"type2_result_{batch_id}"

    p.label(result_label)

    emit_result_poll_and_store(
        p,
        f"type2_poll_{batch_id}_{batch_start}_{batch_end}",
    )

    emit_addi(
        p,
        LOOP_COUNT,
        LOOP_COUNT,
        -1,
        "decrement result count",
    )

    emit_branch_to(
        p,
        "bne",
        LOOP_COUNT,
        0,
        result_label,
        "read next result",
    )


def emit_type1_first_batch(p, count, batch_id):
    """
    TEST_TYPE=1 first batch.

    S0 is already sent before this function.
    x2 is initialized to T0.
    """

    if count <= 0:
        return

    emit_set_reg(
        p,
        LOOP_COUNT,
        count,
        f"type1 first batch: {count} T sequences",
    )

    send_label = f"type1_send_first_{batch_id}"

    p.label(send_label)

    emit_send_t_unrolled(p)

    emit_addi(
        p,
        LOOP_COUNT,
        LOOP_COUNT,
        -1,
        "decrement T count",
    )

    emit_branch_to(
        p,
        "bne",
        LOOP_COUNT,
        0,
        send_label,
        "send next T",
    )

    emit_set_reg(
        p,
        LOOP_COUNT,
        count,
        "type1 first batch: result count",
    )

    result_label = f"type1_result_first_{batch_id}"

    p.label(result_label)

    emit_result_poll_and_store(
        p,
        f"type1_poll_first_{batch_id}",
    )

    emit_addi(
        p,
        LOOP_COUNT,
        LOOP_COUNT,
        -1,
        "decrement result count",
    )

    emit_branch_to(
        p,
        "bne",
        LOOP_COUNT,
        0,
        result_label,
        "read next result",
    )


def emit_type1_later_batch(p, batch_start, batch_end, batch_id):
    """
    TEST_TYPE=1 later batches.

    x2 points to the first T of this batch.
    """

    count = batch_end - batch_start

    if count <= 0:
        return

    seq_addr = word_addr(
        DATA_START_WORD
        + batch_start * 4
        + 2
    )

    emit_set_reg(
        p,
        SEQ_PTR,
        seq_addr,
        f"type1 batch {batch_id}: T pointer",
    )

    emit_set_reg(
        p,
        LOOP_COUNT,
        count,
        f"type1 batch {batch_id}: T count",
    )

    send_label = f"type1_send_{batch_id}"

    p.label(send_label)

    emit_send_t_unrolled(p)

    emit_addi(
        p,
        LOOP_COUNT,
        LOOP_COUNT,
        -1,
        "decrement T count",
    )

    emit_branch_to(
        p,
        "bne",
        LOOP_COUNT,
        0,
        send_label,
        "send next T",
    )

    emit_set_reg(
        p,
        LOOP_COUNT,
        count,
        f"type1 batch {batch_id}: result count",
    )

    result_label = f"type1_result_{batch_id}"

    p.label(result_label)

    emit_result_poll_and_store(
        p,
        f"type1_poll_{batch_id}",
    )

    emit_addi(
        p,
        LOOP_COUNT,
        LOOP_COUNT,
        -1,
        "decrement result count",
    )

    emit_branch_to(
        p,
        "bne",
        LOOP_COUNT,
        0,
        result_label,
        "read next result",
    )


# ============================================================
# Generate DNA test pairs
# ============================================================

def generate_pairs(n, generation_type):
    """
    TEST_TYPE=1:
        One S sequence is generated and reused for all T
        sequences.

    TEST_TYPE=2:
        Every alignment gets an independent S/T pair.
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
# Build optimized PicoRV32 program
# ============================================================

def build_program(
    pairs,
    expected_start,
    calculated_start,
    generation_type,
    beat_size,
):
    """
    Generate an optimized RV32I program.

    The important difference from the old generator is that
    the program uses persistent registers and loops.

    x2 = sequence pointer
    x3 = accelerator MMIO base
    x4 = calculated-result pointer
    x5 = loop counter
    """

    p = Program()

    total_pairs = len(pairs)

    # --------------------------------------------------------
    # Initialize persistent registers
    # --------------------------------------------------------

    emit_init_registers(
        p,
        calculated_start,
    )

    # ========================================================
    # TEST_TYPE = 1
    # ========================================================

    if generation_type == "1":

        if beat_size < 2:
            raise ValueError(
                "BEAT_SIZE must be at least 2 for TEST_TYPE=1"
            )

        # ----------------------------------------------------
        # Send S0 exactly once.
        # ----------------------------------------------------

        emit_set_reg(
            p,
            SEQ_PTR,
            DATA_START_ADDR,
            "S0 pointer",
        )

        emit_send_s_word(
            p,
            SEQ_PTR,
            0,
            FIFO_LOW_OFFSET,
            "S0 low",
        )

        emit_send_s_word(
            p,
            SEQ_PTR,
            4,
            FIFO_HIGH_OFFSET,
            "S0 high/type",
        )

        # ----------------------------------------------------
        # Start T pointer at T0.
        #
        # Each pair occupies:
        #   S low       +0
        #   S high/type +4
        #   T low       +8
        #   T high/type +12
        # ----------------------------------------------------

        if total_pairs > 0:

            first_count = min(
                total_pairs,
                beat_size - 1,
            )

            emit_set_reg(
                p,
                SEQ_PTR,
                DATA_START_ADDR + 8,
                "T0 pointer",
            )

            emit_type1_first_batch(
                p,
                first_count,
                0,
            )

            next_pair = first_count
            batch_id = 1

            while next_pair < total_pairs:

                batch_end = min(
                    next_pair + beat_size,
                    total_pairs,
                )

                emit_type1_later_batch(
                    p,
                    next_pair,
                    batch_end,
                    batch_id,
                )

                next_pair = batch_end
                batch_id += 1

    # ========================================================
    # TEST_TYPE = 2
    # ========================================================

    elif generation_type == "2":

        if beat_size % 2 != 0:
            raise ValueError(
                "BEAT_SIZE must be even for TEST_TYPE=2"
            )

        pairs_per_batch = beat_size // 2

        batch_id = 0

        for batch_start in range(
            0,
            total_pairs,
            pairs_per_batch,
        ):

            batch_end = min(
                batch_start + pairs_per_batch,
                total_pairs,
            )

            emit_type2_batch(
                p,
                batch_start,
                batch_end,
                batch_id,
            )

            batch_id += 1

    else:
        raise ValueError(
            f"unsupported TEST_TYPE={generation_type}"
        )

    # --------------------------------------------------------
    # Finished: infinite loop.
    # --------------------------------------------------------

    p.label("done")

    emit_branch_to(
        p,
        "beq",
        0,
        0,
        "done",
        "finished",
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
    data = {}

    # --------------------------------------------------------
    # Sequence data
    # --------------------------------------------------------

    for i, pair in enumerate(pairs):

        base = DATA_START_WORD + i * 4

        s0, s1 = pack_s_words(pair["s_seq"])
        t0, t1 = pack_t_words(pair["t_seq"])

        data[base + 0] = s0
        data[base + 1] = s1
        data[base + 2] = t0
        data[base + 3] = t1

    # --------------------------------------------------------
    # Expected results
    # --------------------------------------------------------

    for i, pair in enumerate(pairs):

        data[expected_start + i] = (
            pair["expected"] & 0xFFFFFFFF
        )

    # --------------------------------------------------------
    # Calculated results initialized to zero.
    # --------------------------------------------------------

    for i in range(len(pairs)):

        data[calculated_start + i] = 0

    return data


# ============================================================
# Write SRAM initialization
# ============================================================

def write_mem_init(
    filename,
    program,
    data,
):
    memory = [0] * MEM_DEPTH

    # Program occupies SRAM words 0...N-1.
    for i, item in enumerate(program.items):

        if i >= MEM_DEPTH:
            raise ValueError(
                "program exceeds SRAM depth"
            )

        machine = item["machine"]

        if machine is not None:
            memory[i] = machine & 0xFFFFFFFF

    # Data dictionary uses SRAM WORD indices.
    for word_index, value in data.items():

        if not 0 <= word_index < MEM_DEPTH:
            raise ValueError(
                f"SRAM word index {word_index} out of range"
            )

        memory[word_index] = value & 0xFFFFFFFF

    with open(filename, "w") as f:

        for word in memory:
            f.write(f"{word:08x}\n")


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
    labels_by_pc = {}

    for label, pc in program.labels.items():
        labels_by_pc.setdefault(pc, []).append(label)

    with open(filename, "w") as f:

        f.write(
            "# ============================================================\n"
        )
        f.write(
            "# Optimized PicoRV32 DNA accelerator test program\n"
        )
        f.write(
            "# ============================================================\n"
        )
        f.write(
            "# CPU data addresses are BYTE addresses.\n"
        )
        f.write(
            "# mem_init.hex uses SRAM WORD indices.\n"
        )
        f.write("\n")

        f.write("# Register allocation:\n")
        f.write("#   x0 = zero\n")
        f.write("#   x1 = temporary data/status/result\n")
        f.write("#   x2 = sequence SRAM byte pointer\n")
        f.write("#   x3 = accelerator MMIO base (0x80000000)\n")
        f.write("#   x4 = calculated-result SRAM byte pointer\n")
        f.write("#   x5 = loop counter\n")
        f.write("#   x6 = reserved temporary\n")
        f.write("#   x7-x31 = available for future optimization\n")
        f.write("\n")

        f.write("# Accelerator MMIO:\n")
        f.write("#   0x80000000 = RESULT / FIFO_LOW\n")
        f.write("#   0x80000004 = STATUS / FIFO_HIGH\n")
        f.write("#\n")
        f.write("# STATUS[0] = result FIFO empty\n")
        f.write("\n")

        f.write(f"# TEST_TYPE = {generation_type}\n")
        f.write(f"# Number of pairs = {len(pairs)}\n")
        f.write(f"# FIFO depth = {beat_size}\n")
        f.write("\n")

        if generation_type == "1":
            f.write(
                "# TEST_TYPE 1:\n"
                "#   S0 is sent once.\n"
                "#   All T sequences reuse S0.\n"
                "#   First FIFO batch = S0 + up to BEAT_SIZE-1 T entries.\n"
                "#   Later batches contain T entries only.\n"
            )
        else:
            f.write(
                "# TEST_TYPE 2:\n"
                "#   Every alignment sends S + T.\n"
                "#   BEAT_SIZE / 2 alignments are sent per batch.\n"
            )

        f.write("\n")

        for i, item in enumerate(program.items):

            pc = i * 4

            if pc in labels_by_pc:
                f.write("\n")
                for label in labels_by_pc[pc]:
                    f.write(f"{label}:\n")

            machine = item["machine"]

            if machine is None:
                f.write(f"# {item['text']}\n")
            else:
                f.write(
                    f"{i:04d}  "
                    f"0x{machine:08x}  "
                    f"{item['text']}\n"
                )

        # ----------------------------------------------------
        # SRAM data description
        # ----------------------------------------------------

        f.write("\n")
        f.write("# ============================================================\n")
        f.write("# SRAM DATA LAYOUT\n")
        f.write("# ============================================================\n")
        f.write(
            f"# Sequence data:     WORD {DATA_START_WORD}\n"
        )
        f.write(
            f"# Expected results:  WORD {expected_start}\n"
        )
        f.write(
            f"# Calculated results: WORD {calculated_start}\n"
        )
        f.write("\n")

        for i, pair in enumerate(pairs):

            base = DATA_START_WORD + i * 4

            s0, s1 = pack_s_words(pair["s_seq"])
            t0, t1 = pack_t_words(pair["t_seq"])

            expected_addr = expected_start + i
            calculated_addr = calculated_start + i

            f.write("# ------------------------------------------------------------\n")
            f.write(f"# Pair {i}\n")
            f.write(
                f"#   SRAM WORD {base + 0}: S low       = 0x{s0:08x}\n"
            )
            f.write(
                f"#   SRAM WORD {base + 1}: S high/type = 0x{s1:08x}\n"
            )
            f.write(
                f"#   SRAM WORD {base + 2}: T low       = 0x{t0:08x}\n"
            )
            f.write(
                f"#   SRAM WORD {base + 3}: T high/type = 0x{t1:08x}\n"
            )
            f.write(f"#   S = {pair['s_seq']}\n")
            f.write(f"#   T = {pair['t_seq']}\n")
            f.write(
                f"#   Expected   SRAM WORD {expected_addr} "
                f"= {pair['expected']}\n"
            )
            f.write(
                f"#   Calculated SRAM WORD {calculated_addr}\n"
            )
            f.write("\n")


# ============================================================
# Write machine code
# ============================================================

def write_machine_code(filename, program):

    with open(filename, "w") as f:

        for item in program.items:

            machine = item["machine"]

            if machine is not None:
                f.write(f"{machine:08x}\n")


# ============================================================
# Write sequence report
# ============================================================

def write_sequence_report(filename, pairs):

    with open(filename, "w") as f:

        for i, pair in enumerate(pairs):

            f.write(f"PAIR {i}\n")
            f.write(f"S: {pair['s_seq']}\n")
            f.write(f"T: {pair['t_seq']}\n")
            f.write(f"EXPECTED: {pair['expected']}\n")
            f.write("\n")


# ============================================================
# Main
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Generate optimized RV32I/PicoRV32 DNA "
            "accelerator test programs."
        )
    )

    parser.add_argument(
        "--type",
        choices=["1", "2"],
        default="1",
        help=(
            "TEST_TYPE: "
            "1 = shared S0, "
            "2 = independent S/T pairs"
        ),
    )

    parser.add_argument(
        "--N",
        type=int,
        default=20,
        help="number of sequence pairs (default: 20)",
    )

    parser.add_argument(
        "--beat-size",
        type=int,
        default=BEAT_SIZE,
        help=(
            "accelerator input FIFO depth / batch size "
            "(default: 16)"
        ),
    )

    parser.add_argument(
        "--outdir",
        default="output/picorv32_asm",
        help="output directory",
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
            "--beat-size must be even for TEST_TYPE=2"
        )

    # --------------------------------------------------------
    # Generate test pairs.
    # --------------------------------------------------------

    pairs = generate_pairs(
        args.N,
        args.type,
    )

    # --------------------------------------------------------
    # SRAM layout.
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
    # Build optimized program.
    # --------------------------------------------------------

    program = build_program(
        pairs,
        expected_start,
        calculated_start,
        args.type,
        args.beat_size,
    )

    # --------------------------------------------------------
    # Build SRAM data.
    # --------------------------------------------------------

    data = make_data_words(
        pairs,
        expected_start,
        calculated_start,
    )

    # --------------------------------------------------------
    # Check that program and data fit.
    # --------------------------------------------------------

    highest_data_word = max(data.keys())

    if highest_data_word >= MEM_DEPTH:
        raise ValueError(
            f"data requires SRAM word {highest_data_word}, "
            f"but memory depth is {MEM_DEPTH}"
        )

    if len(program.items) >= MEM_DEPTH:
        raise ValueError(
            f"program requires {len(program.items)} words, "
            f"but memory depth is {MEM_DEPTH}"
        )

    # --------------------------------------------------------
    # Output files.
    # --------------------------------------------------------

    os.makedirs(args.outdir, exist_ok=True)

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
    # Write outputs.
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
    # Batch statistics.
    # --------------------------------------------------------

    if args.type == "1":

        first_batch_t = min(
            args.N,
            args.beat_size - 1,
        )

        remaining = max(
            0,
            args.N - first_batch_t,
        )

        later_batches = (
            (
                remaining
                + args.beat_size
                - 1
            )
            // args.beat_size
            if remaining
            else 0
        )

        num_batches = (
            (1 if args.N > 0 else 0)
            + later_batches
        )

    else:

        pairs_per_batch = args.beat_size // 2

        num_batches = (
            args.N
            + pairs_per_batch
            - 1
        ) // pairs_per_batch

    # --------------------------------------------------------
    # Summary.
    # --------------------------------------------------------

    print(f"Pairs                   : {args.N}")
    print(f"TEST_TYPE               : {args.type}")
    print(f"FIFO depth              : {args.beat_size}")
    print(f"Number of batches       : {num_batches}")
    print(f"Program words           : {len(program.items)}")
    print(f"Sequence data start     : SRAM word {DATA_START_WORD}")
    print(f"Expected results start  : SRAM word {expected_start}")
    print(f"Calculated results start: SRAM word {calculated_start}")
    print()
    print(f"Assembly                : {asm_file}")
    print(f"Machine code            : {machine_file}")
    print(f"Memory initialization   : {mem_file}")
    print(f"Sequences/report        : {seq_file}")

    print()
    print("Register allocation:")
    print("  x0 = zero")
    print("  x1 = temporary data/status/result")
    print("  x2 = sequence SRAM byte pointer")
    print("  x3 = accelerator MMIO base")
    print("  x4 = calculated-result SRAM byte pointer")
    print("  x5 = loop counter")
    print("  x6 = reserved temporary")
    print("  x7-x31 = available")

    print()
    print("Accelerator MMIO:")
    print(f"  ACCEL_BASE = 0x{ACCEL_BASE:08x}")
    print(f"  FIFO_LOW  = +0x{FIFO_LOW_OFFSET:02x}")
    print(f"  FIFO_HIGH = +0x{FIFO_HIGH_OFFSET:02x}")
    print(f"  RESULT    = +0x{RESULT_OFFSET:02x}")
    print(f"  STATUS    = +0x{STATUS_OFFSET:02x}")

    print()
    print("Generated sequence pairs:")

    for i, pair in enumerate(pairs):

        s0, s1 = pack_s_words(pair["s_seq"])
        t0, t1 = pack_t_words(pair["t_seq"])

        print(
            f"Pair {i:02d}: "
            f"S={pair['s_seq']} "
            f"T={pair['t_seq']} "
            f"expected={pair['expected']}"
        )

        print(
            f"         S words: "
            f"0x{s0:08x} 0x{s1:08x}"
        )

        print(
            f"         T words: "
            f"0x{t0:08x} 0x{t1:08x}"
        )


if __name__ == "__main__":
    main()
