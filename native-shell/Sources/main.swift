import Cocoa
import EventKit
import Foundation
import WebKit
import LocalAuthentication
import UserNotifications
import Darwin

// 每次进程启动生成唯一首页 URL，避免 WKWebView 按路径复用旧 HTML 文档。
private let legalKBFrontendVersion = "2026081312"
private let legalKBHomeURL: URL = {
    var components = URLComponents(string: "http://localhost:8000/")!
    components.queryItems = [
        URLQueryItem(name: "native-shell", value: "1"),
        URLQueryItem(name: "frontend", value: legalKBFrontendVersion),
        URLQueryItem(name: "launch", value: String(Int(Date().timeIntervalSince1970))),
    ]
    return components.url!
}()
private let legalKBStatusURL = URL(string: "http://127.0.0.1:8000/api/server-status")!

// 与后端 personal_center.py 共享的桥接密钥：只有通过系统 Touch ID 验证的原生壳
// 才能用一次性挑战向后端兑换个人中心会话，页面 JavaScript 无法伪造指纹结果。
private let biometricBridgeSecret = "apex-personal-center-biometric-2026-v1"
private let biometricChallengeURL = URL(string: "http://127.0.0.1:8000/api/personal-center/biometric/challenge")!
private let biometricCompleteURL = URL(string: "http://127.0.0.1:8000/api/personal-center/verify/biometric")!
private let loginBiometricBridgeSecret = "apex-login-biometric-2026-v1"
private let loginBiometricChallengeURL = URL(string: "http://127.0.0.1:8000/api/login/biometric/challenge")!
private let loginBiometricCompleteURL = URL(string: "http://127.0.0.1:8000/api/login/biometric/verify")!

final class DirectoryMonitor {
    private var descriptor: Int32 = -1
    private var source: DispatchSourceFileSystemObject?
    private let queue = DispatchQueue(label: "com.liuzongjin.legalkb.frontend-monitor")
    private var pendingWork: DispatchWorkItem?

    init?(path: String, onChange: @escaping () -> Void) {
        descriptor = open(path, O_EVTONLY)
        guard descriptor >= 0 else { return nil }

        let source = DispatchSource.makeFileSystemObjectSource(
            fileDescriptor: descriptor,
            eventMask: [.write, .extend, .attrib, .link, .rename, .delete],
            queue: queue
        )
        source.setEventHandler { [weak self] in
            self?.pendingWork?.cancel()
            let work = DispatchWorkItem {
                DispatchQueue.main.async(execute: onChange)
            }
            self?.pendingWork = work
            self?.queue.asyncAfter(deadline: .now() + 0.55, execute: work)
        }
        source.setCancelHandler { [descriptor] in
            close(descriptor)
        }
        self.source = source
        source.resume()
    }

    deinit {
        pendingWork?.cancel()
        source?.cancel()
    }
}

private let shortcutModifierMask: NSEvent.ModifierFlags = [.command, .control, .option, .shift]

enum NativeShortcutAction: String, CaseIterable {
    case toggleSidebar
    case closeCurrentPage
    case openFada
    case openCaseManager
    case openPrepaidExpense
    case openCaseResearch
    case openAIAsk
    case openInterestCalculator
    case goHome

    var title: String {
        switch self {
        case .toggleSidebar: return "展开／隐藏侧边栏"
        case .closeCurrentPage: return "关闭当前文章或标签页"
        case .openFada: return "打开法答网"
        case .openCaseManager: return "打开案件管理"
        case .openPrepaidExpense: return "快速唤起新增收支记录"
        case .openCaseResearch: return "打开案件研究"
        case .openAIAsk: return "打开 AI增强"
        case .openInterestCalculator: return "打开计算工具"
        case .goHome: return "返回全部知识"
        }
    }

    var defaultBinding: ShortcutBinding {
        switch self {
        case .toggleSidebar: return ShortcutBinding(key: "s", modifiers: [.command, .option])
        case .closeCurrentPage: return ShortcutBinding(key: "w", modifiers: [.command])
        case .openFada: return ShortcutBinding(key: "f", modifiers: [.command, .option])
        case .openCaseManager: return ShortcutBinding(key: "m", modifiers: [.command, .option])
        case .openPrepaidExpense: return ShortcutBinding(key: "e", modifiers: [.command, .option])
        case .openCaseResearch: return ShortcutBinding(key: "r", modifiers: [.command, .option])
        case .openAIAsk: return ShortcutBinding(key: "a", modifiers: [.command, .option])
        case .openInterestCalculator: return ShortcutBinding(key: "i", modifiers: [.command, .option])
        case .goHome: return ShortcutBinding(key: "h", modifiers: [.command, .option])
        }
    }
}

struct ShortcutBinding: Codable, Equatable {
    let key: String
    let modifierRawValue: UInt

    init(key: String, modifiers: NSEvent.ModifierFlags) {
        self.key = key.lowercased()
        self.modifierRawValue = modifiers.intersection(shortcutModifierMask).rawValue
    }

    var modifiers: NSEvent.ModifierFlags {
        NSEvent.ModifierFlags(rawValue: modifierRawValue)
    }

    var isEnabled: Bool {
        !key.isEmpty && modifierRawValue != 0
    }

    static func from(event: NSEvent) -> ShortcutBinding? {
        let modifiers = event.modifierFlags.intersection(shortcutModifierMask)
        guard modifiers.contains(.command) || modifiers.contains(.control) || modifiers.contains(.option) else {
            return nil
        }
        guard let key = event.charactersIgnoringModifiers?.lowercased(), !key.isEmpty else {
            return nil
        }
        return ShortcutBinding(key: key, modifiers: modifiers)
    }

    func matches(event: NSEvent) -> Bool {
        guard isEnabled else { return false }
        let eventModifiers = event.modifierFlags.intersection(shortcutModifierMask)
        let eventKey = event.charactersIgnoringModifiers?.lowercased() ?? ""
        return eventModifiers.rawValue == modifierRawValue && eventKey == key
    }

    var displayText: String {
        guard isEnabled else { return "未设置" }
        var text = ""
        if modifiers.contains(.control) { text += "⌃" }
        if modifiers.contains(.option) { text += "⌥" }
        if modifiers.contains(.shift) { text += "⇧" }
        if modifiers.contains(.command) { text += "⌘" }
        let specialKeys = [
            "\r": "↩",
            "\t": "⇥",
            " ": "Space",
            String(UnicodeScalar(NSUpArrowFunctionKey)!): "↑",
            String(UnicodeScalar(NSDownArrowFunctionKey)!): "↓",
            String(UnicodeScalar(NSLeftArrowFunctionKey)!): "←",
            String(UnicodeScalar(NSRightArrowFunctionKey)!): "→",
        ]
        text += specialKeys[key] ?? key.uppercased()
        return text
    }
}

final class ShortcutStore {
    private let defaultsKey = "LegalKBNativeShortcutBindings"
    private var overrides: [String: ShortcutBinding] = [:]

    init() {
        guard
            let data = UserDefaults.standard.data(forKey: defaultsKey),
            let decoded = try? JSONDecoder().decode([String: ShortcutBinding].self, from: data)
        else { return }
        overrides = decoded
    }

    func binding(for action: NativeShortcutAction) -> ShortcutBinding {
        overrides[action.rawValue] ?? action.defaultBinding
    }

    func action(matching event: NSEvent) -> NativeShortcutAction? {
        // Editing shortcuts belong to WKWebView and must never be swallowed by
        // the native shortcut monitor, including bindings saved by older builds.
        guard !Self.isSystemEditingShortcut(event) else { return nil }
        return NativeShortcutAction.allCases.first { binding(for: $0).matches(event: event) }
    }

