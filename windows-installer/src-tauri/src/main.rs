#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{io::{BufRead, BufReader, Write}, process::{Child, Command, Stdio}, sync::{Mutex, atomic::{AtomicBool, Ordering}}};
use tauri::{Emitter, Manager};
use tauri_plugin_notification::NotificationExt;

#[derive(Default)]
struct Runtime { child: Mutex<Option<Child>>, exiting: AtomicBool }

fn installer_only(window: &tauri::WebviewWindow) -> Result<(), String> {
    let url = window.url().map_err(|_| "无法确认当前页面")?;
    if url.scheme() == "tauri" || (url.scheme() == "http" && url.host_str() == Some("tauri.localhost")) { Ok(()) }
    else { Err("只能从安装界面执行此操作".into()) }
}

fn worker(app: &tauri::AppHandle, action: &str) -> Result<Command, String> {
    let binary = app.path().resource_dir().map_err(|_| "无法定位安装组件")?.join("resources/bootstrap-engine.exe");
    let mut command = Command::new(binary);
    command.arg(action).stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::null());
    #[cfg(windows)] {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    // A signed offline catalog may accompany the downloaded setup application.
    // Its signature uses the same compiled trust root as the online feed.
    if action != "probe" && action != "launch" {
        let catalog = std::env::current_exe().ok().and_then(|p| p.parent().map(|d| d.join("catalog.json")));
        if let Some(path) = catalog.filter(|p| p.is_file()) { command.arg("--catalog").arg(path); }
    }
    Ok(command)
}

fn run_worker(app: &tauri::AppHandle, action: &str) -> Result<serde_json::Value, String> {
    let mut child = worker(app, action)?.spawn().map_err(|_| "无法启动安装组件")?;
    let stdout = child.stdout.take().ok_or("无法读取安装进度")?;
    let mut result = serde_json::Value::Null;
    for line in BufReader::new(stdout).lines() {
        let line = line.map_err(|_| "安装组件响应中断")?;
        if line.len() > 65536 { continue; }
        if let Ok(event) = serde_json::from_str::<serde_json::Value>(&line) {
            let _ = app.emit_to("main", "stella:installer", &event);
            result = event;
        }
    }
    let success = child.wait().map_err(|_| "无法确认安装结果")?.success();
    if !success || result["event"] == "error" {
        Err(result["message"].as_str().unwrap_or("安装未完成，请重试").to_owned())
    } else { Ok(result) }
}

#[tauri::command]
async fn inspect_installation(window: tauri::WebviewWindow, app: tauri::AppHandle) -> Result<serde_json::Value, String> {
    installer_only(&window)?;
    tauri::async_runtime::spawn_blocking(move || run_worker(&app, "probe")).await.map_err(|_| "检测未完成")?
}

#[tauri::command]
async fn installation_plan(window: tauri::WebviewWindow, app: tauri::AppHandle) -> Result<serde_json::Value, String> {
    installer_only(&window)?;
    tauri::async_runtime::spawn_blocking(move || run_worker(&app, "plan")).await.map_err(|_| "检查未完成")?
}

#[tauri::command]
async fn install_components(window: tauri::WebviewWindow, app: tauri::AppHandle) -> Result<serde_json::Value, String> {
    installer_only(&window)?;
    if app.state::<Runtime>().child.lock().map_err(|_| "状态不可用")?.is_some() { return Err("请先退出运行中的 Stella".into()); }
    tauri::async_runtime::spawn_blocking(move || run_worker(&app, "install")).await.map_err(|_| "安装未完成")?
}

#[tauri::command]
async fn start_stella(window: tauri::WebviewWindow, app: tauri::AppHandle) -> Result<(), String> {
    installer_only(&window)?;
    let handle = app.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let state = handle.state::<Runtime>();
        let mut slot = state.child.lock().map_err(|_| "状态不可用")?;
        if slot.is_some() { return Err("Stella 已在运行".into()); }
        let mut command = worker(&handle, "launch")?;
        command.stdin(Stdio::piped());
        let mut child = command.spawn().map_err(|_| "无法启动本地服务")?;
        let stdout = child.stdout.take().ok_or("无法确认启动结果")?;
        *slot = Some(child);
        drop(slot);
        let mut reader = BufReader::new(stdout);
        let mut line = String::new();
        loop {
            line.clear();
            if reader.read_line(&mut line).map_err(|_| "本地服务响应中断")? == 0 { return Err("本地服务未启动，请修复安装".into()); }
            let event: serde_json::Value = serde_json::from_str(&line).map_err(|_| "启动响应无效")?;
            if event["event"] == "error" { return Err(event["message"].as_str().unwrap_or("启动失败").to_owned()); }
            if event["event"] == "ready" {
                if event["url"] != "http://127.0.0.1:18865/" { return Err("本地服务地址无效".into()); }
                handle.get_webview_window("main").ok_or("窗口已关闭")?.navigate("http://127.0.0.1:18865/".parse().unwrap()).map_err(|_| "无法打开工作空间")?;
                let event_handle = handle.clone();
                std::thread::spawn(move || {
                    for line in reader.lines().map_while(Result::ok) {
                        if let Ok(event) = serde_json::from_str::<serde_json::Value>(&line) { let _ = event_handle.emit_to("main", "stella:installer", event); }
                    }
                });
                return Ok(());
            }
        }
    }).await.map_err(|_| "启动未完成")?
}

