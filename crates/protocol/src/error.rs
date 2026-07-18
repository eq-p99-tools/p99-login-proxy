use thiserror::Error;

#[derive(Debug, Error, PartialEq, Eq)]
pub enum ProtocolError {
    #[error("buffer too short: need {need} bytes, got {got}")]
    TooShort { need: usize, got: usize },
    #[error("malformed combined packet at offset {offset}")]
    MalformedCombined { offset: usize },
    #[error("login sub-packet length {len} exceeds one-byte wire capacity")]
    LoginSubLengthOverflow { len: usize },
    #[error("not a combined ACK+Login packet")]
    NotLoginCombined,
}

pub type Result<T> = std::result::Result<T, ProtocolError>;