    func conflictingAction(for binding: ShortcutBinding, excluding action: NativeShortcutAction) -> NativeShortcutAction? {
        guard binding.isEnabled else { return nil }
        return NativeShortcutAction.allCases.first {
            $0 != action && self.binding(for: $0) == binding
        }
    }

    func isReserved(_ binding: ShortcutBinding) -> Bool {
        let applicationReserved = [
            ShortcutBinding(key: "q", modifiers: [.command]),
            ShortcutBinding(key: "r", modifiers: [.command]),
            ShortcutBinding(key: ",", modifiers: [.command]),
            ShortcutBinding(key: "f", modifiers: [.command, .control]),
        ]
        return applicationReserved.contains(binding) || Self.isSystemEditingShortcut(binding)
    }

    func reservedReason(for binding: ShortcutBinding) -> String? {
        if Self.isSystemEditingShortcut(binding) {
            return "这是 macOS 的系统编辑快捷键，不能设置为 Stella 快捷键。"
        }
        if isReserved(binding) {
            return "该组合键由应用保留，请选择其他快捷键。"
        }
        return nil
    }

    private static func isSystemEditingShortcut(_ event: NSEvent) -> Bool {
        guard let binding = ShortcutBinding.from(event: event) else { return false }
        return isSystemEditingShortcut(binding)
    }

    private static func isSystemEditingShortcut(_ binding: ShortcutBinding) -> Bool {
        let command = NSEvent.ModifierFlags.command.rawValue
        let commandShift = NSEvent.ModifierFlags([.command, .shift]).rawValue
        let key = binding.key
        return (binding.modifierRawValue == command && ["a", "c", "v", "x", "z", "y"].contains(key)) ||
            (binding.modifierRawValue == commandShift && key == "z")
    }

    func set(_ binding: ShortcutBinding, for action: NativeShortcutAction) {
        overrides[action.rawValue] = binding
        save()
    }

    func clear(_ action: NativeShortcutAction) {
        overrides[action.rawValue] = ShortcutBinding(key: "", modifiers: [])
        save()
    }

    func resetAll() {
        overrides.removeAll()
        save()
    }

    private func save() {
        if let data = try? JSONEncoder().encode(overrides) {
            UserDefaults.standard.set(data, forKey: defaultsKey)
        }
    }
}

final class ShortcutRecorderButton: NSButton {
    var recordedBinding: ((ShortcutBinding?) -> Void)?
    private var currentBinding: ShortcutBinding
    private var isRecordingShortcut = false

    init(binding: ShortcutBinding) {
        currentBinding = binding
        super.init(frame: .zero)
        bezelStyle = .rounded
        target = self
        action = #selector(beginRecording)
        updateTitle()
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    override var acceptsFirstResponder: Bool { true }

    func setBinding(_ binding: ShortcutBinding) {
        currentBinding = binding
        isRecordingShortcut = false
        updateTitle()
    }

    @objc private func beginRecording() {
        isRecordingShortcut = true
        title = "请按新的快捷键…"
        window?.makeFirstResponder(self)
    }

    override func keyDown(with event: NSEvent) {
        guard isRecordingShortcut else {
            super.keyDown(with: event)
            return
        }
        if event.keyCode == 53 {
            isRecordingShortcut = false
            updateTitle()
            return
        }
        if event.keyCode == 51 || event.keyCode == 117 {
            isRecordingShortcut = false
            recordedBinding?(nil)
            return
        }
        guard let binding = ShortcutBinding.from(event: event) else {
            NSSound.beep()
            title = "需包含 ⌘、⌃ 或 ⌥"
            return
        }
        isRecordingShortcut = false
        recordedBinding?(binding)
    }

    private func updateTitle() {
        title = currentBinding.displayText
    }
}

final class ShortcutSettingsWindowController: NSWindowController {
    private let store: ShortcutStore
    private var recorders: [NativeShortcutAction: ShortcutRecorderButton] = [:]

    init(store: ShortcutStore) {
        self.store = store
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 590, height: 550),
            styleMask: [.titled, .closable],
            backing: .buffered,
            defer: false
        )
        window.title = "快捷键设置"
        window.isReleasedWhenClosed = false
        super.init(window: window)
        buildContent()
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    override func showWindow(_ sender: Any?) {
        super.showWindow(sender)
        window?.center()
        window?.makeKeyAndOrderFront(sender)
    }