#[tauri::command]
async fn check_stella_update(window: tauri::WebviewWindow, app: tauri::AppHandle) -> Result<serde_json::Value, String> {
    let url = window.url().map_err(|_| "无法确认页面")?;
    if !(url.scheme() == "http" && url.host_str() == Some("127.0.0.1") && url.port() == Some(18865)) { installer_only(&window)?; }
    tauri::async_runtime::spawn_blocking(move || run_worker(&app, "check")).await.map_err(|_| "更新检查未完成")?
}

#[tauri::command]
fn notify_stella(window: tauri::WebviewWindow, app: tauri::AppHandle, title: String, body: String) -> Result<(), String> {
    let url = window.url().map_err(|_| "无法确认页面")?;
    if url.scheme() != "http" || url.host_str() != Some("127.0.0.1") || url.port() != Some(18865) { return Err("页面无权限".into()); }
    if title.chars().count() > 80 || body.chars().count() > 300 { return Err("通知过长".into()); }
    app.notification().builder().title(title).body(body).show().map_err(|_| "系统暂未允许通知".into())
}

#[tauri::command]
async fn return_to_installer(window: tauri::WebviewWindow, app: tauri::AppHandle) -> Result<(), String> {
    let url = window.url().map_err(|_| "无法确认页面")?;
    if url.host_str() != Some("127.0.0.1") || url.port() != Some(18865) { return Err("请从工作空间打开更新".into()); }
    let handle = app.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let mut child = handle.state::<Runtime>().child.lock().map_err(|_| "状态不可用")?.take();
        if let Some(ref mut process) = child {
            if let Some(mut input) = process.stdin.take() { let _ = input.write_all(b"stop\n"); }
            process.wait().map_err(|_| "请等待后台保存结束")?;
        }
        Ok::<(), String>(())
    }).await.map_err(|_| "关闭后台失败")??;
    window.navigate("http://tauri.localhost/index.html".parse().unwrap()).map_err(|_| "无法打开更新界面".into())
}

fn main() {
    tauri::Builder::default()
        .manage(Runtime::default())
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            if let Some(window) = app.get_webview_window("main") { let _ = window.show(); let _ = window.set_focus(); }
        }))
        .plugin(tauri_plugin_notification::init())
        .setup(|app| {
            tauri::WebviewWindowBuilder::new(app, "main", tauri::WebviewUrl::App("index.html".into()))
                .title("Stella").inner_size(1100.0, 760.0).min_inner_size(700.0, 560.0)
                .on_navigation(|url| {
                    url.scheme() == "tauri" || (url.scheme() == "http" &&
                        (url.host_str() == Some("tauri.localhost") ||
                         (url.host_str() == Some("127.0.0.1") && url.port() == Some(18865))))
                })
                .build()?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![inspect_installation, installation_plan, install_components, start_stella, check_stella_update, notify_stella, return_to_installer])
        .on_page_load(|window, _| {
            // Only the top-level local application receives a narrow native adapter.
            if let Ok(url) = window.url() {
                if url.host_str() == Some("127.0.0.1") && url.port() == Some(18865) {
                    let _ = window.eval("window.StellaWindows={invoke:window.__TAURI__.core.invoke};window.dispatchEvent(new Event('stella:windows-ready'));");
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("无法初始化 Stella")
        .run(|app, event| {
            if let tauri::RunEvent::ExitRequested { api, .. } = event {
                let state = app.state::<Runtime>();
                if state.exiting.load(Ordering::SeqCst) { return; }
                let mut slot = state.child.lock().unwrap();
                if let Some(mut child) = slot.take() {
                    api.prevent_exit();
                    state.exiting.store(true, Ordering::SeqCst);
                    if let Some(mut input) = child.stdin.take() { let _ = input.write_all(b"stop\n"); }
                    let handle = app.clone();
                    std::thread::spawn(move || { let _ = child.wait(); handle.exit(0); });
                }
            }
        });
}
