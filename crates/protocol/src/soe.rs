use crate::error::{ProtocolError, Result};

#[repr(u16)]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TransportOp {
    SessionRequest = 0x0001,
    SessionResponse = 0x0002,
    Combined = 0x0003,
    SessionDisconnect = 0x0005,
    KeepAlive = 0x0006,
    SessionStatRequest = 0x0007,
    SessionStatResponse = 0x0008,
    Packet = 0x0009,
    Fragment = 0x000D,
    OutOfOrder = 0x0011,
    Ack = 0x0015,
    AppCombined = 0x0019,
    OutOfSession = 0x001D,
}

impl TransportOp {
    pub fn from_u16(value: u16) -> Option<Self> {
        match value {
            0x0001 => Some(Self::SessionRequest),
            0x0002 => Some(Self::SessionResponse),
            0x0003 => Some(Self::Combined),
            0x0005 => Some(Self::SessionDisconnect),
            0x0006 => Some(Self::KeepAlive),
            0x0007 => Some(Self::SessionStatRequest),
            0x0008 => Some(Self::SessionStatResponse),
            0x0009 => Some(Self::Packet),
            0x000D => Some(Self::Fragment),
            0x0011 => Some(Self::OutOfOrder),
            0x0015 => Some(Self::Ack),
            0x0019 => Some(Self::AppCombined),
            0x001D => Some(Self::OutOfSession),
            _ => None,
        }
    }

    pub fn name(self) -> &'static str {
        match self {
            Self::SessionRequest => "SessionRequest",
            Self::SessionResponse => "SessionResponse",
            Self::Combined => "Combined",
            Self::SessionDisconnect => "SessionDisconnect",
            Self::KeepAlive => "KeepAlive",
            Self::SessionStatRequest => "SessionStatRequest",
            Self::SessionStatResponse => "SessionStatResponse",
            Self::Packet => "Packet",
            Self::Fragment => "Fragment",
            Self::OutOfOrder => "OutOfOrder",
            Self::Ack => "Ack",
            Self::AppCombined => "AppCombined",
            Self::OutOfSession => "OutOfSession",
        }
    }
}

pub fn transport_opcode(data: &[u8]) -> u16 {
    if data.len() < 2 {
        return 0;
    }
    u16::from_be_bytes([data[0], data[1]])
}

/// Read the 2-byte big-endian sequence at `offset + 2`.
///
/// Datagrams arrive from the network with arbitrary length, so a buffer too
/// short to hold the sequence field yields 0 rather than panicking.
pub fn get_sequence(data: &[u8], offset: usize) -> u16 {
    if data.len() < offset + 4 {
        return 0;
    }
    u16::from_be_bytes([data[offset + 2], data[offset + 3]])
}

/// Write the 2-byte big-endian sequence at `offset + 2`.
///
/// No-op when `buf` is too short to hold the sequence field, so truncated or
/// malformed datagrams cannot panic the proxy task.
pub fn set_sequence(buf: &mut [u8], offset: usize, seq: u16) {
    if buf.len() < offset + 4 {
        return;
    }
    let bytes = seq.to_be_bytes();
    buf[offset + 2] = bytes[0];
    buf[offset + 3] = bytes[1];
}

pub fn build_ack(sequence: u16) -> [u8; 4] {
    let mut out = [0u8; 4];
    out[0..2].copy_from_slice(&(TransportOp::Ack as u16).to_be_bytes());
    out[2..4].copy_from_slice(&sequence.to_be_bytes());
    out
}

pub fn build_keepalive() -> [u8; 2] {
    (TransportOp::KeepAlive as u16).to_be_bytes()
}

pub fn build_disconnect() -> [u8; 2] {
    (TransportOp::SessionDisconnect as u16).to_be_bytes()
}

pub fn build_session_request() -> [u8; 2] {
    (TransportOp::SessionRequest as u16).to_be_bytes()
}

/// Minimal valid SessionResponse (17-byte wire format).
pub fn build_session_response() -> Vec<u8> {
    let mut out = vec![0u8; 17];
    out[0..2].copy_from_slice(&(TransportOp::SessionResponse as u16).to_be_bytes());
    out[6..10].copy_from_slice(&1u32.to_be_bytes()); // encode_key
    out[13..17].copy_from_slice(&512u32.to_le_bytes()); // max_packet_size
    out
}

pub fn wrap_app_packet(sequence: u16, app_payload: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(4 + app_payload.len());
    out.extend_from_slice(&(TransportOp::Packet as u16).to_be_bytes());
    out.extend_from_slice(&sequence.to_be_bytes());
    out.extend_from_slice(app_payload);
    out
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SessionResponse {
    pub connect_code: u32,
    pub encode_key: u32,
    pub crc_bytes: u8,
    pub encode_pass1: u8,
    pub encode_pass2: u8,
    pub max_packet_size: u32,
}

pub fn parse_session_response(data: &[u8]) -> Result<SessionResponse> {
    if data.len() < 17 {
        return Err(ProtocolError::TooShort {
            need: 17,
            got: data.len(),
        });
    }
    let connect_code = u32::from_be_bytes(data[2..6].try_into().unwrap());
    let encode_key = u32::from_be_bytes(data[6..10].try_into().unwrap());
    Ok(SessionResponse {
        connect_code,
        encode_key,
        crc_bytes: data[10],
        encode_pass1: data[11],
        encode_pass2: data[12],
        max_packet_size: u32::from_le_bytes(data[13..17].try_into().unwrap()),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn build_ack_wire_format() {
        let ack = build_ack(0x1234);
        assert_eq!(transport_opcode(&ack), TransportOp::Ack as u16);
        assert_eq!(get_sequence(&ack, 0), 0x1234);
    }
}
