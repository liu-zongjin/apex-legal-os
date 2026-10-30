import Cocoa
import Foundation

// Source clients check the source revision; they never install a public binary.
final class ApplicationUpdates: NSObject {
    static let shared = ApplicationUpdates()
    func start() { }
    func addMenuItem(to menu: NSMenu) {
        let item = NSMenuItem(title: "检查更新…", action: #selector(checkUpdates), keyEquivalent: "")
        item.target = self
        menu.addItem(item)
    }
    @objc func checkUpdates() {
        guard let path = Bundle.main.object(forInfoDictionaryKey: "StellaSourceRoot") as? String else { return }
        DispatchQueue.global(qos: .userInitiated).async {
            func git(_ args: [String]) -> String? {
                let child = Process()
                let output = Pipe()
                child.executableURL = URL(fileURLWithPath: "/usr/bin/git")
                child.arguments = ["-C", path] + args
                child.standardOutput = output
                child.standardError = FileHandle.nullDevice
                do { try child.run() } catch { return nil }
                let data = output.fileHandleForReading.readDataToEndOfFile()
                child.waitUntilExit()
                guard child.terminationStatus == 0 else { return nil }
                return String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines)
            }
            let current = git(["rev-parse", "HEAD"])
            let localChanges = git(["status", "--porcelain", "--untracked-files=normal"])
            let remote = git(["ls-remote", "--refs", "https://github.com/liu-zongjin/apex-legal-os.git", "refs/heads/main"])?.split(separator: "\t").first.map(String.init)
            DispatchQueue.main.async {
                let alert = NSAlert()
                if current == nil || remote == nil || localChanges == nil {
                    alert.messageText = "暂时无法检查源码更新"
                    alert.informativeText = "请检查网络和 Git，然后重试。"
                } else if current == remote && localChanges!.isEmpty {
                    alert.messageText = "源码已是 GitHub 主分支最新版本"
                } else {
                    alert.messageText = current == remote ? "本地源码包含修改" : "GitHub 主分支有更新"
                    alert.informativeText = "可将检查和更新指令复制给 AI Agent。操作前请退出 Stella；Agent 会保留现有源码和资料并按仓库说明验证。"
                    alert.addButton(withTitle: "复制更新指令")
                    alert.addButton(withTitle: "稍后")
                    if alert.runModal() == .alertFirstButtonReturn {
                        let prompt = "请根据 https://github.com/liu-zongjin/apex-legal-os 中 docs/MACOS_SOURCE_DEPLOYMENT.md 的源码更新步骤，将此 Mac 上的 Stella 源码版更新到 GitHub main。请先检查现有安装和未保存的修改，保留所有旧源码、案件、附件和设置；不要覆盖、重置或删除用户资料。更新后验证客户端能正常打开、读取原有资料并退出，失败时保留旧入口并说明原因。"
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString(prompt, forType: .string)
                    }
                    return
                }
                alert.addButton(withTitle: "知道了")
                alert.runModal()
            }
        }
    }
}
