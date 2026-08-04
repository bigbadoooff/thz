def hex2int(data: bytes, divisor: int) -> float:
    return int(data.hex(), 16) / divisor

def parse_bit(byteval: int, bit: int) -> int:
    return (byteval >> bit) & 1

def parse_nbit(byteval: int, bit: int) -> int:
    return 0 if (byteval >> bit) & 1 else 1

def esp_mant(data: bytes) -> float:
    if len(data) != 4 and len(data) != 8:
        return 0.0
    mant = int.from_bytes(data[:4], "big")
    exp = int.from_bytes(data[4:], "big")
    return mant * (10 ** (exp - 6))


class MappingParser:
    def __init__(self, mapping):
        self.mapping = mapping

    def parse(self, payload: bytes) -> dict:
        result = {}
        for name, start, length, typ, divisor in self.mapping:
            try:
                raw = payload[start:start + length]
                if typ == "hex2int":
                    value = hex2int(raw, divisor)
                elif typ == "hex":
                    value = int(raw.hex(), 16) / divisor
                elif typ == "esp_mant":
                    value = esp_mant(raw)
                elif typ.startswith("bit"):
                    bit = int(typ[3:])
                    value = parse_bit(raw[0], bit)
                elif typ.startswith("nbit"):
                    bit = int(typ[4:])
                    value = parse_nbit(raw[0], bit)
                else:
                    value = None
                result[name] = value
            except Exception as e:
                result[name] = f"ERR: {e}"
        return result