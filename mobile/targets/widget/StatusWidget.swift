//
//  StatusWidget.swift
//  Home Screen widget: is the PC awake, is it locked, and a button to wake it.
//
//  Three things can go wrong independently, and the widget says which:
//
//    * no App Group        -> "Open PC Unlock" (the extension sees no state)
//    * no shared keychain  -> cached status only, with an age
//    * PC asleep/offline   -> "Asleep", from a live attempt that timed out
//
//  Distinguishing them matters while the entitlements are unproven on a
//  sideloaded build: "cached · 6m ago" and "Asleep" mean very different things.
//

import SwiftUI
import WidgetKit

struct PCEntry: TimelineEntry {
  enum Source {
    case live
    case cached(Date?)
    case unpaired
  }

  let date: Date
  let pc: SharedState.PC?
  let reachable: Bool
  let locked: Bool?
  let source: Source
  /// Why the live attempt failed, when it did. Shown small; it is diagnostic.
  let note: String?

  static func unpaired(at date: Date = Date()) -> PCEntry {
    PCEntry(date: date, pc: nil, reachable: false, locked: nil, source: .unpaired, note: nil)
  }
}

struct PCTimelineProvider: TimelineProvider {
  func placeholder(in context: Context) -> PCEntry {
    PCEntry(
      date: Date(),
      pc: nil,
      reachable: true,
      locked: true,
      source: .live,
      note: nil
    )
  }

  func getSnapshot(in context: Context, completion: @escaping (PCEntry) -> Void) {
    // The gallery preview must not hit the network.
    if context.isPreview {
      completion(placeholder(in: context))
      return
    }
    Task { completion(await makeEntry()) }
  }

  func getTimeline(in context: Context, completion: @escaping (Timeline<PCEntry>) -> Void) {
    Task {
      let current = await makeEntry()
      // WidgetKit budgets refreshes; quarter-hourly is as often as it will
      // reliably honour for a widget that also refreshes on app activity.
      let next = Calendar.current.date(byAdding: .minute, value: 15, to: current.date)
        ?? current.date
      completion(Timeline(entries: [current], policy: .after(next)))
    }
  }

  private func makeEntry() async -> PCEntry {
    guard let pc = SharedState.primaryPC() else { return .unpaired() }

    let cached = pc.status
    let cachedAt = cached.map { Date(timeIntervalSince1970: $0.checkedAt) }

    do {
      let status = try await StatusClient.fetch(pc: pc)
      return PCEntry(
        date: Date(),
        pc: pc,
        reachable: true,
        locked: status.locked,
        source: .live,
        note: nil
      )
    } catch {
      // A signing or entitlement failure is not the same as an offline PC, so
      // fall back to what the app last saw and label it as cached.
      return PCEntry(
        date: Date(),
        pc: pc,
        reachable: cached?.reachable ?? false,
        locked: cached?.locked,
        source: .cached(cachedAt),
        note: error.localizedDescription
      )
    }
  }
}

// MARK: - Presentation

private func statusSymbol(reachable: Bool, locked: Bool?) -> String {
  guard reachable else { return "moon.zzz.fill" }
  guard let locked else { return "desktopcomputer" }
  return locked ? "lock.fill" : "lock.open.fill"
}

private func statusColor(reachable: Bool, locked: Bool?) -> Color {
  guard reachable else { return .secondary }
  guard let locked else { return .green }
  return locked ? .orange : .green
}

private func headline(_ entry: PCEntry) -> String {
  guard entry.pc != nil else { return "Not paired" }
  guard entry.reachable else { return "Asleep" }
  guard let locked = entry.locked else { return "Nobody logged in" }
  return locked ? "Locked" : "Unlocked"
}

private func footnote(_ entry: PCEntry) -> String? {
  switch entry.source {
  case .live:
    return nil
  case .unpaired:
    return "Open PC Unlock"
  case .cached(let at):
    guard let at else { return "cached" }
    let formatter = RelativeDateTimeFormatter()
    formatter.unitsStyle = .abbreviated
    return "cached · " + formatter.localizedString(for: at, relativeTo: Date())
  }
}

struct StatusWidgetView: View {
  @Environment(\.widgetFamily) private var family
  let entry: PCEntry

  var body: some View {
    switch family {
    case .accessoryCircular:
      Image(systemName: statusSymbol(reachable: entry.reachable, locked: entry.locked))
        .font(.title2)
        .widgetAccentable()
    case .accessoryRectangular:
      VStack(alignment: .leading, spacing: 2) {
        Text(entry.pc?.name ?? "PC Unlock").font(.headline).lineLimit(1)
        Label(headline(entry), systemImage: statusSymbol(reachable: entry.reachable, locked: entry.locked))
          .font(.caption)
          .lineLimit(1)
      }
    default:
      systemView
    }
  }

  private var systemView: some View {
    VStack(alignment: .leading, spacing: 6) {
      HStack(spacing: 8) {
        Image(systemName: statusSymbol(reachable: entry.reachable, locked: entry.locked))
          .font(.title3)
          .foregroundStyle(statusColor(reachable: entry.reachable, locked: entry.locked))
        Text(entry.pc?.name ?? "PC Unlock")
          .font(.headline)
          .lineLimit(1)
      }

      Text(headline(entry))
        .font(.subheadline)
        .foregroundStyle(.secondary)

      if let line = footnote(entry) {
        Text(line)
          .font(.caption2)
          .foregroundStyle(.tertiary)
          .lineLimit(1)
      }

      // Why the live check failed, when it did. Only where there is room --
      // this exists so an entitlement problem can be told apart from a
      // sleeping PC without attaching a debugger.
      if family == .systemMedium, let note = entry.note {
        Text(note)
          .font(.caption2)
          .foregroundStyle(.tertiary)
          .lineLimit(2)
      }

      Spacer(minLength: 0)

      if let pc = entry.pc, !pc.macs.isEmpty {
        Button(intent: WakePCIntent(pcId: pc.id)) {
          Label("Wake", systemImage: "power")
            .font(.footnote.weight(.semibold))
            .frame(maxWidth: .infinity)
        }
        .buttonStyle(.borderedProminent)
        .disabled(entry.reachable)
      }
    }
  }
}

struct StatusWidget: Widget {
  static let kind = "com.vercixx.wolunlock.status"

  var body: some WidgetConfiguration {
    StaticConfiguration(kind: Self.kind, provider: PCTimelineProvider()) { entry in
      StatusWidgetView(entry: entry)
        .containerBackground(.fill.tertiary, for: .widget)
    }
    .configurationDisplayName("PC status")
    .description("Whether your PC is awake and locked, with a button to wake it.")
    .supportedFamilies([
      .systemSmall,
      .systemMedium,
      .accessoryCircular,
      .accessoryRectangular,
    ])
  }
}
