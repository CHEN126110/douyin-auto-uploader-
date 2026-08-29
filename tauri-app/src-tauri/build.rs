fn main() {
    let profile = std::env::var("PROFILE").unwrap_or_default();
    let target_os = std::env::var("CARGO_CFG_TARGET_OS").unwrap_or_default();

    // Work around a Windows dev-only panic inside tauri-build -> tauri-winres ->
    // embed-resource when it probes rustc during resource linking.
    if target_os == "windows" && profile == "debug" {
        println!("cargo:rerun-if-changed=tauri.conf.json");
        println!("cargo:rerun-if-changed=build.rs");
        println!("cargo:warning=Skipping tauri-build Windows resource compilation in debug profile");
        return;
    }

    tauri_build::build()
}
