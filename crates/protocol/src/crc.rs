pub fn soe_crc32(data: &[u8], key: u32) -> u32 {
    let table = crc_table();
    let mut crc = 0u32;
    for &byte in data {
        let idx = ((crc ^ u32::from(byte)) & 0xFF) as usize;
        crc = table[idx] ^ (crc >> 8);
    }
    crc ^ key
}

pub fn append_crc(packet: &[u8], key: u32, crc_bytes: u8) -> Vec<u8> {
    if crc_bytes == 0 {
        return packet.to_vec();
    }
    let crc = soe_crc32(packet, key);
    let mut out = packet.to_vec();
    if crc_bytes == 2 {
        out.extend_from_slice(&(crc as u16).to_be_bytes());
    } else {
        out.extend_from_slice(&crc.to_be_bytes());
    }
    out
}

pub fn strip_crc(packet: &[u8], crc_bytes: u8) -> &[u8] {
    if crc_bytes == 0 || packet.len() < crc_bytes as usize {
        return packet;
    }
    &packet[..packet.len() - crc_bytes as usize]
}

fn crc_table() -> &'static [u32; 256] {
    static TABLE: std::sync::OnceLock<[u32; 256]> = std::sync::OnceLock::new();
    TABLE.get_or_init(|| {
        let mut table = [0u32; 256];
        for (i, slot) in table.iter_mut().enumerate() {
            let mut crc = i as u32;
            for _ in 0..8 {
                if crc & 1 != 0 {
                    crc = (crc >> 1) ^ 0xEDB8_8320;
                } else {
                    crc >>= 1;
                }
            }
            *slot = crc;
        }
        table
    })
}
