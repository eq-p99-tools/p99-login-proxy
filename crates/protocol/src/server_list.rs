use crate::login::AppOp;

pub const P99_SERVER_PREFIXES: &[&str] = &["project 1999", "an interesting"];

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ServerEntry {
    pub ip: String,
    pub list_id: u32,
    pub runtime_id: u32,
    pub name: String,
    pub language: String,
    pub region: String,
    pub status: u32,
    pub player_count: u32,
    pub raw: Vec<u8>,
}

pub fn parse_server_list(app_payload: &[u8]) -> Option<(Vec<ServerEntry>, [u8; 16])> {
    if app_payload.len() < 20 {
        return None;
    }
    let data = &app_payload[2..];
    let mut header = [0u8; 16];
    header.copy_from_slice(&data[..16]);
    let count = u32::from_le_bytes(data[16..20].try_into().ok()?) as usize;
    let mut pos = 20;
    let mut servers = Vec::new();
    while pos < data.len() && servers.len() < count {
        let start = pos;
        let Some(ip) = read_cstr(data, &mut pos) else {
            break;
        };
        let Some(list_id) = read_u32_le(data, &mut pos) else {
            break;
        };
        let Some(runtime_id) = read_u32_le(data, &mut pos) else {
            break;
        };
        let Some(name) = read_cstr(data, &mut pos) else {
            break;
        };
        let Some(language) = read_cstr(data, &mut pos) else {
            break;
        };
        let Some(region) = read_cstr(data, &mut pos) else {
            break;
        };
        let Some(status) = read_u32_le(data, &mut pos) else {
            break;
        };
        let Some(player_count) = read_u32_le(data, &mut pos) else {
            break;
        };
        servers.push(ServerEntry {
            ip,
            list_id,
            runtime_id,
            name,
            language,
            region,
            status,
            player_count,
            raw: data[start..pos].to_vec(),
        });
    }
    Some((servers, header))
}

fn read_u32_le(data: &[u8], pos: &mut usize) -> Option<u32> {
    let bytes = data.get(*pos..*pos + 4)?;
    *pos += 4;
    Some(u32::from_le_bytes(bytes.try_into().ok()?))
}

fn read_cstr(data: &[u8], pos: &mut usize) -> Option<String> {
    let start = *pos;
    let end = data[*pos..].iter().position(|&b| b == 0)? + *pos;
    let s = String::from_utf8_lossy(&data[start..end]).to_string();
    *pos = end + 1;
    Some(s)
}

pub fn build_server_list_response(servers: &[ServerEntry], header_bytes: &[u8; 16]) -> Vec<u8> {
    let mut out = Vec::new();
    out.extend_from_slice(&(AppOp::ServerListResponse as u16).to_le_bytes());
    out.extend_from_slice(header_bytes);
    out.extend_from_slice(&(servers.len() as u32).to_le_bytes());
    for s in servers {
        out.extend_from_slice(&s.raw);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn read_fixture(name: &str) -> Vec<u8> {
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("tests/fixtures")
            .join(name);
        let hex: String = std::fs::read_to_string(path).expect("fixture");
        hex::decode(hex.trim()).expect("hex decode")
    }

    #[test]
    fn parse_assembled_capture_server_list() {
        let app = read_fixture("server_list_assembled.hex");
        let (servers, _) = parse_server_list(&app).expect("should parse capture assembly");
        assert_eq!(servers.len(), 110);
        assert!(servers.iter().any(|s| s.name.starts_with("Project 1999")));
    }
}
