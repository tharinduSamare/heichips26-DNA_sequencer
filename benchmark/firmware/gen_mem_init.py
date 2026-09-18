data = open("firmware.bin", "rb").read()

with open("firmware.hex", "w") as f:
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