// Pitwall desktop widget: a small always-on-desktop panel with the 2026 championship forecast.
// It reads championship.json from the published site (rebuilt daily by GitHub Actions), refreshes every
// 30 minutes and keeps the last copy on disk so it still shows something offline.
// Build: widget/build.sh  (needs only the Swift toolchain that ships with Xcode / Command Line Tools)

import AppKit
import SwiftUI

let siteURL = URL(string: "https://emrtunali.github.io/pitwall/")!
let dataURL = URL(string: "https://emrtunali.github.io/pitwall/data/2026/championship.json")!
let indexURL = URL(string: "https://emrtunali.github.io/pitwall/data/2026/index.json")!

// MARK: - Data

struct Forecast: Decodable {
    struct Driver: Decodable, Identifiable {
        let num: Int; let code: String; let name: String; let team: String; let colour: String
        let points: Double; let p_title: Double; let expected: Double; let p10: Double; let p90: Double
        var id: Int { num }
    }
    struct Team: Decodable, Identifiable {
        let team: String; let colour: String; let points: Double; let p_title: Double
        let expected: Double; let p10: Double; let p90: Double
        var id: String { team }
    }
    struct Round: Decodable { let circuit: String; let date: String }
    struct Body: Decodable { let drivers: [Driver]; let teams: [Team]; let remaining: [Round] }
    struct History: Decodable { let after: String; let drivers: [String: Double]; let teams: [String: Double] }
    let generated_at: String
    let after_round: String
    let forecast: Body
    let history: [History]
}

struct SiteIndex: Decodable {
    struct Next: Decodable { let circuit: String; let start: String }
    let next_race: Next?
}

@MainActor
final class Store: ObservableObject {
    @Published var forecast: Forecast?
    @Published var next: SiteIndex.Next?
    @Published var status = "Loading…"
    private var timer: Timer?
    private let cache: URL = {
        let dir = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("PitwallWidget", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir.appendingPathComponent("championship.json")
    }()

    init() {
        if let data = try? Data(contentsOf: cache), let f = try? JSONDecoder().decode(Forecast.self, from: data) {
            forecast = f
            status = "Offline copy"
        }
        refresh()
        timer = Timer.scheduledTimer(withTimeInterval: 30 * 60, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.refresh() }
        }
    }

    func refresh() {
        Task {
            do {
                var req = URLRequest(url: dataURL)
                req.cachePolicy = .reloadIgnoringLocalCacheData
                let (data, _) = try await URLSession.shared.data(for: req)
                let f = try JSONDecoder().decode(Forecast.self, from: data)
                try? data.write(to: cache)
                forecast = f
                if let (idx, _) = try? await URLSession.shared.data(from: indexURL),
                   let i = try? JSONDecoder().decode(SiteIndex.self, from: idx) { next = i.next_race }
                let fmt = DateFormatter(); fmt.dateFormat = "HH:mm"
                status = "Updated \(fmt.string(from: Date()))"
            } catch {
                status = forecast == nil ? "No connection" : "Offline copy"
            }
        }
    }
}

// MARK: - Views

extension Color {
    init(hex: String) {
        let s = hex.trimmingCharacters(in: CharacterSet(charactersIn: "#"))
        let v = UInt64(s, radix: 16) ?? 0x888888
        self.init(red: Double((v >> 16) & 0xff) / 255, green: Double((v >> 8) & 0xff) / 255, blue: Double(v & 0xff) / 255)
    }
}

func pct(_ p: Double) -> String {
    if p >= 0.995 { return ">99%" }
    if p < 0.005 { return "<1%" }
    return "\(Int((p * 100).rounded()))%"
}

