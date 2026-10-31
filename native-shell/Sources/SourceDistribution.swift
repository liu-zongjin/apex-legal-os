import Cocoa
import Foundation

// Source installs own their backend and never use the developer's existing profile.
final class SourceDistribution: NSObject {
    static let shared = SourceDistribution()
    private var server: Process?
    private var log: FileHandle?
    private var stopping = false
    private let runtime: URL = {
        if let path = ProcessInfo.processInfo.environment["STELLA_SOURCE_RUNTIME"], !path.isEmpty {
            return URL(fileURLWithPath: path, isDirectory: true)
        }
        return FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/StellaSource", isDirectory: true)
    }()

    func start(completion: @escaping (Bool) -> Void) {
        DispatchQueue.global(qos: .userInitiated).async {
            do {
                guard let rootPath = Bundle.main.object(forInfoDictionaryKey: "StellaSourceRoot") as? String else {
                    throw NSError(domain: "StellaSource", code: 1)
                }
                let root = URL(fileURLWithPath: rootPath, isDirectory: true)
                try FileManager.default.createDirectory(at: self.runtime, withIntermediateDirectories: true)
                let logPath = self.runtime.appendingPathComponent("server.log")
                if !FileManager.default.fileExists(atPath: logPath.path) {
                    FileManager.default.createFile(atPath: logPath.path, contents: nil)
                }
                self.log = try FileHandle(forWritingTo: logPath)
                self.log?.seekToEndOfFile()
                let token = UUID().uuidString.lowercased()
                let marker = self.runtime.appendingPathComponent("server-ready-\(token)")
                let child = Process()
                // Launch through env so Python sees the venv path as argv[0];
                // Foundation may otherwise resolve the executable symlink.
                child.executableURL = URL(fileURLWithPath: "/usr/bin/env")
                child.arguments = [root.appendingPathComponent(".venv/bin/python").path,
                                   root.appendingPathComponent("scripts/macos/source_server.py").path,
                                   "--runtime", self.runtime.path, "--ready-token", token]
                var environment = ProcessInfo.processInfo.environment
                for name in ["__PYVENV_LAUNCHER__", "PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV"] {
                    environment.removeValue(forKey: name)
                }
                if let helpers = Bundle.main.executableURL?.deletingLastPathComponent().path {
                    environment["STELLA_MACOS_HELPERS_DIR"] = helpers
                }
                child.environment = environment
                child.currentDirectoryURL = root
                child.standardOutput = self.log
                child.standardError = self.log
                var failure: Error?
                DispatchQueue.main.sync {
                    guard !self.stopping else { return }
                    do { self.server = child; try child.run() } catch { failure = error }
                }
                if let error = failure { throw error }
                for _ in 0..<1200 {
                    if !child.isRunning { break }
                    if FileManager.default.fileExists(atPath: marker.path) {
                        try? FileManager.default.removeItem(at: marker)
                        DispatchQueue.main.async { completion(true) }
                        return
                    }
                    Thread.sleep(forTimeInterval: 0.1)
                }
                if child.isRunning { child.terminate() }
            } catch { }
            DispatchQueue.main.async { completion(false) }
        }
    }

    func terminate(_ app: NSApplication) -> NSApplication.TerminateReply {
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
                alert.informativeText = "本次退出已暂停，请稍后重试；本地数据不会被强制中断。"
                alert.runModal()
            }
        }
        return .terminateLater
    }
}
