use crate::error::{ProtocolError, Result};
use crate::soe::TransportOp;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SubPacket {
    pub offset: usize,
    pub length: usize,
    pub transport_op: u16,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CombinedPacket {
    pub subs: Vec<SubPacket>,
}

impl CombinedPacket {
    pub fn parse(buf: &[u8], start_index: usize, length: Option<usize>) -> Result<Self> {
        let end = start_index + length.unwrap_or_else(|| buf.len().saturating_sub(start_index));
        if end < start_index + 2 {
            return Err(ProtocolError::TooShort {
                need: 2,
                got: end.saturating_sub(start_index),
            });
        }
        let mut pos = start_index + 2;
        let mut subs = Vec::new();
        while pos < end {
            if pos >= buf.len() {
                break;
            }
            let mut sublen = buf[pos] as usize;
            pos += 1;
            if sublen == 0xFF {
                if pos + 2 > end {
                    break;
                }
                sublen = u16::from_be_bytes([buf[pos], buf[pos + 1]]) as usize;
                pos += 2;
            }
            if sublen == 0 || pos + sublen > end {
                break;
            }
            let op = if pos + 2 <= buf.len() {
                u16::from_be_bytes([buf[pos], buf[pos + 1]])
            } else {
                0
            };
            subs.push(SubPacket {
                offset: pos,
                length: sublen,
                transport_op: op,
            });
            pos += sublen;
        }
        Ok(Self { subs })
    }

    pub fn sub_bytes<'a>(&self, buf: &'a [u8], sub: &SubPacket) -> &'a [u8] {
        &buf[sub.offset..sub.offset + sub.length]
    }
}

pub fn build_combined(sub_packets: &[&[u8]]) -> Vec<u8> {
    let mut body = Vec::new();
    for sub in sub_packets {
        let slen = sub.len();
        if slen >= 0xFF {
            body.push(0xFF);
            body.extend_from_slice(&(slen as u16).to_be_bytes());
        } else {
            body.push(slen as u8);
        }
        body.extend_from_slice(sub);
    }
    let mut out = Vec::with_capacity(2 + body.len());
    out.extend_from_slice(&(TransportOp::Combined as u16).to_be_bytes());
    out.extend_from_slice(&body);
    out
}

pub fn split_combined(data: &[u8]) -> Vec<Vec<u8>> {
    CombinedPacket::parse(data, 0, None)
        .map(|cp| {
            cp.subs
                .iter()
                .map(|s| data[s.offset..s.offset + s.length].to_vec())
                .collect()
        })
        .unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::soe::{build_ack, transport_opcode};

    #[test]
    fn roundtrip_combined() {
        let ack = build_ack(1);
        let packet = [0x00, 0x09, 0x00, 0x02, 0x02, 0x00];
        let combined = build_combined(&[&ack, &packet]);
        assert_eq!(transport_opcode(&combined), TransportOp::Combined as u16);
        let subs = split_combined(&combined);
        assert_eq!(subs.len(), 2);
    }
}
