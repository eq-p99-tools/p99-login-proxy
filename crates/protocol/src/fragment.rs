use crate::soe::TransportOp;

pub const FIRST_FRAG_OVERHEAD: usize = 8;
pub const SUBSEQUENT_FRAG_OVERHEAD: usize = 4;

#[derive(Debug, Default)]
pub struct FragmentAssembler {
    fragments: std::collections::BTreeMap<u16, Vec<u8>>,
    total_len: Option<u32>,
    first_seq: Option<u16>,
}

impl FragmentAssembler {
    pub fn is_active(&self) -> bool {
        self.first_seq.is_some()
    }

    pub fn reset(&mut self) {
        self.fragments.clear();
        self.total_len = None;
        self.first_seq = None;
    }

    pub fn add(&mut self, seq: u16, raw_frag: &[u8]) -> Option<Vec<u8>> {
        if raw_frag.len() < 4 {
            return None;
        }
        let frag_data = &raw_frag[4..];

        let starts_new_sequence = self.first_seq.is_some_and(|first_seq| {
            seq != first_seq && seq.wrapping_sub(first_seq) > u16::MAX / 2
        });
        if self.first_seq.is_none() || starts_new_sequence {
            if starts_new_sequence {
                self.fragments.clear();
            }
            if frag_data.len() < 4 {
                return None;
            }
            self.first_seq = Some(seq);
            self.total_len = Some(u32::from_be_bytes(frag_data[0..4].try_into().ok()?));
            let payload = frag_data[4..].to_vec();
            self.fragments.insert(seq, payload);
        } else if self.first_seq == Some(seq) {
            // A retransmitted first fragment still contains the 4-byte total
            // length. Treating it as a continuation corrupts the payload.
            if frag_data.len() < 4 {
                return None;
            }
            let total_len = u32::from_be_bytes(frag_data[0..4].try_into().ok()?);
            if self.total_len != Some(total_len) {
                return None;
            }
            self.fragments.insert(seq, frag_data[4..].to_vec());
        } else {
            // Replacing by sequence number makes duplicate retransmissions
            // idempotent instead of counting their bytes more than once.
            self.fragments.insert(seq, frag_data.to_vec());
        }

        let total_len = self.total_len? as usize;
        if self.contiguous_len() >= total_len {
            return Some(self.reassemble(total_len));
        }
        None
    }

    fn contiguous_len(&self) -> usize {
        let Some(mut seq) = self.first_seq else {
            return 0;
        };
        let mut len = 0;
        for _ in 0..self.fragments.len() {
            let Some(payload) = self.fragments.get(&seq) else {
                break;
            };
            len += payload.len();
            seq = seq.wrapping_add(1);
        }
        len
    }

    fn reassemble(&mut self, total_len: usize) -> Vec<u8> {
        let mut joined = Vec::with_capacity(total_len);
        let mut seq = self.first_seq.expect("active assembler has first sequence");
        while joined.len() < total_len {
            let payload = self
                .fragments
                .get(&seq)
                .expect("completion requires contiguous fragments");
            joined.extend_from_slice(payload);
            seq = seq.wrapping_add(1);
        }
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

#[cfg(test)]
mod tests {
    use super::*;

    fn payload() -> Vec<u8> {
        (0..40).collect()
    }

    #[test]
    fn duplicate_fragments_do_not_complete_with_gaps() {
        let payload = payload();
        let fragments = build_fragments(&payload, 10, 16);
        let mut assembler = FragmentAssembler::default();

        assert_eq!(assembler.add(10, &fragments[0]), None);
        for _ in 0..10 {
            assert_eq!(assembler.add(12, &fragments[2]), None);
        }
        assert_eq!(assembler.add(11, &fragments[1]), None);
        assert_eq!(assembler.add(13, &fragments[3]), Some(payload));
    }

    #[test]
    fn duplicate_first_fragment_does_not_include_total_length() {
        let payload = payload();
        let fragments = build_fragments(&payload, 20, 16);
        let mut assembler = FragmentAssembler::default();

        assert_eq!(assembler.add(20, &fragments[0]), None);
        assert_eq!(assembler.add(20, &fragments[0]), None);
        assert_eq!(assembler.add(21, &fragments[1]), None);
        assert_eq!(assembler.add(22, &fragments[2]), None);
        assert_eq!(assembler.add(23, &fragments[3]), Some(payload));
    }

    #[test]
    fn reassembles_contiguous_fragments_across_sequence_wrap() {
        let payload = payload();
        let fragments = build_fragments(&payload, u16::MAX - 1, 16);
        let mut assembler = FragmentAssembler::default();

        assert_eq!(assembler.add(u16::MAX - 1, &fragments[0]), None);
        assert_eq!(assembler.add(u16::MAX, &fragments[1]), None);
        assert_eq!(assembler.add(0, &fragments[2]), None);
        assert_eq!(assembler.add(1, &fragments[3]), Some(payload));
    }
}