    private func buildContent() {
        guard let window = window else { return }
        let root = NSStackView()
        root.orientation = .vertical
        root.alignment = .leading
        root.spacing = 11
        root.edgeInsets = NSEdgeInsets(top: 22, left: 24, bottom: 20, right: 24)
        root.translatesAutoresizingMaskIntoConstraints = false

        let title = NSTextField(labelWithString: "Stella 快捷键")
        title.font = NSFont.systemFont(ofSize: 20, weight: .semibold)
        root.addArrangedSubview(title)

        let note = NSTextField(wrappingLabelWithString: "点击右侧按钮后直接按新的组合键。系统编辑快捷键（如 ⌘C、⌘V、⌘A）不可占用；快捷键只在 Stella 位于最前台时生效；按 Delete 可清除，按 Esc 可取消录制。")
        note.textColor = .secondaryLabelColor
        note.font = NSFont.systemFont(ofSize: 12)
        note.maximumNumberOfLines = 2
        root.addArrangedSubview(note)

        let separator = NSBox()
        separator.boxType = .separator
        root.addArrangedSubview(separator)
        separator.widthAnchor.constraint(equalTo: root.widthAnchor, constant: -48).isActive = true

        for action in NativeShortcutAction.allCases {
            let row = NSStackView()
            row.orientation = .horizontal
            row.alignment = .centerY
            row.spacing = 12

            let label = NSTextField(labelWithString: action.title)
            label.font = NSFont.systemFont(ofSize: 13)
            label.widthAnchor.constraint(equalToConstant: 310).isActive = true

            let recorder = ShortcutRecorderButton(binding: store.binding(for: action))
            recorder.widthAnchor.constraint(equalToConstant: 180).isActive = true
            recorder.recordedBinding = { [weak self, weak recorder] binding in
                self?.accept(binding, for: action, recorder: recorder)
            }
            recorders[action] = recorder

            row.addArrangedSubview(label)
            row.addArrangedSubview(recorder)
            root.addArrangedSubview(row)
        }

        let spacer = NSView()
        spacer.heightAnchor.constraint(equalToConstant: 3).isActive = true
        root.addArrangedSubview(spacer)

        let footer = NSStackView()
        footer.orientation = .horizontal
        footer.spacing = 10
        let resetButton = NSButton(title: "恢复默认快捷键", target: self, action: #selector(resetAll))
        resetButton.bezelStyle = .rounded
        let doneButton = NSButton(title: "完成", target: self, action: #selector(closeSettings))
        doneButton.bezelStyle = .rounded
        doneButton.keyEquivalent = "\r"
        footer.addArrangedSubview(resetButton)
        footer.addArrangedSubview(doneButton)
        root.addArrangedSubview(footer)

        window.contentView = NSView()
        window.contentView?.addSubview(root)
        NSLayoutConstraint.activate([
            root.leadingAnchor.constraint(equalTo: window.contentView!.leadingAnchor),
            root.trailingAnchor.constraint(equalTo: window.contentView!.trailingAnchor),
            root.topAnchor.constraint(equalTo: window.contentView!.topAnchor),
            root.bottomAnchor.constraint(equalTo: window.contentView!.bottomAnchor),
        ])
    }

    private func accept(_ binding: ShortcutBinding?, for action: NativeShortcutAction, recorder: ShortcutRecorderButton?) {
        guard let binding = binding else {
            store.clear(action)
            recorder?.setBinding(store.binding(for: action))
            return
        }
        if let reason = store.reservedReason(for: binding) {
            showWarning(reason)
            recorder?.setBinding(store.binding(for: action))
            return
        }
        if let conflict = store.conflictingAction(for: binding, excluding: action) {
            showWarning("该组合键已用于“\(conflict.title)”。")
            recorder?.setBinding(store.binding(for: action))
            return
        }
        store.set(binding, for: action)
        recorder?.setBinding(binding)
    }

    private func showWarning(_ message: String) {
        let alert = NSAlert()
        alert.messageText = "无法设置快捷键"
        alert.informativeText = message
        if let window = window {
            alert.beginSheetModal(for: window)
        }
    }

    @objc private func resetAll() {
        store.resetAll()
        for action in NativeShortcutAction.allCases {
            recorders[action]?.setBinding(store.binding(for: action))
        }
    }

    @objc private func closeSettings() {
        close()
    }
}

@available(macOS 11.3, *)
final class LegalKBWindowController: NSObject, NSWindowDelegate, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate {
    let window: NSWindow
    let webView: WKWebView

    private var backendTimer: Timer?
    private var isWaitingForBackend = false
    private var frontendMonitors: [DirectoryMonitor] = []
    private var frontendReloadWork: DispatchWorkItem?
    private var frontendPath: String?
    private var frontendFingerprint: String?
    // Keep the store alive until the asynchronous macOS consent callback
    // finishes.  The same APEX bundle identity is used by the calendar helper.
    private let calendarStore = EKEventStore()
    // LAContext 的验证是异步的。按 requestId 持有到回调结束，避免系统认证面板
    // 尚未完成时上下文被提前释放，导致网页一直停在“等待指纹验证”。
    private var activeBiometricContexts: [String: LAContext] = [:]
    private var activeDownloads: [ObjectIdentifier: WKDownload] = [:]
    private var webContentRecoveryTimes: [Date] = []
    private var isDockIconOverridden = false

    var automaticFrontendRefresh: Bool {
        get {
            if UserDefaults.standard.object(forKey: "AutomaticFrontendRefresh") == nil {
                return true
            }
            return UserDefaults.standard.bool(forKey: "AutomaticFrontendRefresh")
        }
        set {
            UserDefaults.standard.set(newValue, forKey: "AutomaticFrontendRefresh")
            NotificationCenter.default.post(name: .automaticFrontendRefreshChanged, object: nil)
        }
    }

    override init() {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = true
        configuration.applicationNameForUserAgent = "LegalKB-NativeShell"

        // 允许网页直接播放录音（无需额外用户手势）
        configuration.mediaTypesRequiringUserActionForPlayback = .init()

        // 启用 WKWebView 的 getUserMedia（私有开关，macOS 12 之前由它控制；
        // 新系统上由 UIDelegate 授权回调决定，设置此开关无副作用）
        let preferences = configuration.preferences
        let mediaDevicesSelector = NSSelectorFromString("_setMediaDevicesEnabled:")
        if preferences.responds(to: mediaDevicesSelector) {
            typealias Setter = @convention(c) (AnyObject, Selector, Bool) -> Void
            let setter = unsafeBitCast(preferences.method(for: mediaDevicesSelector), to: Setter.self)
            setter(preferences, mediaDevicesSelector, true)
        }

        webView = WKWebView(frame: .zero, configuration: configuration)
        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1280, height: 820),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )

        super.init()

        configuration.userContentController.add(self, name: "biometric")
        configuration.userContentController.add(self, name: "clipboard")
        configuration.userContentController.add(self, name: "brandIcon")
        window.title = "Stella"
        window.minSize = NSSize(width: 960, height: 620)
        window.center()
        window.setFrameAutosaveName("LegalKBMainWindow")
        window.delegate = self
        window.contentView = webView
        window.backgroundColor = NSColor(calibratedWhite: 0.97, alpha: 1)
        window.collectionBehavior.insert(.fullScreenPrimary)

        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.allowsMagnification = true

        requestCalendarAccess()
        configureFrontendMonitor()
        loadApplication()
    }

    private func requestCalendarAccess() {
        let completion: @convention(block) (Bool, Error?) -> Void = { _, _ in }
        let fullAccessSelector = NSSelectorFromString("requestFullAccessToEventsWithCompletion:")
        if calendarStore.responds(to: fullAccessSelector), let implementation = calendarStore.method(for: fullAccessSelector) {
            typealias FullAccessRequest = @convention(c) (AnyObject, Selector, @escaping @convention(block) (Bool, Error?) -> Void) -> Void
            let request = unsafeBitCast(implementation, to: FullAccessRequest.self)
            request(calendarStore, fullAccessSelector, completion)
        } else {
            calendarStore.requestAccess(to: .event) { _, _ in }
        }
    }

    deinit {
        frontendReloadWork?.cancel()
        backendTimer?.invalidate()
    }