struct Row: View {
    let colour: String; let label: String; let sub: String; let points: Double; let p: Double
    let lo: Double; let hi: Double
    var body: some View {
        HStack(spacing: 8) {
            RoundedRectangle(cornerRadius: 2).fill(Color(hex: colour)).frame(width: 4, height: 26)
            VStack(alignment: .leading, spacing: 1) {
                Text(label).font(.system(size: 13, weight: .bold))
                Text(sub).font(.system(size: 10)).foregroundStyle(.secondary).lineLimit(1)
            }
            .frame(width: 92, alignment: .leading)
            VStack(alignment: .trailing, spacing: 1) {
                Text("\(Int(points)) pts").font(.system(size: 11, weight: .semibold, design: .monospaced))
                Text("→ \(Int(lo))–\(Int(hi))").font(.system(size: 9, design: .monospaced)).foregroundStyle(.secondary)
            }
            .frame(width: 66, alignment: .trailing)
            GeometryReader { g in
                ZStack(alignment: .leading) {
                    Capsule().fill(.white.opacity(0.08))
                    Capsule().fill(Color(hex: colour)).frame(width: max(3, g.size.width * p))
                }
            }
            .frame(height: 7)
            Text(pct(p)).font(.system(size: 12, weight: .bold, design: .monospaced)).frame(width: 42, alignment: .trailing)
        }
    }
}

struct Sparkline: View {
    let history: [Forecast.History]; let keys: [(String, String)]; let teams: Bool
    var body: some View {
        Canvas { ctx, size in
            guard history.count > 1 else { return }
            for (key, colour) in keys {
                var path = Path()
                for (i, h) in history.enumerated() {
                    let v = (teams ? h.teams[key] : h.drivers[key]) ?? 0
                    let pt = CGPoint(x: size.width * CGFloat(i) / CGFloat(history.count - 1),
                                     y: size.height * (1 - CGFloat(v)))
                    i == 0 ? path.move(to: pt) : path.addLine(to: pt)
                }
                ctx.stroke(path, with: .color(Color(hex: colour)), lineWidth: 1.8)
            }
        }
    }
}

struct WidgetView: View {
    @ObservedObject var store: Store
    var forSnapshot = false  // AppKit-backed controls cannot be rendered off-screen
    @State private var teams = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("🏁 2026 TITLE ODDS").font(.system(size: 12, weight: .heavy)).tracking(0.8)
                Spacer()
                if forSnapshot {
                    Text("Drivers · Teams").font(.system(size: 11, weight: .semibold)).foregroundStyle(.secondary)
                } else {
                    Picker("", selection: $teams) {
                        Text("Drivers").tag(false); Text("Teams").tag(true)
                    }
                    .pickerStyle(.segmented).labelsHidden().frame(width: 130)
                }
            }
            if let f = store.forecast {
                if teams {
                    ForEach(f.forecast.teams.prefix(6)) { t in
                        Row(colour: t.colour, label: t.team.replacingOccurrences(of: " F1 Team", with: ""),
                            sub: "constructors", points: t.points, p: t.p_title, lo: t.p10, hi: t.p90)
                    }
                } else {
                    ForEach(f.forecast.drivers.prefix(6)) { d in
                        Row(colour: d.colour, label: d.code, sub: d.team, points: d.points, p: d.p_title, lo: d.p10, hi: d.p90)
                    }
                }
                let keys: [(String, String)] = teams
                    ? f.forecast.teams.prefix(3).map { ($0.team, $0.colour) }
                    : f.forecast.drivers.prefix(3).map { (String($0.num), $0.colour) }
                VStack(alignment: .leading, spacing: 2) {
                    Text("Title odds after each round").font(.system(size: 9)).foregroundStyle(.secondary)
                    Sparkline(history: f.history, keys: keys, teams: teams).frame(height: 38)
                }
                HStack {
                    Text("After \(f.after_round) · \(f.forecast.remaining.count) races left")
                    Spacer()
                    if let n = store.next, let days = daysUntil(n.start) { Text("Next: \(n.circuit) in \(days)d") }
                }
                .font(.system(size: 10)).foregroundStyle(.secondary)
            }
            HStack {
                Text(store.status).font(.system(size: 9)).foregroundStyle(.tertiary)
                Spacer()
                if forSnapshot {
                    Text("Open Pitwall ↗").font(.system(size: 10)).foregroundStyle(.blue)
                } else {
                    Button("Open Pitwall") { NSWorkspace.shared.open(siteURL) }.buttonStyle(.link).font(.system(size: 10))
                }
            }
        }
        .padding(14)
        .frame(width: 400)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 18))
        .overlay(RoundedRectangle(cornerRadius: 18).stroke(.white.opacity(0.12)))
        .environment(\.colorScheme, .dark)
        .contextMenu {
            Button("Refresh now") { store.refresh() }
            Button("Open Pitwall") { NSWorkspace.shared.open(siteURL) }
            Divider()
            Button("Quit Pitwall Widget") { NSApp.terminate(nil) }
        }
    }

    func daysUntil(_ iso: String) -> Int? {
        let f = ISO8601DateFormatter()
        guard let d = f.date(from: iso) else { return nil }
        return max(0, Int(ceil(d.timeIntervalSinceNow / 86400)))
    }
}

