//! Pure SOE transport and EQ login application protocol.
//!
//! DES-CBC exists only for legacy EQ wire compatibility; it provides no modern integrity.

pub mod error;

pub mod combined;
pub mod crc;
pub mod crypto;
pub mod fragment;
pub mod login;
pub mod retry;
pub mod server_list;
pub mod session;
pub mod soe;

pub use combined::{build_combined, CombinedPacket, SubPacket};
pub use crypto::{des_decrypt, des_encrypt, DesKeyIv, DEFAULT_DES_IV, DEFAULT_DES_KEY};
pub use fragment::FragmentAssembler;
pub use login::{
    build_combined_ack_then_packet, build_login_accepted_combined, build_login_combined,
    encrypt_login_credentials, is_bad_password_login_result, AppOp, LoginPacket,
    LOGIN_RESULT_FAILURE_STATUS,
};
pub use retry::{
    classify_login_accepted, fire_sso_retry, try_intercept_bad_password_combined,
    try_intercept_bad_password_packet, LoginAcceptedClass, RetryOutcome, SsoRetryState,
};
pub use server_list::{
    build_server_list_response, parse_server_list, ServerEntry, P99_SERVER_PREFIXES,
};
pub use session::ProxySessionState;
pub use soe::{
    build_ack, build_disconnect, build_keepalive, build_session_request, build_session_response,
    get_sequence, set_sequence, transport_opcode, wrap_app_packet, SessionResponse, TransportOp,
};
