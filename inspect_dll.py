# To run on Windows

import struct

path = r"P:\Atlanta PECAS 107080x0\2026 Project\Assignment_Simplified\TPPDLIBX.DLL"

with open(path, "rb") as f:
    data = f.read()

e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
opt_magic = struct.unpack_from("<H", data, e_lfanew + 4 + 20)[0]
pe_offset = e_lfanew + 4 + 20
rva_offset = pe_offset + (96 if opt_magic == 0x10b else 112)
export_rva = struct.unpack_from("<I", data, rva_offset)[0]

num_sections = struct.unpack_from("<H", data, e_lfanew + 6)[0]
opt_size = struct.unpack_from("<H", data, e_lfanew + 4 + 16)[0]
sect_offset = e_lfanew + 4 + 20 + opt_size

def rva_to_offset(rva):
    for i in range(num_sections):
        s = sect_offset + i * 40
        vaddr = struct.unpack_from("<I", data, s + 12)[0]
        vsize = struct.unpack_from("<I", data, s + 16)[0]
        raw   = struct.unpack_from("<I", data, s + 20)[0]
        if vaddr <= rva < vaddr + vsize:
            return raw + (rva - vaddr)
    return None

exp_off = rva_to_offset(export_rva)
num_names = struct.unpack_from("<I", data, exp_off + 24)[0]
names_rva = struct.unpack_from("<I", data, exp_off + 32)[0]
names_off = rva_to_offset(names_rva)

print("Exported functions:")
for i in range(num_names):
    name_rva = struct.unpack_from("<I", data, names_off + i * 4)[0]
    name_off = rva_to_offset(name_rva)
    name = data[name_off:data.index(b"\x00", name_off)].decode()
    print(f"  {name}")