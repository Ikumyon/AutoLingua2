#[cfg(feature = "python")]
use pyo3::prelude::*;

pub mod bootstrap;
#[cfg(feature = "python")]
pub mod encoding;
pub mod platform;

#[cfg(feature = "python")]
#[pymodule]
fn autolingua2_native(py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    // 1. エンコーディング関連の登録 (トップレベル & サブモジュール)
    let encoding_module = PyModule::new(py, "encoding")?;
    encoding_module.add_function(wrap_pyfunction!(encoding::detect_encoding, &encoding_module)?)?;
    encoding_module.add_function(wrap_pyfunction!(encoding::read_text_auto, &encoding_module)?)?;
    encoding_module.add_function(wrap_pyfunction!(encoding::read_text_lossless, &encoding_module)?)?;
    m.add_submodule(&encoding_module)?;

    m.add_function(wrap_pyfunction!(encoding::detect_encoding, m)?)?;
    m.add_function(wrap_pyfunction!(encoding::read_text_auto, m)?)?;
    m.add_function(wrap_pyfunction!(encoding::read_text_lossless, m)?)?;

    // 2. プラットフォーム関連の登録 (トップレベル & サブモジュール)
    let platform_module = PyModule::new(py, "platform")?;
    platform_module.add_function(wrap_pyfunction!(platform::allocate_debug_console, &platform_module)?)?;
    platform_module.add_function(wrap_pyfunction!(platform::is_executable_plugin, &platform_module)?)?;
    platform_module.add_function(wrap_pyfunction!(platform::plugin_creation_flags, &platform_module)?)?;
    platform_module.add_class::<platform::ProcessGroup>()?;
    m.add_submodule(&platform_module)?;
    let bootstrap_module = PyModule::new(py, "bootstrap")?;
    bootstrap_module.add_class::<bootstrap::bindings::CoreSession>()?;
    bootstrap_module.add_function(wrap_pyfunction!(bootstrap::bindings::update_status, &bootstrap_module)?)?;
    m.add_submodule(&bootstrap_module)?;

    Ok(())
}