    func showWindow() {
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) { [weak self] in
            guard let self = self, !self.window.styleMask.contains(.fullScreen) else { return }
            self.window.toggleFullScreen(nil)
        }
    }

    func loadApplication() {
        backendTimer?.invalidate()
        backendTimer = nil
        isWaitingForBackend = false
        loadFreshApplicationDocument(url: legalKBHomeURL)
    }

    func reloadApplication() {
        guard webView.url?.host == "localhost" || webView.url?.host == "127.0.0.1" else {
            loadApplication()
            return
        }
        var components = URLComponents(url: webView.url ?? legalKBHomeURL, resolvingAgainstBaseURL: false)
        var items = components?.queryItems ?? []
        items.removeAll { $0.name == "reload" }
        items.append(URLQueryItem(name: "reload", value: String(Int(Date().timeIntervalSince1970 * 1000))))
        components?.queryItems = items
        loadFreshApplicationDocument(url: components?.url ?? legalKBHomeURL)
    }

    private func loadFreshApplicationDocument(url: URL) {
        // 清理会拦截首页请求的 Service Worker 及其 Fetch 缓存；
        // 不碰 localStorage、Cookie、IndexedDB，保留登录信息和用户设置。
        let cacheTypes: Set<String> = [
            WKWebsiteDataTypeMemoryCache,
            WKWebsiteDataTypeDiskCache,
            WKWebsiteDataTypeFetchCache,
            WKWebsiteDataTypeServiceWorkerRegistrations,
        ]
        let store = webView.configuration.websiteDataStore
        store.removeData(ofTypes: cacheTypes, modifiedSince: .distantPast) { [weak self] in
            guard let self = self else { return }
            var request = URLRequest(url: url)
            request.cachePolicy = .reloadIgnoringLocalAndRemoteCacheData
            request.setValue("no-cache, no-store, must-revalidate", forHTTPHeaderField: "Cache-Control")
            request.setValue("no-cache", forHTTPHeaderField: "Pragma")
            request.timeoutInterval = 15
            self.webView.load(request)
        }
    }

    func toggleFullScreen() {
        window.toggleFullScreen(nil)
    }

    func toggleAutomaticFrontendRefresh() {
        automaticFrontendRefresh.toggle()
    }

    func applicationDidBecomeActive() {
        guard automaticFrontendRefresh else { return }
        let fingerprint = currentFrontendFingerprint()
        if let fingerprint = fingerprint, let previous = frontendFingerprint, fingerprint != previous {
            frontendFingerprint = fingerprint
            reloadApplication()
        }
    }

    func applicationDidResignActive() {
        // macOS owns presentation state while the app occupies a full-screen Space.
    }

    func openCourtOnlineService(recordID: Int? = nil) {
        showWindow()
        let value = recordID ?? 0
        webView.evaluateJavaScript("window.openCourtOnlineService && window.openCourtOnlineService(\(value))")
    }

    func windowWillClose(_ notification: Notification) {
        // 后台法院同步启用时，关闭窗口只隐藏 APEX；菜单栏与系统通知仍可工作。
        window.orderOut(nil)
    }

    private func configureFrontendMonitor() {
        guard
            let path = Bundle.main.object(forInfoDictionaryKey: "LegalKBFrontendPath") as? String,
            FileManager.default.fileExists(atPath: path)
        else { return }

        frontendPath = path
        let watchedFiles = [
            "index.html",
            "style.css",
            "app.js",
            "search-shortcut.js",
            "case-manager.html",
            "case-manager-sw.js",
            "recording.html",
            "recording.js",
        ]
        frontendMonitors = watchedFiles.compactMap { filename in
            DirectoryMonitor(path: (path as NSString).appendingPathComponent(filename)) { [weak self] in
                self?.scheduleFrontendReload()
            }
        }
        frontendFingerprint = currentFrontendFingerprint()
    }

    private func currentFrontendFingerprint() -> String? {
        guard let path = frontendPath else { return nil }
        let watchedFiles = ["index.html", "style.css", "app.js", "search-shortcut.js"]
        let parts = watchedFiles.compactMap { filename -> String? in
            let filePath = (path as NSString).appendingPathComponent(filename)
            guard let attrs = try? FileManager.default.attributesOfItem(atPath: filePath) else { return nil }
            let modified = (attrs[.modificationDate] as? Date)?.timeIntervalSince1970 ?? 0
            let size = (attrs[.size] as? NSNumber)?.int64Value ?? 0
            return "\(filename):\(modified):\(size)"
        }
        return parts.isEmpty ? nil : parts.joined(separator: "|")
    }

    private func scheduleFrontendReload() {
        frontendReloadWork?.cancel()
        let work = DispatchWorkItem { [weak self] in
            guard let self = self else { return }
            if self.automaticFrontendRefresh {
                self.frontendFingerprint = self.currentFrontendFingerprint()
                self.reloadApplication()
            }
            // Codex may atomically replace a file. Reopen the paths so monitoring
            // continues against the newly created file descriptors.
            self.configureFrontendMonitor()
        }
        frontendReloadWork = work
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.8, execute: work)
    }

    private func showWaitingForBackend() {
        guard !isWaitingForBackend else { return }
        isWaitingForBackend = true
        let html = """
        <!doctype html>
        <html lang="zh-CN">
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <style>
          *{box-sizing:border-box}html,body{height:100%;margin:0}
          body{display:grid;place-items:center;background:#f7f8fc;color:#334155;
               font-family:-apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}
          main{text-align:center;transform:translateY(-3vh)}
          .mark{width:58px;height:58px;margin:0 auto 18px;display:grid;place-items:center;
                border-radius:17px;background:#fff;color:#8b1f1f;
                box-shadow:0 12px 34px rgba(15,23,42,.10)}
          h1{margin:0 0 9px;font-size:20px;font-weight:680;letter-spacing:.08em}
          p{margin:0;color:#94a3b8;font-size:13px}
          .dots::after{content:"";animation:dots 1.2s steps(4,end) infinite}
          @keyframes dots{0%{content:""}25%{content:"."}50%{content:".."}75%,100%{content:"..."}}
          @media(prefers-color-scheme:dark){body{background:#111720;color:#e5e7eb}.mark{background:#1b2431}}
        </style>
        <main>
          <div class="mark">
            <svg width="30" height="30" viewBox="0 0 30 30" fill="none" aria-hidden="true">
              <path d="M5 25h20M7.5 22h15M9 11.5v10.5M15 11.5v10.5M21 11.5v10.5M5.5 9.5h19L15 4 5.5 9.5Z"
                    stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </div>
          <h1>Stella</h1>
          <p>正在连接本地服务<span class="dots"></span></p>
        </main>
        </html>
        """
        webView.loadHTMLString(html, baseURL: nil)
        startBackendProbe()
    }

    private func startBackendProbe() {
        backendTimer?.invalidate()
        backendTimer = Timer.scheduledTimer(withTimeInterval: 1.5, repeats: true) { [weak self] _ in
            self?.probeBackend()
        }
        probeBackend()
    }

    private func probeBackend() {
        var request = URLRequest(url: legalKBStatusURL)
        request.cachePolicy = .reloadIgnoringLocalCacheData
        request.timeoutInterval = 1.2
        URLSession.shared.dataTask(with: request) { [weak self] data, response, _ in
            guard let http = response as? HTTPURLResponse, http.statusCode == 200 else { return }
            guard let data = data,
                  let status = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  status["source_status"] as? String == "current",
                  status["restart_required"] as? Bool == false else { return }
            DispatchQueue.main.async {
                guard let self = self, self.isWaitingForBackend else { return }
                self.backendTimer?.invalidate()
                self.backendTimer = nil
                self.loadApplication()
            }
        }.resume()
    }

    private func isLocalApplicationURL(_ url: URL?) -> Bool {
        guard let url = url else { return false }
        if url.scheme == "about" || url.scheme == "data" || url.scheme == "blob" {
            return true
        }
        return url.host == "localhost" || url.host == "127.0.0.1"
    }

    private func openExternalURLRequest(_ url: URL) -> Bool {
        guard url.scheme == "legalkb-external" else { return false }

        let components = URLComponents(url: url, resolvingAgainstBaseURL: false)
        guard
            let rawTarget = components?.queryItems?.first(where: { $0.name == "url" })?.value,
            let targetURL = URL(string: rawTarget),
            ["http", "https", "mailto"].contains(targetURL.scheme?.lowercased() ?? "")
        else {
            NSSound.beep()
            return true
        }

        NSWorkspace.shared.open(targetURL)
        return true
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        if let url = webView.url, (url.scheme == "http" || url.scheme == "https"),
           isLocalApplicationURL(url) {
            isWaitingForBackend = false
            backendTimer?.invalidate()
            backendTimer = nil
        }
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        let now = Date()
        webContentRecoveryTimes = webContentRecoveryTimes.filter { now.timeIntervalSince($0) < 60 }
        webContentRecoveryTimes.append(now)
        NSLog("APEX WebKit content process terminated; recovery attempt %d", webContentRecoveryTimes.count)

        // Tab state and drafts are continuously kept by the web app. Reload the
        // same local URL so a WebKit process failure does not close the App.
        if webContentRecoveryTimes.count <= 3 {
            let recoveryURL = isLocalApplicationURL(webView.url) ? (webView.url ?? legalKBHomeURL) : legalKBHomeURL
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) { [weak self] in
                self?.loadFreshApplicationDocument(url: recoveryURL)
            }
            return
        }

        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = "页面进程反复中断"
        alert.informativeText = "Stella 已保留本地状态。请先重新载入；如果仍然出现，可完全退出后再次打开。"
        alert.addButton(withTitle: "重新载入")
        alert.addButton(withTitle: "稍后处理")
        alert.beginSheetModal(for: window) { [weak self] response in
            guard response == .alertFirstButtonReturn else { return }
            self?.webContentRecoveryTimes.removeAll()
            self?.loadApplication()
        }
    }

    // 媒体捕获授权：旧版 macOS 11.3 SDK 没有 WKMediaCaptureType /
    // WKPermissionDecision 类型，这里用 @objc 选择器在运行时注册
    // macOS 12+ 的授权回调，WebKit 通过 respondsToSelector 找到它。
    // WKPermissionDecision: 0 = prompt, 1 = grant, 2 = deny
    // WKMediaCaptureType:   1 = camera, 2 = microphone
    @objc(webView:requestMediaCapturePermissionFor:initiatedByFrame:type:decisionHandler:)
    func webViewMediaCapturePermission(_ webView: WKWebView,
                                       origin: AnyObject,
                                       frame: AnyObject,
                                       type: Int,
                                       decisionHandler: @escaping @convention(block) (Int) -> Void) {
        decisionHandler((type & 2) != 0 ? 1 : 2)
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        let code = (error as NSError).code
        if code == NSURLErrorCannotConnectToHost ||
            code == NSURLErrorTimedOut ||
            code == NSURLErrorNetworkConnectionLost {
            showWaitingForBackend()
        }
    }

    func webView(
        _ webView: WKWebView,
        decidePolicyFor navigationAction: WKNavigationAction,
        decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
    ) {
        guard let url = navigationAction.request.url else {
            decisionHandler(.cancel)
            return
        }

        if openExternalURLRequest(url) {
            decisionHandler(.cancel)
            return
        }

        if isLocalApplicationURL(url) {
            if navigationAction.targetFrame == nil {
                webView.load(navigationAction.request)
                decisionHandler(.cancel)
            } else {
                decisionHandler(.allow)
            }
            return
        }

        if url.scheme == "http" || url.scheme == "https" || url.scheme == "mailto" {
            NSWorkspace.shared.open(url)
            decisionHandler(.cancel)
            return
        }

        decisionHandler(.allow)
    }

    func webView(
        _ webView: WKWebView,
        decidePolicyFor navigationResponse: WKNavigationResponse,
        decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void
    ) {
        let response = navigationResponse.response
        if navigationResponse.isForMainFrame,
           isLocalApplicationURL(response.url),
           let http = response as? HTTPURLResponse,
           http.statusCode == 503 {
            decisionHandler(.cancel)
            DispatchQueue.main.async { [weak self] in
                self?.showWaitingForBackend()
            }
            return
        }
        let disposition = (response as? HTTPURLResponse)?
            .value(forHTTPHeaderField: "Content-Disposition")?
            .lowercased() ?? ""
        if disposition.contains("attachment") || !navigationResponse.canShowMIMEType {
            decisionHandler(.download)
        } else {
            decisionHandler(.allow)
        }
    }

    func webView(
        _ webView: WKWebView,
        navigationAction: WKNavigationAction,
        didBecome download: WKDownload
    ) {
        retainAndConfigure(download)
    }

    func webView(
        _ webView: WKWebView,
        navigationResponse: WKNavigationResponse,
        didBecome download: WKDownload
    ) {
        retainAndConfigure(download)
    }

    private func retainAndConfigure(_ download: WKDownload) {
        activeDownloads[ObjectIdentifier(download)] = download
        download.delegate = self
    }

    func download(
        _ download: WKDownload,
        decideDestinationUsing response: URLResponse,
        suggestedFilename: String,
        completionHandler: @escaping (URL?) -> Void
    ) {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = suggestedFilename
        panel.canCreateDirectories = true
        panel.beginSheetModal(for: window) { result in
            guard result == .OK, let url = panel.url else {
                completionHandler(nil)
                return
            }
            if FileManager.default.fileExists(atPath: url.path) {
                try? FileManager.default.removeItem(at: url)
            }
            completionHandler(url)
        }
    }

    func downloadDidFinish(_ download: WKDownload) {
        activeDownloads.removeValue(forKey: ObjectIdentifier(download))
    }

    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
        activeDownloads.removeValue(forKey: ObjectIdentifier(download))
        let alert = NSAlert(error: error)
        alert.messageText = "下载没有完成"
        alert.beginSheetModal(for: window)
    }

    func webView(
        _ webView: WKWebView,
        runJavaScriptAlertPanelWithMessage message: String,
        initiatedByFrame frame: WKFrameInfo,
        completionHandler: @escaping () -> Void
    ) {
        let alert = NSAlert()
        alert.messageText = "Stella"
        alert.informativeText = message
        alert.alertStyle = .informational
        alert.addButton(withTitle: "确定")
        alert.beginSheetModal(for: window) { _ in
            completionHandler()
        }
    }

    func webView(
        _ webView: WKWebView,
        runJavaScriptConfirmPanelWithMessage message: String,
        initiatedByFrame frame: WKFrameInfo,
        completionHandler: @escaping (Bool) -> Void
    ) {
        let alert = NSAlert()
        alert.messageText = "请确认"
        alert.informativeText = message
        alert.alertStyle = .warning
        alert.addButton(withTitle: "确认")
        alert.addButton(withTitle: "取消")
        alert.beginSheetModal(for: window) { response in
            completionHandler(response == .alertFirstButtonReturn)
        }
    }

    func webView(
        _ webView: WKWebView,
        runJavaScriptTextInputPanelWithPrompt prompt: String,
        defaultText: String?,
        initiatedByFrame frame: WKFrameInfo,
        completionHandler: @escaping (String?) -> Void
    ) {
        let input = NSTextField(frame: NSRect(x: 0, y: 0, width: 360, height: 24))
        input.stringValue = defaultText ?? ""

        let alert = NSAlert()
        alert.messageText = "请输入"
        alert.informativeText = prompt
        alert.alertStyle = .informational
        alert.accessoryView = input
        alert.addButton(withTitle: "确定")
        alert.addButton(withTitle: "取消")
        alert.beginSheetModal(for: window) { response in
            completionHandler(response == .alertFirstButtonReturn ? input.stringValue : nil)
        }
    }

    func webView(
        _ webView: WKWebView,
        runOpenPanelWith parameters: WKOpenPanelParameters,
        initiatedByFrame frame: WKFrameInfo,
        completionHandler: @escaping ([URL]?) -> Void
    ) {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.canChooseDirectories = false
        panel.canChooseFiles = true
        panel.beginSheetModal(for: window) { result in
            completionHandler(result == .OK ? panel.urls : nil)
        }
    }

    func webView(
        _ webView: WKWebView,
        createWebViewWith configuration: WKWebViewConfiguration,
        for navigationAction: WKNavigationAction,
        windowFeatures: WKWindowFeatures
    ) -> WKWebView? {
        guard let url = navigationAction.request.url else { return nil }
        if isLocalApplicationURL(url) {
            webView.load(navigationAction.request)
        } else {
            NSWorkspace.shared.open(url)
        }
        return nil
    }
}

