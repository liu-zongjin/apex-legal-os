// Public distribution only. Runtime data always stays outside the replaced app.
import Cocoa
import Foundation
import Sparkle

final class PublicDistribution: NSObject {
    static let shared = PublicDistribution()
    private var server: Process?
    private var serverLog: FileHandle?
    private var stopping = false
    private var updater: SPUStandardUpdaterController!
    private var heartbeat: Timer?
    private let defaults = UserDefaults.standard
    private let runtime = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/StellaPublic", isDirectory: true)
    private var ready = false

    func start(completion: @escaping (Bool) -> Void) {
        updater = SPUStandardUpdaterController(startingUpdater: true, updaterDelegate: nil, userDriverDelegate: nil)
        DispatchQueue.global(qos: .userInitiated).async {
            do {
                try FileManager.default.createDirectory(at: self.runtime, withIntermediateDirectories: true)
                let log = self.runtime.appendingPathComponent("server.log")
                if !FileManager.default.fileExists(atPath: log.path) {
                    FileManager.default.createFile(atPath: log.path, contents: nil)
                }
                self.serverLog = try FileHandle(forWritingTo: log)
                self.serverLog?.seekToEndOfFile()
                let child = Process()
                child.executableURL = Bundle.main.resourceURL!.appendingPathComponent("Server/stella-preview-server")
                child.arguments = ["--runtime", self.runtime.path, "--app-build", self.build]
                child.environment = ["HOME": NSHomeDirectory(), "PATH": Bundle.main.resourceURL!.appendingPathComponent("Server/_internal/playwright/driver").path + ":/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
                                     "TMPDIR": NSTemporaryDirectory(), "LANG": "zh_CN.UTF-8"]
                child.standardOutput = self.serverLog
                child.standardError = self.serverLog
                var launchError: Error?
                DispatchQueue.main.sync {
                    guard !self.stopping else { return }
                    do { self.server = child; try child.run() }
                    catch { launchError = error }
                }
                if let error = launchError { throw error }
                // A foreign listener is rejected by the backend's exclusive runtime lock and port bind.
                // Wait for this launch's readiness marker, not an unrelated process's HTTP response.
                let marker = self.runtime.appendingPathComponent("server-ready-\(child.processIdentifier)")
                for _ in 0..<1200 {
                    if !child.isRunning { break }
                    if FileManager.default.fileExists(atPath: marker.path) {
                        try? FileManager.default.removeItem(at: marker)
                        DispatchQueue.main.async {
                            self.ready = true
                            self.configureStatistics()
                            completion(true)
                        }
                        return
                    }
                    Thread.sleep(forTimeInterval: 0.1)
                }
                if child.isRunning { child.terminate() }
            } catch { }
            DispatchQueue.main.async { completion(false) }
        }
    }

    private var build: String { Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "0" }

    func addMenuItems(to menu: NSMenu) {
        let update = NSMenuItem(title: "检查更新…", action: #selector(checkUpdates), keyEquivalent: "")
        update.target = self
        menu.addItem(update)
        let statistics = NSMenuItem(title: "匿名使用统计…", action: #selector(statisticsSettings), keyEquivalent: "")
        statistics.target = self
        menu.addItem(statistics)
    }
    @objc private func checkUpdates() { updater.checkForUpdates(nil) }

    // Sparkle uses NSApplication termination too. Defer termination until SQLite and
    // background jobs have received the backend's normal SIGTERM shutdown.
    func terminate(_ app: NSApplication) -> NSApplication.TerminateReply {
        heartbeat?.invalidate()
        if stopping { return server?.isRunning == true ? .terminateLater : .terminateNow }
        stopping = true
        guard let child = server, child.isRunning else { return .terminateNow }
        child.terminate()
        DispatchQueue.global().async {
            for _ in 0..<300 {
                if !child.isRunning {
                    DispatchQueue.main.async { app.reply(toApplicationShouldTerminate: true) }
                    return
                }
                Thread.sleep(forTimeInterval: 0.1)
            }
            DispatchQueue.main.async {
                self.stopping = false
                app.reply(toApplicationShouldTerminate: false)
                let alert = NSAlert()
                alert.messageText = "Stella 仍在保存或结束后台任务"
                alert.informativeText = "本次退出或更新已暂停。请稍后再次退出或检查更新，本地数据不会被强制中断。"
                alert.runModal()
                self.startHeartbeat()
            }
        }
        return .terminateLater
    }

    private var endpoint: URL? {
        guard let text = Bundle.main.object(forInfoDictionaryKey: "StellaMetricsURL") as? String,
              let url = URL(string: text), url.scheme == "https", url.path == "/v1/events" else { return nil }
        return url
    }
    private func configureStatistics() {
        guard endpoint != nil else { return }
        if defaults.object(forKey: "StellaMetricsConsent") == nil { statisticsSettings() }
        sendHeartbeat()
        startHeartbeat()
    }
    @objc private func statisticsSettings() {
        let alert = NSAlert()
        alert.messageText = "帮助改进 Stella"
        alert.informativeText = "是否允许匿名使用统计？仅发送随机安装标识、应用版本、macOS 版本和运行时间，用于统计首次启动和活跃设备。不发送案件、文件、账号或问答内容。可随时在此关闭；关闭后不再发送。重新安装且保留本地偏好时仍视为同一设备。"
        alert.addButton(withTitle: "允许匿名统计")
        alert.addButton(withTitle: "不允许")
        let allowed = alert.runModal() == .alertFirstButtonReturn
        defaults.set(allowed, forKey: "StellaMetricsConsent")
        if allowed { sendHeartbeat() }
    }
    private func startHeartbeat() {
        heartbeat?.invalidate()
        heartbeat = Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { [weak self] _ in self?.sendHeartbeat() }
    }
    private func sendHeartbeat() {
        guard ready, !stopping, defaults.bool(forKey: "StellaMetricsConsent"), let url = endpoint else { return }
        let identifier: String
        if let existing = defaults.string(forKey: "StellaMetricsInstallID") { identifier = existing }
        else { identifier = UUID().uuidString.lowercased(); defaults.set(identifier, forKey: "StellaMetricsInstallID") }
        let os = ProcessInfo.processInfo.operatingSystemVersion
        let payload: [String: String] = ["install_id": identifier, "version": build,
            "os": "\(os.majorVersion).\(os.minorVersion).\(os.patchVersion)"]
        var request = URLRequest(url: url, timeoutInterval: 10)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: payload)
        // No disk queue, cookies, account credentials, or user-generated content.
        let config = URLSessionConfiguration.ephemeral
        config.httpCookieStorage = nil
        let session = URLSession(configuration: config)
        session.dataTask(with: request) { _, _, _ in session.finishTasksAndInvalidate() }.resume()
    }
}
