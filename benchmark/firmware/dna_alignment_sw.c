/*
 * DNA sequence alignment software reference
 * Target: PicoRV32 / bare-metal RISC-V
 *
 * Equivalent to the Python reference implementation.
 *
 * Compile examples:
 *   -DTYPE=1 -DN=10
 *   -DTYPE=2 -DN=100
 */

 #define PC 0 // run on PC for debugging

#include <stdint.h>

#if PC == 1
#include <stdio.h>
#endif

/* ============================================================
 * Configuration
 * ============================================================ */

#ifndef TYPE
#define TYPE 1
#endif

#ifndef N
#define N 20
#endif

#define SEQ_LEN 8


/* Scoring parameters - same as Python */
#define MATCH_SCORE       2
#define MISMATCH_SCORE   -1
#define GAP_OPEN         -2
#define GAP_EXTEND       -1

/* A sufficiently small value to represent -infinity.
 * Scores for our sequence sizes will never reach this value.
 */
#define NEG_INF (-1000000)

/*
 * Set this to 1 if you want the final result written
 * to an MMIO address for your hardware testbench.
 */
#ifndef USE_MMIO
#define USE_MMIO 0
#endif

#if USE_MMIO
#define RESULT_MMIO ((volatile uint32_t *)0x20000000)
#endif


/* ============================================================
 * Sequence memory
 *
 * The sequences can be initialized from your generated data.
 *
 * seq1_mem[i] = first sequence of test i
 * seq2_mem[i] = second sequence of test i
 *
 * For TYPE=1, seq1_mem[0] is reused for all tests.
 * ============================================================ */

static const uint8_t seq1_mem[N][SEQ_LEN] = {
    {0,1,1,1,0,3,3,2},
    {0,1,1,1,0,3,3,2},
    {0,1,1,1,0,3,3,2},
    {0,1,1,1,0,3,3,2},
    {0,1,1,1,0,3,3,2},
    {0,1,1,1,0,3,3,2},
    {0,1,1,1,0,3,3,2},
    {0,1,1,1,0,3,3,2},
    {0,1,1,1,0,3,3,2},
    {0,1,1,1,0,3,3,2},
    {0,1,1,1,0,3,3,2},
    {0,1,1,1,0,3,3,2},
    {0,1,1,1,0,3,3,2},
    {0,1,1,1,0,3,3,2},
    {0,1,1,1,0,3,3,2},
    {0,1,1,1,0,3,3,2},
    {0,1,1,1,0,3,3,2},
    {0,1,1,1,0,3,3,2},
    {0,1,1,1,0,3,3,2},
    {0,1,1,1,0,3,3,2}
};

