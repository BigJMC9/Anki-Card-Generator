use std::fs;
use std::time::{SystemTime, UNIX_EPOCH};

use tauri_plugin_shell::ShellExt;

fn extract_error_from_output(stdout: &str, stderr: &str) -> String {
  if let Ok(value) = serde_json::from_str::<serde_json::Value>(stdout) {
    if let Some(message) = value
      .get("error")
      .and_then(|error| error.get("message"))
      .and_then(|message| message.as_str())
    {
      return message.to_string();
    }
  }

  let stderr_text = stderr.trim();
  if !stderr_text.is_empty() {
    return stderr_text.to_string();
  }

  let stdout_text = stdout.trim();
  if !stdout_text.is_empty() {
    return stdout_text.to_string();
  }

  "Sidecar process failed without output.".to_string()
}

fn parse_sidecar_success(stdout: &str) -> Result<serde_json::Value, String> {
  let parsed = serde_json::from_str::<serde_json::Value>(stdout).map_err(|error| {
    format!("Unable to parse sidecar JSON output: {error}. Output: {}", stdout.trim())
  })?;

  let ok = parsed.get("ok").and_then(|value| value.as_bool()).unwrap_or(false);
  if !ok {
    let message = parsed
      .get("error")
      .and_then(|error| error.get("message"))
      .and_then(|message| message.as_str())
      .unwrap_or("Sidecar returned an unknown error.");
    return Err(message.to_string());
  }

  Ok(parsed
    .get("data")
    .cloned()
    .unwrap_or(serde_json::Value::Null))
}

#[tauri::command]
async fn sidecar_ping(app: tauri::AppHandle) -> Result<String, String> {
  let output = app
    .shell()
    .sidecar("anki-sidecar")
    .map_err(|error| error.to_string())?
    .args(["--ping"])
    .output()
    .await
    .map_err(|error| error.to_string())?;

  if !output.status.success() {
    return Err(String::from_utf8_lossy(&output.stderr).trim().to_string());
  }

  Ok(String::from_utf8_lossy(&output.stdout).trim().to_string())
}

#[tauri::command]
async fn sidecar_call(
  app: tauri::AppHandle,
  action: String,
  payload_json: Option<String>,
) -> Result<serde_json::Value, String> {
  if action.trim().is_empty() {
    return Err("Action is required.".to_string());
  }

  let now = SystemTime::now()
    .duration_since(UNIX_EPOCH)
    .map_err(|error| error.to_string())?;
  let payload_file = std::env::temp_dir().join(format!(
    "anki-sidecar-payload-{}-{}.json",
    std::process::id(),
    now.as_nanos()
  ));

  let payload_text = payload_json.unwrap_or_else(|| "{}".to_string());
  let payload_path_string = payload_file.to_string_lossy().to_string();
  fs::write(&payload_file, payload_text).map_err(|error| {
    format!(
      "Failed to write sidecar payload file {}: {}",
      payload_file.display(),
      error
    )
  })?;

  let output_result = app
    .shell()
    .sidecar("anki-sidecar")
    .map_err(|error| error.to_string())?
    .args([
      "--action",
      action.as_str(),
      "--payload-file",
      payload_path_string.as_str(),
    ])
    .output()
    .await;

  let _ = fs::remove_file(&payload_file);

  let output = output_result.map_err(|error| error.to_string())?;
  let stdout = String::from_utf8_lossy(&output.stdout).to_string();
  let stderr = String::from_utf8_lossy(&output.stderr).to_string();

  if !output.status.success() {
    return Err(extract_error_from_output(&stdout, &stderr));
  }

  parse_sidecar_success(&stdout)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  tauri::Builder::default()
    .plugin(tauri_plugin_dialog::init())
    .plugin(tauri_plugin_shell::init())
    .setup(|app| {
      if cfg!(debug_assertions) {
        app.handle().plugin(
          tauri_plugin_log::Builder::default()
            .level(log::LevelFilter::Info)
            .build(),
        )?;
      }
      Ok(())
    })
    .invoke_handler(tauri::generate_handler![sidecar_ping, sidecar_call])
    .run(tauri::generate_context!())
    .expect("error while running tauri application");
}
