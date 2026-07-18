use cbc::cipher::{block_padding::NoPadding, BlockDecryptMut, BlockEncryptMut, KeyIvInit};
use des::Des;
use thiserror::Error;

type DesCbcEnc = cbc::Encryptor<Des>;
type DesCbcDec = cbc::Decryptor<Des>;

pub const DEFAULT_DES_KEY: [u8; 8] = [0; 8];
pub const DEFAULT_DES_IV: [u8; 8] = [0; 8];

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DesKeyIv {
    pub key: [u8; 8],
    pub iv: [u8; 8],
}

impl Default for DesKeyIv {
    fn default() -> Self {
        Self {
            key: DEFAULT_DES_KEY,
            iv: DEFAULT_DES_IV,
        }
    }
}

#[derive(Debug, Error)]
pub enum CryptoError {
    #[error("ciphertext length {0} is not a multiple of 8")]
    InvalidLength(usize),
}

/// DES-CBC encrypt with zero/null padding to an 8-byte boundary.
pub fn des_encrypt(plaintext: &[u8], key_iv: DesKeyIv) -> Vec<u8> {
    let padded_len = plaintext.len().div_ceil(8) * 8;
    let mut padded = vec![0u8; padded_len];
    padded[..plaintext.len()].copy_from_slice(plaintext);
    let mut buf = padded;
    let cipher = DesCbcEnc::new(&key_iv.key.into(), &key_iv.iv.into());
    cipher
        .encrypt_padded_mut::<NoPadding>(&mut buf, padded_len)
        .expect("padded to block size");
    buf
}

pub fn des_decrypt(ciphertext: &[u8], key_iv: DesKeyIv) -> Result<Vec<u8>, CryptoError> {
    if ciphertext.is_empty() || !ciphertext.len().is_multiple_of(8) {
        return Err(CryptoError::InvalidLength(ciphertext.len()));
    }
    let mut buf = ciphertext.to_vec();
    let cipher = DesCbcDec::new(&key_iv.key.into(), &key_iv.iv.into());
    cipher
        .decrypt_padded_mut::<NoPadding>(&mut buf)
        .map_err(|_| CryptoError::InvalidLength(ciphertext.len()))?;
    Ok(buf)
}
