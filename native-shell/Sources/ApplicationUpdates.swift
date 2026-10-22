import Cocoa
import Sparkle

// Shared by source-connected and packaged Stella. Sparkle remains the only
// appcast parser, version selector, signature verifier and package installer.
final class ApplicationUpdates: NSObject, SPUUpdaterDelegate {
    static let shared = ApplicationUpdates()
    private var controller: SPUStandardUpdaterController!
    private var manualProbe = false
    private var foundItem: SUAppcastItem?
    private let sourceWorkspace = UpdateInstallationPolicy.isSourceWorkspace(Bundle.main.infoDictionary ?? [:])

    func start() {
        guard controller == nil else { return }
        controller = SPUStandardUpdaterController(startingUpdater: true, updaterDelegate: self, userDriverDelegate: nil)
    }

    func addMenuItem(to menu: NSMenu) {
        let item = NSMenuItem(title: "检查更新…", action: #selector(checkUpdates), keyEquivalent: "")
        item.target = self
        menu.addItem(item)
    }

    @objc func checkUpdates() {
        start()
        guard controller.updater.canCheckForUpdates else { return }
        if sourceWorkspace {
            manualProbe = true
            foundItem = nil
            controller.updater.checkForUpdateInformation()
        } else {
            controller.checkForUpdates(nil)
        }
    }

    func updater(_ updater: SPUUpdater, didFindValidUpdate item: SUAppcastItem) {
        if sourceWorkspace { foundItem = item }
    }

    func updater(_ updater: SPUUpdater, shouldProceedWithUpdate item: SUAppcastItem,
                 updateCheck: SPUUpdateCheck) throws {
        // A public binary cannot replace a source-connected shell: it changes
        // bundle identity, backend launch and runtime directory. Block before
        // download, including scheduled checks and stale updater preferences.
        guard sourceWorkspace else { return }
        foundItem = item
        if updateCheck != .updateInformation {
            throw NSError(domain: SUSparkleErrorDomain, code: Int(SUError.installationCanceledError.rawValue),
                          userInfo: [NSLocalizedDescriptionKey: "本地工作区保留源码连接与现有数据。"])
        }
    }

    func updater(_ updater: SPUUpdater, didFinishUpdateCycleFor updateCheck: SPUUpdateCheck, error: Error?) {
        guard sourceWorkspace else { return }
        let manual = manualProbe
        manualProbe = false
        let item = foundItem
        foundItem = nil
        let failure = error as NSError?
        if let item = item {
            let key = "StellaSourceLastNotifiedUpdate"
            guard manual || UserDefaults.standard.string(forKey: key) != item.versionString else { return }
            UserDefaults.standard.set(item.versionString, forKey: key)
            DispatchQueue.main.async { self.showSourceUpdate(item) }
        } else if manual {
            let noUpdate = failure?.domain == SUSparkleErrorDomain && failure?.code == Int(SUError.noUpdateError.rawValue)
            DispatchQueue.main.async {
                let alert = NSAlert()
                alert.messageText = noUpdate || failure == nil ? "暂无可用的兼容更新" : "暂时无法检查更新"
                alert.informativeText = noUpdate || failure == nil
                    ? "官网暂未提供可用的更新安装包。本地功能以当前工作区源码为准。"
                    : "请检查网络后重试。\n\(failure!.localizedDescription)"
                alert.addButton(withTitle: "知道了")
                alert.runModal()
            }
        }
    }

    private func showSourceUpdate(_ item: SUAppcastItem) {
        let alert = NSAlert()
        alert.messageText = "官网可用版本：Stella \(item.displayVersionString)"
        alert.informativeText = "当前应用连接本地源码工作区，功能以本地源码为准；官网版本号不代表本地迭代进度。\n\n直接替换为官网安装包会改变源码连接和数据位置，因此本次只检查更新，保留你当前的工作区与用户数据。"
        alert.addButton(withTitle: "知道了")
        alert.addButton(withTitle: "查看官网")
        if alert.runModal() == .alertSecondButtonReturn {
            NSWorkspace.shared.open(URL(string: "https://liu-zongjin.github.io/stella-downloads/")!)
        }
    }
}
