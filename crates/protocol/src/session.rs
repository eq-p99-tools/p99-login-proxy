use crate::combined::CombinedPacket;
use crate::fragment::FragmentAssembler;
use crate::login::AppOp;
use crate::server_list::{build_server_list_response, parse_server_list, P99_SERVER_PREFIXES};
use crate::soe::{get_sequence, set_sequence, TransportOp};

#[derive(Debug, Default)]
pub struct ProxySessionState {
    pub seq_to_client: u32,
    pub seq_from_server: u32,
    pub cs_offset: u32,
    fragment_assembler: FragmentAssembler,
    pending_app_opcode: Option<u16>,
}

impl ProxySessionState {
    pub fn reset(&mut self) {
        self.seq_to_client = 0;
        self.seq_from_server = 0;
        self.cs_offset = 0;
        self.fragment_assembler.reset();
        self.pending_app_opcode = None;
    }

    pub fn adjust_combined(&self, buf: &mut [u8]) {
        if let Ok(combined) = CombinedPacket::parse(buf, 0, None) {
            for sub in &combined.subs {
                match sub.transport_op {
                    x if x == TransportOp::Ack as u16 => self.rewrite_ack(buf, sub.offset),
                    x if x == TransportOp::Packet as u16 && self.cs_offset != 0 => {
                        self.shift_packet_seq(buf, sub.offset, self.cs_offset);
                    }
                    _ => {}
                }
            }
        }
    }

    pub fn adjust_ack(&self, buf: &mut [u8], offset: usize) {
        self.rewrite_ack(buf, offset);
    }

    pub fn adjust_client_packet(&self, buf: &mut [u8], offset: usize) {
        if self.cs_offset != 0 {
            self.shift_packet_seq(buf, offset, self.cs_offset);
        }
    }

    pub fn adjust_server_ack(&self, buf: &mut [u8], offset: usize) {
        if self.cs_offset == 0 {
            return;
        }
        let cur = get_sequence(buf, offset);
        let new_seq = cur.saturating_sub(self.cs_offset as u16);
        set_sequence(buf, offset, new_seq);
    }

    fn rewrite_ack(&self, buf: &mut [u8], offset: usize) {
        let new_seq = self.seq_from_server.saturating_sub(1) as u16;
        set_sequence(buf, offset, new_seq);
    }

    fn shift_packet_seq(&self, buf: &mut [u8], offset: usize, delta: u32) {
        let cur = get_sequence(buf, offset);
        set_sequence(buf, offset, cur.wrapping_add(delta as u16));
    }

    pub fn note_suppressed_server_packet(&mut self, server_seq: u16) {
        self.seq_from_server = self.seq_from_server.max(u32::from(server_seq) + 1);
    }

    pub fn note_injected_client_packet(&mut self) {
        self.cs_offset += 1;
    }

    pub fn recv_combined(
        &mut self,
        buf: &mut [u8],
        start_index: usize,
        length: Option<usize>,
    ) -> Vec<u8> {
        let len = length.unwrap_or(buf.len().saturating_sub(start_index));
        if let Ok(combined) = CombinedPacket::parse(buf, start_index, Some(len)) {
            for sub in &combined.subs {
                match sub.transport_op {
                    x if x == TransportOp::Ack as u16 => self.adjust_server_ack(buf, sub.offset),
                    x if x == TransportOp::Packet as u16 => {
                        self.rewrite_server_packet_seq(buf, sub.offset)
                    }
                    _ => {}
                }
            }
        }
        if start_index == 0 && len == buf.len() {
            buf.to_vec()
        } else {
            buf[start_index..start_index + len].to_vec()
        }
    }

    pub fn recv_packet(&mut self, buf: &mut [u8], start_index: usize, _length: Option<usize>) {
        self.rewrite_server_packet_seq(buf, start_index);
    }

    fn rewrite_server_packet_seq(&mut self, buf: &mut [u8], offset: usize) {
        let server_seq = get_sequence(buf, offset);
        set_sequence(buf, offset, self.seq_to_client as u16);
        self.seq_to_client += 1;
        if server_seq as u32 == self.seq_from_server {
            self.seq_from_server += 1;
        }
    }

    pub fn recv_fragment(
        &mut self,
        buf: &[u8],
        start_index: usize,
        length: Option<usize>,
    ) -> Option<Vec<u8>> {
        let len = length.unwrap_or(buf.len().saturating_sub(start_index));
        let raw = &buf[start_index..start_index + len];
        let server_seq = get_sequence(raw, 0);
        self.seq_from_server = u32::from(server_seq) + 1;

        if !self.fragment_assembler.is_active() && raw.len() >= 10 {
            self.pending_app_opcode = Some(u16::from_le_bytes([raw[8], raw[9]]));
        }

        if let Some(assembled) = self.fragment_assembler.add(server_seq, raw) {
            let app_opcode = self.pending_app_opcode.take();
            self.fragment_assembler.reset();
            if app_opcode != Some(AppOp::ServerListResponse as u16) {
                return None;
            }
            return Some(self.filter_and_build_server_list(&assembled));
        }
        None
    }

    fn filter_and_build_server_list(&mut self, app_payload: &[u8]) -> Vec<u8> {
        let (servers, header) = parse_server_list(app_payload).unwrap_or((Vec::new(), [0u8; 16]));
        let filtered: Vec<_> = servers
            .into_iter()
            .filter(|s| {
                let lower = s.name.to_lowercase();
                P99_SERVER_PREFIXES.iter().any(|p| lower.starts_with(p))
            })
            .collect();
        let rebuilt = build_server_list_response(&filtered, &header);
        let mut out = Vec::new();
        out.extend_from_slice(&(TransportOp::Packet as u16).to_be_bytes());
        out.extend_from_slice(&(self.seq_to_client as u16).to_be_bytes());
        out.extend_from_slice(&rebuilt);
        self.seq_to_client += 1;
        out
    }
}
