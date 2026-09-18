#include <stdint.h>

/* ============================================================
 * Accelerator MMIO
 * ============================================================ */

#define ACCEL_BASE          0x80000000u

#define FIFO_LOW_ADDR       (ACCEL_BASE + 0x00u)
#define FIFO_HIGH_ADDR      (ACCEL_BASE + 0x04u)

#define RESULT_ADDR         (ACCEL_BASE + 0x00u)
#define STATUS_ADDR         (ACCEL_BASE + 0x04u)

/* Status bits */
#define STATUS_RESULT_EMPTY (1u << 0)
#define STATUS_RESULT_FULL  (1u << 1)
#define STATUS_SEQ_EMPTY    (1u << 2)
#define STATUS_SEQ_FULL     (1u << 3)


/* ============================================================
 * DNA configuration
 * ============================================================ */

#define SEQ_LEN             8
#define TEST_COUNT          20

/*
 * Select the test type:
 *
 * TEST_TYPE = 1:
 *     One S sequence is shared by multiple T sequences.
 *
 * TEST_TYPE = 2:
 *     Every T sequence is preceded by its corresponding S
 *     sequence.
 */
#define TEST_TYPE           1

#define S_SEQ_TYPE          1u
#define T_SEQ_TYPE          0u

/*
 * Accelerator sequence FIFO depth.
 *
 * One sequence occupies one FIFO entry.
 */
#define FIFO_DEPTH          16


/* ============================================================
 * MMIO access
 * ============================================================ */

static inline void mmio_write(uint32_t addr, uint32_t data)
{
    *(volatile uint32_t *)addr = data;
}

static inline uint32_t mmio_read(uint32_t addr)
{
    return *(volatile uint32_t *)addr;
}


/* ============================================================
 * DNA sequence data
 *
 * A = 0
 * C = 1
 * G = 2
 * T = 3
 *
 * The S sequence is intentionally stored in the same order as
 * the input file used by the SystemVerilog testbench.
 *
 * The send_sequence() function reverses the S sequence when
 * encoding it, matching:
 *
 *     s_seq[(`N-1-i)*2 +: 2] = tmp[1:0];
 * ============================================================ */

static const uint8_t seq_s[TEST_COUNT][SEQ_LEN] = {

    {0, 1, 1, 1, 0, 3, 3, 2},
    {0, 1, 1, 1, 0, 3, 3, 2},
    {0, 1, 1, 1, 0, 3, 3, 2},
    {0, 1, 1, 1, 0, 3, 3, 2},
    {0, 1, 1, 1, 0, 3, 3, 2},
    {0, 1, 1, 1, 0, 3, 3, 2},
    {0, 1, 1, 1, 0, 3, 3, 2},
    {0, 1, 1, 1, 0, 3, 3, 2},
    {0, 1, 1, 1, 0, 3, 3, 2},
    {0, 1, 1, 1, 0, 3, 3, 2},
    {0, 1, 1, 1, 0, 3, 3, 2},
    {0, 1, 1, 1, 0, 3, 3, 2},
    {0, 1, 1, 1, 0, 3, 3, 2},
    {0, 1, 1, 1, 0, 3, 3, 2},
    {0, 1, 1, 1, 0, 3, 3, 2},
    {0, 1, 1, 1, 0, 3, 3, 2},
    {0, 1, 1, 1, 0, 3, 3, 2},
    {0, 1, 1, 1, 0, 3, 3, 2},
    {0, 1, 1, 1, 0, 3, 3, 2},
    {0, 1, 1, 1, 0, 3, 3, 2}
};


static const uint8_t seq_t[TEST_COUNT][SEQ_LEN] = {

    {0, 2, 1, 0, 1, 0, 2, 3},
    {0, 1, 2, 2, 1, 0, 3, 0},
    {2, 0, 3, 2, 1, 0, 2, 3},
    {1, 1, 1, 0, 3, 1, 2, 3},
    {0, 1, 2, 2, 3, 2, 1, 1},
    {0, 1, 1, 1, 1, 0, 3, 2},
    {0, 0, 2, 1, 3, 0, 1, 3},
    {1, 0, 1, 1, 2, 3, 0, 3},
    {2, 0, 1, 3, 1, 0, 3, 0},
    {0, 1, 1, 0, 0, 0, 0, 3},
    {3, 1, 1, 0, 3, 2, 3, 2},
    {0, 1, 1, 0, 1, 3, 3, 3},
    {1, 2, 1, 3, 3, 3, 2, 1},
    {2, 1, 1, 2, 3, 3, 1, 3},
    {0, 1, 1, 1, 1, 0, 0, 3},
    {0, 1, 2, 1, 1, 0, 3, 3},
    {0, 3, 1, 1, 2, 3, 3, 2},
    {1, 0, 0, 3, 3, 0, 1, 1},
    {0, 1, 1, 0, 3, 2, 3, 0},
    {1, 1, 1, 3, 3, 0, 3, 0}
};

/*
Expected results for the above sequence pairs
    Result[0] = 6
    Result[1] = 7
    Result[2] = 5
    Result[3] = 11
    Result[4] = 4
    Result[5] = 10
    Result[6] = 5
    Result[7] = 7
    Result[8] = 9
    Result[9] = 7
    Result[10] = 10
    Result[11] = 9
    Result[12] = 8
    Result[13] = 7
    Result[14] = 9
    Result[15] = 12
    Result[16] = 10
    Result[17] = 7
    Result[18] = 8
    Result[19] = 8
*/

volatile uint32_t results[TEST_COUNT];


