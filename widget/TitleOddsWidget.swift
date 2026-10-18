// WidgetKit extension: "2026 Title Odds" for the macOS desktop and Notification Center.
// Small, medium and large sizes. The timeline fetches championship.json from the published site
// (rebuilt daily by GitHub Actions) and asks the system to refresh every 30 minutes.

import SwiftUI
import WidgetKit

private let dataURL = URL(string: "https://emrtunali.github.io/pitwall/data/2026/championship.json")!
private let siteURL = URL(string: "https://emrtunali.github.io/pitwall/")!

struct Forecast: Decodable {
    struct Driver: Decodable, Identifiable {
        let num: Int; let code: String; let team: String; let colour: String
        let points: Double; let p_title: Double; let p10: Double; let p90: Double
        var id: Int { num }
    }
    struct Team: Decodable, Identifiable {
        let team: String; let colour: String; let points: Double; let p_title: Double
        var id: String { team }
    }
    struct Round: Decodable { let circuit: String }
    struct Body: Decodable { let drivers: [Driver]; let teams: [Team]; let remaining: [Round] }
    let after_round: String
    let forecast: Body
}

struct Entry: TimelineEntry {
    let date: Date
    let data: Forecast?
}

struct Provider: TimelineProvider {
    func placeholder(in context: Context) -> Entry { Entry(date: .now, data: Self.sample) }

    func getSnapshot(in context: Context, completion: @escaping (Entry) -> Void) {
        Task { completion(Entry(date: .now, data: await Self.load() ?? Self.sample)) }
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<Entry>) -> Void) {
        Task {
            let entry = Entry(date: .now, data: await Self.load())
            completion(Timeline(entries: [entry], policy: .after(.now.addingTimeInterval(30 * 60))))
        }
    }

    static func load() async -> Forecast? {
        var req = URLRequest(url: dataURL)
        req.cachePolicy = .reloadIgnoringLocalCacheData
        guard let (data, _) = try? await URLSession.shared.data(for: req) else { return nil }
        return try? JSONDecoder().decode(Forecast.self, from: data)
    }

    static let sample = Forecast(after_round: "—", forecast: .init(
        drivers: [.init(num: 1, code: "———", team: "", colour: "#888888", points: 0, p_title: 0.5, p10: 0, p90: 0)],
        teams: [], remaining: []))
}

extension Color {
    init(hex: String) {
        let v = UInt64(hex.trimmingCharacters(in: CharacterSet(charactersIn: "#")), radix: 16) ?? 0x888888
        self.init(red: Double((v >> 16) & 0xff) / 255, green: Double((v >> 8) & 0xff) / 255, blue: Double(v & 0xff) / 255)
    }
}

private func pct(_ p: Double) -> String {
    p >= 0.995 ? ">99%" : p < 0.005 ? "<1%" : "\(Int((p * 100).rounded()))%"
}

struct OddsRow: View {
    let colour: String; let label: String; let points: Double; let p: Double
    var body: some View {
        HStack(spacing: 6) {
            RoundedRectangle(cornerRadius: 1.5).fill(Color(hex: colour)).frame(width: 3, height: 14)
            Text(label).font(.system(size: 12, weight: .bold)).frame(width: 66, alignment: .leading).lineLimit(1)
            Text("\(Int(points))").font(.system(size: 10, design: .monospaced)).foregroundStyle(.secondary)
                .frame(width: 28, alignment: .trailing)
            GeometryReader { g in
                ZStack(alignment: .leading) {
                    Capsule().fill(.white.opacity(0.1))
                    Capsule().fill(Color(hex: colour)).frame(width: max(2, g.size.width * p))
                }
            }
            .frame(height: 6)
            Text(pct(p)).font(.system(size: 11, weight: .bold, design: .monospaced)).frame(width: 36, alignment: .trailing)
        }
    }
}

struct TitleOddsView: View {
    @Environment(\.widgetFamily) var family
    let entry: Entry

    var body: some View {
        Group {
            if let f = entry.data {
                switch family {
                case .systemSmall: small(f)
                case .systemLarge: large(f)
                default: medium(f)
                }
            } else {
                VStack(spacing: 6) {
                    Text("🏁 Title odds").font(.headline)
                    Text("No connection — will retry").font(.caption).foregroundStyle(.secondary)
                }
            }
        }
        .widgetURL(siteURL)
        .containerBackground(for: .widget) {
            LinearGradient(colors: [Color(red: 0.07, green: 0.09, blue: 0.13), Color(red: 0.12, green: 0.05, blue: 0.06)],
                           startPoint: .topLeading, endPoint: .bottomTrailing)
        }
        .environment(\.colorScheme, .dark)
    }

    func header(_ f: Forecast) -> some View {
        HStack {
            Text("🏁 2026 TITLE ODDS").font(.system(size: 11, weight: .heavy)).tracking(0.6)
            Spacer()
            Text("after \(f.after_round)").font(.system(size: 9)).foregroundStyle(.secondary)
        }
    }

    func small(_ f: Forecast) -> some View {
        let d = f.forecast.drivers
        return VStack(alignment: .leading, spacing: 4) {
            Text("🏁 2026 TITLE").font(.system(size: 10, weight: .heavy)).foregroundStyle(.secondary)
            if let top = d.first {
                Text(top.code).font(.system(size: 30, weight: .black)).foregroundStyle(Color(hex: top.colour))
                Text(pct(top.p_title)).font(.system(size: 20, weight: .bold, design: .monospaced))
                Text("\(Int(top.points)) pts · \(top.team)").font(.system(size: 9)).foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer(minLength: 0)
            ForEach(d.dropFirst().prefix(2)) { x in
                HStack { Text(x.code).font(.system(size: 10, weight: .bold)); Spacer(); Text(pct(x.p_title)).font(.system(size: 10, design: .monospaced)) }
            }
        }
    }

    func medium(_ f: Forecast) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            header(f)
            ForEach(f.forecast.drivers.prefix(5)) { d in OddsRow(colour: d.colour, label: d.code, points: d.points, p: d.p_title) }
        }
    }

    func large(_ f: Forecast) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            header(f)
            Text("DRIVERS").font(.system(size: 9, weight: .semibold)).foregroundStyle(.secondary)
            ForEach(f.forecast.drivers.prefix(8)) { d in OddsRow(colour: d.colour, label: d.code, points: d.points, p: d.p_title) }
            Text("CONSTRUCTORS").font(.system(size: 9, weight: .semibold)).foregroundStyle(.secondary).padding(.top, 4)
            ForEach(f.forecast.teams.prefix(4)) { t in
                OddsRow(colour: t.colour, label: t.team.replacingOccurrences(of: " F1 Team", with: ""), points: t.points, p: t.p_title)
            }
            Spacer(minLength: 0)
            Text("\(f.forecast.remaining.count) races left · 20,000 simulated seasons")
                .font(.system(size: 9)).foregroundStyle(.secondary)
        }
    }
}

@main
struct PitwallWidgets: WidgetBundle {
    var body: some Widget { TitleOddsWidget() }
}

struct TitleOddsWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "PitwallTitleOdds", provider: Provider()) { entry in
            TitleOddsView(entry: entry)
        }
        .configurationDisplayName("F1 2026 Title Odds")
        .description("Championship odds from Pitwall's season simulation, updated after every race.")
        .supportedFamilies([.systemSmall, .systemMedium, .systemLarge])
    }
}