// MARK: - Desktop-level window

final class DesktopPanel: NSPanel {
    override var canBecomeKey: Bool { true }
}

@main
struct PitwallWidgetApp {
    static func main() {
        // `PitwallWidget --snapshot out.png` renders the widget once to an image (used for the README).
        if let i = CommandLine.arguments.firstIndex(of: "--snapshot"), i + 1 < CommandLine.arguments.count {
            MainActor.assumeIsolated { snapshot(to: CommandLine.arguments[i + 1]) }
            return
        }
        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)  // no Dock icon, no menu bar
        let delegate = AppDelegate()
        app.delegate = delegate
        app.run()
    }
}

@MainActor
func snapshot(to path: String) {
    let store = Store()
    let deadline = Date().addingTimeInterval(20)
    while (store.forecast == nil || store.next == nil) && Date() < deadline {
        RunLoop.main.run(until: Date().addingTimeInterval(0.2))
    }
    let view = WidgetView(store: store, forSnapshot: true).padding(24).background(Color(red: 0.13, green: 0.16, blue: 0.22))
    let renderer = ImageRenderer(content: view)
    renderer.scale = 2
    guard let img = renderer.nsImage, let tiff = img.tiffRepresentation,
          let png = NSBitmapImageRep(data: tiff)?.representation(using: .png, properties: [:]) else {
        print("snapshot failed"); return
    }
    try? png.write(to: URL(fileURLWithPath: path))
    print("wrote \(path)")
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    var panel: DesktopPanel!

    func applicationDidFinishLaunching(_ notification: Notification) {
        MainActor.assumeIsolated {
            let host = NSHostingView(rootView: WidgetView(store: Store()))
            host.frame.size = host.fittingSize
            panel = DesktopPanel(contentRect: NSRect(x: 0, y: 0, width: 400, height: 360),
                                 styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
            panel.contentView = host
            panel.isOpaque = false
            panel.backgroundColor = .clear
            panel.hasShadow = true
            panel.isMovableByWindowBackground = true
            // Sit on the desktop like a widget: above the wallpaper and icons, below normal windows.
            panel.level = NSWindow.Level(rawValue: Int(CGWindowLevelForKey(.desktopIconWindow)) + 1)
            panel.collectionBehavior = [.canJoinAllSpaces, .stationary, .ignoresCycle]
            panel.setFrameAutosaveName("PitwallWidgetPosition")
            if !panel.setFrameUsingName("PitwallWidgetPosition"), let screen = NSScreen.main {
                let f = screen.visibleFrame
                panel.setFrameOrigin(NSPoint(x: f.maxX - 430, y: f.maxY - 400))
            }
            panel.orderFrontRegardless()
            Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
                MainActor.assumeIsolated {
                    guard let self, let view = self.panel.contentView else { return }
                    let size = view.fittingSize
                    if abs(size.height - self.panel.frame.height) > 1 {
                        var fr = self.panel.frame
                        fr.origin.y += fr.height - size.height
                        fr.size = size
                        self.panel.setFrame(fr, display: true)
                    }
                }
            }
        }
    }
}