static const uint8_t seq2_mem[N][SEQ_LEN] = {
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

/* ============================================================
 * Output memory
 *
 * alignment_results[i] contains the maximum local alignment
 * score for test i.
 * ============================================================ */

volatile int32_t alignment_results[N];


/* ============================================================
 * Smith-Waterman implementation with affine gap penalty
 *
 * This follows the Python implementation:
 *
 * H[i][j]
 * Horizontal_gap[i][j]
 * Vertical_gap[i][j]
 *
 * The traceback is intentionally omitted because your
 * accelerator comparison only needs the alignment score.
 * ============================================================ */

static int32_t smith_waterman(
    const uint8_t *seq1,
    uint32_t len1,
    const uint8_t *seq2,
    uint32_t len2
)
{
    /*
     * Matrices.
     *
     * These are static so that they are placed in data/BSS
     * rather than on the PicoRV32 stack.
     */
    static int32_t H[SEQ_LEN + 1][SEQ_LEN + 1];
    static int32_t Horizontal_gap[SEQ_LEN + 1][SEQ_LEN + 1];
    static int32_t Vertical_gap[SEQ_LEN + 1][SEQ_LEN + 1];

    int32_t max_alignment_score = 0;

    uint32_t i;
    uint32_t j;

    /*
     * Initialize matrices.
     *
     * Python initializes:
     *
     * H = 0
     * Horizontal_gap = -inf
     * Vertical_gap = -inf
     */
    for (i = 0; i <= len1; i++) {
        for (j = 0; j <= len2; j++) {

            H[i][j] = 0;

            Horizontal_gap[i][j] = NEG_INF;
            Vertical_gap[i][j] = NEG_INF;
        }
    }


    /* ========================================================
     * Main dynamic-programming loop
     * ======================================================== */

    for (i = 1; i <= len1; i++) {

        for (j = 1; j <= len2; j++) {

            int32_t score;

            int32_t prev_best_diag;

            int32_t h_value;
            int32_t v_value;
            int32_t hg_value;

            int32_t cell_score;


            /*
             * Match / mismatch
             */
            if (seq1[i - 1] == seq2[j - 1]) {
                score = MATCH_SCORE;
            }
            else {
                score = MISMATCH_SCORE;
            }


            /*
             * Previous diagonal state:
             *
             * max(
             *     H[i-1][j-1],
             *     Horizontal_gap[i-1][j-1],
             *     Vertical_gap[i-1][j-1]
             * )
             */
            prev_best_diag = H[i - 1][j - 1];

            if (Horizontal_gap[i - 1][j - 1] > prev_best_diag) {
                prev_best_diag = Horizontal_gap[i - 1][j - 1];
            }

            if (Vertical_gap[i - 1][j - 1] > prev_best_diag) {
                prev_best_diag = Vertical_gap[i - 1][j - 1];
            }


            /*
             * H state
             *
             * H[i][j] = max(
             *     0,
             *     score + previous diagonal
             * )
             */
            H[i][j] = score + prev_best_diag;

            if (H[i][j] < 0) {
                H[i][j] = 0;
            }


            /*
             * Horizontal gap
             *
             * Python:
             *
             * max(
             *     H[i][j-1] + alpha,
             *     Vertical_gap[i][j-1] + alpha,
             *     Horizontal_gap[i][j-1] + beta
             * )
             */
            h_value = H[i][j - 1] + GAP_OPEN;

            v_value = Vertical_gap[i][j - 1] + GAP_OPEN;

            if (v_value > h_value) {
                h_value = v_value;
            }

            hg_value = Horizontal_gap[i][j - 1] + GAP_EXTEND;

            if (hg_value > h_value) {
                h_value = hg_value;
            }

            Horizontal_gap[i][j] = h_value;


            /*
             * Vertical gap
             *
             * Python:
             *
             * max(
             *     H[i-1][j] + alpha,
             *     Horizontal_gap[i-1][j] + alpha,
             *     Vertical_gap[i-1][j] + beta
             * )
             */
            h_value = H[i - 1][j] + GAP_OPEN;

            hg_value = Horizontal_gap[i - 1][j] + GAP_OPEN;

            if (hg_value > h_value) {
                h_value = hg_value;
            }

            v_value = Vertical_gap[i - 1][j] + GAP_EXTEND;

            if (v_value > h_value) {
                h_value = v_value;
            }

            Vertical_gap[i][j] = h_value;


            /*
             * Final score for this cell
             *
             * cell_score = max(
             *     0,
             *     H,
             *     Horizontal_gap,
             *     Vertical_gap
             * )
             */
            cell_score = H[i][j];

            if (Horizontal_gap[i][j] > cell_score) {
                cell_score = Horizontal_gap[i][j];
            }

            if (Vertical_gap[i][j] > cell_score) {
                cell_score = Vertical_gap[i][j];
            }

            if (cell_score < 0) {
                cell_score = 0;
            }


            /*
             * Global maximum
             */
            if (cell_score > max_alignment_score) {
                max_alignment_score = cell_score;
            }
        }
    }

    return max_alignment_score;
}


/* ============================================================
 * Main
 * ============================================================ */

 #if PC == 0

int main(void)
{
    uint32_t test;

    /*
     * Run N alignment tests.
     */
    for (test = 0; test < N; test++) {

        const uint8_t *seq1;
        const uint8_t *seq2;

        uint32_t len1;
        uint32_t len2;

        int32_t score;


        /*
         * TYPE 1:
         *
         * Same seq1 for every test.
         *
         * This corresponds to:
         *
         * if type1:
         *     fixed_Seq = generate_seq(fixed_Seq)
         *
         * in your Python script.
         */
#if TYPE == 1

        seq1 = seq1_mem[0];
        len1 = SEQ_LEN;

#else

        /*
         * TYPE 2:
         *
         * Every test has a separate seq1.
         */
        seq1 = seq1_mem[test];
        len1 = SEQ_LEN;

#endif


        /*
         * seq2 is always different for every test.
         */
        seq2 = seq2_mem[test];
        len2 = SEQ_LEN;


        /*
         * Calculate alignment.
         */
        score = smith_waterman(
            seq1,
            len1,
            seq2,
            len2
        );


        /*
         * Store result in memory.
         */
        alignment_results[test] = score;


#if USE_MMIO

        /*
         * Optional:
         * write each result to an MMIO register.
         *
         * This can be useful when connecting PicoRV32
         * to your testbench / ASIC interface.
         */
        *RESULT_MMIO = (uint32_t)score;

#endif
    }


    /*
     * Prevent compiler from assuming that the program ends.
     *
     * On a bare-metal PicoRV32 system there is normally
     * no operating system to return to.
     */
    while (1) {
        /*
         * Optionally put a breakpoint here.
         */
    }

    return 0;
}

#endif

#if PC == 1

int main(void)
{
    uint32_t test;

    printf("DNA Smith-Waterman software reference\n");
    printf("TYPE = %d\n", TYPE);
    printf("N    = %d\n\n", N);

    for (test = 0; test < N; test++) {

        const uint8_t *seq1;
        const uint8_t *seq2;

        uint32_t len1;
        uint32_t len2;

        int32_t score;

#if TYPE == 1

        seq1 = seq1_mem[0];
        len1 = SEQ_LEN;

#else

        seq1 = seq1_mem[test];
        len1 = SEQ_LEN;

#endif

        seq2 = seq2_mem[test];
        len2 = SEQ_LEN;

        score = smith_waterman(
            seq1,
            len1,
            seq2,
            len2
        );

        alignment_results[test] = score;

        printf(
            "Test %2d: Alignment score = %d\n",
            test,
            score
        );
    }

    printf("\nResults:\n");

    for (test = 0; test < N; test++) {
        printf("%d\n", alignment_results[test]);
    }

    return 0;
}

#endif


