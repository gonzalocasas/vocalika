//! Vocalika desktop launcher (spike).
//!
//! The installer ships no Python environment. On first start this launcher
//! builds one with the bundled `uv` from the bundled lock export and wheel,
//! behind a progress screen; afterwards it only starts the server. Either way
//! it then runs `vocalika serve` on a free local port and points its window
//! at it. Rebuilding happens whenever the bundled stamp (a hash of the lock
//! export and wheel) differs from the one recorded by the last good install.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::collections::VecDeque;
use std::fs;
use std::io::{BufRead, BufReader, Read};
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use tauri::{AppHandle, Emitter, Manager, RunEvent, State};

const PYTHON_VERSION: &str = "3.12";
const SERVER_START_TIMEOUT: Duration = Duration::from_secs(180);

#[derive(Default)]
struct Launcher {
    server: Mutex<Option<Child>>,
    busy: Mutex<bool>,
}

#[derive(Clone, serde::Serialize)]
struct Progress {
    step: String,
    fraction: f64,
}

struct Paths {
    resources: PathBuf,
    runtime: PathBuf,
    env: PathBuf,
    library: PathBuf,
    log: PathBuf,
}

impl Paths {
    fn new(app: &AppHandle) -> Result<Self, String> {
        let resources = app
            .path()
            .resource_dir()
            .map_err(|e| e.to_string())?
            .join("resources");
        let data = app.path().app_local_data_dir().map_err(|e| e.to_string())?;
        let runtime = data.join("runtime");
        Ok(Self {
            resources,
            env: runtime.join("env"),
            runtime,
            library: data.join("library"),
            log: data.join("server.log"),
        })
    }

    fn uv(&self) -> PathBuf {
        self.resources.join(if cfg!(windows) { "uv.exe" } else { "uv" })
    }

    fn python(&self) -> PathBuf {
        if cfg!(windows) {
            self.env.join("Scripts").join("python.exe")
        } else {
            self.env.join("bin").join("python")
        }
    }

    fn installed_stamp(&self) -> PathBuf {
        self.runtime.join("stamp.txt")
    }
}

#[tauri::command]
fn start(app: AppHandle) {
    spawn_launch(app, false);
}

#[tauri::command]
fn repair(app: AppHandle) {
    spawn_launch(app, true);
}

fn spawn_launch(app: AppHandle, repair: bool) {
    {
        let launcher: State<Launcher> = app.state();
        let mut busy = launcher.busy.lock().unwrap();
        if *busy {
            return;
        }
        *busy = true;
    }
    thread::spawn(move || {
        if let Err(message) = launch(&app, repair) {
            let _ = app.emit("failed", message);
        }
        *app.state::<Launcher>().busy.lock().unwrap() = false;
    });
}

fn launch(app: &AppHandle, repair: bool) -> Result<(), String> {
    let paths = Paths::new(app)?;
    let wanted = fs::read_to_string(paths.resources.join("stamp.txt"))
        .map_err(|e| format!("The installer is incomplete (stamp.txt): {e}"))?;
    let installed = fs::read_to_string(paths.installed_stamp()).unwrap_or_default();
    if repair || installed != wanted {
        install(app, &paths, repair)?;
        fs::write(paths.installed_stamp(), &wanted).map_err(|e| e.to_string())?;
    }
    serve(app, &paths)
}

fn progress(app: &AppHandle, step: &str, fraction: f64) {
    let _ = app.emit("progress", Progress { step: step.into(), fraction });
}

