use pyo3::exceptions::PyIOError;
use pyo3::prelude::*;
use std::fs;
use std::path::Path;

/// バイト列から文字エンコーディングを推定してエンコーディング名を返します
#[pyfunction]
pub fn detect_encoding(bytes: &[u8]) -> &'static str {
    if let Some((enc, _)) = encoding_rs::Encoding::for_bom(bytes) {
        return enc.name();
    }

    let mut detector = chardetng::EncodingDetector::new();
    detector.feed(bytes, true);
    let (enc, _) = detector.guess_assess(None, true);
    enc.name()
}

/// ファイルパスを受け取り、文字コードを自動判定してデコードした文字列と判定エンコーディング名を返します
#[pyfunction]
pub fn read_text_auto(path: &str) -> PyResult<(String, String)> {
    let file_path = Path::new(path);
    let bytes = fs::read(file_path).map_err(|e| {
        PyIOError::new_err(format!("ファイル読み込みに失敗しました ({path}): {e}"))
    })?;

    // 1. BOM チェック
    let (encoding, bom_len) = if let Some((enc, bom_len)) = encoding_rs::Encoding::for_bom(&bytes) {
        (enc, bom_len)
    } else {
        // 2. chardetng による文字コード自動推定
        let mut detector = chardetng::EncodingDetector::new();
        detector.feed(&bytes, true);
        let (enc, _) = detector.guess_assess(None, true);
        (enc, 0)
    };

    // 3. デコード
    let (cow, _, _) = encoding.decode(&bytes[bom_len..]);
    Ok((cow.into_owned(), encoding.name().to_string()))
}

/// 互換用: ファイルパスを受け取り、自動判定してデコードした文字列のみを返します
#[pyfunction]
pub fn read_text_lossless(path: &str) -> PyResult<String> {
    let (text, _) = read_text_auto(path)?;
    Ok(text)
}