@available(macOS 11.3, *)
extension LegalKBWindowController: WKScriptMessageHandler {
    func userContentController(
        _ userContentController: WKUserContentController,
        didReceive message: WKScriptMessage
    ) {
        guard let body = message.body as? [String: Any] else { return }
        if message.name == "brandIcon" {
            guard message.frameInfo.isMainFrame, isLocalApplicationURL(webView.url) else { return }
            updateBrandDockIcon(body["logo"] as? String ?? "")
            return
        }
        guard message.name == "biometric" else {
            guard message.name == "clipboard" else { return }
            let action = body["action"] as? String ?? ""
            let requestId = body["requestId"] as? String ?? ""
            handleClipboardRequest(action: action, requestId: requestId, body: body)
            return
        }
        let action = body["action"] as? String ?? ""
        let requestId = body["requestId"] as? String ?? ""
        guard isLocalApplicationURL(webView.url) else {
            replyBiometric(requestId: requestId, payload: ["ok": false, "error": "仅本机 Stella 页面可使用指纹登录"])
            return
        }
        handleBiometricRequest(action: action, requestId: requestId)
    }

    private func updateBrandDockIcon(_ dataURL: String) {
        guard !dataURL.isEmpty else {
            restoreBundledDockIcon()
            return
        }
        guard dataURL.count < 3_000_000,
              let comma = dataURL.firstIndex(of: ","),
              ["data:image/png;base64", "data:image/webp;base64"].contains(String(dataURL[..<comma]).lowercased()),
              let data = Data(base64Encoded: String(dataURL[dataURL.index(after: comma)...])),
              let source = NSImage(data: data), source.size.width > 0, source.size.height > 0 else { return }

        // The packaged Stella asset is already rendered as an AppIcon.icns.
        // Reuse it byte-for-byte to keep the running Dock icon identical to
        // the icon macOS displays while the app is closed.
        if let path = Bundle.main.path(forResource: "StellaBrand", ofType: "png"),
           let packagedLogo = try? Data(contentsOf: URL(fileURLWithPath: path)),
           data == packagedLogo {
            restoreBundledDockIcon()
            return
        }

        guard let bitmap = NSBitmapImageRep(
            bitmapDataPlanes: nil,
            pixelsWide: 1024,
            pixelsHigh: 1024,
            bitsPerSample: 8,
            samplesPerPixel: 4,
            hasAlpha: true,
            isPlanar: false,
            colorSpaceName: .deviceRGB,
            bytesPerRow: 0,
            bitsPerPixel: 0
        ), let context = NSGraphicsContext(bitmapImageRep: bitmap) else { return }

        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = context
        context.imageInterpolation = .high
        let tile = NSRect(x: 36, y: 36, width: 952, height: 952)
        let shadow = NSShadow()
        shadow.shadowBlurRadius = 18
        shadow.shadowOffset = NSSize(width: 0, height: -7)
        shadow.shadowColor = NSColor.black.withAlphaComponent(0.16)
        shadow.set()
        NSColor.white.setFill()
        NSBezierPath(roundedRect: tile, xRadius: 206, yRadius: 206).fill()
        shadow.shadowColor = .clear
        shadow.set()
        let scale = min(1024 / source.size.width, 1024 / source.size.height)
        let width = source.size.width * scale
        let height = source.size.height * scale
        source.draw(in: NSRect(x: (1024 - width) / 2, y: (1024 - height) / 2, width: width, height: height))
        NSGraphicsContext.restoreGraphicsState()
        bitmap.size = NSSize(width: 512, height: 512)
        let icon = NSImage(size: NSSize(width: 512, height: 512))
        icon.addRepresentation(bitmap)
        NSApp.applicationIconImage = icon
        isDockIconOverridden = true
    }