fn install(app: &AppHandle, paths: &Paths, repair: bool) -> Result<(), String> {
    let started = Instant::now();
    fs::create_dir_all(&paths.runtime).map_err(|e| e.to_string())?;
    // A stale stamp means this env is from another version or a run that was
    // interrupted; either way rebuild it from scratch. A repair also drops
    // the download cache in case a cached file is what broke.
    let _ = fs::remove_file(paths.installed_stamp());
    if paths.env.exists() {
        fs::remove_dir_all(&paths.env).map_err(|e| e.to_string())?;
    }
    if repair {
        let _ = fs::remove_dir_all(paths.runtime.join("cache"));
    }

    let uv = paths.uv();
    let env = paths.env.to_string_lossy().into_owned();
    let python = paths.python().to_string_lossy().into_owned();
    let requirements = paths.resources.join("requirements.txt");
    let wheel = fs::read_dir(&paths.resources)
        .map_err(|e| e.to_string())?
        .filter_map(|entry| entry.ok().map(|entry| entry.path()))
        .find(|path| path.extension().is_some_and(|ext| ext == "whl"))
        .ok_or("The installer is incomplete (no Vocalika wheel).")?;

    progress(app, "Downloading Python…", 0.03);
    run(app, paths, &uv, &[
        "venv", "--python", PYTHON_VERSION, "--python-preference", "only-managed", &env,
    ])?;

    progress(app, "Downloading audio and machine-learning components…", 0.12);
    run(app, paths, &uv, &[
        "pip", "sync", "--compile-bytecode", "--python", &python,
        &requirements.to_string_lossy(),
    ])?;

    progress(app, "Installing Vocalika…", 0.55);
    run(app, paths, &uv, &[
        "pip", "install", "--no-deps", "--compile-bytecode", "--python", &python,
        &wheel.to_string_lossy(),
    ])?;

    // The first load of freshly written native libraries is slow (about 20 s
    // on macOS, where each one is checked). Pay that here, not at launch.
    // Import one module at a time and say which, so the screen shows motion.
    progress(app, "Preparing for first use (about half a minute)…", 0.6);
    run(app, paths, &paths.python(), &[
        "-I", "-c",
        "import importlib\n\
         for name in ('numpy', 'scipy.signal', 'librosa', 'torch', 'torchaudio.pipelines',\n\
                      'demucs.pretrained', 'fastapi', 'vocalika.cli'):\n\
         \x20   print('Loading', name.split('.')[0], flush=True)\n\
         \x20   importlib.import_module(name)",
    ])?;

    progress(app, "Downloading the separation, pitch and lyrics models…", 0.7);
    run(app, paths, &paths.python(), &["-I", "-m", "vocalika", "setup-models"])?;

    progress(app, "Installed.", 1.0);
    println!("install finished in {:.1}s", started.elapsed().as_secs_f64());
    Ok(())
}

/// Run a step, streaming its output lines to the progress screen. On failure
/// the error carries the last lines of output so the user (and we) see why.
fn run(app: &AppHandle, paths: &Paths, program: &Path, args: &[&str]) -> Result<(), String> {
    let started = Instant::now();
    let mut command = Command::new(program);
    command
        .args(args)
        .envs(isolated_environment(paths))
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    hide_console(&mut command);
    let mut child = command
        .spawn()
        .map_err(|e| format!("Could not start {}: {e}", program.display()))?;

    let tail = Arc::new(Mutex::new(VecDeque::<String>::new()));
    let readers: Vec<_> = [
        Box::new(child.stdout.take().unwrap()) as Box<dyn Read + Send>,
        Box::new(child.stderr.take().unwrap()),
    ]
    .into_iter()
    .map(|stream| {
        let (app, tail) = (app.clone(), tail.clone());
        thread::spawn(move || {
            for line in BufReader::new(stream).lines().map_while(Result::ok) {
                let line = line.trim().to_string();
                if line.is_empty() {
                    continue;
                }
                println!("  | {line}");
                let _ = app.emit("detail", &line);
                let mut tail = tail.lock().unwrap();
                tail.push_back(line);
                if tail.len() > 40 {
                    tail.pop_front();
                }
            }
        })
    })
    .collect();
    let status = child.wait().map_err(|e| e.to_string())?;
    for reader in readers {
        let _ = reader.join();
    }
    println!("step {:?} took {:.1}s", args.first(), started.elapsed().as_secs_f64());
    if status.success() {
        return Ok(());
    }
    let tail: Vec<String> = tail.lock().unwrap().iter().cloned().collect();
    Err(format!(
        "{} {} failed ({status}).\n\n{}",
        program.file_name().unwrap_or_default().to_string_lossy(),
        args.first().unwrap_or(&""),
        tail.join("\n")
    ))
}

