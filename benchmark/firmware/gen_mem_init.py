import sys

if len(sys.argv) != 3:
    print("Usage: python3 gen_mem_init.py <input.bin> <output.hex>")
    sys.exit(1)

input_file = sys.argv[1]
output_file = sys.argv[2]

with open(input_file, "rb") as f:
    data = f.read()

with open(output_file, "w") as f:
    for i in range(0, len(data), 4):
        word = data[i:i+4]

        while len(word) < 4:
            word += b"\x00"

        value = (
            word[0]
            | (word[1] << 8)
            | (word[2] << 16)
            | (word[3] << 24)
        )

        f.write(f"{value:08x}\n")