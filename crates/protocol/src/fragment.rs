use crate::soe::TransportOp;

pub const FIRST_FRAG_OVERHEAD: usize = 8;
pub const SUBSEQUENT_FRAG_OVERHEAD: usize = 4;

#[derive(Debug, Default)]
pub struct FragmentAssembler {
    fragments: std::collections::BTreeMap<u16, Vec<u8>>,
    total_len: Option<u32>,
    first_seq: Option<u16>,
    accumulated: usize,
}

impl FragmentAssembler {
    pub fn is_active(&self) -> bool {
        self.first_seq.is_some()
    }

    pub fn reset(&mut self) {
        self.fragments.clear();
        self.total_len = None;
        self.first_seq = None;
        self.accumulated = 0;
    }

    pub fn add(&mut self, seq: u16, raw_frag: &[u8]) -> Option<Vec<u8>> {
        if raw_frag.len() < 4 {
            return None;
        }
        let frag_data = &raw_frag[4..];

        if self.first_seq.is_none() || seq < self.first_seq.unwrap_or(seq) {
            if self.first_seq.is_some() && seq < self.first_seq.unwrap() {
                self.fragments.clear();
                self.accumulated = 0;
            }
            self.first_seq = Some(seq);
            if frag_data.len() < 4 {
                return None;
            }
            self.total_len = Some(u32::from_be_bytes(frag_data[0..4].try_into().ok()?));
            let payload = frag_data[4..].to_vec();
            self.accumulated = payload.len();
            self.fragments.insert(seq, payload);
        } else {
            let payload = frag_data.to_vec();
            self.accumulated += payload.len();
            self.fragments.insert(seq, payload);
        }

        let total = self.total_len?;
        if self.accumulated >= total as usize {
            return Some(self.reassemble(total as usize));
        }
        None
    }

    fn reassemble(&mut self, total_len: usize) -> Vec<u8> {
        let ordered: Vec<_> = self.fragments.values().map(|d| d.as_slice()).collect();
        let mut joined: Vec<u8> = ordered.concat();
        self.reset();
        joined.truncate(total_len);
        joined
    }
}

pub fn parse_first_fragment_header(data: &[u8]) -> Option<(u16, u32, u16)> {
    if data.len() < 10 {
        return None;
    }
    let op = u16::from_be_bytes([data[0], data[1]]);
    let _seq = u16::from_be_bytes([data[2], data[3]]);
    let total_len = u32::from_be_bytes(data[4..8].try_into().ok()?);
    let app_op = u16::from_le_bytes([data[8], data[9]]);
    Some((op, total_len, app_op))
}

pub fn build_fragments(app_payload: &[u8], start_seq: u16, max_packet: usize) -> Vec<Vec<u8>> {
    let total_len = app_payload.len();
    let first_capacity = max_packet.saturating_sub(FIRST_FRAG_OVERHEAD);
    let subsequent_capacity = max_packet.saturating_sub(SUBSEQUENT_FRAG_OVERHEAD);
    let mut frags = Vec::new();

    let chunk = &app_payload[..app_payload.len().min(first_capacity)];
    let mut hdr = Vec::with_capacity(FIRST_FRAG_OVERHEAD + chunk.len());
    hdr.extend_from_slice(&(TransportOp::Fragment as u16).to_be_bytes());
    hdr.extend_from_slice(&start_seq.to_be_bytes());
    hdr.extend_from_slice(&(total_len as u32).to_be_bytes());
    hdr.extend_from_slice(chunk);
    frags.push(hdr);

    let mut pos = first_capacity;
    let mut seq = start_seq.wrapping_add(1);
    while pos < total_len {
        let end = (pos + subsequent_capacity).min(total_len);
        let chunk = &app_payload[pos..end];
        let mut hdr = Vec::with_capacity(SUBSEQUENT_FRAG_OVERHEAD + chunk.len());
        hdr.extend_from_slice(&(TransportOp::Fragment as u16).to_be_bytes());
        hdr.extend_from_slice(&seq.to_be_bytes());
        hdr.extend_from_slice(chunk);
        frags.push(hdr);
        pos = end;
        seq = seq.wrapping_add(1);
    }
    frags
}