/// Keep uv and the app on their own files: no user uv config, no system
/// Python, and the bundled ffmpeg first on PATH.
fn isolated_environment(paths: &Paths) -> Vec<(String, String)> {
    let bin = paths.resources.join("bin");
    let mut search = vec![bin];
    if let Some(existing) = std::env::var_os("PATH") {
        search.extend(std::env::split_paths(&existing));
    }
    vec![
        ("UV_NO_CONFIG".into(), "1".into()),
        ("UV_CACHE_DIR".into(), paths.runtime.join("cache").to_string_lossy().into()),
        ("UV_PYTHON_INSTALL_DIR".into(), paths.runtime.join("python").to_string_lossy().into()),
        ("PYTHONUNBUFFERED".into(), "1".into()),
        (
            "PATH".into(),
            std::env::join_paths(search).unwrap_or_default().to_string_lossy().into(),
        ),
    ]
}

#[cfg(windows)]
fn hide_console(command: &mut Command) {
    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    command.creation_flags(CREATE_NO_WINDOW);
}

#[cfg(not(windows))]
fn hide_console(_: &mut Command) {}

fn serve(app: &AppHandle, paths: &Paths) -> Result<(), String> {
    progress(app, "Starting Vocalika…", 1.0);
    let started = Instant::now();
    // Ask the OS for a free port rather than assuming 8000: a server left over
    // from a crash, or anything else the user runs, may hold a fixed one.
    let port = TcpListener::bind("127.0.0.1:0")
        .and_then(|listener| listener.local_addr())
        .map_err(|e| e.to_string())?
        .port();
    fs::create_dir_all(&paths.library).map_err(|e| e.to_string())?;
    let log = fs::File::create(&paths.log).map_err(|e| e.to_string())?;
    let mut command = Command::new(paths.python());
    command
        .args(["-I", "-m", "vocalika", "serve", "--port", &port.to_string()])
        .arg("--analyses-directory")
        .arg(&paths.library)
        .current_dir(&paths.library)
        .envs(isolated_environment(paths))
        .stdin(Stdio::null())
        .stdout(log.try_clone().map_err(|e| e.to_string())?)
        .stderr(log);
    hide_console(&mut command);
    let child = command.spawn().map_err(|e| format!("Could not start the server: {e}"))?;
    let launcher: State<Launcher> = app.state();
    *launcher.server.lock().unwrap() = Some(child);

    let address = format!("127.0.0.1:{port}");
    loop {
        if TcpStream::connect(&address).is_ok() {
            break;
        }
        if let Some(status) = launcher
            .server
            .lock()
            .unwrap()
            .as_mut()
            .and_then(|child| child.try_wait().ok().flatten())
        {
            let log = fs::read_to_string(&paths.log).unwrap_or_default();
            let tail: Vec<&str> = log.lines().rev().take(30).collect();
            let tail: Vec<&str> = tail.into_iter().rev().collect();
            return Err(format!("The server stopped ({status}).\n\n{}", tail.join("\n")));
        }
        if started.elapsed() > SERVER_START_TIMEOUT {
            return Err(format!("The server did not start; see {}", paths.log.display()));
        }
        thread::sleep(Duration::from_millis(100));
    }
    println!("server ready on {address} in {:.1}s", started.elapsed().as_secs_f64());

    let url: tauri::Url = format!("http://{address}/").parse().map_err(|e| format!("{e}"))?;
    let window = app.get_webview_window("main").ok_or("The main window is gone.")?;
    window.navigate(url).map_err(|e| e.to_string())?;
    Ok(())
}

fn stop_server(app: &AppHandle) {
    if let Some(mut child) = app.state::<Launcher>().server.lock().unwrap().take() {
        let _ = child.kill();
        let _ = child.wait();
    }
}

fn main() {
    tauri::Builder::default()
        .manage(Launcher::default())
        .invoke_handler(tauri::generate_handler![start, repair])
        .build(tauri::generate_context!())
        .expect("error while building the Vocalika launcher")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                stop_server(app);
            }
        });
}
