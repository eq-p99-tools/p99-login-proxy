//! Proxy-specific login policy built on the shared EverQuest protocol crates.
//!
//! Wire framing and login packet codecs live in `eq-network`. This crate keeps
//! only the state and policy needed to rewrite a proxied P99 login session.

pub use eq_network_login::{crypto, login};
pub use eq_network_transport::{combined, crc, fragment, soe};

/// Shared server-list codecs plus the proxy's P99 visibility policy.
pub mod server_list {
    pub use eq_network_login::server_list::*;

    /// Login-server display-name prefixes visible through this P99 proxy.
    pub const P99_SERVER_PREFIXES: &[&str] = &["project 1999", "an interesting"];
}

pub mod retry;
pub mod session;

pub use eq_network_login::{
    build_combined_ack_then_packet, build_login_accepted_combined, build_login_combined,
    des_decrypt, des_encrypt, encrypt_login_credentials, is_bad_password_login_result, AppOp,
    DesKeyIv, LoginPacket, DEFAULT_DES_IV, DEFAULT_DES_KEY, LOGIN_RESULT_FAILURE_STATUS,
};
pub use eq_network_transport::{
    build_ack, build_combined, build_disconnect, build_keepalive, build_session_request,
    build_session_response, get_sequence, set_sequence, transport_opcode, wrap_app_packet,
    CombinedPacket, FragmentAssembler, SessionResponse, SubPacket, TransportOp,
};
pub use retry::{
    classify_login_accepted, fire_sso_retry, try_intercept_bad_password_combined,
    try_intercept_bad_password_packet, LoginAcceptedClass, RetryOutcome, SsoRetryNotice,
    SsoRetryState,
};
pub use server_list::{
    build_server_list_response, parse_server_list, ServerEntry, P99_SERVER_PREFIXES,
};
pub use session::ProxySessionState;