    private func restoreBundledDockIcon() {
        // On first launch the system is already showing AppIcon.icns. Leave
        // that instance untouched so the open and closed Dock states agree.
        guard isDockIconOverridden else { return }
        if let path = Bundle.main.path(forResource: "AppIcon", ofType: "icns"),
           let icon = NSImage(contentsOfFile: path) {
            NSApp.applicationIconImage = icon
            isDockIconOverridden = false
        }
    }

    private func handleBiometricRequest(action: String, requestId: String) {
        let context = LAContext()
        context.localizedCancelTitle = "取消"
        var error: NSError?

        if action == "available" {
            let available = context.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: &error)
            replyBiometric(requestId: requestId, payload: [
                "available": available,
                "error": error?.localizedDescription ?? "",
            ])
            return
        }

        guard action == "verify" || action == "login" else {
            replyBiometric(requestId: requestId, payload: ["ok": false, "error": "未知的指纹操作"])
            return
        }

        guard context.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: &error) else {
            replyBiometric(requestId: requestId, payload: [
                "ok": false,
                "error": error?.localizedDescription ?? "本机未开启或未录入指纹，请使用密码验证",
            ])
            return
        }

        activeBiometricContexts[requestId] = context
        context.evaluatePolicy(
            .deviceOwnerAuthenticationWithBiometrics,
            localizedReason: action == "login" ? "验证指纹以登录 Stella" : "验证指纹以进入个人中心"
        ) { [weak self] success, evalError in
            guard let self = self else { return }
            DispatchQueue.main.async {
                self.activeBiometricContexts.removeValue(forKey: requestId)
            }
            if !success {
                self.replyBiometric(requestId: requestId, payload: [
                    "ok": false,
                    "error": evalError?.localizedDescription ?? "指纹验证未通过",
                ])
                return
            }
            if action == "login" {
                self.exchangeLoginBiometricSession(requestId: requestId)
            } else {
                self.exchangeBiometricSession(requestId: requestId)
            }
        }
    }

    /// Touch ID 通过后，以一次性票据让 WKWebView 建立常规登录 Cookie。
    private func exchangeLoginBiometricSession(requestId: String) {
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            guard let self = self else { return }
            do {
                let challengePayload = try self.syncJSONRequest(
                    url: loginBiometricChallengeURL,
                    method: "GET",
                    body: nil
                )
                let challenge = challengePayload["challenge"] as? String ?? ""
                guard !challenge.isEmpty else {
                    self.finishBiometric(requestId: requestId, payload: [
                        "ok": false, "error": "本地服务未返回指纹验证凭证",
                    ])
                    return
                }
                let completePayload = try self.syncJSONRequest(
                    url: loginBiometricCompleteURL,
                    method: "POST",
                    body: ["challenge": challenge, "secret": loginBiometricBridgeSecret]
                )
                self.finishBiometric(requestId: requestId, payload: completePayload)
            } catch {
                self.finishBiometric(requestId: requestId, payload: [
                    "ok": false, "error": "无法连接本地服务：\(error.localizedDescription)",
                ])
            }
        }
    }

    /// Touch ID 通过后，向本地后端兑换个人中心会话；网络操作放到后台线程。
    private func exchangeBiometricSession(requestId: String) {
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            guard let self = self else { return }
            do {
                let challengePayload = try self.syncJSONRequest(
                    url: biometricChallengeURL,
                    method: "GET",
                    body: nil
                )
                let challenge = challengePayload["challenge"] as? String ?? ""
                guard !challenge.isEmpty else {
                    self.finishBiometric(requestId: requestId, payload: [
                        "ok": false, "error": "本地服务未返回指纹验证凭证",
                    ])
                    return
                }
                let completePayload = try self.syncJSONRequest(
                    url: biometricCompleteURL,
                    method: "POST",
                    body: ["challenge": challenge, "secret": biometricBridgeSecret]
                )
                self.finishBiometric(requestId: requestId, payload: completePayload)
            } catch {
                self.finishBiometric(requestId: requestId, payload: [
                    "ok": false, "error": "无法连接本地服务：\(error.localizedDescription)",
                ])
            }
        }
    }

    private func syncJSONRequest(url: URL, method: String, body: [String: Any]?) throws -> [String: Any] {
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = 10
        request.cachePolicy = .reloadIgnoringLocalCacheData
        if let body = body {
            request.httpBody = try JSONSerialization.data(withJSONObject: body, options: [])
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        var result: Result<[String: Any], Error>?
        let semaphore = DispatchSemaphore(value: 0)
        URLSession.shared.dataTask(with: request) { data, response, error in
            defer { semaphore.signal() }
            if let error = error {
                result = .failure(error)
                return
            }
            guard let data = data,
                  let payload = (try? JSONSerialization.jsonObject(with: data, options: [])) as? [String: Any] else {
                result = .failure(NSError(
                    domain: "LegalKBBiometric",
                    code: -1,
                    userInfo: [NSLocalizedDescriptionKey: "本地服务返回格式无法识别"]
                ))
                return
            }
            if let http = response as? HTTPURLResponse, http.statusCode >= 400 {
                let detail = payload["detail"] as? String ?? "请求失败"
                result = .failure(NSError(
                    domain: "LegalKBBiometric",
                    code: http.statusCode,
                    userInfo: [NSLocalizedDescriptionKey: detail]
                ))
                return
            }
            result = .success(payload)
        }.resume()
        _ = semaphore.wait(timeout: .now() + 12)
        guard let result = result else {
            throw NSError(
                domain: "LegalKBBiometric",
                code: -2,
                userInfo: [NSLocalizedDescriptionKey: "本地服务响应超时"]
            )
        }
        switch result {
        case .success(let payload):
            return payload
        case .failure(let error):
            throw error
        }
    }

    private func finishBiometric(requestId: String, payload: [String: Any]) {
        replyBiometric(requestId: requestId, payload: payload)
    }

    // 系统剪贴板文件互通：前端在案件文件页按 ⌘C/⌘V 时，
    // 读取或写入 NSPasteboard 中的文件路径，实现与访达之间的复制粘贴。
    private func handleClipboardRequest(action: String, requestId: String, body: [String: Any]) {
        switch action {
        case "readFiles":
            replyClipboard(requestId: requestId, payload: clipboardFilePaths())
        case "writeFiles":
            let paths = (body["paths"] as? [String]) ?? []
            let ok = writeFilePathsToClipboard(paths)
            replyClipboard(requestId: requestId, payload: ["ok": ok, "count": paths.count])
        default:
            replyClipboard(requestId: requestId, payload: ["ok": false, "error": "未知的剪贴板操作"])
        }
    }

    /// 读取系统剪贴板中的文件路径（访达或其它文件管理器复制后写入）。
    private func clipboardFilePaths() -> [String: Any] {
        let pasteboard = NSPasteboard.general
        var paths: [String] = []

        // readObjects 是 AppKit 读取文件列表的标准方式，可一次取回全部文件，
        // 兼容访达写入的 public.file-url / NSFilenamesPboardType 格式。
        if let urls = pasteboard.readObjects(
            forClasses: [NSURL.self],
            options: [.urlReadingFileURLsOnly: true]
        ) as? [URL] {
            paths = urls.map { $0.path }
        }

        // 兜底：手动解析原始剪贴板数据（部分第三方应用格式 readObjects 读不到）。
        if paths.isEmpty {
            let fileURLType = NSPasteboard.PasteboardType("public.file-url")
            if let strings = pasteboard.propertyList(forType: fileURLType) as? [String] {
                paths = strings.compactMap { URL(string: $0)?.path }
            } else if let single = pasteboard.propertyList(forType: fileURLType) as? String {
                paths = single.split(separator: "\n").compactMap { URL(string: String($0))?.path }
            } else if let dataArray = pasteboard.propertyList(forType: fileURLType) as? [Data] {
                for data in dataArray {
                    var bytes = [UInt8](data)
                    while let last = bytes.last, last == 0 { bytes.removeLast() }
                    if let text = String(bytes: bytes, encoding: .utf8),
                       let url = URL(string: text) {
                        paths.append(url.path)
                    }
                }
            }
        }

        // 部分应用只写 NSFilenamesPboardType。
        if paths.isEmpty {
            let filenamesType = NSPasteboard.PasteboardType("NSFilenamesPboardType")
            if let names = pasteboard.propertyList(forType: filenamesType) as? [String] {
                paths = names
            }
        }

        // 拖放承诺文件（某些场景延迟提供内容）仅保留其 URL。
        if paths.isEmpty {
            let promisedType = NSPasteboard.PasteboardType("com.apple.pasteboard.promised-file-url")
            if let names = pasteboard.propertyList(forType: promisedType) as? [String] {
                paths = names.compactMap { URL(string: $0)?.path }
            }
        }

        // 只保留本机真实存在的路径，避免把纯文本粘贴当成文件。
        let fileManager = FileManager.default
        return ["ok": true, "paths": paths.filter { fileManager.fileExists(atPath: $0) }]
    }

    /// 把案件文件路径写入系统剪贴板，访达可以直接粘贴。
    private func writeFilePathsToClipboard(_ paths: [String]) -> Bool {
        let valid = paths.filter { !$0.isEmpty }
        guard !valid.isEmpty else { return false }
        let urls = valid.map { URL(fileURLWithPath: $0) }
        let pasteboard = NSPasteboard.general
        pasteboard.clearContents()
        return pasteboard.writeObjects(urls as [NSURL])
    }

    private func replyClipboard(requestId: String, payload: [String: Any]) {
        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }
            guard
                let data = try? JSONSerialization.data(withJSONObject: [requestId, payload], options: []),
                let args = String(data: data, encoding: .utf8)
            else { return }
            // 案件文件页运行在顶层窗口的 iframe 中，必须遍历并投递给每个子 frame。
            let script = """
            (function () {
              var args = \(args);
              if (typeof window.__cfClipboardReply === 'function') { window.__cfClipboardReply(args[0], args[1]); }
              var message = { type: 'cfClipboardReply', requestId: args[0], payload: args[1] };
              function notifyChildren(parentWindow) {
                var count = 0;
                try { count = parentWindow.frames.length; } catch (e) { return; }
                for (var i = 0; i < count; i++) {
                  var child = parentWindow.frames[i];
                  try { child.postMessage(message, '*'); } catch (e) {}
                  try { notifyChildren(child); } catch (e) {}
                }
              }
              notifyChildren(window);
            })();
            """
            self.webView.evaluateJavaScript(script, completionHandler: nil)
        }
    }

    private func replyBiometric(requestId: String, payload: [String: Any]) {
        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }
            guard
                let data = try? JSONSerialization.data(withJSONObject: [requestId, payload], options: []),
                let args = String(data: data, encoding: .utf8)
            else { return }
            // evaluateJavaScript 只在顶层窗口执行；个人中心运行在 iframe 中。
            // window.postMessage 只会投递给被调用的那个 window，不会自动向子 frame
            // 传播，因此必须显式遍历并投递给每个子 frame。
            let script = """
            (function () {
              var args = \(args);
              if (typeof window.__pcBiometricReply === 'function') { window.__pcBiometricReply(args[0], args[1]); }
              if (typeof window.__pcSettingsBiometricReply === 'function') { window.__pcSettingsBiometricReply(args[0], args[1]); }
              var message = { type: 'pcBiometricReply', requestId: args[0], payload: args[1] };
              function notifyChildren(parentWindow) {
                var count = 0;
                try { count = parentWindow.frames.length; } catch (e) { return; }
                for (var i = 0; i < count; i++) {
                  var child = parentWindow.frames[i];
                  try { child.postMessage(message, '*'); } catch (e) {}
                  try { notifyChildren(child); } catch (e) {}
                }
              }
              notifyChildren(window);
            })();
            """
            self.webView.evaluateJavaScript(script, completionHandler: nil)
        }
    }
}

