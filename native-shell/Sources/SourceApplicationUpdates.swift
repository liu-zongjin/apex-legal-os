import Cocoa
import Foundation

// Source clients check the source revision and update through the deployment guide.
final class ApplicationUpdates: NSObject {
    static let shared = ApplicationUpdates()
    private let updatePrompt = "请根据 https://github.com/liu-zongjin/apex-legal-os 中 docs/MACOS_SOURCE_DEPLOYMENT.md 的源码更新步骤，将此 Mac 上的 Stella 源码版更新到 GitHub main。请先检查 Git、现有源码目录和 GitHub 连通性，保留旧源码、案件、附件、数据库和设置。验证新版能正常打开、读取原有资料并退出，失败时保留旧入口并说明具体原因。"
    private var checking = false

    func start() { }

    func addMenuItem(to menu: NSMenu) {
        let item = NSMenuItem(title: "检查更新…", action: #selector(checkUpdates), keyEquivalent: "")
        item.target = self
        menu.addItem(item)
    }

    @objc func checkUpdates() {
        guard !checking else { return }
        checking = true
        let root = Bundle.main.object(forInfoDictionaryKey: "StellaSourceRoot") as? String
        DispatchQueue.global(qos: .userInitiated).async {
            let result = Self.checkSource(root: root)
            DispatchQueue.main.async {
                defer { self.checking = false }
                let alert = NSAlert()
                alert.messageText = result.title
                alert.informativeText = result.detail
                if result.offerInstructions {
                    alert.addButton(withTitle: "复制更新指令")
                    alert.addButton(withTitle: "关闭")
                    if alert.runModal() == .alertFirstButtonReturn {
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString(self.updatePrompt, forType: .string)
                    }
                } else {
                    alert.addButton(withTitle: "知道了")
                    alert.runModal()
                }
            }
        }
    }

    private static func checkSource(root: String?) -> (title: String, detail: String, offerInstructions: Bool) {
        let failed = "暂时无法检查源码更新"
        var directory: ObjCBool = false
        guard let root = root, !root.isEmpty,
              FileManager.default.fileExists(atPath: root, isDirectory: &directory), directory.boolValue else {
            return (failed, "找不到 Stella 连接的源码目录。请检查源码目录是否已移动或删除。", true)
        }
        guard git(["--version"], timeout: 10) != nil else {
            return (failed, "Stella 无法运行系统 Git。请检查 Apple 命令行开发工具是否已安装并可用。", true)
        }
        guard FileManager.default.fileExists(atPath: URL(fileURLWithPath: root).appendingPathComponent(".git").path) else {
            return (failed, "源码目录缺少 Git 仓库信息（.git）。请让 AI 检查原安装并按源码更新步骤恢复。", true)
        }
        guard let current = revision(in: git(["-C", root, "rev-parse", "HEAD"], timeout: 10)),
              let changes = git(["-C", root, "status", "--porcelain", "--untracked-files=normal"], timeout: 15) else {
            return (failed, "无法读取本地源码版本。请检查源码目录权限和 Git 仓库是否完整。", true)
        }
        let remoteOutput = git(["-c", "http.lowSpeedLimit=1", "-c", "http.lowSpeedTime=15", "ls-remote", "--refs",
                                "https://github.com/liu-zongjin/apex-legal-os.git", "refs/heads/main"], timeout: 30)
        guard let remote = revision(in: remoteOutput?.components(separatedBy: "\t").first) else {
            return (failed, "无法从 GitHub 读取主分支版本。请检查 GitHub 网络连接或代理设置。", true)
        }
        if current == remote && changes.isEmpty {
            return ("源码已是 GitHub 主分支最新版本", "", false)
        }
        return (current == remote ? "本地源码包含修改" : "GitHub 主分支有更新",
                "可将更新指令复制给 AI。开始更新前请保存工作并退出 Stella。", true)
    }

    private static func revision(in value: String?) -> String? {
        guard let value = value, value.range(of: "^[0-9a-f]{40}$", options: .regularExpression) != nil else { return nil }
        return value
    }

    private static func git(_ arguments: [String], timeout: TimeInterval) -> String? {
        let child = Process()
        let output = Pipe()
        child.executableURL = URL(fileURLWithPath: "/usr/bin/git")
        child.arguments = arguments
        child.standardOutput = output
        child.standardError = FileHandle.nullDevice
        child.standardInput = FileHandle.nullDevice
        var environment = ProcessInfo.processInfo.environment
        environment["GIT_TERMINAL_PROMPT"] = "0"
        child.environment = environment
        do { try child.run() } catch { return nil }

        let deadline = DispatchWorkItem { if child.isRunning { child.terminate() } }
        DispatchQueue.global().asyncAfter(deadline: .now() + timeout, execute: deadline)
        defer { deadline.cancel() }
        let data = output.fileHandleForReading.readDataToEndOfFile()
        child.waitUntilExit()
        guard child.terminationStatus == 0 else { return nil }
        return String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