/* ============================================================
 * Wait until sequence FIFO has space
 * ============================================================ */

static void wait_seq_fifo_not_full(void)
{
    while (mmio_read(STATUS_ADDR) & STATUS_SEQ_FULL) {
        /* wait */
    }
}


/* ============================================================
 * Wait until result FIFO has data
 * ============================================================ */

static void wait_result_available(void)
{
    while (mmio_read(STATUS_ADDR) & STATUS_RESULT_EMPTY) {
        /* wait */
    }
}


/* ============================================================
 * Send one sequence to accelerator
 *
 * LOW cycle:
 *      bits [7:0]
 *
 * HIGH cycle:
 *      bits [15:8] + sequence type
 *
 * The accelerator input is therefore 9 bits:
 *
 *      {seq_type, seq_in[7:0]}
 *
 * S sequence:
 *      Encoded in reverse order to match the SV testbench.
 *
 * T sequence:
 *      Encoded in normal order.
 * ============================================================ */

static void send_sequence(
    const uint8_t *seq,
    uint32_t seq_type
)
{
    uint16_t encoded = 0;

    /*
     * Encode the 8 DNA bases.
     *
     * S sequence:
     *
     *     Base 0 -> bits [15:14]
     *     Base 1 -> bits [13:12]
     *     ...
     *     Base 7 -> bits [1:0]
     *
     * This matches the SV:
     *
     *     s_seq[(N-1-i)*2 +: 2]
     *
     * T sequence:
     *
     *     Base 0 -> bits [1:0]
     *     Base 1 -> bits [3:2]
     *     ...
     *     Base 7 -> bits [15:14]
     */

    for (int i = 0; i < SEQ_LEN; i++) {

        uint32_t shift;

        if (seq_type == S_SEQ_TYPE) {
            shift = 2 * (SEQ_LEN - 1 - i);
        }
        else {
            shift = 2 * i;
        }

        encoded |=
            ((uint16_t)(seq[i] & 0x3u)) << shift;
    }

    /*
     * A complete sequence occupies one FIFO entry.
     *
     * Wait before sending it so that the sequence FIFO
     * does not overflow.
     */
    wait_seq_fifo_not_full();

    /*
     * First transfer:
     *
     *     FIFO_LOW
     *     bits [7:0]
     */
    mmio_write(
        FIFO_LOW_ADDR,
        encoded & 0xFFu
    );

    /*
     * Second transfer:
     *
     *     FIFO_HIGH
     *     bits [15:8] + sequence type
     *
     * Accelerator sees:
     *
     *     data_in[7:0] = encoded[15:8]
     *     data_in[8]   = seq_type
     */
    mmio_write(
        FIFO_HIGH_ADDR,
        ((uint32_t)(encoded >> 8)) |
        ((seq_type & 0x1u) << 8)
    );
}


/* ============================================================
 * Read one result
 * ============================================================ */

static uint32_t read_result(void)
{
    wait_result_available();

    return mmio_read(RESULT_ADDR);
}


/* ============================================================
 * Main
 * ============================================================ */

int main(void)
{
    int test_index = 0;

    /*
     * --------------------------------------------------------
     * TEST TYPE 1
     * --------------------------------------------------------
     *
     * One S sequence is shared by multiple T sequences.
     *
     * The 16-entry FIFO can therefore contain:
     *
     *     S + 15*T
     *
     * followed by:
     *
     *     S + 5*T
     *
     * for the remaining 5 tests.
     */
#if TEST_TYPE == 1

    while (test_index < TEST_COUNT) {

        /*
         * Send one S sequence.
         */
        send_sequence(
            seq_s[test_index],
            S_SEQ_TYPE
        );

        /*
         * Send up to 15 T sequences.
         */
        int t_count = 0;

        while (
            t_count < (FIFO_DEPTH - 1) &&
            test_index + t_count < TEST_COUNT
        ) {
            send_sequence(
                seq_t[test_index + t_count],
                T_SEQ_TYPE
            );

            t_count++;
        }

        /*
         * Read the corresponding results.
         */
        for (int i = 0; i < t_count; i++) {
            results[test_index + i] = read_result();
        }

        test_index += t_count;
    }


/* ============================================================
 * TEST TYPE 2
 * ============================================================ */

#elif TEST_TYPE == 2

    /*
     * Each test requires:
     *
     *     S + T
     *
     * Therefore each test consumes 2 FIFO entries.
     *
     * With a 16-entry FIFO:
     *
     *     16 / 2 = 8 tests per batch
     */

    while (test_index < TEST_COUNT) {

        int batch_count = 0;

        /*
         * Send S/T pairs.
         */
        while (
            batch_count < (FIFO_DEPTH / 2) &&
            test_index + batch_count < TEST_COUNT
        ) {

            /*
             * Send S sequence.
             */
            send_sequence(
                seq_s[test_index + batch_count],
                S_SEQ_TYPE
            );

            /*
             * Send corresponding T sequence.
             */
            send_sequence(
                seq_t[test_index + batch_count],
                T_SEQ_TYPE
            );

            batch_count++;
        }

        /*
         * Read results corresponding to this batch.
         */
        for (int i = 0; i < batch_count; i++) {
            results[test_index + i] = read_result();
        }

        test_index += batch_count;
    }


#else

#error "Unsupported TEST_TYPE. Use TEST_TYPE 1 or 2."

#endif


    /*
     * Keep CPU here so the simulation can inspect
     * the results array.
     */
    while (1) {
        /* done */
    }

    return 0;
}