extension Notification.Name {
    static let automaticFrontendRefreshChanged = Notification.Name("LegalKBAutomaticFrontendRefreshChanged")
}

@available(macOS 11.3, *)
final class AppDelegate: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate {
    private var controller: LegalKBWindowController?
    private var autoRefreshMenuItem: NSMenuItem?
    private var statusItem: NSStatusItem?
    private var courtTimer: Timer?
    private var knownCourtRecordIDs: Set<Int> = []
    private var hasPrimedCourtRecords = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        controller = LegalKBWindowController()
        buildMainMenu()
        buildStatusItem()
        configureCourtNotifications()
        controller?.showWindow()
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(syncAutoRefreshMenuItem),
            name: .automaticFrontendRefreshChanged,
            object: nil
        )
    }

    func applicationWillTerminate(_ notification: Notification) {
        courtTimer?.invalidate()
    }

    func applicationDidBecomeActive(_ notification: Notification) {
        controller?.applicationDidBecomeActive()
    }

    func applicationDidResignActive(_ notification: Notification) {
        controller?.applicationDidResignActive()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        return false
    }

    private func buildStatusItem() {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        item.button?.image = NSImage(systemSymbolName: "briefcase", accessibilityDescription: "Stella")
        let menu = NSMenu()
        menu.addItem(withTitle: "显示 Stella", action: #selector(showAPEX), keyEquivalent: "")
        menu.addItem(withTitle: "打开法院在线服务", action: #selector(openCourtOnline), keyEquivalent: "")
        menu.addItem(.separator())
        menu.addItem(withTitle: "退出 Stella", action: #selector(quitAPEX), keyEquivalent: "q")
        item.menu = menu
        statusItem = item
    }

    @objc private func showAPEX() { controller?.showWindow() }
    @objc private func openCourtOnline() { controller?.openCourtOnlineService() }
    @objc private func quitAPEX() { NSApp.terminate(nil) }

    private func activeUndoManager() -> UndoManager? {
        NSApp.keyWindow?.firstResponder?.undoManager ?? controller?.webView.undoManager
    }

    @objc private func performUndo(_ sender: Any?) {
        activeUndoManager()?.undo()
    }

    @objc private func performRedo(_ sender: Any?) {
        activeUndoManager()?.redo()
    }

    private func configureCourtNotifications() {
        let center = UNUserNotificationCenter.current()
        center.delegate = self
        center.requestAuthorization(options: [.alert, .sound]) { _, _ in }
        courtTimer = Timer.scheduledTimer(withTimeInterval: 45, repeats: true) { [weak self] _ in self?.pollCourtNotifications() }
        pollCourtNotifications()
    }

    private func pollCourtNotifications() {
        let url = URL(string: "http://127.0.0.1:8000/api/case-manager/court-online/records?unread=true&page_size=20")!
        URLSession.shared.dataTask(with: url) { [weak self] data, _, _ in
            guard let self = self, let data = data,
                  let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let items = root["items"] as? [[String: Any]] else { return }
            let ids = Set(items.compactMap { ($0["id"] as? NSNumber)?.intValue })
            defer { self.knownCourtRecordIDs = ids; self.hasPrimedCourtRecords = true }
            guard self.hasPrimedCourtRecords else { return }
            for item in items where !self.knownCourtRecordIDs.contains((item["id"] as? NSNumber)?.intValue ?? -1) {
                let content = UNMutableNotificationContent()
                content.title = "Stella · 法院在线服务"
                content.body = (item["title"] as? String) ?? "收到新的法院在线服务消息"
                content.sound = .default
                content.userInfo = ["route": "courtOnline", "recordId": item["id"] ?? 0]
                let request = UNNotificationRequest(identifier: "court-online-\(UUID().uuidString)", content: content, trigger: nil)
                UNUserNotificationCenter.current().add(request)
            }
        }.resume()
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse, withCompletionHandler completionHandler: @escaping () -> Void) {
        if (response.notification.request.content.userInfo["route"] as? String) == "courtOnline" {
            let recordID = response.notification.request.content.userInfo["recordId"] as? Int
                ?? (response.notification.request.content.userInfo["recordId"] as? NSNumber)?.intValue
            DispatchQueue.main.async { self.controller?.openCourtOnlineService(recordID: recordID) }
        }
        completionHandler()
    }

    private func buildMainMenu() {
        let mainMenu = NSMenu()

        let appMenuItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "关于 Stella", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        let quitItem = NSMenuItem(title: "退出 Stella", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appMenu.addItem(quitItem)
        appMenuItem.submenu = appMenu
        mainMenu.addItem(appMenuItem)

        // WKWebView relies on the responder-chain edit actions for the standard
        // macOS editing shortcuts. Without these menu items, forwarding the
        // key event alone does not reliably trigger undo/redo/copy/paste/select-all.
        let editMenuItem = NSMenuItem()
        let editMenu = NSMenu(title: "编辑")
        let undoItem = NSMenuItem(title: "撤销", action: #selector(performUndo(_:)), keyEquivalent: "z")
        undoItem.keyEquivalentModifierMask = [.command]
        undoItem.target = self
        editMenu.addItem(undoItem)
        let redoItem = NSMenuItem(title: "重做", action: #selector(performRedo(_:)), keyEquivalent: "z")
        redoItem.keyEquivalentModifierMask = [.command, .shift]
        redoItem.target = self
        editMenu.addItem(redoItem)
        editMenu.addItem(.separator())
        editMenu.addItem(withTitle: "剪切", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        editMenu.addItem(withTitle: "复制", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "粘贴", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(withTitle: "全选", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editMenuItem.submenu = editMenu
        mainMenu.addItem(editMenuItem)

        let viewMenuItem = NSMenuItem()
        let viewMenu = NSMenu(title: "显示")

        let reloadItem = NSMenuItem(title: "重新载入", action: #selector(reloadApplication), keyEquivalent: "r")
        reloadItem.target = self
        viewMenu.addItem(reloadItem)

        let autoItem = NSMenuItem(title: "前端改动后自动刷新", action: #selector(toggleAutomaticFrontendRefresh), keyEquivalent: "")
        autoItem.target = self
        autoRefreshMenuItem = autoItem
        viewMenu.addItem(autoItem)

        let fullScreenItem = NSMenuItem(title: "进入/退出沉浸模式", action: #selector(toggleFullScreen), keyEquivalent: "f")
        fullScreenItem.keyEquivalentModifierMask = [.command, .control]
        fullScreenItem.target = self
        viewMenu.addItem(fullScreenItem)

        viewMenuItem.submenu = viewMenu
        mainMenu.addItem(viewMenuItem)

        NSApp.mainMenu = mainMenu
        syncAutoRefreshMenuItem()
    }

    @objc private func reloadApplication() {
        controller?.reloadApplication()
    }

    @objc private func toggleFullScreen() {
        controller?.toggleFullScreen()
    }

    @objc private func toggleAutomaticFrontendRefresh() {
        controller?.toggleAutomaticFrontendRefresh()
    }

    @objc private func syncAutoRefreshMenuItem() {
        autoRefreshMenuItem?.state = controller?.automaticFrontendRefresh == true ? .on : .off
    }
}

if #available(macOS 11.3, *) {
    let application = NSApplication.shared
    let delegate = AppDelegate()
    application.setActivationPolicy(.regular)
    application.delegate = delegate
    application.run()
} else {
    fputs("Stella 法律操作系统需要 macOS 11.3 或更高版本。\\n", stderr)
    exit(1)
}
