fn main() {
    // Declaring the app's commands gives each an `allow-…` permission, so a
    // capability can grant the served page the update commands and nothing
    // else.
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "start",
            "repair",
            "update_ready",
            "install_update",
        ]),
    ))
    .expect("failed to run the Tauri build script");
}
